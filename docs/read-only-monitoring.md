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
  **UNKNOWN** — nothing read over the API carried one, and nobody wrote it
  down. (`/api/v1/device/hw`, which carries it on the MX30, was never
  requested there.)
- **MX30**, on a show network after the show, 2026-09-26, firmware **v1.5.1 as
  reported by the operator** at the time (no HTTP payload read in that pass
  carried a controller firmware string; `/api/v1/device/hw`, first read that
  evening, does), **read over SNMP later the same afternoon as `V1.5.1`**
  (OBSERVED, below) and over HTTP that evening as `hwVersion` `"V1.5.1"`.
  The first pass was read-only throughout: two ICMP pings,
  HTTP GETs on 8001 (two eight-endpoint snapshots, ten further GETs, six
  `curl -i`, about twenty-four from `survey`/`watch`/`identify` whose outcomes
  were not kept, and 900 from a five-minute 1 Hz poll), two `snmpget` attempts,
  eight `rqProMI:` probes. In that pass: no TCP 5200, no PUT or POST, and
  whether VMP was still attached is **UNKNOWN**.
- **The same MX30, 16:50Z–16:55Z, with VMP closed by the operator** and the
  operator's explicit go for writes — the first session in this project to
  write to a COEX unit. Sent: **2 `PUT hw/colorBeacon` and 5
  `PUT snmpstate`**, the only writes in that session (SNMP was left off); 32 snapshot GETs
  through the read-only client and seven further `GET snmpstate` (a baseline,
  five read-backs, one during the register-bus probe); SNMP v2c
  with community `public` only — walks of the MIB-2 system group and of the
  enterprise arc, and `sysDescr` GETs, every request with one retry; two TCP
  connects to 5200; one 20-byte register-bus read frame to UDP 5201. What it
  settled is in the SNMP recommendation below, §4's SNMP section and §4's
  register-bus note.
- **The same MX30, 17:43Z–17:44Z, with the operator at the wall** watching the
  chassis: nine `PUT hw/colorBeacon` across three request bodies, and nothing
  else. Nothing visible changed (OBSERVED); the endpoint is most likely absent
  on this firmware (REASONED). See `docs/coex-http-api.md`.
- **The same MX30, 17:49:58Z–17:54Z, operator at the wall**, who froze the
  wall from the front panel at about 17:50:30Z and unfroze it at about
  17:51:00Z. Sent: one `PUT snmpstate {"state": true}` at the start and one
  `{"state": false}` at the end; in between, read-only GETs once a second
  (screen, input sources, monitor/info, displaymode, device/input, presets,
  audio; the cabinet list every five seconds) and SNMP v2c walks, of the
  screen arc each second and the whole enterprise arc every five. It did not
  poll `/api/v1/screen/output/display/state`, and its conclusion — that
  display state is not observable — is **withdrawn** (§4, "Display state").
- **The same MX30, 18:01:18Z–18:07:10Z, VMP opened and operated by the
  operator**, with a packet capture running on the VMP host. This project sent
  the unit **one 20-byte register-bus read frame to UDP 5201** (18:01:28Z,
  before VMP connected) and nothing else. Everything else it received came
  from VMP: 218 GETs and four PUTs on 8001 (§3), one websocket and one preview
  stream on TCP 8082 (§4). The operator froze the wall from the front panel
  while VMP was attached. The raw capture has since been deleted; what is
  recorded here comes from masked notes taken from it, and every negative
  drawn from it covers IPv4 only — the capture held no IPv6 frames. What it
  settled is in §1 (announcements), §3 (what VMP writes; the lock) and §4
  (identity, display state, the websocket, the preview).
- **The same MX30, 18:46:41Z–18:47:40Z, VMP closed, operator at the wall.**
  Sent: `GET /api/v1/screen/output/display/state` once a second (60 GETs) and
  one websocket to `/api/v1/websocketchannel` — the upgrade GET, 59 empty
  pongs to the server's pings, a close frame at the end. VMP's hello text was
  deliberately not sent; no PUT, no lock. The operator froze the wall from the
  front panel and unfroze it about 22 s later. What it settled is under
  "Display state" in §4.
- **The same MX30, 18:51Z–19:11Z, VMP closed, operator at the wall.** Three
  writes at about 18:51Z, the only ones in the notes for this stretch: two
  `PUT /api/v1/device/cabinet/brightness` (to 0.45 at 18:51:36Z and back to
  0.2 at 18:51:46Z) and one `PUT /api/v1/screen/brightness`, which changed
  nothing. **The first write took the wall from 20 % to 45 % — brighter — for
  about 9 s, when the test had been announced as dimming it**: it set an
  absolute target, and the wall was at 0.2, not the 0.5 read at 14:44Z.
  Brightness tests now step relative to a fresh read. Everything after that
  was the operator at the front panel or at the cables, watched read-only —
  only GETs and websocket pongs were sent, nothing on UDP (a `display/state`
  GET at 1 Hz, a websocket with the upgrade and pongs only, `monitor/info`
  every 2 s during the unplugging, and a receive-only socket on UDP 54622): a
  brightness-knob turn
  (18:54:27Z–18:54:48Z), a **blackout** (18:57:07Z–18:57:17Z), **every output
  data line unplugged one by one with the unit powered** (18:59:52Z–19:02:29Z),
  and **power-off from the front-panel button** (19:10:56Z; a standby, not a
  mains cut — see §4). What it settled is under "Display state" and
  "Unplugged outputs, and power-off" in §4.

An OBSERVED fact here is a fact about the unit named, not yet about the fleet.
**Every MX30 statement below is scoped to that one unit, that firmware and that
day (the read-only pass 14:44Z–14:57Z; the SNMP and register-bus session
16:50Z–16:55Z, VMP closed; the attended sessions 17:43Z–17:54Z; the VMP capture
18:01Z–18:07Z; the display-state test 18:46Z–18:48Z; the brightness,
blackout, unplugging and power-off session 18:51Z–19:11Z)**; where the MX30
differs from the MX40 Pro, the
earlier statement is kept and scoped rather than withdrawn, because both are
observations. Where the two are compared, "the MX40 record" means this
document plus the simulator's MX40-like shape in `coexsim.py`, not the reduced
fixture — see the note on that fixture in §4.

### Corrections, 2026-09-26 evening — urgent for crewbox

Four claims published earlier were wrong or too broad — two of them that
same day (commits `522da45` and `9ed9db0`), two older (from 2026-09-11 and
before, and extended to the MX30 on 2026-09-26). Each is corrected where it appears below;
this list exists so a consumer that planned around them sees the change first.

1. **"Display state is not observable on the MX30" is withdrawn.**
   `GET /api/v1/screen/output/display/state` reads `displayState[].displayMode`
   2 through a front-panel freeze and 0 when live, per canvas (OBSERVED: polled
   through one attended freeze; the same value marked a second freeze on the
   websocket), and 1 through a front-panel blackout (OBSERVED once, attended,
   18:57Z). The attended sweep behind the withdrawn claim never polled that
   endpoint. §4, "Display state".
2. **The MX30 announces itself.** Every 3.0 s, unsolicited, on UDP 54622,
   54623, 54624 and 54700 from source port 54650, with its MAC and API ports in
   96 bytes of JSON (OBSERVED). A receive-only listener on those ports finds
   MX30s with zero transmission. "Passive inventory: no" was measured on UDP
   3800 only; it is re-scoped to that port, not deleted. §1.
3. **Identity is readable over HTTP.** `GET /api/v1/device/hw` gives `name`
   "MX30", `modelID` 5138, `hwVersion` "V1.5.1", `sn` and `mac` (OBSERVED).
   The same reply carries a `randomPassword` field, served to an
   unauthenticated GET: drop it before logging, storing or displaying anything
   from that endpoint. §4.
4. **"A cabinet present in `monitor/info` with a reporting card is online" is
   withdrawn — it gives a false all-clear.** With every output data line
   unplugged and the MX30 still powered, `GET /api/v1/device/monitor/info`
   kept listing all 72 cabinets and 72 receiving cards, every
   `nextCabinetLinkStatus.linkStatus` true and temperatures 39–42 °C, at every
   2 s poll for the ~8.5 minutes until power-off (OBSERVED); only
   `rvCardsRuntime` emptied. Its per-card readings are last-known values, not
   live (REASONED). A reader that counts cabinets from `monitor/info` reports
   a fully unplugged wall as healthy: crewbox's does (OBSERVED-in-harness at
   `7c8cf6a`, below), and novasun's did until the change that recorded this.
   novasun now counts from the connected sources and says why a wall is not
   healthy (`monitor.health_reasons`, `interpret_coex_status`); monitor/info
   only decorates the cabinets they list. Count from `GET /api/v1/screen/cabinet/count` or the
   `/api/v1/device/cabinet` entry count against the expected number, and read
   `outputStatus[].linkStatus`. §4, "Unplugged outputs, and power-off".

