"""A read-only view of every NovaStar processor on a network.

Discovery, identification and status in one pass, producing a stable serialised
shape. This is the first thing a UI needs and the whole of what a monitoring
pane needs, so it is deliberately a data structure rather than a rendering.

The output is honest about coverage rather than uniform. A COEX controller
yields cabinets, temperatures and signal state; a VX4S yields identity and
little else, because no read-only interface exists for it (see
``docs/read-only-monitoring.md``). ``DeviceSurvey.monitoring_available`` says
which case each device is, so a consumer can show "not available" rather than
"zero".

Transmission policy is explicit and per-call:

* ``allow_probe=False`` sends nothing at all. Devices come only from ``hosts``.
* ``allow_probe=True`` (default) sends the UDP discovery broadcast, which
  carries no register address and no write bit -- the same probe NovaLCT emits
  routinely.
* ``allow_register_bus`` opens a TCP control session on 5200 when no HTTP API
  answers. Off by default: that session may be exclusive, and taking it from
  NovaLCT mid-show is exactly what a monitoring tool must not do.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .coex import DEFAULT_PORT as COEX_PORT
from .devices import DeviceProfile, Family, Identification, coex_profile_for, unknown_profile
from .discovery import discover
from .monitor import CoexMonitor, MonitorSnapshot
from .transport import TCP_PORT

SCHEMA_VERSION = 1
"""Bump when the serialised shape changes incompatibly.

Consumers should check this and refuse a version they do not understand rather
than silently mis-reading fields.
"""


@dataclass
class DeviceSurvey:
    """One device, as far as read-only access can describe it."""

    address: str
    reachable: bool = False
    family: str = Family.UNKNOWN.value
    model: str | None = None
    model_id: int | None = None
    name: str | None = None
    serial: str | None = None
    control_path: str | None = None
    ethernet_ports: int | None = None
    fibre_ports: int = 0
    inputs: list[dict[str, Any]] = field(default_factory=list)
    monitoring_available: str = "none"
    """``"http"``, ``"register-bus"``, ``"snmp-if-enabled"`` or ``"none"``."""
    status: dict[str, Any] | None = None
    discovered_by: str = "supplied"
    """``"discovery"`` if the device answered a probe, ``"supplied"`` if given."""
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary(self) -> str:
        head = f"{self.address:<15} {self.model or 'unknown':<18} {self.family}"
        if not self.reachable:
            return head + "  (unreachable)"
        parts = [head]
        if self.ethernet_ports is not None:
            ports = f"{self.ethernet_ports}x eth"
            if self.fibre_ports:
                ports += f" + {self.fibre_ports}x fibre"
            parts.append(f"  outputs: {ports}")
        if self.status:
            cabinets = self.status.get("cabinets_online")
            total = self.status.get("cabinets_total")
            if total:
                parts.append(f"  cabinets: {cabinets}/{total} online")
            if self.status.get("display_mode") is not None:
                parts.append(f"  display: {self.status['display_mode']}")
            signal = self.status.get("signal_present")
            if signal is not None:
                parts.append(f"  signal: {', '.join(signal) or 'none'}")
        elif self.monitoring_available == "none":
            parts.append("  no read-only monitoring interface on this model")
        for message in self.errors:
            parts.append(f"  ! {message}")
        return "\n".join(parts)


@dataclass
class Survey:
    """Everything found in one pass."""

    schema_version: int = SCHEMA_VERSION
    timestamp: float = field(default_factory=time.time)
    devices: list[DeviceSurvey] = field(default_factory=list)
    probed: bool = True
    """False when the survey transmitted nothing."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "timestamp": self.timestamp,
            "probed": self.probed,
            "devices": [device.to_dict() for device in self.devices],
        }

    @property
    def reachable(self) -> list[DeviceSurvey]:
        return [device for device in self.devices if device.reachable]

    def summary(self) -> str:
        if not self.devices:
            return "no devices found"
        lines = [f"{len(self.reachable)}/{len(self.devices)} device(s) reachable"]
        lines += [device.summary() for device in self.devices]
        return "\n".join(lines)


