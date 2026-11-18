// The parts of pin drift that need no engine: the gh commands, reading their output,
// comparing versions, the band text and switches.json.

import type {
  CiState,
  ConsumerPin,
  Drift,
  DriftFailure,
  DriftSwitches,
  Pending,
  PinPr,
} from '../types'

// A tag the pin accepts: vMAJOR.MINOR.PATCH and nothing else.
const TAG = /^v\d+\.\d+\.\d+$/

// The first repo= and tag= lines of an .claude/att-docs.lock, read as the pin script
// reads them: carriage returns dropped and nothing else, so a tag with a trailing
// space is not a tag the pin accepts. A leading byte order mark is dropped as well.
export function parseLock(text: string): { repo: string | null; tag: string | null } {
  let repo: string | null = null
  let tag: string | null = null
  for (const raw of text.replace(/^﻿/, '').split('\n')) {
    const line = raw.replace(/\r/g, '')
    if (repo === null && line.startsWith('repo=')) repo = line.slice(5)
    else if (tag === null && line.startsWith('tag=')) tag = line.slice(4)
  }
  return { repo, tag }
}

type LockPin = { pinned: string | null; lockRepo: string | null; note: string | null }

// The pinned tag a lock names, or a note saying why there is none.
export function lockPin(text: string): LockPin {
  const { repo, tag } = parseLock(text)
  if (tag === null) return { pinned: null, lockRepo: repo, note: 'the lock has no tag= line' }
  if (!TAG.test(tag)) {
    return { pinned: null, lockRepo: repo, note: `tag=${tag} is not vMAJOR.MINOR.PATCH` }
  }
  return { pinned: tag, lockRepo: repo, note: null }
}

// A version's three numbers, from `v0.32.3` or `0.32.3`; null for anything else.
export function parseVersion(text: string): [number, number, number] | null {
  const found = /^v?(\d+)\.(\d+)\.(\d+)$/.exec(text.trim())
  if (found === null) return null
  return [Number(found[1]), Number(found[2]), Number(found[3])]
}

// Below zero when a is older than b, zero when equal, above zero when newer. A
// version that does not parse counts as older than any that does.
export function compareVersions(a: string, b: string): number {
  const left = parseVersion(a)
  const right = parseVersion(b)
  if (left === null || right === null) {
    return (left === null ? 0 : 1) - (right === null ? 0 : 1)
  }
  for (let index = 0; index < 3; index += 1) {
    const diff = (left[index] ?? 0) - (right[index] ?? 0)
    if (diff !== 0) return diff
  }
  return 0
}

// A tag without its leading v, as the band shows it.
export function shortVersion(tag: string): string {
  return tag.replace(/^v/, '')
}

// The highest vMAJOR.MINOR.PATCH tag in a list of `refs/tags/...` lines, or null.
export function parseTagRefs(stdout: string): string | null {
  let latest: string | null = null
  for (const line of stdout.split(/\r?\n/)) {
    const tag = line.trim().replace(/^refs\/tags\//, '')
    if (!TAG.test(tag)) continue
    if (latest === null || compareVersions(tag, latest) > 0) latest = tag
  }
  return latest
}

// The owner and name a GitHub remote URL names, from the https, ssh, scp-like and
// git forms; null for another host or anything else.
export function parseRemote(url: string | null): { owner: string; name: string } | null {
  if (url === null) return null
  const text = url.trim()
  const found = URL_REMOTE.exec(text) ?? SCP_REMOTE.exec(text)
  if (found === null) return null
  return { owner: found[1] ?? '', name: found[2] ?? '' }
}

const URL_REMOTE =
  /^(?:https?|ssh|git):\/\/(?:[^@/]+@)?github\.com(?::\d+)?\/([^/]+)\/([^/]+?)(?:\.git)?\/?$/i
const SCP_REMOTE = /^[^@/]+@github\.com:([^/]+)\/([^/]+?)(?:\.git)?\/?$/i

// The names this repository has had, as owner/name in lower case. GitHub redirects
// the older ones, so a clone made before a rename still names one of them.
export const HOME_NAMES = [
  'merph518/overmind-mod',
  'merph518/overmind',
  'mfagerstrom/overmind-mod',
  'mfagerstrom/overmind',
]

// True when the remote is this repository under any of its names.
export function isHomeRepo(url: string | null): boolean {
  const remote = parseRemote(url)
  return remote !== null && HOME_NAMES.includes(`${remote.owner}/${remote.name}`.toLowerCase())
}

// The label release-please puts on its open release pull request.
export const PENDING_LABEL = 'autorelease: pending'
// A release pull request title, `chore: release 0.32.4`, with an optional scope or v.
const RELEASE_TITLE = /^chore(?:\([^)]*\))?: release v?(\d+\.\d+\.\d+)$/

