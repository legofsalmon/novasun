"""A COEX controller's reported name is a label, not a model.

On the MX40 Pro read in 2026-09 ``monitor/info.name`` was ``"MX40 Pro_<digits>"``
and happened to carry the model. On an MX30 (2026-09-26; firmware v1.5.1 as
reported by its operator, and read over SNMP later that day) the same field was a plain word with no model in it,
and every read-only path -- survey, watch, identify -- reported that word *as
the model*, with four Ethernet ports assumed alongside (OBSERVED, one unit).
The API documents a custom-name setter, so the field is best read as an
operator-settable label whose factory form is ``"<model>_<digits>"`` (REASONED).

These tests pin the fix across all three paths with a synthetic label. Nothing
from the show that produced the finding is here.

Later that day a capture of VMP opening the same unit showed where the model
*is* served: ``GET /api/v1/device/hw`` carried ``name`` "MX30" and ``modelID``
5138, with the controller's name in ``customName`` (OBSERVED, one unit,
hwVersion V1.5.1; that it is the same label monitor/info reports is REASONED).
It also carried ``randomPassword``, served to that unauthenticated GET
(OBSERVED). The second half of this file pins both: the model named from that
endpoint when it answers, unchanged behaviour when it does not, and the secret
absent from every output. Those tests run against the synthetic unit in
``test_display_state.py`` rather than the simulator.
"""

from __future__ import annotations

import json

import pytest

from novasun import devices
from novasun.cli import build_parser, main
from novasun.coex import CoexClient
from novasun.coexsim import CoexState, SimulatedCoexController
from novasun.devices import Family, identify
from novasun.monitor import CoexMonitor, MonitorSnapshot, ReadOnlyCoexClient, _interpret
from novasun.survey import Survey, survey_device

from test_display_state import (
    DISPLAY_STATE,
    FAKE_RANDOM_PASSWORD,
    HARDWARE,
    MONITOR_INFO,
    SyntheticCoexUnit,
    closed_port,
    display_state,
    hardware,
    monitor_info,
)

LABEL = "Stage left"  # synthetic; the real one is show data and stays out


def _serve(state: CoexState) -> SimulatedCoexController:
    server = SimulatedCoexController("127.0.0.1", 0, state)
    server.serve_in_thread()
    return server


@pytest.fixture()
def renamed():
    """A controller whose operator has replaced the factory name.

    ``/device/hw`` is withheld (a 404 on this profile): these tests pin the
    behaviour of a unit that does not serve it, whatever the simulator does.
    """
    state = CoexState(custom_name=LABEL)
    state.missing_endpoints.add(HARDWARE)
    server = _serve(state)
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


# --- /api/v1/device/hw ---------------------------------------------------------


@pytest.fixture()
def mx30():
    """A synthetic renamed MX30 that serves /device/hw, as the real one did."""
    unit = SyntheticCoexUnit({
        MONITOR_INFO: monitor_info(LABEL),
        HARDWARE: hardware(),
        DISPLAY_STATE: display_state(0),
    })
    yield unit
    unit.stop()


def _all_outputs(host: str, port: int, capsys) -> str:
    """Every read-only output novasun makes from one unit, as one string."""
    with CoexMonitor(host, port, interval=0.0) as monitor:
        snapshot = monitor.poll()
    device = survey_device(host, http_port=port, control_port=closed_port())
    identification = identify(host, timeout=2.0, http_port=port, register_bus=False)
    assert main(["watch", host, "--port", str(port), "--once"]) == 0
    printed = capsys.readouterr().out
    return "\n".join([
        json.dumps(snapshot.raw, default=str),
        repr(snapshot),
        snapshot.summary(),
        json.dumps(Survey(devices=[device]).to_dict()),  # what survey --json prints
        device.summary(),
        repr(device),
        identification.summary(),
        repr(identification),
        printed,
    ])


