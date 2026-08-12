"""Screens and persistence: the venue knowledge no probe can recover."""

from __future__ import annotations

import json
import socket

import pytest

from novasun.app import config as config_module
from novasun.app.config import Config, DeviceEntry, load
from novasun.app.screens import Screen, ScreenMember, aggregate, slugify
from novasun.app.state import Application, Device
from novasun.protocol import IO, Target
from novasun.registers import GLOBAL_BRIGHTNESS, KILL_MODE, brightness_byte
from novasun.simulator import SimulatedController

VX4S = 0x6107
UHD_JR = 0x6205


def closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture()
def vx4s():
    server = SimulatedController("127.0.0.1", 0, model_id=VX4S, cards_per_port=2)
    server.serve_in_thread()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture()
def second():
    server = SimulatedController("127.0.0.2", 0, model_id=VX4S, cards_per_port=2)
    server.serve_in_thread()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture()
def app(tmp_path):
    application = Application(
        refresh_interval=60.0, timeout=1.0, config_path=tmp_path / "config.json"
    )
    yield application
    application.stop()


def add(app, server):
    host, port = server.address
    return app.add(host, control_port=port, http_port=closed_port())


class TestScreenModel:
    def test_slug_from_name(self) -> None:
        assert slugify("Main Wall") == "main-wall"
        assert slugify("  Stage Left / IMAG  ") == "stage-left-imag"
        assert slugify("!!!") == "screen"

    def test_member_describes_its_scope(self) -> None:
        assert "ports 0, 1" in ScreenMember("10.0.0.1", ports=[0, 1]).describe()
        assert "whole device" in ScreenMember("10.0.0.1").describe()
        assert ScreenMember("10.0.0.1").whole_device

    def test_screen_lists_addresses_once(self) -> None:
        screen = Screen.create(
            "Wall",
            [
                ScreenMember("10.0.0.1", ports=[0]),
                ScreenMember("10.0.0.1", ports=[1]),
                ScreenMember("10.0.0.2", ports=[0]),
            ],
        )
        assert screen.addresses == ["10.0.0.1", "10.0.0.2"]

    def test_round_trips_through_json(self) -> None:
        screen = Screen.create("Main Wall", [ScreenMember("10.0.0.1", ports=[0, 1])])
        restored = Screen.from_dict(json.loads(json.dumps(screen.to_dict())))
        assert restored == screen


class TestAggregation:
    def state(self, reachability="online", cabinets=(8, 8), temperature=30.0, cards=None):
        return {
            "reachability": reachability,
            "status": {
                "cabinets_total": cabinets[0],
                "cabinets_online": cabinets[1],
                "temperature_c": temperature,
            },
            "receiving_cards": cards or [],
        }

    def test_all_online_is_healthy(self) -> None:
        screen = Screen.create("W", [ScreenMember("a"), ScreenMember("b")])
        result = aggregate(screen, {"a": self.state(), "b": self.state()})
        assert result.reachability == "online"
        assert result.healthy
        assert result.cabinets_total == 16 and result.online_count == 2

    def test_one_member_down_is_partial_not_online(self) -> None:
        """Half a wall reachable is not a healthy screen."""
        screen = Screen.create("W", [ScreenMember("a"), ScreenMember("b")])
        result = aggregate(screen, {"a": self.state(), "b": self.state("unreachable")})
        assert result.reachability == "partial"
        assert not result.healthy
        assert any("unreachable" in problem for problem in result.problems)

    def test_offline_cabinets_are_a_problem(self) -> None:
        screen = Screen.create("W", [ScreenMember("a")])
        result = aggregate(screen, {"a": self.state(cabinets=(8, 6))})
        assert not result.healthy
        assert any("2 cabinet(s) offline" in problem for problem in result.problems)

    def test_unhealthy_receiving_cards_are_a_problem(self) -> None:
        screen = Screen.create("W", [ScreenMember("a")])
        cards = [{"healthy": True}, {"healthy": False}]
        result = aggregate(screen, {"a": self.state(cards=cards)})
        assert any("not running" in problem for problem in result.problems)

    def test_missing_device_is_reported(self) -> None:
        screen = Screen.create("W", [ScreenMember("gone")])
        result = aggregate(screen, {})
        assert result.reachability == "unknown"
        assert any("not in the device list" in problem for problem in result.problems)

    def test_hottest_across_members(self) -> None:
        screen = Screen.create("W", [ScreenMember("a"), ScreenMember("b")])
        result = aggregate(
            screen, {"a": self.state(temperature=28.0), "b": self.state(temperature=41.5)}
        )
        assert result.hottest_c == 41.5


