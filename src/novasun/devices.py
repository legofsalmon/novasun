"""Model identification, per-model I/O, and capabilities.

Three families matter for Ethernet control, and they do not behave alike:

* **COEX** (MX series, CX, KU) -- an official JSON API on port 8001 is the
  primary interface; the register bus is the compatibility path. These do not
  appear in NovaLCT's model table at all, so they are identified by probing
  HTTP rather than by model ID, and their inputs are *enumerated at runtime*
  from the API rather than being known in advance.
* **Video processors** (VX4S, NovaPro UHD Jr, MCTRL4K, VX1000 ...) -- register
  bus on TCP 5200, with model-specific input switching.
* **Sending cards** (MCTRL660 Pro, MSD/MCTRL series) -- register bus, no video
  processing beyond input selection.

## Why input switching is modelled per device

It is not merely that the values differ. **The register differs too**, and the
meaning of a display-mode value differs, and both are verified against
NovaStar's own documents:

===================  ==============  =====================================
Family               Register        Values
===================  ==============  =====================================
Sending cards        ``0x02000023``  SDI 0x01, HDMI 0x05, DVI 0x58
VX4S                 ``0x0220002D``  DVI 0x10, HDMI 0xA0, VGA1 0x01, ...
NovaPro HD           ``0x02200022``  SDI 0x1A, DVI 0x1C, HDMI 0x1B, ...
COEX                 HTTP            source IDs read from the controller
===================  ==============  =====================================

Display mode is worse: on a VX4S, ``0x02200050`` takes 1 = freeze and
2 = blackout, while the COEX HTTP API takes 1 = blackout and 2 = freeze. Sending
the wrong one to a live screen blacks it out when you meant to freeze it. Nothing
about that is inferable at runtime, so it is data on the profile.

Everything here is sourced -- see ``PROVENANCE`` and ``docs/sources.md``. Model
IDs and port counts come from NovaLCT's decompiled tables; one entry (MCTRL660
Pro, ``0x1107``) also appears in a NovaStar document and agrees. Input registers
and values come from the per-model protocol documents, and every frame in them
was checksum-verified before being transcribed.
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


class ConnectorType(str, Enum):
    HDMI = "HDMI"
    DVI = "DVI"
    SDI = "SDI"
    DP = "DisplayPort"
    VGA = "VGA"
    CVBS = "CVBS"
    OPT = "Optical"
    RJ45 = "Ethernet"
    COMPOSITE_SOURCE = "Composite"
    """A source made of several physical inputs, e.g. the UHD Jr's DVI mosaic."""


@dataclass(frozen=True)
class InputConnector:
    """One selectable input on a processor.

    ``select_value`` is what gets written to the model's input register. It is
    ``None`` when the connector is known to exist but its code has not been
    established -- the application should show the input and refuse to switch to
    it, rather than guessing a value at a live screen.
    """

    type: ConnectorType
    label: str
    select_value: int | None = None
    notes: str = ""

    @property
    def switchable(self) -> bool:
        return self.select_value is not None


@dataclass(frozen=True)
class OutputConnector:
    """A non-Ethernet output: fibre, loop-through, monitor out."""

    type: ConnectorType
    label: str
    count: int = 1
    loop_through: bool = False


@dataclass(frozen=True)
class DisplayControl:
    """How a model implements normal / blackout / freeze.

    Two mechanisms exist and they are not interchangeable:

    * ``receiving_card`` -- broadcast writes to the kill (0x02000100) and lock
      (0x02000102) registers on every receiving card. Universal, works anywhere.
    * ``processor`` -- a single register on the processor itself, with a
      model-specific value for each mode. Faster, and the only way to blank a
      processor's output rather than its cards.
    """

    register: int | None = None
    normal: int = 0
    blackout: int = 1
    freeze: int = 2

    @property
    def is_processor_level(self) -> bool:
        return self.register is not None

    def value_for(self, mode: str) -> int:
        return {"normal": self.normal, "blackout": self.blackout, "freeze": self.freeze}[mode]


RECEIVING_CARD_DISPLAY = DisplayControl()
"""Sentinel: use the universal receiving-card kill/lock registers."""

# Input select registers, per family. Confirmed against NovaStar documents.
INPUT_REGISTER_SENDING_CARD = 0x0200_0023
INPUT_REGISTER_VX4S = 0x0220_002D
INPUT_REGISTER_NOVAPRO_HD = 0x0220_0022

