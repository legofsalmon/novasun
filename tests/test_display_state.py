"""Display state from ``GET /api/v1/screen/output/display/state``.

What hardware settled (one MX30, firmware/hwVersion V1.5.1, 2026-09-26):

* ``displayState[].displayMode`` read 2 for the whole of an attended
  front-panel freeze and 0 before and after it, polled once a second, per
  ``canvasID`` (OBSERVED). The unit's websocket pushed the same values at that
  freeze and at a second one captured from VMP (OBSERVED).
* 1 = blackout was REASONED from the documented COEX enum when these tests were
  written; an attended front-panel blackout later the same evening read 1 on
  this endpoint and on the websocket (OBSERVED once). The code's label for 1,
  asserted below, predates that.
* The documented ``/api/v1/device/screen/displaymode`` GET was absent on both
  units ever read (OBSERVED), which is why display state used to be unknown.

Everything here is synthetic: payloads written inline with the real keys and
types and none of the real values, served by :class:`SyntheticCoexUnit`, a
path-to-payload table on 127.0.0.1. Nothing depends on the COEX simulator or on
``conftest.py``, so these tests pin the monitor's behaviour whatever the
simulator happens to serve. Other test modules import the unit from here.
"""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from novasun import devices
from novasun.monitor import (
    DISPLAY_MODE_CONFIDENCE,
    DISPLAY_MODE_NAMES,
    MONITORING_ENDPOINTS,
    CoexMonitor,
    MonitorSnapshot,
    _interpret,
    interpret_display_state,
)
from novasun.survey import Survey, survey_device

DISPLAY_STATE = "/api/v1/screen/output/display/state"
HARDWARE = "/api/v1/device/hw"
MONITOR_INFO = "/api/v1/device/monitor/info"

CANVAS = 2048  # the MX30's only canvas; the id itself is not show data
LABEL = "Stage left"  # synthetic operator label; the real one is show data

#: An obviously fake stand-in for /device/hw's randomPassword. Nothing else in
#: these payloads contains eight zeros, so finding it anywhere is a leak.
FAKE_RANDOM_PASSWORD = "00000000"

EMPTY_200 = object()
"""Route value: HTTP 200, Content-Length 0, no Content-Type -- the MX30's absent path."""


def display_state(*modes: Any, canvases: tuple[int, ...] | None = None) -> dict[str, Any]:
    """A display/state ``data`` object: one displayState entry per mode."""
    ids = canvases or tuple(CANVAS + index for index in range(len(modes)))
    return {
        "mappingState": [{"canvasID": canvas, "enable": False} for canvas in ids],
        "displayState": [
            {"canvasID": canvas, "displayMode": mode} for canvas, mode in zip(ids, modes)
        ],
    }


def hardware(**overrides: Any) -> dict[str, Any]:
    """A /device/hw ``data`` object: real keys and types, synthetic values."""
    payload: dict[str, Any] = {
        "name": "MX30",
        "customName": LABEL,
        "modelID": 5138,
        "sn": "SIM-MX30-SERIAL-0030",  # 20 characters, as the unit's was
        "thirdPartySn": "",
        "thirdPartySerial": "",
        "mac": "00:00:5e:00:53:30",
        "type": "G3.5",
        "hwVersion": "V1.5.1",
        "swVersion": "1.0.0",
        "mcuVersion": "V1.0.0",
        "fpgaVersion": "V1.0.0.S1.T1.V9",
        "configVersion": "V1.4.0.1",
        "softVersion": {"Package": "", "Version": "", "Architecture": "",
                        "Maintainer": "", "Description": ""},
        "ip": "192.0.2.30",
        "IpNetmask": "255.255.255.0",
        "IpGateway": "192.0.2.1",
        "dhcp": False,
        "WirelessIpAddress": "",
        "mode": 3,
        "companyName": "",
        "deviceWorkMode": 0,
        "uptime": 32460,
        "deviceUUID": "{5e0053aa-bbbb-4ccc-8ddd-eeeeeeeeee30}",
        "groupName": "",
        "capability": {"capabilityVersion": "V4.1.0", "snmp": True, "artNet": True,
                       "NTP": True, "inputImageEcho": True, "outputImageEcho": True},
        "encipher": {"vendorID": 0, "authState": 0, "authStartTime": "",
                     "authEndTime": "", "isOverRange": False},
        "randomPassword": FAKE_RANDOM_PASSWORD,
    }
    payload.update(overrides)
    return payload


