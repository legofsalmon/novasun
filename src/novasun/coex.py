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


SNAPSHOT_ENDPOINTS = {
    "device": "/api/v1/device",
    "screens": "/api/v1/screen",
    "cabinets": "/api/v1/device/cabinet",
    "inputs": "/api/v1/device/input/sources",
    "presets": "/api/v1/preset",
    "monitoring": "/api/v1/device/monitor/info",
    "audio": "/api/v1/device/audio",
    "snmp": "/api/v1/device/snmpstate",
}


def snapshot(client: CoexClient, endpoints: dict[str, str] | None = None) -> dict[str, Any]:
    """GET every read-only endpoint and return the lot.

    The HTTP equivalent of a packet capture: take one before a VMP action and
    one after, diff them, and the fields that moved are what that action
    changed. Endpoints the firmware does not implement are recorded as errors
    rather than aborting the sweep.
    """
    result: dict[str, Any] = {}
    for name, path in (endpoints or SNAPSHOT_ENDPOINTS).items():
        try:
            result[name] = client.request("GET", path)
        except (CoexError, OSError, json.JSONDecodeError) as exc:
            result[name] = {"__error__": str(exc)}
    return result


def diff_snapshots(before: Any, after: Any, path: str = "") -> list[tuple[str, Any, Any]]:
    """Recursively compare two snapshots; returns ``(path, before, after)``.

    Monitoring fields drift on their own (temperatures, uptimes), so expect
    noise and read the diff for what changed *structurally*.
    """
    changes: list[tuple[str, Any, Any]] = []
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after)):
            changes.extend(
                diff_snapshots(
                    before.get(key, "__absent__"),
                    after.get(key, "__absent__"),
                    f"{path}.{key}" if path else str(key),
                )
            )
    elif isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            changes.append((f"{path}[]", f"{len(before)} items", f"{len(after)} items"))
        for index, (old, new) in enumerate(zip(before, after)):
            changes.extend(diff_snapshots(old, new, f"{path}[{index}]"))
    elif before != after:
        changes.append((path, before, after))
    return changes


def probe(host: str, port: int = DEFAULT_PORT, timeout: float = 2.0) -> bool:
    """True when a COEX HTTP API answers -- use it to pick a control path."""
    try:
        CoexClient(host, port, timeout).screens()
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return False
    except CoexError:
        return True  # it answered in the API's own format, so it is a COEX box
    return True
