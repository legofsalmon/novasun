"""Model profiles, COEX HTTP client, and identification across both paths."""

from __future__ import annotations

import inspect
import re
from datetime import datetime, timedelta, timezone

import pytest

from novasun import coex as coex_module
from novasun import devices
from novasun.coex import CoexClient, CoexError, diff_snapshots, redact_secrets, snapshot
from novasun.coexsim import CoexState, SimulatedCoexController
from novasun.devices import Family, identify, profile_for
from novasun.simulator import SimulatedController

from conftest import closed_port


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
        assert devices.coex_profile_for("MX40 Pro_002198").name == "MX40 Pro"
        unknown = devices.coex_profile_for("MX99 Ultra")
        assert unknown.family is Family.COEX and unknown.http_api
        assert unknown is devices.GENERIC_COEX and not unknown.model_known

    def test_a_label_is_not_a_model(self) -> None:
        """monitor/info's name is an operator-settable label, not a model.

        On an MX30 (OBSERVED 2026-09-26) it was a plain word with no model in
        it, and the fallback profile echoed that word back as the model. The
        generic profile now keeps a placeholder name whatever it is given; a
        short label cannot match a model by being a substring of one; and
        "MX2000 Pro" no longer falls to MX20 on a prefix.
        """
        for label in ("Stage left", "Pro", "MX", "k"):
            profile = devices.coex_profile_for(label)
            assert profile is devices.GENERIC_COEX, label
            assert not profile.model_known
            assert label not in profile.name
        assert devices.coex_profile_for("MX2000 Pro_000001").name == "MX2000 Pro"
        assert devices.coex_profile_for("MX20_000001").name == "MX20"

    def test_the_mx30_port_count_is_the_observed_ten(self) -> None:
        """OBSERVED 2026-09-26 on one MX30 (V1.5.1): SNMP ETHERNET_PORT_COUNT = 10
        and ten type-0 outputStatus entries. The table said 2."""
        mx30 = devices.coex_profile_for("MX30")
        assert mx30.name == "MX30" and mx30.model_known
        assert mx30.port_count == 10
        assert "OBSERVED" in mx30.notes and "REASONED" in mx30.notes  # RJ45 is REASONED
        provenance = devices.PROVENANCE["coex:MX30"]
        for fact in ("OBSERVED", "2026-09-26", "V1.5.1", "ETHERNET_PORT_COUNT",
                     "outputStatus", "REASONED"):
            assert fact in provenance, fact

    def test_the_mx40_pro_count_is_flagged_not_changed(self) -> None:
        """Contradicted by cabinets on six outputs, but no count was read: the
        table keeps its documented value rather than a guess."""
        mx40 = devices.coex_profile_for("MX40 Pro")
        assert mx40.port_count == 4
        assert "CONTRADICTED" in mx40.notes
        assert "CONTRADICTED" in devices.PROVENANCE["coex:MX40 Pro"]
        assert "not observed" in devices.PROVENANCE["coex:MX40 Pro"]

    def test_the_other_coex_counts_are_untouched_and_unflagged(self) -> None:
        expected = {"MX20": 2, "MX2000 Pro": 20, "MX6000 Pro": 20,
                    "CX40 Pro": 4, "CX80 Pro": 8, "KU20": 2}
        for name, ports in expected.items():
            profile = devices.coex_profile_for(name)
            assert (profile.name, profile.port_count, profile.notes) == (name, ports, ""), name
        assert set(devices.COEX_PORT_NOTES) == {"MX30", "MX40 Pro"}

    def test_the_port_note_reaches_the_summary(self) -> None:
        summary = devices.Identification("127.0.0.1", devices.coex_profile_for("MX30")).summary()
        assert "10x Ethernet" in summary and "(assumed)" not in summary
        assert "OBSERVED" in summary

    def test_the_mx30_model_id_is_the_observed_5138(self) -> None:
        """OBSERVED 2026-09-26 (one MX30, hwVersion V1.5.1): GET /api/v1/device/hw
        returned name "MX30" and modelID 5138 in one object."""
        mx30 = devices.coex_profile_for("MX30")
        assert mx30.model_id == 5138 and mx30.model_known
        provenance = devices.PROVENANCE["coex:MX30"]
        for fact in ("model_id 5138", "OBSERVED", "/api/v1/device/hw", '"MX30"',
                     "firmware/list", "backcard/info", "REASONED"):
            assert fact in provenance, fact
        # The HTTP API's ID, not a register-bus one: kept out of MODELS.
        assert 5138 not in devices.MODELS
        assert not profile_for(5138).is_known
        # Only the MX30's ID is known; the rest stay None rather than guessed.
        assert devices.COEX_MODEL_IDS == {"MX30": 5138}
        for name, profile in devices.COEX_MODELS.items():
            if name != "mx30":
                assert profile.model_id is None, name

    def test_coex_profiles_resolve_by_model_id(self) -> None:
        assert devices.coex_profile_for_model_id(5138) is devices.coex_profile_for("MX30")
        for unknown in (None, 0, 9999, True, "5138", 5138.0):
            assert devices.coex_profile_for_model_id(unknown) is devices.GENERIC_COEX, unknown

    def test_hardware_names_the_model_by_name_then_by_id(self) -> None:
        mx30 = devices.coex_profile_for("MX30")
        assert devices.coex_profile_from_hardware("MX30", None) is mx30
        assert devices.coex_profile_from_hardware("", 5138) is mx30
        assert devices.coex_profile_from_hardware(None, 5138) is mx30
        assert devices.coex_profile_from_hardware("MX99 Ultra", 5138) is mx30
        assert devices.coex_profile_from_hardware("MX40 Pro", 5138).name == "MX40 Pro"
        for name, model_id in (("Stage left", None), (None, None), ("MX99", 7)):
            assert devices.coex_profile_from_hardware(name, model_id) is devices.GENERIC_COEX

    def test_a_coex_model_id_prints_in_decimal(self) -> None:
        """5138 is the number the payloads carry; 0x1412 would read as a
        register-bus ID. Register-bus models keep hex."""
        mx30 = devices.Identification("127.0.0.1", devices.coex_profile_for("MX30")).summary()
        assert "  model        MX30  (modelID 5138)" in mx30.splitlines()
        assert "0x1412" not in mx30
        vx4s = devices.Identification("127.0.0.1", profile_for(0x6107)).summary()
        assert "  model        VX4S  (0x6107)" in vx4s.splitlines()

    def test_generic_coex_profile_is_an_assumption_not_a_reading(self) -> None:
        generic = devices.GENERIC_COEX
        assert generic.is_known and not generic.model_known
        assert generic.port_count == 4  # assumed; consumers report None instead
        assert "assumed" in generic.notes
        assert not devices.unknown_profile(0xABCD).model_known
        assert profile_for(0x6205).model_known


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
    def test_reads_device_and_topology(self, coex, coex_server) -> None:
        # /api/v1/device is documented but absent from a real MX40 Pro, so the
        # simulator withholds it by default; this test is about the documented
        # API and opts back in.
        coex_server.state.missing_endpoints.clear()
        assert coex.device_info()["model"] == "MX40 Pro"
        assert len(coex.screens()["screens"]) == 1
        # OBSERVED shapes: cabinets are a bare list; presets are grouped per
        # screen under "screenPresets".
        assert len(coex.cabinets()) == 8
        assert len(coex.presets()["screenPresets"][0]["presets"]) == 2

    def test_display_mode_round_trips(self, coex, coex_server) -> None:
        # The GET of displaymode answers 404 on a real MX40 Pro (OBSERVED), so
        # the simulator withholds it by default. This test is about the
        # documented round trip, and opts the read-back in; whether the PUT
        # exists on that firmware is still UNKNOWN.
        coex_server.state.missing_endpoints.discard("/api/v1/device/screen/displaymode")
        coex.set_display_mode(1)
        assert coex_server.state.display_mode == 1
        assert coex.request("GET", "/api/v1/device/screen/displaymode")["value"] == 1

    def test_cabinet_brightness_applies_to_named_cabinets_only(self, coex, coex_server) -> None:
        target = coex_server.state.cabinets[2]["id"]
        coex.set_cabinet_brightness([target], 0.4)
        assert coex_server.state.cabinet(target)["brightness"] == pytest.approx(0.4)
        assert coex_server.state.cabinets[0]["brightness"] == pytest.approx(1.0)

    def test_screen_brightness_refuses_the_body_an_mx30_ignored(self, coex, coex_server) -> None:
        # {idList, ratio} was answered Success and ignored by an MX30 (OBSERVED
        # 2026-09-26), so the client refuses to send it at all.
        from novasun.coex import IgnoredWrite

        before = [cabinet["brightness"] for cabinet in coex_server.state.cabinets]
        with pytest.raises(IgnoredWrite):
            coex.set_screen_brightness(["screen-1"], 0.25)
        assert [cabinet["brightness"] for cabinet in coex_server.state.cabinets] == before
        assert not any(method == "PUT" for method, _p, _b in coex_server.state.requests)

    def test_preset_recall(self, coex, coex_server) -> None:
        coex.apply_preset("preset-2")
        assert coex_server.state.current_preset == "preset-2"

    def test_new_reads_are_gets_of_the_observed_paths(self) -> None:
        client = CoexClient("127.0.0.1", closed_port())
        sent: list[tuple] = []
        client.request = lambda method, path, body=None: sent.append((method, path, body))
        client.display_state()
        client.hardware_info()
        client.lock_state()
        assert sent == [
            ("GET", "/api/v1/screen/output/display/state", None),
            ("GET", "/api/v1/device/hw", None),
            ("GET", "/api/v1/device/hw/lock", None),
        ]

    def test_nothing_writes_the_lock(self) -> None:
        """The lock is what a VMP session holds (OBSERVED: VMP took it with a
        PUT when it opened). No method may PUT, POST or DELETE it."""
        source = inspect.getsource(coex_module)
        calls = re.findall(r'request\(\s*"(\w+)",\s*f?"([^"]+)"', source)
        assert calls, "the pattern no longer finds request calls"
        assert ("GET", "/api/v1/device/hw/lock") in calls
        for method, path in calls:
            if "lock" in path:
                assert method == "GET", (method, path)
        assert "hw/lock" in inspect.getdoc(CoexClient)  # the reason is written down

    def test_system_time_sends_the_body_vmp_sent(self) -> None:
        """OBSERVED shape (VMP, one MX30, 2026-09-26): UTC fields, isUTC true,
        the client's zone name; keys in VMP's order. Never sent by novasun."""
        client = CoexClient("127.0.0.1", closed_port())
        sent: list[tuple] = []
        client.request = lambda method, path, body=None: sent.append((method, path, body))

        plus_one = timezone(timedelta(hours=1))
        client.set_system_time(datetime(2026, 9, 26, 19, 1, 54, tzinfo=plus_one), "Etc/UTC")
        client.set_system_time("2026-09-26T19:01:54+01:00", "Etc/UTC")
        expected = {"clientTimezone": "Etc/UTC", "second": 54, "minute": 1, "hour": 18,
                    "isUTC": True, "day": 26, "month": 9, "year": 2026}
        assert sent == [("PUT", "/api/v1/device/hw/systemtime", expected)] * 2
        assert list(sent[0][2]) == ["clientTimezone", "second", "minute", "hour",
                                    "isUTC", "day", "month", "year"]
        assert "value" not in sent[0][2]  # the old, unobserved body

        sent.clear()
        client.set_system_time("2026-09-27T00:30:00+01:00", "Etc/UTC")  # the date rolls back
        assert (sent[0][2]["day"], sent[0][2]["hour"], sent[0][2]["minute"]) == (26, 23, 30)

    def test_system_time_refuses_a_naive_time(self) -> None:
        client = CoexClient("127.0.0.1", closed_port())
        sent: list[tuple] = []
        client.request = lambda method, path, body=None: sent.append((method, path, body))
        for naive in (datetime(2026, 9, 26, 19, 1, 54), "2026-09-26T19:01:54"):
            with pytest.raises(ValueError):
                client.set_system_time(naive, "Etc/UTC")
        assert sent == []

    def test_errors_surface_as_exceptions(self, coex) -> None:
        with pytest.raises(CoexError) as error:
            coex.select_input(99)
        assert error.value.code == 1

        with pytest.raises(CoexError) as error:
            coex.request("GET", "/api/v1/device/nonexistent")
        assert error.value.code == 6  # NotSupport, as real firmware answers


