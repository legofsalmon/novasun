"""The CLI is a real interface, so its wiring is tested like one."""

from __future__ import annotations

import json

import pytest

from novasun import registers as reg
from novasun.cli import build_parser, main
from novasun.protocol import Target, write_request
from novasun.simulator import SimulatedController

# argparse renders every help string through %-formatting, so a literal '%'
# anywhere in the parser crashes --help at runtime rather than at import.
SUBCOMMANDS = [
    [],
    ["discover"],
    ["identify"],
    ["models"],
    ["inputs"],
    ["select-input"],
    ["outputs"],
    ["bringup"],
    ["serve"],
    ["survey"],
    ["listen"],
    ["watch"],
    ["simulate"],
    ["info"],
    ["status"],
    ["brightness"],
    ["blackout"],
    ["freeze"],
    ["test-pattern"],
    ["read"],
    ["write"],
    ["monitor"],
    ["capture"],
    ["capture", "decode"],
    ["capture", "report"],
    ["capture", "diff"],
    ["proxy"],
    ["names"],
    ["names", "import"],
    ["coex"],
    ["coex", "snapshot"],
    ["coex", "diff"],
]


@pytest.mark.parametrize("path", SUBCOMMANDS, ids=lambda p: " ".join(p) or "(root)")
def test_help_renders(path, capsys) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(path + ["--help"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out


def test_parser_has_no_literal_percent_in_help() -> None:
    """The failure mode above, caught at its root rather than per-command."""
    parser = build_parser()

    def walk(action_container):
        for action in action_container._actions:
            if action.help:
                assert "%" not in action.help.replace("%%", ""), action.dest
            # Sub-parser actions map names to parsers; ordinary `choices` are
            # a plain list of values and must not be recursed into.
            choices = getattr(action, "choices", None)
            if isinstance(choices, dict):
                for subparser in choices.values():
                    if hasattr(subparser, "_actions"):
                        walk(subparser)

    walk(parser)


@pytest.fixture()
def device():
    server = SimulatedController("127.0.0.1", 0)
    server.serve_in_thread()
    yield server
    server.shutdown()
    server.server_close()


def test_status_round_trip(device, capsys) -> None:
    host, port = device.address
    assert main(["brightness", host, "60", "--port", str(port)]) == 0
    assert main(["test-pattern", host, "blue", "--port", str(port)]) == 0
    assert main(["status", host, "--port", str(port)]) == 0
    out = capsys.readouterr().out
    assert "blue" in out
    assert f"{reg.brightness_byte(60)} / 255" in out


def test_capture_commands_on_a_session_log(tmp_path, capsys) -> None:
    log = tmp_path / "session.jsonl"
    frames = [
        write_request(reg.GLOBAL_BRIGHTNESS, b"\x40", Target.all_receiving_cards(), serno=1),
        write_request(reg.SELF_TEST_MODE, b"\x02", Target.all_receiving_cards(), serno=2),
    ]
    with log.open("w") as handle:
        for index, packet in enumerate(frames):
            handle.write(
                json.dumps(
                    {
                        "timestamp": 1700000000.0 + index,
                        "source": "pc",
                        "destination": "device",
                        "frame": packet.to_bytes().hex(),
                    }
                )
                + "\n"
            )

    assert main(["capture", "decode", str(log)]) == 0
    assert "GLOBAL_BRIGHTNESS" in capsys.readouterr().out

    report = tmp_path / "report.md"
    assert main(["capture", "report", str(log), "-o", str(report)]) == 0
    assert "SELF_TEST_MODE" in report.read_text()

    other = tmp_path / "other.jsonl"
    changed = write_request(
        reg.GLOBAL_BRIGHTNESS, b"\xff", Target.all_receiving_cards(), serno=1
    )
    with other.open("w") as handle:
        handle.write(
            json.dumps(
                {
                    "timestamp": 1700000000.0,
                    "source": "pc",
                    "destination": "device",
                    "frame": changed.to_bytes().hex(),
                }
            )
            + "\n"
        )
    assert main(["capture", "diff", str(log), str(other)]) == 0
    output = capsys.readouterr().out
    assert "0x02000001" in output and "40 -> ff" in output


def test_coex_snapshot_issues_only_gets(capsys) -> None:
    """The shipped snapshot command must be read-only in fact, not by luck.

    It once built a full CoexClient and was read-only only because snapshot()
    happened not to write. Against a controller running a live show that is not
    a property worth having. The simulator logs every request's method, so this
    is checked behaviourally rather than by reading the source.
    """
    from novasun.coexsim import SimulatedCoexController

    server = SimulatedCoexController("127.0.0.1", 0)
    server.serve_in_thread()
    try:
        host, port = server.address
        assert main(["coex", "snapshot", host, "--port", str(port)]) == 0
        payload = json.loads(capsys.readouterr().out)
    finally:
        server.shutdown()
        server.server_close()
    assert {"device", "screens", "cabinets", "inputs", "presets",
            "monitoring", "audio", "snmp"} <= set(payload)
    assert {method for method, _path, _body in server.state.requests} == {"GET"}


def test_coex_snapshot_refuses_a_write_before_a_socket_opens(monkeypatch) -> None:
    """Structural: the command hands snapshot() a read-only client.

    If a write ever crept into snapshot(), this is what must happen -- a refusal
    inside the client, before anything reaches the network -- rather than the
    request quietly going out. The refusal itself is tested in test_monitoring;
    this pins that the CLI is on the right side of it.
    """
    from novasun import coex as coex_module
    from novasun.monitor import WriteAttempted

    def would_write(client, endpoints=None):
        return client.request("PUT", "/api/v1/screen", {"brightness": 0})

    monkeypatch.setattr(coex_module, "snapshot", would_write)
    with pytest.raises(WriteAttempted):
        main(["coex", "snapshot", "127.0.0.1", "--port", "1"])
