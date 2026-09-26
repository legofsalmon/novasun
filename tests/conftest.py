"""Shared test helpers.

The only thing here is the second-loopback problem, which is not worth solving
twice.
"""

from __future__ import annotations

import socket


def _bindable(address: str) -> bool:
    with socket.socket() as probe:
        try:
            probe.bind((address, 0))
        except OSError:
            return False
    return True


#: A second loopback address, when the platform offers one.
#:
#: The application keys devices by address string -- one processor per address
#: is the real-world case -- so two simulators have to look like two addresses.
#: Linux assigns the whole of 127/8 to the loopback interface, so 127.0.0.2 is
#: bindable there. macOS assigns only 127.0.0.1 and fails the bind with
#: EADDRNOTAVAIL, so this cannot be a constant.
SECOND_LOOPBACK: str | None = "127.0.0.2" if _bindable("127.0.0.2") else None

#: Where a second simulator should actually bind.
SECOND_BIND = SECOND_LOOPBACK or "127.0.0.1"

#: What the application should call it.
#:
#: Where a second address exists, that address. Where it does not, "localhost" --
#: a distinct dictionary key that still resolves to the interface the simulator
#: is bound to, which is precisely what these tests need. The alternative is
#: aliasing a loopback address, which needs privileges a test run should not ask
#: for.
SECOND_KEY = SECOND_LOOPBACK or "localhost"


def closed_port() -> int:
    """A TCP port on loopback that nothing is listening on right now.

    Bind-then-release: the port is free at the moment of the call, which is
    what a test that needs a refused connection wants.
    """
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def host_key(server) -> str:
    """The address the application should use for ``server``.

    Falls back to whatever the socket reports, so it is safe on servers that
    were never given a key.
    """
    return getattr(server, "key_host", server.address[0])


# --- An MX40 Pro's HTTP API, in miniature -----------------------------------
#
# The structure below is the OBSERVED response shape of a real MX40 Pro
# (2026-09-11), with every value replaced: three cabinets instead of 288, fake
# ids, fake names. Nothing from the show that produced it is here. Field names
# and nesting are exact, which is what the parsers are tested against.

MX40_LIKE_CABINETS = [
    {
        "id": 700000000000001 + i, "index": i, "outputID": 2048, "outputCardID": 8,
        "outputIndex": 0, "canvasID": 2048, "brightness": 0.8,
        "gamma": {"r": 2.8, "g": 2.8, "b": 2.8}, "gain": {"r": 43, "g": 43, "b": 43},
        "colorTemperature": 6500, "resolution": {"width": 128, "height": 128},
        "size": {"width": 500, "height": 500}, "rvCardName": "A5sPlus", "shortName": "",
        "moduleCount": 4, "power": 12, "voltage": 5, "indicatorLightState": True,
    }
    for i in range(3)
]


def _sensor(value):
    return {"name": "", "nameEn": "", "status": 0, "value": value}


MX40_LIKE_MONITOR_INFO = {
    "name": "MX40 Pro_000001",
    "runtime": 17160, "totalRuntime": 986580,
    "mainBoardTemperature": {"name": "Main_board Temperature", "nameEn": "", "status": 0, "value": 42},
    "mainBoardVoltage": {"name": "Main_board Voltage", "nameEn": "", "status": 0, "value": 11.45},
    "fanInfos": [{"fanName": "chassis Fan", "fanNameEn": "", "fanShowType": 0,
                  "fanSpeed": 1293, "fanType": 0, "status": 0}],
    "backupStatus": {"errCode": 108, "status": 0},
    "cardMonitorInfo": None, "temperatureInfos": None, "voltageInfos": None,
    "controllerPortMonitorInfos": [{"controllerPortID": 0, "status": 0}],
    "outputStatus": [{"outputCardID": 8, "outputID": 2048, "status": 0, "type": 0}],
    "powerMonitorInfos": [{"powerID": 0, "status": 0}],
    "screenSourceStatus": [{"inputCardID": 1, "portID": 256, "status": 0}],
    "rvCardsRuntime": [],
    "cabinets": [
        {
            # cabinetID is 0 on every entry and the top-level readings are 0:
            # the real data is on the receiving card.
            "cabinetID": 0, "canvasID": 0, "index": i, "outPutID": 2048,
            "outputCardID": 8, "rvCardID": 0,
            "temperature": _sensor(0), "voltage": _sensor(0),
            "rvCards": [{
                "cabinetID": 700000000000001 + i, "rvCardID": 700000000000001 + i,
                "cabinetIndex": i, "netPortIndex": 2048,
                "temperature": _sensor(temp), "voltage": _sensor(volts),
                "humidity": _sensor(0),
                "errorBit": [{"status": 1, "type": 0, "value": 65535}],
                "nextCabinetLinkStatus": {"linkStatus": link, "status": 0},
                "backupStatus": {"mode": 0, "status": 0},
                "moduleInfos": None, "runtime": 0, "totalRuntime": 0,
            }],
        }
        for i, (temp, volts, link) in enumerate(((39, 4.2, True), (41, 4.1, True), (37, 4.4, False)))
    ],
}

