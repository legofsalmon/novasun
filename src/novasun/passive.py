"""Zero-transmission observation of NovaStar traffic.

For a monitoring tool that must not perturb a live system, this listens and
never sends. One :class:`PassiveListener` covers two channels, each on its own
receive-only socket, and records every datagram that reaches either.

**UDP 3800: register-bus discovery.** The listener binds UDP 3800, joins the
discovery multicast group, and records the ``rqProMI:`` probes that NovaLCT and
VMP emit and any ``rpProMI:`` replies that reach this host. What a silent
listener can see here is established, and it is less than was hoped. The probe
is broadcast, so it is always observable. The *reply* is **unicast** back to the
requester (OBSERVED by packet capture, addressed to the requester's own MAC and
IP at both layer 2 and layer 3), so a switch never forwards it here. A listener
on a third host therefore sees probes and no replies. That tells you a control
application is running and how often it scans. It does not give an inventory.
"Probes seen but no replies" is the *expected* outcome on a third host, not a
sign of a problem.

**UDP 54622/54623/54624/54700: COEX announcements.** OBSERVED on one MX30 at
firmware V1.5.1 (its ``hwVersion`` string), 2026-09-26. The unit announces itself
unsolicited every 3.0 s as a subnet-directed broadcast from UDP source port
54650. Each announcement sends the same 96-byte bare-JSON payload to each of the
four ports, within about a millisecond. The payload has no header, no terminator
and no checksum::

    {"data":[{"apiPort":"8001","mac":"<mac>","authType":0,"workMode":0,"https":"9001"}]}

That is a passive inventory the 3800 path cannot give. Every 3 s, with nothing
sent, a listener learns each unit's IP, MAC, API port and HTTPS port. The IP
comes from the IP header; the payload does not carry it. It is not identity:
there is no model, name, serial or version field (OBSERVED absence). Several
things are UNKNOWN:

- what ``authType`` and ``workMode`` mean (only 0 has been seen);
- whether ``data`` ever holds more than one entry;
- whether an MX40 Pro, or any other COEX model or firmware, announces;
- which of the four ports VMP binds.

So the decoder keeps both integers raw, tolerates extra entries and unknown
keys, and records every datagram it cannot decode rather than raising. It keeps
only the *names* of unknown keys, never their values.

**What "transmits nothing" covers.** No socket here has a send call and none is
connected. The test suite asserts both structurally and behaviourally. Two
kernel-level effects remain. Both are REASONED from documented socket
behaviour; this project has not observed either on the wire:

- **Joining the 3800 multicast group makes the kernel send IGMP membership
  reports**, and a leave when the socket closes. They go to the group and to
  multicast routers, not to any controller, but they are packets.
  ``join_multicast=False`` (``listen --no-multicast``) avoids them. The probe is
  also sent to the subnet broadcast (DERIVED), so probes stay visible without
  the join. The announcement sockets join nothing.
- **Sharing a port with another application on the same host.** The
  announcement sockets set ``SO_REUSEADDR`` and ``SO_REUSEPORT`` so they can
  bind alongside VMP or crewbox. A broadcast is delivered to every socket
  sharing the port, so sharing takes nothing from the other application.
  However, an application that binds *later without* ``SO_REUSEPORT`` fails to
  bind while this listener holds the port. That is why only 54622 is bound by
  default: the payload is identical on all four ports (OBSERVED), and every
  extra port is one more chance of a collision. On a VMP host, ``lsof -iUDP``
  shows which port VMP holds, with no traffic. The 3800 socket deliberately does
  not set ``SO_REUSEPORT``. The replies there are unicast, and a unicast datagram
  to a shared port reaches only one of the sharers, which could be this listener
  instead of the application that asked. On Linux the ``SO_REUSEADDR`` it has
  always set permits sharing on its own, with the same caveat.

Receiving a broadcast needs the wildcard bind address (the default). A socket
bound to one interface's unicast address does not receive subnet broadcasts on
Linux or macOS (REASONED, kernel UDP demultiplexing). ``SO_BROADCAST`` is not
set: it only permits *sending* to a broadcast address (OFFICIAL, socket(7)),
which this module never does.

See ``docs/read-only-monitoring.md``.
"""

from __future__ import annotations

import json
import re
import select
import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from .discovery import MULTICAST_GROUP, PROBE, REPLY_PREFIX, UDP_PORT

CHANNEL_DISCOVERY = "discovery"
CHANNEL_ANNOUNCEMENT = "announcement"

#: Destination ports of the COEX self-announcement. OBSERVED on one MX30,
#: firmware V1.5.1, 2026-09-26: 117 bursts, each sending the same payload to all
#: four ports in this order within 0.970 ms. Why there are four is UNKNOWN.
ANNOUNCEMENT_PORTS: tuple[int, ...] = (54622, 54623, 54624, 54700)

