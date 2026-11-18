import { expect, test } from 'claude-code/testing'

import type { ConsumerPin, Drift } from '../types'
import type { GhResult } from './drift'

import {
  argv,
  bandText,
  ciState,
  classifyFailure,
  compareVersions,
  configDir,
  failureLine,
  fetchDrift,
  hasGaps,
  isBehind,
  isHomeRepo,
  isQuiet,
  lockNote,
  lockPin,
  newestPinPr,
  parseConsumers,
  parseLock,
  parsePinPrs,
  parseReleasePrs,
  parseSwitches,
  parseTagRefs,
  parseVersion,
  shortVersion,
} from './drift'

test('a lock reads its first repo= and tag= lines, with CRLF, a BOM and extra keys', () => {
  expect(parseLock('repo=merph518/Overmind-Mod\ntag=v0.31.4\ncommit=abc\n')).toEqual({
    repo: 'merph518/Overmind-Mod',
    tag: 'v0.31.4',
  })
  expect(parseLock('﻿repo=merph518/Overmind\r\ntag=v0.30.0\r\ntree=def\r\n')).toEqual({
    repo: 'merph518/Overmind',
    tag: 'v0.30.0',
  })
  // As the pin script reads it: carriage returns dropped, spaces kept.
  expect(parseLock('tag=v0.30.0  \r\n')).toEqual({ repo: null, tag: 'v0.30.0  ' })
  expect(parseLock('tag=v1.0.0\ntag=v2.0.0\n')).toEqual({ repo: null, tag: 'v1.0.0' })
  expect(parseLock('repo=x/y\n')).toEqual({ repo: 'x/y', tag: null })
})

test('a lock pin is its tag, or a note saying why there is none', () => {
  expect(lockPin('repo=merph518/Overmind-Mod\ntag=v0.31.4\n')).toEqual({
    pinned: 'v0.31.4',
    lockRepo: 'merph518/Overmind-Mod',
    note: null,
  })
  expect(lockPin('repo=merph518/Overmind-Mod\n')).toEqual({
    pinned: null,
    lockRepo: 'merph518/Overmind-Mod',
    note: 'the lock has no tag= line',
  })
  expect(lockPin('tag=main\n')).toEqual({
    pinned: null,
    lockRepo: null,
    note: 'tag=main is not vMAJOR.MINOR.PATCH',
  })
  expect(lockPin('tag=v1.2\n').note).toBe('tag=v1.2 is not vMAJOR.MINOR.PATCH')
  expect(lockPin('tag=v0.31.4 \n').pinned).toBeNull()
})

test('versions compare numerically, with or without the v', () => {
  expect(parseVersion('v0.32.3')).toEqual([0, 32, 3])
  expect(parseVersion('0.32.3')).toEqual([0, 32, 3])
  expect(parseVersion('v1.0.0-rc1')).toBeNull()
  expect(parseVersion('v1.2')).toBeNull()
  expect(compareVersions('0.10.0', '0.9.9')).toBeGreaterThan(0)
  expect(compareVersions('v0.32.3', '0.32.3')).toBe(0)
  expect(compareVersions('v0.31.10', 'v0.32.0')).toBeLessThan(0)
  expect(shortVersion('v0.32.3')).toBe('0.32.3')
})

test('the latest tag is the highest vMAJOR.MINOR.PATCH ref', () => {
  const refs = [
    'refs/tags/v0.9.9',
    'refs/tags/v0.32.3',
    'refs/tags/v0.10.0',
    'refs/tags/v1.0.0-rc1',
    'refs/tags/vfoo',
    '',
  ].join('\n')
  expect(parseTagRefs(refs)).toBe('v0.32.3')
  expect(parseTagRefs('')).toBeNull()
  expect(parseTagRefs('refs/tags/v2.0.0-beta\n')).toBeNull()
})

test('the home repository is Overmind under any of its names and remote forms', () => {
  for (const url of [
    'https://github.com/merph518/Overmind-Mod.git',
    'https://github.com/merph518/Overmind-Mod',
    'https://github.com/merph518/overmind-mod/',
    'git@github.com:merph518/Overmind.git',
    'ssh://git@github.com/mfagerstrom/Overmind-Mod.git',
    'https://someone@github.com/mfagerstrom/Overmind',
    'git://github.com/MERPH518/OVERMIND-MOD.git',
  ]) {
    expect([url, isHomeRepo(url)]).toEqual([url, true])
  }
  for (const url of [
    'https://github.com/merph518/Laundry-Bot.git',
    'https://github.com/someone/Overmind-Mod.git',
    'https://gitlab.com/merph518/Overmind-Mod.git',
    'https://github.com/merph518/Overmind-Mod-fork.git',
    '',
    null,
  ]) {
    expect([url, isHomeRepo(url)]).toEqual([url, false])
  }
})

