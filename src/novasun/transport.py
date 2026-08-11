"""Byte transports for the register bus: TCP, and serial when pyserial is present."""

from __future__ import annotations

import socket
from typing import Protocol

from .protocol import ENVELOPE_SIZE, Packet, ProtocolError, expected_frame_size

TCP_PORT = 5200
"""Standard control port. VX Pro-series controllers listen on 15200 instead."""

VX_PRO_TCP_PORT = 15200

SERIAL_BAUD_LEGACY = 115200
"""MSD300 / MCTRL300 / MCTRL500, and the COEX RS232 central-control port."""

SERIAL_BAUD_FAST = 1048576
"""MSD600 / MCTRL600 / MCTRL660."""


class Transport(Protocol):
    def send(self, frame: bytes) -> None: ...
    def receive(self) -> Packet: ...
    def close(self) -> None: ...


class FrameReader:
    """Reassembles frames from a byte stream.

    The frame length is not in a single field: it depends on direction and on
    the read/write bit, so 18 bytes must be buffered before the total is known.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> list[Packet]:
        self._buffer.extend(chunk)
        packets: list[Packet] = []
        while True:
            self._resynchronise()
            size = expected_frame_size(bytes(self._buffer))
            if size is None or len(self._buffer) < size:
                return packets
            frame = bytes(self._buffer[:size])
            del self._buffer[:size]
            packets.append(Packet.from_bytes(frame))

    def _resynchronise(self) -> None:
        """Drop leading bytes until the buffer starts on a plausible header."""
        while self._buffer:
            if self._buffer[0] in (0x55, 0xAA):
                if len(self._buffer) < 2:
                    return
                pair = bytes(self._buffer[:2])
                if pair in (b"\x55\xaa", b"\xaa\x55"):
                    return
            del self._buffer[0]


class TcpTransport:
    """Blocking TCP transport. One connection per controller.

    Controllers accept a single control connection at a time in practice: if
    NovaLCT or VMP is attached, expect a refusal or a silent drop.
    """

    def __init__(self, host: str, port: int = TCP_PORT, timeout: float = 2.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._reader = FrameReader()
        self._pending: list[Packet] = []

    def send(self, frame: bytes) -> None:
        self._sock.sendall(frame)

    def receive(self) -> Packet:
        while not self._pending:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ProtocolError("connection closed by device")
            self._pending.extend(self._reader.feed(chunk))
        return self._pending.pop(0)

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass

    def __enter__(self) -> "TcpTransport":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class SerialTransport:
    """USB/RS232 transport. Requires ``pyserial``.

    MCTRL300-class hardware exposes a CP2102 USB-UART, so it appears as an
    ordinary COM/tty device; pick the baud rate matching the controller family.
    """

    def __init__(self, device: str, baudrate: int = SERIAL_BAUD_LEGACY, timeout: float = 2.0) -> None:
        try:
            import serial  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise RuntimeError("SerialTransport needs pyserial: pip install pyserial") from exc
        self._port = serial.Serial(device, baudrate=baudrate, timeout=timeout)
        self._reader = FrameReader()
        self._pending: list[Packet] = []

    def send(self, frame: bytes) -> None:
        self._port.write(frame)

    def receive(self) -> Packet:
        while not self._pending:
            chunk = self._port.read(max(1, self._port.in_waiting or ENVELOPE_SIZE))
            if not chunk:
                raise TimeoutError("no response from serial device")
            self._pending.extend(self._reader.feed(chunk))
        return self._pending.pop(0)

    def close(self) -> None:
        self._port.close()

    def __enter__(self) -> "SerialTransport":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
