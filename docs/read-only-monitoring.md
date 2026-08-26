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

---

## 1. What can be learned with zero transmission?

**Do controllers announce themselves unsolicited?** **UNKNOWN.** No document
describes unsolicited announcement, and no published implementation listens for
one — every client, including the most complete (`sarakusha/novastar`), sends
`rqProMI:` and waits. Absence of evidence here is weak evidence: nobody has
looked. Assume no announcement until a listener proves otherwise.

**Would a silent listener see the inventory when NovaLCT is running?**
**Partly, and the crucial half is UNKNOWN.**

What is certain: the probe is broadcast to the subnet broadcast address *and* to
multicast `224.224.125.119`, both on UDP 3800 (**DERIVED**, from
`sarakusha/novastar`'s discovery implementation). So any host on the segment
sees NovaLCT and VMP probing. That alone tells you a control application is
running and roughly how often it scans.

What is not: whether the **reply** is broadcast or unicast back to the
requester. This decides everything for passive discovery. Published code reads
the reply's source address from the datagram it receives, which is consistent
with either. If replies are unicast — the likelier design — a listener on a
third host sees probes but no inventory, and needs a port mirror or a tap to see
replies at all.

**How long would a listener wait?** **UNKNOWN.** NovaLCT's discovery cadence is
not documented, and it may only probe on user action rather than on a timer. If
it is user-driven, passive discovery could wait indefinitely.

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
so explicitly — that outcome *is* the answer to whether replies are unicast. One
session with a controller and NovaLCT settles questions 1 and 2 together.

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
| Whether the reply is unicast or broadcast | **UNKNOWN** — see below |

`App` is plausibly a run-mode marker (application firmware, as against a
bootloader) and `0161` plausibly a version, but both readings are **REASONED**
and neither is worth building on. What matters for a consumer is the shape:
the tail is short ASCII, and **identification still has to come from the
register bus or the HTTP API, not from discovery**. A consumer that hoped to
build an inventory with model names from discovery alone cannot.

**The unicast question is still open.** The reply was received by the host that
sent the probe, which is consistent with either unicast or broadcast and so
settles nothing. Deciding it needs a second host listening on UDP 3800 while a
*different* host probes — that experiment has not been run.

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

**REASONED: very probably yes for GET. Not verified.**

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

| Endpoint | Gives |
|---|---|
| `GET /api/v1/device` | model, name, serial, firmware, working mode |
| `GET /api/v1/device/monitor/info` | per-cabinet temperature and online state, controller temperature, fan speed |
| `GET /api/v1/device/cabinet` | cabinet list: id, screen, position, size, brightness |
| `GET /api/v1/screen` | screens: id, name, dimensions, brightness, gamma, colour temperature |
| `GET /api/v1/device/input/sources` | inputs: id, name, type, connected, resolution |
| `GET /api/v1/device/screen/displaymode` | 0 normal, 1 blackout, 2 freeze |
| `GET /api/v1/preset` | preset list and the active one |
| `GET /api/v1/device/backup` | primary/backup status |
| `GET /api/v1/device/multifunc-card/detailinfo` | multifunction card status |
| `GET /api/v1/device/snmpstate` | whether SNMP is on — worth reading first |

`MonitorSnapshot` folds these into `healthy`, `offline_cabinets`, `hottest`,
`signal_present` and `display_mode`.

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
| `+0x08` | u16 | measured frame period in microseconds | **REASONED** |
| `+0x16` | u8 | record index, `0x00`..`0x08` ascending | **OBSERVED** |
| `+0x19` | u16 | refresh rate in centihertz (`6000` = 60.00 Hz) | **REASONED** |

On a UHD Jr, records `0`-`7` are input connectors and record `8` reports
`3840x2160` -- the unit's own 4K canvas, not an input. Past record 8 the values
are incoherent and the index byte stops ascending: that is the end of the array,
not more data.

**Record 1 is the HDMI connector on this unit**, established by plugging and
unplugging a 1920x1080 source: record 1 alone moved between `1920x1080` and
`0x0` while records 0 and 2-7 stayed at zero throughout. Which connector each
of the other indices corresponds to is **UNKNOWN** -- it needs a source on each
in turn, and this bench had only one.

The two rate fields are worth distinguishing. `+0x08` jitters between 16663 and
16666 between consecutive reads, which is what a *measured* period does;
`+0x19` reads a rock-steady `6000`, which is what a *nominal* declared rate does.
Both come to 60.00 Hz. That reading is REASONED from the arithmetic and the
jitter, not from any document.

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

### What a read-only consumer should take from this

- Reading is still safe. Neither trap changes controller state; both are about
  believing the answer.
- Do not treat "the read succeeded and returned non-zero" as evidence a register
  exists. It is not.
- Prefer whole-block reads at documented base addresses over exploratory offsets.
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
| Passive inventory | Probes always visible; **replies may be unicast — still UNKNOWN**. Do not assume passive discovery yields an inventory |
| `rpProMI:` payload | **OBSERVED on one unit:** 8-byte ASCII tail, `App,0161`. It carries **no model ID and no device name** — the earlier "appears to carry model and name" guess was wrong as well as unevidenced. Identify over the register bus, not discovery |
| Trusting a register read | **Two OBSERVED traps** (§5): unimplemented addresses echo the previous response instead of erroring, and reads snap to field boundaries. Poison-test anything unverified |
| Polling 8001 with VMP attached | **Very probably safe for GET, unverified.** Use the read-only client, 10–30 s cadence, back off on code 5 |
| Monitoring over GET | **Rich over SNMP** (official OIDs, incl. per-card status and per-input signal); **good over HTTP** with provisional field names; **nothing** on VX4S / UHD Jr without a control session |
| Consuming it | `survey_network()` / `novasun survey --json`, `schema_version` 1. Leave `allow_register_bus` off |

**Status of the first-day list.** Capturing an `rpProMI:` reply is **done** —
see §2; it settled the reply's shape but not the unicast question, which needs a
second listening host. Checking **whether SNMP is enabled** is still outstanding
and still the highest-value item for crewbox: if it is on, most of the
monitoring pane is already available through an interface designed for exactly
this. The bench unit so far is a UHD Jr, which has no SNMP and no HTTP API, so
that question needs COEX hardware to answer.

Added to the list by §5: **do not build any register map from an unguarded
sweep.** That applies to crewbox as much as to this repository.
