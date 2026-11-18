import { expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'
import type { Engine } from 'claude-code/testing'

const START = Date.parse('2026-11-18T12:00:00.000Z')
const MINUTE = 60_000
const HOUR = 60 * MINUTE

type Answer = { exitCode: number; stdout?: string; stderr?: string } | 'reject' | 'timeout'

type Setup = {
  // What `gh pr list` answers, by repository name.
  repos?: Record<string, Answer>
  // What the consumers.json read answers.
  consumers?: Answer
  files?: Record<string, string>
  store?: Record<string, unknown>
}

function pr(number: number, title: string, opened: number, checks: unknown[] = [], isDraft = false) {
  return {
    number,
    title,
    url: `https://github.com/merph518/x/pull/${number}`,
    createdAt: new Date(opened).toISOString(),
    isDraft,
    statusCheckRollup: checks,
  }
}

const ok = (prs: unknown[]): Answer => ({ exitCode: 0, stdout: JSON.stringify(prs) })
const CONSUMERS: Answer = { exitCode: 0, stdout: JSON.stringify({ consumers: ['Laundry-Bot'] }) }

// Stands in for the engine beneath the plugin, and records the gh calls.
function engine(on: On, setup: Setup = {}) {
  const files: Record<string, string> = { ...setup.files }
  const seen = { runs: [] as string[][], toasts: [] as string[], store: { ...setup.store } as Record<string, unknown> }
  const repos: Record<string, Answer> = { 'Overmind-Mod': ok([]), ...setup.repos }
  let gate: Promise<void> | null = null
  mock.env(on, { HOME: '/home/me' })
  const clock = mock.clock(on, { now: START })
  on('store.get', (_, e) => ({ value: seen.store[e.key] }))
  on('store.set', (_, e) => {
    seen.store[e.key] = e.value
    return { value: undefined }
  })
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('fs.read', (_, e) => {
    const text = files[e.path]
    return text === undefined ? { deny: 'ENOENT' } : { value: text }
  })
  on('ui.toast', (_, e) => {
    seen.toasts.push(String((e as { text?: unknown }).text))
    return { value: undefined } as never
  })
  on('process.run', async (_, e) => {
    seen.runs.push([...e.argv])
    if (gate !== null) await gate
    const answer = e.argv[1] === 'api' ? (setup.consumers ?? CONSUMERS) : repos[e.argv[4]?.split('/')[1] ?? '']
    if (answer === undefined) return { value: { exitCode: 0, stdout: '[]', stderr: '' } as never }
    if (answer === 'reject') return { deny: 'spawn gh ENOENT' }
    if (answer === 'timeout') return { deny: 'gh is still running after 20000 ms' }
    return { value: { exitCode: answer.exitCode, stdout: answer.stdout ?? '', stderr: answer.stderr ?? '' } as never }
  })
  on('tool.call', () => ({ result: { stdout: 'ran' } }) as never)
  // What the engine draws when the plugin draws nothing of its own.
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>engine</Text>
  })
  return {
    seen,
    clock,
    files,
    repos,
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

const BAND = (surface: 'terminal' | 'desktop') =>
  ({
    plugin: 'review-queue',
    surface,
    component: 'AbovePrompt',
    requestId: 'band',
    props: { hasSurvey: false, bodyColumns: 100 },
  }) as never

async function band($: Engine, surface: 'terminal' | 'desktop' = 'terminal') {
  const ui = await $.ui.mount(BAND(surface))
  const found = await ui.find({ type: 'Text' })
  await ui.unmount()
  return found?.text ?? ''
}

const lists = (runs: string[][]) => runs.filter(argv => argv[1] === 'pr')

test('a labeled pull request shows in the band, and the list shows its link, CI state and age', async ($, on) => {
  const { clock } = engine(on, {
    repos: {
      'Laundry-Bot': ok([
        pr(12, 'fix: dryer slot', START - 3 * HOUR, [{ status: 'COMPLETED', conclusion: 'FAILURE' }]),
      ]),
      'Overmind-Mod': ok([pr(5, 'feat: band', START - 2 * 24 * HOUR, [{ status: 'IN_PROGRESS' }], true)]),
    },
  })
  await start($, clock)

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount(BAND(surface))
    expect((await ui.find({ type: 'Text' }))?.text).toMatch(/^2 waiting for review/)
    expect(await ui.find({ type: 'Link' })).toBeUndefined()
    await ui.press({ key: 'toggle' })
    const links = await ui.findAll({ type: 'Link' })
    expect(links.map(link => (link.props as { href?: string }).href)).toEqual([
      'https://github.com/merph518/x/pull/5',
      'https://github.com/merph518/x/pull/12',
    ])
    expect((await ui.find({ type: 'Text', text: /running · 2d · draft/ }))).toBeDefined()
    expect((await ui.find({ type: 'Text', text: /failing · 3h/ }))).toBeDefined()
    await ui.press({ key: 'toggle' })
    await ui.unmount()
  }
})

