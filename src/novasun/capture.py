"""Turn captured traffic into named register operations.

The point of this module is to make NovaLCT and VMP document themselves. Capture
a session, decode it here, and every frame the vendor software sent becomes a
labelled read or write of a known register -- or an *unknown* register, which is
the interesting case, because that is a gap in the address map with a worked
example attached.

Two inputs are supported and produce the same records:

* **pcap / pcapng** files, parsed here directly -- no Wireshark, tshark or
  libpcap needed to analyse them. (You still need something to *record* with;
  see ``docs/capture-workflow.md``.)
* **JSONL session logs** written by :mod:`novasun.proxy`, which needs no packet
  capture at all.

The analysis that matters is differential: capture the same operation twice with
one setting changed, diff the register writes, and the register that moved is
the one that setting controls.
"""

from __future__ import annotations

import gzip
import io
import json
import struct
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

from .names import NameIndex, default_index
from .protocol import IO, Packet, ProtocolError
from .transport import FrameReader

NOVASTAR_PORTS = frozenset({5200, 5201, 5203, 15200})
"""Ports carrying the register bus. 5203's role is unconfirmed; decode it anyway."""

# Link-layer types we know how to strip. Values are libpcap DLT numbers.
DLT_NULL = 0
DLT_ETHERNET = 1
DLT_RAW = 101
DLT_LINUX_SLL = 113
DLT_LINUX_SLL2 = 276


class CaptureError(Exception):
    pass


@dataclass
class FrameEvent:
    """One decoded register-bus frame, with when and which way it went."""

    timestamp: float
    packet: Packet
    source: str
    destination: str

    @property
    def to_device(self) -> bool:
        return not self.packet.is_response

    @property
    def is_write(self) -> bool:
        return self.packet.io == IO.WRITE

    def describe(self, names: NameIndex | None = None) -> str:
        names = names or default_index()
        packet = self.packet
        direction = "->" if self.to_device else "<-"
        verb = "write" if packet.io == IO.WRITE else "read "
        name = names.lookup(packet.address)
        label = f"0x{packet.address:08x}" + (f" {name}" if name else "")
        if packet.is_response:
            status = "ok" if packet.ok else f"ack={packet.ack}"
            body = packet.data.hex() if packet.data else f"[{status}]"
        else:
            body = packet.data.hex() if packet.io == IO.WRITE else f"[{packet.length} bytes]"
        return (
            f"{self.timestamp:14.6f} {direction} {verb} {label} "
            f"dev={int(packet.device_type)} port={packet.port:#04x} "
            f"rcv={packet.rcv_index:#06x} {body}"
        )


@dataclass
class Transaction:
    """A request paired with its response, matched on serial number."""

    request: FrameEvent
    response: FrameEvent | None = None

    @property
    def address(self) -> int:
        return self.request.packet.address

    @property
    def succeeded(self) -> bool:
        return self.response is not None and self.response.packet.ok

    @property
    def value(self) -> bytes:
        """Payload that crossed the wire: written bytes, or bytes read back."""
        if self.request.packet.io == IO.WRITE:
            return self.request.packet.data
        return self.response.packet.data if self.response else b""


# --- pcap / pcapng parsing --------------------------------------------------


def _open(path: str | Path) -> io.BufferedReader:
    path = Path(path)
    if path.suffix == ".gz":
        return gzip.open(path, "rb")  # type: ignore[return-value]
    return path.open("rb")


