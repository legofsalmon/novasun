"""Read-only monitoring: passive observation, safe polling, SNMP OIDs."""

from __future__ import annotations

import socket
import time
from pathlib import Path

import pytest

from novasun import passive as passive_module
from novasun import snmp
from novasun.coexsim import SimulatedCoexController
from novasun.discovery import PROBE, REPLY_PREFIX, UDP_PORT
from novasun.monitor import (
    MONITORING_ENDPOINTS,
    CoexMonitor,
    RateLimiter,
    ReadOnlyCoexClient,
    WriteAttempted,
)
from novasun.passive import (
    Observation,
    PassiveListener,
    build_inventory,
    decode_reply,
)


class TestPassiveListener:
    def test_module_contains_no_send_path(self) -> None:
        """Structural: there is no way to transmit, not merely no call to it."""
        source = Path(passive_module.__file__).read_text()
        code = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith("#")
        )
        for forbidden in (".send(", ".sendto(", ".sendall(", ".sendmsg("):
            assert forbidden not in code, f"{forbidden} appears in passive.py"
        # PROBE is imported only to recognise other people's probes, never sent.
        assert "sendto(PROBE" not in code

    def test_nothing_is_transmitted_while_listening(self) -> None:
        """Behavioural: a peer socket sees no traffic from the listener."""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as peer:
            peer.bind(("127.0.0.1", 0))
            peer.settimeout(0.4)
            listener = PassiveListener("127.0.0.1", 0, join_multicast=False)
            try:
                thread = listener.listen_in_thread(duration=0.4)
                thread.join(timeout=2)
            finally:
                listener.stop()
            with pytest.raises((TimeoutError, socket.timeout)):
                peer.recvfrom(1024)

    def test_observes_probes_and_replies(self) -> None:
        listener = PassiveListener("127.0.0.1", 0, join_multicast=False)
        try:
            _host, port = listener.address
            thread = listener.listen_in_thread(duration=3.0)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as speaker:
                speaker.sendto(PROBE, ("127.0.0.1", port))
                speaker.sendto(REPLY_PREFIX + b"MX40 Pro\x00SIM-0001", ("127.0.0.1", port))
            assert listener.wait_for(2, timeout=3.0)
            listener.stop()
            thread.join(timeout=2)

            kinds = [observation.kind for observation in listener.observations]
            assert "probe" in kinds and "reply" in kinds
        finally:
            listener.stop()

    def test_inventory_from_overheard_traffic(self) -> None:
        now = time.time()
        observations = [
            Observation(now, "10.0.0.5", PROBE),
            Observation(now + 0.1, "10.0.0.20", REPLY_PREFIX + b"MX40 Pro\x00SIM-0001"),
            Observation(now + 30, "10.0.0.5", PROBE),
            Observation(now + 30.1, "10.0.0.20", REPLY_PREFIX + b"MX40 Pro\x00SIM-0001"),
            Observation(now + 60, "10.0.0.5", PROBE),
        ]
        inventory = build_inventory(observations)

        assert set(inventory.devices) == {"10.0.0.20"}
        assert inventory.devices["10.0.0.20"].replies == 2
        assert inventory.probe_interval == pytest.approx(30, abs=0.5)
        assert "MX40 Pro" in inventory.summary()

    def test_probe_interval_needs_two_probes(self) -> None:
        inventory = build_inventory([Observation(time.time(), "10.0.0.5", PROBE)])
        assert inventory.probe_interval is None
        assert "interval unknown" in inventory.summary()

    def test_probes_without_replies_are_called_out(self) -> None:
        """The likely real-world case: replies unicast, so a listener sees none."""
        now = time.time()
        inventory = build_inventory(
            [Observation(now, "10.0.0.5", PROBE), Observation(now + 5, "10.0.0.5", PROBE)]
        )
        assert not inventory.devices
        assert "port mirror" in inventory.summary()


class TestReplyDecoder:
    def test_extracts_delimited_text(self) -> None:
        reply = decode_reply(REPLY_PREFIX + b"MX40 Pro\x00SIM-0001\x00")
        assert reply.fields == ["MX40 Pro", "SIM-0001"]

    def test_keeps_binary_tails_as_bytes(self) -> None:
        reply = decode_reply(REPLY_PREFIX + bytes([0x01, 0x02, 0xFF]))
        assert reply.looks_binary
        assert reply.fields == []
        assert "0102ff" in reply.describe()

    def test_empty_tail_is_reported_honestly(self) -> None:
        """No invented structure when there is nothing after the prefix."""
        reply = decode_reply(REPLY_PREFIX)
        assert reply.tail == b""
        assert "no payload" in reply.describe()

    def test_non_reply_payload_yields_no_tail(self) -> None:
        assert decode_reply(PROBE).tail == b""