test('with no labeled pull request there is no band', async ($, on) => {
  const { clock } = engine(on)
  await start($, clock)
  expect(await band($)).toBe('engine')
})

test('the watched repositories are this one and the ones consumers.json names', async ($, on) => {
  const { seen, clock } = engine(on)
  await start($, clock)
  expect(lists(seen.runs).map(argv => argv[4])).toEqual(['merph518/Overmind-Mod', 'merph518/Laundry-Bot'])
  expect((seen.store['repos'] as { list: string[] }).list).toEqual(['Laundry-Bot'])
})

test('consumers.json is read again only after an hour', async ($, on) => {
  const { seen, clock } = engine(on)
  await start($, clock)
  await clock.advance(5 * MINUTE)
  await clock.settle()
  expect(seen.runs.filter(argv => argv[1] === 'api')).toHaveLength(1)
  await clock.advance(HOUR)
  await clock.settle()
  expect(seen.runs.filter(argv => argv[1] === 'api')).toHaveLength(2)
})

test('when consumers.json cannot be read, the kept list is used, else this repository alone', async ($, on) => {
  const { seen, clock } = engine(on, {
    consumers: { exitCode: 1, stderr: 'HTTP 404' },
    store: { repos: { list: ['Gnome-Widgets'], at: START - 2 * HOUR } },
  })
  await start($, clock)
  expect(lists(seen.runs).map(argv => argv[4])).toEqual(['merph518/Overmind-Mod', 'merph518/Gnome-Widgets'])
})

test('with no kept list and no consumers.json, only this repository is read', async ($, on) => {
  const { seen, clock } = engine(on, { consumers: { exitCode: 1, stderr: 'HTTP 404' } })
  await start($, clock)
  expect(lists(seen.runs).map(argv => argv[4])).toEqual(['merph518/Overmind-Mod'])
})

test('gh signed out shows one quiet line that stays the same, with no toast', async ($, on) => {
  const { seen, clock } = engine(on, {
    consumers: { exitCode: 4, stderr: 'gh auth login' },
    repos: { 'Overmind-Mod': { exitCode: 4, stderr: 'To get started with GitHub CLI, please run:  gh auth login' } },
  })
  await start($, clock)
  expect(await band($)).toMatch(/^Review queue: gh is signed out/)
  await clock.advance(10 * MINUTE)
  await clock.settle()
  expect(await band($)).toMatch(/^Review queue: gh is signed out/)
  expect(seen.toasts).toEqual([])
  // One repository is tried per refresh: signed out holds for all of them.
  expect(lists(seen.runs)).toHaveLength(3)
})

test('gh missing shows one quiet line', async ($, on) => {
  const { clock } = engine(on, { consumers: 'reject', repos: { 'Overmind-Mod': 'reject' } })
  await start($, clock)
  expect(await band($)).toBe('Review queue: gh is not installed')
})

