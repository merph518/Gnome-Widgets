// The parts of runner-health that need no engine: reading what systemctl, df and the
// GitHub API print, and deciding from that what is wrong and how to fix it.

import type { ApiRunner, DiskFree, Health, HealthSwitches, LocalUnit, Problem, QueuedJob, Settings } from '../types'

export const MINUTE_MS = 60_000
// How often this machine's runner services and disks are checked: one refresh.
export const TICK_MS = 15_000
// How often GitHub is asked, shared by every open chat.
export const API_MS = 2 * MINUTE_MS
// How long GitHub is left alone after a call that failed.
export const API_RETRY_MS = 10 * MINUTE_MS
// How long after a runner service starts GitHub may still show it offline before
// that counts as a problem.
export const GRACE_MS = 3 * MINUTE_MS
const GIB = 1024 ** 3

export const DEFAULT_SETTINGS: Settings = {
  org: 'merph518',
  repos: ['merph518/Overmind-Mod'],
  label: 'overmind',
  queuedMinutes: 10,
  freeGiB: 5,
}

// The JSON object in `text`, or null when it is not one.
function asObject(text: string | undefined): Record<string, unknown> | null {
  if (text === undefined) return null
  let value: unknown
  try {
    value = JSON.parse(text.replace(/^﻿/, ''))
  } catch {
    return null
  }
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function asList(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) return []
  return value.filter((one): one is Record<string, unknown> => typeof one === 'object' && one !== null)
}

// The Claude Code configuration folder: CLAUDE_CONFIG_DIR when set, else ~/.claude.
export function configDir(home: string | undefined, configured: string | undefined): string {
  if (configured !== undefined && configured.trim() !== '') return configured.trim().replace(/\/+$/, '')
  return `${(home ?? '').replace(/\/+$/, '')}/.claude`
}

// What switches.json says: `"runner-health": false` stops the checks and
// `"runner-health:hidden": true` hides the band. A missing or unreadable file leaves it on.
export function parseSwitches(text: string | undefined): HealthSwitches {
  const record = asObject(text)
  if (record === null) return { isOff: false, isHidden: false }
  return { isOff: record['runner-health'] === false, isHidden: record['runner-health:hidden'] === true }
}

// runner-health.json: each value that has the right type replaces its default.
export function parseSettings(text: string | undefined): Settings {
  const record = asObject(text) ?? {}
  const word = (value: unknown, fallback: string) =>
    typeof value === 'string' && value.trim() !== '' ? value.trim() : fallback
  const count = (value: unknown, fallback: number) =>
    typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : fallback
  const repos = Array.isArray(record['repos'])
    ? record['repos'].filter((one): one is string => typeof one === 'string' && /^[^/\s]+\/[^/\s]+$/.test(one))
    : DEFAULT_SETTINGS.repos
  return {
    org: word(record['org'], DEFAULT_SETTINGS.org),
    repos,
    label: word(record['label'], DEFAULT_SETTINGS.label),
    queuedMinutes: count(record['queuedMinutes'], DEFAULT_SETTINGS.queuedMinutes),
    freeGiB: count(record['freeGiB'], DEFAULT_SETTINGS.freeGiB),
  }
}

const UNIT = /^(?:\S\s+)?(actions\.runner\.([^.\s]+)\.(\S+)\.service)\s+\S+\s+(\S+)/

// The runner services `systemctl list-units --all --plain --no-legend` prints.
export function parseUnits(stdout: string): LocalUnit[] {
  const units: LocalUnit[] = []
  for (const line of stdout.split('\n')) {
    const match = UNIT.exec(line.trim())
    if (match === null) continue
    units.push({ unit: match[1] ?? '', runner: match[3] ?? '', isActive: match[4] === 'active' })
  }
  return units
}

// The runner's name and work folder from its `.runner` file, which starts with a
// byte order mark.
export function parseRunnerFile(text: string | undefined): { name: string | null; workFolder: string } {
  const record = asObject(text)
  const name = record?.['agentName']
  const work = record?.['workFolder']
  return {
    name: typeof name === 'string' && name !== '' ? name : null,
    workFolder: typeof work === 'string' && work !== '' ? work : '_work',
  }
}

