# Read-only monitoring

Written for consumers that observe NovaStar hardware without controlling it —
crewbox in particular. It answers four questions, and is explicit about which
answers are established and which are not.

Confidence labels used throughout:

| Label | Meaning |
|---|---|
| **OBSERVED** | Seen on real hardware by this project, and reproduced |
| **OFFICIAL** | Stated in a NovaStar document |
| **DERIVED** | From decompiled NovaLCT assemblies or published client code |
| **REASONED** | An inference from protocol properties, not observed |
| **UNKNOWN** | Not established. Needs a bench. Do not design around a guess |

Most of this document was written with no NovaStar hardware available. On
2026-08-26 a **NovaPro UHD Jr** (model ID `0x6205`, firmware reporting
`App,0161`) was put on the bench, and the facts it settled are now marked
**OBSERVED**. Every OBSERVED claim below was reproduced across a power cycle of
the unit. Note the scope: one processor, one model, no receiving cards attached.
An OBSERVED fact here is a fact about that unit, not yet about the fleet.

---

## Recommendation first: use SNMP

For a read-only monitoring pane on COEX hardware (MX/CX/KU), SNMP is a better
answer than either passive listening or HTTP polling, and it is the one this
repository recommends. **OFFICIAL** — NovaStar publishes *SNMP Protocol
Instructions V1.4.0* with a full OID map.

- GET is read-only by construction, which removes the "could this write?"
  question entirely.
- It covers more than the HTTP API does for monitoring: per-point mainboard
  temperatures and voltages, fan status, output-card and input-card health,
  Ethernet port link status, per-receiving-card temperature and voltage status,
  per-input signal presence and connector type.
- It supports **traps**, so the controller pushes changes to a collector on port
  162 instead of being polled. For a monitoring tool that is the right shape.

The OIDs are transcribed in [`../src/novasun/snmp.py`](../src/novasun/snmp.py)
with their enumerations. There is deliberately no SNMP client in this
repository — use your platform's.

Two preconditions matter to a read-only consumer: **SNMP must already be enabled
on the controller** (front panel, or a write via the HTTP API), and **traps need
a reporting target configured**, also a write. A strictly read-only tool cannot
turn either on, and should surface "SNMP not enabled" as a state rather than
attempting it. Polling with GET needs neither.

**OBSERVED, 2026-09-11:** on the one COEX unit this project has read — an MX40
Pro running a live show — `/api/v1/device/snmpstate` returned `{"state":
false}`. SNMP was off, and a read-only consumer could not have turned it on. So
the recommendation above is conditional on a precondition that did not hold on
the first unit seen; in practice the HTTP GET path in §4 was the only
monitoring available, which is why its field names being OBSERVED now matters
more than the SNMP OID map, which remains unexercised.

---

## 1. What can be learned with zero transmission?

**Do controllers announce themselves unsolicited?** **No — OBSERVED.** A
passive listener on UDP 3800 sat for thirty minutes on a live-show network with
an **MX40** on the same segment (L2 adjacency confirmed from the ARP table) and
heard nothing from it. No document describes unsolicited announcement, no
published implementation listens for one, and now a controller has been watched
and did not make one. Scope: one model, one thirty-minute window.

**Would a silent listener see the inventory when NovaLCT is running?**
**Partly, and the crucial half is UNKNOWN.**

