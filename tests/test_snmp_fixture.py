"""tests/fixtures/mx30_snmp_walk.json: the COEX enterprise SNMP arc as OBSERVED once.

One snmpwalk of 1.3.6.1.4.1.319 on one MX30 -- firmware V1.5.1, read over SNMP
itself -- on 2026-09-26 with VMP closed, SNMPv2c, community public. SNMP was
enabled for the walk (PUT snmpstate {"state": true}) and disabled straight
after. It was the first time this repository's OID map met hardware, and it is
for consumers outside the repository as much as for this one: crewbox reads the
same OIDs in TypeScript and has never met a controller.

The fixture was built by hand from a masked walk, so there is no Python constant
to regenerate it from. These tests pin what it must keep -- real structure and
real numbers -- and that every identifier and the controller clock are
synthetic. The readings of the masks and the "ERROR:" strings are REASONED, and
the tests below say so where they lean on one.

Counter64 values are exact decimal strings in the fixture: all but one are
64-bit masks above 2**53, which a JSON number would round in JavaScript,
dropping exactly the low bits that carry per-card status.
"""

from __future__ import annotations

import ipaddress
import json
import re
from collections import Counter
from pathlib import Path

from novasun import snmp

FIXTURE = Path(__file__).parent / "fixtures" / "mx30_snmp_walk.json"

C = snmp.CONTROLLER  # 1.3.6.1.4.1.319.10.10
S = snmp.SCREEN  # 1.3.6.1.4.1.319.10.20

#: Output-card ports that carried cabinets: 24 receiving cards each (OBSERVED).
POPULATED_PORTS = {1, 3, 5}
PORTS = range(1, 11)
EMPTY_PORT = "ERROR: there are no cabinets in port "  # trailing space, no port number

#: Every OID that held an identifier, show data or the clock, and the synthetic
#: value the fixture carries in its place.
SYNTHETIC = {
    f"{C}.1.1": "2000-01-01 00:00:00",  # CONTROLLER_TIME
    f"{C}.1.4": "Stage left",  # CONTROLLER_NAME; the mx30_like_api.json label
    f"{C}.1.6": "FIXTURE-SN-CONTROLLER",  # CONTROLLER_SERIAL
    f"{C}.1.7": "00:00:5E:00:53:01",  # CONTROLLER_MAC, RFC 7042 documentation range
    f"{C}.1.8": "192.0.2.30",  # CONTROLLER_IP, RFC 5737 TEST-NET-1
    f"{C}.20.3.1.4": "FIXTURE-SN-INPUT-CARD-1",  # INPUT_CARD_SERIAL
    f"{C}.30.3.1.4": "FIXTURE-SN-OUTPUT-CARD-1",  # OUTPUT_CARD_SERIAL
    f"{S}.1.2.1.1": "Main",  # screen name (undocumented OID); mx30_like_api.json's screenName
}

#: Every other string the unit served, verbatim. Pinning the whole set means an
#: identifier cannot come back in under an OID nobody thought to mask.
OBSERVED_STRINGS = {
    "",  # INPUT_CARD_NAME and OUTPUT_CARD_NAME
    "MX30",
    "V1.5.1",
    "V1.0.0",
    "V1.0.0.S1.T1.V9",
    "no Wire Ip",
    "Main_board Temperature",
    "Main_board Voltage",
    "Chassis Fan 1",
    "FPGA Fan",
    "Chassis Fan 2",
    "ERROR: getLightSensorStatus getData from LightSensorInfoTag err",
    "ERROR: getLightSensorValue getData from LightSensorInfoTag err",
    EMPTY_PORT,
    "HDMI2.0 ",
    "HDMI1.4 ",
    "DP1.1 ",
    "3G-SDI ",
    "0",
    "0.00",
    "3.9",
    "39.444",
    "0.0",
    "50.0",
    "/0",
}

_MAC = re.compile(
    r"(?i)(?<![0-9a-f])(?:[0-9a-f]{2}([:-])(?:[0-9a-f]{2}\1){4}[0-9a-f]{2}"
    r"|[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}|[0-9a-f]{12})(?![0-9a-f])"
)
_IPV4 = re.compile(r"(?<![\d.])\d{1,3}(?:\.\d{1,3}){3}(?![\d.])")