#: What a listener binds unless told otherwise. One port is enough, because the
#: payload is identical on all four (OBSERVED), and each extra bound port is
#: another chance of colliding with a control application on the same host
#: (REASONED; see the module docstring).
DEFAULT_ANNOUNCEMENT_PORTS: tuple[int, ...] = (54622,)

#: Source port of every announcement seen (OBSERVED, same unit and session). It
#: is recorded and not filtered on, because another model or firmware may
#: differ.
ANNOUNCEMENT_SOURCE_PORT = 54650

#: Announcement cadence. OBSERVED: mean 3.0024 s, standard deviation 6.3 ms,
#: over 117 bursts with no gaps.
ANNOUNCEMENT_INTERVAL = 3.0

#: Datagrams from one address closer together than this count as one burst.
#: REASONED: a burst spanned at most 0.970 ms, and bursts were 3 s apart.
BURST_WINDOW = 0.5

#: The announcement's keys and the JSON type of each value. OBSERVED, identical
#: in all 468 datagrams. The ports are strings and the two modes are integers.
ANNOUNCEMENT_KEYS: dict[str, type] = {
    "apiPort": str,
    "mac": str,
    "authType": int,
    "workMode": int,
    "https": str,
}

#: Largest datagram kept whole. An announcement is 96 B (OBSERVED). The large
#: buffer only ensures that nothing unexpected is truncated in the record.
RECEIVE_SIZE = 65535

#: A payload containing any of these byte strings (case-insensitive) is withheld
#: from the log and from printed descriptions. Its timestamp, source and size
#: are still recorded. Nothing observed on these ports carries one. The guard
#: exists because the same firmware serves ``randomPassword`` to a bare GET of
#: ``/api/v1/device/hw`` (OBSERVED), and novasun never records such a field
#: wherever it turns up.
_WITHHELD_MARKERS = (b"password", b"passwd", b"secret", b"token")


def _withheld(payload: bytes) -> bool:
    lowered = payload.lower()
    return any(marker in lowered for marker in _WITHHELD_MARKERS)


def _payload_preview(payload: bytes, limit: int = 32) -> str:
    if _withheld(payload):
        return f"(payload withheld: {len(payload)}B containing a password-like key)"
    return payload[:limit].hex()


# --- COEX announcement decoding ----------------------------------------------

_MAC = re.compile(r"[0-9A-Fa-f]{2}([:-])[0-9A-Fa-f]{2}(?:\1[0-9A-Fa-f]{2}){4}")
_DIGITS = re.compile(r"-?[0-9]{1,9}")


def _json_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _key_name(key: str) -> str:
    """A key name that is safe to print: printable, and bounded in length."""
    name = key if key.isprintable() else repr(key)
    return name if len(name) <= 40 else name[:37] + "..."


def _as_integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and _DIGITS.fullmatch(value.strip()):
        return int(value.strip())
    return None


def _as_port(value: object) -> int | None:
    number = _as_integer(value)
    return number if number is not None and 0 < number < 65536 else None


def _as_mac(value: object) -> str | None:
    if isinstance(value, str) and _MAC.fullmatch(value.strip()):
        return value.strip().lower().replace("-", ":")
    return None


def _show(value: object) -> str:
    return "?" if value is None else str(value)


@dataclass(frozen=True)
class Announcement:
    """One entry of a COEX announcement's ``data`` array.

    A field is ``None`` when it is absent or unusable. The decoding notes say
    which. ``unknown_keys`` holds the names of any other keys, never their
    values.
    """

    mac: str | None
    api_port: int | None
    https_port: int | None
    auth_type: int | None
    work_mode: int | None
    unknown_keys: tuple[str, ...] = ()

    def describe(self) -> str:
        return (
            f"mac {_show(self.mac)}  api {_show(self.api_port)}  "
            f"https {_show(self.https_port)}  authType {_show(self.auth_type)}  "
            f"workMode {_show(self.work_mode)}"
        )


@dataclass(frozen=True)
class AnnouncementPayload:
    """The result of decoding one announcement datagram.

    ``entries`` is empty exactly when ``error`` says why nothing was usable.
    ``notes`` lists tolerated oddities, such as a value of an unexpected type or
    a second entry. ``unknown_keys`` names top-level keys other than ``data``.
    None of these carry values from the payload.
    """

    entries: tuple[Announcement, ...] = ()
    error: str = ""
    notes: tuple[str, ...] = ()
    unknown_keys: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return bool(self.entries)


