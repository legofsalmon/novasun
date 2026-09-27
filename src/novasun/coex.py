"""Client for the COEX HTTP API (MX/CX/KU controllers, the hardware VMP drives).

Current-generation controllers keep the register bus for central-control style
commands, but the interesting surface -- screens, cabinets, presets, layers,
monitoring -- is a documented JSON API on port 8001 with no authentication. If
the target hardware is COEX, this is the layer to build the application on; the
register bus is the fallback for older processors.

Endpoint paths follow NovaStar's *COEX Series Interface API* manual. Responses
are ``{"code": 0, "data": ..., "message": "Success"}``; a non-zero ``code``
raises :class:`CoexError`. A zero ``code`` on a PUT does not show that anything
changed: on an MX30 a PUT whose body key the firmware ignored still answered
Success (OBSERVED once, see :meth:`CoexClient.set_snmp`), so read a setting back
after writing it.

**Secrets are removed at this boundary.** An MX30 (firmware V1.5.1, 2026-09-26)
served ``data.randomPassword`` -- an 8-digit string whose purpose is UNKNOWN --
to a bare, unauthenticated ``GET /api/v1/device/hw`` (OBSERVED). Every response
passes through :func:`redact_secrets` inside :meth:`CoexClient.request`, so no
caller -- monitor, survey, snapshot, identify -- ever holds the value to log,
store, display or serialise.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
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


class IgnoredWrite(Exception):
    """A write this client refuses to send because hardware was seen to ignore it."""


class CoexError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"{ERROR_CODES.get(code, 'Error')} ({code}): {message}")
        self.code = code


#: Response keys that are never passed on, matched case-insensitively anywhere
#: in the name. ``randomPassword`` is the one that has been seen with a value
#: (OBSERVED: ``GET /api/v1/device/hw`` on one MX30, V1.5.1, 2026-09-26, the
#: same 8 digits on four reads, served with no credential of any kind).
#: ``GET /api/v1/device/cloud/status`` carried ``password`` too, empty on that
#: unit. Nothing a monitor shows needs any of them, so the match is broad.
SECRET_KEY_PATTERN = re.compile(r"passw(or)?d", re.IGNORECASE)


def redact_secrets(value: Any) -> Any:
    """``value`` with every secret-named key removed, at any depth.

    Keys matching :data:`SECRET_KEY_PATTERN` are dropped -- not masked -- so a
    later ``json.dumps`` or log line cannot carry them. Dicts and lists are
    rebuilt, so the input is never mutated; anything else is returned as is.
    """
    if isinstance(value, dict):
        return {
            key: redact_secrets(item)
            for key, item in value.items()
            if not (isinstance(key, str) and SECRET_KEY_PATTERN.search(key))
        }
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value


@dataclass
class CoexClient:
    """The COEX HTTP API on port 8001: reads and writes.

    **There is deliberately no method that PUTs ``/api/v1/device/hw/lock``, and
    none may be added.** On one MX30 (firmware V1.5.1, 2026-09-26) VMP took
    that lock with ``PUT /api/v1/device/hw/lock {"appids": [...]}`` a few
    seconds after it opened; the unit pushed ``deviceLockChange {locked: 1,
    ip}`` to websocket subscribers, and the lock outlived the HTTP connection
    that took it, with no unlock seen while VMP ran (all OBSERVED). It read
    unlocked again after VMP quit (operator-reported; the release mechanism
    is UNKNOWN). **The lock is what a VMP session holds.** Taking
    it -- or releasing it -- from here would contend with the operator's own
    control session on a live show, and what else it blocks is UNKNOWN. Read
    it with :meth:`lock_state`; never write it.
    """

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
            parsed = redact_secrets(json.loads(response.read() or b"{}"))
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

    def display_state(self) -> Any:
        """``GET /api/v1/screen/output/display/state`` -- display mode per canvas.

        Shape (OBSERVED, one MX30, firmware V1.5.1, 2026-09-26)::

            {"mappingState": [{"canvasID": 2048, "enable": false}],
             "displayState": [{"canvasID": 2048, "displayMode": 0}]}

        ``displayMode`` read 2 for the whole of an attended front-panel freeze
        and 0 before and after it, polled once a second (OBSERVED); the unit's
        websocket pushed the same values at that freeze and, in a capture of
        VMP, at an earlier one. So 0 = normal
        and 2 = freeze are OBSERVED on that unit, and 1 = blackout too: it read
        1 through an attended front-panel blackout the same evening (OBSERVED
        once; the documented COEX enum said so first). What
        ``mappingState.enable`` means is UNKNOWN. Whether the MX40 Pro serves
        this path is UNKNOWN: it was never requested there.

        This, not :meth:`display_status`, is the endpoint that shows display
        state; the first attended freeze sweep missed it. Interpret it with
        :func:`novasun.monitor.interpret_display_state`, which treats an
        absent answer or an unrecognised value as unknown, never normal.
        """
        return self.request("GET", "/api/v1/screen/output/display/state")

    def hardware_info(self) -> Any:
        """``GET /api/v1/device/hw`` -- identity, versions and capabilities.

        OBSERVED on one MX30 (firmware V1.5.1, 2026-09-26), about 5.7 KB:
        ``name`` "MX30" and ``modelID`` 5138 in the same object, ``sn``,
        ``mac``, ``hwVersion`` "V1.5.1" (the string SNMP reported as firmware
        and ``/device/firmware/list`` as ``deviceVersion``), ``customName``
        (the controller's name -- the same label as ``monitor/info``'s
        ``name``, REASONED), ``capability{}`` and more. That ``name`` is the
        model rather than a label is REASONED from that one read, in which
        ``customName`` held the controller's name; which version string is
        "the firmware" is REASONED. Never requested on an MX40 Pro, so whether that
        firmware serves it is UNKNOWN.

        **The same response carried ``randomPassword``** (OBSERVED), served to
        an unauthenticated GET. It is removed before this returns -- by
        :func:`redact_secrets` in :meth:`request`, which every response passes
        through -- so it cannot reach a snapshot, a log or ``survey --json``.
        """
        return self.request("GET", "/api/v1/device/hw")

    def lock_state(self) -> Any:
        """``GET /api/v1/device/hw/lock`` -- whether a control application holds the unit.

        OBSERVED on one MX30 (firmware V1.5.1, 2026-09-26), before VMP took the
        lock: ``{"locked": 0, "ip": ""}``, twice. Once VMP had taken it, the
        websocket pushed ``deviceLockChange {"locked": 1, "ip": <VMP's host>}``
        (OBSERVED); a GET while locked was not captured, so that it then reads
        ``locked: 1`` with the holder's IP is REASONED. The lock did not stop
        a front-panel freeze (OBSERVED); whether it blocks other API clients is
        UNKNOWN. A read -- see the class docstring for why the matching PUT is
        not, and must not be, offered here.
        """
        return self.request("GET", "/api/v1/device/hw/lock")

    # --- writes -------------------------------------------------------------
    #
    # Only three of these have a body shape settled by hardware, all on one
    # MX30 (firmware V1.5.1, 2026-09-26): set_snmp and identify_controller,
    # which novasun sent, and set_system_time, whose body is the one VMP was
    # captured sending (novasun has never sent it). set_snmp's old
    # {"value": ...} body turned out to be silently ignored while the firmware
    # answered Success; set_system_time's old {"value": iso} body did not match
    # what VMP sends either. REASONED, untested: any other setter whose body
    # follows the same {"value": ...} convention -- set_automatic_time,
    # set_controller_name, set_timezone and the rest -- may be wrong the same
    # way. None of those has been sent to a controller; read the setting back
    # after any of them rather than trusting the envelope.

    def set_display_mode(self, mode: int) -> None:
        """0 normal, 1 blackout, 2 freeze."""
        self.request("PUT", "/api/v1/device/screen/displaymode", {"value": mode})

    def set_cabinet_brightness(self, cabinet_ids: list[int], ratio: float, nit: int | None = None) -> None:
        """``ratio`` is a 0-1 fraction. On an MX30 (V1.5.1, 2026-09-26) this body,
        with every cabinet id and no ``nit``, worked: ``/device/cabinet`` read the
        value back within 1 s (OBSERVED twice, attended)."""
        body: dict[str, Any] = {"idList": cabinet_ids, "ratio": ratio}
        if nit is not None:
            body["nit"] = nit
        self.request("PUT", "/api/v1/device/cabinet/brightness", body)

    def set_screen_brightness(self, screen_ids: list[str], ratio: float) -> None:
        """**A silent no-op on an MX30** (V1.5.1, 2026-09-26): this body answered
        a Success envelope and changed nothing, and the unit pushed
        ``screenBrightnessChange {screenIdList: null, brightness: 0}`` (OBSERVED
        once, attended). The right body is UNKNOWN; use
        :meth:`set_cabinet_brightness` and read back.

        So this refuses rather than send a write the controller reports as done
        and ignores. It sends nothing."""
        raise IgnoredWrite(
            "PUT /api/v1/screen/brightness with {idList, ratio} is ignored by an MX30 "
            "(answered Success, changed nothing; OBSERVED 2026-09-26). Use "
            "set_cabinet_brightness with the screen's cabinet ids."
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
        """The documented display-mode GET -- absent on both units read.

        OBSERVED: HTTP 404 on an MX40 Pro (2026-09-11) and an empty 200 on an
        MX30 (2026-09-26). Use :meth:`display_state`, which the MX30 serves.
        """
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
        """Turn the controller's identification beacon on or off -- a write.

        OBSERVED on one MX30 (firmware V1.5.1, 2026-09-26, VMP closed): both
        ``{"value": true}`` and ``{"value": false}`` answered HTTP 200 with no
        Content-Type, Content-Length 0 and no envelope -- the reply that firmware
        gives GETs of absent endpoints. :meth:`request` turns that into ``{}``, so
        this method returns without a word whatever happened. A PUT to a made-up
        path was never tried, so the reply alone cannot tell whether the
        endpoint exists. Later the same day, with the operator watching the
        chassis -- front panel, LCD and status LEDs -- ``{"value": ...}``,
        ``{"state": ...}`` and ``{"enable": ...}`` were each held true for 10 s
        and then set false: all nine replies were that same empty 200 and
        **nothing visible changed in any window** (OBSERVED). So on that firmware
        this method does nothing anyone could see, and the endpoint is most
        likely absent (REASONED); an indicator elsewhere or a body not tried is
        not excluded. Do not offer it as a working "identify" control.
        """
        self.request("PUT", "/api/v1/device/hw/colorBeacon", {"value": bool(enabled)})

    def backup_status(self) -> Any:
        return self.request("GET", "/api/v1/device/backup")

    def verify_backup(self) -> None:
        self.request("PUT", "/api/v1/device/backup/verify", {})

    def multifunction_card(self) -> Any:
        return self.request("GET", "/api/v1/device/multifunc-card/detailinfo")

    def set_controller_name(self, name: str) -> None:
        self.request("PUT", "/api/v1/device/hw/customname", {"value": name})

    def set_system_time(self, when: datetime | str, client_timezone: str) -> None:
        """Set the controller's clock -- a write.

        Sends the body VMP was captured sending when it opened (OBSERVED, one
        MX30, firmware V1.5.1, 2026-09-26; the unit answered
        ``{"code":0,"data":null,"message":"Success"}``)::

            {"clientTimezone": "<IANA zone name>", "second": 54, "minute": 1,
             "hour": 18, "isUTC": true, "day": 26, "month": 9, "year": 2026}

        VMP sent hour 18 at 19:01 local time (UTC+1) with ``isUTC`` true, so
        the fields are UTC components (OBSERVED values); that the firmware
        reads them as UTC *because* of ``isUTC`` is REASONED. VMP sent its
        host's own zone as ``clientTimezone``; what the unit does with it is
        UNKNOWN. A GET made before the PUT read an empty ``clientTimezone``,
        ``isUTC`` false and local-time fields (OBSERVED); none was made after
        it. Whether the clock actually moved is UNKNOWN: the unit's HTTP
        ``Date`` header lagged by about the same before and after (weak
        evidence it did not).

        This method used to send ``{"value": iso}``, which is not what the
        firmware was seen to accept; by analogy with the snmpstate finding it
        was most likely a Success-answering no-op (REASONED). **novasun has
        never sent either body to a controller.** Read the time back after
        writing, and do not wire this anywhere new: merely opening VMP already
        sends this write (OBSERVED once).

        ``when`` must be timezone-aware (a :class:`~datetime.datetime` or an
        ISO 8601 string with an offset); a naive time is ambiguous and refused.
        """
        moment = datetime.fromisoformat(when) if isinstance(when, str) else when
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError(
                "set_system_time needs a timezone-aware time; a naive one is ambiguous"
            )
        utc = moment.astimezone(timezone.utc)
        self.request(
            "PUT",
            "/api/v1/device/hw/systemtime",
            {
                "clientTimezone": client_timezone,
                "second": utc.second,
                "minute": utc.minute,
                "hour": utc.hour,
                "isUTC": True,
                "day": utc.day,
                "month": utc.month,
                "year": utc.year,
            },
        )

    def set_automatic_time(self, enabled: bool) -> None:
        self.request("PUT", "/api/v1/device/time/enable", {"value": bool(enabled)})

    def set_timezone(self, timezone: str) -> None:
        self.request("PUT", "/api/v1/device/timezone", {"value": timezone})

    def snmp_state(self) -> Any:
        return self.request("GET", "/api/v1/device/snmpstate")

    def set_snmp(self, enabled: bool) -> None:
        """Turn the controller's SNMP agent on or off -- a write.

        The body is ``{"state": bool}``, the key :meth:`snmp_state` returns.
        OBSERVED on one MX30 (firmware V1.5.1, 2026-09-26, VMP closed):
        ``{"state": true}`` and ``{"state": false}`` each flipped the state, twice
        in each direction, and the GET read it back; ``{"value": true}`` -- what
        this method sent until then -- answered HTTP 200 with a full Success
        envelope (``{"code":0,"data":"","message":"Success"}``) and changed
        nothing (OBSERVED once; ``{"value": false}`` was never sent). Because
        :meth:`request` returns that envelope's data without raising, the old
        body was a silent no-op that reported success. Where it came from is
        unrecorded: it dates from commit 6c9cbd8, and whether the manual gives
        ``"value"`` for this endpoint or the body followed the convention of
        other setters is not established.

        A Success envelope on a PUT is therefore not confirmation (REASONED from
        this one endpoint). This method does not read back: call
        :meth:`snmp_state` afterwards before relying on the change.
        """
        self.request("PUT", "/api/v1/device/snmpstate", {"state": bool(enabled)})

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


#: Fields that identify an element of a list, tried in order; a tuple is a
#: compound key. An element is matched by the first of these that every
#: element in both lists carries with distinct values.
IDENTITY_KEYS: tuple[Any, ...] = (
    "cabinetID", "rvCardID", "id", "presetUUID", "screenID", "screenGroupID",
    "controllerPortID", "powerID", "fanName", ("outputCardID", "outputID"),
    ("inputCardID", "portID"),
)


def _identity_by(item: Any, key: Any) -> Any:
    """``item``'s identity under one strategy, or ``None`` if it has none."""
    if not isinstance(item, dict):
        return None
    if key == "__nested__":
        # The real MX40 Pro's monitor/info.cabinets[] carry cabinetID: 0 on
        # every entry and are identified only by the cabinetID on their
        # rvCards[]. A nested list's identity is the tuple of its elements'.
        for name, child in item.items():
            if isinstance(child, list) and child and all(isinstance(c, dict) for c in child):
                for inner in IDENTITY_KEYS:
                    ids = [_identity_by(c, inner) for c in child]
                    if all(i is not None for i in ids) and len(set(ids)) == len(ids):
                        return (name, tuple(ids))
        return None
    names = key if isinstance(key, tuple) else (key,)
    if all(name in item for name in names):
        return (key, tuple(repr(item[name]) for name in names))
    return None


def _aligned(before: list[Any], after: list[Any]) -> dict[Any, tuple[int | None, int | None]] | None:
    """Map identity -> (index in before, index in after), or None if unkeyed.

    The key is a property of the *list*, not of an element: the first strategy
    under which every element on both sides has an identity and no two share
    one. A key that is present but not distinct -- cabinetID: 0 on every entry
    -- is skipped, not trusted.
    """
    if not (before or after) or not all(isinstance(x, dict) for x in before + after):
        return None
    for key in IDENTITY_KEYS + ("__nested__",):
        ids_b = [_identity_by(x, key) for x in before]
        ids_a = [_identity_by(x, key) for x in after]
        if any(i is None for i in ids_b + ids_a):
            continue
        if len(set(ids_b)) != len(ids_b) or len(set(ids_a)) != len(ids_a):
            continue
        table: dict[Any, tuple[int | None, int | None]] = {i: (n, None) for n, i in enumerate(ids_b)}
        for n, i in enumerate(ids_a):
            table[i] = (table[i][0] if i in table else None, n)
        return table
    return None


def diff_snapshots(before: Any, after: Any, path: str = "") -> list[tuple[str, Any, Any]]:
    """Recursively compare two snapshots; returns ``(path, before, after)``.

    Monitoring fields drift on their own (temperatures, uptimes), so expect
    noise and read the diff for what changed *structurally*.

    Lists of identifiable elements are aligned **by identity, not position**.
    OBSERVED on an MX40 Pro: ``monitor/info.cabinets[]`` comes back in a
    different order on every call -- all 288 entries moved between two
    snapshots taken 35 minutes apart, with the same ids and the same per-id
    values. A positional diff reported 1,974 changes; keyed by id there were
    forty-one one-degree temperature flickers. Elements present on only one
    side are reported as ``__absent__``; the index in ``path`` is the element's
    position in ``before`` (or in ``after`` for additions).
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
        table = _aligned(before, after)
        if table is None:
            for index, (old, new) in enumerate(zip(before, after)):
                changes.extend(diff_snapshots(old, new, f"{path}[{index}]"))
        else:
            for _identity, (ib, ia) in sorted(
                table.items(), key=lambda kv: (kv[1][0] is None, kv[1][0] or 0, kv[1][1] or 0)
            ):
                if ib is None:
                    changes.append((f"{path}[{ia}]", "__absent__", after[ia]))
                elif ia is None:
                    changes.append((f"{path}[{ib}]", before[ib], "__absent__"))
                else:
                    changes.extend(diff_snapshots(before[ib], after[ia], f"{path}[{ib}]"))
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
