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

Most of this document was written with no NovaStar hardware available. Three
units have since been seen, and the facts they settled are marked **OBSERVED**
with the unit named:

- **NovaPro UHD Jr** (model ID `0x6205`, firmware reporting `App,0161`), on the
  bench from 2026-08-26. Every OBSERVED claim from it was reproduced across a
  power cycle. Scope: one processor, one model; the first day's facts were
  settled with no receiving cards attached, later ones with 30.
- **MX40 Pro**, on a live-show network, 2026-09-11: listened to passively, then
  read over HTTP in three eight-GET bursts (two mid-show, one after it) and
  polled at 1 Hz for ten minutes after the show. Its firmware version is
  **UNKNOWN** — nothing read over the API carries one, and nobody wrote it down.
- **MX30**, on a show network after the show, 2026-09-26, firmware **v1.5.1 as
  reported by the operator** (not read over the API — no payload read carries a
  controller firmware string). Read-only throughout: two ICMP pings, HTTP GETs
  on 8001 (two eight-endpoint snapshots, ten further GETs, six `curl -i`, about
  twenty-four from `survey`/`watch`/`identify` whose outcomes were not kept, and
  900 from a five-minute 1 Hz poll), two `snmpget` attempts, eight `rqProMI:`
  probes. No TCP 5200, no PUT or POST. Whether VMP was still attached is
  **UNKNOWN**.

An OBSERVED fact here is a fact about the unit named, not yet about the fleet.
**Every MX30 statement below is scoped to that one unit, that firmware and that
afternoon (14:44Z–14:57Z)**; where the MX30 differs from the MX40 Pro, the
earlier statement is kept and scoped rather than withdrawn, because both are
observations. Where the two are compared, "the MX40 record" means this
document plus the simulator's MX40-like shape in `coexsim.py`, not the reduced
fixture — see the note on that fixture in §4.

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

**OBSERVED again, 2026-09-26:** the second COEX unit read, an MX30 on v1.5.1,
returned the same `{"state": false}` in both snapshots. Two of two COEX units
seen had SNMP off. The OID map is still unexercised on any hardware.

---

## 1. What can be learned with zero transmission?

**Do controllers announce themselves unsolicited?** **No — OBSERVED.** A
passive listener on UDP 3800 sat for thirty minutes on a live-show network with
an **MX40** on the same segment (L2 adjacency confirmed from the ARP table) and
heard nothing from it. No document describes unsolicited announcement, no
published implementation listens for one, and now a controller has been watched
and did not make one. Scope: one model, one thirty-minute window.

**Second unit, same silence — OBSERVED, 2026-09-26.** A receive-only socket
bound `0.0.0.0:3800` (`passive.py`, no send path, every datagram appended
unfiltered) heard **zero datagrams of any kind in 600.0 s** on a segment with
an MX30 and its 72-cabinet wall, after the show. The scope is narrower than it
looks. Unicast to the host and the subnet broadcast, both on 3800, are
covered for certain: a socket bound the same way received the host's own
subnet-broadcast probes when they were sent later — kernel loopback, which
rules out a mis-bound listener, not a filtering switch. **Multicast coverage
is UNKNOWN**: the listener joins `224.224.125.119` on `INADDR_ANY`, the host
was multi-homed (a second interface on another network), and which interface
held the membership was not recorded. Method note for the next listen: bind,
join and probe on the wall interface explicitly, and record the routing table.

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

**The MX40 Pro does not answer the discovery probe at all — OBSERVED,
2026-09-11, after the show.** Eight `rqProMI:` probes from the host that reads
its HTTP API without difficulty — two each to its unicast address, the subnet
broadcast, the multicast group (joined on the right interface) and the limited
broadcast — over six seconds of listening drew **no reply**. The UHD Jr answers
the same probe within milliseconds. So the NovaLCT-style discovery this
repository and crewbox both implement **cannot find a COEX controller**, at
least not this model on this firmware; how VMP finds one is **UNKNOWN**, and a
consumer that needs to discover MX-class hardware must be told the address or
find it some other way (the ARP table located this one, by NovaStar's
`54:b5:6c` OUI). Scope: one unit, one firmware, one attempt of eight probes.

**An MX30 on v1.5.1 answered none of them either — a second COEX model,
2026-09-26, after the show.** The same eight probes — two each to its unicast
address, the subnet broadcast, the multicast group (`IP_MULTICAST_IF` pinned to
the wall interface) and the limited broadcast, the last sent at 1.8 s — were
followed by about six seconds of listening on a socket bound `0.0.0.0:3800`.
All eight left without a socket error. Nothing arrived except the host's own
probes looped back — eight of them, and **four carried the address of a second
interface**, so the host was multi-homed and at least one probe class egressed
away from the wall (the limited broadcast most likely followed the default
route; the routing table was not recorded). The unicast and subnet-broadcast
probes are the ones that verifiably reached the segment, and a reply to either
would have been heard. No other host on the segment answered either.
**REASONED**, from one trial and one six-second window with VMP attachment
UNKNOWN: the MX30 does not answer NovaLCT-style discovery, consistent with the
MX40 Pro. COEX hardware still has to be given its address.

**A second finding from the UHD Jr capture: that device ignores the multicast
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

**Yes for a single burst of GETs mid-show, and yes for ten minutes at 1 Hz on
the controller side — both OBSERVED on an MX40 Pro, the second repeated for
five minutes on an MX30. Whether a sustained cadence disturbs an operator
mid-cue is still REASONED: VMP's attachment was UNKNOWN on both units.**

On 2026-09-11 a read-only client issued the eight snapshot GETs — device,
screens, cabinets, inputs, presets, monitor/info, audio, snmpstate — against an
**MX40 Pro** that VMP was driving through a live show. All eight were answered in
0.1 s total, about 680 KB, with no `Busying` and no visible effect on the show.
Two answered HTTP 404 (`device`, `audio`), which is a firmware fact, not
contention — and a fact about *that* firmware: on the MX30 the same two paths
behave differently (§4).

### Ten minutes at 1 Hz — OBSERVED, controller side

Later the same day, after the show had ended and with the wall still lit, the
read-only client polled the same unit at 1 Hz for ten minutes: three GETs per
tick — `monitor/info` (the heaviest endpoint, 265 KB for 288 cabinets),
`input/sources` and `backup` — with a 4 s timeout. The back-off never fired.

| | |
|---|---|
| Ticks | 597 in 600 s; no tick overran its second |
| Requests | 1,791 — **0 errors, 0 `Busying`, 0 timeouts** |
| `monitor/info` latency | p50 48 ms, p95 58 ms, p99 64 ms, max 75 ms |
| `input/sources` latency | p50 6 ms, max 10 ms |
| `backup` latency | p50 4 ms, max 13 ms |
| Drift | `monitor/info` p50 over the first 100 ticks 48 ms; over the last 100, 51 ms |

