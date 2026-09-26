"""The COEX SNMP OID map after its first contact with hardware.

The map was exercised once: a walk of the enterprise arc on one MX30
(firmware V1.5.1, 2026-09-26, VMP closed). These tests pin what that changed
in ``novasun.snmp`` -- the corrected kinds, the observed per-port form of the
receiving-card status, the REASONED scales, the undocumented entries and the
two pure helpers -- and that every such claim carries its provenance label.
Every value below is synthetic; nothing here is read from the unit's walk.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from novasun import snmp
from novasun.snmp import Oid

LABELS = ("OBSERVED", "OFFICIAL", "DERIVED", "REASONED", "UNKNOWN")
ALL_ONES = (1 << 64) - 1


def documented() -> dict[str, Oid]:
    """Every module-level Oid constant: the document's map, as corrected."""
    return {name: value for name, value in vars(snmp).items()
            if isinstance(value, Oid) and name.isupper() and name != "REACHABILITY_PROBE"}


def every_oid() -> list[Oid]:
    return [*documented().values(), *snmp.OBSERVED_UNDOCUMENTED.values()]


class TestTheMap:
    def test_all_46_documented_items_are_still_there(self) -> None:
        # 44 were served on the MX30 as documented; the two per-card
        # receiving-card forms were absent, and their constants now carry the
        # per-port form that was served instead. None was dropped.
        assert len(documented()) == 46

    def test_every_oid_declares_a_known_kind(self) -> None:
        for oid in every_oid():
            assert oid.kind in snmp.KINDS, oid
            assert oid.oid.startswith(snmp.ENTERPRISE + "."), oid
            assert oid.scale >= 1, oid

    def test_every_note_carries_a_provenance_label(self) -> None:
        for oid in every_oid():
            if oid.note:
                assert any(label in oid.note for label in LABELS), oid

    def test_kinds_corrected_to_what_was_observed(self) -> None:
        # Each was typed otherwise here until 2026-09-26; which side (document
        # or transcription) was wrong is not established, and the note says so.
        corrected = {
            "OUTPUT_CARD_FIRMWARE": "string",
            "OUTPUT_CARD_ROLE": "int",
            "OUTPUT_CARD_SERIAL": "string",
            "OUTPUT_SLOT_STATUS": "counter64",
            "ETHERNET_PORT_STATUS": "counter64",
            "RECEIVING_CARD_TEMPERATURE_STATUS": "counter64",
            "RECEIVING_CARDS_ONLINE": "int",
        }
        oids = documented()
        for name, kind in corrected.items():
            assert oids[name].kind == kind, name
            assert "OBSERVED" in oids[name].note, name
        for name in ("OUTPUT_CARD_FIRMWARE", "OUTPUT_CARD_ROLE", "OUTPUT_CARD_SERIAL",
                     "OUTPUT_SLOT_STATUS", "ETHERNET_PORT_STATUS", "RECEIVING_CARDS_ONLINE"):
            assert "not established" in oids[name].note, name

    def test_the_input_card_row_is_unchanged(self) -> None:
        # It matched on the unit, as transcribed.
        assert [snmp.INPUT_CARD_FIRMWARE.kind, snmp.INPUT_CARD_NAME.kind,
                snmp.INPUT_CARD_ROLE.kind, snmp.INPUT_CARD_SERIAL.kind] == [
            "string", "string", "int", "string"]

    def test_card_names_are_served_as_empty_strings_not_absent(self) -> None:
        for oid in (snmp.OUTPUT_CARD_NAME, snmp.INPUT_CARD_NAME):
            assert oid.kind == "string"
            assert "served" in oid.note and "empty string" in oid.note
            assert "not served" not in oid.note

    def test_receiving_cards_online_may_carry_an_error_string(self) -> None:
        note = snmp.RECEIVING_CARDS_ONLINE.note
        assert "ERROR:" in note and "present_value" in note

    def test_provenance_records_the_one_exercise(self) -> None:
        text = snmp.PROVENANCE
        assert "Not yet exercised" not in text
        for fact in ("OFFICIAL", "MX30", "V1.5.1", "2026-09-26", "VMP closed",
                     "44 of the 46", "per-card", "64-bit masks", "ERROR:",
                     "system group", "REASONED"):
            assert fact in text, fact
        assert "another unit, model or firmware" in text


