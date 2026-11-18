import { expect, mock, test } from 'claude-code/testing'
import type { ConfigRow, ConfigSetInput, ModelCompleteInput, On, TurnStepInput } from 'claude-code'
import type { Engine } from 'claude-code/testing'

import { configDir, isEffortRow, optionFor, parsePick, parseSwitches } from './effort'

const USAGE = { input_tokens: 10, output_tokens: 5, cache_creation_input_tokens: 0, cache_read_input_tokens: 0 }

const ROW: ConfigRow = {
  key: 'effortLevel',
  label: 'Effort',
  kind: 'choice',
  value: 'medium',
  options: ['low', 'medium', 'high', 'xhigh', 'max'],
  provider: { plugin: 'engine', tier: 'core' } as ConfigRow['provider'],
  isLocked: false,
}

type Setup = {
  rows?: ConfigRow[]
  pick?: string | null
  // Picks returned in turn, one per model call; `pick` once they run out.
  pickQueue?: string[]
  switches?: string
  env?: Record<string, string>
  store?: Record<string, unknown>
  deny?: string
  surfaces?: string[]
}

// Stands in for the engine beneath the plugin, and records what the plugin asked of it.
function engine(on: On, setup: Setup = {}) {
  const seen = {
    completes: [] as ModelCompleteInput[],
    sets: [] as ConfigSetInput[],
    writes: [] as { path: string; text: string }[],
    reads: [] as string[],
    sent: [] as TurnStepInput[],
    store: { ...setup.store } as Record<string, unknown>,
  }
  on('store.get', (_, e) => ({ value: seen.store[e.key] }))
  on('store.set', (_, e) => {
    seen.store[e.key] = e.value
    return { value: undefined }
  })
  mock.env(on, { HOME: '/home/me', ...setup.env })
  const clock = mock.clock(on)
  on('command.register', () => ({ value: { command: 'effort-optimizer' } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.messages', () => ({ value: [] }))
  on('session.surfaces', () => ({ value: (setup.surfaces ?? ['desktop']) as never }))
  on('config.list', () => ({ value: setup.rows ?? [] }))
  on('config.set', (_, e) => {
    seen.sets.push(e)
    return setup.deny !== undefined ? { deny: setup.deny } : { value: e.value }
  })
  on('model.complete', (_, e) => {
    seen.completes.push(e)
    const queued = setup.pickQueue?.shift()
    const pick = queued !== undefined ? queued : setup.pick === undefined ? '{"level":"high","why":"changes several files"}' : setup.pick
    return {
      value:
        pick === null
          ? { isAnswered: false, reason: 'aborted', usage: USAGE }
          : { isAnswered: true, text: pick, usage: USAGE },
    }
  })
  on('fs.read', (_, e) => {
    seen.reads.push(e.path)
    if (e.path.endsWith('switches.json') && setup.switches !== undefined) return { value: setup.switches }
    return { deny: 'no such file' }
  })
  on('fs.write', (_, e) => {
    seen.writes.push({ path: e.path, text: e.text })
    return { value: undefined }
  })
  // What the engine draws when the plugin draws nothing of its own.
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>engine</Text>
  })
  on('prompt.submit', (_, e) => ({ text: e.text }))
  on('turn.start', (_, e) => ({ turnId: e.turnId }))
  on('turn.complete', () => ({ text: '' }))
  on('session.end', () => ({ sessionId: 's1' }))
  on('turn.step', async function* (_, e) {
    seen.sent.push(e)
    return { turnId: e.turnId, index: e.index, answer: '', toolUses: [], stopReason: 'end_turn', usage: null }
  })
  return { seen, clock }
}

async function start($: Engine) {
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true } as never)
}

// Runs one main-chat request through the chain and returns the effort it went out with.
async function step($: Engine, turnId: string, index: number, effort: string | undefined, agentId?: string) {
  const stream = $.turn.step({
    turnId,
    index,
    model: 'test-model',
    messageCount: 1,
    ...(effort === undefined ? {} : { effort }),
    ...(agentId === undefined ? {} : { agentId }),
  } as TurnStepInput)
  for await (const _ of stream) {
    // nothing streams from the stand-in
  }
  await stream.result
}

// A typed prompt that starts turn `turnId`, its first request at `effort`.
async function prompt($: Engine, clock: { settle: () => Promise<void> }, text: string, turnId: string, effort = 'medium') {
  await $.prompt.submit({ text, wait: false, origin: { kind: 'composer' } } as never)
  await $.turn.start({ text, turnId })
  await step($, turnId, 0, effort)
  await clock.settle()
}

