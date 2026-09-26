"""`novasun verify` writes to a processor, so its safety rails are tested first."""

from __future__ import annotations

import pytest

from novasun.coexsim import SimulatedCoexController
from novasun.verify import CONFIRMATION, format_report, run


@pytest.fixture()
def coex():
    server = SimulatedCoexController("127.0.0.1", 0)
    server.serve_in_thread()
    yield server
    server.shutdown()
    server.server_close()


def scripted(answers: list[str]):
    """An `ask` that replays canned operator answers and records the prompts."""
    prompts: list[str] = []
    queue = list(answers)

    def ask(prompt: str) -> str:
        prompts.append(prompt)
        return queue.pop(0) if queue else ""

    ask.prompts = prompts  # type: ignore[attr-defined]
    return ask


def test_refuses_without_the_exact_confirmation(coex) -> None:
    host, port = coex.address
    said: list[str] = []
    result = run(host, port=port, ask=scripted(["not live"]), say=said.append)
    assert result.aborted
    assert not result.observations
    assert coex.state.display_mode == 0
    assert any("nothing was sent" in line for line in said)


def test_walks_display_modes_and_restores_each(coex) -> None:
    host, port = coex.address
    # Operator sees black for 1, a freeze for 2, confirms each restore, sees the
    # brightness change, confirms restore, reports no VMP disruption.
    answers = [CONFIRMATION, "b", "y", "f", "y", "y", "y", "none"]
    result = run(host, port=port, ask=scripted(answers), say=lambda _: None)

    assert result.aborted is None
    verdicts = {o.claim: o.verdict for o in result.observations}
    assert verdicts["COEX displaymode 1 = blackout"] == "CONFIRMED"
    assert verdicts["COEX displaymode 2 = freeze"] == "CONFIRMED"
    assert all(o.restored for o in result.observations)
    # Everything put back: display normal, brightness where it started.
    assert coex.state.display_mode == 0
    assert coex.state.screens[0]["brightness"] == 1.0
    assert result.vmp_disruption == "none"
    assert "CONFIRMED" in format_report(result)
    assert result.to_dict()["provenance"].startswith("OBSERVED")


def test_records_a_contradiction_rather_than_believing_the_manual(coex) -> None:
    host, port = coex.address
    # The wall freezes on 1 and blacks out on 2: the swapped mapping.
    answers = [CONFIRMATION, "f", "y", "b", "y", "y", "y", ""]
    result = run(host, port=port, ask=scripted(answers), say=lambda _: None)
    verdicts = {o.claim: o.verdict for o in result.observations}
    assert verdicts["COEX displaymode 1 = blackout"] == "CONTRADICTED"
    assert verdicts["COEX displaymode 2 = freeze"] == "CONTRADICTED"
    assert coex.state.display_mode == 0


def test_restores_normal_when_the_processor_goes_away(coex, monkeypatch) -> None:
    host, port = coex.address
    from novasun import coex as coex_module

    calls: list[int] = []
    original = coex_module.CoexClient.set_display_mode

    def flaky(self, mode):
        calls.append(mode)
        if mode == 2:
            raise coex_module.CoexError(5, "Busying")
        return original(self, mode)

    monkeypatch.setattr(coex_module.CoexClient, "set_display_mode", flaky)
    answers = [CONFIRMATION, "b", "y", "y"]
    result = run(host, port=port, ask=scripted(answers), say=lambda _: None)
    assert result.aborted and "displaymode 2 rejected" in result.aborted
    # The last thing sent was the restore to normal.
    assert calls[-1] == 0
    assert coex.state.display_mode == 0