class TestReceivingCardStatus:
    def test_the_constants_carry_the_observed_per_port_form(self) -> None:
        base = f"{snmp.CONTROLLER}.30.6"
        assert snmp.RECEIVING_CARD_TEMPERATURE_STATUS.at(1, 3) == f"{base}.1.1.3.1"
        assert snmp.RECEIVING_CARD_VOLTAGE_STATUS.at(1, 3) == f"{base}.1.1.3.2"
        for oid in (snmp.RECEIVING_CARD_TEMPERATURE_STATUS, snmp.RECEIVING_CARD_VOLTAGE_STATUS):
            assert oid.kind == "counter64" and oid.per_bit
            assert "M" not in oid.oid.split(".")

    def test_a_per_card_index_is_refused(self) -> None:
        # The documented per-card form .Y.{1,2}.M was absent from the walk; a
        # third index is an error rather than an OID nobody has seen served.
        with pytest.raises(ValueError):
            snmp.RECEIVING_CARD_TEMPERATURE_STATUS.at(1, 3, 7)
        with pytest.raises(ValueError):
            snmp.RECEIVING_CARD_VOLTAGE_STATUS.at(1)

    def test_the_documented_form_is_recorded_with_its_status(self) -> None:
        for oid, leaf in ((snmp.RECEIVING_CARD_TEMPERATURE_STATUS, 1),
                          (snmp.RECEIVING_CARD_VOLTAGE_STATUS, 2)):
            assert f".30.6.N.1.Y.{leaf}.M" in oid.note
            assert "absent from the walk" in oid.note
            assert "no direct GET" in oid.note
            assert "REASONED" in oid.note and "UNKNOWN" in oid.note  # bit order
        source = Path(snmp.__file__).read_text()
        assert "30.6.N.1.Y.1.M" in source and "30.6.N.1.Y.2.M" in source


class TestScaling:
    def test_the_reasoned_scales(self) -> None:
        assert (snmp.TEMPERATURE_POINT_VALUE.scale, snmp.TEMPERATURE_POINT_VALUE.unit) == (100, "°C")
        assert (snmp.VOLTAGE_POINT_VALUE.scale, snmp.VOLTAGE_POINT_VALUE.unit) == (100, "V")
        assert (snmp.SCREEN_FRAME_RATE.scale, snmp.SCREEN_FRAME_RATE.unit) == (100, "Hz")
        assert (snmp.SCREEN_SYNC_FRAME_RATE.scale, snmp.SCREEN_SYNC_FRAME_RATE.unit) == (100, "Hz")
        assert snmp.SCREEN_BRIGHTNESS.kind == "string"
        assert (snmp.SCREEN_BRIGHTNESS.scale, snmp.SCREEN_BRIGHTNESS.unit) == (1, "%")

    def test_no_scale_or_unit_is_stated_as_fact(self) -> None:
        scaled = [oid for oid in documented().values() if oid.scale != 1 or oid.unit]
        assert len(scaled) == 5
        for oid in scaled:
            assert "REASONED" in oid.note, oid
        # The temperature match is the weak one, and sub-degree resolution is
        # not claimed.
        assert "weak" in snmp.TEMPERATURE_POINT_VALUE.note
        assert "UNKNOWN" in snmp.TEMPERATURE_POINT_VALUE.note

    def test_everything_else_is_unscaled(self) -> None:
        names = {"TEMPERATURE_POINT_VALUE", "VOLTAGE_POINT_VALUE", "SCREEN_FRAME_RATE",
                 "SCREEN_SYNC_FRAME_RATE"}
        for name, oid in documented().items():
            if name not in names:
                assert oid.scale == 1, name


class TestDescribe:
    def test_controller_role_is_not_rendered_as_backup(self) -> None:
        # OBSERVED 1 on a unit that drove its wall alone: the documented enum
        # would call it "backup", so describe() does not apply it.
        assert snmp.CONTROLLER_ROLE.values is None
        assert "backup" not in snmp.describe(snmp.CONTROLLER_ROLE, 1)
        assert snmp.describe(snmp.CONTROLLER_ROLE, 1) == "1"
        assert snmp.PRIMARY_BACKUP[1] == "backup"  # the enum itself is kept
        assert "UNKNOWN" in snmp.CONTROLLER_ROLE.note

    def test_a_mask_is_never_mapped_through_the_enum_whole(self) -> None:
        for oid in (snmp.OUTPUT_SLOT_STATUS, snmp.ETHERNET_PORT_STATUS,
                    snmp.RECEIVING_CARD_TEMPERATURE_STATUS, snmp.INPUT_SLOT_STATUS):
            assert oid.per_bit
            assert snmp.describe(oid, 0) == "0"
            assert snmp.describe(oid, 1) == "1"
            assert snmp.describe(oid, ALL_ONES) == str(ALL_ONES)

    def test_a_connector_name_passes_through_stripped(self) -> None:
        # The shape observed -- a name with a trailing space where the document
        # promises an integer -- with a made-up name.
        assert snmp.describe(snmp.INPUT_SOURCE_TYPE, "XLINK3.1 ") == "XLINK3.1"
        # The documented integer codes still map (OFFICIAL enum).
        assert "12G-SDI" in snmp.describe(snmp.INPUT_SOURCE_TYPE, 9)
        assert "12G-SDI" in snmp.describe(snmp.INPUT_SOURCE_TYPE, " 9 ")
        assert snmp.describe(snmp.INPUT_SOURCE_TYPE, 250) == "250"

    def test_enumerations_still_decode(self) -> None:
        assert snmp.describe(snmp.FAN_STATUS, 0) == "normal (0)"
        assert snmp.describe(snmp.OUTPUT_CARD_ROLE, 0) == "primary (0)"
        assert "signal present" in snmp.describe(snmp.INPUT_SOURCE_SIGNAL, "1")