The readings behaved throughout: hottest card 36 °C on every tick, main board
36–37 °C, each fan within 25 rpm of where it started, and the input signal
pattern and the cabinet count identical on all 597 ticks. `runtime` advanced by
exactly 600 s in ten steps of 60, at intervals of 59.3–60.5 s of wall time — the
60 s granularity inferred from two samples earlier in the day (§4) is now
observed across ten consecutive steps.

What this settles, and what it does not. The controller sustains 1 Hz reads of
its heaviest endpoint for ten minutes with no errors, no contention signal and
no latency growth — twenty times the cadence the policy below recommends. It
does not settle the test as originally specified below: VMP was not being
operated, and whether it was still attached to the controller after the show is
UNKNOWN. So "1 Hz does not degrade the controller" is OBSERVED; "1 Hz does not
disturb an operator mid-cue" remains REASONED, from the same four arguments as
before, with the controller-side half of the question now removed.

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

What is not established: whether a GET can slow VMP's own operations, and
whether any GET has side effects despite the verb. Neither is documented. The
rate the controller tolerates is now bounded from below rather than unknown: at
least three GETs a second, one of them the 265 KB `monitor/info`, for ten
minutes without complaint on the MX40 Pro — and, below, five minutes of the
same on an MX30.

### Five minutes at 1 Hz on an MX30 — OBSERVED, controller side, second unit

Repeated on 2026-09-26 against the MX30 (v1.5.1, operator-reported), after the
show with the wall still lit: the same three GETs per tick — `monitor/info`,
`input/sources`, `backup` — with the same 4 s timeout, for 300 ticks.

| | |
|---|---|
| Ticks | 300 in 300 s, 14:52:06Z–14:57:05Z; every tick gap exactly 1 s |
| Requests | 900 — **0 errors, 0 `Busying`, 0 timeouts** |
| `monitor/info` latency | p50 10.5 ms, p95 12.7 ms, p99 15.3 ms, max 21.6 ms, min 7.7 ms |
| `input/sources` latency | p50 4.1 ms, max 17.1 ms |
| `backup` latency | p50 2.3 ms, max 7.3 ms |
| Drift | `monitor/info` p50 over the first 100 ticks 10.3 ms; over the last 100, 10.5 ms |
| Payload sizes | `monitor/info` ≈ 97 KB for 72 cabinets, `input/sources` ≈ 9.8 KB, `backup` 64 B — **compact re-serialisations of the parsed JSON, not wire sizes**, which were not recorded |

The readings behaved as on the MX40: 72 reporting cards on every tick, hottest
card 46 °C and main board 32 °C on every tick, each of the three fans within a
39, 29 and 55 rpm span (at most 20, 16 and 32 rpm from its mean), the signal
set constant. `runtime` stepped +60 five times, at three seconds past each
minute — the 60 s granularity now seen on a second unit.

Two limits on the numbers. **"No tick overran" is REASONED**, from the 1 s tick
spacing and per-tick totals under 31 ms, not recorded: the polling script wrote
its overrun flag after the record it belonged to, so the file could never have
shown one. And these were 900 of the 932 GETs with recorded outcomes on the
unit that afternoon; none returned an HTTP error status, a non-zero `code`, a
`Busying` or a timeout — though for eleven of the 932 that statement is
vacuous, because they carried no envelope at all (the empty-200 replies in §4).
About twenty-four further GETs from `survey`, `watch` and `identify` were sent
but their outcomes were not kept.

**VMP attachment is UNKNOWN for this run too.** So the controller-side result
now stands on two units and two firmwares; the operator-side question is
exactly where it was.

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
  `snapshot.errors` and the rest of the poll completes — **when the firmware
  says so.** An MX40 Pro says so with HTTP 404. An MX30 on v1.5.1 answers an
  absent path with an empty HTTP 200, which at the time of the MX30 contact this
  client turned into `{}` with no error recorded (§4). A consumer must test for
  the missing envelope itself rather than rely on the error channel.

A suggested cadence: **status every 10–30 s, topology every few minutes.** The
controller is now known to tolerate 1 Hz (above), so this margin is for the
operator's software, not for the controller — and monitoring rarely needs
faster.

### Settling the rest

The controller half is done (above), on two units. The VMP half needs a person
at the wall:
have VMP connected and doing something visible — a preset recall, a brightness
ramp — and run `CoexMonitor` at 1 Hz alongside. Watch for VMP stuttering,
`Busying` responses, or a dropped VMP connection. If none appear in ten minutes
at 1 Hz, polling at 0.05 Hz is not going to be the thing that breaks a show.

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

**Update, 2026-09-26 — a second COEX unit, an MX30 on firmware v1.5.1
(operator-reported), read after a show.** Every "On an MX40 Pro" statement in
the table below stands as observed on that unit. The MX30 gets its own table
and its own section after the MX40 material, because it differs in ways a
consumer has to handle — starting with how it says an endpoint is absent.

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
| `GET /api/v1/device/screen/displaymode` | **HTTP 404** — a third absent documented endpoint; display mode is not readable over HTTP on this firmware | OBSERVED (post-show) |
| `GET /api/v1/device/backup` | `{"master": "", "backup": "", "masterName": "", "backupName": ""}` — present, empty on a unit with no redundancy configured | OBSERVED |
| `GET /api/v1/device/multifunc-card/detailinfo` | `[]` | OBSERVED |
| `GET /api/v1/device/hw/mode` | `{"mode": 3}` — the manual documents this as a setter taking `0` send-only / `1` all-in-one; `3` is neither, meaning UNKNOWN | OBSERVED value, UNKNOWN meaning |

Three consequences for a consumer. **Cabinet health lives on the receiving card,
not the cabinet:** on the MX40 Pro `monitor/info.cabinets[].cabinetID` is always
0 and its top-level readings are 0; the join to `/device/cabinet` is
`rvCards[].cabinetID` = `id` (288 of 288). The MX30 populates `cabinetID` and
drops the top-level readings altogether (below), but the same join holds there
(72 of 72) — **so key on `rvCards[].cabinetID` and read health from `rvCards[]`
on both.** **There is no online flag** — a cabinet present in `monitor/info`
with a reporting card is the working definition of online (REASONED), and its
absence is how "offline" is expressed. **Every reading is an object,**
`{"name", "nameEn", "status", "value"}`, never a bare number, on the MX40 Pro; a
reader that assumed otherwise crashed the application's refresh thread on first
contact. The MX30 adds exactly one exception, `rvCards[].signalInterruptCount`,
a bare integer — a reader that unwraps `.value` on every `rvCards[]` field fails
on it.

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
all. `diff_snapshots` now aligns by identity for exactly this reason. The MX30
reorders the same way — all 72 cabinets changed position between two reads
seven minutes apart, `screenSourceStatus[]` rotated, and `/device/cabinet` did
not move — so this is two firmwares' behaviour, not one's.

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

