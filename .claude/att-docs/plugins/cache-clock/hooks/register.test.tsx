import { expect, mock, test } from 'claude-code/testing'
import type { ModelForkRequest, On, TurnStepInput } from 'claude-code'
import type { Engine } from 'claude-code/testing'

import { keepWarmStop, readCacheLength } from './clock'

// One transcript line as Claude Code writes it for a model reply.
function reply(cache: { h1?: number; m5?: number } | null, extra: Record<string, unknown> = {}) {
  const usage: Record<string, unknown> = { input_tokens: 3, output_tokens: 10 }
  if (cache !== null) {
    usage.cache_creation = { ephemeral_1h_input_tokens: cache.h1 ?? 0, ephemeral_5m_input_tokens: cache.m5 ?? 0 }
  }
  return JSON.stringify({
    type: 'assistant',
    isSidechain: false,
    timestamp: '2026-11-17T10:00:00.000Z',
    message: { role: 'assistant', usage },
    ...extra,
  })
}

const USER = JSON.stringify({ type: 'user', isSidechain: false, message: { role: 'user', content: 'hi' } })

test('a main-chat reply written to the 1-hour cache reads as 1h', () => {
  expect(readCacheLength([USER, reply({ h1: 5000 })].join('\n')).kind).toBe('1h')
})

test('a main-chat reply written to the 5-minute cache reads as 5m', () => {
  expect(readCacheLength([USER, reply({ m5: 5000 })].join('\n')).kind).toBe('5m')
})

test('subagent replies alone read as unknown', () => {
  const text = [USER, reply({ h1: 5000 }, { isSidechain: true })].join('\n')
  expect(readCacheLength(text).kind).toBe('unknown')
})

test('a transcript with no cache writes reads as unknown', () => {
  expect(readCacheLength([USER, reply(null)].join('\n')).kind).toBe('unknown')
  expect(readCacheLength('').kind).toBe('unknown')
})

test('the newest main-chat reply decides, past newer subagent lines', () => {
  const text = [reply({ h1: 10 }), reply({ m5: 10 }), reply({ h1: 10 }, { isSidechain: true })].join('\n')
  expect(readCacheLength(text).kind).toBe('5m')
})

test('a reply that wrote nothing to the cache is passed over', () => {
  const text = [reply({ h1: 10 }), reply({ h1: 0, m5: 0 })].join('\n')
  expect(readCacheLength(text).kind).toBe('1h')
})

test('a line cut short or not JSON is skipped', () => {
  const text = ['e": 1}}', reply({ m5: 10 }), 'not json', '{"type":"assis'].join('\n')
  expect(readCacheLength(text).kind).toBe('5m')
})

test('the deciding reply gives its time', () => {
  expect(readCacheLength(reply({ m5: 10 })).at).toBe(Date.parse('2026-11-17T10:00:00.000Z'))
  expect(readCacheLength('').at).toBe(null)
})

// The engine beneath the plugin

const MIB = 1024 * 1024
const MINUTE = 60_000
// Where the mock clock starts: well after the transcript lines' own time.
const START = Date.parse('2026-11-17T12:00:00.000Z')

type Fork = { isAnswered: true; read: number } | { isAnswered: false; reason: string }

type Setup = {
  // Files by path.
  files?: Record<string, string>
  // The size fs.stat reports for a path, when not its text's length.
  sizes?: Record<string, number>
  // What `tail` prints for a path.
  tails?: Record<string, string>
  // Project folders, as full paths.
  projects?: string[]
  env?: Record<string, string>
  store?: Record<string, unknown>
  tokens?: number
  // Fork results in turn; once they run out, each ping reads the cache.
  forks?: Fork[]
  // How long each fork takes.
  forkMs?: number
  // Paths whose writes fail.
  failWrites?: string[]
}

