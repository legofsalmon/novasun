"""`novasun verify` writes to a processor, so its safety rails are tested first.

The simulator withholds the same endpoints a real MX40 Pro does, so these runs
exercise the path the hardware forces: identity from monitor/info, no readable
display mode, brightness restored cabinet by cabinet and read back.
"""

from __future__ import annotations

import urllib.error

import pytest

from novasun import coex as coex_module
from novasun.coexsim import SimulatedCoexController
from novasun.verify import CONFIRMATION, format_report, run

# Operator answers, in the order the prompts arrive on a firmware without a
# readable display mode: confirmation, "wall is normal", then per display
# mode what was seen and whether it came back, then the brightness pair, then
# the VMP question.
NORMAL = [CONFIRMATION, "y"]
DISPLAY_AS_DOCUMENTED = ["b", "y", "f", "y"]
DISPLAY_SWAPPED = ["f", "y", "b", "y"]
BRIGHTNESS_SEEN = ["y", "y"]


@pytest.fixture()
def coex():
    server = SimulatedCoexController("127.0.0.1", 0)
    server.serve_in_thread()
    yield server
    server.shutdown()
    server.server_close()


def scripted(answers: list[str]):
    """An `ask` that replays canned operator answers; running out is a failure."""
    prompts: list[str] = []
    queue = list(answers)

    def ask(prompt: str) -> str:
        prompts.append(prompt)
        assert queue, f"verify asked more than the script answers: {prompt!r}"
        return queue.pop(0)

    ask.prompts = prompts  # type: ignore[attr-defined]
    return ask


def cabinet_brightness(coex) -> dict[int, float]:
    return {c["id"]: c["brightness"] for c in coex.state.cabinets}


def test_refuses_without_the_exact_confirmation(coex) -> None:
    host, port = coex.address
    said: list[str] = []
    result = run(host, port=port, ask=scripted(["not live"]), say=said.append)
    assert result.aborted
    assert not result.observations and not result.endpoints
    assert coex.state.display_mode == 0
    assert any("nothing was sent" in line for line in said)


def test_refuses_when_the_wall_is_not_normal_to_begin_with(coex) -> None:
    """With no readable display mode there is nothing to restore *to*."""
    host, port = coex.address
    result = run(host, port=port, ask=scripted([CONFIRMATION, "n"]), say=lambda _: None)
    assert result.aborted and "nothing was sent" in result.aborted
    assert not result.observations
    assert coex.state.requests == [] or all(m == "GET" for m, _, _ in coex.state.requests)


def test_walks_display_modes_and_restores_each(coex) -> None:
    host, port = coex.address
    before = cabinet_brightness(coex)
    answers = NORMAL + DISPLAY_AS_DOCUMENTED + BRIGHTNESS_SEEN + ["none"]
    result = run(host, port=port, ask=scripted(answers), say=lambda _: None)

    assert result.aborted is None
    assert result.identity.startswith("MX40 Pro")
    # The firmware's absences are recorded as facts, and the baseline assumed.
    assert result.endpoints["GET /api/v1/device"].startswith("absent")
    assert result.endpoints["GET displaymode"].startswith("absent")
    assert result.endpoints["PUT displaymode"] == "present"
    assert result.baseline_display_mode is None

    verdicts = {o.claim: o.verdict for o in result.observations}
    assert verdicts["COEX displaymode 1 = blackout"] == "CONFIRMED"
    assert verdicts["COEX displaymode 2 = freeze"] == "CONFIRMED"
    assert verdicts["COEX screen brightness ratio 0..1 maps to visible level"] == "CONFIRMED"
    assert all(o.restored for o in result.observations)
    # Everything put back, and proven by read-back, not by the operator's word.
    assert coex.state.display_mode == 0
    assert cabinet_brightness(coex) == before
    assert "read back at their original value" in result.observations[-1].note
    assert result.vmp_disruption == "none"
    assert "CONFIRMED" in format_report(result)
    assert result.to_dict()["provenance"].startswith("OBSERVED")


