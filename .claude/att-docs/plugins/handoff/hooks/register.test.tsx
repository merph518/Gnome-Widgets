import { expect, mock, test } from 'claude-code/testing'
import type { ModelForkRequest, ModelForkResult, On, SessionMessage } from 'claude-code'
import type { Engine } from 'claude-code/testing'

import { MAX_LINK_CHARS, STEPS, clipboardCommands, draftFrom, newChatLink, scrub, stamp } from './handoff'

const USAGE = { input_tokens: 10, output_tokens: 5, cache_creation_input_tokens: 0, cache_read_input_tokens: 0 }

const HANDOFF = '# Handoff\n\n## Asked\nSplit the parser.\n\n## Next steps\nRun the tests.'

const MESSAGES: SessionMessage[] = [
  { role: 'user', text: 'Split the parser into modules. My key is DB_PASSWORD=hunter2', toolUses: [] },
  {
    role: 'assistant',
    text: 'Done, see https://example.com/pr/1',
    toolUses: [
      { tool_use_id: 'a', tool: 'Edit', input: { file_path: '/repo/src/parser.ts' } },
      { tool_use_id: 'b', tool: 'Skill', input: { skill: 'tdd' } },
      { tool_use_id: 'c', tool: 'Bash', input: { command: 'npm test' } },
    ],
  },
]

type Setup = {
  env?: Record<string, string>
  switches?: string
  // The fork's answer, or a call that returns it when the test lets it.
  fork?: ModelForkResult | (() => Promise<ModelForkResult>)
  files?: Record<string, string>
  // Commands that are not installed: `sh -c 'exec …'` exits 127 for them.
  missing?: string[]
  // Exit codes for installed commands that fail.
  fails?: Record<string, number>
}