// `df -P -k <path>...` prints one row per path, in order. Paths on one filesystem
// share a row.
export function parseDf(stdout: string, paths: readonly string[]): DiskFree[] {
  const rows = stdout
    .split('\n')
    .slice(1)
    .map(line => line.trim().split(/\s+/))
    .filter(cells => cells.length >= 6)
  const byMount = new Map<string, DiskFree>()
  rows.forEach((cells, index) => {
    const free = Number(cells[3])
    const mount = cells.slice(5).join(' ')
    if (!Number.isFinite(free)) return
    const path = paths[index] ?? mount
    const found = byMount.get(mount)
    if (found === undefined) byMount.set(mount, { mount, paths: [path], freeBytes: free * 1024 })
    else if (!found.paths.includes(path)) found.paths.push(path)
  })
  return [...byMount.values()]
}

const hasLabel = (record: Record<string, unknown>, label: string) =>
  asList(record['labels']).some(one => one['name'] === label) ||
  (Array.isArray(record['labels']) && record['labels'].includes(label))

// The organization's runners that carry `label`, or null when the answer is not the
// runners list.
export function parseRunners(json: string, label: string): ApiRunner[] | null {
  const record = asObject(json)
  if (record === null || !Array.isArray(record['runners'])) return null
  return asList(record['runners'])
    .filter(runner => hasLabel(runner, label))
    .map(runner => ({
      name: String(runner['name'] ?? ''),
      isOnline: runner['status'] === 'online',
      isBusy: runner['busy'] === true,
    }))
}

// The ids of the workflow runs in a runs list, or null when the answer is not one.
export function parseRunIds(json: string): number[] | null {
  const record = asObject(json)
  if (record === null || !Array.isArray(record['workflow_runs'])) return null
  return asList(record['workflow_runs'])
    .map(run => run['id'])
    .filter((id): id is number => typeof id === 'number')
}

// The jobs of one run still queued for a runner with `label`, or null when the answer
// is not a jobs list.
export function parseJobs(json: string, repo: string, label: string): QueuedJob[] | null {
  const record = asObject(json)
  if (record === null || !Array.isArray(record['jobs'])) return null
  return asList(record['jobs'])
    .filter(job => job['status'] === 'queued' && hasLabel(job, label))
    .map(job => ({
      repo,
      workflow: String(job['workflow_name'] ?? ''),
      name: String(job['name'] ?? ''),
      createdAt: Date.parse(String(job['created_at'] ?? '')),
    }))
    .filter(job => Number.isFinite(job.createdAt))
}

// Why a `gh` call failed, in a few words.
export function ghFailure(exitCode: number | null, stderr: string): string {
  if (exitCode === null) return 'the gh command did not run (not installed, or no answer in 15 seconds)'
  if (exitCode === 4 || /not logged in|gh auth login/i.test(stderr)) return 'gh is not signed in: run gh auth login'
  if (/rate limit/i.test(stderr)) return 'GitHub API rate limit reached'
  if (/admin:org|HTTP 403|Resource not accessible|must have admin/i.test(stderr)) {
    return 'gh needs the admin:org scope: run gh auth refresh -s admin:org'
  }
  // GitHub answers 404 for an organization endpoint the token may not read.
  if (/HTTP 404/i.test(stderr)) return 'GitHub did not find the organization, or gh lacks the admin:org scope'
  if (/could not resolve|connection|timeout|network/i.test(stderr)) return 'GitHub could not be reached'
  return `gh exited with ${exitCode}`
}

function minutes(ms: number): string {
  const count = Math.floor(ms / MINUTE_MS)
  return `${count} min`
}

function gib(bytes: number): string {
  return `${(bytes / GIB).toFixed(1)} GiB`
}

export type AssessInput = {
  // This machine's runner services; empty when there are none or they could not be read.
  units: LocalUnit[]
  // When each local runner's service was first seen active, by runner name.
  activeSince: Record<string, number>
  runners: ApiRunner[] | null
  jobs: QueuedJob[] | null
  disks: DiskFree[]
  // Why GitHub could not be read, or why this machine's services could not be.
  apiNote: string | null
  localNote: string | null
  now: number
  settings: Settings
}