What is certain: the probe is broadcast to the subnet broadcast address *and* to
multicast `224.224.125.119`, both on UDP 3800 (**DERIVED**, from
`sarakusha/novastar`'s discovery implementation). So any host on the segment
sees NovaLCT and VMP probing. That alone tells you a control application is
running and roughly how often it scans.

What is not, or rather **what no longer is**: whether the reply is broadcast or
unicast. **It is unicast. OBSERVED, and this is the answer crewbox needs.** A
packet capture of a discovery exchange on the wire:

```
probe  00:13:3b:fb:82:ea > ff:ff:ff:ff:ff:ff   192.168.0.50 > 192.168.0.255
reply  54:b5:6c:08:5d:49 > 00:13:3b:fb:82:ea   192.168.0.10 > 192.168.0.50
```

The probe goes out to the broadcast MAC and the broadcast IP; the reply comes
back addressed to **the requester's own MAC and IP**, at both layer 2 and layer
3. A switch will not forward it to any other port.

**Therefore passive discovery does not yield an inventory.** A listener on a
third host sees every probe — so it can tell that NovaLCT or VMP is running, and
how often it scans — but it never sees a single reply, and so never learns what
is on the network. Getting the inventory passively needs a port mirror, a tap,
or a listener running on the same host as the control application. This was
previously guessed at as "the likelier design"; it is now measured.

**How long would a listener wait?** **Indefinitely — OBSERVED for VMP.** During
that same thirty minutes VMP was running and operating the show, and nobody
pressed search. The listener overheard **zero probes**. VMP does not discover on
a timer; it probes only on user action. Passive discovery on a VMP-operated
network therefore has nothing to overhear until an operator happens to press a
button, which during a show they will not.

NovaLCT's cadence is still **UNKNOWN** — it has not been watched — but the
working assumption should now be the same, because that is what the one
vendor tool observed actually did.

**One caveat both findings share.** Broadcast filtering on the show switch was
not ruled out: the ARP entry proves the Mac and the MX40 share a segment, not
that broadcasts reach the Mac's port. The positive control is a packet capture
showing *any* broadcast traffic (ARP requests will do) arriving during the
window. It was not run — the show took precedence — so these two results are
OBSERVED with that stated hole rather than OBSERVED clean.

### The middle option worth considering

There is ground between "transmit nothing" and "open a control session". Sending
the discovery probe yourself is a **broadcast UDP read with no addressed target
and no register write** — it cannot change controller state, and it is exactly
what NovaLCT emits routinely. **REASONED**, not observed, but the reasoning is
strong: the probe carries no register address, no write bit and no destination
device.

For crewbox, an active discovery sweep every few minutes is very likely safer
than it sounds, and turns "unknown wait" into "known 1-second answer". Whether
that crosses your read-only line is a policy decision, not a technical one.

### Settling it

[`../src/novasun/passive.py`](../src/novasun/passive.py) is a listener with no
send path — the test suite asserts that structurally (no `.send`/`.sendto` in
the module) and behaviourally (a peer socket sees nothing while it runs).

```python
from novasun.passive import listen
inventory = listen(duration=600)      # ten minutes, transmitting nothing
print(inventory.summary())
```

It reports the median probe interval and, if it sees probes but no replies, says
so explicitly. It also writes a session record even when it hears nothing,
because the first real run heard nothing for thirty minutes and that silence
turned out to be the finding. Questions 1 and 2 have now been settled by it —
against VMP and an MX40 rather than NovaLCT, and with the broadcast-filtering
caveat above.

---

## 2. Decoding the `rpProMI:` reply

**Partly settled — one reply has now been captured.** An earlier note in
[`investigation.md`](investigation.md) said the reply "appears to carry model and
name information this implementation currently ignores". That overstated what I
had at the time, and it was withdrawn. It is worth keeping the correction on the
record even now that a sample exists, because the sample does **not** vindicate
the guess: the tail carries no model ID and no device name.

The captured reply, from a NovaPro UHD Jr:

```
rpProMI:App,0161
727050726f4d493a 4170702c30313631
└── prefix ────┘ └── tail, 8 bytes: ASCII "App,0161"
```

| Fact | Confidence |
|---|---|
| Probe is the 8 ASCII bytes `rqProMI:` | **OBSERVED** |
| Reply begins `rpProMI:` | **OBSERVED** |
| Both on UDP 3800; multicast group `224.224.125.119` | **OBSERVED** |
| The device is identified by the reply's **source IP** | **OBSERVED** |
| Reply is 16 bytes total: 8-byte prefix + 8-byte tail | **OBSERVED**, one model |
| Tail is **ASCII**, not binary | **OBSERVED** |
| Tail of this unit is `App,0161` | **OBSERVED** |
| Tail is stable across a power cycle | **OBSERVED** |
| The tail contains **no model ID and no device name** | **OBSERVED** |
| What `App` and `0161` actually mean | **UNKNOWN** |
| Whether the tail is fixed-width on other models | **UNKNOWN** |
| Reply is **unicast** to the requester, at both layer 2 and layer 3 | **OBSERVED** |
| The device does **not answer the multicast probe** | **OBSERVED**, one model |

`App` is plausibly a run-mode marker (application firmware, as against a
bootloader) and `0161` plausibly a version, but both readings are **REASONED**
and neither is worth building on. What matters for a consumer is the shape:
the tail is short ASCII, and **identification still has to come from the
register bus or the HTTP API, not from discovery**. A consumer that hoped to
build an inventory with model names from discovery alone cannot.

**The unicast question is settled — the reply is unicast.** See §1: a capture
shows it addressed to the requester's own MAC and IP. It took a packet capture
rather than a second host, because the reply's destination address is in the
frame.

**A second finding from the same capture: this device ignores the multicast
probe.** Probes were sent to the subnet broadcast, to the multicast group
`224.224.125.119`, and unicast to the device, ~2 s apart. Broadcast and unicast
each drew a reply within ~12 ms. The multicast probe drew nothing — and the
capture confirms it left the host correctly, with the right layer-2 mapping
(`01:00:5e:60:7d:77`) for that group, so this is the device declining to answer
rather than a probe that never went out.

That matters because this repository documents multicast as one of the two
discovery destinations, **DERIVED** from published client code. On this model it
is dead. A discovery implementation that used the multicast group alone would
find nothing. Send the subnet broadcast; treat multicast as an extra that may
work on other models, not as a path to rely on. Whether NovaLCT's own multicast
probe is answered by *any* NovaStar model is **UNKNOWN**.

I searched the decompiled NovaLCT assemblies shipped with `sarakusha/novastar`
for the discovery strings and found nothing: the handshake lives in a component
not included there. So there is no second source to cross-check against.

`decode_reply` in `passive.py` is written for that state of knowledge. It keeps
the tail as bytes and offers only conservative readings — NUL/comma-delimited
text if the tail is text, a hex dump if it is not — and reports "no payload
beyond the prefix" rather than inventing fields. When you capture a real reply,
the layout goes in there and this section gets rewritten.

**If model, name and serial do turn out to be in the reply**, that is most of a
monitoring pane from pure observation, and worth the capture. **If they do not**,
the fallbacks are: identity over SNMP (`CONTROLLER_MODEL`, `CONTROLLER_NAME`,
`CONTROLLER_SERIAL`, `CONTROLLER_IP`), or a model-ID read on the register bus,
which needs a control session.

To capture one, with hardware:

```bash
python -m novasun listen --duration 600 --log discovery.log   # transmits nothing
# open NovaLCT on another machine and let it scan
```

Each line is `timestamp<TAB>source<TAB>hex`. A single reply answers this.

---

## 3. Is COEX HTTP on 8001 safe to poll while VMP is connected?

**Yes for a single burst of GETs — OBSERVED once. Sustained polling is still
REASONED.**

On 2026-09-11 a read-only client issued the eight snapshot GETs — device,
screens, cabinets, inputs, presets, monitor/info, audio, snmpstate — against an
**MX40 Pro** that VMP was driving through a live show. All eight were answered in
0.1 s total, about 680 KB, with no `Busying` and no visible effect on the show.
Two answered HTTP 404 (`device`, `audio`), which is a firmware fact, not
contention. That is one burst, not a polling regime: what a sustained cadence
does to VMP is still not established, and the policy below stands.

The evidence, and its limits:

- **The API is documented for third-party integration.** NovaStar's manual says
  it is "provided for users to realize secondary development" (**OFFICIAL**).
  An integration API that broke when the vendor's own software was attached
  would not be much of an integration API.
- **It is a different port and a different protocol** from the register bus.
  The exclusivity concern I raised in [`investigation.md`](investigation.md) is
  about TCP 5200, where a control session is stateful. HTTP on 8001 is stateless
  and request-scoped (**REASONED**).
- **The API has a `Busying` error code (5)** (**OFFICIAL**). A device that
  signals contention through a response code is one that expects concurrent
  callers and degrades rather than breaking.
- **There is no authentication and no session** (**OFFICIAL**), so there is
  nothing for a poller to hold or steal.

What is not established: whether a GET can slow VMP's own operations, whether
any GET has side effects despite the verb, and what rate the controller
tolerates. None of that is documented.

### Recommended polling policy

Implemented in [`../src/novasun/monitor.py`](../src/novasun/monitor.py):

- **Structurally read-only.** `ReadOnlyCoexClient` rejects any method other than
  GET before a socket opens. Every setter inherited from the full client funnels
  through the same `request` method, so blocking it there closes all of them —
  including any added later. Tested by calling six setters and asserting the
  device saw no PUT.
- **Rate limit**, default 200 ms between requests. A full poll is eight
  endpoints, so about 1.6 s of wall time.
- **Back off on code 5.** A `Busying` response pushes the next request out five
  seconds rather than retrying.
- **Tier the endpoints.** Topology and identity (cabinet list, presets, device
  info) are re-read every tenth poll; status every poll. Tested.
- **Degrade, never raise.** An endpoint the firmware does not implement lands in
  `snapshot.errors` and the rest of the poll completes.

A suggested cadence: **status every 10–30 s, topology every few minutes.** That
is far below anything likely to matter, and monitoring rarely needs faster.

### Settling it in ten minutes

Have VMP connected and doing something visible — a preset recall, a brightness
ramp. Run `CoexMonitor` at 1 Hz alongside. Watch for VMP stuttering, `Busying`
responses, or a dropped VMP connection. If none appear in ten minutes at 1 Hz,
polling at 0.05 Hz is not going to be the thing that breaks a show.

---

## 4. What monitoring is available over GET alone?

Two surfaces. **SNMP is richer**; the HTTP API is easier to consume.

### Over SNMP GET — **OFFICIAL**, from the SNMP document

| Fact | OID |
|---|---|
| Model, name, serial, MAC, IP, firmware, date/time | `1.3.6.1.4.1.319.10.10.1.2` … `.1.8` |
| Primary/backup role | `…10.10.1.5` — 0 primary, 1 backup |
| Mainboard temperature points: count, name, status, value | `…10.10.10.1`, `…10.2.N.{1,2,3}` |
| Mainboard voltage points | `…10.10.10.3`, `…10.4.N.{1,2,3}` |
| Fans: count, name, status | `…10.10.10.5`, `…10.6.N.{1,2}` |
| Output card slot status | `…10.10.30.2` — 0 connected, 1 disconnected |
| Output card firmware, name, role, serial | `…10.10.30.3.N.{1..4}` |
| Ethernet port count, **link speed**, status | `…10.10.30.5.N.{1,2,3}` |
| **Receiving cards online per port** | `…10.10.30.5.N.4.Y.1` |
| **Per-receiving-card temperature status** | `…10.10.30.6.N.1.Y.1.M` |
| **Per-receiving-card voltage status** | `…10.10.30.6.N.1.Y.2.M` |
| Input card slots: count, status, firmware, name, role, serial | `…10.10.20.{1,2,3.N.*}` |
| **Input signal status per source** | `…10.10.20.5.N.2.Y.1` — 0 not inserted, 1 signal, 2 inserted but no signal |
| **Input connector type per source** | `…10.10.20.5.N.2.Y.2` — DVI, HDMI 1.4/2.0/2.1, DP 1.1/1.2/1.4, 3G/6G/12G-SDI, ST 2110, … |
| Screen count, width, height, frame rate | `1.3.6.1.4.1.319.10.20.1.1`, `…1.2.N.{2,3,4}` |
| **Screen brightness read-back** | `…10.20.1.2.N.5` — note: read/write |
| Sync source and sync frame rate | `…10.20.1.2.N.{6,7}` |

That covers every item in the question: temperature, cabinet and card status,
input state, redundancy (primary/backup at controller, output-card and
input-card level), and brightness read-back.

`N`/`Y`/`M` are 1-based indices bounded by the corresponding count OID.
`snmp.Oid.at(...)` substitutes them.

### Over COEX HTTP GET

Endpoint paths are **OFFICIAL** (manual and published clients). **Response field
names are not verified against firmware** — they follow the manual and what
published clients expect, and `coexsim.py` reproduces those shapes. Treat field
spellings as provisional and code defensively; `monitor.py` does, leaving
unrecognised fields `None` and keeping the raw payload on the snapshot.

**Update, 2026-09-11 — the field names below are now OBSERVED** on one MX40 Pro,
and the earlier table (kept for the record in the git history) was wrong on
every row that named a field. `coexsim.py` now emits these shapes by default.

| Endpoint | On an MX40 Pro | Confidence |
|---|---|---|
| `GET /api/v1/device` | **HTTP 404.** Identity comes from `monitor/info.name` instead: `"MX40 Pro_<digits>"` | OBSERVED |
| `GET /api/v1/device/monitor/info` | `name`, `runtime`, `totalRuntime`; `mainBoardTemperature.value` (°C), `mainBoardVoltage.value` (V); `fanInfos[].fanSpeed` (rpm) and `.status`; `cabinets[]` — each with `rvCards[]` carrying `cabinetID`, `temperature.value`, `voltage.value`, `humidity`, `errorBit[]`, `nextCabinetLinkStatus.linkStatus`, runtimes; `controllerPortMonitorInfos[]`, `outputStatus[]`, `powerMonitorInfos[]`, `screenSourceStatus[]` with numeric `status` codes. 265 KB for 288 cabinets | OBSERVED (field names); `status` code meanings UNKNOWN |
| `GET /api/v1/device/cabinet` | bare list: `id` (64-bit, matches `rvCards[].cabinetID`), `index`, `outputID`, `outputCardID`, `outputIndex`, `canvasID`, `brightness` **as a 0–1 fraction**, `gamma{r,g,b}`, `gain{r,g,b}`, `colorTemperature`, `resolution{}`, `size{}` (mm), `rvCardName`, `rvCardInfo{firmware, scanNumber, refreshRate, moduleResolution}`, `power`. No name, no online, no temperature. 342 KB for 288 | OBSERVED |
| `GET /api/v1/screen` | `screens[]` with `screenID`, `screenName`, `workingMode`, `masterFrameRate`, `lowLatency`, `canvases`; and `screenGroups[]`. No screen-level brightness | OBSERVED |
| `GET /api/v1/device/input/sources` | bare list: `id`, `name`, `type` (int code), `sourceStatus`, `usable`, `actualResolution{}`, `actualRefreshRate`, `colorSpace`, `defaultEDID{}`. **A disconnected input still reports a resolution** (the EDID default); `sourceStatus` is what distinguishes it — 1 on the inputs feeding the show, 0 elsewhere | OBSERVED; `sourceStatus`=signal REASONED |
| `GET /api/v1/preset` | `screenPresets[]`, each `screenID` + `presets[]` with `presetUUID`, `name`, `sequenceNumber`, `state` (active) | OBSERVED |
| `GET /api/v1/device/snmpstate` | `{"state": false}` — SNMP was **off** on the unit | OBSERVED |
| `GET /api/v1/device/audio` | **HTTP 404** | OBSERVED |
| `GET /api/v1/device/screen/displaymode`, `/backup`, `/multifunc-card/detailinfo` | not requested | as before |

Three consequences for a consumer. **Cabinet health lives on the receiving card,
not the cabinet:** `monitor/info.cabinets[].cabinetID` is always 0 and its
top-level readings are 0; the join to `/device/cabinet` is `rvCards[].cabinetID`
= `id` (288 of 288). **There is no online flag** — a cabinet present in
`monitor/info` with a reporting card is the working definition of online
(REASONED), and its absence is how "offline" is expressed. **Every reading is an
object,** `{"name", "nameEn", "status", "value"}`, never a bare number; a reader
that assumed otherwise crashed the application's refresh thread on first
contact.

**A fourth consequence, from a second snapshot 35 minutes later: `monitor/info`
returns its cabinets in a different order on every call.** All 288 changed list
position between the two reads, with the same ids and the same per-id
attributes; `/api/v1/device/cabinet` kept a stable order, and
`screenSourceStatus[]` reordered too. **Never trend or diff `monitor/info` by
list index** — key everything on `rvCards[].cabinetID`. A positional comparison
of the two snapshots reported 1,974 changes across 15 fields; keyed by id there
were 344 across 7 — of which 288 were the per-card runtime counters advancing,
as they do on every read, and 41 were one-degree temperature flickers. The
identity fields that had dominated the positional diff reported no change at
all. `diff_snapshots` now aligns by identity for exactly this reason.

What the same 35 minutes showed about *readings*, on a quiet wall (OBSERVED,
one interval):

| Reading | Behaviour over 35 min |
|---|---|
| `rvCards[].temperature.value` | integer °C; 41 of 288 cards moved, all by ±1; range 37–42 → 36–42 |
| `rvCards[].voltage.value` | one decimal; 9 of 288 moved, all by ±0.1 |
| `nextCabinetLinkStatus`, `errorBit` | unchanged on all 288 |
| `mainBoardTemperature.value` | unchanged (42); `mainBoardVoltage.value` +0.06 |
| `fanInfos[].fanSpeed` | +5 to +6 rpm |
| `runtime`, `totalRuntime`, `rvCardsRuntime[].totalRuntime` | **seconds, at 60-second granularity**: +2040 over 2081 s of wall clock; every one of 289 values is a multiple of 60; per-card deltas exactly 2040 or 2100 |

For a threshold: a one-degree flicker is noise on this hardware, so an alert on
per-card temperature needs at least the two-degree hysteresis the application's
`Thresholds` already enforce.

`MonitorSnapshot` folds these into `healthy`, `offline_cabinets`, `hottest`,
`signal_present` and `display_mode`; `CabinetHealth` now carries `voltage` and
`link_ok` as well. `interpret_monitor_info()` is the one, total interpreter for
the monitoring payload.

### Receiving cards over the register bus

Receiving cards can be found and identified, and it is a pure read:
`0x00000000` on device type 1 gives a model ID (non-zero = present and working)
and a firmware version. **OFFICIAL** — M3 protocol document §3.9, frames
checksum-verified.

Useful for a monitoring pane: it yields the real cabinet count per port, each
card's firmware, and a health flag (a card that answers with all-zero firmware
is not running). Combined with the `0x0A000000` block it gives per-cabinet
temperature and voltage.