def read_packets(path: str | Path) -> Iterator[tuple[float, int, bytes]]:
    """Yield ``(timestamp, linktype, link_layer_bytes)`` from a pcap or pcapng."""
    with _open(path) as stream:
        magic = stream.read(4)
        if len(magic) < 4:
            raise CaptureError(f"{path}: too short to be a capture file")
        if magic == b"\x0a\x0d\x0d\x0a":
            yield from _read_pcapng(stream)
        elif magic in (b"\xd4\xc3\xb2\xa1", b"\xa1\xb2\xc3\xd4", b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\x3c\x4d"):
            yield from _read_pcap(stream, magic)
        else:
            raise CaptureError(f"{path}: not a pcap or pcapng file")


def _read_pcap(stream: io.BufferedReader, magic: bytes) -> Iterator[tuple[float, int, bytes]]:
    little = magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1")
    nanosecond = magic in (b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\x3c\x4d")
    endian = "<" if little else ">"
    header = stream.read(20)
    if len(header) < 20:
        raise CaptureError("truncated pcap header")
    # version major/minor, timezone offset, timestamp accuracy, snaplen, linktype
    linktype = struct.unpack(endian + "HHiIII", header)[5]
    divisor = 1e9 if nanosecond else 1e6
    record = struct.Struct(endian + "IIII")
    while True:
        raw = stream.read(record.size)
        if len(raw) < record.size:
            return
        seconds, fraction, captured, _original = record.unpack(raw)
        data = stream.read(captured)
        if len(data) < captured:
            return
        yield seconds + fraction / divisor, linktype, data


def _read_pcapng(stream: io.BufferedReader) -> Iterator[tuple[float, int, bytes]]:
    # The section header block's byte-order magic decides endianness for the
    # whole section; we have already consumed its 4-byte type field.
    head = stream.read(8)
    if len(head) < 8:
        raise CaptureError("truncated pcapng section header")
    # The magic is the value 0x1A2B3C4D, so its byte order on disk is the
    # section's byte order: 4D 3C 2B 1A little-endian, 1A 2B 3C 4D big-endian.
    if head[4:8] == b"\x4d\x3c\x2b\x1a":
        endian = "<"
    elif head[4:8] == b"\x1a\x2b\x3c\x4d":
        endian = ">"
    else:
        raise CaptureError("unrecognised pcapng byte-order magic")
    total = struct.unpack(endian + "I", head[0:4])[0]
    stream.read(max(0, total - 12))

    interfaces: list[tuple[int, float]] = []  # (linktype, timestamp resolution)
    while True:
        header = stream.read(8)
        if len(header) < 8:
            return
        block_type, block_length = struct.unpack(endian + "II", header)
        if block_length < 12:
            return
        body = stream.read(block_length - 12)
        stream.read(4)  # trailing length

        if block_type == 0x00000001:  # interface description
            linktype = struct.unpack_from(endian + "H", body, 0)[0]
            interfaces.append((linktype, _pcapng_tsresol(body[8:], endian)))
        elif block_type == 0x00000006:  # enhanced packet
            interface_id, ts_high, ts_low, captured, _original = struct.unpack_from(
                endian + "IIIII", body, 0
            )
            linktype, resolution = (
                interfaces[interface_id] if interface_id < len(interfaces) else (DLT_ETHERNET, 1e-6)
            )
            timestamp = ((ts_high << 32) | ts_low) * resolution
            yield timestamp, linktype, body[20 : 20 + captured]
        elif block_type == 0x00000003:  # simple packet
            linktype, _ = interfaces[0] if interfaces else (DLT_ETHERNET, 1e-6)
            yield 0.0, linktype, body[4:]
        elif block_type == 0x0A0D0D0A:  # a new section
            interfaces = []


def _pcapng_tsresol(options: bytes, endian: str) -> float:
    """Read if_tsresol (option 9); default is microseconds."""
    offset = 0
    while offset + 4 <= len(options):
        code, length = struct.unpack_from(endian + "HH", options, offset)
        value = options[offset + 4 : offset + 4 + length]
        offset += 4 + ((length + 3) // 4) * 4
        if code == 0:
            break
        if code == 9 and value:
            raw = value[0]
            return 2.0 ** -(raw & 0x7F) if raw & 0x80 else 10.0 ** -raw
    return 1e-6


def _strip_link_layer(linktype: int, data: bytes) -> bytes | None:
    """Return the IPv4 datagram inside a link-layer frame, if there is one."""
    if linktype == DLT_ETHERNET:
        if len(data) < 14:
            return None
        ethertype = struct.unpack_from(">H", data, 12)[0]
        offset = 14
        while ethertype in (0x8100, 0x88A8):  # VLAN tags
            if len(data) < offset + 4:
                return None
            ethertype = struct.unpack_from(">H", data, offset + 2)[0]
            offset += 4
        return data[offset:] if ethertype == 0x0800 else None
    if linktype == DLT_RAW:
        return data
    if linktype == DLT_NULL:
        if len(data) < 4:
            return None
        family = struct.unpack_from("<I", data, 0)[0]
        return data[4:] if family in (2, 0x02000000) else None
    if linktype == DLT_LINUX_SLL:
        if len(data) < 16:
            return None
        return data[16:] if struct.unpack_from(">H", data, 14)[0] == 0x0800 else None
    if linktype == DLT_LINUX_SLL2:
        if len(data) < 20:
            return None
        return data[20:] if struct.unpack_from(">H", data, 0)[0] == 0x0800 else None
    return None


@dataclass
class _Stream:
    """TCP segments for one direction of one connection, keyed by sequence."""

    segments: dict[int, bytes] = field(default_factory=dict)
    times: dict[int, float] = field(default_factory=dict)
    base: int | None = None

    def add(self, seq: int, payload: bytes, timestamp: float) -> None:
        if self.base is None:
            self.base = seq
        offset = (seq - self.base) & 0xFFFFFFFF
        # Retransmissions arrive with the same offset; keep the first copy.
        if offset not in self.segments:
            self.segments[offset] = payload
            self.times[offset] = timestamp

    def ordered(self) -> list[tuple[float, bytes]]:
        """Contiguous payloads in sequence order, trimming overlaps."""
        out: list[tuple[float, bytes]] = []
        position = 0
        for offset in sorted(self.segments):
            payload = self.segments[offset]
            if offset + len(payload) <= position:
                continue  # wholly retransmitted
            if offset < position:
                payload = payload[position - offset :]
                offset = position
            out.append((self.times[offset] if offset in self.times else 0.0, payload))
            position = offset + len(payload)
        return out


def decode_capture(
    path: str | Path, ports: Iterable[int] = NOVASTAR_PORTS
) -> list[FrameEvent]:
    """Decode every register-bus frame in a pcap/pcapng file, in time order."""
    ports = set(ports)
    streams: dict[tuple[str, int, str, int], _Stream] = defaultdict(_Stream)

    for timestamp, linktype, data in read_packets(path):
        datagram = _strip_link_layer(linktype, data)
        if not datagram or len(datagram) < 20 or (datagram[0] >> 4) != 4:
            continue
        header_length = (datagram[0] & 0x0F) * 4
        if datagram[9] != 6 or len(datagram) < header_length + 20:
            continue
        source = ".".join(str(b) for b in datagram[12:16])
        destination = ".".join(str(b) for b in datagram[16:20])
        tcp = datagram[header_length:]
        source_port, destination_port, sequence = struct.unpack_from(">HHI", tcp, 0)
        if source_port not in ports and destination_port not in ports:
            continue
        payload = tcp[((tcp[12] >> 4) * 4) :]
        if payload:
            streams[(source, source_port, destination, destination_port)].add(
                sequence, payload, timestamp
            )

    events: list[FrameEvent] = []
    for (source, source_port, destination, destination_port), stream in streams.items():
        reader = FrameReader()
        for timestamp, payload in stream.ordered():
            try:
                packets = reader.feed(payload)
            except ProtocolError:
                continue  # a corrupt or truncated frame; keep going
            for packet in packets:
                events.append(
                    FrameEvent(
                        timestamp=timestamp,
                        packet=packet,
                        source=f"{source}:{source_port}",
                        destination=f"{destination}:{destination_port}",
                    )
                )
    events.sort(key=lambda event: event.timestamp)
    return events


# --- JSONL session logs (written by novasun.proxy) --------------------------


def load_session_log(path: str | Path) -> list[FrameEvent]:
    events: list[FrameEvent] = []
    with Path(path).open() as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            events.append(
                FrameEvent(
                    timestamp=record["timestamp"],
                    packet=Packet.from_bytes(bytes.fromhex(record["frame"]), verify=False),
                    source=record.get("source", ""),
                    destination=record.get("destination", ""),
                )
            )
    return events


def load(path: str | Path) -> list[FrameEvent]:
    """Load either a capture file or a proxy session log, by extension."""
    suffixes = Path(path).suffixes
    if ".jsonl" in suffixes:
        return load_session_log(path)
    return decode_capture(path)


# --- analysis ---------------------------------------------------------------


def pair_transactions(events: list[FrameEvent]) -> list[Transaction]:
    """Match responses to requests by serial number.

    Serial numbers wrap at 256, so a stale response can look like a match for a
    much later request; pairing greedily against the most recent unanswered
    request with that number keeps that from mattering in practice.
    """
    transactions: list[Transaction] = []
    outstanding: dict[int, Transaction] = {}
    for event in events:
        if event.packet.is_response:
            waiting = outstanding.pop(event.packet.serno, None)
            if waiting is not None:
                waiting.response = event
            else:
                transactions.append(Transaction(request=event, response=None))
        else:
            transaction = Transaction(request=event)
            transactions.append(transaction)
            outstanding[event.packet.serno] = transaction
    return transactions


@dataclass
class RegisterActivity:
    """Everything one capture did to one register."""

    address: int
    reads: int = 0
    writes: int = 0
    written_values: list[bytes] = field(default_factory=list)
    read_values: list[bytes] = field(default_factory=list)
    device_types: set[int] = field(default_factory=set)
    failures: int = 0

    @property
    def final_write(self) -> bytes | None:
        return self.written_values[-1] if self.written_values else None


def summarise(events: list[FrameEvent]) -> dict[int, RegisterActivity]:
    """Per-register summary of a capture."""
    summary: dict[int, RegisterActivity] = {}
    for transaction in pair_transactions(events):
        packet = transaction.request.packet
        if packet.is_response:
            continue
        activity = summary.setdefault(packet.address, RegisterActivity(address=packet.address))
        activity.device_types.add(int(packet.device_type))
        if packet.io == IO.WRITE:
            activity.writes += 1
            activity.written_values.append(packet.data)
        else:
            activity.reads += 1
            if transaction.response is not None:
                activity.read_values.append(transaction.response.packet.data)
        if transaction.response is not None and not transaction.response.packet.ok:
            activity.failures += 1
    return summary


@dataclass
class Difference:
    """One register that behaved differently between two captures."""

    address: int
    before: bytes | None
    after: bytes | None
    kind: str  # "changed" | "only-in-after" | "only-in-before"

    def describe(self, names: NameIndex | None = None) -> str:
        names = names or default_index()
        name = names.lookup(self.address)
        label = f"0x{self.address:08x}" + (f"  {name}" if name else "")
        before = self.before.hex() if self.before is not None else "-"
        after = self.after.hex() if self.after is not None else "-"
        return f"{label:<48} {before:>16} -> {after}"


def diff(before: list[FrameEvent], after: list[FrameEvent]) -> list[Difference]:
    """Registers written differently between two captures of the same action.

    This is the workhorse: record the vendor software doing something twice with
    one setting changed, and what comes out is the register that setting drives.
    Reads are ignored -- polling differs run to run and only adds noise.
    """
    left = summarise(before)
    right = summarise(after)
    differences: list[Difference] = []
    for address in sorted(set(left) | set(right)):
        old = left.get(address)
        new = right.get(address)
        old_value = old.final_write if old else None
        new_value = new.final_write if new else None
        if old_value is None and new_value is None:
            continue  # read-only in both captures
        if old_value is None:
            differences.append(Difference(address, None, new_value, "only-in-after"))
        elif new_value is None:
            differences.append(Difference(address, old_value, None, "only-in-before"))
        elif old_value != new_value:
            differences.append(Difference(address, old_value, new_value, "changed"))
    return differences


def report(events: list[FrameEvent], names: NameIndex | None = None) -> str:
    """Markdown summary of a capture: what was touched, and what is unnamed."""
    names = names or default_index()
    summary = summarise(events)
    if not summary:
        return "No register-bus frames found in this capture.\n"

    lines = [
        "# Capture report",
        "",
        f"{len(events)} frames, {len(summary)} distinct registers.",
        "",
        "| Register | Name | Reads | Writes | Last value written | Failures |",
        "|---|---|---:|---:|---|---:|",
    ]
    unknown: list[int] = []
    for address in sorted(summary):
        activity = summary[address]
        name = names.lookup(address)
        if not name:
            unknown.append(address)
        value = activity.final_write.hex() if activity.final_write else ""
        lines.append(
            f"| `0x{address:08x}` | {name or '**unknown**'} | {activity.reads} | "
            f"{activity.writes} | `{value}` | {activity.failures} |"
        )

    if unknown:
        lines += [
            "",
            "## Unnamed registers",
            "",
            "These are the gaps in the address map. Each one has a worked example",
            "in this capture -- re-record the same action with one setting changed",
            "and diff to find out what it controls.",
            "",
        ]
        lines += [f"- `0x{address:08x}`" for address in unknown]
    return "\n".join(lines) + "\n"
