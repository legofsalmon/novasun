"""The machine-readable fixtures are the Python fixtures, byte for byte.

tests/fixtures/mx40_like_api.json is the COEX HTTP API as OBSERVED on an MX40
Pro, and tests/fixtures/mx30_like_api.json the same API as OBSERVED on one MX30
(firmware v1.5.1, operator-reported), for consumers outside this repository --
crewbox's video module reads the same controllers in TypeScript and has never
met one. A fixture that drifts from the one these tests run against would hand
them a shape nothing here verifies, so this pins the two together.

To regenerate the MX30 file after changing the constants::

    .venv/bin/python -c "import json, sys; sys.path.insert(0, 'tests'); \
        from conftest import MX30_LIKE_API; \
        print(json.dumps(MX30_LIKE_API, indent=1, sort_keys=True))" \
        > tests/fixtures/mx30_like_api.json
"""

from __future__ import annotations

import copy
import json
import re
from collections import Counter
from pathlib import Path

from conftest import (
    MX30_LIKE_API,
    MX30_LIKE_EMPTY_200,
    MX30_LIKE_IDS,
    MX30_LIKE_MONITOR_INFO,
    MX30_LIKE_NAME,
    MX30_LIKE_UUIDS,
    MX40_LIKE_CABINETS,
    MX40_LIKE_INPUTS,
    MX40_LIKE_MONITOR_INFO,
    MX40_LIKE_SCREENS,
)

FIXTURE = Path(__file__).parent / "fixtures" / "mx40_like_api.json"
MX30_FIXTURE = Path(__file__).parent / "fixtures" / "mx30_like_api.json"


def test_json_fixture_matches_the_python_fixtures() -> None:
    api = json.loads(FIXTURE.read_text())
    assert api["/api/v1/device/cabinet"] == MX40_LIKE_CABINETS
    assert api["/api/v1/device/input/sources"] == MX40_LIKE_INPUTS
    assert api["/api/v1/device/monitor/info"] == MX40_LIKE_MONITOR_INFO
    assert api["/api/v1/screen"] == MX40_LIKE_SCREENS


def test_the_absent_endpoints_are_marked_as_observed() -> None:
    api = json.loads(FIXTURE.read_text())
    assert api["/api/v1/device"] == {"__http_status__": 404}
    assert api["/api/v1/device/audio"] == {"__http_status__": 404}
    assert api["/api/v1/device/snmpstate"] == {"state": False}
    assert api["/api/v1/device/screen/displaymode"] == {"__http_status__": 404}
    assert api["/api/v1/device/backup"] == {"master": "", "backup": "", "masterName": "", "backupName": ""}
    assert api["/api/v1/device/multifunc-card/detailinfo"] == []
    assert api["/api/v1/device/hw/mode"] == {"mode": 3}


def test_nothing_from_the_show_is_in_the_fixture() -> None:
    text = FIXTURE.read_text()
    # The real unit's name suffix and a real cabinet id; neither may appear.
    assert "_002198" not in text
    assert "11151225588285440" not in text


# --- The MX30 fixture --------------------------------------------------------


def test_mx30_json_fixture_matches_the_python_fixture() -> None:
    api = json.loads(MX30_FIXTURE.read_text())
    assert set(api) == set(MX30_LIKE_API)
    for path, body in MX30_LIKE_API.items():
        assert api[path] == body, path


def test_mx30_empty_200_marker_is_on_exactly_the_paths_that_answered_that_way() -> None:
    api = json.loads(MX30_FIXTURE.read_text())
    assert MX30_LIKE_EMPTY_200 == {"__http_status__": 200, "__empty_body__": True}
    empty = {path for path, body in api.items() if body == MX30_LIKE_EMPTY_200}
    assert empty == {
        # OBSERVED with curl -i: HTTP 200, Content-Length: 0, no Content-Type, no envelope.
        "/api/v1/device",
        "/api/v1/device/screen/displaymode",
        "/api/v1/novasun-probe-no-such-path",
        # Seen only through a client that cannot tell an empty body from an
        # empty envelope: absent-or-empty, UNKNOWN which.
        "/api/v1/screen/cabinets",
        "/api/v1/screen/properties",
        "/api/v1/screen/displayeffect",
    }
    # No 404 was seen on this firmware; the MX40 fixture's markers do not carry over.
    assert not any(body == {"__http_status__": 404} for body in api.values())
    assert api["/api/v1/device/audio"] == {"enable": False, "source": 65535, "sourceName": ""}
    assert api["/api/v1/device/backup"] == {"master": "", "backup": "",
                                            "masterName": "", "backupName": ""}
    assert api["/api/v1/device/multifunc-card/detailinfo"] == []
    assert api["/api/v1/device/hw/mode"] == {"mode": 3}
    assert api["/api/v1/device/snmpstate"] == {"state": False}
    count = api["/api/v1/screen/cabinet/count"]["list"][0]["CabinetCount"]
    assert count == len(api["/api/v1/device/cabinet"])
    assert "__empty_body__" in api["__about__"] and "v1.5.1" in api["__about__"]