test('offline shows one quiet line', async ($, on) => {
  const offline: Answer = { exitCode: 1, stderr: 'error connecting to api.github.com' }
  const { clock } = engine(on, { consumers: offline, repos: { 'Overmind-Mod': offline } })
  await start($, clock)
  expect(await band($)).toBe('Review queue: GitHub cannot be reached')
})

test('one repository that cannot be read leaves the others shown, with a note', async ($, on) => {
  const { clock } = engine(on, {
    repos: {
      'Overmind-Mod': ok([pr(1, 'a', START - MINUTE)]),
      'Laundry-Bot': { exitCode: 1, stderr: 'GraphQL: Could not resolve to a Repository' },
    },
  })
  await start($, clock)
  expect(await band($)).toMatch(/^1 waiting for review · 1 repository could not be read/)
})

test('a good refresh replaces the failure line', async ($, on) => {
  const { clock, repos } = engine(on, {
    consumers: { exitCode: 1, stderr: 'error connecting' },
    repos: { 'Overmind-Mod': { exitCode: 1, stderr: 'error connecting to api.github.com' } },
  })
  await start($, clock)
  expect(await band($)).toMatch(/cannot be reached/)
  repos['Overmind-Mod'] = ok([pr(1, 'a', START)])
  await clock.advance(5 * MINUTE)
  await clock.settle()
  expect(await band($)).toMatch(/^1 waiting for review/)
})

test('a refresh asked for while one runs waits for it, then runs once', async ($, on) => {
  const made = engine(on, { store: { repos: { list: [], at: START } } })
  await start($, made.clock)
  expect(lists(made.seen.runs)).toHaveLength(1)
  const release = made.hold()
  await made.clock.advance(5 * MINUTE)
  expect(lists(made.seen.runs)).toHaveLength(2)
  await $.tool.call({ tool: 'Bash', command: 'gh pr edit 3 --add-label x' } as never)
  await made.clock.advance(5 * MINUTE)
  // Still the one run held open: nothing overlaps it.
  expect(lists(made.seen.runs)).toHaveLength(2)
  release()
  await made.clock.settle()
  expect(lists(made.seen.runs)).toHaveLength(3)
})

test('a gh pr command refreshes a few seconds later without holding the call; other commands do not', async ($, on) => {
  const made = engine(on, { store: { repos: { list: [], at: START } } })
  await start($, made.clock)
  const release = made.hold()
  await $.tool.call({ tool: 'Bash', command: 'ls -la' } as never)
  await made.clock.advance(5000)
  expect(lists(made.seen.runs)).toHaveLength(1)
  const result = await $.tool.call({ tool: 'Bash', command: 'gh pr edit 3 --add-label x' } as never)
  expect(result).toBeDefined()
  expect(lists(made.seen.runs)).toHaveLength(1)
  await made.clock.advance(3000)
  expect(lists(made.seen.runs)).toHaveLength(2)
  release()
  await made.clock.settle()
})

test('switched off, gh is not run and there is no band; switched on again, it refreshes', async ($, on) => {
  const SWITCHES = '/home/me/.claude/mods/switches.json'
  const made = engine(on, {
    files: { [SWITCHES]: '{"review-queue": false}' },
    repos: { 'Overmind-Mod': ok([pr(1, 'a', START)]) },
  })
  await start($, made.clock)
  await made.clock.advance(10 * MINUTE)
  await made.clock.settle()
  expect(made.seen.runs).toEqual([])
  expect(await band($)).toBe('engine')
  made.files[SWITCHES] = '{}'
  await made.clock.advance(15_000)
  await made.clock.settle()
  expect(await band($)).toMatch(/^1 waiting for review/)
})