MX40_LIKE_INPUTS = [
    {"id": 512, "name": "HDMI 1", "type": 3, "port": 0, "cardId": 0, "groupId": 25,
     "sourceStatus": 1, "usable": True, "order": 0, "colorSpace": "YCbCr 4:4:4",
     "actualResolution": {"width": 3840, "height": 2160}, "actualRefreshRate": 50},
    {"id": 768, "name": "DP 1", "type": 5, "port": 0, "cardId": 0, "groupId": 40,
     "sourceStatus": 0, "usable": True, "order": 0, "colorSpace": "RGB 4:4:4",
     "actualResolution": {"width": 3840, "height": 3840}, "actualRefreshRate": 60},
]

MX40_LIKE_SCREENS = {
    "screens": [{"screenID": "{00000000-0000-0000-0000-000000000001}", "screenName": "Main",
                 "screenIndex": 0, "workingMode": 1, "masterFrameRate": 50,
                 "lowLatency": False, "canvases": [], "pageInfos": [],
                 "layersInWorkingMode": [], "position": {}, "inputPort": {},
                 "layoutMode": 0, "outputMode": 0, "ordinal": 0, "selectedPageID": 0,
                 "screenGroupID": "{g}", "createTime": ""}],
    "screenGroups": [{"isShow": False, "name": "Group", "ordinal": 0, "screenGroupID": "{g}"}],
}


# --- An MX30's HTTP API, in miniature ----------------------------------------
#
# The structure below is the OBSERVED response shape of one NovaStar MX30 --
# firmware v1.5.1 as reported by the operator at the time, and read over SNMP
# as V1.5.1 later that day (tests/fixtures/mx30_snmp_walk.json); no field the
# HTTP API returned names the controller model or firmware -- read once after a
# show on 2026-09-26 through HTTP GETs only, with every value that could
# identify the show replaced: three cabinets instead of 72, synthetic ids and
# UUIDs, a made-up controller name, empty receiving-card remarks, generic page
# and preset names. Field names, nesting, the list lengths that carry meaning
# (33 outputs, 3 fans, 2 controller ports, 6 inputs, 8 pages) and the relations
# between endpoints are exact: that is what the parsers here and in crewbox are
# tested against.
#
# The three cabinets are the chain-position-0 cabinet of each of the three
# populated outputs (2048, 2050, 2052; 24 cabinets each on the unit), so the
# per-output errorBit[0].value (190/189/187, constant within an output) and the
# odd /device/cabinet.voltage at chain position 0 (34/57/235 -- 5 on the other
# 69) are both represented. The meaning of either is UNKNOWN.
#
# Scope of every OBSERVED claim in this section: one MX30, one firmware, one
# afternoon (14:44Z-14:57Z), VMP attachment UNKNOWN. Nothing here says what
# another MX30 or another firmware does.

#: The unit's monitor/info.name was a plain word -- no model in it.
#: The label here is made up to make the same point: a consumer reads a name
#: here, never a model. (That the word was operator-set is REASONED: the API
#: has a customname setter; nobody read the unit's settings.)
MX30_LIKE_NAME = "Stage left"

MX30_LIKE_SCREEN_ID = "{00000000-0000-0000-0000-000000000002}"
MX30_LIKE_PRESET_IDS = ("{00000000-0000-0000-0000-000000000003}",
                        "{00000000-0000-0000-0000-000000000004}")
#: Every UUID the fixture contains. The test for show data checks against it.
MX30_LIKE_UUIDS = (MX30_LIKE_SCREEN_ID,) + MX30_LIKE_PRESET_IDS
#: Every cabinet id the fixture contains (the unit's were 16 digits; these are 15).
MX30_LIKE_IDS = (400000000000001, 400000000000002, 400000000000003)

#: What a path that answered HTTP 200 with ``Content-Length: 0`` -- no
#: Content-Type, no ``{"code", "data", "message"}`` envelope, so a JSON parse
#: of the body fails -- looks like in the fixture. OBSERVED with ``curl -i`` on
#: /api/v1/device, /api/v1/device/screen/displaymode and three made-up paths:
#: on this firmware an unknown path answers exactly like an absent one, where
#: the MX40 Pro answered 404 for absent documented endpoints. Status code and
#: latency (about 2 ms either way) do not tell them apart; only the body does.
MX30_LIKE_EMPTY_200 = {"__http_status__": 200, "__empty_body__": True}

# (outputID, outputIndex, errorBit[0].value, /device/cabinet.voltage, card degC, card V)
_MX30_PORTS = ((2048, 0, 190, 34, 41, 4.3), (2050, 2, 189, 57, 43, 4.2), (2052, 4, 187, 235, 44, 4.4))


