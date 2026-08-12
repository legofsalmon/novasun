"""Application state: several devices, held over time.

Everything below this layer is per-operation — open a connection, do a thing,
close it. An application needs the opposite: a persistent model of several
processors that survives a device going away and coming back, refreshes itself,
and can be rendered at any moment without blocking on the network.

Design decisions that matter:

* **Connections are held, not reopened.** A control application legitimately
  owns the control session; reconnecting per click would be slower and would
  fight NovaLCT for the socket more often, not less.
* **Reachability is a state, not an exception.** A processor that is powered off,
  or whose session NovaLCT is holding, is a normal condition to display. It gets
  retried with backoff and never raises into the UI.
* **Refresh never blocks control.** Each device has its own lock; a slow refresh
  on one device cannot delay a command to another.
* **Destructive actions are marked, not blocked.** Blackout and freeze are
  legitimate operations that also ruin a show if sent by accident. The state
  layer labels them so the interface can confirm; it does not decide policy.

Deliberately absent: anything that writes flash, resets to factory defaults, or
touches program space. Those live in the register map and are reachable through
``Controller`` for someone who means it, but an application should not surface
them beside a brightness slider.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from ..devices import DeviceProfile, Family, identify, unknown_profile
from ..processor import CapabilityUnknown, NotSupported, Processor
from ..registers import DisplayMode, TestPattern

MAX_BACKOFF = 60.0
FIRST_BACKOFF = 2.0


class Reachability(str, Enum):
    UNKNOWN = "unknown"
    ONLINE = "online"
    UNREACHABLE = "unreachable"
    IN_USE = "in-use"
    """Answered, but the control session was refused — probably NovaLCT or VMP."""


@dataclass
class ActionRecord:
    """One command this application sent. Kept so an operator can see why."""

    timestamp: float
    address: str
    action: str
    detail: str = ""
    ok: bool = True
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "address": self.address,
            "action": self.action,
            "detail": self.detail,
            "ok": self.ok,
            "error": self.error,
        }


DESTRUCTIVE = frozenset({"blackout", "freeze", "display_mode", "test_pattern"})
"""Actions an interface should confirm. All are reversible, all ruin a show."""


@dataclass
class DeviceState:
    """The renderable state of one device. Plain data; safe to serialise."""

    address: str
    reachability: str = Reachability.UNKNOWN.value
    model: str | None = None
    family: str = Family.UNKNOWN.value
    name: str | None = None
    serial: str | None = None
    control_path: str | None = None
    ethernet_ports: int | None = None
    fibre_ports: int = 0
    inputs: list[dict[str, Any]] = field(default_factory=list)
    status: dict[str, Any] = field(default_factory=dict)
    capabilities: dict[str, bool] = field(default_factory=dict)
    last_seen: float | None = None
    last_error: str | None = None
    next_retry: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "reachability": self.reachability,
            "model": self.model,
            "family": self.family,
            "name": self.name,
            "serial": self.serial,
            "control_path": self.control_path,
            "ethernet_ports": self.ethernet_ports,
            "fibre_ports": self.fibre_ports,
            "inputs": self.inputs,
            "status": self.status,
            "capabilities": self.capabilities,
            "last_seen": self.last_seen,
            "last_error": self.last_error,
        }


class Device:
    """One processor, with its connection and cached state."""

    def __init__(self, address: str, timeout: float = 2.0, **ports: int) -> None:
        self.address = address
        self.timeout = timeout
        self._ports = ports
        self._processor: Processor | None = None
        self._lock = threading.RLock()
        self._backoff = FIRST_BACKOFF
        self.state = DeviceState(address=address)

    # --- connection ---------------------------------------------------------

    def _connect(self) -> Processor | None:
        """Open a session, or record why not. Never raises."""
        try:
            processor = Processor.connect(self.address, timeout=self.timeout, **self._ports)
        except ConnectionError as exc:
            self._mark_down(Reachability.UNREACHABLE, str(exc))
            return None
        except OSError as exc:
            # A refused control port on a device that is otherwise up is the
            # signature of NovaLCT already holding the session.
            self._mark_down(Reachability.IN_USE, str(exc))
            return None
        self._processor = processor
        self._backoff = FIRST_BACKOFF
        return processor

    def _mark_down(self, reachability: Reachability, error: str) -> None:
        self.state.reachability = reachability.value
        self.state.last_error = error
        self.state.next_retry = time.time() + self._backoff
        self._backoff = min(self._backoff * 2, MAX_BACKOFF)
        self._close_processor()

    def _close_processor(self) -> None:
        if self._processor is not None:
            try:
                self._processor.close()
            except OSError:
                pass
            self._processor = None

    def close(self) -> None:
        with self._lock:
            self._close_processor()

    @property
    def due_for_retry(self) -> bool:
        return self.state.next_retry is None or time.time() >= self.state.next_retry

    # --- refresh ------------------------------------------------------------

    def refresh(self, force: bool = False) -> DeviceState:
        """Re-read what can be read. Never raises; failures become state."""
        with self._lock:
            if not force and self.state.reachability != Reachability.ONLINE.value:
                if not self.due_for_retry:
                    return self.state
            processor = self._processor or self._connect()
            if processor is None:
                return self.state

            try:
                self._read_into_state(processor)
            except (OSError, ValueError) as exc:
                self._mark_down(Reachability.UNREACHABLE, str(exc))
            return self.state

    def _read_into_state(self, processor: Processor) -> None:
        profile: DeviceProfile = processor.profile
        state = self.state
        state.reachability = Reachability.ONLINE.value
        state.last_error = None
        state.next_retry = None
        state.last_seen = time.time()
        state.model = profile.name
        state.family = profile.family.value
        state.control_path = "http" if processor.uses_http else "register-bus"
        state.ethernet_ports = profile.port_count
        state.fibre_ports = profile.fibre_ports
        if processor.identification is not None:
            state.serial = processor.identification.serial or state.serial
            state.name = processor.identification.device_name or state.name

        state.inputs = [
            {
                "label": entry.label,
                "type": entry.type,
                "switchable": entry.switchable,
                "connected": entry.connected,
                "notes": entry.notes,
            }
            for entry in processor.inputs()
        ]
        state.capabilities = {
            "select_input": any(entry["switchable"] for entry in state.inputs),
            "display_mode": True,
            "brightness": True,
            "presets": profile.presets or processor.uses_http,
            "panel_lock": profile.panel_lock_register is not None,
            "monitoring": True,
            "test_pattern": not processor.uses_http,
        }
        state.status = self._read_status(processor)

    def _read_status(self, processor: Processor) -> dict[str, Any]:
        status: dict[str, Any] = {}
        try:
            monitoring = processor.monitoring()
        except (NotSupported, ValueError, OSError):
            return status
        if hasattr(monitoring, "temperature_c"):
            status["temperature_c"] = monitoring.temperature_c
            status["voltage_v"] = monitoring.voltage_v
            status["humidity_percent"] = monitoring.humidity_percent
        elif isinstance(monitoring, dict):
            cabinets = monitoring.get("cabinets") or []
            temperatures = [
                c.get("temperature") for c in cabinets if isinstance(c, dict) and c.get("temperature")
            ]
            status["cabinets_total"] = len(cabinets)
            status["cabinets_online"] = len(
                [c for c in cabinets if isinstance(c, dict) and c.get("online")]
            )
            if temperatures:
                status["temperature_c"] = max(temperatures)
        return status

    # --- control ------------------------------------------------------------

    def execute(self, action: str, **arguments: Any) -> ActionRecord:
        """Run a named control action. Errors are recorded, not raised."""
        record = ActionRecord(
            timestamp=time.time(),
            address=self.address,
            action=action,
            detail=", ".join(f"{k}={v}" for k, v in arguments.items()),
        )
        with self._lock:
            processor = self._processor or self._connect()
            if processor is None:
                record.ok = False
                record.error = self.state.last_error or "not connected"
                return record
            try:
                self._dispatch(processor, action, arguments)
            except (CapabilityUnknown, NotSupported, ValueError) as exc:
                record.ok = False
                record.error = str(exc)
            except OSError as exc:
                record.ok = False
                record.error = str(exc)
                self._mark_down(Reachability.UNREACHABLE, str(exc))
            else:
                # Reflect the change straight away rather than waiting for a tick.
                try:
                    self._read_into_state(processor)
                except (OSError, ValueError):
                    pass
        return record

    def _dispatch(self, processor: Processor, action: str, arguments: dict[str, Any]) -> None:
        if action == "brightness":
            processor.set_brightness(float(arguments["percent"]))
        elif action == "select_input":
            processor.select_input(str(arguments["label"]))
        elif action == "display_mode":
            processor.set_display_mode(str(arguments["mode"]))
        elif action == "blackout":
            processor.blackout(bool(arguments.get("enabled", True)))
        elif action == "freeze":
            processor.freeze(bool(arguments.get("enabled", True)))
        elif action == "test_pattern":
            processor.set_test_pattern(str(arguments["pattern"]))
        elif action == "panel_lock":
            processor.set_panel_lock(bool(arguments["locked"]))
        elif action == "apply_preset":
            processor.apply_preset(arguments["identifier"])
        else:
            raise ValueError(f"unknown action {action!r}")


class Application:
    """The application's model: several devices, refreshed in the background."""

    def __init__(self, refresh_interval: float = 10.0, timeout: float = 2.0) -> None:
        self.refresh_interval = refresh_interval
        self.timeout = timeout
        self.devices: dict[str, Device] = {}
        self.history: list[ActionRecord] = []
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.listeners: list[Callable[[], None]] = []

    # --- membership ---------------------------------------------------------

    def add(self, address: str, **ports: int) -> Device:
        """Add a device, or return the existing one for that address.

        The address is the identity: one processor per address is the real-world
        case. Re-adding the same address with *different* ports replaces the
        entry rather than silently keeping the old ports, which would otherwise
        leave the caller talking to somewhere they did not ask for.
        """
        with self._lock:
            device = self.devices.get(address)
            if device is not None and device._ports != ports:
                device.close()
                device = None
            if device is None:
                device = Device(address, timeout=self.timeout, **ports)
                self.devices[address] = device
        device.refresh(force=True)
        self._notify()
        return device

    def remove(self, address: str) -> bool:
        with self._lock:
            device = self.devices.pop(address, None)
        if device is None:
            return False
        device.close()
        self._notify()
        return True

    def discover(self, timeout: float = 1.5) -> list[str]:
        """Broadcast for devices and add anything new."""
        from ..discovery import discover as _discover

        found = [entry.address for entry in _discover(timeout=timeout)]
        for address in found:
            if address not in self.devices:
                self.add(address)
        return found

    def get(self, address: str) -> Device | None:
        return self.devices.get(address)

    # --- actions ------------------------------------------------------------

    def execute(self, address: str, action: str, **arguments: Any) -> ActionRecord:
        device = self.devices.get(address)
        if device is None:
            record = ActionRecord(
                timestamp=time.time(),
                address=address,
                action=action,
                ok=False,
                error="no such device",
            )
        else:
            record = device.execute(action, **arguments)
        with self._lock:
            self.history.append(record)
            del self.history[:-200]
        self._notify()
        return record

    # --- refresh loop -------------------------------------------------------

    def refresh_all(self) -> None:
        for device in list(self.devices.values()):
            device.refresh()
        self._notify()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2)
        for device in self.devices.values():
            device.close()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.refresh_all()
            self._stop.wait(self.refresh_interval)

    def _notify(self) -> None:
        for listener in list(self.listeners):
            try:
                listener()
            except Exception:  # noqa: BLE001 - a bad listener must not stop the app
                pass

    # --- rendering ----------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            devices = [device.state.to_dict() for device in self.devices.values()]
            history = [record.to_dict() for record in self.history[-25:]]
        return {
            "timestamp": time.time(),
            "refresh_interval": self.refresh_interval,
            "devices": sorted(devices, key=lambda entry: entry["address"]),
            "history": list(reversed(history)),
            "destructive_actions": sorted(DESTRUCTIVE),
        }

    def __enter__(self) -> "Application":
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()


__all__ = [
    "Application",
    "Device",
    "DeviceState",
    "ActionRecord",
    "Reachability",
    "DESTRUCTIVE",
    "DisplayMode",
    "TestPattern",
    "unknown_profile",
    "identify",
]
