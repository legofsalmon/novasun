# Controlling NovaStar LED processors: an investigation

**Question.** Can a third party build an application that controls and configures
NovaStar LED processors the way NovaLCT and VMP do, and what would it take?

**Short answer.** Yes for control, and yes for a useful subset of configuration.
Everything NovaLCT and VMP do travels over protocols that are either documented
by NovaStar or already reverse-engineered in public, and the core of it is a
single, stable, easy-to-implement register bus. The gap is not the protocol —
it is the domain data: cabinet definitions, calibration coefficients and screen
topology are where NovaLCT's real value lives, and that part is a long grind
rather than a decode job.

This repository contains the evidence for that answer and a working
implementation of the foundation layer: see [`../README.md`](../README.md) for
the code, [`protocol-register-bus.md`](protocol-register-bus.md) for the wire
format, [`coex-http-api.md`](coex-http-api.md) for the modern JSON API,
[`prior-art.md`](prior-art.md) for what already exists, and
[`sources.md`](sources.md) for every document this was built from.

---

## 1. The landscape: three hardware generations, two protocols

"NovaStar processor" covers three overlapping families, and which one you have
decides which control path you use.

| Generation | Examples | Configured by | Control path |
|---|---|---|---|
| Synchronous sending cards | MSD300, MSD600, MCTRL300, MCTRL500, MCTRL600, MCTRL660 | NovaLCT | Register bus over RS232/USB, TCP 5200 on models with Ethernet |
| Video processors / all-in-ones | VX4S, VX6S, VX1000, MCTRL4K, MCTRL660 Pro, NovaPro | NovaLCT + front panel | Register bus over TCP 5200 (VX Pro series: **15200**) |
| COEX controllers | MX40 Pro, MX30, MX20, MX2000/6000 Pro, CX40 Pro, CX80 Pro, KU20 | VMP | Register bus **and** an official HTTP JSON API on port 8001 |

A fourth family — the asynchronous multimedia players (Taurus/TB series, driven
by ViPlex and NovaLCT-Mplayer) — is a different world: Android-based players
with their own content-management API. It is out of scope here, which matters
mainly because search results for "NovaStar protocol" mix the two freely.

The key structural finding is that **the register bus is the same protocol
across all three generations.** A brightness command captured from a 2014
MCTRL300 over RS232 and one printed in NovaStar's 2025 COEX manual differ only
in the destination fields — same header, same 32-bit register address
`0x02000001`, same additive checksum. That is unusually good news: one codec
covers the whole fleet, and the newest official document doubles as a
specification for the oldest hardware.

## 2. Transports and ports

| Port | Transport | Use |
|---|---|---|
| UDP 3800 | broadcast + multicast `224.224.125.119` | Device discovery (`rqProMI:` → `rpProMI:`) |
| TCP 5200 | register bus | Primary control channel |
| TCP 15200 | register bus | VX Pro-series controllers |
| UDP 5201 | register bus | COEX central-control, connectionless variant |
| TCP 5203 | register bus | Seen in the wild; purpose unconfirmed |
| TCP 8001 | HTTP/JSON | COEX Interface API (official, unauthenticated) |
| UDP 161 | SNMP | COEX monitoring (official MIB) |
| RS232 | 115200 8N1 | MSD300/MCTRL300/MCTRL500, and COEX central control |
| RS232 | 1048576 8N1 | MSD600/MCTRL600/MCTRL660 — note the non-standard baud |
| USB | CDC/virtual COM | MCTRL300 exposes a CP2102 UART; MCTRL4K/R5 are USB-controlled |

Discovery is worth calling out because it is what makes an application feel
native: NovaLCT finds controllers by sending the eight ASCII bytes `rqProMI:`
from **and to** UDP 3800, on the subnet broadcast address and on the multicast
group. Controllers answer with `rpProMI:`; the reply's source IP is what you
connect to. It is implemented in [`../src/novasun/discovery.py`](../src/novasun/discovery.py).

## 3. The register bus

The protocol is not a command set. It is a **memory bus**: every operation is a
read or write of N bytes at a 32-bit register address on a target device, where
the target is addressed hierarchically as *(sending card → output port →
receiving card)*. "Set brightness" is a one-byte write to `0x02000001`. "Read
temperature" is a 256-byte read from `0x0A000000`.

```
55 aa 00 00 fe ff 01 ff ff ff 01 00 01 00 00 02 01 00 00 55 5a
└─┬─┘ │  │  │  │  │  │  └─┬─┘ │  │  └────┬───┘ └─┬─┘ │  └─┬─┘
header│  │  │  │  │  port  rcv io reserved addr  len data checksum
      ack │  src dst device_type            0x02000001    = sum+0x5555
        serno
```

