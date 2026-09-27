"""Read-only monitoring, for tools that observe rather than control.

Two guarantees a monitoring pane wants and this module provides:

* **It cannot write.** :class:`ReadOnlyCoexClient` rejects any method other than
  GET before a socket is opened. Passing it to code that tries to set brightness
  raises rather than changing a live screen. That is a structural guarantee, not
  a convention -- there is no code path from this class to a PUT.
* **It cannot hammer.** Requests are rate-limited, and a ``Busying`` response
  (COEX error code 5) backs the poller off rather than retrying immediately.
* **It holds no secret.** ``/api/v1/device/hw`` serves ``randomPassword`` to any
  GET (OBSERVED, one MX30); :class:`~novasun.coex.CoexClient` drops it before a
  payload reaches a snapshot, and :func:`interpret_hardware_info` copies only
  named identity fields.

Display state is read from ``/api/v1/screen/output/display/state`` and mapped
per canvas by :func:`interpret_display_state`: 0 normal, 2 freeze and 1
blackout are all OBSERVED (one MX30, firmware V1.5.1, attended front-panel
freezes and one front-panel blackout on 2026-09-26). An absent endpoint, an empty 200 or an unrecognised value is
*unknown* -- never normal.

Whether polling a COEX controller disturbs a VMP session is **not established**;
see ``docs/read-only-monitoring.md`` for the reasoning, the evidence, and the
ten-minute test that settles it. The defaults here are deliberately timid.

For the register bus, monitoring means reading the 0x0A000000 block per
receiving card. That is a read, but it is not free: it opens a TCP control
session, which NovaLCT may be holding exclusively. :func:`register_bus_monitor`
exists but is the fallback, not the default.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .coex import DEFAULT_PORT, CoexClient, CoexError
from .protocol import ProtocolError

#: GET endpoints worth polling, and how they map onto a monitoring pane.
#:
#: ``display_state`` replaced the documented ``/api/v1/device/screen/displaymode``
#: GET, which was absent on both units read (OBSERVED: HTTP 404 on an MX40 Pro,
#: an empty 200 on an MX30) and so never yielded a value; polling it cost a
#: request per tick for nothing.
MONITORING_ENDPOINTS: dict[str, str] = {
    "device": "/api/v1/device",
    "hardware": "/api/v1/device/hw",
    "screens": "/api/v1/screen",
    "cabinets": "/api/v1/device/cabinet",
    # ~120 B, so read every poll: the cheap signal that cabinets dropped off.
    # /device/cabinet (~90 KB for 72) stays in the slow tier and is re-read at
    # once when this count disagrees with the cached list (see CoexMonitor.poll).
    "cabinet_count": "/api/v1/screen/cabinet/count",
    "inputs": "/api/v1/device/input/sources",
    "monitoring": "/api/v1/device/monitor/info",
    "display_state": "/api/v1/screen/output/display/state",
    "presets": "/api/v1/preset",
    "backup": "/api/v1/device/backup",
}

SLOW_ENDPOINTS = frozenset({"cabinets", "presets", "device", "hardware"})
"""Topology and identity change rarely -- poll these far less often than status."""

#: ``displayState[].displayMode`` on ``/api/v1/screen/output/display/state``, per
#: canvas -- the COEX convention, the opposite of the VX4S register's.
DISPLAY_MODE_NAMES: dict[int, str] = {0: "normal", 1: "blackout", 2: "freeze"}

#: How each value is known. Scope: one MX30, firmware (hwVersion) V1.5.1,
#: 2026-09-26.
DISPLAY_MODE_CONFIDENCE: dict[int, str] = {
    # Read before and after an attended front-panel freeze, polled at 1 Hz, and
    # pushed by the unit's websocket at the release of two freezes.
    0: "OBSERVED",
    # Read throughout that attended freeze; the websocket pushed the same value
    # at the start of it and of a second freeze.
    2: "OBSERVED",
    # An attended front-panel blackout on 2026-09-26 read 1 here at the 1 Hz
    # poll and was pushed as 1 on the websocket (OBSERVED once).
    1: "OBSERVED",
}

UNKNOWN_DISPLAY = "unknown"
"""The display state when it could not be read or was not understood."""


class WriteAttempted(Exception):
    """Something tried to write through a read-only client."""


class ReadOnlyCoexClient(CoexClient):
    """A COEX client that physically cannot modify the controller.

    Every setter inherited from :class:`~novasun.coex.CoexClient` funnels through
    ``request``; refusing non-GET there closes all of them at once, including
    any added later.
    """

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        if method.upper() != "GET":
            raise WriteAttempted(
                f"read-only client refused {method} {path}"
                + (" with a body" if body else "")
            )
        return super().request(method, path)


@dataclass
class RateLimiter:
    """Minimum spacing between requests, with back-off on device contention."""

    interval: float = 0.2
    backoff: float = 5.0
    _next_allowed: float = field(default=0.0, repr=False)

    def wait(self) -> None:
        delay = self._next_allowed - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self._next_allowed = time.monotonic() + self.interval

    def back_off(self, seconds: float | None = None) -> None:
        self._next_allowed = time.monotonic() + (seconds or self.backoff)


@dataclass
class CabinetHealth:
    """Per-cabinet state a monitoring pane can show.

    ``online`` on a COEX controller means *listed as connected by
    ``/api/v1/device/cabinet`` and reporting in monitor/info*. Presence in
    monitor/info alone **is not presence** (withdrawn 2026-09-26):
    on an MX30 with every output line unplugged, monitor/info kept all 72
    cabinets and cards, ``linkStatus`` true and temperatures reading, for ~8.5
    minutes until power-off (OBSERVED, attended). Its readings are last-known
    values (REASONED), so ``online`` and ``link_ok`` here can report an
    unplugged wall as healthy. Connected cabinets are counted by
    ``/api/v1/screen/cabinet/count`` and ``/api/v1/device/cabinet``, which both
    went to 0 (OBSERVED); see docs/read-only-monitoring.md §4, "Unplugged
    outputs, and power-off". ``link_ok`` is the card's own
    ``nextCabinetLinkStatus.linkStatus`` (true on a healthy wall, and stale on
    an unplugged one).
    """

    identifier: Any
    name: str | None = None
    online: bool | None = None
    temperature: float | None = None
    brightness: float | None = None
    screen: str | None = None
    voltage: float | None = None
    link_ok: bool | None = None


@dataclass
class MonitorSnapshot:
    """One poll's worth of state, plus what failed to read."""

    timestamp: float
    model: str | None = None
    device_name: str | None = None
    serial: str | None = None
    model_id: int | None = None
    """``/api/v1/device/hw`` ``modelID`` as reported (5138 on the MX30, OBSERVED)."""
    firmware: str | None = None
    """``/api/v1/device/hw`` ``hwVersion`` -- "V1.5.1" on the MX30, the string SNMP
    and ``/device/firmware/list`` also report; that it is *the* firmware
    version is REASONED."""
    display_mode: int | None = None
    """0 normal, 1 blackout, 2 freeze (the COEX convention) when every canvas in
    ``display/state`` reported the same recognised value; ``None`` means
    unknown -- never normal. See :attr:`display` and :attr:`display_canvases`."""
    display: str = UNKNOWN_DISPLAY
    """``"normal"``, ``"blackout"``, ``"freeze"``, ``"mixed"`` (canvases differ)
    or ``"unknown"``."""
    display_canvases: list[dict[str, Any]] = field(default_factory=list)
    """Per canvas: ``canvas_id``, ``display_mode``, ``state`` and ``confidence``."""
    connected_cabinets: int | None = None
    """``/api/v1/screen/cabinet/count`` total, or ``None`` when not read."""
    expected_cabinets: int | None = None
    """The most cabinets a :class:`CoexMonitor` has seen connected."""
    outputs: list[dict[str, Any]] = field(default_factory=list)
    """From monitor/info ``outputStatus`` (:func:`interpret_outputs`)."""
    carrying_outputs: list[int] = field(default_factory=list)
    """Outputs seen carrying cabinets, now or (via the monitor) earlier."""
    screens: list[dict[str, Any]] = field(default_factory=list)
    cabinets: list[CabinetHealth] = field(default_factory=list)
    inputs: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def health_reasons(self) -> list[str]:
        """Why this wall is not healthy; empty when it is (see :func:`health_reasons`)."""
        listed = len(self.cabinets) if "cabinets" in self.raw else None
        return health_reasons(
            listed=listed, offline=len(self.offline_cabinets), connected=self.connected_cabinets,
            expected=self.expected_cabinets, outputs=self.outputs, carrying=self.carrying_outputs,
        )

    @property
    def healthy(self) -> bool:
        """True only when a connected-cabinet source answered and nothing is wrong.

        Never true on monitor/info's word alone: it kept an unplugged MX30's
        cabinets listed and linked (OBSERVED 2026-09-26)."""
        return not self.health_reasons

    @property
    def offline_cabinets(self) -> list[CabinetHealth]:
        return [cabinet for cabinet in self.cabinets if cabinet.online is False]

    @property
    def hottest(self) -> CabinetHealth | None:
        with_temperature = [c for c in self.cabinets if c.temperature is not None]
        return max(with_temperature, key=lambda c: c.temperature or 0) if with_temperature else None

    @property
    def signal_present(self) -> list[str]:
        # A real MX40 Pro has no "connected"; it has sourceStatus, 1 on the two
        # inputs that were carrying the show and 0 on the rest. REASONED from
        # that pattern -- an unplug test would make it OBSERVED.
        return [
            str(source.get("name") or source.get("id"))
            for source in self.inputs
            if source.get("connected") or source.get("sourceStatus") == 1
        ]

    def summary(self) -> str:
        lines = [f"{self.model or 'unknown model'}  {self.device_name or ''}".strip()]
        if self.firmware:
            lines.append(f"  firmware    {self.firmware}")
        # Always said, so an unreadable display state cannot pass for a live one.
        lines.append(f"  display     {_display_text(self.display, self.display_canvases)}")
        online = len([c for c in self.cabinets if c.online])
        lines.append(f"  cabinets    {online}/{len(self.cabinets)} online"
                     + (f", {self.expected_cabinets} expected" if self.expected_cabinets
                        and self.expected_cabinets != len(self.cabinets) else ""))
        if self.outputs:
            linked = [str(o["output_id"]) for o in self.outputs if o["linked"]]
            lines.append(f"  outputs     linked: {', '.join(linked) or 'none'}")
        for reason in self.health_reasons:
            lines.append(f"  ! {reason}")
        hottest = self.hottest
        if hottest is not None:
            lines.append(f"  hottest     {hottest.name or hottest.identifier} {hottest.temperature} C")
        if self.inputs:
            lines.append(f"  signal on   {', '.join(self.signal_present) or 'none'}")
        for name, message in self.errors.items():
            lines.append(f"  ! {name}: {message}")
        return "\n".join(lines)


