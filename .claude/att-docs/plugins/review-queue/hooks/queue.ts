// The parts of the review queue that need no engine: the gh commands, reading
// their output, the CI state, the failure line, ages, switches.json, the catchup
// events files, the shared dismissals and the label commands that call a refresh.

import type { CiState, PullRequest, QueueFailure, QueueSwitches } from '../types'

export const OWNER = 'merph518'
// This repository: always watched, and where the list of the others lives.
export const HOME_REPO = 'Overmind-Mod'
export const LABEL = 'Manual Review Needed'
// The most pull requests read from one repository.
export const LIST_LIMIT = 50
// The most rows the band shows; the rest are counted.
export const MAX_ROWS = 8

export const MINUTE_MS = 60_000
export const HOUR_MS = 60 * MINUTE_MS
export const DAY_MS = 24 * HOUR_MS

type Rollup = { conclusion?: unknown; status?: unknown; state?: unknown }

const FAILED = new Set(['FAILURE', 'TIMED_OUT', 'CANCELLED', 'ACTION_REQUIRED', 'STARTUP_FAILURE', 'ERROR'])
const GOING = new Set(['PENDING', 'EXPECTED', 'QUEUED', 'IN_PROGRESS', 'WAITING', 'REQUESTED'])

function upper(value: unknown): string {
  return typeof value === 'string' ? value.toUpperCase() : ''
}

// The CI state of a status check rollup. A check run carries `status` and, once
// completed, `conclusion`; a commit status carries `state`. Neutral and skipped
// count as passing.
export function ciState(rollup: unknown): CiState {
  if (!Array.isArray(rollup) || rollup.length === 0) return 'none'
  let isRunning = false
  for (const item of rollup as Rollup[]) {
    if (item === null || typeof item !== 'object') continue
    const conclusion = upper(item.conclusion)
    const state = upper(item.state)
    const status = upper(item.status)
    if (FAILED.has(conclusion) || state === 'FAILURE' || state === 'ERROR') return 'failing'
    if (GOING.has(state) || (status !== '' && status !== 'COMPLETED')) isRunning = true
  }
  return isRunning ? 'running' : 'passing'
}

// The gh command that lists one repository's open pull requests carrying the label.
export function listArgv(repo: string): string[] {
  return [
    'gh', 'pr', 'list',
    '--repo', `${OWNER}/${repo}`,
    '--label', LABEL,
    '--state', 'open',
    '--limit', String(LIST_LIMIT),
    '--json', 'number,title,url,createdAt,isDraft,statusCheckRollup',
  ]
}

// The gh command that reads the list of repositories that pin this one.
export function consumersArgv(): string[] {
  return [
    'gh', 'api', `repos/${OWNER}/${HOME_REPO}/contents/.github/consumers.json`,
    '-H', 'Accept: application/vnd.github.raw+json',
  ]
}

// The pull requests in `gh pr list` output, or null when it is not a JSON list.
export function parsePrList(stdout: string, repo: string): PullRequest[] | null {
  let value: unknown
  try {
    value = JSON.parse(stdout)
  } catch {
    return null
  }
  if (!Array.isArray(value)) return null
  const prs: PullRequest[] = []
  for (const item of value) {
    if (item === null || typeof item !== 'object') continue
    const record = item as Record<string, unknown>
    const { number, title, url } = record
    if (typeof number !== 'number' || typeof url !== 'string') continue
    const createdAt = typeof record['createdAt'] === 'string' ? Date.parse(record['createdAt']) : Number.NaN
    prs.push({
      repo,
      number,
      title: typeof title === 'string' ? title : '',
      url,
      createdAt: Number.isNaN(createdAt) ? 0 : createdAt,
      isDraft: record['isDraft'] === true,
      ci: ciState(record['statusCheckRollup']),
    })
  }
  return prs
}

const NAME = /^[A-Za-z0-9._-]+$/

// The repository names in consumers.json, `{ "consumers": [...] }`, or null when
// the text is not that shape.
export function parseRepos(text: string): string[] | null {
  let value: unknown
  try {
    value = JSON.parse(text)
  } catch {
    return null
  }
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return null
  const list = (value as Record<string, unknown>)['consumers']
  if (!Array.isArray(list)) return null
  return list.filter((one): one is string => typeof one === 'string' && NAME.test(one))
}

// The repositories to read: this one first, then the others, each once.
export function watched(consumers: readonly string[]): string[] {
  return [...new Set([HOME_REPO, ...consumers])]
}

