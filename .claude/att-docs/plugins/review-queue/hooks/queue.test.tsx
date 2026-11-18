import { expect, test } from 'claude-code/testing'

import {
  CLOSE_SLACK_MS,
  DAY_MS,
  HOUR_MS,
  MINUTE_MS,
  catchupFolder,
  ciState,
  classifyFailure,
  dropClosed,
  fileSignature,
  formatAge,
  isGhPr,
  isGhPrChange,
  labelTrigger,
  listArgv,
  parseCloses,
  parseDismissed,
  parsePrList,
  parseRepos,
  parseSwitches,
  prKey,
  pruneDismissed,
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

test('only a gh pr command that can change a pull request counts as a change', () => {
  expect(isGhPrChange('gh pr edit 3 --add-label "Manual Review Needed"')).toBe(true)
  expect(isGhPrChange('cd /r && gh pr merge 3 --merge')).toBe(true)
  expect(isGhPrChange('gh pr ready 3')).toBe(true)
  expect(isGhPrChange('gh pr view 3 --json labels')).toBe(false)
  expect(isGhPrChange('gh pr checks 3')).toBe(false)
  expect(isGhPrChange(undefined)).toBe(false)
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

const T = Date.parse('2026-11-18T12:00:00Z')
const iso = (ms: number) => new Date(ms).toISOString().replace(/\.000Z$/, 'Z')
const closeLine = (number: number, at: number, closedAt = at, state = 'merged') =>
  JSON.stringify({
    event: 'pr',
    run: `pr:${number}`,
    action: 'closed',
    state,
    closed_at: iso(closedAt),
    at: iso(at),
  })

test('the catchup folder is under ~/.cache, named for the owner and repository', () => {
  const folder = catchupFolder('/home/me/', 'Laundry-Bot')
  expect(folder).toBe('/home/me/.cache/catchup/merph518__Laundry-Bot')
})

test('a file is signed by its size and change time, and a missing one is null', () => {
  const entries = [
    { name: 'events.jsonl', kind: 'file', size: 10, mtimeMs: 5 },
    { name: 'forwarder.lock', kind: 'file', size: 0, mtimeMs: 1 },
  ]
  expect(fileSignature(entries, 'events.jsonl')).toBe('10:5')
  expect(fileSignature(entries, 'events.jsonl.old')).toBe(null)
  const folder = [{ name: 'events.jsonl', kind: 'dir', size: 0, mtimeMs: 0 }]
  expect(fileSignature(folder, 'events.jsonl')).toBe(null)
})

test('pull request closes are read; issue closes, runs and broken lines are not', () => {
  const issue = { event: 'issue', run: 'issue:9', action: 'closed', state: 'closed', at: iso(T) }
  const run = { event: 'run', run: '123', action: 'completed', conclusion: 'success', at: iso(T) }
  const text = [
    closeLine(7, T),
    closeLine(8, T + 1000, T - 5000, 'closed'),
    JSON.stringify(issue),
    JSON.stringify(run),
    JSON.stringify({ event: 'pr', run: 'pr:10', action: 'closed' }),
    '{"event": "pr", "run": "pr:11", "act',
    '',
  ].join('\n')
  expect([...parseCloses(text)]).toEqual([
    [7, T],
    [8, T + 1000],
  ])
  expect(parseCloses('').size).toBe(0)
})

test("a close's time is the later of when it was written and GitHub's closed_at", () => {
  expect(parseCloses(closeLine(1, T, T + 2000)).get(1)).toBe(T + 2000)
  expect(parseCloses([closeLine(1, T), closeLine(1, T - HOUR_MS)].join('\n')).get(1)).toBe(T)
})

test('a pull request that closed after it was listed is dropped; an older close is not', () => {
  const pr = (repo: string, number: number) =>
    ({ repo, number, createdAt: 0, title: '', url: '', isDraft: false, ci: 'none' }) as const
  const prs = [pr('a', 1), pr('a', 2), pr('b', 1), pr('a', 3)]
  const closes = new Map([
    [prKey('a', 1), T + 1000],
    [prKey('a', 2), T - CLOSE_SLACK_MS + 1000],
    [prKey('a', 3), T - CLOSE_SLACK_MS - 1000],
  ])
  expect(dropClosed(prs, closes, T).map(p => prKey(p.repo, p.number))).toEqual(['b#1', 'a#3'])
})

test('the stored dismissals are read as repo#number keys, each once', () => {
  expect(parseDismissed(['a#1', 'a#1', 'b-c#22', 'x', 3, 'a#b'])).toEqual(['a#1', 'b-c#22'])
  expect(parseDismissed(undefined)).toEqual([])
  expect(parseDismissed({ 'a#1': true })).toEqual([])
})

test('a dismissal is pruned only when its repository was read in full and lost it', () => {
  const listed = new Map([['a', [1, 2]]])
  expect(pruneDismissed(['a#1', 'a#3', 'b#4'], listed)).toEqual(['a#1', 'b#4'])
  expect(pruneDismissed([], listed)).toEqual([])
})

const REPOS = ['Overmind-Mod', 'Laundry-Bot']
const ADD = 'gh api repos/merph518/Laundry-Bot/issues/12/labels -f "labels[]=Manual Review Needed"'
const READ_BACK = '[{"name":"enhancement"},{"name":"Manual Review Needed"}]'

const ON = 'repos/merph518/Overmind-Mod/issues/5'
const fires = (command: string, output = '') => labelTrigger(command, output, REPOS)

test('adding the review label through gh api counts when the answer lists the label', () => {
  expect(fires(ADD, READ_BACK)).toBe(true)
  expect(fires(`cd /r && ${ADD} && gh pr view 12 --json labels`, READ_BACK)).toBe(true)
  expect(fires(ADD.replace('repos/', '/repos/'), READ_BACK)).toBe(true)
  expect(fires(`gh api -X POST ${ON}/labels --input l.json`, READ_BACK)).toBe(true)
  expect(fires(ADD, '[{"name":"enhancement"}]')).toBe(false)
})

test("gh's {owner} and {repo} placeholders count as a watched repository", () => {
  const own = 'repos/{owner}/{repo}/issues/7/labels'
  const add = `gh api -X POST ${own} -f "labels[]=Manual Review Needed" --jq ".[].name"`
  expect(fires(add, 'Manual Review Needed')).toBe(true)
  expect(fires(`gh api -X DELETE ${own}/Manual%20Review%20Needed`)).toBe(true)
  const other = 'repos/{owner}/Unwatched/issues/7/labels'
  expect(fires(`gh api ${other} -f "labels[]=x"`, READ_BACK)).toBe(false)
})

test('removing the review label, or every label, through gh api counts; a replace counts', () => {
  expect(fires(`gh api -X DELETE ${ON}/labels/Manual%20Review%20Needed`)).toBe(true)
  expect(fires(`gh api --method DELETE "${ON}/labels/Manual Review Needed"`)).toBe(true)
  expect(fires(`gh api -X DELETE ${ON}/labels`)).toBe(true)
  expect(fires(`gh api -X PUT ${ON}/labels -f "labels[]=x"`)).toBe(true)
  expect(fires(`gh api -X DELETE ${ON}/labels/In%20Progress`)).toBe(false)
})

test('other gh api calls, other repositories and other owners do not count', () => {
  expect(fires(`gh api ${ON}/labels`, READ_BACK)).toBe(false)
  expect(fires(`gh api ${ON}/labels -X GET -f per_page=100`, READ_BACK)).toBe(false)
  expect(fires(`gh api ${ON}/comments -f body=x`, READ_BACK)).toBe(false)
  expect(labelTrigger(ADD.replace('Laundry-Bot', 'Unwatched'), READ_BACK, REPOS)).toBe(false)
  expect(labelTrigger(ADD.replace('merph518', 'someone'), READ_BACK, REPOS)).toBe(false)
  expect(labelTrigger(ADD.replace('gh api', 'echo'), READ_BACK, REPOS)).toBe(false)
  expect(labelTrigger(undefined, READ_BACK, REPOS)).toBe(false)
})
