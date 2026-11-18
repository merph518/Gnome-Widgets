import { expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'
import type { Engine } from 'claude-code/testing'

import { HEADER, bandText, isOfferable, listingFrom, parseSwitches, parseTsv, removalNote } from './sweeper'
import type { SweepRow } from '../types'

// worktree-cleanup.sh's own rules are tested on real worktrees in
// scripts/worktree-cleanup_test.sh. Here a stub answers for the script.

type Line = { name: string; verdict: string; dirty?: string; unpushed?: string; pr?: string }
type Result = { exitCode: number; stdout: string; stderr: string }

const DIR = '/repo/.claude/worktrees'
const line = (one: Line) =>
  [`.claude/worktrees/${one.name}`, one.name, one.pr ?? 'MERGED #1', one.dirty ?? '0', one.unpushed ?? '0', one.verdict, `${DIR}/${one.name}`].join('\t')
const tsv = (lines: readonly Line[]) => [HEADER, ...lines.map(line)].join('\n') + '\n'
const done = (name: string): Line => ({ name, verdict: 'remove' })
const ok = (stdout: string, exitCode = 0, stderr = ''): Result => ({ exitCode, stdout, stderr })

type Setup = {
  lines?: Line[]
  switches?: string
  cwd?: string
  root?: string
  // What a listing returns instead of the rows, or throws.
  list?: Result | 'reject'
  // What --remove-path prints for a path, instead of removing it.
  removals?: Record<string, Result>
  files?: Record<string, string>
  // Holds each listing open until the test releases it.
  hold?: { wait: Promise<void> }
}

type Run = { argv: readonly string[]; cwd: string | undefined }

// Stands in for the engine beneath the plugin, and records what the plugin asked of it.
function engine(on: On, setup: Setup = {}) {
  let lines = [...(setup.lines ?? [])]
  const files: Record<string, string> = { ...setup.files }
  if (setup.switches !== undefined) files['/home/me/.claude/mods/switches.json'] = setup.switches
  const seen = { runs: [] as Run[], opened: [] as string[], closed: 0, files, running: 0, most: 0 }
  mock.env(on, { HOME: '/home/me' })
  mock.store(on)
  const clock = mock.clock(on, { now: Date.UTC(2026, 10, 18, 9, 0, 0) })
  on('session.id', () => ({ value: 's1' }))
  on('session.root', () => ({ value: setup.root ?? '/repo' }))
  on('session.cwd', () => ({ value: setup.cwd ?? setup.root ?? '/repo' }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('command.register', (_, e) => ({ value: { command: e.name } }))
  on('ui.open', (_, e) => {
    seen.opened.push(e.id)
    return { value: { isPlaced: true } } as never
  })
  on('ui.close', () => {
    seen.closed += 1
    return { value: undefined } as never
  })
  on('fs.read', (_, e) => (e.path in files ? { value: files[e.path] as string } : { deny: 'no such file' }))
  on('fs.exists', (_, e) => ({ value: e.path in files }))
  on('process.run', (_, e) => {
    seen.runs.push({ argv: e.argv, cwd: e.init?.cwd })
    const reply = (result: Result) => ({ value: { ...result, isStdoutTruncated: false, isStderrTruncated: false } })
    if (e.argv[0] === 'rm') {
      for (const path of e.argv.slice(2)) delete files[path]
      return reply(ok(''))
    }
    if (e.argv[2] === '--tsv') {
      if (setup.list === 'reject') return { deny: 'timed out' }
      const answer = reply(setup.list ?? ok(tsv(lines)))
      if (setup.hold === undefined) return answer
      seen.running += 1
      seen.most = Math.max(seen.most, seen.running)
      return setup.hold.wait.then(() => {
        seen.running -= 1
        return answer
      })
    }
    if (e.argv[2] === '--remove-path') {
      const path = e.argv[3] ?? ''
      const said = setup.removals?.[path]
      if (said !== undefined) return reply(said)
      lines = lines.filter(one => `${DIR}/${one.name}` !== path)
      return reply(ok(`removed ${path}\n`))
    }
    return reply(ok('', 1))
  })
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>engine</Text>
  })
  const listings = () => seen.runs.filter(run => run.argv[2] === '--tsv')
  const removals = () => seen.runs.filter(run => run.argv[2] === '--remove-path')
  return { seen, clock, listings, removals }
}

async function start($: Engine, clock: { settle: () => Promise<void> }) {
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true } as never)
  await clock.settle()
}

