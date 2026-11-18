import { expect, test } from 'claude-code/testing'

import type { ApiRunner, LocalUnit, QueuedJob } from '../types'
import {
  DEFAULT_SETTINGS,
  GRACE_MS,
  MINUTE_MS,
  assess,
  bandText,
  configDir,
  ghFailure,
  parseDf,
  parseJobs,
  parseRunIds,
  parseRunnerFile,
  parseRunners,
  parseSettings,
  parseSwitches,
  parseUnits,
} from './health'
import type { AssessInput } from './health'

const NOW = Date.parse('2026-11-18T12:00:00.000Z')
const GIB = 1024 ** 3

const UNITS = [
  'actions.runner.MRF-ORG.tablet-runner-1.service loaded active running GitHub Actions Runner (MRF-ORG.tablet-runner-1)',
  'actions.runner.MRF-ORG.tablet-runner-2.service loaded inactive dead GitHub Actions Runner (MRF-ORG.tablet-runner-2)',
  '● actions.runner.MRF-ORG.tablet-runner-3.service loaded failed failed GitHub Actions Runner (MRF-ORG.tablet-runner-3)',
  '',
].join('\n')

test('runner services read from systemctl, with failed and inactive ones stopped', () => {
  expect(parseUnits(UNITS)).toEqual([
    { unit: 'actions.runner.MRF-ORG.tablet-runner-1.service', runner: 'tablet-runner-1', isActive: true },
    { unit: 'actions.runner.MRF-ORG.tablet-runner-2.service', runner: 'tablet-runner-2', isActive: false },
    { unit: 'actions.runner.MRF-ORG.tablet-runner-3.service', runner: 'tablet-runner-3', isActive: false },
  ])
  expect(parseUnits('')).toEqual([])
  expect(parseUnits('ssh.service loaded active running OpenSSH')).toEqual([])
})

test('a .runner file with a byte order mark gives its name and work folder', () => {
  const text = '﻿{\n  "agentName": "tablet-runner-1",\n  "workFolder": "_work"\n}'
  expect(parseRunnerFile(text)).toEqual({ name: 'tablet-runner-1', workFolder: '_work' })
  expect(parseRunnerFile(undefined)).toEqual({ name: null, workFolder: '_work' })
  expect(parseRunnerFile('not json')).toEqual({ name: null, workFolder: '_work' })
})

test('df rows on one filesystem make one disk', () => {
  const out = [
    'Filesystem     1024-blocks      Used Available Capacity Mounted on',
    '/dev/nvme0n1p2   982292956 658289448 274032052      71% /',
    '/dev/nvme0n1p2   982292956 658289448 274032052      71% /',
    'tmpfs             30144584    577608  29566976       2% /tmp',
  ].join('\n')
  expect(parseDf(out, ['/r1/_work', '/r2/_work', '/tmp'])).toEqual([
    { mount: '/', paths: ['/r1/_work', '/r2/_work'], freeBytes: 274032052 * 1024 },
    { mount: '/tmp', paths: ['/tmp'], freeBytes: 29566976 * 1024 },
  ])
  expect(parseDf('', ['/x'])).toEqual([])
})

const RUNNERS = JSON.stringify({
  total_count: 3,
  runners: [
    { name: 'tablet-runner-1', status: 'online', busy: true, labels: [{ name: 'self-hosted' }, { name: 'overmind' }] },
    { name: 'pw-ci-runner-desktop-1', status: 'offline', busy: false, labels: [{ name: 'overmind' }] },
    { name: 'pw-windows-runner-1', status: 'offline', busy: false, labels: [{ name: 'playwright' }] },
  ],
})

test('only runners with the watched label are kept', () => {
  expect(parseRunners(RUNNERS, 'overmind')).toEqual([
    { name: 'tablet-runner-1', isOnline: true, isBusy: true },
    { name: 'pw-ci-runner-desktop-1', isOnline: false, isBusy: false },
  ])
  expect(parseRunners('{"message":"Not Found"}', 'overmind')).toBe(null)
  expect(parseRunners('oops', 'overmind')).toBe(null)
})

