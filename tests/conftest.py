"""Shared test helpers.

The only thing here is the second-loopback problem, which is not worth solving
twice.
"""

from __future__ import annotations

import copy
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
# firmware v1.5.1 as reported by the operator at the time, read over SNMP as
# V1.5.1 later that day (tests/fixtures/mx30_snmp_walk.json), and served over
# HTTP as /api/v1/device/hw's hwVersion "V1.5.1" -- read once after a show on
# 2026-09-26 through HTTP GETs only, with every value that could identify the
# show replaced: three cabinets instead of 72, synthetic ids and UUIDs, a
# made-up controller name, empty receiving-card remarks, generic page and
# preset names. Field names, nesting, the list lengths that carry meaning (33
# outputs, 3 fans, 2 controller ports, 6 inputs, 8 pages) and the relations
# between endpoints are exact: that is what the parsers here and in crewbox are
# tested against.
#
# WITHDRAWN: this comment used to say that no field the HTTP API returned names
# the controller model or firmware. That was true only of the paths the first
# pass requested; it never requested /api/v1/device/hw, which names both
# (MX30_LIKE_HW below, OBSERVED that evening).
#
# The three cabinets are the chain-position-0 cabinet of each of the three
# populated outputs (2048, 2050, 2052; 24 cabinets each on the unit), so the
# per-output errorBit[0].value (190/189/187, constant within an output) and the
# odd /device/cabinet.voltage at chain position 0 (34/57/235 -- 5 on the other
# 69) are both represented. The meaning of either is UNKNOWN.
#
# Scope of every OBSERVED claim in this section: one MX30, one firmware, one
# afternoon (14:44Z-14:57Z), VMP attachment UNKNOWN -- except the constants
# from MX30_LIKE_HW onwards, which come from the same unit the same evening (a
# passive packet capture of NovaStar VMP opening against it, and an attended
# read-only test of display state) and say so where they are defined. Nothing
# here says what another MX30 or another firmware does.

#: The unit's monitor/info.name was a plain word -- no model in it.
#: The label here is made up to make the same point: a consumer reads a name
#: here, never a model. (That the word was operator-set is REASONED: the API
#: has a customname setter; nobody read the unit's settings.)
MX30_LIKE_NAME = "Stage left"

MX30_LIKE_SCREEN_ID = "{00000000-0000-0000-0000-000000000002}"
MX30_LIKE_PRESET_IDS = ("{00000000-0000-0000-0000-000000000003}",
                        "{00000000-0000-0000-0000-000000000004}")
#: /api/v1/device/hw deviceUUID: braced, like the screen and preset ids.
MX30_LIKE_DEVICE_UUID = "{00000000-0000-0000-0000-000000000005}"
#: Every UUID the fixture contains. The test for show data checks against it.
MX30_LIKE_UUIDS = (MX30_LIKE_SCREEN_ID,) + MX30_LIKE_PRESET_IDS + (MX30_LIKE_DEVICE_UUID,)
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
            # modelId. /api/v1/device/hw later gave name "MX30" with modelID
            # 5138 (OBSERVED), so 5138 is the MX30's model ID; that this
            # occurrence names the same thing is REASONED.
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

# --- The same MX30 that evening: identity, lock and display state ------------
#
# Everything from here to MX30_LIKE_ABOUT, and the announcement and websocket
# constants after MX30_LIKE_API, comes from the evening of 2026-09-26 rather
# than the afternoon pass above: a passive packet capture of NovaStar VMP
# opening against the same unit (VMP's own requests; novasun sent none of
# them; IPv4 only), and an attended read-only test an hour later in which
# novasun polled /api/v1/screen/output/display/state once a second and held
# the websocket while the operator froze and unfroze the wall from the front
# panel. Same unit, same firmware. The capture was reduced to masked skeletons
# before anything was written here; values below are synthetic unless a
# comment says they are readings.

#: The unit's MAC, synthetic (RFC 7042 documentation range). The
#: announcement's mac equalled the Ethernet source address and /device/hw's
#: mac (OBSERVED), lower-case and colon-separated, so the three share this
#: value. Deliberately not the SNMP walk's 00:00:5E:00:53:01: whether SNMP's
#: CONTROLLER_MAC equals this one was not recorded (UNKNOWN).
MX30_LIKE_MAC = "00:00:5e:00:53:30"
#: The unit's IP (RFC 5737 TEST-NET-1): the address it was reached at, as in
#: the SNMP walk's CONTROLLER_IP.
MX30_LIKE_IP = "192.0.2.30"
#: The client that wrote to the unit -- VMP's host in the capture.
MX30_LIKE_CLIENT_IP = "192.0.2.10"
#: /device/hw sn and /device/hw/versions controllerSystem.sn. They differed on
#: the unit (OBSERVED: 20 characters against 13 digits). Whether either equals
#: the SNMP walk's CONTROLLER_SERIAL was not recorded (UNKNOWN), so no two
#: synthetic serials match; do not join on them. The format of a synthetic
#: serial is not evidence of the real one's.
MX30_LIKE_HW_SN = "FIXTURE-SN-HW"
MX30_LIKE_SYSTEM_SN = "FIXTURE-SN-SYSTEM"
#: /device/hw randomPassword. The unit served an 8-digit string here to a
#: bare, unauthenticated GET (OBSERVED; identical across four reads; purpose
#: UNKNOWN; it appeared in no websocket push). No novasun code may log, store,
#: display or serialise the field. This value is obviously fake so that a
#: test can prove a consumer dropped it.
MX30_LIKE_RANDOM_PASSWORD = "00000000"

# capability.frameRateTable held 19 numbers, some fractional (count and
# float|int typing OBSERVED; the values were not recorded). These are the HDMI
# input's supportFrameRate list as numbers: a type-illustrative placeholder.
_MX30_HW_FRAME_RATES = [23.98, 24, 25, 29.97, 30, 47.95, 48, 50, 59.94, 60, 72, 75, 85, 100,
                        119.88, 120, 143.86, 144, 240]
_MX30_HW_SIZE = {"width": 0, "height": 0}
_MX30_HW_RANGE = {"min": 0, "max": 0, "step": 0}
_MX30_HW_SUBBOARD = {"type": 0, "sn": "", "modelId": 0}

