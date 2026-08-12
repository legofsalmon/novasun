"""Zero-transmission observation of NovaStar traffic.

For a monitoring tool that must not perturb a live system, this listens and
never sends. It binds UDP 3800, joins the discovery multicast group, and records
what crosses it -- both the ``rqProMI:`` probes that NovaLCT and VMP emit and any
``rpProMI:`` replies that reach this host.

**What a silent listener can actually see is not fully known.** The probe is
broadcast, so it is always observable. Whether the *reply* is broadcast or
unicast back to the requester decides whether a third-party listener sees the
inventory at all, and that has not been established -- see
``docs/read-only-monitoring.md``. This module is written so that one session
with hardware settles it: run :func:`listen`, have someone open NovaLCT, and
read the log.

Nothing in this module transmits. :class:`PassiveListener` opens its socket
receive-only and there is no send path in the class at all; the test suite
asserts that by monkeypatching ``sendto`` to fail.
"""

from __future__ import annotations

import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .discovery import MULTICAST_GROUP, PROBE, REPLY_PREFIX, UDP_PORT


@dataclass
class Observation:
    """One datagram seen on the discovery port."""

    timestamp: float
    source: str
    payload: bytes

    @property
    def is_probe(self) -> bool:
        return self.payload.startswith(PROBE)

    @property
    def is_reply(self) -> bool:
        return self.payload.startswith(REPLY_PREFIX)

    @property
    def kind(self) -> str:
        if self.is_probe:
            return "probe"
        if self.is_reply:
            return "reply"
        return "other"

    def describe(self) -> str:
        detail = decode_reply(self.payload).describe() if self.is_reply else ""
        return (
            f"{self.timestamp:14.3f} {self.kind:<6} from {self.source:<15} "
            f"{len(self.payload):>4}B {detail or self.payload[:32].hex()}"
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


class PassiveListener:
    """Receive-only socket on the discovery port.

    Set ``SO_REUSEADDR`` so this can run alongside NovaLCT on the same machine
    without either failing to bind.
    """

    def __init__(
        self,
        bind_address: str = "0.0.0.0",
        port: int = UDP_PORT,
        join_multicast: bool = True,
        log_path: Path | None = None,
    ) -> None:
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((bind_address, port))
        if join_multicast:
            try:
                self._socket.setsockopt(
                    socket.IPPROTO_IP,
                    socket.IP_ADD_MEMBERSHIP,
                    struct.pack("4sl", socket.inet_aton(MULTICAST_GROUP), socket.INADDR_ANY),
                )
            except OSError:
                pass  # multicast unavailable; broadcast traffic is still visible
        self.observations: list[Observation] = []
        self.observers: list[Observer] = []
        self.log_path = log_path
        self._running = False
        self._lock = threading.Condition()

    @property
    def address(self) -> tuple[str, int]:
        return self._socket.getsockname()

    def listen(self, duration: float | None = None) -> list[Observation]:
        """Receive until ``duration`` elapses, or until :meth:`stop`."""
        self._running = True
        deadline = None if duration is None else time.monotonic() + duration
        while self._running:
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._socket.settimeout(min(remaining, 0.5))
            else:
                self._socket.settimeout(0.5)
            try:
                payload, (source, _port) = self._socket.recvfrom(4096)
            except (TimeoutError, socket.timeout):
                continue
            except OSError:
                break
            self._record(Observation(time.time(), source, payload))
        return self.observations

    def listen_in_thread(self, duration: float | None = None) -> threading.Thread:
        thread = threading.Thread(target=self.listen, args=(duration,), daemon=True)
        thread.start()
        return thread

    def _record(self, observation: Observation) -> None:
        with self._lock:
            self.observations.append(observation)
            if self.log_path is not None:
                with self.log_path.open("a") as handle:
                    handle.write(
                        f"{observation.timestamp}\t{observation.source}\t"
                        f"{observation.payload.hex()}\n"
                    )
            self._lock.notify_all()
        for observe in self.observers:
            observe(observation)

    def wait_for(self, count: int, timeout: float = 2.0) -> bool:
        with self._lock:
            return self._lock.wait_for(lambda: len(self.observations) >= count, timeout)

    def stop(self) -> None:
        self._running = False
        try:
            self._socket.close()
        except OSError:
            pass

    def __enter__(self) -> "PassiveListener":
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()


@dataclass
class InventoryEntry:
    """A device inferred from overheard traffic."""

    address: str
    first_seen: float
    last_seen: float
    replies: int = 0
    detail: str = ""


@dataclass
class PassiveInventory:
    """What was learned without transmitting anything."""

    devices: dict[str, InventoryEntry] = field(default_factory=dict)
    probes: list[Observation] = field(default_factory=list)

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

    def summary(self) -> str:
        lines = [
            f"{len(self.devices)} device(s) seen, {len(self.probes)} probe(s) overheard"
        ]
        interval = self.probe_interval
        if interval is not None:
            lines.append(f"median probe interval {interval:.1f}s")
        elif self.probes:
            lines.append("only one probe seen -- interval unknown")
        for entry in sorted(self.devices.values(), key=lambda e: e.address):
            lines.append(f"  {entry.address:<15} {entry.replies:>3} replies  {entry.detail}")
        if not self.devices and self.probes:
            lines.append(
                "  probes seen but no replies -- replies are probably unicast to the "
                "requester, so passive discovery needs a port mirror"
            )
        return "\n".join(lines)


def build_inventory(observations: list[Observation]) -> PassiveInventory:
    inventory = PassiveInventory()
    for observation in observations:
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


def listen(duration: float = 60.0, log_path: Path | None = None) -> PassiveInventory:
    """Convenience: observe for ``duration`` seconds and summarise."""
    with PassiveListener(log_path=log_path) as listener:
        observations = listener.listen(duration)
    return build_inventory(observations)