test('run ids and queued jobs with the label are read', () => {
  expect(parseRunIds(JSON.stringify({ workflow_runs: [{ id: 7 }, { id: 9 }] }))).toEqual([7, 9])
  expect(parseRunIds('{}')).toBe(null)
  const jobs = JSON.stringify({
    jobs: [
      { status: 'queued', name: 'test-all', workflow_name: 'CI', created_at: '2026-11-18T11:40:00Z', labels: ['self-hosted', 'overmind'] },
      { status: 'in_progress', name: 'lint', workflow_name: 'CI', created_at: '2026-11-18T11:40:00Z', labels: ['overmind'] },
      { status: 'queued', name: 'other', workflow_name: 'CI', created_at: '2026-11-18T11:40:00Z', labels: ['ubuntu-latest'] },
    ],
  })
  expect(parseJobs(jobs, 'o/r', 'overmind')).toEqual([
    { repo: 'o/r', workflow: 'CI', name: 'test-all', createdAt: Date.parse('2026-11-18T11:40:00Z') },
  ])
  expect(parseJobs('[]', 'o/r', 'overmind')).toBe(null)
})

test('gh failures read as a plain reason', () => {
  expect(ghFailure(null, '')).toMatch(/did not run/)
  expect(ghFailure(4, 'To get started with GitHub CLI, please run:  gh auth login')).toMatch(/gh auth login/)
  expect(ghFailure(1, 'gh: Must have admin rights to Repository. (HTTP 403)')).toMatch(/admin:org/)
  expect(ghFailure(1, 'gh: Not Found (HTTP 404)')).toMatch(/did not find.*admin:org/)
  expect(ghFailure(1, 'gh: API rate limit exceeded for user (HTTP 403)')).toBe('GitHub API rate limit reached')
  expect(ghFailure(1, 'something else')).toBe('gh exited with 1')
})

test('switches, settings and the config folder', () => {
  expect(parseSwitches(undefined)).toEqual({ isOff: false, isHidden: false })
  expect(parseSwitches('{"runner-health": false, "runner-health:hidden": true}')).toEqual({ isOff: true, isHidden: true })
  expect(parseSwitches('[1]')).toEqual({ isOff: false, isHidden: false })
  expect(parseSettings(undefined)).toEqual(DEFAULT_SETTINGS)
  expect(parseSettings('{"org":"acme","repos":["acme/a","bad"],"queuedMinutes":5,"freeGiB":-1}')).toEqual({
    ...DEFAULT_SETTINGS,
    org: 'acme',
    repos: ['acme/a'],
    queuedMinutes: 5,
  })
  expect(configDir('/home/me', undefined)).toBe('/home/me/.claude')
  expect(configDir('/home/me', '/cfg/')).toBe('/cfg')
})

const unit = (runner: string, isActive: boolean): LocalUnit => ({
  unit: `actions.runner.ORG.${runner}.service`,
  runner,
  isActive,
})
const online = (name: string, isBusy = false): ApiRunner => ({ name, isOnline: true, isBusy })
const offline = (name: string): ApiRunner => ({ name, isOnline: false, isBusy: false })
const job = (minutesAgo: number, name = 'test-all'): QueuedJob => ({
  repo: 'o/r',
  workflow: 'CI',
  name,
  createdAt: NOW - minutesAgo * MINUTE_MS,
})

function input(over: Partial<AssessInput>): AssessInput {
  return {
    units: [],
    activeSince: {},
    runners: [],
    jobs: [],
    disks: [],
    apiNote: null,
    localNote: null,
    now: NOW,
    settings: DEFAULT_SETTINGS,
    ...over,
  }
}

const kinds = (over: Partial<AssessInput>) => assess(input(over)).problems.map(problem => problem.kind)

test('all well, busy runners included, is no problem', () => {
  const health = assess(
    input({
      units: [unit('r1', true)],
      activeSince: { r1: NOW - GRACE_MS },
      runners: [online('r1', true), online('w1', true)],
      disks: [{ mount: '/', paths: ['/r1/_work'], freeBytes: 200 * GIB }],
    }),
  )
  expect(health).toEqual({ problems: [], note: null })
  expect(bandText(health, 80)).toBe(null)
})

test('a stopped service here is offline with the command that starts it', () => {
  const health = assess(input({ units: [unit('r1', false)], runners: [online('r1')] }))
  expect(health.problems).toEqual([
    { kind: 'offline', text: 'r1 is stopped', fix: 'sudo systemctl start actions.runner.ORG.r1.service' },
  ])
})

