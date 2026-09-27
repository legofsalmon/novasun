"""The MX30 pieces wired together: simulator, fixture, monitor, survey, listener.

Each piece has its own tests (test_coexsim_mx30.py, test_fixtures.py,
test_display_state.py, test_passive_announce.py). These check the joins
between them, which the parallel work on each could not: that the monitor and
the survey read what the MX30-like simulator serves, that the simulator serves
what the fixture records, and that ``randomPassword`` -- served to a bare GET
of ``/api/v1/device/hw`` on one MX30, V1.5.1, 2026-09-26 (OBSERVED) -- reaches
none of what novasun prints, stores or serialises.

Everything here runs on 127.0.0.1.
"""

from __future__ import annotations

import functools
import json
import socket

import pytest

from conftest import (
    MX30_LIKE_ANNOUNCEMENT,
    MX30_LIKE_API,
    MX30_LIKE_DISPLAY_STATE,
    MX30_LIKE_HW,
    MX30_LIKE_HW_LOCK,
    MX30_LIKE_MAC,
    MX30_LIKE_RANDOM_PASSWORD,
)
from novasun import cli, survey as survey_module
from novasun.coex import redact_secrets
from novasun.coexsim import MX30_LIKE_FAKE_RANDOM_PASSWORD, CoexState, SimulatedCoexController
from novasun.monitor import (
    CoexMonitor,
    ReadOnlyCoexClient,
    WriteAttempted,
    interpret_display_state,
    interpret_hardware_info,
)
from novasun.passive import CHANNEL_ANNOUNCEMENT, PassiveListener, decode_announcement
from novasun.survey import survey_device

HW = "/api/v1/device/hw"
DISPLAY_STATE = "/api/v1/screen/output/display/state"
LOCK = "/api/v1/device/hw/lock"
SECRET_VALUES = {MX30_LIKE_FAKE_RANDOM_PASSWORD, MX30_LIKE_RANDOM_PASSWORD}


def closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def skeleton(value):
    """Keys in order, value types and list lengths: the shape without the values."""
    if isinstance(value, dict):
        return [(key, skeleton(item)) for key, item in value.items()]
    if isinstance(value, list):
        return [skeleton(item) for item in value]
    return type(value).__name__


def assert_no_secret(text: str) -> None:
    assert "randomPassword" not in text
    # As a quoted value, not a substring: 600000000 is an ordinary reading.
    for secret in SECRET_VALUES:
        assert f'"{secret}"' not in text and f"'{secret}'" not in text


@pytest.fixture()
def mx30():
    server = SimulatedCoexController("127.0.0.1", 0, CoexState(model="MX30"))
    server.serve_in_thread()
    yield server
    server.shutdown()
    server.server_close()


class TestSimulatorServesTheFixture:
    """The simulator and the fixture were written in parallel; they must agree."""

    @pytest.mark.parametrize("path", [HW, DISPLAY_STATE, LOCK])
    def test_shapes_match(self, mx30, path) -> None:
        host, port = mx30.address
        # CoexClient.request redacts, so compare against the redacted fixture.
        body = ReadOnlyCoexClient(host, port, timeout=2.0).request("GET", path)
        assert skeleton(body) == skeleton(redact_secrets(MX30_LIKE_API[path]))

    def test_the_raw_hw_body_carries_the_field_to_be_dropped(self, mx30) -> None:
        """The simulator serves it, as the unit did, so the redaction is exercised."""
        import urllib.request

        host, port = mx30.address
        with urllib.request.urlopen(f"http://{host}:{port}{HW}", timeout=2.0) as response:
            raw = json.loads(response.read())["data"]
        assert raw["randomPassword"] == MX30_LIKE_FAKE_RANDOM_PASSWORD == MX30_LIKE_RANDOM_PASSWORD
        assert skeleton(raw) == skeleton(MX30_LIKE_HW)

    def test_a_live_wall_and_an_idle_lock_read_as_recorded(self, mx30) -> None:
        host, port = mx30.address
        client = ReadOnlyCoexClient(host, port, timeout=2.0)
        assert client.display_state() == MX30_LIKE_DISPLAY_STATE
        assert client.lock_state() == MX30_LIKE_HW_LOCK


class TestReadersAcceptTheFixture:
    def test_hw_identity(self) -> None:
        identity = interpret_hardware_info(MX30_LIKE_HW)
        assert identity["model"] == "MX30" and identity["model_id"] == 5138
        assert identity["firmware"] == "V1.5.1"
        assert_no_secret(json.dumps(identity))
        assert "randomPassword" not in redact_secrets(MX30_LIKE_HW)
        assert "randomPassword" in MX30_LIKE_HW  # redaction copies; the fixture is untouched

    def test_display_state(self) -> None:
        display = interpret_display_state(MX30_LIKE_DISPLAY_STATE)
        assert display["display_mode"] == 0 and display["display"] == "normal"
        assert [c["canvas_id"] for c in display["canvases"]] == [2048]

    def test_announcement(self) -> None:
        decoded = decode_announcement(MX30_LIKE_ANNOUNCEMENT["payload"].encode("ascii"))
        assert not decoded.error and len(decoded.entries) == 1
        entry = decoded.entries[0]
        assert entry.mac == MX30_LIKE_MAC == MX30_LIKE_HW["mac"]
        assert entry.api_port == 8001


