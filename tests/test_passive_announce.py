"""COEX announcements: a zero-transmission inventory, heard on UDP 54622.

The evidence is one MX30 at firmware V1.5.1, 2026-09-26 (OBSERVED). Every 3 s it
sends a 96-byte bare-JSON datagram as a subnet broadcast from UDP 54650 to
ports 54622, 54623, 54624 and 54700. The payload structure below is that one,
byte for byte, with synthetic values. The MAC is from the documentation range
00:00:5E:00:53:xx, and addresses are 192.0.2.x or loopback. Every datagram in
this file is sent by the test itself to 127.0.0.1, and nothing leaves the host.
"""

from __future__ import annotations

import json
import random
import socket
import threading
import time
import types
from pathlib import Path

import pytest

from novasun import passive as passive_module
from novasun.cli import build_parser, main
from novasun.discovery import PROBE
from novasun.passive import (
    ANNOUNCEMENT_PORTS,
    ANNOUNCEMENT_SOURCE_PORT,
    CHANNEL_ANNOUNCEMENT,
    CHANNEL_DISCOVERY,
    DEFAULT_ANNOUNCEMENT_PORTS,
    Observation,
    PassiveListener,
    build_inventory,
    decode_announcement,
)

MAC = "00:00:5e:00:53:30"
OTHER_MAC = "00:00:5e:00:53:31"
UNIT = "192.0.2.30"
FAKE_SECRET = "00000000"  # the one fake value fixtures may carry


def announcement(
    mac: str = MAC,
    api: object = "8001",
    https: object = "9001",
    auth: object = 0,
    work: object = 0,
    **extra: object,
) -> bytes:
    """An announcement in the observed key order, types and compact spacing."""
    entry = {"apiPort": api, "mac": mac, "authType": auth, "workMode": work, "https": https}
    entry.update(extra)
    return json.dumps({"data": [entry]}, separators=(",", ":")).encode("ascii")


PAYLOAD = announcement()


def send(port: int, *payloads: bytes) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as speaker:
        for payload in payloads:
            speaker.sendto(payload, ("127.0.0.1", port))


def announcement_port(listener: PassiveListener, index: int = 0) -> int:
    ports = [port for channel, (_h, port) in listener.addresses if channel == CHANNEL_ANNOUNCEMENT]
    return ports[index]


@pytest.fixture()
def listener():
    """Announcement-only, loopback, ephemeral port, no multicast join."""
    instance = PassiveListener(
        "127.0.0.1", None, join_multicast=False, announcement_ports=(0,)
    )
    yield instance
    instance.stop()


# --- The payload -------------------------------------------------------------