class TestReadOnlyClient:
    @pytest.fixture()
    def server(self):
        server = SimulatedCoexController("127.0.0.1", 0)
        server.serve_in_thread()
        yield server
        server.shutdown()
        server.server_close()

    def test_get_works(self, server) -> None:
        host, port = server.address
        client = ReadOnlyCoexClient(host, port, timeout=2.0)
        assert client.device_info()["model"] == "MX40 Pro"

    def test_every_setter_is_blocked(self, server) -> None:
        """Blocking `request` closes all setters at once, present and future."""
        host, port = server.address
        client = ReadOnlyCoexClient(host, port, timeout=2.0)

        for call in (
            lambda: client.set_display_mode(1),
            lambda: client.set_screen_brightness(["screen-1"], 0.5),
            lambda: client.select_input(1),
            lambda: client.apply_preset("preset-1"),
            lambda: client.set_snmp(True),
            lambda: client.set_working_mode(True),
        ):
            with pytest.raises(WriteAttempted):
                call()

        # And nothing reached the device.
        assert server.state.display_mode == 0
        assert server.state.current_preset is None
        assert not any(method == "PUT" for method, _path, _body in server.state.requests)


class TestCoexMonitor:
    @pytest.fixture()
    def server(self):
        server = SimulatedCoexController("127.0.0.1", 0)
        server.serve_in_thread()
        yield server
        server.shutdown()
        server.server_close()

    def test_poll_builds_a_snapshot(self, server) -> None:
        host, port = server.address
        with CoexMonitor(host, port, interval=0.0) as monitor:
            snapshot = monitor.poll()

        assert snapshot.model == "MX40 Pro"
        assert snapshot.display_mode == 0
        assert len(snapshot.cabinets) == 8
        assert snapshot.healthy
        assert snapshot.hottest is not None
        assert snapshot.signal_present == ["HDMI 1", "12G-SDI"]
        assert "8/8 online" in snapshot.summary()

    def test_polling_issues_no_writes(self, server) -> None:
        host, port = server.address
        with CoexMonitor(host, port, interval=0.0) as monitor:
            for _ in range(3):
                monitor.poll()
        assert all(method == "GET" for method, _path, _body in server.state.requests)

    def test_slow_endpoints_are_cached_between_polls(self, server) -> None:
        host, port = server.address
        with CoexMonitor(host, port, interval=0.0) as monitor:
            monitor.poll()
            first = len(server.state.requests)
            server.state.requests.clear()
            monitor.poll()
            second = len(server.state.requests)
        # Topology and identity are not re-read every tick.
        assert second < first
        assert second == len(MONITORING_ENDPOINTS) - 3

    def test_unreachable_endpoints_are_recorded_not_raised(self, server) -> None:
        host, port = server.address
        monitor = CoexMonitor(host, port, interval=0.0)
        monitor.client  # noqa: B018 - constructed above
        snapshot = monitor.poll()
        # The simulator does not implement /device/backup, so it answers
        # NotSupport -- which must degrade the snapshot, not break the poll.
        assert "backup" in snapshot.errors
        assert snapshot.model == "MX40 Pro"

    def test_offline_cabinet_shows_up(self, server) -> None:
        server.state.cabinets[3]["online"] = False
        host, port = server.address
        with CoexMonitor(host, port, interval=0.0) as monitor:
            snapshot = monitor.poll()
        assert not snapshot.healthy
        assert [c.identifier for c in snapshot.offline_cabinets] == [
            server.state.cabinets[3]["id"]
        ]


class TestRateLimiter:
    def test_spaces_requests(self) -> None:
        limiter = RateLimiter(interval=0.05)
        start = time.monotonic()
        for _ in range(3):
            limiter.wait()
        assert time.monotonic() - start >= 0.1

    def test_back_off_delays_the_next_call(self) -> None:
        limiter = RateLimiter(interval=0.0, backoff=0.2)
        limiter.back_off()
        start = time.monotonic()
        limiter.wait()
        assert time.monotonic() - start >= 0.15


class TestSnmpOids:
    def test_indices_substitute_in_order(self) -> None:
        assert snmp.TEMPERATURE_POINT_VALUE.at(2) == "1.3.6.1.4.1.319.10.10.10.2.2.3"
        assert (
            snmp.RECEIVING_CARD_TEMPERATURE_STATUS.at(1, 3, 17)
            == "1.3.6.1.4.1.319.10.10.30.6.1.1.3.1.17"
        )

    def test_wrong_index_count_is_an_error(self) -> None:
        with pytest.raises(ValueError):
            snmp.RECEIVING_CARD_TEMPERATURE_STATUS.at(1)
        with pytest.raises(ValueError):
            snmp.CONTROLLER_MODEL.at(1)

    def test_scalar_oids_are_literal(self) -> None:
        assert snmp.CONTROLLER_MODEL.oid == "1.3.6.1.4.1.319.10.10.1.2"
        assert snmp.SCREEN_COUNT.oid == "1.3.6.1.4.1.319.10.20.1.1"

    def test_enumerations_decode(self) -> None:
        assert "signal present" in snmp.describe(snmp.INPUT_SOURCE_SIGNAL, 1)
        assert "inserted, no signal" in snmp.describe(snmp.INPUT_SOURCE_SIGNAL, 2)
        assert "12G-SDI" in snmp.describe(snmp.INPUT_SOURCE_TYPE, 9)
        assert "abnormal" in snmp.describe(snmp.FAN_STATUS, 1)
        # Unmapped values pass through rather than being invented.
        assert snmp.describe(snmp.INPUT_SOURCE_TYPE, 250) == "250"

    def test_monitoring_set_is_all_scalars(self) -> None:
        """The starting walk should need no indices."""
        for oid in snmp.MONITORING_SET:
            assert oid.at() == oid.oid
