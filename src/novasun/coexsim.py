"""A fake COEX controller: the HTTP API on port 8001, without the hardware.

MX-class controllers are driven through the JSON API rather than the register
bus, so developing that path offline needs a server that answers it. This one
holds real state -- change the brightness and the next GET reflects it -- so an
application's read/modify/display loop can be built and tested against it.

It implements the endpoints an application actually leans on, and answers
anything else with ``NotSupport`` (code 6), which is also what real firmware
does for endpoints its model does not implement. Do not mistake it for a
specification: the response *shapes* are reconstructed from NovaStar's manual
and from what published clients expect, and the field names should be confirmed
against hardware before an application depends on their exact spelling.

    python -m novasun.coexsim --port 8001
"""

from __future__ import annotations

import argparse
import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

DEFAULT_PORT = 8001


@dataclass
class CoexState:
    """Everything the fake controller remembers."""

    model: str = "MX40 Pro"
    device_name: str = "Simulated MX40 Pro"
    serial: str = "SIM-MX40-0001"
    firmware: str = "1.5.0"
    display_mode: int = 0  # 0 normal, 1 blackout, 2 freeze
    current_preset: str | None = None
    current_input: int = 1
    screens: list[dict[str, Any]] = field(default_factory=list)
    cabinets: list[dict[str, Any]] = field(default_factory=list)
    presets: list[dict[str, Any]] = field(default_factory=list)
    inputs: list[dict[str, Any]] = field(default_factory=list)
    requests: list[tuple[str, str, Any]] = field(default_factory=list)
    #: Documented endpoints this firmware answers with HTTP 404. OBSERVED on an
    #: MX40 Pro: ``/api/v1/device``, ``/api/v1/device/audio`` and the GET of
    #: ``/api/v1/device/screen/displaymode`` are in NovaStar's manual and absent
    #: from the unit. The default models that unit, so code that depends on any
    #: of them fails here rather than on site; a test that wants one served
    #: removes it from this set. Only GETs consult it: whether the PUT of
    #: displaymode exists on that firmware is UNKNOWN, so the simulator still
    #: accepts it.
    missing_endpoints: set[str] = field(
        default_factory=lambda: {
            "/api/v1/device",
            "/api/v1/device/audio",
            "/api/v1/device/screen/displaymode",
        }
    )

    def __post_init__(self) -> None:
        if not self.screens:
            self.screens = [
                {"screenID": "screen-1", "name": "Main", "width": 3840, "height": 2160,
                 "brightness": 1.0, "gamma": 2.8, "colorTemperature": 6500}
            ]
        if not self.cabinets:
            # Two ports of four cabinets, laid out left to right.
            self.cabinets = [
                {
                    "id": 93138183199495 + index,
                    "screenID": "screen-1",
                    "name": f"Cabinet {index + 1}",
                    "port": index // 4,
                    "positionX": (index % 4) * 480,
                    "positionY": (index // 4) * 540,
                    "width": 480,
                    "height": 540,
                    "brightness": 1.0,
                    "temperature": 27.5 + index * 0.5,
                    "online": True,
                }
                for index in range(8)
            ]
        if not self.presets:
            self.presets = [
                {"id": "preset-1", "name": "Show", "index": 1},
                {"id": "preset-2", "name": "Rehearsal", "index": 2},
            ]
        if not self.inputs:
            self.inputs = [
                {"id": 1, "name": "HDMI 1", "type": "HDMI", "connected": True,
                 "resolution": {"width": 3840, "height": 2160, "frameRate": 60}},
                {"id": 2, "name": "HDMI 2", "type": "HDMI", "connected": False},
                {"id": 3, "name": "12G-SDI", "type": "SDI", "connected": True,
                 "resolution": {"width": 1920, "height": 1080, "frameRate": 60}},
            ]

    def cabinet(self, cabinet_id: int) -> dict[str, Any] | None:
        return next((c for c in self.cabinets if c["id"] == cabinet_id), None)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    @property
    def state(self) -> CoexState:
        return self.server.state  # type: ignore[attr-defined]

    def log_message(self, *args: Any) -> None:  # noqa: D102 - silence the default logger
        if getattr(self.server, "verbose", False):
            super().log_message(*args)

    # --- plumbing -----------------------------------------------------------

    def _body(self) -> Any:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return None
        try:
            return json.loads(self.rfile.read(length) or b"null")
        except json.JSONDecodeError:
            return None

    def _send(self, code: int, message: str, data: Any = None, status: int = 200) -> None:
        payload = json.dumps({"code": code, "data": data, "message": message}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _ok(self, data: Any = None) -> None:
        self._send(0, "Success", data)

    def _not_supported(self) -> None:
        self._send(6, "NotSupport")

    def _invalid(self, why: str = "InvalidParam") -> None:
        self._send(1, why)

    def _http_404(self) -> None:
        """A bare HTTP 404, no JSON envelope -- what the real unit sent."""
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        path = self.path.split("?")[0].rstrip("/")
        self.state.requests.append(("GET", path, None))
        if path in self.state.missing_endpoints:
            return self._http_404()
        handler = GETS.get(path)
        if handler is None:
            return self._not_supported()
        self._ok(handler(self.state))

    def do_PUT(self) -> None:  # noqa: N802
        path = self.path.split("?")[0].rstrip("/")
        body = self._body()
        self.state.requests.append(("PUT", path, body))
        handler = PUTS.get(path)
        if handler is None:
            return self._not_supported()
        try:
            handler(self.state, body or {})
        except (KeyError, TypeError, ValueError) as exc:
            return self._invalid(str(exc) or "InvalidParam")
        self._ok()

    do_POST = do_PUT


# --- endpoint implementations ----------------------------------------------


def _device(state: CoexState) -> dict[str, Any]:
    return {
        "model": state.model,
        "name": state.device_name,
        "sn": state.serial,
        "firmwareVersion": state.firmware,
        "workingMode": 1,
    }


def _display_status(state: CoexState) -> dict[str, Any]:
    return {"value": state.display_mode}


def _set_display_mode(state: CoexState, body: dict[str, Any]) -> None:
    value = int(body["value"])
    if value not in (0, 1, 2):
        raise ValueError("display mode must be 0, 1 or 2")
    state.display_mode = value


def _set_cabinet_brightness(state: CoexState, body: dict[str, Any]) -> None:
    ratio = float(body["ratio"])
    if not 0.0 <= ratio <= 1.0:
        raise ValueError("ratio must be within 0..1")
    for cabinet_id in body["idList"]:
        cabinet = state.cabinet(int(cabinet_id))
        if cabinet is None:
            raise ValueError(f"no cabinet {cabinet_id}")
        cabinet["brightness"] = ratio


def _set_screen_brightness(state: CoexState, body: dict[str, Any]) -> None:
    ratio = float(body["ratio"])
    identifiers = set(body.get("idList") or [screen["screenID"] for screen in state.screens])
    for screen in state.screens:
        if screen["screenID"] in identifiers:
            screen["brightness"] = ratio
            for cabinet in state.cabinets:
                if cabinet["screenID"] == screen["screenID"]:
                    cabinet["brightness"] = ratio


def _select_input(state: CoexState, body: dict[str, Any]) -> None:
    value = int(body["value"])
    if not any(source["id"] == value for source in state.inputs):
        raise ValueError(f"no input {value}")
    state.current_input = value


def _apply_preset(state: CoexState, body: dict[str, Any]) -> None:
    identifier = body.get("id") or body.get("value")
    if not any(preset["id"] == identifier for preset in state.presets):
        raise ValueError(f"no preset {identifier}")
    state.current_preset = str(identifier)


# --- wire shapes, as OBSERVED on an MX40 Pro (2026-09-11) --------------------
#
# CoexState keeps a small internal model (cabinets with "online" and a numeric
# "temperature", inputs with "connected"); the builders below translate it into
# the shapes a real unit returned, field for field. The earlier guesses --
# {"cabinets": [...]} wrappers, "connected", "online", a numeric temperature --
# were wrong on every endpoint, and code written against them read a real
# controller as 288 cabinets with no temperature and then crashed. Tests run
# against these shapes so that cannot happen again unnoticed.

#: Input "type" codes, REASONED from one unit's names: "HDMI2.0 1" was 3,
#: "DP1.2" was 5, "12G-SDI" was 9, "OPT" was 225, "internal-source" was 224.
INPUT_TYPE_CODES = {"HDMI": 3, "DP": 5, "SDI": 9, "OPT": 225, "INTERNAL": 224}


def _sensor(value: float) -> dict[str, Any]:
    """How monitor/info reports every reading: a named, statused value."""
    return {"name": "", "nameEn": "", "status": 0, "value": value}


def _cabinet_wire(cabinet: dict[str, Any], index: int) -> dict[str, Any]:
    port = int(cabinet.get("port", 0))
    return {
        "id": cabinet["id"], "index": index, "outputCardID": 8,
        "outputID": 2048 + port, "outputIndex": port, "canvasID": 2048,
        "brightness": cabinet["brightness"],  # a 0..1 fraction, not 0..255
        "gamma": {"r": 2.8, "g": 2.8, "b": 2.8}, "gain": {"r": 43, "g": 43, "b": 43},
        "colorTemperature": 6500, "customGamma": False,
        "resolution": {"width": cabinet.get("width", 128), "height": cabinet.get("height", 128)},
        "size": {"width": 500, "height": 500},
        "rvCardName": "A5sPlus", "shortName": "", "cabType": "", "familyName": "",
        "manufacture": "", "ncpVersion": "", "pointSpacing": "",
        "moduleCount": 4, "moduleSize": {"moduleCol": 255, "moduleRow": 255, "overwrite": False},
        "power": 12, "voltage": 5, "weight": 5, "angle": 0, "bunchesIndex": 0,
        "indicatorLightState": True, "supportType": 0, "vsFreMax": 0,
        "cabinetFileParam": {"cabinetName": "", "cardModel": "", "issue": 0,
                             "manufactureName": "", "status": "", "version": ""},
        "rvCardInfo": {"chipEffectFlag": 0, "decodeIc": "", "driverChip": "",
                       "firmware": "SIM", "firmwareRemark": "", "grayScale": 14,
                       "maxGamma": 9856, "mcuFirmWare": "SIM", "mcuFirmWareRemark": "",
                       "moduleResolution": {"width": 64, "height": 64},
                       "refreshRate": 4620, "scanNumber": 16},
    }


def _input_wire(source: dict[str, Any]) -> dict[str, Any]:
    # A disconnected input still reports a resolution -- the EDID default --
    # on real hardware. Only sourceStatus tells the two apart, so the simulator
    # does not let a consumer get away with inferring signal from resolution.
    resolution = source.get("resolution") or {"width": 3840, "height": 2160, "frameRate": 60}
    return {
        "id": source["id"], "name": source["name"],
        "type": INPUT_TYPE_CODES.get(str(source.get("type", "")).upper(), 0),
        "port": 0, "cardId": 0, "groupId": source["id"], "order": 0, "usable": True,
        "sourceStatus": 1 if source.get("connected") else 0,
        "colorSpace": "RGB 4:4:4", "dynamicRange": "SDR", "bitDepth": 0,
        "actualResolution": {"width": resolution["width"], "height": resolution["height"]},
        "actualRefreshRate": resolution.get("frameRate", 60),
        "defaultEDID": {"isCustom": False, "refreshRate": 60,
                        "resolution": {"width": 3840, "height": 2160}},
    }


def _monitor_info(state: CoexState) -> dict[str, Any]:
    # A cabinet that is offline is simply absent: the real payload carries no
    # online flag, and absence is the only way it says so (REASONED).
    present = [c for c in state.cabinets if c.get("online", True)]
    return {
        # OBSERVED: the unit names itself here as "<model>_<digits>", and with
        # /api/v1/device absent this is the only identity the API offers.
        "name": f"{state.model}_000001",
        "runtime": 17160, "totalRuntime": 986580,
        "mainBoardTemperature": {"name": "Main_board Temperature",
                                 "nameEn": "Main_board Temperature", "status": 0, "value": 42},
        "mainBoardVoltage": {"name": "Main_board Voltage",
                             "nameEn": "Main_board Voltage", "status": 0, "value": 11.45},
        "fanInfos": [{"fanName": "chassis Fan", "fanNameEn": "chassis Fan",
                      "fanShowType": 0, "fanSpeed": 1293, "fanType": 0, "status": 0}],
        "backupStatus": {"errCode": 108, "status": 0},
        "cardMonitorInfo": None, "temperatureInfos": None, "voltageInfos": None,
        "controllerPortMonitorInfos": [{"controllerPortID": p, "status": 0} for p in range(2)],
        "outputStatus": [{"outputCardID": 8, "outputID": 2048 + p, "status": 0, "type": 0}
                         for p in range(2)],
        "powerMonitorInfos": [{"powerID": 0, "status": 0}],
        "screenSourceStatus": [{"inputCardID": 0, "portID": state.current_input, "status": 0}],
        "rvCardsRuntime": [{"cabinetID": c["id"], "rvCardID": c["id"], "runtime": 0,
                            "totalRuntime": 0} for c in present],
        "cabinets": [
            {
                "cabinetID": 0, "canvasID": 0, "index": i, "outPutID": 2048 + int(c.get("port", 0)),
                "outputCardID": 8, "rvCardID": 0,
                "temperature": _sensor(0), "voltage": _sensor(0),
                "rvCards": [{
                    "cabinetID": c["id"], "rvCardID": c["id"], "cabinetIndex": i,
                    "netPortIndex": 2048 + int(c.get("port", 0)),
                    "temperature": _sensor(c["temperature"]), "voltage": _sensor(3.8),
                    "humidity": _sensor(0),
                    "errorBit": [{"status": 1, "type": 0, "value": 65535},
                                 {"status": 0, "type": 1, "value": 0}],
                    "nextCabinetLinkStatus": {"linkStatus": True, "status": 0},
                    "backupStatus": {"mode": 0, "status": 0},
                    "moduleInfos": None, "runtime": 0, "totalRuntime": 0,
                }],
            }
            for i, c in enumerate(present)
        ],
    }


def _screens(state: CoexState) -> dict[str, Any]:
    group = "{00000000-0000-0000-0000-00000000g001}"
    return {
        "screens": [
            {"screenID": s["screenID"], "screenName": s.get("name", ""), "screenIndex": i,
             "workingMode": 1, "masterFrameRate": 60, "lowLatency": False,
             "canvases": [], "pageInfos": [], "layersInWorkingMode": [],
             "position": {}, "inputPort": {}, "layoutMode": 0, "outputMode": 0,
             "ordinal": i, "selectedPageID": 0, "screenGroupID": group, "createTime": ""}
            for i, s in enumerate(state.screens)
        ],
        "screenGroups": [{"isShow": False, "name": "Group 1", "ordinal": 0, "screenGroupID": group}],
    }


def _presets(state: CoexState) -> dict[str, Any]:
    return {
        "screenPresets": [
            {"screenID": s["screenID"], "presets": [
                {"name": p["name"], "presetUUID": p["id"], "sequenceNumber": p["index"],
                 "state": p["id"] == state.current_preset, "effectSwitch": 0,
                 "outputData": False, "processingData": False,
                 "screenData": True, "sourceData": True}
                for p in state.presets
            ]}
            for s in state.screens
        ]
    }


GETS = {
    "/api/v1/device": _device,
    "/api/v1/screen": _screens,
    "/api/v1/screen/cabinets": lambda state: [_cabinet_wire(c, i) for i, c in enumerate(state.cabinets)],
    "/api/v1/device/cabinet": lambda state: [_cabinet_wire(c, i) for i, c in enumerate(state.cabinets)],
    "/api/v1/device/input/sources": lambda state: [_input_wire(s) for s in state.inputs],
    "/api/v1/preset": _presets,
    "/api/v1/device/monitor/info": _monitor_info,
    "/api/v1/device/screen/displaymode": _display_status,
    "/api/v1/device/audio": lambda state: {"volume": 50, "mute": False},
    # OBSERVED on an MX40 Pro, post-show, GET only:
    "/api/v1/device/backup": lambda state: {"master": "", "backup": "", "masterName": "", "backupName": ""},
    "/api/v1/device/multifunc-card/detailinfo": lambda state: [],
    "/api/v1/device/hw/mode": lambda state: {"mode": 3},  # value observed; meaning UNKNOWN
    "/api/v1/device/snmpstate": lambda state: {"state": False},  # OBSERVED key; false on the unit
}

PUTS = {
    "/api/v1/device/screen/displaymode": _set_display_mode,
    "/api/v1/device/cabinet/brightness": _set_cabinet_brightness,
    "/api/v1//device/cabinet/brightness": _set_cabinet_brightness,  # as printed in the manual
    "/api/v1/screen/brightness": _set_screen_brightness,
    "/api/v1/device/screen/input": _select_input,
    "/api/v1/preset/current/update": _apply_preset,
    "/api/v1/device/currentpreset": _apply_preset,
}


class SimulatedCoexController(ThreadingHTTPServer):
    """HTTP server answering the COEX JSON API."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self, host: str = "127.0.0.1", port: int = DEFAULT_PORT, state: CoexState | None = None
    ) -> None:
        super().__init__((host, port), _Handler)
        self.state = state or CoexState()
        self.verbose = False

    @property
    def address(self) -> tuple[str, int]:
        return self.server_address[0], self.server_address[1]

    def serve_in_thread(self) -> threading.Thread:
        thread = threading.Thread(target=self.serve_forever, daemon=True)
        thread.start()
        return thread


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a fake COEX controller")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--model", default="MX40 Pro")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    server = SimulatedCoexController(args.host, args.port, CoexState(model=args.model))
    server.verbose = args.verbose
    host, port = server.address
    print(f"simulating {server.state.model} HTTP API on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
