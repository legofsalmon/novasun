"""Register addresses on the NovaStar register bus.

Every entry here is corroborated by at least one of:

* an official NovaStar document (`docs/sources.md` lists them),
* the ``AddressMapping`` enum generated from decompiled NovaLCT assemblies by
  the `sarakusha/novastar` project,
* a captured frame reproduced in a published tool.

``CONFIDENCE`` records which. Treat ``derived`` entries as good starting points
to confirm against your own hardware, not as guarantees; register semantics vary
across controller generations and receiving-card chipsets.
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
CONTROLLER_SN_HIGH = 0x0000_0016  # 8 bytes, MAC/serial
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
"""0x100 bytes of receiving-card monitoring: temperature, voltage, fans, cables."""

RED_GAMMA_TABLE = 0x0500_0000  # 512 bytes
GREEN_GAMMA_TABLE = 0x0500_0200  # 512 bytes
BLUE_GAMMA_TABLE = 0x0500_0400  # 512 bytes

SCREEN_CONFIG_SPACE = 0x0210_0000  # sending-card screen configuration block
SOFTWARE_SPACE = 0x0500_0000  # NovaLCT's own "software space" on the sending card
VIDEO_SOURCE_STATE = 0x1301_0000  # 64 bytes of input-signal state

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
