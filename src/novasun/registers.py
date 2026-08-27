"""Register addresses on the NovaStar register bus.

Every entry here is corroborated by at least one of:

* an official NovaStar document (`docs/sources.md` lists them),
* the ``AddressMapping`` enum generated from decompiled NovaLCT assemblies by
  the `sarakusha/novastar` project,
* a captured frame reproduced in a published tool.

``CONFIDENCE`` records which. Treat ``derived`` entries as good starting points
to confirm against your own hardware, not as guarantees; register semantics vary
across controller generations and receiving-card chipsets. ``OBSERVED`` records
what a bench unit actually did, which is a separate question.

**Two hardware behaviours make naive reads lie.** Both are OBSERVED on a NovaPro
UHD Jr and reproduced across a power cycle; both return well-formed frames with
``ack = SUCCEEDED``, so neither is detectable from a single read:

1. **An unimplemented address returns the previous read's payload**, not zeros
   and not an error. A sequential sweep therefore reports nearly every address
   as live, holding plausible data. To test an address, read a known register
   with a distinctive value first ("poison"), then the candidate: if it comes
   back as the poison, it is unimplemented. Use at least two different poisons —
   a candidate whose real value coincides with one poison is otherwise
   misclassified.
2. **Reads snap to field boundaries.** A read starting inside a multi-byte field
   silently returns data from that field's *start*. Reads at documented base
   addresses are unaffected, so this is a trap for probing rather than a bug in
   normal use — but it means a block cannot be walked byte by byte.

See ``docs/read-only-monitoring.md`` section 5 for the evidence.
"""

from __future__ import annotations

from enum import IntEnum

# --- Sending card / controller, low addresses ------------------------------
DEVICE_TYPE = 0x0000_0002
"""u8 device class; u16 read here is the controller model id (NovaLCT's probe)."""
CONTROLLER_MODEL_ID = 0x0000_0002  # u16
COMMUNICATION_PROTOCOL = 0x0000_0004  # u16
MAX_PACKET_PROBE = 0x0000_0006  # u8, 0xA8 marks a device that reports its max packet size
MAX_PACKET_SIZE = 0x0000_0007  # u16
CONTROLLER_SN_HIGH = 0x0000_0016
"""8 bytes of serial number. Not the MAC address, despite the decompiled name.

A UHD Jr reads 16:04:11:00:c1:c9:2d:00 here while its Ethernet MAC, taken from a
packet capture of the same unit in the same session, is 54:b5:6c:08:5d:49. The
two are unrelated, and it is 8 bytes rather than 6. Earlier comments here and in
docs/protocol-register-bus.md described it as "serial number / MAC"; the MAC
half is withdrawn.
"""
DEVICE_NAME_SPACE = 0x1400_0000  # 88 bytes; 0xA8 marker, length at +17, name at +18

SAVE_SENDER_PARAMETERS = 0x0100_0001  # u8, commit RAM settings to flash
RETURN_FACTORY_VALUES = 0x0100_0002  # u8

# --- Receiving card identity (device_type = RECEIVING_CARD) ----------------
RECEIVING_CARD_INFO = 0x0000_0000
"""6 bytes: u16 model ID, then 4 bytes of firmware version.

Reading it is also the presence test. Per the M3 protocol document: "Just try
reading the receiving card model ID. If the ID can be read back, it means the
receiving card is working normally." A model ID of 0 means no card, and a
firmware of all zeros means the card is not running properly.
"""
RECEIVING_CARD_MODEL = 0x0000_0000  # u16, non-zero when a card is present
RECEIVING_CARD_FIRMWARE = 0x0000_0002  # 4 bytes, e.g. 04 02 00 01 -> 4.2.0.1

# --- Receiving card display registers (device_type = RECEIVING_CARD) -------
GAMMA = 0x0200_0000  # u8
GLOBAL_BRIGHTNESS = 0x0200_0001  # u8 0..255
RED_BRIGHTNESS = 0x0200_0002  # u8
GREEN_BRIGHTNESS = 0x0200_0003  # u8
BLUE_BRIGHTNESS = 0x0200_0004  # u8
VIRTUAL_RED_BRIGHTNESS = 0x0200_0005  # u8
RGB_BRIGHTNESS = 0x0200_0002  # 4 bytes R,G,B,vR
ALL_BRIGHTNESS = 0x0200_0001
"""5 bytes written at once: global, R, G, B, virtual-R. NovaLCT's screen slider."""

