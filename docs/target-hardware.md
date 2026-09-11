# Target hardware

Ethernet control, three families, USB deferred to a later phase.

| Target | Model ID | Family | Ports | Control path |
|---|---|---|---|---|
| **MX series** (MX40 Pro, MX30, MX20, MX2000/6000 Pro) | n/a | COEX | 2–20 | HTTP JSON on 8001, register bus as fallback. **Does not answer `rqProMI:` discovery** (OBSERVED, MX40 Pro) — must be given its address |
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

Two entries now have independent confirmation.

**MCTRL660 Pro = `0x1107`** is the value in the device-ID response printed in
NovaStar's own *Protocol for MCTRL 660 Pro* document.

**NovaPro UHD Jr = `0x6205` is OBSERVED** — read from a real unit on 2026-08-26,
reproduced across a power cycle. The same read also returned a serial
(`16:04:11:00:c1:c9:2d:00`), a max packet size of 2048 and a communication
protocol word of `02 05`, and the low block at `0x00000000` is internally
consistent with the register map: the `0xA8` marker sits at `+6` and the u16 max
packet size at `+7`, exactly where `registers.py` says they are.

So the decompiled table now agrees with reality on both entries where an
independent check exists — one vendor document, one bench. That is a materially
better basis for trusting the rest than it was, but it is still two of roughly a
hundred. Confirming the model ID of each target processor remains a five-minute
job worth doing first.

Not recognising a model is not a failure mode: `profile_for` returns a usable
profile for anything, and the register bus does not care whether we know what we
are talking to. An unknown model only means a conservative two-port assumption
for enumeration.

## Inputs and outputs, per model

Processors differ in three ways at once — which connectors they have, what byte
selects each one, and how many output ports they drive. All three are data on
the profile rather than assumptions in the code.

| Model | Inputs | Ethernet out | Other outputs |
|---|---|---|---|
| **VX4S** | DVI, HDMI, VGA 1–2, CVBS 1–2, SDI, DP — all switchable | 4 | — |
| **NovaPro UHD Jr** | DP 1.2, HDMI 2.0, DVI 1–4, 12G-SDI 1–2, OPT 1–2, DVI MOSAIC — *codes unknown* | 16 | 4x fibre, HDMI loop, 2x SDI loop |
| **NovaPro HD** | SDI, DVI, HDMI, VGA, DP, CVBS — all switchable | 4 | — |
| **MCTRL660 Pro** | SDI, HDMI, DVI — all switchable | 6 | — |
| **MX40 Pro** and COEX | read from the controller at runtime | 4 | — |

Two consequences worth designing around.