class TestRedaction:
    """``randomPassword`` was served to a bare GET of /device/hw (OBSERVED)."""

    def test_secret_named_keys_are_dropped_at_any_depth(self) -> None:
        payload = {
            "name": "MX30",
            "randomPassword": "00000000",
            "cloud": {"username": "", "password": "", "node": ""},
            "list": [{"PASSWORD": "x", "Passwd": "y", "keep": 1}, "text", 3],
        }
        assert redact_secrets(payload) == {
            "name": "MX30",
            "cloud": {"username": "", "node": ""},
            "list": [{"keep": 1}, "text", 3],
        }
        assert payload["randomPassword"] == "00000000"  # the input is not mutated

    def test_everything_else_passes_through(self) -> None:
        for value in (None, 0, "randomPassword", [1, 2], {"a": {"b": [None]}}, {1: "x"}):
            assert redact_secrets(value) == value

    def test_the_client_redacts_every_response(self, monkeypatch) -> None:
        """Through CoexClient.request, so no caller can see the field."""
        import io

        coex = CoexClient("127.0.0.1", closed_port())

        class _Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        body = b'{"code":0,"data":{"name":"MX30","randomPassword":"00000000"},"message":"Success"}'
        monkeypatch.setattr(
            coex_module.urllib.request, "urlopen", lambda request, timeout: _Response(body)
        )
        assert coex.hardware_info() == {"name": "MX30"}
        assert coex.request("GET", "/api/v1/device/hw") == {"name": "MX30"}


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
        # Exactly one cabinet moved, and only the cabinet endpoint carries
        # brightness -- monitor/info reports readings, not settings.
        assert brightness == ["cabinets[0].brightness"]

    def test_snapshot_records_unsupported_endpoints_without_failing(self, coex) -> None:
        # Two kinds of absence, both OBSERVED-or-derived and both recorded rather
        # than raised: an undocumented path (code 6, derived) and a documented
        # endpoint the firmware answers with HTTP 404 (observed on an MX40 Pro).
        result = snapshot(
            coex,
            {"nope": "/api/v1/does/not/exist", "device": "/api/v1/device",
             "screens": "/api/v1/screen"},
        )
        assert "__error__" in result["nope"]
        assert "__error__" in result["device"]
        assert "404" in result["device"]["__error__"]
        assert len(result["screens"]["screens"]) == 1  # the sweep carried on


