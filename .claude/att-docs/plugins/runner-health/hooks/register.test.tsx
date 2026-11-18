import { expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'
import type { Engine } from 'claude-code/testing'

import { API_MS, API_RETRY_MS, GRACE_MS, TICK_MS } from './health'

const START = Date.parse('2026-11-18T12:00:00.000Z')
const CONFIG = '/home/me/.claude'
const CACHE = `${CONFIG}/mods/.runner-health.json`
const SWITCHES = `${CONFIG}/mods/switches.json`
const UNIT = 'actions.runner.ORG.tablet-runner-1.service'
const DIR = '/home/me/actions-runner-1'

type Answer = { exitCode: number; stdout?: string; stderr?: string; delayMs?: number } | 'missing'

type Setup = {
  // What each command prints, by its argv joined with spaces. A command not listed
  // cannot start.
  answers?: Record<string, Answer>
  files?: Record<string, string>
}

function runnersJson(status: 'online' | 'offline') {
  return JSON.stringify({ runners: [{ name: 'tablet-runner-1', status, busy: false, labels: [{ name: 'overmind' }] }] })
}

function unitsLine(state: 'active' | 'inactive') {
  return `${UNIT} loaded ${state} ${state === 'active' ? 'running' : 'dead'} GitHub Actions Runner\n`
}

const DF = 'Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/sda1 1000000000 1 200000000 1% /\n'
const LIST = 'systemctl list-units --all --plain --no-legend actions.runner.*.service'
const RUNNERS = 'gh api orgs/merph518/actions/runners?per_page=100'
const QUEUED = 'gh api repos/merph518/Overmind-Mod/actions/runs?status=queued&per_page=100'
const RUNNING = 'gh api repos/merph518/Overmind-Mod/actions/runs?status=in_progress&per_page=100'
const NO_RUNS = { exitCode: 0, stdout: '{"workflow_runs":[]}' }

// A healthy machine with one runner service.
function healthy(): Record<string, Answer> {
  return {
    [LIST]: { exitCode: 0, stdout: unitsLine('active') },
    [`systemctl show -p WorkingDirectory --value ${UNIT}`]: { exitCode: 0, stdout: `${DIR}\n` },
    [`df -P -k ${DIR}/_work`]: { exitCode: 0, stdout: DF },
    'df -P -k /tmp': { exitCode: 0, stdout: DF.replace(/ \/$/m, ' /tmp') },
    [RUNNERS]: { exitCode: 0, stdout: runnersJson('online') },
    [QUEUED]: NO_RUNS,
    [RUNNING]: NO_RUNS,
  }
}

function engine(on: On, setup: Setup = {}) {
  const answers: Record<string, Answer> = { ...setup.answers }
  const files: Record<string, string> = {
    [`${DIR}/.runner`]: '﻿{"agentName":"tablet-runner-1","workFolder":"_work"}',
    ...setup.files,
  }
  const runs: string[] = []
  mock.env(on, { HOME: '/home/me' })
  const clock = mock.clock(on, { now: START })
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.end', () => ({ sessionId: 's1' }))
  on('session.id', () => ({ value: 's1' }))
  on('fs.read', (_, e) => {
    const text = files[e.path]
    return text === undefined ? { deny: 'ENOENT' } : { value: text }
  })
  on('fs.write', (_, e) => {
    files[e.path] = e.text
    return { value: undefined }
  })
  on('process.run', async (_, e) => {
    const line = e.argv.join(' ')
    runs.push(line)
    const answer = answers[line] ?? 'missing'
    if (answer === 'missing') return { deny: 'ENOENT' }
    if (answer.delayMs !== undefined) await clock.sleep(answer.delayMs)
    return { value: { exitCode: answer.exitCode, stdout: answer.stdout ?? '', stderr: answer.stderr ?? '' } as never }
  })
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>engine</Text>
  })
  return { answers, files, runs, clock }
}

async function start($: Engine, clock: { settle: () => Promise<void> }) {
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true } as never)
  await clock.settle()
}

const BAND = (columns: number) =>
  ({
    plugin: 'runner-health',
    surface: 'terminal',
    component: 'AbovePrompt',
    requestId: 'band',
    props: { hasSurvey: false, bodyColumns: columns },
  }) as never