def _decode_entry(item: dict, label: str, notes: list[str]) -> Announcement:
    for key, expected in ANNOUNCEMENT_KEYS.items():
        if key not in item:
            notes.append(f"{label}.{key} missing")
            continue
        value = item[key]
        matches = isinstance(value, expected) and not isinstance(value, bool)
        if not matches:
            notes.append(
                f"{label}.{key} is {_json_type(value)} "
                f"(observed as {_json_type(expected())})"
            )
    announcement = Announcement(
        mac=_as_mac(item.get("mac")),
        api_port=_as_port(item.get("apiPort")),
        https_port=_as_port(item.get("https")),
        auth_type=_as_integer(item.get("authType")),
        work_mode=_as_integer(item.get("workMode")),
        unknown_keys=tuple(
            sorted(_key_name(key) for key in item if key not in ANNOUNCEMENT_KEYS)
        ),
    )
    for key, value in (
        ("mac", announcement.mac),
        ("apiPort", announcement.api_port),
        ("https", announcement.https_port),
        ("authType", announcement.auth_type),
        ("workMode", announcement.work_mode),
    ):
        if key in item and value is None:
            notes.append(f"{label}.{key} unusable")
    return announcement


def decode_announcement(payload: bytes) -> AnnouncementPayload:
    """Decode a COEX announcement datagram. Never raises.

    The accepted shape is the observed one: a JSON object whose ``data`` array
    holds objects carrying some of ``apiPort``, ``mac``, ``authType``,
    ``workMode`` and ``https``. The decoder tolerates trailing NULs or
    whitespace, unknown keys, value types other than those observed, and more
    than one entry, and notes each of them. Anything that is not that shape
    comes back with no entries and an ``error``. It is recorded, never raised.
    """
    notes: list[str] = []
    body = payload.rstrip(b"\x00 \t\r\n")
    if len(body) != len(payload):
        notes.append("trailing NUL or whitespace ignored")
    if not body:
        return AnnouncementPayload(error="empty datagram", notes=tuple(notes))
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return AnnouncementPayload(error="not UTF-8 text", notes=tuple(notes))
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        return AnnouncementPayload(
            error=f"not JSON: {exc.msg} at byte {exc.pos}", notes=tuple(notes)
        )
    except (ValueError, RecursionError) as exc:
        return AnnouncementPayload(
            error=f"not JSON: {type(exc).__name__}", notes=tuple(notes)
        )
    if not isinstance(document, dict):
        return AnnouncementPayload(
            error=f"top level is {_json_type(document)}, not an object",
            notes=tuple(notes),
        )
    unknown_top = tuple(sorted(_key_name(key) for key in document if key != "data"))
    if "data" not in document:
        return AnnouncementPayload(
            error="no data key", notes=tuple(notes), unknown_keys=unknown_top
        )
    data = document["data"]
    if not isinstance(data, list):
        return AnnouncementPayload(
            error=f"data is {_json_type(data)}, not an array",
            notes=tuple(notes),
            unknown_keys=unknown_top,
        )
    if not data:
        return AnnouncementPayload(
            error="data array is empty", notes=tuple(notes), unknown_keys=unknown_top
        )
    if len(data) > 1:
        notes.append(f"{len(data)} entries in data (one has been observed)")
    entries: list[Announcement] = []
    for index, item in enumerate(data):
        label = f"data[{index}]"
        if not isinstance(item, dict):
            notes.append(f"{label} is {_json_type(item)}, skipped")
            continue
        if not any(key in item for key in ANNOUNCEMENT_KEYS):
            notes.append(f"{label} has none of the announcement keys, skipped")
            continue
        entries.append(_decode_entry(item, label, notes))
    if not entries:
        return AnnouncementPayload(
            error="no usable entry in data", notes=tuple(notes), unknown_keys=unknown_top
        )
    return AnnouncementPayload(
        entries=tuple(entries), notes=tuple(notes), unknown_keys=unknown_top
    )


# --- Observations ------------------------------------------------------------