class CoexMonitor:
    """Polls a COEX controller for status, and only for status."""

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        timeout: float = 3.0,
        interval: float = 0.2,
    ) -> None:
        self.client = ReadOnlyCoexClient(host, port, timeout=timeout)
        self.limiter = RateLimiter(interval=interval)
        self._slow_cache: dict[str, Any] = {}
        self._polls = 0
        self._max_connected: int | None = None
        self._carrying: set[int] = set()

    def _get(self, name: str, path: str) -> tuple[Any, str | None]:
        self.limiter.wait()
        try:
            return self.client.request("GET", path), None
        except CoexError as exc:
            if exc.code == 5:  # Busying: the controller is doing something else
                self.limiter.back_off()
            return None, str(exc)
        except (OSError, ValueError, ProtocolError) as exc:
            return None, str(exc)

    def poll(self, include_slow: bool | None = None) -> MonitorSnapshot:
        """One pass. Slow-changing endpoints are re-read every tenth poll."""
        if include_slow is None:
            include_slow = self._polls % 10 == 0
        self._polls += 1

        snapshot = MonitorSnapshot(timestamp=time.time())
        from_cache: set[str] = set()
        for name, path in MONITORING_ENDPOINTS.items():
            if name in SLOW_ENDPOINTS and not include_slow and name in self._slow_cache:
                snapshot.raw[name] = self._slow_cache[name]
                from_cache.add(name)
                continue
            value, error = self._get(name, path)
            if error is not None:
                snapshot.errors[name] = error
                continue
            snapshot.raw[name] = value
            if name in SLOW_ENDPOINTS:
                self._slow_cache[name] = value
        # A cached cabinet list can hide an unplug for nine polls. The count is
        # read every poll; when it disagrees with the cache, re-read the list.
        count = interpret_cabinet_count(snapshot.raw.get("cabinet_count"))
        cached = snapshot.raw.get("cabinets")
        if "cabinets" in from_cache and count is not None and isinstance(cached, list) and len(cached) != count:
            value, error = self._get("cabinets", MONITORING_ENDPOINTS["cabinets"])
            if error is None:
                snapshot.raw["cabinets"] = self._slow_cache["cabinets"] = value
            else:
                snapshot.errors["cabinets"] = error
        snapshot = _interpret(snapshot)
        basis = snapshot.connected_cabinets
        if basis is None and "cabinets" in snapshot.raw:
            basis = len(snapshot.cabinets)
        if basis is not None:
            self._max_connected = max(self._max_connected or 0, basis)
        self._carrying |= set(snapshot.carrying_outputs)
        snapshot.expected_cabinets = self._max_connected
        snapshot.carrying_outputs = sorted(self._carrying)
        return snapshot

    def close(self) -> None:
        pass  # urllib holds no persistent connection

    def __enter__(self) -> "CoexMonitor":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _integer(value: Any) -> int | None:
    """An int that is not a bool; anything else is ``None``."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _text(value: Any) -> str | None:
    """A non-blank string, stripped; anything else is ``None``."""
    return value.strip() if isinstance(value, str) and value.strip() else None


def interpret_display_state(payload: Any) -> dict[str, Any]:
    """Display state from one ``/api/v1/screen/output/display/state`` payload.

    Returns ``{"display_mode", "display", "canvases"}``: the COEX value when
    every canvas agrees on a recognised one (else ``None``), its name
    (:data:`DISPLAY_MODE_NAMES`, ``"mixed"`` or ``"unknown"``), and one entry
    per ``displayState`` element with ``canvas_id``, ``display_mode``,
    ``state`` and ``confidence`` (:data:`DISPLAY_MODE_CONFIDENCE`).

    **Unknown is never normal.** An absent endpoint, the MX30's empty 200 (which
    :class:`~novasun.coex.CoexClient` hands back as ``{}``), a missing or empty
    ``displayState``, and a value outside 0/1/2 -- including a bool or a
    numeric string -- all yield ``display_mode`` ``None`` and ``"unknown"``.

    Total: it never raises, whatever it is handed.
    """
    result: dict[str, Any] = {"display_mode": None, "display": UNKNOWN_DISPLAY, "canvases": []}
    if isinstance(payload, dict) and "displayState" not in payload:
        # Tolerate an envelope a caller did not unwrap.
        inner = payload.get("data")
        if isinstance(inner, dict):
            payload = inner
    entries = payload.get("displayState") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return result
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        mode = _integer(entry.get("displayMode"))
        known = mode in DISPLAY_MODE_NAMES
        result["canvases"].append({
            "canvas_id": _integer(entry.get("canvasID")),
            "display_mode": mode if known else None,
            "state": DISPLAY_MODE_NAMES[mode] if known else UNKNOWN_DISPLAY,
            "confidence": DISPLAY_MODE_CONFIDENCE[mode] if known else "UNKNOWN",
        })
    modes = [canvas["display_mode"] for canvas in result["canvases"]]
    if not modes or any(mode is None for mode in modes):
        return result
    if len(set(modes)) == 1:
        result["display_mode"] = modes[0]
        result["display"] = DISPLAY_MODE_NAMES[modes[0]]
    else:
        result["display"] = "mixed"
    return result


def _display_text(display: str, canvases: list[dict[str, Any]]) -> str:
    """One line for a summary: the state, qualified where it needs to be."""
    text = display
    if display == "mixed" or (display == UNKNOWN_DISPLAY and canvases):
        text += " (" + ", ".join(
            f"canvas {c.get('canvas_id')} {c.get('state')}" for c in canvases
        ) + ")"
    return text


def interpret_hardware_info(payload: Any) -> dict[str, Any]:
    """The identity fields of one ``/api/v1/device/hw`` payload, and nothing else.

    Returns ``model`` (``name``), ``model_id`` (``modelID``), ``firmware``
    (``hwVersion``), ``serial`` (``sn``) and ``custom_name`` (``customName``),
    each ``None`` when absent or of the wrong type. Field names and values are
    OBSERVED on one MX30 (V1.5.1, 2026-09-26); that ``name`` is the model and
    ``hwVersion`` the firmware is REASONED, and ``sn`` equalled the serial in
    ``backcard/info``, so whether it is the chassis's or a board's is UNKNOWN.

    Only these named fields are copied, so ``randomPassword`` -- served in the
    same object -- cannot pass through here even if a caller hands over an
    unredacted payload. Total: it never raises.
    """
    fields = {"model": None, "model_id": None, "firmware": None, "serial": None,
              "custom_name": None}
    if not isinstance(payload, dict):
        return fields
    fields["model"] = _text(payload.get("name"))
    fields["model_id"] = _integer(payload.get("modelID"))
    fields["firmware"] = _text(payload.get("hwVersion"))
    fields["serial"] = _text(payload.get("sn"))
    fields["custom_name"] = _text(payload.get("customName"))
    return fields


def _reading(value: Any) -> float | None:
    """A sensor value as monitor/info reports it: ``{"value": 39, ...}`` or bare."""
    if isinstance(value, dict):
        return _number(value.get("value"))
    return _number(value)


def _live_cabinets(info: Any) -> dict[str, dict[str, Any]]:
    """Per-cabinet readings from monitor/info, keyed by cabinet id.

    OBSERVED shape on an MX40 Pro: ``cabinets[]`` entries whose own ``cabinetID``
    is always 0 and whose top-level temperature reads 0, each carrying an
    ``rvCards[]`` list -- one card on that wall -- and it is the card that holds
    the real readings and the id that matches ``/api/v1/device/cabinet``'s
    ``id`` (288 of 288). The simulator's earlier guess -- flat entries with
    ``id``, numeric ``temperature`` and ``online`` -- is still understood.
    """
    live: dict[str, dict[str, Any]] = {}
    for entry in _as_list(info, "cabinets"):
        if not isinstance(entry, dict):
            continue
        cards = entry.get("rvCards")
        if isinstance(cards, list):
            for card in cards:
                if not isinstance(card, dict) or card.get("cabinetID") is None:
                    continue
                link = card.get("nextCabinetLinkStatus")
                live[str(card["cabinetID"])] = {
                    "present": True,
                    "temperature": _reading(card.get("temperature")),
                    "voltage": _reading(card.get("voltage")),
                    "link_ok": link.get("linkStatus") if isinstance(link, dict) else None,
                }
        elif entry.get("id") is not None:
            live[str(entry["id"])] = {
                "present": entry.get("online"),
                "temperature": _reading(entry.get("temperature")),
                "voltage": _reading(entry.get("voltage")),
                "link_ok": None,
            }
    return live


def interpret_monitor_info(info: Any) -> dict[str, Any]:
    """What one monitor/info payload says on its own -- **not** which cabinets are
    connected.

    Keys: ``cabinets_listed`` and ``links_listed_ok`` (cabinets and card links in
    its list), ``temperature_c`` (hottest listed card), main-board temperature
    and voltage, and ``outputs_linked``. On an MX30 with every output line
    unplugged this payload kept all 72 cabinets listed, every link true and
    temperatures reading for ~8.5 minutes (OBSERVED, 2026-09-26): its cabinet
    list is last-known, not live. So it no longer yields ``cabinets_total`` or
    ``cabinets_online``; use :func:`interpret_coex_status`, which counts from
    ``/api/v1/device/cabinet`` and ``/api/v1/screen/cabinet/count``.

    Total: it never raises, whatever shape it is handed. The application's
    refresh thread once died on a real MX40 Pro because the temperature field
    turned out to be ``{"name", "status", "value"}`` and ``max()`` was asked to
    compare dicts -- a TypeError that nothing caught.
    """
    status: dict[str, Any] = {}
    if not isinstance(info, dict):
        return status
    live = _live_cabinets(info)
    status["cabinets_listed"] = len(live) or len(_as_list(info, "cabinets"))
    temperatures = [c["temperature"] for c in live.values() if c.get("temperature") is not None]
    if temperatures:
        status["temperature_c"] = max(temperatures)
    board_t = _reading(info.get("mainBoardTemperature"))
    if board_t is not None:
        status["main_board_temperature_c"] = board_t
    board_v = _reading(info.get("mainBoardVoltage"))
    if board_v is not None:
        status["main_board_voltage_v"] = board_v
    links = [c["link_ok"] for c in live.values() if c.get("link_ok") is not None]
    if links:
        status["links_listed_ok"] = sum(1 for ok in links if ok)
    outputs = interpret_outputs(info)
    if outputs:
        status["outputs_linked"] = [o["output_id"] for o in outputs if o["linked"]]
    return status


def interpret_coex_status(
    info: Any, cabinets: Any = None, cabinet_count: Any = None,
    expected: int | None = None, carrying: Any = (),
) -> dict[str, Any]:
    """The status a pane or alert engine should show for a COEX controller.

    Counts come from ``cabinets`` (a ``/api/v1/device/cabinet`` payload) and
    ``cabinet_count`` (``/api/v1/screen/cabinet/count``); ``info`` (monitor/info)
    only decorates cabinets those list, and gives output links. ``expected`` and
    ``carrying`` are what a caller remembers from earlier reads. Adds
    ``cabinets_total``, ``cabinets_online``, ``connected_cabinets``,
    ``carrying_outputs``, ``healthy`` and ``health_reasons`` to
    :func:`interpret_monitor_info`'s keys, and replaces its ``temperature_c``
    with the hottest *connected* card -- none when nothing is connected, rather
    than a stale reading. Total: never raises.
    """
    status = interpret_monitor_info(info)
    status.pop("temperature_c", None)
    live = _live_cabinets(info)
    entries = [e for e in _as_list(cabinets, "cabinets") if isinstance(e, dict)] if cabinets is not None else None
    listed = len(entries) if entries is not None else None
    connected = interpret_cabinet_count(cabinet_count)
    ids = [str(e.get("id")) for e in entries or []]
    reporting = [i for i in ids if not live or i in live]
    temperatures = [live[i]["temperature"] for i in reporting if i in live and live[i].get("temperature") is not None]
    if temperatures:
        status["temperature_c"] = max(temperatures)
    carrying = set(carrying) | {_integer(e.get("outputID")) for e in entries or [] if _integer(e.get("outputID")) is not None}
    basis = connected if connected is not None else listed
    known = [n for n in (expected, listed, connected) if n is not None]
    status["cabinets_total"] = max(known) if known else None
    status["cabinets_online"] = min(len(reporting), basis) if basis is not None else None
    status["connected_cabinets"] = basis
    status["carrying_outputs"] = sorted(carrying)
    reasons = health_reasons(listed=listed, offline=len(ids) - len(reporting), connected=connected,
                             expected=expected, outputs=interpret_outputs(info), carrying=carrying)
    status["healthy"] = not reasons
    status["health_reasons"] = reasons
    return status


def interpret_cabinet_count(payload: Any) -> int | None:
    """Connected cabinets from one ``/api/v1/screen/cabinet/count`` payload.

    The sum of ``CabinetCount`` over its ``list``, or ``None`` when absent or not
    understood. OBSERVED on one MX30 (V1.5.1, 2026-09-26): 72 with the wall
    connected, 0 with every output line unplugged, tracking the websocket's
    ``ScreensCabinetsCountChange`` at every stage. Total: never raises.
    """
    counts = [_integer(e.get("CabinetCount")) for e in _as_list(payload, "list") if isinstance(e, dict)]
    if not counts or any(count is None for count in counts):
        return None
    return sum(counts)


def interpret_outputs(info: Any) -> list[dict[str, Any]]:
    """Per output, from monitor/info ``outputStatus``: ``output_id``, ``linked``,
    ``status`` and ``type``. ``linkStatus`` dropped within one 2 s poll of each
    line being unplugged on the MX30 (OBSERVED). Total: never raises."""
    outputs = []
    for entry in _as_list(info, "outputStatus"):
        if not isinstance(entry, dict) or _integer(entry.get("outputID")) is None:
            continue
        linked = entry.get("linkStatus")
        outputs.append({
            "output_id": _integer(entry.get("outputID")),
            "linked": linked if isinstance(linked, bool) else None,
            "status": _integer(entry.get("status")),
            "type": _integer(entry.get("type")),
        })
    return outputs


def health_reasons(
    *, listed: int | None, offline: int, connected: int | None, expected: int | None,
    outputs: list[dict[str, Any]], carrying: Any = (),
) -> list[str]:
    """Why a COEX wall is not healthy; an empty list means healthy.

    ``listed`` is the entry count of ``/api/v1/device/cabinet`` and ``connected``
    the ``/api/v1/screen/cabinet/count`` total -- the two sources that went to 0
    when every line was unplugged (OBSERVED). **monitor/info is not a source**:
    it kept all 72 cabinets listed and linked through that (OBSERVED), so
    counting from it reports an unplugged wall as healthy. ``expected`` is the
    most cabinets seen connected, and ``carrying`` the outputs seen carrying
    them. Neither source answering is a reason in itself: unknown, never healthy.
    """
    basis = connected if connected is not None else listed
    if basis is None:
        return ["no connected-cabinet source answered: state unknown"]
    reasons = []
    if basis == 0:
        reasons.append("no cabinets connected")
    if offline:
        reasons.append(f"{offline} listed cabinet(s) missing from monitoring")
    if listed is not None and connected is not None and connected < listed:
        reasons.append(f"controller counts {connected} connected but lists {listed}")
    if expected and basis < expected:
        reasons.append(f"{expected - basis} of {expected} cabinet(s) disconnected")
    carrying = set(carrying)
    down = sorted(o["output_id"] for o in outputs if o["output_id"] in carrying and o["linked"] is False)
    if down:
        reasons.append("no link on output(s) carrying cabinets: " + ", ".join(map(str, down)))
    return reasons


def _as_list(value: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        for key in keys:
            if isinstance(value.get(key), list):
                return value[key]
    return value if isinstance(value, list) else []


def _interpret(snapshot: MonitorSnapshot) -> MonitorSnapshot:
    """Map raw endpoint payloads onto the monitoring model.

    Field names follow NovaStar's manual and the shapes published clients
    expect. They are *not* verified against firmware, so every lookup is
    forgiving: an unexpected spelling leaves a field ``None`` rather than
    raising, and the raw payload stays on the snapshot for a caller that knows
    better.
    """
    from .coex import redact_secrets
    from .devices import coex_profile_for, coex_profile_from_hardware  # cheap

    # Belt and braces: the client already drops secrets, but a snapshot built
    # by hand from a captured payload must not carry one either.
    if "hardware" in snapshot.raw:
        snapshot.raw["hardware"] = redact_secrets(snapshot.raw["hardware"])

    device = snapshot.raw.get("device")
    if isinstance(device, dict):
        snapshot.model = device.get("model") or device.get("deviceModel")
        snapshot.device_name = device.get("name") or device.get("deviceName")
        snapshot.serial = device.get("sn") or device.get("serialNumber")

    # /api/v1/device is absent on both units read (OBSERVED: MX40 Pro
    # 2026-09-11, MX30 2026-09-26). monitor/info's name is then the device
    # name. On the MX40 Pro it read "MX40 Pro_<digits>" and carried the model;
    # on the MX30 it was a plain word carrying no model at all. The API
    # documents a custom-name setter, so the field is an operator-settable
    # label whose "<model>_<digits>" form is a factory default (REASONED). A
    # model is taken from it only when a known model name is actually in it.
    # An earlier version accepted the fallback profile's name, which *was* the
    # label, and reported the MX30's model as "<label>".
    #
    # /api/v1/device/hw names the model outright on the MX30 -- name "MX30",
    # modelID 5138, with the controller's name in customName (OBSERVED, one
    # read) -- so it is preferred to parsing a label. A name it gives that the
    # table does not know is still reported, as a model field's value; one
    # equal to a label is not, since a label is no evidence of a model.
    hardware = interpret_hardware_info(snapshot.raw.get("hardware"))
    info = snapshot.raw.get("monitoring")
    label = _text(info.get("name")) if isinstance(info, dict) else None
    snapshot.device_name = snapshot.device_name or label or hardware["custom_name"]
    snapshot.serial = snapshot.serial or hardware["serial"]
    snapshot.model_id = hardware["model_id"]
    snapshot.firmware = hardware["firmware"]
    if snapshot.model is None:
        from_hardware = coex_profile_from_hardware(hardware["model"], hardware["model_id"])
        from_label = coex_profile_for(label)
        if from_hardware.model_known:
            snapshot.model = from_hardware.name
        elif label and from_label.model_known:
            snapshot.model = from_label.name
        elif hardware["model"] and hardware["model"] not in {label, hardware["custom_name"]}:
            snapshot.model = hardware["model"]

    display = interpret_display_state(snapshot.raw.get("display_state"))
    snapshot.display_mode = display["display_mode"]
    snapshot.display = display["display"]
    snapshot.display_canvases = display["canvases"]

    snapshot.screens = _as_list(snapshot.raw.get("screens"), "screens")
    snapshot.inputs = _as_list(snapshot.raw.get("inputs"), "sources", "inputs")

    snapshot.connected_cabinets = interpret_cabinet_count(snapshot.raw.get("cabinet_count"))
    snapshot.outputs = interpret_outputs(snapshot.raw.get("monitoring"))
    snapshot.carrying_outputs = sorted({
        _integer(e.get("outputID")) for e in _as_list(snapshot.raw.get("cabinets"), "cabinets")
        if isinstance(e, dict) and _integer(e.get("outputID")) is not None
    })

    live_by_id = _live_cabinets(snapshot.raw.get("monitoring"))
    for entry in _as_list(snapshot.raw.get("cabinets"), "cabinets"):
        if not isinstance(entry, dict):
            continue
        live = live_by_id.get(str(entry.get("id")), {})
        if live:
            online = bool(live.get("present"))
        elif live_by_id:
            online = False  # monitoring answered, and this cabinet was not in it
        else:
            online = entry.get("online")
        snapshot.cabinets.append(
            CabinetHealth(
                identifier=entry.get("id"),
                # Real cabinets carry no "name"; shortName is usually empty and
                # rvCardName is the card model ("A5sPlus"), so a pane falls back
                # to the id -- which is what the operator's VMP shows too.
                name=entry.get("name") or entry.get("shortName") or None,
                online=online,
                temperature=live.get("temperature", _reading(entry.get("temperature"))),
                brightness=_number(entry.get("brightness")),
                screen=entry.get("screenID") or entry.get("canvasID"),
                voltage=live.get("voltage"),
                link_ok=live.get("link_ok"),
            )
        )
    return snapshot


def register_bus_monitor(host: str, ports: int, cards_per_port: int, timeout: float = 2.0):
    """Read monitoring blocks from receiving cards over the register bus.

    The fallback for non-COEX hardware. Note the cost: this opens a TCP control
    session on 5200, which NovaLCT may be holding exclusively, and it issues one
    read per card. Prefer SNMP or the HTTP API where the hardware offers them.
    """
    from .client import Controller

    results: dict[tuple[int, int], Any] = {}
    with Controller.connect(host, timeout=timeout) as controller:
        for port in range(ports):
            for index in range(cards_per_port):
                try:
                    results[(port, index)] = controller.read_receiver_monitoring(port, index)
                except Exception:  # noqa: BLE001 - an absent card is normal here
                    results[(port, index)] = None
    return results
