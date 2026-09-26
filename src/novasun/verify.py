"""Guided verification of claims that need a human looking at the wall.

Most of this project's protocol facts were checked against documents. A few
cannot be: whether the value this repository calls "blackout" actually blanks
the screen is something only an eye on the LEDs can confirm. This walks an
operator through those claims one at a time, asks what they saw, restores the
previous state after every step, and records the answers with provenance.

It is written for what an MX40 Pro was OBSERVED to expose (2026-09-11), not for
what the manual says:

- ``GET /api/v1/device`` and ``GET /api/v1/device/screen/displaymode`` answer
  HTTP 404 on that firmware, so identity comes from ``monitor/info`` and the
  starting display mode cannot be read -- the operator confirms the wall is
  showing normally before anything is sent, and normal (0) is what is restored.
- Whether the ``PUT`` of displaymode exists at all is UNKNOWN. A 404 or a
  ``NotSupport`` envelope on a write is recorded as a finding (``ABSENT``) and
  the run continues; it is not a failure.
- Brightness lives on cabinets as a 0..1 fraction. The write goes through the
  documented screen endpoint; the restore puts every cabinet back to the exact
  value it had, and reads them back to prove it.

It writes to the processor, so it refuses to start until the operator confirms
nothing depends on the screen. On any unexpected error the display is returned
to normal before the run stops.

    novasun verify 192.168.1.10 --json mx30-verify.json
"""

from __future__ import annotations

import json
import time
import urllib.error
from dataclasses import dataclass, field
from typing import Any, Callable

from .coex import DEFAULT_PORT, CoexClient, CoexError

CONFIRMATION = "NOT LIVE"
NOT_SUPPORTED = 6

Ask = Callable[[str], str]
Say = Callable[[str], None]


@dataclass
class Observation:
    claim: str
    sent: dict[str, Any]
    expected: str
    operator_saw: str
    restored: bool
    verdict: str
    """CONFIRMED, CONTRADICTED, UNCLEAR, or ABSENT (the endpoint does not exist)."""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class Verification:
    host: str
    started: float = field(default_factory=time.time)
    identity: str = ""
    """The controller's own name from monitor/info -- the only identity it offers."""
    endpoints: dict[str, str] = field(default_factory=dict)
    """Documented endpoints tried on the way: 'present' or 'absent (HTTP 404)'."""
    baseline_display_mode: int | None = None
    """Read from the device when its GET exists; None means assumed normal."""
    observations: list[Observation] = field(default_factory=list)
    vmp_disruption: str = ""
    aborted: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "started": self.started,
            "identity": self.identity,
            "endpoints": self.endpoints,
            "baseline_display_mode": self.baseline_display_mode,
            "observations": [o.to_dict() for o in self.observations],
            "vmp_disruption": self.vmp_disruption,
            "aborted": self.aborted,
            "provenance": "OBSERVED by an operator watching the wall",
        }


class Absent(Exception):
    """The endpoint is not on this firmware: HTTP 404 or a NotSupport envelope."""


def _call(fn: Callable[[], Any]) -> Any:
    """Run one request, turning 'this endpoint does not exist' into `Absent`."""
    try:
        return fn()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise Absent(f"HTTP {exc.code}") from exc
        raise
    except CoexError as exc:
        if exc.code == NOT_SUPPORTED:
            raise Absent(str(exc)) from exc
        raise


def _choice(ask: Ask, prompt: str, options: dict[str, str]) -> str:
    keys = "/".join(options)
    while True:
        answer = ask(f"{prompt} [{keys}] ").strip().lower()
        if answer in options:
            return options[answer]
        if answer and answer[0] in options:
            return options[answer[0]]


def _yes(ask: Ask, prompt: str) -> bool:
    return _choice(ask, prompt, {"y": "yes", "n": "no"}) == "yes"


def _restore_display(client: CoexClient, mode: int, ask: Ask, say: Say) -> bool:
    try:
        _call(lambda: client.set_display_mode(mode))
    except (Absent, CoexError, OSError) as exc:
        say(f"  !! could not restore display mode {mode}: {exc}")
        return False
    return _yes(ask, "  Is the wall back to how it was?")