const BAND = (surface: 'terminal' | 'desktop') =>
  ({
    plugin: 'effort-optimizer',
    surface,
    component: 'AbovePrompt',
    requestId: 'band',
    props: { hasSurvey: false, bodyColumns: 80 },
  }) as never

const last = (sent: TurnStepInput[]) => sent.at(-1)?.effort

test('suggest is the default: the band offers the pick and nothing changes by itself', async ($, on) => {
  const { seen, clock } = engine(on)
  await start($)
  await prompt($, clock, 'split the parser into three modules', 't1')

  expect(seen.completes.length).toBe(1)
  expect(seen.completes[0]?.model).toBe('haiku')
  expect(seen.completes[0]?.prompt).toMatch(/split the parser/)
  expect(last(seen.sent)).toBe('medium')
  expect(seen.sets).toEqual([])

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount(BAND(surface))
    expect((await ui.find({ type: 'Button', key: 'switch' }))?.text).toBe('Switch to High')
    expect((await ui.find({ type: 'Text', text: /High/ }))?.text).toMatch(/changes several files/)
    await ui.unmount()
  }
})

test('Switch with an open effort setting changes it and the rest of the turn', async ($, on) => {
  const { seen, clock } = engine(on, { rows: [ROW] })
  await start($)
  await prompt($, clock, 'refactor the store', 't1')

  const ui = await $.ui.mount(BAND('desktop'))
  await ui.press({ key: 'switch' })
  expect(seen.sets.map(s => [s.key, s.value])).toEqual([['effortLevel', 'high']])
  expect((await ui.find({ type: 'Text', text: /High/ }))?.text).toMatch(/\/config/)
  await ui.unmount()

  await step($, 't1', 1, 'medium')
  expect(last(seen.sent)).toBe('high')
})

test('Switch with a locked setting sends the level on each main-chat request', async ($, on) => {
  const { seen, clock } = engine(on, { rows: [{ ...ROW, isLocked: true }] })
  await start($)
  await prompt($, clock, 'refactor the store', 't1')

  const ui = await $.ui.mount(BAND('terminal'))
  await ui.press({ key: 'switch' })
  expect((await ui.find({ type: 'Text', text: /High/ }))?.text).toMatch(/locked/)
  await ui.unmount()
  expect(seen.sets).toEqual([])

  await step($, 't1', 1, 'medium')
  expect(last(seen.sent)).toBe('high')
  await step($, 't1', 2, 'medium', 'agent-1')
  expect(last(seen.sent)).toBe('medium')
})

test('Switch with no effort setting holds the level into the next turn', async ($, on) => {
  const { seen, clock } = engine(on)
  await start($)
  await prompt($, clock, 'refactor the store', 't1')
  const ui = await $.ui.mount(BAND('terminal'))
  await ui.press({ key: 'switch' })
  await ui.unmount()

  await $.turn.complete({ turnId: 't1' } as never)
  await $.prompt.submit({ text: 'and the tests', wait: false, origin: { kind: 'composer' } } as never)
  await $.turn.start({ text: 'and the tests', turnId: 't2' })
  await step($, 't2', 0, 'medium')
  expect(last(seen.sent)).toBe('high')
})

test('a refused setting change falls back to the per-request level', async ($, on) => {
  const { seen, clock } = engine(on, { rows: [ROW], deny: 'managed' })
  await start($)
  await prompt($, clock, 'refactor the store', 't1')
  const ui = await $.ui.mount(BAND('desktop'))
  await ui.press({ key: 'switch' })
  await ui.unmount()

  expect(seen.sets.length).toBe(1)
  await step($, 't1', 1, 'medium')
  expect(last(seen.sent)).toBe('high')
})

test('Switch to a level the setting does not offer changes nothing', async ($, on) => {
  const { seen, clock } = engine(on, {
    rows: [{ ...ROW, options: ['low', 'medium', 'high'] }],
    pick: '{"level":"max","why":"hard proof"}',
  })
  await start($)
  await prompt($, clock, 'prove the scheduler is fair', 't1')
  const ui = await $.ui.mount(BAND('terminal'))
  await ui.press({ key: 'switch' })
  expect((await ui.find({ type: 'Text', text: /Max/ }))?.text).toMatch(/not offered/)
  await ui.unmount()

  expect(seen.sets).toEqual([])
  await step($, 't1', 1, 'medium')
  expect(last(seen.sent)).toBe('medium')
})

