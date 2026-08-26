"""A fake controller, so the application can be developed without hardware.

The simulator models a real topology rather than a flat register space, because
the addressing is the part an application most easily gets wrong:

* a sending card at a position on the chain, with its own registers,
* N output ports, each with M receiving cards, each with *its own* registers,
* broadcast writes (port 0xFF, card 0xFFFF) that reach all of them,
* ``ack = TIMEOUT`` when a request names a receiving card that is not there --
  which is what real hardware returns, and how topology is discovered,
* silence when a request names a sending card that is not on the chain, which
  is what terminates chain enumeration.

A flat register file would accept per-cabinet addressing bugs without complaint;
this will not.

Run it standalone::

    python -m novasun.simulator --model vx4s --port 5200
    python -m novasun.simulator --model uhd-jr --cards-per-port 4 --latency 0.002
"""

from __future__ import annotations

import argparse
import socketserver
import threading
import time
from dataclasses import dataclass, field

from . import registers as reg
from .devices import MODELS, DeviceProfile, profile_for
from .protocol import (
    COMPUTER,
    HEADER_RESPONSE,
    DeviceType,
    ErrorType,
    Packet,
    ProtocolError,
)
from .transport import FrameReader

#: Convenient names for `--model`, resolved against the device table.
MODEL_ALIASES = {
    "vx4s": 0x6107,
    "vx4s-n": 0x612A,
    "uhd-jr": 0x6205,
    "novapro-uhd-jr": 0x6205,
    "mctrl4k": 0x1103,
    "mctrl660-pro": 0x1107,
    "vx1000": 0x620C,
}


@dataclass
class RegisterFile:
    """Sparse byte-addressed store."""

    memory: dict[int, int] = field(default_factory=dict)

    def read(self, address: int, length: int) -> bytes:
        return bytes(self.memory.get(address + i, 0) for i in range(length))

    def write(self, address: int, data: bytes) -> None:
        for index, byte in enumerate(data):
            self.memory[address + index] = byte

    def write_uint(self, address: int, value: int, length: int) -> None:
        self.write(address, value.to_bytes(length, "little"))


def _sending_card_state(profile: DeviceProfile, name: str) -> RegisterFile:
    state = RegisterFile()
    state.write_uint(reg.CONTROLLER_MODEL_ID, profile.model_id or 0x1107, 2)
    state.write(reg.CONTROLLER_SN_HIGH, bytes.fromhex("001a2b3c4d5e0000"))
    state.write(reg.MAX_PACKET_PROBE, b"\xa8")
    state.write_uint(reg.MAX_PACKET_SIZE, 1024, 2)
    # Seed the model's own input register with its first switchable input, so a
    # read-back is meaningful. Which register that is differs per model -- a
    # VX4S uses 0x0220002D, a sending card 0x02000023.
    if profile.input_register is not None and profile.switchable_inputs:
        state.write_uint(
            profile.input_register, profile.switchable_inputs[0].select_value or 0, 1
        )
    if profile.display.is_processor_level:
        assert profile.display.register is not None
        state.write_uint(profile.display.register, profile.display.normal, 1)
    # A video-source record array, so the connector-signal decode is testable
    # without hardware. Modelled on a real UHD Jr: an ascending index per
    # record, one connector carrying a signal and the rest idle, and a trailing
    # record reporting the output canvas rather than an input.
    for index in range(reg.VIDEO_SOURCE_INPUT_RECORDS + 1):
        record = bytearray(reg.VIDEO_SOURCE_RECORD_SIZE)
        record[reg.VSR_INDEX] = index
        if index == 1:                      # one connector with a source on it
            record[reg.VSR_WIDTH:reg.VSR_WIDTH + 2] = (1920).to_bytes(2, "little")
            record[reg.VSR_HEIGHT:reg.VSR_HEIGHT + 2] = (1080).to_bytes(2, "little")
            record[reg.VSR_FRAME_PERIOD_US:reg.VSR_FRAME_PERIOD_US + 2] = (
                (16666).to_bytes(2, "little"))
            record[reg.VSR_REFRESH_CHZ:reg.VSR_REFRESH_CHZ + 2] = (
                (6000).to_bytes(2, "little"))
        elif index == reg.VIDEO_SOURCE_INPUT_RECORDS:   # the output canvas
            record[reg.VSR_WIDTH:reg.VSR_WIDTH + 2] = (3840).to_bytes(2, "little")
            record[reg.VSR_HEIGHT:reg.VSR_HEIGHT + 2] = (2160).to_bytes(2, "little")
        state.write(reg.VIDEO_SOURCE_STATE + index * reg.VIDEO_SOURCE_RECORD_SIZE,
                    bytes(record))
    # Past the end of the array the index byte stops ascending, which is what
    # terminates enumeration on real hardware.
    state.write(
        reg.VIDEO_SOURCE_STATE
        + (reg.VIDEO_SOURCE_INPUT_RECORDS + 1) * reg.VIDEO_SOURCE_RECORD_SIZE,
        bytes([0x7F] * reg.VIDEO_SOURCE_RECORD_SIZE),
    )

    label = name.encode()[:64]
    block = bytearray(88)
    block[0] = 0xA8
    block[17] = len(label)
    block[18 : 18 + len(label)] = label
    state.write(reg.DEVICE_NAME_SPACE, bytes(block))
    return state