def monitor_info(name: str = LABEL) -> dict[str, Any]:
    """The top of a monitor/info payload: enough for the name, no cabinets."""
    return {"name": name, "runtime": 32460, "cabinets": []}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:  # noqa: D102 - keep test output quiet
        pass

    def _reply(self, status: int, payload: bytes | None) -> None:
        self.send_response(status)
        if payload is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload or b"")))
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        path = self.path.split("?")[0].rstrip("/")
        self.server.requests.append(("GET", path))  # type: ignore[attr-defined]
        route = self.server.routes.get(path, EMPTY_200)  # type: ignore[attr-defined]
        if route is EMPTY_200:
            return self._reply(200, None)
        if isinstance(route, int):
            return self._reply(route, None)
        envelope = {"code": 0, "data": route, "message": "Success"}
        self._reply(200, json.dumps(envelope, separators=(",", ":")).encode())

    def _refuse(self) -> None:
        self.server.requests.append((self.command, self.path))  # type: ignore[attr-defined]
        self._reply(405, None)

    do_PUT = do_POST = do_DELETE = _refuse


class SyntheticCoexUnit(ThreadingHTTPServer):
    """A fake COEX unit on 127.0.0.1 that serves exactly the routes it is given.

    ``routes`` maps a path to the ``data`` to wrap in a Success envelope, to an
    int HTTP status (sent with no body), or to :data:`EMPTY_200`. Unlisted
    paths answer the empty 200 the MX30 gave absent paths (OBSERVED). Every
    request is recorded; anything but a GET is refused and recorded, so a test
    can assert that nothing wrote.
    """

    daemon_threads = True

    def __init__(self, routes: dict[str, Any]) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.routes = dict(routes)
        self.requests: list[tuple[str, str]] = []
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()

    @property
    def address(self) -> tuple[str, int]:
        host, port = self.server_address[:2]
        return str(host), int(port)

    def stop(self) -> None:
        self.shutdown()
        self.server_close()
        self._thread.join(timeout=2)


def closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture()
def unit():
    """A synthetic MX30-like unit: a live wall on one canvas, /device/hw served."""
    server = SyntheticCoexUnit({
        MONITOR_INFO: monitor_info(),
        DISPLAY_STATE: display_state(0),
        HARDWARE: hardware(),
    })
    yield server
    server.stop()


# --- the mapping -------------------------------------------------------------