# VX4S processor-level display and front-panel lock, from the VX4S document.
VX4S_DISPLAY_REGISTER = 0x0220_0050
VX4S_PANEL_LOCK_REGISTER = 0x0220_00F7


@dataclass(frozen=True)
class DeviceProfile:
    """What a model is, what it has, and how to talk to it."""

    name: str
    family: Family
    model_id: int | None = None
    port_count: int = 2
    """Ethernet (RJ45) output ports carrying receiving cards."""
    control_port: int = TCP_PORT
    http_api: bool = False
    inputs: tuple[InputConnector, ...] = ()
    """Empty for COEX, whose inputs are read from the controller at runtime."""
    outputs: tuple[OutputConnector, ...] = ()
    """Outputs other than the RJ45 ports: fibre, loop-through, monitor out."""
    input_register: int | None = None
    display: DisplayControl = RECEIVING_CARD_DISPLAY
    presets: bool = False
    panel_lock_register: int | None = None
    notes: str = ""

    @property
    def is_known(self) -> bool:
        return self.family is not Family.UNKNOWN

    @property
    def input_select(self) -> bool:
        """Whether switching inputs is possible on this model at all."""
        return bool(self.inputs) or self.http_api or self.input_register is not None

    @property
    def switchable_inputs(self) -> tuple[InputConnector, ...]:
        return tuple(connector for connector in self.inputs if connector.switchable)

    @property
    def fibre_ports(self) -> int:
        return sum(o.count for o in self.outputs if o.type is ConnectorType.OPT)

    def find_input(self, label: str) -> InputConnector | None:
        """Match an input by label or connector type, case-insensitively.

        ``"hdmi"`` finds ``HDMI 1`` when that is the only HDMI. An ambiguous
        bare type returns ``None`` rather than picking one.
        """
        wanted = label.strip().lower()
        for connector in self.inputs:
            if connector.label.lower() == wanted:
                return connector
        matches = [c for c in self.inputs if c.type.value.lower() == wanted]
        return matches[0] if len(matches) == 1 else None


def _numbered(kind: ConnectorType, values: dict[str, int | None], notes: str = "") -> tuple:
    return tuple(
        InputConnector(kind, label, value, notes) for label, value in values.items()
    )


#: VX4S / VX4S-N, from the VX4S Command Protocol document. Every frame in it
#: was checksum-verified before these values were transcribed.
VX4S_INPUTS: tuple[InputConnector, ...] = (
    InputConnector(ConnectorType.DVI, "DVI", 0x10),
    InputConnector(ConnectorType.HDMI, "HDMI", 0xA0),
    InputConnector(ConnectorType.VGA, "VGA 1", 0x01),
    InputConnector(ConnectorType.VGA, "VGA 2", 0x02),
    InputConnector(ConnectorType.CVBS, "CVBS 1", 0x71),
    InputConnector(ConnectorType.CVBS, "CVBS 2", 0x72),
    InputConnector(ConnectorType.SDI, "SDI", 0x40),
    InputConnector(ConnectorType.DP, "DP", 0x90),
)

#: NovaPro HD, from the PRO HD input-source document.
NOVAPRO_HD_INPUTS: tuple[InputConnector, ...] = (
    InputConnector(ConnectorType.SDI, "SDI", 0x1A),
    InputConnector(ConnectorType.DVI, "DVI", 0x1C),
    InputConnector(ConnectorType.HDMI, "HDMI", 0x1B),
    InputConnector(ConnectorType.VGA, "VGA", 0x17),
    InputConnector(ConnectorType.DP, "DP", 0x1E),
    InputConnector(ConnectorType.CVBS, "CVBS", 0x02),
)

#: MCTRL660 Pro, from its protocol document.
MCTRL660_PRO_INPUTS: tuple[InputConnector, ...] = (
    InputConnector(ConnectorType.SDI, "SDI", 0x01),
    InputConnector(ConnectorType.HDMI, "HDMI", 0x05),
    InputConnector(
        ConnectorType.DVI,
        "DVI",
        0x58,
        notes="0x58 is what the document prints; unusual next to 0x01/0x05",
    ),
)

