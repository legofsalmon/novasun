"""The application layer: persistent multi-device state, and a service over it.

``state`` holds the model -- several processors, their connections, cached
status and an action log. ``server`` exposes it over HTTP and serves a browser
UI. They are separate on purpose: a different front end can import the state
layer directly and never start a web server.

    from novasun.app import Application
    with Application() as app:
        app.add("192.168.1.40")
        app.execute("192.168.1.40", "brightness", percent=60)
        print(app.snapshot())
"""

from .server import DEFAULT_PORT, NovasunServer, serve
from .state import ActionRecord, Application, DESTRUCTIVE, Device, DeviceState, Reachability

__all__ = [
    "Application",
    "Device",
    "DeviceState",
    "ActionRecord",
    "Reachability",
    "DESTRUCTIVE",
    "NovasunServer",
    "serve",
    "DEFAULT_PORT",
]
