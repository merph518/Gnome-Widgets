import { expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

import { parseHookOutput } from './classic'

type Ran = { argv: readonly string[]; stdin?: string; env?: Record<string, string> }

// Stands in for the engine beneath the plugin: the session, and every process the
// plugin starts, answered by `answer` from the script's name. With `stubClock` false
// the test brings its own clock.
function engine(
  on: On,
  answer: (argv: readonly string[]) => { exitCode?: number; stdout?: string; stderr?: string },
  stubClock = true,
) {
  const runs: Ran[] = []
  on('session.id', () => ({ value: 'sess-1' }))
  on('session.root', () => ({ value: '/repo' }))
  on('session.cwd', () => ({ value: '/repo' }))
  on('env.get', () => ({ value: '/home/me' }))
  on('ui.status', () => ({ value: undefined }))
  on('ui.log', () => ({ value: undefined }))
  if (stubClock) on('clock.every', () => ({ value: undefined }))
  on('process.run', (_, e) => {
    runs.push({ argv: e.argv, stdin: e.init?.stdin, env: e.init?.env })
    const out = answer(e.argv)
    return {
      value: {
        exitCode: out.exitCode ?? 0,
        stdout: out.stdout ?? '',
        stderr: out.stderr ?? '',
        isStdoutTruncated: false,
        isStderrTruncated: false,
      },
    }
  })
  return runs
}

const DENY = JSON.stringify({
  hookSpecificOutput: { hookEventName: 'PreToolUse', permissionDecision: 'deny', permissionDecisionReason: 'no Testing section' },
})

test('a gate that denies refuses the Bash call with its reason', async ($, on) => {
  const runs = engine(on, argv => (argv.includes('pr_testing_gate.py') ? { stdout: DENY } : {}))
  on('tool.call', () => ({ result: { stdout: 'ran' } }))

  const result = await $.tool.call({ tool: 'Bash', command: 'gh pr create --body-file b.md' })

  expect(result.isError === true || result.deny !== undefined).toBe(true)
  expect(String(result.text ?? result.deny)).toMatch(/no Testing section/)
  const gate = runs.find(run => run.argv.includes('pr_testing_gate.py'))
  expect(gate?.argv.slice(-2)).toEqual(['prTestingGate', 'pr_testing_gate.py'])
  const payload = JSON.parse(gate?.stdin ?? '{}')
  expect(payload.hook_event_name).toBe('PreToolUse')
  expect(payload.tool_name).toBe('Bash')
  expect(payload.tool_input).toEqual({ command: 'gh pr create --body-file b.md' })
  expect(payload.session_id).toBe('sess-1')
  expect(gate?.env?.CLAUDE_PROJECT_DIR).toBe('/repo')
  expect(gate?.env?.CLAUDE_CODE_SESSION_ID).toBe('sess-1')
})

test('the stray files gate runs on by default and passes a clean call through', async ($, on) => {
  const runs = engine(on, () => ({}))
  on('tool.call', () => ({ result: { stdout: 'ran' } }))

  const result = await $.tool.call({ tool: 'Bash', command: 'ls' })

  expect(result.deny).toBeUndefined()
  expect(result.isError).toBeUndefined()
  expect(runs.some(run => run.argv.join(' ').endsWith('--default-on strayFiles stray_files_gate.py'))).toBe(true)
})

test('a post-tool reminder reaches the model as context', async ($, on) => {
  on('classic.PostToolUse', () => ({}))
  engine(on, argv =>
    argv.includes('remind-pr-merge-watch.sh')
      ? { stdout: JSON.stringify({ hookSpecificOutput: { hookEventName: 'PostToolUse', additionalContext: 'watch #7' } }) }
      : {},
  )

  const result = await $.classic.PostToolUse({
    tool_name: 'Bash',
    tool_input: { command: 'gh pr create' },
    tool_response: { stdout: 'https://github.com/o/r/pull/7' },
    tool_use_id: 't1',
  })

  expect(result.additionalContext).toEqual(['watch #7'])
})

test('an edit runs prettier and the related tests, and a failing test is reported', async ($, on) => {
  on('classic.PostToolUse', () => ({ additionalContext: ['from beneath'] }))
  const runs = engine(on, argv =>
    argv.includes('test-on-edit.sh')
      ? { stdout: JSON.stringify({ hookSpecificOutput: { hookEventName: 'PostToolUse', additionalContext: 'a_test failed' } }) }
      : {},
  )

  const result = await $.classic.PostToolUse({
    tool_name: 'Edit',
    tool_input: { file_path: '/repo/a.ts' },
    tool_response: {},
    tool_use_id: 't2',
  })

  expect(runs.map(run => run.argv.at(-1))).toEqual(['prettier-on-save.sh', 'test-on-edit.sh'])
  expect(result.additionalContext).toEqual(['from beneath', 'a_test failed'])
})

test('the oversee loop blocks a stop and the row above the prompt shows it', async ($, on) => {
  const runs = engine(on, argv => {
    if (argv.includes('implement_loop.py')) return { stdout: JSON.stringify({ decision: 'block', reason: 'resume the loop' }) }
    if (argv.at(-1) === 'status') return { stdout: JSON.stringify({ session: 'sess-1', state: 'active', label: 'ready-for-agent' }) }
    return {}
  })
  on('classic.Stop', () => ({}))

  const result = await $.classic.Stop({ stop_hook_active: false })
  expect(result.block).toBe('resume the loop')
  const status = runs.find(run => run.argv.at(-1) === 'status')
  expect(status?.argv.slice(0, 2)).toEqual(['bash', '-c'])
  expect(status?.argv[2]).toMatch(/test -d "\$\{d%\/\*\}\/\.claude\/oversee\/loops" \|\| exit 0/)

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({
      plugin: 'general',
      surface,
      component: 'AbovePrompt',
      requestId: 'band',
      props: { hasSurvey: false, bodyColumns: 80 },
    } as never)
    expect((await ui.find({ type: 'Text', text: /Oversee loop active/ }))?.text).toMatch(/label ready-for-agent/)
    await ui.press({ key: 'pause' })
    await ui.unmount()
  }
  expect(runs.some(run => run.argv.includes('pause'))).toBe(true)
})

