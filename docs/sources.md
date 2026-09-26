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

Everything above is documentary. Three units have now been seen — one on a
bench, two on live-show networks:

| Unit | Identified as | Available since |
|---|---|---|
| NovaPro UHD Jr | model ID `0x6205`, serial `16:04:11:00:c1:c9:2d:00`, discovery tail `App,0161` | 2026-08-26 |
| MX40 Pro (COEX) | reports itself as `MX40 Pro_<digits>`; MAC `54:b5:6c:27:9d:fb` (NovaStar OUI) — on a live-show network with VMP operating it. **Three read-only bursts of eight HTTP GETs** (two mid-show, one five hours later), a few extra GETs, eight unanswered discovery probes and six unanswered SNMP GETs were sent to it, plus a ten-minute 1 Hz read-only poll after the show (1,791 GETs, three endpoints); nothing else. SNMP off; 288 cabinets on 6 outputs. **Firmware UNKNOWN** — never read, never recorded | 2026-09-11 |
| MX30 (COEX) | identified by a MAC in the NovaStar OUI and by the operator, who also reports the **firmware as v1.5.1** — nothing read over HTTP carries the controller's model or firmware, so both are operator-reported, not OBSERVED. `monitor/info.name` is a plain word, not `MX30_<digits>` (that it is an operator-set label is REASONED). Read-only and unattended after a show, wall still lit, VMP attachment UNKNOWN: **two pings and about 950 HTTP GETs** (two eight-endpoint snapshots seven minutes apart, ten further GETs, six `curl -i`, a 300-tick 1 Hz poll of three endpoints = 900, and ~24 from `survey`/`watch`/`identify` whose outcomes were not kept), two unanswered SNMP GETs and eight unanswered discovery probes; nothing else — no TCP 5200, no PUT. SNMP off; 72 cabinets on 3 outputs | 2026-09-26 |

Driving 30 receiving cards (model `0x4506`, firmware `4.3.0.0`) across output
ports 0, 1, 2 and 4. Findings from it are marked **OBSERVED** and were
reproduced across a power cycle of the unit.

What it settled: the model ID against the decompiled table, the shape of the
`rpProMI:` discovery reply (and that replies are unicast), the receiving-card
presence test, the §3.1.1 monitoring decode, cabinet geometry, the per-connector
signal record layout — and four undocumented firmware behaviours that make naive
register reads return plausible wrong data, described in
[`read-only-monitoring.md`](read-only-monitoring.md#5-four-register-bus-traps-that-make-reads-lie).

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
visible. A second burst 35 minutes later settled that `monitor/info` reorders
its cabinets on every call, that runtimes are seconds at 60 s granularity, and
what a quiet wall's readings do over half an hour (±1 °C, ±0.1 V). The SNMP OID map remains **unexercised** — it cannot be exercised
read-only on a unit with SNMP disabled.

The MX30 settled, read-only and unattended after a show (2026-09-26): that a
second COEX firmware spells "absent" differently — **HTTP 200, empty body, no
envelope**, for documented and made-up paths alike, where the MX40 Pro answered
404 — so a status code alone proves nothing about an endpoint; that
`monitor/info.name` can be an operator label, so **no model can be read from
it** (OBSERVED on the MX30, whose name carried none); that `/api/v1/device/audio`,
`/api/v1/screen/cabinet/count` and `/api/v1/device/input` answer on this
firmware, and what they look like; that `hw/mode` reads 3 on a second model;
that runtimes step in 60 s on a second unit; and that a 1 Hz poll of three
endpoints at 72 cabinets costs nothing visible (900 requests, p50 10.5 ms, no
drift, no error). Its SNMP was off too and it left eight discovery probes
unanswered, so the OID map stays unexercised and discovery stays unanswered on
every COEX unit met.

What it cannot settle: **the controller's model or firmware over HTTP** — no
field read carries either, and the one model-like number that recurs across
payloads (`modelId`) identifies UNKNOWN what, so both facts rest on the
operator; whether the five empty-200 endpoints are absent or present-but-empty;
whether the name is operator-set (REASONED from the OFFICIAL `customname`
setter, not read back); whether anything on that segment broadcasts, because
the **packet-level positive control for the passive listener is still unrun**
(tcpdump needs root on the observing host, which was also multi-homed); and
whether VMP was attached during the session. The raw payloads carry show data —
a chosen name, screen and preset names, UUIDs, cabinet ids — and are not
retained in the repository; their structure, with synthetic values, is
`tests/fixtures/mx30_like_api.json`.

Register addresses still marked `derived` in
[`../src/novasun/registers.py`](../src/novasun/registers.py) come from decompiled
sources rather than documentation and should be verified before being relied on;
`OBSERVED` in the same module records which have now been seen on hardware, and
`NOT_IMPLEMENTED` records which were looked for and found absent.
