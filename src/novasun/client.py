"""High-level client for the NovaStar register bus.

``Controller`` owns a transport, matches responses to requests by serial number,
splits oversized transfers into chunks, and exposes the handful of operations a
control surface actually needs. Anything not wrapped is still reachable through
:meth:`Controller.read` / :meth:`Controller.write`, which is the point: the
protocol is a register bus, and the wrappers are only conveniences.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import registers as reg
from .protocol import (
    COMPUTER,
    DeviceError,
    DeviceType,
    ErrorType,
    Packet,
    ProtocolError,
    SerialNumberCounter,
    Target,
    read_request,
    write_request,
)
from .transport import TCP_PORT, TcpTransport, Transport

DEFAULT_CHUNK = 256
"""Bytes per frame. Devices advertise their own maximum; 256 is NovaLCT's floor."""


@dataclass
class DeviceInfo:
    model_id: int
    serial: str
    name: str | None = None
    max_packet_size: int = DEFAULT_CHUNK


class Controller:
    """A connected NovaStar sending card / video controller."""

    def __init__(self, transport: Transport, *, retries: int = 1) -> None:
        self._transport = transport
        self._serno = SerialNumberCounter()
        self._retries = retries

    @classmethod
    def connect(cls, host: str, port: int = TCP_PORT, timeout: float = 2.0) -> "Controller":
        return cls(TcpTransport(host, port, timeout=timeout))

    def close(self) -> None:
        self._transport.close()

    def __enter__(self) -> "Controller":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- raw register access ------------------------------------------------

    def exchange(self, packet: Packet, *, expect_response: bool = True) -> Packet | None:
        """Send one frame and return the matching response."""
        packet.serno = self._serno.next()
        packet.source = COMPUTER
        self._transport.send(packet.to_bytes())
        if not expect_response:
            return None
        for _ in range(self._retries + 1):
            response = self._transport.receive()
            if response.serno == packet.serno:
                if not response.ok:
                    raise DeviceError(response.ack, response)
                return response
            # A stale response from an earlier timed-out request: drop it and
            # keep reading rather than pairing it with this one.
        raise ProtocolError(f"no response matching serial number {packet.serno}")

    def read(self, address: int, length: int, target: Target = Target(), chunk: int = DEFAULT_CHUNK) -> bytes:
        out = bytearray()
        offset = 0
        while offset < length:
            size = min(chunk, length - offset)
            response = self.exchange(read_request(address + offset, size, target))
            assert response is not None
            out.extend(response.data[:size])
            offset += size
        return bytes(out)

    def write(
        self,
        address: int,
        data: bytes,
        target: Target = Target(),
        chunk: int = DEFAULT_CHUNK,
        expect_response: bool = True,
    ) -> None:
        offset = 0
        data = bytes(data)
        while offset < len(data):
            piece = data[offset : offset + chunk]
            self.exchange(
                write_request(address + offset, piece, target),
                expect_response=expect_response,
            )
            offset += len(piece)

    def read_uint(self, address: int, length: int, target: Target = Target()) -> int:
        return int.from_bytes(self.read(address, length, target), "little")

    def write_uint(self, address: int, value: int, length: int, target: Target = Target()) -> None:
        self.write(address, value.to_bytes(length, "little"), target)

    # --- identification -----------------------------------------------------

    def probe(self, index: int = 0) -> DeviceInfo | None:
        """Read enough to identify the sending card at chain position ``index``.

        Returns ``None`` when nothing answers, which is how the device chain is
        enumerated: walk indices upward until two consecutive misses.
        """
        target = Target.sending_card(index)
        try:
            model = self.read_uint(reg.CONTROLLER_MODEL_ID, 2, target)
        except (DeviceError, ProtocolError, TimeoutError):
            return None
        info = DeviceInfo(model_id=model, serial=self._read_serial(target))
        info.max_packet_size = self._read_max_packet(target)
        info.name = self._read_name(target)
        return info

    def _read_serial(self, target: Target) -> str:
        try:
            raw = self.read(reg.CONTROLLER_SN_HIGH, 8, target)
        except (DeviceError, ProtocolError, TimeoutError):
            return ""
        return ":".join(f"{b:02x}" for b in raw)

    def _read_max_packet(self, target: Target) -> int:
        try:
            if self.read(reg.MAX_PACKET_PROBE, 1, target)[0] != 0xA8:
                return DEFAULT_CHUNK
            return self.read_uint(reg.MAX_PACKET_SIZE, 2, target) or DEFAULT_CHUNK
        except (DeviceError, ProtocolError, TimeoutError, IndexError):
            return DEFAULT_CHUNK

    def _read_name(self, target: Target) -> str | None:
        try:
            block = self.read(reg.DEVICE_NAME_SPACE, 88, target)
        except (DeviceError, ProtocolError, TimeoutError):
            return None
        if not block or block[0] != 0xA8:
            return None
        length = block[17]
        name = block[18 : 18 + length].decode("ascii", errors="replace").strip("\x00 ")
        return name or None

    def enumerate_devices(self, limit: int = 8) -> list[DeviceInfo]:
        devices: list[DeviceInfo] = []
        misses = 0
        for index in range(limit):
            info = self.probe(index)
            if info is None:
                misses += 1
                if misses >= 2:
                    break
                continue
            misses = 0
            devices.append(info)
        return devices

    # --- display control ----------------------------------------------------

    def set_brightness(self, percent: float, target: Target | None = None) -> None:
        """Set overall brightness on every receiving card (0..100 %)."""
        self.write_uint(
            reg.GLOBAL_BRIGHTNESS,
            reg.brightness_byte(percent),
            1,
            target or Target.all_receiving_cards(),
        )

    def set_rgbv_brightness(
        self,
        overall: float,
        red: float,
        green: float,
        blue: float,
        virtual_red: float,
        target: Target | None = None,
    ) -> None:
        """Write all five brightness components in a single frame."""
        payload = bytes(
            reg.brightness_byte(v) for v in (overall, red, green, blue, virtual_red)
        )
        self.write(reg.ALL_BRIGHTNESS, payload, target or Target.all_receiving_cards())

    def get_brightness(self, target: Target | None = None) -> int:
        return self.read_uint(
            reg.GLOBAL_BRIGHTNESS, 1, target or Target.receiving_card(port=0, index=0)
        )

    def blackout(self, enabled: bool, target: Target | None = None) -> None:
        self.write_uint(
            reg.KILL_MODE,
            reg.ENGAGED if enabled else reg.NORMAL,
            1,
            target or Target.all_receiving_cards(),
        )

    def freeze(self, enabled: bool, target: Target | None = None) -> None:
        self.write_uint(
            reg.LOCK_MODE,
            reg.ENGAGED if enabled else reg.NORMAL,
            1,
            target or Target.all_receiving_cards(),
        )

    def set_test_pattern(self, pattern: reg.TestPattern, target: Target | None = None) -> None:
        self.write_uint(
            reg.SELF_TEST_MODE, int(pattern), 1, target or Target.all_receiving_cards()
        )

    def select_input(self, source: reg.InputSource | int) -> None:
        """Switch the controller's input. Register numbering is model-specific."""
        self.write_uint(reg.DVI_SELECT, int(source), 1, Target.sending_card())

    def apply_preset(self, number: int) -> None:
        """Recall a preset on COEX-generation hardware (1-based)."""
        if not 1 <= number <= 0xFF:
            raise ValueError("preset numbers start at 1")
        self.write_uint(reg.PRESET_SWITCH, number, 1, Target.all_receiving_cards())

    def set_display_mode(self, mode: reg.DisplayMode, output_card: int = 0xFF) -> None:
        """COEX sending-card display control: normal / blackout / freeze."""
        self.write(
            reg.SENDING_CARD_DISPLAY,
            bytes([output_card, int(mode)]),
            Target.all_receiving_cards(),
        )

    def save_to_flash(self, target: Target | None = None) -> None:
        """Persist current settings. Flash wear is real -- do not call per frame."""
        self.write_uint(
            reg.SAVE_SENDER_PARAMETERS, 1, 1, target or Target.sending_card()
        )

    # --- monitoring ---------------------------------------------------------

    def probe_receiving_card(self, port: int, index: int) -> "ReceivingCard | None":
        """Identify the receiving card at one chain position, if there is one.

        Per the M3 protocol document: reading the model ID back at all is the
        presence and health test. A zero model ID, a timeout ack, or silence all
        mean "no working card here".
        """
        target = Target.receiving_card(port=port, index=index)
        try:
            raw = self.read(reg.RECEIVING_CARD_INFO, 6, target)
        except (DeviceError, ProtocolError, TimeoutError):
            return None
        if len(raw) < 6:
            return None
        model = int.from_bytes(raw[0:2], "little")
        if model == 0:
            return None
        return ReceivingCard(
            port=port,
            index=index,
            model_id=model,
            firmware=tuple(raw[2:6]),
        )

    def enumerate_receiving_cards(
        self,
        ports: int,
        max_per_port: int = 64,
        stop_after_misses: int = 2,
    ) -> list["ReceivingCard"]:
        """Walk every port, finding the cards actually present.

        Cards are numbered from 0 along each port, so the walk stops after
        ``stop_after_misses`` consecutive gaps rather than probing all 64
        positions — an absent card costs a round trip, and a 16-port processor
        would otherwise be 1024 of them.

        A gap in the middle of a chain is real (a dead card still breaks the
        run), so raise ``stop_after_misses`` if you are hunting for one.
        """
        found: list[ReceivingCard] = []
        for port in range(ports):
            misses = 0
            for index in range(max_per_port):
                card = self.probe_receiving_card(port, index)
                if card is None:
                    misses += 1
                    if misses >= stop_after_misses:
                        break
                    continue
                misses = 0
                found.append(card)
        return found

    def read_connector_signals(self, count: int = 12) -> list["ConnectorSignal"]:
        """Per-connector signal state: resolution, refresh and presence.

        Reads the video-source record array from the sending card. This reports
        each connector regardless of which input is routed -- there is no known
        way to read the *selected* input on any model this project has met.
        """
        length = count * reg.VIDEO_SOURCE_RECORD_SIZE
        # One request, not several. The firmware serves this array when it is
        # read from its base; a request starting partway in is resolved as
        # whatever register lives at *that* address instead. 0x13010100 is one
        # such address -- read on its own it returns what look like pointers --
        # so a read chunked at the default 256 bytes silently loses record 8
        # onwards. Passing chunk=length keeps it to a single frame, which the
        # 2048-byte max packet size comfortably allows.
        raw = self.read(
            reg.VIDEO_SOURCE_STATE, length, Target.sending_card(), chunk=length
        )
        return parse_connector_signals(raw)

    def read_receiver_monitoring(self, port: int, index: int) -> "ReceiverStatus":
        raw = self.read(
            reg.RECEIVER_MONITORING, 0x100, Target.receiving_card(port=port, index=index)
        )
        return ReceiverStatus.parse(raw)