test('command hook output is read the way Claude Code reads it', () => {
  expect(parseHookOutput('PreToolUse', 2, '', 'stop here\n').deny).toBe('stop here')
  expect(parseHookOutput('Stop', 2, '', 'keep going').block).toBe('keep going')
  expect(parseHookOutput('PostToolUse', 2, '', 'look').context).toEqual(['look'])
  expect(parseHookOutput('SessionStart', 0, 'plain text\n', '').context).toEqual(['plain text'])
  expect(parseHookOutput('Stop', 0, 'plain text', '').context).toEqual([])
  expect(parseHookOutput('Stop', 1, '{"decision":"block","reason":"x"}', '').block).toBeUndefined()
  expect(parseHookOutput('Stop', 0, '{"systemMessage":"paused"}', '').systemMessage).toBe('paused')
  expect(parseHookOutput('PostToolUse', 0, '{"decision":"block","reason":"fix it"}', '').context).toEqual(['fix it'])
  expect(parseHookOutput('Stop', 0, '{"continue":false,"stopReason":"done"}', '').stop).toEqual({ reason: 'done' })
  expect(
    parseHookOutput(
      'PermissionRequest',
      0,
      '{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}',
      '',
    ).decision,
  ).toEqual({ behavior: 'allow' })
})

test('a failing gate lets the call through, and a stop keeps both blocks', async ($, on) => {
  engine(on, argv => {
    if (argv.includes('stray_files_gate.py')) return { exitCode: 64, stderr: 'allow must be a list' }
    if (argv.includes('implement_loop.py')) return { stdout: JSON.stringify({ decision: 'block', reason: 'resume the loop' }) }
    return {}
  })
  on('tool.call', () => ({ result: { stdout: 'ran' } }))
  on('classic.Stop', () => ({ block: 'a settings hook blocks too' }))

  const call = await $.tool.call({ tool: 'Bash', command: 'ls' })
  expect(call.deny).toBeUndefined()
  expect(call.isError).toBeUndefined()

  const stop = await $.classic.Stop({ stop_hook_active: false })
  expect(stop.block).toBe('a settings hook blocks too\n\nresume the loop')
})

