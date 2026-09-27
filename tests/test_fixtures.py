"""The machine-readable fixtures are the Python fixtures, byte for byte.

tests/fixtures/mx40_like_api.json is the COEX HTTP API as OBSERVED on an MX40
Pro, and tests/fixtures/mx30_like_api.json the same API as OBSERVED on one MX30
(firmware v1.5.1: operator-reported during that pass, read over SNMP later the
same day, and served as /api/v1/device/hw hwVersion that evening), for
consumers outside this repository -- crewbox's video module reads the same
controllers in TypeScript and has never met one. tests/fixtures/
mx30_announcement.json is that MX30's unsolicited UDP announcement and
tests/fixtures/mx30_websocket_events.jsonl the events its websocket pushed.
tests/fixtures/mx30_unplugged_api.json is the same MX30 with every output
line unplugged and the power on: the false all-clear, where monitor/info
still reads healthy. A fixture that drifts from the one these tests run
against would hand them a shape nothing here verifies, so this pins them
together.

To regenerate the MX30 files after changing the constants::

    .venv/bin/python -c "import json, sys; sys.path.insert(0, 'tests'); \
        from conftest import MX30_LIKE_API; \
        print(json.dumps(MX30_LIKE_API, indent=1, sort_keys=True))" \
        > tests/fixtures/mx30_like_api.json

    .venv/bin/python -c "import json, sys; sys.path.insert(0, 'tests'); \
        from conftest import MX30_UNPLUGGED_API; \
        print(json.dumps(MX30_UNPLUGGED_API, indent=1, sort_keys=True))" \
        > tests/fixtures/mx30_unplugged_api.json

    .venv/bin/python -c "import json, sys; sys.path.insert(0, 'tests'); \
        from conftest import MX30_LIKE_ANNOUNCEMENT; \
        print(json.dumps(MX30_LIKE_ANNOUNCEMENT, indent=1, sort_keys=True))" \
        > tests/fixtures/mx30_announcement.json

    .venv/bin/python -c "import json, sys; sys.path.insert(0, 'tests'); \
        from conftest import MX30_LIKE_WEBSOCKET_ABOUT as about, \
            MX30_LIKE_WEBSOCKET_EVENTS as events; \
        print('\\n'.join(json.dumps(line) for line in [{'__about__': about}] + events))" \
        > tests/fixtures/mx30_websocket_events.jsonl

The websocket file keeps each event's keys in the order the unit sent them,
so it is written without sort_keys.
"""

from __future__ import annotations

import copy
import ipaddress
import json
import re
from collections import Counter
from pathlib import Path

from conftest import (
    MX30_LIKE_ANNOUNCEMENT,
    MX30_LIKE_ANNOUNCEMENT_PORTS,
    MX30_LIKE_API,
    MX30_LIKE_APP_UUIDS,
    MX30_LIKE_EMPTY_200,
    MX30_LIKE_HW_OBSERVED,
    MX30_LIKE_IDS,
    MX30_LIKE_MAC,
    MX30_LIKE_MONITOR_INFO,
    MX30_LIKE_NAME,
    MX30_LIKE_RANDOM_PASSWORD,
    MX30_LIKE_UUIDS,
    MX30_LIKE_WEBSOCKET_ABOUT,
    MX30_LIKE_WEBSOCKET_EVENTS,
    MX30_UNPLUGGED_API,
    MX30_UNPLUGGED_DROPPED_OUTPUTS,
    MX40_LIKE_CABINETS,
    MX40_LIKE_INPUTS,
    MX40_LIKE_MONITOR_INFO,
    MX40_LIKE_SCREENS,
)

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE = FIXTURES / "mx40_like_api.json"
MX30_FIXTURE = FIXTURES / "mx30_like_api.json"
MX30_ANNOUNCEMENT_FIXTURE = FIXTURES / "mx30_announcement.json"
MX30_WEBSOCKET_FIXTURE = FIXTURES / "mx30_websocket_events.jsonl"
MX30_UNPLUGGED_FIXTURE = FIXTURES / "mx30_unplugged_api.json"
MX30_FIXTURES = (MX30_FIXTURE, MX30_ANNOUNCEMENT_FIXTURE, MX30_WEBSOCKET_FIXTURE,
                 MX30_UNPLUGGED_FIXTURE)


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
    # The about names the display-state endpoint as readable, and the secret as to be dropped.
    assert "/api/v1/screen/output/display/state" in api["__about__"]
    assert "IS the display state" in api["__about__"]
    assert "must drop randomPassword" in api["__about__"]
    assert "withdrawn" in api["__about__"]


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
    assert status["cabinets_listed"] == status["links_listed_ok"] == 3
    assert "cabinets_online" not in status
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