@dataclass
class Observation:
    """One datagram seen by the listener.

    ``channel`` records which socket it arrived on, and ``port`` that socket's
    local port. Classification goes by channel and not by payload alone, so a
    stray ``rqProMI:`` on an announcement port is recorded as undecodable
    rather than counted as a probe. ``port`` and ``source_port`` are 0 when not
    recorded.
    """

    timestamp: float
    source: str
    payload: bytes
    channel: str = CHANNEL_DISCOVERY
    port: int = 0
    source_port: int = 0

    @property
    def is_probe(self) -> bool:
        return self.channel == CHANNEL_DISCOVERY and self.payload.startswith(PROBE)

    @property
    def is_reply(self) -> bool:
        return self.channel == CHANNEL_DISCOVERY and self.payload.startswith(REPLY_PREFIX)

    def announcement(self) -> AnnouncementPayload | None:
        """The decoded announcement, or ``None`` off the announcement channel."""
        if self.channel != CHANNEL_ANNOUNCEMENT:
            return None
        return decode_announcement(self.payload)

    @property
    def kind(self) -> str:
        if self.channel == CHANNEL_ANNOUNCEMENT:
            decoded = decode_announcement(self.payload)
            return "announce" if decoded.ok else "malformed"
        if self.is_probe:
            return "probe"
        if self.is_reply:
            return "reply"
        return "other"

    def describe(self) -> str:
        """One printable line. Never raises, and never prints a withheld payload."""
        decoded = self.announcement()
        if decoded is not None:
            if decoded.ok:
                detail = "; ".join(entry.describe() for entry in decoded.entries)
            else:
                detail = f"undecodable ({decoded.error}) {_payload_preview(self.payload)}"
            kind = "announce" if decoded.ok else "malformed"
        else:
            kind = self.kind
            if _withheld(self.payload):
                detail = _payload_preview(self.payload)
            elif self.is_reply:
                detail = decode_reply(self.payload).describe()
            else:
                detail = ""
            detail = detail or self.payload[:32].hex()
        destination = f" to :{self.port}" if self.port else ""
        return (
            f"{self.timestamp:14.3f} {kind:<9} from {self.source:<15}{destination} "
            f"{len(self.payload):>4}B {detail}"
        )


@dataclass
class DiscoveryReply:
    """A decoded ``rpProMI:`` payload.

    The prefix is the only part whose meaning is established. Published
    implementations -- including the most complete one, ``sarakusha/novastar`` --
    check the prefix and use the datagram's *source address*, discarding
    everything after it. No document describes the remainder.

    So this decoder keeps the tail as bytes and offers conservative
    interpretations that a caller can accept or ignore. It does not invent field
    boundaries. Once a real reply has been captured, the layout can be filled in
    here and ``docs/read-only-monitoring.md`` updated.
    """

    raw: bytes
    tail: bytes

    @property
    def printable(self) -> str:
        """The tail as text, if it is plausibly text.

        Embedded NULs are treated as separators rather than as evidence of
        binary: a C-style ``name\\0serial\\0`` payload is text with structure,
        and is the most likely shape for this field if it carries anything.
        """
        try:
            text = self.tail.decode("ascii")
        except UnicodeDecodeError:
            return ""
        stripped = text.strip("\x00 \r\n\t")
        if not stripped:
            return ""
        return stripped if all(c.isprintable() or c == "\x00" for c in stripped) else ""

    @property
    def fields(self) -> list[str]:
        """NUL- or comma-separated tokens, if the tail looks delimited."""
        text = self.printable
        if not text:
            return []
        for separator in ("\x00", ",", ";", "|"):
            if separator in text:
                return [part for part in text.split(separator) if part]
        return [text]

    @property
    def looks_binary(self) -> bool:
        return bool(self.tail) and not self.printable

    def describe(self) -> str:
        if self.fields:
            return " | ".join(self.fields)
        if self.looks_binary:
            return f"binary tail {self.tail.hex()}"
        return "(no payload beyond the prefix)"


def decode_reply(payload: bytes) -> DiscoveryReply:
    tail = payload[len(REPLY_PREFIX) :] if payload.startswith(REPLY_PREFIX) else b""
    return DiscoveryReply(raw=payload, tail=tail)


Observer = Callable[[Observation], None]


# --- The listener ------------------------------------------------------------