// Stands in for the engine beneath the plugin, and records what the plugin asked of it.
function engine(on: On, setup: Setup = {}) {
  const files: Record<string, string> = { ...setup.files }
  const seen = {
    forks: [] as ModelForkRequest[],
    runs: [] as string[][],
    writes: [] as { path: string; text: string }[],
    reads: [] as string[],
    lists: [] as string[],
    store: { ...setup.store } as Record<string, unknown>,
  }
  const forks = [...(setup.forks ?? [])]
  mock.env(on, { HOME: '/home/me', ...setup.env })
  const clock = mock.clock(on, { now: START })
  on('store.get', (_, e) => ({ value: seen.store[e.key] }))
  on('store.set', (_, e) => {
    seen.store[e.key] = e.value
    return { value: undefined }
  })
  on('command.register', (_, e) => ({ value: { command: e.name } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.end', () => ({ sessionId: 's1' }))
  on('session.id', () => ({ value: 's1' }))
  on('session.surfaces', () => ({ value: ['desktop'] as never }))
  on('session.usage', () => ({ value: { context: { tokens: setup.tokens ?? 1000, window: 200_000 } } as never }))
  on('fs.list', (_, e) => {
    seen.lists.push(e.path)
    const prefix = `${e.path}/`
    const names = (setup.projects ?? []).filter(p => p.startsWith(prefix)).map(p => p.slice(prefix.length))
    if (names.length === 0) return { deny: 'ENOENT' }
    return { value: names.map(name => ({ name, kind: 'dir', size: 0, mtimeMs: 0, isLink: false })) as never }
  })
  on('fs.exists', (_, e) => ({ value: e.path in files }))
  on('fs.stat', (_, e) => {
    const text = files[e.path]
    if (text === undefined) return { deny: 'ENOENT' }
    return { value: { kind: 'file', size: setup.sizes?.[e.path] ?? text.length, mtimeMs: 0, isLink: false } as never }
  })
  on('fs.read', (_, e) => {
    seen.reads.push(e.path)
    const text = files[e.path]
    if (text === undefined) return { deny: 'ENOENT' }
    if ((setup.sizes?.[e.path] ?? text.length) > 4 * MIB) return { deny: 'over 4 MiB' }
    return { value: text }
  })
  on('fs.write', (_, e) => {
    if (setup.failWrites?.includes(e.path)) return { deny: 'EACCES' }
    seen.writes.push({ path: e.path, text: e.text })
    files[e.path] = e.text
    return { value: undefined }
  })
  on('process.run', (_, e) => {
    seen.runs.push([...e.argv])
    return { value: { exitCode: 0, stdout: setup.tails?.[e.argv.at(-1) ?? ''] ?? '', stderr: '' } as never }
  })
  on('model.fork', async (_, e) => {
    seen.forks.push(e)
    if (setup.forkMs !== undefined) await clock.sleep(setup.forkMs)
    const result = forks.shift() ?? { isAnswered: true, read: 90_000 }
    const usage = { input_tokens: 5, output_tokens: 1, cache_creation_input_tokens: 0, cache_read_input_tokens: 0 }
    if (!result.isAnswered) return { value: { isAnswered: false, reason: result.reason, usage } as never }
    return { value: { isAnswered: true, text: 'ok', usage: { ...usage, cache_read_input_tokens: result.read } } as never }
  })
  // What the engine draws when the plugin draws nothing of its own.
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>engine</Text>
  })
  on('prompt.submit', (_, e) => ({ text: e.text }))
  on('turn.start', (_, e) => ({ turnId: e.turnId }))
  on('turn.complete', () => ({ text: '' }))
  on('session.measure', () => ({ changed: [] }))
  on('turn.step', async function* (_, e) {
    return { turnId: e.turnId, index: e.index, answer: '', toolUses: [], stopReason: 'end_turn', usage: null }
  })
  return { seen, clock, files }
}

const TURN_USAGE = { input_tokens: 3, output_tokens: 10, cache_creation_input_tokens: 500, cache_read_input_tokens: 0, model: 'm' }

async function start($: Engine) {
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true } as never)
}

