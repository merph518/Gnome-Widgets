import { expect, test } from 'claude-code/testing'

import {
  DAY_MS,
  HOUR_MS,
  MINUTE_MS,
  ciState,
  classifyFailure,
  formatAge,
  isGhPr,
  listArgv,
  parsePrList,
  parseRepos,
  parseSwitches,
  sortOldestFirst,
  watched,
} from './queue'

const done = (conclusion: string) => ({ __typename: 'CheckRun', status: 'COMPLETED', conclusion })

test('no checks reads as none', () => {
  expect(ciState([])).toBe('none')
  expect(ciState(undefined)).toBe('none')
  expect(ciState(null)).toBe('none')
})

test('completed check runs that succeeded, were skipped or were neutral read as passing', () => {
  expect(ciState([done('SUCCESS'), done('SKIPPED'), done('NEUTRAL')])).toBe('passing')
  expect(ciState([{ __typename: 'StatusContext', state: 'SUCCESS' }])).toBe('passing')
})

test('a check still going reads as running', () => {
  expect(ciState([done('SUCCESS'), { status: 'IN_PROGRESS', conclusion: '' }])).toBe('running')
  expect(ciState([{ status: 'QUEUED' }])).toBe('running')
  expect(ciState([{ state: 'PENDING' }])).toBe('running')
})

test('any failure reads as failing, ahead of a check still going', () => {
  expect(ciState([{ status: 'IN_PROGRESS' }, done('FAILURE')])).toBe('failing')
  expect(ciState([done('TIMED_OUT')])).toBe('failing')
  expect(ciState([done('CANCELLED')])).toBe('failing')
  expect(ciState([{ state: 'ERROR' }])).toBe('failing')
  expect(ciState([{ state: 'FAILURE' }, { status: 'QUEUED' }])).toBe('failing')
})

test('gh pr list output is read into pull requests', () => {
  const out = JSON.stringify([
    {
      number: 7,
      title: 'feat: a thing',
      url: 'https://github.com/o/r/pull/7',
      createdAt: '2026-11-17T10:00:00Z',
      isDraft: true,
      statusCheckRollup: [done('SUCCESS')],
    },
    { title: 'no number' },
  ])
  expect(parsePrList(out, 'r')).toEqual([
    {
      repo: 'r',
      number: 7,
      title: 'feat: a thing',
      url: 'https://github.com/o/r/pull/7',
      createdAt: Date.parse('2026-11-17T10:00:00Z'),
      isDraft: true,
      ci: 'passing',
    },
  ])
  expect(parsePrList('[]', 'r')).toEqual([])
  expect(parsePrList('not json', 'r')).toBe(null)
  expect(parsePrList('{}', 'r')).toBe(null)
})

test('the list command asks one repository for open pull requests with the label', () => {
  const argv = listArgv('Laundry-Bot')
  expect(argv.slice(0, 3)).toEqual(['gh', 'pr', 'list'])
  expect(argv).toContain('merph518/Laundry-Bot')
  expect(argv).toContain('Manual Review Needed')
  expect(argv.join(' ')).toMatch(/statusCheckRollup/)
})

test('consumers.json is read into repository names, and a bad file into null', () => {
  expect(parseRepos('{"consumers": ["A", "b-c", 3, "../x", "A"]}')).toEqual(['A', 'b-c', 'A'])
  expect(parseRepos('{"other": []}')).toBe(null)
  expect(parseRepos('[]')).toBe(null)
  expect(parseRepos('oops')).toBe(null)
})

test('this repository is always watched, first, and each repository once', () => {
  expect(watched([])).toEqual(['Overmind-Mod'])
  expect(watched(['A', 'Overmind-Mod', 'A'])).toEqual(['Overmind-Mod', 'A'])
})

test('a gh failure is sorted into signed out, offline or failed', () => {
  expect(classifyFailure(4, '')).toBe('signed-out')
  expect(classifyFailure(1, 'To get started with GitHub CLI, please run:  gh auth login')).toBe('signed-out')
  expect(classifyFailure(1, 'error connecting to api.github.com')).toBe('offline')
  expect(classifyFailure(1, 'dial tcp: lookup api.github.com: no such host')).toBe('offline')
  expect(classifyFailure(1, 'GraphQL: Could not resolve to a Repository')).toBe('failed')
})

test('ages read in whole minutes, hours or days', () => {
  expect(formatAge(0)).toBe('0m')
  expect(formatAge(59 * MINUTE_MS)).toBe('59m')
  expect(formatAge(HOUR_MS)).toBe('1h')
  expect(formatAge(DAY_MS - 1)).toBe('23h')
  expect(formatAge(3 * DAY_MS)).toBe('3d')
  expect(formatAge(-5)).toBe('0m')
})

test('only a gh pr command counts', () => {
  expect(isGhPr('gh pr edit 3 --add-label x')).toBe(true)
  expect(isGhPr('cd /r && gh pr create --fill')).toBe(true)
  expect(isGhPr('ghost pr list')).toBe(false)
  expect(isGhPr('gh issue list')).toBe(false)
  expect(isGhPr(undefined)).toBe(false)
})

test('oldest first', () => {
  const pr = (repo: string, number: number, createdAt: number) =>
    ({ repo, number, createdAt, title: '', url: '', isDraft: false, ci: 'none' }) as const
  const sorted = sortOldestFirst([pr('b', 1, 20), pr('a', 2, 10), pr('a', 1, 10)])
  expect(sorted.map(p => `${p.repo}#${p.number}`)).toEqual(['a#1', 'a#2', 'b#1'])
})

test('switches.json turns the plugin off or hides the band', () => {
  expect(parseSwitches(undefined)).toEqual({ isOff: false, isHidden: false })
  expect(parseSwitches('{"review-queue": false}')).toEqual({ isOff: true, isHidden: false })
  expect(parseSwitches('{"review-queue:hidden": true}')).toEqual({ isOff: false, isHidden: true })
  expect(parseSwitches('[1]')).toEqual({ isOff: false, isHidden: false })
  expect(parseSwitches('broken')).toEqual({ isOff: false, isHidden: false })
})
