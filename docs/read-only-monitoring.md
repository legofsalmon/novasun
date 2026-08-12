# Read-only monitoring

Written for consumers that observe NovaStar hardware without controlling it —
crewbox in particular. It answers four questions, and is explicit about which
answers are established and which are not.

Confidence labels used throughout:

| Label | Meaning |
|---|---|
| **OFFICIAL** | Stated in a NovaStar document |
| **DERIVED** | From decompiled NovaLCT assemblies or published client code |
| **REASONED** | An inference from protocol properties, not observed |
| **UNKNOWN** | Not established. Needs a bench. Do not design around a guess |

No NovaStar hardware was available while this was written. Nothing below is
marked OBSERVED, because nothing has been.

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

**UNKNOWN — and I need to correct something.** An earlier note in
[`investigation.md`](investigation.md) said the reply "appears to carry model and
name information this implementation currently ignores". That overstated what I
had. I had not seen a reply. What I had was `sarakusha/novastar` discarding
everything after the prefix, and I inferred there must be something worth
discarding. That inference is not evidence, and crewbox should not plan around
it.

What is actually established:

| Fact | Confidence |
|---|---|
| Probe is the 8 ASCII bytes `rqProMI:` | **DERIVED** |
| Reply begins `rpProMI:` | **DERIVED** |
| Both on UDP 3800; multicast group `224.224.125.119` | **DERIVED** |
| The device is identified by the reply's **source IP** | **DERIVED** |
| Anything after the prefix | **UNKNOWN** — no sample, no document |

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

### On non-COEX hardware (VX4S, NovaPro UHD Jr)

**No read-only path exists.** There is no HTTP API and no SNMP; monitoring means
reading the `0x0A000000` block per receiving card over the register bus, which
requires a TCP control session on 5200 that NovaLCT may hold exclusively
(**REASONED**). `register_bus_monitor` does it, but for these models a
monitoring pane should expect to show "reachable / not reachable" plus whatever
identity it can get, and not much else, unless it is willing to hold a control
connection.

---

## Summary for crewbox

| Question | Answer |
|---|---|
| Passive inventory | Probes always visible; **replies may be unicast — UNKNOWN**. Do not assume passive discovery yields an inventory |
| `rpProMI:` payload | **UNKNOWN, no sample.** My earlier "appears to carry model and name" was speculation and is withdrawn |
| Polling 8001 with VMP attached | **Very probably safe for GET, unverified.** Use the read-only client, 10–30 s cadence, back off on code 5 |
| Monitoring over GET | **Rich over SNMP** (official OIDs, incl. per-card status and per-input signal); **good over HTTP** with provisional field names; **nothing** on VX4S / UHD Jr without a control session |

The two things worth doing on the first day with hardware, in order: **capture
one `rpProMI:` reply** (settles questions 1 and 2 in a minute), and **check
whether SNMP is enabled** — if it is, most of the monitoring pane is already
available through an interface designed for exactly this.