class TestKeyedDiff:
    """diff_snapshots aligns lists by identity, because the real unit reorders.

    Two monitor/info snapshots of an MX40 Pro 35 minutes apart returned the same
    288 cabinets in a completely different order. Positionally that is 1,974
    spurious changes; by cabinet id it is forty-one flickers of one degree.
    """

    def test_a_reordered_list_with_one_real_change_reports_one_change(self) -> None:
        import copy
        from conftest import MX40_LIKE_MONITOR_INFO

        before = copy.deepcopy(MX40_LIKE_MONITOR_INFO)
        after = copy.deepcopy(MX40_LIKE_MONITOR_INFO)
        after["cabinets"].reverse()                       # the order the unit chose this time
        after["rvCardsRuntime"].reverse()
        after["cabinets"][0]["rvCards"][0]["temperature"]["value"] += 1   # was cabinets[2] before
        changes = diff_snapshots(before, after)
        assert [(p, o, n) for p, o, n in changes] == [
            ("cabinets[2].rvCards[0].temperature.value", 37, 38)
        ]

    def test_an_element_that_disappears_is_reported_as_absent_not_as_noise(self) -> None:
        import copy
        from conftest import MX40_LIKE_MONITOR_INFO

        before = copy.deepcopy(MX40_LIKE_MONITOR_INFO)
        after = copy.deepcopy(MX40_LIKE_MONITOR_INFO)
        gone = after["cabinets"].pop(1)
        after["cabinets"].reverse()
        changes = diff_snapshots(before, after)
        paths = [p for p, _o, _n in changes]
        assert "cabinets[]" in paths                       # the count moved
        assert ("cabinets[1]", before["cabinets"][1], "__absent__") in changes
        assert not any(".rvCards[0].cabinetID" in p for p in paths)   # no id "changes"
        assert gone["rvCards"][0]["cabinetID"] == before["cabinets"][1]["rvCards"][0]["cabinetID"]

    def test_unkeyed_lists_still_diff_positionally(self) -> None:
        assert diff_snapshots([1, 2, 3], [1, 9, 3]) == [("[1]", 2, 9)]
        assert diff_snapshots({"a": [{"x": 1}, {"x": 1}]}, {"a": [{"x": 1}, {"x": 2}]}) == [("a[1].x", 1, 2)]