def _cabinet_brightness(client: CoexClient) -> dict[Any, float]:
    """{cabinet id: brightness fraction} as the controller reports it now."""
    cabinets = _call(client.cabinets)
    if isinstance(cabinets, dict):  # the manual's wrapped shape, never observed
        cabinets = cabinets.get("cabinets", [])
    return {
        c["id"]: float(c["brightness"])
        for c in cabinets
        if isinstance(c, dict) and "id" in c and isinstance(c.get("brightness"), (int, float))
    }


def _restore_brightness(
    client: CoexClient, screen_ids: list[str], original: dict[Any, float]
) -> tuple[bool, str]:
    """Put every cabinet back to the value it had, and read back to prove it."""
    values = set(original.values())
    if len(values) == 1:
        client.set_screen_brightness(screen_ids, values.pop())
    else:
        # The wall was not uniform; a screen-level write would flatten it.
        for value in values:
            ids = [cid for cid, v in original.items() if v == value]
            client.set_cabinet_brightness(ids, value)
    now = _cabinet_brightness(client)
    drift = {cid: (original[cid], now.get(cid)) for cid in original
             if now.get(cid) is None or abs(now[cid] - original[cid]) > 1e-6}
    if drift:
        return False, f"{len(drift)} cabinet(s) did not read back their original value: " + \
            ", ".join(f"{cid}: {was} -> {is_}" for cid, (was, is_) in list(drift.items())[:4])
    return True, f"{len(original)} cabinet(s) read back at their original value"


