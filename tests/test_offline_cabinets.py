"""An unplugged wall must never read as healthy.

OBSERVED on one MX30 (firmware V1.5.1, 2026-09-26, attended): with every output
data line unplugged and the controller left up, ``/api/v1/device/cabinet``
returned no entries and ``/api/v1/screen/cabinet/count`` a CabinetCount of 0,
while ``/api/v1/device/monitor/info`` kept all 72 cabinets listed, every card
link true and temperatures reading for ~8.5 minutes. Counting from monitor/info
therefore reported an unplugged wall as healthy. These tests pin the fix at
every layer that reports health: the pure interpreter, the live monitor, the
survey and the application.
"""

from __future__ import annotations

import pytest
from conftest import (
    MX30_LIKE_CABINET_COUNT,
    MX30_LIKE_CABINETS,
    MX30_LIKE_MONITOR_INFO,
    MX30_UNPLUGGED_CABINET_COUNT,
    MX30_UNPLUGGED_CABINETS,
    MX30_UNPLUGGED_MONITOR_INFO,
    closed_port,
    host_key,
)

from novasun.app.state import Application
from novasun.coexsim import CoexState, SimulatedCoexController
from novasun.monitor import CoexMonitor, interpret_coex_status
from novasun.survey import survey_device

CARRYING = {c["outputID"] for c in MX30_LIKE_CABINETS}


class TestInterpretCoexStatus:
    def test_the_connected_fixture_is_healthy(self) -> None:
        status = interpret_coex_status(MX30_LIKE_MONITOR_INFO, MX30_LIKE_CABINETS, MX30_LIKE_CABINET_COUNT)
        assert status["healthy"] is True and status["health_reasons"] == []
        assert status["cabinets_online"] == status["cabinets_total"] == 3

    def test_the_unplugged_fixture_is_not_healthy(self) -> None:
        status = interpret_coex_status(
            MX30_UNPLUGGED_MONITOR_INFO, MX30_UNPLUGGED_CABINETS, MX30_UNPLUGGED_CABINET_COUNT,
            expected=3, carrying=CARRYING,
        )
        assert status["healthy"] is False
        assert status["cabinets_online"] == 0 and status["connected_cabinets"] == 0
        assert status["cabinets_total"] == 3
        assert "no cabinets connected" in status["health_reasons"]
        assert "3 of 3 cabinet(s) disconnected" in status["health_reasons"]
        assert any(r.startswith("no link on output(s) carrying cabinets") for r in status["health_reasons"])
        # monitor/info still lists everything; its stale readings are not shown.
        assert status["cabinets_listed"] == 3
        assert "temperature_c" not in status

    def test_without_memory_an_empty_wall_is_still_not_healthy(self) -> None:
        status = interpret_coex_status(MX30_UNPLUGGED_MONITOR_INFO, MX30_UNPLUGGED_CABINETS,
                                       MX30_UNPLUGGED_CABINET_COUNT)
        assert status["healthy"] is False and "no cabinets connected" in status["health_reasons"]

    def test_monitor_info_alone_is_unknown(self) -> None:
        status = interpret_coex_status(MX30_LIKE_MONITOR_INFO)
        assert status["healthy"] is False
        assert status["cabinets_online"] is None and status["cabinets_total"] is None


@pytest.fixture()
def mx30():
    server = SimulatedCoexController("127.0.0.1", 0, CoexState(model="MX30"))
    server.serve_in_thread()
    yield server
    server.shutdown()
    server.server_close()


class TestLiveMonitor:
    def test_an_unplug_between_slow_reads_is_caught(self, mx30) -> None:
        host, port = mx30.address
        monitor = CoexMonitor(host, port, timeout=2.0, interval=0.0)
        first = monitor.poll(include_slow=True)
        assert first.healthy, first.health_reasons
        mx30.state.unplug_outputs()
        # Not a slow poll: the cabinet list would come from the cache, but the
        # count disagrees with it, so the list is re-read at once.
        second = monitor.poll(include_slow=False)
        assert second.healthy is False
        assert second.cabinets == [] and second.connected_cabinets == 0
        assert f"{first.connected_cabinets} of {first.connected_cabinets} cabinet(s) disconnected" in second.health_reasons
        assert "online" in second.summary() and "! no cabinets connected" in second.summary()


class TestSurveyAndApplication:
    def test_survey_of_an_unplugged_wall(self, mx30) -> None:
        mx30.state.unplug_outputs()
        host, port = mx30.address
        result = survey_device(host, http_port=port)
        assert result.status["healthy"] is False
        assert result.status["connected_cabinets"] == 0
        assert "no cabinets connected" in result.status["health_reasons"]

    def test_the_application_reports_disconnected_cabinets(self, mx30) -> None:
        application = Application(refresh_interval=60.0, timeout=1.0)
        try:
            _host, port = mx30.address
            device = application.add(host_key(mx30), http_port=port, control_port=closed_port())
            before = device.state.status
            assert before["healthy"] is True and before["cabinets_online"] == before["cabinets_total"]
            mx30.state.unplug_outputs()
            after = device.refresh(force=True).status
            assert after["cabinets_online"] == 0
            assert after["cabinets_total"] == before["cabinets_total"]
            assert after["healthy"] is False
        finally:
            application.stop()