Three consequences follow, and they shape any application built on this:

**It is trivially extensible and completely undiscoverable.** There is no
enumeration, no capability query, no error for reading a register that does not
exist — unknown addresses generally read back as zeros. Everything depends on
knowing addresses. That is why the address map, not the framing, is the real
asset.

**Broadcast is built into the addressing.** Port `0xFF` and receiving-card index
`0xFFFF` mean "every card", which is how a screen-wide brightness change is a
single frame rather than a per-cabinet loop. Writes to broadcast addresses get
no meaningful acknowledgement, so an application must decide between fire-and-
forget speed and per-card confirmation.

**Frame length is not a field.** Only write-requests and read-responses carry a
payload, so a stream reader must buffer 18 bytes and combine the header
direction with the read/write bit before it knows the total length. This is the
single most common place to get an implementation subtly wrong; it is handled in
[`expected_frame_size`](../src/novasun/protocol.py) and pinned by a test.

The full field-by-field specification, the checksum, the address map and the
verified packet vectors are in [`protocol-register-bus.md`](protocol-register-bus.md).

### Confidence in the protocol description

The codec in this repository was validated against **26 frames printed in
NovaStar's own documents and in shipped third-party tools**, spanning 2014 to
2025 and four hardware generations. 24 reproduce byte-for-byte, including their
published checksums. The two that do not are errors in the sources, not in the
decode — both are pinned as tests in
[`../tests/test_protocol.py`](../tests/test_protocol.py) so the discrepancy stays
on the record:

- The COEX manual's one response example is internally inconsistent: the bytes
  it prints sum to `0x5C4A`, but it states `0x5D49`. The difference is exactly
  `0xFF`, so a byte was dropped or mistyped in the manual. Every other frame in
  that document is self-consistent.
- The hard-coded frames in Bitfocus's Companion module carry stale checksums
  that omit the serial-number byte. Harmless in context — the module strips and
  recomputes the last two bytes before sending — but the tables must not be
  copied verbatim into new code.

That is a strong basis: the wire format can be treated as settled, and effort
spent on hardware time should go to the address map instead.

## 4. The COEX HTTP API changes the calculation

For current hardware, NovaStar publishes an official JSON API on port 8001 with
roughly 90 documented endpoints — screens, cabinets, presets, layers, EDID,
colour temperature, 3D LUTs, calibration toggles, thermal compensation, live
monitoring. There is no authentication.

This matters strategically. On COEX hardware you do not need to reverse-engineer
anything to build most of a VMP-like application: cabinet topology, per-cabinet
brightness by ID, preset recall and monitoring are all first-class documented
calls, and they operate on the controller's own model of the screen rather than
on raw registers. The register bus remains useful there for the few things the
HTTP API does not cover and for anything that must be fast.

The practical split for an application targeting mixed inventory:

- **COEX controller present** → drive the HTTP API, fall back to the register
  bus for gaps. Probe port 8001 to detect this.
- **Anything older** → register bus only.

Endpoint map and client in [`coex-http-api.md`](coex-http-api.md) and
[`../src/novasun/coex.py`](../src/novasun/coex.py).

## 5. What is genuinely hard

Reproducing NovaLCT's *control* surface — brightness, blackout, freeze, test
patterns, input switching, presets, monitoring — is a few weeks of work, most of
it hardware time rather than decode work. Reproducing its *configuration*
surface is a different proposition, and it is worth being explicit about why.

**Screen configuration and cabinet mapping.** Telling receiving cards how the
LED panel is physically wired — scan mode, data group order, row/column mapping,
chip driver type — means writing large structured blobs into the sending card's
configuration space and the cards' own parameter areas. The layouts are
per-chipset and per-generation. The `@novastar/screen` package in the sarakusha
project shows the scale: dozens of structures for scan-board capability,
irregular cabinets, module alignment tables and virtual-pixel modes, all
reconstructed from decompiled assemblies. This is where a from-scratch effort
would spend most of its time.

**Calibration data.** Per-LED brightness and chroma coefficients are the
commercial heart of the system: multi-megabyte datasets, a dedicated correction
protocol, and vendor-specific cabinet files. Reading and re-uploading existing
coefficients is plausible; generating them is a camera-and-optics problem, not a
protocol problem.

**Chipset-specific driver parameters.** The decompiled address map references
well over a hundred driver chips, each with its own extended property block
(refresh multiplier, ghost elimination, low-grey compensation). Any feature that
touches "smart settings" needs per-chip knowledge.