**All of this is now OBSERVED**, against a UHD Jr driving 30 receiving cards:

| Fact | Evidence |
|---|---|
| Present card answers `0x00000000` with model + firmware | 30 cards, model `0x4506`, firmware `4.3.0.0` |
| Absent position answers `ack = TIMEOUT` | ports 3 and 5–15, and every index past the end of a chain |
| Chains are addressable per port and per index | ports 0 and 2 hold 10 cards, port 4 holds 9, port 1 holds 1 |
| Cards are individually addressed, not aliased | per-card temperature spread 33–37 °C, voltage 4.2–4.3 V |
| The §3.1.1 decode is correct | validity bit, `raw[1] x 0.5` for temperature, `(raw[3] & 0x7F) / 10` for volts |
| The validity bits mean what they say | humidity byte reads `0x00`, correctly decoded as "no reading", on cards with no humidity sensor |

Two things worth drawing out.

**The receiving-card presence test is not affected by the stale-buffer trap in
§5.** An absent position returns a genuine `TIMEOUT` ack, not an echo — verified
by poisoning the buffer with three different values and probing a card position
each time, which returned the card's real data every time. So unlike register
probing on the sending card, *chain enumeration can be trusted at face value*.
That is the good news in this document for anyone building a cabinet view.

**A gap in a port does not mean the end of the chain.** This unit populates
ports 0, 1, 2 and 4, skipping 3. An enumerator that stops at the first empty
port finds a quarter of the installation. Enumerate all of them.

