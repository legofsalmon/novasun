"""Replay hex examples out of NovaStar's own documents against the codec.

Each vector is a frame printed verbatim in a published NovaStar document or in
a shipped tool. Passing means our field offsets and checksum agree with what the
hardware is documented to accept -- the closest thing to a conformance test that
is available without a controller on the bench.

Two known-bad vectors are pinned at the bottom: they are errors in the sources,
not in this codec, and are kept so the discrepancy stays documented.
"""

from __future__ import annotations

import pytest

from novasun import registers as reg
from novasun.protocol import (
    HEADER_REQUEST,
    HEADER_RESPONSE,
    DeviceType,
    IO,
    Packet,
    Target,
    checksum,
    expected_frame_size,
    write_request,
)


def parse_hex(text: str) -> bytes:
    return bytes.fromhex(text.replace(" ", ""))


# name -> (frame, expected address, expected payload)
OFFICIAL_VECTORS = {
    # COEX Central Control Protocol V1.5.0
    "coex brightness 0%": (
        "55 aa 00 00 fe ff 01 ff ff ff 01 00 01 00 00 02 01 00 00",
        reg.GLOBAL_BRIGHTNESS,
        b"\x00",
    ),
    "coex blackout on": (
        "55 aa 00 00 fe ff 01 ff ff ff 01 00 00 01 00 02 01 00 ff",
        reg.KILL_MODE,
        b"\xff",
    ),
    "coex freeze on": (
        "55 aa 00 00 fe ff 01 ff ff ff 01 00 02 01 00 02 01 00 ff",
        reg.LOCK_MODE,
        b"\xff",
    ),
    "coex freeze off": (
        "55 aa 00 00 fe ff 01 ff ff ff 01 00 02 01 00 02 01 00 00",
        reg.LOCK_MODE,
        b"\x00",
    ),
    "coex preset 1": (
        "55 aa 00 00 fe ff 01 ff ff ff 01 00 02 00 00 0a 01 00 01",
        reg.PRESET_SWITCH,
        b"\x01",
    ),
    "coex preset 2": (
        "55 aa 00 00 fe ff 01 ff ff ff 01 00 02 00 00 0a 01 00 02",
        reg.PRESET_SWITCH,
        b"\x02",
    ),
    "coex low latency on": (
        "55 aa 00 00 fe ff 01 ff ff ff 01 00 11 01 00 10 01 00 01",
        reg.LOW_LATENCY,
        b"\x01",
    ),
    "coex 3d on": (
        "55 AA 00 00 FE FF 01 FF FF FF 01 00 16 01 00 10 01 00 01",
        reg.THREE_D_ENABLE,
        b"\x01",
    ),
    "coex 3d right eye": (
        "55 aa 00 00 fe ff 01 ff ff ff 01 00 18 11 00 10 01 00 00",
        reg.THREE_D_EYE,
        b"\x00",
    ),
    "coex all-in-one mode": (
        "55 aa 00 00 fe ff 01 ff ff ff 01 00 f2 ff 08 00 01 00 01",
        reg.WORKING_MODE,
        b"\x01",
    ),
    "coex send-only mode": (
        "55 aa 00 00 fe ff 01 ff ff ff 01 00 f2 ff 08 00 01 00 00",
        reg.WORKING_MODE,
        b"\x00",
    ),
    "coex output card 6 blackout": (
        "55 aa 00 00 fe ff 01 ff ff ff 01 00 00 01 00 10 02 00 06 01",
        reg.SENDING_CARD_DISPLAY,
        b"\x06\x01",
    ),
    "coex layer 1 to input card 1 connector 0": (
        "55 aa 00 00 fe ff 01 ff ff ff 01 00 03 00 00 0a 03 00 01 01 00",
        reg.LAYER_SOURCE,
        b"\x01\x01\x00",
    ),
    # Protocol for MCTRL 660 Pro
    "660pro input sdi": (
        "55 aa 00 9d fe ff 00 00 00 00 01 00 23 00 00 02 01 00 01",
        reg.DVI_SELECT,
        b"\x01",
    ),
    "660pro input hdmi": (
        "55 aa 00 8a fe ff 00 00 00 00 01 00 23 00 00 02 01 00 05",
        reg.DVI_SELECT,
        b"\x05",
    ),
    "660pro input dvi": (
        "55 aa 00 3e fe ff 00 00 00 00 01 00 23 00 00 02 01 00 58",
        reg.DVI_SELECT,
        b"\x58",
    ),
    "660pro blackout": (
        "55 AA 00 80 FE 00 01 FF FF FF 01 00 00 01 00 02 01 00 FF",
        reg.KILL_MODE,
        b"\xff",
    ),
    # RS232 Protocol for Nova M3 Control System V1.9
    "m3 blue test pattern on first receiving card": (
        "55 AA 00 80 FE 00 01 00 00 00 01 00 01 01 00 02 01 00 04",
        reg.SELF_TEST_MODE,
        bytes([reg.TestPattern.BLUE]),
    ),
    "m3 five brightness components at once": (
        "55 AA 00 15 FE 00 01 FF FF FF 01 00 01 00 00 02 05 00 80 80 80 80 80",
        reg.ALL_BRIGHTNESS,
        b"\x80" * 5,
    ),
}

