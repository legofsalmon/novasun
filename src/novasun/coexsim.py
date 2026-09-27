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

The default reproduces the MX40 Pro read on 2026-09-11. ``CoexState(model="MX30")``
selects instead what an MX30 (hwVersion V1.5.1) returned on 2026-09-26 --
different absent-endpoint semantics, a fuller monitor/info, a readable wall
geometry, and the two writes later sent to it: ``snmpstate``, which honours
``{"state": b}`` and answered Success to ``{"value": true}`` without changing
anything (the simulator treats every other body that way), and
``hw/colorBeacon``, which answers an empty 200. A capture of NovaStar VMP
opening the same unit that evening added four more: identity at
``/api/v1/device/hw`` (with a ``randomPassword`` field every consumer must
drop), display state per canvas at ``/api/v1/screen/output/display/state``
(which reads 2 through a front-panel freeze), the ``hw/lock`` VMP takes, and
the ``hw/systemtime`` body VMP sends. The unit's UDP announcement can be
emitted too, off by default. ``CoexState.outputs_unplugged`` reproduces the
same unit with every output data line pulled and the power left on, as an
attended session watched it that evening: the connected-cabinet counts go to
zero while ``monitor/info`` goes on describing a healthy wall -- the false
all-clear a consumer has to be tested against. See the MX30-like blocks
below. One unit of each was read, so where the two differ the simulator does
not say whether model or firmware is the cause.

    python -m novasun.coexsim --port 8001
    python -m novasun.coexsim --port 8001 --model MX30
    python -m novasun.coexsim --port 8001 --model MX30 --announce 127.0.0.1
    python -m novasun.coexsim --port 8001 --model MX30 --outputs-unplugged
"""

from __future__ import annotations

import argparse
import json
import socket
import threading
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

DEFAULT_PORT = 8001

#: The two firmware behaviours the simulator reproduces, chosen by
#: :attr:`CoexState.model`: the MX40 Pro read on 2026-09-11 (the default) and
#: the MX30 read on 2026-09-26.
MX40_LIKE = "mx40-like"
MX30_LIKE = "mx30-like"

#: Documented GET endpoints each firmware lacked -- both OBSERVED, one unit
#: each. How the absence is answered differs; see ``CoexState.absent_style``.
MX40_ABSENT_GETS = frozenset({
    "/api/v1/device",
    "/api/v1/device/audio",
    "/api/v1/device/screen/displaymode",
})
MX30_ABSENT_GETS = frozenset({
    # OBSERVED on an MX30, 2026-09-26, with curl -i: HTTP 200, Content-Length
    # 0, no Content-Type, no body.
    "/api/v1/device",
    "/api/v1/device/screen/displaymode",
    # Came back as {} through the read-only client in the same ~2 ms. That
    # client cannot tell an empty body from a real {"code":0,"data":{}}
    # envelope and no raw envelope was captured, so absent-or-empty is
    # UNKNOWN for these three; they are answered the same way here because a
    # client sees no difference.
    "/api/v1/screen/cabinets",
    "/api/v1/screen/properties",
    "/api/v1/screen/displayeffect",
})


#: CoexState's serial and firmware defaults, which describe the MX40-like
#: unit; the MX30-like profile replaces them when they are left as they are.
_MX40_SERIAL = "SIM-MX40-0001"
_MX40_FIRMWARE = "1.5.0"


_UNPLUG_MX40 = ("outputs_unplugged is modelled on the MX30-like profile only; what an "
                "MX40 Pro reports with its outputs unplugged is UNKNOWN")


def firmware_profile(model: str) -> str:
    """Which unit's observed behaviour a model name selects."""
    return MX30_LIKE if model.strip().lower() == "mx30" else MX40_LIKE


