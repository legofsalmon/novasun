"""COEX SNMP OIDs -- the best read-only monitoring surface NovaStar publishes.

For a monitoring tool this beats polling the HTTP API: SNMP is read-only by
construction on the GET side, it is what NovaStar documents for exactly this
purpose, and the controller can *push* changes as traps rather than being
polled at all.

This module deliberately contains **no SNMP client**. Every platform already has
a good one (pysnmp, net-snmp, a Go or Node library), and a hand-rolled ASN.1
encoder would be a liability. What is here is the OID map from NovaStar's *SNMP
Protocol Instructions V1.4.0*, transcribed with its enumerations, so a consumer
can point its own SNMP stack at the right numbers.

Two operational preconditions, both of which matter to a passive observer:

* **SNMP must already be enabled** on the controller. Turning it on is a write
  -- the front panel, or ``CoexClient.set_snmp`` -- so a strictly read-only tool
  cannot enable it itself and should report it as unavailable instead.
* **Traps need a reporting target configured**, which is also a write. Polling
  with GET needs neither.

Applies to MX40 Pro, MX30, MX20, KU20, MX6000 Pro, CX40 Pro (VMP V1.4.0+).
"""

from __future__ import annotations

from dataclasses import dataclass

ENTERPRISE = "1.3.6.1.4.1.319"
"""NovaStar's private enterprise arc, per the SNMP document."""

CONTROLLER = f"{ENTERPRISE}.10.10"
SCREEN = f"{ENTERPRISE}.10.20"


@dataclass(frozen=True)
class Oid:
    """One monitoring item.

    ``oid`` may contain ``N``, ``Y`` or ``M`` placeholders: an index from 1 to
    the count returned by the corresponding count OID. Substitute with
    :meth:`at`.
    """

    oid: str
    kind: str
    description: str
    values: dict[int, str] | None = None

    def at(self, *indices: int) -> str:
        """Fill the ``N``/``Y``/``M`` placeholders, in order of appearance."""
        parts = self.oid.split(".")
        remaining = list(indices)
        filled = []
        for part in parts:
            if part in ("N", "Y", "M"):
                if not remaining:
                    raise ValueError(f"{self.oid} needs more indices than {indices}")
                filled.append(str(remaining.pop(0)))
            else:
                filled.append(part)
        if remaining:
            raise ValueError(f"too many indices for {self.oid}: {indices}")
        return ".".join(filled)


NORMAL_ABNORMAL = {0: "normal", 1: "abnormal"}
PRIMARY_BACKUP = {0: "primary", 1: "backup"}
CONNECTED = {0: "connected", 1: "disconnected"}

SIGNAL_STATUS = {0: "not inserted", 1: "signal present", 2: "inserted, no signal"}

SOURCE_TYPE = {
    0: "DVI",
    1: "Dual DVI",
    2: "HDMI 1.4",
    3: "HDMI 2.0",
    4: "DP 1.1",
    5: "DP 1.2",
    6: "DP 1.4",
    7: "3G-SDI",
    8: "6G-SDI",
    9: "12G-SDI",
    10: "PIP video",
    16: "HDMI 1.3",
    17: "HDMI 2.1",
    18: "PCIe",
    19: "SerDes",
    20: "LVDS",
    21: "V-by-One",
    22: "ST 2110",
    224: "internal source",
}

SYNC_TYPE = {0: "current video source", 1: "genlock", 2: "internal"}

# --- controller identity ----------------------------------------------------

CONTROLLER_TIME = Oid(f"{CONTROLLER}.1.1", "string", "Controller date and time")
CONTROLLER_MODEL = Oid(f"{CONTROLLER}.1.2", "string", "Controller model")
CONTROLLER_FIRMWARE = Oid(f"{CONTROLLER}.1.3", "string", "Firmware version")
CONTROLLER_NAME = Oid(f"{CONTROLLER}.1.4", "string", "Controller name")
CONTROLLER_ROLE = Oid(
    f"{CONTROLLER}.1.5", "int", "Primary or backup controller", PRIMARY_BACKUP
)
CONTROLLER_SERIAL = Oid(f"{CONTROLLER}.1.6", "string", "Serial number")
CONTROLLER_MAC = Oid(f"{CONTROLLER}.1.7", "string", "MAC address")
CONTROLLER_IP = Oid(f"{CONTROLLER}.1.8", "string", "IP address")

# --- controller health ------------------------------------------------------

TEMPERATURE_POINT_COUNT = Oid(f"{CONTROLLER}.10.1", "int", "Mainboard temperature points")
TEMPERATURE_POINT_NAME = Oid(f"{CONTROLLER}.10.2.N.1", "string", "Temperature point name")
TEMPERATURE_POINT_STATUS = Oid(
    f"{CONTROLLER}.10.2.N.2", "int", "Temperature point status", NORMAL_ABNORMAL
)
TEMPERATURE_POINT_VALUE = Oid(f"{CONTROLLER}.10.2.N.3", "int", "Temperature reading")

VOLTAGE_POINT_COUNT = Oid(f"{CONTROLLER}.10.3", "int", "Mainboard voltage points")
VOLTAGE_POINT_NAME = Oid(f"{CONTROLLER}.10.4.N.1", "string", "Voltage point name")
VOLTAGE_POINT_STATUS = Oid(
    f"{CONTROLLER}.10.4.N.2", "int", "Voltage point status", NORMAL_ABNORMAL
)
VOLTAGE_POINT_VALUE = Oid(f"{CONTROLLER}.10.4.N.3", "int", "Voltage reading")