class TestMonitorReadsTheSimulator:
    def test_identity_and_display_come_from_the_new_endpoints(self, mx30) -> None:
        host, port = mx30.address
        with CoexMonitor(host, port, interval=0.0) as monitor:
            snapshot = monitor.poll()
            assert snapshot.model == "MX30" and snapshot.model_id == 5138
            assert snapshot.firmware == "V1.5.1"
            assert snapshot.display_mode == 0 and snapshot.display == "normal"
            assert "hardware" not in snapshot.errors and "display_state" not in snapshot.errors

            mx30.state.display_mode = 2  # a front-panel freeze
            frozen = monitor.poll()
            assert frozen.display_mode == 2 and frozen.display == "freeze"

            mx30.state.display_mode = 1
            blacked = monitor.poll()
            assert blacked.display_mode == 1
            assert all(c["confidence"] == "OBSERVED" for c in blacked.display_canvases)

            mx30.state.display_mode = 0
            assert monitor.poll().display == "normal"

        assert "  display" in frozen.summary()
        assert_no_secret(repr(frozen) + frozen.summary() + json.dumps(frozen.raw, default=str))

    def test_monitoring_sends_only_gets_and_never_touches_the_lock(self, mx30) -> None:
        host, port = mx30.address
        with CoexMonitor(host, port, interval=0.0) as monitor:
            for _ in range(3):
                monitor.poll()
        assert {method for method, _path, _body in mx30.state.requests} == {"GET"}
        assert LOCK not in {path for _method, path, _body in mx30.state.requests}
        assert mx30.state.lock_ip is None and mx30.state.system_time is None


class TestSurveyOfTheSimulator:
    def test_survey_json_names_the_model_and_display_and_no_secret(
        self, mx30, monkeypatch, capsys
    ) -> None:
        """``novasun survey --no-probe --json`` end to end, pointed at the simulator."""
        host, port = mx30.address
        mx30.state.display_mode = 2
        monkeypatch.setattr(
            survey_module,
            "survey_device",
            functools.partial(survey_device, http_port=port, control_port=closed_port()),
        )
        status = cli.main(["survey", "--no-probe", "--json", host])
        out = capsys.readouterr().out

        assert status == 0
        document = json.loads(out)
        (device,) = document["devices"]
        assert device["model"] == "MX30" and device["model_id"] == 5138
        assert device["firmware"] == "V1.5.1"
        assert device["status"]["display_mode"] == 2
        assert device["status"]["display"] == "freeze"
        assert_no_secret(out)
        # Read-only: GETs over HTTP, and nothing was probed or locked.
        assert {method for method, _path, _body in mx30.state.requests} == {"GET"}
        assert document["probed"] is False
        assert mx30.state.lock_ip is None

    def test_survey_summary_carries_no_secret(self, mx30) -> None:
        host, port = mx30.address
        device = survey_device(host, http_port=port, control_port=closed_port())
        assert device.model == "MX30"
        assert "  display: normal" in device.summary().splitlines()
        assert_no_secret(device.summary() + repr(device))


class TestReadOnlyClientAgainstTheSimulator:
    def test_every_write_the_mx30_profile_answers_is_refused_first(self, mx30) -> None:
        host, port = mx30.address
        client = ReadOnlyCoexClient(host, port, timeout=2.0)
        for method, path, body in (
            ("PUT", LOCK, {"appids": ["x"]}),
            ("PUT", "/api/v1/device/hw/systemtime", {}),
            ("PUT", "/api/v1/device/snmpstate", {"state": True}),
            ("POST", HW, None),
            ("DELETE", HW, None),
        ):
            with pytest.raises(WriteAttempted):
                client.request(method, path, body)
        assert mx30.state.requests == []  # refused before a socket opened


class TestListenerHearsTheSimulator:
    def test_the_simulated_announcement_is_inventoried(self, mx30) -> None:
        listener = PassiveListener(
            "127.0.0.1", None, join_multicast=False, announcement_ports=(0,)
        )
        try:
            (bound,) = listener.coverage[CHANNEL_ANNOUNCEMENT]
            thread = listener.listen_in_thread(duration=3.0)
            mx30.start_announcing("127.0.0.1", ports=(bound,), interval=0.1)
            assert listener.wait_for(2, timeout=2.5)
        finally:
            mx30.stop_announcing()
            listener.stop()
            thread.join(timeout=3.0)
        inventory = listener.inventory()
        (entry,) = inventory.announcers.values()
        assert entry.address == "127.0.0.1"
        assert entry.mac == MX30_LIKE_MAC == mx30.state.mac
        assert entry.api_port == mx30.address[1]
        assert not inventory.malformed
