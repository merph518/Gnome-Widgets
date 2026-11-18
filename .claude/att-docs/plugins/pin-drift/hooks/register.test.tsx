import { expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'
import type { Engine } from 'claude-code/testing'

import { argv } from './drift'

const START = Date.parse('2026-11-18T12:00:00.000Z')
const MINUTE = 60_000

type Answer = { exitCode: number; stdout?: string; stderr?: string } | 'reject'

const HOME_REMOTE = 'https://github.com/merph518/Overmind-Mod.git'
const MARKER = '/home/me/.claude/mods/.open-pin-drift-s1'
const SWITCHES = '/home/me/.claude/mods/switches.json'

type Setup = {
  // The origin remote; null for a repository with none. `repo: null` means no
  // repository, and `repo: 'reject'` an engine that fails to say.
  remote?: string | null
  repo?: null | 'reject'
  consumers?: Answer
  tags?: Answer
  releases?: Answer
  locks?: Record<string, Answer>
  pins?: Record<string, Answer>
  files?: Record<string, string>
  store?: Record<string, unknown>
}

const ok = (stdout: string): Answer => ({ exitCode: 0, stdout })
const ALL = [
  'ATT-Test-Pack-Gen',
  'Laundry-Bot',
  'personal',
  'Gnome-Widgets',
  'Playwright-Testing',
]

const lock = (tag: string, repo = 'merph518/Overmind-Mod') =>
  ok(`repo=${repo}\ntag=${tag}\ncommit=abc\n`)
const release = (number: number, version: string) => ({
  number,
  title: `chore: release ${version}`,
  state: 'open',
  html_url: `https://github.com/merph518/Overmind-Mod/pull/${number}`,
  labels: [{ name: 'autorelease: pending' }],
})
const pinPr = (number: number, tag: string, checks: unknown[] = []) => ({
  number,
  url: `https://github.com/merph518/Laundry-Bot/pull/${number}`,
  headRefName: `overmind/pin-${tag}`,
  statusCheckRollup: checks,
})

// Stands in for the engine beneath the plugin, and records the gh calls.
function engine(on: On, setup: Setup = {}) {
  const files: Record<string, string> = { ...setup.files }
  const seen = {
    runs: [] as string[][],
    opened: [] as string[],
    files,
    store: { ...setup.store } as Record<string, unknown>,
  }
  const answers = new Map<string, Answer>()
  const set = (args: string[], answer: Answer | undefined) => {
    if (answer !== undefined) answers.set(JSON.stringify(args), answer)
  }
  const two = ok(JSON.stringify({ consumers: ['Laundry-Bot', 'personal'] }))
  set(argv.consumers(), setup.consumers ?? two)
  set(argv.tags(), setup.tags ?? ok('refs/tags/v0.30.0\nrefs/tags/v0.31.4\nrefs/tags/v0.32.3\n'))
  set(argv.releasePrs(), setup.releases ?? ok('[]'))
  for (const name of ALL) {
    set(argv.lock(name), setup.locks?.[name] ?? lock('v0.32.3'))
    set(argv.pinPrs(name), setup.pins?.[name] ?? ok('[]'))
  }
  let gate: Promise<void> | null = null
  mock.env(on, { HOME: '/home/me' })
  const clock = mock.clock(on, { now: START })
  on('store.get', (_, e) => ({ value: seen.store[e.key] }))
  on('store.set', (_, e) => {
    seen.store[e.key] = e.value
    return { value: undefined }
  })
  on('session.id', () => ({ value: 's1' }))
  on('session.repo', () => {
    if (setup.repo === 'reject') return { deny: 'no repository information' } as never
    if (setup.repo === null) return { value: null } as never
    const remote = setup.remote === undefined ? HOME_REMOTE : setup.remote
    return { value: { root: '/repo', remote, internal: false, name: null } } as never
  })
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('command.register', (_, e) => ({ value: { command: e.name } }))
  on('ui.open', (_, e) => {
    seen.opened.push(e.id)
    return { value: { isPlaced: true } } as never
  })
  on('ui.close', () => ({ value: undefined }) as never)
  on('fs.read', (_, e) =>
    e.path in files ? { value: files[e.path] as string } : { deny: 'ENOENT' },
  )
  on('fs.exists', (_, e) => ({ value: e.path in files }))
  on('process.run', async (_, e) => {
    const args = [...e.argv]
    if (args[0] === 'rm') {
      for (const path of args.slice(2)) delete files[path]
      return { value: { exitCode: 0, stdout: '', stderr: '' } as never }
    }
    seen.runs.push(args)
    if (gate !== null) await gate
    const answer = answers.get(JSON.stringify(args)) ?? { exitCode: 1, stderr: 'HTTP 500' }
    if (answer === 'reject') return { deny: 'spawn gh ENOENT' }
    const { exitCode, stdout = '', stderr = '' } = answer
    return { value: { exitCode, stdout, stderr } as never }
  })
  // What the engine draws when the plugin draws nothing of its own.
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>engine</Text>
  })
  return {
    seen,
    clock,
    files,
    hold() {
      let open = () => {}
      gate = new Promise<void>(resolve => {
        open = resolve
      })
      return () => {
        gate = null
        open()
      }
    },
  }
}

