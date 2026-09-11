# Sources

Everything in this repository traces back to one of these. Retrieved August 2026.

## NovaStar documents

| Document | What it gives | Where |
|---|---|---|
| Central Control Protocol Instructions V1.5.0 (2025) | The register bus as currently documented: frame layout, checksum rule, worked hex for brightness, blackout, freeze, presets, low latency, 3D, working mode, output-card display, layer source. Applies to MX40 Pro, MX30, MX20, KU20, CX40 Pro, MX6000 Pro, MX2000 Pro. | [oss.novastar.tech](https://oss.novastar.tech/uploads/2025/09/Central-Control-Protocol-Instructions-V1.5.0.pdf) |
| COEX Series Interface API User Manual (2023) | The HTTP API on port 8001: endpoints, JSON bodies, global response codes. | [oss.novastar.tech](https://oss.novastar.tech/uploads/2023/02/COEX-Series-Interface-API-User-Manual.pdf) |
| RS232 Protocol for Nova M3 Control System V1.9 (2018) | The authoritative field-by-field specification of the register bus, plus command tables for monitoring, power, brightness, gamma, display control, calibration, redundancy, EDID and cabinet size. 71 pages. | Bundled in `sarakusha/novastar` under `doc/` |
| Protocol for MCTRL 660 Pro | Input switching and display control with verified hex, including the device-ID probe. | Bundled in `sarakusha/novastar` under `doc/` |
| VX4S Command Protocol | The VX4S input register `0x0220002D` and its eight input codes, the processor display register `0x02200050` (0 normal, 1 freeze, 2 blackout) and the front-panel lock `0x022000F7`. Every frame checksum-verified. | Bundled in `sarakusha/novastar`; also attached to [companion-module-novastar-controller issue #4](https://github.com/bitfocus/companion-module-novastar-controller/issues/4) |
| Switching input sources protocol of PRO HD | The NovaPro HD input register `0x02200022` and its six input codes. Every frame checksum-verified. | As above |
| NovaPro UHD Jr Specifications V1.5.1 | Connector complement: 1x DP 1.2, 4x DVI, 1x HDMI 2.0 with loop, 2x 12G-SDI with loop, 16x Neutrik Ethernet and 4x optical fibre outputs. | [oss.novastar.tech](https://oss.novastar.tech/uploads/2024/11/NovaPro-UHD-Jr-All-in-One-Controller-Specifications-V1.5.1.pdf) |
| Nova Mars LED SDK User Manual V1.5.2 (2016) | The legacy official Windows SDK's API surface. | Bundled in `sarakusha/novastar` under `doc/` |
| COEX SNMP Protocol Instructions V1.4.0 (2024) | Published MIB for COEX monitoring. | [oss.novastar.tech](https://oss.novastar.tech/uploads/2024/07/SNMP-Protocol-Instructions-V1.4.0.pdf) |
| COEX API online documentation | Browsable version of the HTTP API, endpoint by endpoint. | [api.coex.novastar.tech](https://api.coex.novastar.tech/en/doc-7530630) |
| NovaLCT user manuals | Feature surface to reproduce, and the vocabulary the documents assume. | [oss.novastar.tech](https://oss.novastar.tech/uploads/2022/08/NovaLCT-LED-Configuration-Tool-for-Synchronous-Control-System-User-Manual-V5.4.4.5.pdf) |

## Code

| Project | Licence | Used for |
|---|---|---|
| [sarakusha/novastar](https://github.com/sarakusha/novastar) | MIT | Frame codec cross-check, discovery handshake, the decompiled `AddressMapping` register names, the Wireshark dissector, and the bundled protocol PDFs |
| [@novastar-dev/coex](https://www.npmjs.com/package/@novastar-dev/coex) | MIT | COEX HTTP endpoint paths as served by current firmware |
| [bitfocus/companion-module-novastar-controller](https://github.com/bitfocus/companion-module-novastar-controller) | MIT | Register-bus command tables; the VX Pro port 15200 detail; brightness step tables |
| [bitfocus/companion-module-novastar-coex](https://github.com/bitfocus/companion-module-novastar-coex) | MIT | COEX API usage in practice |
| [dietervansteenwegen/Novastar_MCTRL300_basic_controller](https://github.com/dietervansteenwegen/Novastar_MCTRL300_basic_controller) | MIT | Serial path on MCTRL300 hardware |
| [cedric-uden/Novastar-Controller](https://github.com/cedric-uden/Novastar-Controller) | MIT | Capture-and-diff methodology for TCP 5200 |

## Method

The wire format was reconstructed from the M3 and COEX documents, then checked
against the `sarakusha/novastar` codec and against every hex frame printed in
any of the sources above — 26 frames spanning 2014 to 2025 and four hardware
generations. Those frames are the test suite. A further 19 frames from the VX4S
and PRO HD documents were checksum-verified before their input registers and
select codes were transcribed into the device profiles; all 19 were
self-consistent. Two of the 26 do not match their
own stated checksums; both are source errors and are documented as such in
[`../tests/test_protocol.py`](../tests/test_protocol.py).

## Hardware

Everything above is documentary. One physical source now exists:

| Unit | Identified as | Available since |
|---|---|---|
| NovaPro UHD Jr | model ID `0x6205`, serial `16:04:11:00:c1:c9:2d:00`, discovery tail `App,0161` | 2026-08-26 |
| MX40 Pro (COEX) | reports itself as `MX40 Pro_<digits>`; MAC `54:b5:6c:27:9d:fb` (NovaStar OUI) — on a live-show network with VMP operating it. **One read-only burst of eight HTTP GETs** was sent to it, nothing else; SNMP off; 288 cabinets on 6 outputs | 2026-09-11 |

Driving 30 receiving cards (model `0x4506`, firmware `4.3.0.0`) across output
ports 0, 1, 2 and 4. Findings from it are marked **OBSERVED** and were
reproduced across a power cycle of the unit.

What it settled: the model ID against the decompiled table, the shape of the
`rpProMI:` discovery reply (and that replies are unicast), the receiving-card
presence test, the §3.1.1 monitoring decode, cabinet geometry, the per-connector
signal record layout — and four undocumented firmware behaviours that make naive
register reads return plausible wrong data, described in
[`read-only-monitoring.md`](read-only-monitoring.md#5-two-register-bus-traps-that-make-reads-lie).

What it did **not** settle, despite an earlier version of this note claiming
otherwise: **which input register the UHD Jr implements**. All three documented
candidates are ruled out and the selection state was not found anywhere in the
~20 KB of distinct register content swept. See
[`target-hardware.md`](target-hardware.md#refusing-rather-than-guessing).

What it cannot settle: anything COEX, anything VX4S, and input values in general.

The MX40 Pro settled, by listening: it does not announce itself on UDP 3800,
and VMP does not probe on a timer. By one read-only burst of eight GETs: the
real response shapes of six endpoints (every field name this project had
guessed was wrong), that two documented endpoints are absent (HTTP 404), that
SNMP was off, and that a burst of GETs with VMP attached costs nothing
visible. The SNMP OID map remains **unexercised** — it cannot be exercised
read-only on a unit with SNMP disabled.

Register addresses still marked `derived` in
[`../src/novasun/registers.py`](../src/novasun/registers.py) come from decompiled
sources rather than documentation and should be verified before being relied on;
`OBSERVED` in the same module records which have now been seen on hardware, and
`NOT_IMPLEMENTED` records which were looked for and found absent.