def _mx30_cabinet(i: int, output: int, output_index: int, voltage: int) -> dict:
    return {
        "id": MX30_LIKE_IDS[i],
        # index is the chain position (0-23 on the unit) and outputIndex the
        # output's ordinal (outputID - 2048): (outputID, index) was unique 72/72.
        "index": 0, "outputID": output, "outputCardID": 8, "outputIndex": output_index,
        "canvasID": 2048, "brightness": 0.5,
        "gamma": {"r": 2.8, "g": 2.8, "b": 2.8}, "gain": {"r": 43, "g": 43, "b": 43},
        "colorTemperature": 6500, "resolution": {"width": 128, "height": 128},
        # Descriptive fields were unset on this wall -- size 0x0, power 0, weight
        # 0, pointSpacing "0.000", moduleSize 255/255 -- so a pane cannot rely
        # on them for geometry or load.
        "size": {"width": 0, "height": 0}, "rvCardName": "A5sPlus", "shortName": "",
        "moduleCount": 4, "power": 0,
        # 5 on 69 cabinets; 34, 57 and 235 on the three at chain position 0.
        # Meaning UNKNOWN. The card's own reading is monitor/info rvCards[].voltage.
        "voltage": voltage,
        "indicatorLightState": True,
        "angle": 0, "bunchesIndex": 0, "cabType": "", "clientOrderNo": "", "customGamma": False,
        "familyName": "", "manufacture": "", "ncpFileName": "", "ncpVersion": "0.0.0.0",
        "pointSpacing": "0.000", "supportType": 0, "vsFreMax": 0, "weight": 0,
        "cabinetFileParam": {"cabinetName": "", "cardModel": "", "issue": 0,
                             "manufactureName": "", "status": "unknown", "version": "0.0.0.0"},
        "moduleSize": {"moduleCol": 255, "moduleRow": 255, "overwrite": False},
        "rvCardInfo": {
            "chipEffectFlag": 0, "decodeIc": "", "driverChip": "",
            "firmware": "4.6.6.68", "mcuFirmWare": "4.6.6.68",
            # Both remarks were populated, and identical on all 72 cards. They
            # are show data and are deliberately empty here.
            "firmwareRemark": "", "mcuFirmWareRemark": "",
            "grayScale": 14, "maxGamma": 9856, "refreshRate": 3850, "scanNumber": 16,
            "moduleResolution": {"width": 64, "height": 64},
        },
    }


MX30_LIKE_CABINETS = [
    _mx30_cabinet(i, output, output_index, voltage)
    for i, (output, output_index, _, voltage, _, _) in enumerate(_MX30_PORTS)
]


def _mx30_card(i: int, output: int, error_value: int, temp: int, volts: float) -> dict:
    return {
        "cabinetID": MX30_LIKE_IDS[i], "rvCardID": MX30_LIKE_IDS[i],
        "cabinetIndex": 0, "netPortIndex": output,
        "temperature": _sensor(temp), "voltage": _sensor(volts), "humidity": _sensor(0),
        # phy1/phy2 read 0 on every card. signalInterruptCount is a bare int --
        # the one rvCards reading that is not a {name, nameEn, status, value}
        # object; a reader that unwraps .value on every field fails on it.
        "phyTemperature": {"phy1": _sensor(0), "phy2": _sensor(0)},
        "signalInterruptCount": 0,
        # errorBit[0].value: one value per output, constant within it, in both
        # snapshots; errorBit[1] was {0, 1, 0} on all 72. Meaning UNKNOWN.
        "errorBit": [{"status": 1, "type": 0, "value": error_value},
                     {"status": 0, "type": 1, "value": 0}],
        "nextCabinetLinkStatus": {"linkStatus": True, "status": 0},
        "backupStatus": {"mode": 0, "status": 0},
        # runtime/totalRuntime were 0 on every card; the per-card values live
        # in rvCardsRuntime[] (as on the MX40).
        "moduleInfos": None, "runtime": 0, "totalRuntime": 0,
    }


def _mx30_output(output_id: int, type_: int, link: bool, status: int = 0, card: int = 8) -> dict:
    return {"outputCardID": card, "outputID": output_id, "status": status, "type": type_,
            "linkStatus": link}


