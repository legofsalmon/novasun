# Sources

Everything in this repository traces back to one of these. Retrieved August 2026.

## NovaStar documents

| Document | What it gives | Where |
|---|---|---|
| Central Control Protocol Instructions V1.5.0 (2025) | The register bus as currently documented: frame layout, checksum rule, worked hex for brightness, blackout, freeze, presets, low latency, 3D, working mode, output-card display, layer source. Applies to MX40 Pro, MX30, MX20, KU20, CX40 Pro, MX6000 Pro, MX2000 Pro. | [oss.novastar.tech](https://oss.novastar.tech/uploads/2025/09/Central-Control-Protocol-Instructions-V1.5.0.pdf) |
| COEX Series Interface API User Manual (2023) | The HTTP API on port 8001: endpoints, JSON bodies, global response codes. | [oss.novastar.tech](https://oss.novastar.tech/uploads/2023/02/COEX-Series-Interface-API-User-Manual.pdf) |
| RS232 Protocol for Nova M3 Control System V1.9 (2018) | The authoritative field-by-field specification of the register bus, plus command tables for monitoring, power, brightness, gamma, display control, calibration, redundancy, EDID and cabinet size. 71 pages. | Bundled in `sarakusha/novastar` under `doc/` |
| Protocol for MCTRL 660 Pro | Input switching and display control with verified hex, including the device-ID probe. | Bundled in `sarakusha/novastar` under `doc/` |
| VX4S Input Switching protocol · PRO HD input source protocol | Model-specific input switching. | Bundled in `sarakusha/novastar`; also attached to [companion-module-novastar-controller issue #4](https://github.com/bitfocus/companion-module-novastar-controller/issues/4) |
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
generations. Those frames are the test suite. Two of the 26 do not match their
own stated checksums; both are source errors and are documented as such in
[`../tests/test_protocol.py`](../tests/test_protocol.py).

No NovaStar hardware was available while this was written, so nothing here has
been confirmed against a live controller. Register addresses marked `derived` in
[`../src/novasun/registers.py`](../src/novasun/registers.py) come from decompiled
sources rather than documentation and should be verified before being relied on.