The cost is that it needs a **control session on TCP 5200**, which is the thing
a read-only consumer should not take. It is a read in protocol terms and an
intrusion in operational terms. `survey` therefore leaves it behind
`allow_register_bus`, and the application exposes it as an explicit "scan chain"
action rather than doing it on a refresh tick — one round trip per chain
position, so a 16-port processor is hundreds of frames.

On COEX hardware, do not do this: the controller already reports the same
hardware as cabinets over HTTP, with no session to take.

### On non-COEX hardware (VX4S, NovaPro UHD Jr)

**No session-free path exists.** There is no HTTP API and no SNMP; everything
below needs a TCP control session on 5200, and a controller accepts only one --
**OBSERVED**: opening a second connection to a UHD Jr while one was already
established reset the existing one (`ECONNRESET`), so this is genuinely
exclusive, not merely discouraged. A consumer that takes it takes it from
NovaLCT.

What was previously written here -- that such a pane could show "reachable / not
reachable plus whatever identity it can get, and not much else" -- **understated
what is available.** Behind that one session a UHD Jr exposes a great deal:

- per-receiving-card temperature, voltage and health (`0x0A000000`, above)
- the real chain topology, per port and per index
- **per-input-connector signal state**, which is new -- see below

### Per-connector signal state -- OBSERVED

