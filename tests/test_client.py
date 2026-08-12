"""End-to-end tests of the client against the bundled simulator."""

from __future__ import annotations

import pytest

from novasun import registers as reg
from novasun.client import Controller
from novasun.protocol import DeviceError, DeviceType, ErrorType, IO, Target
from novasun.simulator import SimulatedController

VX4S = 0x6107


@pytest.fixture()
def server():
    server = SimulatedController("127.0.0.1", 0, model_id=VX4S, cards_per_port=2)
    server.serve_in_thread()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture()
def controller(server):
    host, port = server.address
    with Controller.connect(host, port, timeout=2.0) as client:
        yield client


def test_probe_reads_identity(controller, server) -> None:
    info = controller.probe()
    assert info is not None
    assert info.model_id == VX4S
    assert info.serial.startswith("00:1a:2b:3c:4d:5e")
    assert info.name == "Simulated VX4S"
    assert info.max_packet_size == 1024
    assert server.port_count == 4  # VX4S has four output ports


def test_brightness_round_trips(controller, server) -> None:
    controller.set_brightness(60)
    expected = bytes([reg.brightness_byte(60)])
    assert server.card(0, 0).read(reg.GLOBAL_BRIGHTNESS, 1) == expected
    assert controller.get_brightness() == reg.brightness_byte(60)


def test_blackout_and_freeze_use_ff_not_01(controller, server) -> None:
    controller.blackout(True)
    controller.freeze(True)
    assert server.card(0, 0).read(reg.KILL_MODE, 1) == b"\xff"
    assert server.card(0, 0).read(reg.LOCK_MODE, 1) == b"\xff"

    controller.blackout(False)
    controller.freeze(False)
    assert server.card(0, 0).read(reg.KILL_MODE, 1) == b"\x00"
    assert server.card(0, 0).read(reg.LOCK_MODE, 1) == b"\x00"


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
    assert server.card(0, 0).read(reg.ALL_BRIGHTNESS, 5) == bytes([0x80] * 5)


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
    assert server.card(0, 0).read(0x0500_0000, len(payload)) == payload


def test_monitoring_block_decodes(controller) -> None:
    status = controller.read_receiver_monitoring(port=0, index=0)
    assert status.temperature_c == 27.5
    assert status.humidity_percent == 40
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


class TestTopologyAddressing:
    """The simulator models a real chain, so addressing mistakes are visible."""

    def test_cards_have_independent_registers(self, controller, server) -> None:
        controller.set_brightness(25, Target.receiving_card(port=1, index=1))
        assert server.card(1, 1).read(reg.GLOBAL_BRIGHTNESS, 1) == bytes(
            [reg.brightness_byte(25)]
        )
        # Every other card is untouched -- a flat register file could not tell.
        assert server.card(0, 0).read(reg.GLOBAL_BRIGHTNESS, 1) == b"\xff"
        assert server.card(1, 0).read(reg.GLOBAL_BRIGHTNESS, 1) == b"\xff"

    def test_broadcast_reaches_every_card_on_every_port(self, controller, server) -> None:
        controller.set_brightness(10)
        expected = bytes([reg.brightness_byte(10)])
        for port in range(server.port_count):
            for index in range(server.cards_per_port):
                assert server.card(port, index).read(reg.GLOBAL_BRIGHTNESS, 1) == expected

    def test_reads_come_from_the_addressed_card(self, controller, server) -> None:
        server.card(2, 1).write(reg.GLOBAL_BRIGHTNESS, b"\x11")
        assert controller.get_brightness(Target.receiving_card(2, 1)) == 0x11
        assert controller.get_brightness(Target.receiving_card(0, 0)) == 0xFF

    def test_absent_card_answers_with_a_timeout_ack(self, controller, server) -> None:
        """What real hardware does when a card is not on the port."""
        with pytest.raises(DeviceError) as error:
            controller.get_brightness(Target.receiving_card(port=0, index=99))
        assert error.value.ack == ErrorType.TIMEOUT

    def test_absent_port_answers_with_a_timeout_ack(self, controller) -> None:
        with pytest.raises(DeviceError) as error:
            controller.get_brightness(Target.receiving_card(port=9, index=0))
        assert error.value.ack == ErrorType.TIMEOUT

    def test_monitoring_differs_per_card(self, controller) -> None:
        """Per-cabinet displays should not look uniform when they are not."""
        first = controller.read_receiver_monitoring(port=0, index=0)
        second = controller.read_receiver_monitoring(port=2, index=1)
        assert first.temperature_c != second.temperature_c