@dataclass
class CoexState:
    """Everything the fake controller remembers."""

    model: str = "MX40 Pro"
    device_name: str = "Simulated MX40 Pro"
    #: When set, ``monitor/info`` reports this as ``name`` instead of the
    #: factory-style ``"<model>_000001"``. Models a controller whose operator
    #: has renamed it: on an MX30 (OBSERVED 2026-09-26) the field was a plain
    #: word carrying no model, so nothing downstream may derive a model from it.
    custom_name: str | None = None
    serial: str = _MX40_SERIAL
    firmware: str = _MX40_FIRMWARE  # the MX30-like profile serves it as /device/hw hwVersion
    display_mode: int = 0  # 0 normal, 1 blackout, 2 freeze
    current_preset: str | None = None
    current_input: int | None = None  # filled per firmware profile in __post_init__
    screens: list[dict[str, Any]] = field(default_factory=list)
    cabinets: list[dict[str, Any]] = field(default_factory=list)
    presets: list[dict[str, Any]] = field(default_factory=list)
    inputs: list[dict[str, Any]] = field(default_factory=list)
    requests: list[tuple[str, str, Any]] = field(default_factory=list)
    #: Documented GET endpoints this firmware lacks, and how it says so; both
    #: are filled per firmware profile when left ``None``. The MX40 Pro default
    #: (OBSERVED 2026-09-11) withholds ``/api/v1/device``,
    #: ``/api/v1/device/audio`` and the GET of
    #: ``/api/v1/device/screen/displaymode`` with a bare HTTP 404. The
    #: MX30-like profile (OBSERVED 2026-09-26) withholds
    #: :data:`MX30_ABSENT_GETS` -- and any unknown path -- with an empty HTTP
    #: 200 carrying no Content-Type and no envelope, so code that takes
    #: "answered" as "exists" fails here rather than on site. A test that wants
    #: one served removes it from the set. Only GETs consult either. The
    #: read-only pass sent the MX30 GETs only; a later session the same day,
    #: with VMP closed, sent it two hw/colorBeacon PUTs and five snmpstate PUTs,
    #: and VMP's own open, captured that evening, sent hw/systemtime, hw/lock
    #: and two device/picture PUTs. PUTS_MX30 models all but device/picture.
    #: The PUT of displaymode was never sent to either unit, and whether it
    #: exists is UNKNOWN, so the simulator still accepts it on both profiles.
    missing_endpoints: set[str] | None = None
    absent_style: str | None = None  # "404" or "empty-200"
    #: What ``GET /api/v1/device/snmpstate`` reports on the MX30-like profile,
    #: set only by a PUT carrying ``{"state": <bool>}`` (OBSERVED: that body
    #: flips the unit's state and the GET reads it back). Off by default, as
    #: the unit was. The MX40-like default ignores it: its GET is the constant
    #: ``False`` that unit returned, and its PUT behaviour is UNKNOWN.
    snmp_enabled: bool = False
    #: The MX30-like unit's MAC, served by ``/api/v1/device/hw`` and carried
    #: by its UDP announcement -- the same value in both (OBSERVED). Filled
    #: per profile; the MX40-like default serves neither.
    mac: str | None = None
    #: Who holds ``/api/v1/device/hw/lock`` on the MX30-like profile: the
    #: caller's IP once a PUT naming ``appids`` has taken it, else ``None``.
    #: Nothing over HTTP releases it -- VMP sent no unlock, and the unit read
    #: unlocked again only after VMP had quit, by websocket close or timeout
    #: (mechanism UNKNOWN) -- so a test models the release by clearing this.
    lock_ip: str | None = None
    lock_appids: list[str] = field(default_factory=list)
    #: The last ``PUT /api/v1/device/hw/systemtime`` body of the shape VMP
    #: sent (MX30-like profile). Recorded, never applied: no clock is modelled.
    system_time: dict[str, Any] | None = None
    #: Every output data line unplugged, the controller left powered -- the
    #: MX30-like profile only; set it with :meth:`unplug_outputs` or at
    #: construction. OBSERVED on the MX30 (hwVersion V1.5.1), attended,
    #: 2026-09-26, lines pulled one at a time 18:59:52Z-19:02:29Z, watched
    #: read-only (docs/read-only-monitoring.md §4, "Unplugged outputs, and
    #: power-off"), and reproduced as read once every line was out:
    #:
    #: * ``/api/v1/device/cabinet`` answers ``[]`` and
    #:   ``/api/v1/screen/cabinet/count`` ``CabinetCount`` 0: both count the
    #:   cabinets connected *now*, not the configured ones;
    #: * ``monitor/info`` ``outputStatus[].linkStatus`` is false on every
    #:   output, and each output whose link dropped reads ``status`` 2 (meaning
    #:   UNKNOWN); the other entries are left as the connected read had them,
    #:   because whether their status moved was not recorded (UNKNOWN);
    #: * ``monitor/info`` ``rvCardsRuntime`` is ``[]`` (72 entries before);
    #: * **and nothing else in ``monitor/info`` moves** -- the false
    #:   all-clear: every cabinet and card stays listed, every
    #:   ``nextCabinetLinkStatus.linkStatus`` stays true, and the temperatures,
    #:   voltages and ``errorBit`` read what they last read, for the ~8.5
    #:   minutes until power-off (OBSERVED; that they are last-known values
    #:   rather than live ones is REASONED). Change a cabinet's reading here
    #:   and ``monitor/info`` will show it, which the unit could not have done
    #:   with no card connected: set the readings before unplugging;
    #: * ``/api/v1/screen/output/display/state`` keeps reading the display
    #:   mode (0 at every 1 Hz poll through the unplugging, OBSERVED), and the
    #:   UDP announcement carries on (OBSERVED every 3 s throughout).
    #:
    #: Not modelled: ``/api/v1/screen`` is served unchanged, though it was not
    #: re-read with the lines out and the websocket pushed
    #: ``screenCabinetSizeChange`` at each stage (UNKNOWN whether its geometry
    #: moved); the intermediate stages (one line out, some lines out), which
    #: were watched only through monitor/info and the websocket; the
    #: websocket itself; and plugging back in, which was never done -- setting
    #: this back to False restores the connected shapes as a simulator
    #: convention, not an observation. Whether an MX40 Pro does any of this
    #: is UNKNOWN (it was never watched with a line out), so the MX40-like
    #: default refuses the setting.
    outputs_unplugged: bool = False

    def __post_init__(self) -> None:
        mx30 = self.mx30_like
        if self.outputs_unplugged and not mx30:
            raise ValueError(_UNPLUG_MX40)
        if self.absent_style is None:
            self.absent_style = "empty-200" if mx30 else "404"
        if self.missing_endpoints is None:
            self.missing_endpoints = set(MX30_ABSENT_GETS if mx30 else MX40_ABSENT_GETS)
        if mx30:
            _mx30_defaults(self)
            return
        if self.current_input is None:
            self.current_input = 1
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

    def unplug_outputs(self) -> None:
        """Pull every output data line, leaving the controller powered.

        See :attr:`outputs_unplugged` for what that does and does not change.
        MX30-like profile only: an MX40 Pro was never watched with a line out.
        """
        if not self.mx30_like:
            raise ValueError(_UNPLUG_MX40)
        self.outputs_unplugged = True

    @property
    def profile(self) -> str:
        return firmware_profile(self.model)

    @property
    def mx30_like(self) -> bool:
        return self.profile == MX30_LIKE


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
        # The MX30 sent compact JSON, keys in code/data/message order (OBSERVED:
        # display/state's 140 B and hw/lock's 58 B bodies are exactly that
        # encoding). The MX40 Pro's bytes were not retained, so the default
        # keeps json.dumps's spacing.
        separators = (",", ":") if self.state.mx30_like else None
        payload = json.dumps({"code": code, "data": data, "message": message},
                             separators=separators).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self._common_headers()
        self.end_headers()
        self.wfile.write(payload)

    def _ok(self, data: Any = None) -> None:
        self._send(0, "Success", data)

    def _not_supported(self) -> None:
        self._send(6, "NotSupport")

    def _invalid(self, why: str = "InvalidParam") -> None:
        self._send(1, why)

    def _http_404(self) -> None:
        """A bare HTTP 404, no JSON envelope -- what the MX40 Pro sent."""
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self._common_headers()
        self.end_headers()

    def _empty_200(self) -> None:
        """HTTP 200 with Content-Length 0, no Content-Type and no envelope.

        OBSERVED on an MX30 (v1.5.1), 2026-09-26, for documented endpoints the
        firmware lacks and for made-up paths alike, in the same ~2 ms as a
        real answer. Nothing but the missing body tells a reader the endpoint
        is not there; ``CoexClient.request`` returns ``{}`` for it.
        """
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self._common_headers()
        self.end_headers()

    def _absent(self) -> None:
        if self.state.absent_style == "empty-200":
            return self._empty_200()
        self._http_404()

    def _common_headers(self) -> None:
        # OBSERVED on an MX30, 2026-09-26, on every response, empty and JSON
        # alike. Whether the MX40 Pro sent them is UNKNOWN (its raw headers
        # were not retained), so the default sends none. X-Request-Id is a
        # fresh value per request here; on the unit it was one global counter
        # with a constant suffix (OBSERVED in the VMP capture: 222 consecutive
        # values), which is not modelled. Date is already sent by send_response.
        if self.state.mx30_like:
            self.send_header("X-Request-Id", str(uuid.uuid4()))
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Credentials", "true")

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        path = self.path.split("?")[0].rstrip("/")
        self.state.requests.append(("GET", path, None))
        if path in (self.state.missing_endpoints or ()):
            return self._absent()
        handler = (GETS_MX30 if self.state.mx30_like else GETS).get(path)
        if handler is None:
            # The MX40-like default keeps the NotSupport envelope: a made-up
            # path was never tried on that unit. The MX30 answered one with the
            # same empty 200 as an absent documented endpoint (OBSERVED).
            return self._absent() if self.state.mx30_like else self._not_supported()
        self._ok(handler(self.state))

    def do_PUT(self) -> None:  # noqa: N802
        path = self.path.split("?")[0].rstrip("/")
        body = self._body()
        self.state.requests.append(("PUT", path, body))
        if self.state.mx30_like and path in PUTS_MX30:
            return PUTS_MX30[path](self, body)
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
    # A cabinet that is offline is simply absent here. That was REASONED and
    # is not what an MX30 does: with every output line unplugged its
    # monitor/info kept all 72 cabinets, links true and temperatures reading,
    # until power-off ~8.5 minutes later (OBSERVED, 2026-09-26), while
    # screen/cabinet/count and device/cabinet went to 0. The MX30-like profile
    # models that with CoexState.outputs_unplugged; what an MX40 Pro does is
    # UNKNOWN, so this default does not.
    present = [c for c in state.cabinets if c.get("online", True)]
    return {
        # A name, not a model: "<model>_<digits>" on the MX40 Pro read in
        # 2026-09, a plain word with no model in it on an MX30 (2026-09-26;
        # both OBSERVED, one unit each). The API documents a custom-name
        # setter, so the field is an operator-settable label whose
        # "<model>_<digits>" form is a factory default (REASONED). With
        # /api/v1/device absent it is the only identity this default serves:
        # /api/v1/device/hw was never requested on the MX40 Pro (UNKNOWN
        # there), while the MX30 carries model and version in it (_mx30_hw).
        "name": state.custom_name or f"{state.model}_000001",
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


# --- MX30-like firmware profile, as OBSERVED on an MX30, 2026-09-26 ---------
#
# One unit, hwVersion V1.5.1, read only after the show -- then, with VMP
# closed, sent the snmpstate and colorBeacon writes in PUTS_MX30. That pass
# found no model or firmware string over HTTP only because it never requested
# /api/v1/device/hw; VMP's open did that evening, and it carries both (see the
# next block, which also covers display/state, hw/lock and hw/systemtime).
# Selected with ``CoexState(model="MX30")``; the MX40-like shapes above stay
# the default. Where the two units differ the simulator does not say whether
# model or firmware is the cause -- one of each was read. Every value below is
# synthetic; the key spellings, nesting and the patterns the comments call out
# are what the unit returned. The meanings of status and type codes are UNKNOWN
# and deliberately left unstated.

MX30_LIKE_LABEL = "simlab"
"""monitor/info's ``name`` on the MX30-like unit: a plain word.

OBSERVED: a single alphabetic word with no model in it, equal to no other
string in any payload that pass read. ``/api/v1/device/hw``, read later that
day, carries it too as ``customName`` (REASONED: the capture's masking gave
both strings one token); the simulator serves the same label in both. Whether
an operator set it is REASONED (the API has a custom-name setter), not
established. The real word is show data and is not
this one; the point is that nothing downstream may read a model out of it.
"""

MX30_LIKE_ID_BASE = 2**48  # synthetic; the unit's 64-bit cabinet ids are show data
MX30_LIKE_PORTS = (0, 2, 4)  # outputID 2048, 2050 and 2052 carried the cabinets
MX30_LIKE_CHAIN = 24  # cabinets per port, chain positions 0..23
MX30_LIKE_CABINET = 128  # every cabinet was 128x128
MX30_LIKE_SCREEN_ID = "{00000000-0000-0000-0000-000000000030}"
MX30_LIKE_GROUP_ID = "{00000000-0000-0000-0000-00000000g030}"
#: 0x1412. OBSERVED as the MX30's own ``modelID`` in ``/api/v1/device/hw``,
#: beside ``name`` "MX30" (and repeated by firmware/list and backcard/info).
#: That the other occurrences -- inputPort.ModelId, canvases[].outputCardModeId
#: and every device/input modelId -- name the same thing is REASONED.
MX30_LIKE_MODEL_ID = 5138
MX30_LIKE_CARD_RUNTIME = 30_000_000  # rvCardsRuntime[].runtime: one value on every card, static across 7 minutes; meaning UNKNOWN
#: errorBit[0].value: one value per output port, none 65535 (the MX40 record's
#: constant); identical across snapshots. Meaning UNKNOWN.
MX30_LIKE_ERROR_BIT = {2048: 190, 2050: 189, 2052: 187}


def _mx30_default_cabinets(screen_id: str) -> list[dict[str, Any]]:
    """72 cabinets on three ports, 24 per chain, a 12x6 grid of 128x128.

    OBSERVED layout (from ``/api/v1/screen``, the only endpoint with
    positions): each port's chain runs a serpentine over two rows -- chain
    position 0 at the right-hand end of the lower row, back along the upper
    row -- and the ports stack from the bottom of the canvas upwards.
    """
    cabinets = []
    for ordinal, port in enumerate(MX30_LIKE_PORTS):
        lower = (5 - 2 * ordinal) * MX30_LIKE_CABINET
        for index in range(MX30_LIKE_CHAIN):
            n = ordinal * MX30_LIKE_CHAIN + index
            column = 11 - index if index < 12 else index - 12
            cabinets.append({
                "id": MX30_LIKE_ID_BASE + n, "screenID": screen_id,
                "port": port, "index": index,
                "positionX": column * MX30_LIKE_CABINET,
                "positionY": lower if index < 12 else lower - MX30_LIKE_CABINET,
                "width": MX30_LIKE_CABINET, "height": MX30_LIKE_CABINET,
                "brightness": 0.5,
                "temperature": 41 + n % 6, "voltage": round(4.1 + 0.1 * (n % 4), 1),
                "online": True,
            })
    return cabinets


def _mx30_default_inputs() -> list[dict[str, Any]]:
    """The six inputs, with the (id, type, groupId, cardId) tuples OBSERVED.

    ``type`` is the numeric wire code; the names are the firmware's port names.
    REASONED from those names, one unit: 2 = HDMI 1.4, 3 = HDMI 2.0, 4 = DP 1.1,
    7 = 3G-SDI; REASONED: 224 with cardId 101 is the internal generator. Note
    ``groupId`` is not ``id`` on any connector, and id 768 is a different
    connector here from the MX40-like shape's -- a consumer must key type on
    ``type``, never on ``id``. ``connected`` inputs report their live
    resolution; the rest echo their EDID default (OBSERVED, 4/4).
    """
    return [
        {"id": 3, "name": "3G-SDI 1", "type": 7, "groupId": 57, "cardId": 0, "order": 4,
         "connected": False, "edid": (1920, 1080, 60)},
        {"id": 4, "name": "3G-SDI 2", "type": 7, "groupId": 58, "cardId": 0, "order": 5,
         "connected": False, "edid": (1920, 1080, 60)},
        {"id": 256, "name": "DP1.1", "type": 4, "groupId": 32, "cardId": 0, "order": 3,
         "connected": False, "edid": (3840, 1080, 60)},
        {"id": 768, "name": "HDMI1.4 2", "type": 2, "groupId": 18, "cardId": 0, "order": 2,
         "connected": False, "edid": (3840, 1080, 60), "hdrList": [255, 0, 1, 2]},
        {"id": 512, "name": "HDMI2.0 1", "type": 3, "groupId": 25, "cardId": 0, "order": 1,
         "connected": True, "resolution": {"width": 1920, "height": 1080, "frameRate": 50},
         "edid": (3840, 2160, 60), "hdrList": [255, 0, 1, 2],
         "colorSpace": "YCbCr 4:4:4", "gamut": "Rec.709"},
        {"id": 25856, "name": "internal-source", "type": 224, "groupId": 224, "cardId": 101,
         "order": 0, "connected": True,
         "resolution": {"width": 1280, "height": 768, "frameRate": 50},
         "edid": (3840, 1080, 60), "colorSpace": "YCbCr 4:4:4", "gamut": "Rec.709"},
    ]


def _mx30_defaults(state: CoexState) -> None:
    """Fill a fresh MX30-like state the way ``__post_init__`` fills the default."""
    if state.custom_name is None:
        state.custom_name = MX30_LIKE_LABEL
    if state.serial == _MX40_SERIAL:
        state.serial = MX30_LIKE_SERIAL
    if state.firmware == _MX40_FIRMWARE:
        state.firmware = MX30_LIKE_HW_VERSION
    if state.mac is None:
        state.mac = MX30_LIKE_MAC
    if not state.screens:
        state.screens = [
            {"screenID": MX30_LIKE_SCREEN_ID, "name": "Wall", "width": 1536, "height": 768,
             "brightness": 0.5, "gamma": 2.8, "colorTemperature": 6500}
        ]
    if not state.cabinets:
        state.cabinets = _mx30_default_cabinets(state.screens[0]["screenID"])
    if not state.presets:
        # Two presets, neither active: the same per-preset keys as the MX40-like
        # shape (OBSERVED identical), so _presets serves both.
        state.presets = [
            {"id": "preset-1", "name": "Show", "index": 1},
            {"id": "preset-2", "name": "Rehearsal", "index": 2},
        ]
    if not state.inputs:
        state.inputs = _mx30_default_inputs()
    if state.current_input is None:
        state.current_input = 512  # the input the working-mode-1 layer was showing


def _mx30_actual(source: dict[str, Any]) -> dict[str, Any]:
    """What an input reports as its signal: live values, or its EDID default."""
    width, height, rate = source.get("edid", (3840, 2160, 60))
    if source.get("connected") and source.get("resolution"):
        return dict(source["resolution"])
    return {"width": width, "height": height, "frameRate": rate}


def _mx30_metadata() -> dict[str, int]:
    """The twelve zeroed ``metaData`` fields (spellings as the unit sent them)."""
    return {"checksum": 0, "infoFramLength": 0, "infoFrameType": 0, "infoFrameVersion": 0,
            "maxContentLight": 0, "maxFrameAvgLight": 0, "maxLight": 0,
            "maxMasterDisplayLight": 0, "minMasterDisplayLight": 0, "sourceTye": 0,
            "whitePointX": 0, "whitePointY": 0}


def _mx30_cabinet_wire(cabinet: dict[str, Any]) -> dict[str, Any]:
    # OBSERVED on an MX30, 2026-09-26: 34 keys, all 72 identical apart from
    # id, index, outputID/outputIndex and voltage. ``index`` is the chain
    # position (= monitor/info index and rvCards[].cabinetIndex) and
    # ``outputIndex`` the port ordinal, so (outputID, index) is a stable
    # address. Every descriptive field is unset -- size 0x0, power 0, weight 0,
    # version strings "0.0.0.0", status "unknown" -- so a pane cannot size a
    # cabinet from here. ``voltage`` read 5 on 69 cabinets and an unexplained
    # other value on the first cabinet of each chain; the receiving card's
    # own reading lives in monitor/info. Not modelled: it is 5 throughout.
    # The two remark fields are "" here: on the unit they were show data.
    port = int(cabinet.get("port", 0))
    return {
        "id": cabinet["id"], "index": int(cabinet.get("index", 0)), "outputCardID": 8,
        "outputID": 2048 + port, "outputIndex": port, "canvasID": 2048,
        "brightness": cabinet["brightness"],
        "gamma": {"r": 2.8, "g": 2.8, "b": 2.8}, "gain": {"r": 43, "g": 43, "b": 43},
        "colorTemperature": 6500, "customGamma": False,
        "resolution": {"width": cabinet.get("width", 128), "height": cabinet.get("height", 128)},
        "size": {"width": 0, "height": 0},
        "rvCardName": "A5sPlus", "shortName": "", "cabType": "", "familyName": "",
        "manufacture": "", "ncpVersion": "0.0.0.0", "ncpFileName": "", "clientOrderNo": "",
        "pointSpacing": "0.000",
        "moduleCount": 4, "moduleSize": {"moduleCol": 255, "moduleRow": 255, "overwrite": False},
        "power": 0, "voltage": 5, "weight": 0, "angle": 0, "bunchesIndex": 0,
        "indicatorLightState": True, "supportType": 0, "vsFreMax": 0,
        "cabinetFileParam": {"cabinetName": "", "cardModel": "", "issue": 0,
                             "manufactureName": "", "status": "unknown", "version": "0.0.0.0"},
        "rvCardInfo": {"chipEffectFlag": 0, "decodeIc": "", "driverChip": "",
                       "firmware": "SIM", "firmwareRemark": "", "grayScale": 14,
                       "maxGamma": 9856, "mcuFirmWare": "SIM", "mcuFirmWareRemark": "",
                       "moduleResolution": {"width": 64, "height": 64},
                       "refreshRate": 3850, "scanNumber": 16},
    }


def _mx30_input_wire(source: dict[str, Any], channel: int) -> dict[str, Any]:
    # OBSERVED on an MX30, 2026-09-26: 50 keys per input. The capability flags
    # varied by port type as reproduced below; the two long capability strings
    # are elided to "". hdrList was a list on the HDMI inputs and null on the
    # rest; fiberPortLinkStatus null on all six.
    kind = int(source["type"])
    connected = bool(source.get("connected"))
    width, height, rate = source.get("edid", (3840, 2160, 60))
    actual = _mx30_actual(source)
    return {
        "id": source["id"], "name": source["name"], "type": kind,
        "port": 0, "cardId": int(source.get("cardId", 0)), "groupId": int(source["groupId"]),
        "order": int(source.get("order", 0)), "usable": True,
        "sourceStatus": 1 if connected else 0, "sourceChannel": channel,
        "scanMode": 0, "inPhase": False, "ip": "", "range": 1 if kind == 224 else 0,
        "colorSpace": source.get("colorSpace", "RGB 4:4:4"), "dynamicRange": "SDR",
        "gamut": source.get("gamut", "") if connected else "",
        "bitDepth": 1 if connected else 0,
        "hdrList": source.get("hdrList"),
        "supportColorSpace": [0] if kind == 224 else [0, 1, 2, 3, 255] if kind == 3 else [0, 1, 2, 255],
        "supportFrameRate": "", "supportResolution": "", "supportCapacities": None,
        "actualResolution": {"width": actual["width"], "height": actual["height"]},
        "actualRefreshRate": actual.get("frameRate", 60),
        "defaultEDID": {"isCustom": False, "refreshRate": rate,
                        "resolution": {"width": width, "height": height}},
        "isEdidCustom": False, "fiberPortLinkStatus": None, "monitorSlotId": 0,
        "maxwidth": 8192 if kind == 224 else 4096 if kind == 7 else 4092,
        "maxheight": 8192 if kind == 224 else 4096 if kind == 7 else 4095,
        "minwidth": 800, "minheight": 600,
        "step": 4, "stepHeight": 1, "yuv420StepWidth": 8, "yuv420StepHeight": 2,
        "maxCapacity": 0, "minCapacity": 0,
        "isSupportCapacities": False, "isSupportColorAdjust": True,
        "isSupportEDID": kind != 7, "isSupportHDR": kind == 3, "isSupportHDRParams": True,
        "isSupportIPAndPort": False, "isSupportInputOverride": True,
        "isSupportMetaData": kind == 3, "isSupportPQMaxCllChecked": True,
        "isSupportSPDIF": kind in (2, 3, 4),
        "metaData": _mx30_metadata(),
    }


def _mx30_output_status(
    linked: set[int], dropped: frozenset[int] = frozenset()
) -> list[dict[str, Any]]:
    # OBSERVED: 33 entries -- outputID 2048-2057 type 0, 2058-2077 type 5,
    # 2078-2079 type 1, and one all-zero type-3 entry; outputCardID 8 on all
    # but the last. linkStatus was true on 2048-2052 inclusive, which included
    # two ports carrying no cabinets (why is UNKNOWN); status was 0 everywhere
    # except one unlinked type-0 port reading 2. What the types and statuses
    # mean is UNKNOWN; a consumer that alarms on any non-zero status alarms
    # here, as it would have on the unit. ``dropped`` are outputs whose link
    # went down with the unit powered: each went linkStatus false and read
    # status 2 (OBSERVED, every line unplugged, 2026-09-26).
    entries = []
    for output_id in range(2048, 2058):
        entries.append({"linkStatus": output_id in linked, "outputCardID": 8,
                        "outputID": output_id,
                        "status": 2 if output_id == 2053 or output_id in dropped else 0, "type": 0})
    for output_id in range(2058, 2078):
        entries.append({"linkStatus": False, "outputCardID": 8, "outputID": output_id,
                        "status": 0, "type": 5})
    for output_id in range(2078, 2080):
        entries.append({"linkStatus": False, "outputCardID": 8, "outputID": output_id,
                        "status": 0, "type": 1})
    entries.append({"linkStatus": False, "outputCardID": 0, "outputID": 0, "status": 0, "type": 3})
    return entries


def _mx30_monitor_info(state: CoexState) -> dict[str, Any]:
    # OBSERVED on an MX30, 2026-09-26. Against the MX40 record: cabinetID and
    # rvCardID populated (= rvCards[0].cabinetID; the MX40's were 0); no
    # top-level temperature/voltage on cabinets[] but a nested ``cabinet``
    # object whose ``voltage`` is a live mirror of the card's (a keyed diff
    # that reads both double-counts) and whose other readings are 0/null;
    # rvCards[] gain phyTemperature and signalInterruptCount -- the latter a
    # bare int, the one reading that is not a {name, nameEn, status, value}
    # object; three fans; screenSourceStatus gains groupID and linkStatus;
    # accessoryMonitorInfo, imbLinkStatus, inputFiberStatus and backupStatus's
    # min/maxNormalValue appear. Per-card runtimes live in rvCardsRuntime[]
    # (totalRuntime a multiple of 60 and advancing; runtime one static value on
    # every card, meaning UNKNOWN) while the rvCards[] runtime fields are 0 --
    # as on the MX40. Only cabinets[] and screenSourceStatus[] reorder between
    # reads; the simulator keeps them in order.
    #
    # With CoexState.outputs_unplugged (OBSERVED, every output line pulled,
    # unit powered): cabinets[] and every reading in it are served exactly as
    # before -- the false all-clear, a stale list with every link still true --
    # while every output's link goes false (status 2 on the ones that dropped)
    # and rvCardsRuntime empties. Nothing else here was seen to change.
    present = [c for c in state.cabinets if c.get("online", True)]
    ports = sorted({2048 + int(c.get("port", 0)) for c in state.cabinets})
    linked = set(range(ports[0], ports[-1] + 1)) if ports else set()
    dropped: frozenset[int] = frozenset()
    if state.outputs_unplugged:
        linked, dropped = set(), frozenset(linked)
    cabinets = []
    for c in present:
        output_id = 2048 + int(c.get("port", 0))
        index = int(c.get("index", 0))
        voltage = _sensor(c.get("voltage", 4.2))
        cabinets.append({
            "cabinet": {"cabinetID": 0, "humidity": _sensor(0), "power": None,
                        "smoke": _sensor(0), "temperature": _sensor(0), "voltage": dict(voltage)},
            "cabinetID": c["id"], "canvasID": 2048, "index": index, "outPutID": output_id,
            "outputCardID": 8, "rvCardID": c["id"],
            "rvCards": [{
                "backupStatus": {"mode": 0, "status": 0},
                "cabinetID": c["id"], "cabinetIndex": index,
                "errorBit": [{"status": 1, "type": 0, "value": MX30_LIKE_ERROR_BIT.get(output_id, 190)},
                             {"status": 0, "type": 1, "value": 0}],
                "humidity": _sensor(0), "moduleInfos": None, "netPortIndex": output_id,
                "nextCabinetLinkStatus": {"linkStatus": True, "status": 0},
                "phyTemperature": {"phy1": _sensor(0), "phy2": _sensor(0)},
                "runtime": 0, "rvCardID": c["id"], "signalInterruptCount": 0,
                "temperature": _sensor(c["temperature"]), "totalRuntime": 0,
                "voltage": voltage,
            }],
        })
    return {
        "name": state.custom_name or MX30_LIKE_LABEL,
        "runtime": 21000, "totalRuntime": 2000040,
        "mainBoardTemperature": {"name": "Main_board Temperature",
                                 "nameEn": "Main_board Temperature", "status": 0, "value": 32},
        "mainBoardVoltage": {"name": "Main_board Voltage",
                             "nameEn": "Main_board Voltage", "status": 0, "value": 11.56},
        "fanInfos": [
            {"fanName": "Chassis Fan 1", "fanNameEn": "Chassis Fan 1", "fanShowType": 0,
             "fanSpeed": 3780, "fanType": 1, "status": 0},
            {"fanName": "FPGA Fan", "fanNameEn": "FPGA Fan", "fanShowType": 0,
             "fanSpeed": 2790, "fanType": 15, "status": 0},
            {"fanName": "Chassis Fan 2", "fanNameEn": "Chassis Fan 2", "fanShowType": 0,
             "fanSpeed": 3760, "fanType": 2, "status": 0},
        ],
        "backupStatus": {"errCode": 108, "maxNormalValue": 0, "minNormalValue": 0, "status": 0},
        "accessoryMonitorInfo": {"multifunctionCardStatus": [], "transmitterStatus": []},
        "imbLinkStatus": {"linkStatus": False, "status": 0},
        "inputFiberStatus": None,
        "cardMonitorInfo": None, "temperatureInfos": None, "voltageInfos": None,
        "controllerPortMonitorInfos": [{"controllerPortID": 0, "status": 0},
                                       {"controllerPortID": 1, "status": 2}],
        "outputStatus": _mx30_output_status(linked, dropped),
        "powerMonitorInfos": [{"powerID": 0, "status": 0}],
        "screenSourceStatus": [
            {"groupID": int(s["groupId"]), "inputCardID": 0,
             "linkStatus": bool(s.get("connected")), "portID": s["id"], "status": 0}
            for s in state.inputs
        ],
        "rvCardsRuntime": [] if state.outputs_unplugged else [
            {"cabinetID": c["id"], "runtime": MX30_LIKE_CARD_RUNTIME, "rvCardID": c["id"],
             "totalRuntime": 3999960 + 60 * n}
            for n, c in enumerate(present)
        ],
        "cabinets": cabinets,
    }


def _mx30_layer(layer_id: int, source: dict[str, Any], position: dict[str, int],
                scaler: dict[str, int], in_canvas: int, grid: int, z: int) -> dict[str, Any]:
    actual = _mx30_actual(source)
    return {
        "border": {"color": {"b": 0, "g": 0, "r": 255}, "enable": False, "width": 0},
        "canvasId": 0,
        "cut": {"enable": False, "rect": {"height": actual["height"], "width": actual["width"], "x": 0, "y": 0}},
        "followState": False, "gridId": grid, "id": layer_id, "layerInCanvasId": in_canvas,
        "layerIndex": 1, "layerSortId": 0, "lock": False,
        "position": dict(position), "scaler": dict(scaler),
        # OBSERVED: a layer's source is the input's groupId (REASONED from one
        # discriminating value: 25 matched only inputs[].groupId), never its id.
        "source": int(source["groupId"]),
        "sourceSize": {"height": actual["height"], "width": actual["width"]},
        "zOrder": z,
    }


def _mx30_input_port(source: dict[str, Any]) -> dict[str, Any]:
    # OBSERVED: screens[].inputPort describes the selected input with
    # LogicId (= the input id) and GroupId (= its groupId), a ModelId of 5138
    # (the MX30's model ID per /device/hw; that it means the same here is
    # REASONED), a FirmwareVersion whose four fields are all
    # empty, and two nested blocks: InputDetailInfo (a second, different
    # GroupId for the same port -- relation UNKNOWN) and InputSrcInfo, live
    # signal detail the input list does not carry (SourceFieldRate 5000 for
    # 50 Hz, REASONED as the x100 encoding the register bus uses).
    kind = int(source["type"])
    width, height, rate = source.get("edid", (3840, 2160, 60))
    actual = _mx30_actual(source)
    net = {"dhcp": False, "gateWay": "", "localIp": "", "netMask": "",
           "targetIp": "", "targetPort": 0, "videoStreamIp": ""}
    return {
        "CardId": 0, "EnableFrameRateCorrection": False,
        "FirmwareVersion": {"FileNum": "", "VersionName": "", "VersionNumber": "", "VersionRemark": ""},
        "GroupId": int(source["groupId"]), "HardwareID": "", "HwCardId": 0,
        "InputDetailInfo": {
            "Capacities": "", "DefaultFrameRate": 0, "DefaultHeight": height, "DefaultWidth": width,
            "GroupId": 49, "HDCPVersion": 4, "HeightStepVal": 1, "InputType": kind,
            "InterfaceUseState": 0, "InterlacedInputSupport": 0, "IsSupportHDR": True,
            "IsSupportHDROverwrite": True, "IsSupportSPDIF": True, "MCUDeviceIndex": 0,
            "MCUInterface": 0, "MaxBand": 600000000, "MaxBandWidth": 6000, "MaxCapacity": 0,
            "MaxHeight": 4095, "MaxSourceDepth": 10, "MaxWidth": 4092, "MinBand": 25000000,
            "MinCapacity": 0, "MinHeight": 600, "MinWidth": 800, "PortIndex": 0,
            "SilkNumber": 1, "SlotId": 2, "SourceName": str(source["name"]).replace(" ", "_"),
            "SourceNumber": 2, "SupportColorSpace": "0|1|2|3|255", "SupportFrameRate": "",
            "SupportResolution": "", "Type": 1, "WidthStepVal": 4, "YcbcrSwapIn": 0,
        },
        "InputSrcInfo": {
            "ChannelId": 0, "ColorGamut": 2, "ColorSpaceType": 2, "CurrentSourceDepth": 1,
            "FiberNetConfig": {"backupNetConfig": dict(net), "masterNetConfig": dict(net)},
            "FiberPortLinkStatus": None, "HDRSDRInformation": 0, "HdcpState": 1, "IP": "",
            "InPhase": 0, "InputID": source["id"], "InputType": kind, "InterfaceUseState": 0,
            "InterlacedInputFlag": 0, "IsSupportHDR": 1, "OverWriteColorGamut": 2, "Port": 0,
            "Range": 0,
            "SourceDetInColPixel": actual["width"], "SourceDetInRowPixel": actual["height"],
            "SourceFieldRate": int(actual.get("frameRate", 60) * 100),
            # CEA-861 blanking for 1080p, the signal the unit carried.
            "SourceHBackPorch": 148, "SourceHFrontPorch": 528, "SourceHSyncPulse": 44,
            "SourceHTotal": actual["width"] + 720,
            "SourceStatus": 1 if source.get("connected") else 0,
            "SourceVBackPorch": 36, "SourceVFrontPorch": 4, "SourceVSyncPulse": 5,
            "SourceVTotal": actual["height"] + 45,
            "VideoFormat": 0, "XOffset": 0, "YOffset": 0,
        },
        "LogicId": source["id"], "MaxCapacityLimit": 0, "MetaData": _mx30_metadata(),
        "ModelId": MX30_LIKE_MODEL_ID, "MonitorSlotId": 0, "Order": 0,
    }


def _mx30_screens(state: CoexState) -> dict[str, Any]:
    # OBSERVED on an MX30, 2026-09-26: the wall geometry is readable over GET.
    # canvases[].cabinets[] carries every cabinet's canvas-relative position
    # and size (the only positions anywhere in the API), keyed by cabinetID
    # with connectID = chain position; the cabinet extent equals the canvas
    # size for the *active* working mode only -- canvasInWorkingMode carries a
    # different size per mode. canvas.position is negative and layer
    # positions share that frame, so a pane must not mix the two frames or
    # read a negative layer position as off-screen (REASONED from one read).
    # layersInWorkingMode has one entry per working mode, each layer's source
    # being an input groupId, and screens[].workingMode says which applies.
    by_id = {int(s["id"]): s for s in state.inputs}
    live = by_id.get(int(state.current_input or 0)) or state.inputs[0]
    internal = next((s for s in state.inputs if int(s.get("type", 0)) == 224), live)
    canvas_position = {"x": -160, "y": -1080}
    screens = []
    for i, screen in enumerate(state.screens):
        members = [c for c in state.cabinets if c.get("screenID") == screen["screenID"]]
        size = {
            "width": max((c["positionX"] + c["width"] for c in members), default=screen["width"]),
            "height": max((c["positionY"] + c["height"] for c in members), default=screen["height"]),
        }
        screens.append({
            "canvases": [{
                "backupType": 0,
                "cabinets": [
                    {"angle": 0, "cabinetID": c["id"], "connectID": int(c.get("index", 0)),
                     "lockStatus": False, "outputID": 2048 + int(c.get("port", 0)), "pageID": 0,
                     "position": {"x": c["positionX"], "y": c["positionY"]},
                     "size": {"height": c["height"], "width": c["width"]}}
                    for c in members
                ],
                "canvasID": 2048,
                "canvasInWorkingMode": [
                    {"isCustomSize": True, "maxFrameRate": 480,
                     "size": {"height": 576, "width": 1024}, "workingMode": 0},
                    {"isCustomSize": True, "maxFrameRate": 330.6, "size": dict(size), "workingMode": 1},
                ],
                "canvasSerialNum": 0, "frequencyPhaseStatus": 0, "groups": None, "inputID": 0,
                "isCustomSize": True, "lastSize": dict(size), "layoutLines": None,
                "maxFrameRate": 330.6, "ordinal": 0, "outputCardId": 8,
                "outputCardModeId": MX30_LIKE_MODEL_ID, "position": dict(canvas_position),
                "rectSize": dict(size), "size": dict(size), "sizeMode": 0, "zorder": 0,
            }],
            "createTime": "", "cryptoCabinetNum": 0,
            "inputPort": _mx30_input_port(live),
            "layersInWorkingMode": [
                {"layerLayoutMode": 1, "workingMode": 0,
                 "layers": [_mx30_layer(1, internal, canvas_position,
                                        {"height": 1080, "width": 3840}, 2048, 0, 1)]},
                {"layerLayoutMode": 0, "workingMode": 1,
                 "layers": [_mx30_layer(65537, live, canvas_position, size, 0, 10, 2147483646)]},
            ],
            "layoutMode": 0, "lowLatency": False,
            "masterFrameRate": _mx30_actual(live).get("frameRate", 60),
            "monitorSlotId": 0, "ordinal": i, "outputMode": 0,
            "pageInfos": [{"isShow": p == 0, "pageID": p, "pageName": f"Simulated page {p + 1}"}
                          for p in range(8)],
            "position": {"x": 0, "y": 0}, "screenGroupID": MX30_LIKE_GROUP_ID,
            "screenID": screen["screenID"], "screenIndex": i,
            "screenName": screen.get("name", ""), "selectedPageID": 0, "workingMode": 1,
        })
    return {
        "screenGroups": [{"isShow": False, "name": "", "ordinal": 1,
                          "screenGroupID": MX30_LIKE_GROUP_ID}],
        "screens": screens,
    }


def _mx30_cabinet_count(state: CoexState) -> dict[str, Any]:
    # OBSERVED shape of /api/v1/screen/cabinet/count (first exercised on this
    # unit). It counts connected cabinets: 72 with the wall connected and 0
    # with every output line unplugged (OBSERVED, attended), so it is a
    # presence signal where monitor/info is not. CabinetCountInBlackList is 0
    # in both states: read 0 connected, and the websocket's
    # ScreensCabinetsCountChange carried 0 at every stage of the unplugging
    # (both OBSERVED); the HTTP value with the lines out was not recorded.
    return {"list": [
        {"CabinetCount": 0 if state.outputs_unplugged else
         sum(1 for c in state.cabinets if c.get("screenID") == s["screenID"]),
         "CabinetCountInBlackList": 0, "ScreenID": s["screenID"]}
        for s in state.screens
    ]}


def _mx30_device_cabinets(state: CoexState) -> list[dict[str, Any]]:
    # The cabinets connected now, not the configured ones: 0 entries with every
    # output line unplugged (OBSERVED, attended, 2026-09-26). A cabinet marked
    # offline stays listed here, as before: what one missing cabinet does to
    # this list was not observed (UNKNOWN).
    if state.outputs_unplugged:
        return []
    return [_mx30_cabinet_wire(c) for c in state.cabinets]


def _mx30_device_input(state: CoexState) -> dict[str, Any]:
    # OBSERVED shape of /api/v1/device/input (first exercised on this unit):
    # one inputPortConfig entry per input, every one carrying modelId 5138 and
    # a short hardwareID, plus the test-pattern generator's settings.
    def port_config(source: dict[str, Any]) -> dict[str, Any]:
        kind = int(source["type"])
        width, height, rate = source.get("edid", (3840, 2160, 60))
        dhcp = {"dhcp": False, "gateWay": "", "localIp": "", "netMask": ""}
        stream = {"targetIp": "", "targetPort": 0, "videoStreamIp": ""}
        level = {"b": 100, "g": 100, "r": 100, "w": 100}
        return {
            "blackLevelInfo": {"highLight": dict(level), "shadow": dict(level)},
            "capacity": 0, "colorGamut": 255, "colorSpaceType": 2 if kind == 224 else 255,
            "cscParameter": {"contrastValue": 100, "hueValue": 0, "portId": 255, "saturationValue": 100},
            "dhcpConfig": {"backupDHCPConfig": dict(dhcp), "masterDHCPConfig": dict(dhcp)},
            "edidInfo": {"isCustom": False, "refreshRate": rate,
                         "resolution": {"height": height, "width": width}},
            "fiberPortLinkStatus": None, "hardwareID": f"SIM{int(source['id']):05X}",
            "hdrParameter": {"overrideHdrType": 2 if kind == 224 else 255, "pqMaxCll": 1000,
                             "pqMaxCllChecked": False, "pqMode": 0, "realHdrType": 2},
            "isEdidSetting": False, "isLimitToFull": False,
            "logicId": source["id"], "modelId": MX30_LIKE_MODEL_ID, "range": 255,
            "sdpFileName": "",
            "sdpSourceInfo": {"colorGamut": 0, "colorSpaceType": 0, "hdrSdrInformation": 0,
                              "range": 0, "scanMode": 0, "sourceDepth": 0,
                              "sourceDetInColPixel": 0, "sourceDetInRowPixel": 0,
                              "sourceFieldRate": 0},
            "videoStreamConfig": {"backupVideoStreamConfig": dict(stream),
                                  "masterVideoStreamConfig": dict(stream)},
        }

    return {
        "inputPortConfig": [port_config(s) for s in state.inputs],
        "testPattern": {"mode": 0,
                        "parameters": {"blue": 0, "gradientStretch": 1, "gray": 1023, "green": 0,
                                       "gridWidth": 8, "moveSpeed": 50, "red": 4095, "state": 0,
                                       "x": 0, "y": 0, "z": 0},
                        "txColorSpaceType": 0, "txHDRType": 0},
    }


# --- MX30-like: what VMP read and wrote when it opened (OBSERVED 2026-09-26) --
#
# From a capture of NovaStar VMP connecting to the same MX30 (hwVersion
# V1.5.1) that evening, then an attended read-only test of display state. Key
# names, nesting, list lengths and types are as the unit sent them; every
# value is synthetic unless a comment says OBSERVED. Show data -- the unit's
# name, serial, MAC, UUID, addresses and times -- is replaced throughout.

MX30_LIKE_MODEL_NAME = "MX30"  # /device/hw ``name`` (OBSERVED); the model, not the operator's label
#: /device/hw ``hwVersion`` (OBSERVED), the string SNMP reported as firmware.
#: Which of the unit's version strings is "the firmware" is UNKNOWN.
MX30_LIKE_HW_VERSION = "V1.5.1"
MX30_LIKE_SERIAL = "SIMULATED-MX30-00001"  # synthetic; 20 characters, as the unit's ``sn`` was
MX30_LIKE_MAC = "00:00:5e:00:53:30"  # RFC 7042 documentation range; lower-case, colon-separated, as sent
MX30_LIKE_DEVICE_UUID = "{00000000-0000-0000-0000-000000000031}"  # synthetic; braced, as sent
MX30_LIKE_ADDRESS = "192.0.2.30"  # RFC 5737; the unit's own address is show data
MX30_LIKE_CANVAS_ID = 2048  # the wall's only canvas, keyed the same in display/state and the websocket
#: ``randomPassword`` as the simulator serves it. **Every consumer must drop
#: this field** before logging, storing, displaying or serialising a
#: ``/device/hw`` reply: the unit served a real 8-digit value to a bare,
#: unauthenticated GET (OBSERVED), and what it is for is UNKNOWN. This value
#: is deliberately fake so a test can assert it never gets through. It is also
#: a substring of the synthetic UUIDs, so a test should look for the key.
MX30_LIKE_FAKE_RANDOM_PASSWORD = "00000000"

#: The UDP ports the MX30 announced itself on, in the order of every burst,
#: from source port 54650 to the subnet broadcast, every 3 s (OBSERVED: 117
#: bursts of four). Which of them VMP listens on is UNKNOWN.
MX30_ANNOUNCE_PORTS = (54622, 54623, 54624, 54700)
MX30_ANNOUNCE_INTERVAL = 3.0
MX30_LIKE_HTTPS_PORT = "9001"  # announced as ``https``; whether anything listens there is UNKNOWN

#: The body keys of ``PUT /api/v1/device/hw/systemtime`` as VMP sent it
#: (OBSERVED, once): the time in UTC as separate fields, plus the client's
#: IANA time-zone name. The ``{"value": iso}`` body novasun's client used to
#: send is not this shape.
SYSTEMTIME_KEYS = ("clientTimezone", "second", "minute", "hour", "isUTC", "day", "month", "year")


def _size() -> dict[str, int]:
    return {"width": 0, "height": 0}


def _span() -> dict[str, int]:
    return {"min": 0, "max": 0, "step": 0}


def _mx30_capability() -> dict[str, Any]:
    """``/device/hw`` ``capability``: 161 keys in the order the unit sent them.

    OBSERVED values: capabilityVersion "V4.1.0"; snmp, artNet, NTP,
    inputImageEcho, outputImageEcho and allowChangeWorkMode true; every
    ``hwMonitor`` flag false. Every other leaf is a placeholder of the observed
    type (0, false, "", null; lists at their observed lengths): the real values
    were not retained, so a false here -- ``supportColorBeacon`` and
    ``disableSetSystemTime`` included -- is not evidence of anything.
    """
    return {
        "deviceType": 0, "systemLatency": False, "processing": False, "schedule": False,
        "rotation": False, "mirror": False, "3D": False, "multiUserThreeD": False,
        "multiUserThreeDNum": None, "threeDFrame": False, "threeDSource": None,
        "threeDFrameList": [], "hideThreeDRightOffset": False, "CabinetManagementTool": False,
        "HDR10": False, "inputBackup": False, "sync": False, "genLock": False,
        "frameRateMultiplication": False, "shutterSync": False,
        "photoelectricConversion": False, "lowLatency": False, "additionalFrameDelay": False,
        "blackLevel": False, "baseImageCount": 0, "inputZoom": False, "negPosSupport": False,
        "maxCapacity": 0, "presetImage": False, "abnormalImage": False,
        "customTestImage": False, "inputImageEcho": True, "outputImageEcho": True,
        "HDCP": False, "limitToFull": False, "highLights": False, "shadow": False,
        "signalTransmitter": False, "ABL": False, "EDE": False, "ITMO": False,
        "dynamicEngineIndependentControl": False, "colorReplace": False,
        "colorCalibration": False, "systemRestore": False, "3DLUT": False, "PIP": False,
        "CSC": False, "inputAutoSwitch": False, "curtainOverspread": False, "ipem": False,
        "hdmiModeSetting": False, "frameRemaping": False, "curve": False,
        "noVideoSignal": False, "maxWidth": 0, "maxHeight": 0, "presetImageMaxNum": 0,
        "outputBitDepth": [0] * 3, "bitDepth": 0, "internalBitDepths": [0] * 2,
        "colorSpaceType": [0] * 4, "colorGamutType": [0] * 4, "mosaic": {"mode": None},
        "presetImageSize": _size(), "presetImageSetInfo": {"maxWidth": 0, "maxHeight": 0},
        "additionalFrameDelayRange": _span(), "frameRateMultiplicationRange": _span(),
        "threeDRightEyeOffsetRange": _span(),
        "hwMonitor": dict.fromkeys((  # OBSERVED: every flag false
            "armSupported", "fanSupported", "fpgaSupported", "inputSubCardSupported",
            "mainBordSupported", "netWorkSubCardSupported", "opticalCardSupported"), False),
        "virtualMode": None, "videoController": False, "defaultCurtainSize": _size(),
        "maxCurtainSize": _size(), "minCurtainSize": _size(), "layerNumberLimit": 0,
        "supportSizeList": {"mode": [_size() for _ in range(2)]}, "maxCurtainArea": 0,
        "maxCurtainCapacity": 0, "maxLayerArea": 0, "modifyCurtainSize": False,
        "modifyLayerCoordinate": False, "modifyLayerSize": False, "supportLayerCut": False,
        "supportLayerBorder": False, "supportLayerZOrder": False, "minLayerSize": _size(),
        "maxLayerSize": _size(), "supportLayerStretch": False, "supportLayerOriginSize": False,
        "supportLayerScreenSize": False, "supportLayerFollow": False, "blackLevelOutPutBit": 0,
        "cabinetsPainter": False, "maxSourceDefaultWidth": 0, "maxSourceDefaultHeight": 0,
        "channelNumber": 0, "presetNameCheck": False, "customGamutNameChange": False,
        "customRate": False, "supportSourcecutTypes": None, "minSourcecutResolutionProduct": 0,
        "minSourcecutWidth": 0, "minSourcecutHeight": 0, "cinemaTxTest": False,
        "xyzTxTestPattern": False, "supportArtNetProtocol": False, "minFrameOffset": 0,
        "maxFrameOffset": 0, "supportHDRSourceTypes": "", "upgradeMaxTimeout": 0,
        "ncpManager": False,
        "layout": {"mode": [{"value": 0, "comment": "", "minCurtainSize": _size(),
                             "step": _size()} for _ in range(2)]},
        "presetNumber": 0, "maxScreenNumber": 0, "switchSourceType": 0, "audioSources": None,
        "hwScreenNeedHandleProcessing": False, "supportCable": False, "systemBackup": False,
        "controllerPosition": False, "allowChangeWorkMode": True, "curtainManage": False,
        "dP14Mode": False, "internalSource": False, "outputSyncSource": False,
        "outputSyncInner": False, "phaseShift": False, "cabinetsStore": False,
        "controllerMaintenance": False, "cabinetMaintenance": False, "preset": False,
        "artNet": True, "artNetMaxStartAddressList": [0] * 4, "snmp": True, "userManual": False,
        "shortcutKey": False, "isSupportModifyOpticalMode": False,
        # 19 numbers, some fractional (count and float|int typing OBSERVED; the
        # values were not recorded): a type-illustrative placeholder.
        "frameRateTable": [23.98, 24, 25, 29.97, 30, 47.95, 48, 50, 59.94, 60, 72, 75, 85,
                           100, 119.88, 120, 143.86, 144, 240],
        "supportPxToPx": False, "monitorType": 0, "disableSetSystemTime": False,
        "lineHWScreenType": 0, "layerDelete": False, "imageEnhance": False,
        "supportColorBeacon": False, "supportRGBWRatioAdjust": False,
        "isSupportGamutAsync": False, "correctSpeedVersion": "", "NTP": True,
        "mfCardUpdate": False, "deviceLocation": False, "smartHWScreen": False,
        "firmwarePainter": False, "sdi12GCustomHDR10": False, "dPCustomHDR10": False,
        "isSupportCloud": False, "capabilityVersion": "V4.1.0",
        "isSupportBatchCorrectionSwitch": False, "isSupportMvr": False,
        "isUpgradeHttpMode": False,
    }


def _mx30_hw(state: CoexState) -> dict[str, Any]:
    """``GET /api/v1/device/hw``: identity, versions and capabilities.

    OBSERVED on the MX30 (5698 B, read four times, differing only in
    memoryUsed and memoryFree): 44 keys in this order. ``name`` "MX30" and
    ``modelID`` 5138 in one object settle what 5138 names; ``hwVersion`` is the
    "V1.5.1" SNMP reported as firmware; ``mac`` is the MAC the announcement
    carries. OBSERVED values kept: type "G3.5", swVersion "1.0.0", mcuVersion
    "V1.0.0", fpgaVersion "V1.0.0.S1.T1.V9", configVersion "V1.4.0.1",
    ``softVersion.Version`` "", thirdPartySn and thirdPartySerial "", mode 3,
    deviceWorkMode 0, ``encipher.authState`` 0. ``customName`` carries the
    same label as monitor/info's ``name`` here; that the unit's two strings
    are equal is REASONED (the capture's masking gave both one token). Every
    other value is synthetic or a placeholder of the observed type.

    ``randomPassword`` is served, as the unit served it, to any GET -- see
    :data:`MX30_LIKE_FAKE_RANDOM_PASSWORD`, and drop it.
    """
    sub_board = {"type": 0, "sn": "", "modelId": 0}
    return {
        "name": MX30_LIKE_MODEL_NAME, "customName": state.custom_name or MX30_LIKE_LABEL,
        "modelID": MX30_LIKE_MODEL_ID, "sn": state.serial,
        "thirdPartySn": "", "thirdPartySerial": "", "mac": state.mac or MX30_LIKE_MAC,
        "type": "G3.5", "netPortBandWidth": 0, "hwVersion": state.firmware,
        "swVersion": "1.0.0", "mcuVersion": "V1.0.0", "fpgaVersion": "V1.0.0.S1.T1.V9",
        "mcuVersionRemark": "", "fpgaVersionRemark": "",
        "softVersion": {"Package": "", "Version": "", "Architecture": "", "Maintainer": "",
                        "Description": ""},
        "configVersion": "V1.4.0.1", "ip": MX30_LIKE_ADDRESS, "WirelessIpAddress": "",
        "mode": 3, "companyName": "", "capability": _mx30_capability(), "deviceWorkMode": 0,
        "IpNetmask": "255.255.255.0", "IpGateway": "192.0.2.1", "ethMode": "", "hostName": "",
        "Dns": None, "dhcp": False, "configIP": "", "Series": 0,
        "uptime": 3600, "memorySize": 0, "memoryUsed": 0, "memoryFree": 0,
        "subBoardInfo": {"inputSn": dict(sub_board), "sasaSn": dict(sub_board),
                         "sasbSn": dict(sub_board), "qsfpSn": dict(sub_board)},
        "customIp": "", "deviceUUID": MX30_LIKE_DEVICE_UUID, "groupName": "",
        "isAllowSingleDev": False, "supportInputSubCardNum": 0, "supportOutputSubCardNum": 0,
        "encipher": {"vendorID": 0, "authState": 0, "authStartTime": "", "authEndTime": "",
                     "isOverRange": False},
        # Consumers must drop this field -- see MX30_LIKE_FAKE_RANDOM_PASSWORD.
        "randomPassword": MX30_LIKE_FAKE_RANDOM_PASSWORD,
    }


def _mx30_display_state(state: CoexState) -> dict[str, Any]:
    """``GET /api/v1/screen/output/display/state``: display mode per canvas.

    OBSERVED on the MX30: ``displayMode`` read 0 while the wall was live and 2
    for the whole of a front-panel freeze, polled once a second through it
    (60 GETs, 2026-09-26), so a plain GET is enough for a read-only monitor
    (REASONED). The first attended freeze sweep polled
    ``/device/screen/displaymode`` (absent: an empty 200) and missed this
    endpoint. 0 normal, 2 freeze and 1 blackout are all OBSERVED (the
    blackout once, attended, on the same unit and evening).
    ``mappingState[].enable`` read false throughout; its meaning is UNKNOWN.
    Here the mode tracks :attr:`CoexState.display_mode`, so a test simulates
    a front-panel freeze by setting it.
    """
    return {
        "mappingState": [{"canvasID": MX30_LIKE_CANVAS_ID, "enable": False}],
        "displayState": [{"canvasID": MX30_LIKE_CANVAS_ID, "displayMode": state.display_mode}],
    }


def _mx30_lock(state: CoexState) -> dict[str, Any]:
    """``GET /api/v1/device/hw/lock``: whether a control application holds the unit.

    OBSERVED ``{"locked": 0, "ip": ""}`` before VMP took the lock (and, by the
    operator's report, after VMP quit). After VMP's PUT the unit pushed ``deviceLockChange {"locked": 1, "ip": <requester>}``
    over the websocket; no GET was made while it was held, so that the GET
    then reads the same pair is REASONED from the event, and is what is served.
    """
    held = state.lock_ip is not None
    return {"locked": 1 if held else 0, "ip": state.lock_ip if held else ""}


def _mx30_put_lock(handler: _Handler, body: Any) -> None:
    """``PUT /api/v1/device/hw/lock``: taken by a body naming ``appids``.

    OBSERVED once: ``{"appids": ["LCTPro<id>"]}`` -- an app-id list, not VMP's
    ``Application-Id`` header, and no IP -- answered ``{"code": 0, "data":
    null}``, and the pushed ``deviceLockChange`` named the requesting host's
    IP (REASONED to be the requester's: it was also the only subscriber's).
    Modelled only that far:

    * a body with a non-empty list of strings under ``appids`` takes the lock
      for the caller; what the list names or excludes is UNKNOWN;
    * any other body answers the same envelope and changes nothing (UNKNOWN on
      the unit; a simulator convention, like snmpstate's);
    * a second taker simply replaces the first (UNKNOWN on the unit);
    * nothing over HTTP releases it (VMP sent no unlock), and the lock blocks
      nothing here: the front-panel freeze went through while it was held
      (OBSERVED); whether it blocks other API clients is UNKNOWN.
    """
    appids = body.get("appids") if isinstance(body, dict) else None
    if isinstance(appids, list) and appids and all(isinstance(a, str) for a in appids):
        handler.state.lock_ip = handler.client_address[0]
        handler.state.lock_appids = list(appids)
    handler._send(0, "Success", None)


def _mx30_put_systemtime(handler: _Handler, body: Any) -> None:
    """``PUT /api/v1/device/hw/systemtime`` with the body VMP sent.

    OBSERVED once, as the first of VMP's writes on opening: the fields of
    :data:`SYSTEMTIME_KEYS` (UTC, ``isUTC`` true) answered ``{"code": 0,
    "data": null}``. So merely opening VMP writes the controller's clock and
    time zone. A body of exactly those keys is recorded in
    :attr:`CoexState.system_time`; no clock is modelled, and whether the unit
    applies it is UNKNOWN. Any other body -- the old ``{"value": iso}``
    included -- gets the same Success and is not recorded: REASONED to be a
    no-op on this firmware, by analogy with snmpstate's ``{"value": ...}``.
    """
    if isinstance(body, dict) and set(body) == set(SYSTEMTIME_KEYS):
        handler.state.system_time = dict(body)
    handler._send(0, "Success", None)


def announcement_payload(state: CoexState, api_port: int = DEFAULT_PORT) -> bytes:
    """The MX30's UDP announcement: 96 bytes of bare JSON at the default port.

    OBSERVED layout, byte for byte: no header, no terminator, compact JSON,
    keys in this order, ``apiPort`` and ``https`` strings, ``authType`` and
    ``workMode`` integers (0 on the unit; meanings UNKNOWN), ``data`` a
    one-element list. It carries no model, name, serial, version or IP -- a
    listener takes the address from the datagram's source. ``apiPort`` is the
    simulator's own port so a listener can follow it here; the unit sent
    "8001".
    """
    entry = {"apiPort": str(api_port), "mac": state.mac or MX30_LIKE_MAC,
             "authType": 0, "workMode": 0, "https": MX30_LIKE_HTTPS_PORT}
    return json.dumps({"data": [entry]}, separators=(",", ":")).encode("ascii")


#: GETs the MX30-like profile serves. Anything not here -- and anything in
#: ``missing_endpoints`` -- answers the empty HTTP 200 (OBSERVED for unknown
#: paths and absent documented paths alike). ``/api/v1/device/audio`` is
#: present on this unit (HTTP 404 on the MX40 Pro).
GETS_MX30 = {
    "/api/v1/screen": _mx30_screens,
    "/api/v1/device/cabinet": _mx30_device_cabinets,
    "/api/v1/device/input/sources": lambda state: [_mx30_input_wire(s, n + 1) for n, s in enumerate(state.inputs)],
    "/api/v1/preset": _presets,
    "/api/v1/device/monitor/info": _mx30_monitor_info,
    "/api/v1/device/audio": lambda state: {"enable": False, "source": 65535, "sourceName": ""},
    "/api/v1/device/backup": lambda state: {"master": "", "backup": "", "masterName": "", "backupName": ""},
    "/api/v1/device/multifunc-card/detailinfo": lambda state: [],
    "/api/v1/device/hw/mode": lambda state: {"mode": 3},  # 3 on this unit too; meaning UNKNOWN
    "/api/v1/device/snmpstate": lambda state: {"state": state.snmp_enabled},
    "/api/v1/screen/cabinet/count": _mx30_cabinet_count,
    "/api/v1/device/input": _mx30_device_input,
    # First requested by VMP's open, 2026-09-26 (OBSERVED shapes; see above).
    "/api/v1/device/hw": _mx30_hw,
    "/api/v1/screen/output/display/state": _mx30_display_state,
    "/api/v1/device/hw/lock": _mx30_lock,
}


def _mx30_put_snmpstate(handler: _Handler, body: Any) -> None:
    """PUT snmpstate as the MX30 answered it (OBSERVED, 2026-09-26).

    ``{"state": true|false}`` flipped the unit's state, twice in each
    direction, and the GET read it back. ``{"value": true}`` answered the same
    full Success envelope -- ``data`` an empty string -- and left the state as
    it was (OBSERVED once). Any body without a boolean ``"state"`` is answered
    that way here; that the firmware ignores such bodies in general is
    REASONED from that one.
    """
    if isinstance(body, dict) and isinstance(body.get("state"), bool):
        handler.state.snmp_enabled = body["state"]
    handler._send(0, "Success", "")


def _mx30_put_color_beacon(handler: _Handler, body: Any) -> None:
    """PUT hw/colorBeacon: HTTP 200, no Content-Type, Content-Length 0.

    OBSERVED on the MX30 for ``{"value"}``, ``{"state"}`` and ``{"enable"}``
    bodies, true and false alike. It is the reply that firmware gives GETs of
    absent endpoints, and with the operator watching the chassis no body
    changed anything visible (OBSERVED), so the endpoint is most likely absent
    (REASONED) and no state is modelled.
    """
    handler._empty_200()


#: PUTs the MX30-like profile answers as the unit did, consulted before PUTS.
#: A PUT to a made-up path was never tried on the MX30, so unknown PUT paths
#: keep the NotSupport envelope -- a simulator convention, not an observation:
#: do not read colorBeacon's empty 200 as proof that it exists.
PUTS_MX30 = {
    "/api/v1/device/snmpstate": _mx30_put_snmpstate,
    "/api/v1/device/hw/colorBeacon": _mx30_put_color_beacon,
    "/api/v1/device/hw/lock": _mx30_put_lock,
    "/api/v1/device/hw/systemtime": _mx30_put_systemtime,
}


#: GETs the MX40-like default serves.
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
        self._announcer: tuple[threading.Event, threading.Thread] | None = None
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

    def start_announcing(
        self,
        host: str = "127.0.0.1",
        ports: tuple[int, ...] = MX30_ANNOUNCE_PORTS,
        interval: float = MX30_ANNOUNCE_INTERVAL,
    ) -> None:
        """Send :func:`announcement_payload` to each of ``ports`` every ``interval`` s.

        Off unless called. The unit sent to its subnet broadcast from source
        port 54650; this sends to ``host`` (loopback by default) from an
        ephemeral port, first burst at once, one datagram per port in order,
        then a sleep -- the unit's phase drifted as a sleep loop's would
        (REASONED). Pointing ``host`` at a broadcast address puts the
        datagrams on that network. MX30-like profile only: whether an MX40 Pro
        announces is UNKNOWN.
        """
        if not self.state.mx30_like:
            raise ValueError("only the MX30-like profile announces; whether an MX40 Pro does is UNKNOWN")
        if self._announcer is not None:
            raise RuntimeError("already announcing")
        stop = threading.Event()
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sender.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        def run() -> None:
            try:
                while not stop.is_set():
                    payload = announcement_payload(self.state, self.address[1])
                    for port in ports:
                        try:
                            sender.sendto(payload, (host, port))
                        except OSError:
                            pass  # a lost datagram is what UDP does; keep the cadence
                    stop.wait(interval)
            finally:
                sender.close()

        thread = threading.Thread(target=run, name="coexsim-announce", daemon=True)
        self._announcer = (stop, thread)
        thread.start()

    def stop_announcing(self) -> None:
        if self._announcer is None:
            return
        stop, thread = self._announcer
        self._announcer = None
        stop.set()
        thread.join(timeout=5.0)

    @property
    def announcing(self) -> bool:
        return self._announcer is not None

    def server_close(self) -> None:
        self.stop_announcing()
        super().server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a fake COEX controller")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--model", default="MX40 Pro", help="MX40 Pro (default) or MX30")
    parser.add_argument(
        "--announce", metavar="HOST", default=None,
        help="MX30 only: also send its UDP announcement to HOST every 3 s (off by default)",
    )
    parser.add_argument(
        "--outputs-unplugged", action="store_true",
        help="MX30 only: serve the unit as read with every output data line unplugged "
             "and the power on -- connected-cabinet counts 0, monitor/info unchanged",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    try:
        state = CoexState(model=args.model, outputs_unplugged=args.outputs_unplugged)
    except ValueError as exc:
        parser.error(str(exc))
    server = SimulatedCoexController(args.host, args.port, state)
    server.verbose = args.verbose
    host, port = server.address
    print(f"simulating {server.state.model} HTTP API on http://{host}:{port}"
          + (" with every output unplugged" if state.outputs_unplugged else ""))
    if args.announce:
        try:
            server.start_announcing(args.announce)
        except ValueError as exc:
            server.server_close()
            parser.error(str(exc))
        print(f"announcing to {args.announce} on UDP {', '.join(map(str, MX30_ANNOUNCE_PORTS))}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