class TestDecodeStatusMask:
    def test_one_boolean_per_index_lsb_first(self) -> None:
        assert snmp.decode_status_mask(0b1010, 4) == (False, True, False, True)
        assert snmp.decode_status_mask(0b1, 1) == (True,)
        assert snmp.decode_status_mask(0, 3) == (False, False, False)

    def test_clear_low_bits_under_set_padding(self) -> None:
        # The observed shape: low bits clear for the indices in use, every
        # other bit set. Synthetic counts.
        mask = ALL_ONES & ~0b111
        assert snmp.decode_status_mask(mask, 3) == (False, False, False)
        assert snmp.decode_status_mask(mask, 5) == (False, False, False, True, True)
        assert snmp.decode_status_mask(ALL_ONES, 6) == (True,) * 6

    def test_bits_above_count_are_ignored(self) -> None:
        assert snmp.decode_status_mask(ALL_ONES & ~1, 1) == (False,)
        assert snmp.decode_status_mask(1 << 40, 40) == (False,) * 40

    def test_the_full_width(self) -> None:
        bits = snmp.decode_status_mask(1 << 63, 64)
        assert len(bits) == 64 and bits[63] and not any(bits[:63])
        assert snmp.decode_status_mask(ALL_ONES, 0) == ()

    def test_a_signed_reading_of_the_same_bits_decodes_alike(self) -> None:
        # An 8-byte encoding read as signed: -2 is 0xFFFFFFFFFFFFFFFE.
        assert snmp.decode_status_mask(-2, 8) == snmp.decode_status_mask(ALL_ONES - 1, 8)
        assert snmp.decode_status_mask(-(1 << 63), 64) == snmp.decode_status_mask(1 << 63, 64)

    @pytest.mark.parametrize("mask", [1 << 64, -(1 << 63) - 1])
    def test_out_of_range_masks_are_refused(self, mask: int) -> None:
        with pytest.raises(ValueError):
            snmp.decode_status_mask(mask, 1)

    @pytest.mark.parametrize("count", [-1, 65, True, 2.0])
    def test_bad_counts_are_refused(self, count) -> None:
        with pytest.raises(ValueError):
            snmp.decode_status_mask(0, count)

    @pytest.mark.parametrize("mask", ["255", 255.0, True, None])
    def test_non_integers_are_refused(self, mask) -> None:
        with pytest.raises(TypeError):
            snmp.decode_status_mask(mask, 1)

    def test_the_docstring_labels_the_reading(self) -> None:
        doc = snmp.decode_status_mask.__doc__
        assert "REASONED" in doc and "UNKNOWN" in doc
        assert "least significant bit is index 1" in doc


class TestErrorStrings:
    def test_error_text_is_absent(self) -> None:
        assert snmp.present_value("ERROR: something went wrong in slot ") is None
        assert snmp.present_value("ERROR:") is None
        assert snmp.present_value(b"ERROR: bytes too") is None
        assert snmp.is_error_string("ERROR: x") and snmp.is_error_string(b"ERROR: x")

    def test_everything_else_passes_through(self) -> None:
        for value in (0, 12, "", "12", "no error: here", "error: lower case",
                      " ERROR: leading space", "OK ERROR:", None, 3.5, b"data"):
            assert snmp.present_value(value) == value, value
            assert not snmp.is_error_string(value), value

    def test_a_mixed_integer_column_reads_cleanly(self) -> None:
        # The observed shape of RECEIVING_CARDS_ONLINE: integers on ports with
        # cards, error text on the rest. Synthetic counts and message.
        column = {1: 5, 2: "ERROR: nothing here ", 3: 7, 4: "ERROR: nothing here "}
        present = {port: snmp.present_value(v) for port, v in column.items()}
        assert present == {1: 5, 2: None, 3: 7, 4: None}
        assert sum(v for v in present.values() if v is not None) == 12

    def test_the_docstring_labels_the_rule(self) -> None:
        assert "REASONED" in snmp.present_value.__doc__
        assert "OBSERVED" in snmp.present_value.__doc__