class TestHardwareIdentity:
    def test_the_fixture_really_carries_the_secret(self) -> None:
        """Otherwise the absence checks below would prove nothing."""
        assert hardware()["randomPassword"] == FAKE_RANDOM_PASSWORD
        assert json.dumps(hardware()).count(FAKE_RANDOM_PASSWORD) == 1

    def test_hardware_info_drops_random_password(self, mx30) -> None:
        host, port = mx30.address
        for client in (CoexClient(host, port, timeout=2.0),
                       ReadOnlyCoexClient(host, port, timeout=2.0)):
            info = client.hardware_info()
            assert "randomPassword" not in info
            assert (info["name"], info["modelID"], info["hwVersion"]) == ("MX30", 5138, "V1.5.1")
            assert "randomPassword" not in client.request("GET", HARDWARE)

    def test_the_monitor_names_the_model_from_hw(self, mx30) -> None:
        """The label is not a model; /device/hw's name is (OBSERVED pairing)."""
        host, port = mx30.address
        with CoexMonitor(host, port, interval=0.0) as monitor:
            snapshot = monitor.poll()
        assert snapshot.model == "MX30"
        assert snapshot.device_name == LABEL
        assert snapshot.model_id == 5138
        assert snapshot.firmware == "V1.5.1"
        assert snapshot.serial == "SIM-MX30-SERIAL-0030"
        lines = snapshot.summary().splitlines()
        assert lines[0] == f"MX30  {LABEL}"
        assert "  firmware    V1.5.1" in lines
        assert "randomPassword" not in snapshot.raw["hardware"]

    def test_the_survey_reports_the_model_ports_and_id(self, mx30) -> None:
        host, port = mx30.address
        device = survey_device(host, http_port=port, control_port=closed_port())
        assert device.reachable and device.family == "coex"
        assert device.model == "MX30"
        assert device.model_id == 5138
        assert device.name == LABEL
        assert device.ethernet_ports == 10  # the MX30 profile's OBSERVED count
        assert device.firmware == "V1.5.1"
        assert device.serial == "SIM-MX30-SERIAL-0030"

    def test_identify_names_the_model_from_hw(self, mx30) -> None:
        host, port = mx30.address
        identification = identify(host, timeout=2.0, http_port=port, register_bus=False)
        assert identification.profile is devices.coex_profile_for("MX30")
        assert identification.device_name == LABEL
        assert identification.serial == "SIM-MX30-SERIAL-0030"
        lines = identification.summary().splitlines()
        assert "  model        MX30  (modelID 5138)" in lines
        assert f"  name         {LABEL}" in lines
        assert ("GET", HARDWARE) in mx30.requests

    def test_identify_skips_hw_when_the_name_already_gives_the_model(self) -> None:
        """One GET fewer against a unit whose factory name carries its model."""
        unit = SyntheticCoexUnit({MONITOR_INFO: monitor_info("MX40 Pro_000001")})
        try:
            host, port = unit.address
            identification = identify(host, timeout=2.0, http_port=port, register_bus=False)
        finally:
            unit.stop()
        assert identification.profile.name == "MX40 Pro"
        assert ("GET", HARDWARE) not in unit.requests

    def test_a_model_id_alone_names_the_mx30(self) -> None:
        snapshot = _interpret(MonitorSnapshot(timestamp=0.0, raw={
            "monitoring": monitor_info(LABEL), "hardware": hardware(name=""),
        }))
        assert snapshot.model == "MX30" and snapshot.model_id == 5138

    def test_a_hw_name_equal_to_the_label_is_not_a_model(self) -> None:
        """If some firmware put the label in ``name``, it must not become a model."""
        snapshot = _interpret(MonitorSnapshot(timestamp=0.0, raw={
            "monitoring": monitor_info(LABEL),
            "hardware": hardware(name=LABEL, modelID=None),
        }))
        assert snapshot.model is None
        assert snapshot.device_name == LABEL

    def test_an_unknown_hw_model_is_reported_with_its_ports_unknown(self) -> None:
        unit = SyntheticCoexUnit({
            MONITOR_INFO: monitor_info(LABEL),
            HARDWARE: hardware(name="MX99 Ultra", modelID=9999),
        })
        try:
            host, port = unit.address
            device = survey_device(host, http_port=port, control_port=closed_port())
            identification = identify(host, timeout=2.0, http_port=port, register_bus=False)
        finally:
            unit.stop()
        # The survey reports the model field's value; the table does not know
        # it, so nothing about its ports is claimed.
        assert device.model == "MX99 Ultra"
        assert device.model_id == 9999
        assert device.ethernet_ports is None
        # identify() names only models its table knows.
        assert identification.profile is devices.GENERIC_COEX

    @pytest.mark.parametrize("absent", [404, None])
    def test_without_hw_nothing_changes(self, absent) -> None:
        """A 404 (the MX40 Pro's absent-path answer) or the MX30's empty 200."""
        routes = {MONITOR_INFO: monitor_info(LABEL)}
        if absent is not None:
            routes[HARDWARE] = absent
        unit = SyntheticCoexUnit(routes)
        try:
            host, port = unit.address
            device = survey_device(host, http_port=port, control_port=closed_port())
            identification = identify(host, timeout=2.0, http_port=port, register_bus=False)
        finally:
            unit.stop()
        assert device.model is None and device.name == LABEL
        assert device.ethernet_ports is None and device.firmware is None
        assert identification.profile is devices.GENERIC_COEX
        assert identification.device_name == LABEL

    def test_random_password_appears_in_no_output(self, mx30, capsys) -> None:
        """Snapshot, its raw payloads, summary(), survey --json, survey summary,
        identify, and watch's printed output: none carries the field or value."""
        host, port = mx30.address
        everything = _all_outputs(host, port, capsys)
        assert "MX30" in everything and LABEL in everything  # the outputs are real
        assert FAKE_RANDOM_PASSWORD not in everything
        assert "randomPassword" not in everything

    def test_a_hand_built_snapshot_is_scrubbed_too(self) -> None:
        """A snapshot made from a captured payload, bypassing the client."""
        raw = {"hardware": hardware(), "monitoring": monitor_info(LABEL)}
        snapshot = _interpret(MonitorSnapshot(timestamp=0.0, raw=raw))
        assert "randomPassword" not in snapshot.raw["hardware"]
        assert FAKE_RANDOM_PASSWORD not in json.dumps(snapshot.raw)
        assert snapshot.model == "MX30"

    def test_only_gets_were_sent(self, mx30, capsys) -> None:
        host, port = mx30.address
        _all_outputs(host, port, capsys)
        assert {method for method, _path in mx30.requests} == {"GET"}