test('hidden, there is no band', async ($, on) => {
  const { clock } = engine(on, {
    files: { '/home/me/.claude/mods/switches.json': '{"review-queue:hidden": true}' },
    repos: { 'Overmind-Mod': ok([pr(1, 'a', START)]) },
  })
  await start($, clock)
  expect(await band($)).toBe('engine')
})

test('more pull requests than the list holds are counted', async ($, on) => {
  const many = Array.from({ length: 11 }, (_, i) => pr(i + 1, `pr ${i + 1}`, START - (i + 1) * MINUTE))
  const { clock } = engine(on, { repos: { 'Overmind-Mod': ok(many) } })
  await start($, clock)
  const ui = await $.ui.mount(BAND('desktop'))
  await ui.press({ key: 'toggle' })
  expect(await ui.findAll({ type: 'Link' })).toHaveLength(8)
  expect((await ui.find({ type: 'Text', text: /and 3 more/ }))?.text).toBe('and 3 more')
  await ui.unmount()
})

test('with the question dialog up there is no band', async ($, on) => {
  const { clock } = engine(on, { repos: { 'Overmind-Mod': ok([pr(1, 'a', START)]) } })
  await start($, clock)
  const ui = await $.ui.mount({
    plugin: 'review-queue',
    surface: 'terminal',
    component: 'AbovePrompt',
    requestId: 'band',
    props: { hasSurvey: true, bodyColumns: 100 },
  } as never)
  expect((await ui.find({ type: 'Text' }))?.text).toBe('engine')
  await ui.unmount()
})

test('a second session.start, as a reload runs, leaves one timer refreshing', async ($, on) => {
  const { seen, clock } = engine(on, { store: { repos: { list: [], at: START } } })
  await start($, clock)
  await start($, clock)
  const before = lists(seen.runs).length
  await clock.advance(5 * MINUTE)
  await clock.settle()
  expect(lists(seen.runs).length - before).toBe(1)
})

test('hidden then shown, the band waits for a fresh list', async ($, on) => {
  const SWITCHES = '/home/me/.claude/mods/switches.json'
  const made = engine(on, { repos: { 'Overmind-Mod': ok([pr(1, 'a', START)]) } })
  await start($, made.clock)
  expect(await band($)).toMatch(/^1 waiting/)
  made.files[SWITCHES] = '{"review-queue:hidden": true}'
  await made.clock.advance(15_000)
  await made.clock.settle()
  made.files[SWITCHES] = '{}'
  const release = made.hold()
  await made.clock.advance(15_000)
  // The refresh is still running: the list from before the band was hidden is gone.
  expect(await band($)).toBe('engine')
  release()
  await made.clock.settle()
  expect(await band($)).toMatch(/^1 waiting/)
})

test('one repository timing out does not stop the others being read', async ($, on) => {
  const { clock } = engine(on, {
    repos: { 'Overmind-Mod': 'timeout', 'Laundry-Bot': ok([pr(4, 'b', START - MINUTE)]) },
  })
  await start($, clock)
  expect(await band($)).toMatch(/^1 waiting for review · 1 repository could not be read/)
})

test('hidden while a refresh runs, its list is not kept', async ($, on) => {
  const SWITCHES = '/home/me/.claude/mods/switches.json'
  const made = engine(on, { store: { repos: { list: [], at: START } } })
  const release = made.hold()
  made.repos['Overmind-Mod'] = ok([pr(1, 'a', START)])
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true } as never)
  await made.clock.advance(0)
  made.files[SWITCHES] = '{"review-queue:hidden": true}'
  await made.clock.advance(15_000)
  release()
  await made.clock.settle()
  made.files[SWITCHES] = '{}'
  const shown = made.hold()
  await made.clock.advance(15_000)
  // Shown again with the next refresh still running: nothing from before is drawn.
  expect(await band($)).toBe('engine')
  shown()
  await made.clock.settle()
  expect(lists(made.seen.runs).length).toBe(2)
  expect(await band($)).toMatch(/^1 waiting/)
})
