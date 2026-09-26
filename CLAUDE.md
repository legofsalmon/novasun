# novasun — working notes for Claude

Reverse-engineered control and monitoring for NovaStar LED processors. Read
[`docs/investigation.md`](docs/investigation.md) before changing anything
substantive; it explains what the protocol is and why the code is shaped as it
is.

## Standing instruction: keep crewbox supplied

**crewbox** (a separate application at `/crewbox`, built by another agent)
consumes this repository **read-only**, to show a passive view of the LED
processors on a network. It cannot control anything and must not be given a
route to.

For all future work here:

- **Update the read-only docs whenever a finding affects them.** The contract
  lives in [`docs/read-only-monitoring.md`](docs/read-only-monitoring.md). Any
  new fact about what can be observed without transmitting, what is safe to
  poll, what SNMP or HTTP GET exposes, or what a passive listener can decode
  belongs there — not only in the module that discovered it.
- **Keep the confidence labels.** OFFICIAL / DERIVED / REASONED / UNKNOWN, as
  used throughout that document. A consumer needs to know which facts it can
  build on and which are guesses; crewbox holds the same standard in its
  `docs/DMX_MONITORING.md`.
- **Withdraw claims that turn out to be inference.** This has already happened
  once: the `rpProMI:` reply payload was described as "appears to carry model
  and name information" when that was inferred rather than observed. If a
  downstream consumer might be planning around a claim, correcting it is
  urgent, not cosmetic.
- **Anything new that hardware settles** — a captured discovery reply, an
  observed polling limit, a confirmed register — updates that document and the
  provenance markers in the same change.
- **Never widen crewbox's surface to writes.** `ReadOnlyCoexClient` rejects
  non-GET before a socket opens, and `passive.py` has no send path at all. Both
  properties are asserted by tests. Keep them.
- **Ship evidence, not PRs.** When a finding affects crewbox, record it here —
  the contract document, a fixture under `tests/fixtures/` with real structure
  and synthetic values, a harness if one helps — and push. crewbox's own agent
  applies it. Do not implement the crewbox side from this repository or open
  PRs against it: on 2026-09-11 that was tried in parallel with crewbox's agent
  working from the pushed fixture, and the agent's version landed first, better
  reasoned for that codebase, and the duplicate had to be thrown away. The
  handoff that worked was the one through the documents, which is what this
  standing instruction is for.

## Provenance discipline

Every protocol fact in this repository carries where it came from. This is the
core quality standard here, and the reason the work is usable by others.

- `registers.CONFIDENCE` — per-register: official document, decompiled source,
  or captured.
- `devices.PROVENANCE` — per-model: which model IDs, port counts, input
  registers and select codes are documented versus derived.
- `snmp.PROVENANCE` — the SNMP OID map's source and whether it has been
  exercised.
- [`docs/sources.md`](docs/sources.md) — every document and repository used.

**Verify hex before transcribing it.** Frames printed in vendor documents get
checksum-checked first; two published frames turned out to be wrong, and both
are pinned as tests in `tests/test_protocol.py` so the discrepancy stays on the
record.

**Refuse rather than guess.** Where a capability exists but its encoding is
unestablished — every NovaPro UHD Jr input, for instance — the code raises
`CapabilityUnknown` naming the capture workflow. It does not write a plausible
byte at a live screen. Preserve that behaviour when extending the device table.

## Layout

```
src/novasun/
  app/           application layer: screens, state, history/alerts, HTTP, UI
  protocol.py    frame codec: encode, decode, checksum, stream framing
  registers.py   register addresses with provenance
  devices.py     model IDs, per-model inputs/outputs, capabilities
  processor.py   one interface over both control paths
  client.py      register-bus Controller
  coex.py        COEX HTTP API client (port 8001)
  monitor.py     read-only polling; a client that cannot write
  passive.py     zero-transmission listener (no send path)
  snmp.py        COEX SNMP OID map (no client by design)
  capture.py     pcap/pcapng parsing and differential analysis
  proxy.py       MITM proxy for learning the address map from NovaLCT
  simulator.py   fake register-bus controller with real chain topology
  coexsim.py     fake COEX controller serving the HTTP API
```