async function start($: Engine, clock: { settle: () => Promise<void> }) {
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true } as never)
  await clock.settle()
}

async function command($: Engine, name: string) {
  const origin = { kind: 'composer' }
  return $.command.run({ command: name, args: '', origin, presentation: 'text' } as never)
}

const SURFACES = ['terminal', 'desktop'] as const

const BAND = (surface: (typeof SURFACES)[number], columns = 120) =>
  ({
    plugin: 'pin-drift',
    surface,
    component: 'AbovePrompt',
    requestId: 'band',
    props: { hasSurvey: false, bodyColumns: columns },
  }) as never

const PANE = (surface: (typeof SURFACES)[number]) =>
  ({
    plugin: 'pin-drift',
    surface,
    component: 'Pane',
    requestId: 'pin-drift',
    props: {
      title: 'Pin drift',
      isFocused: true,
      bodyColumns: 100,
      placement: 'dock',
      scroll: { offset: 0, bodyRows: 60 },
      view: {},
    },
  }) as never

async function band($: Engine, surface: (typeof SURFACES)[number] = 'terminal') {
  const ui = await $.ui.mount(BAND(surface))
  const found = await ui.find({ type: 'Text' })
  await ui.unmount()
  return found?.text ?? ''
}

const BEHIND: Setup = {
  releases: ok(JSON.stringify([release(101, '0.32.4')])),
  locks: { 'Laundry-Bot': lock('v0.31.4'), personal: lock('v0.30.0') },
}

test('here the band names the pending release and consumers behind', async ($, on) => {
  const { seen, clock } = engine(on, BEHIND)
  await start($, clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount(BAND(surface))
    expect((await ui.find({ type: 'Text' }))?.text).toBe(
      '0.32.4 pending · 2 consumers behind latest (Laundry-Bot 0.31.4, personal 0.30.0)',
    )
    await ui.press({ key: 'details' })
    await ui.unmount()
  }
  expect(seen.opened).toEqual(['pin-drift', 'pin-drift'])
})

async function expectAbsent($: Engine, on: On, setup: Setup) {
  const { seen, clock } = engine(on, { ...BEHIND, ...setup })
  await start($, clock)
  await clock.advance(30 * MINUTE)
  await clock.settle()
  expect(await band($)).toBe('engine')
  expect(seen.runs).toEqual([])
  const ui = await $.ui.mount(PANE('terminal'))
  expect(await ui.find({ type: 'Text', text: /only in the Overmind repository/ })).toBeDefined()
  await ui.unmount()
}

test('in another repository there is no band and gh never runs', async ($, on) => {
  await expectAbsent($, on, { remote: 'https://github.com/merph518/Laundry-Bot.git' })
})