function parseJsonList(text: string): unknown[] | null {
  let value: unknown
  try {
    value = JSON.parse(text)
  } catch {
    return null
  }
  return Array.isArray(value) ? value : null
}

// The open release pull request with the highest version above the latest tag, or
// null. One at or below the latest tag was already released and is not pending.
export function parseReleasePrs(json: string, latest: string | null): Pending | null {
  const list = parseJsonList(json)
  if (list === null) return null
  let best: Pending | null = null
  for (const item of list) {
    if (item === null || typeof item !== 'object') continue
    const record = item as Record<string, unknown>
    const { number, title, state } = record
    const url = record['html_url']
    if (typeof number !== 'number' || typeof title !== 'string' || typeof url !== 'string') {
      continue
    }
    if (state !== undefined && state !== 'open') continue
    const labels = Array.isArray(record['labels']) ? (record['labels'] as unknown[]) : []
    if (!labels.some(isPendingLabel)) continue
    const version = RELEASE_TITLE.exec(title.trim())?.[1]
    if (version === undefined) continue
    if (latest !== null && compareVersions(version, latest) <= 0) continue
    if (best === null || compareVersions(version, best.version) > 0) {
      best = { version, number, url, title: title.trim() }
    }
  }
  return best
}

function isPendingLabel(label: unknown): boolean {
  if (label === null || typeof label !== 'object') return false
  return (label as Record<string, unknown>)['name'] === PENDING_LABEL
}

type Rollup = { conclusion?: unknown; status?: unknown; state?: unknown }

const FAILED = new Set([
  'FAILURE',
  'TIMED_OUT',
  'CANCELLED',
  'ACTION_REQUIRED',
  'STARTUP_FAILURE',
  'ERROR',
])
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

// The branch a pin pull request comes from: a new tag, or the same tag moved to a
// renamed repository.
const PIN_BRANCH = /^overmind\/(?:pin|move)-(v\d+\.\d+\.\d+)$/

// The pin pull requests in `gh pr list` output, or null when it is not a JSON list.
export function parsePinPrs(stdout: string): PinPr[] | null {
  const list = parseJsonList(stdout)
  if (list === null) return null
  const prs: PinPr[] = []
  for (const item of list) {
    if (item === null || typeof item !== 'object') continue
    const record = item as Record<string, unknown>
    const { number, url, headRefName } = record
    if (typeof number !== 'number' || typeof url !== 'string' || typeof headRefName !== 'string') {
      continue
    }
    const tag = PIN_BRANCH.exec(headRefName)?.[1]
    if (tag === undefined) continue
    const ci = ciState(record['statusCheckRollup'])
    prs.push({ number, url, branch: headRefName, tag, ci })
  }
  return prs
}

// True when a pull request from an `overmind/move-` branch: it keeps the tag and moves
// the lock to the repository's current name.
export function isMovePr(pr: PinPr): boolean {
  return pr.branch.startsWith('overmind/move-')
}

// The pin pull request for the highest tag, or null when there is none. With the
// consumer's current pin known, a pin pull request must move it to a newer tag and a
// move pull request to the same tag or a newer one; older ones are stale.
export function newestPinPr(prs: readonly PinPr[], pinned: string | null): PinPr | null {
  let best: PinPr | null = null
  for (const pr of prs) {
    if (pinned !== null) {
      const step = compareVersions(pr.tag, pinned)
      if (step < 0 || (step === 0 && !isMovePr(pr))) continue
    }
    const order = best === null ? 1 : compareVersions(pr.tag, best.tag)
    if (best === null || order > 0 || (order === 0 && pr.number > best.number)) best = pr
  }
  return best
}