async function command($: Engine, name: string) {
  return $.command.run({ command: name, args: '', origin: { kind: 'composer' }, presentation: 'text' } as never)
}

const SURFACES = ['terminal', 'desktop'] as const

const BAND = (surface: (typeof SURFACES)[number]) =>
  ({
    plugin: 'worktree-sweeper',
    surface,
    component: 'AbovePrompt',
    requestId: 'band',
    props: { hasSurvey: false, bodyColumns: 80 },
  }) as never

const PANE = (surface: (typeof SURFACES)[number]) =>
  ({
    plugin: 'worktree-sweeper',
    surface,
    component: 'Pane',
    requestId: 'worktree-sweeper',
    props: { title: 'Worktree sweeper', isFocused: true, bodyColumns: 100, placement: 'dock', scroll: { offset: 0, bodyRows: 60 }, view: {} },
  }) as never

const MIXED: Line[] = [
  done('a'),
  { name: 'dirty', verdict: 'keep: 1 uncommitted path(s)', dirty: '1' },
  { name: 'ahead', verdict: 'keep: 1 unpushed commit(s)', unpushed: '1' },
  done('b'),
  { name: 'open', verdict: 'keep: pull request open', pr: 'OPEN #4' },
]

// --- the parts that need no engine

test('parseTsv reads rows of seven cells under the header', () => {
  const listing = parseTsv(tsv([done('a'), { name: 'x', verdict: 'keep: locked' }]))
  expect('rows' in listing && listing.rows.map(row => [row.worktree, row.verdict, row.path])).toEqual([
    ['.claude/worktrees/a', 'remove', `${DIR}/a`],
    ['.claude/worktrees/x', 'keep: locked', `${DIR}/x`],
  ])
  const empty = parseTsv(`${HEADER}\n`)
  expect('rows' in empty && empty.rows).toEqual([])
})

test('parseTsv refuses output without the header or with a short row', () => {
  expect(parseTsv('worktree  branch\n')).toEqual({ error: 'the script printed no header' })
  expect('error' in parseTsv(`${HEADER}\na\tb\tc\n`)).toBe(true)
  expect('error' in parseTsv('')).toBe(true)
})

test('listingFrom names a folder outside git and a failed run', () => {
  expect(listingFrom(ok('', 64, 'not inside'))).toEqual({ error: 'This folder is not in a git repository.' })
  expect(listingFrom(ok('', 2, 'jq: boom'))).toEqual({ error: 'Could not list worktrees: jq: boom' })
})

test('isOfferable takes only remove rows outside the folders this chat runs in', () => {
  const row = (verdict: string, name = 'a'): SweepRow => ({
    worktree: `.claude/worktrees/${name}`, branch: name, pullRequest: 'MERGED #1', uncommitted: '0', unpushed: '0', verdict, path: `${DIR}/${name}`,
  })
  expect(isOfferable(row('remove'), ['/repo'])).toBe(true)
  expect(isOfferable(row('keep: 1 uncommitted path(s)'), ['/repo'])).toBe(false)
  expect(isOfferable(row('remove'), ['/repo', `${DIR}/a`])).toBe(false)
  expect(isOfferable(row('remove'), ['/repo', `${DIR}/a/src`])).toBe(false)
  expect(isOfferable(row('remove', 'ab'), ['/repo', `${DIR}/a`])).toBe(true)
})

test('bandText counts one or many', () => {
  expect(bandText(1)).toBe('1 worktree done · ')
  expect(bandText(5)).toBe('5 worktrees done · ')
})