**A machine-readable copy of these shapes is in
[`tests/fixtures/mx40_like_api.json`](../tests/fixtures/mx40_like_api.json)** —
one JSON object keyed by endpoint path, real structure, synthetic values, three
cabinets standing in for 288, with the endpoints that answered HTTP 404 marked
as such. A consumer in any language can serve it from a fake and see what its
own parser makes of a real MX40 Pro before ever meeting one. It is generated
from this repository's test fixtures and a test asserts the two agree.
[`tests/fixtures/crewbox_harness.mts`](../tests/fixtures/crewbox_harness.mts)
does exactly that for crewbox's own `CoexReader` — imports it, serves the
fixture, polls twice, prints the grade — and it is how the false all-clear
described above was measured rather than predicted.

**That fixture is a reduced stand-in, and lossy in ways that matter when
comparing against it.** It carries `rvCardsRuntime: []` where the table above
records 289 populated values, one `errorBit` entry where `coexsim.py`'s
MX40-like shape emits two, one controller port where the simulator emits two,
and no `rvCardInfo` where this document names one. The raw MX40 payload was not
retained, so **where the fixture and the simulator disagree, the MX40's real
value is UNKNOWN.** Comparisons in this document are therefore made against
"the MX40 record" — this document plus the simulator — never against the
fixture alone, and a difference that shows only against the fixture is a
fixture gap, not a firmware difference. Do not "repair" the fixture from
another model's data; the MX30 shapes are in a companion fixture of their own,
[`tests/fixtures/mx30_like_api.json`](../tests/fixtures/mx30_like_api.json),
built the same way, with an explicit marker for the empty-200 replies described
below.

**What crewbox's reader makes of the MX30 shapes — OBSERVED-in-harness,
2026-09-26.** Measured with
[`tests/fixtures/crewbox_harness.mts`](../tests/fixtures/crewbox_harness.mts)
serving [`tests/fixtures/mx30_like_api.json`](../tests/fixtures/mx30_like_api.json)
to crewbox's `CoexReader` (crewbox at `7c8cf6a`, unmodified), **against the
fixture, not against hardware**; the fake fetch answers an
`{"__http_status__": 200, "__empty_body__": true}` entry with `ok`, 200 and a
`json()` that rejects with `SyntaxError: Unexpected end of JSON input`, which is
what this Node's own `Response.json()` does on an empty body (checked on Node
v26.8.1). The reader requested the same eight paths as on the MX40 record, all
GET, and graded the wall **`ok`, "3 cabinets, 44°C"** — the hottest receiving
card, joined by `rvCards[].cabinetID` to `/device/cabinet.id` 3 of 3, the ids
stable across a reordered `monitor/info` (their order was not), all three
`onlineAssumed` and carrying a temperature. It did not fail on the nested
`cabinet{}` object, the populated `cabinetID` or the bare-integer
`signalInterruptCount`. `reportedName` is the fixture's label and `model`,
`serial` and `firmware` are undefined — no model is derived from the name.
`temperature` 32 is the main board; `fanRpm` 3776 is the first of the three
fans served; `brightness` 50, `snmpEnabled` false, `isBackup` false,
`displayMode` undefined. Inputs: six, the two with `sourceStatus` 1 (HDMI 2.0,
id 512, and the internal source, id 25856) `present`, the other four
`not-connected`, no `connector` on any — so the internal generator is shown as
a present signal (see the inputs note below). **The empty-200 prediction below
held exactly:** poll 1 errors `/api/v1/device no answer` and
`/api/v1/device/screen/displaymode no answer`, `answered` 6; poll 2 only the
second, `answered` 3; poll 21, after the topology sweeps at 11 and 21, both
again; `absent` stayed `undefined` throughout, so the two paths are asked on
every poll they are due and reported as "no answer" each time. Against the
MX40 fixture, unchanged from the earlier run: the same two paths error
`answered 404`, `absent` lists both after poll 21, poll 21 errors `[]`; 80
requests over 21 polls against 96 on the MX30 fixture, because the latched
paths stop being asked. What the harness does not show: whether crewbox reads
voltage from both `rvCards[]` and the nested `cabinet{}` (it prints no
voltage), and whether its UI could skip a proxy on the CORS headers (no
browser in the harness). Nothing under `~/crewbox` was modified.

`MonitorSnapshot` folds these into `healthy`, `offline_cabinets`, `hottest`,
`signal_present` and `display_mode`; `CabinetHealth` now carries `voltage` and
`link_ok` as well. `interpret_monitor_info()` is the one, total interpreter for
the monitoring payload.

### The same surface on an MX30, firmware v1.5.1 — OBSERVED, 2026-09-26

Scope for everything in this section: one MX30, firmware v1.5.1 as reported by
the operator, read after a show between 14:44Z and 14:57Z with VMP attachment
UNKNOWN, through the read-only client (two eight-endpoint snapshots seven
minutes apart, ten further GETs, six `curl -i`) and a 300-tick poll. Nothing
here generalises to other MX30s or other firmware until a second unit is read.

**Absent endpoints answer differently per firmware — the biggest correction.**
On the MX40 Pro, an absent documented endpoint answered **HTTP 404** (`device`,
`audio`, `displaymode`, above; a bogus path was never tried on it). On the MX30,
`curl -i` on three paths that cannot exist (`/api/v1/novasun-probe-no-such-path`,
`/api/v2/nope`, `/novasun-nope`) and on two documented ones (`/api/v1/device`,
`/api/v1/device/screen/displaymode`) drew the same reply every time:
**`HTTP/1.1 200 OK`, `Content-Length: 0`, no `Content-Type`, zero body bytes** —
against a control, `/api/v1/device/snmpstate` in the same transcript, which
carried `Content-Type: application/json`, `Content-Length: 53` and a proper
`{"code":0,"data":{...},"message":"Success"}` envelope. Both kinds answered in
about 2 ms, so **status, latency, and every header but the two named do not
distinguish an absent path from a real one; only the body does.** Three more
documented paths — `/api/v1/screen/cabinets`, `/api/v1/screen/properties`,
`/api/v1/screen/displayeffect` — came back as `{}` through the read-only client
in 2.0–2.5 ms, consistent with the same empty 200 but **not distinguishable by
that client** from a genuine `{"code":0,"data":{}}`, because it returns `{}` for
both; no raw envelope was captured for those three. All five are
**absent-or-empty, UNKNOWN which**; the empty-body mechanism is OBSERVED on the
first two. The same firmware does say "nothing" with an envelope where it means
it — `/multifunc-card/detailinfo` returned `[]`, which can only have come from a
JSON body.