#: GET /api/v1/device/hw, the identity endpoint: 5698 bytes on the unit, read
#: four times in 0.13 s, the reads differing only in memoryUsed and memoryFree.
#: Keys, nesting, value types, nulls and list lengths are OBSERVED. The values
#: are of three kinds: readings, every one of which MX30_LIKE_HW_OBSERVED
#: lists; synthetic identifiers (sn, mac, ip, customName, deviceUUID, uptime,
#: randomPassword); and type-correct placeholders -- False, 0, "", lists of
#: zeros -- for values that were not recorded. A placeholder False is not a
#: reading that the unit lacks a capability.
#:
#: name and modelID arrived together in one object, and firmware/list and
#: backcard/info repeated 5138: modelID 5138 is the MX30 (OBSERVED). That the
#: other 5138s in this fixture (device/input modelId, inputPort.ModelId,
#: canvases[].outputCardModeId) name the same thing is REASONED. Which of the
#: version strings is "the firmware" is REASONED/UNKNOWN: hwVersion carries the
#: "V1.5.1" that SNMP returns as CONTROLLER_FIRMWARE, and so do hw/versions'
#: xserver and firmware/list's deviceVersion.
MX30_LIKE_HW = {
    "name": "MX30",
    # The unit's customName and the websocket push's name were masked with
    # one token (REASONED: equal on the unit); the synthetic label here too.
    "customName": MX30_LIKE_NAME,
    "modelID": 5138, "sn": MX30_LIKE_HW_SN, "thirdPartySn": "", "thirdPartySerial": "",
    "mac": MX30_LIKE_MAC, "type": "G3.5", "netPortBandWidth": 0,
    "hwVersion": "V1.5.1", "swVersion": "1.0.0", "mcuVersion": "V1.0.0",
    "fpgaVersion": "V1.0.0.S1.T1.V9", "mcuVersionRemark": "", "fpgaVersionRemark": "",
    "softVersion": {"Package": "", "Version": "", "Architecture": "", "Maintainer": "",
                    "Description": ""},
    "configVersion": "V1.4.0.1",
    "ip": MX30_LIKE_IP, "WirelessIpAddress": "",
    # 3, as /device/hw/mode read in the afternoon (MX30_LIKE_HW_MODE). Meaning UNKNOWN.
    "mode": 3,
    "companyName": "",
    "capability": {
        "deviceType": 0, "systemLatency": False, "processing": False, "schedule": False,
        "rotation": False, "mirror": False, "3D": False, "multiUserThreeD": False,
        "multiUserThreeDNum": None, "threeDFrame": False, "threeDSource": None,
        "threeDFrameList": [], "hideThreeDRightOffset": False, "CabinetManagementTool": False,
        "HDR10": False, "inputBackup": False, "sync": False, "genLock": False,
        "frameRateMultiplication": False, "shutterSync": False, "photoelectricConversion": False,
        "lowLatency": False, "additionalFrameDelay": False, "blackLevel": False,
        "baseImageCount": 0, "inputZoom": False, "negPosSupport": False, "maxCapacity": 0,
        "presetImage": False, "abnormalImage": False, "customTestImage": False,
        "inputImageEcho": True, "outputImageEcho": True,
        "HDCP": False, "limitToFull": False,
        "highLights": False, "shadow": False, "signalTransmitter": False, "ABL": False,
        "EDE": False, "ITMO": False, "dynamicEngineIndependentControl": False,
        "colorReplace": False, "colorCalibration": False, "systemRestore": False, "3DLUT": False,
        "PIP": False, "CSC": False, "inputAutoSwitch": False, "curtainOverspread": False,
        "ipem": False, "hdmiModeSetting": False, "frameRemaping": False, "curve": False,
        "noVideoSignal": False, "maxWidth": 0, "maxHeight": 0, "presetImageMaxNum": 0,
        "outputBitDepth": [0, 0, 0], "bitDepth": 0, "internalBitDepths": [0, 0],
        "colorSpaceType": [0, 0, 0, 0], "colorGamutType": [0, 0, 0, 0], "mosaic": {"mode": None},
        "presetImageSize": dict(_MX30_HW_SIZE),
        "presetImageSetInfo": {"maxWidth": 0, "maxHeight": 0},
        "additionalFrameDelayRange": dict(_MX30_HW_RANGE),
        "frameRateMultiplicationRange": dict(_MX30_HW_RANGE),
        "threeDRightEyeOffsetRange": dict(_MX30_HW_RANGE),
        # Every *Supported flag read false (OBSERVED), though the unit served
        # fan, temperature and voltage readings over monitor/info and SNMP.
        "hwMonitor": {"armSupported": False, "fanSupported": False, "fpgaSupported": False,
                      "inputSubCardSupported": False, "mainBordSupported": False,
                      "netWorkSubCardSupported": False, "opticalCardSupported": False},
        "virtualMode": None, "videoController": False,
        "defaultCurtainSize": dict(_MX30_HW_SIZE),
        "maxCurtainSize": dict(_MX30_HW_SIZE), "minCurtainSize": dict(_MX30_HW_SIZE),
        "layerNumberLimit": 0,
        "supportSizeList": {"mode": [dict(_MX30_HW_SIZE), dict(_MX30_HW_SIZE)]},
        "maxCurtainArea": 0, "maxCurtainCapacity": 0, "maxLayerArea": 0,
        "modifyCurtainSize": False, "modifyLayerCoordinate": False, "modifyLayerSize": False,
        "supportLayerCut": False, "supportLayerBorder": False, "supportLayerZOrder": False,
        "minLayerSize": dict(_MX30_HW_SIZE), "maxLayerSize": dict(_MX30_HW_SIZE),
        "supportLayerStretch": False, "supportLayerOriginSize": False,
        "supportLayerScreenSize": False, "supportLayerFollow": False, "blackLevelOutPutBit": 0,
        "cabinetsPainter": False, "maxSourceDefaultWidth": 0, "maxSourceDefaultHeight": 0,
        "channelNumber": 0, "presetNameCheck": False, "customGamutNameChange": False,
        "customRate": False, "supportSourcecutTypes": None, "minSourcecutResolutionProduct": 0,
        "minSourcecutWidth": 0, "minSourcecutHeight": 0, "cinemaTxTest": False,
        "xyzTxTestPattern": False, "supportArtNetProtocol": False, "minFrameOffset": 0,
        "maxFrameOffset": 0, "supportHDRSourceTypes": "", "upgradeMaxTimeout": 0,
        "ncpManager": False,
        "layout": {"mode": [
            {"value": 0, "comment": "", "minCurtainSize": dict(_MX30_HW_SIZE),
             "step": dict(_MX30_HW_SIZE)}
            for _ in range(2)
        ]},
        "presetNumber": 0, "maxScreenNumber": 0, "switchSourceType": 0, "audioSources": None,
        "hwScreenNeedHandleProcessing": False, "supportCable": False, "systemBackup": False,
        "controllerPosition": False, "allowChangeWorkMode": True, "curtainManage": False,
        "dP14Mode": False, "internalSource": False, "outputSyncSource": False,
        "outputSyncInner": False, "phaseShift": False, "cabinetsStore": False,
        "controllerMaintenance": False, "cabinetMaintenance": False, "preset": False,
        "artNet": True, "artNetMaxStartAddressList": [0, 0, 0, 0], "snmp": True,
        "userManual": False, "shortcutKey": False, "isSupportModifyOpticalMode": False,
        "frameRateTable": list(_MX30_HW_FRAME_RATES), "supportPxToPx": False, "monitorType": 0,
        "disableSetSystemTime": False, "lineHWScreenType": 0, "layerDelete": False,
        "imageEnhance": False, "supportColorBeacon": False, "supportRGBWRatioAdjust": False,
        "isSupportGamutAsync": False, "correctSpeedVersion": "", "NTP": True,
        "mfCardUpdate": False, "deviceLocation": False, "smartHWScreen": False,
        "firmwarePainter": False, "sdi12GCustomHDR10": False, "dPCustomHDR10": False,
        "isSupportCloud": False, "capabilityVersion": "V4.1.0",
        "isSupportBatchCorrectionSwitch": False, "isSupportMvr": False,
        "isUpgradeHttpMode": False,
    },
    "deviceWorkMode": 0,
    "IpNetmask": "", "IpGateway": "", "ethMode": "", "hostName": "", "Dns": None,
    "dhcp": False, "configIP": "", "Series": 0,
    # The unit's uptime equalled the websocket push's runtime five seconds
    # later (OBSERVED once; that they are one counter is REASONED). Here it is
    # MX30_LIKE_MONITOR_INFO's runtime.
    "uptime": 21000, "memorySize": 0, "memoryUsed": 0, "memoryFree": 0,
    "subBoardInfo": {"inputSn": dict(_MX30_HW_SUBBOARD), "sasaSn": dict(_MX30_HW_SUBBOARD),
                     "sasbSn": dict(_MX30_HW_SUBBOARD), "qsfpSn": dict(_MX30_HW_SUBBOARD)},
    "customIp": "", "deviceUUID": MX30_LIKE_DEVICE_UUID, "groupName": "",
    "isAllowSingleDev": False, "supportInputSubCardNum": 0, "supportOutputSubCardNum": 0,
    "encipher": {"vendorID": 0, "authState": 0, "authStartTime": "", "authEndTime": "",
                 "isOverRange": False},
    "randomPassword": MX30_LIKE_RANDOM_PASSWORD,
}