class TestInterpretDisplayState:
    def test_a_live_wall_reads_normal(self) -> None:
        state = interpret_display_state(display_state(0))
        assert state["display_mode"] == 0
        assert state["display"] == "normal"
        assert state["canvases"] == [
            {"canvas_id": CANVAS, "display_mode": 0, "state": "normal", "confidence": "OBSERVED"}
        ]

    def test_a_front_panel_freeze_reads_freeze(self) -> None:
        state = interpret_display_state(display_state(2))
        assert (state["display_mode"], state["display"]) == (2, "freeze")
        assert state["canvases"][0]["confidence"] == "OBSERVED"

    def test_blackout_is_observed(self) -> None:
        # An attended front-panel blackout read 1 (OBSERVED 2026-09-26).
        state = interpret_display_state(display_state(1))
        assert (state["display_mode"], state["display"]) == (1, "blackout")
        assert state["canvases"][0]["confidence"] == "OBSERVED"

    @pytest.mark.parametrize("payload", [
        None, {}, [], "", 0,
        {"displayState": []},
        {"displayState": None},
        {"displayState": "2"},
        {"mappingState": [{"canvasID": CANVAS, "enable": False}]},  # no displayState
        {"displayState": ["not a dict", 2]},
    ])
    def test_absent_empty_or_malformed_is_unknown_never_normal(self, payload: Any) -> None:
        """``{}`` is what the client makes of the MX30's empty 200."""
        state = interpret_display_state(payload)
        assert state["display_mode"] is None
        assert state["display"] == "unknown"

    @pytest.mark.parametrize("value", [3, -1, 255, "2", "0", 2.0, 0.0, True, False, None, {"value": 2}])
    def test_an_unrecognised_value_is_unknown(self, value: Any) -> None:
        """Including bools: in Python ``False == 0`` and ``True == 1``."""
        state = interpret_display_state(display_state(value))
        assert state["display_mode"] is None
        assert state["display"] == "unknown"
        assert state["canvases"] == [
            {"canvas_id": CANVAS, "display_mode": None, "state": "unknown", "confidence": "UNKNOWN"}
        ]

    def test_canvases_that_differ_are_mixed_and_kept_apart(self) -> None:
        state = interpret_display_state(display_state(0, 2, canvases=(2048, 2049)))
        assert state["display_mode"] is None  # no single answer to give
        assert state["display"] == "mixed"
        assert [(c["canvas_id"], c["state"]) for c in state["canvases"]] == [
            (2048, "normal"), (2049, "freeze")
        ]

    def test_canvases_that_agree_give_one_answer(self) -> None:
        state = interpret_display_state(display_state(2, 2, canvases=(2048, 2049)))
        assert (state["display_mode"], state["display"]) == (2, "freeze")

    def test_one_unreadable_canvas_makes_the_whole_unknown(self) -> None:
        """A frozen canvas beside an unreadable one is not reported as frozen overall."""
        state = interpret_display_state(display_state(2, 7, canvases=(2048, 2049)))
        assert (state["display_mode"], state["display"]) == (None, "unknown")
        assert [c["state"] for c in state["canvases"]] == ["freeze", "unknown"]

    def test_a_missing_canvas_id_does_not_hide_the_mode(self) -> None:
        state = interpret_display_state({"displayState": [{"displayMode": 2}]})
        assert state["display"] == "freeze"
        assert state["canvases"][0]["canvas_id"] is None

    def test_an_envelope_left_on_is_tolerated(self) -> None:
        wrapped = {"code": 0, "data": display_state(2), "message": "Success"}
        assert interpret_display_state(wrapped)["display"] == "freeze"

    def test_it_never_raises(self) -> None:
        for junk in (object(), 7.5, b"\x00", {"displayState": [{"displayMode": [2]}]},
                     {"displayState": [{"canvasID": "x", "displayMode": {"v": 1}}]},
                     {"data": "nope"}, {"data": {"displayState": {"a": 1}}}):
            interpret_display_state(junk)  # must not raise

    def test_the_mapping_is_the_coex_convention(self) -> None:
        """1 blackout, 2 freeze -- the HTTP API's, not the VX4S register's."""
        assert DISPLAY_MODE_NAMES == {0: "normal", 1: "blackout", 2: "freeze"}
        coex = devices.coex_profile_for("MX30").display
        for value, name in DISPLAY_MODE_NAMES.items():
            assert coex.value_for(name) == value

    def test_the_confidence_labels(self) -> None:
        assert DISPLAY_MODE_CONFIDENCE == {0: "OBSERVED", 2: "OBSERVED", 1: "OBSERVED"}


# --- the snapshot ------------------------------------------------------------


def _snapshot(**raw: Any) -> MonitorSnapshot:
    return _interpret(MonitorSnapshot(timestamp=0.0, raw=raw))


class TestSnapshotDisplay:
    def test_display_mode_comes_from_display_state(self) -> None:
        snapshot = _snapshot(display_state=display_state(2))
        assert snapshot.display_mode == 2
        assert snapshot.display == "freeze"
        assert snapshot.display_canvases[0]["canvas_id"] == CANVAS
        assert "  display     freeze" in snapshot.summary().splitlines()

    def test_an_unread_display_is_said_to_be_unknown(self) -> None:
        """Always a line, so a missing reading cannot pass for a live wall."""
        for raw in ({}, {"display_state": {}}, {"display_state": None}):
            snapshot = _snapshot(**raw)
            assert snapshot.display_mode is None
            assert snapshot.display == "unknown"
            assert "  display     unknown" in snapshot.summary().splitlines()

    def test_the_old_displaymode_payload_is_not_read(self) -> None:
        """The documented GET was absent on both units; it is no longer polled."""
        assert "/api/v1/device/screen/displaymode" not in MONITORING_ENDPOINTS.values()
        assert MONITORING_ENDPOINTS["display_state"] == DISPLAY_STATE
        snapshot = _snapshot(display_mode={"value": 2})
        assert snapshot.display_mode is None and snapshot.display == "unknown"

    def test_blackout_needs_no_qualifier(self) -> None:
        line = next(
            line for line in _snapshot(display_state=display_state(1)).summary().splitlines()
            if line.startswith("  display")
        )
        assert "blackout" in line and "REASONED" not in line

    def test_mixed_and_unreadable_canvases_are_listed(self) -> None:
        mixed = _snapshot(display_state=display_state(0, 2, canvases=(2048, 2049))).summary()
        assert "mixed (canvas 2048 normal, canvas 2049 freeze)" in mixed
        odd = _snapshot(display_state=display_state(9)).summary()
        assert "unknown (canvas 2048 unknown)" in odd


