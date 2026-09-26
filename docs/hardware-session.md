# Hardware session checklist

For whoever is sitting on the same LAN as a processor — a human, or a Claude
instance running locally. Order matters: read-only first, writes last, and only
once someone has said the wall is not live.

Two sessions have already happened — a NovaPro UHD Jr on the bench and an
MX40 Pro at a show (2026-09-11). Each step below says what those settled, so a
new session spends its time on what is still open, and names where the answer
must be written down. A fact that only lives in a terminal scrollback is lost;
the standing instruction in [`CLAUDE.md`](../CLAUDE.md) is that hardware
findings update [`read-only-monitoring.md`](read-only-monitoring.md) and the
provenance markers in the same change.

Every OBSERVED fact so far has the scope *one unit, one firmware*. A second
COEX model — an MX30, say — is worth a session even if it repeats every step,
because "the same on two models" is a different claim from "seen once".

## 0. Before anything

- `git pull` — `novasun verify` (step 4) is recent.
- Ask the operator: **is the wall live?** If yes, or unsure, stop after step 3.
- Note the model, firmware, IP, and whether VMP or NovaLCT is open. The
  operator's software holding a session is normal; do not close it.
- Make a directory for raw output and keep everything:
  `mkdir -p captures/<date>-<model>`.

## 1. Zero transmission — any time

```
python -m novasun listen --duration 120 --log captures/<dir>/discovery.log
```

Settled on the MX40 Pro: it **does not answer** `rqProMI:` at all, and VMP does
not probe on a timer, so a passive listener hears nothing. Settled on the UHD
Jr: the reply is 16 bytes, `rpProMI:App,0161`, unicast, and carries no model or
name. Both in [read-only-monitoring.md §1–2](read-only-monitoring.md).

Still open, and what this step answers on a new unit: does *this* model answer
the probe or stay silent like the MX40 Pro, and if it answers, is the tail the
same width? `listen` writes a session record even when it hears nothing —
silence is the finding, not a failed run. Paste the raw hex, if any, into §2.

## 2. Read-only bring-up — any time on COEX (MX/CX/KU)

```
python -m novasun identify <ip>
python -m novasun bringup <ip> --json captures/<dir>/bringup.json
```

`identify` no longer opens a register-bus session to a COEX controller.
`bringup` stops at HTTP GETs when the controller answers on 8001, and does not
touch TCP 5200 unless told to with `--register-bus` (step 4).

Settled on the MX40 Pro: the real JSON shapes of six endpoints (every field the
manual led this project to guess was wrong; the simulator now emits what was
seen); that `/api/v1/device`, `/api/v1/device/audio` and the GET of
`/api/v1/device/screen/displaymode` are **HTTP 404**; that identity comes from
`monitor/info`'s `name` as `<model>_<digits>`; that SNMP was off.

Still open, with the file to update in brackets:

- whether the 404 list is the same on this model and firmware
  (`coexsim.CoexState.missing_endpoints`, `target-hardware.md`)
- the port count as the hardware reports it — count
  `controllerPortMonitorInfos[]` in `monitor/info` — against the spec-sheet
  figure in `devices.COEX_MODELS` (`devices.PROVENANCE`; an MX30 should say 2)
- whether SNMP is on by default here (`snmp.PROVENANCE`; the OID map is still
  unexercised because the only unit seen had it off — if it is on, one
  `snmpget` of `sysDescr` and the controller-temperature OID settles that)
- what `hw/mode` reports (`3` on the MX40 Pro; meaning UNKNOWN)
- whether TCP 5200 is open at all on a COEX box — **UNKNOWN**; it is a
  write-class question, answered in step 4

If VMP is open, also run

```
python -m novasun watch <ip> --interval 1
```

for ten minutes **while the operator does something visible in VMP** — a preset
recall, a brightness ramp. The controller side of §3 is settled (1,791 GETs at
1 Hz, no error, no `Busying`, no latency drift); the operator side is not,
because VMP was idle at the time. Ask whether VMP stuttered, disconnected or
refreshed. That closes [§3](read-only-monitoring.md).

## 3. Optional, still read-only

Learn which GET fields reflect which VMP controls, without sending a single
write yourself: snapshot, have the operator change one thing in VMP, snapshot
again, diff. `coex diff` aligns cabinets by identity, because `monitor/info`
reorders them on every call.

```
python -m novasun coex snapshot <ip> -o captures/<dir>/before.json
# operator changes brightness / input / preset in VMP
python -m novasun coex snapshot <ip> -o captures/<dir>/after.json
python -m novasun coex diff captures/<dir>/before.json captures/<dir>/after.json
```

## 4. Writes — show finished, operator agrees, someone watching the wall

```
python -m novasun verify <ip> --json captures/<dir>/verify.json
```

It refuses to start until `NOT LIVE` is typed. Because the display mode cannot
be read on the firmware seen so far, it then asks the operator to confirm the
wall is showing normally, and normal is what it restores. It sends display mode
1, asks what the wall did, restores; sends 2, asks, restores; halves the
brightness through the screen endpoint, asks, and puts every cabinet back to
the exact fraction it had, reading them back to prove it. On any unexpected
error the last thing sent is a restore to normal.

Settles the claim the application layer depends on and has never seen: that
the COEX HTTP display mode is **1 = blackout, 2 = freeze** (the VX4S register is
the other way round). Three outcomes are all results:

- `CONFIRMED` — the manual was right; mark it OBSERVED in
  `coex.py`, `coexsim.py` and `protocol-register-bus.md`.
- `CONTRADICTED` — `coex.py`, `coexsim.py`, `processor.py` and the "swapped"
  note in `CLAUDE.md` all change together.
- `ABSENT` — the PUT answered 404 or `NotSupport`: **the write does not exist
  on this firmware**, which is currently UNKNOWN. Record it in
  `missing_endpoints` and the app layer loses a control on COEX.

Only after `verify` is it reasonable to try the register bus on a COEX box:

```
python -m novasun bringup <ip> --register-bus --json captures/<dir>/bringup-bus.json
```

which answers whether 5200 is open, whether `0x00000002` returns anything, and
what receiving-card model IDs the chain reports (`client.RECEIVING_CARD_NAMES`
is nearly empty). Read the four register-bus traps in
[read-only-monitoring.md §5](read-only-monitoring.md) first: a read that
succeeds is not evidence the address exists.

## 5. Writing it down

One commit per session, containing:

- the raw files from `captures/<dir>/`, and for a new COEX model a
  `tests/fixtures/<model>_like_api.json` pinned to the Python fixtures the way
  `test_fixtures.py` pins the MX40 Pro's, so other consumers get the shapes
- `docs/sources.md`: a row for the unit itself — model, how it named itself,
  MAC, exactly what was sent to it, date — as the MX40 Pro row does
- `docs/read-only-monitoring.md`: each **UNKNOWN** or **REASONED** that was
  settled becomes **OBSERVED**, with model, firmware and date beside it, and
  "one unit" widened to "two" where a second model agreed
- the provenance markers: `devices.PROVENANCE`, `registers.OBSERVED` and
  `registers.NOT_IMPLEMENTED`, `snmp.PROVENANCE`
- the simulators, so the next offline session tests against what was seen
  rather than what the manual said

Anything the hardware contradicted gets fixed in the same commit, and the old
claim is left in the docs with the correction beside it, not deleted. The
record of having been wrong is part of what makes the rest believable.