async function band($: Engine, columns = 200) {
  const ui = await $.ui.mount(BAND(columns))
  const found = await ui.find({ type: 'Text' })
  await ui.unmount()
  return found?.text ?? ''
}

async function tick(clock: { advance: (ms: number) => Promise<void>; settle: () => Promise<void> }, ms = TICK_MS) {
  await clock.advance(ms)
  await clock.settle()
}

test('a healthy runner shows no band', async ($, on) => {
  const { clock } = engine(on, { answers: healthy() })
  await start($, clock)
  expect(await band($)).toBe('engine')
})

test('stopping the runner service shows the band within one refresh, and starting it hides it', async ($, on) => {
  const { answers, clock } = engine(on, { answers: healthy() })
  await start($, clock)
  answers[LIST] = { exitCode: 0, stdout: unitsLine('inactive') }
  await tick(clock)
  expect(await band($)).toBe(`Runner health: tablet-runner-1 is stopped: sudo systemctl start ${UNIT}`)

  // GitHub catches up and reports it offline; the service is started again.
  answers[RUNNERS] = { exitCode: 0, stdout: runnersJson('offline') }
  await tick(clock, API_MS)
  answers[LIST] = { exitCode: 0, stdout: unitsLine('active') }
  await tick(clock)
  expect(await band($)).toBe('engine')

  // Still offline on GitHub once the grace period is over is a problem of its own.
  await tick(clock, GRACE_MS)
  expect(await band($)).toMatch(/runs here but GitHub shows it offline: sudo systemctl restart/)
})

test('with no way to read runner state, one steady line says why and gh is not asked each refresh', async ($, on) => {
  const { runs, clock } = engine(on, {
    answers: { [RUNNERS]: { exitCode: 4, stderr: 'To get started with GitHub CLI, please run:  gh auth login' } },
  })
  await start($, clock)
  const first = await band($)
  expect(first).toBe('Runner health: cannot read the runners: gh is not signed in: run gh auth login')
  for (let i = 0; i < 10; i += 1) await tick(clock)
  expect(await band($)).toBe(first)
  expect(runs.filter(line => line.startsWith('gh ')).length).toBe(1)
  await tick(clock, API_RETRY_MS)
  expect(runs.filter(line => line.startsWith('gh ')).length).toBe(2)
})

test('GitHub is asked once an interval, and another chat reuses a fresh answer', async ($, on) => {
  const { runs, files, clock } = engine(on, { answers: healthy() })
  await start($, clock)
  for (let i = 0; i < 4; i += 1) await tick(clock)
  expect(runs.filter(line => line === RUNNERS).length).toBe(1)
  expect(JSON.parse(files[CACHE] ?? '{}').fetchedAt).toBe(START)
  await tick(clock, API_MS)
  expect(runs.filter(line => line === RUNNERS).length).toBe(2)
})

test('a fresh shared answer from another chat stands in for a call', async ($, on) => {
  const key = JSON.stringify(['merph518', ['merph518/Overmind-Mod'], 'overmind'])
  const api = { runners: [{ name: 'w1', isOnline: false, isBusy: false }], jobs: [], note: null }
  const { runs, clock } = engine(on, {
    answers: healthy(),
    files: { [CACHE]: JSON.stringify({ key, fetchedAt: START - 1000, api }) },
  })
  await start($, clock)
  expect(runs.some(line => line.startsWith('gh '))).toBe(false)
  expect(await band($)).toBe('Runner health: w1 is offline (another machine)')
})

test('a queued job is looked up only when a run is open, and shows once past the threshold', async ($, on) => {
  const answers = healthy()
  answers[RUNNING] = { exitCode: 0, stdout: '{"workflow_runs":[{"id":5}]}' }
  answers['gh api repos/merph518/Overmind-Mod/actions/runs/5/jobs?per_page=100'] = {
    exitCode: 0,
    stdout: JSON.stringify({
      jobs: [
        { status: 'queued', name: 'test-all', workflow_name: 'CI', created_at: new Date(START - 20 * 60_000).toISOString(), labels: ['overmind'] },
      ],
    }),
  }
  const { runs, clock } = engine(on, { answers })
  await start($, clock)
  expect(runs.filter(line => line.includes('/jobs')).length).toBe(1)
  expect(await band($)).toBe('Runner health: merph518/Overmind-Mod job "CI / test-all" waiting 20 min for an overmind runner')
})