const release = (
  number: number,
  title: string,
  labels = ['autorelease: pending'],
  state = 'open',
) => ({
  number,
  title,
  state,
  html_url: `https://github.com/merph518/Overmind-Mod/pull/${number}`,
  labels: labels.map(name => ({ name })),
})

test('a release is pending when a labeled release pull request is above the latest tag', () => {
  const one = JSON.stringify([release(101, 'chore: release 0.32.4')])
  expect(parseReleasePrs(one, 'v0.32.3')).toEqual({
    version: '0.32.4',
    number: 101,
    url: 'https://github.com/merph518/Overmind-Mod/pull/101',
    title: 'chore: release 0.32.4',
  })
  // Already tagged: the release pull request is stale.
  expect(parseReleasePrs(one, 'v0.32.4')).toBeNull()
  const unlabeled = JSON.stringify([release(101, 'chore: release 0.32.4', [])])
  expect(parseReleasePrs(unlabeled, 'v0.32.3')).toBeNull()
  const closed = JSON.stringify([release(101, 'chore: release 0.32.4', undefined, 'closed')])
  expect(parseReleasePrs(closed, 'v0.32.3')).toBeNull()
  const scoped = JSON.stringify([release(7, 'chore(main): release v0.33.0')])
  expect(parseReleasePrs(scoped, 'v0.32.3')?.version).toBe('0.33.0')
  const two = JSON.stringify([
    release(7, 'chore: release 0.32.4'),
    release(8, 'chore: release 0.33.0'),
  ])
  expect(parseReleasePrs(two, 'v0.32.3')?.number).toBe(8)
  expect(parseReleasePrs(two, null)?.number).toBe(8)
  expect(parseReleasePrs('not json', 'v0.32.3')).toBeNull()
})

const pinPr = (number: number, headRefName: string, statusCheckRollup: unknown[] = []) => ({
  number,
  url: `https://github.com/merph518/Laundry-Bot/pull/${number}`,
  headRefName,
  statusCheckRollup,
})

test('pin pull requests come from overmind/pin- and overmind/move- branches', () => {
  const prs = parsePinPrs(
    JSON.stringify([
      pinPr(3, 'overmind/pin-v0.31.4'),
      pinPr(4, 'overmind/move-v0.32.3', [{ status: 'COMPLETED', conclusion: 'SUCCESS' }]),
      pinPr(5, 'topic/overmind/pin-v1.0.0'),
      pinPr(6, 'feat/x'),
      pinPr(7, 'overmind/pin-v0.32'),
    ]),
  )
  expect(prs?.map(pr => [pr.number, pr.tag, pr.ci])).toEqual([
    [3, 'v0.31.4', 'none'],
    [4, 'v0.32.3', 'passing'],
  ])
  expect(newestPinPr(prs ?? [], null)?.number).toBe(4)
  expect(newestPinPr([], null)).toBeNull()
})

test('a pin pull request at or below the current pin is stale; a move one at it is not', () => {
  const prs = parsePinPrs(
    JSON.stringify([pinPr(3, 'overmind/pin-v0.31.4'), pinPr(4, 'overmind/move-v0.31.4')]),
  ) ?? []
  expect(newestPinPr(prs, 'v0.31.4')?.number).toBe(4)
  expect(newestPinPr(prs.slice(0, 1), 'v0.31.4')).toBeNull()
  expect(newestPinPr(prs.slice(0, 1), 'v0.31.0')?.number).toBe(3)
  expect(newestPinPr(prs.slice(1), 'v0.32.0')).toBeNull()
  expect(parsePinPrs('{}')).toBeNull()
})

test('the CI state of a pull request comes from its checks', () => {
  expect(ciState([])).toBe('none')
  expect(ciState(undefined)).toBe('none')
  const success = { status: 'COMPLETED', conclusion: 'SUCCESS' }
  const failure = { status: 'COMPLETED', conclusion: 'FAILURE' }
  expect(ciState([success, { state: 'SUCCESS' }])).toBe('passing')
  expect(ciState([{ status: 'IN_PROGRESS' }, success])).toBe('running')
  expect(ciState([{ status: 'IN_PROGRESS' }, failure])).toBe('failing')
  expect(ciState([{ state: 'ERROR' }])).toBe('failing')
})