KILL_MODE = 0x0200_0100  # u8 0x00 normal / 0xFF blackout
SELF_TEST_MODE = 0x0200_0101  # u8, see TestPattern
LOCK_MODE = 0x0200_0102  # u8 0x00 unfrozen / 0xFF frozen
LOW_DELAY = 0x0200_0074  # u8
DVI_SELECT = 0x0200_0023  # u8, input source on the controller, see InputSource
BRIGHTNESS_16BIT = 0x0200_000F  # u16

RECEIVER_MONITORING = 0x0A00_0000
"""0x100 bytes of receiving-card monitoring: temperature, voltage, fans, cables.

**Exactly** 0x100 bytes. ``0x0A000100`` aliases ``0x02000000`` on a UHD Jr's
receiving cards, so a read longer than the block returns display registers
without saying so: 256 bytes of monitoring followed by gamma, brightness and the
rest, all looking like more monitoring. Read 0x100 and no more.
"""
RECEIVER_MONITORING_SIZE = 0x100

# --- Screen geometry (receiving card) --------------------------------------
# OBSERVED on a UHD Jr chain; the interpretation below is REASONED.
CABINET_PIXELS_A = 0x0200_0017  # u16, reads 104 on every card of a 30-card wall
CABINET_PIXELS_B = 0x0200_0019  # u16, reads 208 on every card of the same wall
"""Cabinet pixel dimensions, almost certainly height and width in that order.

Three independent places agree on 104: this field, the 104 real entries in
:data:`ROW_MAPPING_TABLE`, and the 104-pixel step in
:data:`CABINET_POSITION_TABLE` on the sending card. That makes 104 the vertical
pitch with high confidence, and so ``CABINET_PIXELS_A`` the height.

Which of the two is width and which height is nonetheless **REASONED, not
observed** -- one wall of uniform cabinets cannot distinguish them, and a wall
of 208x104 cabinets would produce identical readings to one of 104x208 laid out
the other way. Confirm against a wall with non-square cabinets of known
orientation before relying on it.
"""

ROW_MAPPING_TABLE = 0x0300_0000
"""Receiving card: u16 entries mapping rows, 0..103, padded to 128 with 0xFFFF.

Aliased at ``0x13000000`` on the same card. The 104 real entries match the
cabinet height, which is what identifies this as a per-row table.
"""

CABINET_POSITION_TABLE = 0x0300_0000
"""Sending card: ten u32 offsets, 936 down to 0 in steps of 104.

Ten entries for the ten cabinets on this wall's longest chains, stepping by the
cabinet height, which reads as the vertical position of each cabinet in the
canvas. **REASONED** -- the arithmetic is compelling but no second wall has been
seen, and a single uniform chain cannot distinguish a position table from any
other evenly-spaced quantity.

An earlier version of this note said "aliased at ``0x09000000``". **Withdrawn.**
That was an echo: the test read this address immediately before ``0x09000000``,
which guarantees a match on any unimplemented address. Read after something
else, ``0x09000000`` returns something else.

Note this shares an address with :data:`ROW_MAPPING_TABLE`, which is a different
register on a different device type -- the same pattern as
:data:`SOFTWARE_SPACE` and :data:`RED_GAMMA_TABLE` at ``0x05000000``.
"""

RED_GAMMA_TABLE = 0x0500_0000  # 512 bytes
GREEN_GAMMA_TABLE = 0x0500_0200  # 512 bytes
BLUE_GAMMA_TABLE = 0x0500_0400  # 512 bytes