# --- The same MX30 that evening: identity, lock, display state ----------------


def _enveloped_size(data) -> int:
    """Bytes of the unit's compact {code, data, message} body around ``data``."""
    return len(json.dumps({"code": 0, "data": data, "message": "Success"}, separators=(",", ":")))


def _at(document, dotted: str):
    for key in dotted.split("."):
        document = document[key]
    return document


def _walk(value, key=None):
    """Every (key, value) pair in a JSON document; list items inherit the list's key."""
    yield key, value
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _walk(v, k)
    elif isinstance(value, list):
        for v in value:
            yield from _walk(v, key)


def _documents(path: Path) -> list:
    text = path.read_text()
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines()]
    return [json.loads(text)]


def test_mx30_display_state_and_lock_are_exactly_as_read() -> None:
    api = json.loads(MX30_FIXTURE.read_text())
    # Nothing in either body is show data, so both are the unit's bytes: the
    # compact enveloped sizes are the OBSERVED Content-Lengths.
    state = api["/api/v1/screen/output/display/state"]
    assert state == {"mappingState": [{"canvasID": 2048, "enable": False}],
                     "displayState": [{"canvasID": 2048, "displayMode": 0}]}
    assert _enveloped_size(state) == 140
    lock = api["/api/v1/device/hw/lock"]
    assert lock == {"locked": 0, "ip": ""}
    assert _enveloped_size(lock) == 58
    # canvasID 2048 is the canvas the rest of the fixture keys on.
    canvas = api["/api/v1/screen"]["screens"][0]["canvases"][0]
    assert {s["canvasID"] for s in state["displayState"]} == {canvas["canvasID"]} == {2048}
    # The endpoint the afternoon pass polled is still the empty 200 it was.
    assert api["/api/v1/device/screen/displaymode"] == MX30_LIKE_EMPTY_200


def test_mx30_hw_identity_carries_the_readings_and_the_joins() -> None:
    api = json.loads(MX30_FIXTURE.read_text())
    hw = api["/api/v1/device/hw"]
    # Every value the capture recorded is in the fixture as recorded.
    for dotted, value in MX30_LIKE_HW_OBSERVED.items():
        assert _at(hw, dotted) == value, dotted
    assert (hw["name"], hw["modelID"], hw["hwVersion"]) == ("MX30", 5138, "V1.5.1")
    # 44 top-level keys and 161 capability keys, as the unit sent them.
    assert len(hw) == 44 and len(hw["capability"]) == 161
    # REASONED joins, kept so a consumer can make them: 5138 is the modelId
    # device/input carries; mode is hw/mode's; uptime is monitor/info's runtime.
    assert api["/api/v1/device/input"]["inputPortConfig"][0]["modelId"] == hw["modelID"]
    assert hw["mode"] == api["/api/v1/device/hw/mode"]["mode"] == 3
    assert hw["uptime"] == api["/api/v1/device/monitor/info"]["runtime"]
    assert hw["customName"] == api["/api/v1/device/monitor/info"]["name"] == MX30_LIKE_NAME
    # OBSERVED: the announcement's mac is /device/hw's, and the unit's IP is where it came from.
    assert hw["mac"] == MX30_LIKE_MAC == MX30_LIKE_ANNOUNCEMENT["payload"][34:51]
    assert hw["ip"] == MX30_LIKE_ANNOUNCEMENT["source_ip"]
    # frameRateTable: 19 numbers, some fractional (count and typing OBSERVED).
    rates = hw["capability"]["frameRateTable"]
    assert len(rates) == 19 and any(isinstance(r, float) for r in rates)
    assert any(isinstance(r, int) for r in rates)
    versions = api["/api/v1/device/hw/versions"]
    # OBSERVED: the two serials differ; the SNMP "firmware" string is on both endpoints.
    assert versions["controllerSystem"]["sn"] != hw["sn"]
    assert versions["controllerSystem"]["xserver"] == hw["hwVersion"]
    assert versions["mainBoard"] == dict.fromkeys(("hardware", "mcu", "fpgaA", "fpgaB", "fpga"), "")
    assert versions["slots"] == []