// Why a gh call that ran and exited non-zero failed. gh exits 4 when it is not
// signed in.
export function classifyFailure(exitCode: number, stderr: string): QueueFailure {
  if (exitCode === 4 || /gh auth login|not logged in|authentication required/i.test(stderr)) return 'signed-out'
  if (/error connecting|could not resolve host|no such host|network is unreachable|dial tcp|i\/o timeout/i.test(stderr)) {
    return 'offline'
  }
  return 'failed'
}

// The one line the band shows when no repository could be read.
export function failureLine(failure: QueueFailure): string {
  switch (failure) {
    case 'missing':
      return 'Review queue: gh is not installed'
    case 'signed-out':
      return 'Review queue: gh is signed out (gh auth login)'
    case 'offline':
      return 'Review queue: GitHub cannot be reached'
    case 'failed':
      return 'Review queue: gh could not read the pull requests'
  }
}

// How long ago, in whole minutes, hours or days.
export function formatAge(ms: number): string {
  const age = Math.max(0, ms)
  if (age < HOUR_MS) return `${Math.floor(age / MINUTE_MS)}m`
  if (age < DAY_MS) return `${Math.floor(age / HOUR_MS)}h`
  return `${Math.floor(age / DAY_MS)}d`
}

export function ciLabel(ci: CiState): string {
  return ci === 'none' ? 'no checks' : ci
}

export function sortOldestFirst(prs: readonly PullRequest[]): PullRequest[] {
  return [...prs].sort((a, b) => a.createdAt - b.createdAt || a.repo.localeCompare(b.repo) || a.number - b.number)
}

