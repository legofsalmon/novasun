"""Tests for capture parsing and differential analysis.

The pcap and pcapng files are synthesised here rather than committed, so the
parser is exercised against bytes built to the file-format specifications rather
than against a fixture that could have been produced by the same misreading.
"""

from __future__ import annotations

import json
import struct

import pytest

from novasun import capture, registers as reg
from novasun.names import NameIndex, parse_address_mapping
from novasun.protocol import (
    HEADER_RESPONSE,
    ErrorType,
    Packet,
    Target,
    read_request,
    write_request,
)

CLIENT = "192.168.1.100"
DEVICE = "192.168.1.40"


def tcp_segment(source_ip: str, destination_ip: str, source_port: int, destination_port: int, sequence: int, payload: bytes) -> bytes:
    """An Ethernet + IPv4 + TCP frame carrying ``payload``."""
    tcp = struct.pack(
        ">HHIIBBHHH",
        source_port,
        destination_port,
        sequence,
        0,  # acknowledgement
        5 << 4,  # data offset, no options
        0x18,  # PSH | ACK
        65535,
        0,  # checksum, not verified by the parser
        0,
    ) + payload
    total = 20 + len(tcp)
    ip = struct.pack(
        ">BBHHHBBH4s4s",
        0x45,
        0,
        total,
        0,
        0,
        64,
        6,  # TCP
        0,
        bytes(int(o) for o in source_ip.split(".")),
        bytes(int(o) for o in destination_ip.split(".")),
    ) + tcp
    return b"\xff" * 6 + b"\xaa" * 6 + b"\x08\x00" + ip


def write_pcap(path, packets: list[tuple[float, bytes]]) -> None:
    with open(path, "wb") as handle:
        handle.write(struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1))
        for timestamp, frame in packets:
            handle.write(
                struct.pack(
                    "<IIII",
                    int(timestamp),
                    int(round((timestamp % 1) * 1_000_000)),
                    len(frame),
                    len(frame),
                )
            )
            handle.write(frame)


def write_pcapng(path, packets: list[tuple[float, bytes]]) -> None:
    def block(block_type: int, body: bytes) -> bytes:
        padding = (-len(body)) % 4
        length = 12 + len(body) + padding
        return (
            struct.pack("<II", block_type, length)
            + body
            + b"\x00" * padding
            + struct.pack("<I", length)
        )

    with open(path, "wb") as handle:
        handle.write(block(0x0A0D0D0A, struct.pack("<IHHq", 0x1A2B3C4D, 1, 0, -1)))
        handle.write(block(0x00000001, struct.pack("<HHI", 1, 0, 65535)))
        for timestamp, frame in packets:
            microseconds = int(timestamp * 1_000_000)
            handle.write(
                block(
                    0x00000006,
                    struct.pack(
                        "<IIIII",
                        0,
                        microseconds >> 32,
                        microseconds & 0xFFFFFFFF,
                        len(frame),
                        len(frame),
                    )
                    + frame,
                )
            )


def session_frames() -> list[tuple[bool, bytes]]:
    """A plausible little NovaLCT session: probe, then set brightness to 50 %."""
    probe = read_request(reg.CONTROLLER_MODEL_ID, 2, Target.sending_card(), serno=1)
    probe_reply = Packet(
        head=HEADER_RESPONSE,
        ack=ErrorType.SUCCEEDED,
        serno=1,
        source=0,
        destination=0xFE,
        io=probe.io,
        address=probe.address,
        length=2,
        data=b"\x07\x11",
    )
    brightness = write_request(
        reg.GLOBAL_BRIGHTNESS, b"\x80", Target.all_receiving_cards(), serno=2
    )
    brightness_reply = Packet(
        head=HEADER_RESPONSE,
        ack=ErrorType.SUCCEEDED,
        serno=2,
        source=0xFF,
        destination=0xFE,
        device_type=brightness.device_type,
        port=0xFF,
        rcv_index=0xFFFF,
        io=brightness.io,
        address=brightness.address,
        length=0,
    )
    return [
        (True, probe.to_bytes()),
        (False, probe_reply.to_bytes()),
        (True, brightness.to_bytes()),
        (False, brightness_reply.to_bytes()),
    ]


