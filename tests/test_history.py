"""Monitoring history and alerts.

The rules exist to avoid crying wolf, so most of these test the *restraint*:
not firing on one dropped poll, not flapping on a reading that sits on a
threshold, and clearing loudly enough that a log does not read as permanently
on fire.
"""

from __future__ import annotations

import json

import pytest

from novasun.app.history import (
    AlertEngine,
    Series,
    Severity,
    Thresholds,
)


def state(address="10.0.0.1", reachability="online", temperature=None, cabinets=None):
    status = {}
    if temperature is not None:
        status["temperature_c"] = temperature
    if cabinets is not None:
        status["cabinets_total"], status["cabinets_online"] = cabinets
    return {"address": address, "reachability": reachability, "status": status}


class TestSeries:
    def test_is_bounded(self) -> None:
        series = Series("t", maxlen=5)
        for value in range(20):
            series.add(value)
        assert len(series.samples) == 5
        assert series.latest == 19

    def test_summary_reports_direction(self) -> None:
        series = Series("t")
        for value in [20, 25, 30, 35]:
            series.add(value)
        summary = series.summary()
        assert summary["min"] == 20 and summary["max"] == 35
        assert summary["trend"] == 15  # climbing, which is the useful fact
        assert summary["mean"] == 27.5

    def test_empty_summary_is_safe(self) -> None:
        assert Series("t").summary() == {"name": "t", "count": 0}


class TestOfflineDwell:
    def test_one_missed_poll_does_not_alert(self) -> None:
        """A single dropped poll on a busy network is not an outage."""
        engine = AlertEngine(Thresholds(offline_ticks=2))
        engine.observe(state())
        events = engine.observe(state(reachability="unreachable"))
        assert events == []
        assert engine.alerts == {}

    def test_sustained_loss_alerts(self) -> None:
        engine = AlertEngine(Thresholds(offline_ticks=2))
        engine.observe(state())
        engine.observe(state(reachability="unreachable"))
        events = engine.observe(state(reachability="unreachable"))

        assert len(events) == 1
        assert events[0].severity == Severity.CRITICAL
        assert len(engine.active()) == 1

    def test_recovery_clears_and_is_itself_an_event(self) -> None:
        """"Came back at 19:44" matters as much as the failure."""
        engine = AlertEngine(Thresholds(offline_ticks=1))
        engine.observe(state())
        engine.observe(state(reachability="unreachable"))
        assert engine.active()

        events = engine.observe(state())
        assert not engine.active()
        assert len(events) == 1
        assert "came back online" in events[0].message
        assert events[0].severity == Severity.INFO

    def test_in_use_is_a_warning_not_a_critical(self) -> None:
        """NovaLCT holding the session is not the same as a dead processor."""
        engine = AlertEngine(Thresholds(offline_ticks=1))
        engine.observe(state(reachability="in-use"))
        alert = engine.active()[0]
        assert alert.severity == Severity.WARNING
        assert "NovaLCT" in alert.message

    def test_repeated_failures_do_not_duplicate_the_alert(self) -> None:
        engine = AlertEngine(Thresholds(offline_ticks=1))
        for _ in range(5):
            engine.observe(state(reachability="unreachable"))
        assert len(engine.active()) == 1
        assert len(engine.events) == 1


class TestTemperatureHysteresis:
    def engine(self) -> AlertEngine:
        return AlertEngine(
            Thresholds(
                temperature_warning=45.0,
                temperature_critical=60.0,
                temperature_clear=42.0,
                offline_ticks=1,
            )
        )

    def test_warns_above_the_threshold(self) -> None:
        engine = self.engine()
        engine.observe(state(temperature=46.0))
        assert engine.active()[0].severity == Severity.WARNING

    def test_does_not_flap_between_clear_and_warning(self) -> None:
        """The whole point of a separate clear threshold."""
        engine = self.engine()
        engine.observe(state(temperature=46.0))
        assert len(engine.events) == 1

        for value in [44.0, 46.0, 43.5, 44.9]:
            engine.observe(state(temperature=value))
        # Still one alert, still one event: no flapping in the band.
        assert len(engine.active()) == 1
        assert len(engine.events) == 1

    def test_clears_only_below_the_clear_threshold(self) -> None:
        engine = self.engine()
        engine.observe(state(temperature=46.0))
        engine.observe(state(temperature=43.0))
        assert engine.active(), "43 is in the hysteresis band, must not clear"
        engine.observe(state(temperature=41.0))
        assert not engine.active()

    def test_escalates_to_critical(self) -> None:
        engine = self.engine()
        engine.observe(state(temperature=46.0))
        events = engine.observe(state(temperature=61.0))
        assert len(events) == 1 and "escalated" in events[0].message
        assert engine.active()[0].severity == Severity.CRITICAL

    def test_escalation_revokes_acknowledgement(self) -> None:
        """An operator agreed to ignore a warning, not a critical."""
        engine = self.engine()
        engine.observe(state(temperature=46.0))
        key = engine.active()[0].key
        assert engine.acknowledge(key)
        assert engine.active()[0].acknowledged

        engine.observe(state(temperature=61.0))
        assert not engine.active()[0].acknowledged

    def test_does_not_de_escalate_noisily(self) -> None:
        engine = self.engine()
        engine.observe(state(temperature=61.0))
        engine.observe(state(temperature=46.0))
        # Still critical until it actually clears; no downgrade churn.
        assert engine.active()[0].severity == Severity.CRITICAL
        assert len(engine.events) == 1

    def test_can_be_switched_off(self) -> None:
        engine = AlertEngine(Thresholds(temperature_alerts=False))
        engine.observe(state(temperature=99.0))
        assert not engine.active()