What a consumer must do: treat an empty body — `Content-Length: 0`, or a parsed
reply with no `code` key — as **absent**, never as present-and-empty, and never
take "answered HTTP 200" as "exists". Neither reader this project knows of did
so at the time of the contact:

- novasun's `CoexClient.request` did `json.loads(body or b"{}")` and returned
  `{}` when no `code` key followed, so `snapshot()` recorded `device: {}` with
  no error (OBSERVED; reproduced against a stub on 127.0.0.1 serving
  `Content-Length: 0`). A defect in this repository, not a fact about the
  hardware.
- crewbox's reader calls `res.json()` once `res.ok`; on a 200 with an empty
  body Node's `fetch().json()` throws `SyntaxError: Unexpected end of JSON
  input` (confirmed against the same stub on Node v26.8.1), and its catch maps
  any non-abort error to `'<path> no answer'` with no status. Its `notFound`
  count requires a 404, so on this firmware it reports "no answer" for
  `/api/v1/device` on every topology sweep and for
  `/api/v1/device/screen/displaymode` on every poll, for as long as it runs,
  and never lists either as absent — **REASONED from its code, then OBSERVED
  in the harness against the MX30 fixture through 21 polls (above); not yet
  against hardware.** Other endpoints still answer, so the processor is not
  counted missing (`answered` 6 on a topology poll, 3 on a status poll).

**Identity: the name is a label, and the model is not readable.** On the MX30
`monitor/info.name` is a single plain alphabetic word — no `MX`, `CX` or `KU`,
no digits — identical in both snapshots and equal to no other string in the
payload (not a screen, group or preset name). It is not reproduced here; it is
the operator's. **The model cannot be read from `name` — OBSERVED on the MX30,
whose name carried none; as a rule for the fleet, REASONED** — one unit shows
`MX40 Pro_<digits>`, the other a plain word.
That the word is an operator-set label is **REASONED**, not established: the
API has an OFFICIAL `PUT /api/v1/device/hw/customname` setter, which makes a
label possible, but nobody read the unit's settings and a firmware default word
is not excluded; that the MX40 Pro's form was a factory default is likewise one
sample. **No field read over HTTP on either unit gives the controller model or
firmware** (UNKNOWN over the API): a key search of every MX30 payload for
model, firmware, version, serial, product, hardware, software or build finds
version strings only on the receiving cards (`rvCardInfo.firmware`,
`mcuFirmWare`, `ncpVersion`, `cabinetFileParam.version`), a
`screens[0].inputPort.FirmwareVersion{}` whose every field is empty, and one
model-like *number* — `modelId` 5138 (`0x1412`) on every
`/api/v1/device/input` port entry, `screens[0].inputPort.ModelId` and
`canvases[0].outputCardModeId`. It appears in none of this repository's model
tables, and **what it identifies — controller, input block, output card, mode —
is UNKNOWN**; do not present it as the controller model. What *is* available to
tell the units apart: the input complement (six sources — two 3G-SDI, one DP
1.1, one HDMI 1.4, one HDMI 2.0, one internal generator) and the output
enumeration (10 type-0 plus 2 type-1 outputs in `outputStatus[]`), both
consistent with an MX30 (**REASONED**; the model name itself is
operator-reported). One consequence for consumers of `survey --json`: at the
time of the contact `survey`, `watch --once` and `identify` all reported this
label as the `model`, because an unrecognised COEX name fell through to a
profile whose name is the input string (OBSERVED, reproduced against a stub).
Treat `model` from a COEX unit as unestablished until that fix is in the
version you run.

| Endpoint | On an MX30, v1.5.1 (operator-reported), 2026-09-26 | Confidence |
|---|---|---|
| `GET /api/v1/device` | **HTTP 200, empty body** — absent-or-empty, not 404 | OBSERVED (`curl -i`) |
| `GET /api/v1/device/monitor/info` | Same skeleton as the MX40 Pro, with the differences tabled below: populated `cabinets[].cabinetID`, a nested `cabinets[].cabinet{}` in place of top-level readings, `rvCards[].phyTemperature` and `.signalInterruptCount`, `outputStatus[].type` and `.linkStatus`, `screenSourceStatus[].groupID` and `.linkStatus`, three fans, two controller ports, three new top-level keys. ≈ 97 KB compact for 72 cabinets | OBSERVED |
| `GET /api/v1/device/cabinet` | 72 entries, **34 keys** each (the MX40-like simulator already carries 32 of them); `id` joins `rvCards[].cabinetID` 72/72; descriptive fields unset on this wall; `voltage` unusable (below). ≈ 90 KB compact | OBSERVED |
| `GET /api/v1/screen` | `screens[]` as on the MX40 Pro **plus** `canvases[]` with per-cabinet positions, `layersInWorkingMode[]` naming each layer's source, `canvasInWorkingMode[]`, `pageInfos[]`, an `inputPort{}` block with live signal detail; new keys `cryptoCabinetNum`, `monitorSlotId`. Byte-identical across the two snapshots | OBSERVED |
| `GET /api/v1/device/input/sources` | six entries including an internal generator; 38 keys the MX40 fixture lacks (`defaultEDID{}`, `hdrList`, `gamut`, `dynamicRange`, `bitDepth`, `fiberPortLinkStatus`, `isSupport*`, `metaData{}`, `monitorSlotId`, …) | OBSERVED |
| `GET /api/v1/preset` | same keys as the MX40 Pro; one screen, two presets, `state` false on both | OBSERVED |
| `GET /api/v1/device/snmpstate` | `{"state": false}` — SNMP off on the second unit too | OBSERVED |
| `GET /api/v1/device/audio` | **present**: `{"enable": false, "source": 65535, "sourceName": ""}` (HTTP 404 on the MX40 Pro) | OBSERVED |
| `GET /api/v1/device/screen/displaymode` | **HTTP 200, empty body** — absent-or-empty (HTTP 404 on the MX40 Pro) | OBSERVED (`curl -i`) |
| `GET /api/v1/device/backup` | all four strings empty, as on the MX40 Pro | OBSERVED |
| `GET /api/v1/device/multifunc-card/detailinfo` | `[]` — a genuine JSON body, so this firmware *can* say "nothing" with an envelope | OBSERVED |
| `GET /api/v1/device/hw/mode` | `{"mode": 3}` — second unit, second model, same value; meaning still UNKNOWN | OBSERVED value, UNKNOWN meaning |
| `GET /api/v1/screen/cabinet/count` | `{"list": [{"ScreenID": …, "CabinetCount": 72, "CabinetCountInBlackList": 0}]}` — first time exercised by this project | OBSERVED |
| `GET /api/v1/device/input` | `inputPortConfig[]` (six entries, each with `modelId` 5138 and a per-port `hardwareID`) and `testPattern{mode, parameters, txColorSpaceType, txHDRType}`, ≈ 7.6 KB — first time exercised | OBSERVED |
| `GET /api/v1/screen/cabinets`, `…/screen/properties`, `…/screen/displayeffect` | `{}` through the read-only client in 2.0–2.5 ms — consistent with an empty 200, not distinguishable by that client from an empty envelope | absent-or-empty, UNKNOWN which |
| any unknown path | **HTTP 200, `Content-Length: 0`, no `Content-Type`** | OBSERVED (`curl -i`, three paths) |

**`monitor/info` on the MX30, against the MX40 record.** The skeleton is the
same; these are the differences and near-differences, each OBSERVED on the MX30
across 72 of 72 cabinets and both snapshots unless stated:

| Field | MX30, v1.5.1 | MX40 record | Note |
|---|---|---|---|
| `cabinets[].cabinetID`, `.rvCardID` | populated: non-zero, distinct, equal to `rvCards[0].cabinetID` and to each other, 72/72; `canvasID` 2048 | `cabinetID` always 0 (OBSERVED); `canvasID` 0 | A genuine difference. Join on `rvCards[].cabinetID` regardless |
| `cabinets[].temperature`, `.voltage` (top level) | **absent** | present, 0 | |
| `cabinets[].cabinet{}` | nested object: `cabinetID` 0, `temperature`/`humidity`/`smoke` zeroed objects, `power` null, `voltage` **a live mirror of `rvCards[0].voltage`** — equal as whole objects 72/72 in both snapshots, and the one voltage move appeared in both | not in the record | Adds nothing. **Read voltage from `rvCards[]` only — a keyed diff over both paths double-counts** |
| `rvCards[].phyTemperature` | `{phy1, phy2}` sensor objects, 0 | not in the record | |
| `rvCards[].signalInterruptCount` | **bare integer**, 0 | not in the record | The one reading that is not a `{name, nameEn, status, value}` object |
| `rvCards[].errorBit[]` | two entries; `[0] = {status 1, type 0, value V}` with V one value per output port (190, 189, 187 on the three populated ports); `[1] = {status 0, type 1, value 0}` | value 65535 per the record; the simulator already emits two entries, the fixture one | Meaning of V UNKNOWN; two entries is not new |
| top-level keys | adds `accessoryMonitorInfo{multifunctionCardStatus: [], transmitterStatus: []}`, `imbLinkStatus{linkStatus: false, status: 0}`, `inputFiberStatus: null`; `backupStatus` gains `minNormalValue`, `maxNormalValue` | none of the three in fixture or simulator | |
| `outputStatus[]` | 33 entries with `type` and `linkStatus`: type 0 = `outputID` 2048–2057 (10), type 5 = 2058–2077 (20), type 1 = 2078–2079 (2), one type 3 with `outputCardID` 0; `linkStatus` true on 2048–2052 only; cabinets on 2048, 2050 and 2052 (24 each) with `rvCards[].netPortIndex` = `outPutID` 72/72; the only non-zero `status` is 2, on 2053 | `linkStatus` not in the record | **REASONED, UNKNOWN until an attended test:** type 0 = the 10 RJ45 ports, type 1 = the 2 OPT ports, type 5 = 20 fibre-carried channels, type 3 = ?; 2049 and 2051 = loop or backup returns. `status` code meanings UNKNOWN |
| `controllerPortMonitorInfos[]` | two entries: `{0, status 0}`, `{1, status 2}` | **count not recorded** — fixture one, simulator two | UNKNOWN how many the MX40 returned; status meaning UNKNOWN |
| `fanInfos[]` | three: "Chassis Fan 1" (fanType 1, ~3776 rpm), "FPGA Fan" (fanType 15, ~2783), "Chassis Fan 2" (fanType 2, ~3756); `fanNameEn` populated | one fan, "chassis Fan", fanType 0 | Read the array; never assume one fan |
| `screenSourceStatus[]` | six entries (one per input, the internal source included) with `groupID` = `inputs[].groupId` 6/6 and `linkStatus`, true exactly on the two inputs with `sourceStatus` 1; `inputCardID` 0 | `groupID`, `linkStatus` not in the fixture; `inputCardID` 1 | |
| `rvCardsRuntime[]` | 72 entries, `cabinetID` joins `rvCards[]` 72/72; `totalRuntime` 71 distinct values, all multiples of 60; `runtime` **identical on all 72 and unchanged across seven minutes** — not a counter on this firmware, meaning UNKNOWN. `rvCards[].runtime` and `.totalRuntime` are 0 | the same: per-card runtimes live in `rvCardsRuntime[]` (289 values, above); the fixture's `[]` is a fixture gap | Not a difference |
| `mainBoardTemperature`, `mainBoardVoltage`; card readings | 32 °C, 11.56 V; cards 41–46 °C, 4.1–4.4 V, after the show | main board 42 °C mid-show, 37 °C idle | The same receiving-card model, `A5sPlus`, on both walls per the repository record |

What a consumer should key on so that both firmwares parse: join `monitor/info`
to `/device/cabinet` on `rvCards[].cabinetID` = `id` (288/288 and 72/72); take
temperature, voltage, link and error bits from `rvCards[]` and ignore both
`cabinets[]`'s top-level readings and its nested `cabinet{}`; assume nothing
about `cabinets[].cabinetID` (0 on one firmware, populated on the other); count
fans, controller ports, outputs and `errorBit` entries from their arrays; unwrap
`.value` only on fields that are objects. Both of this repository's readers
already do: run offline against the MX30 payload, `interpret_monitor_info`
reported 72 cabinets, 72 online, hottest 46 °C, main board 32 °C and 11.56 V,
72 links ok, and `diff_snapshots` keyed the cabinets by the populated
`cabinetID` with zero identity churn (OBSERVED, offline).

**`/device/cabinet` on the MX30.** 72 entries, the whole list identical in
every value and in order between the two snapshots; `id` joins
`rvCards[].cabinetID` 72/72, as on the MX40 Pro. Each entry carries 34 keys:
the fixture's 18 plus `angle`, `bunchesIndex`, `cabType`,
`cabinetFileParam{cabinetName, cardModel, issue, manufactureName, status,
version}`, `clientOrderNo`, `customGamma`, `familyName`, `manufacture`,
`moduleSize{moduleCol, moduleRow, overwrite}`, `ncpFileName`, `ncpVersion`,
`pointSpacing`, a twelve-field `rvCardInfo{}`, `supportType`, `vsFreMax`,
`weight`. Fourteen of those sixteen are already in the MX40-like simulator with
the same nested key sets, so they are a fixture gap, not a firmware difference;
**only `clientOrderNo` and `ncpFileName` (both `""` here) are in neither fixture
nor simulator, and whether the MX40 sent them is UNKNOWN.**

Three things a pane should know:

- **The descriptive fields are unset on this wall.** All 72: `size` 0x0, `power`
  0, `cabinetFileParam` empty strings / `"unknown"` / `"0.0.0.0"`, `ncpVersion`
  `"0.0.0.0"`, `pointSpacing` `"0.000"`, `moduleSize` 255/255, `weight` 0,
  `cabType`, `familyName` and `manufacture` `""`. So `size` and `power` cannot be
  relied on for a pane. The MX40 record's 500x500 mm and 12 are the fixture's
  synthetic values — do not read them as the MX40 wall's real size.
- **`voltage` is garbage on the first cabinet of each chain.** 5 on 69
  cabinets; 34, 57 and 235 on the three with `index` 0 (one per populated
  port), while the same three cards read 4.3 V on `rvCards[].voltage.value`.
  The discriminator is `index`, not `outputIndex` (0 on all 24 cabinets of a
  port). Meaning UNKNOWN. **Do not display `/device/cabinet.voltage`; use
  `rvCards[]`.** The record's constant 5 is consistent with the MX40.
- **The consistent fields:** `brightness` 0.5 — the 0–1 fraction again —
  `gamma` 2.8 x3, `gain` 43 x3, `colorTemperature` 6500, `resolution` 128x128,
  `rvCardName` `"A5sPlus"`, `rvCardInfo.firmware` `"4.6.6.68"` (= `mcuFirmWare`),
  `grayScale` 14, `scanNumber` 16, `refreshRate` 3850, `moduleResolution` 64x64,
  `moduleCount` 4, `indicatorLightState` true, identical on all 72.
  `rvCardInfo.firmwareRemark` and `mcuFirmWareRemark` are non-empty on this
  wall; they are the show's and are not reproduced.

**A stable per-cabinet address exists**, which `monitor/info`'s reordering makes
worth having: `/device/cabinet.index` is the chain position 0–23 and equals
`monitoring.cabinets[].index` and `rvCards[].cabinetIndex` 72/72;
`outputIndex` = `outputID` − 2048 (0, 2, 4 on the three populated ports);
`(outputID, index)` is unique 72/72; `outputID` = the monitoring `outPutID`
72/72; `canvasID` 2048 on both endpoints. A pane can show "port 2, position 7"
beside the 64-bit id, and both `/device/cabinet` and `rvCardsRuntime[]` keep a
stable order between reads.

**Inputs on the MX30.** Exactly six `input/sources` entries — `(id, type,
groupId)`: (3, 7, 57) and (4, 7, 58) labelled 3G-SDI, (256, 4, 32) DP 1.1,
(768, 2, 18) HDMI 1.4, (512, 3, 25) HDMI 2.0, and (25856, 224, 224) with
`cardId` 101, the internal source. **REASONED, one unit, read off each port's
own `name` string rather than any documented table:** `type` 2 = HDMI 1.4, 3 =
HDMI 2.0, 4 = DP 1.1, 7 = 3G-SDI. **REASONED:** 224 with `cardId` 101 = the
internal generator; 5 = DP 1.2 (from the MX40 record) remains REASONED.

- **`id` is not a connector-type identifier across models** (OBSERVED across
  the two units read): 768 is a DP port per the MX40 record and HDMI 1.4 here;
  512 is HDMI type 3 with `groupId` 25 on both. Key connector type on `type` or
  `name`, never on `id`.
- `sourceStatus` 1 on 512 (`actualResolution` 1920x1080, `actualRefreshRate`
  50, `colorSpace` `"YCbCr 4:4:4"`) and on 25856 (1280x768 at 50), 0 on the
  other four. Every `sourceStatus`-0 input's `actualResolution` and
  `actualRefreshRate` equal its `defaultEDID` exactly (4/4); the two live inputs
  differ from theirs (OBSERVED). That disconnected inputs echo their EDID
  default is the same REASONED reading as on the MX40 Pro, now with a second
  unit's pattern behind it. That 512 was the show input is REASONED — it has
  signal and is the active layer's source (below); nobody watched the wall.
- **The internal source reported `sourceStatus` 1 throughout the ~15 minutes
  observed** (two snapshots, 300 poll ticks). Not "always": that is the window.
  A pane should treat type 224 / `cardId` 101 as a generator, not a connector
  (REASONED), or it will count a signal that no cable carries.
- 38 keys the MX40 fixture lacks (none the other way): `defaultEDID{}`,
  `hdrList` (`[255, 0, 1, 2]` on the two HDMI inputs, null elsewhere), `gamut`,
  `dynamicRange`, `bitDepth`, `fiberPortLinkStatus` (null on all six),
  `isSupport*` flags, min/max width and height, `supportResolution`,
  `supportFrameRate` and `supportColorSpace` strings, `metaData{}` (twelve
  zeroed fields; "HDR infoframe" is REASONED from names such as
  `maxContentLight`), `monitorSlotId`.

**Selected input and wall geometry are readable from `/api/v1/screen` — new
for COEX, with the label split that matters.** The `screens` payload was
byte-identical across the two snapshots seven minutes apart, and was not
polled, so every fact below is one reading of a static wall.

| Fact | Confidence |
|---|---|
| `screens[0].workingMode` = 1; `layersInWorkingMode[]` has two entries (working modes 0 and 1), one layer each | OBSERVED |
| The mode-1 layer has `source` 25 and `sourceSize` 1920x1080; the mode-0 layer `source` 224 and `sourceSize` 1280x768 | OBSERVED |
| Each `sourceSize` equals the referenced input's `actualResolution`; `masterFrameRate` 50 equals the HDMI 2.0 input's `actualRefreshRate` | OBSERVED |
| `screens[0].inputPort.LogicId` = 512, `.GroupId` = 25 — the HDMI 2.0 input's `id` and `groupId` | OBSERVED |
| `layers[].source` is **not** an input `id` (neither 25 nor 224 is one) | OBSERVED |
| `layers[].source` **is** `input/sources[].groupId` | **REASONED, one discriminating data point**: 25 matches only `inputs[4].groupId`, but 224 matches both the `groupId` and the `type` of the internal source, so only one of the two values separates the readings. `inputPort.GroupId` beside `LogicId` is the supporting hint that the firmware calls this concept GroupId |
| The mode-1 layer's source is what the wall was displaying | **REASONED** until an attended switch is watched |
| `inputPort.InputDetailInfo.GroupId` = 49 for the same port | OBSERVED; so "GroupId" is not one concept within the payload — meaning UNKNOWN |
| `inputPort.InputSrcInfo` carries live signal detail `input/sources` does not: `SourceDetInColPixel` 1920, `SourceDetInRowPixel` 1080, `SourceFieldRate` 5000, `SourceHTotal` 2640, `SourceVTotal` 1125, `HdcpState` 1, `ColorSpaceType` 2, `ColorGamut` 2, `InputType` 3, `InputID` 512, `SourceStatus` 1 | OBSERVED values; code meanings UNKNOWN; `5000` = 50.00 Hz in the register bus's x100 encoding is REASONED |

So a COEX pane can now say "this screen is on HDMI 2.0 1" with the REASONED
caveat, where the register-bus hardware below still cannot. Do not present the
two statements as equally established.

Geometry, from `screens[0].canvases` (one entry):

| Fact | Confidence |
|---|---|
| `canvases[0].cabinets[]`: 72 entries, keys exactly `{angle, cabinetID, connectID, lockStatus, outputID, pageID, position, size}`, every `size` 128x128 | OBSERVED |
| Distinct `position.x`: 12 values 0..1408 step 128; distinct `y`: 6 values 0..640; no duplicate positions; extent 1536x768 — a 12x6 grid | OBSERVED |
| Extent = canvas `size` = `rectSize` = `lastSize` = `canvasInWorkingMode[mode 1].size` | OBSERVED, **for the active working mode only**: `canvasInWorkingMode[mode 0].size` is 832x624, smaller than the cabinet extent. Do not assume size = extent in general |
| `cabinetID` joins `/device/cabinet.id` 72/72 and `monitor/info` 72/72; `outputID` agrees with `/device/cabinet.outputID` 72/72 | OBSERVED |
| `connectID` = `/device/cabinet.index` 72/72 (not `outputIndex`, which agrees 3/72) | OBSERVED |
| `/device/cabinet` has no position key — `/api/v1/screen` is the only source of cabinet positions on this unit | OBSERVED |
| Each output's 24 cabinets run a serpentine: `connectID` 0 at the far end of the lower of its two rows, back along the upper | OBSERVED, this wall |
| Cabinet positions are canvas-relative and 0-based, while `canvases[0].position` is negative (−158, −1072) and `layers[].position` shares that frame — the mode-0 layer sits exactly at the canvas position, the mode-1 layer covers the canvas rect with a small overhang | **REASONED from one snapshot.** A pane must not mix the two frames and must not read a negative layer position as off-screen |
| `canvasInWorkingMode[]`: mode 0 832x624, `maxFrameRate` 480 (int), `isCustomSize` true; mode 1 1536x768, `maxFrameRate` 330.6 (float), matching the canvas top-level value | OBSERVED; "maximum fps" is REASONED from the name |
| `pageInfos[]`: 8 pages, exactly one `isShow`, = `selectedPageID`; `screenGroups[]`: 1; screen keys not in the fixture: `cryptoCabinetNum`, `monitorSlotId` | OBSERVED |
| Presets: one screen, two presets, `state` false on both; per-preset keys as the fixture | OBSERVED; "no preset active after the show" is REASONED, supported by the MX40 `state` transition below |
| `screens[0].createTime` reads one year behind the snapshot date (same calendar day, about an hour earlier) while the HTTP `Date` header agreed with UTC to ~2 s | **UNKNOWN** whether the clock was wrong when the screen was built or the screen is a year old. Do not trust payload timestamps for alerting or history without an external clock |
| Whether the MX40 Pro returned any `canvases[]` | **UNKNOWN** — the MX40 fixture hard-codes `[]` with no note |

**Seven minutes apart: the reorder and the keyed diff, on the MX30.** Between
14:44:05Z and 14:51:05Z all 72 `monitor/info` cabinets changed list position;
`screenSourceStatus[]` rotated (its first entry moved to last);
`/device/cabinet` was identical in every value and in order; `input/sources`,
`rvCardsRuntime`, `outputStatus` and `fanInfos` kept their order. Keyed by
`cabinetID`, `diff_snapshots` found **87 changes and zero identity churn**:

| Reading | Behaviour over 420 s |
|---|---|
| `rvCardsRuntime[].totalRuntime` | +420 on 67 cards, +480 on 5 — the one-tick straddle at 60 s granularity the MX40 showed |
| `runtime`, `totalRuntime` | 20640 → 21060 and +420; both multiples of 60 |
| `rvCards[].temperature.value` | 7 of 72 moved, all by ±1 |
| `rvCards[].voltage.value` | 1 of 72 moved, 4.3 → 4.2 — **and `cabinets[].cabinet.voltage.value` moved identically on the same card**, the nested mirror; a reader watching both reports two changes for one |
| `fanInfos[].fanSpeed` | +11, −19, −16 rpm |
| `mainBoardVoltage.value` | +0.01 |
| `rvCardsRuntime[].runtime` | unchanged on all 72 — static on this firmware |
| everything else in the payload | unchanged; the 87 are fully accounted for above |

The two-degree hysteresis argued for above holds here too: ±1 is noise on this
wall as well.

**Headers, for a consumer that reads the wire.** Every one of the six
`curl -i` envelopes, empty and JSON alike, carried `Vary: Origin`,
`Access-Control-Allow-Origin: *` and `Access-Control-Allow-Credentials: true`
(OBSERVED). REASONED consequence: an in-browser page can GET the API directly,
without a proxy, for requests that send no credentials (browsers reject the `*`
plus credentials combination only when credentials are sent). The `Date` header
agreed with the polling host's UTC to about 2 s — the only clock reading this
project has from a COEX unit (OBSERVED), and note that it did not save the
stored `createTime` above from being a year out. And `X-Request-Id` on six GETs
within one second had a leading byte that incremented by exactly one per
request with the remainder constant — which looks like a server-side request
counter. **REASONED and untested**: if other clients' requests advance it, a
jump between two of your own would be a passive indicator of controller-side
API activity such as an attached VMP. Six samples; do not build on it yet.

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

**What the end of the show settled, with no writes by this project.** A third
snapshot five hours after the second found `sourceStatus` on one HDMI input
gone from `1` to `0` with every other input unchanged — a source removed after
the show — and `presets[].state` moved to a different preset. Both fields
therefore move as the readings above assumed; `sourceStatus` = signal is now
supported by a real transition rather than by one snapshot's pattern, though an
attended unplug would still make it clean. Over the same five hours `runtime`
advanced 17,880 s against 17,842 s of wall clock (seconds, at the 60 s
granularity already noted), and the idle wall ran **31–36 °C** against
**37–42 °C** mid-show, main board 37 °C against 42 °C — a six-degree show load,
which is the kind of number a threshold should be set with in mind.

**SNMP, from the wire.** With `snmpstate` reporting `false`, `snmpget` on v1
and v2c with the default community drew no response at all — the agent is
absent, not merely restricted. OBSERVED, on the MX40 Pro. On the MX30 the same
shape: `snmpstate` `false` in both snapshots, two `snmpget` attempts answered
"Timeout: No Response" (OBSERVED) — but the version, community and OID tried
were not recorded in the evidence, and an SNMPv1/v2c agent silently drops an
unknown community, which also times out. So on the second unit "agent
disabled" is **REASONED**, with `snmpstate` false as the consistent reading,
rather than OBSERVED clean. The OID map has now met two COEX units and been
exercised on neither.

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

That is the register-bus picture. Over COEX HTTP the MX30 exposes the active
layer's source in `/api/v1/screen` (§4, above) — REASONED to be the input's
`groupId`, REASONED to be what the wall is showing — so on that family the
first statement can be made, labelled as such.

---

## 5. Four register-bus traps that make reads lie

**OBSERVED on a NovaPro UHD Jr.** The first two were reproduced across a power
cycle and contradict assumptions this project previously held in writing; the
third and fourth turned up later in ordinary block reads, and one of them was
already in this repository's code as a chunked read. All four matter to anyone
who reads registers — including a read-only consumer, because *all are
triggered by reads alone*. None produces an error. All produce
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

- Reading is still safe. None of the four changes controller state; all are about
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
| Passive inventory | **Settled: no, on three independent counts.** Replies are **unicast to the requester** (OBSERVED, L2 and L3); the **MX40 never announces itself** (OBSERVED, 30 min); and **VMP does not probe on a timer** (OBSERVED, 30 min with VMP running and nobody searching). A passive listener on a VMP-operated show network hears *nothing at all* — not even that a control app exists. **An MX30 was equally silent for 600 s** (OBSERVED, second unit, after the show; unicast and subnet-broadcast coverage certain, multicast coverage UNKNOWN on a multi-homed host). An inventory needs a port mirror, a tap, or co-location with the control app. Caveat: broadcast filtering on the switch was not excluded by a positive control on either network |
| Discovery destination | Send the **subnet broadcast** for register-bus hardware; the multicast group went unanswered on a UHD Jr (OBSERVED). **An MX40 Pro answers no probe at all** (OBSERVED, eight probes, four destinations), **and an MX30 on v1.5.1 answered none either** (OBSERVED, the same eight; that it does not answer is REASONED from one ~6 s trial) — COEX units must be given their address; the probe cannot find them |
| `rpProMI:` payload | **OBSERVED on one unit:** 8-byte ASCII tail, `App,0161`. It carries **no model ID and no device name** — the earlier "appears to carry model and name" guess was wrong as well as unevidenced. Identify over the register bus, not discovery |
| Trusting a register read | **Four OBSERVED traps** (§5): unimplemented addresses echo the previous response instead of erroring; reads snap to field boundaries; a block must be read from its base in one request; and the receiving-card monitoring block is exactly 0x100 bytes, beyond which a read aliases into another block. Poison-test anything unverified, and never chunk a block read |
| Polling 8001 with VMP attached | **One burst of eight GETs is OBSERVED safe mid-show** (0.1 s, no `Busying`, no effect on a live show) and **ten minutes at 1 Hz is OBSERVED clean on the controller side** (1,791 GETs after the show: 0 errors, 0 `Busying`, `monitor/info` p50 48 ms / p99 64 ms, no drift), **repeated for five minutes on an MX30** (900 GETs: 0 errors, 0 `Busying`, `monitor/info` p50 10.5 ms / p99 15.3 ms for 72 cabinets, no drift). Whether 1 Hz disturbs an operator mid-cue is still REASONED — VMP was not being driven, and its attachment after the show is UNKNOWN on both units. Use the read-only client, 10–30 s, back off on code 5 |
| Monitoring over GET | **Rich over HTTP, field names now OBSERVED** (§4): per-card temperature, voltage, link state and error bits; main-board temperature and voltage; fan rpm; per-input signal via `sourceStatus`. On the MX30, `/api/v1/screen` adds cabinet positions (OBSERVED) and each layer's source (REASONED to be `groupId`, from one discriminating value; that it is the displayed input is REASONED too). SNMP was **off** on both COEX units seen. **Nothing** on VX4S / UHD Jr without a control session |
| Absent endpoints | **Differ per firmware.** MX40 Pro: HTTP 404 (OBSERVED). MX30 v1.5.1: **HTTP 200 with an empty body** — no `Content-Type`, no envelope, ~2 ms like everything else (OBSERVED). Test for the missing envelope; treat empty as absent, never as present-and-empty; never take 200 as "exists". Both readers this project knows of mishandled it at the time of contact (§4) |
| Identity over HTTP | `monitor/info.name` is `MX40 Pro_<digits>` on one unit and a plain word on the other — **the model cannot be read from it** (OBSERVED on the MX30, whose name carried none); that the word is an operator label is REASONED. No model or firmware field exists on either unit (UNKNOWN over the API); a `modelId` 5138 is present but what it names is UNKNOWN. Tell units apart by input complement and output enumeration (REASONED) |
| Parsing both firmwares | Join on `rvCards[].cabinetID`; readings from `rvCards[]`; ignore `cabinets[]` top-level and nested `cabinet{}` readings (the nested voltage mirrors `rvCards[]` and double-counts); `signalInterruptCount` is a bare int; count fans, ports and outputs from their arrays; key connector type on `type`, never `id`; never trend by list index |
| Consuming it | `survey_network()` / `novasun survey --json`, `schema_version` 1. Leave `allow_register_bus` off |

**Status of the first-day list.** Capturing an `rpProMI:` reply is **done** —
see §2 — and so is the unicast question, which turned out to need a packet
capture rather than a second host. Checking **whether SNMP is enabled** has now
been done on two COEX units, and it was off on both (OBSERVED, 2026-09-11 and
2026-09-26). If a unit is ever found with it on, most of the monitoring pane is
available through an interface designed for exactly this; until then the HTTP
GET path in §4 is the monitoring there is, and its two firmwares' differences
are the thing to build for.

Added to the list by §5: **do not build any register map from an unguarded
sweep.** That applies to crewbox as much as to this repository.