const pin = (name: string, pinned: string | null, note: string | null = null): ConsumerPin => ({
  name,
  pinned,
  lockRepo: 'merph518/Overmind-Mod',
  note,
  pr: null,
  isPrUnknown: false,
})
const drift = (consumers: ConsumerPin[], pending: string | null = null): Drift => ({
  latest: 'v0.32.3',
  pending:
    pending === null
      ? null
      : { version: pending, number: 101, url: 'u', title: `chore: release ${pending}` },
  isReleaseUnknown: false,
  consumers,
  failure: null,
  at: 0,
})

test('a consumer is behind when its pin is below the latest tag', () => {
  expect(isBehind(pin('a', 'v0.31.4'), 'v0.32.3')).toBe(true)
  expect(isBehind(pin('a', 'v0.32.3'), 'v0.32.3')).toBe(false)
  expect(isBehind(pin('a', 'v0.33.0'), 'v0.32.3')).toBe(false)
  expect(isBehind(pin('a', null, 'x'), 'v0.32.3')).toBe(false)
})

test('the band is quiet when every consumer is on the latest tag and nothing is pending', () => {
  const current = drift([pin('Laundry-Bot', 'v0.32.3'), pin('personal', 'v0.33.0')])
  expect(isQuiet(current)).toBe(true)
  expect(bandText(current, 100)).toBeNull()
  expect(isQuiet(drift([pin('a', 'v0.32.3')], '0.32.4'))).toBe(false)
  expect(isQuiet(drift([pin('a', null, 'x')]))).toBe(false)
  expect(isQuiet({ ...current, failure: 'offline', latest: null })).toBe(false)
  expect(isQuiet({ ...current, isReleaseUnknown: true })).toBe(false)
  expect(bandText({ ...current, isReleaseUnknown: true }, 100)).toBe('release state unreadable')
})

test('a result is partial when a release or pin pull request read failed', () => {
  const current = drift([pin('Laundry-Bot', 'v0.32.3')])
  expect(hasGaps(current)).toBe(false)
  expect(hasGaps({ ...current, failure: 'offline' })).toBe(true)
  expect(hasGaps({ ...current, isReleaseUnknown: true })).toBe(true)
  expect(hasGaps(drift([{ ...pin('Laundry-Bot', 'v0.31.0'), isPrUnknown: true }]))).toBe(true)
})

test('the band names the pending release and each consumer behind, in listed order', () => {
  const two = drift(
    [
      pin('ATT-Test-Pack-Gen', 'v0.32.3'),
      pin('Laundry-Bot', 'v0.31.4'),
      pin('personal', 'v0.30.0'),
    ],
    '0.32.4',
  )
  expect(bandText(two, 200)).toBe(
    '0.32.4 pending · 2 consumers behind latest (Laundry-Bot 0.31.4, personal 0.30.0)',
  )
  expect(bandText(drift([pin('a', 'v0.32.3')], '0.32.4'), 200)).toBe('0.32.4 pending')
  expect(bandText(drift([pin('Laundry-Bot', 'v0.31.4')]), 200)).toBe(
    '1 consumer behind latest (Laundry-Bot 0.31.4)',
  )
  const unreadable = drift([pin('a', null, 'x'), pin('b', 'v0.32.3')])
  expect(bandText(unreadable, 200)).toBe('1 lock unreadable')
  const mixed = drift([pin('a', null, 'x'), pin('b', null, 'y'), pin('c', 'v0.1.0')])
  expect(bandText(mixed, 200)).toBe('1 consumer behind latest (c 0.1.0) · 2 locks unreadable')
  expect(bandText({ ...mixed, isReleaseUnknown: true }, 200)).toBe(
    'release state unreadable · 1 consumer behind latest (c 0.1.0) · 2 locks unreadable',
  )
})

test('a narrow band drops names from the end, then the list', () => {
  const many = drift([
    pin('Laundry-Bot', 'v0.31.4'),
    pin('personal', 'v0.30.0'),
    pin('Gnome-Widgets', 'v0.29.0'),
    pin('Playwright-Testing', 'v0.28.0'),
  ])
  expect(bandText(many, 90)).toBe(
    '4 consumers behind latest (Laundry-Bot 0.31.4, personal 0.30.0, +2 more)',
  )
  expect(bandText(many, 70)).toBe('4 consumers behind latest (Laundry-Bot 0.31.4, +3 more)')
  expect(bandText(many, 40)).toBe('4 consumers behind latest')
})