def _open_receive_socket(address: str, port: int, share_port: bool) -> socket.socket:
    """A bound UDP socket that is only ever read from.

    ``share_port`` adds ``SO_REUSEPORT`` where the platform has it. The module
    docstring explains why only the broadcast-fed announcement sockets use it.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if share_port and hasattr(socket, "SO_REUSEPORT"):
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass  # present in the headers but refused by this kernel
        sock.bind((address, port))
        sock.setblocking(False)
    except OSError:
        sock.close()
        raise
    return sock


class PassiveListener:
    """Receive-only sockets on the discovery port and the announcement ports.

    ``port`` is the discovery port (UDP 3800), or ``None`` to leave it unbound.
    ``announcement_ports`` lists the COEX announcement ports to bind. It is
    empty by default here, so that constructing a listener binds nothing
    beyond what was asked for. :func:`listen` and the ``listen`` command
    default to both. Port 0 binds an ephemeral port, which is how the tests
    run without touching a real port.

    A port that cannot be bound is recorded in :attr:`bind_failures`, printed
    in the summary and written to the session record. It is raised only when
    nothing at all could be bound, so a busy 54622 does not stop a 3800 listen.
    """

    def __init__(
        self,
        bind_address: str = "0.0.0.0",
        port: int | None = UDP_PORT,
        join_multicast: bool = True,
        log_path: Path | None = None,
        *,
        announcement_ports: Sequence[int] = (),
    ) -> None:
        self._sockets: list[tuple[str, socket.socket, tuple[str, int]]] = []
        self.bind_failures: dict[str, str] = {}
        #: The multicast group joined on the discovery socket, "off", or
        #: "failed". Joining is the one thing here that makes the kernel emit
        #: packets (IGMP reports), so the session record states it.
        self.multicast = "off"
        first_error: OSError | None = None

        requested: list[tuple[str, int]] = []
        if port is not None:
            requested.append((CHANNEL_DISCOVERY, port))
        requested.extend((CHANNEL_ANNOUNCEMENT, p) for p in announcement_ports)
        for channel, wanted in requested:
            try:
                sock = _open_receive_socket(
                    bind_address, wanted, share_port=channel == CHANNEL_ANNOUNCEMENT
                )
            except OSError as exc:
                self.bind_failures[f"{bind_address}:{wanted}/{channel}"] = str(exc)
                first_error = first_error or exc
                continue
            self._sockets.append((channel, sock, sock.getsockname()))
            if channel == CHANNEL_DISCOVERY and join_multicast:
                try:
                    sock.setsockopt(
                        socket.IPPROTO_IP,
                        socket.IP_ADD_MEMBERSHIP,
                        struct.pack(
                            "4sl", socket.inet_aton(MULTICAST_GROUP), socket.INADDR_ANY
                        ),
                    )
                    self.multicast = MULTICAST_GROUP
                except OSError:
                    self.multicast = "failed"  # broadcast traffic is still visible
        if not self._sockets:
            if first_error is not None:
                raise first_error
            raise ValueError("nothing to listen on: no discovery port and no announcement ports")

        self.observations: list[Observation] = []
        self.observers: list[Observer] = []
        self.log_path = log_path
        self._running = False
        self._lock = threading.Condition()

    @property
    def address(self) -> tuple[str, int]:
        """The first bound socket's address: the discovery port, if bound."""
        return self._sockets[0][2]

    @property
    def addresses(self) -> list[tuple[str, tuple[str, int]]]:
        """``(channel, (host, port))`` for every bound socket."""
        return [(channel, bound) for channel, _sock, bound in self._sockets]

    @property
    def coverage(self) -> dict[str, tuple[int, ...]]:
        """The local ports actually bound, per channel."""
        ports: dict[str, list[int]] = {}
        for channel, _sock, (_host, port) in self._sockets:
            ports.setdefault(channel, []).append(port)
        return {channel: tuple(values) for channel, values in ports.items()}

    def listen(self, duration: float | None = None) -> list[Observation]:
        """Receive until ``duration`` elapses, or until :meth:`stop`."""
        self._running = True
        started = time.time()
        binds = ",".join(f"{host}:{port}/{channel}" for channel, (host, port) in self.addresses)
        self._log_line(
            f"# session start={started:.3f} bind={binds} "
            f"channels={','.join(self.coverage)} multicast={self.multicast} "
            f"duration={'until-stopped' if duration is None else f'{duration:g}s'}"
        )
        for where, error in self.bind_failures.items():
            self._log_line(f"# bind failed {where}: {error}")
        deadline = None if duration is None else time.monotonic() + duration
        sockets = {sock: (channel, bound[1]) for channel, sock, bound in self._sockets}
        while self._running:
            timeout = 0.5
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                timeout = min(remaining, 0.5)
            try:
                ready, _writable, _errored = select.select(list(sockets), [], [], timeout)
            except (OSError, ValueError):
                break  # a socket was closed under us: stop() was called
            failed = False
            for sock in ready:
                channel, local_port = sockets[sock]
                try:
                    payload, (source, source_port) = sock.recvfrom(RECEIVE_SIZE)
                except (BlockingIOError, InterruptedError):
                    continue
                except OSError:
                    failed = True
                    break
                self._record(
                    Observation(
                        time.time(), source, payload, channel, local_port, source_port
                    )
                )
            if failed:
                break
        # A run that hears nothing is a result -- thirty minutes of silence on a
        # network with a controller on it says something about passive
        # discovery -- so the session leaves evidence of itself even when no
        # datagram ever did.
        with self._lock:
            counts = {
                channel: sum(1 for o in self.observations if o.channel == channel)
                for channel in self.coverage
            }
            total = len(self.observations)
        self._log_line(
            f"# session end={time.time():.3f} elapsed={time.time() - started:.1f}s "
            f"observations={total} "
            + " ".join(f"{channel}={count}" for channel, count in counts.items())
        )
        return self.observations

    def listen_in_thread(self, duration: float | None = None) -> threading.Thread:
        thread = threading.Thread(target=self.listen, args=(duration,), daemon=True)
        thread.start()
        return thread

    def inventory(self) -> "PassiveInventory":
        """What has been learned so far, with what was and was not listened to."""
        with self._lock:
            observations = list(self.observations)
        return build_inventory(
            observations, coverage=self.coverage, bind_failures=self.bind_failures
        )

    def _log_line(self, line: str) -> None:
        """Append one line to the log, if there is one.

        Lines starting with ``#`` are session records. Every other line is one
        datagram, tab-separated: timestamp, source address, payload hex, source
        port, local port. The first three columns are unchanged from the
        3800-only format. A payload containing a password-like key is written
        as ``withheld:<n>B`` in place of its hex.
        """
        if self.log_path is None:
            return
        with self._lock:  # a Condition's default lock is re-entrant
            with self.log_path.open("a") as handle:
                handle.write(line + "\n")

    def _record(self, observation: Observation) -> None:
        payload = (
            f"withheld:{len(observation.payload)}B"
            if _withheld(observation.payload)
            else observation.payload.hex()
        )
        with self._lock:
            self.observations.append(observation)
            self._log_line(
                f"{observation.timestamp}\t{observation.source}\t{payload}\t"
                f"{observation.source_port}\t{observation.port}"
            )
            self._lock.notify_all()
        for observe in self.observers:
            observe(observation)

    def wait_for(self, count: int, timeout: float = 2.0) -> bool:
        with self._lock:
            return self._lock.wait_for(lambda: len(self.observations) >= count, timeout)

    def stop(self) -> None:
        self._running = False
        for _channel, sock, _bound in self._sockets:
            try:
                sock.close()
            except OSError:
                pass

    def __enter__(self) -> "PassiveListener":
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()