// One main-chat turn: a typed prompt, one request, and the reply.
async function turn($: Engine, clock: { settle: () => Promise<void> }, turnId: string, agentId?: string) {
  const agent = agentId === undefined ? {} : { agentId }
  if (agentId === undefined) {
    await $.prompt.submit({ text: 'go on', wait: false, origin: { kind: 'composer' } } as never)
  }
  await $.turn.start({ text: 'go on', turnId, ...agent } as never)
  const stream = $.turn.step({ turnId, index: 0, model: 'm', messageCount: 1, ...agent } as TurnStepInput)
  for await (const _ of stream) {
    // nothing streams from the stand-in
  }
  await stream.result
  await $.turn.complete({ turnId, answer: 'done', durationMs: 1, isAborted: false, usage: TURN_USAGE, ...agent } as never)
  await clock.settle()
}

const BAND = (surface: 'terminal' | 'desktop') =>
  ({
    plugin: 'cache-clock',
    surface,
    component: 'AbovePrompt',
    requestId: 'band',
    props: { hasSurvey: false, bodyColumns: 80 },
  }) as never

// The band's words on a surface, or 'engine' when the plugin draws nothing.
async function band($: Engine, surface: 'terminal' | 'desktop' = 'terminal') {
  const ui = await $.ui.mount(BAND(surface))
  const found = await ui.find({ type: 'Text' })
  await ui.unmount()
  return found?.text ?? ''
}

const CONFIG = '/cfg'
const TRANSCRIPT = `${CONFIG}/projects/-repo/s1.jsonl`

test('with CLAUDE_CONFIG_DIR set, a 1-hour chat counts down from 60:00 and goes cold on time', async ($, on) => {
  const { seen, clock } = engine(on, {
    env: { CLAUDE_CONFIG_DIR: CONFIG },
    projects: [`${CONFIG}/projects/-other`, `${CONFIG}/projects/-repo`],
    files: { [TRANSCRIPT]: [USER, reply({ h1: 5000 })].join('\n') },
  })
  await start($)
  await turn($, clock, 't1')

  for (const surface of ['terminal', 'desktop'] as const) {
    expect(await band($, surface)).toMatch(/warm.*60:00.*1h/)
  }
  await clock.advance(59 * MINUTE)
  expect(await band($)).toMatch(/1:00/)
  await clock.advance(MINUTE)
  expect(await band($)).toMatch(/cold/i)
  expect([...seen.lists, ...seen.reads].every(path => path.startsWith(CONFIG))).toBe(true)
})

const HOME_TRANSCRIPT = '/home/me/.claude/projects/-repo/s1.jsonl'
const HOME_PROJECTS = ['/home/me/.claude/projects/-repo']

test('a 5-minute chat counts down from 5:00, and an unknown one is counted as 5 minutes', async ($, on) => {
  const { clock, files } = engine(on, { projects: HOME_PROJECTS, files: { [HOME_TRANSCRIPT]: reply({ m5: 10 }) } })
  await start($)
  await turn($, clock, 't1')
  expect(await band($)).toMatch(/5:00.*\(5m\)/)
  await clock.advance(5 * MINUTE)
  expect(await band($)).toMatch(/cold/i)

  files[HOME_TRANSCRIPT] = USER
  await turn($, clock, 't2')
  await clock.advance(2000)
  expect(await band($)).toMatch(/4:58.*5m\?/)
})

test('no band before the first reply, and a subagent turn does not restart the clock', async ($, on) => {
  const { clock, files } = engine(on, { projects: HOME_PROJECTS })
  await start($)
  expect(await band($)).toBe('engine')
  files[HOME_TRANSCRIPT] = reply({ m5: 10 })
  await turn($, clock, 't1')
  await clock.advance(4 * MINUTE)
  await turn($, clock, 'a1', 'agent-1')
  expect(await band($)).toMatch(/1:00/)
})