test('two stopped services share one start command that names them', () => {
  const [problem] = assess(input({ units: [unit('r1', false), unit('r2', false)], runners: null, apiNote: 'x' })).problems
  expect(problem?.text).toBe('r1, r2 are stopped')
  expect(problem?.fix).toBe('sudo systemctl start actions.runner.ORG.r1.service actions.runner.ORG.r2.service')
})

test('a service without the watched label is left out once GitHub has answered', () => {
  expect(kinds({ units: [unit('other', false)], runners: [online('r1')] })).toEqual([])
})

test('a runner on another machine that is offline is named, with no command', () => {
  expect(assess(input({ runners: [offline('w1')] })).problems).toEqual([
    { kind: 'offline', text: 'w1 is offline (another machine)', fix: null },
  ])
})

test('a service that just started is not offline while GitHub catches up', () => {
  const units = [unit('r1', true)]
  expect(kinds({ units, runners: [offline('r1')], activeSince: { r1: NOW - GRACE_MS + 1 } })).toEqual([])
  expect(assess(input({ units, runners: [offline('r1')], activeSince: { r1: NOW - GRACE_MS } })).problems).toEqual([
    {
      kind: 'offline',
      text: 'r1 runs here but GitHub shows it offline',
      fix: 'sudo systemctl restart actions.runner.ORG.r1.service',
    },
  ])
})

test('a job queued past the threshold shows; one under it does not', () => {
  expect(kinds({ jobs: [job(9)] })).toEqual([])
  expect(assess(input({ jobs: [job(11)] })).problems).toEqual([
    { kind: 'queued', text: 'o/r job "CI / test-all" waiting 11 min for an overmind runner', fix: null },
  ])
  expect(assess(input({ jobs: [job(12, 'a'), job(30, 'b')] })).problems[0]?.text).toBe(
    '2 jobs waiting for an overmind runner, oldest 30 min',
  )
})

test('a job that waits past the threshold while every runner is busy still shows, and says it waits', () => {
  const health = assess(input({ runners: [online('r1', true)], jobs: [job(15)] }))
  expect(health.problems.map(problem => problem.text)).toEqual(['o/r job "CI / test-all" waiting 15 min for an overmind runner'])
})

test('a disk under the threshold shows its free space', () => {
  const disks = [
    { mount: '/', paths: ['/r1/_work'], freeBytes: 3.1 * GIB },
    { mount: '/tmp', paths: ['/tmp'], freeBytes: 20 * GIB },
  ]
  expect(assess(input({ disks })).problems).toEqual([{ kind: 'disk', text: 'only 3.1 GiB free on /', fix: null }])
})

test('with nothing readable, one line says why', () => {
  const health = assess(input({ runners: null, apiNote: 'gh is not signed in: run gh auth login', localNote: 'systemctl is not available' }))
  expect(health.problems).toEqual([
    { kind: 'unreadable', text: 'cannot read the runners: gh is not signed in: run gh auth login', fix: null },
  ])
  expect(bandText(health, 200)).toBe('Runner health: cannot read the runners: gh is not signed in: run gh auth login')
})

test('with GitHub unreadable, the services here are still checked and the reason rides along', () => {
  const quiet = assess(input({ units: [unit('r1', true)], runners: null, apiNote: 'GitHub could not be reached' }))
  expect(bandText(quiet, 200)).toBe(null)
  const loud = assess(input({ units: [unit('r1', false)], runners: null, apiNote: 'GitHub could not be reached' }))
  expect(bandText(loud, 200)).toBe(
    'Runner health: r1 is stopped: sudo systemctl start actions.runner.ORG.r1.service (GitHub not checked: GitHub could not be reached)',
  )
})

test('problems past the width are counted at the end', () => {
  const health = {
    problems: [
      { kind: 'offline' as const, text: 'w1 is offline (another machine)', fix: null },
      { kind: 'queued' as const, text: '2 jobs waiting for an overmind runner, oldest 30 min', fix: null },
      { kind: 'disk' as const, text: 'only 3.1 GiB free on /', fix: null },
    ],
    note: null,
  }
  expect(bandText(health, 60)).toBe('Runner health: w1 is offline (another machine) · +2 more')
  expect(bandText(health, 500)).toBe(
    'Runner health: w1 is offline (another machine) · 2 jobs waiting for an overmind runner, oldest 30 min · only 3.1 GiB free on /',
  )
})
