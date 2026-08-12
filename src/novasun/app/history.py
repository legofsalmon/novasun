"""Monitoring history and alerts.

Every reading before this was instantaneous: you could see that a cabinet is
offline, never that it *went* offline at 19:42, and nothing told you unless you
were looking at the right pane. Both of those matter more than the live value.

Two structures:

* **Series** -- bounded ring buffers of readings per device, so a temperature
  can be shown as a trend and a drop-out has a timestamp.
* **Alerts** -- rules evaluated on each refresh, raising and clearing conditions.

The engineering that matters is in not crying wolf, because an alerting system
that fires spuriously gets ignored during exactly the show it was meant to help:

* **Dwell.** A device must miss several consecutive refreshes before it is
  called offline. One dropped poll on a busy network is not an outage.
* **Hysteresis.** A temperature alert clears at a *lower* value than it fires,
  so a reading sitting on the threshold does not flap.
* **Acknowledgement.** An operator can silence an alert without dismissing it;
  it stays visible until the underlying condition actually clears.
* **Raised and cleared are both events.** "Came back at 19:44" is as useful as
  the failure, and without it a log of alerts reads as permanently on fire.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Iterable

DEFAULT_SAMPLES = 720
"""Two hours at a ten-second refresh. Bounded so a long run cannot grow forever."""

DEFAULT_EVENTS = 500


class Severity:
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


_ORDER = {Severity.INFO: 0, Severity.WARNING: 1, Severity.CRITICAL: 2}


@dataclass
class Sample:
    timestamp: float
    value: float

    def to_dict(self) -> dict[str, float]:
        return {"t": round(self.timestamp, 3), "v": self.value}


@dataclass
class Series:
    """A bounded time series for one metric."""

    name: str
    maxlen: int = DEFAULT_SAMPLES
    samples: Deque[Sample] = field(default_factory=deque)

    def __post_init__(self) -> None:
        self.samples = deque(self.samples, maxlen=self.maxlen)

    def add(self, value: float, timestamp: float | None = None) -> None:
        self.samples.append(Sample(timestamp or time.time(), float(value)))

    @property
    def latest(self) -> float | None:
        return self.samples[-1].value if self.samples else None

    def since(self, seconds: float) -> list[Sample]:
        cutoff = time.time() - seconds
        return [sample for sample in self.samples if sample.timestamp >= cutoff]

    def summary(self, window: float = 3600.0) -> dict[str, Any]:
        window_samples = self.since(window) or list(self.samples)
        if not window_samples:
            return {"name": self.name, "count": 0}
        values = [sample.value for sample in window_samples]
        first, last = values[0], values[-1]
        return {
            "name": self.name,
            "count": len(values),
            "latest": last,
            "min": min(values),
            "max": max(values),
            "mean": round(sum(values) / len(values), 2),
            # Direction over the window, which is what "climbing" means to an
            # operator -- not an instantaneous derivative.
            "trend": round(last - first, 2),
        }

    def to_dict(self, window: float = 3600.0) -> dict[str, Any]:
        return {
            "name": self.name,
            "samples": [sample.to_dict() for sample in self.since(window)],
        }


@dataclass
class Event:
    """Something that happened, with a time. Append-only."""

    timestamp: float
    address: str
    kind: str
    severity: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "address": self.address,
            "kind": self.kind,
            "severity": self.severity,
            "message": self.message,
        }


@dataclass
class Alert:
    """A condition currently true of a device."""

    key: str
    address: str
    kind: str
    severity: str
    message: str
    since: float
    value: Any = None
    acknowledged: bool = False

    @property
    def age(self) -> float:
        return time.time() - self.since

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "address": self.address,
            "kind": self.kind,
            "severity": self.severity,
            "message": self.message,
            "since": self.since,
            "age": round(self.age, 1),
            "value": self.value,
            "acknowledged": self.acknowledged,
        }


@dataclass
class Thresholds:
    """When to complain. Persisted, so a venue can tune them once."""

    temperature_warning: float = 45.0
    temperature_critical: float = 60.0
    temperature_clear: float = 42.0
    """Below this, a temperature alert clears. Deliberately under the warning
    level: equal thresholds make a reading sitting on the line flap."""
    offline_ticks: int = 2
    """Consecutive failed refreshes before a device counts as offline."""
    cabinet_loss_alerts: bool = True
    temperature_alerts: bool = True

    def validate(self) -> None:
        if self.temperature_clear >= self.temperature_warning:
            raise ValueError(
                "temperature_clear must be below temperature_warning, or alerts flap"
            )
        if self.temperature_warning >= self.temperature_critical:
            raise ValueError("temperature_warning must be below temperature_critical")
        if self.offline_ticks < 1:
            raise ValueError("offline_ticks must be at least 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "temperature_warning": self.temperature_warning,
            "temperature_critical": self.temperature_critical,
            "temperature_clear": self.temperature_clear,
            "offline_ticks": self.offline_ticks,
            "cabinet_loss_alerts": self.cabinet_loss_alerts,
            "temperature_alerts": self.temperature_alerts,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Thresholds":
        return cls(
            temperature_warning=float(raw.get("temperature_warning", 45.0)),
            temperature_critical=float(raw.get("temperature_critical", 60.0)),
            temperature_clear=float(raw.get("temperature_clear", 42.0)),
            offline_ticks=int(raw.get("offline_ticks", 2)),
            cabinet_loss_alerts=bool(raw.get("cabinet_loss_alerts", True)),
            temperature_alerts=bool(raw.get("temperature_alerts", True)),
        )


@dataclass
class DeviceHistory:
    """Per-device series and the counters the rules need."""

    address: str
    maxlen: int = DEFAULT_SAMPLES
    series: dict[str, Series] = field(default_factory=dict)
    consecutive_misses: int = 0
    last_reachability: str | None = None
    peak_cabinets: int = 0
    """High-water mark. A screen that had 8 cabinets and now reports 6 has lost
    two, even though the controller only ever reports what it can currently see."""

    def record(self, name: str, value: float, timestamp: float | None = None) -> None:
        series = self.series.get(name)
        if series is None:
            series = Series(name, maxlen=self.maxlen)
            self.series[name] = series
        series.add(value, timestamp)

    def summary(self, window: float = 3600.0) -> dict[str, Any]:
        return {name: series.summary(window) for name, series in self.series.items()}


class AlertEngine:
    """Turns a stream of device states into events and current alerts."""

    def __init__(
        self,
        thresholds: Thresholds | None = None,
        max_events: int = DEFAULT_EVENTS,
        samples: int = DEFAULT_SAMPLES,
    ) -> None:
        self.thresholds = thresholds or Thresholds()
        self.histories: dict[str, DeviceHistory] = {}
        self.alerts: dict[str, Alert] = {}
        self.events: Deque[Event] = deque(maxlen=max_events)
        self.samples = samples

    # --- ingestion ----------------------------------------------------------

    def observe(self, state: dict[str, Any], now: float | None = None) -> list[Event]:
        """Take one device state and update history and alerts."""
        now = now or time.time()
        address = state["address"]
        history = self.histories.get(address)
        if history is None:
            history = DeviceHistory(address, maxlen=self.samples)
            self.histories[address] = history

        raised: list[Event] = []
        reachability = state.get("reachability", "unknown")
        status = state.get("status") or {}

        raised += self._reachability(history, address, reachability, now)
        if reachability == "online":
            history.consecutive_misses = 0
            temperature = status.get("temperature_c")
            if isinstance(temperature, (int, float)):
                history.record("temperature_c", float(temperature), now)
                raised += self._temperature(address, float(temperature), now)
            total = status.get("cabinets_total")
            online = status.get("cabinets_online")
            if isinstance(total, int) and isinstance(online, int) and total:
                history.record("cabinets_online", online, now)
                raised += self._cabinets(history, address, online, total, now)
            brightness = status.get("brightness")
            if isinstance(brightness, (int, float)):
                history.record("brightness", float(brightness), now)

        history.last_reachability = reachability
        return raised

    def observe_all(self, states: Iterable[dict[str, Any]]) -> list[Event]:
        now = time.time()
        raised: list[Event] = []
        for state in states:
            raised += self.observe(state, now)
        return raised

    # --- rules --------------------------------------------------------------

    def _reachability(
        self, history: DeviceHistory, address: str, reachability: str, now: float
    ) -> list[Event]:
        if reachability == "online":
            history.record("online", 1.0, now)
            return self._clear(f"{address}:offline", address, "came back online", now)

        history.record("online", 0.0, now)
        history.consecutive_misses += 1
        if history.consecutive_misses < self.thresholds.offline_ticks:
            # Not yet: one dropped poll on a busy network is not an outage.
            return []
        severity = Severity.WARNING if reachability == "in-use" else Severity.CRITICAL
        message = (
            "control session refused (NovaLCT or VMP is probably connected)"
            if reachability == "in-use"
            else f"unreachable for {history.consecutive_misses} checks"
        )
        return self._raise(
            f"{address}:offline", address, "offline", severity, message, now,
            value=reachability,
        )

    def _temperature(self, address: str, value: float, now: float) -> list[Event]:
        if not self.thresholds.temperature_alerts:
            return []
        key = f"{address}:temperature"
        if value >= self.thresholds.temperature_critical:
            return self._raise(
                key, address, "temperature", Severity.CRITICAL,
                f"{value:g} C, at or above the critical threshold "
                f"({self.thresholds.temperature_critical:g} C)", now, value=value,
            )
        if value >= self.thresholds.temperature_warning:
            return self._raise(
                key, address, "temperature", Severity.WARNING,
                f"{value:g} C, above the warning threshold "
                f"({self.thresholds.temperature_warning:g} C)", now, value=value,
            )
        if value <= self.thresholds.temperature_clear:
            return self._clear(key, address, f"temperature back to {value:g} C", now)
        # Between clear and warning: hold whatever state we are in rather than
        # clearing, which is what stops a reading on the line from flapping.
        return []

    def _cabinets(
        self, history: DeviceHistory, address: str, online: int, total: int, now: float
    ) -> list[Event]:
        if not self.thresholds.cabinet_loss_alerts:
            return []
        history.peak_cabinets = max(history.peak_cabinets, total, online)
        key = f"{address}:cabinets"
        missing = total - online
        if missing > 0:
            return self._raise(
                key, address, "cabinets", Severity.CRITICAL,
                f"{missing} of {total} cabinet(s) offline", now, value=missing,
            )
        return self._clear(key, address, f"all {total} cabinets online", now)

    # --- alert bookkeeping --------------------------------------------------

    def _raise(
        self,
        key: str,
        address: str,
        kind: str,
        severity: str,
        message: str,
        now: float,
        value: Any = None,
    ) -> list[Event]:
        existing = self.alerts.get(key)
        if existing is not None:
            escalated = _ORDER[severity] > _ORDER[existing.severity]
            existing.message = message
            existing.value = value
            if escalated:
                existing.severity = severity
                # An escalation is worth announcing, and un-acknowledging: the
                # operator agreed to ignore a warning, not a critical.
                existing.acknowledged = False
                event = Event(now, address, kind, severity, f"escalated: {message}")
                self.events.append(event)
                return [event]
            return []
        alert = Alert(
            key=key, address=address, kind=kind, severity=severity,
            message=message, since=now, value=value,
        )
        self.alerts[key] = alert
        event = Event(now, address, kind, severity, message)
        self.events.append(event)
        return [event]

    def _clear(self, key: str, address: str, message: str, now: float) -> list[Event]:
        alert = self.alerts.pop(key, None)
        if alert is None:
            return []
        duration = now - alert.since
        event = Event(
            now, address, alert.kind, Severity.INFO,
            f"{message} (after {_duration(duration)})",
        )
        self.events.append(event)
        return [event]

    def forget(self, address: str) -> None:
        """Drop a removed device's history and alerts."""
        self.histories.pop(address, None)
        for key in [k for k in self.alerts if k.startswith(f"{address}:")]:
            del self.alerts[key]

    def acknowledge(self, key: str) -> bool:
        alert = self.alerts.get(key)
        if alert is None:
            return False
        alert.acknowledged = True
        return True

    # --- rendering ----------------------------------------------------------

    @property
    def worst_severity(self) -> str | None:
        unacknowledged = [a for a in self.alerts.values() if not a.acknowledged]
        if not unacknowledged:
            return None
        return max(unacknowledged, key=lambda a: _ORDER[a.severity]).severity

    def active(self, address: str | None = None) -> list[Alert]:
        alerts = [
            alert
            for alert in self.alerts.values()
            if address is None or alert.address == address
        ]
        return sorted(alerts, key=lambda a: (-_ORDER[a.severity], a.since))

    def recent_events(self, limit: int = 50) -> list[Event]:
        return list(self.events)[-limit:][::-1]

    def to_dict(self, window: float = 3600.0, event_limit: int = 50) -> dict[str, Any]:
        return {
            "alerts": [alert.to_dict() for alert in self.active()],
            "events": [event.to_dict() for event in self.recent_events(event_limit)],
            "worst_severity": self.worst_severity,
            "thresholds": self.thresholds.to_dict(),
            "metrics": {
                address: history.summary(window)
                for address, history in self.histories.items()
            },
        }


def _duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