test('the band leaves room for the button, drawn as [ Details ], and the space before it', () => {
  const many = drift([
    pin('Laundry-Bot', 'v0.31.4'),
    pin('personal', 'v0.30.0'),
    pin('Gnome-Widgets', 'v0.1.0'),
  ])
  const two = '3 consumers behind latest (Laundry-Bot 0.31.4, personal 0.30.0, +1 more)'
  const button = '[ Details ]'.length + 1
  expect(bandText(many, two.length + button)).toBe(two)
  expect(bandText(many, two.length + button - 1)).toBe(
    '3 consumers behind latest (Laundry-Bot 0.31.4, +2 more)',
  )
})

test('a failed gh call is signed out, offline, rate limited, missing or failed', () => {
  expect(classifyFailure(4, '')).toBe('signed-out')
  const login = 'To get started with GitHub CLI, please run:  gh auth login'
  expect(classifyFailure(1, login)).toBe('signed-out')
  expect(classifyFailure(1, 'error connecting to api.github.com')).toBe('offline')
  expect(classifyFailure(1, 'HTTP 403: API rate limit exceeded for user')).toBe('rate-limited')
  expect(classifyFailure(1, 'HTTP 500')).toBe('failed')
  expect(classifyFailure(null, 'spawn gh ENOENT')).toBe('missing')
  expect(classifyFailure(null, 'gh is still running after 20000 ms')).toBe('failed')
  expect(failureLine('missing')).toBe('Pin drift: gh is not installed')
  expect(failureLine('signed-out')).toBe('Pin drift: gh is signed out (gh auth login)')
  expect(failureLine('offline')).toBe('Pin drift: GitHub cannot be reached')
  expect(failureLine('rate-limited')).toBe('Pin drift: GitHub API rate limit reached')
  expect(failureLine('failed')).toBe('Pin drift: gh could not read the tags')
})

test('a lock that cannot be read gets a note saying why', () => {
  expect(lockNote(1, 'gh: Not Found (HTTP 404)')).toBe(
    'no .claude/att-docs.lock on the default branch, or gh cannot read the repository',
  )
  expect(lockNote(1, 'HTTP 403: API rate limit exceeded')).toBe(
    'the GitHub API rate limit was reached',
  )
  expect(lockNote(1, 'error connecting to api.github.com')).toBe('GitHub cannot be reached')
  expect(lockNote(null, 'gh is still running after 20000 ms')).toBe('gh could not read the lock')
})

test('consumers.json lists repository names', () => {
  const listed = JSON.stringify({ consumers: ['Laundry-Bot', 'personal', 'bad name', 3] })
  expect(parseConsumers(listed)).toEqual(['Laundry-Bot', 'personal'])
  expect(parseConsumers('[]')).toBeNull()
  expect(parseConsumers('nope')).toBeNull()
})

test('switches.json turns the plugin off or hides the band', () => {
  expect(parseSwitches(undefined)).toEqual({ isOff: false, isHidden: false })
  expect(parseSwitches('{"pin-drift": false}')).toEqual({ isOff: true, isHidden: false })
  expect(parseSwitches('{"pin-drift:hidden": true}')).toEqual({ isOff: false, isHidden: true })
  expect(parseSwitches('[1]')).toEqual({ isOff: false, isHidden: false })
  expect(parseSwitches('{')).toEqual({ isOff: false, isHidden: false })
  expect(configDir('/home/me', undefined)).toBe('/home/me/.claude')
  expect(configDir('/home/me', ' /cfg/ ')).toBe('/cfg')
})

type Fake = Partial<{
  consumers: GhResult
  tags: GhResult
  releases: GhResult
  locks: Record<string, GhResult>
  pins: Record<string, GhResult>
}>

const out = (stdout: string): GhResult => ({ exitCode: 0, stdout, stderr: '' })
const err = (exitCode: number | null, stderr: string): GhResult => ({
  exitCode,
  stdout: '',
  stderr,
})
const lock = (tag: string) => out(`repo=merph518/Overmind-Mod\ntag=${tag}\ncommit=abc\n`)

