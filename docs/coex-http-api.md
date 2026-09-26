# The COEX HTTP API

Current-generation NovaStar controllers — MX40 Pro, MX30, MX20, MX2000/6000 Pro,
CX40 Pro, CX80 Pro, KU20 — expose an official JSON API on **TCP 8001**. This is
the layer VMP-class functionality is built on, and it is documented by NovaStar
rather than reverse-engineered.

Client: [`../src/novasun/coex.py`](../src/novasun/coex.py).

## Basics

- HTTP only, port 8001. The controller's IP is on its LCD home screen.
- **No authentication.** Anything that can reach the port can reconfigure the
  screen. Treat control networks accordingly.
- JSON bodies; `PUT` for setters, `GET` for getters.
- Every documented response is `{"code": 0, "data": ..., "message": "Success"}`.
  Non-zero codes: `1` InvalidParam, `2` SendFailed, `3` InternalErr,
  `4` AnalysisFailed, `5` Busying, `6` NotSupport, `39` CfgFileNotExist,
  `41` NonStandardFileName. Neither unit read so far has produced a code 6; both
  answer an absent path *outside* the envelope, and differently (next two
  bullets).
- **OBSERVED on an MX40 Pro (2026-09-11):** three documented GETs,
  `/api/v1/device`, `/api/v1/device/audio` and
  `/api/v1/device/screen/displaymode`, answered a bare **HTTP 404** — no JSON
  envelope, no code 6. `/api/v1/device/backup`, `/multifunc-card/detailinfo`
  and `/hw/mode` answered (the last reading `{"mode": 3}`, a value the manual
  does not list). An undocumented path was never tried on this unit, so what it
  does for one is UNKNOWN.
- **OBSERVED on an MX30 (firmware v1.5.1, operator-reported; 2026-09-26):**
  an absent path answers **HTTP 200 with `Content-Length: 0`** — no body, no
  JSON envelope, no `Content-Type` header (a real endpoint carries
  `Content-Type: application/json`). Three made-up paths did this, and so did
  `/api/v1/device` and `/api/v1/device/screen/displaymode`, both seen raw with
  `curl -i`. Three more — `/api/v1/screen/cabinets`, `/api/v1/screen/properties`,
  `/api/v1/screen/displayeffect` — came back as `{}` through the read-only
  client, which is consistent with the same empty 200 but is not something that
  client can tell from a genuine `{"code":0,"data":{}}`; for all five, *absent*
  versus *present but empty* is UNKNOWN. Latency does not separate them either:
  the empty replies took 2.0–2.5 ms, the same band as `hw/mode` or
  `cabinet/count`. **The only discriminator is the body** — zero bytes, no
  envelope — not the status code. `/api/v1/device/audio` *did* answer on this
  unit (`{"enable": false, "source": 65535, "sourceName": ""}`), `hw/mode` again
  read `{"mode": 3}` (second model, same undocumented value, meaning still
  UNKNOWN), and `/api/v1/screen/cabinet/count` and `/api/v1/device/input` were
  exercised for the first time; see the endpoint map.
- **Consequence for any consumer: handle both spellings of "absent", and never
  read an empty 200 as "exists".** This project's own `CoexClient.request`
  turns an empty body into `{}` (`json.loads(b or b"{}")`), so `coex snapshot`
  on the MX30 reported `device: {}` with no error — exactly the misreading to
  avoid. A `res.json()` on the same reply throws instead. Test for the missing
  envelope explicitly.