// Stands in for the engine beneath the plugin, and records what the plugin asked of it.
function engine(on: On, setup: Setup = {}) {
  const files: Record<string, string> = { ...setup.files }
  const seen = {
    files,
    runs: [] as { argv: readonly string[]; stdin?: string }[],
    forks: [] as ModelForkRequest[],
  }
  mock.env(on, { HOME: '/home/me', WAYLAND_DISPLAY: 'wayland-0', ...setup.env })
  const clock = mock.clock(on, { now: Date.UTC(2026, 10, 18, 9, 5, 7) })
  on('store.get', () => ({ value: undefined }))
  on('command.register', (_, e) => ({ value: { command: e.name } }))
  on('tool.register', (_, e) => ({ value: { tool: `mcp__handoff__${e.name}` } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.end', () => ({ sessionId: 's1' }))
  on('session.id', () => ({ value: 's1' }))
  on('session.messages', () => ({ value: MESSAGES }))
  on('session.measure', (_, e) => ({ changed: e.changed }))
  on('model.fork', async (_, e) => {
    seen.forks.push(e)
    const answer = typeof setup.fork === 'function' ? await setup.fork() : setup.fork
    return { value: answer ?? { isAnswered: true, text: `${HANDOFF}\nAuthorization: Bearer abc.def-123`, usage: USAGE } }
  })
  on('fs.read', (_, e) => {
    if (e.path.endsWith('switches.json') && setup.switches !== undefined) return { value: setup.switches }
    const text = files[e.path]
    return text === undefined ? { deny: 'no such file' } : { value: text }
  })
  on('fs.write', (_, e) => {
    files[e.path] = e.text
    return { value: undefined }
  })
  on('fs.exists', (_, e) => ({ value: files[e.path] !== undefined }))
  on('process.run', (_, e) => {
    seen.runs.push({ argv: e.argv, ...(e.init?.stdin === undefined ? {} : { stdin: e.init.stdin }) })
    const command = e.argv[0] === 'sh' ? e.argv[4] : e.argv[0]
    if (e.argv[0] === 'rm') for (const path of e.argv.slice(2)) delete files[path]
    const exitCode =
      command === undefined ? 0 : setup.missing?.includes(command) ? 127 : (setup.fails?.[command] ?? 0)
    return { value: { exitCode, stdout: '', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>engine</Text>
  })
  return { seen, clock }
}

async function start($: Engine) {
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true } as never)
}

async function measure($: Engine, tokens: number) {
  await $.session.measure({ context: { tokens, window: 1_000_000 }, rateLimits: [], changed: ['context'] })
}

async function command($: Engine, name: string) {
  return $.command.run({ command: name, args: '', origin: { kind: 'composer' }, presentation: 'text' } as never)
}

const BAND = (surface: 'terminal' | 'desktop') =>
  ({
    plugin: 'handoff',
    surface,
    component: 'AbovePrompt',
    requestId: 'band',
    props: { hasSurvey: false, bodyColumns: 80 },
  }) as never

const DIR = '/home/me/.claude/handoffs'
const DRAFT = `${DIR}/20261118-090507-draft.md`
const SAVED = `${DIR}/20261118-090507-handoff.md`

// --- the parts that need no engine

test('scrub removes an API key, a Bearer token and a PASSWORD= line, and leaves the rest', () => {
  const sample = [
    'Use the key sk-ant-api03-AbCdEf0123456789AbCdEf0123456789 for the call.',
    'curl -H "Authorization: Bearer eyJhbGciOi.abc-123_def" https://api.example.com',
    'DB_PASSWORD=hunter2',
    'export GITHUB_TOKEN="ghp_0123456789abcdefghijABCDEFGHIJ012345"',
    'The parser now has three modules.',
  ].join('\n')
  const clean = scrub(sample)
  expect(clean).not.toMatch(/sk-ant-api03/)
  expect(clean).not.toMatch(/eyJhbGciOi/)
  expect(clean).not.toMatch(/hunter2/)
  expect(clean).not.toMatch(/ghp_/)
  expect(clean).toMatch(/Use the key <secret removed> for the call\./)
  expect(clean).toMatch(/Authorization: Bearer <secret removed>" https:\/\/api\.example\.com/)
  expect(clean).toMatch(/^DB_PASSWORD=<secret removed>$/m)
  expect(clean).toMatch(/^export GITHUB_TOKEN=<secret removed>$/m)
  expect(clean).toMatch(/^The parser now has three modules\.$/m)
})

test('scrub removes private key blocks, AWS keys, JSON secrets and api_key= values', () => {
  const sample = [
    '-----BEGIN OPENSSH PRIVATE KEY-----',
    'b3BlbnNzaC1rZXktdjEAAAAA',
    '-----END OPENSSH PRIVATE KEY-----',
    'AKIAABCDEFGHIJKLMNOP',
    '{"client_secret": "s3cr3t", "name": "ok"}',
    'api_key=abc123',
  ].join('\n')
  const clean = scrub(sample)
  expect(clean).not.toMatch(/b3BlbnNzaC1rZXktdjEAAAAA|AKIAABCDEFGHIJKLMNOP|s3cr3t|abc123/)
  expect(clean).toMatch(/"name": "ok"/)
})

test('scrub run twice gives the same text as once', () => {
  const sample = 'set API_KEY=abc123\n"token": "x"\nAuthorization: Bearer abc.def\nsk-ant-api03-AbCdEf0123456789AbCdEf'
  expect(scrub(scrub(sample))).toBe(scrub(sample))
  expect(scrub(sample)).toMatch(/^set API_KEY=<secret removed>$/m)
})

test('scrub leaves ordinary prose about keys and tokens alone', () => {
  const prose = 'The token count passed the limit. Press the key: Enter. A password field is shown.'
  expect(scrub(prose)).toBe(prose)
})

test('draftFrom lists what was asked, files, skills, tools and links', () => {
  const draft = draftFrom(MESSAGES)
  expect(draft).toMatch(/Split the parser into modules/)
  expect(draft).toMatch(/\/repo\/src\/parser\.ts/)
  expect(draft).toMatch(/tdd/)
  expect(draft).toMatch(/Edit/)
  expect(draft).toMatch(/Bash/)
  expect(draft).toMatch(/https:\/\/example\.com\/pr\/1/)
})

test('draftFrom removes a secret that a cut would otherwise leave half there', () => {
  const key = 'sk-ant-api03-AbCdEf0123456789AbCdEf0123456789'
  const draft = scrub(draftFrom([{ role: 'user', text: `${'x'.repeat(290)} ${key}`, toolUses: [] }]))
  expect(draft).not.toMatch(/sk-ant/)
})

test('stamp names the moment in the file name', () => {
  expect(stamp(Date.UTC(2026, 10, 18, 9, 5, 7))).toBe('20261118-090507')
})

test('newChatLink encodes the handoff and falls back to the saved file when too long', () => {
  const link = newChatLink('a & b #c\nd', '/x/h.md')
  expect(link).toBe('claude://code/new?q=a%20%26%20b%20%23c%0Ad')
  const long = newChatLink('x'.repeat(MAX_LINK_CHARS), '/x/h.md')
  expect(long.length).toBeLessThanOrEqual(MAX_LINK_CHARS)
  expect(decodeURIComponent(long.slice('claude://code/new?q='.length))).toMatch(/\/x\/h\.md/)
})

test('clipboardCommands picks wl-copy on Wayland, then xclip, and xclip alone on X11', () => {
  expect(clipboardCommands({ WAYLAND_DISPLAY: 'wayland-0', DISPLAY: ':0' })).toEqual([
    { argv: ['wl-copy'], apt: 'wl-clipboard' },
    { argv: ['xclip', '-selection', 'clipboard'], apt: 'xclip' },
  ])
  expect(clipboardCommands({ DISPLAY: ':0' })).toEqual([{ argv: ['xclip', '-selection', 'clipboard'], apt: 'xclip' }])
  expect(clipboardCommands({ XDG_SESSION_TYPE: 'wayland' })).toEqual([{ argv: ['wl-copy'], apt: 'wl-clipboard' }])
  expect(clipboardCommands({})).toEqual([])
})

// --- the hooks module

test('the band is offered once the context reaches 250,000 tokens', async ($, on) => {
  engine(on)
  await start($)
  await measure($, 249_999)
  let ui = await $.ui.mount(BAND('terminal'))
  expect(await ui.find({ type: 'Button', key: 'refresh' })).toBeUndefined()
  await ui.unmount()

  await measure($, 250_000)
  for (const surface of ['terminal', 'desktop'] as const) {
    ui = await $.ui.mount(BAND(surface))
    expect((await ui.find({ type: 'Button', key: 'refresh' }))?.text).toBe('Refresh')
    await ui.unmount()
  }
})

test('Refresh writes the draft, then the handoff, with five steps and secrets removed', async ($, on) => {
  const { seen, clock } = engine(on)
  await start($)
  await measure($, 300_000)
  const ui = await $.ui.mount(BAND('desktop'))
  await ui.press({ key: 'refresh' })
  await clock.settle()

  expect(seen.files[DRAFT]).toMatch(/Split the parser/)
  expect(seen.files[DRAFT]).not.toMatch(/hunter2/)
  expect(seen.forks.length).toBe(1)
  expect(seen.forks[0]?.prompt).toMatch(/Next steps/)
  expect(seen.forks[0]?.effort).toBeUndefined()
  expect(seen.files[SAVED]).toMatch(/## Next steps/)
  expect(seen.files[SAVED]).toMatch(/Bearer <secret removed>/)
  expect(seen.files[SAVED]).not.toMatch(/abc\.def-123/)
  expect(seen.files[`${DIR}/handoff.log`]).toMatch(/20261118-090507-handoff\.md/)

  // Each step is drawn as a progress bar whose label reads the step and its state.
  for (const label of STEPS) {
    expect((await ui.find({ type: 'Text', text: new RegExp(`^${label}`) }))?.text).toMatch(/done/)
  }
  expect((await ui.find({ type: 'Button', key: 'copy' }))?.text).toBe('Copy')
  expect((await ui.find({ type: 'Button', key: 'new' }))?.text).toBe('Start new chat with it')
  await ui.unmount()
})

test('/handoff writes a handoff without waiting for the offer', async ($, on) => {
  const { seen, clock } = engine(on)
  await start($)
  await command($, 'handoff')
  await clock.settle()
  expect(seen.files[SAVED]).toMatch(/## Asked/)
})

test('a failed write-up keeps the draft and says why', async ($, on) => {
  const { seen, clock } = engine(on, { fork: { isAnswered: false, reason: 'empty-reply' } as ModelForkResult })
  await start($)
  await command($, 'handoff')
  await clock.settle()
  expect(seen.files[DRAFT]).toBeDefined()
  expect(seen.files[SAVED]).toBeUndefined()
  const ui = await $.ui.mount(BAND('terminal'))
  expect((await ui.find({ type: 'Text', text: /empty-reply/ }))?.text).toMatch(/draft/)
  await ui.unmount()
})

test('Copy sends the handoff to wl-copy on Wayland', async ($, on) => {
  const { seen, clock } = engine(on)
  await start($)
  await command($, 'handoff')
  await clock.settle()
  const ui = await $.ui.mount(BAND('terminal'))
  await ui.press({ key: 'copy' })
  await clock.settle()
  const copy = seen.runs.find(run => run.argv.includes('wl-copy'))
  expect(copy?.stdin).toMatch(/## Next steps/)
  expect(copy?.stdin).not.toMatch(/abc\.def-123/)
  expect((await ui.find({ type: 'Text', text: /Copied/ }))?.text).toMatch(/Ctrl\+Shift\+V/)
  await ui.unmount()
})

test('Copy on X11 runs xclip, and with no clipboard tool names the apt package', async ($, on) => {
  const { seen, clock } = engine(on, { env: { WAYLAND_DISPLAY: '', DISPLAY: ':0' }, missing: ['xclip'] })
  await start($)
  await command($, 'handoff')
  await clock.settle()
  const ui = await $.ui.mount(BAND('terminal'))
  await ui.press({ key: 'copy' })
  await clock.settle()
  expect(seen.runs.some(run => run.argv.includes('xclip'))).toBe(true)
  expect((await ui.find({ type: 'Text', text: /Copy failed/ }))?.text).toMatch(/sudo apt install xclip/)
  await ui.unmount()
})

test('Copy on Wayland with neither tool names wl-clipboard', async ($, on) => {
  const { clock } = engine(on, { env: { DISPLAY: ':0' }, missing: ['wl-copy', 'xclip'] })
  await start($)
  await command($, 'handoff')
  await clock.settle()
  const ui = await $.ui.mount(BAND('terminal'))
  await ui.press({ key: 'copy' })
  await clock.settle()
  expect((await ui.find({ type: 'Text', text: /Copy failed/ }))?.text).toMatch(/sudo apt install wl-clipboard/)
  await ui.unmount()
})

test('Copy reports a clipboard tool that fails, when the next one is missing', async ($, on) => {
  const { clock } = engine(on, { env: { DISPLAY: ':0' }, fails: { 'wl-copy': 1 }, missing: ['xclip'] })
  await start($)
  await command($, 'handoff')
  await clock.settle()
  const ui = await $.ui.mount(BAND('terminal'))
  await ui.press({ key: 'copy' })
  await clock.settle()
  expect((await ui.find({ type: 'Text', text: /Copy failed/ }))?.text).toMatch(/wl-copy exited with status 1/)
  await ui.unmount()
})

test('Copy falls back to xclip when wl-copy fails', async ($, on) => {
  const { clock } = engine(on, { env: { DISPLAY: ':0' }, fails: { 'wl-copy': 1 } })
  await start($)
  await command($, 'handoff')
  await clock.settle()
  const ui = await $.ui.mount(BAND('terminal'))
  await ui.press({ key: 'copy' })
  await clock.settle()
  expect(await ui.find({ type: 'Text', text: /Copied/ })).toBeDefined()
  await ui.unmount()
})

test('Open file and Start new chat use xdg-open', async ($, on) => {
  const { seen, clock } = engine(on)
  await start($)
  await command($, 'handoff')
  await clock.settle()
  const ui = await $.ui.mount(BAND('desktop'))
  await ui.press({ key: 'open' })
  await ui.press({ key: 'new' })
  await clock.settle()
  const opens = seen.runs.filter(run => run.argv.includes('xdg-open')).map(run => run.argv.at(-1))
  expect(opens[0]).toBe(SAVED)
  expect(opens[1]).toMatch(/^claude:\/\/code\/new\?q=%23%20Handoff/)
  expect(opens[1]).not.toMatch(/abc\.def-123/)
  await ui.unmount()
})

test('closing a finished handoff snoozes the offer by 100,000 tokens', async ($, on) => {
  const { clock } = engine(on)
  await start($)
  await measure($, 260_000)
  await command($, 'handoff')
  await clock.settle()
  let ui = await $.ui.mount(BAND('terminal'))
  await ui.press({ key: 'close' })
  await ui.unmount()

  await measure($, 359_999)
  ui = await $.ui.mount(BAND('terminal'))
  expect(await ui.find({ type: 'Button', key: 'refresh' })).toBeUndefined()
  await ui.unmount()
  await measure($, 360_000)
  ui = await $.ui.mount(BAND('terminal'))
  expect(await ui.find({ type: 'Button', key: 'refresh' })).toBeDefined()
  await ui.unmount()
})

test('/fresh shows the band, and the refresh tool does too', async ($, on) => {
  engine(on)
  await start($)
  await command($, 'fresh')
  let ui = await $.ui.mount(BAND('terminal'))
  expect(await ui.find({ type: 'Button', key: 'refresh' })).toBeDefined()
  await ui.press({ key: 'close' })
  await ui.unmount()

  const answer = await $.tool.call({ tool: 'mcp__handoff__refresh', input: {} } as never)
  expect(answer.deny).toBeUndefined()
  ui = await $.ui.mount(BAND('terminal'))
  expect(await ui.find({ type: 'Button', key: 'refresh' })).toBeDefined()
  await ui.unmount()
})

test('a request file for this session starts a handoff and is removed', async ($, on) => {
  const { seen, clock } = engine(on, { files: { [`${DIR}/.request-s1`]: '', [`${DIR}/.request-other`]: '' } })
  await start($)
  await clock.advance(5000)
  await clock.settle()
  expect(seen.files[`${DIR}/.request-s1`]).toBeUndefined()
  expect(seen.files[`${DIR}/.request-other`]).toBeDefined()
  // The clock moved five seconds before the check found the file.
  expect(seen.files[`${DIR}/20261118-090512-handoff.md`]).toBeDefined()
})

test('a request file that arrives while a handoff is being written waits for the next check', async ($, on) => {
  let release: (value: ModelForkResult) => void = () => {}
  const { seen, clock } = engine(on, { fork: () => new Promise(resolve => (release = resolve)) })
  await start($)
  await command($, 'handoff')
  await clock.settle()
  seen.files[`${DIR}/.request-s1`] = ''
  await clock.advance(5000)
  await clock.settle()
  expect(seen.files[`${DIR}/.request-s1`]).toBeDefined()
  release({ isAnswered: true, text: HANDOFF, usage: USAGE })
  await clock.settle()
  await clock.advance(5000)
  await clock.settle()
  expect(seen.files[`${DIR}/.request-s1`]).toBeUndefined()
  expect(seen.forks.length).toBe(2)
})

test('CLAUDE_CONFIG_DIR moves the handoffs folder', async ($, on) => {
  const { seen, clock } = engine(on, { env: { CLAUDE_CONFIG_DIR: '/cfg' } })
  await start($)
  await command($, 'handoff')
  await clock.settle()
  expect(seen.files['/cfg/handoffs/20261118-090507-handoff.md']).toBeDefined()
})

test('switches.json can turn the plugin off or hide the band', async ($, on) => {
  const { seen, clock } = engine(on, { switches: '{"handoff": false}' })
  await start($)
  await measure($, 300_000)
  const ui = await $.ui.mount(BAND('terminal'))
  expect(await ui.find({ type: 'Button', key: 'refresh' })).toBeUndefined()
  await ui.unmount()
  const answer = await command($, 'handoff')
  await clock.settle()
  expect(answer.text).toMatch(/switched off/)
  expect(seen.files[SAVED]).toBeUndefined()
})

test('switches.json hidden keeps the band away but /handoff still works', async ($, on) => {
  const { seen, clock } = engine(on, { switches: '{"handoff:hidden": true}' })
  await start($)
  await measure($, 300_000)
  const ui = await $.ui.mount(BAND('terminal'))
  expect(await ui.find({ type: 'Button', key: 'refresh' })).toBeUndefined()
  await ui.unmount()
  await command($, 'handoff')
  await clock.settle()
  expect(seen.files[SAVED]).toBeDefined()
})

test('/clear drops a handoff still being written', async ($, on) => {
  let release: (value: ModelForkResult) => void = () => {}
  const { seen, clock } = engine(on, { fork: () => new Promise(resolve => (release = resolve)) })
  await start($)
  await command($, 'handoff')
  await clock.settle()
  await $.session.end({ reason: 'clear' } as never)
  release({ isAnswered: true, text: HANDOFF, usage: USAGE })
  await clock.settle()
  expect(seen.files[SAVED]).toBeUndefined()
  const ui = await $.ui.mount(BAND('terminal'))
  expect(await ui.find({ type: 'Text', text: /^Read the chat/ })).toBeUndefined()
  await ui.unmount()
})
