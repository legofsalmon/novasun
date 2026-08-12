"""The application layer: screens, devices, and a service over them.

``state`` holds the model -- several processors, their connections, cached
status and an action log -- and ``screens`` adds the layer an operator actually
works in: a named wall made of parts of one or more processors. ``config``
persists both to disk, because which ports feed which wall cannot be
discovered. ``server`` exposes the lot over HTTP and serves a browser UI.

State and transport are separate on purpose: a different front end can import
the state layer directly and never start a web server.

    from novasun.app import Application, ScreenMember

    app = Application.from_config()
    app.add("192.168.1.40")
    app.add_screen("Main Wall", [ScreenMember("192.168.1.40", ports=[0, 1])])
    app.execute_screen("main-wall", "brightness", percent=60)
"""

from .config import Config, DeviceEntry
from .screens import Screen, ScreenMember, ScreenState
from .server import DEFAULT_PORT, NovasunServer, serve
from .state import ActionRecord, Application, DESTRUCTIVE, Device, DeviceState, Reachability

__all__ = [
    "Application",
    "Screen",
    "ScreenMember",
    "ScreenState",
    "Config",
    "DeviceEntry",
    "Device",
    "DeviceState",
    "ActionRecord",
    "Reachability",
    "DESTRUCTIVE",
    "NovasunServer",
    "serve",
    "DEFAULT_PORT",
]