test('removalNote keeps the script line and adds what git said on a refusal', () => {
  expect(removalNote('/w', ok('removed /w\n'))).toBe('removed /w')
  expect(removalNote('/w', ok('kept /w: locked\n', 1))).toBe('kept /w: locked')
  expect(removalNote('/w', ok('kept /w: git refused to remove it\n', 1, 'fatal: busy\n'))).toBe('kept /w: git refused to remove it (fatal: busy)')
  expect(removalNote('/w', ok('', 2, 'boom'))).toBe('kept /w: boom')
})

test('parseSwitches reads off and hidden, and stays on for an unreadable file', () => {
  expect(parseSwitches('{"worktree-sweeper": false}')).toEqual({ isOff: true, isHidden: false })
  expect(parseSwitches('{"worktree-sweeper:hidden": true}')).toEqual({ isOff: false, isHidden: true })
  expect(parseSwitches('not json')).toEqual({ isOff: false, isHidden: false })
  expect(parseSwitches(undefined)).toEqual({ isOff: false, isHidden: false })
})

// --- the band

test('the band counts the done worktrees and Review opens the pane', async ($, on) => {
  const { seen, clock, listings } = engine(on, { lines: [done('a'), done('b'), done('c'), done('d'), done('e'), ...MIXED.slice(1, 3)] })
  await start($, clock)
  expect(listings()).toHaveLength(1)
  expect(listings()[0]?.cwd).toBe('/repo')
  expect(listings()[0]?.argv[1]).toMatch(/\/scripts\/worktree-cleanup\.sh$/)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount(BAND(surface))
    expect((await ui.find({ type: 'Text', text: /done/ }))?.text).toBe('5 worktrees done · ')
    expect((await ui.find({ type: 'Button', key: 'review' }))?.text).toBe('Review')
    await ui.press({ key: 'review' })
    await clock.settle()
    await ui.unmount()
  }
  expect(seen.opened).toEqual(['worktree-sweeper', 'worktree-sweeper'])
  expect(listings()).toHaveLength(3)
})

test('no band when no worktree can go', async ($, on) => {
  const { clock } = engine(on, { lines: MIXED.filter(one => one.verdict !== 'remove') })
  await start($, clock)
  const ui = await $.ui.mount(BAND('terminal'))
  expect((await ui.find({ type: 'Text' }))?.text).toBe('engine')
  await ui.unmount()
})

test('hidden shows no band and lists nothing on a timer', async ($, on) => {
  const { clock, listings } = engine(on, { lines: [done('a')], switches: '{"worktree-sweeper:hidden": true}' })
  await start($, clock)
  await clock.advance(10 * 60 * 1000)
  expect(listings()).toHaveLength(0)
  const ui = await $.ui.mount(BAND('desktop'))
  expect((await ui.find({ type: 'Text' }))?.text).toBe('engine')
  await ui.unmount()
})

test('off runs no process at all, and /worktree-sweeper says so', async ($, on) => {
  const marker = '/home/me/.claude/mods/.open-worktree-sweeper-s1'
  const { seen, clock } = engine(on, { lines: [done('a')], switches: '{"worktree-sweeper": false}', files: { [marker]: '' } })
  await start($, clock)
  await clock.advance(10 * 60 * 1000)
  const reply = await command($, 'worktree-sweeper')
  await clock.settle()
  expect(JSON.stringify(reply)).toMatch(/switched off/)
  expect(seen.runs).toHaveLength(0)
  expect(seen.opened).toEqual([])
})

test('the worktrees are listed again every ten minutes', async ($, on) => {
  const { clock, listings } = engine(on, { lines: [done('a')] })
  await start($, clock)
  await clock.advance(10 * 60 * 1000)
  await clock.settle()
  expect(listings()).toHaveLength(2)
})