MX30_LIKE_MONITOR_INFO = {
    "name": MX30_LIKE_NAME,
    # Both multiples of 60; runtime advanced +60 at hh:mm:03 each minute.
    "runtime": 21000, "totalRuntime": 2052000,
    "mainBoardTemperature": {"name": "Main_board Temperature", "nameEn": "Main_board Temperature",
                             "status": 0, "value": 32},
    "mainBoardVoltage": {"name": "Main_board Voltage", "nameEn": "Main_board Voltage",
                         "status": 0, "value": 11.56},
    "fanInfos": [
        {"fanName": "Chassis Fan 1", "fanNameEn": "Chassis Fan 1", "fanShowType": 0,
         "fanSpeed": 3776, "fanType": 1, "status": 0},
        {"fanName": "FPGA Fan", "fanNameEn": "FPGA Fan", "fanShowType": 0,
         "fanSpeed": 2783, "fanType": 15, "status": 0},
        {"fanName": "Chassis Fan 2", "fanNameEn": "Chassis Fan 2", "fanShowType": 0,
         "fanSpeed": 3756, "fanType": 2, "status": 0},
    ],
    "backupStatus": {"errCode": 108, "maxNormalValue": 0, "minNormalValue": 0, "status": 0},
    "cardMonitorInfo": None, "temperatureInfos": None, "voltageInfos": None,
    # Not in the MX40 fixture; whether the MX40 sent them is UNKNOWN.
    "accessoryMonitorInfo": {"multifunctionCardStatus": [], "transmitterStatus": []},
    "imbLinkStatus": {"linkStatus": False, "status": 0},
    "inputFiberStatus": None,
    # Two entries; status 2 on the second. Status code meanings UNKNOWN.
    "controllerPortMonitorInfos": [{"controllerPortID": 0, "status": 0},
                                   {"controllerPortID": 1, "status": 2}],
    # 33 entries: 2048-2057 type 0, linkStatus true on 2048-2052 only (cabinets
    # hung on 2048/2050/2052; 2049/2051 linked with none) and status 2 on the
    # unlinked 2053; 2058-2077 type 5; 2078-2079 type 1; one outputID 0 type 3.
    # REASONED, all UNKNOWN until an attended test: type 0 the ten RJ45 ports,
    # type 1 the two OPT ports, type 5 twenty fibre-carried channels.
    "outputStatus": (
        [_mx30_output(o, 0, o <= 2052, 2 if o == 2053 else 0) for o in range(2048, 2058)]
        + [_mx30_output(o, 5, False) for o in range(2058, 2078)]
        + [_mx30_output(o, 1, False) for o in range(2078, 2080)]
        + [_mx30_output(0, 3, False, card=0)]
    ),
    "powerMonitorInfos": [{"powerID": 0, "status": 0}],
    # groupID is input/sources[].groupId and portID its id; linkStatus was true
    # on exactly the two inputs with sourceStatus 1. inputCardID 0 throughout.
    # This list, like cabinets[], came back reordered between reads.
    "screenSourceStatus": [
        {"groupID": 25, "inputCardID": 0, "linkStatus": True, "portID": 512, "status": 0},
        {"groupID": 57, "inputCardID": 0, "linkStatus": False, "portID": 3, "status": 0},
        {"groupID": 58, "inputCardID": 0, "linkStatus": False, "portID": 4, "status": 0},
        {"groupID": 32, "inputCardID": 0, "linkStatus": False, "portID": 256, "status": 0},
        {"groupID": 18, "inputCardID": 0, "linkStatus": False, "portID": 768, "status": 0},
        {"groupID": 224, "inputCardID": 0, "linkStatus": True, "portID": 25856, "status": 0},
    ],
    # Stable order that is not cabinets[] order: join on cabinetID. runtime read
    # 31764480 on all 72 cards in both snapshots (static; meaning UNKNOWN);
    # totalRuntime differed per card and advanced in 60 s steps.
    "rvCardsRuntime": [
        {"cabinetID": MX30_LIKE_IDS[i], "rvCardID": MX30_LIKE_IDS[i],
         "runtime": 31764480, "totalRuntime": total}
        for i, total in ((2, 5940000), (1, 6072000), (0, 10170000))
    ],
    "cabinets": [
        {
            # Unlike the MX40 record: cabinetID and rvCardID are populated and
            # equal the card's; the top-level temperature/voltage are gone and
            # a nested "cabinet" object appears whose voltage mirrors
            # rvCards[0].voltage (it moved in lock-step) and whose other
            # readings are 0 or null. Read the card; a keyed diff that reads
            # both counts every voltage move twice.
            "cabinetID": MX30_LIKE_IDS[i], "rvCardID": MX30_LIKE_IDS[i], "canvasID": 2048,
            "index": 0, "outPutID": output, "outputCardID": 8,
            "cabinet": {"cabinetID": 0, "temperature": _sensor(0), "voltage": _sensor(volts),
                        "humidity": _sensor(0), "smoke": _sensor(0), "power": None},
            "rvCards": [_mx30_card(i, output, error_value, temp, volts)],
        }
        for i, (output, _, error_value, _, temp, volts) in enumerate(_MX30_PORTS)
    ],
}

# Capability strings as the firmware sent them: "|"-separated, "*" between
# width and height. The 71.93 list belongs to the SDI and internal inputs, the
# 85.00 list to DP and HDMI.
_MX30_FRAME_RATES_SDI = ("23.98|24.00|25.00|29.97|30.00|47.95|48.00|50.00|59.94|60.00|71.93|72.00"
                         "|75.00|100.00|119.88|120.00|143.86|144.00|240.00")
_MX30_FRAME_RATES_HDMI = ("23.98|24.00|25.00|29.97|30.00|47.95|48.00|50.00|59.94|60.00|72.00|75.00"
                          "|85.00|100.00|119.88|120.00|143.86|144.00|240.00")
_MX30_RESOLUTIONS_HDMI = ("800*600|1024*768|1152*864|1280*720|1280*800|1280*960|1440*900|1600*900"
                          "|1600*1200|1680*1050|1920*1080|1920*1200|2048*1080|2304*1152|2560*1080"
                          "|2560*1400|2560*1600|3840*1080")
_MX30_RESOLUTIONS_INTERNAL = ("800*600|1024*768|1152*864|1280*720|1280*800|1440*900|1600*900"
                              "|1600*1200|1680*1050|1920*1080|1920*1200|2048*1080|2048*1152"
                              "|2304*1024|2304*1152|2560*1080|2560*1440|2560*1600|2880*1800"
                              "|3840*1080")
# All twelve read 0 on every input. "infoFramLength" and "sourceTye" are the
# firmware's spellings (sic). That this is an HDR infoframe is REASONED from
# the field names.
_MX30_METADATA = {key: 0 for key in (
    "checksum", "infoFramLength", "infoFrameType", "infoFrameVersion", "maxContentLight",
    "maxFrameAvgLight", "maxLight", "maxMasterDisplayLight", "minMasterDisplayLight",
    "sourceTye", "whitePointX", "whitePointY",
)}