test('in a repository with no remote there is no band and gh never runs', async ($, on) => {
  await expectAbsent($, on, { remote: null })
})

test('outside any repository there is no band and gh never runs', async ($, on) => {
  await expectAbsent($, on, { repo: null })
})

test('when the repository cannot be read, there is no band and gh never runs', async ($, on) => {
  await expectAbsent($, on, { repo: 'reject' })
})

const ghRuns = (runs: string[][]) => runs.filter(args => args[0] === 'gh')

test('a clone under an older name shows the band; gh reads the current name', async ($, on) => {
  const remote = 'git@github.com:mfagerstrom/Overmind.git'
  const { seen, clock } = engine(on, { ...BEHIND, remote })
  await start($, clock)
  expect(await band($)).toMatch(/^0\.32\.4 pending/)
  const api = ghRuns(seen.runs)
    .filter(args => args[1] === 'api')
    .map(args => args.find(arg => arg.startsWith('repos/')) ?? '')
  expect(api.filter(path => path.includes('Overmind'))).toEqual([
    'repos/merph518/Overmind-Mod/contents/.github/consumers.json',
    'repos/merph518/Overmind-Mod/git/matching-refs/tags/v',
    expect.stringMatching(/^repos\/merph518\/Overmind-Mod\/pulls\?/),
  ])
})

test('with every consumer current and no release pending there is no band', async ($, on) => {
  const { clock } = engine(on)
  await start($, clock)
  expect(await band($)).toBe('engine')
})

test('a lock with CRLF line endings shows its version', async ($, on) => {
  const crlf = ok('repo=merph518/Overmind-Mod\r\ntag=v0.31.4\r\n')
  const { clock } = engine(on, { locks: { 'Laundry-Bot': crlf } })
  await start($, clock)
  expect(await band($)).toBe('1 consumer behind latest (Laundry-Bot 0.31.4)')
})

test('a lock that cannot be read shows in the band', async ($, on) => {
  const missing = { exitCode: 1, stderr: 'gh: Not Found (HTTP 404)' }
  const { clock } = engine(on, { locks: { personal: missing } })
  await start($, clock)
  expect(await band($)).toBe('1 lock unreadable')
})

test('unreadable release pull requests show, and are read again later', async ($, on) => {
  const { seen, clock } = engine(on, { releases: { exitCode: 1, stderr: 'HTTP 502' } })
  await start($, clock)
  expect(await band($)).toBe('release state unreadable')
  const ui = await $.ui.mount(PANE('terminal'))
  const text = 'The release pull requests could not be read.'
  expect(await ui.find({ type: 'Text', text })).toBeDefined()
  await ui.unmount()
  const releaseReads = () => ghRuns(seen.runs).filter(args => args[2]?.includes('/pulls?')).length
  await clock.advance(10 * MINUTE)
  await clock.settle()
  expect(releaseReads()).toBe(1)
  await clock.advance(10 * MINUTE)
  await clock.settle()
  expect(releaseReads()).toBe(2)
})

test('signed out partway shows the quiet line; the pane keeps what was read', async ($, on) => {
  const { clock } = engine(on, {
    locks: { 'Laundry-Bot': lock('v0.31.4'), personal: { exitCode: 4, stderr: 'gh auth login' } },
  })
  await start($, clock)
  expect(await band($)).toBe('Pin drift: gh is signed out (gh auth login)')
  const ui = await $.ui.mount(PANE('terminal'))
  const signedOut = 'Pin drift: gh is signed out (gh auth login)'
  expect(await ui.find({ type: 'Text', text: signedOut })).toBeDefined()
  const behind = /pinned 0\.31\.4 · behind 0\.32\.3 · pin pull requests could not be read/
  expect(await ui.find({ type: 'Text', text: behind })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'lock unreadable: gh is signed out' })).toBeDefined()
  await ui.unmount()
})