# --- Inventory ---------------------------------------------------------------


@dataclass
class InventoryEntry:
    """A device inferred from overheard ``rpProMI:`` replies."""

    address: str
    first_seen: float
    last_seen: float
    replies: int = 0
    detail: str = ""


@dataclass
class AnnouncementEntry:
    """A unit heard announcing itself, keyed by the address it announced from.

    The address comes from the IP header. The MAC, ports and modes come from the
    latest datagram, and ``macs`` and ``variants`` keep every value seen, so a
    change or a duplicate address shows up rather than being overwritten.
    ``count`` is datagrams, and each burst of up to four ports is one of
    ``bursts``. ``ports`` holds the local ports the datagrams arrived on.
    """

    address: str
    first_seen: float
    last_seen: float
    mac: str | None = None
    api_port: int | None = None
    https_port: int | None = None
    auth_type: int | None = None
    work_mode: int | None = None
    count: int = 0
    bursts: int = 0
    ports: set[int] = field(default_factory=set)
    source_ports: set[int] = field(default_factory=set)
    macs: set[str] = field(default_factory=set)
    variants: set[tuple[Announcement, ...]] = field(default_factory=set)
    unknown_keys: set[str] = field(default_factory=set)
    notes: set[str] = field(default_factory=set)
    burst_starts: list[float] = field(default_factory=list, repr=False)

    @property
    def interval(self) -> float | None:
        """Median gap between bursts, or ``None`` with fewer than two."""
        if len(self.burst_starts) < 2:
            return None
        starts = sorted(self.burst_starts)
        gaps = sorted(b - a for a, b in zip(starts, starts[1:]))
        middle = len(gaps) // 2
        return gaps[middle] if len(gaps) % 2 else (gaps[middle - 1] + gaps[middle]) / 2

    def add(self, observation: Observation, decoded: AnnouncementPayload) -> None:
        first = decoded.entries[0]
        self.mac = first.mac
        self.api_port = first.api_port
        self.https_port = first.https_port
        self.auth_type = first.auth_type
        self.work_mode = first.work_mode
        self.count += 1
        self.first_seen = min(self.first_seen, observation.timestamp)
        self.last_seen = max(self.last_seen, observation.timestamp)
        if not self.burst_starts or observation.timestamp - self.burst_starts[-1] > BURST_WINDOW:
            self.burst_starts.append(observation.timestamp)
            self.bursts += 1
        if observation.port:
            self.ports.add(observation.port)
        if observation.source_port:
            self.source_ports.add(observation.source_port)
        self.macs.update(entry.mac for entry in decoded.entries if entry.mac)
        self.variants.add(decoded.entries)
        for entry in decoded.entries:
            self.unknown_keys.update(entry.unknown_keys)
        self.unknown_keys.update(decoded.unknown_keys)
        self.notes.update(decoded.notes)

    def describe(self) -> str:
        interval = self.interval
        cadence = f", every {interval:.1f}s" if interval is not None else ""
        return (
            f"{self.address:<15} mac {_show(self.mac)}  api {_show(self.api_port)}  "
            f"https {_show(self.https_port)}  authType {_show(self.auth_type)}  "
            f"workMode {_show(self.work_mode)}  "
            f"{self.count} datagram(s) in {self.bursts} burst(s){cadence}"
        )


