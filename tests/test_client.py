"""End-to-end tests of the client against the bundled simulator."""

from __future__ import annotations

import pytest

from novasun import registers as reg
from novasun.client import Controller
from novasun.protocol import DeviceType, IO, Target
from novasun.simulator import SimulatedController


@pytest.fixture()
def server():
    server = SimulatedController("127.0.0.1", 0)
    server.serve_in_thread()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture()
def controller(server):
    host, port = server.address
    with Controller.connect(host, port, timeout=2.0) as client:
        yield client


def test_probe_reads_identity(controller) -> None:
    info = controller.probe()
    assert info is not None
    assert info.model_id == 0x1107
    assert info.serial.startswith("00:1a:2b:3c:4d:5e")
    assert info.name == "NovaSun Simulator"
    assert info.max_packet_size == 1024


def test_brightness_round_trips(controller, server) -> None:
    controller.set_brightness(60)
    assert server.registers.read(reg.GLOBAL_BRIGHTNESS, 1) == bytes([reg.brightness_byte(60)])
    assert controller.get_brightness() == reg.brightness_byte(60)


def test_blackout_and_freeze_use_ff_not_01(controller, server) -> None:
    controller.blackout(True)
    controller.freeze(True)
    assert server.registers.read(reg.KILL_MODE, 1) == b"\xff"
    assert server.registers.read(reg.LOCK_MODE, 1) == b"\xff"

    controller.blackout(False)
    controller.freeze(False)
    assert server.registers.read(reg.KILL_MODE, 1) == b"\x00"
    assert server.registers.read(reg.LOCK_MODE, 1) == b"\x00"


def test_display_commands_are_addressed_to_every_receiving_card(controller, server) -> None:
    server.log.clear()
    controller.set_test_pattern(reg.TestPattern.WHITE)
    sent = server.log[-1]
    assert sent.device_type == DeviceType.RECEIVING_CARD
    assert sent.port == 0xFF
    assert sent.rcv_index == 0xFFFF
    assert sent.io == IO.WRITE
    assert sent.data == bytes([reg.TestPattern.WHITE])


def test_five_component_brightness_is_one_frame(controller, server) -> None:
    server.log.clear()
    controller.set_rgbv_brightness(50, 50, 50, 50, 50)
    assert len([p for p in server.log if p.io == IO.WRITE]) == 1
    assert server.registers.read(reg.ALL_BRIGHTNESS, 5) == bytes([0x80] * 5)


def test_large_reads_are_chunked(controller, server) -> None:
    server.log.clear()
    data = controller.read(reg.RECEIVER_MONITORING, 0x100, Target.receiving_card(0, 0), chunk=64)
    assert len(data) == 0x100
    reads = [p for p in server.log if p.io == IO.READ]
    assert len(reads) == 4
    assert [p.address - reg.RECEIVER_MONITORING for p in reads] == [0, 64, 128, 192]


def test_large_writes_are_chunked(controller, server) -> None:
    server.log.clear()
    payload = bytes(range(256)) * 2
    controller.write(0x0500_0000, payload, Target.all_receiving_cards(), chunk=200)
    writes = [p for p in server.log if p.io == IO.WRITE]
    assert len(writes) == 3
    assert server.registers.read(0x0500_0000, len(payload)) == payload


def test_monitoring_block_decodes(controller) -> None:
    status = controller.read_receiver_monitoring(port=0, index=0)
    assert status.temperature_c == 27.5
    assert status.humidity_percent == 42
    assert status.voltage_v == 3.8


def test_serial_numbers_advance_and_are_matched(controller, server) -> None:
    server.log.clear()
    for _ in range(3):
        controller.probe()
    sernos = [p.serno for p in server.log]
    assert len(set(sernos)) == len(sernos)


def test_enumerate_stops_after_consecutive_misses(controller, server) -> None:
    """Only chain position 0 answers, so the walk finds one device and stops."""
    server.log.clear()
    devices = controller.enumerate_devices(limit=8)
    assert len(devices) == 1
    # Probed index 0 (hit), then 1 and 2 (misses) -- never as far as index 3.
    assert max(packet.destination for packet in server.log) == 2