test('a pick that comes back after a newer prompt is dropped', async ($, on) => {
  const { seen, clock } = engine(on)
  await start($)
  await $.prompt.submit({ text: 'first prompt', wait: false, origin: { kind: 'composer' } } as never)
  await $.turn.start({ text: 'first prompt', turnId: 't1' })
  await step($, 't1', 0, 'medium')
  // A second prompt arrives before the first pick is back.
  await $.prompt.submit({ text: 'second prompt', wait: false, origin: { kind: 'composer' } } as never)
  await clock.settle()
  expect(seen.completes.length).toBe(1)

  const ui = await $.ui.mount(BAND('terminal'))
  expect((await ui.find({ type: 'Text' }))?.text).toBe('engine')
  await ui.unmount()
})

test('scripted runs that draw on no surface get no pick', async ($, on) => {
  const { seen, clock } = engine(on, { surfaces: [] })
  await start($)
  await prompt($, clock, 'refactor the store', 't1')
  await $.prompt.submit({ text: 'run the job', wait: false, origin: { kind: 'sdk' } } as never)
  await $.turn.start({ text: 'run the job', turnId: 't2' })
  await step($, 't2', 0, 'medium')
  await clock.settle()
  expect(seen.completes.length).toBe(1)
})

test('the desktop app counts as typed', async ($, on) => {
  const { seen, clock } = engine(on, { surfaces: ['desktop'] })
  await start($)
  await $.prompt.submit({ text: 'refactor the store', wait: false, origin: { kind: 'sdk' } } as never)
  await $.turn.start({ text: 'refactor the store', turnId: 't1' })
  await step($, 't1', 0, 'medium')
  await clock.settle()
  expect(seen.completes.length).toBe(1)
})

test('a locked setting that does not offer the level changes nothing', async ($, on) => {
  const { seen, clock } = engine(on, {
    rows: [{ ...ROW, isLocked: true, options: ['low', 'medium', 'high'] }],
    pick: '{"level":"max","why":"hard proof"}',
  })
  await start($)
  await prompt($, clock, 'prove the scheduler is fair', 't1')
  const ui = await $.ui.mount(BAND('desktop'))
  await ui.press({ key: 'switch' })
  await ui.unmount()
  await step($, 't1', 1, 'medium')
  expect(last(seen.sent)).toBe('medium')
})

test('in auto mode an unoffered pick lets an older held level go', async ($, on) => {
  const { seen } = engine(on, {
    rows: [{ ...ROW, isLocked: true, options: ['low', 'medium', 'high'] }],
    store: { mode: 'auto' },
    pickQueue: ['{"level":"high","why":"several files"}', '{"level":"max","why":"hard proof"}'],
  })
  await start($)
  for (const [text, turnId] of [['refactor the store', 't1'], ['prove it is fair', 't2']] as const) {
    await $.prompt.submit({ text, wait: false, origin: { kind: 'composer' } } as never)
    await $.turn.start({ text, turnId })
    await step($, turnId, 0, 'medium')
    if (turnId === 't1') {
      expect(last(seen.sent)).toBe('high')
      await $.turn.complete({ turnId } as never)
    }
  }
  expect(last(seen.sent)).toBe('medium')
  const ui = await $.ui.mount(BAND('terminal'))
  expect((await ui.find({ type: 'Text', text: /Max/ }))?.text).toMatch(/stopped sending High/)
  await ui.unmount()
})

test('/clear drops a pick that is still out', async ($, on) => {
  const { clock } = engine(on)
  await start($)
  await $.prompt.submit({ text: 'refactor the store', wait: false, origin: { kind: 'composer' } } as never)
  await $.turn.start({ text: 'refactor the store', turnId: 't1' })
  await step($, 't1', 0, 'medium')
  await $.session.end({ reason: 'clear' } as never)
  await clock.settle()

  const ui = await $.ui.mount(BAND('terminal'))
  expect((await ui.find({ type: 'Text' }))?.text).toBe('engine')
  await ui.unmount()
})