READ_VECTORS = {
    # (frame, address, requested length)
    "m3 monitoring block read": (
        "55 AA 00 32 FE 00 01 00 00 00 00 00 00 00 00 0A 00 01",
        reg.RECEIVER_MONITORING,
        0x100,
    ),
    "660pro read device id": (
        "55 AA 00 00 FE 00 00 00 00 00 00 00 02 00 00 00 02 00",
        reg.CONTROLLER_MODEL_ID,
        2,
    ),
}

RESPONSE_VECTORS = {
    # (frame, address, payload)
    "660pro device id response": (
        "AA 55 00 00 00 FE 00 00 00 00 00 00 02 00 00 00 02 00 07 11",
        reg.CONTROLLER_MODEL_ID,
        b"\x07\x11",
    ),
    "m3 write acknowledge": (
        "AA 55 00 5D 00 FE 00 00 00 00 01 00 10 00 00 05 00 00",
        0x0500_0010,
        b"",
    ),
    "m3 blue pattern acknowledge": (
        "AA 55 00 80 00 FE 01 00 00 00 01 00 01 01 00 02 00 00",
        reg.SELF_TEST_MODE,
        b"",
    ),
}


def _with_checksum(body_hex: str) -> bytes:
    body = parse_hex(body_hex)
    return body + checksum(body).to_bytes(2, "little")


@pytest.mark.parametrize("name", sorted(OFFICIAL_VECTORS))
def test_write_vectors_round_trip(name: str) -> None:
    body_hex, address, payload = OFFICIAL_VECTORS[name]
    frame = _with_checksum(body_hex)
    packet = Packet.from_bytes(frame)

    assert packet.head == HEADER_REQUEST
    assert packet.io == IO.WRITE
    assert packet.address == address
    assert packet.data == payload
    assert packet.length == len(payload)
    assert packet.to_bytes() == frame


@pytest.mark.parametrize("name", sorted(READ_VECTORS))
def test_read_vectors_round_trip(name: str) -> None:
    body_hex, address, length = READ_VECTORS[name]
    frame = _with_checksum(body_hex)
    packet = Packet.from_bytes(frame)

    assert packet.io == IO.READ
    assert packet.address == address
    assert packet.length == length
    assert packet.data == b""
    assert packet.to_bytes() == frame


@pytest.mark.parametrize("name", sorted(RESPONSE_VECTORS))
def test_response_vectors_round_trip(name: str) -> None:
    body_hex, address, payload = RESPONSE_VECTORS[name]
    frame = _with_checksum(body_hex)
    packet = Packet.from_bytes(frame)

    assert packet.head == HEADER_RESPONSE
    assert packet.is_response
    assert packet.ok
    assert packet.address == address
    assert packet.data == payload
    assert packet.to_bytes() == frame


def test_documented_checksums_match_the_published_bytes() -> None:
    """The checksum bytes printed in the documents, not just our own recompute."""
    published = {
        "55 aa 00 00 fe ff 01 ff ff ff 01 00 01 00 00 02 01 00 00": "55 5a",
        "55 aa 00 00 fe ff 01 ff ff ff 01 00 00 01 00 02 01 00 ff": "54 5b",
        "55 aa 00 00 fe ff 01 ff ff ff 01 00 02 00 00 0a 01 00 01": "5f 5a",
        "55 aa 00 00 fe ff 01 ff ff ff 01 00 f2 ff 08 00 01 00 00": "4b 5c",
        "55 AA 00 32 FE 00 01 00 00 00 00 00 00 00 00 0A 00 01": "91 56",
        "AA 55 00 5D 00 FE 00 00 00 00 01 00 10 00 00 05 00 00": "C6 56",
        "55 AA 00 80 FE 00 01 00 00 00 01 00 01 01 00 02 01 00 04": "DE 56",
        "55 AA 00 15 FE 00 01 FF FF FF 01 00 01 00 00 02 05 00 80 80 80 80 80": "EF 5B",
    }
    for body_hex, checksum_hex in published.items():
        body = parse_hex(body_hex)
        assert checksum(body).to_bytes(2, "little") == parse_hex(checksum_hex), body_hex


