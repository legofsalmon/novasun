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
| [prior-art.md](docs/prior-art.md) | Existing libraries and official interfaces, with licensing |
| [sources.md](docs/sources.md) | Every document and repository this was built from |

## The code

A dependency-free Python implementation of the foundation layer: frame codec,
discovery, transports, a high-level client, a COEX HTTP client, a CLI, and a
simulator so the application layer can be built without hardware.

```
src/novasun/
  protocol.py    frame codec — encode, decode, checksum, stream framing
  registers.py   register addresses, each tagged with its provenance
  transport.py   TCP and serial byte transports, stream reassembly
  discovery.py   UDP 3800 broadcast discovery
  client.py      Controller: read/write registers, display control, monitoring
  coex.py        COEX HTTP API client (port 8001)
  simulator.py   a fake controller that speaks the same protocol
  cli.py         command line front end
```

### Try it without hardware

```bash
python -m novasun.simulator --port 5200 &

python -m novasun info 127.0.0.1
python -m novasun brightness 127.0.0.1 60
python -m novasun test-pattern 127.0.0.1 blue
python -m novasun status 127.0.0.1
python -m novasun monitor 127.0.0.1
```

### Against real hardware

```bash
python -m novasun discover
python -m novasun info 192.168.1.40
python -m novasun read 192.168.1.40 0x02000001 1 --receiving-card
```

Or from Python:

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

42 tests. The protocol suite replays 26 frames printed in NovaStar's own
documents and in shipped third-party tools, spanning 2014 to 2025 and four
hardware generations; 24 reproduce byte-for-byte including their published
checksums, and the two that do not are pinned as documented source errata. The
client suite runs end to end against the simulator.

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