def _key(oid: str) -> tuple[int, ...]:
    return tuple(int(part) for part in oid.split("."))


def _load() -> tuple[str, dict[str, dict]]:
    walk = json.loads(FIXTURE.read_text())
    about = walk.pop("__about__")
    return about, walk


def _counter64(walk: dict[str, dict], oid: str) -> int:
    entry = walk[oid]
    assert entry["type"] == "Counter64", oid
    return int(entry["value"])


# --- structure ----------------------------------------------------------------


def test_the_fixture_parses_as_one_whole_walk() -> None:
    about, walk = _load()
    assert isinstance(about, str) and about
    # Exactly the 170 varbinds the walk returned, in walk (numeric OID) order.
    assert len(walk) == 170
    keys = list(walk)
    assert keys == sorted(keys, key=_key)
    assert all(re.fullmatch(r"1\.3\.6\.1\.4\.1\.319(?:\.\d+)+", oid) for oid in keys)
    for oid, entry in walk.items():
        assert set(entry) == {"type", "value"}, oid
        kind, value = entry["type"], entry["value"]
        if kind == "INTEGER":
            assert type(value) is int, oid
        elif kind == "STRING":
            assert isinstance(value, str), oid
        elif kind == "Counter64":
            # A decimal string, never a JSON number: see the module docstring.
            assert isinstance(value, str) and re.fullmatch(r"0|[1-9]\d*", value), oid
            assert 0 <= int(value) < 2**64, oid
        else:
            raise AssertionError(f"{oid}: unexpected type {kind!r}")
    assert Counter(e["type"] for e in walk.values()) == {
        "INTEGER": 102,
        "STRING": 44,
        "Counter64": 24,
    }
    # Two of the strings are empty: the card names, served but blank. net-snmp
    # printed them as `= ""` with no type tag.
    assert {oid for oid, e in walk.items() if e["value"] == ""} == {
        f"{C}.20.3.1.2",  # INPUT_CARD_NAME
        f"{C}.30.3.1.2",  # OUTPUT_CARD_NAME
    }
    # endOfMibView came after .10.200.6; the gaps inside the walk are real.
    assert keys[-1] == f"{snmp.ENTERPRISE}.10.200.6"
    for gap in (f"{C}.20.4.1.2", f"{C}.30.4.1.2", f"{S}.1.2.1.8"):
        assert gap not in walk


def test_about_states_the_scope_and_does_not_overclaim() -> None:
    about, _ = _load()
    for phrase in (
        "MX30",
        "V1.5.1",
        "2026-09-26",
        "VMP closed",
        "SNMPv2c",
        "community public",
        "1.3.6.1.4.1.319",
        # Only the system group was seen absent; other MIB-2 groups were not walked.
        "MIB-2 system group (1.3.6.1.2.1.1) was not served",
        "other MIB-2 groups were not walked (UNKNOWN)",
        '{"state": true}',
        '{"state": false}',
        "endOfMibView",
        "SYNTHETIC",
    ):
        assert phrase in about, phrase
    for label in ("OBSERVED", "REASONED", "UNKNOWN"):
        assert label in about
    assert "MIB-2 is not served" not in about
    assert "MIB-2 not served" not in about


# --- no show data -------------------------------------------------------------


def test_every_masked_oid_holds_its_synthetic_value() -> None:
    _, walk = _load()
    for oid, value in SYNTHETIC.items():
        assert walk[oid] == {"type": "STRING", "value": value}, oid
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", SYNTHETIC[f"{C}.1.1"])


