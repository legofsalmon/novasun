"""First contact with real hardware: read everything, change nothing.

Every check here is a read. No register is written, no display state is
touched, no configuration is saved. It is safe to run against a processor
driving a live screen.

The point is to settle, in one pass, the things this project could only infer
from documents: whether the model ID matches the decompiled table, what the
discovery reply actually contains, how many ports and receiving cards are
really there, and which input register a model responds on.

    novasun bringup 192.168.1.40 --json report.json
"""

from __future__ import annotations

import json
import socket
import time
from dataclasses import dataclass, field
from typing import Any

from . import registers as reg
from .client import Controller
from .devices import (
    INPUT_REGISTER_NOVAPRO_HD,
    INPUT_REGISTER_SENDING_CARD,
    INPUT_REGISTER_VX4S,
    profile_for,
)
from .discovery import MULTICAST_GROUP, PROBE, REPLY_PREFIX, UDP_PORT
from .protocol import DeviceError, ProtocolError, Target
from .transport import TCP_PORT, VX_PRO_TCP_PORT

#: Candidate input-select registers, so a model whose map is unknown can be
#: narrowed by reading rather than by writing a guessed byte.
INPUT_REGISTER_CANDIDATES = {
    "sending-card 0x02000023": INPUT_REGISTER_SENDING_CARD,
    "VX4S 0x0220002D": INPUT_REGISTER_VX4S,
    "NovaPro HD 0x02200022": INPUT_REGISTER_NOVAPRO_HD,
}

#: Read-only registers worth capturing verbatim for later analysis.
RAW_READS = {
    "device_type_0x00000002": (reg.CONTROLLER_MODEL_ID, 2),
    "comm_protocol_0x00000004": (reg.COMMUNICATION_PROTOCOL, 2),
    "serial_0x00000016": (reg.CONTROLLER_SN_HIGH, 8),
    "low_addresses_0x00000000": (0x0000_0000, 32),
    "name_block_0x14000000": (reg.DEVICE_NAME_SPACE, 88),
    "video_source_state_0x13010000": (reg.VIDEO_SOURCE_STATE, 64),
    "screen_config_0x02100000": (reg.SCREEN_CONFIG_SPACE, 32),
}


@dataclass
class BringUp:
    host: str
    started: float = field(default_factory=time.time)
    discovery: dict[str, Any] = field(default_factory=dict)
    coex: dict[str, Any] = field(default_factory=dict)
    identity: dict[str, Any] = field(default_factory=dict)
    ports: dict[str, Any] = field(default_factory=dict)
    cards: list[dict[str, Any]] = field(default_factory=list)
    monitoring: dict[str, Any] = field(default_factory=dict)
    input_registers: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "started": self.started,
            "novasun_bringup_version": 1,
            "discovery": self.discovery,
            "coex": self.coex,
            "identity": self.identity,
            "ports": self.ports,
            "receiving_cards": self.cards,
            "monitoring": self.monitoring,
            "input_registers": self.input_registers,
            "raw_reads": self.raw,
            "notes": self.notes,
        }


