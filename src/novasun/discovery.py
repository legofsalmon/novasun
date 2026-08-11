"""Find NovaStar controllers on the local network.

NovaLCT discovers devices by sending the ASCII probe ``rqProMI:`` from UDP port
3800 to the subnet broadcast address and to the multicast group
224.224.125.119. Any controller on the wire answers from its own address with
``rpProMI:`` followed by device details; the source IP of that reply is what you
then connect to on TCP 5200.

The probe must be sent *from* port 3800 as well as to it -- controllers reply to
the port they were contacted from, and firmware in the field is inconsistent
about honouring an ephemeral source port.
"""

from __future__ import annotations

import socket
import struct
import time
from dataclasses import dataclass

UDP_PORT = 3800
MULTICAST_GROUP = "224.224.125.119"
PROBE = b"rqProMI:"
REPLY_PREFIX = b"rpProMI:"


@dataclass
class DiscoveredDevice:
    address: str
    payload: bytes

    @property
    def detail(self) -> str:
        """Printable tail of the reply, which some firmware fills with a name."""
        tail = self.payload[len(REPLY_PREFIX) :]
        return tail.decode("ascii", errors="replace").strip("\x00 ")


def _local_ipv4_addresses() -> list[str]:
    """Best-effort list of local IPv4 interface addresses, without netifaces."""
    addresses: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addresses.add(info[4][0])
    except socket.gaierror:
        pass
    # The default-route address is the one that matters most and is not always
    # in the hostname lookup.
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))  # TEST-NET-1: never actually routed
        addresses.add(probe.getsockname()[0])
    except OSError:
        pass
    finally:
        probe.close()
    return sorted(a for a in addresses if not a.startswith("127."))


def discover(
    timeout: float = 1.0,
    destinations: list[str] | None = None,
    bind_address: str = "0.0.0.0",
) -> list[DiscoveredDevice]:
    """Broadcast the probe and collect replies for ``timeout`` seconds."""
    targets = destinations or ["255.255.255.255", MULTICAST_GROUP]
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 128)
    found: dict[str, DiscoveredDevice] = {}
    try:
        sock.bind((bind_address, UDP_PORT))
        try:
            sock.setsockopt(
                socket.IPPROTO_IP,
                socket.IP_ADD_MEMBERSHIP,
                struct.pack("4sl", socket.inet_aton(MULTICAST_GROUP), socket.INADDR_ANY),
            )
        except OSError:
            pass  # multicast unavailable here; broadcast alone still finds devices
        for target in targets:
            try:
                sock.sendto(PROBE, (target, UDP_PORT))
            except OSError:
                continue
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            sock.settimeout(remaining)
            try:
                payload, (address, _) = sock.recvfrom(1024)
            except (TimeoutError, socket.timeout):
                break
            except OSError:
                break
            if payload.startswith(REPLY_PREFIX) and address not in found:
                found[address] = DiscoveredDevice(address=address, payload=payload)
    finally:
        sock.close()
    return list(found.values())