def test_nothing_from_the_show_is_in_the_fixture() -> None:
    text = FIXTURE.read_text()
    about, walk = _load()
    strings = [e["value"] for e in walk.values() if e["type"] == "STRING"]
    # The whole set of strings is pinned: the synthetic ones and the observed
    # non-identifying ones, nothing else.
    assert set(strings) == set(SYNTHETIC.values()) | OBSERVED_STRINGS
    # No masking placeholder survived.
    assert not any("<" in s or ">" in s for s in strings)
    # The only MAC-shaped text anywhere is the documentation-range one.
    assert {m.group(0) for m in _MAC.finditer(text)} == {"00:00:5E:00:53:01"}
    # The only IPv4-shaped value is in TEST-NET-1 (keys are OIDs, so look at values).
    found = {m.group(0) for s in [*strings, about] for m in _IPV4.finditer(s)}
    assert found == {"192.0.2.30"}
    assert all(ipaddress.ip_address(ip) in ipaddress.ip_network("192.0.2.0/24") for ip in found)
    # No serial-like digit runs in any string.
    assert not any(re.search(r"\d{8,}", s) for s in strings)


# --- what the unit said -------------------------------------------------------


def test_identity_reads_mx30_firmware_v1_5_1() -> None:
    _, walk = _load()
    assert walk[snmp.CONTROLLER_MODEL.oid] == {"type": "STRING", "value": "MX30"}
    assert walk[snmp.CONTROLLER_FIRMWARE.oid] == {"type": "STRING", "value": "V1.5.1"}
    # The input- and output-card firmware OIDs agree.
    assert walk[f"{C}.20.3.1.1"] == {"type": "STRING", "value": "V1.5.1"}
    assert walk[f"{C}.30.3.1.1"] == {"type": "STRING", "value": "V1.5.1"}
    # CONTROLLER_ROLE read 1, the documented "backup", on a unit that drove the
    # wall alone: the value is OBSERVED, its meaning UNKNOWN.
    assert walk[snmp.CONTROLLER_ROLE.oid] == {"type": "INTEGER", "value": 1}


def test_receiving_cards_online_is_24_on_ports_1_3_5_and_an_error_string_elsewhere() -> None:
    _, walk = _load()
    assert walk[f"{C}.30.5.1.1"] == {"type": "INTEGER", "value": 10}  # ETHERNET_PORT_COUNT
    online = {}
    for port in PORTS:
        entry = walk[snmp.RECEIVING_CARDS_ONLINE.at(1, port)]
        if port in POPULATED_PORTS:
            assert entry == {"type": "INTEGER", "value": 24}, port
            online[port] = 24
        else:
            assert entry == {"type": "STRING", "value": EMPTY_PORT}, port
    assert snmp.RECEIVING_CARDS_ONLINE.at(1, 11) not in walk
    # The sum equals the undocumented Counter64 at .30.4.1.5 (REASONED: the
    # total receiving-card count).
    assert sum(online.values()) == _counter64(walk, f"{C}.30.4.1.5") == 72


def test_receiving_card_status_is_a_per_port_mask_clear_in_the_low_24_bits_on_ports_1_3_5() -> None:
    _, walk = _load()
    per_port = {f"{C}.30.6.1.1.{port}.{k}" for port in PORTS for k in (1, 2)}
    # The documented per-card forms (.30.6.N.1.Y.{1,2}.M) are absent; these
    # twenty per-port values are all that was served under .30.6.
    assert {oid for oid in walk if oid.startswith(f"{C}.30.6.")} == per_port
    clear = set()
    for port in PORTS:
        temperature = _counter64(walk, f"{C}.30.6.1.1.{port}.1")
        voltage = _counter64(walk, f"{C}.30.6.1.1.{port}.2")
        assert temperature == voltage, port
        assert temperature >> 24 == (1 << 40) - 1, port  # bits above 24 are all set
        low = temperature & 0xFFFFFF
        assert low in (0, 0xFFFFFF), port
        if low == 0:
            clear.add(port)
    assert clear == POPULATED_PORTS
    assert _counter64(walk, f"{C}.30.6.1.1.1.1") == 0xFFFFFFFFFF000000
    assert _counter64(walk, f"{C}.30.6.1.1.2.1") == 0xFFFFFFFFFFFFFFFF


def test_slot_and_ethernet_status_are_counter64_masks() -> None:
    _, walk = _load()
    # Where the document gives 0/1 (OBSERVED type and value; per-bit reading REASONED).
    assert _counter64(walk, f"{C}.30.2") == 0xFFFFFFFFFFFFFFFE  # OUTPUT_SLOT_STATUS
    assert _counter64(walk, f"{C}.20.2") == 0xFFFFFFFFFFFFFFFE  # INPUT_SLOT_STATUS
    assert _counter64(walk, f"{C}.30.5.1.3") == 0xFFFFFFFFFFFFFFE0  # ETHERNET_PORT_STATUS