**Firmware update.** Technically just writes to program-space registers, and
visible in the address map. Also the one operation that bricks a controller if
it goes wrong. Recommendation: leave it to NovaLCT.

A realistic scope statement for a new application: *complete* on control and
monitoring, *good* on screen-level settings that are already register-mapped
(brightness, gamma, colour temperature, test patterns, low-latency, presets),
*read-only or absent* on physical configuration and calibration, with NovaLCT
kept around for commissioning.

## 6. Recommended architecture

The layering that falls out of the findings, and which this repository already
implements:

```
        application / UI
              │
     device abstraction  ── one interface, several backends
        │            │
  register bus    COEX HTTP        (pick by probing port 8001)
        │
   transports: TCP · UDP · serial
        │
   frame codec + address map
```

Four points that are easy to get wrong and expensive to retrofit:

1. **Model the register bus as a bus, not as a command list.** Expose
   `read(address, length, target)` / `write(address, data, target)` as public
   API, with named operations as a thin layer on top. Every published library
   that hard-codes command blobs — including the Companion modules — has ended
   up limited by that choice. New registers then cost one constant, not a new
   code path.
2. **Treat the address map as data with provenance.** Each entry should record
   whether it came from an official document, from decompiled sources, or from
   your own capture, because the confidence differs by an order of magnitude.
   That is what `registers.CONFIDENCE` is for.
3. **Assume one connection per controller.** Controllers accept a single control
   session in practice; if NovaLCT or VMP is attached, you will be refused or
   silently dropped. Applications that poll monitoring data should own the
   connection and multiplex internally rather than opening sockets per feature.
4. **Keep flash writes deliberate.** Settings live in RAM until an explicit save
   to `0x01000001`. Never wire that to a slider.

**Language.** For a desktop application in the NovaLCT/VMP mould, TypeScript
with Electron or Tauri gives the shortest path, and it can lean on the existing
`@novastar/*` packages for the register bus. The Python implementation here was
chosen for the investigation because it is dependency-free and testable without
hardware; it is a reference and a bench tool, and it is complete enough to be
the backend of a service if you would rather keep the UI in the browser.

**Phasing.** Discovery and identification first, then read-only monitoring
(brightness, temperature, card status), then display control, then screen-level
image settings, then whatever configuration your use case actually needs. The
first two phases are where you validate the address map against your own
hardware, and they cannot break anything.

## 7. Risks

- **A single connection is exclusive.** Design for the case where the operator
  also has NovaLCT open.
- **Broadcast writes are unverified.** Confirm critical state with a read-back
  from one card rather than trusting the write.
- **Register semantics drift between generations.** `DVI_SELECT` input numbering
  is model-specific; the 660 Pro's values will not match a VX4S. Probe, and keep
  per-model overrides.
- **Undocumented registers can be destructive.** The address map includes
  factory reset, encryption and program-space entries. Do not sweep the space
  looking for behaviour on hardware you cannot afford to lose.
- **Flash wear is real** on any register that persists.
- **Provenance of the decompiled address map.** The names and addresses in
  `sarakusha/novastar`'s `@novastar/native` were generated from decompiled
  NovaLCT assemblies, and that package ships the DLLs. The repository is MIT,
  but an MIT header on generated output does not settle the status of the
  original. Using the addresses as facts to verify against your own hardware is
  a materially different position from vendoring generated code or
  redistributing the binaries — worth a decision before you take a dependency,
  and worth legal input if this becomes a product.
- **Support and warranty.** Third-party control of a processor mid-show is a
  liability question as much as a technical one. Blackout and freeze are exactly
  the commands you least want to send by accident.

## 8. What to do next

The decode work is essentially done; the open questions all need hardware:

1. Confirm discovery against a real controller and capture the full `rpProMI:`
   reply, which appears to carry model and name information this implementation
   currently ignores.
2. Verify the address map per model, starting with the read-only registers —
   model ID, serial, name, monitoring block — then brightness read-back.
3. Establish input-source numbering for each processor you care about, since it
   is the one confirmed model-specific register.
4. Capture a NovaLCT session with the bundled Wireshark dissector while doing a
   screen configuration, to size the configuration work properly before
   committing to it.
5. Decide the COEX question: if the target inventory is MX/CX/KU, build on the
   HTTP API and treat the register bus as the compatibility path.

Until hardware is available, the simulator in
[`../src/novasun/simulator.py`](../src/novasun/simulator.py) answers the same
protocol and lets the application layer be developed and tested against it.