test('tags that cannot be read show one quiet line', async ($, on) => {
  const { clock } = engine(on, { tags: { exitCode: 4, stderr: 'gh auth login' } })
  await start($, clock)
  expect(await band($)).toBe('Pin drift: gh is signed out (gh auth login)')
})

test('gh missing shows one quiet line', async ($, on) => {
  const { clock } = engine(on, { consumers: 'reject', tags: 'reject' })
  await start($, clock)
  expect(await band($)).toBe('Pin drift: gh is not installed')
})

test('a result another chat kept minutes ago is used without asking GitHub', async ($, on) => {
  const laundry = {
    name: 'Laundry-Bot',
    pinned: 'v0.31.0',
    lockRepo: 'merph518/Overmind-Mod',
    note: null,
    pr: null,
    isPrUnknown: false,
  }
  const kept = {
    latest: 'v0.32.3',
    pending: null,
    isReleaseUnknown: false,
    consumers: [laundry],
    failure: null,
    at: START - 5 * MINUTE,
  }
  const { seen, clock } = engine(on, { store: { drift: kept } })
  await start($, clock)
  expect(ghRuns(seen.runs)).toEqual([])
  expect(await band($)).toBe('1 consumer behind latest (Laundry-Bot 0.31.0)')
  // The every-ten-minutes timer finds the kept result stale and reads GitHub.
  await clock.advance(10 * MINUTE)
  await clock.settle()
  expect(ghRuns(seen.runs).length).toBeGreaterThan(0)
  expect(await band($)).toBe('engine')
  expect((seen.store['drift'] as { at: number }).at).toBe(START + 10 * MINUTE)
})

test('after a failure GitHub is asked again only after fifteen minutes', async ($, on) => {
  const offline = { exitCode: 1, stderr: 'error connecting to api.github.com' }
  const { seen, clock } = engine(on, { tags: offline })
  await start($, clock)
  const tagReads = () => ghRuns(seen.runs).filter(args => args.includes('--paginate')).length
  expect(tagReads()).toBe(1)
  await clock.advance(10 * MINUTE)
  await clock.settle()
  expect(tagReads()).toBe(1)
  await clock.advance(10 * MINUTE)
  await clock.settle()
  expect(tagReads()).toBe(2)
})

test('switched off, gh never runs and the band is gone; back on, it refreshes', async ($, on) => {
  const off = { [SWITCHES]: '{"pin-drift": false}' }
  const { seen, clock, files } = engine(on, { ...BEHIND, files: off })
  await start($, clock)
  await clock.advance(20 * MINUTE)
  await clock.settle()
  expect(ghRuns(seen.runs)).toEqual([])
  expect(await band($)).toBe('engine')
  const reply = (await command($, 'pin-drift')) as unknown
  expect(reply).toEqual({ text: expect.stringMatching(/switched off/) })
  files[SWITCHES] = '{}'
  await clock.advance(3000)
  await clock.settle()
  expect(await band($)).toMatch(/^0\.32\.4 pending/)
})

test('hidden, the band is gone and timed reads stop, but the pane reads', async ($, on) => {
  const hidden = { [SWITCHES]: '{"pin-drift:hidden": true}' }
  const { seen, clock } = engine(on, { ...BEHIND, files: hidden })
  await start($, clock)
  await clock.advance(20 * MINUTE)
  await clock.settle()
  expect(ghRuns(seen.runs)).toEqual([])
  expect(await band($)).toBe('engine')
  await command($, 'pin-drift')
  await clock.settle()
  expect(ghRuns(seen.runs).length).toBeGreaterThan(0)
  expect(await band($)).toBe('engine')
  const ui = await $.ui.mount(PANE('terminal'))
  expect(await ui.find({ type: 'Text', text: 'Laundry-Bot' })).toBeDefined()
  await ui.unmount()
})

