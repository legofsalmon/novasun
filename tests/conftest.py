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


def host_key(server) -> str:
    """The address the application should use for ``server``.

    Falls back to whatever the socket reports, so it is safe on servers that
    were never given a key.
    """
    return getattr(server, "key_host", server.address[0])