def _mx30_input(id_: int, name: str, type_: int, group: int, order: int, channel: int,
                **overrides) -> dict:
    """One input/sources entry: the 50 keys the unit returned, HDMI defaults."""
    entry = {
        # id is not a connector-type code across models (768 is "DP 1" type 5
        # on the MX40 fixture and "HDMI1.4 2" type 2 here); key on type or name.
        "id": id_, "name": name, "type": type_, "port": 0, "cardId": 0, "groupId": group,
        "sourceStatus": 0, "usable": True, "order": order, "sourceChannel": channel,
        "colorSpace": "RGB 4:4:4", "actualRefreshRate": 60,
        "actualResolution": {"width": 1920, "height": 1080},
        # A disconnected input reports its EDID default as actualResolution.
        "defaultEDID": {"isCustom": False, "refreshRate": 60,
                        "resolution": {"width": 1920, "height": 1080}},
        "bitDepth": 0, "dynamicRange": "SDR", "gamut": "", "hdrList": None, "range": 0,
        "scanMode": 0, "fiberPortLinkStatus": None, "inPhase": False, "ip": "",
        "isEdidCustom": False, "isSupportCapacities": False, "isSupportColorAdjust": True,
        "isSupportEDID": True, "isSupportHDR": False, "isSupportHDRParams": True,
        "isSupportIPAndPort": False, "isSupportInputOverride": True, "isSupportMetaData": False,
        "isSupportPQMaxCllChecked": True, "isSupportSPDIF": True,
        "maxCapacity": 0, "minCapacity": 0, "supportCapacities": None,
        "maxwidth": 4092, "maxheight": 4095, "minwidth": 800, "minheight": 600,
        "step": 4, "stepHeight": 1, "yuv420StepWidth": 8, "yuv420StepHeight": 2,
        "monitorSlotId": 0, "metaData": dict(_MX30_METADATA),
        "supportColorSpace": [0, 1, 2, 255],
        "supportFrameRate": _MX30_FRAME_RATES_HDMI, "supportResolution": _MX30_RESOLUTIONS_HDMI,
    }
    entry.update(overrides)
    return entry


_MX30_SDI = dict(isSupportEDID=False, isSupportSPDIF=False, maxwidth=4096, maxheight=4096,
                 supportFrameRate=_MX30_FRAME_RATES_SDI, supportResolution="1920*1080")
_MX30_EDID_3840x1080 = {"isCustom": False, "refreshRate": 60,
                        "resolution": {"width": 3840, "height": 1080}}

# Six inputs in the order the unit listed them. Type codes REASONED from each
# port's own name (2 HDMI 1.4, 3 HDMI 2.0, 4 DP 1.1, 7 3G-SDI) on this one
# unit; 224 with cardId 101 is the internal generator (REASONED). Two had
# signal: HDMI2.0 1 (the mode-1 layer's source) and the internal source, which
# reported sourceStatus 1 throughout the fifteen minutes it was watched.
MX30_LIKE_INPUTS = [
    _mx30_input(3, "3G-SDI 1", 7, 57, 4, 4, **_MX30_SDI),
    _mx30_input(4, "3G-SDI 2", 7, 58, 5, 5, **_MX30_SDI),
    _mx30_input(256, "DP1.1", 4, 32, 3, 1,
                actualResolution={"width": 3840, "height": 1080}, defaultEDID=_MX30_EDID_3840x1080),
    _mx30_input(768, "HDMI1.4 2", 2, 18, 2, 3,
                actualResolution={"width": 3840, "height": 1080}, defaultEDID=_MX30_EDID_3840x1080,
                hdrList=[255, 0, 1, 2]),
    _mx30_input(512, "HDMI2.0 1", 3, 25, 1, 2,
                sourceStatus=1, colorSpace="YCbCr 4:4:4", actualRefreshRate=50,
                actualResolution={"width": 1920, "height": 1080},
                defaultEDID={"isCustom": False, "refreshRate": 60,
                             "resolution": {"width": 3840, "height": 2160}},
                bitDepth=1, gamut="Rec.709", hdrList=[255, 0, 1, 2],
                isSupportHDR=True, isSupportMetaData=True, supportColorSpace=[0, 1, 2, 3, 255],
                supportResolution=_MX30_RESOLUTIONS_HDMI + "|3840*2160"),
    _mx30_input(25856, "internal-source", 224, 224, 0, 6,
                cardId=101, sourceStatus=1, colorSpace="YCbCr 4:4:4", actualRefreshRate=50,
                actualResolution={"width": 1280, "height": 768}, defaultEDID=_MX30_EDID_3840x1080,
                bitDepth=1, gamut="DCI-P3(D65)", isSupportSPDIF=False, maxwidth=8192, maxheight=8192,
                range=1, supportColorSpace=[0], supportFrameRate=_MX30_FRAME_RATES_SDI,
                supportResolution=_MX30_RESOLUTIONS_INTERNAL),
]

_MX30_NET_CONFIG = {"dhcp": False, "gateWay": "", "localIp": "", "netMask": "",
                    "targetIp": "", "targetPort": 0, "videoStreamIp": ""}
_MX30_LAYER_BORDER = {"color": {"r": 255, "g": 0, "b": 0}, "enable": False, "width": 0}