for (const [name, list, why] of [
  ['outside a git repository', ok('', 64, 'not a repo'), /not in a git repository/],
  ['that is refused or times out', 'reject', /Could not list worktrees/],
] as const) {
  test(`a listing ${name} shows why and offers nothing`, async ($, on) => {
    const { clock } = engine(on, { lines: [done('a')], list })
    await start($, clock)
    const band = await $.ui.mount(BAND('terminal'))
    expect((await band.find({ type: 'Text' }))?.text).toBe('engine')
    await band.unmount()
    const pane = await $.ui.mount(PANE('terminal'))
    expect(await pane.find({ type: 'Text', text: why })).toBeDefined()
    expect(await pane.find({ type: 'Button', key: 'remove-0' })).toBeUndefined()
    await pane.unmount()
  })
}

// --- the pane

test('the pane shows the script cells and offers Remove only on done rows', async ($, on) => {
  const { clock } = engine(on, { lines: MIXED })
  await start($, clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount(PANE(surface))
    for (const one of MIXED) {
      expect((await ui.find({ type: 'Text', text: new RegExp(`^\\.claude/worktrees/${one.name}$`) }))?.text).toBe(`.claude/worktrees/${one.name}`)
      expect(await ui.find({ type: 'Text', text: `${one.name} · ${one.pr ?? 'MERGED #1'} · uncommitted ${one.dirty ?? '0'} · unpushed ${one.unpushed ?? '0'}` })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: one.verdict })).toBeDefined()
    }
    const buttons = (await ui.findAll({ type: 'Button' })).map(button => button.key)
    expect(buttons.filter(key => key?.startsWith('remove-') && key !== 'remove-all')).toEqual(['remove-0', 'remove-3'])
    expect((await ui.find({ type: 'Button', key: 'remove-all' }))?.text).toBe('Remove all done (2)')
    await ui.unmount()
  }
})

test('the worktree this chat runs in is never offered, even when the script says remove', async ($, on) => {
  const { clock } = engine(on, { lines: [done('a'), done('b')], cwd: `${DIR}/a/src` })
  await start($, clock)
  const ui = await $.ui.mount(PANE('desktop'))
  expect(await ui.find({ type: 'Button', key: 'remove-0' })).toBeUndefined()
  expect(await ui.find({ type: 'Button', key: 'remove-1' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /this chat runs here/ })).toBeDefined()
  await ui.unmount()
  const band = await $.ui.mount(BAND('desktop'))
  expect((await band.find({ type: 'Text', text: /done/ }))?.text).toBe('1 worktree done · ')
  await band.unmount()
})

test('Remove runs --remove-path without --force, notes the result, and lists again', async ($, on) => {
  const { seen, clock, listings, removals } = engine(on, { lines: MIXED })
  await start($, clock)
  const ui = await $.ui.mount(PANE('terminal'))
  await ui.press({ key: 'remove-3' })
  await clock.settle()
  expect(removals().map(run => run.argv.slice(2))).toEqual([['--remove-path', `${DIR}/b`]])
  expect(removals()[0]?.argv[0]).toBe('bash')
  expect(removals()[0]?.cwd).toBe('/repo')
  expect(seen.runs.some(run => run.argv.includes('--force'))).toBe(false)
  expect(listings()).toHaveLength(2)
  expect(await ui.find({ type: 'Text', text: `removed ${DIR}/b` })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^\.claude\/worktrees\/b$/ })).toBeUndefined()
  await ui.unmount()
})

test('a worktree that changed after the listing is kept, with the reason', async ($, on) => {
  const kept = ok(`kept ${DIR}/a: 1 uncommitted path(s)\n`, 1)
  const { clock } = engine(on, { lines: [done('a')], removals: { [`${DIR}/a`]: kept } })
  await start($, clock)
  const ui = await $.ui.mount(PANE('terminal'))
  await ui.press({ key: 'remove-0' })
  await clock.settle()
  expect(await ui.find({ type: 'Text', text: `kept ${DIR}/a: 1 uncommitted path(s)` })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^\.claude\/worktrees\/a$/ })).toBeDefined()
  await ui.unmount()
})