test('a transcript over 4 MiB is read from its last 4,000,000 bytes', async ($, on) => {
  const { seen, clock } = engine(on, {
    projects: HOME_PROJECTS,
    files: { [HOME_TRANSCRIPT]: 'x' },
    sizes: { [HOME_TRANSCRIPT]: 5 * MIB },
    tails: { [HOME_TRANSCRIPT]: ['_input_tokens":4}}}', reply({ h1: 10 })].join('\n') },
  })
  await start($)
  await turn($, clock, 't1')
  expect(seen.runs.length).toBeGreaterThan(0)
  for (const argv of seen.runs) expect(argv).toEqual(['tail', '-c', '4000000', HOME_TRANSCRIPT])
  expect(await band($)).toMatch(/60:00/)
})

test('a reply not yet in the transcript is read again two seconds later', async ($, on) => {
  const { clock, files } = engine(on, { projects: HOME_PROJECTS, files: { [HOME_TRANSCRIPT]: USER } })
  await start($)
  await turn($, clock, 't1')
  expect(await band($)).toMatch(/5m\?/)
  files[HOME_TRANSCRIPT] = reply({ h1: 10 }, { timestamp: new Date(START + 1000).toISOString() })
  await clock.advance(2000)
  expect(await band($)).toMatch(/59:58.*\(1h\)/)
})

test('a resumed chat starts from its newest reply in the transcript', async ($, on) => {
  const at = START - 2 * MINUTE
  const line = reply({ m5: 10 }, { timestamp: new Date(at).toISOString() })
  const { clock } = engine(on, { projects: HOME_PROJECTS, files: { [HOME_TRANSCRIPT]: line } })
  await start($)
  await clock.settle()
  expect(await band($)).toMatch(/3:00/)
})

const PING = 'Reply with the single word: ok'
const SECOND = 1000

async function command($: Engine, name: string, args = '') {
  const result = await $.command.run({ command: name, args, origin: { kind: 'composer' } } as never)
  return (result as { text?: string }).text ?? ''
}

// A 5-minute chat with one reply at START.
async function fiveMinuteChat($: Engine, on: On, setup: Setup = {}) {
  const made = engine(on, { projects: HOME_PROJECTS, ...setup })
  await start($)
  made.files[HOME_TRANSCRIPT] = reply({ m5: 10 })
  await turn($, made.clock, 't1')
  return made
}

test('keep warm is off until /keepwarm: the cache goes cold with no ping', async ($, on) => {
  const { seen, clock } = await fiveMinuteChat($, on)
  await clock.advance(10 * MINUTE)
  expect(seen.forks).toEqual([])
  expect(await band($)).toMatch(/cold/i)
})

test('/keepwarm pings 45 seconds before cold, and a ping that reads the cache starts the count again', async ($, on) => {
  const { seen, clock } = await fiveMinuteChat($, on)
  expect(await command($, 'keepwarm')).toMatch(/on/i)
  await clock.advance(4 * MINUTE + 14 * SECOND)
  expect(seen.forks).toEqual([])
  await clock.advance(SECOND)
  expect(seen.forks.map(f => f.prompt)).toEqual([PING])
  expect(seen.forks[0]?.effort).toBeUndefined()
  expect(await band($)).toMatch(/5:00.*keep warm on \(1\/30\)/)
  await clock.advance(4 * MINUTE + 15 * SECOND)
  expect(seen.forks.length).toBe(2)
})

test('a typed prompt stops keep warm', async ($, on) => {
  const { seen, clock } = await fiveMinuteChat($, on)
  await command($, 'keepwarm', 'on')
  await $.prompt.submit({ text: 'next thing', wait: false, origin: { kind: 'composer' } } as never)
  await clock.advance(10 * MINUTE)
  expect(seen.forks).toEqual([])
  expect(await band($)).toMatch(/cold/i)
})