MX30_LIKE_SCREENS = {
    "screens": [{
        "screenID": MX30_LIKE_SCREEN_ID, "screenName": "Main", "screenIndex": 0,
        # The unit's screenGroupID was its screenID with a "g" appended.
        "screenGroupID": MX30_LIKE_SCREEN_ID + "g",
        "workingMode": 1, "masterFrameRate": 50, "lowLatency": False,
        "layoutMode": 0, "outputMode": 0, "ordinal": 0, "selectedPageID": 0,
        "cryptoCabinetNum": 0, "monitorSlotId": 0, "position": {"x": 0, "y": 0},
        # Format as the unit gave it; the value is a placeholder. The unit's
        # read a year behind the HTTP Date header (which agreed with UTC to
        # about 2 s); which clock was wrong when the screen was built is UNKNOWN.
        "createTime": "2025-01-01 00:00:00",
        "canvases": [{
            "canvasID": 2048, "backupType": 0, "canvasSerialNum": 0, "frequencyPhaseStatus": 0,
            "groups": None, "layoutLines": None, "inputID": 0, "isCustomSize": True,
            "ordinal": 0, "sizeMode": 0, "zorder": 0,
            # 5138 (0x1412) is also inputPort.ModelId and every /device/input
            # modelId. What it identifies -- controller, output card, mode --
            # is UNKNOWN; it is not the controller model until a second unit
            # shows a different value.
            "outputCardId": 8, "outputCardModeId": 5138,
            "maxFrameRate": 330.6,
            # size == rectSize == lastSize == the active mode's size below ==
            # the 12x6 cabinet extent (1536x768) -- for the active mode only;
            # mode 0's canvas is smaller than the wall.
            "size": {"width": 1536, "height": 768}, "rectSize": {"width": 1536, "height": 768},
            "lastSize": {"width": 1536, "height": 768},
            # Negative: the canvas and the layers share one frame. The cabinet
            # positions below are canvas-relative, from (0, 0).
            "position": {"x": -158, "y": -1072},
            "canvasInWorkingMode": [
                {"workingMode": 0, "size": {"width": 832, "height": 624}, "maxFrameRate": 480,
                 "isCustomSize": True},
                {"workingMode": 1, "size": {"width": 1536, "height": 768}, "maxFrameRate": 330.6,
                 "isCustomSize": True},
            ],
            # The only source of cabinet positions on this unit. connectID is
            # /device/cabinet.index (chain position); each output's 24 cabinets
            # ran a serpentine from x=1408 on the lower of its two rows.
            "cabinets": [
                {"cabinetID": MX30_LIKE_IDS[i], "outputID": output, "connectID": 0, "pageID": 0,
                 "angle": 0, "lockStatus": False,
                 "position": {"x": 1408, "y": y}, "size": {"width": 128, "height": 128}}
                for i, (output, y) in enumerate(((2048, 640), (2050, 384), (2052, 128)))
            ],
        }],
        # One entry per working mode. layers[].source is an input's groupId --
        # 25 is HDMI2.0 1, 224 the internal source -- not its id (neither value
        # is any input id; the groupId reading is REASONED from one discriminating
        # data point). That the mode-1 layer is what the wall was showing is
        # REASONED until an attended switch is watched.
        "layersInWorkingMode": [
            {"workingMode": 0, "layerLayoutMode": 1, "layers": [{
                "border": dict(_MX30_LAYER_BORDER), "canvasId": 0,
                "cut": {"enable": False, "rect": {"x": 0, "y": 0, "width": 64, "height": 77}},
                "followState": False, "gridId": 0, "id": 1, "layerInCanvasId": 2048,
                "layerIndex": 1, "layerSortId": 0, "lock": False,
                "position": {"x": -158, "y": -1072}, "scaler": {"width": 3840, "height": 1080},
                "source": 224, "sourceSize": {"width": 1280, "height": 768}, "zOrder": 1,
            }]},
            {"workingMode": 1, "layerLayoutMode": 0, "layers": [{
                "border": dict(_MX30_LAYER_BORDER), "canvasId": 0,
                "cut": {"enable": False, "rect": {"x": 0, "y": 0, "width": 1920, "height": 540}},
                "followState": False, "gridId": 10, "id": 65537, "layerInCanvasId": 0,
                "layerIndex": 1, "layerSortId": 0, "lock": False,
                "position": {"x": -158, "y": -1126}, "scaler": {"width": 1537, "height": 864},
                "source": 25, "sourceSize": {"width": 1920, "height": 1080}, "zOrder": 2147483646,
            }]},
        ],
        # Eight pages, exactly one shown (the selectedPageID). Names are synthetic.
        "pageInfos": [{"isShow": i == 0, "pageID": i, "pageName": f"Fixture page {i + 1}"}
                      for i in range(8)],
        # The selected input, in PascalCase. LogicId is its id and GroupId its
        # groupId, but InputDetailInfo.GroupId is 49 for the same port -- two
        # "GroupId"s, meaning UNKNOWN. InputSrcInfo carries signal detail that
        # input/sources does not; SourceFieldRate 5000 = 50.00 Hz is REASONED
        # (the register bus uses the same x100 encoding). FirmwareVersion is
        # all empty strings; nothing here names a controller firmware.
        "inputPort": {
            "CardId": 0, "EnableFrameRateCorrection": False,
            "FirmwareVersion": {"FileNum": "", "VersionName": "", "VersionNumber": "",
                                "VersionRemark": ""},
            "GroupId": 25, "HardwareID": "", "HwCardId": 0, "LogicId": 512, "MaxCapacityLimit": 0,
            "MetaData": dict(_MX30_METADATA), "ModelId": 5138, "MonitorSlotId": 0, "Order": 0,
            "InputDetailInfo": {
                "Capacities": "", "DefaultFrameRate": 0, "DefaultHeight": 2160, "DefaultWidth": 3840,
                "GroupId": 49, "HDCPVersion": 4, "HeightStepVal": 1, "InputType": 3,
                "InterfaceUseState": 0, "InterlacedInputSupport": 0, "IsSupportHDR": True,
                "IsSupportHDROverwrite": True, "IsSupportSPDIF": True, "MCUDeviceIndex": 0,
                "MCUInterface": 0, "MaxBand": 600000000, "MaxBandWidth": 6000, "MaxCapacity": 0,
                "MaxHeight": 4095, "MaxSourceDepth": 10, "MaxWidth": 4092, "MinBand": 25000000,
                "MinCapacity": 0, "MinHeight": 600, "MinWidth": 800, "PortIndex": 0,
                "SilkNumber": 1, "SlotId": 2, "SourceName": "HDMI2.0_1", "SourceNumber": 2,
                "SupportColorSpace": "0|1|2|3|255", "SupportFrameRate": _MX30_FRAME_RATES_HDMI,
                "SupportResolution": _MX30_RESOLUTIONS_INTERNAL + "|3840*2160",
                "Type": 1, "WidthStepVal": 4, "YcbcrSwapIn": 0,
            },
            "InputSrcInfo": {
                "ChannelId": 0, "ColorGamut": 2, "ColorSpaceType": 2, "CurrentSourceDepth": 1,
                "FiberNetConfig": {"backupNetConfig": dict(_MX30_NET_CONFIG),
                                   "masterNetConfig": dict(_MX30_NET_CONFIG)},
                "FiberPortLinkStatus": None, "HDRSDRInformation": 0, "HdcpState": 1, "IP": "",
                "InPhase": 0, "InputID": 512, "InputType": 3, "InterfaceUseState": 0,
                "InterlacedInputFlag": 0, "IsSupportHDR": 1, "OverWriteColorGamut": 2, "Port": 0,
                "Range": 0, "SourceDetInColPixel": 1920, "SourceDetInRowPixel": 1080,
                "SourceFieldRate": 5000, "SourceHBackPorch": 148, "SourceHFrontPorch": 528,
                "SourceHSyncPulse": 44, "SourceHTotal": 2640, "SourceStatus": 1,
                "SourceVBackPorch": 36, "SourceVFrontPorch": 4, "SourceVSyncPulse": 5,
                "SourceVTotal": 1125, "VideoFormat": 0, "XOffset": 0, "YOffset": 0,
            },
        },
    }],
    "screenGroups": [{"isShow": False, "name": "", "ordinal": 1,
                      "screenGroupID": MX30_LIKE_SCREEN_ID + "g"}],
}