def test_random_password_is_only_ever_the_fake_value() -> None:
    """The unit served a real 8-digit randomPassword to a bare GET; no fixture may carry one."""
    seen = []
    for path in sorted(FIXTURES.glob("*.json")) + sorted(FIXTURES.glob("*.jsonl")):
        for document in _documents(path):
            for key, value in _walk(document):
                if key == "randomPassword":
                    seen.append((path.name, value))
                # Anything shaped like the real value is the fake one.
                if isinstance(value, str) and re.fullmatch(r"\d{8}", value):
                    assert value == MX30_LIKE_RANDOM_PASSWORD, (path.name, key)
    assert MX30_LIKE_RANDOM_PASSWORD == "00000000"
    # The unplugged fixture carries /device/hw over from the connected one.
    assert seen == [("mx30_like_api.json", "00000000"), ("mx30_unplugged_api.json", "00000000")]
    assert MX30_LIKE_API["/api/v1/device/hw"]["randomPassword"] == "00000000"
    # It appeared in no websocket push on the unit, and appears in none here.
    assert "randomPassword" not in MX30_WEBSOCKET_FIXTURE.read_text()


def test_nothing_from_the_show_is_in_any_mx30_fixture() -> None:
    mac = re.compile(r"(?<![0-9A-Fa-f:])[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}(?![0-9A-Fa-f:])")
    uuid = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
    synthetic_uuids = {u.strip("{}") for u in MX30_LIKE_UUIDS} | set(MX30_LIKE_APP_UUIDS)
    documentation = ipaddress.ip_network("192.0.2.0/24")  # RFC 5737 TEST-NET-1
    for path in MX30_FIXTURES:
        text = path.read_text()
        # The only MAC is the documentation-range one (RFC 7042).
        assert {m.lower() for m in mac.findall(text)} <= {MX30_LIKE_MAC}, path.name
        assert MX30_LIKE_MAC.startswith("00:00:5e:00:53:")
        # The only UUIDs are the synthetic ones, all zeros but for the last digits.
        found = set(uuid.findall(text))
        assert found <= synthetic_uuids, (path.name, found - synthetic_uuids)
        assert all(u.startswith("00000000-0000-0000-0000-") for u in found)
        assert "192.168." not in text and "172.16." not in text, path.name
        for document in _documents(path):
            for key, value in _walk(document):
                if not isinstance(key, str) or not isinstance(value, str):
                    continue
                # Every address is TEST-NET-1, bar the front panel's loopback (OBSERVED).
                if "ip" in key.lower() and re.fullmatch(r"[0-9.]+", value):
                    address = ipaddress.ip_address(value)
                    assert address in documentation or value == "127.0.0.1", (path.name, key)
                # Every serial is empty or an obvious fixture value.
                if key == "sn" or key.endswith("Sn") or "serial" in key.lower():
                    assert value == "" or value.startswith("FIXTURE-SN-"), (path.name, key)


# --- The MX30's announcement ----------------------------------------------------


def test_mx30_announcement_fixture_matches_the_python_fixture() -> None:
    assert json.loads(MX30_ANNOUNCEMENT_FIXTURE.read_text()) == MX30_LIKE_ANNOUNCEMENT


def test_mx30_announcement_keeps_the_observed_byte_layout() -> None:
    fixture = json.loads(MX30_ANNOUNCEMENT_FIXTURE.read_text())
    payload = fixture["payload"]
    raw = payload.encode("ascii")
    # 96 bytes of bare JSON: no header, no terminator, compact, keys in this order.
    assert len(raw) == 96 and raw[:1] == b"{" and raw[-3:] == b"}]}"
    decoded = json.loads(payload)
    assert json.dumps(decoded, separators=(",", ":")) == payload
    assert list(decoded) == ["data"] and len(decoded["data"]) == 1
    entry = decoded["data"][0]
    assert list(entry) == ["apiPort", "mac", "authType", "workMode", "https"]
    assert entry == {"apiPort": "8001", "mac": MX30_LIKE_MAC, "authType": 0, "workMode": 0,
                     "https": "9001"}
    # Ports are strings, authType and workMode integers (OBSERVED types).
    assert [type(entry[k]) for k in entry] == [str, str, int, int, str]
    # Every value sits where it sat on the wire.
    for key, (first, last) in fixture["value_spans"].items():
        assert payload[first:last + 1] == json.dumps(entry[key], separators=(",", ":")), key
    assert set(fixture["value_spans"]) == set(entry)
    # The MAC is /device/hw's (OBSERVED equality), lower-case and colon-separated.
    assert entry["mac"] == MX30_LIKE_API["/api/v1/device/hw"]["mac"] == entry["mac"].lower()
    assert entry["apiPort"] == "8001"
    # Wire facts.
    assert fixture["destination_ports"] == list(MX30_LIKE_ANNOUNCEMENT_PORTS) == [54622, 54623,
                                                                                 54624, 54700]
    assert fixture["source_port"] == 54650
    assert fixture["interval_s"] == 3.0
    assert fixture["source_ip"] == MX30_LIKE_API["/api/v1/device/hw"]["ip"]
    assert fixture["destination_ip"].endswith(".255")
    about = fixture["__about__"]
    for fact in ("54622", "54623", "54624", "54700", "54650", "every 3 s", "96 bytes",
                 "OBSERVED", "REASONED", "UNKNOWN"):
        assert fact in about, fact