class TestScreenActions:
    def test_screen_action_reaches_only_its_own_ports(self, app, vx4s) -> None:
        """A screen on ports 0-1 must not touch ports 2-3."""
        device = add(app, vx4s)
        app.add_screen("Left", [ScreenMember(device.address, ports=[0, 1])])

        records = app.execute_screen("left", "brightness", percent=30)
        assert all(record.ok for record in records)

        expected = bytes([brightness_byte(30)])
        assert vx4s.card(0, 0).read(GLOBAL_BRIGHTNESS, 1) == expected
        assert vx4s.card(1, 1).read(GLOBAL_BRIGHTNESS, 1) == expected
        # Ports 2 and 3 are untouched, still at the power-on value.
        assert vx4s.card(2, 0).read(GLOBAL_BRIGHTNESS, 1) == b"\xff"
        assert vx4s.card(3, 1).read(GLOBAL_BRIGHTNESS, 1) == b"\xff"

    def test_partial_screen_blackout_uses_receiving_cards(self, app, vx4s) -> None:
        """The processor register would blank the whole output, so it is avoided."""
        device = add(app, vx4s)
        app.add_screen("Left", [ScreenMember(device.address, ports=[0])])
        app.execute_screen("left", "display_mode", mode="blackout")

        assert vx4s.card(0, 0).read(KILL_MODE, 1) == b"\xff"
        assert vx4s.card(1, 0).read(KILL_MODE, 1) == b"\x00"
        # And the processor-level display register was left alone.
        assert vx4s.sender.read(0x0220_0050, 1) == b"\x00"

    def test_whole_device_member_uses_the_broadcast_path(self, app, vx4s) -> None:
        device = add(app, vx4s)
        app.add_screen("All", [ScreenMember(device.address)])
        vx4s.log.clear()
        app.execute_screen("all", "brightness", percent=20)

        writes = [p for p in vx4s.log if p.io == IO.WRITE]
        assert len(writes) == 1  # one broadcast frame, not one per port
        assert writes[0].port == 0xFF

    def test_screen_spanning_two_processors(self, app, vx4s, second) -> None:
        first = add(app, vx4s)
        other = add(app, second)
        app.add_screen(
            "Wide",
            [
                ScreenMember(first.address, ports=[3]),
                ScreenMember(other.address, ports=[0]),
            ],
        )
        records = app.execute_screen("wide", "brightness", percent=70)
        assert len(records) == 2 and all(record.ok for record in records)

        expected = bytes([brightness_byte(70)])
        assert vx4s.card(3, 0).read(GLOBAL_BRIGHTNESS, 1) == expected
        assert second.card(0, 0).read(GLOBAL_BRIGHTNESS, 1) == expected
        assert vx4s.card(0, 0).read(GLOBAL_BRIGHTNESS, 1) == b"\xff"

    def test_one_bad_member_does_not_stop_the_others(self, app, vx4s) -> None:
        """Half a wall staying lit is worse than a partial failure report."""
        device = add(app, vx4s)
        app.add_screen(
            "Mixed",
            [ScreenMember(device.address, ports=[0]), ScreenMember("10.99.99.99")],
        )
        records = app.execute_screen("mixed", "brightness", percent=15)
        assert [record.ok for record in records] == [True, False]
        assert vx4s.card(0, 0).read(GLOBAL_BRIGHTNESS, 1) == bytes([brightness_byte(15)])

    def test_a_port_the_model_lacks_is_refused(self, app, vx4s) -> None:
        device = add(app, vx4s)
        app.add_screen("Bad", [ScreenMember(device.address, ports=[9])])
        records = app.execute_screen("bad", "brightness", percent=50)
        assert not records[0].ok
        assert "no port 9" in (records[0].error or "")

    def test_unknown_screen_is_reported(self, app) -> None:
        records = app.execute_screen("nope", "brightness", percent=10)
        assert len(records) == 1 and not records[0].ok
        assert records[0].error == "no such screen"


