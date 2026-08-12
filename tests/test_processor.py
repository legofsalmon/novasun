"""Per-model I/O and the unified facade.

These tests exist because the differences between processors are not cosmetic:
the input register, the input values, and the meaning of a display-mode value
all change between models. Getting one wrong at a live screen blacks it out
when you meant to freeze it.
"""

from __future__ import annotations

import socket

import pytest

from novasun import devices
from novasun.coexsim import SimulatedCoexController
from novasun.devices import ConnectorType, Family, profile_for
from novasun.processor import CapabilityUnknown, NotSupported, Processor
from novasun.registers import DisplayMode
from novasun.simulator import SimulatedController

VX4S = 0x6107
UHD_JR = 0x6205
NOVAPRO_HD = 0x6101
MCTRL660_PRO = 0x1107


class TestInputMaps:
    """Every value here is transcribed from a checksum-verified vendor frame."""

    def test_each_family_uses_a_different_input_register(self) -> None:
        assert profile_for(VX4S).input_register == 0x0220_002D
        assert profile_for(NOVAPRO_HD).input_register == 0x0220_0022
        assert profile_for(MCTRL660_PRO).input_register == 0x0200_0023

    def test_vx4s_input_values(self) -> None:
        profile = profile_for(VX4S)
        expected = {
            "DVI": 0x10,
            "HDMI": 0xA0,
            "VGA 1": 0x01,
            "VGA 2": 0x02,
            "CVBS 1": 0x71,
            "CVBS 2": 0x72,
            "SDI": 0x40,
            "DP": 0x90,
        }
        assert {c.label: c.select_value for c in profile.inputs} == expected

    def test_novapro_hd_input_values(self) -> None:
        profile = profile_for(NOVAPRO_HD)
        expected = {"SDI": 0x1A, "DVI": 0x1C, "HDMI": 0x1B, "VGA": 0x17, "DP": 0x1E, "CVBS": 0x02}
        assert {c.label: c.select_value for c in profile.inputs} == expected

    def test_the_same_connector_means_different_bytes_per_model(self) -> None:
        """HDMI is 0xA0, 0x1B or 0x05 depending on what you are talking to."""
        values = {
            profile_for(model).name: profile_for(model).find_input("HDMI").select_value
            for model in (VX4S, NOVAPRO_HD, MCTRL660_PRO)
        }
        assert values == {"VX4S": 0xA0, "NovaPro HD": 0x1B, "MCTRL660 Pro": 0x05}
        assert len(set(values.values())) == 3

    def test_lookup_by_type_when_unambiguous(self) -> None:
        profile = profile_for(VX4S)
        assert profile.find_input("hdmi").label == "HDMI"
        assert profile.find_input("HDMI").select_value == 0xA0
        # Two VGA connectors, so a bare "vga" is ambiguous and refuses to pick.
        assert profile.find_input("vga") is None
        assert profile.find_input("VGA 2").select_value == 0x02

    def test_uhd_jr_connectors_are_listed_but_not_switchable(self) -> None:
        """Connectors known from the spec; select codes not established."""
        profile = profile_for(UHD_JR)
        labels = [c.label for c in profile.inputs]
        assert "DP 1.2" in labels and "HDMI 2.0" in labels
        assert len([c for c in profile.inputs if c.type is ConnectorType.DVI]) == 4
        assert len([c for c in profile.inputs if c.type is ConnectorType.SDI]) == 2
        assert "DVI MOSAIC" in labels
        assert profile.switchable_inputs == ()


class TestOutputs:
    def test_port_counts_differ_per_model(self) -> None:
        assert profile_for(VX4S).port_count == 4
        assert profile_for(UHD_JR).port_count == 16
        assert profile_for(MCTRL660_PRO).port_count == 6

    def test_uhd_jr_has_fibre_and_loop_outputs(self) -> None:
        profile = profile_for(UHD_JR)
        assert profile.fibre_ports == 4
        loops = [output for output in profile.outputs if output.loop_through]
        assert {output.type for output in loops} == {ConnectorType.HDMI, ConnectorType.SDI}

    def test_vx4s_has_no_extra_outputs(self) -> None:
        assert profile_for(VX4S).outputs == ()
        assert profile_for(VX4S).fibre_ports == 0


class TestDisplayModeDiffers:
    def test_vx4s_swaps_blackout_and_freeze_relative_to_coex(self) -> None:
        """The footgun this modelling exists to prevent."""
        vx4s = profile_for(VX4S).display
        coex = devices.coex_profile_for("MX40 Pro").display

        assert vx4s.value_for("freeze") == 1
        assert vx4s.value_for("blackout") == 2
        assert coex.value_for("blackout") == 1
        assert coex.value_for("freeze") == 2
        assert vx4s.value_for("blackout") != coex.value_for("blackout")

    def test_sending_cards_fall_back_to_receiving_card_registers(self) -> None:
        assert not profile_for(MCTRL660_PRO).display.is_processor_level
        assert profile_for(VX4S).display.is_processor_level


def closed_port() -> int:
    """A port nothing is listening on, so an HTTP probe is refused at once.

    Real register-bus hardware has 8001 closed and refuses instantly; pointing
    the probe at an open non-HTTP port instead would make every test wait out
    the full timeout, which is both slow and unrepresentative.
    """
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _processor(model_id: int):
    server = SimulatedController("127.0.0.1", 0, model_id=model_id)
    server.serve_in_thread()
    host, port = server.address
    processor = Processor.connect(
        host, timeout=2.0, http_port=closed_port(), control_port=port
    )
    return server, processor