What else crewbox's agent should see is in [Handoff evidence for
crewbox](#handoff-evidence-for-crewbox-2026-09-26), near the end.

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
monitoring available, which is why its field names being OBSERVED mattered
more than the SNMP OID map, which was then unexercised.

**OBSERVED again, 2026-09-26:** the second COEX unit read, an MX30 on v1.5.1,
returned the same `{"state": false}` in both snapshots of the read-only pass.
Two of two COEX units seen had SNMP off as found, and at that point the OID map
was still unexercised on any hardware.

**Exercised once, later the same afternoon — OBSERVED on that MX30, V1.5.1, VMP
closed.** With the operator's go, SNMP was switched on over HTTP, walked over
v2c with community `public`, and switched off again. The agent answered at
once, and the enterprise walk returned 170 values. What it gave, in short — the
detail, with every label, is in §4 under [The OID map on an
MX30](#the-oid-map-on-an-mx30-v151--exercised-once-2026-09-26):

- **The controller's model and firmware** — `CONTROLLER_MODEL` `"MX30"`,
  `CONTROLLER_FIRMWARE` `"V1.5.1"`. When this was written no HTTP GET on
  either COEX unit had given either, and SNMP was called the only surface that
  does. **That no longer holds:** `GET /api/v1/device/hw`, first read that
  evening, gives both over plain HTTP with no switch-on (§4; OBSERVED on the
  MX30 only).
- 44 of the 46 OIDs `snmp.py` transcribes, served — but several in forms the
  document does not give: values scaled x100 (REASONED), 64-bit bitmasks where
  the document says 0/1, `"ERROR: ..."` strings in place of numbers, and the
  per-receiving-card status collapsed into **one bitmask per port**; the
  documented per-card OIDs were absent from the walk.
- **The MIB-2 system group is not served** (`sysDescr` drew `noSuchName`), so a
  reachability probe must ask an enterprise OID.
- `CONTROLLER_ROLE` read **1, "backup" in the document, on a unit running the
  wall alone**. Do not display "backup" from it.

So the recommendation survives contact with one unit, with conditions: every
item the second bullet above lists was served in some form (OBSERVED; that the
health and link items mean what they say rests on reading the bitmasks bit by
bit, REASONED), but not "more than the HTTP API" — on that unit each surface
gave something the other did not (§4) — receiving-card status arrives per port
rather than per card, and a consumer has to handle every quirk in §4 before its
numbers mean anything. Traps were not tried; that the controller pushes them is
still OFFICIAL only.

**Enabling it is a write, and the body matters — OBSERVED on the MX30,
V1.5.1.** `PUT /api/v1/device/snmpstate` with **`{"state": true}`** turned the
agent on and `{"state": false}` off again, twice in each direction, each time
read back by `GET snmpstate`. **`{"value": true}` answered HTTP 200 with a full
`{"code":0,"data":"","message":"Success"}` envelope and changed nothing** — the
GET in the same second still read `{"state": false}` (OBSERVED once; the
`false` direction was never sent). This repository's `CoexClient.set_snmp`
sent `{"value": ...}` at the time, so it reported success while doing nothing.
The lesson is wider than one endpoint, though it rests on one: **a Success
envelope on a PUT does not mean the change happened; read the value back**
(REASONED). None of this is crewbox's to do — it cannot write — but the GET is
the part it reads, and it held up: each read-back that was checked against the
agent matched it — answered after `true`, timed out after `false` (OBSERVED
after the second enable and after both disables; that the agent answered after
the first enable is REASONED from timestamps).

---

## 1. What can be learned with zero transmission?

**Do controllers announce themselves unsolicited?** **On UDP 3800, no —
OBSERVED on two units. On four other UDP ports, the MX30 does — OBSERVED,
2026-09-26** (see [COEX announcements](#coex-announcements-on-udp-54622-54623-54624-and-54700--observed-on-an-mx30),
below). This answer was first written as a plain "no". It was measured on UDP
3800 only, and is kept with that scope rather than deleted.

A passive listener on UDP 3800 sat for thirty minutes on a live-show network
with an **MX40** on the same segment (L2 adjacency confirmed from the ARP
table) and heard nothing from it. No document describes unsolicited
announcement, and no published implementation listens for one. Scope: one
model, one thirty-minute window, **one port**. Whether the MX40 Pro announces
on the ports the MX30 uses is **UNKNOWN**: nothing listened there.

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
**Re-scoped, 2026-09-26 evening:** that listener was bound to UDP 3800 only.
The same MX30 was later captured announcing every 3 s on four other ports
(below), so it was very probably announcing throughout those 600 s, unheard
(REASONED: the sessions were hours apart, and whether the capture's segment was
the listener's was not recorded).

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

**Therefore passive discovery by overhearing `rqProMI:` replies does not yield
an inventory.** A listener on a third host sees every probe — so it can tell
that NovaLCT or VMP is running, and how often it scans — but it never sees a
single reply, and so never learns what is on the network. Getting the inventory passively needs a port mirror, a tap,
or a listener running on the same host as the control application. This was
previously guessed at as "the likelier design"; it is now measured. It holds
for the register-bus discovery exchange; it does not apply to the COEX
announcements below, which the unit broadcasts itself.

**How long would a listener wait?** **Indefinitely — OBSERVED for VMP.** During
that same thirty minutes VMP was running and operating the show, and nobody
pressed search. The listener overheard **zero probes**. VMP does not discover on
a timer; it probes only on user action. Passive discovery on a VMP-operated
network therefore has nothing to overhear until an operator happens to press a
button, which during a show they will not.

NovaLCT's cadence is still **UNKNOWN** — it has not been watched — but the
working assumption should now be the same, because that is what the one
vendor tool observed actually did.

**Refined, 2026-09-26:** against a COEX MX30, VMP sent **no probe of any kind**
and connected 5 ms after the unit's own announcement (below). So VMP's silence
on UDP 3800 is most likely because it listens for COEX hardware rather than
probing for it (REASONED). That would also explain the thirty probe-free
minutes on the MX40's network, if the MX40 Pro announces too (UNKNOWN).

**One caveat both findings share.** Broadcast filtering on the show switch was
not ruled out: the ARP entry proves the Mac and the MX40 share a segment, not
that broadcasts reach the Mac's port. The positive control is a packet capture
showing *any* broadcast traffic (ARP requests will do) arriving during the
window. It was not run — the show took precedence — so these two results are
OBSERVED with that stated hole rather than OBSERVED clean. **On the MX30's
segment the positive control now exists** (below): the unit's own subnet
broadcasts reached the capturing host. On the MX40's network it still does not.

### COEX announcements on UDP 54622, 54623, 54624 and 54700 — OBSERVED on an MX30

Found in the packet capture on the VMP host, 2026-09-26, 18:01Z–18:07Z. Scope:
one MX30, `hwVersion` "V1.5.1", one segment, IPv4 only (the capture held no
IPv6 frames).

**The unit announces itself unsolicited, every 3 s, on four ports (OBSERVED).**
117 bursts of four UDP datagrams, one each to **54622, 54623, 54624 and
54700**, always in that order and within 1 ms, all from source port **54650**
to the subnet broadcast address (Ethernet `ff:ff:ff:ff:ff:ff`). Interval: mean
3.0024 s, standard deviation 6.3 ms; 117 bursts where 117.09 were expected, so
none were missed. No other host sent to or from those ports.

**The payload is 96 bytes of bare ASCII JSON** — no header, no NUL terminator,
no application checksum — and it was byte-identical in all 468 datagrams
(OBSERVED). With a synthetic MAC:

```
{"data":[{"apiPort":"8001","mac":"00:00:5e:00:53:30","authType":0,"workMode":0,"https":"9001"}]}
```

The real `mac` is the unit's own, in NovaStar's `54:b5:6c` OUI, lower-case and
colon-separated — the same length, so the offsets below hold.

| Field | JSON type | Value bytes (0-based, quotes included) | Value seen | Confidence |
|---|---|---|---|---|
| `data` | array of one object | — | — | OBSERVED; whether it can hold more than one is UNKNOWN |
| `apiPort` | string | 20–25 | `"8001"` | OBSERVED |
| `mac` | string | 33–51 | equal to the Ethernet source MAC and to `mac` in `GET /api/v1/device/hw` | OBSERVED |
| `authType` | integer | 64 | 0 | OBSERVED value; meaning UNKNOWN |
| `workMode` | integer | 77 | 0 | OBSERVED value; meaning UNKNOWN (`/device/hw`'s `deviceWorkMode` also read 0 — a weak match, REASONED) |
| `https` | string | 87–92 | `"9001"` | OBSERVED value; whether anything listens on 9001 is UNKNOWN |

The frame is 138 bytes (IP total length 124, UDP length 104, DF set, TTL 64);
across all 468, only the IP ID, the IP and UDP checksums and the destination
port vary.

What it carries, and what it does not:

- **IP (from the IP header), MAC, API port and HTTPS port.** No model, name,
  serial or version (OBSERVED). Identifying the unit takes one
  `GET /api/v1/device/hw` (§4) — a transmission, but a plain read.
- **No state.** The payload was byte-identical before VMP connected, across
  VMP taking the lock, across a front-panel freeze and after VMP quit
  (OBSERVED). It has no field that could carry lock or display state, so
  "unchanged across the freeze" says nothing about the freeze (REASONED).
- **The controller's liveness, not the wall's.** In a later attended session
  (18:59Z–19:11Z, a receive-only socket on 54622) the unit kept announcing
  every 3 s with every output line unplugged, and the announcements stopped at
  once when it was switched off at its front-panel button: the last at
  19:10:55.824Z, the next never came (OBSERVED). Two or three missed announcements make a passive offline dwell
  (REASONED; §4, "Unplugged outputs, and power-off").
- **Not triggered by VMP** (REASONED): bursts came before VMP connected and
  after it quit, and their phase drifted smoothly, +1.78 ms per burst, with no
  reset at either point — the shape of a sleep-style loop. A client elsewhere
  on the switch cannot be excluded from one vantage point.
- **Jumps in the unit's IP ID between bursts are not hidden traffic.** They
  are a uniform-looking 26–896 whatever else is happening, which fits a
  per-destination counter with a random increment (REASONED); the unit's TCP
  and ICMP use unrelated ID sequences (OBSERVED).

**So on the MX30 passive inventory is possible** (REASONED from the OBSERVED
payloads): a receive-only socket bound to those four ports learns every
announcing unit's IP, MAC and API port every 3 s, transmitting nothing. A
subnet-directed broadcast does not cross a router, so it covers one segment
(REASONED). Why there are four ports, and which one VMP binds, are UNKNOWN.
One port is enough to hear every announcement, since the payload is the same
on all four; binding more only adds chances to collide with a control
application on the same host (REASONED; see "Settling it", below). Whether the
MX40 Pro, other COEX models or other firmware announce the same way is
UNKNOWN.

**VMP sent no discovery probe; it most likely used the announcement.** In the
whole capture there was nothing on UDP 3800 (no `rqProMI:`), 5353 (mDNS) or
1900 (SSDP), and no IPv4 or Ethernet multicast at all (OBSERVED, IPv4). VMP's
first packet to the unit was a TCP SYN to the announced `apiPort`, 8001,
**5.0 ms after the first datagram of a burst** — about a 0.17% chance for a
launch timed at random against a 3 s cycle — after four earlier bursts went
unused, most likely before VMP's listener was up (REASONED, strongly; a saved
device list is not excluded outright). Which port VMP binds cannot be seen in a
capture, because a broadcast to a closed port draws no ICMP; `lsof -iUDP` on
the VMP host while it runs would show it, transmitting nothing.

VMP's first HTTP request was `GET /api/v1/device/discovery?vendorName=coex`,
sent once, with no body or credentials. It drew an empty 200 — the MX30's
absent-path reply (§4), so whether that endpoint exists is UNKNOWN. Identity
came from the next request on the same connection, `GET /api/v1/device/hw`,
3 ms later.

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

For COEX hardware the probe is beside the point: no COEX unit seen has answered
it. On the MX30 there is a better option than any probe — it announces itself,
so listening costs nothing (above).

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

It now hears the COEX announcements as well. `novasun listen` covers both
UDP 3800 and the announcement ports unless `--only` narrows it, and
`listen_announcements()` covers the announcements alone, joining no group.
Both bind **UDP 54622 only by default** — the payload is identical on all four
ports (OBSERVED), and each extra bound port is one more chance of colliding
with a control application on the same host that binds later without
`SO_REUSEPORT` (REASONED); `--announcement-ports all` binds the four. The
announcement sockets set `SO_REUSEADDR` and `SO_REUSEPORT`, so they can share
a port with VMP or crewbox on the same host, and they are receive-only under
the same structural and behavioural no-send tests. The payload's real layout,
with a synthetic MAC and IPs, is
[`tests/fixtures/mx30_announcement.json`](../tests/fixtures/mx30_announcement.json).

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
least not this model on this firmware. How VMP finds one was **UNKNOWN** when
this was written; on the MX30 it most likely hears the unit's own announcement
(§1, REASONED), and on the MX40 Pro it is still UNKNOWN. A consumer that needs
to discover MX-class hardware must be told the address or
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
MX40 Pro. The probe cannot find COEX hardware; the MX30 finds itself for you,
by announcement (§1).

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
which needs a control session. The SNMP fallback has now been seen to work,
once: an MX30 with SNMP switched on served all four, and its firmware (§4,
OBSERVED) — but only while SNMP was on, which it was not on either COEX unit
as found. On COEX hardware there is now a better fallback than either:
`GET /api/v1/device/hw` over plain HTTP gives model, name, serial and version
with nothing to switch on (§4, OBSERVED on the MX30).

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
  and request-scoped (**REASONED**). **Refined, 2026-09-26:** each GET is
  request-scoped, but the API does carry state a client can hold — a lock taken
  by `PUT /api/v1/device/hw/lock` that outlives its HTTP connection, and a
  long-lived websocket (below, and §4).
- **The API has a `Busying` error code (5)** (**OFFICIAL**). A device that
  signals contention through a response code is one that expects concurrent
  callers and degrades rather than breaking.
- **There is no authentication** (**OFFICIAL**, and OBSERVED on the MX30: none
  of VMP's 222 requests carried an `Authorization` header, a cookie or a
  token). This bullet used to add "and no session, so there is nothing for a
  poller to hold or steal". **Too strong: there is a lock** (below). A
  GET-only poller still takes nothing, because the lock is taken only by a PUT
  (REASONED).

What is not established: whether a GET can slow VMP's own operations, and
whether any GET has side effects despite the verb. Neither is documented. The
rate the controller tolerates is now bounded from below rather than unknown: at
least three GETs a second, one of them the 265 KB `monitor/info`, for ten
minutes without complaint on the MX40 Pro — and, below, five minutes of the
same on an MX30.

### Five minutes at 1 Hz on an MX30 — OBSERVED, controller side, second unit

Repeated on 2026-09-26 against the MX30 (v1.5.1 — operator-reported at the
time, read over SNMP later that afternoon), after the show with the wall still
lit: the same three GETs per tick — `monitor/info`, `input/sources`, `backup` —
with the same 4 s timeout, for 300 ticks.

| | |
|---|---|
| Ticks | 300 in 300 s, 14:52:06Z–14:57:05Z; every tick gap exactly 1 s |
| Requests | 900 — **0 errors, 0 `Busying`, 0 timeouts** |
| `monitor/info` latency | p50 10.5 ms, p95 12.7 ms, p99 15.3 ms, max 21.6 ms, min 7.7 ms |
| `input/sources` latency | p50 4.1 ms, max 17.1 ms |
| `backup` latency | p50 2.3 ms, max 7.3 ms |
| Drift | `monitor/info` p50 over the first 100 ticks 10.3 ms; over the last 100, 10.5 ms |
| Payload sizes | `monitor/info` ≈ 97 KB for 72 cabinets, `input/sources` ≈ 9.8 KB, `backup` 64 B — **compact re-serialisations of the parsed JSON, not wire sizes**, which were not recorded |

The readings behaved as on the MX40: 72 cards listed on every tick (a
listing, not proof of connection — §4, "Unplugged outputs, and power-off"), hottest
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

### What VMP does when it opens — OBSERVED, one capture, MX30

From the 18:01Z–18:07Z capture on the VMP host (§1). VMP's open is a burst,
then silence on HTTP:

- **218 GETs in 0.65 s** (18:01:41.377Z–18:01:42.027Z) across 90 distinct
  paths, most read two or three times on parallel connections (why is
  UNKNOWN), then **four PUTs** between 18:01:54.9Z and 18:01:57.1Z — and **no
  HTTP at all after that**, for the four minutes VMP stayed open. Every reply
  carried code 0 except the two `GET /api/v1/device/config-file` replies:
  code 3, "don't have config info", inside HTTP 200.
- After its open, VMP's traffic to the unit was **one websocket** (a server
  ping a second, pushed events; §4) and **one preview stream on TCP 8082 at
  about 51 Mbit/s** (§4). It polls nothing over HTTP.
- Two HTTP clients shared one `Application-Id: Launcher_<uuid>` header: a
  `Go-http-client/1.1` (18 requests, including the discovery GET, the first
  `/device/hw` reads and the websocket upgrade) and a `Nova` client (204
  requests, each also sending `Device-Key: <ip>:8001`, `Device-Type: VMP` and
  an empty `Need-Report-All`). Whether the Go client is part of VMP or a
  separate service is UNKNOWN.
- 52 of the GETs carried a JSON body (a `portList` on the cabinet reads, for
  example). `/api/v1/screen` returned 4,855 bytes to one client and body and
  16,694 to another; whether the body alone causes the difference is UNKNOWN.
- The replies' `X-Request-Id` values form **222 consecutive counter values,
  none missing**, across both clients (OBSERVED). So no other client used the
  API during those sixteen seconds — if the counter is global to the unit
  (REASONED).

**The four writes VMP makes when it opens** — the only non-GET requests in the
capture, all from the `Nova` client on one connection (OBSERVED):

| Time (Z) | Request | Body | Reply | Push event |
|---|---|---|---|---|
| 18:01:54.915 | `PUT /api/v1/device/hw/systemtime` | `{"clientTimezone": "<IANA zone>", "second", "minute", "hour", "isUTC": true, "day", "month", "year"}` | 200, code 0 | `deviceLastOperatorChange` naming VMP's IP and its `Application-Id` |
| 18:01:54.948 | `PUT /api/v1/device/picture` | `{"type": 0}` | 200, code 0 | none |
| 18:01:54.968 | `PUT /api/v1/device/hw/lock` | `{"appids": ["LCTPro<id>"]}` | 200, code 0 | `deviceLockChange {locked: 1, ip: <VMP host>}` |
| 18:01:57.085 | `PUT /api/v1/device/picture` | `{"type": 0}` | 200, code 0 | none |

- **Opening VMP writes the controller's clock and time zone** (OBSERVED
  once: the PUT and its Success reply). An earlier GET of `systemtime` read
  local time with an empty `clientTimezone`; VMP's PUT sent UTC and its own
  zone name. It is a side effect of merely opening the application. Whether
  the write takes effect is UNKNOWN: no GET of `systemtime` followed it, and
  the unit's `Date` header lagged the capturing host by about the same before
  and after (weak evidence that it did not step; REASONED).
- **`/device/picture` is most likely preview control, not display mode**
  (REASONED): the first PUT preceded the 8082 connection by 1.5 ms. What
  `type` means, and why it was sent twice, are UNKNOWN.
- **A monitor must copy none of these.** All four are writes.

### The HTTP lock — the COEX control mechanism

On the MX30 the nearest thing to a control session is not a connection but a
lock. REASONED from one capture; the observations under it are labelled:

- **Before VMP:** `GET /api/v1/device/hw/lock` → `{"locked": 0, "ip": ""}`
  (OBSERVED, twice).
- **Taken by a PUT** of an application-id list, `{"appids": ["LCTPro<id>"]}` —
  not VMP's `Launcher_` id, and no IP — and announced to websocket subscribers
  as `deviceLockChange {locked: 1, ip: <requester>}` (OBSERVED). What the list
  names or excludes is UNKNOWN; that the IP is the requester's is REASONED.
- **Held without traffic.** The connection that carried the PUT closed at
  18:02:00Z, three seconds after VMP's last write, with no unlock event, and
  no HTTP followed for four minutes. There was no lock heartbeat: the only
  periodic client traffic was the websocket's pongs (OBSERVED).
- **Did not stop the front panel.** A front-panel freeze and unfreeze went
  through while `locked: 1` stood, with no unlock event before them
  (OBSERVED). An unlock without an event is not excluded, so "the lock does
  not block the front panel" is REASONED.
- **Released at quit, by a mechanism UNKNOWN.** VMP dropped its websocket with
  a TCP FIN — no close frame, no unlock request, no `locked: 0` event before
  the socket closed (OBSERVED). A later `GET hw/lock` read
  `{"locked": 0, "ip": ""}` (operator-reported; not in the capture). So the
  lock went with the websocket, or on a timeout.
- **Whether it blocks other API clients' writes or reads is UNKNOWN.**

What this means for a read-only consumer:

- **Never `PUT /api/v1/device/hw/lock`.** `ReadOnlyCoexClient` cannot — it
  refuses every non-GET before a socket opens — and nothing on a read-only
  surface should try.
- **`GET /api/v1/device/hw/lock` is a useful read.** It shows, without
  writing, whether a control application holds the unit and from which IP
  (REASONED).
- It is the COEX counterpart of the register-bus exclusivity worry, but
  different in kind: explicit (taken only by a PUT), visible (a GET and a push
  event), and no bar to the front panel. The register-bus rule — never open a
  TCP 5200 session to a live COEX controller — is unchanged.

### Recommended polling policy

Implemented in [`../src/novasun/monitor.py`](../src/novasun/monitor.py):

- **Structurally read-only.** `ReadOnlyCoexClient` rejects any method other than
  GET before a socket opens. Every setter inherited from the full client funnels
  through the same `request` method, so blocking it there closes all of them —
  including any added later. Tested by calling six setters and asserting the
  device saw no PUT.
- **Rate limit**, default 200 ms between requests. A full poll is nine
  endpoints, so about 1.8 s of wall time. (It was eight until 2026-09-26:
  `display/state` replaced the absent `displaymode` GET, and `/device/hw` was
  added to the slow tier.)
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

The controller half is done (above), on two units. One thing the VMP capture
narrows: after its open, VMP makes no HTTP requests of its own, so there are no
VMP GETs for a poller to contend with — only the websocket and the 8082 stream
it is served (REASONED from one capture). The VMP half needs a person at the
wall:
have VMP connected and doing something visible — a preset recall, a brightness
ramp — and run `CoexMonitor` at 1 Hz alongside. Watch for VMP stuttering,
`Busying` responses, or a dropped VMP connection. If none appear in ten minutes
at 1 Hz, polling at 0.05 Hz is not going to be the thing that breaks a show.

---

## 4. What monitoring is available over GET alone?

Two surfaces. **SNMP is richer on paper**; the HTTP API is easier to consume.
On the one unit where both were read, one MX30, neither covers the other
(OBSERVED): HTTP gives per-card temperature and voltage *values*, cabinet ids
and positions, display state, and — at `/api/v1/device/hw`, first read that
evening — the controller's model and firmware; SNMP gives per-port status bits,
and has to be switched on. An earlier version of this paragraph credited model
and firmware to SNMP alone; see "Identity at `/api/v1/device/hw`", below.

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

### The OID map on an MX30, V1.5.1 — exercised once, 2026-09-26

The first time this project's OID map met hardware. Scope: **one MX30, firmware
V1.5.1, VMP closed by the operator**, SNMP switched on over HTTP for the purpose
and off again afterwards (16:50Z–16:52Z). SNMPv2c with community `public` —
nothing else was ever sent. Asked: walks of the MIB-2 system group
`1.3.6.1.2.1.1` (v2c then v1) after the first enable; a GET of `sysDescr`, a
walk of the system group and **one walk of the enterprise arc
`1.3.6.1.4.1.319`** after the second; a `sysDescr` GET after each disable.
Everything in the table is from that one walk. **Other communities, and v1
against the enterprise arc, are UNKNOWN** — not tried.

The whole walk is
[`tests/fixtures/mx30_snmp_walk.json`](../tests/fixtures/mx30_snmp_walk.json):
every OID with its type and value, real structure and numbers, and synthetic
serial, MAC, IP, controller label, screen name and controller time. Values are
as net-snmp decoded them; **the wire BER encoding of the Counter64 values was
not captured and is UNKNOWN**, which matters to crewbox (below).

**The walk: 170 values, then `endOfMibView` after `…319.10.200.6`** — nothing
is served past it (OBSERVED). 102 INTEGER, 42 STRING, 24 Counter64 and two
empty OCTET STRINGs (the two card names). Gaps: `…10.10.20.4.1.2`,
`…10.10.30.4.1.2`, `…10.20.1.2.1.8`. **44 of the 46 OIDs `snmp.py` transcribes
are served**; the two absent are the per-card receiving-card status forms.

| Item | On the MX30 | Confidence |
|---|---|---|
| `CONTROLLER_MODEL`, `CONTROLLER_FIRMWARE` | `"MX30"`, `"V1.5.1"`; input- and output-card firmware also `"V1.5.1"` | OBSERVED. **The first reading of either from the device**; it confirms the operator's report. No HTTP GET read up to then gave either; `/api/v1/device/hw`, read that evening, gives both (below) |
| `CONTROLLER_NAME`, `_SERIAL`, `_MAC`, `_IP` | served; show-specific, masked in the evidence | OBSERVED. That the name equals `monitor/info.name` was checked before masking and cannot be re-checked from what was kept |
| `CONTROLLER_TIME` | `"YYYY-MM-DD HH:MM:SS"`, one hour ahead of UTC when read | OBSERVED; that UTC+1 is the controller's zone rather than a misset clock is REASONED |
| `CONTROLLER_ROLE` | **1** — "backup" in the document — on a unit whose `/device/backup` is four empty strings and which drove the wall alone. Output- and input-card roles 0 | OBSERVED value, **meaning UNKNOWN. Do not display "backup" from this OID alone** |
| `TEMPERATURE_POINT_VALUE` | 3100 — one point, "Main_board Temperature", status 0 | OBSERVED value. **x100, so 31.00 °C, is REASONED**: HTTP read the main board at 32 °C, at a different time. Whether SNMP resolves finer than 1 °C is UNKNOWN — 3100 carries no sub-degree information |
| `VOLTAGE_POINT_VALUE` | 1156 — one point | OBSERVED value; x100, so 11.56 V, is REASONED — it equals HTTP `mainBoardVoltage` 11.56 exactly |
| `SCREEN_FRAME_RATE`, `SCREEN_SYNC_FRAME_RATE` | 5000, 5000 | OBSERVED; x100, so 50.00 Hz, is REASONED (HTTP `masterFrameRate` 50) |
| `SCREEN_BRIGHTNESS` | the STRING `"50.0"` | OBSERVED; percent is REASONED (HTTP `/device/cabinet` `brightness` 0.5) |
| Fans | `FAN_COUNT` 3; names equal to HTTP `fanInfos` ("Chassis Fan 1", "FPGA Fan", "Chassis Fan 2"); `FAN_STATUS` 0, 0, 0. Undocumented `…10.10.10.6.N.3` = 3799, 2783, 3689 | OBSERVED; `.N.3` = rpm is REASONED, only from closeness to HTTP `fanSpeed` |
| `OUTPUT_SLOT_STATUS`, `INPUT_SLOT_STATUS` | Counter64 `0xFFFFFFFFFFFFFFFE` — bit 0 clear | OBSERVED structure, where the document says 0/1. One bit per slot, LSB = slot 1, the documented enum per bit (0 = connected) is **REASONED**; on that reading slot 1 is present |
| `ETHERNET_PORT_COUNT` | **10**, on output card 1 | OBSERVED — with the ten type-0 `outputStatus` entries over HTTP, ten Ethernet ports on this MX30 (RJ45 is REASONED) |
| `ETHERNET_PORT_STATUS` | Counter64 `0xFFFFFFFFFFFFFFE0` — bits 0–4 clear | OBSERVED structure; per-bit, ports 1–5 up, is REASONED. That is **link, not cabinets**: cards hang on ports 1, 3 and 5 only, and HTTP `linkStatus` was true on exactly the five outputs 2048–2052 |
| `ETHERNET_PORT_SPEED` | 0, with five links up | OBSERVED; meaning UNKNOWN |
| `RECEIVING_CARDS_ONLINE` (`…10.10.30.5.1.4.Y.1`) | INTEGER **24** on ports 1, 3 and 5; on the other seven the STRING **`"ERROR: there are no cabinets in port "`** — trailing space, no port number | OBSERVED. The sum, 72, equals undocumented `…10.10.30.4.1.5` and HTTP `cabinet/count`. SNMP port Y = HTTP `outputID` 2048 + (Y − 1) is REASONED, from which ports carry cabinets and which are linked. Whether it drops when a line is unplugged, as `cabinet/count` did, or stays stale like `monitor/info`, is **UNKNOWN**: SNMP was off through the unplug test |
| Receiving-card temperature / voltage status | The documented per-card forms `…10.10.30.6.N.1.Y.1.M` and `.Y.2.M` are **absent from the walk** (none of 240 possible each; no direct GET was sent). Instead `…10.10.30.6.1.1.Y.1` and `.Y.2` are one Counter64 per port, identical to each other: `0xFFFFFFFFFF000000` on ports 1, 3 and 5, all ones on the other seven | OBSERVED structure. **One bit per card, unused bits set, is REASONED** — the 24 clear bits are on exactly the ports with 24 cards. With every card normal, "0 = normal" cannot be told from "0 = present"; bit order within the 24 is UNKNOWN |
| Inputs | `INPUT_SLOT_COUNT` 1; `INPUT_SOURCE_COUNT` **5**, types `"HDMI2.0 "`, `"HDMI1.4 "`, `"DP1.1 "`, `"3G-SDI "`, `"3G-SDI "` — **strings with a trailing space**, not the document's integer enum; `INPUT_SOURCE_SIGNAL` 1, 0, 0, 0, 0 | OBSERVED, matching HTTP `sourceStatus`. **The internal generator HTTP lists as a sixth source is absent.** Undocumented `…10.10.20.5.1.2.Y.3` = 0, 2, 2, 2, 2, meaning UNKNOWN |
| Screen | `SCREEN_COUNT` 1; width 1536, height 768 (the HTTP canvas); sync type 0. Undocumented `…10.20.1.2.1.1` is the screen name (show data); `.9`/`.10` = 1920/1080; `.11` 0; `.12` 500 | OBSERVED; `.9`/`.10` = the active input's resolution is REASONED; `.11`, `.12` UNKNOWN |
| `OUTPUT_CARD_NAME`, `INPUT_CARD_NAME` | served, as **empty strings** | OBSERVED |
| Light sensor (undocumented `…10.10.10.12.1`, `.2`) | `"ERROR: ..."` strings | OBSERVED |

What a consumer has to handle — the rules are REASONED from the one walk:

- **Probe reachability with an enterprise OID.** The MIB-2 **system group is
  not served**: a v2c GET of `sysDescr` (`1.3.6.1.2.1.1.1.0`) drew error-status
  `noSuchName` — a v1-style error inside a v2c reply, as net-snmp reports it —
  and walks of `1.3.6.1.2.1.1` came back empty (OBSERVED). Other MIB-2 groups
  were not walked (UNKNOWN; do not read this as "MIB-2 is not served"). Ask
  `CONTROLLER_MODEL`, not `sysDescr` or `sysUpTime`. And given a v1-style
  error-status, one absent OID in a multi-varbind GET may void the whole batch
  (REASONED; only a single-OID GET was observed), so keep anything that might
  be absent out of the batch that decides reachability.
- **A string beginning `ERROR:` is absent data.** Nine values carried one:
  seven empty ports in `RECEIVING_CARDS_ONLINE` and the two light-sensor
  values. A column typed as a number must accept one.
- **Scale before display** — temperature, voltage and frame rates by 100.
- **Decode status masks bit by bit; never compare them with 0 or 1.** A mask
  read as one integer is "not 0", so a naive reader calls a present slot
  disconnected and a linked port abnormal.
- **The types differ from the transcription** (OBSERVED). Against `snmp.py` as
  it stood before this walk: `OUTPUT_CARD_FIRMWARE` is a STRING (transcribed
  counter64), `OUTPUT_CARD_ROLE` an INTEGER (string), `OUTPUT_CARD_SERIAL` a
  STRING (int), `OUTPUT_SLOT_STATUS` and `ETHERNET_PORT_STATUS` Counter64
  (int), `RECEIVING_CARDS_ONLINE` INTEGER or STRING (counter64), and
  `INPUT_SOURCE_TYPE` a string that the integer `SOURCE_TYPE` enum cannot map.
  The input-card row matched. Whether the document or the transcription is at
  fault is not established; `snmp.py` carries the per-OID provenance.
- **Undocumented subtrees exist** (OBSERVED existence): `…10.1` (`"V1.0.0"`),
  `…10.10.1.9`–`.11`, `…10.10.10.7`–`.12`, `…10.10.20.4.1.{1,3}`,
  `…10.10.30.1`, `…10.10.30.4.1.{1,3,5}`, `…10.10.30.5.1.4.Y.{2,3.*}`,
  `…10.10.50`, `.60`, `.70` and `…10.200.1`–`.6`. The only readings allowed:
  `…10.10.30.4.1.5` = 72 = the total receiving-card count (REASONED, 3 x 24),
  and `…10.10.30.1` = 1 possibly an output slot count, by symmetry with
  `INPUT_SLOT_COUNT` (REASONED, not asserted). Everything else — including the
  per-port table `…10.10.30.5.1.4.Y.{2,3.1,3.2,3.3}`, whose values are in the
  fixture — has **no established meaning; do not assign one**.

Switching SNMP on and off changed nothing else visible across the eight
snapshot endpoints — **REASONED**, from diffs of snapshots that were not kept
(they held show data) and that could not separate SNMP's effect from the
`colorBeacon` PUTs made in the same window.

**What crewbox's SNMP reader would make of this — REASONED from its code**
(crewbox at `7c8cf6a`, `server/src/video/snmp.ts` and `ber.ts`; read, not run,
and never against hardware). These are handoff items for crewbox's own agent,
not changes made here:

1. **It would show the main board as "3100°C" and grade the unit `warn`.**
   `snmp.ts:372–375` takes `TEMPERATURE_POINT_VALUE` through `asNumber()`
   unscaled; `gradeReading` (`shared/src/video.ts`) falls back to
   `reading.temperature` when no cabinet carries one — always, on the SNMP
   path — and 3100 ≥ `HOT_C` (60). The x100 scale behind this is itself
   REASONED.
2. **It would label the unit a backup.** `snmp.ts:343` sets
   `isBackup = role === 1`; this unit read 1 while driving the wall alone.
3. **Its identity round may fail outright — UNKNOWN whether it does.**
   `OUTPUT_SLOT_STATUS` is in the identity GET (`snmp.ts:322`) and read
   `0xFFFFFFFFFFFFFFFE`. A conformant BER encoding of that Counter64 needs nine
   bytes (a leading `0x00`); `ber.ts`'s `decodeInteger` throws
   `BerError('integer too wide')` above eight, and the socket handler drops a
   `BerError` as "not ours" (`snmp.ts:253`). The request would then time out as
   `identity: no answer`, `answered` 0, and the whole SNMP read would look
   unanswered. If the firmware sends eight bytes it decodes as −2 and nothing
   breaks (the field is unused). The encoding was not captured; if a capture
   ever exists, a fixture should carry the raw BER bytes.
4. **Per-card status asks OIDs this firmware did not serve in the walk.**
   `snmp.ts:482` and `:493` build the documented `.Y.1.M` form — 24 OIDs per
   populated port, in GETs of 16 + 8. What a GET of them returns was never
   observed. If it looks like the `sysDescr` reply (`noSuchName`, varbinds
   echoed as NULL), `session.get` ignores the error-status and each value
   decodes as null, so all 72 cabinets would show `online: true` with no
   temperature status. The per-port masks above are where this firmware keeps
   the information.
5. **The `ERROR:` port string is harmless there.** `asNumber()` makes it
   `undefined`, `bounded()` makes that 0, and the port is skipped
   (`snmp.ts:477–480`) — an empty port renders as empty, which is right.

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
(operator-reported during this pass; read over SNMP later that afternoon), read
after a show.** Every "On an MX40 Pro" statement in the table below stands as
observed on that unit. The MX30 gets its own table and its own section after
the MX40 material, because it differs in ways a consumer has to handle —
starting with how it says an endpoint is absent.

**Update, 2026-09-26 evening — VMP's own reads, and one attended test.** A
capture of VMP opening against the MX30 (§3) exercised 90 paths, several never
read by this project: identity at `/api/v1/device/hw`, display state at
`/api/v1/screen/output/display/state`, the lock at `/api/v1/device/hw/lock`,
and a websocket push channel. They are in their own subsections after the MX30
material. Display state, the one that matters most, was then tested attended.

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
| `GET /api/v1/device/screen/displaymode` | **HTTP 404** — a third absent documented endpoint; display mode is not readable *at this path* on this firmware. `/api/v1/screen/output/display/state`, where the MX30 reports it (below), was never tried on the MX40 Pro | OBSERVED (post-show); the other path UNKNOWN here |
| `GET /api/v1/device/backup` | `{"master": "", "backup": "", "masterName": "", "backupName": ""}` — present, empty on a unit with no redundancy configured | OBSERVED |
| `GET /api/v1/device/multifunc-card/detailinfo` | `[]` | OBSERVED |
| `GET /api/v1/device/hw/mode` | `{"mode": 3}` — the manual documents this as a setter taking `0` send-only / `1` all-in-one; `3` is neither, meaning UNKNOWN | OBSERVED value, UNKNOWN meaning |

Three consequences for a consumer. **Cabinet health lives on the receiving card,
not the cabinet:** on the MX40 Pro `monitor/info.cabinets[].cabinetID` is always
0 and its top-level readings are 0; the join to `/device/cabinet` is
`rvCards[].cabinetID` = `id` (288 of 288). The MX30 populates `cabinetID` and
drops the top-level readings altogether (below), but the same join holds there
(72 of 72) — **so key on `rvCards[].cabinetID` and read health from `rvCards[]`
on both.** **There is no online flag.** This paragraph used to say that a
cabinet present in `monitor/info` with a reporting card is the working
definition of online (REASONED), and its absence how "offline" is expressed.
**Withdrawn, 2026-09-26:** on the MX30 `monitor/info` kept all 72 cabinets,
links up and temperatures reading, with every output line unplugged (OBSERVED;
§4, "Unplugged outputs, and power-off"). Count connected cabinets from
`/api/v1/screen/cabinet/count` or `/api/v1/device/cabinet` instead (OBSERVED on
the MX30; on the MX40 Pro, never tried with a line out). **Every reading is an object,**
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
`link_ok` as well. `interpret_monitor_info()` interprets the monitoring payload
on its own and, since the unplug test, reports only what it can vouch for
(`cabinets_listed`, `links_listed_ok`, never an online count);
`interpret_coex_status()` adds the connected-cabinet sources and is what the
application and survey report.

### The same surface on an MX30, firmware v1.5.1 — OBSERVED, 2026-09-26

Scope for everything in this section: one MX30, firmware v1.5.1 as reported by
the operator at the time (and read over SNMP as `V1.5.1` at 16:51Z, above),
read after a show between 14:44Z and 14:57Z with VMP attachment UNKNOWN,
through the read-only client (two eight-endpoint snapshots seven minutes apart,
ten further GETs, six `curl -i`) and a 300-tick poll. Nothing here generalises
to other MX30s or other firmware until a second unit is read.

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

**Identity over HTTP: the name is a label; the model is at
`/api/v1/device/hw`.** This paragraph was headed "the model is not readable
there" until the evening of 2026-09-26; what follows is kept as the record of
what the afternoon's endpoints carry. On the MX30 `monitor/info.name` is a
single plain alphabetic word — no
`MX`, `CX` or `KU`, no digits — identical in both snapshots and equal to no
other string in the payload (not a screen, group or preset name). It is not
reproduced here; it is the operator's. **The model cannot be read from `name` —
OBSERVED on the MX30, whose name carried none; as a rule for the fleet,
REASONED** — one unit shows `MX40 Pro_<digits>`, the other a plain word. That
the word is an operator-set label is **REASONED**, not established: the API has
an OFFICIAL `PUT /api/v1/device/hw/customname` setter, which makes a label
possible, but nobody read the unit's settings and a firmware default word is
not excluded; that the MX40 Pro's form was a factory default is likewise one
sample. **No field read over HTTP in that pass gave the controller model or
firmware** — over SNMP the MX30 gave both later that afternoon (`"MX30"`,
`"V1.5.1"`, above), and `/api/v1/device/hw` gives both over HTTP (OBSERVED
that evening, below). A key search of every afternoon MX30 payload for model,
firmware, version, serial, product, hardware, software
or build finds version strings only on the receiving cards
(`rvCardInfo.firmware`, `mcuFirmWare`, `ncpVersion`,
`cabinetFileParam.version`), a `screens[0].inputPort.FirmwareVersion{}` whose
every field is empty, and one model-like *number* — `modelId` 5138 (`0x1412`)
on every `/api/v1/device/input` port entry, `screens[0].inputPort.ModelId` and
`canvases[0].outputCardModeId`. It appeared in none of this repository's model
tables, and what it identified was recorded as UNKNOWN. **It is the MX30's model
ID:** `/api/v1/device/hw` gives `name` "MX30" and `modelID` 5138 in one object
(OBSERVED). That the input-port and canvas occurrences carry the same meaning is
REASONED. Before that was known, what told the units apart was the input
complement (six sources — two 3G-SDI, one DP
1.1, one HDMI 1.4, one HDMI 2.0, one internal generator) and the output
enumeration (10 type-0 plus 2 type-1 outputs in `outputStatus[]`), both
consistent with an MX30 (**REASONED**; the model name was operator-reported
during this pass, then read over SNMP and over HTTP). One consequence for
consumers of
`survey --json`: at the time of the contact `survey`, `watch --once` and
`identify` all reported this label as the `model`, because an unrecognised COEX
name fell through to a profile whose name is the input string (OBSERVED,
reproduced against a stub). Treat `model` from a COEX unit as unestablished
until that fix is in the version you run.

| Endpoint | On an MX30, v1.5.1 (SNMP-confirmed later), 2026-09-26 | Confidence |
|---|---|---|
| `GET /api/v1/device` | **HTTP 200, empty body** — absent-or-empty, not 404 | OBSERVED (`curl -i`) |
| `GET /api/v1/device/monitor/info` | Same skeleton as the MX40 Pro, with the differences tabled below: populated `cabinets[].cabinetID`, a nested `cabinets[].cabinet{}` in place of top-level readings, `rvCards[].phyTemperature` and `.signalInterruptCount`, `outputStatus[].type` and `.linkStatus`, `screenSourceStatus[].groupID` and `.linkStatus`, three fans, two controller ports, three new top-level keys. ≈ 97 KB compact for 72 cabinets | OBSERVED |
| `GET /api/v1/device/cabinet` | 72 entries, **34 keys** each (the MX40-like simulator already carries 32 of them); `id` joins `rvCards[].cabinetID` 72/72; descriptive fields unset on this wall; `voltage` unusable (below). ≈ 90 KB compact | OBSERVED |
| `GET /api/v1/screen` | `screens[]` as on the MX40 Pro **plus** `canvases[]` with per-cabinet positions, `layersInWorkingMode[]` naming each layer's source, `canvasInWorkingMode[]`, `pageInfos[]`, an `inputPort{}` block with live signal detail; new keys `cryptoCabinetNum`, `monitorSlotId`. Byte-identical across the two snapshots | OBSERVED |
| `GET /api/v1/device/input/sources` | six entries including an internal generator; 38 keys the MX40 fixture lacks (`defaultEDID{}`, `hdrList`, `gamut`, `dynamicRange`, `bitDepth`, `fiberPortLinkStatus`, `isSupport*`, `metaData{}`, `monitorSlotId`, …) | OBSERVED |
| `GET /api/v1/preset` | same keys as the MX40 Pro; one screen, two presets, `state` false on both | OBSERVED |
| `GET /api/v1/device/snmpstate` | `{"state": false}` — SNMP off on the second unit too, as found. Later, with VMP closed, `PUT {"state": true}` turned it on and this GET read `{"state": true}`; `PUT {"value": true}` answered Success and changed nothing (see the SNMP recommendation) | OBSERVED |
| `GET /api/v1/device/audio` | **present**: `{"enable": false, "source": 65535, "sourceName": ""}` (HTTP 404 on the MX40 Pro) | OBSERVED |
| `GET /api/v1/device/screen/displaymode` | **HTTP 200, empty body** — absent-or-empty (HTTP 404 on the MX40 Pro). Unchanged through a front-panel freeze; display state is at the next row's path instead | OBSERVED (`curl -i`; attended freeze) |
| `GET /api/v1/screen/output/display/state` | `{"mappingState": [{canvasID, enable}], "displayState": [{canvasID, displayMode}]}`; `displayMode` 0 live, **2 frozen** — not read in this pass | OBSERVED (VMP's open; the attended test under "Display state", below) |
| `GET /api/v1/device/backup` | all four strings empty, as on the MX40 Pro | OBSERVED |
| `GET /api/v1/device/multifunc-card/detailinfo` | `[]` — a genuine JSON body, so this firmware *can* say "nothing" with an envelope | OBSERVED |
| `GET /api/v1/device/hw/mode` | `{"mode": 3}` — second unit, second model, same value; meaning still UNKNOWN | OBSERVED value, UNKNOWN meaning |
| `GET /api/v1/screen/cabinet/count` | `{"list": [{"ScreenID": …, "CabinetCount": 72, "CabinetCountInBlackList": 0}]}` — first time exercised by this project | OBSERVED |
| `GET /api/v1/device/input` | `inputPortConfig[]` (six entries, each with `modelId` 5138 and a per-port `hardwareID`) and `testPattern{mode, parameters, txColorSpaceType, txHDRType}`, ≈ 7.6 KB — first time exercised | OBSERVED |
| `GET /api/v1/screen/cabinets`, `…/screen/properties`, `…/screen/displayeffect` | `{}` through the read-only client in 2.0–2.5 ms — consistent with an empty 200, not distinguishable by that client from an empty envelope | absent-or-empty, UNKNOWN which |
| any unknown path | **HTTP 200, `Content-Length: 0`, no `Content-Type`** | OBSERVED (`curl -i`, three paths) |

**Display state: a front-panel freeze and a front-panel blackout are both
visible at `GET /api/v1/screen/output/display/state` — OBSERVED, 2026-09-26;
the value that marks a freeze was seen at two freezes, the one that marks a
blackout at one blackout. This replaces a claim published earlier
the same day (commit `9ed9db0`), and the correction is urgent for crewbox.**

The first attempt got it wrong. With the operator at the wall, the MX30 was
frozen from its front panel for about 30 seconds (about 17:50:30Z to
17:51:00Z, operator-timed) while a read-only watcher diffed every HTTP endpoint
in the table above once a second (the cabinet list every five) and SNMP once a
second for the screen arc and every five seconds for the whole enterprise arc.
Nothing it polled moved at the freeze or the unfreeze: the display-mode GET
stayed an empty 200; screens, layers, inputs, `monitor/info`, presets and the
SNMP screen arc were unchanged. Sensor readings, runtimes and fan speeds were
excluded from the diff; apart from them, the only values that changed in the
whole four-minute window were two undocumented SNMP strings under
`…10.10.70.1`, which drifted at the same rate before, during and after the
freeze (all OBSERVED). That was written up here as "a frozen wall is
invisible" and "a monitor reading HTTP or SNMP cannot tell a frozen wall from
a live one". **Withdrawn: the sweep missed the endpoint that shows it.**
`/api/v1/screen/output/display/state` was not in its list, and at the time
appeared nowhere in this repository's code, tests or documents.

The endpoint came to light in the capture of VMP opening (§3), which read it
twice while the wall was live:

```
{"code":0,"data":{"mappingState":[{"canvasID":2048,"enable":false}],"displayState":[{"canvasID":2048,"displayMode":0}]},"message":"Success"}
```

It was then polled once a second through an attended front-panel freeze, VMP
closed, with a websocket open alongside (18:46:41Z–18:47:40Z; nothing
written — the session is in the list at the top):

| Time (Z) | Websocket push | `GET display/state`, 1 Hz |
|---|---|---|
| 18:46:41.086 | — | `displayMode` 0 |
| 18:46:57.497 | `deviceLastOperatorChange` from the front panel (`ip` 127.0.0.1, an `LCDAPP_` app id) | |
| 18:46:57.600 | `canvasDisplayModeChange {canvasIDs: [2048], value: 2}` | |
| 18:46:58.124 | | `displayMode` **2** — the first poll after the push |
| 18:47:19.971 | `deviceLastOperatorChange`, front panel again | |
| 18:47:20.074 | `canvasDisplayModeChange {canvasIDs: [2048], value: 0}` | |
| 18:47:20.203 | | `displayMode` 0 |

A blackout was then tested the same way, VMP closed, the same read-only
watcher (a 1 Hz `display/state` GET and a websocket with the upgrade and pongs
only); the operator blacked the wall out from the front panel for about 10 s:

| Time (Z) | Websocket push | `GET display/state`, 1 Hz |
|---|---|---|
| 18:57:07.054 | `canvasDisplayModeChange {canvasIDs: [2048], value: 1}` | |
| 18:57:07.893 | | `displayMode` **1** |
| 18:57:17.219 | `canvasDisplayModeChange {canvasIDs: [2048], value: 0}` | |
| 18:57:17.919 | | `displayMode` 0 |

What is established, scoped to one MX30, `hwVersion` V1.5.1:

| Fact | Confidence |
|---|---|
| `displayState[].displayMode` reads **2 for the whole of a front-panel freeze** and 0 before and after it | **OBSERVED** (attended, a 22 s freeze, polled at 1 Hz) |
| 2 = freeze | **OBSERVED on this unit, twice**: the attended poll, and the websocket event `value` 2 during an earlier front-panel freeze in the VMP capture (18:05:16.846Z–18:05:30.142Z), 0 either side |
| 0 = normal (live) | **OBSERVED** |
| 1 = blackout | **OBSERVED once** (attended, a ~10 s front-panel blackout at 18:57Z): `displayMode` 1 on the first poll after the push, the websocket event `value` 1, 0 either side. Until then it was REASONED from the documented COEX enum (0 normal, 1 blackout, 2 freeze) — the COEX HTTP convention, the reverse of the VX4S register |
| The reading is **per canvas**, keyed by `canvasID` (2048, the screen's only canvas here) — the same key as the websocket event | **OBSERVED** |
| `mappingState[].enable`, false throughout | OBSERVED value; meaning UNKNOWN (cabinet-mapping display, by its name, is REASONED) |
| A 1 Hz poller sees the change within its interval: the push arrived ~0.5 s before the next poll | **OBSERVED** once |
| `GET /api/v1/device/hwinfo` also carries a `displayMode` (0 in VMP's three reads, wall live) | OBSERVED value; whether it tracks a freeze is **UNKNOWN** — not polled during one |
| The HTTP endpoints the first sweep polled, and SNMP's screen and enterprise arcs, do **not** move at a freeze | **OBSERVED** (the first attempt, above) — still true, and the reason not to look for display state there |

For a consumer:

- **Read `GET /api/v1/screen/output/display/state`** for display state on COEX
  hardware. It is a plain GET, answered in the same envelope as everything
  else, and needs no long-lived connection.
- Map `displayMode` 0 to normal, 2 to **frozen** and 1 to **blacked out**
  (all three OBSERVED on this unit; 1 from a single blackout), and anything
  else to unknown. A blackout reaches a 1 Hz poller within its interval and
  the websocket at once, exactly as a freeze does (OBSERVED).
- This repository's code still labels 1 REASONED in
  `monitor.DISPLAY_MODE_CONFIDENCE` and in `survey`'s `display_canvases`; the
  label predates the blackout test and is out of date, not a doubt about the
  value.
- **An empty 200, a missing envelope, a missing canvas or an unmapped value is
  unknown, never normal.** On the MX40 Pro this endpoint was never tried.
- Report per canvas: a unit with several canvases could be frozen on one and
  live on another (REASONED from the per-canvas shape; this unit had one).
- `/api/v1/device/screen/displaymode` — the path crewbox's `STATUS_ENDPOINTS`
  asks, and this repository's `MONITORING_ENDPOINTS` asked until this
  correction — is an empty 200 on the MX30 and a 404 on the MX40 Pro. A reader
  that asks only that path shows no display state at all.
- This repository's reader now asks `display/state`:
  `monitor.interpret_display_state` maps it per canvas, and `survey`'s
  `status` carries `display_mode` (0, 1 or 2 when every canvas agrees, `null`
  otherwise), `display` (`"normal"`, `"blackout"`, `"freeze"`, `"mixed"` or
  `"unknown"`) and `display_canvases` (each with its confidence label). A
  `null` `display_mode` still means *unknown*, never *normal*.
- Time freezes from the wire, not from an operator's estimate: in the VMP
  capture the operator's "about 18:05Z, for about 10 s" was ~17 s early and
  ~3 s short against the push events. The first sweep's ~30 s freeze was
  operator-timed.

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
| `outputStatus[]` | 33 entries with `type` and `linkStatus`: type 0 = `outputID` 2048–2057 (10), type 5 = 2058–2077 (20), type 1 = 2078–2079 (2), one type 3 with `outputCardID` 0; `linkStatus` true on 2048–2052 only; cabinets on 2048, 2050 and 2052 (24 each) with `rvCards[].netPortIndex` = `outPutID` 72/72; the only non-zero `status` is 2, on 2053 | `linkStatus` not in the record | **REASONED, UNKNOWN until an attended test:** type 0 = the 10 RJ45 ports, type 1 = the 2 OPT ports, type 5 = 20 fibre-carried channels, type 3 = ?. **2049 and 2051 are backup ports — OBSERVED** from the unit's own `outputPortLinkChange` event (`backupState: true` on 2051 while 2049 went down, during the unplug test below); first recorded here as loop or backup returns (REASONED). `status` code meanings UNKNOWN |
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
reported 72 cabinets, 72 online (it now reports them as listed, not online),
hottest 46 °C, main board 32 °C and 11.56 V,
72 links ok, and `diff_snapshots` keyed the cabinets by the populated
`cabinetID` with zero identity churn (OBSERVED, offline). **That "72 online"
is the false all-clear of correction 4:** it is counted from `monitor/info`,
which reads the same with every output line unplugged, so parsing both
firmwares correctly does not make the online count true.

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
**Firmer, 2026-09-26 evening:** across VMP's 222 requests from two clients the
IDs, read little-endian, formed 222 consecutive values with one constant suffix
and none missing (OBSERVED). So it is a request counter those two clients
share; that it is global to the unit, and so an indicator of *other* clients,
is still REASONED.

### Unplugged outputs, and power-off — OBSERVED, attended, one MX30

Scope: the MX30 above, `hwVersion` V1.5.1, VMP closed, 2026-09-26. The
operator unplugged the output data lines one at a time with the unit left
powered (18:59:52Z–19:02:29Z), then powered it off (19:10:56Z). Watched
read-only: `GET /api/v1/device/monitor/info` every 2 s, a websocket with the
upgrade and pongs only, and a receive-only socket on UDP 54622. Nothing was
written in this stretch.

**What tracked the unplugging (OBSERVED):**

- The websocket's `ScreensCabinetsCountChange`
  `{list: [{ScreenID, CabinetCount, CabinetCountInBlackList}]}` followed every
  stage: 72 → 48 (18:59:52.632Z) → 46 (18:59:59.363Z) → 45 (19:00:40.554Z) →
  36 (19:00:57.122Z) → 24 (19:02:22.130Z) → 0 (19:02:28.764Z). With it came
  `outputPortLinkChange` and `physicalOutputPortLinkChange`
  (`{portLinkState: [{cardId, port, linkState, backupState, type}]}`, per
  port), `alarmCountChange` (`{alarmCounts: [{screenId, count, status,
  subCardStatus}]}`, `count` 3 → 4 → 6, `status` 2), `loopDetectStatusList`, and
  a burst of screen-reconfiguration events at each change
  (`screenCabinetSizeChange`, bit depth, correction,
  `dynamicEngineConfigChange`).
- Over HTTP, `monitor/info` `outputStatus[].linkStatus` went false per output
  within one 2 s poll (2048 at 18:59:50Z, 2049 at 18:59:52Z, 2050 at
  19:00:00Z, all of them by 19:02:29Z), and every output then read `status` 2.
- Read at about 19:03Z, after every line was out: `GET
  /api/v1/screen/cabinet/count` gave `CabinetCount` 0 and `GET
  /api/v1/device/cabinet` gave **0 entries**. That list holds the cabinets
  connected now, not the configured ones; where this document calls it the
  cabinet or topology list, read it that way.
- `backupState: true` on port 2051 while 2049 went down: 2049 and 2051 are
  backup ports.

**What did not — the false all-clear (OBSERVED):** `GET
/api/v1/device/monitor/info` still returned 72 `cabinets[]` with 72 `rvCards[]`,
every `nextCabinetLinkStatus.linkStatus` true and temperatures 39–42 °C, with
nothing connected, at every poll from the last unplug (19:02:28Z) to power-off
— about 8.5 minutes, and it never cleared. Only `rvCardsRuntime` emptied (`[]`,
against 72 entries before). Its per-card readings are last-known values, not
live (REASONED). How long it would have kept them is UNKNOWN. Whether
`rvCardsRuntime` emptying is a usable signal is UNKNOWN too — seen once, on a
list whose `runtime` is not a counter on this firmware — so do not build on it
in place of the counts below. Whether the MX40
Pro's `monitor/info` does the same is UNKNOWN; it was never watched with a line
out.

**Power-off from the front-panel button (OBSERVED unless labelled):** the
operator switched the unit off with its front-panel power button, not at the
mains (operator-reported).

- The last announcement on UDP 54622 was at 19:10:55.824Z; the next, due at
  about 19:10:58.8Z, never came, and none followed. The announcements had
  continued every 3 s through the whole unplugging.
- The websocket ended at 19:10:56.265Z.
- HTTP GETs failed with **connection refused**, not a timeout, from
  19:10:56.633Z (`display/state`) and 19:10:57Z (`monitor/info`) — and kept
  failing with connection refused, never a timeout, on every attempt until the
  watch ended at 19:18:42Z, 7.5 minutes later. Something at the unit's address
  went on answering TCP with resets while HTTP and the announcements were gone.
- So on this unit the front-panel "off" is a **standby** (REASONED, well
  supported): HTTP stops within a second, the announcements stop, the
  websocket closes, and the network stack stays up. A mains cut or a pulled
  cable was not tried; that it would show as timeouts with no ARP reply is
  REASONED and unobserved. The earlier reading of the first refusals as "a
  staged shutdown" is superseded.

For a consumer:

- **Never count cabinets online from `monitor/info`.** Compare
  `/api/v1/screen/cabinet/count` `CabinetCount`, or the `/api/v1/device/cabinet`
  entry count, with the expected number, and read
  `outputStatus[].linkStatus`; on the websocket, `ScreensCabinetsCountChange`
  and `alarmCountChange` carry the same news at once. Temperatures and link
  flags from `monitor/info` describe the last time a card reported, not now.
- **"Controller not serving" is quick to see** (REASONED from the timings
  above): within about a second by websocket EOF or an HTTP refusal, and
  within one missed 3 s interval by the announcements' absence. A passive
  consumer can take two or three missed announcements as its offline dwell,
  which fits this repository's dwell-before-offline rule.
- **Do not read "connection refused" as "unplugged".** On this unit it meant
  front-panel standby, for as long as it was watched. Announcements absent plus
  HTTP refused = standby; HTTP timing out with no ARP reply = unpowered or
  disconnected (REASONED; the second case unobserved).
- The unplugged payloads, with synthetic values, are
  [`tests/fixtures/mx30_unplugged_api.json`](../tests/fixtures/mx30_unplugged_api.json):
  a reader that passes the connected fixture and reports that one healthy has
  this bug.

### Brightness — OBSERVED, attended, one MX30

Same unit and day, VMP closed, 18:51Z–18:55Z.

- **Brightness is a 0–1 fraction** (0.600 read while the front panel showed 60)
  (OBSERVED). It is readable per cabinet at `GET /api/v1/device/cabinet`
  `brightness`, which read back a written value within 1 s (OBSERVED).
- It is pushed: `ScreensCabinetsDisplayChange` `{list: [{screenId, brightness,
  colorTemperature, gamma}]}` about 55 ms after each write, and
  `screenBrightnessChange` `{screenIdList: [<screen UUID>], brightness}` at
  each front-panel step (OBSERVED).
- A front-panel knob turn from 20 % to 60 % and back (18:54:27Z–18:54:48Z)
  produced 72 `screenBrightnessChange` pushes, one per knob step of 0.001 to
  0.008, peaking at 0.600 at 18:54:37.397Z and ending at 0.200, with 70
  `ScreensCabinetsDisplayChange` and 72 `deviceLastOperatorChange`, all from the
  front panel (OBSERVED). A consumer should debounce (REASONED).
- `display/state` did not change: brightness is not display mode (OBSERVED).
- **Every write is attributed.** Each one, this project's or the front
  panel's, was preceded by a `deviceLastOperatorChange` naming the writer: this
  project's client appeared as its own IP with an empty `appID`, the front
  panel as an `LCDAPP_` app id (OBSERVED). Any subscriber can see who changed
  the wall.
- The writes themselves are in
  [`coex-http-api.md`](coex-http-api.md); a read-only consumer makes none. One
  of them, `PUT /api/v1/screen/brightness` — the body `coex.py`'s
  `set_screen_brightness` sends — answered Success and changed nothing
  (OBSERVED), and was followed by `screenBrightnessChange {screenIdList: null,
  brightness: 0}`, though the wall stayed lit. A subscriber that trusted that
  push alone would have read the wall as at 0 (REASONED): cross-check pushed
  brightness against `/device/cabinet`.
- **The first write brightened the wall.** It set an absolute 0.45 on a wall
  at 0.2 — not the 0.5 read at 14:44Z — so the wall went from 20 % to 45 % for
  about 9 s when dimming had been announced (OBSERVED). Anyone testing
  brightness: read first, step relative to that reading, and tell the operator
  which way it will go.

### Identity at `/api/v1/device/hw` — OBSERVED on an MX30, V1.5.1

First read by VMP in the evening capture: four reads, identical except for two
memory counters, 5,698 bytes each, no credentials sent — the first carried no
identifying header at all. It overturns "the model is not readable over HTTP"
for this unit:

| Field | On the MX30 | Confidence |
|---|---|---|
| `name` | `"MX30"` | OBSERVED |
| `modelID` | **5138** (`0x1412`) | OBSERVED. `firmware/list` and `backcard/info` repeat it |
| `hwVersion` | `"V1.5.1"` — the string SNMP returns as `CONTROLLER_FIRMWARE` | OBSERVED; which of the version strings here is "the firmware" is REASONED at best |
| `swVersion`, `mcuVersion`, `fpgaVersion`, `configVersion` | `"1.0.0"`, `"V1.0.0"`, `"V1.0.0.S1.T1.V9"`, `"V1.4.0.1"`; `softVersion.Version` empty | OBSERVED |
| `sn` | a 20-character serial (not reproduced) | OBSERVED |
| `mac` | the unit's MAC — the same value as the announcement's `mac` | OBSERVED |
| `type` | `"G3.5"` | OBSERVED value; meaning UNKNOWN |
| `customName`, `companyName`, `groupName`, `deviceUUID` | present; `customName` carries the operator's label (not reproduced) | OBSERVED |
| `ip`, `IpNetmask`, `IpGateway`, `dhcp`, `WirelessIpAddress`, `uptime` | present; `uptime` in seconds | OBSERVED |
| `mode` | 3 — the same undocumented value `hw/mode` reads | OBSERVED value; meaning UNKNOWN |
| `capability{}` | `capabilityVersion` "V4.1.0"; `snmp`, `artNet`, `NTP`, `inputImageEcho`, `outputImageEcho` true; every `hwMonitor.*Supported` false | OBSERVED values; what each flag gates is UNKNOWN |
| `deviceWorkMode`, `capability.allowChangeWorkMode` | 0, true | OBSERVED |
| `encipher{}` | `vendorID`, `authState` 0, … | OBSERVED; meaning UNKNOWN |
| **`randomPassword`** | an 8-digit string, the same on all four reads, found nowhere else — not in any websocket push | **OBSERVED. Purpose UNKNOWN. Served to an unauthenticated GET** |

**`randomPassword` must be dropped at the client boundary**, before anything
from this endpoint is logged, stored, displayed, diffed or serialised. It is
secret-shaped, its purpose is unknown, and the unit serves it to anyone who can
reach port 8001. In this repository `CoexClient` drops every key whose name
matches `passw(or)?d`, at any depth, before a payload reaches a snapshot, and
`monitor.interpret_hardware_info` copies only named identity fields. The
fixture [`tests/fixtures/mx30_like_api.json`](../tests/fixtures/mx30_like_api.json)
carries `/device/hw` with synthetic values and `randomPassword` as an obviously
fake `"00000000"`, so that tests can assert it is dropped. crewbox should do
the same. `GET /api/v1/device/cloud/status` carries `username`, `password` and
`node` fields, empty on this unit — treat those the same way.

Related identity endpoints, each OBSERVED once on the MX30:

- `GET /api/v1/device/hw/versions` — `controllerSystem{hardWareVersion "A3",
  system "V1.5.1.B2", xserver "V1.5.1", …, sn}`, whose `sn` is 13 digits and
  differs from `hw.sn`; the `mainBoard` strings are empty.
- `GET /api/v1/device/firmware/list` — `deviceModelID` 5138, `deviceVersion`
  "V1.5.1", and a `subcardList` with model IDs 5138 and 41603, versions empty.
- `GET /api/v1/device/backcard/info` — `name` "Mctrl BackCard", `modelId`
  5138, `sn` equal to `hw.sn`, MCU version "V1.5.1".
- `GET /api/protocol/version` → `{"protocolVersion": "V1.1"}`, and
  `GET /api/capability/version` → `{"CapabilityVersion": "V4.1.0"}` (capital
  C) — both outside `/api/v1`.

Scope: `/device/hw` was never requested on the MX40 Pro, so whether it exists
there is UNKNOWN. For a consumer, this is identity with nothing to switch on:
one GET per unit, in the slow tier, with `randomPassword` removed on receipt.

### Other endpoints first read in VMP's open — OBSERVED once, MX30

Beyond identity and display state, the endpoints among VMP's 90 paths that a
monitoring consumer might use, or must not misread:

| Endpoint | On the MX30 | Confidence |
|---|---|---|
| `GET /api/v1/device/hw/lock` | `{"locked": 0, "ip": ""}` before VMP; the lock, once taken, as the push event `{locked: 1, ip}` | OBSERVED; §3, "The HTTP lock" |
| `GET /api/v1/device/hwinfo` | `displayMode` 0; `deviceAvailable{available false, ip ""}`; `deviceControlState{permitState, permitTimeLength, identityState, identityTimeLength}` all 0; `timeEnable` true, `timeSource` 0; `beaconEnable` and `beaconColor{r,g,b}` keys | OBSERVED values; meanings UNKNOWN |
| `GET /api/v1/device/timestamp` | `{"timestamp": <epoch s>}` — matching this project's last write that afternoon (the final `PUT snmpstate`, about 17:54Z), not the clock | OBSERVED value; "time of the last operator write" is REASONED |
| `GET /api/v1/screen/statistic` | cabinets `{total 72, normal 72, warning 0, error 0}` | OBSERVED |
| `GET /api/v1/screen/monitor/alarmcount` | `{count 1, status 2, subCardStatus [{subCardID 8, status 2}]}` — at odds with `statistic` | OBSERVED; meaning of status 2 UNKNOWN. Do not raise an alarm from it alone |
| `GET /api/v1/device/genlock/info`, `…/self-check/result`, `…/hw/timezone`, `…/timezone` | genlock off; `{result: true}`; offset 3600, no DST | OBSERVED |
| `GET /api/v1/device/cabinet/baseinfo` | ~335 KB: per-card `macAddr` and `serialNo` for 72 cards — show data, not for a fixture | OBSERVED |
| `GET /api/v1/device/config-file` | HTTP 200 with **code 3**, "don't have config info" | OBSERVED, twice |
| `GET /api/v1/device/screen` | 15,888 bytes with **no envelope** — seven top-level keys including `subScreens`, 72 cabinets | OBSERVED; the one non-empty unwrapped body seen. A reader that requires `code` must special-case it |
| `GET /api/v1/device/discovery?vendorName=coex`, `/device/hw/networkinfolist`, `/device/output/display`, `/screen/input`, `/device/hw/threed/emitterpara`, `/device/hwscreen` | **empty 200** | OBSERVED; absent-or-empty, UNKNOWN which — six more for the list above |

`monitor/info` was read three times with the skeleton already recorded here,
and the websocket's values below agree with what this document records of it
(one constant `rvCardsRuntime[].runtime`, non-zero `errorBit` constants).

### The websocket push channel, `/api/v1/websocketchannel` — OBSERVED, one MX30

VMP holds one websocket to the unit for as long as it is open, and after its
initial GETs takes what it shows from it (REASONED: it made no HTTP request
after its open, yet the operator moved through its monitoring pages — clicks
that left no trace on the wire). Plain `ws://` on port 8001, no
authentication.

**Handshake (OBSERVED).** `GET /api/v1/websocketchannel` with `Upgrade`,
`Connection`, `Sec-WebSocket-Key` and `Sec-WebSocket-Version: 13` — no Origin,
credentials, subprotocol, extensions or `Application-Id` — answered `101
Switching Protocols`. No compression was negotiated.

**Traffic (OBSERVED).** The server sends an empty **ping every 1.000 s** and
JSON text events; the client answers each ping with an empty pong. No binary
frames. VMP also sent one text frame, 3 ms after the upgrade: its
`Launcher_<uuid>` application id, and nothing more, ever. **The server pushes
without that hello**: in the attended test only the upgrade and pongs were
sent, and controller telemetry, the front-panel operator events and both
display-mode events all arrived (OBSERVED).

**Events (OBSERVED).** Every event is `{"eventData": {...}, "eventSender": str,
"eventType": str}`:

| `eventSender` / `eventType` | When | `eventData` |
|---|---|---|
| `monitor` / `controllerRealTimeInfoChange` | Every 10 s on a free-running grid, plus a runtime tick once a minute | The top of `monitor/info`: `name`, `runtime`, `totalRuntime`, main-board temperature and voltage objects, `backupStatus`, `fanInfos[3]`, `powerMonitorInfos`, `controllerPortMonitorInfos[2]`, `imbLinkStatus`, and a device-local `"YYYY-MM-DD HH:MM:SS"` `timestamp` |
| `monitor` / `cabinetRealTimeInfoChange` | ~100 ms after a controller push, 0–2 per tick; apparently only when a card's reading changed (REASONED) | One receiving card, in `monitor/info`'s `rvCards[]` shape plus `cabinetID`, `rvCardID` (equal) and `netPortIndex` |
| `monitor` / `cabinetsRuntimeInfoChange` | Every 60 s | `rvCardMonitorInfos[72]{cabinetID, rvCardID, runtime, totalRuntime}` — `runtime` one constant on every card, as over HTTP |
| `device` / `deviceLastOperatorChange` | On an operator write | `{ip, appID, timestamp}`, naming the actor: a front-panel action shows as `ip` 127.0.0.1 with an `LCDAPP_<uuid>` app id; VMP's write as VMP's IP and its `Application-Id` header |
| `device` / `deviceLockChange` | When the lock is taken | `{locked, ip}` |
| `device` / `canvasDisplayModeChange` | On a display-mode change | `{canvasIDs: [2048], value}` — 2 at a freeze, 0 at the release (OBSERVED, two freezes) |

- A display change is preceded by ~100 ms by the `deviceLastOperatorChange`
  that names who made it (OBSERVED four times, over two sessions).
- `canvasDisplayModeChange` is **not** pushed on connect (OBSERVED once), so a
  subscriber needs the `display/state` GET for the current value and the push
  only for changes.
- In the VMP session no health field moved — no status, `errorBit`,
  `signalInterruptCount`, link or backup field changed; only fans, voltages,
  temperatures, runtimes and timestamps (OBSERVED). `errorBit[0]` was
  `{type 0, status 1, value 200 or 187}` on every card: not a health flag,
  meaning UNKNOWN.
- Opening the websocket raised no lock or operator event (OBSERVED).
- Later attended sessions, each subscriber sending only the upgrade and pongs,
  added more event types (OBSERVED; §4, "Unplugged outputs, and power-off" and
  "Brightness"): `canvasDisplayModeChange` with `value` 1 at a blackout;
  `ScreensCabinetsCountChange`, `outputPortLinkChange`,
  `physicalOutputPortLinkChange`, `alarmCountChange` and
  `loopDetectStatusList` as output lines were unplugged;
  `ScreensCabinetsDisplayChange` and `screenBrightnessChange` on brightness
  changes. The websocket ended within a second of power-off.

**Kept off the read-only surface — a contract decision (REASONED).** Getting
the events takes transmission: a TCP connect, the upgrade GET and a pong a
second. None of that is a write verb, but its side effects are **UNKNOWN** —
one subscriber for one minute changed nothing visible, and whether the server
drops a client that stops ponging, admits a second subscriber, or records its
subscribers anywhere is untested. The `display/state` GET answers the
monitoring question within the poll interval and holds nothing open. So:
**use the GET.** The websocket is documented here and is not part of
`ReadOnlyCoexClient` or `monitor.py`. If it is ever added, it belongs in a
module of its own with its own tests: the upgrade and pongs only, no text
frames. One of each event type, in the real envelope and shapes with synthetic
values — the freeze pair included — is
[`tests/fixtures/mx30_websocket_events.jsonl`](../tests/fixtures/mx30_websocket_events.jsonl).

**From a passive vantage (REASONED).** The websocket is unicast between VMP's
host and the unit. A zero-transmission observer can decode its events only
where it can see that traffic — on VMP's host, a mirror port or a tap. A third
host on a switch sees none of it.

### The preview stream on TCP 8082 — not a monitoring source

VMP opens one TCP connection to port 8082 as it opens, 1.5 ms after its first
`PUT /api/v1/device/picture`, and receives a continuous preview. OBSERVED from
sizes, hashes and headers only; no image was decoded or kept.

- **Request:** two bare strings with no HTTP version or line ending —
  `GET /Device:<sn>` (the `/device/hw` serial), then `Frame Rate(Hz):60` —
  and nothing more from the client.
- **Reply:** `HTTP/1.0 200 OK`, `Server: Motion/0.1`,
  `Content-Type: multipart/x-mixed-replace; boundary=--BoundaryString`. Each
  part carries `Nova-type: <t>`, `Content-type: image/jpeg` and a
  space-padded `Content-Length`, then one baseline JPEG, **1920x1076**, 4:2:0.
- **Rate:** about **51 Mbit/s**, 12.7 parts a second, paced by the sender; the
  requested 60 Hz is never approached.
- `Nova-type` 2 and 6 equal the `sourceChannel` of the two inputs carrying
  signal (REASONED); `f0`, seen only in the first two parts, is UNKNOWN.

**It cannot show a freeze** (REASONED, from 20 frames and one freeze). During
the front-panel freeze in the capture, the type-2 stream kept cycling through
its four distinct images with no repeat; an encoder this deterministic — the
static type-6 input gave one byte-identical image 190 times — would have
collapsed to repeats had it been showing the frozen output. It shows the
**inputs before processing**, not the wall, and at 51 Mbit/s it is no poll.
Do not use it for monitoring.

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

**The register bus on the MX30 — tried once, VMP closed, 2026-09-26.** With the
operator's go and VMP closed, not during a show:

- **TCP 5200 refused the connection** (`ECONNREFUSED`) at 16:51:56Z, and once
  more later in the session per the operator's log, of which no evidence file
  was kept (OBSERVED). There was no packet capture, so an RST is not
  established — on macOS an ICMP port-unreachable or a rejecting firewall
  produces the same error. **No listener on 5200 at that moment is REASONED.**
- **One read frame on UDP 5201 drew nothing in 3 s** (OBSERVED): 20 bytes,
  address `0x00000000`, length 16 — byte for byte `protocol.read_request(0,
  16)`. **Whether UDP 5201 listens is UNKNOWN**: silence cannot separate "not
  listening" from "dropped" or "wrong frame", and an unconnected socket would
  not have surfaced an ICMP rejection either.
- **Settled for a later moment:** in the evening capture (18:01:28Z, VMP not
  yet connected) one identical read frame to UDP 5201 drew an **ICMP
  port-unreachable** from the unit (OBSERVED). So at that moment nothing was
  listening on UDP 5201 (REASONED from the ICMP). Whether an attached VMP
  changes that is UNKNOWN.
- Ports 15200 and 5203 were not tried.

The Central Control Protocol document covers the MX30 over TCP 5200, UDP 5201
and RS232 (OFFICIAL). **Whether Ethernet central control is a setting, off by
default, or opened while VMP runs is UNKNOWN**, and this is not evidence that
the register bus is closed on COEX hardware — not even on that unit, whose UDP
port stayed unanswered rather than refused. Over Ethernet, only HTTP on 8001,
TCP 8082 (the preview) and SNMP (when switched on) were seen to answer, and the
unit's own announcements leave from UDP 54650 (REASONED from what was tried).
**None of this relaxes the rule above:** a different unit, firmware or VMP
state may listen, and the rule is about what happens when one does.

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
rather than OBSERVED clean. At that point the OID map had met two COEX units and
been exercised on neither. The later session on the same MX30 settled the
mechanism there: with `snmpstate` false a v2c `public` GET of `sysDescr` timed
out (after each of two disables), and with it true the same GET answered at
once (OBSERVED) — so on that unit `false` means no agent answering, not one
refusing an unknown community (REASONED from those two states).
The two earlier attempts stay REASONED, their parameters unrecorded.

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

Added on 2026-09-26 without a schema bump, because they are compatible:
`firmware` on a device (`/api/v1/device/hw` `hwVersion` on COEX — REASONED to
be the firmware), and `display` and `display_canvases` in `status`.
`status.display_mode` keeps its type and meaning — 0 normal, 1 blackout, 2
freeze, `null` unknown — and on COEX hardware now comes from
`/api/v1/screen/output/display/state` (§4, "Display state"). All three values
are OBSERVED on the MX30; the per-canvas label that `display_canvases` gives
value 1 is still `REASONED` in this build, written before the blackout test. On an MX30,
`model_id` is the `/device/hw` `modelID`, 5138.

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
reachability) and raises alerts from them. On COEX hardware a "cabinets
online" series is only as good as its source: count connected cabinets, never
`monitor/info`'s list (§4, "Unplugged outputs, and power-off"), or the
"cabinets dropping" rule never fires (REASONED). And an MX30 in front-panel standby
refuses connections rather than timing out, so a refusal is a missed poll like
any other, not proof the unit is gone (OBSERVED once; §4). A consumer that wants the same
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

## Handoff evidence for crewbox, 2026-09-26

Evidence for crewbox's own agent to apply, under this repository's standing
instruction; nothing in crewbox was changed from here. File and line
references are to crewbox at `7c8cf6a`, read and not run.

1. **Display state — urgent.** crewbox's `STATUS_ENDPOINTS`
   (`server/src/video/coex.ts:128`) asks `/api/v1/device/screen/displaymode`,
   an empty 200 on the MX30 and a 404 on the MX40 Pro, so it cannot show a
   frozen wall. `GET /api/v1/screen/output/display/state` can (§4, "Display
   state"). "Not observable on the MX30" was this document's claim, and it is
   withdrawn. All three values are now OBSERVED on the MX30: 0 normal, 1
   blackout, 2 freeze. The endpoint's shape is in
   [`tests/fixtures/mx30_like_api.json`](../tests/fixtures/mx30_like_api.json);
   the push events, freeze pair included, in
   [`tests/fixtures/mx30_websocket_events.jsonl`](../tests/fixtures/mx30_websocket_events.jsonl).
2. **Zero-transmission inventory** of MX30s, from the announcements on UDP
   54622, 54623, 54624 and 54700 (§1). `discovery.ts`'s header comment says
   NovaLCT and VMP find controllers by broadcasting `rqProMI:` and that
   passive discovery cannot produce an inventory; against the MX30, VMP sent
   no probe at all (OBSERVED, IPv4, one capture). The payload, real layout and
   synthetic values, is
   [`tests/fixtures/mx30_announcement.json`](../tests/fixtures/mx30_announcement.json).
3. **Identity** from `GET /api/v1/device/hw`, with `randomPassword` dropped on
   receipt (§4). The fixture carries it as `"00000000"` so a test can assert
   it never comes out the other side.
4. **`GET /api/v1/device/hw/lock`** as a read-only "held by a control
   application at <ip>" indicator (§3). Never the PUT.
5. **A watcher polling a host that is not a processor.** The capture on the
   VMP host also recorded, from that same host, a poller aimed at another
   address on the segment — not the MX30, and not any processor — every 20.0 s
   from before VMP opened until after it quit, its cadence unchanged by either
   (OBSERVED):
   - 18 SNMPv2c GetRequests, community `public`, each for the same ten OIDs in
     this order: `…319.10.10.1.2`, `.10.10.1.4`, `.10.10.1.6`, `.10.10.1.3`,
     `.10.10.1.5`, `.10.10.10.1`, `.10.10.10.5`, `.10.20.1.1`, `.10.10.20.1`,
     `.10.10.30.2`. None was answered (ICMP port-unreachable).
   - 2.0 s after each GetRequest, four sequential TCP connects to port 8001,
     each refused. No HTTP byte was ever sent.
   - **REASONED, strongly — a capture cannot name the process:** this is
     crewbox's video watcher with a non-processor address configured as a
     processor. The OIDs and their order are exactly the identity GET at
     `snmp.ts:312–323` (`CONTROLLER_MODEL`, `_NAME`, `_SERIAL`, `_FIRMWARE`,
     `_ROLE`, `TEMPERATURE_POINT_COUNT`, `FAN_COUNT`, `SCREEN_COUNT`,
     `INPUT_SLOT_COUNT`, `OUTPUT_SLOT_STATUS`, as `oids.ts` defines them); the
     cadence is `POLL_INTERVAL_MS` 20 000 (`watcher.ts:34`); the 2 s gap is
     `SNMP_TIMEOUT_MS` (`snmp.ts:70`) before the HTTP fallback; and four
     connects are the four `STATUS_ENDPOINTS`.
   - Nothing of the kind reached the MX30: every HTTP request to it carried
     VMP's user agents (OBSERVED).

   Which processor entry holds that address, and why, is for crewbox's agent.
6. **Cabinets online — urgent.** Grading a wall from `monitor/info` cabinets
   gives a false all-clear: with every output line unplugged the MX30's
   `monitor/info` kept 72 cabinets, links up and temperatures reading until
   power-off, ~8.5 minutes later (OBSERVED; §4, "Unplugged outputs, and
   power-off"). crewbox's reader grades from those cabinets: against the
   unplugged fixture it reported **`{"health":"ok","summary":"3 cabinets, 44°C"}`**
   on every poll, all three cabinets `online` by assumption, although the
   fixture's `/device/cabinet` and `screen/cabinet/count` are both 0
   (OBSERVED-in-harness, crewbox `7c8cf6a`, against the fixture, not hardware).
   Connected-cabinet count is at
   `GET /api/v1/screen/cabinet/count` and in the `/api/v1/device/cabinet` entry
   count; output links at `monitor/info` `outputStatus[].linkStatus`, which
   did track the unplugging. The unplugged state, real structure and
   synthetic values, is
   [`tests/fixtures/mx30_unplugged_api.json`](../tests/fixtures/mx30_unplugged_api.json);
   `tests/fixtures/crewbox_harness.mts` takes it as its fixture argument.
   This repository's reader was fixed in the same change; see correction 4 in
   the corrections at the top of this document.
7. **Offline dwell from announcements, and standby versus gone.** At a
   front-panel power-off the announcements stopped at once (OBSERVED); two or
   three missed 3 s announcements make a passive offline dwell (REASONED).
   HTTP then answered connection refused for all 7.5 minutes it was watched —
   the front-panel "off" is a standby with the network up (REASONED) — so a
   refusal is not "unplugged". Announcements absent plus HTTP refused =
   standby; HTTP timing out with no ARP reply = unpowered or disconnected
   (REASONED, unobserved). The announcements kept coming with every output
   line out, so they cannot say whether the wall is connected (OBSERVED).

## Summary for crewbox

| Question | Answer |
|---|---|
| Passive inventory | **Possible on the MX30 — not by overhearing `rqProMI:`. Re-scoped 2026-09-26; this row used to read "Settled: no".** The MX30 **announces itself every 3.0 s** on UDP 54622, 54623, 54624 and 54700 from port 54650: 96 bytes of JSON carrying its MAC, API port (8001) and HTTPS port (9001), the IP being the packet's source; no model or name (OBSERVED, before, during and after VMP). A receive-only listener on those ports learns every announcing MX30 on the segment, transmitting nothing; model, name and serial then take one GET of `/api/v1/device/hw` (REASONED). **On UDP 3800 the earlier findings stand, scoped to that port:** `rpProMI:` replies are **unicast to the requester** (OBSERVED, L2 and L3); the **MX40 sent nothing on 3800 in 30 min** and the **MX30 nothing in 600 s** (OBSERVED); **VMP does not probe on a timer** (OBSERVED) — and against the MX30 it sent **no probe at all**, connecting 5 ms after an announcement (OBSERVED timing; that it used the announcement is REASONED). The broadcast positive control is now run on the MX30's segment (its announcements reached the capture host), not on the MX40's. Whether the MX40 Pro announces is UNKNOWN |
| Discovery destination | Send the **subnet broadcast** for register-bus hardware; the multicast group went unanswered on a UHD Jr (OBSERVED). **An MX40 Pro answers no probe at all** (OBSERVED, eight probes, four destinations), **and an MX30 on v1.5.1 answered none either** (OBSERVED, the same eight; that it does not answer is REASONED from one ~6 s trial) — the probe cannot find COEX units. **The MX30 finds itself for you**, by announcement (row above); otherwise give COEX units their address |
| `rpProMI:` payload | **OBSERVED on one unit:** 8-byte ASCII tail, `App,0161`. It carries **no model ID and no device name** — the earlier "appears to carry model and name" guess was wrong as well as unevidenced. Identify over the register bus, not discovery |
| Trusting a register read | **Four OBSERVED traps** (§5): unimplemented addresses echo the previous response instead of erroring; reads snap to field boundaries; a block must be read from its base in one request; and the receiving-card monitoring block is exactly 0x100 bytes, beyond which a read aliases into another block. Poison-test anything unverified, and never chunk a block read |
| Polling 8001 with VMP attached | **One burst of eight GETs is OBSERVED safe mid-show** (0.1 s, no `Busying`, no effect on a live show) and **ten minutes at 1 Hz is OBSERVED clean on the controller side** (1,791 GETs after the show: 0 errors, 0 `Busying`, `monitor/info` p50 48 ms / p99 64 ms, no drift), **repeated for five minutes on an MX30** (900 GETs: 0 errors, 0 `Busying`, `monitor/info` p50 10.5 ms / p99 15.3 ms for 72 cabinets, no drift). Whether 1 Hz disturbs an operator mid-cue is still REASONED — VMP was not being driven, and its attachment after the show is UNKNOWN on both units. **What VMP itself does** (OBSERVED, one capture): 218 GETs in 0.65 s and four PUTs as it opens, then **no HTTP at all** — one websocket and a ~51 Mbit/s preview on 8082 — so after its open there are no VMP GETs for a poller to contend with (REASONED). Use the read-only client, 10–30 s, back off on code 5 |
| Monitoring over GET | **Rich over HTTP, field names now OBSERVED** (§4): per-card temperature, voltage, link state and error bits — **last-known values in `monitor/info`, not proof a card is connected** (see "Cabinet online / offline"); main-board temperature and voltage; fan rpm; per-input signal via `sourceStatus`. On the MX30, `/api/v1/screen` adds cabinet positions (OBSERVED) and each layer's source (REASONED to be `groupId`, from one discriminating value; that it is the displayed input is REASONED too). On the MX30, **display state** at `/api/v1/screen/output/display/state` and **identity** at `/api/v1/device/hw` (rows below). SNMP was **off** on both COEX units as found; switched on once, on the MX30, it gave identity and per-port status (below). **Nothing** on VX4S / UHD Jr without a control session |
| Frozen or blacked-out wall | **Freeze: observable on the MX30 — a correction, urgent for crewbox.** `GET /api/v1/screen/output/display/state` → `displayState[].displayMode` **2 through a front-panel freeze**, 0 live, per `canvasID` (OBSERVED: a 1 Hz poll through an attended 22 s freeze; the same value 2 marked a second freeze in the websocket event, with VMP attached). **Blackout: observable too — `displayMode` 1** through an attended ~10 s front-panel blackout, on the GET and the websocket (OBSERVED once). This row used to say "Not observable on the MX30". That came from an attended sweep that polled `displaymode` (an empty 200 on the MX30, 404 on the MX40 Pro), the other HTTP endpoints and SNMP, and **missed this endpoint**; it is withdrawn. Nothing that sweep polled moves at a freeze, SNMP included. An empty or unmapped reading is unknown, never normal. Untested on the MX40 Pro |
| SNMP, exercised once | **One MX30, V1.5.1, VMP closed, v2c `public`** (§4, OBSERVED): 170 values; model `"MX30"` and firmware `"V1.5.1"` (first thought the only surface to give either; `/api/v1/device/hw` gives both over HTTP, found later); 44 of 46 transcribed OIDs served. Handle before displaying: the **MIB-2 system group is absent** (`sysDescr` → `noSuchName`; probe with an enterprise OID); temperature, voltage and frame rates **x100** (REASONED); slot, Ethernet and receiving-card statuses are **64-bit bitmasks**, receiving-card status **one mask per port**, the documented per-card `.M` OIDs absent (bit readings REASONED); `"ERROR: ..."` **strings** where numbers belong, including `RECEIVING_CARDS_ONLINE` on empty ports; input types are strings with a trailing space; the internal source is missing; card names are empty strings; **`CONTROLLER_ROLE` 1 on a standalone unit — never show "backup" from it**. The walk, synthetic identifiers, is `tests/fixtures/mx30_snmp_walk.json` |
| crewbox's SNMP reader | **REASONED from its code at `7c8cf6a`, never run against hardware — handoff items:** it would show **"3100°C"** and grade `warn` (no x100 scaling); label the unit a **backup** (`role === 1`); possibly lose the **whole identity round** if the firmware encodes the Counter64 `OUTPUT_SLOT_STATUS` in nine BER bytes (`integer too wide`, swallowed as "not ours") — the encoding is UNKNOWN; and ask per-card `.M` OIDs that were absent from the walk, which, if answered like `sysDescr`, show all 72 cabinets online with no status. The `ERROR:` port string is handled correctly |
| Enabling SNMP | **A write, so never crewbox's.** `PUT /api/v1/device/snmpstate` takes **`{"state": true}`** (OBSERVED, twice each way, read back); **`{"value": true}` answers a Success envelope and changes nothing** (OBSERVED once) — so a Success on a PUT is not confirmation; read back (REASONED). `GET snmpstate` agreed with the agent in every observed check. Both COEX units were found with SNMP off, and the MX30 was left off |
| Absent endpoints | **Differ per firmware.** MX40 Pro: HTTP 404 (OBSERVED). MX30 v1.5.1: **HTTP 200 with an empty body** — no `Content-Type`, no envelope, ~2 ms like everything else (OBSERVED). Test for the missing envelope; treat empty as absent, never as present-and-empty; never take 200 as "exists". Both readers this project knows of mishandled it at the time of contact (§4). Six more MX30 paths answered the empty 200 in VMP's open, among them `discovery?vendorName=coex` and `/device/output/display` (OBSERVED) |
| Identity over HTTP | **Readable on the MX30 at `GET /api/v1/device/hw`** — `name` "MX30", `modelID` **5138**, `hwVersion` "V1.5.1", `sn`, `mac` (OBSERVED, VMP's open). This overturns "no model or firmware field exists over the API" for that unit, and settles 5138 as the MX30's model ID (OBSERVED; its other occurrences meaning the same is REASONED). **The same reply carries `randomPassword`, served unauthenticated, purpose UNKNOWN: drop it on receipt** — never log, store, display or serialise it. `monitor/info.name` stays a label (`MX40 Pro_<digits>` on one unit, a plain word on the other): read no model from it. Never requested on the MX40 Pro (UNKNOWN there). Over SNMP, when it is on, the MX30 gave model and firmware too (OBSERVED) |
| Parsing both firmwares | Join on `rvCards[].cabinetID`; readings from `rvCards[]`; ignore `cabinets[]` top-level and nested `cabinet{}` readings (the nested voltage mirrors `rvCards[]` and double-counts); `signalInterruptCount` is a bare int; count fans, ports and outputs from their arrays; key connector type on `type`, never `id`; never trend by list index |
| Cabinet online / offline | **URGENT for crewbox — `monitor/info` gives a FALSE ALL-CLEAR.** With every output line unplugged, the MX30's `monitor/info` kept 72 cabinets and cards, every `nextCabinetLinkStatus.linkStatus` true and 39–42 °C, for ~8.5 minutes until power-off, never clearing (OBSERVED); "present in `monitor/info` with a reporting card = online" was REASONED and is withdrawn. A reader grading cabinets from it shows an unplugged wall as healthy. Count connected cabinets from `GET /api/v1/screen/cabinet/count` (`CabinetCount` 0 with the lines out) or the `/api/v1/device/cabinet` entry count (0) against the expected number, and read `outputStatus[].linkStatus`, which went false per output within one 2 s poll (all OBSERVED). Announcements do not help here: they continued every 3 s with nothing connected — they show the controller, not the wall (OBSERVED). Untested on the MX40 Pro |
| Controller offline: standby versus gone | At a front-panel power-off the MX30's announcements stopped, the websocket ended and HTTP answered **connection refused** within about a second, and went on refusing — never timing out — for the 7.5 minutes watched (OBSERVED): the front-panel "off" is a **standby** with the network up (REASONED, well supported), so **refused is not "unplugged"**. Tell them apart: **announcements absent + HTTP refused = standby** (OBSERVED once); **announcements absent + HTTP timing out with no ARP reply = unpowered or disconnected** (REASONED — a mains cut and a pulled controller cable were never tried). Two or three missed 3 s announcements make a passive offline dwell (REASONED); telling standby from gone takes one connect attempt, a transmission |
| Brightness | A **0–1 fraction**, per cabinet at `GET /api/v1/device/cabinet` and pushed on change (OBSERVED, MX30). A knob turn is dozens of pushes a second: debounce (REASONED) |
| What VMP writes when it opens | **Four PUTs, OBSERVED once** on the MX30: `hw/systemtime` — **opening VMP writes the controller's clock and zone** (whether the write takes effect is UNKNOWN) — then `device/picture {"type": 0}` twice (preview control, REASONED) and `hw/lock`. None is for a monitor to copy (§3) |
| The HTTP lock | `PUT /api/v1/device/hw/lock` takes it; `GET hw/lock` shows `{locked, ip}` and the websocket pushes `deviceLockChange` (OBSERVED). It outlived VMP's HTTP connection and did not stop a front-panel freeze (REASONED); how it is released, and whether it blocks other clients, are UNKNOWN. **A read-only consumer must never PUT it**; the GET is a useful "held by a control app at <ip>" indicator (§3) |
| Websocket `/api/v1/websocketchannel` | Pushes controller telemetry every 10 s, changed cabinet readings, operator events, **display-mode changes**, brightness changes, and cabinet-count, output-link and alarm-count changes when lines are unplugged — with no hello needed (OBSERVED); lock events too, but those were seen only on VMP's connection, which sent a hello (whether they need it is UNKNOWN). Costs a connect, an upgrade and a pong a second; side effects UNKNOWN. **Kept off the read-only surface: use the `display/state` GET.** Decodable passively only from VMP's host, a mirror or a tap (REASONED) |
| Preview on TCP 8082 | MJPEG of the **inputs**, 1920x1076, ~51 Mbit/s (OBSERVED); cannot show a freeze (REASONED). Not for monitoring |
| Register bus on COEX | **Never open it to a live COEX controller** — unchanged. On the MX30, with VMP closed, TCP 5200 refused a connect (OBSERVED once with evidence; a second refusal is in the operator's log only) and one read frame on UDP 5201 drew nothing in 3 s; in the evening capture a second frame drew an **ICMP port-unreachable** (OBSERVED), so nothing listened on 5201 then, VMP not yet connected. That is one unit at two moments, not evidence the bus is closed on COEX hardware |
| crewbox's watcher | A poller matching crewbox's video watcher was aiming SNMP and 8001 at a non-processor address on the segment every 20 s (REASONED from the capture; [handoff evidence](#handoff-evidence-for-crewbox-2026-09-26)) |
| Consuming it | `survey_network()` / `novasun survey --json`, `schema_version` 1. Leave `allow_register_bus` off |

**Status of the first-day list.** Capturing an `rpProMI:` reply is **done** —
see §2 — and so is the unicast question, which turned out to need a packet
capture rather than a second host. Checking **whether SNMP is enabled** has now
been done on two COEX units, and it was off on both as found (OBSERVED,
2026-09-11 and 2026-09-26). It was then switched on once, deliberately, on the
MX30 with VMP closed, and the OID map was walked (§4): it gives identity —
which `/api/v1/device/hw` was later found to give over HTTP too — and much of
the pane, but only through the quirks listed there, and a read-only consumer
still cannot turn it on. Where it is off, the HTTP GET path
in §4 is the monitoring there is, and its two firmwares' differences are the
thing to build for.

Added to the list by §5: **do not build any register map from an unguarded
sweep.** That applies to crewbox as much as to this repository.
