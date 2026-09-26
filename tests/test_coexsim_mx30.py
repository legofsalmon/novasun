"""The COEX simulator's MX30-like firmware profile.

Pins the shapes OBSERVED on one MX30 (firmware V1.5.1, read over SNMP) on
2026-09-26, so a consumer developed against the simulator meets the surface
that unit presented -- above all that an absent endpoint answers an empty HTTP
200 rather than a 404, which the read-only client turns into ``{}`` without a
word. The read-only pass sent GETs only; the two writes sent later that day
(snmpstate and hw/colorBeacon, with VMP closed) are pinned in ``TestWrites``.
Every value here is synthetic. The MX40 Pro default is asserted unchanged
alongside: one unit of each was read, and the simulator must not blur them.
"""

from __future__ import annotations

import http.client
import json
import re
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
        # The two absent endpoints are empty 200s, so nothing is *recorded* as
        # failing: that silence is the observed behaviour, not a simulator gap.
        assert snapshot.errors == {}
        assert snapshot.display_mode is None
        assert snapshot.raw["device"] == {}
        assert len(snapshot.cabinets) == 72 and snapshot.healthy
        assert "72/72 online" in snapshot.summary()
        assert snapshot.hottest is not None and snapshot.hottest.temperature == 46
        assert snapshot.signal_present == ["HDMI2.0 1", "internal-source"]
        assert snapshot.device_name == mx30.state.custom_name
        # The name is a label, not a model (OBSERVED on the MX30: it carried none).
        assert snapshot.model != "MX30"
        assert all(method == "GET" for method, _path, _body in mx30.state.requests)

    def test_interpret_monitor_info_reads_the_shape(self, client) -> None:
        status = interpret_monitor_info(client.monitoring())
        assert status["cabinets_total"] == 72 and status["cabinets_online"] == 72
        assert status["temperature_c"] == 46
        assert status["main_board_temperature_c"] == 32
        assert status["main_board_voltage_v"] == 11.56
        assert status["links_ok"] == 72

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
        # Whether the beacon lit is UNKNOWN, so nothing is modelled as changing.
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


class TestNothingFromTheShow:
    def test_the_simulator_source_carries_no_show_data(self) -> None:
        text = Path(coexsim.__file__).read_text()
        assert "_002198" not in text and "11151225588285440" not in text
        # A real 64-bit cabinet id runs to 17 digits; nothing that long is here.
        assert re.search(r"\d{16,}", text) is None

    def test_served_remarks_and_labels_are_synthetic(self, client, mx30) -> None:
        for c in client.cabinets():
            assert c["rvCardInfo"]["firmwareRemark"] == ""
            assert c["rvCardInfo"]["mcuFirmWareRemark"] == ""
        assert client.monitoring()["name"] == coexsim.MX30_LIKE_LABEL
        screen = client.screens()["screens"][0]
        assert screen["screenName"] == "Wall"
        assert [p["pageName"] for p in screen["pageInfos"]] == [f"Simulated page {i + 1}" for i in range(8)]