SCREEN_CONFIG_SPACE = 0x0210_0000  # sending-card screen configuration block
SOFTWARE_SPACE = 0x0500_0000  # NovaLCT's own "software space" on the sending card
VIDEO_SOURCE_STATE = 0x1301_0000
"""Array of per-connector signal records, NOT a flat block.

Described here as "64 bytes of input-signal state" until hardware showed
otherwise. It is an array of :data:`VIDEO_SOURCE_RECORD_SIZE`-byte records, each
carrying its own ascending index at ``+0x16``; on a NovaPro UHD Jr records 0-7
are input connectors and record 8 reports the output canvas. Reading it as one
flat structure yields whichever connector happens to sit at the offset being
read, which is how this was originally misread as "the current input".
"""
VIDEO_SOURCE_RECORD_SIZE = 32
VIDEO_SOURCE_INPUT_RECORDS = 8  # uhd-jr: 0..7 are inputs, 8 is the output canvas

# Offsets within one video-source record, all OBSERVED. The rate fields were
# confirmed by driving a connector at 60 Hz and then 50 Hz: the nominal field
# went 6000 -> 5000 while the measured period went ~16666 -> 20000 (exactly
# 1/50 s). Only the measured one jitters, which is how the two were told apart.
VSR_WIDTH = 0x04  # u16, 0 when no signal; seen at 1920 and 3840
VSR_HEIGHT = 0x06  # u16, 0 when no signal; seen at 1080 and 2160
VSR_FRAME_PERIOD_US = 0x08  # u16 microseconds, measured: 16666 @60Hz, 20000 @50Hz
VSR_INDEX = 0x16  # u8, ascends 0x00..0x08 and stops
VSR_REFRESH_CHZ = 0x19  # u16 centihertz, nominal: 6000 @60Hz, 5000 @50Hz

# --- COEX-era controller registers (MX/CX/KU, VMP hardware) ----------------
PRESET_SWITCH = 0x0A00_0002  # u8, preset number, 1-based
LAYER_SOURCE = 0x0A00_0003  # 3 bytes: layer, input card, connector
SENDING_CARD_DISPLAY = 0x1000_0100
"""2 bytes: output-card number (0xFF = all), mode 0 normal / 1 blackout / 2 freeze."""
LOW_LATENCY = 0x1000_0111  # u8
THREE_D_ENABLE = 0x1000_0116  # u8
THREE_D_EYE = 0x1000_1118  # u8 0 right / 1 left
WORKING_MODE = 0x0008_FFF2  # u8 0 send-only / 1 all-in-one

CONFIDENCE: dict[int, str] = {
    DEVICE_TYPE: "official (MCTRL 660 Pro protocol, NovaLCT probe)",
    COMMUNICATION_PROTOCOL: "derived (decompiled AddressMapping)",
    MAX_PACKET_PROBE: "derived (NovaLCT ControllerProcessor)",
    MAX_PACKET_SIZE: "derived (NovaLCT ControllerProcessor)",
    CONTROLLER_SN_HIGH: "derived (decompiled AddressMapping)",
    DEVICE_NAME_SPACE: "derived (NovaLCT ControllerProcessor)",
    SAVE_SENDER_PARAMETERS: "official (M3 protocol 3.15 Parameter Store)",
    RETURN_FACTORY_VALUES: "official (M3 protocol 3.4)",
    GAMMA: "derived (decompiled AddressMapping)",
    GLOBAL_BRIGHTNESS: "official (COEX central control, M3 protocol 3.3)",
    RED_BRIGHTNESS: "official (M3 protocol 3.3)",
    KILL_MODE: "official (COEX central control 3.2.3, MCTRL 660 Pro)",
    SELF_TEST_MODE: "official (M3 protocol 3.12.1)",
    LOCK_MODE: "official (COEX central control 3.2.4)",
    LOW_DELAY: "derived (decompiled AddressMapping)",
    DVI_SELECT: "official (MCTRL 660 Pro input switching)",
    BRIGHTNESS_16BIT: "derived (decompiled AddressMapping)",
    RECEIVER_MONITORING: "official (M3 protocol 3.1.1)",
    RECEIVING_CARD_INFO: "official (M3 protocol 3.9, frames checksum-verified)",
    RECEIVING_CARD_FIRMWARE: "official (M3 protocol 3.9)",
    RED_GAMMA_TABLE: "derived (decompiled AddressMapping)",
    SCREEN_CONFIG_SPACE: "derived (decompiled AddressMapping)",
    VIDEO_SOURCE_STATE: "derived (decompiled AddressMapping)",
    PRESET_SWITCH: "official (COEX central control 3.3)",
    LAYER_SOURCE: "official (COEX central control 3.6)",
    SENDING_CARD_DISPLAY: "official (COEX central control 3.5)",
    LOW_LATENCY: "official (COEX central control 3.4.2)",
    THREE_D_ENABLE: "official (COEX central control 3.4.4)",
    THREE_D_EYE: "official (COEX central control 3.4.6)",
    WORKING_MODE: "official (COEX central control 3.4.8)",
}