# --- The MX30's websocket ---------------------------------------------------------

_EVENT_SENDERS = {
    "controllerRealTimeInfoChange": "monitor",
    "cabinetRealTimeInfoChange": "monitor",
    "cabinetsRuntimeInfoChange": "monitor",
    "deviceLastOperatorChange": "device",
    "deviceLockChange": "device",
    "canvasDisplayModeChange": "device",
}


def test_mx30_websocket_fixture_matches_the_python_fixture() -> None:
    lines = _documents(MX30_WEBSOCKET_FIXTURE)
    assert lines[0] == {"__about__": MX30_LIKE_WEBSOCKET_ABOUT}
    assert lines[1:] == MX30_LIKE_WEBSOCKET_EVENTS


def test_mx30_websocket_events_keep_the_observed_envelope_and_order() -> None:
    lines = _documents(MX30_WEBSOCKET_FIXTURE)[1:]
    assert all(set(line) == {"t", "event"} for line in lines)
    times = [line["t"] for line in lines]
    assert times == sorted(set(times)) and times[0] > 0
    events = [line["event"] for line in lines]
    for event in events:
        assert list(event) == ["eventData", "eventSender", "eventType"]
        assert event["eventSender"] == _EVENT_SENDERS[event["eventType"]]
    # One of each type the unit pushed, with the freeze pair and both actor shapes.
    assert {e["eventType"] for e in events} == set(_EVENT_SENDERS)
    # The freeze and its release: 2 then 0, on the canvas display/state keys on.
    changes = [(i, e) for i, e in enumerate(events) if e["eventType"] == "canvasDisplayModeChange"]
    assert [e["eventData"]["value"] for _, e in changes] == [2, 0]
    canvas = MX30_LIKE_API["/api/v1/screen/output/display/state"]["displayState"][0]["canvasID"]
    for i, change in changes:
        assert change["eventData"]["canvasIDs"] == [canvas]
        # Compact, as on the wire: this event carries nothing synthetic, so its
        # size is the OBSERVED one.
        assert len(json.dumps(change, separators=(",", ":"))) == 105
        # Each followed a front-panel operator event by about 103 ms (OBSERVED four times).
        actor = events[i - 1]
        assert actor["eventType"] == "deviceLastOperatorChange"
        assert actor["eventData"]["ip"] == "127.0.0.1"
        assert actor["eventData"]["appID"].startswith("LCDAPP_")
        assert 0.09 < lines[i]["t"] - lines[i - 1]["t"] < 0.12
    front_panel = {e["eventData"]["appID"] for e in events
                   if e["eventType"] == "deviceLastOperatorChange"
                   and e["eventData"]["ip"] == "127.0.0.1"}
    assert len(front_panel) == 1  # the same id both times
    # A client's write is attributed to its IP and Application-Id; the lock names the requester.
    client = [e["eventData"] for e in events if e["eventType"] == "deviceLastOperatorChange"
              and e["eventData"]["ip"] != "127.0.0.1"]
    assert len(client) == 1 and client[0]["appID"].startswith("Launcher_")
    lock = next(e["eventData"] for e in events if e["eventType"] == "deviceLockChange")
    assert lock == {"locked": 1, "ip": client[0]["ip"]}
    # Timestamps: formats OBSERVED, values synthetic (2000-01-01).
    for event in events:
        stamp = event["eventData"].get("timestamp")
        if isinstance(stamp, int):
            assert 946684800 <= stamp < 946684800 + 86400
        elif stamp is not None:
            assert re.fullmatch(r"2000-01-01 \d\d:\d\d:\d\d", stamp)