class TestProcessorRegisterBus:
    def test_vx4s_input_switch_writes_the_right_register_and_value(self) -> None:
        server, processor = _processor(VX4S)
        try:
            processor.select_input("HDMI")
            assert server.sender.read(0x0220_002D, 1) == b"\xa0"
            processor.select_input("CVBS 2")
            assert server.sender.read(0x0220_002D, 1) == b"\x72"
        finally:
            processor.close()
            server.shutdown()
            server.server_close()

    def test_novapro_hd_writes_its_own_register(self) -> None:
        server, processor = _processor(NOVAPRO_HD)
        try:
            processor.select_input("HDMI")
            assert server.sender.read(0x0220_0022, 1) == b"\x1b"
            # And nothing landed in the VX4S register.
            assert server.sender.read(0x0220_002D, 1) == b"\x00"
        finally:
            processor.close()
            server.shutdown()
            server.server_close()

    def test_unknown_select_code_refuses_rather_than_guessing(self) -> None:
        server, processor = _processor(UHD_JR)
        try:
            with pytest.raises(CapabilityUnknown) as error:
                processor.select_input("HDMI 2.0")
            assert "capture" in str(error.value).lower()
            # The input is still listed, so a UI can show it as unavailable.
            hdmi = next(i for i in processor.inputs() if i.label == "HDMI 2.0")
            assert not hdmi.switchable
        finally:
            processor.close()
            server.shutdown()
            server.server_close()

    def test_unknown_input_name_is_a_clear_error(self) -> None:
        server, processor = _processor(VX4S)
        try:
            with pytest.raises(NotSupported) as error:
                processor.select_input("SCART")
            assert "SCART" in str(error.value) and "HDMI" in str(error.value)
        finally:
            processor.close()
            server.shutdown()
            server.server_close()

    def test_display_mode_uses_the_processor_register_on_a_vx4s(self) -> None:
        server, processor = _processor(VX4S)
        try:
            processor.freeze()
            assert server.sender.read(0x0220_0050, 1) == b"\x01"
            processor.blackout()
            assert server.sender.read(0x0220_0050, 1) == b"\x02"
            processor.set_display_mode(DisplayMode.NORMAL)
            assert server.sender.read(0x0220_0050, 1) == b"\x00"
        finally:
            processor.close()
            server.shutdown()
            server.server_close()

    def test_display_mode_falls_back_to_receiving_cards(self) -> None:
        server, processor = _processor(MCTRL660_PRO)
        try:
            processor.blackout()
            assert server.card(0, 0).read(0x0200_0100, 1) == b"\xff"
            processor.set_display_mode("normal")
            assert server.card(0, 0).read(0x0200_0100, 1) == b"\x00"
        finally:
            processor.close()
            server.shutdown()
            server.server_close()

    def test_panel_lock_only_where_documented(self) -> None:
        server, processor = _processor(VX4S)
        try:
            processor.set_panel_lock(True)
            assert server.sender.read(0x0220_00F7, 1) == b"\x01"
        finally:
            processor.close()
            server.shutdown()
            server.server_close()

        server, processor = _processor(MCTRL660_PRO)
        try:
            with pytest.raises(NotSupported):
                processor.set_panel_lock(True)
        finally:
            processor.close()
            server.shutdown()
            server.server_close()

    def test_card_targets_follow_the_model_port_count(self) -> None:
        server, processor = _processor(UHD_JR)
        try:
            targets = processor.cards(per_port=2)
            assert len(targets) == 32  # 16 ports, not a VX4S-shaped 4
            assert max(target.port for target in targets) == 15
            assert processor.outputs()["fibre_ports"] == 4
        finally:
            processor.close()
            server.shutdown()
            server.server_close()

    def test_monitoring_rejects_a_port_the_model_does_not_have(self) -> None:
        server, processor = _processor(VX4S)
        try:
            with pytest.raises(ValueError, match="no port 9"):
                processor.monitoring(port=9)
            assert processor.monitoring(port=3).temperature_c is not None
        finally:
            processor.close()
            server.shutdown()
            server.server_close()


class TestProcessorCoex:
    @pytest.fixture()
    def coex(self):
        server = SimulatedCoexController("127.0.0.1", 0)
        server.serve_in_thread()
        host, port = server.address
        processor = Processor.connect(
            host, timeout=2.0, http_port=port, control_port=closed_port()
        )
        yield server, processor
        processor.close()
        server.shutdown()
        server.server_close()

    def test_uses_the_http_path(self, coex) -> None:
        _server, processor = coex
        assert processor.uses_http
        assert processor.profile.family is Family.COEX

    def test_inputs_are_enumerated_from_the_controller(self, coex) -> None:
        """COEX does not need a static input map -- it reports its own."""
        _server, processor = coex
        inputs = processor.inputs()
        assert [state.label for state in inputs] == ["HDMI 1", "HDMI 2", "12G-SDI"]
        assert all(state.switchable for state in inputs)
        assert inputs[0].connected is True

    def test_select_input_by_reported_name(self, coex) -> None:
        server, processor = coex
        processor.select_input("12G-SDI")
        assert server.state.current_input == 3

    def test_display_mode_uses_the_http_convention(self, coex) -> None:
        server, processor = coex
        processor.blackout()
        assert server.state.display_mode == 1  # 1 is blackout here, unlike a VX4S
        processor.freeze()
        assert server.state.display_mode == 2

    def test_brightness_goes_through_screens(self, coex) -> None:
        server, processor = coex
        processor.set_brightness(40)
        assert server.state.screens[0]["brightness"] == pytest.approx(0.4)

    def test_presets_come_from_the_controller(self, coex) -> None:
        server, processor = coex
        assert [preset["name"] for preset in processor.presets()] == ["Show", "Rehearsal"]
        processor.apply_preset("preset-2")
        assert server.state.current_preset == "preset-2"
