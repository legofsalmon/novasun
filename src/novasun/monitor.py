"""Read-only monitoring, for tools that observe rather than control.

Two guarantees a monitoring pane wants and this module provides:

* **It cannot write.** :class:`ReadOnlyCoexClient` rejects any method other than
  GET before a socket is opened. Passing it to code that tries to set brightness
  raises rather than changing a live screen. That is a structural guarantee, not
  a convention -- there is no code path from this class to a PUT.
* **It cannot hammer.** Requests are rate-limited, and a ``Busying`` response
  (COEX error code 5) backs the poller off rather than retrying immediately.

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

#: GET endpoints worth polling, and how they map onto a monitoring pane.
MONITORING_ENDPOINTS: dict[str, str] = {
    "device": "/api/v1/device",
    "screens": "/api/v1/screen",
    "cabinets": "/api/v1/device/cabinet",
    "inputs": "/api/v1/device/input/sources",
    "monitoring": "/api/v1/device/monitor/info",
    "display_mode": "/api/v1/device/screen/displaymode",
    "presets": "/api/v1/preset",
    "backup": "/api/v1/device/backup",
}

SLOW_ENDPOINTS = frozenset({"cabinets", "presets", "device"})
"""Topology and identity change rarely -- poll these far less often than status."""


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
    """Per-cabinet state a monitoring pane can show."""

    identifier: Any
    name: str | None = None
    online: bool | None = None
    temperature: float | None = None
    brightness: float | None = None
    screen: str | None = None


@dataclass
class MonitorSnapshot:
    """One poll's worth of state, plus what failed to read."""

    timestamp: float
    model: str | None = None
    device_name: str | None = None
    serial: str | None = None
    display_mode: int | None = None
    screens: list[dict[str, Any]] = field(default_factory=list)
    cabinets: list[CabinetHealth] = field(default_factory=list)
    inputs: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def healthy(self) -> bool:
        """True when every cabinet that reported a state reported itself online."""
        states = [c.online for c in self.cabinets if c.online is not None]
        return bool(states) and all(states)

    @property
    def offline_cabinets(self) -> list[CabinetHealth]:
        return [cabinet for cabinet in self.cabinets if cabinet.online is False]

    @property
    def hottest(self) -> CabinetHealth | None:
        with_temperature = [c for c in self.cabinets if c.temperature is not None]
        return max(with_temperature, key=lambda c: c.temperature or 0) if with_temperature else None

    @property
    def signal_present(self) -> list[str]:
        return [
            str(source.get("name") or source.get("id"))
            for source in self.inputs
            if source.get("connected")
        ]

    def summary(self) -> str:
        lines = [f"{self.model or 'unknown model'}  {self.device_name or ''}".strip()]
        if self.display_mode is not None:
            lines.append(
                f"  display     {['normal', 'blackout', 'freeze'][self.display_mode]}"
                if self.display_mode in (0, 1, 2)
                else f"  display     {self.display_mode}"
            )
        online = len([c for c in self.cabinets if c.online])
        lines.append(f"  cabinets    {online}/{len(self.cabinets)} online")
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

    def _get(self, name: str, path: str) -> tuple[Any, str | None]:
        self.limiter.wait()
        try:
            return self.client.request("GET", path), None
        except CoexError as exc:
            if exc.code == 5:  # Busying: the controller is doing something else
                self.limiter.back_off()
            return None, str(exc)
        except (OSError, ValueError) as exc:
            return None, str(exc)

    def poll(self, include_slow: bool | None = None) -> MonitorSnapshot:
        """One pass. Slow-changing endpoints are re-read every tenth poll."""
        if include_slow is None:
            include_slow = self._polls % 10 == 0
        self._polls += 1

        snapshot = MonitorSnapshot(timestamp=time.time())
        for name, path in MONITORING_ENDPOINTS.items():
            if name in SLOW_ENDPOINTS and not include_slow and name in self._slow_cache:
                snapshot.raw[name] = self._slow_cache[name]
                continue
            value, error = self._get(name, path)
            if error is not None:
                snapshot.errors[name] = error
                continue
            snapshot.raw[name] = value
            if name in SLOW_ENDPOINTS:
                self._slow_cache[name] = value
        return _interpret(snapshot)

    def close(self) -> None:
        pass  # urllib holds no persistent connection

    def __enter__(self) -> "CoexMonitor":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


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
    device = snapshot.raw.get("device")
    if isinstance(device, dict):
        snapshot.model = device.get("model") or device.get("deviceModel")
        snapshot.device_name = device.get("name") or device.get("deviceName")
        snapshot.serial = device.get("sn") or device.get("serialNumber")

    display = snapshot.raw.get("display_mode")
    if isinstance(display, dict) and isinstance(display.get("value"), int):
        snapshot.display_mode = display["value"]

    snapshot.screens = _as_list(snapshot.raw.get("screens"), "screens")
    snapshot.inputs = _as_list(snapshot.raw.get("inputs"), "sources", "inputs")

    monitoring = {
        str(entry.get("id")): entry
        for entry in _as_list(snapshot.raw.get("monitoring"), "cabinets")
        if isinstance(entry, dict)
    }
    for entry in _as_list(snapshot.raw.get("cabinets"), "cabinets"):
        if not isinstance(entry, dict):
            continue
        live = monitoring.get(str(entry.get("id")), {})
        snapshot.cabinets.append(
            CabinetHealth(
                identifier=entry.get("id"),
                name=entry.get("name"),
                online=live.get("online", entry.get("online")),
                temperature=live.get("temperature", entry.get("temperature")),
                brightness=entry.get("brightness"),
                screen=entry.get("screenID"),
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
