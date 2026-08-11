# Making NovaLCT and VMP document themselves

The address map is the asset, and the vendor software knows all of it. This is
the workflow for extracting that knowledge once you have hardware: observe a
session, decode it, change one setting, diff. Every unnamed register that comes
out is a gap in the map with a worked example attached.

All of it is implemented in this repository. None of it needs Wireshark.

## Day one bring-up

Before any of the capture work, confirm the basics. All read-only, nothing here
can change the state of a screen.

```bash
python -m novasun discover                       # UDP 3800 broadcast probe
python -m novasun info 192.168.1.40              # model, serial, name, chain walk
python -m novasun status 192.168.1.40            # brightness, blackout, freeze, pattern
python -m novasun monitor 192.168.1.40           # temperature, humidity, voltage
python -m novasun coex snapshot 192.168.1.40     # is this a COEX box? then dump it
```

Record what the discovery reply actually contains — the current implementation
keeps only the source address and prints the rest as a raw tail, and there is
probably model and name information in there worth parsing properly.

## Observing a session

Three ways, best first.

### 1. The proxy — no capture tooling at all

Sit between the vendor software and the controller. NovaLCT connects to a
controller by IP, so pointing it at your machine instead is all it takes.

```bash
python -m novasun proxy 192.168.1.40 --log session.jsonl
```

It listens on 5200, forwards to the real controller on 5200, decodes everything
passing through and prints it live:

```
1786463966.974171 -> read  0x00000002 CONTROLLER_MODEL_ID dev=0 port=0x00 rcv=0x0000 [2 bytes]
1786463966.975041 <- read  0x00000002 CONTROLLER_MODEL_ID dev=0 port=0x00 rcv=0x0000 0711
1786463966.976168 -> write 0x02000001 GLOBAL_BRIGHTNESS   dev=1 port=0xff rcv=0xffff 4c
```

Why this beats packet capture: no elevated privileges, no libpcap, no
promiscuous mode, no network tap, no snaplen to truncate a frame, and it works
when the vendor software runs on the same machine as the proxy. It also recovers
the byte stream directly, so there is nothing to reassemble.

Frames are forwarded first and decoded afterwards, so observation can never
delay or corrupt the session being watched — which matters when the far end is
a live screen.

The one thing it cannot see is traffic that does not go through it: UDP
discovery, and any device the software reaches directly. Run a capture alongside
if you need those.

### 2. Packet capture

Record with whatever you have, then decode here. `dumpcap` ships with Wireshark;
`tcpdump` is everywhere else.

```bash
# Linux / macOS
sudo tcpdump -i any -w before.pcap 'tcp port 5200 or tcp port 15200 or udp port 3800'

# Windows, from the Wireshark install directory
dumpcap -i 1 -w before.pcapng -f "tcp port 5200 or udp port 3800"
```

Then:

```bash
python -m novasun capture decode before.pcapng      # every frame, named
python -m novasun capture report before.pcapng -o report.md
```

The parser reads pcap and pcapng (either byte order, gzipped or not), handles
Ethernet, raw IP, Linux SLL and loopback, reassembles TCP streams and skips
retransmissions. Wireshark is not required to analyse a file it produced.

### 3. Wireshark, for live exploration

Still the right tool when you want to click around a session rather than script
it. Use the dissector from `sarakusha/novastar`: drop `novastar.lua` and
`addressMapping.lua` into your Wireshark plugins directory and it will label
register operations in the packet list.

Capture in Wireshark, save, and decode the same file here when you want to diff
it.

## The differential method

This is the part that actually produces new knowledge.

1. Start the proxy with a log: `python -m novasun proxy 192.168.1.40 --log a.jsonl`
2. In NovaLCT, do the thing you want to understand — once, cleanly.
3. Stop. Restart with `--log b.jsonl`.
4. Do the identical thing, changing exactly one setting.
5. Diff:

```bash
python -m novasun capture diff a.jsonl b.jsonl
```

```
2 register(s) differ:

  0x02000001  ALL_BRIGHTNESS / GLOBAL_BRIGHTNESS       4c -> e6
  0x02000101  SELF_TEST_MODE                           02 -> 04
```

Writes are compared, reads ignored — polling differs run to run and only adds
noise. Registers present in only one capture are reported separately from
registers whose value changed.

Discipline matters more than tooling here. One variable per pair of runs,
identical navigation through the UI, and the same starting state. Two changes at
once and you cannot attribute either.

## Naming what you find

`capture report` marks every address it cannot name as **unknown** and lists
them at the end. To cut that list down, import an external address map:

```bash
python -m novasun names import ../novastar/packages/native/generated/AddressMapping.ts
```

That reads the enum generated from decompiled NovaLCT assemblies by the
`sarakusha/novastar` project — 567 distinct addresses — and caches it in
`~/.novasun/addressmap.json`.

**It is imported, not vendored, on purpose.** The names are enormously useful
for reading your own captures, and using them that way keeps them as facts you
verify against hardware. Committing generated output from decompiled assemblies
into a product is a different position, and this repository does not take it on
your behalf. See the provenance note in
[`investigation.md`](investigation.md#7-risks).

When you have confirmed what a register does on your own hardware, promote it
into [`../src/novasun/registers.py`](../src/novasun/registers.py) with a
`CONFIDENCE` entry recording how you established it. That file is the durable
output of all this; the captures are scaffolding.

## The COEX equivalent

On COEX hardware the same method works over HTTP, and it is easier:

```bash
python -m novasun coex snapshot 192.168.1.10 -o before.json
# ... do something in VMP ...
python -m novasun coex snapshot 192.168.1.10 -o after.json
python -m novasun coex diff before.json after.json
```

Expect noise from monitoring fields that drift on their own — temperatures,
uptimes. Read the diff for what changed structurally.

## The serial gap

Nothing above helps on a USB or RS232 connection, which is how MCTRL300-class
hardware is driven. The equivalent is a pseudo-terminal in the middle:

- Linux/macOS: `socat -d -d PTY,link=/tmp/fake,raw TCP:...` or a `socat` pair
  with a logging filter.
- Windows: `com0com` to create a linked pair, plus a port monitor.

Then decode the captured bytes with `FrameReader` from
[`../src/novasun/transport.py`](../src/novasun/transport.py) — the framing is
identical, only the transport differs. This is not wrapped in a command yet; if
your target hardware is USB-only it is the next tool worth building.

## What is deliberately not here

**A register scanner.** Sweeping the address space to see what responds is the
obvious next tool and the wrong one. The map includes factory reset, encryption
and program-space registers, reads on some addresses have side effects, and
differential capture answers the same question with the vendor software doing
the dangerous parts correctly. If you build one anyway, keep it read-only, give
it an explicit range rather than a default sweep, and never point it at hardware
you cannot afford to replace.

**Replay.** Recording a NovaLCT configuration sequence and replaying it from
your own code is genuinely useful and genuinely risky — a half-replayed
configuration write can leave a receiving card in a state NovaLCT itself cannot
recover. Worth building later, behind a dry-run default, once the register map
is better understood.

## Safety

- Blackout and freeze are the two commands you will test most and least want to
  send by accident. Bench rig separate from anything in service.
- Settings live in RAM until an explicit save to `0x01000001`. Never wire that
  to a slider, and remember flash wear is real.
- Assume one control connection per controller: if NovaLCT is attached, your
  own client will likely be refused. The proxy exists partly to sidestep this —
  it is the one arrangement where both can be connected at once.