**The same connector is a different byte on each model.** HDMI is `0xA0` on a
VX4S, `0x1B` on a NovaPro HD and `0x05` on an MCTRL660 Pro — written to three
different registers. See
[`protocol-register-bus.md`](protocol-register-bus.md#input-selection-is-per-model-register-included).

**Blackout and freeze are swapped between the VX4S and COEX.** `1` means freeze
on a VX4S and blackout over HTTP. An application that hard-codes either will
eventually black out a screen it meant to freeze.

`Processor` resolves all of this from the profile, so application code stays in
the user's terms:

```python
from novasun.processor import Processor

with Processor.connect("192.168.1.40") as processor:
    for state in processor.inputs():
        print(state.label, state.type, "switchable" if state.switchable else "unknown code")
    processor.select_input("HDMI")   # right register, right value, right path
    processor.freeze()               # right value for this model
```

From the command line:

```bash
novasun inputs 192.168.1.40          # what it has, and what can be switched to
novasun select-input 192.168.1.40 "VGA 2"
novasun outputs 192.168.1.40         # ethernet ports, fibre, loop-throughs
novasun models                       # the whole table
```

### Refusing rather than guessing

Every UHD Jr input is listed but none is switchable, because no input-switching
document for it was found. `select_input` raises `CapabilityUnknown` — naming
the capture workflow — instead of writing a plausible byte. A UI should show
those inputs greyed out rather than hiding them: the connector is real, only our
knowledge of its code is missing, and one capture session fills the gap.

**The gap is now wider than it looked, and that is the finding.** All three
candidate input-select registers are ruled out on a UHD Jr, by reading only.

First, two of them are not backed by storage at all:

| Candidate | Address | Verdict |
|---|---|---|
| VX4S input select | `0x0220002D` | **OBSERVED unimplemented** — 8/8 poison trials echoed |
| NovaPro HD input select | `0x02200022` | **OBSERVED unimplemented** — 8/8 echoed |

Classified with the poison-read discriminator in
[`read-only-monitoring.md`](read-only-monitoring.md#5-two-register-bus-traps-that-make-reads-lie),
which is required here: the whole `0x022000xx` space on this model echoes the
previous response rather than erroring, so a naive read of either address
returns a plausible-looking value. An earlier note in this file, written from
that evidence alone, concluded the third candidate was therefore the answer.
**That conclusion was wrong**, and the correction is worth keeping visible.

`0x02000023` (sending-card `DVI_SELECT`) *is* backed — 0/4 poison trials echoed,
consistently `0x00`. But being backed is not the same as being the input
selector, and a front-panel differential settled it:

| Input selected | `0x02000023` |
|---|---|
| DisplayPort | `0x00` |
| HDMI | `0x00` |
| DVI 1 | `0x00` |

It does not move. **`DVI_SELECT` is not the UHD Jr's input register.**

Worse for anyone hoping to find it by sweeping. A fixed-order differential read
of **131,072 bytes across eleven regions** — every base the address map uses:
`0x00000000`, `0x0008F000`, `0x02000000` (64 KB), `0x02100000`, `0x02200000`,
`0x05000000`, `0x0A000000`, `0x10000000`, `0x13000000`, `0x13010000` and
`0x14000000` — found **nothing whatever that tracks the selected input**. Only
327 of those bytes (0.25%) jitter on their own, so 130,745 were usable ground
for the comparison.

That negative carries a **positive control**, which is what makes it worth
trusting rather than merely reporting. In the same session, with the same
method and the same regions, changing only the *source refresh rate* from 60 Hz
to 50 Hz was detected precisely, to the byte:

```
control: refresh 60 -> 50 Hz, input unchanged     3 bytes changed
  0x13010029   41 -> 4e     frame period 16666 -> 20000 us
  0x13010039   70 -> 88  }  nominal rate 0x1770 (6000) -> 0x1388 (5000)
  0x1301003a   17 -> 13  }
test:    HDMI -> DisplayPort, refresh unchanged    0 bytes changed
```

A sweep that finds nothing proves nothing if it cannot find anything; this one
demonstrably can. The only bytes ever seen to move across an input change
tracked *signal presence*, and were proven to do so by unplugging the source
while leaving the input selected.

A second, wider sweep was then run against the bases the address map does *not*
describe. Probing every top-level base `0x00000000`-`0x1F000000` with the poison
discriminator found **26 backed bases**, four of them carrying structured
non-zero data this project had never recorded:

```
0x03000000  a8 03 00 00 40 03 00 00 d8 02 00 00 70 02 00 00   (936, 832, 728, 624)
0x09000000  ff ff ff ff 00 00 ...
0x0a000000  00 06 01 00 01 01 01 02 01 00 03 01 01 3c 00 05
0x13000000  c0 00 a8 00 00 00 0a 00 ff 00 ff 00 ff 00 00 00
```

Sweeping 8 KB at each of those 26 bases across an input change again found
**zero** differing bytes, with its own positive control detecting the same three
refresh bytes.

**The coverage of both sweeps was, however, badly overstated when first
recorded, and the correction matters more than the original claim did.**

Counting *distinct responses* rather than bytes requested tells a different
story. Reading sequentially past a region's real extent does not fail — it
returns the previous response (see
[`read-only-monitoring.md`](read-only-monitoring.md#5-two-register-bus-traps-that-make-reads-lie)).
So a 64 KB sweep of a 1 KB region reads that 1 KB once and echoes it 63 times:

| Sweep | Bytes requested | Distinct 1 KB responses | Distinct bytes |
|---|---|---|---|
| Eleven mapped regions | 131,072 | 16 | 16,384 (12.5%) |
| Twenty-six backed bases | 212,992 | 9 | 9,216 (4.3%) |

`0x02000000` was swept as 64 KB and returned **one** distinct kilobyte. Twenty-one
of the twenty-six bases in the second sweep returned nothing but their
predecessor's payload.

**The honest figure is 20 distinct kilobytes across both sweeps combined** —
`0x00000000`, `0x02000000`, `0x02100000`, `0x02200000`, `0x03000000` (3 KB),
`0x05000000` (3 KB), `0x0A000000` (2 KB) and `0x13010000` (8 KB).

The negative result survives, and its positive control is unaffected: the
differential compared like against like, and the refresh change was detected in
content that was genuinely returned. What does not survive is the *strength*
originally claimed for it. **Input selection is absent from ~20 KB of distinct
register content covering the display, screen-config, input, software,
monitoring and video-source spaces** — not from 212,761 bytes, and not from
anything like the whole address space.

Recording bytes requested as though they were bytes observed is precisely the
provenance failure this repository exists to avoid, and it went unnoticed for a
day. Any future sweep must count distinct responses, and
[`capture-workflow.md`](capture-workflow.md) says so.

**An unresolved contradiction, flagged for the next session.** The 21 echoing
bases were classified `implemented` by the poison discriminator using 16-byte
reads — they returned a consistent all-zero value that tracked no poison. Yet at
1024 bytes they echo. Short and long reads at the same address behave
differently, and only the short-read result went through the discriminator. Until
that is resolved, treat "backed base" claims above `0x0A000000` as **UNKNOWN**:
the 16-byte probe may itself have been measuring something other than storage.

**Scope of the negative, stated honestly.** Both sweeps read the sending card
only (`device_type = SENDING_CARD`), and sampled 8 KB at each base rather than
the whole 16 MB behind it. Input selection could still live deeper inside a
base, behind a different device type, or in a write-only register that reads
back as something else. What is ruled out is that it sits in the first 8 KB of
any base this firmware backs — which includes every location this project's
address map describes, and every location a reasonable person would look next.

So on a UHD Jr, input selection is currently **UNKNOWN**, and `CapabilityUnknown`
is not a placeholder to be removed shortly — it is the correct and evidenced
state. Finding the register needs a NovaLCT capture (see
[`capture-workflow.md`](capture-workflow.md)) showing what the vendor software
writes when *it* switches an input, because the state is evidently not where
this repository was looking.

What the same investigation *did* establish is per-connector signal state:
`0x13010000` is an array of 32-byte records giving resolution and refresh for
each input. That is documented in
[`read-only-monitoring.md`](read-only-monitoring.md#per-connector-signal-state----observed).
It answers "does HDMI have a signal, and at what resolution", which is useful,
but it does not answer "which input is live".

This is the pattern to keep as the map grows: connectors are facts about the
hardware, select codes are facts about the protocol, and the two are established
separately.

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
reflects it. Its response *shapes* were originally reconstructed from NovaStar's
manual and from what published clients expect, and **they were wrong on every
endpoint** — cabinets and inputs are bare lists, not wrapped; there is no
`connected`, no `online`, and no numeric temperature; presets are grouped per
screen. A single read-only pass over a live **MX40 Pro** (2026-09-11) settled
the real shapes, and the simulator now emits them by default, field for field —
see [`read-only-monitoring.md`](read-only-monitoring.md#over-coex-http-get).

Two documented endpoints, `/api/v1/device` and `/api/v1/device/audio`, answered
a bare **HTTP 404** on that unit — not a `NotSupport` (code 6) envelope — and the
simulator withholds them by default for the same reason. Whether an
*undocumented* path draws code 6 is still **DERIVED** and unobserved. Scope: one
unit, one firmware.

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