// True when the consumer's lock reads and pins a tag below the latest one.
export function isBehind(consumer: ConsumerPin, latest: string): boolean {
  return consumer.pinned !== null && compareVersions(consumer.pinned, latest) < 0
}

// True when the consumer's lock names this repository by an older name, so a move pull
// request may be open for it.
export function namesOldRepo(consumer: ConsumerPin): boolean {
  const named = consumer.lockRepo
  return named !== null && named.toLowerCase() !== `${OWNER}/${HOME_REPO}`.toLowerCase()
}

// True when there is nothing to show: the tags read, the release pull requests read
// and none is pending, and every consumer's lock reads and pins the latest tag or a
// newer one.
export function isQuiet(drift: Drift): boolean {
  if (drift.failure !== null || drift.latest === null || drift.pending !== null) return false
  if (drift.isReleaseUnknown === true) return false
  const latest = drift.latest
  return drift.consumers.every(
    consumer => consumer.pinned !== null && !isBehind(consumer, latest),
  )
}

// True when some read failed: a failure, release pull requests that could not be
// read, or a consumer's pull requests that could not be read. Such a result is kept
// for the shorter retry wait, not the full refresh wait.
export function hasGaps(drift: Drift): boolean {
  if (drift.failure !== null || drift.isReleaseUnknown === true) return true
  return drift.consumers.some(consumer => consumer.isPrUnknown === true)
}