def _profile_fields(survey: DeviceSurvey, profile: DeviceProfile) -> None:
    survey.family = profile.family.value
    survey.model = profile.name if profile.is_known else survey.model
    survey.model_id = profile.model_id
    survey.ethernet_ports = profile.port_count
    survey.fibre_ports = profile.fibre_ports
    survey.inputs = [
        {
            "label": connector.label,
            "type": connector.type.value,
            "switchable": connector.switchable,
        }
        for connector in profile.inputs
    ]


def _status_from(snapshot: MonitorSnapshot) -> dict[str, Any]:
    """Flatten a monitor snapshot into the survey's stable shape."""
    hottest = snapshot.hottest
    return {
        "display_mode": snapshot.display_mode,
        "cabinets_total": len(snapshot.cabinets),
        "cabinets_online": len([c for c in snapshot.cabinets if c.online]),
        "cabinets_offline": [str(c.identifier) for c in snapshot.offline_cabinets],
        "hottest_cabinet": (
            {"id": str(hottest.identifier), "temperature": hottest.temperature}
            if hottest
            else None
        ),
        "signal_present": snapshot.signal_present,
        "screens": len(snapshot.screens),
        "healthy": snapshot.healthy,
    }


def survey_device(
    address: str,
    timeout: float = 2.0,
    allow_register_bus: bool = False,
    http_port: int = COEX_PORT,
    control_port: int = TCP_PORT,
    read_status: bool = True,
) -> DeviceSurvey:
    """Describe one device using only reads."""
    result = DeviceSurvey(address=address)

    # COEX first: read-only, stateless, and definitive for MX-class hardware.
    try:
        with CoexMonitor(address, http_port, timeout=timeout) as monitor:
            snapshot = monitor.poll(include_slow=True)
        if snapshot.model or snapshot.cabinets or not snapshot.errors:
            result.reachable = True
            result.control_path = "http"
            result.monitoring_available = "http"
            result.model = snapshot.model
            result.name = snapshot.device_name
            result.serial = snapshot.serial
            _profile_fields(result, coex_profile_for(snapshot.model))
            result.model = snapshot.model or result.model
            if read_status:
                result.status = _status_from(snapshot)
            result.errors = [f"{name}: {msg}" for name, msg in snapshot.errors.items()]
            return result
    except (OSError, ValueError):
        pass

    if not allow_register_bus:
        result.errors.append(
            "no HTTP API; a register-bus probe was not attempted "
            "(allow_register_bus=False)"
        )
        result.monitoring_available = "none"
        return result

    # Fallback: identify over the register bus. This opens a control session.
    from .devices import identify

    identification: Identification = identify(
        address, timeout=timeout, http_port=http_port, control_port=control_port
    )
    if not identification.reachable_register_bus:
        result.errors.append("did not answer on the register bus either")
        return result

    result.reachable = True
    result.control_path = "register-bus"
    result.serial = identification.serial or None
    result.name = identification.device_name
    _profile_fields(result, identification.profile)
    result.model = identification.profile.name
    # These models publish no read-only interface; SNMP is COEX-only.
    result.monitoring_available = "register-bus"
    return result


def survey_network(
    hosts: list[str] | None = None,
    timeout: float = 2.0,
    allow_probe: bool = True,
    allow_register_bus: bool = False,
    read_status: bool = True,
) -> Survey:
    """Find and describe the processors on this network, read-only.

    With ``allow_probe=False`` and an explicit ``hosts`` list, nothing is
    broadcast; each host is still contacted over HTTP unless
    ``read_status=False``. For a survey that transmits absolutely nothing, use
    :mod:`novasun.passive` instead — it can only report what it overhears.
    """
    result = Survey(probed=allow_probe)
    addresses: dict[str, str] = {host: "supplied" for host in (hosts or [])}

    if allow_probe:
        for found in discover(timeout=min(timeout, 2.0)):
            addresses.setdefault(found.address, "discovery")

    for address, origin in addresses.items():
        device = survey_device(
            address,
            timeout=timeout,
            allow_register_bus=allow_register_bus,
            read_status=read_status,
        )
        device.discovered_by = origin
        result.devices.append(device)
    return result