test('keep warm stops at 30 pings, 3 failures in a row, or 2 hours', () => {
  const warm = { isOn: true, isArmed: false, startedAt: 0, pings: 0, failures: 0, note: '' }
  expect(keepWarmStop({ ...warm, pings: 29, failures: 2 }, 2 * 60 * MINUTE - 1)).toBe(null)
  expect(keepWarmStop({ ...warm, pings: 30 }, 0)).toMatch(/30/)
  expect(keepWarmStop({ ...warm, failures: 3 }, 0)).toMatch(/three|3/)
  expect(keepWarmStop(warm, 2 * 60 * MINUTE)).toMatch(/2 hours/)
})

test('in a 5-minute chat keep warm pings every 4:15 until 2 hours are up, then lets the cache go cold', async ($, on) => {
  const { seen, clock } = await fiveMinuteChat($, on)
  await command($, 'keepwarm')
  for (let i = 0; i < 3; i += 1) await clock.advance(60 * MINUTE)
  // 28 pings fit in 2 hours; the 29th would fall at 2:03:15.
  expect(seen.forks.length).toBe(28)
  expect(await band($)).toMatch(/cold.*keep warm stopped: 2 hours/i)
})

test('keep warm stops after three pings in a row that do not read the cache', async ($, on) => {
  const failed = { isAnswered: false, reason: 'api-error' } as const
  const { seen, clock } = await fiveMinuteChat($, on, { forks: [{ isAnswered: true, read: 0 }, failed, failed] })
  await command($, 'keepwarm')
  await clock.advance(10 * MINUTE)
  expect(seen.forks.length).toBe(3)
  expect(await band($)).toMatch(/cold.*keep warm stopped/i)
})

test('keep warm stops two hours after /keepwarm', async ($, on) => {
  const made = engine(on, { projects: HOME_PROJECTS })
  await start($)
  made.files[HOME_TRANSCRIPT] = reply({ h1: 10 })
  await turn($, made.clock, 't1')
  await command($, 'keepwarm')
  for (let i = 0; i < 4; i += 1) await made.clock.advance(60 * MINUTE)
  // Pings at 59:15 and 1:58:30; the next would fall past two hours.
  expect(made.seen.forks.length).toBe(2)
})

test('/keepwarm off stops it, and /keepwarm with nothing to fork stops by itself', async ($, on) => {
  const { seen, clock } = await fiveMinuteChat($, on, { forks: [{ isAnswered: false, reason: 'nothing-to-fork' }] })
  await command($, 'keepwarm', 'on')
  await clock.advance(5 * MINUTE)
  expect(seen.forks.length).toBe(1)
  await clock.advance(10 * MINUTE)
  expect(seen.forks.length).toBe(1)

  await turn($, clock, 't2')
  expect(await command($, 'keepwarm', 'on')).toMatch(/on/i)
  expect(await command($, 'keepwarm', 'off')).toMatch(/off/i)
  await clock.advance(10 * MINUTE)
  expect(seen.forks.length).toBe(1)
})

test('a ping due while a turn runs waits for the turn', async ($, on) => {
  const { seen, clock } = await fiveMinuteChat($, on)
  await command($, 'keepwarm')
  await $.turn.start({ text: 'task finished', turnId: 't2' } as never)
  await clock.advance(5 * MINUTE)
  expect(seen.forks).toEqual([])
  await $.turn.complete({ turnId: 't2', answer: '', durationMs: 1, isAborted: false, usage: TURN_USAGE } as never)
  await clock.advance(4 * MINUTE + 15 * SECOND)
  expect(seen.forks.length).toBe(1)
})

test('a cold chat over 150,000 tokens offers a handoff that asks the handoff plugin for one', async ($, on) => {
  const { seen, clock } = await fiveMinuteChat($, on, { tokens: 150_001 })
  await clock.advance(5 * MINUTE)
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount(BAND(surface))
    expect((await ui.find({ type: 'Button', key: 'handoff' }))?.text).toMatch(/hand off/i)
    await ui.unmount()
  }
  const ui = await $.ui.mount(BAND('desktop'))
  await ui.press({ key: 'handoff' })
  await ui.unmount()
  const asked = seen.writes.filter(w => w.path === '/home/me/.claude/handoffs/.request-s1')
  expect(asked.map(w => w.text)).toEqual([String(clock.now())])
  const after = await $.ui.mount(BAND('desktop'))
  expect(await after.find({ type: 'Button', key: 'handoff' })).toBeUndefined()
  await after.unmount()
})