#: Receiving-card model IDs we can put a name to. The register is generic --
#: every Nova receiving card answers it -- but the ID space is not documented,
#: so most cards report a number we can show and cannot label. NovaLCT's
#: decompiled table contains only the generic `Scanner` entry.
RECEIVING_CARD_NAMES: dict[int, str] = {
    0x4101: "Scanner (generic)",
}


@dataclass
class ReceivingCard:
    """A receiving card found on a port.

    ``model_id`` is whatever the card reports; the 0x41xx range is what has been
    seen, but the mapping from ID to product name is undocumented, so
    :attr:`name` falls back to the raw value rather than guessing.
    """

    port: int
    index: int
    model_id: int
    firmware: tuple[int, ...] = ()

    @property
    def name(self) -> str:
        return RECEIVING_CARD_NAMES.get(self.model_id, f"model 0x{self.model_id:04x}")

    @property
    def firmware_version(self) -> str:
        return ".".join(str(part) for part in self.firmware) if self.firmware else ""

    @property
    def healthy(self) -> bool:
        """A card that answers but reports all-zero firmware is not running."""
        return self.model_id != 0 and any(self.firmware)

    def to_dict(self) -> dict[str, object]:
        return {
            "port": self.port,
            "index": self.index,
            "model_id": self.model_id,
            "name": self.name,
            "firmware": self.firmware_version,
            "healthy": self.healthy,
        }


