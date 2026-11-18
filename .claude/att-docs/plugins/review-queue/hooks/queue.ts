// The parts of the review queue that need no engine: the gh commands, reading
// their output, the CI state, the failure line, ages and switches.json.

import type { CiState, PullRequest, QueueFailure, QueueSwitches } from '../types'

export const OWNER = 'merph518'
// This repository: always watched, and where the list of the others lives.
export const HOME_REPO = 'Overmind-Mod'
export const LABEL = 'Manual Review Needed'
// The most pull requests read from one repository.
export const LIST_LIMIT = 50
// The most rows the expanded band shows; the rest are counted.
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