#: Every value in MX30_LIKE_HW that is a reading from the unit (OBSERVED), by
#: dotted path. Nulls and empty lists are readings too: the masked skeleton
#: kept them. Everything not listed is synthetic or a placeholder.
MX30_LIKE_HW_OBSERVED = {
    "name": "MX30", "modelID": 5138, "type": "G3.5",
    "hwVersion": "V1.5.1", "swVersion": "1.0.0", "mcuVersion": "V1.0.0",
    "fpgaVersion": "V1.0.0.S1.T1.V9", "configVersion": "V1.4.0.1", "softVersion.Version": "",
    "thirdPartySn": "", "thirdPartySerial": "", "mode": 3, "deviceWorkMode": 0, "Dns": None,
    "encipher.authState": 0,
    "capability.capabilityVersion": "V4.1.0", "capability.snmp": True,
    "capability.artNet": True, "capability.NTP": True, "capability.inputImageEcho": True,
    "capability.outputImageEcho": True, "capability.allowChangeWorkMode": True,
    "capability.multiUserThreeDNum": None, "capability.threeDSource": None,
    "capability.threeDFrameList": [], "capability.mosaic.mode": None,
    "capability.virtualMode": None, "capability.supportSourcecutTypes": None,
    "capability.audioSources": None,
    **{f"capability.hwMonitor.{flag}": False for flag in (
        "armSupported", "fanSupported", "fpgaSupported", "inputSubCardSupported",
        "mainBordSupported", "netWorkSubCardSupported", "opticalCardSupported")},
}

#: GET /api/v1/device/hw/versions (355 bytes on the unit). Readings except
#: controllerSystem.sn (synthetic; it differed from /device/hw's sn, OBSERVED)
#: and uBoot (not recorded; placeholder). The mainBoard strings were all empty
#: and slots an empty list (OBSERVED).
MX30_LIKE_HW_VERSIONS = {
    "controllerSystem": {"hardWareVersion": "A3", "system": "V1.5.1.B2", "uBoot": "",
                         "bsp": "V1.5.0.2025070301", "xserver": "V1.5.1", "lcd": "V1.5.1.T6",
                         "upgradeService": "V1.5.0", "sn": MX30_LIKE_SYSTEM_SN},
    "mainBoard": {"hardware": "", "mcu": "", "fpgaA": "", "fpgaB": "", "fpga": ""},
    "frontPanel": {"hardware": "A1"},
    "slots": [],
}

#: GET /api/v1/device/hw/lock before any control application held the unit:
#: exactly as read (58 bytes with the envelope, twice). VMP then took the
#: lock with PUT /api/v1/device/hw/lock {"appids": [...]} and the websocket
#: pushed deviceLockChange {"locked": 1, "ip": <the requester>}. This GET was
#: never made while the lock was held, so its locked shape is UNKNOWN
#: (REASONED: locked 1 and the holder's IP, as the push carries). A read made
#: after VMP quit returned this again (reported by the operator; not in the
#: capture). Read-only, it shows whether a control application holds the
#: unit and from where. The lock did not stop a front-panel freeze (REASONED);
#: whether it stops other API clients is UNKNOWN.
MX30_LIKE_HW_LOCK = {"locked": 0, "ip": ""}

#: GET /api/v1/screen/output/display/state while the wall was live: exactly
#: as read (140 bytes with the envelope, twice). This IS the display state:
#: displayState[].displayMode, per canvasID, read 0 while the wall was live and
#: 2 for the whole of an attended front-panel freeze, polled at 1 Hz (OBSERVED;
#: the first poll after the websocket's push saw it 0.5 s later), and 1 through
#: an attended front-panel blackout later the same evening (OBSERVED once; it
#: was REASONED from the documented COEX enum until then). canvasID 2048 is the screen's only canvas, the id the websocket's
#: canvasDisplayModeChange carries. mappingState's meaning is UNKNOWN. The
#: afternoon pass polled /api/v1/device/screen/displaymode (an empty 200) and
#: never this path; its conclusion that a frozen wall cannot be read is withdrawn.
MX30_LIKE_DISPLAY_STATE = {
    "mappingState": [{"canvasID": 2048, "enable": False}],
    "displayState": [{"canvasID": 2048, "displayMode": 0}],
}