class TestPayload:
    def test_synthetic_payload_has_the_observed_layout(self) -> None:
        """Same length and byte offsets as the captured datagram (OBSERVED)."""
        assert len(PAYLOAD) == 96
        assert PAYLOAD[10:19] == b'"apiPort"'
        assert PAYLOAD[20:26] == b'"8001"'
        assert PAYLOAD[27:32] == b'"mac"'
        assert PAYLOAD[33:52] == f'"{MAC}"'.encode()
        assert PAYLOAD[53:63] == b'"authType"'
        assert PAYLOAD[64:65] == b"0"
        assert PAYLOAD[66:76] == b'"workMode"'
        assert PAYLOAD[77:78] == b"0"
        assert PAYLOAD[79:86] == b'"https"'
        assert PAYLOAD[87:93] == b'"9001"'
        assert PAYLOAD[93:] == b"}]}"

    def test_decodes_the_observed_shape(self) -> None:
        decoded = decode_announcement(PAYLOAD)
        assert decoded.ok and not decoded.error
        assert decoded.notes == () and decoded.unknown_keys == ()
        (entry,) = decoded.entries
        assert entry.mac == MAC
        assert entry.api_port == 8001 and entry.https_port == 9001
        assert entry.auth_type == 0 and entry.work_mode == 0
        assert entry.unknown_keys == ()

    def test_unknown_keys_are_named_and_their_values_dropped(self) -> None:
        payload = json.dumps(
            {
                "data": [
                    {
                        "apiPort": "8001",
                        "mac": MAC,
                        "authType": 0,
                        "workMode": 0,
                        "https": "9001",
                        "model": "SYNTHETIC-MODEL-VALUE",
                    }
                ],
                "version": "SYNTHETIC-TOP-VALUE",
            }
        ).encode()
        decoded = decode_announcement(payload)
        assert decoded.ok
        assert decoded.entries[0].unknown_keys == ("model",)
        assert decoded.unknown_keys == ("version",)
        assert "SYNTHETIC-MODEL-VALUE" not in repr(decoded)
        assert "SYNTHETIC-TOP-VALUE" not in repr(decoded)

    @pytest.mark.parametrize(
        ("payload", "note"),
        [
            (PAYLOAD + b"\x00", "trailing NUL"),
            (announcement(api=8001), "apiPort is integer (observed as string)"),
            (announcement(auth="0"), "authType is string (observed as integer)"),
            (
                json.dumps(
                    {"data": [json.loads(PAYLOAD)["data"][0]] * 2}
                ).encode(),
                "2 entries in data",
            ),
        ],
        ids=["trailing-nul", "int-port", "string-mode", "two-entries"],
    )
    def test_tolerated_variations_decode_with_a_note(self, payload: bytes, note: str) -> None:
        decoded = decode_announcement(payload)
        assert decoded.ok
        assert decoded.entries[0].api_port == 8001
        assert decoded.entries[0].auth_type == 0
        assert any(note in text for text in decoded.notes), decoded.notes

    def test_mac_is_normalised(self) -> None:
        decoded = decode_announcement(announcement(mac="00-00-5E-00-53-30"))
        assert decoded.entries[0].mac == MAC

    def test_unusable_values_become_none_with_a_note(self) -> None:
        decoded = decode_announcement(announcement(mac="not-a-mac", api="99999", https=True))
        (entry,) = decoded.entries
        assert entry.mac is None and entry.api_port is None and entry.https_port is None
        assert "data[0].mac unusable" in decoded.notes
        assert "data[0].apiPort unusable" in decoded.notes
        assert "data[0].https unusable" in decoded.notes

    @pytest.mark.parametrize(
        ("payload", "reason"),
        [
            (b"", "empty datagram"),
            (b"\xff\xfe\x00\x01", "not UTF-8"),
            (b"hello", "not JSON"),
            (PAYLOAD[:50], "not JSON"),
            (b"[" * 100_000, "not JSON"),
            (b"[1, 2]", "top level is array"),
            (b'{"nodata": 1}', "no data key"),
            (b'{"data": {}}', "data is object"),
            (b'{"data": []}', "data array is empty"),
            (b'{"data": [1, "x", null]}', "no usable entry"),
            (b'{"data": [{"unrelated": 1}]}', "no usable entry"),
            (PROBE, "not JSON"),
        ],
        ids=[
            "empty",
            "binary",
            "text",
            "truncated",
            "deep-nesting",
            "array",
            "no-data",
            "data-object",
            "data-empty",
            "no-objects",
            "no-known-keys",
            "rqProMI",
        ],
    )
    def test_malformed_is_reported_not_raised(self, payload: bytes, reason: str) -> None:
        decoded = decode_announcement(payload)
        assert not decoded.ok
        assert decoded.entries == ()
        assert reason in decoded.error

    def test_arbitrary_bytes_never_raise(self) -> None:
        """Fuzz: every prefix of the real payload, and seeded random bytes."""
        rng = random.Random(54622)
        samples = [PAYLOAD[:cut] for cut in range(len(PAYLOAD))]
        samples += [bytes(rng.randrange(256) for _ in range(rng.randrange(200))) for _ in range(300)]
        samples += [
            bytes(rng.choice(b'{}[]":,0123456789abcdefghijklmnopqrstuvwxyz ') for _ in range(80))
            for _ in range(300)
        ]
        for sample in samples:
            decoded = decode_announcement(sample)
            assert decoded.ok or decoded.error
        # No proper prefix of the payload is a valid announcement.
        assert not any(decode_announcement(PAYLOAD[:cut]).ok for cut in range(len(PAYLOAD)))


# --- The inventory -----------------------------------------------------------


def bursts(
    source: str = UNIT,
    count: int = 5,
    start: float = 1_000.0,
    payload: bytes = PAYLOAD,
    ports: tuple[int, ...] = ANNOUNCEMENT_PORTS,
) -> list[Observation]:
    """The observed pattern: one datagram per port within a millisecond, every 3 s."""
    return [
        Observation(
            start + 3.0 * burst + 0.0002 * index,
            source,
            payload,
            CHANNEL_ANNOUNCEMENT,
            port,
            ANNOUNCEMENT_SOURCE_PORT,
        )
        for burst in range(count)
        for index, port in enumerate(ports)
    ]


