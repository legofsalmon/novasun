"""Model profiles, COEX HTTP client, and identification across both paths."""

from __future__ import annotations

import pytest

from novasun import devices
from novasun.coex import CoexClient, CoexError, diff_snapshots, snapshot
from novasun.coexsim import CoexState, SimulatedCoexController
from novasun.devices import Family, identify, profile_for
from novasun.simulator import SimulatedController


class TestProfiles:
    def test_target_models_are_known(self) -> None:
        """The three families this project is being built for."""
        vx4s = profile_for(0x6107)
        assert vx4s.name == "VX4S"
        assert vx4s.family is Family.VIDEO_PROCESSOR
        assert vx4s.port_count == 4
        assert vx4s.control_port == 5200

        uhd_jr = profile_for(0x6205)
        assert uhd_jr.name == "NovaPro UHD Jr"
        assert uhd_jr.port_count == 16
        assert uhd_jr.input_select

        mx40 = devices.coex_profile_for("MX40 Pro")
        assert mx40.family is Family.COEX
        assert mx40.http_api and mx40.presets

    def test_mctrl660_pro_matches_the_official_document(self) -> None:
        """0x1107 is the one model ID NovaStar's own PDF states outright."""
        profile = profile_for(0x1107)
        assert profile.model_id == 0x1107
        assert profile.name == "MCTRL660 Pro"
        assert "official" in devices.PROVENANCE[0x1107]

    def test_vx_pro_uses_the_other_control_port(self) -> None:
        assert profile_for(0x622B).control_port == 5200 + 10000

    def test_unknown_models_stay_usable(self) -> None:
        """Not recognising a model must not stop the register bus working."""
        profile = profile_for(0xABCD)
        assert not profile.is_known
        assert profile.port_count == 2
        assert "abcd" in profile.name

    def test_coex_names_match_loosely(self) -> None:
        assert devices.coex_profile_for("mx40 pro").name == "MX40 Pro"
        assert devices.coex_profile_for("NovaStar KU20 Controller").name == "KU20"
        unknown = devices.coex_profile_for("MX99 Ultra")
        assert unknown.family is Family.COEX and unknown.http_api


@pytest.fixture()
def coex_server():
    server = SimulatedCoexController("127.0.0.1", 0)
    server.serve_in_thread()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture()
def coex(coex_server):
    host, port = coex_server.address
    return CoexClient(host, port, timeout=2.0)


class TestCoexClient:
    def test_reads_device_and_topology(self, coex) -> None:
        assert coex.device_info()["model"] == "MX40 Pro"
        assert len(coex.screens()["screens"]) == 1
        assert len(coex.cabinets()["cabinets"]) == 8
        assert len(coex.presets()["presets"]) == 2

    def test_display_mode_round_trips(self, coex, coex_server) -> None:
        coex.set_display_mode(1)
        assert coex_server.state.display_mode == 1
        assert coex.request("GET", "/api/v1/device/screen/displaymode")["value"] == 1

    def test_cabinet_brightness_applies_to_named_cabinets_only(self, coex, coex_server) -> None:
        target = coex_server.state.cabinets[2]["id"]
        coex.set_cabinet_brightness([target], 0.4)
        assert coex_server.state.cabinet(target)["brightness"] == pytest.approx(0.4)
        assert coex_server.state.cabinets[0]["brightness"] == pytest.approx(1.0)

    def test_screen_brightness_cascades_to_its_cabinets(self, coex, coex_server) -> None:
        coex.set_screen_brightness(["screen-1"], 0.25)
        assert all(
            cabinet["brightness"] == pytest.approx(0.25)
            for cabinet in coex_server.state.cabinets
        )

    def test_preset_recall(self, coex, coex_server) -> None:
        coex.apply_preset("preset-2")
        assert coex_server.state.current_preset == "preset-2"

    def test_errors_surface_as_exceptions(self, coex) -> None:
        with pytest.raises(CoexError) as error:
            coex.select_input(99)
        assert error.value.code == 1

        with pytest.raises(CoexError) as error:
            coex.request("GET", "/api/v1/device/nonexistent")
        assert error.value.code == 6  # NotSupport, as real firmware answers


class TestSnapshotDiff:
    def test_snapshot_then_diff_isolates_what_changed(self, coex, coex_server) -> None:
        target = coex_server.state.cabinets[0]["id"]
        before = snapshot(coex)
        coex.set_cabinet_brightness([target], 0.5)
        after = snapshot(coex)

        changes = {path: (old, new) for path, old, new in diff_snapshots(before, after)}
        brightness = [path for path in changes if path.endswith("brightness")]
        assert brightness, changes
        assert all(changes[path] == (1.0, 0.5) for path in brightness)
        # Exactly one cabinet moved, in each endpoint that lists cabinets.
        assert len(brightness) == len(
            [path for path in changes if "cabinets[0]" in path and "brightness" in path]
        )

    def test_snapshot_records_unsupported_endpoints_without_failing(self, coex) -> None:
        result = snapshot(coex, {"nope": "/api/v1/does/not/exist", "device": "/api/v1/device"})
        assert "__error__" in result["nope"]
        assert result["device"]["model"] == "MX40 Pro"


class TestIdentify:
    def test_identifies_a_coex_controller_over_http(self, coex_server) -> None:
        host, port = coex_server.address
        identification = identify(host, timeout=2.0, http_port=port, control_port=port)

        assert identification.reachable_http
        assert identification.profile.name == "MX40 Pro"
        assert identification.profile.family is Family.COEX
        assert identification.preferred_path == "http"
        assert "MX40 Pro" in identification.summary()

    def test_identifies_a_register_bus_processor(self) -> None:
        server = SimulatedController("127.0.0.1", 0, model_id=0x6205)
        server.serve_in_thread()
        try:
            host, port = server.address
            identification = identify(host, timeout=2.0, http_port=port, control_port=port)

            assert identification.reachable_register_bus
            assert not identification.reachable_http
            assert identification.profile.name == "NovaPro UHD Jr"
            assert identification.profile.port_count == 16
            assert identification.preferred_path == "register-bus"
            assert identification.serial.startswith("00:1a:2b")
        finally:
            server.shutdown()
            server.server_close()

    def test_identifies_a_vx4s(self) -> None:
        server = SimulatedController("127.0.0.1", 0, model_id=0x6107)
        server.serve_in_thread()
        try:
            host, port = server.address
            identification = identify(host, timeout=2.0, http_port=port, control_port=port)
            assert identification.profile.name == "VX4S"
            assert identification.profile.port_count == 4
            assert identification.profile.input_select
        finally:
            server.shutdown()
            server.server_close()

    def test_identify_reports_nothing_reachable_for_a_dead_host(self) -> None:
        """A closed port must produce a clean answer, not an exception."""
        identification = identify("127.0.0.1", timeout=0.2)
        assert not identification.reachable_http
        assert not identification.reachable_register_bus
        assert identification.profile.family is Family.UNKNOWN