## Working here

```bash
python -m pytest                                  # 170+ tests, no hardware needed
python -m novasun simulate register --model vx4s  # or uhd-jr, mctrl4k, ...
python -m novasun simulate coex                   # MX-class HTTP API
```

A **NovaPro UHD Jr** has been on the bench since 2026-08-26, at `192.168.0.10`,
driving 30 receiving cards across ports 0, 1, 2 and 4. Findings confirmed on it
are marked `OBSERVED` (see `registers.OBSERVED` and `registers.NOT_IMPLEMENTED`);
`docs/sources.md` records what it can and cannot settle.

An **MX40 Pro** on a live-show network was listened to passively and then read
through the read-only client — first a single burst of eight HTTP GETs
mid-show (2026-09-11), later two more bursts and a ten-minute 1 Hz poll; its
firmware is UNKNOWN. Until the MX30 below, that was the whole of this project's
contact with COEX hardware, and it changed a lot: every response shape the simulator had
guessed was wrong, `/api/v1/device` is absent (HTTP 404) on that firmware, SNMP
was off, and the application both crashed on the real monitoring payload and
would have opened register-bus sessions to the controller. All four are fixed;
the simulator now emits the observed shapes by default. VX4S is still
document-and-simulator only.

An **MX30** — firmware v1.5.1, operator-reported at first and later read over
SNMP; nothing read over HTTP gives model or firmware — was read the same way on
2026-09-26, unattended after a show with the wall still lit: two pings, about
950 GETs, two SNMP GETs, eight discovery probes; in that read-only pass nothing
else — no TCP 5200, no PUT. Two traps came out of it.
**Absent paths answer HTTP 200 with an empty body and no envelope** —
documented and made-up paths alike, in the same ~2 ms as a real endpoint —
where the MX40 Pro answered 404; only the missing envelope tells them apart,
and `CoexClient.request` turns that body into `{}`, so an empty 200 must never
be read as "exists". And **`monitor/info.name` is a label, not a model**: a
plain word on this unit, not `MX30_<digits>`, so no model can be read from it
(OBSERVED on that unit; that the word is operator-set is REASONED) — `survey`,
`watch` and `identify` all reported the word as the model that day. The
observed shapes, with synthetic values, are `tests/fixtures/mx30_like_api.json`.
Scope: one unit, one firmware.

Later that afternoon, **with VMP closed and the operator's explicit go**, the
same MX30 took this project's first COEX writes — 2 `colorBeacon` PUTs and 5
`snmpstate` PUTs, SNMP left off — its first SNMP walk, and a register-bus
probe. With the operator then watching the chassis, nine more `colorBeacon`
PUTs across three request bodies changed nothing visible: treat that endpoint
as absent on this firmware (REASONED). **SNMP turns on with `{"state": true}`; `{"value": true}` answers
Success and does nothing**, which is what `set_snmp` sent at the time, so read
back after any PUT. SNMP gave model `MX30` and firmware `V1.5.1`, which HTTP
does not; its quirks (no MIB-2 system group, x100 values (REASONED), bitmask
statuses, `ERROR:` strings, role 1 on a standalone unit) are in
`docs/read-only-monitoring.md`, the walk in
`tests/fixtures/mx30_snmp_walk.json`. TCP 5200 refused and UDP 5201 stayed
silent — one unit, one moment, VMP closed. That changes nothing below.

**Neither COEX unit answered `rqProMI:` discovery** (OBSERVED on the MX40 Pro;
the MX30 left eight probes unanswered), so `novasun discover` cannot find COEX
hardware; it has to be given the address.

**On a live show, never open a register-bus session to a COEX controller.** The
session is exclusive and displaces the VMP session running the show. `bringup`
and `info` open one unconditionally. `identify()` — and so `serve` and `status`
— stops at the HTTP API once it has answered, but check that holds in the
version you are running before trusting it near a live unit. `listen`,
`watch --once`, `coex snapshot` and `survey --no-probe` are read-only by
construction. Use those, and only with the operator's go.