#: What real hardware showed, as distinct from where the address came from.
#:
#: ``CONFIDENCE`` records provenance -- which document or decompiled source an
#: address came from. This records the separate question of what a bench unit
#: actually did when the address was read. The two are independent: a register
#: can be OFFICIAL and absent from a given model, or derived and clearly present.
#:
#: "implemented" here means the address is backed by real storage, established
#: with the poison-read discriminator below -- **not** that the documented
#: semantics hold. ``WORKING_MODE`` is the cautionary case: the address is
#: backed, but it reads 0x54 on a UHD Jr, which is neither of the two documented
#: values, so its meaning on that model is unknown.
#:
#: Reproduced across a power cycle of the unit on 2026-08-26.
OBSERVED: dict[int, str] = {
    CONTROLLER_MODEL_ID: "uhd-jr: 0x6205, matches the decompiled table",
    COMMUNICATION_PROTOCOL: "uhd-jr: reads 0x0502; meaning unconfirmed",
    MAX_PACKET_PROBE: "uhd-jr: 0xA8 marker present exactly as documented",
    MAX_PACKET_SIZE: "uhd-jr: 2048",
    CONTROLLER_SN_HIGH: "uhd-jr: 16:04:11:00:c1:c9:2d:00 -- NOT the MAC, which "
                        "is 54:b5:6c:08:5d:49 on the same unit",
    DEVICE_NAME_SPACE: "uhd-jr: implemented, all zeros (unit has no name set)",
    GAMMA: "uhd-jr: sending card reads 0xFF, receiving cards read 0x1C -- like "
           "GLOBAL_BRIGHTNESS, the two levels disagree",
    GLOBAL_BRIGHTNESS: "uhd-jr: sending card reads 0xFF while its receiving "
                       "cards read 0xAA (67%). The sending-card register is NOT "
                       "the wall's brightness -- read the cards for that",
    BRIGHTNESS_16BIT: "uhd-jr: implemented, reads 0x0000",
    DVI_SELECT: "uhd-jr: backed by storage (0/4 poison trials echoed) but NOT "
                "the input selector -- reads 0x00 on DisplayPort, HDMI and "
                "DVI 1 alike. The UHD Jr's input register is UNKNOWN",
    LOW_DELAY: "uhd-jr: implemented, reads 0x00",
    KILL_MODE: "uhd-jr: implemented, reads 0x00 (not blacked out)",
    SELF_TEST_MODE: "uhd-jr: implemented, reads 0x00 (no test pattern)",
    LOCK_MODE: "uhd-jr: implemented, reads 0x00 (not frozen)",
    SCREEN_CONFIG_SPACE: "uhd-jr: implemented",
    VIDEO_SOURCE_STATE: "uhd-jr: an ARRAY of 32-byte per-connector records, not "
                        "a flat block. Records 0-7 are input connectors, record "
                        "8 is the 3840x2160 output canvas, beyond that is "
                        "unmapped. Per record: u16 width +0x04, u16 height "
                        "+0x06 (both 0 = no signal), u16 measured frame period "
                        "in microseconds +0x08, u8 record index +0x16, u16 "
                        "refresh in centihertz +0x19. Record 1 = HDMI, proven "
                        "by plug/unplug. See docs/read-only-monitoring.md",
    SENDING_CARD_DISPLAY: "uhd-jr: implemented, reads 0x0000",
    LOW_LATENCY: "uhd-jr: implemented, reads 0x00",
    WORKING_MODE: "uhd-jr: implemented, reads 0x54 -- NOT one of the documented "
                  "0/1 values; semantics unknown on this model",
    RGB_BRIGHTNESS: "uhd-jr: sending card ff ff ff ff; card p0c0 also ff ff ff ff",
    BRIGHTNESS_16BIT: "uhd-jr: implemented, reads 0x0000",
    PRESET_SWITCH: "uhd-jr: implemented, reads 0x01",
    LAYER_SOURCE: "uhd-jr: implemented, reads 00 01 01",
    THREE_D_ENABLE: "uhd-jr: implemented, reads 0x00",
    THREE_D_EYE: "uhd-jr: implemented, reads 0x00",
    SOFTWARE_SPACE: "uhd-jr sending card: opens 4e 53 53 44 -- ASCII \"NSSD\", a "
                    "magic marker. Same address is RED_GAMMA_TABLE on a "
                    "receiving card, so this overlap is real, not a slip",
    RED_GAMMA_TABLE: "uhd-jr card p0c0: 00 00 08 00 10 00 18 00 ... -- a linear "
                     "u16 ramp (0, 8, 16, 24), which is what a gamma table "
                     "should look like untouched",
    RECEIVING_CARD_INFO: "uhd-jr chain: present cards answer model+firmware, "
                         "absent positions answer ack=TIMEOUT. Unaffected by "
                         "the stale-buffer behaviour, so it can be trusted",
    CABINET_PIXELS_A: "uhd-jr chain: 104 on all 30 cards",
    CABINET_PIXELS_B: "uhd-jr chain: 208 on all 30 cards",
    RECEIVER_MONITORING: "uhd-jr chain: §3.1.1 decode confirmed on 30 cards -- "
                         "temperature 33-37C, voltage 4.2-4.3V, humidity "
                         "correctly invalid where there is no sensor",
}