def test_records_a_contradiction_rather_than_believing_the_manual(coex) -> None:
    host, port = coex.address
    answers = NORMAL + DISPLAY_SWAPPED + BRIGHTNESS_SEEN + [""]
    result = run(host, port=port, ask=scripted(answers), say=lambda _: None)
    verdicts = {o.claim: o.verdict for o in result.observations}
    assert verdicts["COEX displaymode 1 = blackout"] == "CONTRADICTED"
    assert verdicts["COEX displaymode 2 = freeze"] == "CONTRADICTED"
    assert coex.state.display_mode == 0


def test_uses_the_device_baseline_when_display_mode_is_readable(coex) -> None:
    """A firmware that does serve the GET is asked, not the operator."""
    host, port = coex.address
    coex.state.missing_endpoints.discard("/api/v1/device/screen/displaymode")
    answers = [CONFIRMATION] + DISPLAY_AS_DOCUMENTED + BRIGHTNESS_SEEN + [""]
    result = run(host, port=port, ask=scripted(answers), say=lambda _: None)
    assert result.aborted is None
    assert result.endpoints["GET displaymode"] == "present"
    assert result.baseline_display_mode == 0


def test_an_absent_write_is_a_finding_not_a_failure(coex, monkeypatch) -> None:
    """Whether PUT displaymode exists on MX firmware is UNKNOWN; a 404 answers it."""
    host, port = coex.address

    def gone(self, mode):
        raise urllib.error.HTTPError(self.base_url, 404, "Not Found", None, None)  # type: ignore[arg-type]

    monkeypatch.setattr(coex_module.CoexClient, "set_display_mode", gone)
    answers = NORMAL + BRIGHTNESS_SEEN + [""]
    result = run(host, port=port, ask=scripted(answers), say=lambda _: None)
    assert result.aborted is None
    assert result.endpoints["PUT displaymode"].startswith("absent (HTTP 404)")
    display = [o for o in result.observations if o.claim.startswith("COEX displaymode")]
    assert [o.verdict for o in display] == ["ABSENT", "ABSENT"]
    # The brightness claim was still exercised.
    assert result.endpoints["PUT screen/brightness"] == "present"


def test_not_support_envelope_counts_as_absent(coex, monkeypatch) -> None:
    host, port = coex.address

    def unsupported(self, ids, ratio):
        raise coex_module.CoexError(6, "NotSupport")

    monkeypatch.setattr(coex_module.CoexClient, "set_screen_brightness", unsupported)
    before = cabinet_brightness(coex)
    answers = NORMAL + DISPLAY_AS_DOCUMENTED + [""]
    result = run(host, port=port, ask=scripted(answers), say=lambda _: None)
    assert result.endpoints["PUT screen/brightness"].startswith("absent")
    assert result.observations[-1].verdict == "ABSENT"
    assert cabinet_brightness(coex) == before


def test_restores_normal_when_the_processor_goes_away(coex, monkeypatch) -> None:
    host, port = coex.address
    calls: list[int] = []
    original = coex_module.CoexClient.set_display_mode

    def flaky(self, mode):
        calls.append(mode)
        if mode == 2:
            raise coex_module.CoexError(5, "Busying")
        return original(self, mode)

    monkeypatch.setattr(coex_module.CoexClient, "set_display_mode", flaky)
    answers = NORMAL + ["b", "y", "y"]
    result = run(host, port=port, ask=scripted(answers), say=lambda _: None)
    assert result.aborted and "displaymode 2 failed" in result.aborted
    # The last thing sent was the restore to normal.
    assert calls[-1] == 0
    assert coex.state.display_mode == 0


def test_a_non_uniform_wall_is_restored_cabinet_by_cabinet(coex) -> None:
    host, port = coex.address
    coex.state.cabinets[0]["brightness"] = 0.4
    coex.state.cabinets[3]["brightness"] = 0.7
    before = cabinet_brightness(coex)
    answers = NORMAL + DISPLAY_AS_DOCUMENTED + BRIGHTNESS_SEEN + [""]
    result = run(host, port=port, ask=scripted(answers), say=lambda _: None)
    assert result.observations[-1].restored
    assert cabinet_brightness(coex) == before
    # A screen-level restore would have flattened it; the per-cabinet path ran.
    puts = [path for method, path, _ in coex.state.requests if method == "PUT"]
    assert "/api/v1/device/cabinet/brightness" in puts
