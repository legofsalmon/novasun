# Target hardware

Ethernet control, three families, USB deferred to a later phase.

| Target | Model ID | Family | Ports | Control path |
|---|---|---|---|---|
| **MX series** (MX40 Pro, MX30, MX20, MX2000/6000 Pro) | n/a | COEX | 2–20 | HTTP JSON on 8001, register bus as fallback |
| **VX4S** (and VX4S-N) | `0x6107` / `0x612A` | Video processor | 4 | Register bus, TCP 5200 |
| **NovaPro UHD Jr** | `0x6205` | Video processor | 16 | Register bus, TCP 5200 |

That spread is the reason the device abstraction is not optional: MX-class
hardware is HTTP-first and does not appear in NovaLCT's model table at all,
while the VX4S and UHD Jr are register-bus devices that NovaLCT manages
directly. An application covering both needs one interface over two protocols.

## Identification

`novasun identify HOST` works out which it is and which path applies. It probes
the HTTP API first — definitive for MX, and fails fast when the port is closed —
then falls back to a model-ID read on the register bus.

```
$ novasun identify 192.168.1.40
192.168.1.40
  model        NovaPro UHD Jr  (0x6205)
  family       video-processor
  output ports 16
  control      register-bus
  register bus TCP 5200
  serial       00:1a:2b:3c:4d:5e:00:00
  note         4K all-in-one; 16 output ports; also drivable from V-Can
```

`novasun models` lists the whole table.

## Where the model IDs come from

Model ID is a two-byte read of register `0x00000002`. The values and port counts
in [`../src/novasun/devices.py`](../src/novasun/devices.py) come from the
`NSCardType` enum and `GetPortNumber` function generated from decompiled NovaLCT
assemblies.

One entry has independent confirmation: **MCTRL660 Pro = `0x1107`**, which is
the value in the device-ID response printed in NovaStar's own *Protocol for
MCTRL 660 Pro* document. The decompiled table agrees with the vendor's bytes on
the one entry where both exist, which is a reasonable basis for trusting the
rest — but only until you can check your own hardware. Confirming the model ID
of each target processor is a five-minute job on day one and worth doing first.

Not recognising a model is not a failure mode: `profile_for` returns a usable
profile for anything, and the register bus does not care whether we know what we
are talking to. An unknown model only means a conservative two-port assumption
for enumeration.

## What differs between the families

**COEX (MX).** Cabinet topology, presets, layers and monitoring are documented
HTTP calls operating on the controller's own model of the installation. Cabinets
have IDs; you ask for the list and address them by ID. Nothing needs
reverse-engineering, and the register bus is only for gaps.

**VX4S and UHD Jr.** Register bus only. Brightness, blackout, freeze, test
patterns and monitoring work identically to any other sending card — the same
registers, the same broadcast addressing. Input switching is the one register
known to be model-specific: the values in `InputSource` are confirmed for the
MCTRL660 Pro and should not be assumed to hold for a VX4S. Establishing the
input numbering per processor is on the day-one list.

The UHD Jr's 16 output ports matter for enumeration: a cabinet-level UI that
assumes four ports will silently miss three quarters of the installation.

## Developing against all three without hardware

Both simulators model their family properly, so the application can be built
before any hardware exists:

```bash
novasun simulate register --model uhd-jr --cards-per-port 4   # 16 ports x 4 cards
novasun simulate register --model vx4s                        # 4 ports x 2 cards
novasun simulate coex --model "MX40 Pro"                      # HTTP API on 8001
```

The register-bus simulator models a real chain — a sending card, its output
ports, and a receiving card at each position, each with its own registers. It
answers `ack = TIMEOUT` for a card that is not there (which is what real
hardware does, and how topology gets discovered) and stays silent for a sending
card that is not on the chain (which is what terminates enumeration). Per-card
monitoring values differ, so a per-cabinet display does not look uniform when it
should not. `--latency` adds a per-request delay to exercise timeout handling.

A flat register file would let per-cabinet addressing bugs pass unnoticed; this
will not, which is the point.

The COEX simulator holds real state: set the brightness and the next `GET`
reflects it. Its response *shapes* are reconstructed from NovaStar's manual and
from what published clients expect — confirm the exact field spellings against
hardware before an application depends on them. Endpoints it does not implement
answer `NotSupport` (code 6), which is also what real firmware does.

## Phasing

1. **Now, no hardware.** Application layer against both simulators. Complete the
   COEX client from the published API documentation — mechanical and immediately
   useful, since MX is the priority.
2. **Day one with hardware.** Confirm model IDs and port counts; confirm the
   discovery reply; establish input-source numbering per processor. All
   read-only except the last.
3. **Week one.** Differential capture against NovaLCT for whatever the register
   map is missing — see [`capture-workflow.md`](capture-workflow.md).
4. **Later.** USB and RS232. The framing is identical, so `FrameReader` already
   decodes it; what is missing is a serial transport wrapper and a pseudo-
   terminal MITM for capture.
