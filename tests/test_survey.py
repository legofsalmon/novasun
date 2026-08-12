"""The network-wide read-only survey, and its serialised contract."""

from __future__ import annotations

import json
import socket

import pytest

from novasun.coexsim import SimulatedCoexController
from novasun.simulator import SimulatedController
from novasun.survey import SCHEMA_VERSION, Survey, survey_device, survey_network


def closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture()
def coex():
    server = SimulatedCoexController("127.0.0.1", 0)
    server.serve_in_thread()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture()
def vx4s():
    server = SimulatedController("127.0.0.1", 0, model_id=0x6107)
    server.serve_in_thread()
    yield server
    server.shutdown()
    server.server_close()


class TestCoexSurvey:
    def test_describes_a_coex_controller_over_http(self, coex) -> None:
        host, port = coex.address
        device = survey_device(host, http_port=port, control_port=closed_port())

        assert device.reachable
        assert device.control_path == "http"
        assert device.monitoring_available == "http"
        assert device.model == "MX40 Pro"
        assert device.family == "coex"
        assert device.status["cabinets_total"] == 8
        assert device.status["cabinets_online"] == 8
        assert device.status["healthy"]
        assert device.status["signal_present"] == ["HDMI 1", "12G-SDI"]

    def test_survey_never_writes(self, coex) -> None:
        host, port = coex.address
        survey_device(host, http_port=port, control_port=closed_port())
        assert all(method == "GET" for method, _path, _body in coex.state.requests)

    def test_offline_cabinets_surface(self, coex) -> None:
        coex.state.cabinets[2]["online"] = False
        host, port = coex.address
        device = survey_device(host, http_port=port, control_port=closed_port())
        assert not device.status["healthy"]
        assert device.status["cabinets_offline"] == [str(coex.state.cabinets[2]["id"])]


class TestRegisterBusSurvey:
    def test_register_bus_is_not_touched_by_default(self, vx4s) -> None:
        """A monitoring tool must not take a control session by accident."""
        host, port = vx4s.address
        vx4s.log.clear()
        device = survey_device(host, http_port=closed_port(), control_port=port)

        assert not device.reachable
        assert vx4s.log == []  # nothing was sent to the controller
        assert "allow_register_bus=False" in " ".join(device.errors)

    def test_opt_in_identifies_over_the_register_bus(self, vx4s) -> None:
        host, port = vx4s.address
        device = survey_device(
            host, http_port=closed_port(), control_port=port, allow_register_bus=True
        )

        assert device.reachable
        assert device.control_path == "register-bus"
        assert device.model == "VX4S"
        assert device.ethernet_ports == 4
        assert device.monitoring_available == "register-bus"
        assert [i["label"] for i in device.inputs][:2] == ["DVI", "HDMI"]

    def test_uhd_jr_reports_its_full_output_complement(self) -> None:
        server = SimulatedController("127.0.0.1", 0, model_id=0x6205)
        server.serve_in_thread()
        try:
            host, port = server.address
            device = survey_device(
                host, http_port=closed_port(), control_port=port, allow_register_bus=True
            )
            assert device.model == "NovaPro UHD Jr"
            assert device.ethernet_ports == 16
            assert device.fibre_ports == 4
            # Inputs are listed, but none is switchable -- the honest state.
            assert device.inputs and not any(i["switchable"] for i in device.inputs)
        finally:
            server.shutdown()
            server.server_close()


class TestSurveyContract:
    def test_serialises_to_json(self, coex) -> None:
        host, port = coex.address
        survey = Survey(devices=[survey_device(host, http_port=port, control_port=closed_port())])
        payload = json.dumps(survey.to_dict())
        restored = json.loads(payload)

        assert restored["schema_version"] == SCHEMA_VERSION
        assert restored["devices"][0]["model"] == "MX40 Pro"
        assert restored["devices"][0]["status"]["cabinets_total"] == 8

    def test_unreachable_device_still_serialises(self) -> None:
        device = survey_device(
            "127.0.0.1", timeout=0.2, http_port=closed_port(), control_port=closed_port()
        )
        assert not device.reachable
        assert json.dumps(device.to_dict())
        assert "unreachable" in device.summary()

    def test_no_probe_means_no_broadcast(self) -> None:
        """allow_probe=False with no hosts contacts nothing at all."""
        survey = survey_network(hosts=[], allow_probe=False)
        assert survey.devices == []
        assert survey.probed is False

    def test_supplied_hosts_are_marked_as_such(self, coex) -> None:
        host, port = coex.address
        survey = survey_network(hosts=[host], allow_probe=False, timeout=1.0)
        # The default COEX port is not the simulator's, so this is unreachable;
        # the point under test is provenance of the address, not reachability.
        assert survey.devices[0].discovered_by == "supplied"
        assert survey.devices[0].address == host