`VIDEO_SOURCE_STATE` at `0x13010000` is not a flat block describing "the current
input", which is how this repository previously described it. It is an **array
of 32-byte records, one per connector**, carrying its own index:

| Offset in record | Width | Meaning | Confidence |
|---|---|---|---|
| `+0x04` | u16 | signal width in pixels, `0` when no signal | **OBSERVED** |
| `+0x06` | u16 | signal height in pixels, `0` when no signal | **OBSERVED** |
| `+0x08` | u16 | measured frame period in microseconds | **OBSERVED** |
| `+0x16` | u8 | record index, `0x00`..`0x08` ascending | **OBSERVED** |
| `+0x19` | u16 | refresh rate in centihertz (`6000` = 60.00 Hz) | **OBSERVED** |

On a UHD Jr, records `0`-`7` are input connectors and record `8` reports
`3840x2160` -- the unit's own 4K canvas, not an input. Past record 8 the values
are incoherent and the index byte stops ascending: that is the end of the array,
not more data.

**Record 1 is the HDMI connector on this unit**, established by plugging and
unplugging a 1920x1080 source: record 1 alone moved between `1920x1080` and
`0x0` while records 0 and 2-7 stayed at zero throughout. Which connector each
of the other indices corresponds to is **UNKNOWN** -- it needs a source on each
in turn, and this bench had only one.

The two rate fields were confirmed by driving the connector at two rates from a
laptop and watching the record:

| Source mode | width x height | `+0x19` | `+0x08` | `1e6 / period` |
|---|---|---|---|---|
| 1920x1080 @ 60 Hz | `1920x1080` | `6000` | 16663-16666 us | 60.01 Hz |
| *link re-training* | `0x0` | — | — | — |
| 1920x1080 @ 50 Hz | `1920x1080` | `5000` | 20000 us | 50.00 Hz |
| 3840x2160 @ 60 Hz | `3840x2160` | `6000` | 16663 us | 60.01 Hz |

Resolution and refresh vary independently of each other, which is what
establishes that these are four separate fields rather than one composite mode
code.

So `+0x19` is the **nominal** rate in centihertz and `+0x08` the **measured**
frame period in microseconds — 20000 us is exactly 1/50 s, and only `+0x08`
jitters, which is the tell for a measurement rather than a declaration. A
consumer wanting a stable "50 Hz" label should read `+0x19`; one wanting to
detect a drifting or out-of-spec source should watch `+0x08`.

The mode change also passed through a brief no-signal state that the record
reported as `0x0`, so `width == 0` tracks genuine signal loss during link
re-training and not merely cable removal.

