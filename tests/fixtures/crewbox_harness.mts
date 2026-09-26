// Drive crewbox's CoexReader with the COEX HTTP API as OBSERVED on real COEX
// hardware -- the fixtures beside this file: real structure, synthetic values,
// three cabinets standing in for the wall. Nothing in crewbox is modified; its
// reader is imported and run against a fake fetch.
//
//   cd $CREWBOX/server && ../node_modules/.bin/tsx <novasun>/tests/fixtures/crewbox_harness.mts [fixture]
//
// CREWBOX defaults to ~/crewbox; the fixture defaults to mx40_like_api.json
// (an MX40 Pro, 2026-09-11). mx30_like_api.json is an MX30 on firmware v1.5.1
// (operator-reported), 2026-09-26.
//
// The two units spell "absent" differently, so the fake fetch knows two
// markers. On the MX40 Pro an absent endpoint answered 404: a fixture entry
// {"__http_status__": 404} answers 404 here, and endpoints never requested on
// that unit (displaymode, backup) also 404, which is the conservative
// assumption and is labelled as such. On the MX30 an absent or unknown path
// answered HTTP 200 with Content-Length: 0 and no body (OBSERVED with curl -i):
// an entry {"__http_status__": 200, "__empty_body__": true} answers ok, 200,
// and a json() that rejects with a SyntaxError, which is what fetch does on an
// empty body.
import { readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const crewbox = process.env.CREWBOX ?? join(homedir(), 'crewbox')
const { CoexReader } = await import(join(crewbox, 'server/src/video/coex.ts'))
const { gradeReading } = await import(join(crewbox, 'shared/src/video.ts'))

const here = dirname(fileURLToPath(import.meta.url))
const fixture = process.argv[2] ?? join(here, 'mx40_like_api.json')
const api = JSON.parse(readFileSync(fixture, 'utf8')) as Record<string, any>

let t = 1_000
const requested: string[] = []
const io = {
  fetch: (url: string, init: any) => {
    const path = new URL(url).pathname
    requested.push(`${init.method} ${path}`)
    const body = api[path]
    if (body === undefined || (body && body.__http_status__ === 404)) {
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) })
    }
    if (body && body.__http_status__ === 200 && body.__empty_body__ === true) {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.reject(new SyntaxError('Unexpected end of JSON input')),
      })
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) })
  },
  now: () => t,
  wait: (ms: number) => { t += ms; return Promise.resolve() },
}

function show(label: string, r: any) {
  const withTemp = r.cabinets.filter((c: any) => c.temperature !== undefined).length
  const online = r.cabinets.filter((c: any) => c.online).length
  console.log(`\n=== ${label} ===`)
  console.log(`model=${r.model}  reportedName=${r.reportedName}  serial=${r.serial}  firmware=${r.firmware}`)
  console.log(`temperature=${r.temperature}  fanSpeed=${r.fanSpeed}  fanRpm=${r.fanRpm}  brightness=${r.brightness}  snmpEnabled=${r.snmpEnabled}  isBackup=${r.isBackup}  displayMode=${r.displayMode}  answered=${r.answered}`)
  console.log(`cabinets: ${r.cabinets.length} total, ${online} online, ${withTemp} with temperature; ids=${JSON.stringify(r.cabinets.map((c: any) => c.id))}`)
  console.log(`inputs  : ${JSON.stringify(r.inputs)}`)
  console.log(`errors  : ${JSON.stringify(r.errors)}`)
  console.log(`absent  : ${JSON.stringify(r.absent)}`)
  console.log(`grade   : ${JSON.stringify(gradeReading(r))}`)
}

const reader = new CoexReader('192.0.2.1', io as any)
const first = await reader.poll()
show('POLL 1 (topology + status)', first)
console.log(`requested: ${JSON.stringify(requested)}`)

// The real unit returns monitor/info cabinets in a different order every call.
api['/api/v1/device/monitor/info'].cabinets.reverse()
const second = await reader.poll()
show('POLL 2 (status only; monitor/info order changed, as on the real unit)', second)
console.log(`\nsame cabinet ids in the same order across polls? ${JSON.stringify(first.cabinets.map((c: any) => c.id)) === JSON.stringify(second.cabinets.map((c: any) => c.id))}`)
console.log(`requests made in polls 1-2: ${requested.length}; all GET: ${requested.every((r) => r.startsWith('GET '))}`)

// Keep going through two more topology sweeps (polls 11 and 21). Three 404s
// latch an endpoint as absent from the firmware and it stops being asked; an
// empty 200 carries no 404, so whether the MX30's missing paths ever latch is
// something to measure rather than infer.
const before = requested.length
let mark = before
let last = second
for (let i = 3; i <= 21; i++) {
  mark = requested.length
  last = await reader.poll()
}
console.log(`\n=== POLLS 3-21 (through the topology sweeps at 11 and 21) ===`)
console.log(`requests in polls 3-21: ${requested.length - before}; poll 21 alone: ${requested.length - mark}`)
console.log(`errors on poll 21: ${JSON.stringify(last.errors)}`)
console.log(`absent after poll 21: ${JSON.stringify(last.absent)}`)
console.log(`grade on poll 21: ${JSON.stringify(gradeReading(last))}`)
console.log(`requests made in all 21 polls: ${requested.length}; all GET: ${requested.every((r) => r.startsWith('GET '))}`)
