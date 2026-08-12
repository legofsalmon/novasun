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

    # --- screens ------------------------------------------------------------

    def screen_cabinets(self) -> Any:
        return self.request("GET", "/api/v1/screen/cabinets")

    def screen_properties(self) -> Any:
        return self.request("GET", "/api/v1/screen/properties")

    def display_effect(self) -> Any:
        return self.request("GET", "/api/v1/screen/displayeffect")

    def display_status(self) -> Any:
        return self.request("GET", "/api/v1/device/screen/displaymode")

    def set_screen_gamma(self, screen_ids: list[str], gamma: float) -> None:
        self.request("PUT", "/api/v1/screen/gamma", {"idList": screen_ids, "value": gamma})

    def set_screen_color_temperature(self, screen_ids: list[str], kelvin: int) -> None:
        self.request(
            "PUT", "/api/v1/screen/colortemperature", {"idList": screen_ids, "value": kelvin}
        )

    def set_screen_colour_gamut(self, screen_ids: list[str], gamut: str | int) -> None:
        self.request("PUT", "/api/v1/screen/gamut", {"idList": screen_ids, "value": gamut})

    def set_brightness_limit(self, enabled: bool, nit: int | None = None) -> None:
        self.request("PUT", "/api/v1/screen/brightnesslimit/enable", {"value": bool(enabled)})
        if nit is not None:
            self.request("PUT", "/api/v1/screen/brightnesslimit", {"value": nit})

    def set_output_bit_depth(self, bits: int) -> None:
        self.request("PUT", "/api/v1/device/screen/video/bitdepth", {"value": bits})

    def set_multi_mode(self, screen_ids: list[str], mode: int) -> None:
        self.request("PUT", "/api/v1/screen/multimode", {"idList": screen_ids, "value": mode})

    def set_output_sync(self, source: int) -> None:
        self.request("PUT", "/api/v1/screen/output/sync", {"value": source})

    def set_3d_enabled(self, enabled: bool) -> None:
        self.request("PUT", "/api/v1/screen/3d/enable", {"value": bool(enabled)})

    def set_3d_emitter(self, enabled: bool) -> None:
        self.request("PUT", "/api/v1/screen/3d/emitter", {"value": bool(enabled)})

    def switch_layer_source(self, layer: int, source_id: int) -> None:
        self.request(
            "PUT", "/api/v1/screen/layer/source", {"layer": layer, "sourceId": source_id}
        )

    def canvas_mapping(self, enabled: bool) -> None:
        self.request("PUT", "/api/v1/screen/canvas/mapping", {"value": bool(enabled)})

    # --- cabinets -----------------------------------------------------------

    def cabinet_count(self) -> Any:
        return self.request("GET", "/api/v1/screen/cabinet/count")

    def set_cabinet_rgb_brightness(
        self, cabinet_ids: list[int], red: float, green: float, blue: float
    ) -> None:
        self.request(
            "PUT",
            "/api/v1/device/cabinet/rgb/brightness",
            {"idList": cabinet_ids, "red": red, "green": green, "blue": blue},
        )

    def set_cabinet_rgbw_components(self, cabinet_ids: list[int], **components: float) -> None:
        self.request(
            "PUT",
            "/api/v1/device/cabinet/rgbwbrightness",
            {"idList": cabinet_ids, **components},
        )

    def set_cabinet_gamma(self, cabinet_ids: list[int], gamma: float) -> None:
        self.request(
            "PUT", "/api/v1/device/cabinet/gamma", {"idList": cabinet_ids, "value": gamma}
        )

    def set_cabinet_colour_temperature(self, cabinet_ids: list[int], kelvin: int) -> None:
        self.request(
            "PUT",
            "/api/v1/device/cabinet/colortemperature",
            {"idList": cabinet_ids, "value": kelvin},
        )

    def set_cabinet_test_pattern(self, cabinet_ids: list[int], mode: int) -> None:
        self.request(
            "PUT", "/api/v1/device/cabinet/testpattern", {"idList": cabinet_ids, "mode": mode}
        )

    def set_cabinet_multi_mode(self, cabinet_ids: list[int], mode: int) -> None:
        self.request(
            "PUT", "/api/v1/device/cabinet/multimode", {"idList": cabinet_ids, "value": mode}
        )

    def set_prestored_image(self, cabinet_ids: list[int], mode: int) -> None:
        """What a cabinet shows when its signal disappears."""
        self.request(
            "PUT", "/api/v1/device/cabinet/prestoreimage", {"idList": cabinet_ids, "value": mode}
        )

    def move_cabinet(self, cabinet_id: int, x: int, y: int) -> None:
        self.request(
            "PUT", "/api/v1/device/cabinet/position", {"id": cabinet_id, "x": x, "y": y}
        )

    def set_thermal_compensation(
        self, cabinet_ids: list[int], enabled: bool, amount: int | None = None, mode: int | None = None
    ) -> None:
        self.request(
            "PUT",
            "/api/v1/device/correctionop/cabinets/thermacal/enable",
            {"idList": cabinet_ids, "value": bool(enabled)},
        )
        if amount is not None:
            self.request(
                "PUT",
                "/api/v1/device/correctionop/cabinets/thermacal/amount",
                {"idList": cabinet_ids, "value": amount},
            )
        if mode is not None:
            self.request(
                "PUT",
                "/api/v1/device/correctionop/cabinets/thermacal/mode",
                {"idList": cabinet_ids, "value": mode},
            )

    def set_colour_correction(self, enabled: bool) -> None:
        self.request("PUT", "/api/v1/device/correctionop/enable", {"value": bool(enabled)})

    def set_cabinet_gamut(self, cabinet_ids: list[int], gamut: str | int) -> None:
        self.request(
            "PUT",
            "/api/v1/device/correctionop/cabinets/gamut",
            {"idList": cabinet_ids, "value": gamut},
        )

    # --- input --------------------------------------------------------------

    def input_data(self) -> Any:
        return self.request("GET", "/api/v1/device/input")

    def set_edid(self, input_id: int, width: int, height: int, frame_rate: int) -> None:
        self.request(
            "PUT",
            f"/api/v1/device/input/{input_id}/edid",
            {"resolution": {"width": width, "height": height, "frameRate": frame_rate}},
        )

    def set_colour_space(self, input_id: int, value: int | str) -> None:
        self.request("PUT", f"/api/v1/device/input/{input_id}/colorspace", {"value": value})

    def set_colour_gamut(self, input_id: int, value: int | str) -> None:
        self.request("PUT", f"/api/v1/device/input/{input_id}/colourgamut", {"value": value})

    def set_quantisation_range(self, input_id: int, value: int | str) -> None:
        self.request("PUT", f"/api/v1/device/input/{input_id}/range", {"value": value})

    def set_hdr_mode(self, input_id: int, mode: int) -> None:
        self.request("PUT", f"/api/v1/device/input/{input_id}/hdrmode", {"value": mode})

    def set_internal_source(self, **parameters: Any) -> None:
        self.request("PUT", "/api/v1/device/input/internalsource", parameters)

    def set_input_adjustment(self, name: str, value: Any) -> None:
        """Colour adjustment: shadow, highlight, saturation, contrast, hue, reset."""
        allowed = {"shadow", "highlight", "saturation", "contrast", "hue", "reset"}
        if name not in allowed:
            raise ValueError(f"unknown adjustment {name!r}; expected one of {sorted(allowed)}")
        self.request("PUT", f"/api/v1/device/input/{name}", {"value": value})

    # --- presets ------------------------------------------------------------

    def update_preset(self, preset_id: str, **fields: Any) -> None:
        self.request("PUT", "/api/v1/preset/update", {"id": preset_id, **fields})

    # --- device -------------------------------------------------------------

    def audio(self) -> Any:
        return self.request("GET", "/api/v1/device/audio")

    def set_audio(self, volume: int | None = None, mute: bool | None = None) -> None:
        body: dict[str, Any] = {}
        if volume is not None:
            body["volume"] = volume
        if mute is not None:
            body["mute"] = mute
        if not body:
            raise ValueError("set_audio needs a volume or a mute state")
        self.request("PUT", "/api/v1/device/audio", body)

    def identify_controller(self, enabled: bool) -> None:
        self.request("PUT", "/api/v1/device/hw/colorBeacon", {"value": bool(enabled)})

    def backup_status(self) -> Any:
        return self.request("GET", "/api/v1/device/backup")

    def verify_backup(self) -> None:
        self.request("PUT", "/api/v1/device/backup/verify", {})

    def multifunction_card(self) -> Any:
        return self.request("GET", "/api/v1/device/multifunc-card/detailinfo")

    def set_controller_name(self, name: str) -> None:
        self.request("PUT", "/api/v1/device/hw/customname", {"value": name})

    def set_system_time(self, iso_timestamp: str) -> None:
        self.request("PUT", "/api/v1/device/hw/systemtime", {"value": iso_timestamp})

    def set_automatic_time(self, enabled: bool) -> None:
        self.request("PUT", "/api/v1/device/time/enable", {"value": bool(enabled)})

    def set_timezone(self, timezone: str) -> None:
        self.request("PUT", "/api/v1/device/timezone", {"value": timezone})

    def snmp_state(self) -> Any:
        return self.request("GET", "/api/v1/device/snmpstate")

    def set_snmp(self, enabled: bool) -> None:
        self.request("PUT", "/api/v1/device/snmpstate", {"value": bool(enabled)})

    def export_project(self) -> Any:
        return self.request("GET", "/api/v1/device/hw/deviceengineeringdocdata")

    def export_log(self) -> Any:
        return self.request("GET", "/api/v1/device/hw/log")


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
