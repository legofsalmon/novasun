"""Wire codec for the NovaStar "Nova Control System" register protocol.

This is the single protocol spoken by NovaStar sending cards / video controllers
over RS232, USB-serial and TCP 5200 (UDP 5201 on COEX hardware). It is a
memory-mapped register bus: every operation is a read or a write of N bytes at a
32-bit register address on a target device (sending card, receiving card or
function card).

Frame layout (little-endian throughout), 20 bytes of envelope + N bytes payload::

    offset  size  field
    0       2     head        0x55 0xAA request / 0xAA 0x55 response
    2       1     ack         0 in requests; ErrorType in responses
    3       1     serno       sequence number, echoed in the response
    4       1     source      0xFE = computer
    5       1     destination sending-card index on the chain (0xFF broadcast)
    6       1     device_type DeviceType
    7       1     port        RJ45 output port index, 0xFF = all ports
    8       2     rcv_index   receiving-card index on the port, 0xFFFF = all
    10      1     io          IO.READ / IO.WRITE
    11      1     reserved
    12      4     address     32-bit register address
    16      2     length      bytes to read, or length of the write payload
    18      N     data        payload (writes: request side; reads: response side)
    18+N    2     checksum    (sum of bytes[2:] + 0x5555) & 0xFFFF

The checksum covers every byte after the header, plus the 0x5555 seed. It is a
plain additive sum, not a CRC, despite the "CRC" naming in some tooling.

Sources cross-checked when writing this module are listed in
``docs/protocol-register-bus.md``; ``tests/test_protocol.py`` replays the hex
examples out of NovaStar's own documents against this codec.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import IntEnum

HEADER_REQUEST = 0xAA55  # bytes 55 AA on the wire (little-endian u16)
HEADER_RESPONSE = 0x55AA  # bytes AA 55 on the wire
CHECKSUM_SEED = 0x5555

COMPUTER = 0xFE
"""Source address a PC always uses; also the destination in a response."""

BROADCAST_DEVICE = 0xFF
BROADCAST_PORT = 0xFF
BROADCAST_RCV = 0xFFFF

ENVELOPE_SIZE = 20
"""Bytes in a frame that carries no payload (18 header + 2 checksum)."""

_HEADER = struct.Struct("<HBBBBBBHBBIH")


class DeviceType(IntEnum):
    """Target device class for a request."""

    SENDING_CARD = 0
    RECEIVING_CARD = 1
    FUNCTION_CARD = 2


class IO(IntEnum):
    READ = 0
    WRITE = 1


class ErrorType(IntEnum):
    """``ack`` byte of a response."""

    SUCCEEDED = 0
    TIMEOUT = 1
    REQUEST_CHECKSUM_ERROR = 2
    RESPONSE_CHECKSUM_ERROR = 3
    UNKNOWN_COMMAND = 4
    INVALID = 255


class ProtocolError(Exception):
    """Malformed frame, or a response the device rejected."""


class ChecksumError(ProtocolError):
    pass


class DeviceError(ProtocolError):
    """The device answered, but with a non-zero ack."""

    def __init__(self, ack: int, packet: "Packet | None" = None) -> None:
        name = ErrorType(ack).name if ack in ErrorType._value2member_map_ else f"0x{ack:02x}"
        super().__init__(f"device returned {name}")
        self.ack = ack
        self.packet = packet


def checksum(frame_without_checksum: bytes) -> int:
    """Additive checksum over everything after the two header bytes."""
    return (sum(frame_without_checksum[2:]) + CHECKSUM_SEED) & 0xFFFF


@dataclass
class Packet:
    """One request or response frame."""

    address: int = 0
    io: IO = IO.READ
    length: int = 0
    data: bytes = b""
    head: int = HEADER_REQUEST
    ack: int = 0
    serno: int = 0
    source: int = COMPUTER
    destination: int = 0
    device_type: DeviceType = DeviceType.SENDING_CARD
    port: int = 0
    rcv_index: int = 0
    reserved: int = 0

    @property
    def is_response(self) -> bool:
        return self.head == HEADER_RESPONSE

    @property
    def ok(self) -> bool:
        return self.ack == ErrorType.SUCCEEDED

    def to_bytes(self) -> bytes:
        payload = self.data if self.carries_payload else b""
        body = _HEADER.pack(
            self.head,
            self.ack,
            self.serno,
            self.source,
            self.destination,
            int(self.device_type),
            self.port,
            self.rcv_index,
            int(self.io),
            self.reserved,
            self.address & 0xFFFFFFFF,
            self.length,
        ) + payload
        return body + struct.pack("<H", checksum(body))

    @property
    def carries_payload(self) -> bool:
        """Writes carry their payload outbound, reads carry it back.

        A write request holds the bytes to store; its response is bare. A read
        request is bare; its response holds the bytes read. ``length`` is set on
        both sides regardless, which is why it cannot be used to size the frame
        on its own -- see :func:`expected_frame_size`.
        """
        request = self.head == HEADER_REQUEST
        return (self.io == IO.WRITE) == request

    @classmethod
    def from_bytes(cls, raw: bytes, *, verify: bool = True) -> "Packet":
        if len(raw) < ENVELOPE_SIZE:
            raise ProtocolError(f"frame too short: {len(raw)} bytes")
        (
            head,
            ack,
            serno,
            source,
            destination,
            device_type,
            port,
            rcv_index,
            io,
            reserved,
            address,
            length,
        ) = _HEADER.unpack_from(raw, 0)
        if head not in (HEADER_REQUEST, HEADER_RESPONSE):
            raise ProtocolError(f"bad header 0x{head:04x}")
        if verify:
            expected = checksum(raw[:-2])
            actual = struct.unpack_from("<H", raw, len(raw) - 2)[0]
            if expected != actual:
                raise ChecksumError(f"checksum 0x{actual:04x}, expected 0x{expected:04x}")
        packet = cls(
            address=address,
            io=IO(io),
            length=length,
            head=head,
            ack=ack,
            serno=serno,
            source=source,
            destination=destination,
            device_type=DeviceType(device_type) if device_type in DeviceType._value2member_map_ else device_type,
            port=port,
            rcv_index=rcv_index,
            reserved=reserved,
        )
        packet.data = raw[_HEADER.size : len(raw) - 2]
        return packet


def expected_frame_size(prefix: bytes) -> int | None:
    """Total frame length implied by ``prefix``, or ``None`` if undecidable yet.

    A stream reader needs the first 18 bytes to know whether a payload follows:
    only write-requests and read-responses carry one.
    """
    if len(prefix) < _HEADER.size:
        return None
    head = struct.unpack_from("<H", prefix, 0)[0]
    io = prefix[10]
    length = struct.unpack_from("<H", prefix, 16)[0]
    request = head == HEADER_REQUEST
    carries_payload = (io == IO.WRITE) == request
    return ENVELOPE_SIZE + (length if carries_payload else 0)


@dataclass
class Target:
    """Where a request is aimed.

    ``destination`` selects the sending card (0 for the first device on the
    link, 0xFF to broadcast); ``port`` and ``rcv_index`` then select a receiving
    card behind it. The broadcast defaults address every receiving card on every
    output port, which is what NovaLCT sends for screen-wide brightness.
    """

    destination: int = 0
    device_type: DeviceType = DeviceType.SENDING_CARD
    port: int = 0
    rcv_index: int = 0

    @classmethod
    def sending_card(cls, index: int = 0) -> "Target":
        return cls(destination=index, device_type=DeviceType.SENDING_CARD)

    @classmethod
    def all_receiving_cards(cls, destination: int = BROADCAST_DEVICE) -> "Target":
        return cls(
            destination=destination,
            device_type=DeviceType.RECEIVING_CARD,
            port=BROADCAST_PORT,
            rcv_index=BROADCAST_RCV,
        )

    @classmethod
    def receiving_card(cls, port: int, index: int, destination: int = 0) -> "Target":
        return cls(
            destination=destination,
            device_type=DeviceType.RECEIVING_CARD,
            port=port,
            rcv_index=index,
        )

    @classmethod
    def function_card(cls, port: int = BROADCAST_PORT, index: int = BROADCAST_RCV, destination: int = 0) -> "Target":
        return cls(
            destination=destination,
            device_type=DeviceType.FUNCTION_CARD,
            port=port,
            rcv_index=index,
        )


@dataclass
class SerialNumberCounter:
    """Per-connection 8-bit request counter."""

    value: int = field(default=0)

    def next(self) -> int:
        self.value = (self.value + 1) & 0xFF
        return self.value


def read_request(address: int, length: int, target: Target = Target(), serno: int = 0) -> Packet:
    return Packet(
        address=address,
        io=IO.READ,
        length=length,
        serno=serno,
        destination=target.destination,
        device_type=target.device_type,
        port=target.port,
        rcv_index=target.rcv_index,
    )


def write_request(address: int, data: bytes, target: Target = Target(), serno: int = 0) -> Packet:
    return Packet(
        address=address,
        io=IO.WRITE,
        length=len(data),
        data=bytes(data),
        serno=serno,
        destination=target.destination,
        device_type=target.device_type,
        port=target.port,
        rcv_index=target.rcv_index,
    )


def hexdump(raw: bytes) -> str:
    return " ".join(f"{b:02x}" for b in raw)