class TestModelProfiles:
    def test_port_count_follows_the_model(self) -> None:
        for model_id, expected in [(0x6107, 4), (0x6205, 16), (0x1107, 6)]:
            server = SimulatedController("127.0.0.1", 0, model_id=model_id)
            try:
                assert server.port_count == expected
            finally:
                server.server_close()

    def test_uhd_jr_exposes_all_sixteen_ports(self) -> None:
        server = SimulatedController("127.0.0.1", 0, model_id=0x6205, cards_per_port=1)
        server.serve_in_thread()
        try:
            host, port = server.address
            with Controller.connect(host, port, timeout=2.0) as controller:
                info = controller.probe()
                assert info is not None and info.model_id == 0x6205
                controller.set_brightness(50, Target.receiving_card(port=15, index=0))
            assert server.card(15, 0).read(reg.GLOBAL_BRIGHTNESS, 1) == bytes(
                [reg.brightness_byte(50)]
            )
        finally:
            server.shutdown()
            server.server_close()


class TestReceivingCardEnumeration:
    """Finding the cards actually present, rather than assuming a count.

    The presence test is reading back the model ID (M3 protocol 3.9): "if the ID
    can be read back, it means the receiving card is working normally".
    """

    def test_probe_identifies_a_card(self, controller) -> None:
        card = controller.probe_receiving_card(port=1, index=0)
        assert card is not None
        assert card.model_id == 0x4105
        assert card.firmware_version == "4.2.0.1"
        assert card.healthy
        assert "0x4105" in card.name  # unnamed model IDs show the raw value

    def test_probe_returns_none_for_an_absent_card(self, controller) -> None:
        assert controller.probe_receiving_card(port=0, index=99) is None
        assert controller.probe_receiving_card(port=9, index=0) is None

    def test_enumeration_finds_every_card(self, controller, server) -> None:
        cards = controller.enumerate_receiving_cards(ports=server.port_count)
        assert len(cards) == server.port_count * server.cards_per_port
        assert {(c.port, c.index) for c in cards} == {
            (p, i) for p in range(server.port_count) for i in range(server.cards_per_port)
        }

    def test_enumeration_stops_after_consecutive_gaps(self, controller, server) -> None:
        """Two misses end a port, rather than probing all 64 positions."""
        server.log.clear()
        controller.enumerate_receiving_cards(ports=1, max_per_port=64)
        probed = {p.rcv_index for p in server.log if p.io == IO.READ}
        assert max(probed) == server.cards_per_port + 1  # the two misses, no more

    def test_a_card_reporting_zero_firmware_is_unhealthy(self, controller, server) -> None:
        server.card(0, 0).write(reg.RECEIVING_CARD_FIRMWARE, b"\x00\x00\x00\x00")
        card = controller.probe_receiving_card(0, 0)
        assert card is not None and not card.healthy

    def test_a_card_reporting_model_zero_is_absent(self, controller, server) -> None:
        server.card(0, 1).write(reg.RECEIVING_CARD_MODEL, b"\x00\x00")
        assert controller.probe_receiving_card(0, 1) is None

    def test_cards_serialise(self, controller) -> None:
        import json

        card = controller.probe_receiving_card(0, 0)
        assert card is not None
        assert json.dumps(card.to_dict())