#: Addresses a bench unit does **not** implement, per model.
#:
#: These matter because an unimplemented address does not error and does not
#: read zero -- it returns the previous read's payload (see the module note).
#: Recording the negative result is what stops the next person rediscovering it.
NOT_IMPLEMENTED: dict[str, dict[int, str]] = {
    "uhd-jr": {
        0x0220_002D: "VX4S input select: echoes the previous response, 8/8 trials",
        0x0220_0022: "NovaPro HD input select: echoes the previous response, 8/8",
    },
}


BLOCKS: dict[int, int] = {
    DEVICE_NAME_SPACE: 88,
    RECEIVER_MONITORING: 0x100,
    RED_GAMMA_TABLE: 512,
    GREEN_GAMMA_TABLE: 512,
    BLUE_GAMMA_TABLE: 512,
    VIDEO_SOURCE_STATE: 64,
    SCREEN_CONFIG_SPACE: 15,
}
"""Registers that are blocks rather than scalars, and how long they are.

Used when reading captures: an access partway into a block belongs to that
block, and should not be reported as an unknown register.
"""


class TestPattern(IntEnum):
    """Values for :data:`SELF_TEST_MODE` (M3 protocol, receiving-card table)."""

    NORMAL = 0x00
    RESERVED = 0x01
    RED = 0x02
    GREEN = 0x03
    BLUE = 0x04
    WHITE = 0x05
    HORIZONTAL_LINE = 0x06
    VERTICAL_LINE = 0x07
    DIAGONAL_LINE = 0x08
    GRAYSCALE = 0x09
    AGING = 0x0A


class DisplayMode(IntEnum):
    """Values for :data:`SENDING_CARD_DISPLAY` byte 2 and the COEX HTTP API."""

    NORMAL = 0
    BLACKOUT = 1
    FREEZE = 2


class InputSource(IntEnum):
    """Values for :data:`DVI_SELECT`.

    Only the three confirmed by the MCTRL 660 Pro document are listed; other
    generations renumber this register, so probe before trusting it.
    """

    SDI = 0x01
    HDMI = 0x05
    DVI = 0x58


NORMAL = 0x00
ENGAGED = 0xFF
"""Receiving-card KILL_MODE / LOCK_MODE use 0xFF for "on", not 0x01."""


def brightness_byte(percent: float) -> int:
    """Map 0..100 % onto the 0..255 register value NovaLCT writes."""
    if not 0.0 <= percent <= 100.0:
        raise ValueError("percent must be within 0..100")
    return round(percent * 255 / 100)