// A gh that answers by the argv the plugin builds, and records each call.
function fakeGh(fake: Fake) {
  const calls: string[][] = []
  const gh = async (args: string[]): Promise<GhResult> => {
    calls.push(args)
    const key = JSON.stringify(args)
    if (key === JSON.stringify(argv.consumers())) {
      return fake.consumers ?? out(JSON.stringify({ consumers: ['Laundry-Bot', 'personal'] }))
    }
    if (key === JSON.stringify(argv.tags())) {
      return fake.tags ?? out('refs/tags/v0.31.4\nrefs/tags/v0.32.3\n')
    }
    if (key === JSON.stringify(argv.releasePrs())) return fake.releases ?? out('[]')
    for (const name of ['Laundry-Bot', 'personal', 'Gnome-Widgets']) {
      if (key === JSON.stringify(argv.lock(name))) return fake.locks?.[name] ?? lock('v0.32.3')
      if (key === JSON.stringify(argv.pinPrs(name))) return fake.pins?.[name] ?? out('[]')
    }
    return err(1, `unexpected ${key}`)
  }
  return { gh, calls }
}

const noFallback = async () => [] as string[]

const RAW = ['-H', 'Accept: application/vnd.github.raw+json']

test('gh reads each repository by its current name, the lock from the default branch', () => {
  expect(argv.consumers()).toEqual([
    'gh', 'api', 'repos/merph518/Overmind-Mod/contents/.github/consumers.json', ...RAW,
  ])
  expect(argv.tags()).toEqual([
    'gh', 'api', '--paginate', 'repos/merph518/Overmind-Mod/git/matching-refs/tags/v',
    '--jq', '.[].ref',
  ])
  expect(argv.lock('Laundry-Bot')).toEqual([
    'gh', 'api', 'repos/merph518/Laundry-Bot/contents/.claude/att-docs.lock', ...RAW,
  ])
  expect(argv.lock('Laundry-Bot').join(' ')).not.toMatch(/ref=/)
  expect(argv.pinPrs('Laundry-Bot').slice(0, 5)).toEqual([
    'gh', 'pr', 'list', '--repo', 'merph518/Laundry-Bot',
  ])
})

test('a refresh reads each lock, and pin pull requests only for consumers behind', async () => {
  const { gh, calls } = fakeGh({
    releases: out(JSON.stringify([release(101, 'chore: release 0.32.4')])),
    locks: { 'Laundry-Bot': lock('v0.31.4') },
    pins: {
      'Laundry-Bot': out(
        JSON.stringify([
          pinPr(9, 'overmind/pin-v0.32.3', [{ status: 'IN_PROGRESS' }]),
          pinPr(8, 'overmind/pin-v0.32.0'),
        ]),
      ),
    },
  })
  const drift = await fetchDrift(gh, noFallback, 1234)
  expect(drift.latest).toBe('v0.32.3')
  expect(drift.pending?.version).toBe('0.32.4')
  expect(drift.failure).toBeNull()
  expect(drift.at).toBe(1234)
  const rows = drift.consumers.map(c => [c.name, c.pinned, c.pr?.number ?? null, c.pr?.ci ?? null])
  expect(rows).toEqual([
    ['Laundry-Bot', 'v0.31.4', 9, 'running'],
    ['personal', 'v0.32.3', null, null],
  ])
  const prReads = calls.filter(args => args[1] === 'pr').map(args => args[4])
  expect(prReads).toEqual(['merph518/Laundry-Bot'])
})

test('tags that cannot be read give a failure and no lock is read', async () => {
  const { gh, calls } = fakeGh({ tags: err(1, 'error connecting to api.github.com') })
  const drift = await fetchDrift(gh, noFallback, 0)
  expect(drift.failure).toBe('offline')
  expect(drift.consumers).toEqual([])
  expect(calls.some(args => args[2]?.includes('att-docs.lock'))).toBe(false)
  const none = await fetchDrift(fakeGh({ tags: out('refs/tags/v1.0.0-rc1\n') }).gh, noFallback, 0)
  expect(none.failure).toBe('failed')
})

test('one unreadable lock does not stop the others', async () => {
  const { gh } = fakeGh({
    locks: { 'Laundry-Bot': err(1, 'gh: Not Found (HTTP 404)'), personal: lock('v0.30.0') },
  })
  const drift = await fetchDrift(gh, noFallback, 0)
  expect(drift.failure).toBeNull()
  expect(drift.consumers.map(c => [c.name, c.pinned, c.note])).toEqual([
    [
      'Laundry-Bot',
      null,
      'no .claude/att-docs.lock on the default branch, or gh cannot read the repository',
    ],
    ['personal', 'v0.30.0', null],
  ])
})

