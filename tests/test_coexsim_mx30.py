"""The COEX simulator's MX30-like firmware profile.

Pins the shapes OBSERVED on one MX30 (hwVersion V1.5.1) on 2026-09-26, so a
consumer developed against the simulator meets the surface that unit presented
-- above all that an absent endpoint answers an empty HTTP 200 rather than a
404, which the read-only client turns into ``{}`` without a word. The read-only
pass sent GETs only; the two writes sent later that day (snmpstate and
hw/colorBeacon, with VMP closed) are pinned in ``TestWrites``. What a capture
of VMP opening the unit that evening added -- identity at ``/device/hw`` with
its ``randomPassword``, display state that shows a front-panel freeze, the
lock VMP takes, its systemtime body, and the unit's UDP announcement -- is
pinned from ``TestDeviceHw`` on, and the same unit with every output line
unplugged -- connected-cabinet counts at zero while monitor/info still reads
healthy -- in ``TestOutputsUnplugged``. Every value here is synthetic, and every
socket is on 127.0.0.1. The MX40 Pro default is asserted unchanged alongside:
one unit of each was read, and the simulator must not blur them.
"""

from __future__ import annotations

import http.client
import json
import re
import socket
import sys
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

import pytest

from novasun import coexsim
from novasun.coex import CoexClient, CoexError
from novasun.coexsim import (
    MX30_ABSENT_GETS,
    MX30_LIKE,
    MX40_ABSENT_GETS,
    MX40_LIKE,
    CoexState,
    SimulatedCoexController,
)
from novasun.monitor import (
    MONITORING_ENDPOINTS,
    CoexMonitor,
    ReadOnlyCoexClient,
    WriteAttempted,
    interpret_monitor_info,
)

CORS = {"vary": "Origin", "access-control-allow-origin": "*",
        "access-control-allow-credentials": "true"}


@contextmanager
def serving(state: CoexState | None = None):
    server = SimulatedCoexController("127.0.0.1", 0, state)
    server.serve_in_thread()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def raw_get(server, path: str) -> tuple[int, dict[str, str], bytes]:
    """Status, lower-cased headers and body -- what the wire carried."""
    host, port = server.address
    connection = http.client.HTTPConnection(host, port, timeout=2.0)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read()
    finally:
        connection.close()