test('the ready-label gate and the loop both block a stop, and both reasons are kept', async ($, on) => {
  const runs = engine(on, argv => {
    if (argv.includes('ready_label_gate.py')) return { stdout: JSON.stringify({ decision: 'block', reason: 'add the label' }) }
    if (argv.includes('implement_loop.py')) return { stdout: JSON.stringify({ decision: 'block', reason: 'resume the loop' }) }
    return {}
  })
  on('classic.Stop', () => ({}))

  const stop = await $.classic.Stop({ stop_hook_active: false })

  expect(stop.block).toBe('add the label\n\nresume the loop')
  const gate = runs.find(run => run.argv.includes('ready_label_gate.py'))
  expect(gate?.argv.slice(-2)).toEqual(['readyLabelGate', 'ready_label_gate.py'])
})

test('session start hands the loop instructions to the model', async ($, on) => {
  engine(on, argv =>
    argv.includes('implement_loop.py')
      ? { stdout: JSON.stringify({ hookSpecificOutput: { hookEventName: 'SessionStart', additionalContext: 'loop helper' } }) }
      : {},
  )
  on('classic.SessionStart', () => ({}))

  const started = await $.classic.SessionStart({ source: 'startup' })

  expect(started.additionalContext).toEqual(['loop helper'])
})

test('the row stays empty without a loop, and turns to Resume once paused', async ($, on) => {
  let state = 'absent'
  engine(on, argv => {
    if (argv.at(-2) === 'pause') state = 'paused'
    if (argv.at(-1) === 'status') return { stdout: JSON.stringify({ session: 'sess-1', state }) }
    return {}
  })
  on('classic.Stop', () => ({}))
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>engine</Text>
  })
  const BAND = {
    plugin: 'general',
    surface: 'desktop',
    component: 'AbovePrompt',
    requestId: 'band',
    props: { hasSurvey: false, bodyColumns: 80 },
  } as never

  await $.classic.Stop({ stop_hook_active: false })
  let ui = await $.ui.mount(BAND)
  expect((await ui.find({ type: 'Text' }))?.text).toBe('engine')
  await ui.unmount()

  state = 'active'
  await $.classic.Stop({ stop_hook_active: false })
  ui = await $.ui.mount(BAND)
  await ui.press({ key: 'pause' })
  await ui.unmount()
  ui = await $.ui.mount(BAND)
  expect((await ui.find({ type: 'Text', text: /Oversee loop/ }))?.text).toMatch(/^Oversee loop paused/)
  expect(await ui.find({ type: 'Button', key: 'resume' })).toBeDefined()
  await ui.unmount()
})

test("a gate's stop leaves the tool call to run", async ($, on) => {
  engine(on, argv => (argv.includes('pr_testing_gate.py') ? { stdout: JSON.stringify({ continue: false, stopReason: 'halt' }) } : {}))
  on('classic.PreToolUse', () => ({ additionalContext: ['from beneath'] }))
  on('tool.call', () => ({ result: { stdout: 'ran' } }))

  const result = (await $.tool.call({ tool: 'Bash', command: 'ls' })) as Record<string, unknown>

  expect(result.deny).toBeUndefined()
  expect(result).toEqual({ result: { stdout: 'ran' } })
})

