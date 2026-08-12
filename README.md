# novasun

Talking to NovaStar LED processors — an investigation into how NovaLCT and VMP
control their hardware, and a working implementation of the protocol layer a
third-party application would need.

**Start with [`docs/investigation.md`](docs/investigation.md)** for the findings.
The short version: everything NovaLCT and VMP do travels over a single
register-bus protocol that is documented by NovaStar for current hardware and
already reverse-engineered for older hardware; current COEX controllers also
expose an official, unauthenticated JSON API. Control is very achievable.
Configuration — cabinet mapping, calibration coefficients — is where the real
work is.

| Document | Contents |
|---|---|
| [investigation.md](docs/investigation.md) | Findings, architecture recommendation, risks, next steps |
| [protocol-register-bus.md](docs/protocol-register-bus.md) | Wire format, addressing, register map, worked examples |
| [coex-http-api.md](docs/coex-http-api.md) | The port 8001 JSON API on MX/CX/KU controllers |
| [target-hardware.md](docs/target-hardware.md) | The MX / VX4S / UHD Jr targets, identification, phasing |
| [capture-workflow.md](docs/capture-workflow.md) | Day-one bring-up, and how to make NovaLCT document itself |
| [read-only-monitoring.md](docs/read-only-monitoring.md) | For observers: what is safe to poll, what SNMP gives, what is still unknown |
| [prior-art.md](docs/prior-art.md) | Existing libraries and official interfaces, with licensing |
| [sources.md](docs/sources.md) | Every document and repository this was built from |

## The application

```bash
pip install -e .
novasun serve 192.168.1.40        # then open http://127.0.0.1:8770
novasun serve --discover          # or let it find them
```

A local service holding connections to several processors, with a browser UI
over it. Capability-aware: a control appears only if the connected model
supports it, inputs whose select code is unestablished are shown greyed with
the reason, and blackout / freeze / test-pattern are confirmed before they are
sent. Unreachable is a state with a retry, not an error dialog — including
`in-use`, which is what you see when NovaLCT is already holding the session.

State lives in `novasun.app.state` and the HTTP service only exposes it, so a
different front end (Electron, Tauri, native) can import the state layer
directly and skip the web server:

```python
from novasun.app import Application

with Application() as app:
    app.add("192.168.1.40")
    app.execute("192.168.1.40", "brightness", percent=60)
    print(app.snapshot())
```

Nothing that writes flash, resets to factory defaults or touches program space
is reachable from this layer. Those registers exist and `Controller` can reach
them, but they do not belong beside a brightness slider.

## The code

A dependency-free Python implementation of the foundation layer: frame codec,
discovery, transports, a high-level client, a COEX HTTP client, a CLI, and a
simulator so the application layer can be built without hardware.

```
src/novasun/
  app/           the application: multi-device state, HTTP service, browser UI
  protocol.py    frame codec — encode, decode, checksum, stream framing
  registers.py   register addresses, each tagged with its provenance
  transport.py   TCP and serial byte transports, stream reassembly
  discovery.py   UDP 3800 broadcast discovery
  client.py      Controller: read/write registers, display control, monitoring
  devices.py     model IDs, per-model inputs/outputs, capabilities, identification
  processor.py   one interface over both paths, resolving per-model differences
  coex.py        COEX HTTP API client (port 8001), snapshot and diff
  proxy.py       MITM proxy: log NovaLCT's conversation with a controller
  capture.py     pcap/pcapng parser, register summaries, differential analysis
  names.py       register naming, with an optional externally-imported map
  simulator.py   a fake controller: real chain topology, real error behaviour
  coexsim.py     a fake COEX controller serving the HTTP API
  survey.py      read-only view of a whole network, in a versioned JSON shape
  passive.py     zero-transmission listener for discovery traffic
  monitor.py     read-only polling: a client that cannot write, rate limited
  snmp.py        COEX SNMP OID map (no client -- use your own)
  cli.py         command line front end
```

### Try it without hardware

Both target families are simulated, so the application layer can be built before
any hardware arrives:

```bash
python -m novasun simulate register --model uhd-jr &   # or vx4s, mctrl4k, ...
python -m novasun simulate coex &                      # MX-class HTTP API

python -m novasun info 127.0.0.1
python -m novasun brightness 127.0.0.1 60
python -m novasun test-pattern 127.0.0.1 blue
python -m novasun status 127.0.0.1
python -m novasun monitor 127.0.0.1 --port-index 15 --card-index 2
```