def _receiving_card_state(port: int, index: int, model_id: int = 0x4105) -> RegisterFile:
    state = RegisterFile()
    # Identity: reading this back is how a card is found at all (M3 doc 3.9).
    state.write_uint(reg.RECEIVING_CARD_MODEL, model_id, 2)
    state.write(reg.RECEIVING_CARD_FIRMWARE, bytes([4, 2, 0, 1]))
    state.write(reg.GLOBAL_BRIGHTNESS, b"\xff")
    state.write(reg.RGB_BRIGHTNESS, b"\xff\xff\xff\xff")
    # Monitoring: validity bit set, temperature in 0.5 C units, humidity and
    # supply voltage. Values vary per card so an application showing per-cabinet
    # data does not look uniform when it should not.
    temperature_halves = 55 + port * 2 + index
    state.write(
        reg.RECEIVER_MONITORING,
        bytes([0x80, temperature_halves, 0x80 | (40 + index), 0x80 | 38]),
    )
    return state


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
                if server.latency:
                    time.sleep(server.latency)
                response = server.handle_packet(packet)
                if response is not None:
                    try:
                        self.request.sendall(response.to_bytes())
                    except OSError:
                        return


class SimulatedController(socketserver.ThreadingTCPServer):
    """Threaded TCP server that behaves like a sending card and its cards."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5200,
        model_id: int = 0x6107,
        ports: int | None = None,
        cards_per_port: int = 2,
        card_model_id: int = 0x4105,
        chain_index: int = 0,
        latency: float = 0.0,
        name: str | None = None,
        unimplemented: tuple[tuple[int, int], ...] = (),
    ) -> None:
        super().__init__((host, port), _Handler)
        self.profile = profile_for(model_id)
        self.chain_index = chain_index
        self.latency = latency
        self.port_count = ports if ports is not None else self.profile.port_count
        self.cards_per_port = cards_per_port
        self.name = name or f"Simulated {self.profile.name}"
        self.sender = _sending_card_state(self.profile, self.name)
        self.card_model_id = card_model_id
        # Address ranges the firmware does not back, as (start, length).
        #
        # Real hardware does not answer these with zeros and does not raise an
        # error: it returns the payload of the previous read, out of a response
        # buffer it never clears. That is OBSERVED on a NovaPro UHD Jr, and it
        # is modelled here because it is the difference between "this register
        # exists" and "this register appears to exist", which is a distinction a
        # register sweep cannot otherwise make. See registers.py.
        #
        # A sparse RegisterFile cannot express it on its own: an unset address
        # there reads zero, which is also what a real, implemented, zero-valued
        # register does. So the unbacked ranges are declared rather than
        # inferred.
        self.unimplemented = unimplemented
        self._response_buffer = b""

        self.cards: dict[tuple[int, int], RegisterFile] = {
            (port, index): _receiving_card_state(port, index, card_model_id)
            for port in range(self.port_count)
            for index in range(cards_per_port)
        }
        self.log: list[Packet] = []

    @property
    def address(self) -> tuple[str, int]:
        return self.server_address[0], self.server_address[1]

    def card(self, port: int, index: int) -> RegisterFile:
        """The register file of one receiving card; raises if it is not there."""
        return self.cards[(port, index)]

    def serve_in_thread(self) -> threading.Thread:
        thread = threading.Thread(target=self.serve_forever, daemon=True)
        thread.start()
        return thread

    # --- request handling ---------------------------------------------------

    def handle_packet(self, packet: Packet) -> Packet | None:
        self.log.append(packet)

        # A sending card ignores traffic addressed to a different chain
        # position. Silence, not an error -- this is what makes enumeration
        # terminate.
        if packet.destination not in (self.chain_index, 0xFF):
            return None

        if packet.device_type == DeviceType.SENDING_CARD:
            return self._respond(packet, self._access(packet, [self.sender]))

        if packet.device_type == DeviceType.RECEIVING_CARD:
            targets = self._targets(packet)
            if not targets:
                # The sending card tried to reach a card that did not answer.
                return self._respond(packet, ErrorType.TIMEOUT)
            return self._respond(packet, self._access(packet, targets))

        # Function cards are not simulated.
        return self._respond(packet, ErrorType.TIMEOUT)

    def _targets(self, packet: Packet) -> list[RegisterFile]:
        ports = (
            range(self.port_count) if packet.port == 0xFF else [packet.port]
        )
        indices = (
            range(self.cards_per_port) if packet.rcv_index == 0xFFFF else [packet.rcv_index]
        )
        return [
            self.cards[(port, index)]
            for port in ports
            for index in indices
            if (port, index) in self.cards
        ]

    def _is_unimplemented(self, address: int, length: int) -> bool:
        return any(
            address >= start and address + length <= start + size
            for start, size in self.unimplemented
        )

    def _access(self, packet: Packet, targets: list[RegisterFile]) -> bytes | ErrorType:
        if packet.io == 0:  # read: answer from the first matching target
            if self._is_unimplemented(packet.address, packet.length):
                # Echo the last payload, padded, exactly as the hardware does.
                stale = self._response_buffer[: packet.length]
                return stale + bytes(packet.length - len(stale))
            data = targets[0].read(packet.address, packet.length)
            self._response_buffer = data
            return data
        for target in targets:  # write: applies to every matching target
            target.write(packet.address, packet.data)
        return ErrorType.SUCCEEDED

    def _respond(self, packet: Packet, result: bytes | ErrorType) -> Packet:
        failed = isinstance(result, ErrorType) and result is not ErrorType.SUCCEEDED
        data = result if isinstance(result, bytes) else b""
        return Packet(
            head=HEADER_RESPONSE,
            ack=result if isinstance(result, ErrorType) else ErrorType.SUCCEEDED,
            serno=packet.serno,
            source=packet.destination,
            destination=COMPUTER,
            device_type=packet.device_type,
            port=packet.port,
            rcv_index=packet.rcv_index,
            io=packet.io,
            address=packet.address,
            length=0 if (failed or packet.io == 1) else len(data),
            data=data,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a fake NovaStar controller")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5200)
    parser.add_argument(
        "--model",
        default="vx4s",
        help="alias (%s) or a hex model id" % ", ".join(sorted(MODEL_ALIASES)),
    )
    parser.add_argument("--ports", type=int, help="override the output port count")
    parser.add_argument("--cards-per-port", type=int, default=2)
    parser.add_argument("--latency", type=float, default=0.0, help="seconds per request")
    args = parser.parse_args()

    model_id = MODEL_ALIASES.get(args.model.lower())
    if model_id is None:
        try:
            model_id = int(args.model, 0)
        except ValueError:
            parser.error(f"unknown model {args.model!r}")
    if model_id not in MODELS:
        print(f"warning: model 0x{model_id:04x} is not in the device table")

    server = SimulatedController(
        args.host,
        args.port,
        model_id=model_id,
        ports=args.ports,
        cards_per_port=args.cards_per_port,
        latency=args.latency,
    )
    host, port = server.address
    print(
        f"simulating {server.profile.name} on {host}:{port} -- "
        f"{server.port_count} ports x {server.cards_per_port} receiving cards"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
