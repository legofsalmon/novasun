// Drive crewbox's CoexReader with the COEX HTTP API as OBSERVED on a real MX40
// Pro -- the fixture beside this file: real structure, synthetic values, three
// cabinets standing in for 288. Nothing in crewbox is modified; its reader is
// imported and run against a fake fetch.
//
//   cd $CREWBOX/server && ../node_modules/.bin/tsx <novasun>/tests/fixtures/crewbox_harness.mts
//
// CREWBOX defaults to ~/crewbox. Endpoints the real unit answered 404 answer
// 404 here; endpoints never requested on the real unit (displaymode, backup)
// also 404, which is the conservative assumption and is labelled as such.
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
  console.log(`temperature=${r.temperature}  fanSpeed=${r.fanSpeed}  brightness=${r.brightness}  snmpEnabled=${r.snmpEnabled}  displayMode=${r.displayMode}  answered=${r.answered}`)
  console.log(`cabinets: ${r.cabinets.length} total, ${online} online, ${withTemp} with temperature; ids=${JSON.stringify(r.cabinets.map((c: any) => c.id))}`)
  console.log(`inputs  : ${JSON.stringify(r.inputs)}`)
  console.log(`errors  : ${JSON.stringify(r.errors)}`)
  console.log(`grade   : ${JSON.stringify(gradeReading(r))}`)
}

const reader = new CoexReader('192.0.2.1', io as any)
const first = await reader.poll()
show('POLL 1 (topology + status)', first)

// The real unit returns monitor/info cabinets in a different order every call.
api['/api/v1/device/monitor/info'].cabinets.reverse()
const second = await reader.poll()
show('POLL 2 (status only; monitor/info order changed, as on the real unit)', second)
console.log(`\nsame cabinet ids in the same order across polls? ${JSON.stringify(first.cabinets.map((c: any) => c.id)) === JSON.stringify(second.cabinets.map((c: any) => c.id))}`)
console.log(`requests made: ${requested.length}; all GET: ${requested.every((r) => r.startsWith('GET '))}`)