class TestIdentify:
    def test_identifies_a_coex_controller_over_http(self, coex_server) -> None:
        """With /api/v1/device absent, as on a real MX40 Pro.

        Presence comes from /api/v1/screen and the model from monitor/info's
        name field -- the only identity that firmware's HTTP API offers.
        """
        host, port = coex_server.address
        identification = identify(host, timeout=2.0, http_port=port, control_port=port)

        assert identification.reachable_http
        assert identification.profile.name == "MX40 Pro"
        assert identification.profile.family is Family.COEX
        assert identification.preferred_path == "http"
        assert identification.device_name == "MX40 Pro_000001"
        assert "MX40 Pro" in identification.summary()

    def test_a_renamed_coex_controller_has_no_model(self, coex_server) -> None:
        """A synthetic operator label stands in for the MX30's real one.

        The label is reported as the name and as nothing else: no model, and
        the generic profile's port count marked as the assumption it is.
        """
        coex_server.state.custom_name = "Stage left"
        # /device/hw absent, as the simulator's default may or may not serve
        # it: this pins the behaviour without it. With it, see
        # tests/test_coex_identity.py.
        coex_server.state.missing_endpoints.add("/api/v1/device/hw")
        host, port = coex_server.address
        identification = identify(host, timeout=2.0, http_port=port, register_bus=False)

        assert identification.reachable_http
        assert identification.profile is devices.GENERIC_COEX
        assert not identification.profile.model_known
        assert identification.profile.family is Family.COEX
        assert identification.device_name == "Stage left"
        summary = identification.summary()
        assert "model        unknown" in summary
        assert "name         Stage left" in summary
        assert "model        Stage left" not in summary
        assert "(assumed)" in summary

    def test_a_coex_controller_never_gets_a_register_bus_session(self, coex_server) -> None:
        """The register bus is exclusive; opening it displaces VMP mid-show.

        An earlier identify() probed the bus after HTTP answered "because it is
        useful to know". Pointing control_port at a register-bus simulator and
        asserting it saw nothing pins that it no longer does.
        """
        bus = SimulatedController("127.0.0.1", 0, model_id=0x6205)
        bus.serve_in_thread()
        try:
            host, http_port = coex_server.address
            _host, bus_port = bus.address
            identification = identify(host, timeout=2.0, http_port=http_port, control_port=bus_port)
        finally:
            bus.shutdown()
            bus.server_close()
        assert identification.reachable_http
        assert not identification.reachable_register_bus
        assert bus.log == [], "identify() opened a register-bus session to a COEX controller"

    def test_the_register_bus_can_be_forbidden_outright(self) -> None:
        """register_bus=False must hold even when HTTP is down."""
        bus = SimulatedController("127.0.0.1", 0, model_id=0x6205)
        bus.serve_in_thread()
        try:
            _host, bus_port = bus.address
            identification = identify(
                "127.0.0.1", timeout=1.0, http_port=closed_port(), control_port=bus_port,
                register_bus=False,
            )
        finally:
            bus.shutdown()
            bus.server_close()
        assert not identification.reachable_http
        assert not identification.reachable_register_bus
        assert bus.log == []

    def test_device_info_is_still_used_when_the_firmware_serves_it(self, coex_server) -> None:
        coex_server.state.missing_endpoints.clear()
        host, port = coex_server.address
        identification = identify(host, timeout=2.0, http_port=port, control_port=port)
        assert identification.reachable_http
        assert identification.profile.name == "MX40 Pro"
        assert identification.details.get("sn") == "SIM-MX40-0001"

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
