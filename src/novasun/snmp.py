"""COEX SNMP OIDs -- the best read-only monitoring surface NovaStar publishes.

For a monitoring tool this beats polling the HTTP API: SNMP is read-only by
construction on the GET side, it is what NovaStar documents for exactly this
purpose, and the controller can *push* changes as traps rather than being
polled at all.

This module deliberately contains **no SNMP client**. Every platform already has
a good one (pysnmp, net-snmp, a Go or Node library), and a hand-rolled ASN.1
encoder would be a liability. What is here is the OID map from NovaStar's *SNMP
Protocol Instructions V1.4.0*, transcribed with its enumerations, so a consumer
can point its own SNMP stack at the right numbers -- plus two pure helpers for
the value shapes the one controller that has answered actually sent.

Two operational preconditions, both of which matter to a passive observer:

* **SNMP must already be enabled** on the controller. Turning it on is a write
  -- the front panel, or ``CoexClient.set_snmp`` -- so a strictly read-only tool
  cannot enable it itself and should report it as unavailable instead. The HTTP
  body that works is ``{"state": true}`` (OBSERVED on one MX30, firmware
  V1.5.1, 2026-09-26); ``{"value": true}``, which ``set_snmp`` sent until then,
  drew a Success envelope and changed nothing. Read
  ``/api/v1/device/snmpstate`` back after the PUT rather than trusting its
  Success (REASONED from that one endpoint).
* **Traps need a reporting target configured**, which is also a write. Polling
  with GET needs neither.

Applies to MX40 Pro, MX30, MX20, KU20, MX6000 Pro, CX40 Pro (VMP V1.4.0+), per
the document (OFFICIAL).

What one controller showed
--------------------------

The map has met hardware once: one MX30, firmware V1.5.1 (read through
:data:`CONTROLLER_FIRMWARE`), on 2026-09-26 with VMP closed, SNMPv2c community
``public``, one walk of the enterprise arc, walks of the MIB-2 system group,
and ``sysDescr`` GETs (one answered with SNMP on; the others, sent with it off,
timed out). Every OBSERVED note in this module has that scope and no wider;
nothing here is OBSERVED for another unit, model or firmware. See :data:`PROVENANCE` for what
matched and what did not. In short:

* **Identity is readable** -- :data:`CONTROLLER_MODEL` and
  :data:`CONTROLLER_FIRMWARE` answered, and of the surfaces seen SNMP is the
  only one that gives either; the HTTP API gives neither (OBSERVED).
* **Status values documented as 0/1 arrived as 64-bit masks** (OBSERVED
  structure). Reading them one bit per index is REASONED; see
  :func:`decode_status_mask`.
* **Some STRING values carry ``"ERROR: ..."`` text in place of data**,
  including in an integer column (OBSERVED); see :func:`present_value`.
* **Readings are scaled** -- x100 on temperature, voltage and frame rates
  (REASONED); see ``Oid.scale``.
* **Several kinds differ from this transcription**; each affected ``Oid``
  says so in its ``note``, and its ``kind`` is now the observed one.
* **The MIB-2 system group is not served** (OBSERVED); probe reachability with
  :data:`REACHABILITY_PROBE` instead of ``sysDescr``/``sysUpTime`` (REASONED).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

ENTERPRISE = "1.3.6.1.4.1.319"
"""NovaStar's private enterprise arc, per the SNMP document."""

CONTROLLER = f"{ENTERPRISE}.10.10"
SCREEN = f"{ENTERPRISE}.10.20"

MIB2_SYSTEM = "1.3.6.1.2.1.1"
"""The MIB-2 system group (``sysDescr``, ``sysUpTime``, ...).

OBSERVED not served on the MX30 (V1.5.1, 2026-09-26): a v2c GET of
``sysDescr.0`` drew error-status noSuchName -- a v1-style error inside a v2c
reply, as net-snmp reports it -- and a walk of the group returned nothing.
Other MIB-2 groups (interfaces and the rest) were not walked: UNKNOWN. Do not
read this as "MIB-2 is not served".
"""

KINDS = frozenset({"int", "string", "counter64"})
"""The value types an :class:`Oid` may declare."""