test('no handoff at 150,000 tokens or while the cache is warm', async ($, on) => {
  const { clock } = await fiveMinuteChat($, on, { tokens: 150_000 })
  const warm = await $.ui.mount(BAND('terminal'))
  expect(await warm.find({ type: 'Button', key: 'handoff' })).toBeUndefined()
  await warm.unmount()
  await clock.advance(5 * MINUTE)
  const cold = await $.ui.mount(BAND('terminal'))
  expect(await cold.find({ type: 'Button', key: 'handoff' })).toBeUndefined()
  await cold.unmount()
})

test('the context size the engine pushes decides the handoff', async ($, on) => {
  const { clock } = await fiveMinuteChat($, on, { tokens: 1000 })
  await $.session.measure({ context: { tokens: 200_000, window: 1_000_000 }, rateLimits: [], changed: ['context'] } as never)
  await clock.advance(5 * MINUTE)
  const ui = await $.ui.mount(BAND('terminal'))
  expect(await ui.find({ type: 'Button', key: 'handoff' })).toBeDefined()
  await ui.unmount()
})

test('switches.json turns the plugin off or hides the band', async ($, on) => {
  const { seen, clock, files } = await fiveMinuteChat($, on)
  files['/home/me/.claude/mods/switches.json'] = '{"cache-clock:hidden": true}'
  await command($, 'keepwarm')
  await clock.advance(5 * SECOND)
  expect(await band($)).toBe('engine')

  files['/home/me/.claude/mods/switches.json'] = '{"cache-clock": false}'
  await clock.advance(5 * MINUTE)
  expect(await band($)).toBe('engine')
  expect(seen.forks).toEqual([])
})

test('/cacheclock hides and shows the band, and the choice is kept', async ($, on) => {
  const { seen, clock } = await fiveMinuteChat($, on)
  expect(await command($, 'cacheclock', 'hide')).toMatch(/hidden/i)
  expect(await band($)).toBe('engine')
  expect(seen.store.isShown).toBe(false)
  expect(await command($, 'cacheclock')).toMatch(/shown/i)
  expect(await band($)).toMatch(/warm/)
  await clock.settle()
})

test('the choice to hide the band is read back at the start', async ($, on) => {
  const { clock } = await fiveMinuteChat($, on, { store: { isShown: false } })
  await clock.settle()
  expect(await band($)).toBe('engine')
})

test('/clear drops the clock and keep warm', async ($, on) => {
  const { seen, clock } = await fiveMinuteChat($, on)
  await command($, 'keepwarm')
  await $.session.end({ reason: 'clear' } as never)
  expect(await band($)).toBe('engine')
  await clock.advance(10 * MINUTE)
  expect(seen.forks).toEqual([])
})

test('with CLAUDE_CONFIG_DIR set, the handoff request goes under it', async ($, on) => {
  const made = engine(on, { env: { CLAUDE_CONFIG_DIR: CONFIG }, projects: [`${CONFIG}/projects/-repo`], tokens: 200_000 })
  await start($)
  made.files[TRANSCRIPT] = reply({ m5: 10 })
  await turn($, made.clock, 't1')
  await made.clock.advance(5 * MINUTE)
  const ui = await $.ui.mount(BAND('terminal'))
  await ui.press({ key: 'handoff' })
  await ui.unmount()
  expect(made.seen.writes.map(w => w.path)).toEqual([`${CONFIG}/handoffs/.request-s1`])
})

