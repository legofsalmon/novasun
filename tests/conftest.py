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