def test_nothing_from_the_mx30_show_is_in_the_fixture() -> None:
    text = MX30_FIXTURE.read_text()
    api = json.loads(text)
    # The unit's cabinet ids were 16 digits with one common prefix; every large
    # integer here is one of the synthetic ids.
    assert not re.search(r"407338\d{10}", text)
    assert {int(m) for m in re.findall(r"\b\d{13,}\b", text)} == set(MX30_LIKE_IDS)
    # The only UUIDs are the synthetic ones.
    uuid = r"\{[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}"
    assert set(re.findall(uuid, text)) == set(MX30_LIKE_UUIDS)
    # Every operator-facing string is the synthetic one.
    assert api["/api/v1/device/monitor/info"]["name"] == MX30_LIKE_NAME == "Stage left"
    screen = api["/api/v1/screen"]["screens"][0]
    assert screen["screenName"] == "Main"
    assert [p["pageName"] for p in screen["pageInfos"]] == [f"Fixture page {i}" for i in range(1, 9)]
    presets = api["/api/v1/preset"]["screenPresets"][0]["presets"]
    assert [p["name"] for p in presets] == ["Preset A", "Preset B"]
    # The receiving-card remarks were populated on the unit: show data, empty here.
    for cabinet in api["/api/v1/device/cabinet"]:
        assert cabinet["rvCardInfo"]["firmwareRemark"] == ""
        assert cabinet["rvCardInfo"]["mcuFirmWareRemark"] == ""
    assert api["/api/v1/device/input"]["inputPortConfig"][0]["hardwareID"] == "0 0 0001"
    assert screen["inputPort"]["HardwareID"] == ""


def test_the_mx30_fixture_keeps_the_joins_the_unit_showed() -> None:
    api = MX30_LIKE_API
    ids = [c["id"] for c in api["/api/v1/device/cabinet"]]
    info = api["/api/v1/device/monitor/info"]
    # cabinetID is populated on this firmware and joins every list that carries one.
    assert [c["cabinetID"] for c in info["cabinets"]] == ids
    assert all(c["rvCardID"] == c["cabinetID"] == c["rvCards"][0]["cabinetID"] for c in info["cabinets"])
    assert {r["cabinetID"] for r in info["rvCardsRuntime"]} == set(ids)
    assert [r["cabinetID"] for r in info["rvCardsRuntime"]] != ids  # its own stable order
    canvas = api["/api/v1/screen"]["screens"][0]["canvases"][0]
    assert {c["cabinetID"] for c in canvas["cabinets"]} == set(ids)
    # (outputID, index) is the per-cabinet address; connectID on the canvas is index.
    by_id = {c["id"]: c for c in api["/api/v1/device/cabinet"]}
    assert all(c["outputID"] == by_id[c["cabinetID"]]["outputID"] for c in canvas["cabinets"])
    assert all(c["connectID"] == by_id[c["cabinetID"]]["index"] for c in canvas["cabinets"])
    assert all(c["outPutID"] == c["rvCards"][0]["netPortIndex"] == by_id[c["cabinetID"]]["outputID"]
               for c in info["cabinets"])
    # The nested cabinet.voltage mirrors the card's reading; the card is the source.
    assert all(c["cabinet"]["voltage"] == c["rvCards"][0]["voltage"] for c in info["cabinets"])
    assert all("temperature" not in c and "voltage" not in c for c in info["cabinets"])
    # screenSourceStatus and the layers reference inputs by groupId, never by id.
    inputs = {i["id"]: i for i in api["/api/v1/device/input/sources"]}
    assert {s["portID"] for s in info["screenSourceStatus"]} == set(inputs)
    assert all(s["groupID"] == inputs[s["portID"]]["groupId"] for s in info["screenSourceStatus"])
    assert all(s["linkStatus"] is (inputs[s["portID"]]["sourceStatus"] == 1)
               for s in info["screenSourceStatus"])
    groups = {i["groupId"]: i for i in inputs.values()}
    for mode in api["/api/v1/screen"]["screens"][0]["layersInWorkingMode"]:
        for layer in mode["layers"]:
            assert layer["source"] in groups and layer["source"] not in inputs
            assert layer["sourceSize"] == groups[layer["source"]]["actualResolution"]
    # 33 outputs: ten type 0, twenty type 5, two type 1, one type 3; five linked.
    assert Counter(o["type"] for o in info["outputStatus"]) == {0: 10, 5: 20, 1: 2, 3: 1}
    linked = {o["outputID"] for o in info["outputStatus"] if o["linkStatus"]}
    assert linked == {2048, 2049, 2050, 2051, 2052}
    assert {o["outputID"] for o in info["outputStatus"] if o["status"]} == {2053}
    # errorBit[0].value differs per output; the same three voltages are odd on /device/cabinet.
    assert [c["rvCards"][0]["errorBit"][0]["value"] for c in info["cabinets"]] == [190, 189, 187]
    assert [c["voltage"] for c in api["/api/v1/device/cabinet"]] == [34, 57, 235]


def test_this_repositorys_readers_accept_the_mx30_shape() -> None:
    from novasun.coex import diff_snapshots
    from novasun.monitor import interpret_monitor_info

    status = interpret_monitor_info(MX30_LIKE_MONITOR_INFO)
    assert status["cabinets_total"] == status["cabinets_online"] == status["links_ok"] == 3
    assert status["temperature_c"] == 44.0
    assert status["main_board_temperature_c"] == 32.0
    assert status["main_board_voltage_v"] == 11.56
    # Keyed by the now-populated cabinetID: a reordered list is not a change ...
    before = copy.deepcopy(MX30_LIKE_MONITOR_INFO)
    after = copy.deepcopy(MX30_LIKE_MONITOR_INFO)
    after["cabinets"].reverse()
    assert diff_snapshots(before, after) == []
    # ... and one voltage move surfaces twice, on the card and in the mirror.
    after["cabinets"][0]["rvCards"][0]["voltage"]["value"] = 4.0
    after["cabinets"][0]["cabinet"]["voltage"]["value"] = 4.0
    changes = diff_snapshots(before, after)
    assert len(changes) == 2
    assert {path.rsplit(".", 2)[-2] for path, _, _ in changes} == {"voltage"}