def test_the_two_mx30_fixtures_agree_where_the_unit_agreed() -> None:
    from conftest import MX30_LIKE_API, MX30_LIKE_MONITOR_INFO

    _, walk = _load()
    info = MX30_LIKE_MONITOR_INFO
    # The controller name was recorded equal to HTTP monitor/info's before
    # masking; both fixtures carry the same synthetic label so a join survives.
    assert walk[snmp.CONTROLLER_NAME.oid]["value"] == info["name"]
    # Point and fan names match HTTP's, in HTTP's order (OBSERVED).
    assert walk[snmp.TEMPERATURE_POINT_NAME.at(1)]["value"] == info["mainBoardTemperature"]["name"]
    assert walk[snmp.VOLTAGE_POINT_NAME.at(1)]["value"] == info["mainBoardVoltage"]["name"]
    fans = [walk[snmp.FAN_NAME.at(n)]["value"] for n in range(1, walk[snmp.FAN_COUNT.oid]["value"] + 1)]
    assert fans == [f["fanName"] for f in info["fanInfos"]]
    # The voltage matches exactly under the x100 reading; that reading is REASONED
    # and this match is most of its support. (The temperature, 3100 against HTTP's
    # 32 read at another time, is too weak to assert.)
    assert walk[snmp.VOLTAGE_POINT_VALUE.at(1)]["value"] / 100 == info["mainBoardVoltage"]["value"]
    # SNMP port Y = HTTP outputID 2047 + Y is REASONED. Under it, the ports with
    # cards online are the outputs that carry cabinets, and the ETHERNET_PORT_STATUS
    # bits that are clear are the outputs whose link is up.
    cabinet_outputs = {c["outputID"] for c in MX30_LIKE_API["/api/v1/device/cabinet"]}
    assert {2047 + port for port in POPULATED_PORTS} == cabinet_outputs
    ethernet = _counter64(walk, f"{C}.30.5.1.3")
    clear_bits = {bit for bit in range(64) if not ethernet >> bit & 1}
    linked = {o["outputID"] for o in info["outputStatus"] if o["type"] == 0 and o["linkStatus"]}
    assert {2048 + bit for bit in clear_bits} == linked


# --- the snmp module against the fixture --------------------------------------
#
# These use the helpers and corrections made to novasun.snmp from the same walk.
# They import them directly and never skip: a helper that goes missing must fail
# here, not pass unnoticed as a skip.

_KIND_TO_TYPE = {"int": "INTEGER", "string": "STRING", "counter64": "Counter64"}


def _pattern(oid: str) -> re.Pattern[str]:
    return re.compile(
        r"\.".join(r"\d+" if part in ("N", "Y", "M") else re.escape(part) for part in oid.split("."))
    )