FAN_COUNT = Oid(f"{CONTROLLER}.10.5", "int", "Number of fans")
FAN_NAME = Oid(f"{CONTROLLER}.10.6.N.1", "string", "Fan name")
FAN_STATUS = Oid(f"{CONTROLLER}.10.6.N.2", "int", "Fan status", NORMAL_ABNORMAL)

# --- output cards, ethernet ports and receiving cards -----------------------

OUTPUT_SLOT_STATUS = Oid(f"{CONTROLLER}.30.2", "int", "Output card slot status", CONNECTED)
OUTPUT_CARD_FIRMWARE = Oid(f"{CONTROLLER}.30.3.N.1", "counter64", "Output card firmware")
OUTPUT_CARD_NAME = Oid(f"{CONTROLLER}.30.3.N.2", "string", "Output card name")
OUTPUT_CARD_ROLE = Oid(
    f"{CONTROLLER}.30.3.N.3", "string", "Output card primary/backup", PRIMARY_BACKUP
)
OUTPUT_CARD_SERIAL = Oid(f"{CONTROLLER}.30.3.N.4", "int", "Output card serial")

ETHERNET_PORT_COUNT = Oid(f"{CONTROLLER}.30.5.N.1", "int", "Ethernet ports on output card N")
ETHERNET_PORT_SPEED = Oid(f"{CONTROLLER}.30.5.N.2", "int", "Ethernet port link speed")
ETHERNET_PORT_STATUS = Oid(
    f"{CONTROLLER}.30.5.N.3", "int", "Ethernet port status", NORMAL_ABNORMAL
)
RECEIVING_CARDS_ONLINE = Oid(
    f"{CONTROLLER}.30.5.N.4.Y.1", "counter64", "Online receiving cards on port Y of card N"
)
RECEIVING_CARD_TEMPERATURE_STATUS = Oid(
    f"{CONTROLLER}.30.6.N.1.Y.1.M",
    "int",
    "Temperature status of receiving card M, port Y, output card N",
    NORMAL_ABNORMAL,
)
RECEIVING_CARD_VOLTAGE_STATUS = Oid(
    f"{CONTROLLER}.30.6.N.1.Y.2.M",
    "counter64",
    "Voltage status of receiving card M, port Y, output card N",
    NORMAL_ABNORMAL,
)

# --- input cards and sources ------------------------------------------------

INPUT_SLOT_COUNT = Oid(f"{CONTROLLER}.20.1", "int", "Input card slots")
INPUT_SLOT_STATUS = Oid(f"{CONTROLLER}.20.2", "counter64", "Input card slot status")
INPUT_CARD_FIRMWARE = Oid(f"{CONTROLLER}.20.3.N.1", "string", "Input card firmware")
INPUT_CARD_NAME = Oid(f"{CONTROLLER}.20.3.N.2", "string", "Input card name")
INPUT_CARD_ROLE = Oid(f"{CONTROLLER}.20.3.N.3", "int", "Input card primary/backup", PRIMARY_BACKUP)
INPUT_CARD_SERIAL = Oid(f"{CONTROLLER}.20.3.N.4", "string", "Input card serial")

INPUT_SOURCE_COUNT = Oid(f"{CONTROLLER}.20.5.N.1", "int", "Input sources on card N")
INPUT_SOURCE_SIGNAL = Oid(
    f"{CONTROLLER}.20.5.N.2.Y.1", "int", "Signal status of source Y", SIGNAL_STATUS
)
INPUT_SOURCE_TYPE = Oid(
    f"{CONTROLLER}.20.5.N.2.Y.2", "string", "Connector type of source Y", SOURCE_TYPE
)

# --- screens ----------------------------------------------------------------

SCREEN_COUNT = Oid(f"{SCREEN}.1.1", "int", "Number of screens")
SCREEN_WIDTH = Oid(f"{SCREEN}.1.2.N.2", "int", "Screen width")
SCREEN_HEIGHT = Oid(f"{SCREEN}.1.2.N.3", "int", "Screen height")
SCREEN_FRAME_RATE = Oid(f"{SCREEN}.1.2.N.4", "int", "Screen frame rate")
SCREEN_BRIGHTNESS = Oid(f"{SCREEN}.1.2.N.5", "string", "Screen brightness (read/write)")
SCREEN_SYNC_TYPE = Oid(f"{SCREEN}.1.2.N.6", "int", "Sync source", SYNC_TYPE)
SCREEN_SYNC_FRAME_RATE = Oid(f"{SCREEN}.1.2.N.7", "int", "Sync frame rate")


#: What a monitoring pane most likely wants, as a starting walk.
MONITORING_SET: tuple[Oid, ...] = (
    CONTROLLER_MODEL,
    CONTROLLER_NAME,
    CONTROLLER_SERIAL,
    CONTROLLER_IP,
    CONTROLLER_FIRMWARE,
    CONTROLLER_ROLE,
    TEMPERATURE_POINT_COUNT,
    VOLTAGE_POINT_COUNT,
    FAN_COUNT,
    OUTPUT_SLOT_STATUS,
    INPUT_SLOT_COUNT,
    SCREEN_COUNT,
)

PROVENANCE = (
    "COEX SNMP Protocol Instructions V1.4.0 (official, 2024). OIDs and "
    "enumerations transcribed from sections 5.1.1-5.1.9. Not yet exercised "
    "against hardware."
)


def describe(oid: Oid, value: object) -> str:
    """Render a value using the OID's enumeration, when it has one."""
    if oid.values and isinstance(value, int) and value in oid.values:
        return f"{oid.values[value]} ({value})"
    if oid.values and isinstance(value, str) and value.isdigit():
        numeric = int(value)
        if numeric in oid.values:
            return f"{oid.values[numeric]} ({numeric})"
    return str(value)