#: NovaPro UHD Jr. Connector list from the product specification (1x DP 1.2,
#: 4x DVI, 1x HDMI 2.0 with loop-through, 2x 12G-SDI with loop, plus OPT inputs
#: in fibre-converter mode and a DVI mosaic composite source). No input-switching
#: protocol document was found for it, so the select codes are unknown: the
#: connectors are listed, and switching to them is refused rather than guessed.
UHD_JR_INPUTS: tuple[InputConnector, ...] = (
    InputConnector(ConnectorType.DP, "DP 1.2", None),
    InputConnector(ConnectorType.HDMI, "HDMI 2.0", None, notes="loop-through"),
    *_numbered(ConnectorType.DVI, {f"DVI {n}": None for n in range(1, 5)}),
    *_numbered(ConnectorType.SDI, {"SDI 1": None, "SDI 2": None}, "12G-SDI, with loop"),
    InputConnector(ConnectorType.OPT, "OPT 1", None, notes="fibre-converter mode"),
    InputConnector(ConnectorType.OPT, "OPT 2", None, notes="fibre-converter mode"),
    InputConnector(
        ConnectorType.COMPOSITE_SOURCE,
        "DVI MOSAIC",
        None,
        notes="up to 4 DVI inputs combined into one source",
    ),
)

UHD_JR_OUTPUTS: tuple[OutputConnector, ...] = (
    OutputConnector(ConnectorType.OPT, "Optical fibre", 4),
    OutputConnector(ConnectorType.HDMI, "HDMI loop", 1, loop_through=True),
    OutputConnector(ConnectorType.SDI, "SDI loop", 2, loop_through=True),
)


MODELS: dict[int, DeviceProfile] = {
    # --- video processors ---------------------------------------------------
    0x6107: DeviceProfile(
        "VX4S",
        Family.VIDEO_PROCESSOR,
        0x6107,
        4,
        inputs=VX4S_INPUTS,
        input_register=INPUT_REGISTER_VX4S,
        display=DisplayControl(VX4S_DISPLAY_REGISTER, normal=0, blackout=2, freeze=1),
        panel_lock_register=VX4S_PANEL_LOCK_REGISTER,
        notes="blackout is 2 and freeze is 1 here -- the opposite of the COEX API",
    ),
    0x612A: DeviceProfile(
        "VX4S-N",
        Family.VIDEO_PROCESSOR,
        0x612A,
        4,
        inputs=VX4S_INPUTS,
        input_register=INPUT_REGISTER_VX4S,
        display=DisplayControl(VX4S_DISPLAY_REGISTER, normal=0, blackout=2, freeze=1),
        panel_lock_register=VX4S_PANEL_LOCK_REGISTER,
        notes="assumed identical to the VX4S; confirm on hardware",
    ),
    0x6205: DeviceProfile(
        "NovaPro UHD Jr",
        Family.VIDEO_PROCESSOR,
        0x6205,
        16,
        inputs=UHD_JR_INPUTS,
        outputs=UHD_JR_OUTPUTS,
        input_register=None,
        notes="4K all-in-one; 16 Neutrik + 4 fibre outputs; input codes unconfirmed",
    ),
    0x7504: DeviceProfile(
        "NovaPro UHD",
        Family.VIDEO_PROCESSOR,
        0x7504,
        16,
        inputs=NOVAPRO_HD_INPUTS,
        input_register=INPUT_REGISTER_NOVAPRO_HD,
        notes="input map assumed shared with NovaPro HD; confirm on hardware",
    ),
    0x6101: DeviceProfile(
        "NovaPro HD",
        Family.VIDEO_PROCESSOR,
        0x6101,
        4,
        inputs=NOVAPRO_HD_INPUTS,
        input_register=INPUT_REGISTER_NOVAPRO_HD,
    ),
    0x6121: DeviceProfile(
        "NovaPro HD II",
        Family.VIDEO_PROCESSOR,
        0x6121,
        8,
        inputs=NOVAPRO_HD_INPUTS,
        input_register=INPUT_REGISTER_NOVAPRO_HD,
        notes="input map assumed shared with NovaPro HD; confirm on hardware",
    ),
    0x1103: DeviceProfile(
        "MCTRL4K",
        Family.VIDEO_PROCESSOR,
        0x1103,
        16,
        inputs=(
            InputConnector(ConnectorType.HDMI, "HDMI", None),
            InputConnector(ConnectorType.DVI, "DVI", None),
            InputConnector(ConnectorType.DP, "DP", None),
        ),
        notes="input codes unconfirmed",
    ),
    0x1105: DeviceProfile("MCTRL1600", Family.VIDEO_PROCESSOR, 0x1105, 16),
    0x620C: DeviceProfile(
        "VX1000",
        Family.VIDEO_PROCESSOR,
        0x620C,
        10,
        inputs=(
            InputConnector(ConnectorType.HDMI, "HDMI", None),
            InputConnector(ConnectorType.DVI, "DVI", None),
            InputConnector(ConnectorType.DP, "DP", None),
            InputConnector(ConnectorType.SDI, "SDI", None),
        ),
        notes="input codes unconfirmed",
    ),
    0x622B: DeviceProfile(
        "VX1000 Pro",
        Family.VIDEO_PROCESSOR,
        0x622B,
        10,
        control_port=VX_PRO_TCP_PORT,
        notes="VX Pro series listens on 15200, not 5200",
    ),
    0x6109: DeviceProfile(
        "VX5", Family.VIDEO_PROCESSOR, 0x6109, 4, inputs=VX4S_INPUTS,
        input_register=INPUT_REGISTER_VX4S,
        notes="input map assumed shared with the VX4S; confirm on hardware",
    ),
    0x6106: DeviceProfile(
        "VX4", Family.VIDEO_PROCESSOR, 0x6106, 4, inputs=VX4S_INPUTS,
        input_register=INPUT_REGISTER_VX4S,
        notes="the VX4S document's own device-ID example reads back 0x6106",
    ),
    0x6105: DeviceProfile("VX2", Family.VIDEO_PROCESSOR, 0x6105, 2),
    # --- sending cards ------------------------------------------------------
    0x1107: DeviceProfile(
        "MCTRL660 Pro",
        Family.SENDING_CARD,
        0x1107,
        6,
        inputs=MCTRL660_PRO_INPUTS,
        input_register=INPUT_REGISTER_SENDING_CARD,
        notes="model ID confirmed by NovaStar's own protocol document",
    ),
    0x1108: DeviceProfile("MCTRL660 ROE", Family.SENDING_CARD, 0x1108, 4),
    0x1104: DeviceProfile("MCTRL R5", Family.SENDING_CARD, 0x1104, 8),
    0x1102: DeviceProfile("E500", Family.SENDING_CARD, 0x1102, 4),
    0x0001: DeviceProfile("Sending card", Family.SENDING_CARD, 0x0001, 2),
    0x0101: DeviceProfile("Controller", Family.SENDING_CARD, 0x0101, 4),
}

