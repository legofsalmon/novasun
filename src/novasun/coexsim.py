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

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        path = self.path.split("?")[0].rstrip("/")
        self.state.requests.append(("GET", path, None))
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


GETS = {
    "/api/v1/device": _device,
    "/api/v1/screen": lambda state: {"screens": state.screens},
    "/api/v1/screen/cabinets": lambda state: {"cabinets": state.cabinets},
    "/api/v1/device/cabinet": lambda state: {"cabinets": state.cabinets},
    "/api/v1/device/input/sources": lambda state: {"sources": state.inputs},
    "/api/v1/preset": lambda state: {
        "presets": state.presets,
        "current": state.current_preset,
    },
    "/api/v1/device/monitor/info": lambda state: {
        "cabinets": [
            {"id": cabinet["id"], "temperature": cabinet["temperature"],
             "online": cabinet["online"], "voltage": 3.8}
            for cabinet in state.cabinets
        ],
        "fanSpeed": 2400,
        "temperature": 41.0,
    },
    "/api/v1/device/screen/displaymode": _display_status,
    "/api/v1/device/audio": lambda state: {"volume": 50, "mute": False},
    "/api/v1/device/snmpstate": lambda state: {"value": False},
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