test('a handoff request that cannot be written leaves the button to try again', async ($, on) => {
  const { clock } = await fiveMinuteChat($, on, { tokens: 200_000, failWrites: ['/home/me/.claude/handoffs/.request-s1'] })
  await clock.advance(5 * MINUTE)
  const ui = await $.ui.mount(BAND('terminal'))
  await ui.press({ key: 'handoff' })
  await clock.settle()
  await ui.unmount()
  const again = await $.ui.mount(BAND('terminal'))
  expect(await again.find({ type: 'Button', key: 'handoff' })).toBeDefined()
  await again.unmount()
})

test('/keepwarm while cold waits for the next reply', async ($, on) => {
  const { seen, clock } = await fiveMinuteChat($, on)
  await clock.advance(6 * MINUTE)
  await command($, 'keepwarm', 'on')
  await clock.advance(10 * MINUTE)
  expect(seen.forks).toEqual([])
  await turn($, clock, 't2')
  await clock.advance(4 * MINUTE + 15 * SECOND)
  expect(seen.forks.length).toBe(1)
})

test('keep warm never retries a ping after the cache has gone cold', async ($, on) => {
  const failed = { isAnswered: false, reason: 'api-error' } as const
  // Each ping takes 20 seconds: the first ends 25 seconds before cold, and a retry
  // started 10 seconds later would end after it.
  const { seen, clock } = await fiveMinuteChat($, on, { forks: [failed, failed], forkMs: 20 * SECOND })
  await command($, 'keepwarm')
  await clock.advance(4 * MINUTE + 35 * SECOND)
  expect(await band($)).toMatch(/warm · 0:25 left.*keep warm stopped: too close to cold to try again/i)
  await clock.advance(10 * MINUTE)
  expect(seen.forks.length).toBe(1)
})

test('a turn that starts and ends while a ping runs keeps its own count', async ($, on) => {
  const { clock } = await fiveMinuteChat($, on, { forkMs: 20 * SECOND })
  await command($, 'keepwarm')
  // The ping starts at 4:15 and ends at 4:35; a turn with no typed prompt runs at 4:20.
  await clock.advance(4 * MINUTE + 20 * SECOND)
  await $.turn.start({ text: 'task finished', turnId: 't2' } as never)
  const stream = $.turn.step({ turnId: 't2', index: 0, model: 'm', messageCount: 1 } as TurnStepInput)
  for await (const _ of stream) {
    // nothing streams from the stand-in
  }
  await stream.result
  await $.turn.complete({ turnId: 't2', answer: 'done', durationMs: 1, isAborted: false, usage: TURN_USAGE } as never)
  await clock.advance(15 * SECOND)
  // Counted from the turn at 4:20, not from the ping at 4:15.
  expect(await band($)).toMatch(/4:45 left/)
})

test('a ping that ends while a typed turn runs leaves the clock to that turn', async ($, on) => {
  const { seen, clock } = await fiveMinuteChat($, on, { forkMs: 20 * SECOND })
  await command($, 'keepwarm')
  await clock.advance(4 * MINUTE + 15 * SECOND)
  expect(seen.forks.length).toBe(1)
  await $.turn.start({ text: 'task finished', turnId: 't2' } as never)
  await clock.advance(20 * SECOND)
  // The ping did not start the count again, so the cache reads as it was.
  expect(await band($)).toMatch(/0:25/)
})

test('a newer reply not yet in the transcript is read two seconds later, past an older reply', async ($, on) => {
  const old = reply({ m5: 10 }, { timestamp: new Date(START - 60 * MINUTE).toISOString() })
  const made = engine(on, { projects: HOME_PROJECTS })
  await start($)
  made.files[HOME_TRANSCRIPT] = old
  await turn($, made.clock, 't1')
  expect(await band($)).toMatch(/\(5m\)/)
  made.files[HOME_TRANSCRIPT] = [old, reply({ h1: 10 }, { timestamp: new Date(START + 1000).toISOString() })].join('\n')
  await made.clock.advance(2000)
  expect(await band($)).toMatch(/59:58.*\(1h\)/)
})