// --- the oversee loop pane

const BAND = (surface: 'terminal' | 'desktop') =>
  ({
    plugin: 'general',
    surface,
    component: 'AbovePrompt',
    requestId: 'band',
    props: { hasSurvey: false, bodyColumns: 80 },
  }) as never

const LOOP_PANE = (surface: 'terminal' | 'desktop') =>
  ({
    plugin: 'general',
    surface,
    component: 'Pane',
    requestId: 'oversee-loop',
    props: {
      title: 'Oversee loop',
      isFocused: true,
      bodyColumns: 100,
      placement: 'dock',
      scroll: { offset: 0, bodyRows: 60 },
      view: {},
    },
  }) as never

const EMPTY_BOARD = {
  session: 'sess-1',
  state: 'active',
  repo: 'https://github.com/o/r',
  current: null,
  queued: [],
  finished: [],
  more: 0,
}

// A loop in `state` whose board is whatever `board()` returns when the plugin asks.
function loopEngine(on: On, state: () => string, board: () => unknown, stubClock = true) {
  const opened: string[] = []
  on('ui.open', (_, e) => {
    opened.push(e.id)
    return { value: { isPlaced: true } } as never
  })
  on('ui.close', () => ({ value: undefined }) as never)
  on('classic.Stop', () => ({}))
  const runs = engine(
    on,
    argv => {
      if (argv.at(-1) === 'status') {
        return { stdout: JSON.stringify({ session: 'sess-1', state: state() }) }
      }
      if (argv.at(-1) === 'board') return { stdout: JSON.stringify(board()) }
      return {}
    },
    stubClock,
  )
  return { opened, runs }
}

async function texts(ui: { findAll: (q: { type: string }) => Promise<{ text?: string }[]> }) {
  return (await ui.findAll({ type: 'Text' })).map(node => node.text ?? '').join('\n')
}

async function hrefs(ui: { findAll: (q: { type: string }) => Promise<{ props: unknown }[]> }) {
  return (await ui.findAll({ type: 'Link' })).map(link => (link.props as { href?: string }).href)
}

test('Open on the row opens the loop pane, active or paused', async ($, on) => {
  let state = 'active'
  const { opened } = loopEngine(on, () => state, () => EMPTY_BOARD)
  await $.classic.Stop({ stop_hook_active: false })
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount(BAND(surface))
    expect((await ui.find({ type: 'Button', key: 'open' }))?.text).toBe('Open')
    await ui.press({ key: 'open' })
    await ui.unmount()
  }
  state = 'paused'
  await $.classic.Stop({ stop_hook_active: false })
  const ui = await $.ui.mount(BAND('desktop'))
  expect(await ui.find({ type: 'Button', key: 'resume' })).toBeDefined()
  await ui.press({ key: 'open' })
  await ui.unmount()
  expect(opened).toEqual(['oversee-loop', 'oversee-loop', 'oversee-loop'])
})

test('the pane says so when nothing is current, queued or finished', async ($, on) => {
  loopEngine(on, () => 'active', () => EMPTY_BOARD)
  await $.classic.Stop({ stop_hook_active: false })
  const ui = await $.ui.mount(LOOP_PANE('terminal'))
  const all = await texts(ui)
  expect(all).toMatch(/Nothing is being worked on\./)
  expect(all).toMatch(/The queue is empty\./)
  expect(all).toMatch(/No finished issues yet\./)
  expect(await ui.find({ type: 'Link' })).toBeUndefined()
  expect(await ui.find({ type: 'Button', key: 'close' })).toBeDefined()
  await ui.unmount()
})