# Two presets configured, neither active after the show (state false on both;
# REASONED from the MX40's observed state transition). Same keys as the MX40.
MX30_LIKE_PRESETS = {"screenPresets": [{
    "screenID": MX30_LIKE_SCREEN_ID,
    "presets": [
        {"name": "Preset A", "presetUUID": MX30_LIKE_PRESET_IDS[0], "sequenceNumber": 1,
         "state": False, "effectSwitch": 0, "outputData": False, "processingData": False,
         "screenData": False, "sourceData": True},
        {"name": "Preset B", "presetUUID": MX30_LIKE_PRESET_IDS[1], "sequenceNumber": 2,
         "state": False, "effectSwitch": 0, "outputData": False, "processingData": False,
         "screenData": True, "sourceData": True},
    ],
}]}

#: Present on the MX30 (HTTP 404 on the MX40 Pro). 65535 with an empty name.
MX30_LIKE_AUDIO = {"enable": False, "source": 65535, "sourceName": ""}
MX30_LIKE_BACKUP = {"master": "", "backup": "", "masterName": "", "backupName": ""}
#: Second unit, second model, same 3. Meaning UNKNOWN.
MX30_LIKE_HW_MODE = {"mode": 3}
MX30_LIKE_MULTIFUNC_CARDS: list = []
MX30_LIKE_SNMPSTATE = {"state": False}
#: First time exercised. The unit said 72; 3 here to match the lists above.
MX30_LIKE_CABINET_COUNT = {"list": [{"ScreenID": MX30_LIKE_SCREEN_ID, "CabinetCount": 3,
                                     "CabinetCountInBlackList": 0}]}