// Room the band leaves after its text: a space, then the button, which draws as
// `[ Details ]`.
const BUTTON_COLUMNS = 12

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`
}

// The band's one line, or null when it is quiet. The pending release or that the
// release pull requests could not be read, the consumers behind the latest tag with
// their pins, and the locks that could not be read, each part joined by a middle dot.
// A line too wide for the columns drops names from the end of the list, then the list.
export function bandText(drift: Drift, columns: number): string | null {
  if (isQuiet(drift) || drift.latest === null) return null
  const latest = drift.latest
  const behind = drift.consumers.filter(consumer => isBehind(consumer, latest))
  const unreadable = drift.consumers.filter(consumer => consumer.pinned === null).length
  const release =
    drift.pending !== null
      ? `${drift.pending.version} pending`
      : drift.isReleaseUnknown === true
        ? 'release state unreadable'
        : null
  const locks = unreadable === 0 ? null : `${plural(unreadable, 'lock', 'locks')} unreadable`
  const count =
    behind.length === 0 ? null : `${plural(behind.length, 'consumer', 'consumers')} behind latest`
  const line = (names: string | null) => {
    const list = count === null || names === null ? count : `${count} (${names})`
    return [release, list, locks].filter((part): part is string => part !== null).join(' · ')
  }
  const named = behind.map(consumer => `${consumer.name} ${shortVersion(consumer.pinned ?? '')}`)
  const room = columns - BUTTON_COLUMNS
  for (let shown = named.length; shown >= 1; shown -= 1) {
    const rest = named.length - shown
    const names = [...named.slice(0, shown), ...(rest === 0 ? [] : [`+${rest} more`])].join(', ')
    const text = line(names)
    if (text.length <= room) return text
  }
  return line(null)
}

// Why a gh call failed. gh exits 4 when it is not signed in. A null exit code means
// the command never finished: it could not start, or it ran past its timeout.
export function classifyFailure(exitCode: number | null, stderr: string): DriftFailure {
  if (exitCode === null) return MISSING.test(stderr) ? 'missing' : 'failed'
  if (exitCode === 4 || SIGNED_OUT.test(stderr)) return 'signed-out'
  if (/rate limit/i.test(stderr)) return 'rate-limited'
  if (OFFLINE.test(stderr)) return 'offline'
  return 'failed'
}

const MISSING = /ENOENT|not found|no such file/i
const SIGNED_OUT = /gh auth login|not logged in|authentication required/i
const OFFLINE = new RegExp(
  [
    'error connecting',
    'could not resolve host',
    'no such host',
    'network is unreachable',
    'dial tcp',
    'i/o timeout',
  ].join('|'),
  'i',
)

// The one line the band shows in place of the drift. Only the tags read ends in
// `failed`; a later read stops the refresh only for the other four.
export function failureLine(failure: DriftFailure): string {
  switch (failure) {
    case 'missing':
      return 'Pin drift: gh is not installed'
    case 'signed-out':
      return 'Pin drift: gh is signed out (gh auth login)'
    case 'offline':
      return 'Pin drift: GitHub cannot be reached'
    case 'rate-limited':
      return 'Pin drift: GitHub API rate limit reached'
    case 'failed':
      return 'Pin drift: gh could not read the tags'
  }
}

// Why one consumer's lock could not be read. GitHub answers 404 both for a missing
// file and for a private repository the signed-in account cannot see.
export function lockNote(exitCode: number | null, stderr: string): string {
  if (/HTTP 404|Not Found/i.test(stderr)) {
    return 'no .claude/att-docs.lock on the default branch, or gh cannot read the repository'
  }
  switch (classifyFailure(exitCode, stderr)) {
    case 'missing':
      return 'gh is not installed'
    case 'signed-out':
      return 'gh is signed out'
    case 'offline':
      return 'GitHub cannot be reached'
    case 'rate-limited':
      return 'the GitHub API rate limit was reached'
    case 'failed':
      return 'gh could not read the lock'
  }
}

const NAME_PATTERN = /^[A-Za-z0-9._-]+$/

// The repository names in consumers.json, `{ "consumers": [...] }`, or null when the
// text is not that shape.
export function parseConsumers(text: string): string[] | null {
  let value: unknown
  try {
    value = JSON.parse(text)
  } catch {
    return null
  }
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return null
  const list = (value as Record<string, unknown>)['consumers']
  if (!Array.isArray(list)) return null
  return list.filter((one): one is string => typeof one === 'string' && NAME_PATTERN.test(one))
}

// The plugin's name: its key in switches.json, its pane and its slash command.
export const NAME = 'pin-drift'

// The Claude Code configuration folder: CLAUDE_CONFIG_DIR when set, else ~/.claude.
export function configDir(home: string | undefined, configured: string | undefined): string {
  if (configured !== undefined && configured.trim() !== '') {
    return configured.trim().replace(/\/+$/, '')
  }
  return `${(home ?? '').replace(/\/+$/, '')}/.claude`
}

// What switches.json says: `"pin-drift": false` turns the plugin off and
// `"pin-drift:hidden": true` hides the band. A missing file, or one that is not a
// JSON object, leaves it on.
export function parseSwitches(text: string | undefined): DriftSwitches {
  const on: DriftSwitches = { isOff: false, isHidden: false }
  if (text === undefined) return on
  let value: unknown
  try {
    value = JSON.parse(text)
  } catch {
    return on
  }
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return on
  const record = value as Record<string, unknown>
  return { isOff: record[NAME] === false, isHidden: record[`${NAME}:hidden`] === true }
}

export const OWNER = 'merph518'
// This repository, by the name the API reads it under whatever the local remote says.
export const HOME_REPO = 'Overmind-Mod'
// The branch release-please opens its release pull request from.
export const RELEASE_BRANCH = 'release-please--branches--main'
// The most open pull requests read from one consumer when looking for its pin pull
// request.
export const PIN_LIST_LIMIT = 50
const RAW = ['-H', 'Accept: application/vnd.github.raw+json']
const HOME = `repos/${OWNER}/${HOME_REPO}`

// The gh commands one refresh runs. All of them only read.
export const argv = {
  consumers: (): string[] => ['gh', 'api', `${HOME}/contents/.github/consumers.json`, ...RAW],
  // --jq runs once per page, so the output stays one ref per line across pages.
  tags: (): string[] => [
    'gh', 'api', '--paginate', `${HOME}/git/matching-refs/tags/v`, '--jq', '.[].ref',
  ],
  releasePrs: (): string[] => [
    'gh', 'api', `${HOME}/pulls?state=open&head=${OWNER}:${RELEASE_BRANCH}&per_page=10`,
  ],
  // No ref: the API reads the repository's default branch.
  lock: (name: string): string[] => [
    'gh', 'api', `repos/${OWNER}/${name}/contents/.claude/att-docs.lock`, ...RAW,
  ],
  pinPrs: (name: string): string[] => [
    'gh', 'pr', 'list',
    '--repo', `${OWNER}/${name}`,
    '--state', 'open',
    '--limit', String(PIN_LIST_LIMIT),
    '--json', 'number,url,headRefName,statusCheckRollup',
  ],
}

// What one gh call returned. exitCode is null when the command never finished, with
// the reason in stderr.
export type GhResult = { exitCode: number | null; stdout: string; stderr: string }
export type Gh = (args: string[]) => Promise<GhResult>

// The failure behind a gh call when it holds for every repository alike (gh missing,
// signed out, offline or rate limited), so the remaining reads are skipped; null for
// one that concerns only the repository read, such as a 404 or a server error.
function failureForAll(ran: GhResult): DriftFailure | null {
  if (/HTTP 404|Not Found/i.test(ran.stderr)) return null
  const failure = classifyFailure(ran.exitCode, ran.stderr)
  return failure === 'failed' ? null : failure
}

function unread(name: string, note: string | null): ConsumerPin {
  return { name, pinned: null, lockRepo: null, note, pr: null, isPrUnknown: false }
}

// Reads the release state and every consumer's pin: consumers.json (or the fallback
// list when it cannot be read), the tags, the open release pull request, each
// consumer's lock, and the pull requests of each consumer behind the latest tag or
// whose lock names an older name of this repository. A read that fails for one
// repository does not stop the others. When gh is missing, signed out, offline or
// rate limited, which holds for every repository alike, the remaining reads are
// skipped and the result carries that failure along with what was read before it.
export async function fetchDrift(
  gh: Gh,
  fallbackConsumers: () => Promise<string[]>,
  now: number,
): Promise<Drift> {
  const read = await gh(argv.consumers())
  const listed = read.exitCode === 0 ? parseConsumers(read.stdout) : null
  const names = listed ?? (await fallbackConsumers())

  const tags = await gh(argv.tags())
  const latest = tags.exitCode === 0 ? parseTagRefs(tags.stdout) : null
  if (latest === null) {
    const failure = tags.exitCode === 0 ? 'failed' : classifyFailure(tags.exitCode, tags.stderr)
    return {
      latest: null,
      pending: null,
      isReleaseUnknown: false,
      consumers: [],
      failure,
      at: now,
    }
  }

  let failure: DriftFailure | null = null
  let pending: Pending | null = null
  let isReleaseUnknown = false
  const releases = await gh(argv.releasePrs())
  if (releases.exitCode !== 0) {
    failure = failureForAll(releases)
    isReleaseUnknown = true
  } else if (parseJsonList(releases.stdout) === null) {
    isReleaseUnknown = true
  } else {
    pending = parseReleasePrs(releases.stdout, latest)
  }

  const consumers: ConsumerPin[] = []
  for (const name of names) {
    if (failure !== null) {
      consumers.push(unread(name, null))
      continue
    }
    const ran = await gh(argv.lock(name))
    if (ran.exitCode !== 0) {
      failure = failureForAll(ran)
      consumers.push(unread(name, lockNote(ran.exitCode, ran.stderr)))
      continue
    }
    consumers.push({ name, ...lockPin(ran.stdout), pr: null, isPrUnknown: false })
  }

  for (const consumer of consumers) {
    if (consumer.pinned === null) continue
    if (!isBehind(consumer, latest) && !namesOldRepo(consumer)) continue
    if (failure !== null) {
      consumer.isPrUnknown = true
      continue
    }
    const ran = await gh(argv.pinPrs(consumer.name))
    const prs = ran.exitCode === 0 ? parsePinPrs(ran.stdout) : null
    if (prs === null) {
      if (ran.exitCode !== 0) failure = failureForAll(ran)
      consumer.isPrUnknown = true
      continue
    }
    consumer.pr = newestPinPr(prs, consumer.pinned)
  }

  return { latest, pending, isReleaseUnknown, consumers, failure, at: now }
}
