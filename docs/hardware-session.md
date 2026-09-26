# Hardware session checklist

For whoever is sitting on the same LAN as a processor — a human, or a Claude
instance running locally. The remote sessions that built this repository never
had that; everything below is what they would have run first. Order matters:
read-only first, writes last, and only once someone has said the wall is not
live.

Each step names what it settles and where the answer must be written down.
A fact that only lives in a terminal scrollback is lost; the standing
instruction in [`CLAUDE.md`](../CLAUDE.md) is that hardware findings update
[`read-only-monitoring.md`](read-only-monitoring.md) and the provenance markers
in the same change.

## 0. Before anything

- `git pull` — `novasun verify` (step 4) is recent.
- Ask the operator: **is the wall live?** If yes, or unsure, stop after step 3.
- Note the model, firmware, IP, and whether VMP or NovaLCT is open. The
  operator's software holding a session is normal; do not close it.
- Make a directory for raw output and keep everything: `mkdir -p captures/<date>-<model>`.

## 1. Zero transmission — any time

```
python -m novasun listen --duration 120 --log captures/<dir>/discovery.log
```

Settles:

- whether VMP/NovaLCT probes and processor replies are visible on this
  segment from a plain port (they may not be; a switch does not mirror
  unicast)
- the raw bytes of a real `rpProMI:` reply, which
  [read-only-monitoring.md §2](read-only-monitoring.md) currently marks
  **UNKNOWN**. Whatever is captured, paste the hex into that section as
  observed; do not interpret fields that were not seen to change.

## 2. Read-only bring-up — any time on COEX (MX/CX/KU)

```
python -m novasun identify <ip>
python -m novasun bringup <ip> --json captures/<dir>/bringup.json
```

`bringup` stops at HTTP GETs when the controller answers on 8001. It does not
open TCP 5200 unless told to with `--register-bus`, which is a write-class
action (it takes a control session) and belongs in step 4.

Settles, with the file to update in brackets:

- the exact JSON field names and the model string in `/api/v1/device`
  (`coex.py` docstrings, `coexsim.py` fixtures — both reconstructed from the
  manual and marked provisional)
- output port count as the hardware reports it (`devices.COEX_MODELS`,
  `devices.PROVENANCE`)
- whether SNMP is enabled by default (`snmp.PROVENANCE`; read-only doc §4)
- cabinet, input and preset lists and their field names
- whether TCP 5200 is open at all on a COEX box (`identify` reports both
  paths; read-only doc §1)

If VMP is open, also run

```
python -m novasun watch <ip> --interval 5
```

for a few minutes and ask the operator whether VMP showed any disconnect, lag
or refresh. That answers read-only doc §3, which is currently **REASONED**.

## 3. Optional, still read-only

Learn which GET fields reflect which VMP controls, without sending a single
write yourself: snapshot, have the operator change one thing in VMP, snapshot
again, diff.

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

It refuses to start until `NOT LIVE` is typed. It then sends display mode 1,
asks what the wall did, restores; sends 2, asks, restores; nudges brightness,
asks, restores. Every step is reversed before the next question, and on any
error the last thing sent is a restore to normal.

Settles the one claim the application layer depends on and has never seen:
that the COEX HTTP API's display mode is **1 = blackout, 2 = freeze** (the
VX4S register is the other way round). A `CONTRADICTED` verdict means
`coex.py`, `coexsim.py`, `processor.py` and the "swapped" note in
`CLAUDE.md` all change together — that is a correct outcome, not a failed run.

Only after `verify` passes is it reasonable to try the register-bus path on a
COEX box:

```
python -m novasun bringup <ip> --register-bus --json captures/<dir>/bringup-bus.json
```

which answers whether `0x00000002` returns anything and what receiving-card
model IDs the chain reports (`client.RECEIVING_CARD_NAMES` is nearly empty).

## 5. Writing it down

One commit per session, containing:

- the raw files from `captures/<dir>/` (they make every claim checkable)
- `docs/read-only-monitoring.md`: each **UNKNOWN** or **REASONED** that was
  settled becomes **OBSERVED**, with the model, firmware and date beside it
- `docs/sources.md`: a line for the session itself — model, firmware, date,
  who watched the wall
- the provenance markers in `devices.py`, `registers.py`, `snmp.py`
- the simulators, so the next offline session tests against what was seen
  rather than what the manual said

Anything the hardware contradicted gets fixed in the same commit, and the old
claim is left in the docs struck through with the correction, not deleted.
The record of having been wrong is part of what makes the rest believable.