test('changing the level by hand lets the held level go', async ($, on) => {
  const { seen, clock } = engine(on)
  await start($)
  await prompt($, clock, 'refactor the store', 't1')
  const ui = await $.ui.mount(BAND('desktop'))
  await ui.press({ key: 'switch' })
  await ui.unmount()
  await $.turn.complete({ turnId: 't1' } as never)

  await step($, 't2', 0, 'low')
  expect(last(seen.sent)).toBe('low')
  await step($, 't2', 1, 'medium')
  expect(last(seen.sent)).toBe('medium')
})

test('auto mode is off until the command turns it on, then applies the pick itself', async ($, on) => {
  const { seen, clock } = engine(on, { rows: [ROW] })
  await start($)

  const shown = await $.command.run({ command: 'effort-optimizer', args: '', origin: { kind: 'composer' } } as never)
  expect(shown.text).toMatch(/suggest/)

  const set = await $.command.run({ command: 'effort-optimizer', args: 'auto', origin: { kind: 'composer' } } as never)
  expect(set.text).toMatch(/auto/)
  expect(seen.store.mode).toBe('auto')

  await $.prompt.submit({ text: 'rewrite the scheduler', wait: false, origin: { kind: 'composer' } } as never)
  await $.turn.start({ text: 'rewrite the scheduler', turnId: 't1' })
  await step($, 't1', 0, 'medium')
  expect(last(seen.sent)).toBe('high')
  expect(seen.sets.map(s => s.value)).toEqual(['high'])

  const bad = await $.command.run({ command: 'effort-optimizer', args: 'sometimes', origin: { kind: 'composer' } } as never)
  expect(bad.text).toMatch(/suggest\|auto/)

  await $.command.run({ command: 'effort-optimizer', args: 'suggest', origin: { kind: 'composer' } } as never)
  expect(seen.store.mode).toBe('suggest')
})

test('a stored auto mode survives a new session', async ($, on) => {
  const { seen } = engine(on, { store: { mode: 'auto' } })
  await start($)
  await $.prompt.submit({ text: 'rewrite the scheduler', wait: false, origin: { kind: 'composer' } } as never)
  await $.turn.start({ text: 'rewrite the scheduler', turnId: 't1' })
  await step($, 't1', 0, 'medium')
  expect(last(seen.sent)).toBe('high')
})

test('in auto mode a failed pick sends the level the user set', async ($, on) => {
  const { seen } = engine(on, { store: { mode: 'auto' }, pick: null })
  await start($)
  await $.prompt.submit({ text: 'rewrite the scheduler', wait: false, origin: { kind: 'composer' } } as never)
  await $.turn.start({ text: 'rewrite the scheduler', turnId: 't1' })
  await step($, 't1', 0, 'medium')
  expect(last(seen.sent)).toBe('medium')
})

test('switches.json turns the plugin off or hides the band', async ($, on) => {
  const off = engine(on, { switches: '{"effort-optimizer": false}', store: { mode: 'auto' } })
  await start($)
  await prompt($, off.clock, 'rewrite the scheduler', 't1')
  expect(off.seen.completes).toEqual([])
  expect(last(off.seen.sent)).toBe('medium')
  expect(off.seen.reads).toContain('/home/me/.claude/mods/switches.json')
})

test('a hidden band still lets auto mode work', async ($, on) => {
  const { seen } = engine(on, { switches: '{"effort-optimizer:hidden": true}', store: { mode: 'auto' } })
  await start($)
  await $.prompt.submit({ text: 'rewrite the scheduler', wait: false, origin: { kind: 'composer' } } as never)
  await $.turn.start({ text: 'rewrite the scheduler', turnId: 't1' })
  await step($, 't1', 0, 'medium')
  expect(last(seen.sent)).toBe('high')

  const ui = await $.ui.mount(BAND('terminal'))
  expect((await ui.find({ type: 'Text' }))?.text).toBe('engine')
  await ui.unmount()
})

test('a switch flipped in another chat reaches the band within a few seconds, with no prompt', async ($, on) => {
  const setup: Setup = {}
  const { clock } = engine(on, setup)
  await start($)
  await prompt($, clock, 'split the parser into three modules', 't1')
  const band = async () => {
    const ui = await $.ui.mount(BAND('desktop'))
    const text = (await ui.find({ type: 'Text' }))?.text
    await ui.unmount()
    return text
  }
  expect(await band()).toMatch(/High/)

  setup.switches = '{"effort-optimizer": false}'
  await clock.advance(3000)
  expect(await band()).toBe('engine')

  setup.switches = '{"effort-optimizer:hidden": true}'
  await clock.advance(3000)
  expect(await band()).toBe('engine')

  setup.switches = '{}'
  await clock.advance(3000)
  expect(await band()).toMatch(/High/)
})