def build_capture(tmp_path, name: str, frames, writer=write_pcap, split: bool = False):
    """Write a capture file containing ``frames`` as a TCP conversation."""
    packets = []
    sequences = {True: 1000, False: 5000}
    for index, (to_device, frame) in enumerate(frames):
        chunks = (
            [frame[: len(frame) // 2], frame[len(frame) // 2 :]] if split else [frame]
        )
        for chunk in chunks:
            if to_device:
                packets.append(
                    (
                        1700000000.0 + index * 0.01,
                        tcp_segment(CLIENT, DEVICE, 51000, 5200, sequences[True], chunk),
                    )
                )
                sequences[True] += len(chunk)
            else:
                packets.append(
                    (
                        1700000000.0 + index * 0.01,
                        tcp_segment(DEVICE, CLIENT, 5200, 51000, sequences[False], chunk),
                    )
                )
                sequences[False] += len(chunk)
    path = tmp_path / name
    writer(path, packets)
    return path


def test_decodes_a_pcap(tmp_path) -> None:
    path = build_capture(tmp_path, "session.pcap", session_frames())
    events = capture.decode_capture(path)

    assert len(events) == 4
    assert [event.packet.address for event in events] == [
        reg.CONTROLLER_MODEL_ID,
        reg.CONTROLLER_MODEL_ID,
        reg.GLOBAL_BRIGHTNESS,
        reg.GLOBAL_BRIGHTNESS,
    ]
    assert events[0].to_device and not events[1].to_device
    assert events[2].is_write
    assert events[2].packet.data == b"\x80"


def test_decodes_a_pcapng(tmp_path) -> None:
    path = build_capture(tmp_path, "session.pcapng", session_frames(), writer=write_pcapng)
    events = capture.decode_capture(path)
    assert len(events) == 4
    assert events[3].packet.ok


def test_reassembles_frames_split_across_segments(tmp_path) -> None:
    """Frames are not aligned to TCP segments; the reader must span them."""
    path = build_capture(tmp_path, "split.pcap", session_frames(), split=True)
    events = capture.decode_capture(path)
    assert len(events) == 4
    assert events[2].packet.data == b"\x80"


def test_ignores_retransmissions(tmp_path) -> None:
    frames = session_frames()
    packets = []
    sequence = 1000
    for _ in range(2):  # the same segment twice, same sequence number
        packets.append(
            (1700000000.0, tcp_segment(CLIENT, DEVICE, 51000, 5200, sequence, frames[0][1]))
        )
    write_pcap(tmp_path / "dup.pcap", packets)
    assert len(capture.decode_capture(tmp_path / "dup.pcap")) == 1


def test_ignores_traffic_on_other_ports(tmp_path) -> None:
    frame = session_frames()[0][1]
    write_pcap(
        tmp_path / "other.pcap",
        [(1700000000.0, tcp_segment(CLIENT, DEVICE, 51000, 22, 1000, frame))],
    )
    assert capture.decode_capture(tmp_path / "other.pcap") == []


def test_transactions_pair_by_serial_number(tmp_path) -> None:
    path = build_capture(tmp_path, "session.pcap", session_frames())
    transactions = capture.pair_transactions(capture.decode_capture(path))
    assert len(transactions) == 2
    assert all(transaction.succeeded for transaction in transactions)
    assert transactions[0].value == b"\x07\x11"  # read: the value read back
    assert transactions[1].value == b"\x80"  # write: the value written


def test_summary_counts_reads_and_writes(tmp_path) -> None:
    path = build_capture(tmp_path, "session.pcap", session_frames())
    summary = capture.summarise(capture.decode_capture(path))
    assert summary[reg.CONTROLLER_MODEL_ID].reads == 1
    assert summary[reg.CONTROLLER_MODEL_ID].writes == 0
    assert summary[reg.GLOBAL_BRIGHTNESS].writes == 1
    assert summary[reg.GLOBAL_BRIGHTNESS].final_write == b"\x80"


def test_diff_finds_the_register_a_setting_changed(tmp_path) -> None:
    """The core workflow: same action, one setting different, diff the two."""
    before = build_capture(tmp_path, "before.pcap", session_frames())

    changed = session_frames()
    brightness = write_request(
        reg.GLOBAL_BRIGHTNESS, b"\x40", Target.all_receiving_cards(), serno=2
    )
    changed[2] = (True, brightness.to_bytes())
    after = build_capture(tmp_path, "after.pcap", changed)

    differences = capture.diff(
        capture.decode_capture(before), capture.decode_capture(after)
    )
    assert len(differences) == 1
    assert differences[0].address == reg.GLOBAL_BRIGHTNESS
    assert differences[0].before == b"\x80"
    assert differences[0].after == b"\x40"
    assert differences[0].kind == "changed"


def test_diff_reports_registers_present_in_only_one_capture(tmp_path) -> None:
    before = build_capture(tmp_path, "before.pcap", session_frames())
    extra = session_frames() + [
        (
            True,
            write_request(
                reg.SELF_TEST_MODE,
                bytes([reg.TestPattern.WHITE]),
                Target.all_receiving_cards(),
                serno=3,
            ).to_bytes(),
        )
    ]
    after = build_capture(tmp_path, "after.pcap", extra)

    differences = capture.diff(
        capture.decode_capture(before), capture.decode_capture(after)
    )
    assert [d.kind for d in differences] == ["only-in-after"]
    assert differences[0].address == reg.SELF_TEST_MODE


def test_report_names_known_registers_and_flags_unknown(tmp_path) -> None:
    frames = session_frames() + [
        (True, write_request(0xDEAD_BEEF, b"\x01", Target.sending_card(), serno=9).to_bytes())
    ]
    path = build_capture(tmp_path, "session.pcap", frames)
    text = capture.report(capture.decode_capture(path), NameIndex())

    assert "GLOBAL_BRIGHTNESS" in text
    assert "0xdeadbeef" in text
    assert "**unknown**" in text
    assert "## Unnamed registers" in text


def test_reads_a_proxy_session_log(tmp_path) -> None:
    path = tmp_path / "session.jsonl"
    with path.open("w") as handle:
        for to_device, frame in session_frames():
            handle.write(
                json.dumps(
                    {
                        "timestamp": 1700000000.0,
                        "source": CLIENT if to_device else DEVICE,
                        "destination": DEVICE if to_device else CLIENT,
                        "frame": frame.hex(),
                    }
                )
                + "\n"
            )
    events = capture.load(path)
    assert len(events) == 4
    assert events[2].packet.address == reg.GLOBAL_BRIGHTNESS


def test_rejects_a_file_that_is_not_a_capture(tmp_path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("this is not a pcap")
    with pytest.raises(capture.CaptureError):
        capture.decode_capture(path)


class TestNameIndex:
    def test_builtin_names_cover_documented_registers(self) -> None:
        index = NameIndex()
        assert index.lookup(reg.GLOBAL_BRIGHTNESS)
        assert index.lookup(0xDEAD_BEEF) is None

    def test_offsets_into_a_known_block_are_attributed_to_it(self) -> None:
        index = NameIndex()
        name = index.lookup(reg.RECEIVER_MONITORING + 0x40)
        assert name and name.startswith("RECEIVER_MONITORING") and name.endswith("+0x40")

    def test_offsets_are_only_attributed_within_a_known_length(self) -> None:
        """No guessing: past the end of the block it is unknown again."""
        index = NameIndex()
        assert index.lookup(reg.RECEIVER_MONITORING + 0x100) is None
        assert index.lookup(reg.VIDEO_SOURCE_STATE + 0x20)
        assert index.lookup(reg.VIDEO_SOURCE_STATE + 0x80) is None

    def test_parses_a_typescript_address_enum(self) -> None:
        source = """
        enum AddressMapping {
          GlobalBrightnessAddr = 33554433,       // 0x200_0001
          GlobalBrightnessOccupancy = 1,
          SelfTestModeAddr = 33554689,           // 0x200_0101
          HexStyleAddr = 0x0200_0102,
        }
        """
        names = parse_address_mapping(source)
        assert names[0x0200_0001] == "GlobalBrightnessAddr"
        assert names[0x0200_0101] == "SelfTestModeAddr"
        assert names[0x0200_0102] == "HexStyleAddr"
        # Occupancy entries are sizes, not addresses.
        assert "GlobalBrightnessOccupancy" not in names.values()

    def test_imported_names_fill_gaps_without_overriding_builtins(self) -> None:
        index = NameIndex(imported={0xDEAD_BEEF: "SomethingAddr", reg.GLOBAL_BRIGHTNESS: "Other"})
        assert index.lookup(0xDEAD_BEEF) == "SomethingAddr"
        assert "GLOBAL_BRIGHTNESS" in (index.lookup(reg.GLOBAL_BRIGHTNESS) or "")
        assert "Other" not in (index.lookup(reg.GLOBAL_BRIGHTNESS) or "")

    def test_aliased_addresses_report_every_name(self) -> None:
        """0x02000001 is both the one-byte global and the five-byte block."""
        name = NameIndex().lookup(reg.GLOBAL_BRIGHTNESS) or ""
        assert "GLOBAL_BRIGHTNESS" in name and "ALL_BRIGHTNESS" in name