test('a machine without systemctl still checks GitHub and does not throw', async ($, on) => {
  const answers = healthy()
  delete answers[LIST]
  answers[RUNNERS] = { exitCode: 0, stdout: runnersJson('offline') }
  const { clock } = engine(on, { answers })
  await start($, clock)
  expect(await band($)).toBe('Runner health: tablet-runner-1 is offline (another machine)')
})

test('switched off runs nothing; hidden draws nothing', async ($, on) => {
  const answers = healthy()
  answers[LIST] = { exitCode: 0, stdout: unitsLine('inactive') }
  const { runs, files, clock } = engine(on, { answers, files: { [SWITCHES]: '{"runner-health": false}' } })
  await start($, clock)
  await tick(clock)
  expect(runs).toEqual([])
  expect(await band($)).toBe('engine')

  files[SWITCHES] = '{"runner-health:hidden": true}'
  await tick(clock)
  expect(runs.length).toBeGreaterThan(0)
  expect(await band($)).toBe('engine')
  files[SWITCHES] = '{}'
  await tick(clock)
  expect(await band($)).toMatch(/is stopped/)
})

test('a narrow band counts what does not fit', async ($, on) => {
  const answers = healthy()
  answers[LIST] = { exitCode: 0, stdout: unitsLine('inactive') }
  answers[`df -P -k ${DIR}/_work`] = {
    exitCode: 0,
    stdout: 'Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/sda1 1000000000 1 1000 1% /\n',
  }
  const { clock } = engine(on, { answers })
  await start($, clock)
  expect(await band($, 60)).toBe(`Runner health: tablet-runner-1 is stopped: sudo systemctl start ${UNIT} · +1 more`)
})

test('a check that runs past the next tick is not stacked on', async ($, on) => {
  const { answers, runs, clock } = engine(on, { answers: healthy() })
  await start($, clock)
  const before = runs.filter(line => line === LIST).length
  answers[LIST] = { exitCode: 0, stdout: unitsLine('active'), delayMs: 40_000 }
  // The tick at 15 s starts a check that ends at 55 s; the ticks at 30 s and 45 s find it running.
  await tick(clock)
  await tick(clock)
  await tick(clock)
  expect(runs.filter(line => line === LIST).length - before).toBe(1)
  await tick(clock)
  expect(runs.filter(line => line === LIST).length - before).toBe(2)
})

test('two runners on one low disk give one disk row, and /tmp is checked too', async ($, on) => {
  const UNIT2 = 'actions.runner.ORG.tablet-runner-2.service'
  const DIR2 = '/home/me/actions-runner-2'
  const LOW = 'Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/sda1 1000000000 1 1048576 1% /\n'
  const answers = healthy()
  answers[LIST] = { exitCode: 0, stdout: unitsLine('active') + unitsLine('active').replaceAll('tablet-runner-1', 'tablet-runner-2') }
  answers[`systemctl show -p WorkingDirectory --value ${UNIT2}`] = { exitCode: 0, stdout: `${DIR2}\n` }
  answers[`df -P -k ${DIR}/_work`] = { exitCode: 0, stdout: LOW }
  answers[`df -P -k ${DIR2}/_work`] = { exitCode: 0, stdout: LOW }
  answers[RUNNERS] = {
    exitCode: 0,
    stdout: JSON.stringify({
      runners: ['tablet-runner-1', 'tablet-runner-2'].map(name => ({ name, status: 'online', busy: false, labels: [{ name: 'overmind' }] })),
    }),
  }
  const { runs, clock } = engine(on, {
    answers,
    files: { [`${DIR2}/.runner`]: '\uFEFF{"agentName":"tablet-runner-2","workFolder":"_work"}' },
  })
  await start($, clock)
  expect(runs).toContain('df -P -k /tmp')
  expect(await band($)).toBe('Runner health: only 1.0 GiB free on /')
})

test('an absolute work folder in .runner is used as it is', async ($, on) => {
  const answers = healthy()
  answers['df -P -k /data/_work'] = { exitCode: 0, stdout: DF }
  const { runs, clock } = engine(on, {
    answers,
    files: { [`${DIR}/.runner`]: '{"agentName":"tablet-runner-1","workFolder":"/data/_work"}' },
  })
  await start($, clock)
  expect(runs).toContain('df -P -k /data/_work')
})