@dataclass(frozen=True)
class Oid:
    """One monitoring item.

    ``oid`` may contain ``N``, ``Y`` or ``M`` placeholders: an index from 1 to
    the count returned by the corresponding count OID. Substitute with
    :meth:`at`.
    """

    oid: str
    kind: str
    """The value type to expect: the documented one, or the OBSERVED one where
    the MX30 differed (``note`` then says so)."""
    description: str
    values: dict[int, str] | None = None
    """The document's enumeration (OFFICIAL), where it has one."""
    scale: int = 1
    """Divide the raw value by this to get ``unit``. Every scale other than 1
    is REASONED from one MX30; none was transcribed from the document."""
    unit: str = ""
    per_bit: bool = False
    """The value is a 64-bit mask, not a single enum value (OBSERVED on the
    MX30). ``values`` then applies to each bit (REASONED), and
    :func:`describe` does not map the whole value through it."""
    note: str = ""
    """Where the hardware and the document or this transcription part ways,
    with provenance labels."""

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

# Shared wording for the three kinds this transcription had wrong against the
# MX30. Which side was wrong is not established: the document was not
# re-checked, and a transcription slip looks likely for the output-card row
# only because the input-card row matched (REASONED).
_KIND_WAS = (
    "; typed {was} here until 2026-09-26. Whether the transcription or the "
    "document is at fault is not established"
)

# --- controller identity ----------------------------------------------------