@dataclass
class MalformedDatagram:
    """A datagram on an announcement port that could not be decoded.

    Only its metadata and the reason are kept here. The payload itself is in
    the observation and, unless withheld, in the log.
    """

    timestamp: float
    source: str
    port: int
    size: int
    reason: str


@dataclass
class PassiveInventory:
    """What was learned without transmitting anything.

    ``coverage`` maps each channel listened on to its bound local ports. It is
    ``None`` when the inventory was built from observations alone, in which
    case silence on a channel cannot be told apart from not listening, and the
    summary does not claim either.
    """

    devices: dict[str, InventoryEntry] = field(default_factory=dict)
    probes: list[Observation] = field(default_factory=list)
    announcers: dict[str, AnnouncementEntry] = field(default_factory=dict)
    malformed: list[MalformedDatagram] = field(default_factory=list)
    coverage: dict[str, tuple[int, ...]] | None = None
    bind_failures: dict[str, str] = field(default_factory=dict)

    @property
    def probe_interval(self) -> float | None:
        """Median gap between observed probes, or ``None`` with too few.

        This is the number that decides whether passive discovery is viable: it
        is how long a listener waits before the inventory appears.
        """
        if len(self.probes) < 2:
            return None
        times = sorted(observation.timestamp for observation in self.probes)
        gaps = sorted(b - a for a, b in zip(times, times[1:]))
        middle = len(gaps) // 2
        return gaps[middle] if len(gaps) % 2 else (gaps[middle - 1] + gaps[middle]) / 2

    def _listened(self, channel: str) -> bool | None:
        return None if self.coverage is None else channel in self.coverage

    def _discovery_lines(self) -> list[str]:
        if self._listened(CHANNEL_DISCOVERY) is False:
            return ["UDP 3800 discovery: not listened"]
        if not self.devices and not self.probes:
            return ["UDP 3800 discovery: nothing heard"]
        lines = [
            f"UDP 3800 discovery: {len(self.probes)} probe(s), "
            f"{len(self.devices)} device(s) replying"
        ]
        interval = self.probe_interval
        if interval is not None:
            lines.append(f"  median probe interval {interval:.1f}s")
        elif self.probes:
            lines.append("  only one probe seen -- interval unknown")
        for entry in sorted(self.devices.values(), key=lambda e: e.address):
            lines.append(f"  {entry.address:<15} {entry.replies:>3} replies  {entry.detail}")
        if not self.devices and self.probes:
            lines.append(
                "  probes seen but no replies -- replies are unicast to the "
                "requester, so passive discovery on UDP 3800 needs a port mirror"
            )
        return lines

    def _announcement_lines(self) -> list[str]:
        listened = self._listened(CHANNEL_ANNOUNCEMENT)
        if listened is False:
            return ["COEX announcements: not listened"]
        if listened is None and not self.announcers and not self.malformed:
            return []
        if self.coverage is not None:
            ports = sorted(self.coverage[CHANNEL_ANNOUNCEMENT])
        else:
            ports = sorted(
                {port for entry in self.announcers.values() for port in entry.ports}
                | {item.port for item in self.malformed if item.port}
            )
        where = f" (UDP {', '.join(str(port) for port in ports)})" if ports else ""
        if not self.announcers:
            lines = [f"COEX announcements{where}: none heard"]
            if not self.malformed:
                lines.append(
                    "  an MX30 at firmware V1.5.1 announces every 3s; whether other "
                    "models do is UNKNOWN"
                )
        else:
            lines = [f"COEX announcements{where}: {len(self.announcers)} unit(s)"]
        by_mac: dict[str, set[str]] = {}
        for entry in sorted(self.announcers.values(), key=lambda e: e.address):
            lines.append(f"  {entry.describe()}")
            if len(entry.macs) > 1:
                lines.append(
                    f"    several MACs from this address: {', '.join(sorted(entry.macs))}"
                )
            if len(entry.variants) > 1:
                lines.append(f"    payload changed: {len(entry.variants)} different payloads")
            if entry.unknown_keys:
                lines.append(
                    f"    unknown keys (names only): {', '.join(sorted(entry.unknown_keys))}"
                )
            notes = sorted(entry.notes)
            for note in notes[:5]:
                lines.append(f"    note: {note}")
            if len(notes) > 5:
                lines.append(f"    ... and {len(notes) - 5} more note(s)")
            for mac in entry.macs:
                by_mac.setdefault(mac, set()).add(entry.address)
        for mac, addresses in sorted(by_mac.items()):
            if len(addresses) > 1:
                lines.append(
                    f"  mac {mac} announced from several addresses: "
                    f"{', '.join(sorted(addresses))}"
                )
        if self.malformed:
            lines.append(
                f"  {len(self.malformed)} undecodable datagram(s), recorded, not decoded:"
            )
            for item in self.malformed[:5]:
                lines.append(
                    f"    {item.source}{f' to :{item.port}' if item.port else ''}  "
                    f"{item.size}B  {item.reason}"
                )
            if len(self.malformed) > 5:
                lines.append(f"    ... and {len(self.malformed) - 5} more")
        if self.announcers:
            lines.append(
                "  announcements carry no model, name or serial; authType and "
                "workMode are shown raw, their meanings UNKNOWN"
            )
        return lines

    def summary(self) -> str:
        seen = set(self.devices) | set(self.announcers)
        lines = [
            f"{len(seen)} device(s) seen: {len(self.announcers)} announcing, "
            f"{len(self.devices)} replying to discovery; "
            f"{len(self.probes)} probe(s) overheard"
        ]
        lines.extend(self._discovery_lines())
        lines.extend(self._announcement_lines())
        for where, error in sorted(self.bind_failures.items()):
            lines.append(f"could not bind {where}: {error}")
        return "\n".join(lines)


