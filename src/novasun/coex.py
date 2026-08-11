"""Client for the COEX HTTP API (MX/CX/KU controllers, the hardware VMP drives).

Current-generation controllers keep the register bus for central-control style
commands, but the interesting surface -- screens, cabinets, presets, layers,
monitoring -- is a documented JSON API on port 8001 with no authentication. If
the target hardware is COEX, this is the layer to build the application on; the
register bus is the fallback for older processors.

Endpoint paths follow NovaStar's *COEX Series Interface API* manual. Responses
are ``{"code": 0, "data": ..., "message": "Success"}``; a non-zero ``code``
raises :class:`CoexError`.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

DEFAULT_PORT = 8001

ERROR_CODES = {
    0: "Success",
    1: "InvalidParam",
    2: "SendFailed",
    3: "InternalErr",
    4: "AnalysisFailed",
    5: "Busying",
    6: "NotSupport",
}


class CoexError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"{ERROR_CODES.get(code, 'Error')} ({code}): {message}")
        self.code = code


@dataclass
class CoexClient:
    host: str
    port: int = DEFAULT_PORT
    timeout: float = 5.0

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        payload = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            url,
            data=payload,
            method=method,
            headers={"Content-Type": "application/json"} if payload else {},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            parsed = json.loads(response.read() or b"{}")
        if isinstance(parsed, dict) and "code" in parsed:
            if parsed["code"] != 0:
                raise CoexError(parsed["code"], parsed.get("message", ""))
            return parsed.get("data")
        return parsed

    # --- reads --------------------------------------------------------------

    def device_info(self) -> Any:
        return self.request("GET", "/api/v1/device")

    def screens(self) -> Any:
        return self.request("GET", "/api/v1/screen")

    def cabinets(self) -> Any:
        return self.request("GET", "/api/v1/device/cabinet")

    def input_sources(self) -> Any:
        return self.request("GET", "/api/v1/device/input/sources")

    def presets(self) -> Any:
        return self.request("GET", "/api/v1/preset")

    def monitoring(self) -> Any:
        return self.request("GET", "/api/v1/device/monitor/info")

    # --- writes -------------------------------------------------------------

    def set_display_mode(self, mode: int) -> None:
        """0 normal, 1 blackout, 2 freeze."""
        self.request("PUT", "/api/v1/device/screen/displaymode", {"value": mode})

    def set_cabinet_brightness(self, cabinet_ids: list[int], ratio: float, nit: int | None = None) -> None:
        body: dict[str, Any] = {"idList": cabinet_ids, "ratio": ratio}
        if nit is not None:
            body["nit"] = nit
        self.request("PUT", "/api/v1/device/cabinet/brightness", body)

    def set_screen_brightness(self, screen_ids: list[str], ratio: float) -> None:
        self.request(
            "PUT", "/api/v1/screen/brightness", {"idList": screen_ids, "ratio": ratio}
        )

    def select_input(self, source_id: int) -> None:
        self.request("PUT", "/api/v1/device/screen/input", {"value": source_id})

    def apply_preset(self, preset_id: str) -> None:
        self.request("PUT", "/api/v1/preset/current/update", {"id": preset_id})

    def set_test_pattern(self, mode: int, **parameters: Any) -> None:
        defaults = {
            "red": 4095,
            "green": 4095,
            "blue": 4095,
            "gray": 4095,
            "gridWidth": 1,
            "moveSpeed": 50,
            "gradientStretch": 8,
            "state": 0,
        }
        defaults.update(parameters)
        self.request(
            "PUT",
            "/api/v1/device/screen/controller/pattern/test",
            {"mode": mode, "parameters": defaults},
        )

    def set_cabinet_mapping(self, enabled: bool) -> None:
        self.request("PUT", "/api/v1/device/cabinet/mapping", {"value": bool(enabled)})

    def set_working_mode(self, all_in_one: bool) -> None:
        self.request("PUT", "/api/v1/device/hw/mode", {"value": 1 if all_in_one else 0})


def probe(host: str, port: int = DEFAULT_PORT, timeout: float = 2.0) -> bool:
    """True when a COEX HTTP API answers -- use it to pick a control path."""
    try:
        CoexClient(host, port, timeout).screens()
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return False
    except CoexError:
        return True  # it answered in the API's own format, so it is a COEX box
    return True