class TestCabinets:
    def test_a_lost_cabinet_alerts_with_a_timestamp(self) -> None:
        engine = AlertEngine(Thresholds(offline_ticks=1))
        engine.observe(state(cabinets=(8, 8)))
        events = engine.observe(state(cabinets=(8, 7)))

        assert len(events) == 1
        assert "1 of 8 cabinet(s) offline" in events[0].message
        assert events[0].timestamp > 0

    def test_recovery_reports_how_long_it_was_down(self) -> None:
        engine = AlertEngine(Thresholds(offline_ticks=1))
        engine.observe(state(cabinets=(8, 6)))
        engine.active()[0].since -= 125  # pretend it has been down two minutes
        events = engine.observe(state(cabinets=(8, 8)))
        assert "all 8 cabinets online" in events[0].message
        assert "2m" in events[0].message

    def test_history_is_recorded_for_trends(self) -> None:
        engine = AlertEngine()
        for online in [8, 8, 7, 7]:
            engine.observe(state(cabinets=(8, online)))
        series = engine.histories["10.0.0.1"].series["cabinets_online"]
        assert [s.value for s in series.samples] == [8, 8, 7, 7]
        assert series.summary()["trend"] == -1


class TestEngineBookkeeping:
    def test_worst_severity_ignores_acknowledged(self) -> None:
        engine = AlertEngine(Thresholds(offline_ticks=1))
        engine.observe(state(address="a", reachability="unreachable"))
        assert engine.worst_severity == Severity.CRITICAL

        engine.acknowledge(engine.active()[0].key)
        assert engine.worst_severity is None
        # But the alert is still there: silenced, not dismissed.
        assert len(engine.active()) == 1

    def test_alerts_are_sorted_worst_first(self) -> None:
        engine = AlertEngine(Thresholds(offline_ticks=1, temperature_warning=45))
        engine.observe(state(address="a", temperature=46.0))
        engine.observe(state(address="b", reachability="unreachable"))
        assert [a.severity for a in engine.active()] == [
            Severity.CRITICAL,
            Severity.WARNING,
        ]

    def test_forgetting_a_device_drops_its_alerts(self) -> None:
        engine = AlertEngine(Thresholds(offline_ticks=1))
        engine.observe(state(address="a", reachability="unreachable"))
        engine.observe(state(address="b", reachability="unreachable"))
        engine.forget("a")
        assert [alert.address for alert in engine.active()] == ["b"]
        assert "a" not in engine.histories

    def test_acknowledging_an_unknown_alert_is_false(self) -> None:
        assert not AlertEngine().acknowledge("nope")

    def test_events_are_bounded(self) -> None:
        engine = AlertEngine(Thresholds(offline_ticks=1), max_events=3)
        for index in range(10):
            engine.observe(state(address=f"d{index}", reachability="unreachable"))
        assert len(engine.events) == 3

    def test_serialises(self) -> None:
        engine = AlertEngine(Thresholds(offline_ticks=1))
        engine.observe(state(temperature=70.0, cabinets=(8, 6)))
        payload = json.loads(json.dumps(engine.to_dict()))
        assert payload["worst_severity"] == Severity.CRITICAL
        assert len(payload["alerts"]) == 2
        assert payload["thresholds"]["temperature_warning"] == 45.0
        assert "temperature_c" in payload["metrics"]["10.0.0.1"]


class TestThresholdValidation:
    def test_clear_must_be_below_warning(self) -> None:
        """Equal thresholds are exactly the flapping bug hysteresis prevents."""
        with pytest.raises(ValueError, match="flap"):
            Thresholds(temperature_warning=45, temperature_clear=45).validate()

    def test_warning_must_be_below_critical(self) -> None:
        with pytest.raises(ValueError, match="critical"):
            Thresholds(temperature_warning=70, temperature_critical=60).validate()

    def test_dwell_must_be_at_least_one(self) -> None:
        with pytest.raises(ValueError):
            Thresholds(offline_ticks=0).validate()

    def test_defaults_are_valid(self) -> None:
        Thresholds().validate()

    def test_round_trips(self) -> None:
        thresholds = Thresholds(temperature_warning=50, offline_ticks=4)
        assert Thresholds.from_dict(thresholds.to_dict()) == thresholds