MX30_LIKE_ABOUT = (
    "The COEX HTTP API as OBSERVED on one NovaStar MX30 -- firmware v1.5.1: reported by the "
    "operator, read over SNMP, and served over HTTP as /api/v1/device/hw hwVersion \"V1.5.1\" -- "
    "on 2026-09-26: real response structure and key spellings, synthetic values. An earlier "
    "version of this note said no HTTP field carries the firmware; that is withdrawn -- the "
    "afternoon pass never requested /api/v1/device/hw. Most paths were read once, that afternoon, "
    "after a show, through HTTP GETs only. The unit drove 72 cabinets "
    "on three of its ten type-0 outputs (REASONED: the RJ45 ports; output type codes are "
    "unconfirmed). Three cabinets stand in for 72 -- the chain-position-0 cabinet of each populated "
    "output (2048, 2050, 2052) -- so the per-output errorBit[0].value (190/189/187) and the odd "
    "/device/cabinet.voltage at chain position 0 (34/57/235; 5 elsewhere) are represented, both of "
    "UNKNOWN meaning; screen/cabinet/count says 3 to match. Every id, UUID, serial, MAC, IP, "
    "operator-set name and remark is synthetic; the controller name is a made-up label because "
    "the unit's was a plain word too, from which no model can be read. {\"__http_status__\": 200, "
    "\"__empty_body__\": true} marks a "
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
    "/api/v1/device/input is trimmed to one of its six inputPortConfig entries. "
    "Four paths come from the same unit that evening, from a passive packet capture of NovaStar "
    "VMP opening against it (VMP's own GETs; novasun sent none of them): /api/v1/device/hw, "
    "/api/v1/device/hw/versions, /api/v1/device/hw/lock and /api/v1/screen/output/display/state. "
    "/api/v1/device/hw is the identity endpoint: name \"MX30\" and modelID 5138 in one object, so "
    "5138 is the MX30 (OBSERVED; that the other 5138s here name the same thing is REASONED), with "
    "hwVersion, sn and mac. Its keys, types, nulls and list lengths are OBSERVED, but only the "
    "values listed in tests/conftest.py MX30_LIKE_HW_OBSERVED are readings: sn, mac, ip, "
    "customName, deviceUUID and uptime are synthetic, and every other value is a type-correct "
    "placeholder (false, 0, \"\", zeros) for a value that was not recorded -- a placeholder false "
    "is not a reading that the unit lacks a capability. /api/v1/device/hw also carries "
    "randomPassword, an 8-digit string the unit served to a bare, unauthenticated GET (OBSERVED; "
    "purpose UNKNOWN). Here it is \"00000000\", an obviously fake value, so a test can prove it "
    "was dropped: a consumer must drop randomPassword before it logs, stores, displays or "
    "serialises anything read from this endpoint. /api/v1/device/hw/versions: controllerSystem.sn "
    "differed from /device/hw's sn on the unit (OBSERVED; both synthetic here, and neither is the "
    "SNMP walk's serial); uBoot was not recorded (placeholder). /api/v1/device/hw/lock is "
    "{\"locked\": 0, \"ip\": \"\"} exactly as read before VMP took the lock with a PUT; it was never "
    "read while the lock was held, so its locked shape is UNKNOWN (REASONED: locked 1 and the "
    "holder's IP, as the websocket's deviceLockChange carries). Read with GET only, it shows "
    "whether a control application holds the unit. /api/v1/screen/output/display/state is exactly "
    "as read while the wall was live, and it IS the display state: displayState[].displayMode per "
    "canvasID read 0 while the wall was live and 2 for the whole of a front-panel freeze "
    "(OBSERVED in an attended read-only test later that evening, in which novasun polled this "
    "path at 1 Hz), so a frozen wall is readable over a plain GET. "
    "1 = blackout is OBSERVED too, once: displayMode read 1 through an attended front-panel "
    "blackout later still that evening (it was REASONED from the documented COEX display-mode "
    "enum until then). mappingState's meaning is UNKNOWN. The afternoon pass polled "
    "/api/v1/device/screen/displaymode (the empty 200 above) and missed this path, which is why a "
    "frozen wall was once recorded as unobservable; that conclusion is withdrawn. The same state "
    "is pushed on the websocket (tests/fixtures/mx30_websocket_events.jsonl), and the unit's "
    "unsolicited UDP announcement is tests/fixtures/mx30_announcement.json. Nothing here says "
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
    "/api/v1/device/hw": MX30_LIKE_HW,
    "/api/v1/device/hw/lock": MX30_LIKE_HW_LOCK,
    "/api/v1/device/hw/mode": MX30_LIKE_HW_MODE,
    "/api/v1/device/hw/versions": MX30_LIKE_HW_VERSIONS,
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
    "/api/v1/screen/output/display/state": MX30_LIKE_DISPLAY_STATE,
    "/api/v1/screen/properties": MX30_LIKE_EMPTY_200,
}


# --- The MX30's announcement --------------------------------------------------
#
# From the evening packet capture (see MX30_LIKE_HW). The unit broadcast this
# unprompted, before, during and after VMP's session; novasun heard it only
# because the capture was not bound to one port.

#: UDP destination ports, in the order of every burst (OBSERVED).
MX30_LIKE_ANNOUNCEMENT_PORTS = (54622, 54623, 54624, 54700)
#: UDP source port of every datagram (OBSERVED; whether it survives a reboot is UNKNOWN).
MX30_LIKE_ANNOUNCEMENT_SOURCE_PORT = 54650

#: The whole UDP payload: 96 bytes of ASCII JSON, no header, no terminator,
#: no checksum. Byte for byte as the unit sent it except the MAC, which is
#: synthetic and the same length, so every offset holds.
MX30_LIKE_ANNOUNCEMENT_PAYLOAD = (
    '{"data":[{"apiPort":"8001","mac":"' + MX30_LIKE_MAC
    + '","authType":0,"workMode":0,"https":"9001"}]}'
)