_MX30_DHCP = {"dhcp": False, "gateWay": "", "localIp": "", "netMask": ""}
_MX30_STREAM = {"targetIp": "", "targetPort": 0, "videoStreamIp": ""}
#: First time exercised. Trimmed to one of its six inputPortConfig entries (one
#: per input/sources entry on the unit; every one carried modelId 5138 and a
#: 7-8 character hardwareID of hex-ish digits and spaces, synthetic here).
MX30_LIKE_DEVICE_INPUT = {
    "inputPortConfig": [{
        "logicId": 512, "modelId": 5138, "hardwareID": "0 0 0001",
        "blackLevelInfo": {"highLight": {"r": 100, "g": 100, "b": 100, "w": 100},
                           "shadow": {"r": 100, "g": 100, "b": 100, "w": 100}},
        "capacity": 0, "colorGamut": 255, "colorSpaceType": 255,
        "cscParameter": {"contrastValue": 100, "hueValue": 0, "portId": 255, "saturationValue": 100},
        "dhcpConfig": {"backupDHCPConfig": dict(_MX30_DHCP), "masterDHCPConfig": dict(_MX30_DHCP)},
        "edidInfo": {"isCustom": False, "refreshRate": 50,
                     "resolution": {"width": 1920, "height": 1080}},
        "fiberPortLinkStatus": None,
        "hdrParameter": {"overrideHdrType": 255, "pqMaxCll": 1000, "pqMaxCllChecked": False,
                         "pqMode": 0, "realHdrType": 2},
        "isEdidSetting": False, "isLimitToFull": False, "range": 255, "sdpFileName": "",
        "sdpSourceInfo": {"colorGamut": 0, "colorSpaceType": 0, "hdrSdrInformation": 0, "range": 0,
                          "scanMode": 0, "sourceDepth": 0, "sourceDetInColPixel": 0,
                          "sourceDetInRowPixel": 0, "sourceFieldRate": 0},
        "videoStreamConfig": {"backupVideoStreamConfig": dict(_MX30_STREAM),
                              "masterVideoStreamConfig": dict(_MX30_STREAM)},
    }],
    "testPattern": {
        "mode": 0,
        "parameters": {"red": 4095, "green": 0, "blue": 0, "gray": 1023, "gradientStretch": 1,
                       "gridWidth": 8, "moveSpeed": 50, "state": 0, "x": 0, "y": 0, "z": 0},
        "txColorSpaceType": 0, "txHDRType": 0,
    },
}

MX30_LIKE_ABOUT = (
    "The COEX HTTP API as OBSERVED on one NovaStar MX30 -- firmware v1.5.1, reported by the "
    "operator and later read over SNMP (no HTTP field carries it) -- on 2026-09-26, read once after a show through HTTP GETs "
    "only: real response structure and key spellings, synthetic values. The unit drove 72 cabinets "
    "on three of its ten type-0 outputs (REASONED: the RJ45 ports; output type codes are "
    "unconfirmed). Three cabinets stand in for 72 -- the chain-position-0 cabinet of each populated "
    "output (2048, 2050, 2052) -- so the per-output errorBit[0].value (190/189/187) and the odd "
    "/device/cabinet.voltage at chain position 0 (34/57/235; 5 elsewhere) are represented, both of "
    "UNKNOWN meaning; screen/cabinet/count says 3 to match. Every id, UUID, name and remark is "
    "synthetic; the controller name is a made-up label because the unit's was a plain word too, "
    "from which no model can be read. {\"__http_status__\": 200, \"__empty_body__\": true} marks a "
    "path that answered HTTP 200 with Content-Length: 0, no Content-Type and no "
    "{code, data, message} envelope, so a JSON parse of the body fails. OBSERVED with curl -i on "
    "/api/v1/device, /api/v1/device/screen/displaymode and the made-up "
    "/api/v1/novasun-probe-no-such-path: on this firmware an unknown path answers exactly like an "
    "absent one, where the MX40 Pro answered 404 for absent documented endpoints. "
    "/api/v1/screen/cabinets, /properties and /displayeffect carry the same marker but were seen "
    "only through a client that returns {} for an empty body and for {\"code\": 0, \"data\": {}} "
    "alike: absent-or-empty, UNKNOWN which. Every one of the six responses seen raw with curl -i, "
    "empty or not, carried Vary: Origin, Access-Control-Allow-Origin: * and "
    "Access-Control-Allow-Credentials: true. "
    "/api/v1/device/input is trimmed to one of its six inputPortConfig entries. Nothing here says "
    "what another MX30 or another firmware does. Generated from tests/conftest.py (MX30_LIKE_API); "
    "tests/test_fixtures.py asserts they agree."
)

#: The whole fixture file, keyed by path, exactly as tests/fixtures/mx30_like_api.json holds it.
MX30_LIKE_API = {
    "__about__": MX30_LIKE_ABOUT,
    "/api/v1/device": MX30_LIKE_EMPTY_200,
    "/api/v1/device/audio": MX30_LIKE_AUDIO,
    "/api/v1/device/backup": MX30_LIKE_BACKUP,
    "/api/v1/device/cabinet": MX30_LIKE_CABINETS,
    "/api/v1/device/hw/mode": MX30_LIKE_HW_MODE,
    "/api/v1/device/input": MX30_LIKE_DEVICE_INPUT,
    "/api/v1/device/input/sources": MX30_LIKE_INPUTS,
    "/api/v1/device/monitor/info": MX30_LIKE_MONITOR_INFO,
    "/api/v1/device/multifunc-card/detailinfo": MX30_LIKE_MULTIFUNC_CARDS,
    "/api/v1/device/screen/displaymode": MX30_LIKE_EMPTY_200,
    "/api/v1/device/snmpstate": MX30_LIKE_SNMPSTATE,
    "/api/v1/novasun-probe-no-such-path": MX30_LIKE_EMPTY_200,
    "/api/v1/preset": MX30_LIKE_PRESETS,
    "/api/v1/screen": MX30_LIKE_SCREENS,
    "/api/v1/screen/cabinet/count": MX30_LIKE_CABINET_COUNT,
    "/api/v1/screen/cabinets": MX30_LIKE_EMPTY_200,
    "/api/v1/screen/displayeffect": MX30_LIKE_EMPTY_200,
    "/api/v1/screen/properties": MX30_LIKE_EMPTY_200,
}