def test_brightness_percentage_follows_the_documented_ratio() -> None:
    """COEX Central Control 3.2.1: "Brightness ratio = Brightness value / FF".

    Only the endpoints are fixed by the documents; everything between is the
    application's choice of rounding. Published step tables disagree with each
    other -- see :class:`TestSourceErrata` -- so they are not a specification.
    """
    assert reg.brightness_byte(0) == 0x00
    assert reg.brightness_byte(100) == 0xFF
    assert reg.brightness_byte(50) == 0x80
    assert all(
        reg.brightness_byte(p) <= reg.brightness_byte(p + 1) for p in range(100)
    )
    with pytest.raises(ValueError):
        reg.brightness_byte(101)


def test_our_encoder_reproduces_a_documented_frame() -> None:
    """Build the COEX blackout frame from the API rather than from hex."""
    packet = write_request(reg.KILL_MODE, b"\xff", Target.all_receiving_cards())
    assert packet.to_bytes() == _with_checksum(
        "55 aa 00 00 fe ff 01 ff ff ff 01 00 00 01 00 02 01 00 ff"
    )
    assert packet.device_type == DeviceType.RECEIVING_CARD


def test_frame_size_depends_on_direction_not_length_alone() -> None:
    write = _with_checksum("55 aa 00 00 fe ff 01 ff ff ff 01 00 01 00 00 02 01 00 00")
    write_ack = _with_checksum("aa 55 00 00 ff fe 01 ff ff ff 01 00 01 00 00 02 01 00")
    read = _with_checksum("55 AA 00 00 FE 00 00 00 00 00 00 00 02 00 00 00 02 00")
    read_reply = _with_checksum("AA 55 00 00 00 FE 00 00 00 00 00 00 02 00 00 00 02 00 07 11")

    # Same length field, different frame sizes, decided by head + io.
    assert expected_frame_size(write) == 21
    assert expected_frame_size(write_ack) == 20
    assert expected_frame_size(read) == 20
    assert expected_frame_size(read_reply) == 22
    assert expected_frame_size(b"\x55\xaa\x00") is None


def test_checksum_rejects_a_corrupted_frame() -> None:
    frame = bytearray(_with_checksum("55 aa 00 00 fe ff 01 ff ff ff 01 00 01 00 00 02 01 00 00"))
    frame[18] ^= 0xFF
    with pytest.raises(Exception):
        Packet.from_bytes(bytes(frame))


class TestSourceErrata:
    """Two published frames do not match their own stated checksums."""

    def test_coex_manual_response_example_is_inconsistent(self) -> None:
        """COEX Central Control V1.5.0, section 3.1 D: response example.

        Printed as ``aa 55 ... 49 5d``; the bytes shown sum to 0x5c4a. The
        difference is exactly 0xFF, so one byte of the frame was dropped or
        mistyped in the manual. Every other frame in the same document is
        self-consistent, and the acknowledge examples in the M3 document verify,
        so the rule -- not the example -- is what to trust.
        """
        body = parse_hex("aa 55 00 00 ff fe 01 ff ff ff 01 00 f2 ff 08 00 00 00")
        assert checksum(body) == 0x5C4A
        assert checksum(body) != 0x5D49
        assert 0x5D49 - checksum(body) == 0xFF

    def test_published_brightness_step_tables_disagree(self) -> None:
        """The two tables in Companion's choices.js round differently.

        Its 0/10/20-step table is ``floor(percent * 255 / 100)``; its finer
        table is neither floor nor round (15 % maps to 0x27 = 39, where both
        rules give 38). They are hand-made lists, not a mapping to copy.
        """
        coarse = {10: 0x19, 20: 0x33, 30: 0x4C, 50: 0x7F, 100: 0xFF}
        for percent, value in coarse.items():
            assert value == int(percent * 255 / 100)

        fine = {3: 0x08, 8: 0x14, 15: 0x27, 75: 0xC0}
        disagreements = {
            percent: value
            for percent, value in fine.items()
            if value != int(percent * 255 / 100)
        }
        assert disagreements == {3: 0x08, 15: 0x27, 75: 0xC0}

    def test_companion_table_checksums_exclude_the_serial_number(self) -> None:
        """bitfocus/companion-module-novastar-controller, choices.js.

        Its hard-coded frames carry stale checksums that omit the serial-number
        byte. Harmless there -- the module strips the last two bytes and
        recomputes before sending -- but the tables must not be copied verbatim.
        """
        body = parse_hex("55 AA 00 80 FE 00 01 FF FF FF 01 00 01 01 00 02 01 00 02")
        stated = 0x5959
        assert checksum(body) == 0x59D9
        assert checksum(body) - stated == body[3]  # exactly the serial number
