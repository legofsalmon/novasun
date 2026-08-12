"""The application layer: multi-device state, safety properties, and the API."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request

import pytest

from novasun.app.server import NovasunServer
from novasun.app.state import DESTRUCTIVE, Application, Reachability
from novasun.coexsim import SimulatedCoexController
from novasun.registers import GLOBAL_BRIGHTNESS, KILL_MODE, SELF_TEST_MODE, brightness_byte
from novasun.simulator import SimulatedController

VX4S = 0x6107
UHD_JR = 0x6205


def closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture()
def vx4s():
    server = SimulatedController("127.0.0.1", 0, model_id=VX4S)
    server.serve_in_thread()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture()
def coex():
    # A second loopback address: the application keys devices by address, which
    # is right for real hardware and means two simulators need two addresses.
    server = SimulatedCoexController("127.0.0.2", 0)
    server.serve_in_thread()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture()
def app():
    application = Application(refresh_interval=60.0, timeout=1.0)
    yield application
    application.stop()


def add_register_device(app, server):
    host, port = server.address
    return app.add(host, control_port=port, http_port=closed_port())


def add_coex_device(app, server):
    host, port = server.address
    return app.add(host, http_port=port, control_port=closed_port())


class TestDeviceState:
    def test_a_register_bus_device_comes_up(self, app, vx4s) -> None:
        device = add_register_device(app, vx4s)
        state = device.state
        assert state.reachability == Reachability.ONLINE.value
        assert state.model == "VX4S"
        assert state.control_path == "register-bus"
        assert state.ethernet_ports == 4
        assert state.capabilities["select_input"]
        assert state.capabilities["panel_lock"]
        assert state.capabilities["test_pattern"]

    def test_a_coex_device_comes_up(self, app, coex) -> None:
        device = add_coex_device(app, coex)
        state = device.state
        assert state.reachability == Reachability.ONLINE.value
        assert state.model == "MX40 Pro"
        assert state.control_path == "http"
        assert state.status["cabinets_total"] == 8
        # Test patterns are refused on COEX: the mode numbering is unknown.
        assert not state.capabilities["test_pattern"]

    def test_unreachable_is_a_state_not_an_exception(self, app) -> None:
        device = app.add("127.0.0.1", control_port=closed_port(), http_port=closed_port())
        assert device.state.reachability == Reachability.UNREACHABLE.value
        assert device.state.last_error
        assert json.dumps(device.state.to_dict())

    def test_unreachable_devices_back_off(self, app) -> None:
        device = app.add("127.0.0.1", control_port=closed_port(), http_port=closed_port())
        first = device.state.next_retry
        device.refresh()  # too soon: should not retry yet
        assert device.state.next_retry == first

    def test_uhd_jr_inputs_are_listed_but_flagged(self, app) -> None:
        server = SimulatedController("127.0.0.1", 0, model_id=UHD_JR)
        server.serve_in_thread()
        try:
            device = add_register_device(app, server)
            assert device.state.ethernet_ports == 16
            assert device.state.fibre_ports == 4
            assert device.state.inputs
            # Every input present, none switchable -- the UI greys them out.
            assert not any(entry["switchable"] for entry in device.state.inputs)
            assert not device.state.capabilities["select_input"]
        finally:
            server.shutdown()
            server.server_close()


class TestActions:
    def test_brightness_reaches_the_device(self, app, vx4s) -> None:
        device = add_register_device(app, vx4s)
        record = app.execute(device.address, "brightness", percent=60)
        assert record.ok
        assert vx4s.card(0, 0).read(GLOBAL_BRIGHTNESS, 1) == bytes([brightness_byte(60)])

    def test_input_switch_uses_the_model_register(self, app, vx4s) -> None:
        device = add_register_device(app, vx4s)
        assert app.execute(device.address, "select_input", label="HDMI").ok
        assert vx4s.sender.read(0x0220_002D, 1) == b"\xa0"

    def test_display_mode_uses_the_model_value(self, app, vx4s) -> None:
        device = add_register_device(app, vx4s)
        app.execute(device.address, "display_mode", mode="blackout")
        assert vx4s.sender.read(0x0220_0050, 1) == b"\x02"  # 2 is blackout here
        app.execute(device.address, "display_mode", mode="freeze")
        assert vx4s.sender.read(0x0220_0050, 1) == b"\x01"

    def test_test_pattern_by_name(self, app, vx4s) -> None:
        device = add_register_device(app, vx4s)
        assert app.execute(device.address, "test_pattern", pattern="blue").ok
        assert vx4s.card(0, 0).read(SELF_TEST_MODE, 1) == b"\x04"

    def test_unknown_capability_fails_without_writing(self, app) -> None:
        """A UHD Jr input switch must not put a guessed byte on the wire."""
        server = SimulatedController("127.0.0.1", 0, model_id=UHD_JR)
        server.serve_in_thread()
        try:
            device = add_register_device(app, server)
            server.log.clear()
            record = app.execute(device.address, "select_input", label="HDMI 2.0")
            assert not record.ok
            assert "not been established" in (record.error or "")
            assert not any(packet.io == 1 for packet in server.log)
        finally:
            server.shutdown()
            server.server_close()

    def test_actions_are_recorded_with_their_outcome(self, app, vx4s) -> None:
        device = add_register_device(app, vx4s)
        app.execute(device.address, "brightness", percent=40)
        app.execute(device.address, "select_input", label="NOPE")
        history = app.snapshot()["history"]
        assert history[0]["action"] == "select_input" and not history[0]["ok"]
        assert history[1]["action"] == "brightness" and history[1]["ok"]

    def test_action_on_an_unknown_device_is_reported(self, app) -> None:
        record = app.execute("10.0.0.99", "brightness", percent=10)
        assert not record.ok and record.error == "no such device"

    def test_state_reflects_the_change_immediately(self, app, coex) -> None:
        """No waiting for the next tick to see what you just did."""
        device = add_coex_device(app, coex)
        app.execute(device.address, "display_mode", mode="blackout")
        assert coex.state.display_mode == 1  # COEX: 1 is blackout

    def test_destructive_actions_are_labelled_for_the_ui(self) -> None:
        assert {"blackout", "freeze", "display_mode", "test_pattern"} <= DESTRUCTIVE
        assert "brightness" not in DESTRUCTIVE

    def test_flash_and_factory_reset_are_not_exposed(self, app, vx4s) -> None:
        """The application layer offers no route to the destructive registers."""
        device = add_register_device(app, vx4s)
        for action in ("save_to_flash", "factory_reset", "write"):
            record = app.execute(device.address, action)
            assert not record.ok
            assert "unknown action" in (record.error or "")


class TestSnapshot:
    def test_snapshot_serialises(self, app, vx4s, coex) -> None:
        add_register_device(app, vx4s)
        add_coex_device(app, coex)
        payload = json.dumps(app.snapshot())
        restored = json.loads(payload)
        assert len(restored["devices"]) == 2
        assert {entry["family"] for entry in restored["devices"]} == {
            "video-processor",
            "coex",
        }

    def test_readd_with_different_ports_replaces_the_entry(self, app, vx4s) -> None:
        host, port = vx4s.address
        first = app.add(host, control_port=port, http_port=closed_port())
        second = app.add(host, control_port=closed_port(), http_port=closed_port())
        assert second is not first
        assert len(app.devices) == 1

    def test_removing_a_device_closes_it(self, app, vx4s) -> None:
        device = add_register_device(app, vx4s)
        assert app.remove(device.address)
        assert not app.snapshot()["devices"]
        assert not app.remove(device.address)


class TestHttpService:
    @pytest.fixture()
    def service(self, app, vx4s):
        add_register_device(app, vx4s)
        server = NovasunServer(app, "127.0.0.1", 0)
        server.serve_in_thread()
        yield server, app, vx4s
        server.shutdown()
        server.server_close()

    def call(self, server, path, method="GET", body=None):
        host, port = server.address
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            f"http://{host}:{port}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"{}")

    def test_state_endpoint(self, service) -> None:
        server, _app, _vx4s = service
        status, payload = self.call(server, "/api/state")
        assert status == 200
        assert payload["devices"][0]["model"] == "VX4S"
        assert "blackout" in payload["destructive_actions"]

    def test_ui_is_served(self, service) -> None:
        server, _app, _vx4s = service
        host, port = server.address
        with urllib.request.urlopen(f"http://{host}:{port}/", timeout=5) as response:
            body = response.read().decode()
        assert "novasun" in body and "/api/state" in body

    def test_action_endpoint_drives_the_device(self, service) -> None:
        server, app, vx4s = service
        address = next(iter(app.devices))
        status, payload = self.call(
            server,
            "/api/action",
            "POST",
            {"address": address, "action": "brightness", "percent": 25},
        )
        assert status == 200 and payload["result"]["ok"]
        assert vx4s.card(0, 0).read(GLOBAL_BRIGHTNESS, 1) == bytes([brightness_byte(25)])

    def test_failed_action_returns_conflict(self, service) -> None:
        server, app, _vx4s = service
        address = next(iter(app.devices))
        status, payload = self.call(
            server, "/api/action", "POST", {"address": address, "action": "nonsense"}
        )
        assert status == 409
        assert not payload["result"]["ok"]

    def test_add_and_remove_over_http(self, service) -> None:
        server, _app, _vx4s = service
        status, payload = self.call(
            server, "/api/devices", "POST", {"address": "127.0.0.2"}
        )
        assert status == 200
        assert any(entry["address"] == "127.0.0.2" for entry in payload["devices"])

        status, payload = self.call(server, "/api/devices/127.0.0.2", "DELETE")
        assert status == 200
        assert not any(entry["address"] == "127.0.0.2" for entry in payload["devices"])

    def test_missing_fields_are_rejected(self, service) -> None:
        server, _app, _vx4s = service
        status, _payload = self.call(server, "/api/action", "POST", {"action": "brightness"})
        assert status == 400

    def test_unknown_route(self, service) -> None:
        server, _app, _vx4s = service
        assert self.call(server, "/api/nope")[0] == 404


class TestBlackoutSafety:
    def test_blackout_is_recorded_and_reversible(self, app, vx4s) -> None:
        device = add_register_device(app, vx4s)
        app.execute(device.address, "blackout", enabled=True)
        assert vx4s.sender.read(0x0220_0050, 1) == b"\x02"
        app.execute(device.address, "blackout", enabled=False)
        assert vx4s.sender.read(0x0220_0050, 1) == b"\x00"
        actions = [record["action"] for record in app.snapshot()["history"]]
        assert actions.count("blackout") == 2

    def test_receiving_card_fallback_for_sending_cards(self, app) -> None:
        server = SimulatedController("127.0.0.1", 0, model_id=0x1107)  # MCTRL660 Pro
        server.serve_in_thread()
        try:
            device = add_register_device(app, server)
            app.execute(device.address, "blackout", enabled=True)
            assert server.card(0, 0).read(KILL_MODE, 1) == b"\xff"
        finally:
            server.shutdown()
            server.server_close()


class TestReceivingCards:
    def test_scan_finds_the_chain(self, app, vx4s) -> None:
        device = add_register_device(app, vx4s)
        assert device.state.capabilities["scan_cards"]
        assert device.state.receiving_cards == []  # not scanned on every refresh

        record = app.execute(device.address, "scan_cards")
        assert record.ok
        expected = vx4s.port_count * vx4s.cards_per_port
        assert len(device.state.receiving_cards) == expected
        assert device.state.cards_scanned_at is not None
        assert all(card["healthy"] for card in device.state.receiving_cards)
        assert json.dumps(device.state.to_dict())

    def test_scanning_is_not_part_of_the_refresh_tick(self, app, vx4s) -> None:
        """A chain walk is a round trip per position; it must be opt-in."""
        device = add_register_device(app, vx4s)
        vx4s.log.clear()
        device.refresh(force=True)
        probes = [p for p in vx4s.log if p.address == 0x0000_0000 and p.device_type == 1]
        assert probes == []

    def test_coex_refuses_a_chain_walk(self, app, coex) -> None:
        """COEX reports cabinets over HTTP; walking the bus is the wrong tool."""
        device = add_coex_device(app, coex)
        assert not device.state.capabilities["scan_cards"]
        record = app.execute(device.address, "scan_cards")
        assert not record.ok
        assert "cabinets" in (record.error or "")


class TestScreenHttp:
    @pytest.fixture()
    def service(self, tmp_path, vx4s):
        from novasun.app.state import Application

        app = Application(refresh_interval=60.0, timeout=1.0,
                          config_path=tmp_path / "config.json")
        host, port = vx4s.address
        app.add(host, control_port=port, http_port=closed_port())
        server = NovasunServer(app, "127.0.0.1", 0)
        server.serve_in_thread()
        yield server, app, vx4s
        server.shutdown()
        server.server_close()
        app.stop()

    def call(self, server, path, method="GET", body=None):
        host, port = server.address
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            f"http://{host}:{port}{path}", data=data, method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"{}")

    def test_create_drive_and_delete_a_screen(self, service) -> None:
        server, app, vx4s = service
        address = next(iter(app.devices))

        status, payload = self.call(
            server, "/api/screens", "POST",
            {"name": "Main Wall", "members": [{"address": address, "ports": [0, 1]}]},
        )
        assert status == 200
        identifier = payload["screen"]["identifier"]
        assert identifier == "main-wall"

        status, payload = self.call(
            server, f"/api/screens/{identifier}/action", "POST",
            {"action": "brightness", "percent": 35},
        )
        assert status == 200 and all(r["ok"] for r in payload["results"])
        assert vx4s.card(0, 0).read(GLOBAL_BRIGHTNESS, 1) == bytes([brightness_byte(35)])
        assert vx4s.card(2, 0).read(GLOBAL_BRIGHTNESS, 1) == b"\xff"  # not in the screen

        status, payload = self.call(server, f"/api/screens/{identifier}", "DELETE")
        assert status == 200 and payload["screens"] == []

    def test_renaming_a_screen(self, service) -> None:
        server, _app, _vx4s = service
        _status, payload = self.call(server, "/api/screens", "POST", {"name": "Wall"})
        identifier = payload["screen"]["identifier"]
        status, payload = self.call(
            server, f"/api/screens/{identifier}", "POST", {"name": "Upstage Wall"}
        )
        assert status == 200 and payload["screen"]["name"] == "Upstage Wall"

    def test_partial_screen_failure_reports_conflict(self, service) -> None:
        server, _app, _vx4s = service
        self.call(
            server, "/api/screens", "POST",
            {"name": "Broken", "members": [{"address": "10.99.99.99"}]},
        )
        status, payload = self.call(
            server, "/api/screens/broken/action", "POST",
            {"action": "brightness", "percent": 10},
        )
        assert status == 409
        assert not payload["results"][0]["ok"]

    def test_unknown_screen_is_404(self, service) -> None:
        server, _app, _vx4s = service
        assert self.call(server, "/api/screens/nope", "DELETE")[0] == 404
        assert self.call(server, "/api/screens/nope", "POST", {"name": "x"})[0] == 404
