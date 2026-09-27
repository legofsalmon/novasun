# The COEX HTTP API

Current-generation NovaStar controllers — MX40 Pro, MX30, MX20, MX2000/6000 Pro,
CX40 Pro, CX80 Pro, KU20 — expose an official JSON API on **TCP 8001**. This is
the layer VMP-class functionality is built on, and it is documented by NovaStar
rather than reverse-engineered.

Client: [`../src/novasun/coex.py`](../src/novasun/coex.py).

## Basics

- HTTP only, port 8001. The controller's IP is on its LCD home screen.
- **No authentication.** Anything that can reach the port can reconfigure the
  screen. Treat control networks accordingly. OBSERVED as well as OFFICIAL:
  none of VMP's 222 requests to an MX30 carried an `Authorization` header, a
  cookie or a token. What the API does have is a **lock**,
  `/api/v1/device/hw/lock`, which VMP takes as it opens (below).
- JSON bodies; `PUT` for setters, `GET` for getters.
- Every documented response is `{"code": 0, "data": ..., "message": "Success"}`.
  Non-zero codes: `1` InvalidParam, `2` SendFailed, `3` InternalErr,
  `4` AnalysisFailed, `5` Busying, `6` NotSupport, `39` CfgFileNotExist,
  `41` NonStandardFileName. Neither unit read so far has produced a code 6; both
  answer an absent path *outside* the envelope, and differently (next two
  bullets). One present endpoint also answers outside it: on the MX30,
  `GET /api/v1/device/screen` returned 15,888 bytes of JSON with no envelope
  (OBSERVED, VMP's reads), and `GET /api/v1/device/config-file` answered code
  3 inside HTTP 200 ("don't have config info").
- **OBSERVED on an MX40 Pro (2026-09-11):** three documented GETs,
  `/api/v1/device`, `/api/v1/device/audio` and
  `/api/v1/device/screen/displaymode`, answered a bare **HTTP 404** — no JSON
  envelope, no code 6. `/api/v1/device/backup`, `/multifunc-card/detailinfo`
  and `/hw/mode` answered (the last reading `{"mode": 3}`, a value the manual
  does not list). An undocumented path was never tried on this unit, so what it
  does for one is UNKNOWN.
- **OBSERVED on an MX30 (firmware v1.5.1 — operator-reported during the
  read-only pass, read over SNMP as `V1.5.1` later the same day and over HTTP
  as `/device/hw` `hwVersion` that evening; 2026-09-26):**
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
  exercised for the first time; see the endpoint map. VMP's own reads that
  evening added six more empty-200 paths:
  `/api/v1/device/discovery?vendorName=coex`, `/device/hw/networkinfolist`, `/device/output/display`, `/screen/input`,
  `/device/hw/threed/emitterpara` and `/device/hwscreen` (OBSERVED).
- **Consequence for any consumer: handle both spellings of "absent", and never
  read an empty 200 as "exists".** This project's own `CoexClient.request`
  turns an empty body into `{}` (`json.loads(b or b"{}")`), so `coex snapshot`
  on the MX30 reported `device: {}` with no error — exactly the misreading to
  avoid. A `res.json()` on the same reply throws instead. Test for the missing
  envelope explicitly.
- **Neither COEX unit answered `rqProMI:` discovery** on UDP 3800 — unicast,
  broadcast or multicast. OBSERVED on the MX40 Pro; the MX30 left eight probes
  unanswered in one ~6 s trial on 2026-09-26, which is consistent with the same
  behaviour (REASONED from one trial). To the probe, a COEX controller has to
  be given its address. **The MX30 announces itself instead:** every 3.0 s,
  unsolicited, on UDP 54622, 54623, 54624 and 54700 from source port 54650, a
  96-byte JSON payload `{"data":[{"apiPort":"8001","mac":…,"authType":0,"workMode":0,"https":"9001"}]}`
  to the subnet broadcast (OBSERVED; layout in
  [`read-only-monitoring.md`](read-only-monitoring.md#coex-announcements-on-udp-54622-54623-54624-and-54700--observed-on-an-mx30)).
  VMP sent no probe and connected to the announced `apiPort` 5 ms after an
  announcement (REASONED: that is how it found the unit). Whether the MX40 Pro
  announces is UNKNOWN. The response *shapes* of the GETs that answered are
  recorded in [`read-only-monitoring.md`](read-only-monitoring.md#over-coex-http-get) and
  differ from what the manual and published clients led this project to expect.
- **A Success envelope on a PUT does not mean the change happened.** The only
  PUTs this project has sent to COEX hardware went to that MX30 later the same
  day, with VMP closed and the operator's go. `PUT /api/v1/device/snmpstate`
  with `{"value": true}` answered HTTP 200, `Content-Type: application/json`,
  `{"code":0,"data":"","message":"Success"}` — and a GET in the same second
  still read `{"state": false}` (OBSERVED once; `{"value": false}` was never
  sent). With **`{"state": true}`** the GET read `{"state": true}`, and
  `{"state": false}` put it back — twice in each direction, with the SNMP agent
  answering and falling silent to match (OBSERVED; the agent's answer after the
  first enable is REASONED from timestamps). The setter's key mirrors the
  getter's (REASONED). `CoexClient.set_snmp` sent `{"value": ...}` at the time,
  so on this firmware it reported success and did nothing; where that body came
  from is not recorded (it dates from commit `6c9cbd8`). The other setters in
  `coex.py` that send `{"value": ...}` — `identify_controller`,
  `set_automatic_time`, `set_controller_name`, `set_timezone` — may be wrong
  the same way: REASONED, not tested. `set_system_time` sent `{"value": ...}`
  too until 2026-09-26 and now sends the body VMP was seen to send (endpoint
  map, "Clock"). **Read the value back after a PUT** (REASONED, from one
  endpoint).
- **VMP's requests carry headers the manual does not mention** (OBSERVED, MX30):
  `Application-Id: Launcher_<uuid>` on every request — the id a
  `deviceLastOperatorChange` event later names — and, from its UI client,
  `Device-Key: <ip>:8001`, `Device-Type: VMP` and an empty `Need-Report-All`.
  None is needed for a GET: the first `/device/hw` read carried none of them.
  52 of VMP's GETs carried a JSON body; whether a body changes what a GET
  returns is UNKNOWN (one endpoint answered two client-and-body pairs with
  different sizes).
- **`X-Request-Id` is a request counter** (OBSERVED on the MX30): across VMP's
  222 requests from two clients, the IDs formed 222 consecutive values, none
  missing. That it is global to the unit — so a gap between two of your own
  requests means another client — is REASONED.

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
| PUT | `/api/v1/device/screen/displaymode` | `0` normal, `1` blackout, `2` freeze. **Not readable back at this path**: a GET drew HTTP 404 on the MX40 Pro and an empty 200 on the MX30 (OBSERVED, both). **Read display state at `/api/v1/screen/output/display/state`** (next row). This row used to say "not readable back, by any route seen"; that came from a freeze sweep which never polled the next row's endpoint, and it is withdrawn |
| GET | `/api/v1/screen/output/display/state` | `{"mappingState": [{"canvasID", "enable"}], "displayState": [{"canvasID", "displayMode"}]}`, per canvas. On the MX30: `displayMode` **2 through a front-panel freeze**, 0 live (OBSERVED, attended, polled at 1 Hz; the same value marked a second freeze on the websocket); **1 through a front-panel blackout** (OBSERVED once, attended, on the GET and the websocket). Never tried on the MX40 Pro. **The read-only way to see a frozen or blacked-out wall** |
| GET | `/api/v1/device/output/display` | Empty 200 on the MX30 (OBSERVED, VMP's reads). Not the display state |
| GET | `/api/v1/screen` | Screen list with IDs |
| GET | `/api/v1/screen/cabinets` | Cabinets per screen — came back `{}` through the read-only client on the MX30; absent or empty, UNKNOWN which |
| GET | `/api/v1/screen/cabinet/count` | `{"list": [{"ScreenID", "CabinetCount", "CabinetCountInBlackList"}]}` per screen — OBSERVED on the MX30: 72 and 0 with the wall connected, **`CabinetCount` 0 with every output line unplugged** (attended). Counts connected cabinets, which `monitor/info` does not (see its row). Never tried on the MX40 Pro |
| PUT | `/api/v1/screen/brightness` | Brightness by screen ID list. **Do not use: the body is ignored.** On the MX30, `{"idList": [<screenID>], "ratio": 0.45}` — the body `CoexClient.set_screen_brightness` sends — **answered Success and changed nothing** (OBSERVED once, attended); the unit then pushed `screenBrightnessChange {screenIdList: null, brightness: 0}`, neither key recognised. A silent no-op, like the old `snmpstate {"value"}` body. The right body is UNKNOWN. The same event at each front-panel knob step carried `screenIdList: [<screen UUID>]` and the new 0–1 fraction (OBSERVED), so `screenIdList`/`brightness` is a candidate body only — REASONED, untested, not to be shipped as the fix. Use `device/cabinet/brightness` |
| PUT | `/api/v1/device/screen/video/bitdepth` | Output bit depth |
| PUT | `/api/v1/device/screen/input` | Select input source |
| PUT | `/api/v1/device/screen/controller/pattern/test` | Controller test pattern |

### Cabinets

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/device/cabinet` | All cabinet information. On the MX30 it tracks the cabinets **connected now**, not the configured wall: 72 entries connected, **0 entries with every output line unplugged** (OBSERVED, attended) — the entry count, against the expected number, is a presence signal; `monitor/info` is not. `brightness` is a 0–1 fraction (OBSERVED on both units), per cabinet, and read back a PUT within 1 s |
| PUT | `/api/v1/device/cabinet/brightness` | `{"idList": [...], "ratio": 1.0, "nit": 1000}`. **Works on the MX30:** `{"idList": [all 72 cabinet ids], "ratio": r}`, no `nit`, took effect — `/device/cabinet` read back `r` within 1 s and the websocket pushed `ScreensCabinetsDisplayChange {list: [{screenId, brightness: r, colorTemperature, gamma}]}` ~55 ms after the PUT (OBSERVED, twice, attended). **`ratio` is a 0–1 fraction** (OBSERVED: the front panel's 60 was pushed as 0.600). `nit` untested. Set it from a fresh read with a relative step: the first test sent an absolute 0.45 to a wall that was at 0.2, not the 0.5 read hours earlier, so the wall went from 20 % to 45 % — brighter — for ~9 s when dimmer had been announced |
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
| GET | `/api/v1/device` | Device information — **not returned by either unit read: HTTP 404 on the MX40 Pro, an empty HTTP 200 on the MX30 (OBSERVED, both)**. Identity is at `/api/v1/device/hw` (next row) on the MX30; `monitor/info.name` is a label, not a model (see `hw/customname`) |
| GET | `/api/v1/device/hw` | **Identity** (OBSERVED on the MX30, VMP's reads, 5,698 bytes): `name` "MX30", `modelID` **5138**, `hwVersion` "V1.5.1" (the string SNMP gives as firmware), `sn`, `mac`, `type` "G3.5", `swVersion`, `mcuVersion`, `fpgaVersion`, `configVersion`, `customName`, `deviceUUID`, network settings, `uptime`, `mode` 3, `deviceWorkMode`, a `capability{}` block (`capabilityVersion` "V4.1.0") and `encipher{}`. **Also `randomPassword`, an 8-digit string served to an unauthenticated GET, purpose UNKNOWN: never log, store, display or serialise it** — drop it on receipt. Never requested on the MX40 Pro |
| GET | `/api/v1/device/hw/versions`, `/firmware/list`, `/backcard/info` | Version detail (OBSERVED, MX30): `controllerSystem.system` "V1.5.1.B2" and a second, 13-digit `sn`; `deviceModelID` 5138 and `deviceVersion` "V1.5.1" with sub-card model IDs 5138 and 41603; the back card as "Mctrl BackCard", `modelId` 5138, `sn` = `hw.sn` |
| GET | `/api/protocol/version`, `/api/capability/version` | `{"protocolVersion": "V1.1"}` and `{"CapabilityVersion": "V4.1.0"}` (capital C) — outside `/api/v1` (OBSERVED, MX30) |
| GET | `/api/v1/device/discovery?vendorName=coex` | VMP's first request; an empty 200 on the MX30, so absent or empty, UNKNOWN which (OBSERVED) |
| GET/PUT | `/api/v1/device/hw/lock` | **The control lock.** GET `{"locked": 0, "ip": ""}` when free (OBSERVED). VMP's PUT `{"appids": ["LCTPro<id>"]}` on opening set it, and the websocket pushed `deviceLockChange {locked: 1, ip}` (OBSERVED). It outlived the PUT's connection, did not stop a front-panel freeze, and was gone after VMP quit (REASONED; release mechanism and effect on other clients UNKNOWN). **A monitor never PUTs it**; the GET shows who holds the unit |
| GET | `/api/v1/device/hwinfo` | `displayMode` (0, wall live), `deviceAvailable`, `deviceControlState`, `timeEnable`, `timeSource`, `beaconEnable`, `beaconColor{r,g,b}` and more (OBSERVED keys, MX30); meanings UNKNOWN, and whether its `displayMode` tracks a freeze is untested |
| GET | `/api/v1/device/timestamp` | `{"timestamp": <epoch s>}` — on the MX30 it matched the time of the last operator write, not the clock (REASONED from one read) |
| GET | `/api/v1/screen/statistic`, `/screen/monitor/alarmcount` | Cabinet counts by health (`{total, normal, warning, error}`), and an alarm summary that disagreed with it on the MX30 (`count` 1, `status` 2, meaning UNKNOWN) — OBSERVED once each |
| GET | `/api/v1/device/audio` | `{"enable", "source", "sourceName"}` — HTTP 404 on the MX40 Pro, **present on the MX30** (`false`, `65535`, `""`), OBSERVED |
| GET | `/api/v1/device/monitor/info` | Real-time monitoring. **A stale cabinet list — a false all-clear on the MX30:** with every output line unplugged it kept all 72 `cabinets[]` and `rvCards[]`, every `nextCabinetLinkStatus.linkStatus` true and temperatures 39–42 °C, at every 2 s poll for the ~8.5 minutes until power-off, and never cleared (OBSERVED, attended); only `rvCardsRuntime` emptied. Its per-card readings are last-known values, not live (REASONED). `outputStatus[].linkStatus` did track the unplugging, per output, within one poll. Count cabinets from `screen/cabinet/count` or `device/cabinet`, never from here. Never watched with a line out on the MX40 Pro |
| GET/PUT | `/api/v1/device/hw/mode` | `0` send-only, `1` all-in-one. Both units read back `{"mode": 3}`, a value the manual does not list; meaning UNKNOWN |
| GET/PUT | `/api/v1/device/hw/deviceengineeringdocdata` | Export / import project file |
| PUT | `/api/v1/device/hw/customname` | Rename controller (OFFICIAL). This is why `monitor/info.name` cannot carry the model: the MX40 Pro reported `MX40 Pro_<digits>`, the MX30 a single plain word (OBSERVED) — an operator label, most likely set here (REASONED). **No model can be read from `name`** (OBSERVED on the MX30, whose name carried none; as a rule, REASONED). The model and firmware are at `/api/v1/device/hw` — `name` "MX30", `modelID` 5138, `hwVersion` "V1.5.1" (OBSERVED on the MX30) — which also settles the `modelId` 5138 recurring across the MX30's payloads: it is the MX30's model ID. This row used to say no field read over HTTP gave either |
| PUT | `/api/v1/device/hw/systemtime`, `/timezone`, `/time/enable` | Clock. **VMP's `systemtime` body** (OBSERVED, MX30): `{"clientTimezone": "<IANA zone>", "second", "minute", "hour", "isUTC": true, "day", "month", "year"}` — and VMP sent it as it opened (OBSERVED once), so **opening VMP writes the controller's clock and zone**. The unit answered it with a Success envelope; whether the clock moved is UNKNOWN (the `Date` header lagged about the same before and after — weak evidence it did not). `CoexClient.set_system_time` used to send `{"value": <iso>}`, most likely a Success-and-no-op (REASONED, by analogy with `snmpstate`); it now sends VMP's shape. novasun has sent neither body to a controller; do not test either on a live unit |
| PUT | `/api/v1/device/picture` | `{"type": 0}`, sent twice by VMP as it opens, the first 1.5 ms before it connected to the 8082 preview — most likely preview control (REASONED); what `type` selects is UNKNOWN (OBSERVED, MX30). A write: not for monitoring |
| GET/PUT | `/api/v1/device/snmpstate` | SNMP on/off. GET `{"state": bool}` — false on both units as found (OBSERVED). **PUT body `{"state": bool}`** (OBSERVED on the MX30, twice each way, read back); `{"value": true}` answers a Success envelope and changes nothing (OBSERVED once). Turning SNMP on is a write, so a read-only consumer cannot |
| GET | `/api/v1/device/multifunc-card/detailinfo` | Multifunction card status |
| PUT | `/api/v1/device/backup`, `/backup/verify` | Primary/backup |
| PUT | `/api/v1/device/hw/colorBeacon` | Identify the controller. On the MX30, `{"value": true}` and then `{"value": false}` each answered **HTTP 200, `Content-Length: 0`, no `Content-Type`, no envelope** (OBSERVED) — the shape that firmware gives an absent path on GET; a PUT to a made-up path was never tried, so the reply alone cannot tell existence either way. Then, with the operator watching the chassis (front panel, LCD, status LEDs), `{"value"}`, `{"state"}` and `{"enable"}` bodies were each held true for 10 s and set false: nine more empty 200s and **nothing visible changed in any window** (OBSERVED, 17:43–17:44Z). **Most likely absent on this firmware** (REASONED); an indicator elsewhere or an untried body is not excluded — `GET /api/v1/device/hwinfo` does carry `beaconEnable` and `beaconColor` keys (OBSERVED), and whether another setter drives them is UNKNOWN. Do not offer it as an identify control |

Screen-level equivalents exist for most cabinet operations under
`/api/v1/screen/...`, along with 3D LUT import, colour correction, canvas
mapping and scheduling.

## Push channel: `/api/v1/websocketchannel`

Not in the endpoint map above, which follows the manual; whether the manual
documents it was not checked. Plain `ws://` on 8001, no authentication
(OBSERVED on the MX30: VMP's connection, and attended tests that sent only the
upgrade, pongs and a close frame).

- **Handshake:** a standard upgrade — `Upgrade`, `Connection`,
  `Sec-WebSocket-Key`, `Sec-WebSocket-Version: 13`, nothing else — answered
  `101 Switching Protocols`, no compression.
- **Server to client:** an empty ping every 1.000 s, and JSON text events
  `{"eventData": {...}, "eventSender": str, "eventType": str}`. The client
  answers pings with empty pongs.
- **Events seen:** `monitor/controllerRealTimeInfoChange` (the top of
  `monitor/info`, every 10 s), `monitor/cabinetRealTimeInfoChange` (one
  receiving card, apparently on change), `monitor/cabinetsRuntimeInfoChange`
  (every 60 s), `device/deviceLastOperatorChange` (`{ip, appID, timestamp}` —
  the actor behind a write; the front panel appears as 127.0.0.1 with an
  `LCDAPP_` id), `device/deviceLockChange` (`{locked, ip}`) and
  `device/canvasDisplayModeChange` (`{canvasIDs, value}` — 2 at a freeze, 1 at
  a blackout, 0 at release). In later attended sessions:
  `ScreensCabinetsDisplayChange` (`{list: [{screenId, brightness,
  colorTemperature, gamma}]}`) and `screenBrightnessChange` (`{screenIdList,
  brightness}`) on brightness changes; `ScreensCabinetsCountChange` (`{list:
  [{ScreenID, CabinetCount, CabinetCountInBlackList}]}`),
  `outputPortLinkChange` and `physicalOutputPortLinkChange` (`{portLinkState:
  [{cardId, port, linkState, backupState, type}]}`), `alarmCountChange` and
  `loopDetectStatusList` as output lines were unplugged, with a burst of
  screen-reconfiguration events at each change (`screenCabinetSizeChange`, bit
  depth, correction, `dynamicEngineConfigChange`). Every write, the front
  panel's or an API client's, was preceded by `deviceLastOperatorChange`; this
  project's client appeared with its IP and an empty `appID`.
- **What the unplug test showed on it** (OBSERVED, one MX30, attended):
  `ScreensCabinetsCountChange` followed every stage of the unplugging, 72 → 48
  → 46 → 45 → 36 → 24 → 0 — the connected count, where `monitor/info` stayed
  at 72; `alarmCountChange` `{alarmCounts: [{screenId, count, status,
  subCardStatus}]}` went `count` 3 → 4 → 6 with `status` 2; and
  `outputPortLinkChange` reported `backupState: true` on 2051 as 2049 went
  down, so 2049 and 2051 are backup ports.
- **What a brightness change looks like on it** (OBSERVED): one
  `ScreensCabinetsDisplayChange` ~55 ms after each cabinet-brightness PUT; a
  front-panel knob turn from 20 % to 60 % and back gave 72
  `screenBrightnessChange` (one per step of 0.001–0.008), 70
  `ScreensCabinetsDisplayChange` and 72 `deviceLastOperatorChange` in 21 s —
  debounce (REASONED).
- **At a front-panel power-off** the websocket ended within half a second
  (OBSERVED; see "Power-off and standby", below).
- **No hello is needed.** VMP sends its `Application-Id` as one text frame after
  the upgrade, but a client sending only the upgrade and pongs received every
  kind of event that occurred (OBSERVED). No lock was taken while such a
  client listened, so whether `deviceLockChange` needs the hello is UNKNOWN.
- Display-mode changes are pushed only on change, not on connect: take the
  current value from `GET /api/v1/screen/output/display/state`.

Side effects of subscribing are UNKNOWN, so this repository's read-only
surface uses the GET, not the websocket. Detail, with the contract reasoning,
in [`read-only-monitoring.md`](read-only-monitoring.md#the-websocket-push-channel-apiv1websocketchannel--observed-one-mx30).

## Preview stream: TCP 8082

VMP's live preview (OBSERVED on the MX30, from headers and sizes only). The
client sends two bare strings, `GET /Device:<sn>` (the `/device/hw` serial)
and `Frame Rate(Hz):60`, with no HTTP version or line ending. The unit answers
`HTTP/1.0 200 OK`, `Server: Motion/0.1`, `Content-Type:
multipart/x-mixed-replace; boundary=--BoundaryString`, then JPEG parts, each
headed `Nova-type: <t>`, `Content-type: image/jpeg` and a space-padded
`Content-Length`. Frames are 1920x1076 baseline JPEG, about 12.7 a second,
**about 51 Mbit/s**. `Nova-type` appears to name the input (REASONED). It shows
inputs, not the processed output — it kept changing through a front-panel
freeze (REASONED) — so it is no monitoring source.

## What VMP sends when it opens

OBSERVED once, MX30: 218 GETs over 90 paths in 0.65 s, the first of them
`GET discovery?vendorName=coex`, then four PUTs — `hw/systemtime`, `device/picture` twice and
`hw/lock` — then no further HTTP, only the websocket and the 8082 stream.
Opening VMP therefore writes the controller's clock and takes its lock. The
sequence, timed, is in
[`read-only-monitoring.md`](read-only-monitoring.md#what-vmp-does-when-it-opens--observed-one-capture-mx30) §3.

## Power-off and standby

OBSERVED on one MX30, V1.5.1, attended, with every output line already
unplugged: the operator switched the unit off at its **front-panel power
button**, not at the mains (operator-reported).

- The UDP announcements stopped at once — the last at 19:10:55.824Z, the next,
  due three seconds later, never came — and the websocket ended at
  19:10:56.265Z.
- HTTP answered **connection refused**, not a timeout, from 19:10:56.6Z, and
  kept refusing on every attempt until the watch ended 7.5 minutes later.
  Something at the unit's address went on answering TCP with resets while HTTP
  and the announcements were gone.

So the front-panel "off" is a **standby** with the network stack up
(REASONED, well supported). For a client: announcements absent plus HTTP
refused = standby; HTTP timing out with no ARP reply = unpowered or
disconnected (REASONED; a mains cut and a pulled cable were not tried). **A
refusal is not "unplugged".** Whether the unit wakes over the network, and how
it looks after longer than 7.5 minutes, are UNKNOWN. Detail in
[`read-only-monitoring.md`](read-only-monitoring.md#unplugged-outputs-and-power-off--observed-attended-one-mx30).

## Adjacent official interfaces

- **Central Control Protocol** — the register bus over TCP 5200, UDP 5201 or
  RS232, documented for the same controllers. Fewer capabilities, but the same
  commands work on much older hardware. See
  [`protocol-register-bus.md`](protocol-register-bus.md). On the one MX30 tried
  (V1.5.1, VMP closed), **TCP 5200 refused a connection** and one read frame on
  UDP 5201 drew no reply in 3 s (OBSERVED once each). Whether Ethernet central
  control is a setting, off by default, or opened while VMP runs is UNKNOWN.
  In a later packet capture, before VMP connected, a second UDP 5201 read
  frame drew an **ICMP port-unreachable** (OBSERVED): nothing listened on 5201
  at that moment. Never open a session to a COEX controller on a live show
  regardless: it is exclusive and displaces VMP's.
- **SNMP** — NovaStar publishes a MIB for COEX monitoring, which is the right
  choice if the goal is integration with existing monitoring rather than
  control. Exercised once, on that MX30 after enabling it over this API: it
  gives the controller **model and firmware** — which `/api/v1/device/hw` was
  later found to give over HTTP as well — with quirks — no MIB-2 system group, x100 scaling, bitmask statuses,
  `"ERROR: ..."` strings — recorded in
  [`read-only-monitoring.md`](read-only-monitoring.md#the-oid-map-on-an-mx30-v151--exercised-once-2026-09-26).

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
- **`/api/v1/device/hw` serves `randomPassword`** to any unauthenticated GET
  (OBSERVED, MX30; purpose UNKNOWN). Any client that reads that endpoint must
  drop the field before it reaches a log, a store, a display or a fixture.
- **A PUT's Success is not confirmation.** Two MX30 setters accepted a body
  they did not understand, said Success and did nothing (both OBSERVED once):
  `snmpstate` with `{"value": true}` and `screen/brightness` with
  `{"idList", "ratio"}` (above). Where a getter exists, read back; where none
  does (`colorBeacon`, whose reply is an empty 200), the effect is unverified.
- Cabinet IDs are large integers tied to the current project; re-import a
  project file and they can change. Resolve IDs at connect time rather than
  persisting them.
