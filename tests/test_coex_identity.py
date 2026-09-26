"""A COEX controller's reported name is a label, not a model.

On the MX40 Pro read in 2026-09 ``monitor/info.name`` was ``"MX40 Pro_<digits>"``
and happened to carry the model. On an MX30 (2026-09-26; firmware v1.5.1 as
reported by its operator) the same field was a plain word with no model in it,
and every read-only path -- survey, watch, identify -- reported that word *as
the model*, with four Ethernet ports assumed alongside (OBSERVED, one unit).
The API documents a custom-name setter, so the field is best read as an
operator-settable label whose factory form is ``"<model>_<digits>"`` (REASONED).

These tests pin the fix across all three paths with a synthetic label. Nothing
from the show that produced the finding is here.
"""

from __future__ import annotations

import json

import pytest

from novasun import devices
from novasun.cli import build_parser, main
from novasun.coexsim import CoexState, SimulatedCoexController
from novasun.devices import Family, identify
from novasun.monitor import CoexMonitor
from novasun.survey import survey_device

from conftest import closed_port

LABEL = "Stage left"  # synthetic; the real one is show data and stays out


def _serve(state: CoexState) -> SimulatedCoexController:
    server = SimulatedCoexController("127.0.0.1", 0, state)
    server.serve_in_thread()
    return server


@pytest.fixture()
def renamed():
    """A controller whose operator has replaced the factory name."""
    server = _serve(CoexState(custom_name=LABEL))
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture()
def factory():
    """The default: the factory-style ``"<model>_000001"`` name."""
    server = _serve(CoexState())
    yield server
    server.shutdown()
    server.server_close()


class TestRenamedController:
    def test_survey_reports_the_name_and_no_model(self, renamed) -> None:
        host, port = renamed.address
        device = survey_device(host, http_port=port, control_port=closed_port())

        assert device.reachable and device.control_path == "http"
        assert device.family == "coex"
        assert device.name == LABEL
        assert device.model is None
        # The generic profile's four ports are an assumption, not a reading.
        assert device.ethernet_ports is None
        assert device.status["cabinets_total"] == 8
        # And the JSON a consumer reads says the same: model null, name kept.
        serialised = json.loads(json.dumps(device.to_dict()))
        assert serialised["model"] is None and serialised["name"] == LABEL

    def test_watch_prints_the_name_and_unknown_model(self, renamed, capsys) -> None:
        host, port = renamed.address
        assert main(["watch", host, "--port", str(port), "--once"]) == 0
        first_line = capsys.readouterr().out.splitlines()[0]
        assert first_line == f"unknown model  {LABEL}"

    def test_monitor_snapshot_has_no_model(self, renamed) -> None:
        host, port = renamed.address
        with CoexMonitor(host, port, interval=0.0) as monitor:
            snapshot = monitor.poll()
        assert snapshot.model is None
        assert snapshot.device_name == LABEL

    def test_identify_prints_unknown_model_with_the_name(self, renamed) -> None:
        host, port = renamed.address
        identification = identify(host, timeout=2.0, http_port=port, register_bus=False)

        assert identification.reachable_http
        assert identification.profile is devices.GENERIC_COEX
        assert identification.profile.family is Family.COEX
        assert identification.device_name == LABEL
        lines = identification.summary().splitlines()
        assert "  model        unknown" in lines
        assert f"  name         {LABEL}" in lines
        assert not any(line.startswith("  model") and LABEL in line for line in lines)
        assert any("(assumed)" in line for line in lines if line.startswith("  outputs"))

    def test_nothing_but_gets_were_sent(self, renamed) -> None:
        host, port = renamed.address
        survey_device(host, http_port=port, control_port=closed_port())
        identify(host, timeout=2.0, http_port=port, register_bus=False)
        assert {method for method, _path, _body in renamed.state.requests} == {"GET"}


class TestFactoryNameStillResolves:
    """The MX40 Pro's ``"<model>_<digits>"`` form must keep identifying the model."""

    def test_survey(self, factory) -> None:
        host, port = factory.address
        device = survey_device(host, http_port=port, control_port=closed_port())
        assert device.model == "MX40 Pro"
        assert device.name == "MX40 Pro_000001"
        assert device.ethernet_ports == 4

    def test_watch(self, factory, capsys) -> None:
        host, port = factory.address
        assert main(["watch", host, "--port", str(port), "--once"]) == 0
        assert capsys.readouterr().out.splitlines()[0] == "MX40 Pro  MX40 Pro_000001"

    def test_identify(self, factory) -> None:
        host, port = factory.address
        identification = identify(host, timeout=2.0, http_port=port, register_bus=False)
        assert identification.profile.name == "MX40 Pro"
        assert identification.profile.model_known
        assert identification.device_name == "MX40 Pro_000001"
        assert "  model        MX40 Pro" in identification.summary().splitlines()


def test_the_simulator_knob_is_reachable_from_the_cli() -> None:
    """``simulate coex --name`` builds the renamed state these tests use."""
    args = build_parser().parse_args(["simulate", "coex", "--name", LABEL])
    assert args.name == LABEL
    assert CoexState(model=args.model or "MX40 Pro", custom_name=args.name).custom_name == LABEL