def raw_put(server, path: str, body: object) -> tuple[int, dict[str, str], bytes]:
    """A PUT with a JSON body, returning what the wire carried."""
    host, port = server.address
    connection = http.client.HTTPConnection(host, port, timeout=2.0)
    try:
        connection.request("PUT", path, body=json.dumps(body).encode(),
                           headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read()
    finally:
        connection.close()


SNMPSTATE = "/api/v1/device/snmpstate"
BEACON = "/api/v1/device/hw/colorBeacon"
SUCCESS_EMPTY_DATA = {"code": 0, "data": "", "message": "Success"}


@pytest.fixture()
def mx30():
    with serving(CoexState(model="MX30")) as server:
        yield server


@pytest.fixture()
def client(mx30):
    host, port = mx30.address
    return CoexClient(host, port, timeout=2.0)


class TestProfileSelection:
    def test_the_model_name_selects_the_profile(self) -> None:
        assert CoexState().profile == MX40_LIKE
        assert CoexState(model="MX40 Pro").profile == MX40_LIKE
        assert CoexState(model="MX30").profile == MX30_LIKE
        assert CoexState(model=" mx30 ").mx30_like

    def test_absence_semantics_default_per_profile(self) -> None:
        mx30, mx40 = CoexState(model="MX30"), CoexState()
        assert mx30.absent_style == "empty-200" and mx40.absent_style == "404"
        assert mx30.missing_endpoints == set(MX30_ABSENT_GETS)
        assert mx40.missing_endpoints == set(MX40_ABSENT_GETS)
        # The two curl-confirmed absences are in the MX30 set; audio is not.
        assert {"/api/v1/device", "/api/v1/device/screen/displaymode"} <= mx30.missing_endpoints
        assert "/api/v1/device/audio" not in mx30.missing_endpoints
        # Both remain ordinary settings a test can change.
        assert CoexState(model="MX30", absent_style="404").absent_style == "404"
        assert CoexState(model="MX30", missing_endpoints=set()).missing_endpoints == set()

    def test_the_default_wall_is_the_one_observed(self) -> None:
        state = CoexState(model="MX30")
        assert len(state.cabinets) == 72
        assert Counter(c["port"] for c in state.cabinets) == {0: 24, 2: 24, 4: 24}
        assert len(state.inputs) == 6
        assert state.current_input == 512
        # monitor/info's name is a plain word with no model in it: nothing may
        # read a model out of it, and it must never be the unit's real word.
        assert re.fullmatch(r"[A-Za-z]+", state.custom_name)
        assert "mx30" not in state.custom_name.lower()


class TestAbsentEndpoints:
    def test_absent_documented_endpoints_answer_an_empty_200(self, mx30) -> None:
        for path in ("/api/v1/device", "/api/v1/device/screen/displaymode"):
            status, headers, body = raw_get(mx30, path)
            assert status == 200, path
            assert headers["content-length"] == "0" and body == b"", path
            assert "content-type" not in headers, path
            assert "x-request-id" in headers and "date" in headers, path
            assert {k: headers[k] for k in CORS} == CORS, path

    def test_unknown_paths_answer_the_same_empty_200(self, mx30) -> None:
        # Not a NotSupport envelope, not a 404: indistinguishable by status
        # from an endpoint that exists.
        for path in ("/api/v1/no-such-path", "/api/v2/nope", "/nope"):
            status, headers, body = raw_get(mx30, path)
            assert (status, headers["content-length"], body) == (200, "0", b""), path
            assert "content-type" not in headers, path

    def test_a_populated_endpoint_carries_the_envelope(self, mx30) -> None:
        status, headers, body = raw_get(mx30, "/api/v1/device/snmpstate")
        assert status == 200
        assert headers["content-type"] == "application/json"
        assert int(headers["content-length"]) == len(body) > 0
        assert json.loads(body) == {"code": 0, "data": {"state": False}, "message": "Success"}
        assert {k: headers[k] for k in CORS} == CORS

    def test_the_client_reads_an_empty_200_as_an_empty_dict(self, client) -> None:
        # The trap: no exception, no error code -- just {} where a payload
        # should be. A reader that takes "answered" as "exists" is misled.
        assert client.device_info() == {}
        assert client.request("GET", "/api/v1/device/screen/displaymode") == {}
        assert client.request("GET", "/api/v1/no-such-path") == {}

    def test_absent_style_is_a_setting_not_a_model_property(self) -> None:
        with serving(CoexState(model="MX30", absent_style="404")) as server:
            assert raw_get(server, "/api/v1/device")[0] == 404
        with serving(CoexState(absent_style="empty-200")) as server:
            status, headers, body = raw_get(server, "/api/v1/device")
            assert (status, headers["content-length"], body) == (200, "0", b"")

    def test_removing_an_endpoint_from_the_set_serves_nothing_new(self, mx30, client) -> None:
        # /api/v1/device is not implemented by this profile at all, so lifting
        # the marker still yields the empty 200: the simulator has no device
        # payload to invent for a unit that never sent one.
        mx30.state.missing_endpoints.discard("/api/v1/device")
        assert client.device_info() == {}


class TestShapes:
    def test_audio_is_present(self, client) -> None:
        assert client.request("GET", "/api/v1/device/audio") == {
            "enable": False, "source": 65535, "sourceName": ""}

    def test_monitor_info_identity_and_cabinets(self, client, mx30) -> None:
        info = client.monitoring()
        assert info["name"] == mx30.state.custom_name
        cabinets = info["cabinets"]
        assert len(cabinets) == 72
        for entry in cabinets:
            card = entry["rvCards"][0]
            assert len(entry["rvCards"]) == 1
            assert entry["cabinetID"] == entry["rvCardID"] == card["cabinetID"] == card["rvCardID"] != 0
            assert entry["canvasID"] == 2048
            assert "temperature" not in entry and "voltage" not in entry
            nested = entry["cabinet"]
            assert set(nested) == {"cabinetID", "humidity", "power", "smoke", "temperature", "voltage"}
            assert nested["cabinetID"] == 0 and nested["power"] is None
            assert nested["temperature"]["value"] == nested["humidity"]["value"] == nested["smoke"]["value"] == 0
            assert nested["voltage"] == card["voltage"]  # a live mirror, not a second reading
            assert set(card["phyTemperature"]) == {"phy1", "phy2"}
            assert card["signalInterruptCount"] == 0 and isinstance(card["signalInterruptCount"], int)
            assert card["runtime"] == 0 and card["totalRuntime"] == 0
            assert card["netPortIndex"] == entry["outPutID"] and card["cabinetIndex"] == entry["index"]
            assert [e["type"] for e in card["errorBit"]] == [0, 1]
            assert card["errorBit"][0]["value"] != 65535
        # One errorBit value per output port, not one per cabinet.
        per_port = {(e["outPutID"], e["rvCards"][0]["errorBit"][0]["value"]) for e in cabinets}
        assert len(per_port) == 3 and len({p for p, _v in per_port}) == 3
        assert {e["outPutID"] for e in cabinets} == {2048, 2050, 2052}

    def test_monitor_info_controller_side(self, client) -> None:
        info = client.monitoring()
        assert {"accessoryMonitorInfo", "imbLinkStatus", "inputFiberStatus"} <= set(info)
        assert info["accessoryMonitorInfo"] == {"multifunctionCardStatus": [], "transmitterStatus": []}
        assert info["imbLinkStatus"] == {"linkStatus": False, "status": 0}
        assert info["inputFiberStatus"] is None
        assert set(info["backupStatus"]) == {"errCode", "maxNormalValue", "minNormalValue", "status"}
        assert [(f["fanName"], f["fanType"]) for f in info["fanInfos"]] == [
            ("Chassis Fan 1", 1), ("FPGA Fan", 15), ("Chassis Fan 2", 2)]
        assert all(f["fanNameEn"] == f["fanName"] for f in info["fanInfos"])
        assert [p["controllerPortID"] for p in info["controllerPortMonitorInfos"]] == [0, 1]
        assert info["runtime"] % 60 == 0 and info["totalRuntime"] % 60 == 0

    def test_output_status_pattern(self, client) -> None:
        outputs = client.monitoring()["outputStatus"]
        assert len(outputs) == 33
        assert all(set(o) == {"linkStatus", "outputCardID", "outputID", "status", "type"} for o in outputs)
        assert Counter(o["type"] for o in outputs) == {0: 10, 5: 20, 1: 2, 3: 1}
        assert [o["outputID"] for o in outputs if o["type"] == 0] == list(range(2048, 2058))
        assert [o["outputID"] for o in outputs if o["type"] == 5] == list(range(2058, 2078))
        assert [o["outputID"] for o in outputs if o["type"] == 1] == [2078, 2079]
        assert [o for o in outputs if o["type"] == 3] == [
            {"linkStatus": False, "outputCardID": 0, "outputID": 0, "status": 0, "type": 3}]
        assert {o["outputID"] for o in outputs if o["linkStatus"]} == set(range(2048, 2053))

    def test_screen_source_status_and_runtimes(self, client) -> None:
        info = client.monitoring()
        sources = {s["portID"]: s for s in info["screenSourceStatus"]}
        inputs = {s["id"]: s for s in client.input_sources()}
        assert set(sources) == set(inputs) and len(sources) == 6
        for port_id, entry in sources.items():
            assert set(entry) == {"groupID", "inputCardID", "linkStatus", "portID", "status"}
            assert entry["groupID"] == inputs[port_id]["groupId"]
            assert entry["linkStatus"] is (inputs[port_id]["sourceStatus"] == 1)
        runtimes = info["rvCardsRuntime"]
        assert len(runtimes) == 72
        assert {r["cabinetID"] for r in runtimes} == {e["cabinetID"] for e in info["cabinets"]}
        assert len({r["runtime"] for r in runtimes}) == 1  # one static value on every card
        assert all(r["totalRuntime"] % 60 == 0 for r in runtimes)
        assert len({r["totalRuntime"] for r in runtimes}) == 72

    def test_screen_carries_the_wall_geometry(self, client, mx30) -> None:
        payload = client.screens()
        screen = payload["screens"][0]
        assert {"cryptoCabinetNum", "monitorSlotId"} <= set(screen)
        canvas = screen["canvases"][0]
        cabinets = canvas["cabinets"]
        assert len(cabinets) == 72
        assert all(set(c) == {"angle", "cabinetID", "connectID", "lockStatus", "outputID",
                              "pageID", "position", "size"} for c in cabinets)
        xs = sorted({c["position"]["x"] for c in cabinets})
        ys = sorted({c["position"]["y"] for c in cabinets})
        assert xs == [128 * i for i in range(12)] and ys == [128 * i for i in range(6)]
        assert len({(c["position"]["x"], c["position"]["y"]) for c in cabinets}) == 72
        extent = {"width": max(xs) + 128, "height": max(ys) + 128}
        modes = {m["workingMode"]: m for m in canvas["canvasInWorkingMode"]}
        assert canvas["size"] == canvas["rectSize"] == canvas["lastSize"] == extent
        assert modes[screen["workingMode"]]["size"] == extent
        assert modes[0]["size"] != extent  # size is per mode; extent = size only for the active one
        assert canvas["position"]["x"] < 0 and canvas["position"]["y"] < 0
        assert canvas["outputCardModeId"] == 5138 and canvas["outputCardId"] == 8
        # connectID is the chain position, and cabinetID joins /device/cabinet.
        by_id = {c["id"]: c for c in client.cabinets()}
        for c in cabinets:
            assert c["connectID"] == by_id[c["cabinetID"]]["index"]
            assert c["outputID"] == by_id[c["cabinetID"]]["outputID"]
        # Chain position 0 sits at the right-hand end of its port's lower row.
        first = [c for c in cabinets if c["outputID"] == 2048 and c["connectID"] == 0]
        assert [(c["position"]["x"], c["position"]["y"]) for c in first] == [(1408, 640)]
        assert [(p["pageID"], p["isShow"]) for p in screen["pageInfos"]] == [
            (i, i == 0) for i in range(8)]

    def test_layers_reference_inputs_by_group_id(self, client, mx30) -> None:
        screen = client.screens()["screens"][0]
        inputs = {s["id"]: s for s in client.input_sources()}
        group_ids = {s["groupId"] for s in inputs.values()}
        modes = {m["workingMode"]: m for m in screen["layersInWorkingMode"]}
        assert set(modes) == {0, 1} and screen["workingMode"] == 1
        for mode in modes.values():
            layer = mode["layers"][0]
            assert layer["source"] in group_ids and layer["source"] not in inputs
            source = next(s for s in inputs.values() if s["groupId"] == layer["source"])
            assert layer["sourceSize"] == source["actualResolution"]
            assert layer["position"] == screen["canvases"][0]["position"]  # one frame with the canvas
        live = inputs[mx30.state.current_input]
        assert modes[1]["layers"][0]["source"] == live["groupId"]
        assert modes[0]["layers"][0]["source"] == inputs[25856]["groupId"]
        port = screen["inputPort"]
        assert port["LogicId"] == live["id"] and port["GroupId"] == live["groupId"]
        assert port["ModelId"] == 5138
        assert port["FirmwareVersion"] == {"FileNum": "", "VersionName": "", "VersionNumber": "",
                                           "VersionRemark": ""}
        assert port["InputSrcInfo"]["InputID"] == live["id"]
        assert port["InputSrcInfo"]["SourceFieldRate"] == live["actualRefreshRate"] * 100
        assert screen["masterFrameRate"] == live["actualRefreshRate"]

    def test_input_sources(self, client) -> None:
        sources = client.input_sources()
        assert [(s["id"], s["type"], s["groupId"], s["cardId"]) for s in sources] == [
            (3, 7, 57, 0), (4, 7, 58, 0), (256, 4, 32, 0), (768, 2, 18, 0),
            (512, 3, 25, 0), (25856, 224, 224, 101)]
        assert all(s["groupId"] != s["id"] for s in sources if s["type"] != 224)
        internal = sources[-1]
        assert internal["name"] == "internal-source" and internal["sourceStatus"] == 1
        assert [s["id"] for s in sources if s["sourceStatus"] == 1] == [512, 25856]
        for s in sources:
            assert {"groupId", "defaultEDID", "hdrList", "metaData", "fiberPortLinkStatus",
                    "monitorSlotId"} <= set(s)
            edid = s["defaultEDID"]
            if s["sourceStatus"] == 0:  # no signal: echoes the EDID default exactly
                assert s["actualResolution"] == edid["resolution"]
                assert s["actualRefreshRate"] == edid["refreshRate"]
            else:
                assert (s["actualResolution"], s["actualRefreshRate"]) != (
                    edid["resolution"], edid["refreshRate"])
        assert {s["id"] for s in sources if s["hdrList"] is not None} == {512, 768}

    def test_cabinet_count_and_device_input(self, client, mx30) -> None:
        count = client.request("GET", "/api/v1/screen/cabinet/count")
        assert count == {"list": [{"CabinetCount": 72, "CabinetCountInBlackList": 0,
                                   "ScreenID": mx30.state.screens[0]["screenID"]}]}
        config = client.request("GET", "/api/v1/device/input")
        assert set(config) == {"inputPortConfig", "testPattern"}
        ports = config["inputPortConfig"]
        assert {p["logicId"] for p in ports} == {s["id"] for s in mx30.state.inputs}
        assert all(p["modelId"] == 5138 and 7 <= len(p["hardwareID"]) <= 8 for p in ports)
        assert set(config["testPattern"]) == {"mode", "parameters", "txColorSpaceType", "txHDRType"}
        assert {"edidInfo", "hdrParameter", "sdpSourceInfo", "videoStreamConfig"} <= set(ports[0])

    def test_device_cabinet_entries(self, client) -> None:
        cabinets = client.cabinets()
        assert len(cabinets) == 72
        expected = {
            "angle", "brightness", "bunchesIndex", "cabType", "cabinetFileParam", "canvasID",
            "clientOrderNo", "colorTemperature", "customGamma", "familyName", "gain", "gamma",
            "id", "index", "indicatorLightState", "manufacture", "moduleCount", "moduleSize",
            "ncpFileName", "ncpVersion", "outputCardID", "outputID", "outputIndex",
            "pointSpacing", "power", "resolution", "rvCardInfo", "rvCardName", "shortName",
            "size", "supportType", "voltage", "vsFreMax", "weight",
        }
        assert len(expected) == 34
        for c in cabinets:
            assert set(c) == expected
            assert c["size"] == {"width": 0, "height": 0} and c["power"] == 0
            assert c["outputIndex"] == c["outputID"] - 2048
            assert 0 <= c["index"] < 24
            assert set(c["rvCardInfo"]) == {
                "chipEffectFlag", "decodeIc", "driverChip", "firmware", "firmwareRemark",
                "grayScale", "maxGamma", "mcuFirmWare", "mcuFirmWareRemark",
                "moduleResolution", "refreshRate", "scanNumber"}
            assert c["cabinetFileParam"]["status"] == "unknown"
        assert len({(c["outputID"], c["index"]) for c in cabinets}) == 72
        assert len({c["id"] for c in cabinets}) == 72

    def test_the_two_voltage_paths_move_together(self, client, mx30) -> None:
        target = mx30.state.cabinets[5]
        target["voltage"] = 3.9
        entry = next(e for e in client.monitoring()["cabinets"] if e["cabinetID"] == target["id"])
        assert entry["rvCards"][0]["voltage"]["value"] == 3.9
        assert entry["cabinet"]["voltage"]["value"] == 3.9


class TestReadOnlyMonitor:
    def test_polls_without_error_and_sees_the_wall(self, mx30) -> None:
        host, port = mx30.address
        with CoexMonitor(host, port, interval=0.0) as monitor:
            snapshot = monitor.poll()
        # /api/v1/device is an empty 200, so nothing is *recorded* as failing:
        # that silence is the observed behaviour, not a simulator gap.
        assert snapshot.errors == {}
        assert snapshot.raw["device"] == {}
        # display/state reads a live wall (TestDisplayState covers a freeze).
        assert snapshot.display_mode == 0
        assert len(snapshot.cabinets) == 72 and snapshot.healthy
        assert "72/72 online" in snapshot.summary()
        assert snapshot.hottest is not None and snapshot.hottest.temperature == 46
        assert snapshot.signal_present == ["HDMI2.0 1", "internal-source"]
        assert snapshot.device_name == mx30.state.custom_name
        # monitor/info's name is a label with no model in it (OBSERVED); the
        # model comes from /device/hw's name, never from the label.
        assert snapshot.model == "MX30" != mx30.state.custom_name
        assert all(method == "GET" for method, _path, _body in mx30.state.requests)

    def test_interpret_monitor_info_reads_the_shape(self, client) -> None:
        status = interpret_monitor_info(client.monitoring())
        assert status["cabinets_listed"] == 72 and "cabinets_online" not in status
        assert status["temperature_c"] == 46
        assert status["main_board_temperature_c"] == 32
        assert status["main_board_voltage_v"] == 11.56
        assert status["links_listed_ok"] == 72

    def test_an_offline_cabinet_is_absent_from_monitoring(self, mx30) -> None:
        mx30.state.cabinets[7]["online"] = False
        host, port = mx30.address
        with CoexMonitor(host, port, interval=0.0) as monitor:
            snapshot = monitor.poll()
        assert not snapshot.healthy
        assert [c.identifier for c in snapshot.offline_cabinets] == [mx30.state.cabinets[7]["id"]]
        assert "71/72 online" in snapshot.summary()


class TestWrites:
    """The two writes the MX30 was sent on 2026-09-26, as it answered them."""

    def test_set_snmp_flips_the_state_and_the_get_reads_it_back(self, client, mx30) -> None:
        assert client.snmp_state() == {"state": False}  # off, as the unit was
        client.set_snmp(True)
        assert mx30.state.snmp_enabled is True
        assert client.snmp_state() == {"state": True}
        client.set_snmp(False)
        assert client.snmp_state() == {"state": False}
        client.set_snmp(True)
        client.set_snmp(True)  # idempotent
        assert client.snmp_state() == {"state": True}

    def test_set_snmp_sends_the_state_key(self, client, mx30) -> None:
        client.set_snmp(True)
        client.set_snmp(False)
        puts = [(path, body) for method, path, body in mx30.state.requests if method == "PUT"]
        assert puts == [(SNMPSTATE, {"state": True}), (SNMPSTATE, {"state": False})]

    def test_the_old_value_body_answers_success_and_changes_nothing(self, client, mx30) -> None:
        # The W1 trap: no exception, a Success envelope, and no change. Only
        # a read-back shows it.
        assert client.request("PUT", SNMPSTATE, {"value": True}) == ""
        assert client.snmp_state() == {"state": False}
        client.set_snmp(True)
        assert client.request("PUT", SNMPSTATE, {"value": False}) == ""
        assert client.snmp_state() == {"state": True}

    @pytest.mark.parametrize("body", [{}, {"value": True}, {"state": 1}, {"state": "true"},
                                      {"enable": True}, [True], None])
    def test_any_body_without_a_boolean_state_is_ignored(self, mx30, body) -> None:
        status, headers, raw = raw_put(mx30, SNMPSTATE, body)
        assert status == 200 and headers["content-type"] == "application/json"
        assert json.loads(raw) == SUCCESS_EMPTY_DATA
        assert mx30.state.snmp_enabled is False

    def test_the_put_reply_is_the_full_success_envelope(self, mx30) -> None:
        status, headers, raw = raw_put(mx30, SNMPSTATE, {"state": True})
        assert status == 200 and headers["content-type"] == "application/json"
        assert int(headers["content-length"]) == len(raw)
        assert json.loads(raw) == SUCCESS_EMPTY_DATA  # data is "", not null
        assert {k: headers[k] for k in CORS} == CORS
        assert mx30.state.snmp_enabled is True

    def test_identify_controller_gets_the_empty_200(self, client, mx30) -> None:
        for value in (True, False):
            status, headers, raw = raw_put(mx30, BEACON, {"value": value})
            assert (status, headers["content-length"], raw) == (200, "0", b"")
            assert "content-type" not in headers
            assert {k: headers[k] for k in CORS} == CORS
        # Silent through the client: request() returns {} and the method None.
        assert client.identify_controller(True) is None
        assert client.request("PUT", BEACON, {"value": False}) == {}
        # Nothing is modelled as changing: watched on the unit, no body lit anything.
        assert client.snmp_state() == {"state": False}
        assert [p for m, p, _b in mx30.state.requests if m == "PUT"] == [BEACON] * 4

    def test_an_unknown_put_path_keeps_not_support(self, client) -> None:
        # A PUT to a made-up path was never tried on the MX30: the simulator
        # keeps its NotSupport convention there, so colorBeacon's empty 200 is
        # not evidence that the endpoint exists.
        with pytest.raises(CoexError) as error:
            client.request("PUT", "/api/v1/device/hw/no-such-put", {"value": True})
        assert error.value.code == 6

    def test_the_read_only_client_still_reaches_neither(self, mx30) -> None:
        host, port = mx30.address
        reader = ReadOnlyCoexClient(host, port, timeout=2.0)
        for call in (lambda: reader.set_snmp(True), lambda: reader.identify_controller(True)):
            with pytest.raises(WriteAttempted):
                call()
        assert reader.snmp_state() == {"state": False}
        assert all(method == "GET" for method, _path, _body in mx30.state.requests)


# --- What VMP read and wrote when it opened (OBSERVED 2026-09-26) -----------

HW = "/api/v1/device/hw"
DISPLAY_STATE = "/api/v1/screen/output/display/state"
LOCK = "/api/v1/device/hw/lock"
SYSTEMTIME = "/api/v1/device/hw/systemtime"

#: /device/hw's 44 data keys, in the order the MX30 sent them (OBSERVED).
HW_KEYS = [
    "name", "customName", "modelID", "sn", "thirdPartySn", "thirdPartySerial", "mac", "type",
    "netPortBandWidth", "hwVersion", "swVersion", "mcuVersion", "fpgaVersion",
    "mcuVersionRemark", "fpgaVersionRemark", "softVersion", "configVersion", "ip",
    "WirelessIpAddress", "mode", "companyName", "capability", "deviceWorkMode", "IpNetmask",
    "IpGateway", "ethMode", "hostName", "Dns", "dhcp", "configIP", "Series", "uptime",
    "memorySize", "memoryUsed", "memoryFree", "subBoardInfo", "customIp", "deviceUUID",
    "groupName", "isAllowSingleDev", "supportInputSubCardNum", "supportOutputSubCardNum",
    "encipher", "randomPassword",
]

#: display/state on a live wall, byte for byte as the MX30 sent it (OBSERVED, 140 B).
DISPLAY_STATE_LIVE = (
    b'{"code":0,"data":{"mappingState":[{"canvasID":2048,"enable":false}],'
    b'"displayState":[{"canvasID":2048,"displayMode":0}]},"message":"Success"}'
)
#: hw/lock before VMP took it (OBSERVED, 58 B), and the reply to both of VMP's
#: PUTs modelled here, systemtime and hw/lock (OBSERVED, 42 B).
LOCK_FREE = b'{"code":0,"data":{"locked":0,"ip":""},"message":"Success"}'
SUCCESS_NULL = b'{"code":0,"data":null,"message":"Success"}'
#: A synthetic app id in the place of the ``LCTPro<id>`` VMP sent.
APP_ID = "LCTProSIM"
#: The systemtime body VMP sent, with its shape and synthetic values (the
#: real zone and time are show data).
SYSTEMTIME_BODY = {"clientTimezone": "Etc/UTC", "second": 0, "minute": 0, "hour": 12,
                   "isUTC": True, "day": 1, "month": 1, "year": 2000}
#: The announcement at the default API port with the simulator's MAC: the
#: unit's 96-byte layout exactly (OBSERVED), synthetic MAC.
ANNOUNCEMENT = (b'{"data":[{"apiPort":"8001","mac":"00:00:5e:00:53:30",'
                b'"authType":0,"workMode":0,"https":"9001"}]}')


def display_modes(payload: dict) -> dict[int, int]:
    """display/state's modes by canvas."""
    return {entry["canvasID"]: entry["displayMode"] for entry in payload["displayState"]}


def hw_data(server) -> dict:
    return json.loads(raw_get(server, HW)[2])["data"]


class TestDeviceHw:
    def test_identity_is_readable_over_http(self, mx30, client) -> None:
        status, headers, body = raw_get(mx30, HW)
        assert status == 200 and headers["content-type"] == "application/json"
        assert {k: headers[k] for k in CORS} == CORS
        envelope = json.loads(body)
        assert (envelope["code"], envelope["message"]) == (0, "Success")
        hw = envelope["data"]
        assert hw["name"] == "MX30"
        assert hw["modelID"] == coexsim.MX30_LIKE_MODEL_ID == 5138
        assert hw["hwVersion"] == "V1.5.1" and hw["type"] == "G3.5"
        assert (hw["swVersion"], hw["mcuVersion"], hw["fpgaVersion"], hw["configVersion"]) == (
            "1.0.0", "V1.0.0", "V1.0.0.S1.T1.V9", "V1.4.0.1")
        assert hw["softVersion"]["Version"] == ""
        assert hw["mode"] == 3 and hw["deviceWorkMode"] == 0
        assert hw["encipher"]["authState"] == 0
        assert hw["thirdPartySn"] == hw["thirdPartySerial"] == ""
        # The model is ``name``; the operator's label is ``customName`` -- the
        # same label monitor/info carries, and never a model.
        assert hw["customName"] == mx30.state.custom_name == client.monitoring()["name"]
        assert hw["customName"] != hw["name"]

    def test_capabilities_as_observed(self, mx30) -> None:
        capability = hw_data(mx30)["capability"]
        assert capability["capabilityVersion"] == "V4.1.0"
        for flag in ("snmp", "artNet", "NTP", "inputImageEcho", "outputImageEcho",
                     "allowChangeWorkMode"):
            assert capability[flag] is True, flag
        assert len(capability["hwMonitor"]) == 7
        assert set(capability["hwMonitor"].values()) == {False}

    def test_the_skeleton_is_the_one_observed(self, mx30) -> None:
        hw = hw_data(mx30)
        assert list(hw) == HW_KEYS
        capability = hw["capability"]
        assert len(capability) == 161
        lengths = {key: len(capability[key]) for key in (
            "threeDFrameList", "outputBitDepth", "internalBitDepths", "colorSpaceType",
            "colorGamutType", "artNetMaxStartAddressList", "frameRateTable")}
        assert lengths == {"threeDFrameList": 0, "outputBitDepth": 3, "internalBitDepths": 2,
                           "colorSpaceType": 4, "colorGamutType": 4,
                           "artNetMaxStartAddressList": 4, "frameRateTable": 19}
        assert len(capability["supportSizeList"]["mode"]) == len(capability["layout"]["mode"]) == 2
        assert set(hw["subBoardInfo"]) == {"inputSn", "sasaSn", "sasbSn", "qsfpSn"}
        assert all(set(board) == {"type", "sn", "modelId"} for board in hw["subBoardInfo"].values())
        assert set(hw["softVersion"]) == {"Package", "Version", "Architecture", "Maintainer",
                                          "Description"}
        assert set(hw["encipher"]) == {"vendorID", "authState", "authStartTime", "authEndTime",
                                       "isOverRange"}
        assert hw["Dns"] is None and isinstance(hw["dhcp"], bool)
        for key in ("modelID", "uptime", "memorySize", "memoryUsed", "memoryFree", "Series"):
            assert type(hw[key]) is int, key

    def test_identifiers_are_synthetic(self, mx30) -> None:
        hw = hw_data(mx30)
        assert hw["sn"] == coexsim.MX30_LIKE_SERIAL and len(hw["sn"]) == 20
        assert hw["sn"].startswith("SIMULATED")
        # RFC 7042 documentation range, lower-case and colon-separated as sent.
        assert re.fullmatch(r"00:00:5e:00:53:[0-9a-f]{2}", hw["mac"])
        assert hw["mac"] == mx30.state.mac
        assert re.fullmatch(r"\{0{8}-0{4}-0{4}-0{4}-0{9}[0-9a-f]{3}\}", hw["deviceUUID"])
        assert hw["ip"].startswith("192.0.2.") and hw["IpGateway"].startswith("192.0.2.")

    def test_random_password_is_served_to_a_bare_get_and_is_fake(self, mx30) -> None:
        # The hazard, reproduced: the unit served it to a GET carrying no
        # Application-Id and no credential (OBSERVED). raw_get sends neither.
        # The value is the obvious fake, so a consumer's test can prove it
        # drops the field; the served password is never a real one.
        hw = hw_data(mx30)
        assert hw["randomPassword"] == coexsim.MX30_LIKE_FAKE_RANDOM_PASSWORD == "00000000"

    def test_the_client_drops_random_password(self, mx30, client) -> None:
        assert "randomPassword" in hw_data(mx30)
        hw = client.request("GET", HW)
        assert hw["name"] == "MX30" and "randomPassword" not in hw
        host, port = mx30.address
        assert "randomPassword" not in ReadOnlyCoexClient(host, port, timeout=2.0).request("GET", HW)

    def test_state_overrides_are_served(self) -> None:
        state = CoexState(model="MX30", serial="SIMULATED-MX30-00002", firmware="V9.9.9",
                          mac="00:00:5e:00:53:31")
        with serving(state) as server:
            hw = hw_data(server)
        assert (hw["sn"], hw["hwVersion"], hw["mac"]) == (
            "SIMULATED-MX30-00002", "V9.9.9", "00:00:5e:00:53:31")


class TestDisplayState:
    def test_a_live_wall_reads_the_observed_bytes(self, mx30) -> None:
        status, headers, body = raw_get(mx30, DISPLAY_STATE)
        assert status == 200 and headers["content-type"] == "application/json"
        assert body == DISPLAY_STATE_LIVE and len(body) == 140

    @pytest.mark.parametrize("mode", [0, 2, 1])  # 0 and 2 OBSERVED, 1 REASONED
    def test_the_mode_tracks_the_simulated_display(self, client, mx30, mode) -> None:
        mx30.state.display_mode = mode
        payload = client.request("GET", DISPLAY_STATE)
        assert display_modes(payload) == {coexsim.MX30_LIKE_CANVAS_ID: mode}
        assert payload["mappingState"] == [{"canvasID": 2048, "enable": False}]

    def test_it_is_keyed_by_the_wall_s_canvas(self, client) -> None:
        canvases = {c["canvasID"] for s in client.screens()["screens"] for c in s["canvases"]}
        assert set(display_modes(client.request("GET", DISPLAY_STATE))) == canvases == {2048}

    def test_the_documented_displaymode_get_stays_absent_through_a_freeze(self, mx30) -> None:
        # The trap the first attended sweep fell into: it polled this path, got
        # an empty 200 throughout, and concluded that a freeze was invisible.
        mx30.state.display_mode = 2
        status, headers, body = raw_get(mx30, "/api/v1/device/screen/displaymode")
        assert (status, headers["content-length"], body) == (200, "0", b"")
        assert display_modes(json.loads(raw_get(mx30, DISPLAY_STATE)[2])["data"]) == {2048: 2}

    def test_the_read_only_client_sees_a_front_panel_freeze_and_release(self, mx30) -> None:
        host, port = mx30.address
        reader = ReadOnlyCoexClient(host, port, timeout=2.0)
        seen = [display_modes(reader.request("GET", DISPLAY_STATE))[2048]]
        mx30.state.display_mode = 2  # the operator freezes from the front panel
        seen.append(display_modes(reader.request("GET", DISPLAY_STATE))[2048])
        mx30.state.display_mode = 0  # and releases it
        seen.append(display_modes(reader.request("GET", DISPLAY_STATE))[2048])
        assert seen == [0, 2, 0]
        assert all(method == "GET" for method, _path, _body in mx30.state.requests)

    def test_the_monitor_sees_a_simulated_freeze(self, mx30) -> None:
        name = next(n for n, path in MONITORING_ENDPOINTS.items() if path == DISPLAY_STATE)
        host, port = mx30.address
        with CoexMonitor(host, port, interval=0.0) as monitor:
            live = monitor.poll()
            mx30.state.display_mode = 2
            frozen = monitor.poll()
            mx30.state.display_mode = 0
            released = monitor.poll()
        assert [s.display_mode for s in (live, frozen, released)] == [0, 2, 0]
        assert display_modes(frozen.raw[name]) == {2048: 2}
        assert "freeze" in frozen.summary() and "freeze" not in live.summary()
        assert all(not s.errors for s in (live, frozen, released))
        assert all(method == "GET" for method, _path, _body in mx30.state.requests)

    def test_a_withheld_display_state_is_unknown_to_the_monitor_never_normal(self, mx30) -> None:
        mx30.state.missing_endpoints.add(DISPLAY_STATE)  # the empty 200, as for any absent path
        host, port = mx30.address
        with CoexMonitor(host, port, interval=0.0) as monitor:
            snapshot = monitor.poll()
        assert snapshot.display_mode is None


class TestLock:
    def test_unlocked_reads_the_observed_bytes(self, mx30) -> None:
        status, headers, body = raw_get(mx30, LOCK)
        assert (status, body) == (200, LOCK_FREE) and len(body) == 58
        assert headers["content-type"] == "application/json"

    def test_a_put_naming_appids_takes_it_for_the_caller(self, mx30, client) -> None:
        status, headers, body = raw_put(mx30, LOCK, {"appids": [APP_ID]})
        assert (status, body) == (200, SUCCESS_NULL) and len(body) == 42
        assert headers["content-type"] == "application/json"
        assert {k: headers[k] for k in CORS} == CORS
        # REASONED from the deviceLockChange push: the GET then names the caller.
        assert client.request("GET", LOCK) == {"locked": 1, "ip": "127.0.0.1"}
        assert mx30.state.lock_ip == "127.0.0.1" and mx30.state.lock_appids == [APP_ID]

    def test_it_outlives_the_connection_that_took_it(self, mx30, client) -> None:
        raw_put(mx30, LOCK, {"appids": [APP_ID]})  # that connection is closed on return
        for _ in range(3):
            assert client.request("GET", LOCK)["locked"] == 1
        # No HTTP unlock was observed; a test models VMP quitting by clearing it.
        mx30.state.lock_ip = None
        assert raw_get(mx30, LOCK)[2] == LOCK_FREE

    @pytest.mark.parametrize("body", [{}, {"appids": []}, {"appids": APP_ID}, {"appids": [1]},
                                      {"value": True}, [APP_ID], None])
    def test_other_bodies_answer_success_and_take_nothing(self, mx30, body) -> None:
        status, _headers, raw = raw_put(mx30, LOCK, body)
        assert (status, raw) == (200, SUCCESS_NULL)
        assert raw_get(mx30, LOCK)[2] == LOCK_FREE

    def test_a_front_panel_freeze_goes_through_while_it_is_held(self, mx30, client) -> None:
        # OBSERVED: the front-panel freeze and release happened with locked:1 in force.
        raw_put(mx30, LOCK, {"appids": [APP_ID]})
        mx30.state.display_mode = 2
        assert display_modes(client.request("GET", DISPLAY_STATE)) == {2048: 2}
        assert client.request("GET", LOCK) == {"locked": 1, "ip": "127.0.0.1"}

    def test_the_read_only_client_can_read_it_and_cannot_take_it(self, mx30) -> None:
        host, port = mx30.address
        reader = ReadOnlyCoexClient(host, port, timeout=2.0)
        with pytest.raises(WriteAttempted):
            reader.request("PUT", LOCK, {"appids": [APP_ID]})
        assert reader.request("GET", LOCK) == {"locked": 0, "ip": ""}
        assert mx30.state.lock_ip is None
        assert all(method == "GET" for method, _path, _body in mx30.state.requests)


class TestSystemTime:
    def test_the_observed_body_is_accepted_and_recorded(self, mx30) -> None:
        assert list(SYSTEMTIME_BODY) == list(coexsim.SYSTEMTIME_KEYS)
        status, headers, raw = raw_put(mx30, SYSTEMTIME, SYSTEMTIME_BODY)
        assert (status, raw) == (200, SUCCESS_NULL)
        assert headers["content-type"] == "application/json"
        assert mx30.state.system_time == SYSTEMTIME_BODY

    @pytest.mark.parametrize("body", [{"value": "2000-01-01T12:00:00+00:00"}, {},
                                      {**SYSTEMTIME_BODY, "extra": 1}, None])
    def test_any_other_body_answers_success_and_is_not_recorded(self, mx30, body) -> None:
        # The snmpstate trap again, REASONED here: Success, and nothing taken.
        status, _headers, raw = raw_put(mx30, SYSTEMTIME, body)
        assert (status, raw) == (200, SUCCESS_NULL)
        assert mx30.state.system_time is None

    def test_the_read_only_client_cannot_set_it(self, mx30) -> None:
        host, port = mx30.address
        reader = ReadOnlyCoexClient(host, port, timeout=2.0)
        with pytest.raises(WriteAttempted):
            reader.request("PUT", SYSTEMTIME, SYSTEMTIME_BODY)
        assert mx30.state.system_time is None and mx30.state.requests == []


def udp_receiver() -> socket.socket:
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    receiver.settimeout(2.0)
    return receiver


def drain(receiver: socket.socket) -> None:
    receiver.setblocking(False)
    try:
        while True:
            receiver.recv(2048)
    except BlockingIOError:
        pass
    finally:
        receiver.setblocking(True)


class TestAnnouncement:
    def test_the_payload_has_the_observed_layout(self) -> None:
        payload = coexsim.announcement_payload(CoexState(model="MX30"))
        assert payload == ANNOUNCEMENT and len(payload) == 96
        # The byte offsets the unit's datagrams had (inclusive ranges in the record).
        assert payload[10:19] == b'"apiPort"' and payload[20:26] == b'"8001"'
        assert payload[27:32] == b'"mac"' and payload[33:52] == b'"00:00:5e:00:53:30"'
        assert payload[53:63] == b'"authType"' and payload[64:65] == b"0"
        assert payload[66:76] == b'"workMode"' and payload[77:78] == b"0"
        assert payload[79:86] == b'"https"' and payload[87:93] == b'"9001"'
        assert payload[93:] == b"}]}"
        (entry,) = json.loads(payload)["data"]
        assert type(entry["apiPort"]) is str and type(entry["https"]) is str
        assert type(entry["authType"]) is int and type(entry["workMode"]) is int
        # No model, name, serial, version or address: only the MAC and two ports.
        assert set(entry) == {"apiPort", "mac", "authType", "workMode", "https"}

    def test_it_carries_the_mac_device_hw_serves_and_the_simulator_s_port(self, mx30) -> None:
        (entry,) = json.loads(coexsim.announcement_payload(mx30.state, mx30.address[1]))["data"]
        assert entry["mac"] == hw_data(mx30)["mac"]
        assert entry["apiPort"] == str(mx30.address[1])

    def test_the_observed_ports_and_cadence_are_the_defaults(self) -> None:
        assert coexsim.MX30_ANNOUNCE_PORTS == (54622, 54623, 54624, 54700)
        assert coexsim.MX30_ANNOUNCE_INTERVAL == 3.0

    def test_it_is_off_by_default(self, mx30) -> None:
        assert not mx30.announcing

    def test_it_sends_to_every_configured_port_until_stopped(self, mx30) -> None:
        receivers = [udp_receiver(), udp_receiver()]
        try:
            ports = tuple(r.getsockname()[1] for r in receivers)
            mx30.start_announcing("127.0.0.1", ports=ports, interval=0.05)
            assert mx30.announcing
            with pytest.raises(RuntimeError):
                mx30.start_announcing("127.0.0.1", ports=ports)
            expected = coexsim.announcement_payload(mx30.state, mx30.address[1])
            for receiver in receivers:
                for _ in range(2):  # at least two bursts
                    data, (source, _port) = receiver.recvfrom(2048)
                    assert data == expected and source == "127.0.0.1"
            mx30.stop_announcing()
            assert not mx30.announcing
            for receiver in receivers:
                drain(receiver)
                receiver.settimeout(0.3)
                with pytest.raises(TimeoutError):
                    receiver.recv(2048)
        finally:
            mx30.stop_announcing()
            for receiver in receivers:
                receiver.close()

    def test_closing_the_server_stops_it(self) -> None:
        receiver = udp_receiver()
        try:
            with serving(CoexState(model="MX30")) as server:
                server.start_announcing("127.0.0.1", ports=(receiver.getsockname()[1],),
                                        interval=0.05)
                receiver.recv(2048)
            assert not server.announcing
        finally:
            receiver.close()


CABINET_COUNT = "/api/v1/screen/cabinet/count"
DEVICE_CABINET = "/api/v1/device/cabinet"
MONITOR_INFO = "/api/v1/device/monitor/info"


class TestOutputsUnplugged:
    """Every output data line pulled, the unit powered (OBSERVED, attended, 2026-09-26)."""

    def test_connected_by_default_and_set_by_a_method(self) -> None:
        state = CoexState(model="MX30")
        assert state.outputs_unplugged is False
        state.unplug_outputs()
        assert state.outputs_unplugged is True
        assert CoexState(model="MX30", outputs_unplugged=True).outputs_unplugged

    def test_the_mx40_default_refuses_it(self) -> None:
        # Whether an MX40 Pro does any of this is UNKNOWN: never watched with a line out.
        with pytest.raises(ValueError, match="UNKNOWN"):
            CoexState(outputs_unplugged=True)
        with pytest.raises(ValueError, match="UNKNOWN"):
            CoexState().unplug_outputs()

    def test_the_connected_cabinet_counts_go_to_zero(self, client, mx30) -> None:
        assert len(client.request("GET", DEVICE_CABINET)) == 72
        mx30.state.unplug_outputs()
        # /device/cabinet holds the cabinets connected now; cabinet/count counts them.
        assert client.request("GET", DEVICE_CABINET) == []
        assert client.request("GET", CABINET_COUNT) == {"list": [{
            "CabinetCount": 0, "CabinetCountInBlackList": 0,
            "ScreenID": mx30.state.screens[0]["screenID"]}]}
        # Still an enveloped Success answer, not an absence: the wall is gone, the endpoint is not.
        status, headers, body = raw_get(mx30, DEVICE_CABINET)
        assert status == 200 and headers["content-type"] == "application/json"
        assert json.loads(body) == {"code": 0, "data": [], "message": "Success"}

    def test_monitor_info_is_the_false_all_clear(self, client, mx30) -> None:
        before = client.monitoring()
        mx30.state.unplug_outputs()
        after = client.monitoring()
        # Nothing but outputStatus and rvCardsRuntime moves (OBSERVED) ...
        assert set(after) == set(before)
        assert {k for k in before if before[k] != after[k]} == {"outputStatus", "rvCardsRuntime"}
        # ... so every cabinet and card is still there, every link up, every
        # reading as last read: a healthy-looking wall with nothing connected.
        assert after["cabinets"] == before["cabinets"] and len(after["cabinets"]) == 72
        cards = [card for entry in after["cabinets"] for card in entry["rvCards"]]
        assert len(cards) == 72
        assert all(card["nextCabinetLinkStatus"]["linkStatus"] is True for card in cards)
        assert all(card["temperature"]["value"] > 0 for card in cards)
        assert after["rvCardsRuntime"] == [] and len(before["rvCardsRuntime"]) == 72

    def test_every_output_link_drops_and_the_dropped_read_status_2(self, client, mx30) -> None:
        before = {o["outputID"]: o for o in client.monitoring()["outputStatus"]}
        dropped = {i for i, o in before.items() if o["linkStatus"]}
        assert dropped == set(range(2048, 2053))
        mx30.state.unplug_outputs()
        after = {o["outputID"]: o for o in client.monitoring()["outputStatus"]}
        assert set(after) == set(before) and len(after) == 33
        assert not any(o["linkStatus"] for o in after.values())
        assert all(after[i]["status"] == 2 for i in dropped)
        # The rest are as they were: whether their status moved was not recorded.
        assert all(after[i] == before[i] for i in set(before) - dropped)

    def test_display_state_screen_and_announcement_carry_on(self, client, mx30) -> None:
        screen = client.screens()
        state = client.request("GET", DISPLAY_STATE)
        announcement = coexsim.announcement_payload(mx30.state)
        mx30.state.unplug_outputs()
        # display/state read 0 throughout the unplugging (OBSERVED): it does not show it.
        assert client.request("GET", DISPLAY_STATE) == state
        assert display_modes(state) == {2048: 0}
        # /api/v1/screen was not re-read unplugged (UNKNOWN): served unchanged, not modelled.
        assert client.screens() == screen
        # The unit went on announcing every 3 s (OBSERVED); the payload says nothing of the wall.
        assert coexsim.announcement_payload(mx30.state) == announcement

    def test_the_readings_monitor_info_serves_are_frozen_by_the_caller(self, client, mx30) -> None:
        # The simulator serves state.cabinets as they stand, so a test that
        # moves a reading after unplugging is modelling something no card could
        # report. The documented way is to set readings first.
        mx30.state.cabinets[0]["temperature"] = 55
        mx30.state.unplug_outputs()
        entry = next(e for e in client.monitoring()["cabinets"]
                     if e["cabinetID"] == mx30.state.cabinets[0]["id"])
        assert entry["rvCards"][0]["temperature"]["value"] == 55

    def test_the_read_only_client_can_see_it_with_gets_alone(self, mx30) -> None:
        mx30.state.unplug_outputs()
        host, port = mx30.address
        reader = ReadOnlyCoexClient(host, port, timeout=2.0)
        count = reader.request("GET", CABINET_COUNT)["list"][0]["CabinetCount"]
        entries = reader.request("GET", DEVICE_CABINET)
        linked = [o for o in reader.request("GET", MONITOR_INFO)["outputStatus"] if o["linkStatus"]]
        listed = len(reader.request("GET", MONITOR_INFO)["cabinets"])
        assert (count, len(entries), linked, listed) == (0, 0, [], 72)
        assert all(method == "GET" for method, _path, _body in mx30.state.requests)

    def test_plugging_back_in_is_a_simulator_convention(self, client, mx30) -> None:
        before = {path: client.request("GET", path) for path in (DEVICE_CABINET, CABINET_COUNT)}
        info = client.monitoring()
        mx30.state.unplug_outputs()
        mx30.state.outputs_unplugged = False  # never done on the unit: not an observation
        assert {path: client.request("GET", path) for path in before} == before
        assert client.monitoring() == info

    def test_the_simulator_agrees_with_the_unplugged_fixture(self, client, mx30) -> None:
        from conftest import MX30_LIKE_API, MX30_UNPLUGGED_API

        mx30.state.unplug_outputs()
        info = client.monitoring()
        fixture = MX30_UNPLUGGED_API[MONITOR_INFO]
        assert set(info) == set(fixture)
        assert info["rvCardsRuntime"] == fixture["rvCardsRuntime"] == []

        def outputs(entries):
            return [(o["outputID"], o["type"], o["linkStatus"], o["status"]) for o in entries]

        assert outputs(info["outputStatus"]) == outputs(fixture["outputStatus"])
        assert client.request("GET", DEVICE_CABINET) == MX30_UNPLUGGED_API[DEVICE_CABINET] == []
        served = client.request("GET", CABINET_COUNT)["list"][0]
        assert served["CabinetCount"] == MX30_UNPLUGGED_API[CABINET_COUNT]["list"][0]["CabinetCount"] == 0
        # The comparison discriminates: connected, the outputs read otherwise.
        assert outputs(MX30_LIKE_API[MONITOR_INFO]["outputStatus"]) != outputs(fixture["outputStatus"])

    def test_the_command_line_offers_it_and_refuses_it_on_the_mx40(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(sys, "argv", ["coexsim", "--help"])
        with pytest.raises(SystemExit) as done:
            coexsim.main()
        assert done.value.code == 0 and "--outputs-unplugged" in capsys.readouterr().out
        # Refused before any socket is bound.
        monkeypatch.setattr(sys, "argv", ["coexsim", "--port", "0", "--outputs-unplugged"])
        with pytest.raises(SystemExit) as refused:
            coexsim.main()
        assert refused.value.code == 2 and "UNKNOWN" in capsys.readouterr().err


class TestMX40DefaultUnchanged:
    def test_snmp_writes_are_not_modelled_on_the_default(self) -> None:
        # What the MX40 Pro's firmware does with these PUTs is UNKNOWN: the
        # default keeps NotSupport and its constant GET, whatever the flag.
        with serving() as server:
            host, port = server.address
            client = CoexClient(host, port, timeout=2.0)
            for call in (lambda: client.set_snmp(True), lambda: client.identify_controller(True)):
                with pytest.raises(CoexError) as error:
                    call()
                assert error.value.code == 6
            server.state.snmp_enabled = True
            assert client.snmp_state() == {"state": False}

    def test_absent_endpoints_still_answer_404(self) -> None:
        with serving() as server:
            for path in MX40_ABSENT_GETS:
                status, headers, body = raw_get(server, path)
                assert (status, body) == (404, b""), path
                assert not any(k in headers for k in CORS), path
            status, headers, body = raw_get(server, "/api/v1/device/nonexistent")
            assert status == 200 and json.loads(body)["code"] == 6  # NotSupport, as before
            assert not any(k in headers for k in CORS)
            host, port = server.address
            client = CoexClient(host, port, timeout=2.0)
            with pytest.raises(CoexError):
                client.request("GET", "/api/v1/device/nonexistent")
            info = client.monitoring()
            assert info["name"] == "MX40 Pro_000001"
            assert len(info["cabinets"]) == 8
            assert info["cabinets"][0]["cabinetID"] == 0 and "cabinet" not in info["cabinets"][0]
            assert len(info["fanInfos"]) == 1 and len(info["outputStatus"]) == 2
            assert "accessoryMonitorInfo" not in info
            assert client.request("GET", "/api/v1/screen/cabinets")  # served on this profile
            assert server.state.current_input == 1

    def test_the_vmp_capture_endpoints_are_not_served_on_the_default(self) -> None:
        # /device/hw, display/state and hw/lock were never requested on the MX40
        # Pro (UNKNOWN there), and whether it announces is UNKNOWN: the default
        # keeps NotSupport, sends nothing, and keeps json.dumps's spacing.
        with serving() as server:
            host, port = server.address
            client = CoexClient(host, port, timeout=2.0)
            for path in (HW, DISPLAY_STATE, LOCK):
                with pytest.raises(CoexError) as error:
                    client.request("GET", path)
                assert error.value.code == 6, path
            for path, body in ((LOCK, {"appids": [APP_ID]}), (SYSTEMTIME, SYSTEMTIME_BODY)):
                with pytest.raises(CoexError) as error:
                    client.request("PUT", path, body)
                assert error.value.code == 6, path
            state = server.state
            assert state.lock_ip is None and state.system_time is None and state.mac is None
            assert (state.serial, state.firmware) == ("SIM-MX40-0001", "1.5.0")
            with pytest.raises(ValueError):
                server.start_announcing()
            assert not server.announcing
            assert raw_get(server, SNMPSTATE)[2] == (
                b'{"code": 0, "data": {"state": false}, "message": "Success"}')


class TestNothingFromTheShow:
    def test_the_simulator_source_carries_no_show_data(self) -> None:
        text = Path(coexsim.__file__).read_text()
        assert "_002198" not in text and "11151225588285440" not in text
        # A real 64-bit cabinet id runs to 17 digits; nothing that long is here.
        assert re.search(r"\d{16,}", text) is None

    def test_no_private_address_or_vendor_mac_is_in_the_simulator(self) -> None:
        text = Path(coexsim.__file__).read_text()
        assert "192.168." not in text
        assert "54:b5:6c" not in text.lower()  # the vendor's OUI: the served MAC is synthetic

    def test_served_remarks_and_labels_are_synthetic(self, client, mx30) -> None:
        for c in client.cabinets():
            assert c["rvCardInfo"]["firmwareRemark"] == ""
            assert c["rvCardInfo"]["mcuFirmWareRemark"] == ""
        assert client.monitoring()["name"] == coexsim.MX30_LIKE_LABEL
        screen = client.screens()["screens"][0]
        assert screen["screenName"] == "Wall"
        assert [p["pageName"] for p in screen["pageInfos"]] == [f"Simulated page {i + 1}" for i in range(8)]
