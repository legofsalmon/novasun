"""novasun -- talk to NovaStar LED processors.

Two control paths, depending on the hardware:

* :mod:`novasun.client` -- the register bus (RS232 / USB / TCP 5200) that
  NovaLCT uses. Works from MSD300-era sending cards through to current
  controllers.
* :mod:`novasun.coex` -- the JSON API on port 8001 exposed by COEX-generation
  controllers (MX/CX/KU), the hardware VMP manages.

Start with :func:`novasun.discovery.discover` to find devices, then
:meth:`novasun.client.Controller.connect`.
"""

from .client import Controller, DeviceInfo, ReceiverStatus
from .coex import CoexClient, CoexError
from .discovery import DiscoveredDevice, discover
from .protocol import (
    DeviceType,
    ErrorType,
    IO,
    Packet,
    ProtocolError,
    Target,
    checksum,
)
from .registers import DisplayMode, InputSource, TestPattern

__all__ = [
    "Controller",
    "DeviceInfo",
    "ReceiverStatus",
    "CoexClient",
    "CoexError",
    "DiscoveredDevice",
    "discover",
    "Packet",
    "Target",
    "DeviceType",
    "ErrorType",
    "IO",
    "ProtocolError",
    "checksum",
    "TestPattern",
    "DisplayMode",
    "InputSource",
]

__version__ = "0.1.0"