test('the pane lists the current issue and the queue in order', async ($, on) => {
  loopEngine(on, () => 'active', () => ({
    ...EMPTY_BOARD,
    current: {
      issue: 12,
      title: 'Current work',
      phase: 'waiting on runs',
      branch: 'feat/issue-12',
      since: '2026-11-18T09:00:00Z',
    },
    queued: [
      { issue: 14, title: 'First', area: null, blockers: null, waits: null },
      { issue: 15, title: 'Second', area: 'voice', blockers: '#14', waits: null },
      { issue: 16, title: null, area: null, blockers: null, waits: null },
    ],
  }))
  await $.classic.Stop({ stop_hook_active: false })
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount(LOOP_PANE(surface))
    const all = await texts(ui)
    expect(all).toMatch(/Current work · waiting on runs · feat\/issue-12/)
    expect(all).toMatch(/Queued \(3\)/)
    expect(all.indexOf('First')).toBeLessThan(all.indexOf('Second'))
    expect(all).toMatch(/blocked by #14/)
    expect((await hrefs(ui)).slice(0, 4)).toEqual([
      'https://github.com/o/r/issues/12',
      'https://github.com/o/r/issues/14',
      'https://github.com/o/r/issues/15',
      'https://github.com/o/r/issues/16',
    ])
    await ui.unmount()
  }
})

test('finished issues show their result and link their pull request', async ($, on) => {
  const finished = [
    { issue: 9, title: 'Shipped', status: 'done', pr: 41, note: 'ready', at: '2026-11-18T08:40Z' },
    { issue: 8, title: 'Stuck', status: 'stalled', pr: null, note: 'checks red', at: null },
  ]
  let repo: string | null = 'https://github.com/o/r'
  loopEngine(on, () => 'active', () => ({ ...EMPTY_BOARD, repo, finished, more: 3 }))
  await $.classic.Stop({ stop_hook_active: false })
  let ui = await $.ui.mount(LOOP_PANE('desktop'))
  let all = await texts(ui)
  expect(all).toMatch(/Finished \(5\)/)
  expect(all).toMatch(/Shipped · done · ready/)
  expect(all).toMatch(/Stuck · stalled · checks red/)
  expect(all).toMatch(/and 3 more/)
  expect(all).not.toMatch(/PR #-|PR #null/)
  expect(await hrefs(ui)).toEqual([
    'https://github.com/o/r/issues/9',
    'https://github.com/o/r/pull/41',
    'https://github.com/o/r/issues/8',
  ])
  await ui.unmount()

  repo = null
  await $.classic.Stop({ stop_hook_active: false })
  ui = await $.ui.mount(LOOP_PANE('terminal'))
  all = await texts(ui)
  expect(await ui.find({ type: 'Link' })).toBeUndefined()
  expect(all).toMatch(/#9/)
  expect(all).toMatch(/PR #41/)
  await ui.unmount()
})

test("the pane follows the row's poll, and no board is read without a loop", async ($, on) => {
  const clock = mock.clock(on, { now: Date.UTC(2026, 10, 18, 9, 0, 0) })
  let state = 'absent'
  let board: unknown = EMPTY_BOARD
  const { runs } = loopEngine(on, () => state, () => board, false)

  await $.classic.Stop({ stop_hook_active: false })
  expect(runs.some(run => run.argv.at(-1) === 'board')).toBe(false)
  let ui = await $.ui.mount(LOOP_PANE('terminal'))
  expect(await texts(ui)).toMatch(/No loop data yet\./)
  await ui.unmount()

  state = 'active'
  await $.classic.Stop({ stop_hook_active: false })
  ui = await $.ui.mount(LOOP_PANE('terminal'))
  expect(await texts(ui)).toMatch(/The queue is empty\./)
  await ui.unmount()

  const later = { issue: 21, title: 'Arrived later', area: null, blockers: null, waits: null }
  board = { ...EMPTY_BOARD, queued: [later] }
  await clock.advance(30 * 1000)
  await clock.settle()
  ui = await $.ui.mount(LOOP_PANE('terminal'))
  expect(await texts(ui)).toMatch(/Arrived later/)
  await ui.unmount()
})