def build_inventory(
    observations: list[Observation],
    coverage: dict[str, tuple[int, ...]] | None = None,
    bind_failures: dict[str, str] | None = None,
) -> PassiveInventory:
    """Summarise observations. Never raises on payload content.

    Pass ``coverage`` (a listener's :attr:`PassiveListener.coverage`) so that
    the summary can tell silence on a channel apart from not listening to it.
    """
    inventory = PassiveInventory(
        coverage=None if coverage is None else dict(coverage),
        bind_failures=dict(bind_failures or {}),
    )
    for observation in sorted(observations, key=lambda o: o.timestamp):
        if observation.channel == CHANNEL_ANNOUNCEMENT:
            decoded = decode_announcement(observation.payload)
            if not decoded.ok:
                inventory.malformed.append(
                    MalformedDatagram(
                        timestamp=observation.timestamp,
                        source=observation.source,
                        port=observation.port,
                        size=len(observation.payload),
                        reason=decoded.error,
                    )
                )
                continue
            announcer = inventory.announcers.get(observation.source)
            if announcer is None:
                announcer = AnnouncementEntry(
                    address=observation.source,
                    first_seen=observation.timestamp,
                    last_seen=observation.timestamp,
                )
                inventory.announcers[observation.source] = announcer
            announcer.add(observation, decoded)
            continue
        if observation.is_probe:
            inventory.probes.append(observation)
            continue
        if not observation.is_reply:
            continue
        entry = inventory.devices.get(observation.source)
        if entry is None:
            entry = InventoryEntry(
                address=observation.source,
                first_seen=observation.timestamp,
                last_seen=observation.timestamp,
            )
            inventory.devices[observation.source] = entry
        entry.last_seen = observation.timestamp
        entry.replies += 1
        entry.detail = decode_reply(observation.payload).describe()
    return inventory


def listen(
    duration: float = 60.0,
    log_path: Path | None = None,
    *,
    discovery: bool = True,
    announcements: bool = True,
    announcement_ports: Sequence[int] = DEFAULT_ANNOUNCEMENT_PORTS,
    join_multicast: bool = True,
    bind_address: str = "0.0.0.0",
) -> PassiveInventory:
    """Convenience: observe for ``duration`` seconds and summarise.

    Covers UDP 3800 and the default announcement port unless told otherwise.
    ``join_multicast=False`` removes the one kernel-level transmission (IGMP).
    """
    with PassiveListener(
        bind_address,
        UDP_PORT if discovery else None,
        join_multicast=join_multicast and discovery,
        log_path=log_path,
        announcement_ports=announcement_ports if announcements else (),
    ) as listener:
        listener.listen(duration)
        return listener.inventory()


def listen_announcements(
    duration: float = 60.0,
    log_path: Path | None = None,
    *,
    ports: Sequence[int] = DEFAULT_ANNOUNCEMENT_PORTS,
    bind_address: str = "0.0.0.0",
) -> PassiveInventory:
    """Observe COEX announcements only. It joins no group and sends nothing."""
    return listen(
        duration,
        log_path,
        discovery=False,
        announcement_ports=ports,
        join_multicast=False,
        bind_address=bind_address,
    )