CONTROLLER_TIME = Oid(
    f"{CONTROLLER}.1.1", "string", "Controller date and time",
    note="OBSERVED 'YYYY-MM-DD HH:MM:SS', one hour ahead of UTC on the day; that "
    "this is the controller's local zone rather than a misset clock is REASONED",
)
CONTROLLER_MODEL = Oid(
    f"{CONTROLLER}.1.2", "string", "Controller model",
    note="OBSERVED 'MX30' -- the first time the model was read from the device "
    "rather than reported. Of the surfaces seen, SNMP is the only one that gives it",
)
CONTROLLER_FIRMWARE = Oid(
    f"{CONTROLLER}.1.3", "string", "Firmware version",
    note="OBSERVED 'V1.5.1', confirming the operator's report. Of the surfaces "
    "seen, SNMP is the only one that gives it",
)
CONTROLLER_NAME = Oid(
    f"{CONTROLLER}.1.4", "string", "Controller name",
    note="OBSERVED served. That it equals HTTP monitor/info's name rests on a "
    "comparison made before the evidence was masked",
)
CONTROLLER_ROLE = Oid(
    f"{CONTROLLER}.1.5", "int", "Primary or backup controller",
    note="The document's enum is PRIMARY_BACKUP, 1 = backup (OFFICIAL). OBSERVED "
    "1 on an MX30 that drove its wall alone and whose HTTP /device/backup was "
    "four empty strings, so the meaning on that firmware is UNKNOWN. The enum "
    "is deliberately not attached: do not display 'backup' from this OID alone",
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
TEMPERATURE_POINT_VALUE = Oid(
    f"{CONTROLLER}.10.2.N.3", "int", "Temperature reading", scale=100, unit="°C",
    note="OBSERVED 3100. REASONED x100 (31.00 °C): near HTTP monitor/info's "
    "main-board 32, read at a different time -- a weak match. 3100 carries no "
    "sub-degree information, so whether SNMP resolves finer than 1 °C is UNKNOWN",
)

VOLTAGE_POINT_COUNT = Oid(f"{CONTROLLER}.10.3", "int", "Mainboard voltage points")
VOLTAGE_POINT_NAME = Oid(f"{CONTROLLER}.10.4.N.1", "string", "Voltage point name")
VOLTAGE_POINT_STATUS = Oid(
    f"{CONTROLLER}.10.4.N.2", "int", "Voltage point status", NORMAL_ABNORMAL
)
VOLTAGE_POINT_VALUE = Oid(
    f"{CONTROLLER}.10.4.N.3", "int", "Voltage reading", scale=100, unit="V",
    note="OBSERVED 1156. REASONED x100 (11.56 V): exactly HTTP monitor/info's "
    "mainBoardVoltage 11.56 -- the strongest of the scale matches",
)

FAN_COUNT = Oid(f"{CONTROLLER}.10.5", "int", "Number of fans")
FAN_NAME = Oid(
    f"{CONTROLLER}.10.6.N.1", "string", "Fan name",
    note="OBSERVED equal to HTTP monitor/info fanInfos[].fanName on all three fans",
)
FAN_STATUS = Oid(f"{CONTROLLER}.10.6.N.2", "int", "Fan status", NORMAL_ABNORMAL)

# --- output cards, ethernet ports and receiving cards -----------------------

OUTPUT_SLOT_STATUS = Oid(
    f"{CONTROLLER}.30.2", "counter64", "Output card slot status mask", CONNECTED,
    per_bit=True,
    note="OBSERVED Counter64 0xFFFFFFFFFFFFFFFE (bit 0 clear) where the document "
    "gives a 0/1 CONNECTED value" + _KIND_WAS.format(was="int") + ". REASONED: "
    "one bit per slot, LSB = slot 1, the enum per bit -- slot 1 present",
)
OUTPUT_CARD_FIRMWARE = Oid(
    f"{CONTROLLER}.30.3.N.1", "string", "Output card firmware",
    note="OBSERVED STRING 'V1.5.1'" + _KIND_WAS.format(was="counter64"),
)
OUTPUT_CARD_NAME = Oid(
    f"{CONTROLLER}.30.3.N.2", "string", "Output card name",
    note="OBSERVED served, as an empty string",
)
OUTPUT_CARD_ROLE = Oid(
    f"{CONTROLLER}.30.3.N.3", "int", "Output card primary/backup", PRIMARY_BACKUP,
    note="OBSERVED INTEGER 0" + _KIND_WAS.format(was="string"),
)
OUTPUT_CARD_SERIAL = Oid(
    f"{CONTROLLER}.30.3.N.4", "string", "Output card serial",
    note="OBSERVED STRING" + _KIND_WAS.format(was="int"),
)

ETHERNET_PORT_COUNT = Oid(
    f"{CONTROLLER}.30.5.N.1", "int", "Ethernet ports on output card N",
    note="OBSERVED 10 on output card 1 of the MX30, agreeing with ten type-0 "
    "entries in HTTP monitor/info outputStatus (devices.COEX_MODELS carries it)",
)
ETHERNET_PORT_SPEED = Oid(
    f"{CONTROLLER}.30.5.N.2", "int", "Ethernet port link speed",
    note="OBSERVED 0 with five links up; meaning UNKNOWN",
)
ETHERNET_PORT_STATUS = Oid(
    f"{CONTROLLER}.30.5.N.3", "counter64", "Ethernet port status mask", NORMAL_ABNORMAL,
    per_bit=True,
    note="OBSERVED Counter64 0xFFFFFFFFFFFFFFE0 (bits 0-4 clear) where the "
    "document gives a 0/1 value" + _KIND_WAS.format(was="int") + ". REASONED: "
    "one bit per port, LSB = port 1 -- ports 1-5 up, which fits HTTP linkStatus "
    "true on exactly outputs 2048-2052. Cards were online on ports 1, 3 and 5 "
    "only, so this is link state, not cabinet presence (REASONED)",
)
RECEIVING_CARDS_ONLINE = Oid(
    f"{CONTROLLER}.30.5.N.4.Y.1", "int", "Online receiving cards on port Y of card N",
    note="OBSERVED INTEGER on the three ports carrying cards, and on the other "
    "seven the STRING 'ERROR: there are no cabinets in port ' (trailing space, "
    "no port number) -- accept a string in this column and pass it through "
    "present_value()" + _KIND_WAS.format(was="counter64") + ". OBSERVED: the "
    "counts sum to the undocumented .30.4.1.5 and to HTTP cabinet count. "
    "REASONED: SNMP port Y = HTTP outputID 2048 + (Y - 1)",
)
# The document gives the two receiving-card statuses per card:
#
#     RECEIVING_CARD_TEMPERATURE_STATUS  {CONTROLLER}.30.6.N.1.Y.1.M
#     RECEIVING_CARD_VOLTAGE_STATUS      {CONTROLLER}.30.6.N.1.Y.2.M
#
# (card M on port Y of output card N, a 0/1 NORMAL_ABNORMAL value; the first
# was typed int here, the second counter64). The MX30's walk served neither
# form -- 0 of 240 each -- and served a per-port Counter64 at .Y.1 and .Y.2
# instead (OBSERVED). Only a walk was made: what a direct GET of the per-card
# form returns is unobserved. The two constants below carry the observed form.
_RECEIVING_CARD_MASK = (
    "OBSERVED form: a per-port Counter64, identical for temperature and voltage "
    "on every port. The documented per-card form .30.6.N.1.Y.{leaf}.M was absent "
    "from the walk (0 of 240); no direct GET of it was sent. OBSERVED values: "
    "0xFFFFFFFFFF000000 on the three ports carrying 24 cards each, all ones on "
    "the other seven. REASONED: one bit per card, unused bits set, so the "
    "documented index M collapses into a bit position; with every card normal, "
    "'0 = normal' cannot be told apart from '0 = card present'. Bit order within "
    "a port is UNKNOWN"
)
RECEIVING_CARD_TEMPERATURE_STATUS = Oid(
    f"{CONTROLLER}.30.6.N.1.Y.1",
    "counter64",
    "Temperature status of the receiving cards on port Y, output card N, one bit per card",
    NORMAL_ABNORMAL,
    per_bit=True,
    note=_RECEIVING_CARD_MASK.format(leaf=1),
)
RECEIVING_CARD_VOLTAGE_STATUS = Oid(
    f"{CONTROLLER}.30.6.N.1.Y.2",
    "counter64",
    "Voltage status of the receiving cards on port Y, output card N, one bit per card",
    NORMAL_ABNORMAL,
    per_bit=True,
    note=_RECEIVING_CARD_MASK.format(leaf=2),
)

# --- input cards and sources ------------------------------------------------

INPUT_SLOT_COUNT = Oid(f"{CONTROLLER}.20.1", "int", "Input card slots")
INPUT_SLOT_STATUS = Oid(
    f"{CONTROLLER}.20.2", "counter64", "Input card slot status mask", per_bit=True,
    note="OBSERVED Counter64 0xFFFFFFFFFFFFFFFE (bit 0 clear). REASONED: one bit "
    "per slot, LSB = slot 1 -- slot 1 present",
)
INPUT_CARD_FIRMWARE = Oid(f"{CONTROLLER}.20.3.N.1", "string", "Input card firmware")
INPUT_CARD_NAME = Oid(
    f"{CONTROLLER}.20.3.N.2", "string", "Input card name",
    note="OBSERVED served, as an empty string",
)
INPUT_CARD_ROLE = Oid(f"{CONTROLLER}.20.3.N.3", "int", "Input card primary/backup", PRIMARY_BACKUP)
INPUT_CARD_SERIAL = Oid(f"{CONTROLLER}.20.3.N.4", "string", "Input card serial")

INPUT_SOURCE_COUNT = Oid(
    f"{CONTROLLER}.20.5.N.1", "int", "Input sources on card N",
    note="OBSERVED 5 where the HTTP API lists six sources: the internal "
    "generator is not among them",
)
INPUT_SOURCE_SIGNAL = Oid(
    f"{CONTROLLER}.20.5.N.2.Y.1", "int", "Signal status of source Y", SIGNAL_STATUS,
    note="OBSERVED to agree with HTTP sourceStatus on all five sources",
)
INPUT_SOURCE_TYPE = Oid(
    f"{CONTROLLER}.20.5.N.2.Y.2", "string", "Connector type of source Y", SOURCE_TYPE,
    note="OBSERVED STRING with a trailing space ('HDMI2.0 ', 'DP1.1 ', "
    "'3G-SDI ', ...), not the integer SOURCE_TYPE keys on. The enum (OFFICIAL) "
    "maps only integer values, which this firmware did not send; describe() "
    "passes the string through stripped and guesses no code for it",
)

# --- screens ----------------------------------------------------------------

SCREEN_COUNT = Oid(f"{SCREEN}.1.1", "int", "Number of screens")
SCREEN_WIDTH = Oid(
    f"{SCREEN}.1.2.N.2", "int", "Screen width",
    note="OBSERVED equal to the HTTP canvas width",
)
SCREEN_HEIGHT = Oid(
    f"{SCREEN}.1.2.N.3", "int", "Screen height",
    note="OBSERVED equal to the HTTP canvas height",
)
SCREEN_FRAME_RATE = Oid(
    f"{SCREEN}.1.2.N.4", "int", "Screen frame rate", scale=100, unit="Hz",
    note="OBSERVED 5000. REASONED x100 (50.00 Hz): HTTP masterFrameRate read 50",
)
SCREEN_BRIGHTNESS = Oid(
    f"{SCREEN}.1.2.N.5", "string", "Screen brightness (read/write)", unit="%",
    note="OBSERVED STRING '50.0'. REASONED percent: HTTP /device/cabinet "
    "brightness read 0.5",
)
SCREEN_SYNC_TYPE = Oid(f"{SCREEN}.1.2.N.6", "int", "Sync source", SYNC_TYPE)
SCREEN_SYNC_FRAME_RATE = Oid(
    f"{SCREEN}.1.2.N.7", "int", "Sync frame rate", scale=100, unit="Hz",
    note="OBSERVED 5000. REASONED x100 (50.00 Hz), as SCREEN_FRAME_RATE",
)


#: What a monitoring pane most likely wants, as a starting walk. All twelve
#: were served on the MX30 (OBSERVED). REASONED: keep a multi-varbind GET to
#: OIDs known to be served -- the one absent OID asked for came back as a
#: v1-style error-status inside a v2c reply, which may void a whole batch; only
#: single-OID GETs were observed.
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

REACHABILITY_PROBE = CONTROLLER_MODEL
"""The OID to ask when checking that the agent answers.

REASONED: the MIB-2 system group -- the usual ``sysDescr``/``sysUpTime`` probe
-- is not served on the MX30 (OBSERVED, see :data:`MIB2_SYSTEM`), while this
was served in the enterprise walk (OBSERVED). No direct GET of it was sent, so
that it answers a single GET is itself REASONED.
"""


# --- observed but undocumented ----------------------------------------------
#
# Present in the MX30's walk (OBSERVED existence and type) and absent from the
# document as transcribed above. Each entry's meaning carries its own label;
# none is asserted beyond it. Indices appear as placeholders only where the
# entry sits in a documented table; literal indices were the only ones seen.
#
# Also OBSERVED on that walk, and deliberately not described:
#   * existence only, meaning UNKNOWN: the arcs in OBSERVED_UNDOCUMENTED_SUBTREES;
#     two values under .10.10.10.12 carry "ERROR:" text naming a light sensor.
#   * gaps: .10.10.20.4.1.2, .10.10.30.4.1.2 and .10.20.1.2.1.8 are not served
#     between served neighbours.
#   * the walk ended with endOfMibView after .10.200.6: in the agent's view
#     nothing is served past it.

OBSERVED_UNDOCUMENTED: dict[str, Oid] = {
    o.oid: o
    for o in (
        Oid(f"{CONTROLLER}.10.6.N.3", "int", "Fan speed (REASONED)", unit="rpm",
            note="OBSERVED on all three fans. REASONED rpm, only from closeness to "
            "HTTP monitor/info fanInfos[].fanSpeed; no document defines it"),
        Oid(f"{CONTROLLER}.20.4.1.1", "int", "UNKNOWN", note="OBSERVED 0; meaning UNKNOWN"),
        Oid(f"{CONTROLLER}.20.4.1.3", "int", "UNKNOWN",
            note="OBSERVED 0; meaning UNKNOWN. The input-side twin of .30.4.1.3"),
        Oid(f"{CONTROLLER}.20.5.N.2.Y.3", "int", "UNKNOWN",
            note="OBSERVED 0 on source 1 and 2 on sources 2-5; meaning UNKNOWN"),
        Oid(f"{CONTROLLER}.30.1", "int", "Output card slots (REASONED, not asserted)",
            note="OBSERVED 1. REASONED only by symmetry with INPUT_SLOT_COUNT (.20.1)"),
        Oid(f"{CONTROLLER}.30.4.1.1", "int", "UNKNOWN", note="OBSERVED 0; meaning UNKNOWN"),
        Oid(f"{CONTROLLER}.30.4.1.3", "int", "UNKNOWN", note="OBSERVED 0; meaning UNKNOWN"),
        Oid(f"{CONTROLLER}.30.4.1.5", "counter64", "Total receiving cards (REASONED)",
            note="OBSERVED equal to the sum of RECEIVING_CARDS_ONLINE over the ports "
            "and to HTTP cabinet count. REASONED: the total receiving-card count"),
        Oid(f"{CONTROLLER}.30.5.N.4.Y.2", "int", "UNKNOWN",
            note="OBSERVED 7, 7, 7, 7, 5, 5, 1, 1, 1, 1 for Y = 1..10; meaning UNKNOWN"),
        Oid(f"{CONTROLLER}.30.5.N.4.Y.3.1", "int", "UNKNOWN",
            note="OBSERVED Y + 1 on odd Y and -1 on every even Y; meaning UNKNOWN"),
        Oid(f"{CONTROLLER}.30.5.N.4.Y.3.2", "int", "UNKNOWN",
            note="OBSERVED 0 on ports 1 and 3 and 2 on every other port, including "
            "port 5, which carried cards; meaning UNKNOWN"),
        Oid(f"{CONTROLLER}.30.5.N.4.Y.3.3", "int", "UNKNOWN",
            note="OBSERVED equal to .Y.3.2 on every port; meaning UNKNOWN"),
        Oid(f"{SCREEN}.1.2.N.1", "string", "Screen name",
            note="OBSERVED to hold the screen's name, which is show data: never "
            "record a real one"),
        Oid(f"{SCREEN}.1.2.N.9", "int", "Active input width (REASONED)",
            note="OBSERVED equal to the live input signal's width"),
        Oid(f"{SCREEN}.1.2.N.10", "int", "Active input height (REASONED)",
            note="OBSERVED equal to the live input signal's height"),
        Oid(f"{SCREEN}.1.2.N.11", "int", "UNKNOWN", note="OBSERVED 0; meaning UNKNOWN"),
        Oid(f"{SCREEN}.1.2.N.12", "int", "UNKNOWN", note="OBSERVED 500; meaning UNKNOWN"),
    )
}
"""Undocumented OIDs the MX30 served, keyed by OID pattern. Types OBSERVED;
meanings as each entry labels them."""

OBSERVED_UNDOCUMENTED_SUBTREES: tuple[str, ...] = (
    f"{ENTERPRISE}.10.1",
    f"{CONTROLLER}.1.9",
    f"{CONTROLLER}.1.10",
    f"{CONTROLLER}.1.11",
    f"{CONTROLLER}.10.7",
    f"{CONTROLLER}.10.8",
    f"{CONTROLLER}.10.9",
    f"{CONTROLLER}.10.10",
    f"{CONTROLLER}.10.11",
    f"{CONTROLLER}.10.12",
    f"{CONTROLLER}.50",
    f"{CONTROLLER}.60",
    f"{CONTROLLER}.70",
    f"{ENTERPRISE}.10.200",
)
"""Further arcs the MX30 served: existence OBSERVED, meaning UNKNOWN."""


PROVENANCE = (
    "COEX SNMP Protocol Instructions V1.4.0 (OFFICIAL, 2024): OIDs and "
    "enumerations transcribed from sections 5.1.1-5.1.9. Exercised once: one "
    "MX30, firmware V1.5.1, 2026-09-26, VMP closed -- one SNMPv2c walk "
    "(community public) of the enterprise arc, 170 varbinds, and GETs of "
    "sysDescr (one answered noSuchName with SNMP on; the rest timed out with "
    "it off). Matched: 44 of the 46 documented OIDs were served, the two card "
    "names as empty strings. Did not match: the two per-card receiving-card "
    "status forms were absent and a per-port Counter64 was served in their "
    "place (the constants now carry that form); seven kinds differed from this "
    "transcription and now carry the observed kind; status values documented "
    "as 0/1 were 64-bit masks; nine STRING values carried 'ERROR:' text in "
    "place of data, seven of them in RECEIVING_CARDS_ONLINE, an integer "
    "column; INPUT_SOURCE_TYPE "
    "was a string, not the enum's integer; the MIB-2 system group was not "
    "served. Scales on readings are REASONED. Nothing here is OBSERVED for "
    "another unit, model or firmware; each Oid's note carries its own labels."
)


# --- helpers ----------------------------------------------------------------

MASK_BITS = 64
ERROR_PREFIX = "ERROR:"

T = TypeVar("T")


def decode_status_mask(mask: int, count: int) -> tuple[bool, ...]:
    """Split a 64-bit status mask into one boolean per index, 1 to ``count``.

    Element ``i - 1`` is whether bit ``i - 1`` is **set**. Nothing about the
    reading is established beyond the structure: the masks arrived as
    Counter64 values where the document describes a 0/1 status (OBSERVED on
    one MX30), and both of the following are REASONED from that one unit:

    * **Bit order** -- the least significant bit is index 1.
    * **Polarity** -- the documented per-OID enumeration applies per bit, so a
      clear bit is 0 (normal / connected) and a set bit 1 (abnormal /
      disconnected). Unused positions read set. On the receiving-card masks,
      with every card normal, "clear = normal" cannot be told apart from
      "clear = card present".

    ``count`` comes from the matching count OID (for example
    ``ETHERNET_PORT_COUNT`` or ``RECEIVING_CARDS_ONLINE``); bits above it are
    not returned, because on the observed unit they were padding.

    A decoder that reads the 8-byte BER encoding as a signed integer gets
    ``-2`` for ``0xFFFFFFFFFFFFFFFE``; negative values in the signed 64-bit
    range are therefore accepted and read as their two's-complement bit
    pattern. Which encoding the controller sends is UNKNOWN.
    """
    if isinstance(mask, bool) or not isinstance(mask, int):
        raise TypeError(f"a status mask is an integer, not {type(mask).__name__}")
    if not -(1 << (MASK_BITS - 1)) <= mask < (1 << MASK_BITS):
        raise ValueError(f"{mask} does not fit a {MASK_BITS}-bit mask")
    if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= MASK_BITS:
        raise ValueError(f"count must be an integer from 0 to {MASK_BITS}, not {count!r}")
    mask &= (1 << MASK_BITS) - 1
    return tuple(bool(mask >> bit & 1) for bit in range(count))


def is_error_string(value: object) -> bool:
    """Whether ``value`` is firmware error text standing in for data."""
    if isinstance(value, bytes):
        return value.startswith(ERROR_PREFIX.encode())
    return isinstance(value, str) and value.startswith(ERROR_PREFIX)


def present_value(value: T) -> T | None:
    """``value``, or ``None`` when it is an ``"ERROR: ..."`` string.

    OBSERVED on one MX30 (V1.5.1, 2026-09-26): nine STRING values carried such
    text in place of data -- seven ``RECEIVING_CARDS_ONLINE`` ports with no
    cabinets (``"ERROR: there are no cabinets in port "``, with no port
    number), an integer column, and two undocumented values under
    ``.10.10.10.12`` whose text names a light sensor. Reading such a value as
    absent -- not as zero, and not as a label to show -- is a REASONED
    consumer rule.
    """
    return None if is_error_string(value) else value


def describe(oid: Oid, value: object) -> str:
    """Render a value using the OID's enumeration, when it has one.

    A mask (``oid.per_bit``) is never mapped through the enumeration as a
    whole: the enum applies per bit (REASONED); decode it with
    :func:`decode_status_mask`. A string that is not a number is shown with
    surrounding whitespace removed and no code guessed for it --
    ``INPUT_SOURCE_TYPE`` arrived as ``"HDMI2.0 "`` on the MX30 (OBSERVED),
    not as the enumeration's integer.
    """
    if oid.values and not oid.per_bit:
        if isinstance(value, int) and value in oid.values:
            return f"{oid.values[value]} ({value})"
        if isinstance(value, str) and value.strip().isdigit():
            numeric = int(value)
            if numeric in oid.values:
                return f"{oid.values[numeric]} ({numeric})"
    if isinstance(value, str):
        return value.strip()
    return str(value)
