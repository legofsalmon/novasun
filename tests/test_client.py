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


class TestStaleResponseBuffer:
    """An unimplemented address echoes the previous read instead of erroring.

    OBSERVED on a NovaPro UHD Jr and reproduced across a power cycle: reading an
    address the firmware does not back returns the previous read's payload in a
    well-formed frame with ack = SUCCEEDED. Nothing in the response says "no
    such register", so a sequential sweep reports nearly every address as live,
    holding plausible data.

    These tests exist so the discriminator that defeats it cannot regress.
    """

    UNBACKED = 0x0220_0020

    @pytest.fixture()
    def server(self):
        s = SimulatedController(
            "127.0.0.1", 0, model_id=0x6205, unimplemented=((self.UNBACKED, 0x10),)
        )
        s.serve_in_thread()
        yield s
        s.shutdown()
        s.server_close()

    def test_unbacked_address_echoes_the_previous_read(self, server) -> None:
        host, port = server.address
        with Controller.connect(host, port, timeout=1.0) as controller:
            first = controller.read(reg.CONTROLLER_SN_HIGH, 8)
            assert controller.read(self.UNBACKED, 8) == first

            second = controller.read(reg.CONTROLLER_MODEL_ID, 2)
            assert controller.read(self.UNBACKED, 2) == second

    def test_the_echo_is_not_an_error_and_not_zeros(self, server) -> None:
        """The trap is precisely that it looks like a successful read."""
        host, port = server.address
        with Controller.connect(host, port, timeout=1.0) as controller:
            controller.read(reg.CONTROLLER_SN_HIGH, 8)
            echoed = controller.read(self.UNBACKED, 8)
        assert echoed != bytes(8)          # not zeros, as the docs once claimed
        assert any(echoed)                 # and it carries plausible content

    def test_a_backed_register_is_independent_of_the_poison(self, server) -> None:
        host, port = server.address
        with Controller.connect(host, port, timeout=1.0) as controller:
            controller.read(reg.CONTROLLER_SN_HIGH, 8)
            a = controller.read(reg.CONTROLLER_MODEL_ID, 2)
            controller.read(0x0000_0000, 8)
            b = controller.read(reg.CONTROLLER_MODEL_ID, 2)
        assert a == b

    def test_one_poison_can_misclassify_a_backed_register(self, server) -> None:
        """Why the discriminator needs more than one poison.

        A register whose genuine value happens to equal the poison looks like an
        echo. This is not hypothetical: a two-trial version of this test
        misclassified 0x02200022 during bring-up of the first real unit.
        """
        host, port = server.address
        with Controller.connect(host, port, timeout=1.0) as controller:
            # Poison with the model ID, then read the model ID: a single trial
            # cannot tell "echoed" from "genuinely equal".
            poison = controller.read(reg.CONTROLLER_MODEL_ID, 2)
            assert controller.read(reg.CONTROLLER_MODEL_ID, 2) == poison

    def test_bringup_classifier_separates_backed_from_unbacked(self, server) -> None:
        from novasun.bringup import _classify_register

        host, port = server.address
        with Controller.connect(host, port, timeout=1.0) as controller:
            backed = _classify_register(
                controller, reg.CONTROLLER_MODEL_ID, 2, Target.sending_card()
            )
            unbacked = _classify_register(
                controller, self.UNBACKED, 2, Target.sending_card()
            )
        assert backed["verdict"] == "implemented"
        assert unbacked["verdict"] == "unimplemented"
        assert unbacked["trials_echoed"] == unbacked["trials_total"]

    def test_a_coincidental_echo_does_not_condemn_a_backed_register(self, server) -> None:
        """A backed register whose real value equals a poison must survive.

        KILL_MODE reads 0x00, and several poison sources also lead with 0x00, so
        most trials echo by coincidence. The classifier keys on whether the value
        VARIES WITH the poison rather than on whether it ever equals one, so this
        is reported as implemented rather than as unimplemented or inconclusive.

        Getting this wrong is not hypothetical: an earlier version keyed on
        equality and misclassified 0x02200022 on real hardware.
        """
        from novasun.bringup import _classify_register

        host, port = server.address
        with Controller.connect(host, port, timeout=1.0) as controller:
            result = _classify_register(
                controller, reg.KILL_MODE, 1, Target.sending_card()
            )
        assert result["verdict"] == "implemented"
        assert result["trials_echoed"] >= 1        # the coincidence really happens
        assert result["value"] == "00"             # and the value is still right

    def test_a_long_candidate_is_testable(self, server) -> None:
        """Poisons are read at the candidate's length, so size does not matter.

        An earlier version fixed the poison lengths and discarded any shorter
        than the candidate, which left every long register with zero usable
        trials -- reported as "unreadable", which reads as a device refusing when
        the device had answered perfectly well.
        """
        from novasun.bringup import _classify_register

        host, port = server.address
        with Controller.connect(host, port, timeout=1.0) as controller:
            result = _classify_register(
                controller, reg.DEVICE_NAME_SPACE, 88, Target.sending_card()
            )
        assert result["verdict"] == "implemented"
        assert result["trials_total"] >= 2