// Decides what is wrong. Healthy is no problems.
export function assess(input: AssessInput): Health {
  const { units, runners, jobs, disks, now, settings } = input
  const problems: Problem[] = []

  // Without GitHub's list, every runner service here counts; with it, only the
  // ones that carry the label.
  const watched = runners === null ? null : new Set(runners.map(runner => runner.name))
  const local = units.filter(unit => watched === null || watched.has(unit.runner))
  const stopped = local.filter(unit => !unit.isActive)
  if (stopped.length === 1) {
    const unit = stopped[0] as LocalUnit
    problems.push({ kind: 'offline', text: `${unit.runner} is stopped`, fix: `sudo systemctl start ${unit.unit}` })
  } else if (stopped.length > 1) {
    problems.push({
      kind: 'offline',
      text: `${stopped.map(unit => unit.runner).join(', ')} are stopped`,
      fix: `sudo systemctl start ${stopped.map(unit => unit.unit).join(' ')}`,
    })
  }

  for (const runner of runners ?? []) {
    if (runner.isOnline) continue
    const unit = local.find(one => one.runner === runner.name)
    if (unit === undefined) {
      problems.push({ kind: 'offline', text: `${runner.name} is offline (another machine)`, fix: null })
      continue
    }
    // A stopped service is named above. A running one GitHub has not caught up
    // with yet is given the grace period.
    if (!unit.isActive) continue
    const since = input.activeSince[unit.runner] ?? now
    if (now - since < GRACE_MS) continue
    problems.push({
      kind: 'offline',
      text: `${runner.name} runs here but GitHub shows it offline`,
      fix: `sudo systemctl restart ${unit.unit}`,
    })
  }

  const waiting = (jobs ?? [])
    .filter(job => now - job.createdAt >= settings.queuedMinutes * MINUTE_MS)
    .sort((a, b) => a.createdAt - b.createdAt)
  const oldest = waiting[0]
  if (oldest !== undefined) {
    const label = oldest.workflow === '' ? oldest.name : `${oldest.workflow} / ${oldest.name}`
    const text =
      waiting.length === 1
        ? `${oldest.repo} job "${label}" waiting ${minutes(now - oldest.createdAt)} for an ${settings.label} runner`
        : `${waiting.length} jobs waiting for an ${settings.label} runner, oldest ${minutes(now - oldest.createdAt)}`
    problems.push({ kind: 'queued', text, fix: null })
  }

  for (const disk of disks) {
    if (disk.freeBytes >= settings.freeGiB * GIB) continue
    problems.push({ kind: 'disk', text: `only ${gib(disk.freeBytes)} free on ${disk.mount}`, fix: null })
  }

  if (units.length === 0 && runners === null) {
    const why = input.apiNote ?? input.localNote ?? 'nothing to read'
    return { problems: [{ kind: 'unreadable', text: `cannot read the runners: ${why}`, fix: null }], note: null }
  }
  return { problems, note: runners === null ? input.apiNote : null }
}

// The band's one line, or null when nothing is wrong. Problems that do not fit in
// `columns` are counted at the end.
export function bandText(health: Health, columns: number): string | null {
  if (health.problems.length === 0) return null
  const parts = health.problems.map(problem => (problem.fix === null ? problem.text : `${problem.text}: ${problem.fix}`))
  const head = 'Runner health: '
  const tail = health.note === null ? '' : ` (GitHub not checked: ${health.note})`
  let line = head + (parts[0] ?? '')
  let shown = 1
  for (const part of parts.slice(1)) {
    const left = parts.length - shown - 1
    const more = left > 0 ? ` · +${left} more` : ''
    if ((line + ' · ' + part + more + tail).length > columns) break
    line += ` · ${part}`
    shown += 1
  }
  if (shown < parts.length) line += ` · +${parts.length - shown} more`
  return line + tail
}

export function sameHealth(a: Health, b: Health): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}
