import { expect, mock, test } from 'claude-code/testing'
import type { AgentSpawnInput, ModelCompleteInput, On } from 'claude-code'
import type { Engine } from 'claude-code/testing'

import { DEFAULT_TIERS } from './models'

const USAGE = { input_tokens: 400, output_tokens: 20, cache_creation_input_tokens: 0, cache_read_input_tokens: 0 }
const RUN_USAGE = { input_tokens: 10_000, output_tokens: 2_000, cache_creation_input_tokens: 0, cache_read_input_tokens: 0 }

type Setup = {
  // What the judge answers; null for no answer.
  judge?: string | null
  switches?: string
}

// Stands in for the engine beneath the plugin, and records what the plugin asked of it.
function engine(on: On, setup: Setup = {}) {
  const seen = {
    completes: [] as ModelCompleteInput[],
    spawns: [] as AgentSpawnInput[],
    runs: [] as { argv: readonly string[]; stdin?: string }[],
    exists: [] as string[],
    files: {} as Record<string, string>,
  }
  if (setup.switches !== undefined) seen.files['/home/me/.claude/mods/switches.json'] = setup.switches
  mock.env(on, { HOME: '/home/me' })
  mock.store(on)
  const clock = mock.clock(on)
  on('session.id', () => ({ value: 's1' }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('command.register', () => ({ value: { command: 'model-router' } }))
  on('ui.open', () => ({ value: undefined }) as never)
  on('ui.close', () => ({ value: undefined }) as never)
  on('ui.log', () => ({ value: undefined }) as never)
  on('ui.status', () => ({ value: undefined }) as never)
  on('model.complete', (_, e) => {
    seen.completes.push(e)
    const text = setup.judge === undefined ? '{"tier":"fast","confidence":0.86,"effort":1,"effort_confidence":0.7,"risky":0.02}' : setup.judge
    return { value: text === null ? { isAnswered: false, reason: 'aborted', usage: USAGE } : { isAnswered: true, text, usage: USAGE } } as never
  })
  on('fs.exists', (_, e) => {
    seen.exists.push(e.path)
    return { value: e.path in seen.files }
  })
  on('fs.read', (_, e) => (e.path in seen.files ? { value: seen.files[e.path] as string } : { deny: 'no such file' }))
  on('fs.write', (_, e) => {
    seen.files[e.path] = e.text
    return { value: undefined }
  })
  on('process.run', (_, e) => {
    seen.runs.push({ argv: e.argv, stdin: e.init?.stdin })
    const path = e.argv[4]
    if (e.argv[0] === '/bin/sh' && path) seen.files[path] = (seen.files[path] ?? '') + (e.init?.stdin ?? '')
    return { value: { exitCode: 0, stdout: '', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('agent.spawn', (_, e) => {
    seen.spawns.push(e)
    return { model: e.model ?? e.parentModel, agentId: `agent-${seen.spawns.length}` }
  })
  on('turn.complete', () => ({ text: '' }))
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>engine</Text>
  })
  return { seen, clock }
}

async function start($: Engine) {
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true } as never)
}

const SPAWN: AgentSpawnInput = {
  tool_use_id: 'tu1',
  prompt: 'List the files in this folder.',
  description: 'List files',
  subagentType: 'general-purpose',
  provider: { kind: 'engine' } as never,
  parentModel: 'claude-opus-5-5',
  background: false,
  fork: false,
}

const spawn = ($: Engine, change: Partial<AgentSpawnInput> = {}) => $.agent.spawn({ ...SPAWN, ...change })

const finish = ($: Engine, agentId: string) =>
  $.turn.complete({ answer: 'done', durationMs: 10, isAborted: false, turnId: 't1', agentId, usage: RUN_USAGE, reason: 'answer' } as never)

const pane = ($: Engine) =>
  $.ui.mount({
    plugin: 'model-router',
    surface: 'terminal',
    component: 'Pane',
    requestId: 'model-router',
    props: { title: 'Subagent Model Selector', isFocused: true, bodyColumns: 80 } as never,
  })

const LEDGER = '/home/me/.claude/mods-logs/savings.jsonl'

test('a mechanical task moves to the fast tier and shows Haiku’s tier and confidence in the pane', async ($, on) => {
  const { seen, clock } = engine(on)
  await start($)
  const result = await spawn($)
  await clock.settle()

  expect(seen.completes.length).toBe(1)
  expect(seen.completes[0]?.model).toBe('haiku')
  expect(seen.completes[0]?.prompt).toMatch(/List the files in this folder/)
  expect(seen.spawns[0]?.model).toBe('claude-haiku-5-5')
  expect(result.model).toBe('claude-haiku-5-5')

  const ui = await pane($)
  expect(await ui.find({ type: 'Text', text: /Haiku said simple work · confidence 0\.86/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /Ran on Haiku · would have run on Opus/ })).toBeDefined()
})

test('a ledger line is added when the subagent ends', async ($, on) => {
  const { seen, clock } = engine(on)
  await start($)
  await spawn($)
  expect(seen.files[LEDGER]).toBe(undefined)
  await finish($, 'agent-1')
  await clock.settle()

  const lines = (seen.files[LEDGER] ?? '').trim().split('\n')
  expect(lines.length).toBe(1)
  const line = JSON.parse(lines[0] as string)
  expect(line.mod).toBe('model-router')
  expect(line.model).toBe('claude-haiku-5-5')
  expect(line.replaced).toBe('claude-opus-5-5')
  expect(line.changed).toBe(true)
  expect(line.cost_usd.saved > 0).toBe(true)
  expect(line.helper).toEqual({ model: 'claude-haiku-5-5', in: 400, out: 20 })
})

test('a spawn that names its own model is judged too, and can move down', async ($, on) => {
  const { seen, clock } = engine(on)
  await start($)
  await spawn($, { model: 'opus', parentModel: 'claude-sonnet-5-5' })
  await clock.settle()

  expect(seen.completes.length).toBe(1)
  expect(seen.spawns[0]?.model).toBe('claude-haiku-5-5')
})

test('a confidence under the bar keeps the model, and the card says why', async ($, on) => {
  const { seen, clock } = engine(on, { judge: '{"tier":"fast","confidence":0.59,"risky":0.01}' })
  await start($)
  await spawn($)
  await clock.settle()

  expect(seen.spawns[0]?.model).toBe(undefined)
  const ui = await pane($)
  expect(await ui.find({ type: 'Text', text: 'Kept Opus: confidence 0.59 under the 0.6 bar.' })).toBeDefined()
})

test('no judge answer leaves the spawn as it was and writes no ledger line', async ($, on) => {
  const { seen, clock } = engine(on, { judge: null })
  await start($)
  await spawn($)
  await finish($, 'agent-1')
  await clock.settle()

  expect(seen.spawns[0]?.model).toBe(undefined)
  expect(seen.files[LEDGER]).toBe(undefined)
})

test('forks and resumes are not judged', async ($, on) => {
  const { seen, clock } = engine(on)
  await start($)
  await spawn($, { fork: true })
  await spawn($, { resume: { agentId: 'agent-0' } })
  await clock.settle()

  expect(seen.completes.length).toBe(0)
  expect(seen.spawns.map(s => s.model)).toEqual([undefined, undefined])
})

test('switches.json turns the plugin off', async ($, on) => {
  const { seen, clock } = engine(on, { switches: '{"model-router": false}' })
  await start($)
  await spawn($)
  await clock.settle()

  expect(seen.completes.length).toBe(0)
  expect(seen.spawns[0]?.model).toBe(undefined)
})

test('the pane opens the detail file with xdg-open', async ($, on) => {
  const { seen, clock } = engine(on)
  await start($)
  await spawn($)
  await finish($, 'agent-1')
  await clock.settle()

  const ui = await pane($)
  await ui.press({ key: 'card-1' })
  await ui.press({ key: 'file-1' })
  const opened = seen.runs.find(r => r.argv[0] === 'xdg-open')
  expect(opened?.argv[1]).toMatch(/^\/home\/me\/\.claude\/mods-logs\/model-router\/.+\.md$/)
})

// Left without options, the kit hands register the userConfig defaults from
// plugin.json, so this line shows those defaults. They must match the table.
test('plugin.json’s tier defaults are the model table’s ids', async ($, on) => {
  engine(on)
  await start($)
  const shown = await $.command.run({ command: 'model-router', args: '', origin: { kind: 'composer' } } as never)
  expect(shown.text).toContain(`Tiers: ${DEFAULT_TIERS.fast} / ${DEFAULT_TIERS.balanced} / ${DEFAULT_TIERS.deep}.`)
})