- **Neither COEX unit answered `rqProMI:` discovery** on UDP 3800 — unicast,
  broadcast or multicast. OBSERVED on the MX40 Pro; the MX30 left eight probes
  unanswered in one ~6 s trial on 2026-09-26, which is consistent with the same
  behaviour (REASONED from one trial). A COEX controller has to be given its
  address. The response *shapes* of the GETs that answered are recorded in
  [`read-only-monitoring.md`](read-only-monitoring.md#over-coex-http-get) and
  differ from what the manual and published clients led this project to expect.

```
PUT http://192.168.1.10:8001/api/v1/device/screen/displaymode
{"value": 1}
```

## Why this changes the build

The register bus addresses hardware; this API addresses the controller's own
*model* of the installation. Screens and cabinets have IDs, presets have names,
layers have sources. Retrieving the cabinet list and setting brightness on three
specific cabinets by ID is two documented calls — the equivalent over the
register bus means knowing the topology yourself and issuing per-card writes.

For an application targeting COEX hardware, build here first and drop to the
register bus only for gaps. Probe port 8001 to decide at runtime; `coex.probe()`
does this.

## Endpoint map

Paths as documented in the *COEX Series Interface API* manual and as used by the
published `@novastar-dev/coex` client. Roughly 90 endpoints exist; this is the
useful core.

### Display and screens

| Method | Path | Purpose |
|---|---|---|
| PUT | `/api/v1/device/screen/displaymode` | `0` normal, `1` blackout, `2` freeze. **Not readable back**: a GET drew HTTP 404 on the MX40 Pro and an empty 200 on the MX30 (OBSERVED, both) |
| GET | `/api/v1/screen` | Screen list with IDs |
| GET | `/api/v1/screen/cabinets` | Cabinets per screen — came back `{}` through the read-only client on the MX30; absent or empty, UNKNOWN which |
| GET | `/api/v1/screen/cabinet/count` | `{"list": [{"ScreenID", "CabinetCount", "CabinetCountInBlackList"}]}` per screen — OBSERVED once, on the MX30 (72 and 0); never tried on the MX40 Pro |
| PUT | `/api/v1/screen/brightness` | Brightness by screen ID list |
| PUT | `/api/v1/device/screen/video/bitdepth` | Output bit depth |
| PUT | `/api/v1/device/screen/input` | Select input source |
| PUT | `/api/v1/device/screen/controller/pattern/test` | Controller test pattern |

### Cabinets

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/device/cabinet` | All cabinet information |
| PUT | `/api/v1/device/cabinet/brightness` | `{"idList": [...], "ratio": 1.0, "nit": 1000}` |
| PUT | `/api/v1/device/cabinet/rgb/brightness` | Per-component brightness |
| PUT | `/api/v1/device/cabinet/gamma` | Gamma |
| PUT | `/api/v1/device/cabinet/colortemperature` | Colour temperature |
| PUT | `/api/v1/device/cabinet/mapping` | Cabinet mapping display on/off |
| PUT | `/api/v1/device/cabinet/testpattern` | Receiving-card test pattern |
| PUT | `/api/v1/device/cabinet/prestoreimage` | No-signal image behaviour |
| PUT | `/api/v1/device/correctionop/cabinets/gamut` | Colour gamut |
| PUT | `/api/v1/device/correctionop/cabinets/thermacal/*` | Thermal compensation |

### Input

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/device/input/sources` | Available sources |
| GET | `/api/v1/device/input` | Per-port configuration: `{"inputPortConfig": [one entry per source, incl. the internal one], "testPattern": {mode, parameters, txColorSpaceType, txHDRType}}`; each port entry carries `logicId`, `modelId`, `hardwareID`, `edidInfo`, `hdrParameter`, `colorSpaceType`, `range`, `videoStreamConfig`, `sdpSourceInfo`, `dhcpConfig` and more — ~7.6 KB for six ports. OBSERVED once, on the MX30; never tried on the MX40 Pro. What `modelId` identifies is UNKNOWN |
| PUT | `/api/v1/device/input/{id}/edid` | Resolution and frame rate |
| PUT | `/api/v1/device/input/{id}/colorspace` | Colour space override |
| PUT | `/api/v1/device/input/{id}/colourgamut` | Gamut override |
| PUT | `/api/v1/device/input/{id}/range` | Quantisation range |
| PUT | `/api/v1/device/input/{id}/hdrmode` | HDR mode |
| PUT | `/api/v1/device/input/internalsource` | Internal test source |
| PUT | `/api/v1/device/input/{shadow,highlight,saturation,contrast,hue,reset}` | Colour adjustment |

### Presets, device, monitoring

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/preset` | Preset list |
| PUT | `/api/v1/preset/current/update` | Apply preset |
| PUT | `/api/v1/preset/update` | Modify preset |
| GET | `/api/v1/device` | Device information — **not returned by either unit read: HTTP 404 on the MX40 Pro, an empty HTTP 200 on the MX30 (OBSERVED, both)**. Identity falls back to `monitor/info.name`, which is a label, not a model (see `hw/customname`) |
| GET | `/api/v1/device/audio` | `{"enable", "source", "sourceName"}` — HTTP 404 on the MX40 Pro, **present on the MX30** (`false`, `65535`, `""`), OBSERVED |
| GET | `/api/v1/device/monitor/info` | Real-time monitoring |
| GET/PUT | `/api/v1/device/hw/mode` | `0` send-only, `1` all-in-one. Both units read back `{"mode": 3}`, a value the manual does not list; meaning UNKNOWN |
| GET/PUT | `/api/v1/device/hw/deviceengineeringdocdata` | Export / import project file |
| PUT | `/api/v1/device/hw/customname` | Rename controller (OFFICIAL). This is why `monitor/info.name` cannot carry the model: the MX40 Pro reported `MX40 Pro_<digits>`, the MX30 a single plain word (OBSERVED) — an operator label, most likely set here (REASONED). **No model can be read from `name`** (OBSERVED on the MX30, whose name carried none; as a rule, REASONED), and no other field read over HTTP gives the controller model or firmware — a numeric `modelId` 5138 recurs across the MX30's payloads, but what it identifies is UNKNOWN |
| PUT | `/api/v1/device/hw/systemtime`, `/timezone`, `/time/enable` | Clock |
| GET/PUT | `/api/v1/device/snmpstate` | SNMP on/off |
| GET | `/api/v1/device/multifunc-card/detailinfo` | Multifunction card status |
| PUT | `/api/v1/device/backup`, `/backup/verify` | Primary/backup |
| PUT | `/api/v1/device/hw/colorBeacon` | Identify the controller |

Screen-level equivalents exist for most cabinet operations under
`/api/v1/screen/...`, along with 3D LUT import, colour correction, canvas
mapping and scheduling.

## Adjacent official interfaces

- **Central Control Protocol** — the register bus over TCP 5200, UDP 5201 or
  RS232, documented for the same controllers. Fewer capabilities, but the same
  commands work on much older hardware. See
  [`protocol-register-bus.md`](protocol-register-bus.md).
- **SNMP** — NovaStar publishes a MIB for COEX monitoring, which is the right
  choice if the goal is integration with existing monitoring rather than
  control.

## Caveats

- Endpoint availability varies by model and firmware, **and so does the way
  absence is spelled.** `NotSupport` (code 6) is documented as the normal
  answer; a plain HTTP 404 is what an MX40 Pro actually returned for three
  documented endpoints, and an **HTTP 200 with an empty body and no envelope**
  is what an MX30 on v1.5.1 returned for absent documented and undocumented
  paths alike (both OBSERVED; scope one unit each). Handle all three, key on
  the body rather than the status, and treat an empty 200 as *not there* until
  a populated read proves otherwise — the same firmware answers a genuinely
  empty list with a real envelope (`multifunc-card/detailinfo` → `[]`), so the
  two are distinguishable.
- Two payloads are large and scale with the wall: `/api/v1/device/cabinet` was
  342 KB and `/api/v1/device/monitor/info` 265 KB for 288 cabinets on the MX40
  Pro; about 90 KB and 97 KB for 72 cabinets on the MX30 (compact
  re-serialisation, not wire size). A monitoring consumer should poll
  `monitor/info` on its own cadence and the cabinet list rarely.
- **`monitor/info` lists cabinets in a different order on every call**
  (OBSERVED: all 288 moved between two reads). Match them on
  `rvCards[].cabinetID`, never on position. `coex diff` does; a naive diff of
  two real snapshots reports ~2,000 changes that are not changes.
- `runtime` and `totalRuntime` are seconds, advancing in 60-second steps
  (OBSERVED on the MX40 Pro over one 35-minute interval, and again on the MX30
  over seven minutes and a five-minute 1 Hz poll).
- Nothing here is authenticated or rate-limited; a stray loop can hammer a live
  screen. Confirm the destructive calls in the UI.
- Cabinet IDs are large integers tied to the current project; re-import a
  project file and they can change. Resolve IDs at connect time rather than
  persisting them.