test('signed out on a lock is the failure, and stops the remaining reads', async () => {
  const { gh, calls } = fakeGh({
    locks: { 'Laundry-Bot': lock('v0.31.0'), personal: err(4, 'gh auth login') },
  })
  const drift = await fetchDrift(gh, noFallback, 0)
  expect(drift.failure).toBe('signed-out')
  expect(drift.latest).toBe('v0.32.3')
  // What was read before the failure is kept for the pane.
  expect(drift.consumers.map(c => [c.name, c.pinned, c.note])).toEqual([
    ['Laundry-Bot', 'v0.31.0', null],
    ['personal', null, 'gh is signed out'],
  ])
  expect(calls.filter(args => args[1] === 'pr')).toEqual([])
})

test('rate limited on the release list is the failure, and no lock is read', async () => {
  const { gh, calls } = fakeGh({ releases: err(1, 'HTTP 403: API rate limit exceeded') })
  const drift = await fetchDrift(gh, noFallback, 0)
  expect(drift.failure).toBe('rate-limited')
  expect(drift.consumers.map(c => [c.name, c.pinned])).toEqual([
    ['Laundry-Bot', null],
    ['personal', null],
  ])
  expect(calls.filter(args => args[2]?.includes('att-docs.lock'))).toEqual([])
})

test('a release list that cannot be read leaves the release unknown, not quiet', async () => {
  for (const releases of [err(1, 'HTTP 500'), err(null, 'gh is still running'), out('<html>')]) {
    const drift = await fetchDrift(fakeGh({ releases }).gh, noFallback, 0)
    expect(drift.pending).toBeNull()
    expect(drift.isReleaseUnknown).toBe(true)
    expect(drift.failure).toBeNull()
    expect(isQuiet(drift)).toBe(false)
    expect(hasGaps(drift)).toBe(true)
  }
})

test('pin pull requests that cannot be read are unknown, not missing', async () => {
  const { gh } = fakeGh({
    locks: { 'Laundry-Bot': lock('v0.31.4'), personal: lock('v0.30.0') },
    pins: { 'Laundry-Bot': err(1, 'HTTP 502'), personal: out('not json') },
  })
  const drift = await fetchDrift(gh, noFallback, 0)
  expect(drift.failure).toBeNull()
  expect(drift.consumers.map(c => [c.name, c.pr, c.isPrUnknown])).toEqual([
    ['Laundry-Bot', null, true],
    ['personal', null, true],
  ])
})

test('offline on a pin pull request read is the failure, and stops the reads', async () => {
  const { gh, calls } = fakeGh({
    locks: { 'Laundry-Bot': lock('v0.31.4'), personal: lock('v0.30.0') },
    pins: { 'Laundry-Bot': err(1, 'error connecting to api.github.com') },
  })
  const drift = await fetchDrift(gh, noFallback, 0)
  expect(drift.failure).toBe('offline')
  expect(drift.consumers.map(c => c.isPrUnknown)).toEqual([true, true])
  expect(calls.filter(args => args[1] === 'pr')).toHaveLength(1)
})

test('a current consumer whose lock names an older repository has its pulls read', async () => {
  const moved = out('repo=merph518/Overmind\ntag=v0.32.3\n')
  const { gh, calls } = fakeGh({
    locks: { 'Laundry-Bot': moved, personal: out('repo=MERPH518/overmind-mod\ntag=v0.32.3\n') },
    pins: { 'Laundry-Bot': out(JSON.stringify([pinPr(12, 'overmind/move-v0.32.3')])) },
  })
  const drift = await fetchDrift(gh, noFallback, 0)
  expect(drift.consumers.map(c => [c.name, c.pr?.number ?? null])).toEqual([
    ['Laundry-Bot', 12],
    ['personal', null],
  ])
  expect(calls.filter(args => args[1] === 'pr').map(args => args[4])).toEqual([
    'merph518/Laundry-Bot',
  ])
  expect(isQuiet(drift)).toBe(true)
})

test('when consumers.json cannot be read, the fallback list is used', async () => {
  const { gh } = fakeGh({ consumers: err(1, 'HTTP 500') })
  const drift = await fetchDrift(gh, async () => ['Gnome-Widgets'], 0)
  expect(drift.consumers.map(c => c.name)).toEqual(['Gnome-Widgets'])
})