def test_the_snmp_helpers_decode_the_masks_and_the_error_strings() -> None:
    from novasun.snmp import decode_status_mask, is_error_string, present_value

    _, walk = _load()
    # "ERROR:" strings read as absent (REASONED consumer rule); nine of them.
    values = [e["value"] for e in walk.values()]
    assert sum(present_value(v) is None for v in values) == 9
    assert sum(is_error_string(v) for v in values) == 9
    assert all(present_value(v) == v for v in values if not is_error_string(v))
    # Receiving cards: the count column carries an int or an error string, and
    # the per-port mask decodes to 24 clear bits exactly where 24 cards are online.
    status_oids = [(o, o.at(1, 1)) for o in (snmp.RECEIVING_CARD_TEMPERATURE_STATUS,
                                              snmp.RECEIVING_CARD_VOLTAGE_STATUS)]
    assert all(oid in walk for _, oid in status_oids)
    for port in PORTS:
        online = present_value(walk[snmp.RECEIVING_CARDS_ONLINE.at(1, port)]["value"])
        assert online == (24 if port in POPULATED_PORTS else None), port
        for status in (snmp.RECEIVING_CARD_TEMPERATURE_STATUS, snmp.RECEIVING_CARD_VOLTAGE_STATUS):
            mask = _counter64(walk, status.at(1, port))
            bits = decode_status_mask(mask, 64)
            assert bits.count(False) == (online or 0), port
            # REASONED reading: clear = normal (or present), unused bits set.
            assert decode_status_mask(mask, 24) == ((False,) * 24 if online else (True,) * 24)
    # Ethernet ports, counted by ETHERNET_PORT_COUNT: 1-5 clear (link up, REASONED).
    ports = walk[snmp.ETHERNET_PORT_COUNT.at(1)]["value"]
    ethernet = _counter64(walk, snmp.ETHERNET_PORT_STATUS.at(1))
    assert decode_status_mask(ethernet, ports) == (False,) * 5 + (True,) * 5
    # Slots: slot 1 present on both sides.
    assert decode_status_mask(_counter64(walk, snmp.OUTPUT_SLOT_STATUS.oid), 1) == (False,)
    assert decode_status_mask(_counter64(walk, snmp.INPUT_SLOT_STATUS.oid), 1) == (False,)
    # A decoder that reads the 8-byte BER as signed gets a negative number; the
    # bits must come out the same. (Which encoding the unit sent is UNKNOWN.)
    for entry in walk.values():
        if entry["type"] == "Counter64":
            unsigned = int(entry["value"])
            signed = unsigned - (1 << 64) if unsigned >> 63 else unsigned
            assert decode_status_mask(signed, 64) == decode_status_mask(unsigned, 64)


def test_the_corrected_oid_map_agrees_with_the_walk() -> None:
    from novasun.snmp import (
        MIB2_SYSTEM,
        OBSERVED_UNDOCUMENTED,
        OBSERVED_UNDOCUMENTED_SUBTREES,
        REACHABILITY_PROBE,
    )

    _, walk = _load()
    documented = [v for v in vars(snmp).values() if isinstance(v, snmp.Oid)]
    covered: set[str] = set()
    for oid in [*documented, *OBSERVED_UNDOCUMENTED.values()]:
        matches = [key for key in walk if _pattern(oid.oid).fullmatch(key)]
        # Every OID the module names was served on this unit ...
        assert matches, oid.oid
        covered.update(matches)
        for key in matches:
            observed = walk[key]["type"]
            if oid is snmp.RECEIVING_CARDS_ONLINE and observed == "STRING":
                # ... this one as an int or an "ERROR:" string (OBSERVED) ...
                assert walk[key]["value"].startswith("ERROR:"), key
            else:
                # ... and every other with the kind the module declares.
                assert _KIND_TO_TYPE[oid.kind] == observed, key
    # Whatever no Oid names lies under an arc recorded as existence-only.
    for key in set(walk) - covered:
        assert any(key == arc or key.startswith(arc + ".") for arc in OBSERVED_UNDOCUMENTED_SUBTREES), key
    assert walk[REACHABILITY_PROBE.oid]["type"] == "STRING"
    assert not any(key == MIB2_SYSTEM or key.startswith(MIB2_SYSTEM + ".") for key in walk)
    # Scales are REASONED; under them the readings come out as below.
    def reading(oid: snmp.Oid) -> float:
        return walk[oid.at(1)]["value"] / oid.scale

    assert reading(snmp.TEMPERATURE_POINT_VALUE) == 31.0
    assert reading(snmp.VOLTAGE_POINT_VALUE) == 11.56
    assert reading(snmp.SCREEN_FRAME_RATE) == reading(snmp.SCREEN_SYNC_FRAME_RATE) == 50.0
    # CONTROLLER_ROLE 1 must not render as "backup"; source types are strings.
    assert "backup" not in snmp.describe(snmp.CONTROLLER_ROLE, walk[snmp.CONTROLLER_ROLE.oid]["value"])
    types = [snmp.describe(snmp.INPUT_SOURCE_TYPE, walk[snmp.INPUT_SOURCE_TYPE.at(1, y)]["value"])
             for y in range(1, walk[snmp.INPUT_SOURCE_COUNT.at(1)]["value"] + 1)]
    assert types == ["HDMI2.0", "HDMI1.4", "DP1.1", "3G-SDI", "3G-SDI"]