class TestUndocumented:
    def test_keys_are_the_patterns(self) -> None:
        assert snmp.OBSERVED_UNDOCUMENTED
        for key, oid in snmp.OBSERVED_UNDOCUMENTED.items():
            assert key == oid.oid
            assert oid.kind in snmp.KINDS

    def test_nothing_undocumented_shadows_a_documented_oid(self) -> None:
        patterns = {oid.oid for oid in documented().values()}
        assert not patterns & set(snmp.OBSERVED_UNDOCUMENTED)
        for arc in snmp.OBSERVED_UNDOCUMENTED_SUBTREES:
            assert arc.startswith(snmp.ENTERPRISE + ".")
            for pattern in patterns | set(snmp.OBSERVED_UNDOCUMENTED):
                assert pattern != arc and not pattern.startswith(arc + "."), (arc, pattern)

    def test_every_meaning_is_labelled(self) -> None:
        for oid in snmp.OBSERVED_UNDOCUMENTED.values():
            text = f"{oid.description} {oid.note}"
            assert "OBSERVED" in oid.note, oid
            assert oid.description == "UNKNOWN" or "REASONED" in text or \
                oid.description == "Screen name", oid

    def test_the_only_readings_permitted(self) -> None:
        by_tail = {oid.oid.removeprefix(snmp.ENTERPRISE): oid
                   for oid in snmp.OBSERVED_UNDOCUMENTED.values()}
        assert "REASONED" in by_tail[".10.10.30.4.1.5"].description  # total cards
        assert by_tail[".10.10.30.4.1.5"].kind == "counter64"
        assert "not asserted" in by_tail[".10.10.30.1"].description
        assert by_tail[".10.10.10.6.N.3"].unit == "rpm"
        assert "REASONED" in by_tail[".10.10.10.6.N.3"].description
        assert "show data" in by_tail[".10.20.1.2.N.1"].note
        for tail in (".10.10.30.5.N.4.Y.2", ".10.10.30.5.N.4.Y.3.1",
                     ".10.10.30.5.N.4.Y.3.2", ".10.10.30.5.N.4.Y.3.3",
                     ".10.10.20.5.N.2.Y.3", ".10.20.1.2.N.11", ".10.20.1.2.N.12",
                     ".10.10.20.4.1.1", ".10.10.20.4.1.3",
                     ".10.10.30.4.1.1", ".10.10.30.4.1.3"):
            assert by_tail[tail].description == "UNKNOWN", tail

    def test_undocumented_placeholders_fill_like_documented_ones(self) -> None:
        fan = snmp.OBSERVED_UNDOCUMENTED[f"{snmp.CONTROLLER}.10.6.N.3"]
        assert fan.at(2) == f"{snmp.CONTROLLER}.10.6.2.3"
        assert fan.at(2) == snmp.FAN_STATUS.at(2)[:-1] + "3"


class TestProbing:
    def test_reachability_is_probed_on_the_enterprise_arc(self) -> None:
        probe = snmp.REACHABILITY_PROBE
        assert probe is snmp.CONTROLLER_MODEL
        assert probe.oid.startswith(snmp.ENTERPRISE + ".")
        assert not probe.oid.startswith(snmp.MIB2_SYSTEM)
        assert "REASONED" in Path(snmp.__file__).read_text().split("REACHABILITY_PROBE = ")[1][:400]

    def test_the_monitoring_set_asks_only_for_served_oids(self) -> None:
        # One absent OID may void a multi-varbind GET (REASONED); none of the
        # starting walk is the per-card form that was absent.
        for oid in snmp.MONITORING_SET:
            assert oid.at() == oid.oid
            assert ".30.6." not in oid.oid

    def test_the_setter_advice_names_the_working_body(self) -> None:
        doc = snmp.__doc__
        assert '{"state": true}' in doc and "read" in doc.lower()
        assert '{"value": true}' in doc


class TestStillNoClient:
    def test_the_module_cannot_transmit(self) -> None:
        """An OID map and pure helpers: nothing it imports can open a socket."""
        tree = ast.parse(Path(snmp.__file__).read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        assert imported <= {"__future__", "dataclasses", "typing"}, imported


class TestNothingFromTheShow:
    def test_no_identifier_or_timestamp_in_the_map(self) -> None:
        text = Path(snmp.__file__).read_text() + Path(__file__).read_text()
        assert re.search(r"\b[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}\b", text) is None  # MAC
        assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", text) is None  # a real time
        assert re.search(r"\d{16,}", text) is None  # a long serial or cabinet id