# --- polled end to end -------------------------------------------------------


class TestPolledDisplayState:
    def test_a_frozen_wall_polls_as_freeze(self, unit) -> None:
        unit.routes[DISPLAY_STATE] = display_state(2)
        host, port = unit.address
        with CoexMonitor(host, port, interval=0.0) as monitor:
            snapshot = monitor.poll()
        assert (snapshot.display_mode, snapshot.display) == (2, "freeze")
        assert "display_state" not in snapshot.errors
        assert ("GET", DISPLAY_STATE) in unit.requests

    def test_freeze_and_release_show_on_successive_polls(self, unit) -> None:
        """The attended test's sequence: 0, then 2 for the freeze, then 0 again."""
        host, port = unit.address
        seen = []
        with CoexMonitor(host, port, interval=0.0) as monitor:
            for mode in (0, 2, 2, 0):
                unit.routes[DISPLAY_STATE] = display_state(mode)
                seen.append(monitor.poll().display)
        assert seen == ["normal", "freeze", "freeze", "normal"]

    def test_display_state_is_polled_every_tick_not_cached(self, unit) -> None:
        host, port = unit.address
        with CoexMonitor(host, port, interval=0.0) as monitor:
            monitor.poll()
            unit.requests.clear()
            monitor.poll(include_slow=False)
        assert ("GET", DISPLAY_STATE) in unit.requests
        assert ("GET", HARDWARE) not in unit.requests  # identity is the slow tier

    def test_an_empty_200_is_unknown_not_normal(self, unit) -> None:
        """The MX30's answer for an absent path; nothing is recorded as failing."""
        unit.routes[DISPLAY_STATE] = EMPTY_200
        host, port = unit.address
        with CoexMonitor(host, port, interval=0.0) as monitor:
            snapshot = monitor.poll()
        assert snapshot.display_mode is None
        assert snapshot.display == "unknown"
        assert "display_state" not in snapshot.errors
        assert "  display     unknown" in snapshot.summary().splitlines()

    def test_a_404_is_unknown_and_recorded(self, unit) -> None:
        """The MX40 Pro's answer for an absent path (whether it serves this one is UNKNOWN)."""
        unit.routes[DISPLAY_STATE] = 404
        host, port = unit.address
        with CoexMonitor(host, port, interval=0.0) as monitor:
            snapshot = monitor.poll()
        assert snapshot.display_mode is None and snapshot.display == "unknown"
        assert "404" in snapshot.errors["display_state"]

    def test_polling_sends_nothing_but_gets(self, unit) -> None:
        host, port = unit.address
        with CoexMonitor(host, port, interval=0.0) as monitor:
            for _ in range(3):
                monitor.poll()
        assert unit.requests and {method for method, _path in unit.requests} == {"GET"}


class TestSurveyDisplay:
    def test_status_carries_the_mapping(self, unit) -> None:
        unit.routes[DISPLAY_STATE] = display_state(2)
        host, port = unit.address
        device = survey_device(host, http_port=port, control_port=closed_port())
        status = json.loads(json.dumps(Survey(devices=[device]).to_dict()))["devices"][0]["status"]
        assert status["display_mode"] == 2
        assert status["display"] == "freeze"
        assert status["display_canvases"] == [
            {"canvas_id": CANVAS, "display_mode": 2, "state": "freeze", "confidence": "OBSERVED"}
        ]
        assert "  display: freeze" in device.summary().splitlines()

    def test_an_unreadable_display_serialises_as_null_and_unknown(self, unit) -> None:
        """``null`` -- never 0 -- so a consumer cannot render it as live."""
        unit.routes[DISPLAY_STATE] = EMPTY_200
        host, port = unit.address
        device = survey_device(host, http_port=port, control_port=closed_port())
        text = json.dumps(device.to_dict())
        status = json.loads(text)["status"]
        assert status["display_mode"] is None and '"display_mode": null' in text
        assert status["display"] == "unknown"
        assert status["display_canvases"] == []
        assert "  display: unknown" in device.summary().splitlines()