MX30_LIKE_ANNOUNCEMENT_ABOUT = (
    "The unsolicited UDP announcement of one NovaStar MX30 (hwVersion V1.5.1), as OBSERVED on "
    "2026-09-26 in a passive IPv4 packet capture: real byte layout, synthetic MAC and IPs. "
    "\"payload\" is the whole UDP payload as a string: exactly 96 bytes of ASCII JSON with no "
    "header, no terminator and no application checksum, byte-identical in every datagram (468 "
    "over six minutes: before VMP opened, while VMP held the unit's lock, through a front-panel "
    "freeze and after VMP quit). Keys, order, compact spacing and value types are OBSERVED: "
    "apiPort and https are strings -- the HTTP API port and an HTTPS port (whether anything "
    "listens on 9001 is UNKNOWN); mac is a lower-case colon-separated string equal to the "
    "Ethernet source address and to GET /api/v1/device/hw's mac (OBSERVED); authType and "
    "workMode are integers, only 0 seen, meanings UNKNOWN (pairing them with /device/hw's "
    "encipher.authState and deviceWorkMode is REASONED and weak); data is a one-element array "
    "(whether it can hold more is UNKNOWN). No model, name, serial, version, IP, lock or display "
    "state is carried, so an unchanged payload says nothing about the unit's state. A listener "
    "learns the unit's IP (from the IP header only), MAC, API port and HTTPS port; one GET of "
    "/api/v1/device/hw then gives model, name, serial and version. value_spans gives the first "
    "and last byte offset, inclusive, of each value in the payload, quotes included for strings "
    "(OBSERVED on the real payload; a MAC is always 17 characters, so they hold here). "
    "Wire (OBSERVED): from UDP source port 54650 to the subnet-directed broadcast (Ethernet "
    "broadcast), one datagram to each of UDP 54622, 54623, 54624 and 54700, always in that order, "
    "in a burst spanning at most 0.97 ms; a burst every 3 s (interval mean 3.0024 s, standard "
    "deviation 6.3 ms, no gaps in 117 bursts); DF set, TTL 64. The phase drifted smoothly, about "
    "+1.8 ms a burst, with no reset when VMP connected or quit (OBSERVED), which suggests a "
    "sleep-style loop that no client triggers (REASONED). VMP sent no discovery probe of its own "
    "on IPv4 and connected to "
    "the announced apiPort 5 ms after a burst (REASONED, strongly: VMP finds COEX units from this "
    "announcement); which of the four ports it listens on is UNKNOWN. A receive-only socket bound "
    "to any of the four ports hears it without transmitting anything, but only inside the "
    "broadcast domain (REASONED: a subnet-directed broadcast is not forwarded between subnets "
    "by default). Whether other MX30s, "
    "other firmware or the MX40 Pro announce is UNKNOWN; every earlier listen in this project was "
    "bound to UDP 3800 only and could not have heard it. The announcement tracks the controller, "
    "not the wall: in a later attended session it continued every 3 s with every output line "
    "unplugged and stopped at once when the unit was powered off (OBSERVED). source_ip, "
    "destination_ip and the MAC "
    "are synthetic (RFC 5737 TEST-NET-1, RFC 7042 documentation range); source_ip and the MAC are "
    "tests/fixtures/mx30_like_api.json's /api/v1/device/hw ip and mac. Nothing here says what "
    "another MX30, "
    "another model or another firmware does. Generated from tests/conftest.py "
    "(MX30_LIKE_ANNOUNCEMENT); tests/test_fixtures.py asserts they agree."
)

#: tests/fixtures/mx30_announcement.json, exactly.
MX30_LIKE_ANNOUNCEMENT = {
    "__about__": MX30_LIKE_ANNOUNCEMENT_ABOUT,
    "payload": MX30_LIKE_ANNOUNCEMENT_PAYLOAD,
    # [first, last] byte offsets, inclusive, of each value, quotes included.
    "value_spans": {"apiPort": [20, 25], "mac": [33, 51], "authType": [64, 64],
                    "workMode": [77, 77], "https": [87, 92]},
    "source_ip": MX30_LIKE_IP,
    # The subnet-directed broadcast of a /24; the unit's netmask was not recorded.
    "destination_ip": "192.0.2.255",
    "source_port": MX30_LIKE_ANNOUNCEMENT_SOURCE_PORT,
    "destination_ports": list(MX30_LIKE_ANNOUNCEMENT_PORTS),
    "interval_s": 3.0,
}


# --- The MX30's websocket -----------------------------------------------------
#
# Server pushes on /api/v1/websocketchannel (port 8001, plain ws://), from the
# evening capture (VMP's connection, VMP's hello sent) and the attended test
# (novasun's connection: the upgrade and pongs only, no text frame). One
# illustrative timeline carries events from both.

#: A client's Application-Id header value (VMP's, in the capture). The unit
#: attributes a client's write to it. 36-character UUID: the length is
#: OBSERVED (the frames' byte counts), the canonical form REASONED.
MX30_LIKE_APP_ID = "Launcher_00000000-0000-0000-0000-000000000006"
#: The unit's own front-panel application, seen with ip 127.0.0.1 (OBSERVED;
#: the same id both times).
MX30_LIKE_FRONT_PANEL_APP_ID = "LCDAPP_00000000-0000-0000-0000-000000000007"
#: Every unbraced UUID the websocket fixture contains.
MX30_LIKE_APP_UUIDS = tuple(app.split("_", 1)[1]
                            for app in (MX30_LIKE_APP_ID, MX30_LIKE_FRONT_PANEL_APP_ID))

# Synthetic device clock: epoch seconds of 2000-01-01T00:00:00Z. The format of
# each timestamp is OBSERVED; no value is.
_MX30_WS_EPOCH = 946684800


def _mx30_ws_sensor(value) -> dict:
    # Key order as the websocket sends it (monitor/info's differs; JSON does not care).
    return {"value": value, "status": 0, "name": "", "nameEn": ""}


def _mx30_event(sender: str, event_type: str, data: dict) -> dict:
    return {"eventData": data, "eventSender": sender, "eventType": event_type}


_MX30_WS_CONTROLLER = {
    "name": MX30_LIKE_NAME,
    "runtime": MX30_LIKE_MONITOR_INFO["runtime"],
    "totalRuntime": MX30_LIKE_MONITOR_INFO["totalRuntime"],
    "mainBoardTemperature": {"value": 32, "status": 0, "name": "Main_board Temperature",
                             "nameEn": "Main_board Temperature"},
    "mainBoardVoltage": {"value": 11.56, "status": 0, "name": "Main_board Voltage",
                         "nameEn": "Main_board Voltage"},
    "backupStatus": {"status": 0, "errCode": 108, "minNormalValue": 0, "maxNormalValue": 0},
    "fanInfos": [
        {"fanSpeed": fan["fanSpeed"], "fanType": fan["fanType"], "fanShowType": 0,
         "fanName": fan["fanName"], "fanNameEn": fan["fanNameEn"], "status": 0}
        for fan in MX30_LIKE_MONITOR_INFO["fanInfos"]
    ],
    "voltageInfos": None, "temperatureInfos": None,
    "powerMonitorInfos": [{"powerID": 0, "status": 0}],
    "controllerPortMonitorInfos": [{"controllerPortID": 0, "status": 0},
                                   {"controllerPortID": 1, "status": 2}],
    "imbLinkStatus": {"linkStatus": False, "status": 0},
    "timestamp": "2000-01-01 00:00:03",
}

