"""Model identification and per-model capabilities.

Three families matter for Ethernet control, and they do not behave alike:

* **COEX** (MX series, CX, KU) -- an official JSON API on port 8001 is the
  primary interface; the register bus is the compatibility path. These do not
  appear in NovaLCT's model table at all, so they are identified by probing
  HTTP rather than by model ID.
* **Video processors** (VX4S, NovaPro UHD Jr, MCTRL4K, VX1000 ...) -- register
  bus on TCP 5200, with input switching and processor-specific registers.
* **Sending cards** (MCTRL660 Pro, MSD/MCTRL series) -- register bus, no video
  processing.

Model IDs come from a 2-byte read of register 0x00000002. The values below were
taken from the ``NSCardType`` enum generated from decompiled NovaLCT assemblies,
and port counts from its ``GetPortNumber``. One of them -- MCTRL660 Pro,
``0x1107`` -- also appears in an official NovaStar document, which agrees, so
the table has at least one independent check against the vendor's own bytes.
Everything else here is unverified until you point it at hardware; see
``PROVENANCE``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .transport import TCP_PORT, VX_PRO_TCP_PORT


class Family(str, Enum):
    COEX = "coex"
    VIDEO_PROCESSOR = "video-processor"
    SENDING_CARD = "sending-card"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DeviceProfile:
    """What a model is and how to talk to it."""

    name: str
    family: Family
    model_id: int | None = None
    port_count: int = 2
    control_port: int = TCP_PORT
    http_api: bool = False
    """Serves the COEX JSON API on port 8001."""
    input_select: bool = False
    """Has a switchable input, i.e. the DVI_SELECT register means something."""
    presets: bool = False
    """Supports preset recall (COEX register 0x0A000002 or the HTTP API)."""
    notes: str = ""

    @property
    def is_known(self) -> bool:
        return self.family is not Family.UNKNOWN


# Deliberately not the full 280-entry table: these are the models reachable over
# Ethernet that are worth naming. Anything else falls back to `unknown_profile`,
# which still works -- the register bus does not require us to know the model.
MODELS: dict[int, DeviceProfile] = {
    # --- video processors ---------------------------------------------------
    0x6107: DeviceProfile("VX4S", Family.VIDEO_PROCESSOR, 0x6107, 4, input_select=True),
    0x612A: DeviceProfile("VX4S-N", Family.VIDEO_PROCESSOR, 0x612A, 4, input_select=True),
    0x6205: DeviceProfile(
        "NovaPro UHD Jr",
        Family.VIDEO_PROCESSOR,
        0x6205,
        16,
        input_select=True,
        notes="4K all-in-one; 16 output ports; also drivable from V-Can",
    ),
    0x7504: DeviceProfile("NovaPro UHD", Family.VIDEO_PROCESSOR, 0x7504, 16, input_select=True),
    0x6101: DeviceProfile("NovaPro HD", Family.VIDEO_PROCESSOR, 0x6101, 4, input_select=True),
    0x6121: DeviceProfile("NovaPro HD II", Family.VIDEO_PROCESSOR, 0x6121, 8, input_select=True),
    0x1103: DeviceProfile("MCTRL4K", Family.VIDEO_PROCESSOR, 0x1103, 16, input_select=True),
    0x1105: DeviceProfile("MCTRL1600", Family.VIDEO_PROCESSOR, 0x1105, 16),
    0x620C: DeviceProfile("VX1000", Family.VIDEO_PROCESSOR, 0x620C, 10, input_select=True),
    0x622B: DeviceProfile(
        "VX1000 Pro",
        Family.VIDEO_PROCESSOR,
        0x622B,
        10,
        control_port=VX_PRO_TCP_PORT,
        input_select=True,
        notes="VX Pro series listens on 15200, not 5200",
    ),
    0x6109: DeviceProfile("VX5", Family.VIDEO_PROCESSOR, 0x6109, 4, input_select=True),
    0x6106: DeviceProfile("VX4", Family.VIDEO_PROCESSOR, 0x6106, 4, input_select=True),
    0x6105: DeviceProfile("VX2", Family.VIDEO_PROCESSOR, 0x6105, 2, input_select=True),
    # --- sending cards ------------------------------------------------------
    0x1107: DeviceProfile(
        "MCTRL660 Pro",
        Family.SENDING_CARD,
        0x1107,
        6,
        input_select=True,
        notes="model ID confirmed by NovaStar's own protocol document",
    ),
    0x1108: DeviceProfile("MCTRL660 ROE", Family.SENDING_CARD, 0x1108, 4),
    0x1104: DeviceProfile("MCTRL R5", Family.SENDING_CARD, 0x1104, 8),
    0x1102: DeviceProfile("E500", Family.SENDING_CARD, 0x1102, 4),
    0x0001: DeviceProfile("Sending card", Family.SENDING_CARD, 0x0001, 2),
    0x0101: DeviceProfile("Controller", Family.SENDING_CARD, 0x0101, 4),
}

# COEX controllers are identified by the HTTP API, not by model ID: they post-
# date NovaLCT's table and are managed by VMP. Names are matched against what
# /api/v1/device reports.
COEX_MODELS: dict[str, DeviceProfile] = {
    name.lower(): DeviceProfile(
        name, Family.COEX, None, ports, http_api=True, input_select=True, presets=True
    )
    for name, ports in {
        "MX40 Pro": 4,
        "MX30": 2,
        "MX20": 2,
        "MX2000 Pro": 20,
        "MX6000 Pro": 20,
        "CX40 Pro": 4,
        "CX80 Pro": 8,
        "KU20": 2,
    }.items()
}

PROVENANCE = {
    0x1107: "official (MCTRL 660 Pro protocol document) + decompiled NSCardType",
    "others": "decompiled NSCardType / GetPortNumber -- unverified on hardware",
    "coex": "product documentation; identified by HTTP probe, not by model ID",
}


def unknown_profile(model_id: int | None = None) -> DeviceProfile:
    """A usable profile for a model we have no entry for.

    Not knowing the model is not an error: the register bus works regardless,
    and a conservative two-port assumption only limits enumeration breadth.
    """
    label = f"unknown (0x{model_id:04x})" if model_id is not None else "unknown"
    return DeviceProfile(label, Family.UNKNOWN, model_id, port_count=2)


def profile_for(model_id: int) -> DeviceProfile:
    return MODELS.get(model_id) or unknown_profile(model_id)


def coex_profile_for(name: str | None) -> DeviceProfile:
    """Match a name reported by the COEX HTTP API against the known models."""
    if name:
        lowered = name.strip().lower()
        for key, profile in COEX_MODELS.items():
            if key in lowered or lowered in key:
                return profile
    return DeviceProfile(
        name or "COEX controller",
        Family.COEX,
        None,
        port_count=4,
        http_api=True,
        input_select=True,
        presets=True,
    )


@dataclass
class Identification:
    """What is at an address, and which control path to use for it."""

    host: str
    profile: DeviceProfile
    reachable_http: bool = False
    reachable_register_bus: bool = False
    http_port: int = 8001
    register_bus_port: int = TCP_PORT
    serial: str = ""
    device_name: str | None = None
    details: dict = field(default_factory=dict)

    @property
    def preferred_path(self) -> str:
        """``"http"`` for COEX hardware, ``"register-bus"`` otherwise."""
        return "http" if (self.reachable_http and self.profile.http_api) else "register-bus"

    def summary(self) -> str:
        lines = [
            f"{self.host}",
            f"  model        {self.profile.name}"
            + (f"  (0x{self.profile.model_id:04x})" if self.profile.model_id else ""),
            f"  family       {self.profile.family.value}",
            f"  output ports {self.profile.port_count}",
            f"  control      {self.preferred_path}",
        ]
        if self.reachable_register_bus:
            lines.append(f"  register bus TCP {self.register_bus_port}")
        if self.reachable_http:
            lines.append(f"  http api     TCP {self.http_port}")
        if self.serial:
            lines.append(f"  serial       {self.serial}")
        if self.device_name:
            lines.append(f"  name         {self.device_name}")
        if self.profile.notes:
            lines.append(f"  note         {self.profile.notes}")
        return "\n".join(lines)


def identify(
    host: str,
    timeout: float = 2.0,
    http_port: int | None = None,
    control_port: int | None = None,
) -> Identification:
    """Work out what is at ``host`` and how to drive it.

    Tries the COEX HTTP API first: it is definitive for MX-class hardware and
    fails fast when the port is closed. Falls back to the register bus, which is
    everything else. Both are attempted, because a COEX controller answers on
    both and it is useful to know that.

    The port arguments exist for non-standard deployments and for testing; left
    unset, the documented ports are used.
    """
    from .client import Controller  # imported here to keep module import cheap
    from .coex import DEFAULT_PORT, CoexClient, CoexError

    identification = Identification(host=host, profile=unknown_profile())

    try:
        identification.http_port = http_port or DEFAULT_PORT
        client = CoexClient(host, identification.http_port, timeout=timeout)
        device = client.device_info()
        identification.reachable_http = True
        name = None
        if isinstance(device, dict):
            name = device.get("model") or device.get("name") or device.get("deviceName")
            identification.details = device
        identification.profile = coex_profile_for(name)
        identification.device_name = name
    except (CoexError, OSError, ValueError):
        pass

    for port in [control_port] if control_port else _candidate_ports(identification.profile):
        try:
            with Controller.connect(host, port, timeout=timeout) as controller:
                info = controller.probe()
                if info is None:
                    continue
                identification.reachable_register_bus = True
                identification.register_bus_port = port
                identification.serial = info.serial
                identification.device_name = identification.device_name or info.name
                if not identification.profile.is_known:
                    identification.profile = profile_for(info.model_id)
                break
        except OSError:
            continue

    return identification


def _candidate_ports(profile: DeviceProfile) -> list[int]:
    """5200 first, then the VX Pro port, unless the profile already knows."""
    if profile.is_known:
        return [profile.control_port]
    return [TCP_PORT, VX_PRO_TCP_PORT]