class TestInventory:
    def test_four_ports_every_three_seconds_is_one_unit(self) -> None:
        inventory = build_inventory(bursts())
        assert set(inventory.announcers) == {UNIT}
        entry = inventory.announcers[UNIT]
        assert entry.mac == MAC
        assert (entry.api_port, entry.https_port) == (8001, 9001)
        assert (entry.auth_type, entry.work_mode) == (0, 0)
        assert entry.count == 20
        assert entry.bursts == 5
        assert entry.interval == pytest.approx(3.0, abs=0.01)
        assert entry.ports == set(ANNOUNCEMENT_PORTS)
        assert entry.source_ports == {ANNOUNCEMENT_SOURCE_PORT}
        assert entry.first_seen == pytest.approx(1_000.0)
        assert entry.last_seen == pytest.approx(1_012.0006)
        assert not inventory.malformed and not inventory.devices and not inventory.probes

    def test_summary_names_the_unit_by_ip_and_mac(self) -> None:
        summary = build_inventory(bursts()).summary()
        unit_lines = [line for line in summary.splitlines() if UNIT in line]
        assert unit_lines and MAC in unit_lines[0]
        assert "api 8001" in unit_lines[0] and "https 9001" in unit_lines[0]
        assert "1 device(s) seen: 1 announcing" in summary
        assert "meanings UNKNOWN" in summary

    def test_order_of_observations_does_not_matter(self) -> None:
        observations = bursts()
        forward = build_inventory(observations).announcers[UNIT]
        backward = build_inventory(list(reversed(observations))).announcers[UNIT]
        assert (forward.bursts, forward.first_seen, forward.last_seen) == (
            backward.bursts,
            backward.first_seen,
            backward.last_seen,
        )

    def test_changes_and_conflicts_are_flagged_not_overwritten(self) -> None:
        observations = (
            bursts(count=2)
            + bursts(count=1, start=1_010.0, payload=announcement(mac=OTHER_MAC))
            + bursts(source="192.0.2.31", count=1, start=1_020.0)
            + bursts(count=1, start=1_030.0, payload=announcement(work=1))
        )
        inventory = build_inventory(observations)
        summary = inventory.summary()
        assert inventory.announcers[UNIT].macs == {MAC, OTHER_MAC}
        assert "several MACs from this address" in summary
        assert f"mac {MAC} announced from several addresses: {UNIT}, 192.0.2.31" in summary
        assert "payload changed" in summary

    def test_malformed_is_recorded_in_the_inventory(self) -> None:
        observations = bursts(count=1) + [
            Observation(2_000.0, "192.0.2.99", b"not json", CHANNEL_ANNOUNCEMENT, 54622)
        ]
        inventory = build_inventory(observations)
        assert len(inventory.malformed) == 1
        (bad,) = inventory.malformed
        assert (bad.source, bad.port, bad.size) == ("192.0.2.99", 54622, 8)
        assert "not JSON" in bad.reason
        assert "192.0.2.99" not in inventory.announcers
        assert "1 undecodable datagram(s)" in inventory.summary()

    def test_classification_follows_the_channel(self) -> None:
        """A probe on an announcement port is not a probe; JSON on 3800 is not an announcer."""
        inventory = build_inventory(
            [
                Observation(1.0, "192.0.2.5", PROBE, CHANNEL_ANNOUNCEMENT, 54622),
                Observation(2.0, UNIT, PAYLOAD, CHANNEL_DISCOVERY, 3800),
            ]
        )
        assert not inventory.probes
        assert not inventory.announcers
        assert len(inventory.malformed) == 1

    def test_observations_built_positionally_still_mean_discovery(self) -> None:
        observation = Observation(1.0, "192.0.2.5", PROBE)
        assert observation.channel == CHANNEL_DISCOVERY
        assert observation.is_probe and observation.kind == "probe"

    def test_silence_and_not_listening_are_told_apart(self) -> None:
        both = build_inventory(
            [], coverage={CHANNEL_DISCOVERY: (3800,), CHANNEL_ANNOUNCEMENT: (54622,)}
        ).summary()
        assert "UDP 3800 discovery: nothing heard" in both
        assert "COEX announcements (UDP 54622): none heard" in both

        only_discovery = build_inventory([], coverage={CHANNEL_DISCOVERY: (3800,)}).summary()
        assert "COEX announcements: not listened" in only_discovery

        only_announcements = build_inventory(
            [], coverage={CHANNEL_ANNOUNCEMENT: (54622,)}
        ).summary()
        assert "UDP 3800 discovery: not listened" in only_announcements

    def test_a_password_like_key_never_reaches_the_inventory(self) -> None:
        """Nothing observed carries one. /api/v1/device/hw does, and novasun records none."""
        payload = announcement(randomPassword=FAKE_SECRET)
        observations = bursts(count=1, payload=payload)
        inventory = build_inventory(observations)
        entry = inventory.announcers[UNIT]
        assert "randomPassword" in entry.unknown_keys
        assert FAKE_SECRET not in repr(inventory)
        assert FAKE_SECRET not in inventory.summary()
        assert FAKE_SECRET not in observations[0].describe()