**Four firmware behaviours make naive register reads lie**, all OBSERVED and
all silent — well-formed frames, `ack = SUCCEEDED`, no error. The two that
matter when probing:

- **An unimplemented address returns the previous read's payload**, not zeros.
  A sequential sweep therefore reports nearly every address as a live register
  holding plausible data. Test an address by poisoning the response buffer with
  a known value first; use several distinct poisons, and key the verdict on
  whether the value *varies with* the poison rather than on whether it ever
  equals one. `bringup._classify_register` does this.
- **Reads snap to field boundaries.** A read starting inside a multi-byte field
  returns that field's start. Reads at documented base addresses are fine, so
  this is a trap for probing, not a bug in normal use — but a block cannot be
  walked byte by byte.

The other two bite in normal use: **a block must be read from its base in one
request** (chunking a read corrupts it), and **the receiving-card monitoring
block is exactly 0x100 bytes** (reads beyond it alias into another block). Both
are traps 3 and 4 in `docs/read-only-monitoring.md` §5.

Everything else is validated against vendor documents and the two simulators. When adding a
protocol feature, add it to the relevant simulator too — otherwise it is
untestable, and an untested protocol claim is a guess with extra steps.

The register-bus simulator models a real chain (ports, per-card registers,
`ack=TIMEOUT` for absent cards, silence for absent chain positions) precisely so
that addressing mistakes fail here rather than on site. Do not flatten it.

## The application layer

`app/state.py` holds the model, `app/screens.py` the operator-facing grouping,
`app/config.py` the persistence, and `app/server.py` only exposes them. Keep
that split: a different front end should be able to import the state layer
without starting a web server.

**Screens are venue knowledge, not protocol.** Which output ports feed which
wall cannot be discovered, so it is entered by a human and persisted. A screen
action addresses only its members' own ports — a partial screen blacks out via
the receiving cards rather than the processor register, which would blank the
whole output including a screen sharing that processor.

**Alerting exists to be trusted, so restraint is the feature.** Dwell before
calling a device offline, hysteresis so a threshold reading cannot flap,
acknowledgement that silences without dismissing, and clearing events so the log
is a history rather than a permanent fire. `Thresholds.validate` rejects
settings that would reintroduce flapping. Do not "simplify" these away.

**Config is written atomically and a corrupt file is moved aside, never
overwritten.** Losing a venue layout to a stray character is worse than starting
empty. A config version newer than the build refuses to load rather than being
rewritten.

Rules it enforces, worth preserving:

- **Reachability is a state, never an exception.** `unreachable` and `in-use`
  are normal conditions with backoff, not error dialogs.
- **Capabilities drive the interface.** A control is offered only if the
  connected model supports it; unestablished encodings are shown and disabled
  with the reason, never guessed.
- **Destructive actions are labelled, not blocked.** `DESTRUCTIVE` tells the
  interface what to confirm. Blackout and freeze are legitimate and also ruin a
  show.
- **No route to flash writes, factory reset or program space.** `_dispatch`
  is an allowlist; there is a test asserting those actions are rejected.
- **The service binds to localhost** and has no authentication. It holds
  control sessions to live screens; do not change the default.

## Things that bite

- **Frame length is not a field.** Only write-requests and read-responses carry
  a payload; a stream reader needs 18 bytes before it knows the total.
- **Blackout and freeze are swapped** between the VX4S register (1 freeze,
  2 blackout) and the COEX HTTP API (1 blackout, 2 freeze).
- **Input select differs by register, not just by value**, across model
  families.
- **No literal `%` in argparse help strings** — argparse runs them through
  `%`-formatting and `--help` crashes at runtime. There is a test for it.
- **Settings live in RAM** until an explicit save to `0x01000001`. Never wire
  that to a slider; flash wear is real.