One practical note for anyone reproducing this: changing a *scaled* resolution
on macOS does not change the wire timing, and the record correctly does not
move. Only a genuine output-mode change reaches the connector. That is a useful
property in itself — the record reports what the processor actually receives,
not what the source believes it is displaying.

### The sending card's brightness is not the wall's brightness

**OBSERVED, and a trap for exactly this kind of consumer.** On a UHD Jr driving
30 cabinets, `GLOBAL_BRIGHTNESS` (`0x02000001`) read **`0xFF`** on the sending
card and **`0xAA`** on its receiving cards. The wall was running at 67%, and the
processor-level register said 100%. `GAMMA` disagrees between the two levels in
the same way (`0xFF` against `0x1C`).

A pane that reads the processor and labels it "brightness" will be wrong
whenever the two have diverged, and will be wrong silently. **Read the receiving
cards for anything you intend to display as the screen's state**, and treat the
sending-card value as a separate quantity rather than as a cheaper way to get
the same number.

This is one more reason the chain walk matters: it is not only where the
per-cabinet detail lives, it is where the *correct* screen-level values live too.

**For a monitoring pane this is the useful find:** signal presence, resolution
and refresh for every input, all by reading. `width == 0` is a reliable "no
signal" indicator -- it was observed going to zero on cable removal and back to
`1920x1080` on reconnection, with nothing else in nine swept register regions
moving.