test('/pin-drift opens the pane, and so does an .open- file from /mods', async ($, on) => {
  const { seen, clock } = engine(on, { files: { [MARKER]: '' } })
  await start($, clock)
  await clock.advance(3000)
  await clock.settle()
  expect(seen.opened).toEqual(['pin-drift'])
  expect(MARKER in seen.files).toBe(false)
  await command($, 'pin-drift')
  await clock.settle()
  expect(seen.opened).toEqual(['pin-drift', 'pin-drift'])
})

const passing = [{ status: 'COMPLETED', conclusion: 'SUCCESS' }]

test('the pane lists each consumer: current, behind, unreadable, old lock name', async ($, on) => {
  const { clock } = engine(on, {
    consumers: ok(JSON.stringify({ consumers: ALL })),
    releases: ok(JSON.stringify([release(101, '0.32.4')])),
    locks: {
      'Laundry-Bot': lock('v0.31.4'),
      personal: lock('v0.30.0', 'merph518/Overmind'),
      'Gnome-Widgets': { exitCode: 1, stderr: 'gh: Not Found (HTTP 404)' },
      'Playwright-Testing': lock('v0.32.0'),
    },
    pins: {
      'Laundry-Bot': ok(JSON.stringify([pinPr(57, 'v0.32.3', passing)])),
      'Playwright-Testing': { exitCode: 1, stderr: 'HTTP 502' },
    },
  })
  await start($, clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount(PANE(surface))
    const has = async (text: string | RegExp) =>
      expect(await ui.find({ type: 'Text', text })).toBeDefined()
    await has('Latest tag 0.32.3')
    const links = await ui.findAll({ type: 'Link' })
    expect(links.map(link => (link.props as { label?: string }).label)).toEqual([
      '#101 chore: release 0.32.4',
      'pin pull request #57 (v0.32.3)',
    ])
    await has(/pinned 0\.31\.4 · behind 0\.32\.3 · .*CI passing/)
    await has('pinned 0.30.0 · behind 0.32.3 · no open pin pull request')
    await has('pinned 0.32.0 · behind 0.32.3 · pin pull requests could not be read')
    await has('lock names merph518/Overmind')
    await has(/^lock unreadable: no \.claude\/att-docs\.lock/)
    await has('pinned 0.32.3 · on latest')
    await has('Checked 0m ago')
    await ui.unmount()
  }
})

test('a current consumer under an older lock name shows its move pull request', async ($, on) => {
  const move = { ...pinPr(12, 'v0.32.3', passing), headRefName: 'overmind/move-v0.32.3' }
  const { clock } = engine(on, {
    locks: { 'Laundry-Bot': lock('v0.32.3', 'merph518/Overmind') },
    pins: { 'Laundry-Bot': ok(JSON.stringify([move])) },
  })
  await start($, clock)
  expect(await band($)).toBe('engine')
  const ui = await $.ui.mount(PANE('terminal'))
  const links = await ui.findAll({ type: 'Link' })
  expect(links.map(link => (link.props as { label?: string }).label)).toEqual([
    'move pull request #12 (v0.32.3)',
  ])
  expect(await ui.find({ type: 'Text', text: 'lock names merph518/Overmind' })).toBeDefined()
  await ui.unmount()
})

test('Refresh reads again even when the kept result is fresh, not overlapping', async ($, on) => {
  const { seen, clock, hold } = engine(on, BEHIND)
  await start($, clock)
  // consumers.json is the first read of every refresh.
  const refreshes = () =>
    ghRuns(seen.runs).filter(args => args[2]?.endsWith('consumers.json')).length
  expect(refreshes()).toBe(1)
  const open = hold()
  const ui = await $.ui.mount(PANE('terminal'))
  await ui.press({ key: 'refresh' })
  await clock.settle()
  expect(refreshes()).toBe(2)
  await ui.press({ key: 'refresh' })
  await ui.press({ key: 'refresh' })
  await clock.settle()
  // Held: the run in progress has not finished, so no second one has started.
  expect(refreshes()).toBe(2)
  open()
  await clock.settle()
  await ui.unmount()
  // The two presses during the held run fold into one more.
  expect(refreshes()).toBe(3)
})
