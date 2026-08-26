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

#: Registers with distinctive, stable values, read immediately before a
#: candidate to detect the stale-response-buffer behaviour described in
#: :mod:`novasun.registers`. Their leading bytes differ from each other on
#: purpose: a candidate whose genuine value coincides with one poison is
#: misclassified by a single-poison test, which happened during bring-up of the
#: first real unit before this was made rigorous.
POISON_READS: tuple[tuple[int, int], ...] = (
    (0x0000_0000, 8),                    # 09 36 05 62 ...
    (reg.CONTROLLER_SN_HIGH, 8),         # the serial
    (reg.CONTROLLER_MODEL_ID, 2),        # 05 62
    (reg.MAX_PACKET_PROBE, 1),           # a8
)

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


def _coex(report: BringUp, timeout: float) -> None:
    from .coex import CoexClient, CoexError

    try:
        client = CoexClient(report.host, timeout=timeout)
        report.coex = {"answered": True, "device": client.device_info()}
    except CoexError as exc:
        report.coex = {"answered": True, "error": str(exc)}
    except (OSError, ValueError) as exc:
        report.coex = {"answered": False, "error": str(exc)}


def _safe_read(controller: Controller, address: int, length: int, target: Target) -> Any:
    try:
        return controller.read(address, length, target).hex()
    except (DeviceError, ProtocolError, TimeoutError, OSError) as exc:
        return f"<{type(exc).__name__}: {exc}>"


def _read_bytes(
    controller: Controller, address: int, length: int, target: Target
) -> bytes | None:
    try:
        return controller.read(address, length, target)
    except (DeviceError, ProtocolError, TimeoutError, OSError):
        return None


def _classify_register(
    controller: Controller, address: int, length: int, target: Target
) -> dict[str, Any]:
    """Decide whether ``address`` is backed by storage, or echoing the buffer.

    An address this firmware does not implement does not error and does not read
    zero: it returns the previous read's payload. So "it read back a plausible
    value" is not evidence a register exists. Poison the buffer with a known
    value first, and repeat with several different poisons -- a candidate whose
    real value happens to equal one poison would otherwise look unimplemented.

    Reads only. Safe against a live screen.
    """
    trials: list[dict[str, str]] = []
    echoes = 0
    values: set[bytes] = set()
    # Only poisons at least as long as the candidate. A shorter one cannot be
    # compared against a longer read without assuming how the device pads the
    # leftover bytes, and that padding has not been established on hardware.
    usable_poisons = [(a, n) for a, n in POISON_READS if n >= length]
    for poison_address, poison_length in usable_poisons:
        poison = _read_bytes(controller, poison_address, poison_length, target)
        value = _read_bytes(controller, address, length, target)
        if poison is None or value is None:
            trials.append({"poison": f"0x{poison_address:08x}", "read": "<unreadable>"})
            continue
        echo = value == poison[:length]
        echoes += echo
        values.add(value)
        trials.append(
            {
                "poison": f"0x{poison_address:08x}",
                "poison_value": poison[:length].hex(),
                "read": value.hex(),
                "verdict": "echo" if echo else "independent",
            }
        )

    # The signal is not "did it equal the poison" but "did it VARY WITH the
    # poison". A backed register whose real value happens to match one poison
    # would fail the first test and be called inconclusive; it passes this one,
    # because its value stayed put while the poisons changed underneath it.
    usable = [t for t in trials if "verdict" in t]
    distinct_poisons = {t["poison_value"] for t in usable}
    if not usable or len(distinct_poisons) < 2:
        # With fewer than two distinct poisons there is nothing to vary against,
        # so the honest answer is "not established" rather than a guess.
        verdict, value = "unreadable" if not usable else "inconclusive", None
    elif len(values) == 1:
        verdict, value = "implemented", next(iter(values)).hex()
    elif echoes == len(usable):
        verdict, value = "unimplemented", None
    else:
        verdict, value = "inconclusive", None
    return {
        "verdict": verdict,
        "value": value,
        "trials_total": len(usable),
        "trials_echoed": echoes,
        "trials": trials,
    }


def run(
    host: str,
    port: int = TCP_PORT,
    timeout: float = 2.0,
    max_ports: int = 16,
    cards_per_port: int = 32,
) -> BringUp:
    report = BringUp(host=host)
    _discovery(report, timeout)
    _coex(report, timeout)

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
        # safe; writing a guessed value at a live screen is not. A plain read is
        # not enough to answer it -- see _classify_register.
        for label, address in INPUT_REGISTER_CANDIDATES.items():
            report.input_registers[label] = _classify_register(
                controller, address, 1, Target.sending_card()
            )
        implemented = [
            label
            for label, result in report.input_registers.items()
            if result["verdict"] == "implemented"
        ]
        if len(implemented) == 1:
            report.notes.append(
                f"input register narrowed to {implemented[0]} -- the others are "
                f"unimplemented on this model. The register is settled; the VALUES "
                f"are not. Establish them by changing the input from the front "
                f"panel and re-reading, not by writing a guess."
            )
        elif not implemented:
            report.notes.append(
                "no candidate input register is backed by storage on this model"
            )

        # Which ports actually have cards, and how many.
        # Every port, not "until the first empty one": a real unit was found
        # populating ports 0, 1, 2 and 4, and an enumerator that stops at the
        # first gap would have reported a quarter of the installation.
        found_ports: dict[str, int] = {}
        saturated: list[str] = []
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
            # A chain that fills the scan limit was probably cut short. Say so:
            # a truncated count that looks like a complete one is worse than no
            # count at all.
            if cards == cards_per_port:
                saturated.append(str(port_index))
        if saturated:
            report.notes.append(
                f"ports {', '.join(saturated)} returned a card at every scanned "
                f"position, so the chain may be longer than the {cards_per_port} "
                f"scanned -- re-run with a higher --cards-per-port to be sure"
            )
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

    lines.append("COEX HTTP (8001)")
    lines.append(f"  answered: {report.coex.get('answered')}")
    if report.coex.get("device"):
        lines.append(f"  {report.coex['device']}")
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

    lines.append("INPUT REGISTER CANDIDATES (poison-discriminated, read only)")
    for label, result in report.input_registers.items():
        value = f"  value={result['value']}" if result.get("value") else ""
        lines.append(
            f"  {label:<26} {result['verdict']:<14} "
            f"({result['trials_echoed']}/{result['trials_total']} echoed){value}"
        )
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