**What is NOT available: which input is selected.** See
[`target-hardware.md`](target-hardware.md#refusing-rather-than-guessing). A
consumer cannot currently show "this processor is on HDMI"; it can show "HDMI
has a 1920x1080 signal", which is a different statement. Do not present one as
the other.

---

## 5. Two register-bus traps that make reads lie

**OBSERVED on a NovaPro UHD Jr, reproduced across a power cycle.** Both of these
contradict assumptions this project previously held in writing, and both matter
to anyone who reads registers — including a read-only consumer, because *both
are triggered by reads alone*. Neither produces an error. Both produce
plausible-looking wrong data.

### Trap 1: an unimplemented address returns the previous response

An earlier version of [`investigation.md`](investigation.md) said "unknown
addresses generally read back as zeros". **That is wrong, and the correction is
the single most important finding on this page.** Reading an address the
firmware does not implement returns *the payload of the previous read on that
connection*, apparently straight out of an uncleared response buffer:

```
read 0x02200020 (8 bytes) as the first request of a session -> 01 00 00 00 00 00 00 00
read 0x0008FFF2 -> 54           then read 0x02200020 -> 54 08 00 00 00 00 00 00
read 0x00000000 -> 09 36 05 62  then read 0x02200020 -> 09 36 05 62 00 00 00 00
read 0x00000016 -> 16 04 11 00 c1 c9 2d 00
                                then read 0x02200020 -> 16 04 11 00 c1 c9 2d 00
```

The response frame is otherwise well-formed: correct header, correct echoed
address, `ack = SUCCEEDED`, valid checksum. Nothing about it says "no such
register".

The consequence is severe for map-building. **A register sweep that reads
candidate addresses in sequence will report almost all of them as implemented,
with values that look like real data**, because each is echoing its predecessor.
Any address-map work — anyone's, not just this project's — must control for it.

**The discriminator: poison the buffer.** Read a known register with a
distinctive value, then read the candidate. If the candidate returns the poison,
it is unimplemented. Repeat with a second, different poison, because a candidate
whose genuine value happens to match one poison would otherwise be misread —
this is not hypothetical, a two-trial version of this test misclassified
`0x02200022` before a four-poison version settled it:

```
poison 0x00000000 -> 09 36 ...   candidate reads 09  -> echo
poison 0x00000016 -> 16 04 ...   candidate reads 16  -> echo      => UNIMPLEMENTED
poison 0x00000000 -> 09 36 ...   candidate reads 00  -> independent
poison 0x00000016 -> 16 04 ...   candidate reads 00  -> independent => REAL, value 0x00
```

Four poisons over two rounds classified every candidate 8/8 consistently. Fewer
than that is not enough.

### Trap 2: reads snap to field boundaries

The bus is **field-addressed, not byte-addressed**. This project has described it
throughout as a memory bus where a read returns N bytes at an address; that is
not quite what the firmware does. A read whose start address falls *inside* a
multi-byte field silently returns data from the **beginning of that field**:

```
truth at 0x00000000:  09 36 05 62 02 05 a8 00 08
  read(0x01, 2) -> 09 36     byte-truth would be 36 05    SNAPPED to field at 0x00
  read(0x03, 2) -> 05 62     byte-truth would be 62 02    SNAPPED to field at 0x02
  read(0x05, 2) -> 02 05     byte-truth would be 05 a8    SNAPPED to field at 0x04
  read(0x07, 2) -> 00 08     correct - 0x07 IS a field base (u16 max packet size)
  read(0x08, 2) -> 00 08     byte-truth would be 08 00    SNAPPED to field at 0x07
```

Reading *forward across* fields works correctly, and a read that starts on a
field base is always right. Since the documented registers are field bases, code
that reads them as documented is unaffected — this is a trap for probing, not a
bug in existing reads. But it means **you cannot walk a block byte by byte to
discover its layout**: the byte-by-byte walk of `0x00000000` returns
`09 09 05 05 02 02 a8 00 00`, which is not the block's contents. Read blocks
whole.

### Trap 3: a block must be read from its base in one request

A corollary of trap 2, but it bites harder and in a way that looks like working
code. The firmware serves a block when the request starts **at the block's base
address**. A request starting partway in is resolved as whatever register lives
at *that* address — which may be something else entirely, not the block's
continuation.

The video-source array is the case that caught this project out. Reading it from
`0x13010000` returns a coherent array of records with ascending indices.
Reading `0x13010100` — offset `0x100` into that same array — returns this:

```
e4 e8 01 20  80 7e 00 10  c8 d6 01 20  80 7e 00 10
```

Those look like pointers (`0x2001e8e4`, `0x10007e80`), not signal state. The
address has its own meaning; it is not "the array, 256 bytes in".

So a client that chunks a long read — as this repository's `Controller.read`
does, at 256 bytes by default — silently corrupts any block longer than its
chunk size *if a chunk boundary lands on a defined register*. The array came
back one record short, with no error and nothing obviously wrong, until the
missing record was noticed by eye.

**It does not always bite**, which is what makes it nasty. The 512-byte gamma
tables chunk perfectly well: `0x05000100` is apparently not separately defined,
so the second request returns the continuation as hoped. Both reads produce the
same clean monotonic ramp. You cannot tell the safe blocks from the unsafe ones
by looking at the client.

**Read blocks in a single request.** The negotiated max packet size is 2048 on a
UHD Jr, which covers every documented block. `read_connector_signals` passes an
explicit chunk to guarantee one frame, and there are tests asserting no request
starts partway into the array.

### Trap 4: the monitoring block is exactly 0x100 bytes

`0x0A000100` **aliases `0x02000000`** on a UHD Jr's receiving cards. So a read
longer than the documented block returns 256 bytes of monitoring followed by the
card's display registers — gamma, brightness, kill/lock modes — with nothing to
say the data changed meaning:

```
read 0x0A000000, 512 bytes -> bytes 256-271: 1c aa ff ff ff ff 3f 00 ...
read 0x02000000,  16 bytes ->                1c aa ff ff ff ff 3f 00 ...
```

A consumer that reads "a bit extra for safety" gets plausible bytes that decode
as nonsense temperatures and voltages. **Read `0x100` and no more**;
`registers.RECEIVER_MONITORING_SIZE` exists so that is not a magic number.

Address aliasing is not confined to this one case. **Two** pairs are OBSERVED on
a UHD Jr, both on a receiving card: `0x03000000` ≡ `0x13000000`, and
`0x0A000100` ≡ `0x02000000`. Each survives the test that matters — it equals its
claimed twin and *not* whatever was read immediately before it.

**A third pair, `0x03000000` ≡ `0x09000000` on the sending card, was published
here and is now withdrawn.** It was an echo, not an alias, and the way it was
produced is worth recording because it is the exact failure mode §5 trap 1
describes:

```
tested as:  read 0x03000000 ; read 0x09000000 ; compare   -> "identical!"
```

Reading the claimed source immediately before the claimed alias guarantees a
match on any unimplemented address, because the second read returns the first
one's payload. In a later capture where `0x09000000` was preceded by a different
read it returned something else entirely, which is what an echo does and an
alias never does.

**The test for an alias is therefore three-way**, and it is cheap:

1. read a poison, then A, then B — B must equal A;
2. read a *different* poison, then B alone — B must still equal A;
3. B must not equal either poison.

Anything less measures the read order rather than the address decoder. In the
1 KB-chunked sweeps, 21 of 26 top-level bases returned exactly their
predecessor's payload — so on this firmware, echo is the *common* case for an
address that is not backed, and an unexpected match between two regions should
be assumed to be one until all three steps pass.

### Screen geometry is readable — OBSERVED

Useful for a monitoring pane that wants to draw the wall rather than list it.

| What | Where | On the bench wall |
|---|---|---|
| Cabinet pixel dimensions | receiving card `0x02000017`, `0x02000019` (u16 each) | `104` and `208`, identical on all 30 cards |
| Row mapping table | receiving card `0x03000000` | u16 entries `0..103`, padded to 128 with `0xFFFF` |
| Cabinet position table | sending card `0x03000000` | ten u32s, `936` down to `0`, step `104` |

Three independent places agree on **104**, which is what makes it trustworthy as
the cabinet's vertical pitch: the dimension field, the count of real entries in
the row map, and the step in the position table.

**What is REASONED rather than observed:** which of `0x02000017` and
`0x02000019` is width and which is height, and that the sending-card table is
positions at all. One wall of uniform cabinets cannot separate width from
height, and cannot distinguish a position table from any other evenly-spaced
quantity. A second wall — ideally with cabinets of a different size — settles
both in minutes. Until then, a consumer can safely report "cabinets are 104x208"
without committing to which axis is which.

### What a read-only consumer should take from this

- Reading is still safe. Neither trap changes controller state; both are about
  believing the answer.
- Do not treat "the read succeeded and returned non-zero" as evidence a register
  exists. It is not.
- Prefer whole-block reads at documented base addresses over exploratory offsets.
- Read each block in **one** request. If your client chunks long reads, make
  sure a chunk boundary cannot land inside a block you care about.
- If crewbox ever displays a value read from an address this repository has not
  marked as verified, poison-test it first or label it unverified.

---

## The survey: one call, both families

[`../src/novasun/survey.py`](../src/novasun/survey.py) is the read-only view of a
whole network in one pass — discovery, identification and status, in a stable
serialised shape.

```bash
novasun survey --json                 # broadcast probe, then read-only status
novasun survey 10.0.0.20 --no-probe   # transmit no broadcast; named hosts only
```

```python
from novasun.survey import survey_network
result = survey_network(allow_probe=True)
payload = result.to_dict()            # JSON-serialisable, versioned
```

Transmission is explicit per call:

| Setting | What it sends |
|---|---|
| `allow_probe=False`, explicit `hosts` | no broadcast; HTTP GETs to those hosts only |
| `allow_probe=True` (default) | the UDP discovery broadcast, then HTTP GETs |
| `allow_register_bus=True` | additionally opens a TCP 5200 control session on non-COEX models |

**`allow_register_bus` is off by default and should stay off for crewbox.** That
session may be exclusive, and taking it from NovaLCT mid-show is the one thing a
monitoring tool must not do. A test asserts that with the default, a register-bus
device receives *no frames at all*.

### Coverage is reported, not assumed

`monitoring_available` is `"http"`, `"register-bus"`, `"snmp-if-enabled"` or
`"none"`, so a pane can show "not available" rather than a misleading zero. A
VX4S surveyed without the register-bus opt-in comes back unreachable with the
reason in `errors` — that is the correct answer for that model, not a failure.

### Serialised shape

`schema_version` is `1`. **Check it and refuse a version you do not
understand** rather than mis-reading fields; it will be bumped on any
incompatible change.

```json
{
  "schema_version": 1,
  "timestamp": 1786530453.2,
  "probed": false,
  "devices": [{
    "address": "10.0.0.20",
    "reachable": true,
    "family": "coex",
    "model": "MX40 Pro",
    "model_id": null,
    "name": "Main wall controller",
    "serial": "…",
    "control_path": "http",
    "ethernet_ports": 4,
    "fibre_ports": 0,
    "inputs": [{"label": "HDMI", "type": "HDMI", "switchable": true}],
    "monitoring_available": "http",
    "discovered_by": "discovery",
    "status": {
      "display_mode": 0,
      "cabinets_total": 8,
      "cabinets_online": 8,
      "cabinets_offline": [],
      "hottest_cabinet": {"id": "…", "temperature": 31.0},
      "signal_present": ["HDMI 1", "12G-SDI"],
      "screens": 1,
      "healthy": true
    },
    "errors": []
  }]
}
```

`status` is `null` when no read-only interface exists. `errors` carries
per-endpoint failures without failing the survey — an endpoint the firmware does
not implement is normal, not an outage.

Field names inside `status` are **this repository's** contract and stable under
`schema_version`. Field names *inside the raw COEX payloads* are NovaStar's and
remain provisional until confirmed against firmware; `survey` exists partly to
insulate consumers from that.

---

---

## History and alerts

The application keeps bounded per-device series (temperature, cabinets online,
reachability) and raises alerts from them. A consumer that wants the same
behaviour rather than the same code can take the rules, which are the part worth
copying:

* **Dwell before declaring an outage.** A device must miss several consecutive
  polls, because one dropped poll on a busy network is not a failure. Default 2.
* **Hysteresis on thresholds.** Alerts clear at a lower value than they fire
  (default: warn at 45 °C, clear at 42 °C). Equal thresholds make a reading
  sitting on the line flap, which trains operators to ignore the pane.
* **Acknowledgement silences without dismissing.** An acknowledged alert drops
  out of "worst severity" but stays listed until the condition actually clears,
  and an escalation revokes the acknowledgement.
* **Clearing is an event.** Without "came back at 19:44", a log of alerts reads
  as permanently on fire and stops being read.

These are in `novasun.app.history`, which is pure data structures with no I/O:
feed it device-state dicts and it returns events. It needs no connection of its
own, so it is usable from a read-only consumer that polls by other means.

## Summary for crewbox

| Question | Answer |
|---|---|
| Passive inventory | **Settled: no, on three independent counts.** Replies are **unicast to the requester** (OBSERVED, L2 and L3); the **MX40 never announces itself** (OBSERVED, 30 min); and **VMP does not probe on a timer** (OBSERVED, 30 min with VMP running and nobody searching). A passive listener on a VMP-operated show network hears *nothing at all* — not even that a control app exists. An inventory needs a port mirror, a tap, or co-location with the control app. Caveat: broadcast filtering on the switch was not excluded by a positive control |
| Discovery destination | Send the **subnet broadcast**. The multicast group `224.224.125.119` went unanswered on a UHD Jr despite egressing correctly (OBSERVED) — do not rely on it |
| `rpProMI:` payload | **OBSERVED on one unit:** 8-byte ASCII tail, `App,0161`. It carries **no model ID and no device name** — the earlier "appears to carry model and name" guess was wrong as well as unevidenced. Identify over the register bus, not discovery |
| Trusting a register read | **Two OBSERVED traps** (§5): unimplemented addresses echo the previous response instead of erroring, and reads snap to field boundaries. Poison-test anything unverified |
| Polling 8001 with VMP attached | **One burst of eight GETs is OBSERVED safe** — 0.1 s, no `Busying`, no effect on a live show. Sustained cadence still unverified: use the read-only client, 10–30 s, back off on code 5 |
| Monitoring over GET | **Rich over HTTP, field names now OBSERVED** (§4): per-card temperature, voltage, link state and error bits; main-board temperature and voltage; fan rpm; per-input signal via `sourceStatus`. SNMP was **off** on the unit seen. **Nothing** on VX4S / UHD Jr without a control session |
| Consuming it | `survey_network()` / `novasun survey --json`, `schema_version` 1. Leave `allow_register_bus` off |

**Status of the first-day list.** Capturing an `rpProMI:` reply is **done** —
see §2 — and so is the unicast question, which turned out to need a packet
capture rather than a second host. Checking **whether SNMP is enabled** is still outstanding
and still the highest-value item for crewbox: if it is on, most of the
monitoring pane is already available through an interface designed for exactly
this. The bench unit so far is a UHD Jr, which has no SNMP and no HTTP API, so
that question needs COEX hardware to answer.

Added to the list by §5: **do not build any register map from an unguarded
sweep.** That applies to crewbox as much as to this repository.
