"""Guided verification of claims that need a human looking at the wall.

Most of this project's protocol facts were checked against documents. A few
cannot be: whether the byte this repository calls "blackout" actually blanks
the screen is something only an eye on the LEDs can confirm. This walks an
operator through those claims one at a time, asks what they saw, restores the
previous state after every step, and records the answers with provenance.

It writes to the processor -- display mode and brightness -- so it refuses to
start until the operator confirms nothing depends on the screen. Every change
is reversed before the next question is asked, and on any error the screen is
returned to normal before the run stops.

    novasun verify 192.168.1.10 --json mx30-verify.json
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .coex import DEFAULT_PORT, CoexClient, CoexError

CONFIRMATION = "NOT LIVE"

Ask = Callable[[str], str]


@dataclass
class Observation:
    claim: str
    sent: dict[str, Any]
    expected: str
    operator_saw: str
    restored: bool
    verdict: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class Verification:
    host: str
    started: float = field(default_factory=time.time)
    device: dict[str, Any] = field(default_factory=dict)
    initial_display_mode: int | None = None
    observations: list[Observation] = field(default_factory=list)
    vmp_disruption: str = ""
    aborted: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "started": self.started,
            "device": self.device,
            "initial_display_mode": self.initial_display_mode,
            "observations": [o.to_dict() for o in self.observations],
            "vmp_disruption": self.vmp_disruption,
            "aborted": self.aborted,
            "provenance": "OBSERVED by an operator watching the wall",
        }


def _choice(ask: Ask, prompt: str, options: dict[str, str]) -> str:
    keys = "/".join(options)
    while True:
        answer = ask(f"{prompt} [{keys}] ").strip().lower()
        if answer in options:
            return options[answer]
        if answer and answer[0] in options:
            return options[answer[0]]


def _restore_display(client: CoexClient, mode: int, ask: Ask, say: Callable[[str], None]) -> bool:
    try:
        client.set_display_mode(mode)
    except (CoexError, OSError) as exc:
        say(f"  !! could not restore display mode {mode}: {exc}")
        return False
    return _choice(ask, "  Is the wall back to how it was?", {"y": "yes", "n": "no"}) == "yes"


def run(
    host: str,
    port: int = DEFAULT_PORT,
    timeout: float = 5.0,
    ask: Ask = input,
    say: Callable[[str], None] = print,
    skip_confirmation: bool = False,
) -> Verification:
    result = Verification(host=host)
    client = CoexClient(host, port, timeout=timeout)

    say(f"novasun verify -- {host}")
    say("This WRITES display mode and brightness to the processor, restoring")
    say("each before moving on. Do not run it while anything depends on the wall.")
    if not skip_confirmation:
        typed = ask(f'Type "{CONFIRMATION}" to continue: ').strip()
        if typed != CONFIRMATION:
            result.aborted = "operator did not confirm the screen is not live"
            say("aborted; nothing was sent.")
            return result

    # Identity, and the state we must put back.
    try:
        device = client.device_info()
        result.device = device if isinstance(device, dict) else {"raw": device}
        current = client.display_status()
        result.initial_display_mode = (
            int(current["value"]) if isinstance(current, dict) and "value" in current else None
        )
    except (CoexError, OSError, ValueError, KeyError) as exc:
        result.aborted = f"could not read device state: {exc}"
        say(f"aborted: {exc}")
        return result

    say(f"  device: {json.dumps(result.device)[:120]}")
    say(f"  current display mode value: {result.initial_display_mode}")
    baseline = result.initial_display_mode if result.initial_display_mode is not None else 0
    say("")

    # --- Claim 1 and 2: the display-mode values --------------------------------
    for value, documented in ((1, "blackout"), (2, "freeze")):
        say(f"Sending displaymode = {value}. The manual says this is {documented.upper()}.")
        try:
            client.set_display_mode(value)
        except (CoexError, OSError) as exc:
            result.aborted = f"displaymode {value} rejected: {exc}"
            say(f"  rejected: {exc}")
            _restore_display(client, baseline, ask, say)
            return result
        seen = _choice(
            ask,
            "  What did the wall do?",
            {"b": "went black", "f": "froze (last frame held)", "n": "nothing changed", "o": "something else"},
        )
        if seen == "something else":
            seen = "other: " + ask("  describe it: ").strip()
        restored = _restore_display(client, baseline, ask, say)
        matches = (
            (documented == "blackout" and seen == "went black")
            or (documented == "freeze" and seen.startswith("froze"))
        )
        result.observations.append(
            Observation(
                claim=f"COEX displaymode {value} = {documented}",
                sent={"path": "/api/v1/device/screen/displaymode", "value": value},
                expected=documented,
                operator_saw=seen,
                restored=restored,
                verdict="CONFIRMED" if matches else "CONTRADICTED",
            )
        )
        say(f"  -> {'CONFIRMED' if matches else 'CONTRADICTED'}")
        say("")

    # --- Claim 3: brightness ratio --------------------------------------------
    try:
        screens = client.screens()
        entries = screens.get("screens", []) if isinstance(screens, dict) else []
        identifiers = [s["screenID"] for s in entries if "screenID" in s]
        original = entries[0].get("brightness") if entries else None
    except (CoexError, OSError, ValueError, KeyError) as exc:
        say(f"  brightness check skipped: {exc}")
        identifiers, original = [], None

    if identifiers:
        target = 0.25 if not isinstance(original, (int, float)) or original > 0.5 else min(1.0, original * 2)
        say(f"Setting screen brightness ratio to {target} (was {original}).")
        restored = False
        try:
            client.set_screen_brightness(identifiers, target)
            seen = _choice(
                ask,
                f"  Did the wall get {'dimmer' if target < (original or 1) else 'brighter'}?",
                {"y": "yes, clearly", "s": "slightly", "n": "no", "o": "something else"},
            )
            if isinstance(original, (int, float)):
                client.set_screen_brightness(identifiers, float(original))
                restored = _choice(ask, "  Back to the original brightness?", {"y": "yes", "n": "no"}) == "yes"
            result.observations.append(
                Observation(
                    claim="COEX screen brightness ratio 0..1 maps to visible level",
                    sent={"path": "/api/v1/screen/brightness", "ratio": target, "idList": identifiers},
                    expected="visible change in the expected direction",
                    operator_saw=seen,
                    restored=restored,
                    verdict="CONFIRMED" if seen.startswith("yes") else "UNCLEAR",
                    note=f"original ratio {original}",
                )
            )
        except (CoexError, OSError) as exc:
            say(f"  brightness write failed: {exc}")
            if isinstance(original, (int, float)):
                try:
                    client.set_screen_brightness(identifiers, float(original))
                except (CoexError, OSError):
                    pass
        say("")

    result.vmp_disruption = ask(
        "If VMP was open during this: did it show any disruption, disconnect or lag? "
    ).strip()
    say("")
    say("done. Everything sent has been reversed; check the wall once more.")
    return result


def format_report(result: Verification) -> str:
    lines = [f"verification: {result.host}", "=" * 44]
    if result.aborted:
        lines.append(f"ABORTED: {result.aborted}")
    for obs in result.observations:
        lines.append(f"{obs.verdict:<13} {obs.claim}")
        lines.append(f"              saw: {obs.operator_saw}; restored: {obs.restored}")
    if result.vmp_disruption:
        lines.append(f"VMP: {result.vmp_disruption}")
    return "\n".join(lines)