def test_mx30_websocket_telemetry_agrees_with_the_http_fixture() -> None:
    events = {line["event"]["eventType"]: line["event"]["eventData"]
              for line in MX30_LIKE_WEBSOCKET_EVENTS}
    info = MX30_LIKE_MONITOR_INFO
    controller = events["controllerRealTimeInfoChange"]
    # The push carries the top of monitor/info, plus a timestamp, and nothing per cabinet.
    assert list(controller) == [
        "name", "runtime", "totalRuntime", "mainBoardTemperature", "mainBoardVoltage",
        "backupStatus", "fanInfos", "voltageInfos", "temperatureInfos", "powerMonitorInfos",
        "controllerPortMonitorInfos", "imbLinkStatus", "timestamp",
    ]
    for key in ("name", "runtime", "totalRuntime", "mainBoardTemperature", "mainBoardVoltage",
                "backupStatus", "fanInfos", "powerMonitorInfos", "controllerPortMonitorInfos",
                "imbLinkStatus"):
        assert controller[key] == info[key], key
    cabinet = events["cabinetRealTimeInfoChange"]
    assert cabinet["cabinetID"] == cabinet["rvCardID"] in MX30_LIKE_IDS
    assert isinstance(cabinet["cabinetID"], int)  # REASONED: the masking kept length, not type
    by_id = {c["id"]: c for c in MX30_LIKE_API["/api/v1/device/cabinet"]}
    assert cabinet["netPortIndex"] == by_id[cabinet["cabinetID"]]["outputID"]
    assert cabinet["cabinetMonitorInfo"]["cabinetID"] == 0
    assert cabinet["cabinetMonitorInfo"]["voltage"] == cabinet["voltage"]
    card = next(c["rvCards"][0] for c in info["cabinets"] if c["cabinetID"] == cabinet["cabinetID"])
    for key in ("temperature", "voltage", "errorBit", "nextCabinetLinkStatus", "backupStatus"):
        assert cabinet[key] == card[key], key
    runtimes = events["cabinetsRuntimeInfoChange"]["rvCardMonitorInfos"]
    assert runtimes == info["rvCardsRuntime"]
    assert len({r["runtime"] for r in runtimes}) == 1
    about = MX30_LIKE_WEBSOCKET_ABOUT
    for fact in ("/api/v1/websocketchannel", "101", "ping every 1.000 s", "without any hello",
                 "OBSERVED", "REASONED", "UNKNOWN", "1 = blackout is REASONED"):
        assert fact in about, fact


# --- The same MX30 with every output line unplugged ---------------------------------

UNPLUGGED_CHANGED_PATHS = {
    "__about__",
    "/api/v1/device/cabinet",
    "/api/v1/device/monitor/info",
    "/api/v1/screen/cabinet/count",
}


def test_mx30_unplugged_json_fixture_matches_the_python_fixture() -> None:
    api = json.loads(MX30_UNPLUGGED_FIXTURE.read_text())
    assert set(api) == set(MX30_UNPLUGGED_API)
    for path, body in MX30_UNPLUGGED_API.items():
        assert api[path] == body, path


def test_mx30_unplugged_differs_from_the_connected_fixture_only_where_the_unit_did() -> None:
    connected = json.loads(MX30_FIXTURE.read_text())
    unplugged = json.loads(MX30_UNPLUGGED_FIXTURE.read_text())
    # Same paths; everything not re-read with the lines out is carried over as is.
    assert set(unplugged) == set(connected)
    assert {p for p in connected if connected[p] != unplugged[p]} == UNPLUGGED_CHANGED_PATHS
    # Within monitor/info only outputStatus and rvCardsRuntime moved (OBSERVED).
    before = connected["/api/v1/device/monitor/info"]
    after = unplugged["/api/v1/device/monitor/info"]
    assert set(after) == set(before)
    assert {k for k in before if before[k] != after[k]} == {"outputStatus", "rvCardsRuntime"}