test('Remove all done asks first, then removes each done row in order and lists once', async ($, on) => {
  const lines = [done('a'), ...MIXED.slice(1, 3), done('b'), done('c')]
  const kept = ok(`kept ${DIR}/b: pull request open\n`, 1)
  const { clock, listings, removals } = engine(on, { lines, removals: { [`${DIR}/b`]: kept } })
  await start($, clock)
  const ui = await $.ui.mount(PANE('desktop'))
  await ui.press({ key: 'remove-all' })
  await clock.settle()
  expect(removals()).toHaveLength(0)
  expect(await ui.find({ type: 'Text', text: /files git ignores/ })).toBeDefined()
  await ui.press({ key: 'cancel-all' })
  await clock.settle()
  expect(await ui.find({ type: 'Button', key: 'confirm-all' })).toBeUndefined()
  await ui.press({ key: 'remove-all' })
  await clock.settle()
  expect((await ui.find({ type: 'Button', key: 'confirm-all' }))?.text).toBe('Remove 3')
  await ui.press({ key: 'confirm-all' })
  await clock.settle()
  expect(removals().map(run => run.argv[3])).toEqual([`${DIR}/a`, `${DIR}/b`, `${DIR}/c`])
  expect(listings()).toHaveLength(2)
  for (const said of [`removed ${DIR}/a`, `kept ${DIR}/b: pull request open`, `removed ${DIR}/c`]) {
    expect(await ui.find({ type: 'Text', text: said })).toBeDefined()
  }
  await ui.unmount()
})

test('presses made during a listing fold into one more listing, never two at once', async ($, on) => {
  let release = () => {}
  const setup: Setup = { lines: [done('a')], hold: { wait: Promise.resolve() } }
  const { seen, clock, listings } = engine(on, setup)
  await start($, clock)
  const ui = await $.ui.mount(PANE('terminal'))
  setup.hold = { wait: new Promise<void>(done => (release = done)) }
  await command($, 'worktree-sweeper')
  await clock.settle()
  expect(listings()).toHaveLength(2)
  expect(await ui.find({ type: 'Button', key: 'remove-0' })).toBeUndefined()
  for (let press = 0; press < 3; press += 1) await command($, 'worktree-sweeper')
  await clock.settle()
  expect(listings()).toHaveLength(2)
  setup.hold = { wait: Promise.resolve() }
  release()
  await clock.settle()
  expect(listings()).toHaveLength(3)
  expect(seen.most).toBe(1)
  await ui.unmount()
})

test('a worktree the chat moved into after the listing is kept when Remove is pressed', async ($, on) => {
  const setup: Setup = { lines: [done('a'), done('b')] }
  const { clock, removals } = engine(on, setup)
  await start($, clock)
  const ui = await $.ui.mount(PANE('desktop'))
  await ui.press({ key: 'remove-all' })
  await clock.settle()
  setup.cwd = `${DIR}/a`
  await ui.press({ key: 'confirm-all' })
  await clock.settle()
  expect(removals().map(run => run.argv[3])).toEqual([`${DIR}/b`])
  expect(await ui.find({ type: 'Text', text: `kept ${DIR}/a: this chat runs here` })).toBeDefined()
  await ui.unmount()
})

test('/worktree-sweeper opens the pane, and so does an .open- file from /mods', async ($, on) => {
  const marker = '/home/me/.claude/mods/.open-worktree-sweeper-s1'
  const { seen, clock } = engine(on, { lines: [done('a')], files: { [marker]: '' } })
  await start($, clock)
  await clock.advance(3000)
  await clock.settle()
  expect(seen.opened).toEqual(['worktree-sweeper'])
  expect(marker in seen.files).toBe(false)
  await command($, 'worktree-sweeper')
  await clock.settle()
  expect(seen.opened).toEqual(['worktree-sweeper', 'worktree-sweeper'])
})

test('the pane says when there is no worktree besides the main checkout', async ($, on) => {
  const { clock } = engine(on, { lines: [] })
  await start($, clock)
  const ui = await $.ui.mount(PANE('terminal'))
  expect(await ui.find({ type: 'Text', text: /No worktrees besides the main checkout/ })).toBeDefined()
  expect(await ui.find({ type: 'Button', key: 'remove-all' })).toBeUndefined()
  await ui.unmount()
})