def _discovery(report: BringUp, timeout: float) -> None:
    """Send the standard probe and keep every reply byte verbatim.

    This is the one transmit in the whole run, and it is the same broadcast
    NovaLCT emits: no register address, no write bit, no addressed target.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    replies: list[dict[str, Any]] = []
    try:
        sock.bind(("0.0.0.0", UDP_PORT))
        for destination in ("255.255.255.255", MULTICAST_GROUP, report.host):
            try:
                sock.sendto(PROBE, (destination, UDP_PORT))
            except OSError:
                continue
        deadline = time.time() + timeout
        while time.time() < deadline:
            sock.settimeout(max(0.05, deadline - time.time()))
            try:
                payload, (address, port) = sock.recvfrom(4096)
            except (TimeoutError, socket.timeout, OSError):
                break
            replies.append(
                {
                    "from": address,
                    "port": port,
                    "is_reply": payload.startswith(REPLY_PREFIX),
                    "length": len(payload),
                    "hex": payload.hex(),
                    "tail_hex": payload[len(REPLY_PREFIX):].hex()
                    if payload.startswith(REPLY_PREFIX)
                    else "",
                    "ascii": "".join(
                        chr(b) if 32 <= b < 127 else "." for b in payload
                    ),
                }
            )
    except OSError as exc:
        report.notes.append(f"discovery socket unavailable: {exc}")
    finally:
        sock.close()
    report.discovery = {"replies": replies, "count": len(replies)}
    if not replies:
        report.notes.append(
            "no discovery replies -- the probe may be blocked, or replies may be "
            "unicast to a port this socket did not bind"
        )


#: Read-only COEX endpoints worth capturing verbatim. Recording the raw JSON
#: is the point: this repository's field names are reconstructed from the
#: manual and have never been checked against firmware.
COEX_ENDPOINTS = {
    "device": "/api/v1/device",
    "screen": "/api/v1/screen",
    "cabinet": "/api/v1/device/cabinet",
    "screen_cabinets": "/api/v1/screen/cabinets",
    "input_sources": "/api/v1/device/input/sources",
    "displaymode": "/api/v1/device/screen/displaymode",
    "preset": "/api/v1/preset",
    "monitor_info": "/api/v1/device/monitor/info",
    "backup": "/api/v1/device/backup",
    "snmpstate": "/api/v1/device/snmpstate",
    "audio": "/api/v1/device/audio",
    "multifunc_card": "/api/v1/device/multifunc-card/detailinfo",
}


def _coex(report: BringUp, timeout: float, rate: float = 0.25) -> None:
    """Read every documented GET endpoint through a client that cannot write.

    ReadOnlyCoexClient rejects any method other than GET before a socket is
    opened, so this cannot alter a live screen even by mistake.
    """
    from .coex import CoexError
    from .monitor import ReadOnlyCoexClient

    client = ReadOnlyCoexClient(report.host, timeout=timeout)
    results: dict[str, Any] = {}
    answered = False
    for name, path in COEX_ENDPOINTS.items():
        time.sleep(rate)  # deliberately unhurried: a show may be running
        try:
            results[name] = client.request("GET", path)
            answered = True
        except CoexError as exc:
            # An API-shaped error still proves a COEX controller is there.
            answered = True
            results[name] = {"__error__": str(exc)}
        except (OSError, ValueError) as exc:
            results[name] = {"__error__": str(exc)}
    report.coex = {"answered": answered, "endpoints": results}
    if answered:
        report.notes.append(
            "COEX HTTP answered: this is an MX/CX/KU-class controller, driven "
            "over the documented JSON API rather than the register bus"
        )


def _safe_read(controller: Controller, address: int, length: int, target: Target) -> Any:
    try:
        return controller.read(address, length, target).hex()
    except (DeviceError, ProtocolError, TimeoutError, OSError) as exc:
        return f"<{type(exc).__name__}: {exc}>"


def run(
    host: str,
    port: int = TCP_PORT,
    timeout: float = 2.0,
    max_ports: int = 16,
    cards_per_port: int = 8,
    probe: bool = True,
    allow_register_bus: bool | None = None,
) -> BringUp:
    """Read-only first contact.

    ``allow_register_bus`` defaults to "only if this is not a COEX controller".
    A COEX box already answers everything over HTTP, and opening a TCP 5200
    session on one during a show risks contending with VMP for a resource it
    may be holding -- for no information we cannot get more safely.
    """
    report = BringUp(host=host)
    if probe:
        _discovery(report, timeout)
    else:
        report.notes.append("discovery probe skipped (--no-probe)")
    _coex(report, timeout)

    if allow_register_bus is None:
        allow_register_bus = not report.coex.get("answered", False)
    if not allow_register_bus:
        report.notes.append(
            "register-bus phase skipped. It would open a TCP 5200 control "
            "session and walk the receiving-card chain; pass --register-bus "
            "to do it anyway, ideally not during a show"
        )
        return report

    control_port = port
    controller: Controller | None = None
    for candidate in (port, VX_PRO_TCP_PORT):
        try:
            controller = Controller.connect(host, candidate, timeout=timeout)
            control_port = candidate
            break
        except OSError as exc:
            report.notes.append(f"TCP {candidate}: {exc}")
    if controller is None:
        report.notes.append("no register-bus connection; nothing further to read")
        return report

    try:
        report.identity["control_port"] = control_port
        info = controller.probe()
        if info is None:
            report.notes.append("connected, but no device answered a model-ID read")
            return report

        profile = profile_for(info.model_id)
        report.identity.update(
            {
                "model_id": f"0x{info.model_id:04x}",
                "model_id_int": info.model_id,
                "expected_name": profile.name,
                "recognised": profile.is_known,
                "serial": info.serial,
                "device_name": info.name,
                "max_packet_size": info.max_packet_size,
                "expected_ports": profile.port_count,
            }
        )

        for name, (address, length) in RAW_READS.items():
            report.raw[name] = _safe_read(controller, address, length, Target.sending_card())

        # Which input register does this model actually answer on? Reading is
        # safe; writing a guessed value at a live screen is not.
        for label, address in INPUT_REGISTER_CANDIDATES.items():
            report.input_registers[label] = {
                "sending_card": _safe_read(controller, address, 1, Target.sending_card()),
                "receiving_card": _safe_read(
                    controller, address, 1, Target.receiving_card(0, 0)
                ),
            }

        # Which ports actually have cards, and how many.
        found_ports: dict[str, int] = {}
        for port_index in range(max_ports):
            cards = 0
            misses = 0
            for card_index in range(cards_per_port):
                card = controller.probe_receiving_card(port_index, card_index)
                if card is None:
                    misses += 1
                    if misses >= 2:
                        break
                    continue
                misses = 0
                cards += 1
                report.cards.append(card.to_dict())
            if cards:
                found_ports[str(port_index)] = cards
        report.ports = {
            "probed": max_ports,
            "with_cards": found_ports,
            "total_cards": len(report.cards),
        }

        # Full monitoring block from the first card we found, unparsed.
        if report.cards:
            first = report.cards[0]
            target = Target.receiving_card(int(first["port"]), int(first["index"]))
            report.monitoring = {
                "port": first["port"],
                "index": first["index"],
                "block_0x0A000000": _safe_read(
                    controller, reg.RECEIVER_MONITORING, 0x100, target
                ),
                "decoded": _decode(controller, target),
            }
    finally:
        controller.close()
    return report


def _decode(controller: Controller, target: Target) -> dict[str, Any]:
    try:
        status = controller.read_receiver_monitoring(target.port, target.rcv_index)
    except (DeviceError, ProtocolError, TimeoutError, OSError) as exc:
        return {"error": str(exc)}
    return {
        "temperature_c": status.temperature_c,
        "humidity_percent": status.humidity_percent,
        "voltage_v": status.voltage_v,
    }


def format_report(report: BringUp) -> str:
    lines = [f"novasun bring-up: {report.host}", "=" * 52, ""]

    lines.append("DISCOVERY (UDP 3800)")
    if report.discovery.get("replies"):
        for reply in report.discovery["replies"]:
            lines.append(f"  from {reply['from']}:{reply['port']}  {reply['length']} bytes")
            lines.append(f"    ascii  {reply['ascii']}")
            lines.append(f"    hex    {reply['hex']}")
            if reply["tail_hex"]:
                lines.append(f"    tail   {reply['tail_hex']}  <-- the unknown part")
    else:
        lines.append("  no replies")
    lines.append("")

    lines.append("COEX HTTP (8001)  -- read-only GETs")
    lines.append(f"  answered: {report.coex.get('answered')}")
    for name, value in (report.coex.get("endpoints") or {}).items():
        if isinstance(value, dict) and "__error__" in value:
            lines.append(f"  {name:<16} ! {value['__error__']}")
            continue
        rendered = json.dumps(value)
        if len(rendered) > 400:
            rendered = rendered[:400] + f" ... ({len(rendered)} chars total)"
        lines.append(f"  {name:<16} {rendered}")
    lines.append("")

    lines.append("IDENTITY (register bus)")
    if report.identity:
        for key in (
            "control_port", "model_id", "expected_name", "recognised",
            "serial", "device_name", "max_packet_size", "expected_ports",
        ):
            if key in report.identity:
                lines.append(f"  {key:<18} {report.identity[key]}")
    else:
        lines.append("  no identity read")
    lines.append("")

    lines.append("PORTS AND RECEIVING CARDS")
    if report.ports:
        lines.append(f"  probed {report.ports['probed']} ports, "
                     f"found {report.ports['total_cards']} card(s)")
        for port, count in report.ports.get("with_cards", {}).items():
            lines.append(f"    port {port}: {count} card(s)")
        for card in report.cards[:8]:
            lines.append(
                f"    p{card['port']} c{card['index']}  {card['name']}  "
                f"fw {card['firmware']}  healthy={card['healthy']}"
            )
        if len(report.cards) > 8:
            lines.append(f"    ... and {len(report.cards) - 8} more")
    lines.append("")

    lines.append("INPUT REGISTER CANDIDATES (read only)")
    for label, values in report.input_registers.items():
        lines.append(f"  {label:<26} sender={values['sending_card']}  "
                     f"card={values['receiving_card']}")
    lines.append("")

    if report.monitoring:
        lines.append(f"MONITORING (port {report.monitoring['port']}, "
                     f"card {report.monitoring['index']})")
        lines.append(f"  decoded {report.monitoring['decoded']}")
        block = report.monitoring.get("block_0x0A000000", "")
        lines.append(f"  first 64 bytes {block[:128]}")
        lines.append("")

    if report.notes:
        lines.append("NOTES")
        lines += [f"  - {note}" for note in report.notes]
    return "\n".join(lines)