# One cabinet per push; this is the fixture's chain-position-0 cabinet on 2050.
_MX30_WS_CABINET = {
    "cabinetID": MX30_LIKE_IDS[1], "rvCardID": MX30_LIKE_IDS[1],
    "netPortIndex": 2050, "cabinetIndex": 0, "runtime": 0, "totalRuntime": 0,
    "temperature": _mx30_ws_sensor(43), "voltage": _mx30_ws_sensor(4.2),
    "humidity": _mx30_ws_sensor(0),
    "errorBit": [{"value": 189, "type": 0, "status": 1}, {"value": 0, "type": 1, "status": 0}],
    "signalInterruptCount": 0, "backupStatus": {"mode": 0, "status": 0},
    "nextCabinetLinkStatus": {"linkStatus": True, "status": 0},
    "phyTemperature": {"phy1": _mx30_ws_sensor(0), "phy2": _mx30_ws_sensor(0)},
    "moduleInfos": None,
    # cabinetID 0 always; its voltage moved with the card's.
    "cabinetMonitorInfo": {"cabinetID": 0, "power": None, "temperature": _mx30_ws_sensor(0),
                           "humidity": _mx30_ws_sensor(0), "smoke": _mx30_ws_sensor(0),
                           "voltage": _mx30_ws_sensor(4.2)},
    "timestamp": "2000-01-01 00:00:03",
}

#: Every line of tests/fixtures/mx30_websocket_events.jsonl after the first:
#: {"t": seconds after the 101 response, "event": one text frame's JSON}.
MX30_LIKE_WEBSOCKET_EVENTS = [
    {"t": 5.06, "event": _mx30_event("monitor", "controllerRealTimeInfoChange",
                                     _MX30_WS_CONTROLLER)},
    {"t": 5.16, "event": _mx30_event("monitor", "cabinetRealTimeInfoChange", _MX30_WS_CABINET)},
    # A client's write (VMP's PUT of /api/v1/device/hw/systemtime in the capture).
    {"t": 13.5, "event": _mx30_event("device", "deviceLastOperatorChange", {
        "ip": MX30_LIKE_CLIENT_IP, "appID": MX30_LIKE_APP_ID, "timestamp": _MX30_WS_EPOCH + 12})},
    # A client's PUT of /api/v1/device/hw/lock.
    {"t": 13.556, "event": _mx30_event("device", "deviceLockChange", {
        "locked": 1, "ip": MX30_LIKE_CLIENT_IP})},
    {"t": 20.52, "event": _mx30_event("monitor", "cabinetsRuntimeInfoChange", {
        "rvCardMonitorInfos": [
            {"cabinetID": card["cabinetID"], "rvCardID": card["rvCardID"],
             "runtime": card["runtime"], "totalRuntime": card["totalRuntime"]}
            for card in MX30_LIKE_MONITOR_INFO["rvCardsRuntime"]
        ]})},
    # A front-panel freeze and its release: each display change ~103 ms after
    # the operator event that names the actor.
    {"t": 36.4, "event": _mx30_event("device", "deviceLastOperatorChange", {
        "ip": "127.0.0.1", "appID": MX30_LIKE_FRONT_PANEL_APP_ID,
        "timestamp": _MX30_WS_EPOCH + 34})},
    {"t": 36.503, "event": _mx30_event("device", "canvasDisplayModeChange", {
        "canvasIDs": [2048], "value": 2})},
    {"t": 58.9, "event": _mx30_event("device", "deviceLastOperatorChange", {
        "ip": "127.0.0.1", "appID": MX30_LIKE_FRONT_PANEL_APP_ID,
        "timestamp": _MX30_WS_EPOCH + 57})},
    {"t": 59.003, "event": _mx30_event("device", "canvasDisplayModeChange", {
        "canvasIDs": [2048], "value": 0})},
]

