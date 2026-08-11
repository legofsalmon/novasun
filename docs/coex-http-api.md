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
- Every response is `{"code": 0, "data": ..., "message": "Success"}`. Non-zero
  codes: `1` InvalidParam, `2` SendFailed, `3` InternalErr, `4` AnalysisFailed,
  `5` Busying, `6` NotSupport, `39` CfgFileNotExist, `41` NonStandardFileName.

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
| PUT | `/api/v1/device/screen/displaymode` | `0` normal, `1` blackout, `2` freeze |
| GET | `/api/v1/screen` | Screen list with IDs |
| GET | `/api/v1/screen/cabinets` | Cabinets per screen |
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
| GET | `/api/v1/device` | Device information |
| GET | `/api/v1/device/monitor/info` | Real-time monitoring |
| PUT | `/api/v1/device/hw/mode` | `0` send-only, `1` all-in-one |
| GET/PUT | `/api/v1/device/hw/deviceengineeringdocdata` | Export / import project file |
| PUT | `/api/v1/device/hw/customname` | Rename controller |
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

- Endpoint availability varies by model and firmware. `NotSupport` (code 6) is a
  normal answer, not a failure of the client.
- Nothing here is authenticated or rate-limited; a stray loop can hammer a live
  screen. Confirm the destructive calls in the UI.
- Cabinet IDs are large integers tied to the current project; re-import a
  project file and they can change. Resolve IDs at connect time rather than
  persisting them.