# --- The listener, on loopback -------------------------------------------------


class TestLoopbackListener:
    def test_decodes_announcements_sent_by_the_test(self, listener: PassiveListener) -> None:
        port = announcement_port(listener)
        thread = listener.listen_in_thread(duration=3.0)
        send(port, PAYLOAD, PAYLOAD, PAYLOAD, b"\xffnot an announcement")
        assert listener.wait_for(4, timeout=3.0)
        listener.stop()
        thread.join(timeout=2)

        inventory = listener.inventory()
        assert set(inventory.announcers) == {"127.0.0.1"}
        entry = inventory.announcers["127.0.0.1"]
        assert entry.mac == MAC
        assert (entry.api_port, entry.https_port, entry.auth_type, entry.work_mode) == (
            8001,
            9001,
            0,
            0,
        )
        assert entry.count == 3
        assert entry.first_seen <= entry.last_seen
        assert entry.ports == {port}
        assert len(inventory.malformed) == 1
        assert inventory.malformed[0].reason == "not UTF-8 text"

        summary = inventory.summary()
        assert any("127.0.0.1" in line and MAC in line for line in summary.splitlines())

    def test_malformed_datagrams_do_not_stop_the_listener(self, listener: PassiveListener) -> None:
        port = announcement_port(listener)
        thread = listener.listen_in_thread(duration=3.0)
        send(port, b"", b"[" * 4000, b'{"data": 7}', PROBE, PAYLOAD)
        assert listener.wait_for(5, timeout=3.0)
        listener.stop()
        thread.join(timeout=2)

        inventory = listener.inventory()
        assert len(inventory.malformed) == 4
        assert inventory.announcers["127.0.0.1"].count == 1
        for observation in listener.observations:
            assert observation.describe()  # never raises either

    def test_one_listen_covers_discovery_and_announcements(self, tmp_path: Path) -> None:
        log = tmp_path / "listen.log"
        instance = PassiveListener(
            "127.0.0.1", 0, join_multicast=False, log_path=log, announcement_ports=(0, 0)
        )
        try:
            coverage = instance.coverage
            assert set(coverage) == {CHANNEL_DISCOVERY, CHANNEL_ANNOUNCEMENT}
            (discovery_port,) = coverage[CHANNEL_DISCOVERY]
            first, second = coverage[CHANNEL_ANNOUNCEMENT]
            thread = instance.listen_in_thread(duration=3.0)
            send(discovery_port, PROBE)
            send(first, PAYLOAD)
            send(second, PAYLOAD)
            assert instance.wait_for(3, timeout=3.0)
        finally:
            instance.stop()
        thread.join(timeout=2)

        inventory = instance.inventory()
        assert len(inventory.probes) == 1
        entry = inventory.announcers["127.0.0.1"]
        assert entry.count == 2 and entry.ports == {first, second}

        text = log.read_text()
        start = next(line for line in text.splitlines() if line.startswith("# session start="))
        assert f"127.0.0.1:{discovery_port}/discovery" in start
        assert f"127.0.0.1:{first}/announcement" in start
        assert "channels=discovery,announcement" in start
        assert "multicast=off" in start
        end = next(line for line in text.splitlines() if line.startswith("# session end="))
        assert "observations=3" in end and "discovery=1" in end and "announcement=2" in end
        datagrams = [line.split("\t") for line in text.splitlines() if not line.startswith("#")]
        assert len(datagrams) == 3
        assert all(len(columns) == 5 for columns in datagrams)
        assert {columns[4] for columns in datagrams} == {
            str(discovery_port),
            str(first),
            str(second),
        }
        assert PAYLOAD.hex() in {columns[2] for columns in datagrams}

    def test_a_silent_listen_still_writes_a_session_record(self, tmp_path: Path) -> None:
        log = tmp_path / "listen.log"
        instance = PassiveListener(
            "127.0.0.1", None, join_multicast=False, log_path=log, announcement_ports=(0,)
        )
        try:
            thread = instance.listen_in_thread(duration=0.3)
            thread.join(timeout=2)
        finally:
            instance.stop()
        text = log.read_text()
        assert "# session start=" in text
        assert "/announcement" in text
        assert "channels=announcement" in text
        assert "multicast=off" in text
        assert "duration=0.3s" in text
        assert "# session end=" in text
        assert "observations=0" in text and "announcement=0" in text
        assert "none heard" in instance.inventory().summary()

    def test_a_password_like_payload_is_withheld_from_the_log(self, tmp_path: Path) -> None:
        log = tmp_path / "listen.log"
        instance = PassiveListener(
            "127.0.0.1", None, join_multicast=False, log_path=log, announcement_ports=(0,)
        )
        payload = announcement(randomPassword=FAKE_SECRET)
        try:
            thread = instance.listen_in_thread(duration=3.0)
            send(announcement_port(instance), payload)
            assert instance.wait_for(1, timeout=3.0)
        finally:
            instance.stop()
        thread.join(timeout=2)
        text = log.read_text()
        assert f"withheld:{len(payload)}B" in text
        assert FAKE_SECRET not in text
        assert FAKE_SECRET.encode().hex() not in text
        assert payload.hex() not in text
        # The unit is still inventoried from the safe fields.
        assert instance.inventory().announcers["127.0.0.1"].mac == MAC

    def test_listens_with_every_transmit_method_disabled(self, monkeypatch) -> None:
        """Behavioural: the listener works when its sockets cannot send or connect."""

        class NoTransmitSocket(socket.socket):
            def _refuse(self, *args, **kwargs):
                raise AssertionError("passive.py tried to transmit")

            send = sendto = sendall = sendmsg = sendfile = _refuse
            connect = connect_ex = _refuse

        restricted = types.SimpleNamespace(
            **{name: getattr(socket, name) for name in dir(socket) if not name.startswith("__")}
        )
        restricted.socket = NoTransmitSocket
        monkeypatch.setattr(passive_module, "socket", restricted)

        instance = PassiveListener(
            "127.0.0.1", 0, join_multicast=False, announcement_ports=(0,)
        )
        coverage = instance.coverage
        discovery_port = coverage[CHANNEL_DISCOVERY][0]
        announce_port = coverage[CHANNEL_ANNOUNCEMENT][0]

        def speak() -> None:
            time.sleep(0.2)
            send(discovery_port, PROBE)  # the test's own, unrestricted socket
            send(announce_port, PAYLOAD)

        speaker = threading.Thread(target=speak)
        speaker.start()
        try:
            observations = instance.listen(duration=1.0)  # in this thread: errors surface
        finally:
            instance.stop()
            speaker.join(timeout=2)
        assert {o.kind for o in observations} == {"probe", "announce"}

    def test_module_contains_no_send_or_connect(self) -> None:
        """Structural, and stricter than tests/test_monitoring.py's check."""
        source = Path(passive_module.__file__).read_text()
        code = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith("#")
        )
        for forbidden in (
            ".send(",
            ".sendto(",
            ".sendall(",
            ".sendmsg(",
            ".sendfile(",
            ".connect(",
            ".connect_ex(",
            "create_connection(",
            "SO_BROADCAST,",
        ):
            assert forbidden not in code, f"{forbidden} appears in passive.py"

    @pytest.mark.skipif(not hasattr(socket, "SO_REUSEPORT"), reason="no SO_REUSEPORT")
    def test_an_announcement_port_can_be_shared(self, listener: PassiveListener) -> None:
        """So it can sit alongside VMP or crewbox on the same host."""
        port = announcement_port(listener)
        second = PassiveListener(
            "127.0.0.1", None, join_multicast=False, announcement_ports=(port,)
        )
        try:
            assert not second.bind_failures
            assert second.coverage[CHANNEL_ANNOUNCEMENT] == (port,)
        finally:
            second.stop()

    @pytest.mark.skipif(not hasattr(socket, "SO_REUSEPORT"), reason="no SO_REUSEPORT")
    def test_the_discovery_socket_does_not_share_its_port(self) -> None:
        """Deliberate: rpProMI: replies are unicast, and a shared port could take one
        meant for a co-located control application. Broadcast-fed announcement
        sockets share; the 3800 socket does not."""
        instance = PassiveListener("127.0.0.1", 0, join_multicast=False, announcement_ports=(0,))
        try:
            options = {
                channel: sock.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT)
                for channel, sock, _bound in instance._sockets
            }
        finally:
            instance.stop()
        assert options[CHANNEL_DISCOVERY] == 0
        assert options[CHANNEL_ANNOUNCEMENT] != 0

    def test_a_busy_port_is_recorded_not_fatal(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as exclusive:
            exclusive.bind(("127.0.0.1", 0))  # no reuse options: nobody may share
            busy = exclusive.getsockname()[1]
            instance = PassiveListener(
                "127.0.0.1", None, join_multicast=False, announcement_ports=(busy, 0)
            )
            try:
                assert list(instance.bind_failures) == [f"127.0.0.1:{busy}/announcement"]
                assert len(instance.coverage[CHANNEL_ANNOUNCEMENT]) == 1
                assert "could not bind 127.0.0.1:" in instance.inventory().summary()
            finally:
                instance.stop()
            with pytest.raises(OSError):
                PassiveListener(
                    "127.0.0.1", None, join_multicast=False, announcement_ports=(busy,)
                )

    def test_nothing_to_listen_on_is_an_error(self) -> None:
        with pytest.raises(ValueError):
            PassiveListener("127.0.0.1", None, join_multicast=False)


# --- The listen command --------------------------------------------------------


def free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe_socket:
        probe_socket.bind(("127.0.0.1", 0))
        return probe_socket.getsockname()[1]


class TestListenCommand:
    def test_parser_defaults_and_flags(self, capsys) -> None:
        parser = build_parser()
        args = parser.parse_args(["listen"])
        assert args.only is None
        assert args.announcement_ports is None  # resolved to the default in cmd_listen
        assert args.bind == "0.0.0.0" and not args.no_multicast
        assert DEFAULT_ANNOUNCEMENT_PORTS == (54622,)

        assert parser.parse_args(["listen", "--only", "discovery"]).only == "discovery"
        assert parser.parse_args(["listen", "--only", "announcements"]).only == "announcements"
        assert (
            parser.parse_args(["listen", "--announcement-ports", "all"]).announcement_ports
            == ANNOUNCEMENT_PORTS
        )
        assert parser.parse_args(
            ["listen", "--announcement-ports", "54622,54700"]
        ).announcement_ports == (54622, 54700)
        for bad in ("none", "0", "70000", ","):
            with pytest.raises(SystemExit):
                parser.parse_args(["listen", "--announcement-ports", bad])
        with pytest.raises(SystemExit):
            parser.parse_args(["listen", "--only", "everything"])
        capsys.readouterr()

    def test_listen_announcements_only_on_loopback(self, tmp_path: Path, capsys) -> None:
        port = free_udp_port()
        log = tmp_path / "listen.log"
        stop = threading.Event()

        def beacon() -> None:
            # Like the unit: repeat, so it does not matter when the bind lands.
            while not stop.wait(0.1):
                send(port, PAYLOAD)

        speaker = threading.Thread(target=beacon, daemon=True)
        speaker.start()
        try:
            code = main(
                [
                    "listen",
                    "--only",
                    "announcements",
                    "--bind",
                    "127.0.0.1",
                    "--announcement-ports",
                    str(port),
                    "--duration",
                    "1.5",
                    "--log",
                    str(log),
                ]
            )
        finally:
            stop.set()
            speaker.join(timeout=2)
        assert code == 0
        captured = capsys.readouterr()
        assert f"127.0.0.1:{port} (announcement)" in captured.err
        assert "transmitting nothing" in captured.err
        assert "announce" in captured.out
        assert any(
            "127.0.0.1" in line and MAC in line and "api 8001" in line
            for line in captured.out.splitlines()
        )
        assert "UDP 3800 discovery: not listened" in captured.out
        text = log.read_text()
        assert "# session start=" in text and "# session end=" in text