// True when a shell command runs `gh pr`, which may have added or removed the label.
export function isGhPr(command: unknown): boolean {
  return typeof command === 'string' && /(^|[\s;&|(`])gh\s+pr\b/.test(command)
}

const GH_PR_CHANGE = /(^|[\s;&|(`])gh\s+pr\s+(create|edit|merge|close|reopen|ready)\b/

// True when a `gh pr` command can change which pull requests carry the label: one
// that creates, edits, merges, closes, reopens or readies a pull request. Reads such
// as `gh pr view` or `gh pr checks` cannot.
export function isGhPrChange(command: unknown): boolean {
  return typeof command === 'string' && GH_PR_CHANGE.test(command)
}

// The Claude Code configuration folder: CLAUDE_CONFIG_DIR when set, else ~/.claude.
export function configDir(home: string | undefined, configured: string | undefined): string {
  if (configured !== undefined && configured.trim() !== '') return configured.trim().replace(/\/+$/, '')
  return `${(home ?? '').replace(/\/+$/, '')}/.claude`
}

// What switches.json says: `"review-queue": false` turns the plugin off and
// `"review-queue:hidden": true` hides the band. A missing file, or one that is not
// a JSON object, leaves it on.
export function parseSwitches(text: string | undefined): QueueSwitches {
  const on: QueueSwitches = { isOff: false, isHidden: false }
  if (text === undefined) return on
  let value: unknown
  try {
    value = JSON.parse(text)
  } catch {
    return on
  }
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return on
  const record = value as Record<string, unknown>
  return { isOff: record['review-queue'] === false, isHidden: record['review-queue:hidden'] === true }
}

// A row's key, `repo#number`, as the shared dismiss list keeps it.
export function prKey(repo: string, number: number): string {
  return `${repo}#${number}`
}

// How much earlier than a listing a close may be and still drop the row. GitHub's
// search lists a merged pull request for a few seconds after the merge, and the
// event times are whole seconds.
export const CLOSE_SLACK_MS = 60_000
// The files catchup.py writes a repository's events to: the current one, and the
// one it renames it to past a megabyte.
export const EVENT_FILES = ['events.jsonl', 'events.jsonl.old'] as const

// The folder where `catchup.py wait` keeps a repository's events.
export function catchupFolder(home: string | undefined, repo: string): string {
  return `${(home ?? '').replace(/\/+$/, '')}/.cache/catchup/${OWNER}__${repo}`
}

type Entry = { name: string; kind: string; size: number; mtimeMs: number }

// A file's size and change time from a folder listing, or null when it is not there.
export function fileSignature(entries: readonly Entry[], name: string): string | null {
  const entry = entries.find(one => one.name === name && one.kind === 'file')
  return entry === undefined ? null : `${entry.size}:${entry.mtimeMs}`
}

const PR_RUN = /^pr:(\d+)$/

// The pull request closes in an events file: each number with the latest time it
// closed. A line's time is the later of when it was written (`at`, this machine's
// clock) and GitHub's `closed_at`. Issue closes, workflow runs and lines that are
// not JSON, such as a half-written last line, are skipped.
export function parseCloses(text: string): Map<number, number> {
  const closes = new Map<number, number>()
  for (const line of text.split('\n')) {
    if (!line.includes('"pr"')) continue
    let value: unknown
    try {
      value = JSON.parse(line)
    } catch {
      continue
    }
    if (value === null || typeof value !== 'object' || Array.isArray(value)) continue
    const record = value as Record<string, unknown>
    const { event, action, run } = record
    if (event !== 'pr' || action !== 'closed' || typeof run !== 'string') continue
    const match = PR_RUN.exec(run)
    if (match === null) continue
    const times = [record['at'], record['closed_at']]
      .map(time => (typeof time === 'string' ? Date.parse(time) : Number.NaN))
      .filter(time => !Number.isNaN(time))
    if (times.length === 0) continue
    const number = Number(match[1])
    closes.set(number, Math.max(closes.get(number) ?? 0, ...times))
  }
  return closes
}

// The rows left once each pull request that closed after it was listed is taken
// out. `closes` is keyed by `repo#number`. A close well before the listing belongs
// to an earlier life of a pull request that was opened again.
export function dropClosed(
  prs: readonly PullRequest[],
  closes: ReadonlyMap<string, number>,
  listedAt: number,
): PullRequest[] {
  return prs.filter(pr => {
    const closed = closes.get(prKey(pr.repo, pr.number))
    return closed === undefined || closed <= listedAt - CLOSE_SLACK_MS
  })
}

const DISMISSED_KEY = /^[A-Za-z0-9._-]+#\d+$/

// The dismissed pull requests kept in the store, each `repo#number` once.
export function parseDismissed(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  const isKey = (one: unknown): one is string => typeof one === 'string' && DISMISSED_KEY.test(one)
  const keys = value.filter(isKey)
  return [...new Set(keys)]
}

// The dismissals left after a refresh. `listed` holds, for each repository read in
// full, the numbers it listed. A dismissal is dropped when its repository was read
// in full and no longer lists it; a repository not read, or one that hit the list
// limit, keeps its dismissals.
export function pruneDismissed(
  dismissed: readonly string[],
  listed: ReadonlyMap<string, readonly number[]>,
): string[] {
  return dismissed.filter(key => {
    const hash = key.lastIndexOf('#')
    const numbers = listed.get(key.slice(0, hash))
    return numbers === undefined || numbers.includes(Number(key.slice(hash + 1)))
  })
}

const GH_API_COMMAND = /(^|[\s;&|(`])gh\s+api\b/
// `repos/<owner>/<repo>/issues/<n>/labels`, with gh's `{owner}` and `{repo}`
// placeholders allowed, and the rest of the path after `labels`.
const NAME_PART = '[A-Za-z0-9._-]+'
const LABELS_ENDPOINT = new RegExp(
  `/?repos/(${NAME_PART}|\\{owner\\})/(${NAME_PART}|\\{repo\\})/issues/\\d+/labels\\b(/\\S*)?`,
  'g',
)
const METHOD_FLAG = /(?:-X\s*|--method[\s=]+)['"]?([A-Za-z]+)/
const FIELD_FLAG = /\s(?:-f|-F|--field|--raw-field|--input)\b/
const ENCODED_LABEL = LABEL.replace(/ /g, '%20')

// True when a labels endpoint names a watched repository. gh fills `{owner}` and
// `{repo}` from the folder the command runs in, which a hook does not see, so a
// placeholder counts as watched.
function isWatchedEndpoint(match: RegExpMatchArray, repos: readonly string[]): boolean {
  const [, owner = '', repo = ''] = match
  return (owner === OWNER || owner === '{owner}') && (repo === '{repo}' || repos.includes(repo))
}

// True when a shell command changed the review label on a watched repository's
// pull request through `gh api .../issues/<n>/labels`: an add whose answer lists
// the label, a replace, or a delete of the label or of every label. A read of the
// labels, another endpoint, or another repository is not.
export function labelTrigger(command: unknown, output: string, repos: readonly string[]): boolean {
  if (typeof command !== 'string' || !GH_API_COMMAND.test(command)) return false
  const endpoints = [...command.matchAll(LABELS_ENDPOINT)]
    .filter(match => isWatchedEndpoint(match, repos))
  if (endpoints.length === 0) return false
  const method = (METHOD_FLAG.exec(command)?.[1] ?? '').toUpperCase()
  if (method === 'GET') return false
  if (method === 'PUT') return true
  if (method === 'DELETE') {
    const isEveryLabel = endpoints.some(match => match[3] === undefined || match[3] === '/')
    return isEveryLabel || command.includes(ENCODED_LABEL) || command.includes(LABEL)
  }
  if (method === 'POST' || FIELD_FLAG.test(command)) return output.includes(LABEL)
  return false
}