MX30_LIKE_WEBSOCKET_ABOUT = (
    "Server-to-client events on the websocket of one NovaStar MX30 (hwVersion V1.5.1), "
    "/api/v1/websocketchannel on the HTTP API port 8001, plain ws:// -- as OBSERVED on 2026-09-26: "
    "real envelope, event types, key spellings, nesting and value types; synthetic values and "
    "times. Sources: a passive packet capture of NovaStar VMP connecting (VMP's websocket; "
    "novasun sent nothing on it), and an attended test the same evening in which novasun held a "
    "websocket for about a minute while the operator froze and unfroze the wall from the front "
    "panel. Line 1 is this note. Every other line is {\"t\": seconds after the 101 response, "
    "\"event\": the JSON object one text frame carried}. The offsets are synthetic, one "
    "illustrative timeline carrying events from both sessions; the spacings that were OBSERVED are "
    "kept (a cabinet push about 100 ms after a controller push; a display change about 103 ms "
    "after its operator event). Upgrade (OBSERVED): GET /api/v1/websocketchannel with Host, "
    "Connection, Upgrade, Sec-WebSocket-Key and Sec-WebSocket-Version 13 only -- no Origin, "
    "authentication, cookie, subprotocol, extension or Application-Id -- answered 101 Switching "
    "Protocols; permessage-deflate was not negotiated and no frame set an RSV bit. Keepalive "
    "(OBSERVED): the server sends an empty ping every 1.000 s and the client answers each with an "
    "empty masked pong; they are not listed here. No binary frame was seen, and VMP's session "
    "ended with a bare TCP close, no close frame in either direction. Hello: VMP sends one text "
    "frame, its Application-Id \"Launcher_<uuid>\", 3 ms after "
    "the 101. Pushes arrive without any hello (OBSERVED): in the attended test novasun sent no "
    "text frame at all, and controller telemetry, the front-panel deviceLastOperatorChange events "
    "and both canvasDisplayModeChange events still arrived. deviceLockChange and a "
    "client-attributed deviceLastOperatorChange were seen only on VMP's connection, so whether "
    "they arrive without the hello is UNKNOWN. Envelope (OBSERVED, every event): "
    "{\"eventData\": {...}, \"eventSender\": \"monitor\" or \"device\", \"eventType\": str}, "
    "serialised compactly (canvasDisplayModeChange is exactly 105 bytes on the wire). Nothing is "
    "replayed on connect: canvasDisplayModeChange was not pushed when VMP connected (OBSERVED "
    "once), so a subscriber reads GET /api/v1/screen/output/display/state for the current value. "
    "Cadence (OBSERVED on VMP's connection, 4 min 20 s): "
    "controllerRealTimeInfoChange every 10 s on a free-running grid, plus one extra a minute, the "
    "only one to advance runtime and totalRuntime (by 60); cabinetRealTimeInfoChange 93-110 ms "
    "after a controller push, 0-2 per tick, one cabinet each, only 5 of 72 cabinets ever "
    "appearing and each repeat differing only in a temperature or voltage (REASONED: "
    "change-driven); cabinetsRuntimeInfoChange every 60 s with one entry per receiving card (72 on "
    "the unit, 3 here, in a stable order that is not the cabinet order; runtime one constant on "
    "every card, meaning UNKNOWN); device events when something changes. "
    "canvasDisplayModeChange.value: 0 normal and 2 freeze are OBSERVED (two front-panel freezes, "
    "one in each session; in the attended one the HTTP display/state read 2 throughout). No "
    "blackout happened in either session, so in this file 1 = blackout is REASONED from the "
    "documented COEX display-mode enum; a later attended session the same evening OBSERVED it "
    "(value 1 pushed at a front-panel blackout, and display/state read 1 throughout). "
    "canvasIDs holds the canvasID the rest of the API keys on (2048, the screen's only canvas). "
    "Each display change came about 103 ms after a deviceLastOperatorChange naming the actor "
    "(OBSERVED four times). The front panel appears as ip \"127.0.0.1\" with appID "
    "\"LCDAPP_<uuid>\" (OBSERVED); a client's write as the client's IP with the Application-Id "
    "header its HTTP request carried (REASONED: VMP's PUT of /api/v1/device/hw/systemtime drew "
    "one, its PUTs of /device/picture and /hw/lock drew none). In a later attended session every "
    "write was preceded by one, and novasun's own client, which sends no Application-Id, "
    "appeared with its IP and an empty appID (OBSERVED). deviceLockChange "
    "{\"locked\": 1, \"ip\": the requester's IP (REASONED)} followed a PUT of "
    "/api/v1/device/hw/lock. No locked 0 push was ever seen: after VMP's websocket closed, a GET of "
    "/api/v1/device/hw/lock read locked 0 (reported by the operator), so the release mechanism is "
    "UNKNOWN. deviceLastOperatorChange's timestamp is epoch seconds, and the controller and "
    "cabinet events' a device-local \"YYYY-MM-DD HH:MM:SS\" string (formats OBSERVED; values "
    "synthetic, 2000-01-01). No health field moved during the capture: no status, errorBit, "
    "signalInterruptCount, link or backup field changed; errorBit[0] is {value nonzero, type 0, "
    "status 1} on every card and is not a health flag (meaning UNKNOWN), and "
    "controllerPortMonitorInfos[1].status 2 is of UNKNOWN meaning. cabinetID and rvCardID are "
    "integers here: the masked evidence kept their length (16 bytes on the wire, like the 16-digit "
    "integer ids of /api/v1/device/cabinet) but not their type, so integer is REASONED. Ids, "
    "UUIDs, names, IPs, readings and times are synthetic and agree with "
    "tests/fixtures/mx30_like_api.json where the unit's agreed. Subscribing transmits (a TCP "
    "connection, the upgrade GET, a pong a second) and its side effects are UNKNOWN: novasun's "
    "read-only surface reads GET /api/v1/screen/output/display/state instead, and this channel "
    "is documented, not implemented. Nothing here says what another MX30, another model or "
    "another firmware does. Generated from tests/conftest.py (MX30_LIKE_WEBSOCKET_ABOUT, "
    "MX30_LIKE_WEBSOCKET_EVENTS); tests/test_fixtures.py asserts they agree."
)


# --- The same MX30 with every output line unplugged ---------------------------
#
# From an attended read-only session on the same unit the same evening (VMP
# closed): the operator pulled the output data lines one at a time with the
# unit left powered, 18:59:52Z-19:02:29Z, while novasun polled
# /api/v1/device/monitor/info every 2 s and display/state every 1 s, held the
# websocket (upgrade and pongs only) and listened on UDP 54622. Nothing was
# written in that stretch. /api/v1/device/cabinet and /api/v1/screen/cabinet/
# count were read once at about 19:03Z, after every line was out. Everything
# below is MX30_LIKE_API with what that session showed applied, and nothing
# else changed, so a diff of the two fixtures is exactly what unplugging did.

#: GET /api/v1/device/cabinet with every line out: 0 entries (OBSERVED). The
#: list holds the cabinets connected now, not the configured ones.
MX30_UNPLUGGED_CABINETS: list = []

#: GET /api/v1/screen/cabinet/count with every line out: CabinetCount 0
#: (OBSERVED; 72 connected). CabinetCountInBlackList: 0 as the connected read
#: had it; the websocket's ScreensCabinetsCountChange carried 0 at every stage
#: (OBSERVED), but the HTTP value unplugged was not recorded.
MX30_UNPLUGGED_CABINET_COUNT = {"list": [{"ScreenID": MX30_LIKE_SCREEN_ID, "CabinetCount": 0,
                                          "CabinetCountInBlackList": 0}]}

#: Outputs whose link went down: every output linked in the connected read.
#: 2048 dropped at 18:59:50Z, 2049 at 18:59:52Z, 2050 at 19:00:00Z, the rest by
#: 19:02:29Z, each within one 2 s poll of its line coming out (OBSERVED).
#: 2049 and 2051 carried no cabinets: they are backup ports (OBSERVED from the
#: unit's own outputPortLinkChange, backupState true on 2051).
MX30_UNPLUGGED_DROPPED_OUTPUTS = tuple(
    o["outputID"] for o in MX30_LIKE_MONITOR_INFO["outputStatus"] if o["linkStatus"])


def _mx30_unplugged_output(entry: dict) -> dict:
    # A dropped output reads linkStatus false and status 2 (OBSERVED: "every
    # output then read status 2" over HTTP, and the websocket's outputStatus
    # showed each pulled output go {status 2, linkStatus false}). Status 2's
    # meaning is UNKNOWN. Entries whose link was already false are left as the
    # connected read had them: whether their status moved was not recorded.
    if entry["outputID"] in MX30_UNPLUGGED_DROPPED_OUTPUTS:
        return {**entry, "linkStatus": False, "status": 2}
    return dict(entry)