def test_mx30_unplugged_monitor_info_is_the_false_all_clear() -> None:
    connected = json.loads(MX30_FIXTURE.read_text())
    api = json.loads(MX30_UNPLUGGED_FIXTURE.read_text())
    info = api["/api/v1/device/monitor/info"]
    # Every cabinet and card still listed, every link up, every reading as it
    # was connected -- with nothing connected (OBSERVED for ~8.5 minutes).
    assert info["cabinets"] == connected["/api/v1/device/monitor/info"]["cabinets"]
    cards = [card for cabinet in info["cabinets"] for card in cabinet["rvCards"]]
    assert [card["cabinetID"] for card in cards] == list(MX30_LIKE_IDS)
    assert all(card["nextCabinetLinkStatus"]["linkStatus"] is True for card in cards)
    assert all(card["temperature"]["value"] > 0 and card["voltage"]["value"] > 0 for card in cards)
    # What did move.
    assert info["rvCardsRuntime"] == []
    assert all(o["linkStatus"] is False for o in info["outputStatus"])
    assert MX30_UNPLUGGED_DROPPED_OUTPUTS == (2048, 2049, 2050, 2051, 2052)
    status = {o["outputID"]: o["status"] for o in info["outputStatus"]}
    assert all(status[o] == 2 for o in MX30_UNPLUGGED_DROPPED_OUTPUTS)
    # Outputs whose link was already false are as the connected read had them
    # (whether their status moved was not recorded).
    was = {o["outputID"]: o for o in connected["/api/v1/device/monitor/info"]["outputStatus"]}
    for o in info["outputStatus"]:
        if o["outputID"] not in MX30_UNPLUGGED_DROPPED_OUTPUTS:
            assert o == was[o["outputID"]], o["outputID"]
    assert len(info["outputStatus"]) == 33


def test_mx30_unplugged_presence_signals_say_nothing_is_connected() -> None:
    api = json.loads(MX30_UNPLUGGED_FIXTURE.read_text())
    assert api["/api/v1/device/cabinet"] == []
    counts = api["/api/v1/screen/cabinet/count"]["list"]
    screen = api["/api/v1/screen"]["screens"][0]["screenID"]
    assert counts == [{"ScreenID": screen, "CabinetCount": 0, "CabinetCountInBlackList": 0}]
    # The wall still has cabinets configured -- the count to compare against is
    # the expected number, not whatever monitor/info lists.
    assert len(api["/api/v1/device/monitor/info"]["cabinets"]) == len(MX30_LIKE_IDS) > 0
    # Display state read normal through the unplugging (OBSERVED): it does not show it either.
    state = api["/api/v1/screen/output/display/state"]
    assert [s["displayMode"] for s in state["displayState"]] == [0]
    # The endpoints this firmware lacks are still the empty 200, lines out or not.
    assert api["/api/v1/device"] == api["/api/v1/device/screen/displaymode"] == MX30_LIKE_EMPTY_200


def test_mx30_unplugged_about_states_the_trap_with_labels() -> None:
    about = json.loads(MX30_UNPLUGGED_FIXTURE.read_text())["__about__"]
    for fact in ("FALSE-ALL-CLEAR TRAP", "/api/v1/device/monitor/info", "/api/v1/device/cabinet",
                 "/api/v1/screen/cabinet/count", "CabinetCount is 0", "outputStatus[].linkStatus",
                 "rvCardsRuntime", "about 8.5 minutes", "last-known values",
                 "was REASONED and is withdrawn", "displayMode 0", "every 3 s throughout",
                 "not re-read with the lines out", "must drop randomPassword",
                 "crewbox_harness.mts", "OBSERVED", "REASONED", "UNKNOWN", "hwVersion V1.5.1"):
        assert fact.lower() in about.lower(), fact
    assert "OBSERVED" in about and "REASONED" in about and "UNKNOWN" in about
    # A standby after power-off is not an unplugged wall, and is not in this file.
    assert "connection refused" in about and "standby" in about


def test_nothing_from_the_mx30_show_is_in_the_unplugged_fixture() -> None:
    text = MX30_UNPLUGGED_FIXTURE.read_text()
    api = json.loads(text)
    # The same checks as the connected fixture's: synthetic ids and UUIDs only.
    assert not re.search(r"407338\d{10}", text)
    assert {int(m) for m in re.findall(r"\b\d{13,}\b", text)} == set(MX30_LIKE_IDS)
    uuid = r"\{[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}"
    assert set(re.findall(uuid, text)) == set(MX30_LIKE_UUIDS)
    assert api["/api/v1/device/monitor/info"]["name"] == MX30_LIKE_NAME
    assert api["/api/v1/device/hw"]["randomPassword"] == MX30_LIKE_RANDOM_PASSWORD
    assert api["/api/v1/device/hw"]["mac"] == MX30_LIKE_MAC
    assert "192.168." not in text and "router" not in text.lower() and "wi-fi" not in text.lower()
    # Every clock time in the note is UTC, as docs/read-only-monitoring.md gives them.
    times = re.findall(r"\b\d\d:\d\d(?::\d\d)?Z?", api["__about__"])
    assert times and all(t.endswith("Z") for t in times), times