class TestPersistence:
    def test_devices_and_screens_survive_a_restart(self, tmp_path, vx4s) -> None:
        path = tmp_path / "config.json"
        host, port = vx4s.address

        first = Application(config_path=path, timeout=1.0)
        first.add(host, control_port=port, http_port=closed_port())
        first.add_screen("Main Wall", [ScreenMember(host, ports=[0, 1])])
        first.save()
        first.stop()

        second = Application.from_config(path, timeout=1.0)
        try:
            assert list(second.devices) == [host]
            assert second.devices[host].state.model == "VX4S"
            screen = second.screens["main-wall"]
            assert screen.name == "Main Wall"
            assert screen.members[0].ports == [0, 1]
        finally:
            second.stop()

    def test_non_standard_ports_are_remembered(self, tmp_path, vx4s) -> None:
        """Otherwise a reload silently talks to 5200 instead."""
        path = tmp_path / "config.json"
        host, port = vx4s.address
        first = Application(config_path=path, timeout=1.0)
        first.add(host, control_port=port, http_port=closed_port())
        first.stop()

        reloaded = Application.from_config(path, timeout=1.0, connect=False)
        try:
            assert reloaded.devices[host]._ports["control_port"] == port
        finally:
            reloaded.stop()

    def test_operator_label_overrides_the_device_name(self, tmp_path, vx4s) -> None:
        host, port = vx4s.address
        device = Device(host, timeout=1.0, label="Upstage", control_port=port,
                        http_port=closed_port())
        device.refresh(force=True)
        try:
            assert device.state.name == "Upstage"
        finally:
            device.close()

    def test_mutations_autosave(self, tmp_path, vx4s) -> None:
        path = tmp_path / "config.json"
        app = Application(config_path=path, timeout=1.0)
        try:
            app.add_screen("Wall")
            assert path.exists()
            assert "Wall" in path.read_text()
            app.remove_screen("wall")
            assert "Wall" not in path.read_text()
        finally:
            app.stop()

    def test_duplicate_screen_names_do_not_merge(self, app) -> None:
        first = app.add_screen("Stage Left")
        second = app.add_screen("Stage Left")
        assert first.identifier == "stage-left"
        assert second.identifier == "stage-left-2"
        assert len(app.screens) == 2

    def test_save_is_atomic(self, tmp_path) -> None:
        path = tmp_path / "config.json"
        Config(devices=[DeviceEntry("10.0.0.1")]).save(path)
        assert json.loads(path.read_text())["devices"][0]["address"] == "10.0.0.1"
        assert not list(tmp_path.glob("*.tmp*"))

    def test_missing_config_is_normal(self, tmp_path) -> None:
        config = load(tmp_path / "absent.json")
        assert config.devices == [] and config.screens == []
        assert config.load_error is None

    def test_corrupt_config_is_moved_aside_not_overwritten(self, tmp_path) -> None:
        path = tmp_path / "config.json"
        path.write_text("{ this is not json")
        config = load(path)

        assert config.load_error and "kept at" in config.load_error
        salvaged = list(tmp_path.glob("config.broken-*.json"))
        assert len(salvaged) == 1
        assert salvaged[0].read_text() == "{ this is not json"

    def test_a_newer_config_version_refuses_rather_than_rewriting(self, tmp_path) -> None:
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"version": 99, "devices": []}))
        with pytest.raises(config_module.ConfigError, match="newer"):
            load(path)
        # And the file is untouched.
        assert json.loads(path.read_text())["version"] == 99


class TestSnapshot:
    def test_screens_appear_in_the_snapshot(self, app, vx4s) -> None:
        device = add(app, vx4s)
        app.add_screen("Main", [ScreenMember(device.address, ports=[0, 1])])
        payload = json.loads(json.dumps(app.snapshot()))

        screen = payload["screens"][0]
        assert screen["name"] == "Main"
        assert screen["reachability"] == "online"
        assert screen["device_count"] == 1
        assert payload["config_path"].endswith("config.json")