#: GET /api/v1/device/monitor/info with every line out. **The false all-clear:**
#: cabinets[] is MX30_LIKE_MONITOR_INFO's unchanged -- every cabinet and card
#: listed, nextCabinetLinkStatus.linkStatus true on every card, temperatures,
#: voltages and errorBit as last read -- which is what the unit returned at
#: every 2 s poll from the last unplug to power-off, ~8.5 minutes, never
#: clearing (OBSERVED: 72 cabinets, 72 cards, 72 links up, the same three
#: errorBit variants). The readings are last-known values, not live (REASONED:
#: no card was connected to report them). What changed: outputStatus (above)
#: and rvCardsRuntime, empty with the lines out (OBSERVED; 72 entries before).
#: Every other field is carried over; whether it moved was not recorded.
MX30_UNPLUGGED_MONITOR_INFO = {
    **copy.deepcopy(MX30_LIKE_MONITOR_INFO),
    "outputStatus": [_mx30_unplugged_output(o) for o in MX30_LIKE_MONITOR_INFO["outputStatus"]],
    "rvCardsRuntime": [],
}

#: GET /api/v1/screen/output/display/state through the unplugging: displayMode
#: 0 at every 1 Hz poll from before the first line came out to power-off
#: (OBSERVED). An unplugged wall reads "normal"; display state does not show it.
MX30_UNPLUGGED_DISPLAY_STATE = copy.deepcopy(MX30_LIKE_DISPLAY_STATE)

MX30_UNPLUGGED_ABOUT = (
    "The COEX HTTP API of the MX30 in tests/fixtures/mx30_like_api.json (hwVersion V1.5.1) with "
    "EVERY OUTPUT DATA LINE UNPLUGGED AND THE UNIT LEFT POWERED, as OBSERVED in an attended "
    "read-only session on 2026-09-26 (lines pulled one at a time, 18:59:52Z-19:02:29Z; nothing "
    "written in that stretch): real structure, synthetic values, the same three stand-in cabinets "
    "for the unit's 72. THIS FILE IS A FALSE-ALL-CLEAR TRAP. /api/v1/device/monitor/info reads "
    "exactly like a healthy wall: it still lists every cabinet and receiving card (72 of 72 on the "
    "unit, the three stand-ins here), every rvCards[].nextCabinetLinkStatus.linkStatus is true, "
    "and the temperatures, voltages and errorBit read what they read connected -- with nothing "
    "connected. The unit returned that at every 2 s poll from the last unplug to power-off, about "
    "8.5 minutes later, and it never cleared (OBSERVED); the per-card readings are last-known "
    "values, not live (REASONED). So a reader that counts cabinets online from monitor/info, or "
    "takes a reporting card to be a connected one, reports this wall as healthy: \"present in "
    "monitor/info with a reporting card = online\" was REASONED and is withdrawn. What did change, "
    "all OBSERVED: /api/v1/device/cabinet is an empty list (it holds the cabinets connected now, "
    "not the configured ones; 0 entries, read at about 19:03Z); /api/v1/screen/cabinet/count "
    "CabinetCount is 0 (72 connected; read at about 19:03Z); monitor/info "
    "outputStatus[].linkStatus is false on every output, each linked output having gone false "
    "within one 2 s poll of its line coming out and reading status 2 after (status 2's meaning "
    "is UNKNOWN); and monitor/info rvCardsRuntime is empty (72 entries connected). Those are the "
    "signals to build on: compare CabinetCount, or the /api/v1/device/cabinet entry count, with "
    "the number expected, and read outputStatus[].linkStatus. Display state does not show it "
    "either: /api/v1/screen/output/display/state read displayMode 0 at every 1 Hz poll through "
    "the unplugging (OBSERVED). Nor does the controller's presence: its UDP announcement went on "
    "every 3 s throughout (OBSERVED), so an announcing, answering controller is not a connected "
    "wall. The websocket did carry the news at once -- ScreensCabinetsCountChange 72 -> 48 -> 46 "
    "-> 45 -> 36 -> 24 -> 0, outputPortLinkChange and physicalOutputPortLinkChange per port, "
    "alarmCountChange with count rising 3 -> 4 -> 6 (OBSERVED; not in this file). Outputs 2049 "
    "and 2051, linked but carrying no cabinets, are backup ports (OBSERVED from the unit's own "
    "outputPortLinkChange). Carried over unchanged from mx30_like_api.json and NOT re-read with "
    "the lines out, so whether they changed is UNKNOWN: every other path, every other "
    "monitor/info field (controller readings, fans, runtimes, screenSourceStatus, cabinets[]'s "
    "order) and the status of every output whose link was already false. /api/v1/screen in "
    "particular: the websocket pushed screenCabinetSizeChange (a 128x128 cabinet size) at each "
    "stage, so its geometry may have moved (UNKNOWN). Only the end state, every line out, is here: "
    "the intermediate stages were watched through monitor/info and the websocket only. Whether "
    "the MX40 Pro's monitor/info does the same is UNKNOWN; it was never watched with a line out. "
    "The unit was then switched off at its front-panel button: HTTP answered connection refused, "
    "never a timeout, for the 7.5 minutes watched, and the announcements stopped (OBSERVED) -- a "
    "standby, not an unplugged wall (REASONED), and not represented here. Ids, UUIDs, the MAC, IPs "
    "and serials are mx30_like_api.json's synthetic ones, and randomPassword is its fake "
    "\"00000000\": a consumer must drop randomPassword before it logs, stores, displays or "
    "serialises anything read from /api/v1/device/hw. A diff of this file against "
    "mx30_like_api.json shows exactly what unplugging changed: this note, /api/v1/device/cabinet, "
    "/api/v1/screen/cabinet/count, and monitor/info's outputStatus and rvCardsRuntime. "
    "tests/fixtures/crewbox_harness.mts serves this file to crewbox's CoexReader and prints the "
    "grade it gives: at crewbox commit 7c8cf6a that was {\"health\": \"ok\", \"summary\": \"3 "
    "cabinets, 44\u00b0C\"}, every cabinet online (assumed), exactly its grade for the connected "
    "mx30_like_api.json (OBSERVED in the harness, 2026-09-26). Nothing here says what another "
    "MX30 or another firmware does. Generated from "
    "tests/conftest.py (MX30_UNPLUGGED_API); tests/test_fixtures.py asserts they agree."
)

#: tests/fixtures/mx30_unplugged_api.json, exactly.
MX30_UNPLUGGED_API = {
    **copy.deepcopy(MX30_LIKE_API),
    "__about__": MX30_UNPLUGGED_ABOUT,
    "/api/v1/device/cabinet": MX30_UNPLUGGED_CABINETS,
    "/api/v1/device/monitor/info": MX30_UNPLUGGED_MONITOR_INFO,
    "/api/v1/screen/cabinet/count": MX30_UNPLUGGED_CABINET_COUNT,
    "/api/v1/screen/output/display/state": MX30_UNPLUGGED_DISPLAY_STATE,
}