def run(
    host: str,
    port: int = DEFAULT_PORT,
    timeout: float = 5.0,
    ask: Ask = input,
    say: Say = print,
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

    # --- identity, and which documented reads this firmware has ------------
    try:
        info = _call(client.monitoring)
        result.identity = str(info.get("name", "")) if isinstance(info, dict) else ""
    except (Absent, CoexError, OSError, ValueError) as exc:
        result.aborted = f"could not read monitor/info: {exc}"
        say(f"aborted: {exc}")
        return result
    say(f"  controller: {result.identity or '(no name in monitor/info)'}")

    try:
        _call(client.device_info)
        result.endpoints["GET /api/v1/device"] = "present"
    except Absent as exc:
        result.endpoints["GET /api/v1/device"] = f"absent ({exc})"
    except (CoexError, OSError, ValueError) as exc:
        result.endpoints["GET /api/v1/device"] = f"error ({exc})"

    try:
        status = _call(client.display_status)
        result.endpoints["GET displaymode"] = "present"
        if isinstance(status, dict) and "value" in status:
            result.baseline_display_mode = int(status["value"])
    except Absent as exc:
        result.endpoints["GET displaymode"] = f"absent ({exc})"
    except (CoexError, OSError, ValueError) as exc:
        result.endpoints["GET displaymode"] = f"error ({exc})"

    if result.baseline_display_mode is None:
        say("  display mode is not readable on this firmware; normal (0) will be")
        say("  restored after each step, so the wall must be normal now.")
        if not _yes(ask, "  Is the wall showing content normally (not black, not frozen)?"):
            result.aborted = "wall is not in a normal state to begin with; nothing was sent"
            say("aborted; nothing was sent.")
            return result
        baseline = 0
    else:
        say(f"  display mode reads {result.baseline_display_mode}")
        baseline = result.baseline_display_mode
    say("")

    # --- claims 1 and 2: the display-mode values ----------------------------
    for value, documented in ((1, "blackout"), (2, "freeze")):
        say(f"Sending displaymode = {value}. The manual says this is {documented.upper()}.")
        sent = {"method": "PUT", "path": "/api/v1/device/screen/displaymode", "value": value}
        try:
            _call(lambda: client.set_display_mode(value))
        except Absent as exc:
            result.endpoints["PUT displaymode"] = f"absent ({exc})"
            result.observations.append(Observation(
                claim=f"COEX displaymode {value} = {documented}", sent=sent,
                expected=documented, operator_saw="(nothing sent: endpoint absent)",
                restored=True, verdict="ABSENT",
                note="the write itself does not exist on this firmware",
            ))
            say(f"  -> ABSENT: {exc}; nothing changed")
            say("")
            continue
        except (CoexError, OSError) as exc:
            result.aborted = f"displaymode {value} failed: {exc}"
            say(f"  failed: {exc}")
            _restore_display(client, baseline, ask, say)
            return result
        result.endpoints["PUT displaymode"] = "present"
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
        result.observations.append(Observation(
            claim=f"COEX displaymode {value} = {documented}", sent=sent,
            expected=documented, operator_saw=seen, restored=restored,
            verdict="CONFIRMED" if matches else "CONTRADICTED",
        ))
        say(f"  -> {'CONFIRMED' if matches else 'CONTRADICTED'}")
        say("")

    # --- claim 3: the brightness ratio ---------------------------------------
    try:
        screens = _call(client.screens)
        entries = screens.get("screens", []) if isinstance(screens, dict) else []
        screen_ids = [s["screenID"] for s in entries if isinstance(s, dict) and "screenID" in s]
        original = _cabinet_brightness(client)
    except (Absent, CoexError, OSError, ValueError, KeyError) as exc:
        say(f"  brightness check skipped: could not read screens/cabinets: {exc}")
        screen_ids, original = [], {}

    if screen_ids and original:
        typical = max(original.values())
        target = round(typical / 2, 3) if typical > 0.5 else round(min(1.0, typical * 2), 3)
        direction = "dimmer" if target < typical else "brighter"
        say(f"Setting screen brightness ratio to {target} (cabinets are at "
            f"{sorted(set(original.values()))}).")
        sent = {"method": "PUT", "path": "/api/v1/screen/brightness",
                "idList": screen_ids, "ratio": target}
        try:
            _call(lambda: client.set_screen_brightness(screen_ids, target))
        except Absent as exc:
            result.endpoints["PUT screen/brightness"] = f"absent ({exc})"
            result.observations.append(Observation(
                claim="COEX screen brightness ratio 0..1 maps to visible level", sent=sent,
                expected=f"wall gets {direction}", operator_saw="(nothing sent: endpoint absent)",
                restored=True, verdict="ABSENT",
            ))
            say(f"  -> ABSENT: {exc}; nothing changed")
        except (CoexError, OSError) as exc:
            say(f"  brightness write failed: {exc}")
        else:
            result.endpoints["PUT screen/brightness"] = "present"
            seen = _choice(
                ask, f"  Did the wall get {direction}?",
                {"y": "yes, clearly", "s": "slightly", "n": "no", "o": "something else"},
            )
            try:
                read_back, note = _restore_brightness(client, screen_ids, original)
            except (Absent, CoexError, OSError, ValueError) as exc:
                read_back, note = False, f"restore failed: {exc}"
            say(f"  {note}")
            confirmed = _yes(ask, "  Back to the original brightness?")
            result.observations.append(Observation(
                claim="COEX screen brightness ratio 0..1 maps to visible level", sent=sent,
                expected=f"wall gets {direction}", operator_saw=seen,
                restored=read_back and confirmed,
                verdict="CONFIRMED" if seen.startswith("yes") else "UNCLEAR",
                note=note,
            ))
            say(f"  -> {'CONFIRMED' if seen.startswith('yes') else 'UNCLEAR'}")
        say("")

    result.vmp_disruption = ask(
        "If VMP was open during this: did it show any disruption, disconnect or lag? "
    ).strip()
    say("")
    say("done. Everything sent has been reversed; check the wall once more.")
    return result


def format_report(result: Verification) -> str:
    lines = [f"verification: {result.host}  {result.identity}".rstrip(), "=" * 44]
    if result.aborted:
        lines.append(f"ABORTED: {result.aborted}")
    for path, state in result.endpoints.items():
        lines.append(f"{state:<13} {path}")
    for obs in result.observations:
        lines.append(f"{obs.verdict:<13} {obs.claim}")
        lines.append(f"              saw: {obs.operator_saw}; restored: {obs.restored}")
        if obs.note:
            lines.append(f"              {obs.note}")
    if result.vmp_disruption:
        lines.append(f"VMP: {result.vmp_disruption}")
    return "\n".join(lines)