class TestConnectorSignals:
    """The video-source record array: per-connector signal state.

    Layout confirmed on a NovaPro UHD Jr against three source modes, so these
    pin a decode that is evidenced rather than inferred. The array describes
    connectors, not the selected input -- a record reports its own connector
    whatever the processor is routing.
    """

    @pytest.fixture()
    def server(self):
        s = SimulatedController("127.0.0.1", 0, model_id=0x6205)
        s.serve_in_thread()
        yield s
        s.shutdown()
        s.server_close()

    def test_reads_the_connector_array(self, server) -> None:
        host, port = server.address
        with Controller.connect(host, port, timeout=1.0) as controller:
            signals = controller.read_connector_signals()
        # Records 0..8: eight inputs plus the output canvas. The garbage record
        # past the end must not be included.
        assert [s.index for s in signals] == list(range(9))

    def test_a_connector_with_a_source(self, server) -> None:
        host, port = server.address
        with Controller.connect(host, port, timeout=1.0) as controller:
            signals = controller.read_connector_signals()
        live = signals[1]
        assert live.has_signal
        assert (live.width, live.height) == (1920, 1080)
        assert live.refresh_hz == 60.0
        assert live.measured_hz == pytest.approx(60.0, abs=0.05)
        assert "1920x1080" in live.describe()

    def test_an_idle_connector_reports_no_signal(self, server) -> None:
        host, port = server.address
        with Controller.connect(host, port, timeout=1.0) as controller:
            signals = controller.read_connector_signals()
        idle = signals[0]
        assert not idle.has_signal
        assert idle.refresh_hz is None      # not 0.0 -- there is no rate to give
        assert idle.measured_hz is None
        assert "no signal" in idle.describe()

    def test_the_array_terminates_on_a_broken_index(self) -> None:
        """The index byte, not a hard-coded count, ends the array.

        Past the end of the real array the index stops ascending and the values
        become incoherent. A different model may have a different number of
        connectors, so the terminator has to be the data.
        """
        from novasun.client import parse_connector_signals

        good = bytearray(reg.VIDEO_SOURCE_RECORD_SIZE * 3)
        for i in range(3):
            good[i * reg.VIDEO_SOURCE_RECORD_SIZE + reg.VSR_INDEX] = i
        rubbish = bytes([0x7F]) * reg.VIDEO_SOURCE_RECORD_SIZE
        assert len(parse_connector_signals(bytes(good) + rubbish)) == 3

    def test_zero_dimensions_is_no_signal_not_a_zero_sized_signal(self) -> None:
        from novasun.client import ConnectorSignal

        blank = ConnectorSignal.parse(bytes(reg.VIDEO_SOURCE_RECORD_SIZE), 0)
        assert not blank.has_signal
        assert blank.to_dict()["refresh_hz"] is None


class TestBlockReadsAreSingleRequests:
    """A block must be read from its base in one request.

    OBSERVED on a UHD Jr: the video-source array is served when read from its
    base, but a request starting partway in is resolved as whatever register
    lives at that address instead. 0x13010100 is such an address -- standalone
    it returns what look like pointers -- so a read chunked at the default 256
    bytes silently drops record 8 onwards and the array looks one record short.

    The simulator's register file is flat and cannot reproduce that, so this
    asserts the property that protects against it: one request, not several.
    """

    @pytest.fixture()
    def server(self):
        s = SimulatedController("127.0.0.1", 0, model_id=0x6205)
        s.serve_in_thread()
        yield s
        s.shutdown()
        s.server_close()

    def test_the_connector_array_is_fetched_in_one_frame(self, server) -> None:
        host, port = server.address
        with Controller.connect(host, port, timeout=1.0) as controller:
            server.log.clear()
            controller.read_connector_signals(count=12)
        reads = [
            p for p in server.log
            if p.io == IO.READ and p.address == reg.VIDEO_SOURCE_STATE
        ]
        assert len(reads) == 1, f"array split across {len(reads)} requests"
        assert reads[0].length == 12 * reg.VIDEO_SOURCE_RECORD_SIZE

    def test_no_request_starts_partway_into_the_array(self, server) -> None:
        host, port = server.address
        with Controller.connect(host, port, timeout=1.0) as controller:
            server.log.clear()
            controller.read_connector_signals(count=12)
        base = reg.VIDEO_SOURCE_STATE
        span = 12 * reg.VIDEO_SOURCE_RECORD_SIZE
        inside = [p for p in server.log if base < p.address < base + span]
        assert not inside, f"request(s) starting mid-array: {inside}"