test('CLAUDE_CONFIG_DIR moves the switches file', async ($, on) => {
  const { seen } = engine(on, { env: { CLAUDE_CONFIG_DIR: '/cfg' } })
  await start($)
  expect(seen.reads).toContain('/cfg/mods/switches.json')
})

test('slash commands, hidden prompts and notifications get no pick', async ($, on) => {
  const { seen, clock } = engine(on)
  await start($)
  for (const extra of [
    { command: { name: 'x', args: '' } },
    { isMeta: true },
    { origin: { kind: 'task-notification' } },
  ]) {
    await $.prompt.submit({ text: 'do it', wait: false, origin: { kind: 'composer' }, ...extra } as never)
    await $.turn.start({ text: 'do it', turnId: 'tx' })
    await step($, 'tx', 0, 'medium')
    await clock.settle()
  }
  expect(seen.completes).toEqual([])
})

test('a request with no effort gets no band and no change', async ($, on) => {
  const { seen, clock } = engine(on)
  await start($)
  await $.prompt.submit({ text: 'hello', wait: false, origin: { kind: 'composer' } } as never)
  await $.turn.start({ text: 'hello', turnId: 't1' })
  await step($, 't1', 0, undefined)
  await clock.settle()
  expect(seen.completes).toEqual([])
  expect(last(seen.sent)).toBeUndefined()
})

test('a pick equal to the current level shows no band', async ($, on) => {
  const { clock } = engine(on, { pick: '{"level":"medium","why":"routine"}' })
  await start($)
  await prompt($, clock, 'rename a variable', 't1')
  const ui = await $.ui.mount(BAND('desktop'))
  expect((await ui.find({ type: 'Text' }))?.text).toBe('engine')
  await ui.unmount()
})

test('the log is written only when it is switched on', async ($, on) => {
  const { seen, clock } = engine(on)
  await start($)
  await prompt($, clock, 'refactor the store', 't1')
  expect(seen.writes).toEqual([])
})

test('with the log on, picks go to the log file', { options: { log: true } }, async ($, on) => {
  const { seen, clock } = engine(on)
  await start($)
  await prompt($, clock, 'refactor the store', 't1')
  const written = seen.writes.filter(w => w.path === '/home/me/.claude/mods-logs/effort-optimizer.log')
  expect(written.length > 0).toBe(true)
  expect(written.at(-1)?.text).toMatch(/high/)
})

test('helpers read picks, switches, rows and the configuration folder', () => {
  expect(parsePick('{"level":"xhigh","why":"big"}')).toEqual({ level: 'xhigh', why: 'big' })
  expect(parsePick('I would go with Extra high here.')?.level).toBe('xhigh')
  expect(parsePick('```json\n{"level": "LOW", "why": "one line"}\n```')).toEqual({ level: 'low', why: 'one line' })
  expect(parsePick('no idea')).toBeNull()

  expect(parseSwitches(undefined)).toEqual({ isOff: false, isHidden: false })
  expect(parseSwitches('not json')).toEqual({ isOff: false, isHidden: false })
  expect(parseSwitches('[false]')).toEqual({ isOff: false, isHidden: false })
  expect(parseSwitches('{"effort-optimizer": false, "effort-optimizer:hidden": true}')).toEqual({
    isOff: true,
    isHidden: true,
  })

  expect(isEffortRow(ROW)).toBe(true)
  expect(isEffortRow({ ...ROW, kind: 'boolean', options: undefined })).toBe(false)
  expect(isEffortRow({ ...ROW, key: 'theme', label: 'Theme', options: ['dark', 'light'] })).toBe(false)
  expect(optionFor({ ...ROW, options: ['Low', 'Medium', 'High', 'Extra high', 'Max'] }, 'xhigh')).toBe('Extra high')
  expect(optionFor({ ...ROW, options: ['low', 'medium', 'high'] }, 'max')).toBeUndefined()

  expect(configDir('/home/me', undefined)).toBe('/home/me/.claude')
  expect(configDir('/home/me', ' /cfg/ ')).toBe('/cfg')
  expect(configDir('/home/me', '~/cc')).toBe('/home/me/cc')
  expect(configDir('/home/me', '~')).toBe('/home/me')
})