#: COEX controllers are identified by the HTTP API, not by model ID, and their
#: inputs are read from ``/api/v1/device/input/sources`` at runtime -- which is
#: why `inputs` is empty here. Display-mode values follow the HTTP API's own
#: convention (1 blackout, 2 freeze), the opposite of the VX4S register.
COEX_MODELS: dict[str, DeviceProfile] = {
    name.lower(): DeviceProfile(
        name,
        Family.COEX,
        None,
        ports,
        http_api=True,
        presets=True,
        display=DisplayControl(None, normal=0, blackout=1, freeze=2),
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
    0x6107: "model ID decompiled; inputs and display from the VX4S Command Protocol",
    0x6101: "model ID decompiled; inputs from the PRO HD input-source document",
    0x6205: "model ID and port count decompiled; connectors from the product "
    "specification; input select codes unknown",
    "others": "decompiled NSCardType / GetPortNumber -- unverified on hardware",
    "coex": "product documentation; identified by HTTP probe, inputs read at runtime",
}


def unknown_profile(model_id: int | None = None) -> DeviceProfile:
    """A usable profile for a model we have no entry for.

    Not recognising a model is not an error: the register bus works regardless,
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
        presets=True,
        display=DisplayControl(None, normal=0, blackout=1, freeze=2),
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
        profile = self.profile
        lines = [
            f"{self.host}",
            f"  model        {profile.name}"
            + (f"  (0x{profile.model_id:04x})" if profile.model_id else ""),
            f"  family       {profile.family.value}",
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

        outputs = [f"{profile.port_count}x Ethernet"]
        outputs += [f"{o.count}x {o.label}" for o in profile.outputs]
        lines.append(f"  outputs      {', '.join(outputs)}")

        if profile.http_api:
            lines.append("  inputs       read from the controller at runtime")
        elif profile.inputs:
            switchable = len(profile.switchable_inputs)
            detail = ", ".join(connector.label for connector in profile.inputs)
            lines.append(f"  inputs       {detail}")
            if switchable != len(profile.inputs):
                lines.append(
                    f"               {switchable}/{len(profile.inputs)} have known "
                    "select codes"
                )
        if profile.display.is_processor_level:
            lines.append(f"  display      processor register 0x{profile.display.register:08x}")
        else:
            lines.append("  display      receiving-card kill/lock registers")
        if profile.notes:
            lines.append(f"  note         {profile.notes}")
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
