"""A fake controller, so the application can be developed without hardware.

The simulator speaks the same framing as a real sending card: it keeps a sparse
byte-addressed register file, answers reads from it, applies writes to it, and
replies with the same serial number. It is deliberately permissive about
addresses -- unknown registers read back as zeros rather than erroring, matching
what devices in the field tend to do.

Run it standalone::

    python -m novasun.simulator --port 5200
"""

from __future__ import annotations

import argparse
import socketserver
import threading
from dataclasses import dataclass, field

from . import registers as reg
from .protocol import (
    COMPUTER,
    HEADER_RESPONSE,
    ErrorType,
    Packet,
    ProtocolError,
)
from .transport import FrameReader


@dataclass
class RegisterFile:
    """Sparse byte-addressed store with a plausible power-on state."""

    memory: dict[int, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.write(reg.CONTROLLER_MODEL_ID, (0x1107).to_bytes(2, "little"))
        self.write(reg.CONTROLLER_SN_HIGH, bytes.fromhex("001a2b3c4d5e0000"))
        self.write(reg.MAX_PACKET_PROBE, b"\xa8")
        self.write(reg.MAX_PACKET_SIZE, (1024).to_bytes(2, "little"))
        self.write(reg.GLOBAL_BRIGHTNESS, b"\xff")
        name = b"NovaSun Simulator"
        block = bytearray(88)
        block[0] = 0xA8
        block[17] = len(name)
        block[18 : 18 + len(name)] = name
        self.write(reg.DEVICE_NAME_SPACE, bytes(block))
        # Receiving-card monitoring: valid 27.5 C, valid 42 %RH, valid 3.8 V
        self.write(reg.RECEIVER_MONITORING, bytes([0x80, 55, 0x80 | 42, 0x80 | 38]))

    def read(self, address: int, length: int) -> bytes:
        return bytes(self.memory.get(address + i, 0) for i in range(length))

    def write(self, address: int, data: bytes) -> None:
        for i, byte in enumerate(data):
            self.memory[address + i] = byte


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        server: "SimulatedController" = self.server  # type: ignore[assignment]
        reader = FrameReader()
        while True:
            try:
                chunk = self.request.recv(4096)
            except OSError:
                return
            if not chunk:
                return
            try:
                packets = reader.feed(chunk)
            except ProtocolError:
                return
            for packet in packets:
                response = server.handle_packet(packet)
                if response is not None:
                    self.request.sendall(response.to_bytes())


class SimulatedController(socketserver.ThreadingTCPServer):
    """Threaded TCP server answering register reads and writes."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, host: str = "127.0.0.1", port: int = 5200) -> None:
        super().__init__((host, port), _Handler)
        self.registers = RegisterFile()
        self.log: list[Packet] = []

    @property
    def address(self) -> tuple[str, int]:
        return self.server_address[0], self.server_address[1]

    #: Chain position this fake device answers on. Requests aimed elsewhere are
    #: dropped without a reply, exactly as a real card ignores another card's
    #: address -- which is what makes chain enumeration terminate.
    chain_index = 0

    def handle_packet(self, packet: Packet) -> Packet | None:
        self.log.append(packet)
        if packet.destination not in (self.chain_index, 0xFF):
            return None
        response = Packet(
            head=HEADER_RESPONSE,
            ack=ErrorType.SUCCEEDED,
            serno=packet.serno,
            source=packet.destination,
            destination=COMPUTER,
            device_type=packet.device_type,
            port=packet.port,
            rcv_index=packet.rcv_index,
            io=packet.io,
            address=packet.address,
            length=packet.length,
        )
        if packet.io == 0:  # read
            response.data = self.registers.read(packet.address, packet.length)
        else:
            self.registers.write(packet.address, packet.data)
            response.length = 0
        return response

    def serve_in_thread(self) -> threading.Thread:
        thread = threading.Thread(target=self.serve_forever, daemon=True)
        thread.start()
        return thread


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a fake NovaStar controller")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5200)
    args = parser.parse_args()
    server = SimulatedController(args.host, args.port)
    host, port = server.address
    print(f"simulated controller listening on {host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
