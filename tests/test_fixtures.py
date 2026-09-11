"""The machine-readable fixture is the Python fixture, byte for byte.

tests/fixtures/mx40_like_api.json is the COEX HTTP API as OBSERVED on an MX40
Pro, for consumers outside this repository -- crewbox's video module reads the
same controllers in TypeScript and has never met one. A fixture that drifts
from the one these tests run against would hand them a shape nothing here
verifies, so this pins the two together.
"""

from __future__ import annotations

import json
from pathlib import Path

from conftest import (
    MX40_LIKE_CABINETS,
    MX40_LIKE_INPUTS,
    MX40_LIKE_MONITOR_INFO,
    MX40_LIKE_SCREENS,
)

FIXTURE = Path(__file__).parent / "fixtures" / "mx40_like_api.json"


def test_json_fixture_matches_the_python_fixtures() -> None:
    api = json.loads(FIXTURE.read_text())
    assert api["/api/v1/device/cabinet"] == MX40_LIKE_CABINETS
    assert api["/api/v1/device/input/sources"] == MX40_LIKE_INPUTS
    assert api["/api/v1/device/monitor/info"] == MX40_LIKE_MONITOR_INFO
    assert api["/api/v1/screen"] == MX40_LIKE_SCREENS


def test_the_absent_endpoints_are_marked_as_observed() -> None:
    api = json.loads(FIXTURE.read_text())
    assert api["/api/v1/device"] == {"__http_status__": 404}
    assert api["/api/v1/device/audio"] == {"__http_status__": 404}
    assert api["/api/v1/device/snmpstate"] == {"state": False}


def test_nothing_from_the_show_is_in_the_fixture() -> None:
    text = FIXTURE.read_text()
    # The real unit's name suffix and a real cabinet id; neither may appear.
    assert "_002198" not in text
    assert "11151225588285440" not in text