The register-bus simulator models a real chain — ports, receiving cards with
their own registers, `ack = TIMEOUT` for cards that are not there — so
per-cabinet addressing mistakes fail here rather than on site.

### Surveying a network, read-only

```bash
python -m novasun survey --json      # discovery + status, no writes
python -m novasun watch 192.168.1.10 # poll one COEX controller read-only
python -m novasun listen             # observe, transmitting nothing at all
```

For consumers that observe rather than control — see
[`docs/read-only-monitoring.md`](docs/read-only-monitoring.md), which documents
the serialised contract and is explicit about which facts are official, derived,
reasoned or still unknown.

### Working out what a device is, and what it has

```bash
python -m novasun identify 192.168.1.40     # model, family, ports, which path
python -m novasun inputs 192.168.1.40       # connectors, and which are switchable
python -m novasun outputs 192.168.1.40      # ethernet ports, fibre, loop-throughs
python -m novasun select-input 192.168.1.40 "VGA 2"
python -m novasun models                    # the whole device table
```

Processors differ in what connectors they have, what byte selects each one, and
how many ports they drive — "switch to HDMI" is `0x0220002D = 0xA0` on a VX4S but
`0x02200022 = 0x1B` on a NovaPro HD, and blackout/freeze values are *swapped*
between the VX4S register and the COEX HTTP API. `Processor` resolves all of it
from the model profile:

```python
from novasun.processor import Processor

with Processor.connect("192.168.1.40") as processor:
    print(processor.describe())
    processor.select_input("HDMI")   # right register, right value, right path
    processor.freeze()               # right value for this model
```

Where a connector exists but its select code has not been established — every
input on the NovaPro UHD Jr — switching raises `CapabilityUnknown` rather than
writing a guessed byte at a live screen. See
[`docs/target-hardware.md`](docs/target-hardware.md).

### Against real hardware

```bash
python -m novasun discover
python -m novasun info 192.168.1.40
python -m novasun read 192.168.1.40 0x02000001 1 --receiving-card
```

### Learning the address map from the vendor software

Put the proxy between NovaLCT and a controller, drive the same action twice with
one setting changed, and diff — the register that moved is the one that setting
drives. No Wireshark involved; full workflow in
[`docs/capture-workflow.md`](docs/capture-workflow.md).

```bash
python -m novasun proxy 192.168.1.40 --log a.jsonl   # then again to b.jsonl
python -m novasun capture diff a.jsonl b.jsonl
```

```
2 register(s) differ:

  0x02000001  ALL_BRIGHTNESS / GLOBAL_BRIGHTNESS       4c -> e6
  0x02000101  SELF_TEST_MODE                           02 -> 04
```

Packet captures work the same way — `capture decode`, `report` and `diff` all
read pcap and pcapng directly, so a file recorded with tcpdump or Wireshark
needs no Wireshark to analyse.

### From Python

```python
from novasun import Controller, TestPattern, discover

for device in discover():
    print(device.address, device.detail)

with Controller.connect("192.168.1.40") as controller:
    print(controller.probe())
    controller.set_brightness(60)
    controller.set_test_pattern(TestPattern.WHITE)
    print(controller.read_receiver_monitoring(port=0, index=0))
```

The named methods are conveniences. The protocol is a register bus, so
`controller.read(address, length, target)` and `controller.write(address, data,
target)` are first-class API — anything in the address map is reachable without
waiting for a wrapper.

## Tests

```bash
pip install pytest && python -m pytest
```

210 tests. The protocol suite replays 26 frames printed in NovaStar's own
documents and in shipped third-party tools, spanning 2014 to 2025 and four
hardware generations; 24 reproduce byte-for-byte including their published
checksums, and the two that do not are pinned as documented source errata. The
client, proxy and COEX suites run end to end against the simulators, and the
capture tests synthesise pcap and pcapng files to the file-format specifications
rather than using committed fixtures.

## Status and caveats

No NovaStar hardware was available while this was written. The frame codec is
well corroborated; register addresses marked `derived` in `registers.py` come
from decompiled sources rather than documentation and should be confirmed on
your own hardware before you rely on them.

Some registers are destructive — factory reset, flash writes, program space.
Do not sweep the address space looking for behaviour on a controller you cannot
afford to lose, and see the risk list in
[`docs/investigation.md`](docs/investigation.md#7-risks) before pointing any of
this at a live screen.