@dataclass
class ReceiverStatus:
    """First bytes of the 0x0A000000 monitoring block on a receiving card.

    Layout per the M3 protocol document, section 3.1.1. The high bit of each
    field marks validity; only the documented leading fields are decoded here.
    """

    temperature_c: float | None
    humidity_percent: int | None
    voltage_v: float | None
    raw: bytes

    @classmethod
    def parse(cls, raw: bytes) -> "ReceiverStatus":
        temperature = None
        if len(raw) >= 2 and raw[0] & 0x80:
            magnitude = raw[1] * 0.5
            temperature = -magnitude if raw[0] & 0x01 else magnitude
        humidity = raw[2] & 0x7F if len(raw) >= 3 and raw[2] & 0x80 else None
        voltage = (raw[3] & 0x7F) / 10 if len(raw) >= 4 and raw[3] & 0x80 else None
        return cls(temperature_c=temperature, humidity_percent=humidity, voltage_v=voltage, raw=raw)


@dataclass
class ConnectorSignal:
    """One 32-byte record from the :data:`registers.VIDEO_SOURCE_STATE` array.

    The array describes **connectors**, not the selected input: a record reports
    its own connector's signal whatever the processor is currently routing. On a
    UHD Jr, records 0-7 are inputs and record 8 reports the output canvas.

    Field offsets and their meanings are OBSERVED -- see
    ``docs/read-only-monitoring.md``. Which connector each index corresponds to
    is not: only index 1 has been tied to a physical socket (HDMI, on one unit),
    so :attr:`label` is deliberately absent rather than guessed.
    """

    index: int
    width: int
    height: int
    frame_period_us: int
    refresh_centihertz: int
    raw: bytes

    @property
    def has_signal(self) -> bool:
        """Whether a source is locked.

        Zero width and height is the no-signal indicator: observed going to zero
        both on cable removal and during link re-training on a mode change.
        """
        return self.width > 0 and self.height > 0

    @property
    def refresh_hz(self) -> float | None:
        """Nominal refresh rate. Steady, so this is the one to display."""
        if not self.has_signal or not self.refresh_centihertz:
            return None
        return self.refresh_centihertz / 100

    @property
    def measured_hz(self) -> float | None:
        """Refresh implied by the measured frame period.

        Jitters by a few microseconds between reads, because it is measured
        rather than declared. Useful for spotting a drifting source; misleading
        as a label, which is what :attr:`refresh_hz` is for.
        """
        if not self.has_signal or not self.frame_period_us:
            return None
        return round(1_000_000 / self.frame_period_us, 2)

    def describe(self) -> str:
        if not self.has_signal:
            return f"connector {self.index}: no signal"
        rate = f" @ {self.refresh_hz:g}Hz" if self.refresh_hz else ""
        return f"connector {self.index}: {self.width}x{self.height}{rate}"

    @classmethod
    def parse(cls, raw: bytes, index: int) -> "ConnectorSignal":
        def u16(offset: int) -> int:
            return int.from_bytes(raw[offset : offset + 2], "little")

        return cls(
            index=index,
            width=u16(reg.VSR_WIDTH),
            height=u16(reg.VSR_HEIGHT),
            frame_period_us=u16(reg.VSR_FRAME_PERIOD_US),
            refresh_centihertz=u16(reg.VSR_REFRESH_CHZ),
            raw=raw,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "has_signal": self.has_signal,
            "width": self.width,
            "height": self.height,
            "refresh_hz": self.refresh_hz,
            "measured_hz": self.measured_hz,
        }


def parse_connector_signals(raw: bytes, limit: int | None = None) -> list[ConnectorSignal]:
    """Split the video-source block into records, stopping where the array does.

    Each record carries its own index at ``VSR_INDEX``, ascending from zero.
    Past the end of the array that byte stops ascending and the values become
    incoherent, so the index is used as the terminator rather than a hard-coded
    count -- a different model may well have a different number of connectors.
    """
    size = reg.VIDEO_SOURCE_RECORD_SIZE
    records: list[ConnectorSignal] = []
    for position in range(len(raw) // size):
        chunk = raw[position * size : (position + 1) * size]
        if chunk[reg.VSR_INDEX] != position:
            break  # past the end of the array
        records.append(ConnectorSignal.parse(chunk, position))
        if limit is not None and len(records) >= limit:
            break
    return records


__all__ = [
    "ConnectorSignal",
    "Controller",
    "DeviceInfo",
    "ReceivingCard",
    "ReceiverStatus",
    "Target",
    "DeviceType",
    "ErrorType",
    "parse_connector_signals",
]
