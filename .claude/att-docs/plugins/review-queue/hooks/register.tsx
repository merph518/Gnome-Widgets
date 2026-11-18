// Shows above the prompt the open pull requests that carry the review label, across
// this repository and the repositories that pin it, one row each.
//
// The list of watched repositories is .github/consumers.json in this repository,
// read through gh at most once an hour and kept in the plugin's store, so a chat
// in any folder sees the same list. Each refresh runs one `gh pr list` per
// repository, one after another: every fifteen minutes as a backstop, a few seconds
// after a shell command that runs `gh pr` or changes the label through `gh api`,
// and in every other chat once a command that changes labels or pull requests
// stamps the store. A refresh asked for while one runs waits for it and then runs
// once, so refreshes never overlap and never hold up a turn. A gh call already
// running when the module reloads finishes on its own; the run it belongs to stops
// after it. switches.json in the configuration folder turns the plugin off or hides
// the band; while either is set, gh is not run.
//
// Every few seconds, while rows wait, the events files `catchup.py wait` writes
// for those rows' repositories are checked from disk, and a pull request they say
// closed after it was listed leaves the band with no gh call. A row dismissed in
// any chat is kept in the store and left out of every chat's band until a refresh
// no longer lists its pull request.
//
// A reload of the module drops its timers; session.start starts them again.

import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { PullRequest, Queue, QueueFailure, QueueSwitches } from '../types'
import {
  EVENT_FILES,
  HOUR_MS,
  LIST_LIMIT,
  MAX_ROWS,
  catchupFolder,
  ciLabel,
  classifyFailure,
  configDir,
  consumersArgv,
  dropClosed,
  failureLine,
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

const queue = atom({ plugin: 'review-queue', key: 'queue' } as const, null as Queue | null)
const switches = atom({ plugin: 'review-queue', key: 'switches' } as const, { isOff: false, isHidden: false } as QueueSwitches)
// The pull requests dismissed in any chat, as `repo#number`, mirrored from the store.
const dismissed = atom({ plugin: 'review-queue', key: 'dismissed' } as const, [] as string[])
const showDismissed = atom({ plugin: 'review-queue', key: 'showDismissed' } as const, false)

// The backstop refresh, for what nothing else brings: a label changed in the web UI
// or on another machine, and CI state.
export const REFRESH_MS = 15 * 60_000
// switches.json and the shared dismissals are read this often, so a change made in
// another chat shows soon.
export const SWITCH_MS = 15_000
// How long after a `gh pr` or label command the refresh runs, so GitHub has the change.
export const GH_DELAY_MS = 3000
// How often the catchup events files are checked while rows wait.
export const CLOSE_POLL_MS = 5000
// How long one gh call may take before it is given up.
const GH_TIMEOUT_MS = 20_000
const GH = { timeoutMs: GH_TIMEOUT_MS, env: { GH_PROMPT_DISABLED: '1' } }

type Timer = { cancel: () => void }
type StoredRepos = { list: string[]; at: number }
// One events file as last read: its size and change time, and the closes in it.
type EventsFile = { repo: string; signature: string; closes: Map<number, number> }

let folder: string | null = null
let home: string | null = null
let refresher: Timer | null = null
let switchPoll: Timer | null = null
let closePoll: Timer | null = null
let afterGh: Timer | null = null
// Set while the pending delayed refresh is to stamp the store for the other chats.
let isStampDue = false
// The newest label stamp this chat has refreshed for, so one stamp calls one refresh.
let seenStamp = 0
// Each events file read so far, by path.
const events = new Map<string, EventsFile>()
let running: Promise<void> | null = null
let isPending = false
// Counts the times the module registered, so a run from before a reload stops.
let registered = 0

async function configFolder($: EngineInterface): Promise<string> {
  folder ??= configDir(await $.env.get('HOME'), await $.env.get('CLAUDE_CONFIG_DIR'))
  return folder
}

async function homeDir($: EngineInterface): Promise<string> {
  home ??= (await $.env.get('HOME')) ?? ''
  return home
}

async function readSwitches($: EngineInterface): Promise<QueueSwitches> {
  const text = await $.fs.read(`${await configFolder($)}/mods/switches.json`).then(
    value => (typeof value === 'string' ? value : undefined),
    () => undefined,
  )
  const value = parseSwitches(text)
  const before = await read($, switches)
  if (before.isOff !== value.isOff || before.isHidden !== value.isHidden) await update($, switches, () => value)
  return value
}

function asStored(value: unknown): StoredRepos | null {
  if (value === null || typeof value !== 'object') return null
  const { list, at } = value as Record<string, unknown>
  if (!Array.isArray(list) || typeof at !== 'number') return null
  return { list: list.filter((one): one is string => typeof one === 'string'), at }
}

// The dismissals kept in the store; none when it cannot be read.
async function storedDismissed($: EngineInterface): Promise<string[]> {
  return parseDismissed(await $.store.get('dismissed').catch(() => undefined))
}

async function mirrorDismissed($: EngineInterface, list: string[]) {
  const before = await read($, dismissed)
  const isSame = before.length === list.length && before.every((key, i) => key === list[i])
  if (!isSame) await update($, dismissed, () => list)
}

// Changes the shared dismissals from what the store holds now, so a dismissal made
// in another chat since the last read is kept.
async function changeDismissed($: EngineInterface, change: (list: string[]) => string[]) {
  const list = change(await storedDismissed($))
  await $.store.set('dismissed', list)
  await mirrorDismissed($, list)
}

function withKey(list: string[], key: string): string[] {
  return list.includes(key) ? list : [...list, key]
}

// Every close read from the events files, keyed by `repo#number`.
function knownCloses(): Map<string, number> {
  const all = new Map<string, number>()
  for (const file of events.values()) {
    for (const [number, at] of file.closes) {
      const key = prKey(file.repo, number)
      all.set(key, Math.max(all.get(key) ?? 0, at))
    }
  }
  return all
}

// Reads a repository's events files again where they changed since the last read.
// A missing folder or file reads as no closes. True when anything changed.
async function readEvents($: EngineInterface, repo: string): Promise<boolean> {
  const dir = catchupFolder(await homeDir($), repo)
  const entries = await $.fs.list(dir).catch(() => [])
  let isChanged = false
  for (const name of EVENT_FILES) {
    const path = `${dir}/${name}`
    const signature = fileSignature(entries, name)
    const kept = events.get(path)
    if (signature === null) {
      if (kept !== undefined) events.delete(path)
      isChanged ||= kept !== undefined
      continue
    }
    if (kept?.signature === signature) continue
    const text = await $.fs.read(path).then(
      value => (typeof value === 'string' ? value : ''),
      () => '',
    )
    events.set(path, { repo, signature, closes: parseCloses(text) })
    isChanged = true
  }
  return isChanged
}

// Takes out of the band each pull request the events files say closed after the
// refresh that listed it.
async function pollCloses($: EngineInterface) {
  const state = await read($, queue)
  if (state === null || state.prs.length === 0 || isQuiet(await read($, switches))) return
  let isChanged = false
  for (const repo of new Set(state.prs.map(pr => pr.repo))) {
    if (await readEvents($, repo)) isChanged = true
  }
  if (!isChanged) return
  const closes = knownCloses()
  await update($, queue, value => {
    // A list kept from before refreshes recorded when they started is left alone.
    if (value === null || typeof value.at !== 'number') return value
    const prs = dropClosed(value.prs, closes, value.at)
    return prs.length === value.prs.length ? value : { ...value, prs }
  })
}

async function storedRepos($: EngineInterface): Promise<StoredRepos | null> {
  return asStored(await $.store.get('repos').catch(() => undefined))
}

// The repositories to read. The list kept in the store is used while under an hour
// old; otherwise it is read again, and kept when that read fails.
async function watchedRepos($: EngineInterface): Promise<string[]> {
  const now = await $.clock.now()
  const stored = await storedRepos($)
  if (stored !== null && now - stored.at < HOUR_MS) return watched(stored.list)
  try {
    const ran = await $.process.run(consumersArgv(), GH)
    const list = ran.exitCode === 0 ? parseRepos(ran.stdout) : null
    if (list !== null) {
      await $.store.set('repos', { list, at: now })
      return watched(list)
    }
  } catch {
    // gh missing or too slow: the kept list, or this repository alone.
  }
  return watched(stored?.list ?? [])
}

// $.process.run rejects when the command cannot start or runs past its timeout. A
// timeout can be one slow repository, so it does not stop the refresh.
function rejected(error: unknown): QueueFailure {
  return /ENOENT|not found|no such file/i.test(String(error)) ? 'missing' : 'failed'
}

function isQuiet(flags: QueueSwitches): boolean {
  return flags.isOff || flags.isHidden
}

async function refreshOnce($: EngineInterface) {
  // While quiet, the list is dropped, so showing the band again waits for a fresh one.
  if (isQuiet(await readSwitches($))) {
    await update($, queue, value => (value === null ? value : null))
    return
  }
  // A close is compared with when the refresh started, before GitHub was asked.
  const at = await $.clock.now()
  const repos = await watchedRepos($)
  const prs: PullRequest[] = []
  const unread: string[] = []
  // The numbers each repository listed, for those read in full.
  const listed = new Map<string, number[]>()
  let failure: QueueFailure | null = null
  let readCount = 0
  for (const repo of repos) {
    let failed: QueueFailure | null = null
    try {
      const ran = await $.process.run(listArgv(repo), GH)
      const found = ran.exitCode === 0 ? parsePrList(ran.stdout, repo) : null
      if (found !== null) {
        prs.push(...found)
        readCount += 1
        if (found.length < LIST_LIMIT) listed.set(repo, found.map(pr => pr.number))
        continue
      }
      failed = ran.exitCode === 0 ? 'failed' : classifyFailure(ran.exitCode, ran.stderr)
    } catch (error) {
      failed = rejected(error)
    }
    unread.push(repo)
    failure ??= failed
    // Not installed, signed out or offline holds for every repository alike.
    if (readCount === 0 && failed !== 'failed') break
  }
  // A dismissal whose pull request is no longer listed is dropped from the store.
  if (readCount > 0) {
    try {
      const kept = await storedDismissed($)
      const left = pruneDismissed(kept, listed)
      if (left.length !== kept.length) await $.store.set('dismissed', left)
      await mirrorDismissed($, left)
    } catch {
      // The next refresh prunes it.
    }
  }
  // Turned off or hidden while gh ran: the list is not kept.
  if (isQuiet(await read($, switches))) return
  // GitHub's search can still list a pull request for a few seconds after it
  // merged, so the closes already read are applied to the new list too.
  const value: Queue =
    readCount === 0
      ? { prs: [], unread: [], failure: failure ?? 'failed', at }
      : { prs: dropClosed(sortOldestFirst(prs), knownCloses(), at), unread, failure: null, at }
  await update($, queue, () => value)
}

function refresh($: EngineInterface): Promise<void> {
  if (running !== null) {
    isPending = true
    return running
  }
  // A run started before the module registered again neither loops on nor clears
  // the newer run's guard.
  const generation = registered
  // Set before the body's first await returns control, so the finally sees it.
  let run!: Promise<void>
  run = (async () => {
    try {
      do {
        isPending = false
        await refreshOnce($).catch(() => undefined)
      } while (isPending && generation === registered)
    } finally {
      if (running === run) running = null
    }
  })()
  running = run
  return run
}

function stopTimers() {
  refresher?.cancel()
  refresher = null
  switchPoll?.cancel()
  switchPoll = null
  closePoll?.cancel()
  closePoll = null
  afterGh?.cancel()
  afterGh = null
  isStampDue = false
}

function row(pr: PullRequest, now: number): string {
  const draft = pr.isDraft ? ' · draft' : ''
  return ` · ${ciLabel(pr.ci)} · ${formatAge(now - pr.createdAt)}${draft}`
}

// Refreshes after GH_DELAY_MS. With `isShared`, it also stamps the store as that
// refresh starts, so every other chat refreshes on its next switch poll, once
// GitHub lists the change. Two calls within the delay make one refresh, shared
// when either asked for it.
function refreshSoon($: EngineInterface, isShared: boolean) {
  afterGh?.cancel()
  isStampDue ||= isShared
  afterGh = $.clock.after(GH_DELAY_MS, async () => {
    afterGh = null
    if (isStampDue) {
      isStampDue = false
      try {
        const now = await $.clock.now()
        seenStamp = Math.max(seenStamp, now)
        await $.store.set('labeledAt', now)
      } catch {
        // The other chats wait for their own refresh.
      }
    }
    void refresh($)
  })
}

// A stamp newer than the last one this chat refreshed for, or 0.
async function newStamp($: EngineInterface): Promise<number> {
  const stamp = await $.store.get('labeledAt').catch(() => undefined)
  return typeof stamp === 'number' && stamp > seenStamp ? stamp : 0
}

// The text a Bash call answered, where the label read-back is.
function outputOf(result: unknown): string {
  if (result === null || typeof result !== 'object') return ''
  const record = result as { result?: { stdout?: unknown }; text?: unknown }
  const parts = [record.result?.stdout, record.text]
  return parts.filter((part): part is string => typeof part === 'string').join('\n')
}

export const register: Register = on => {
  registered += 1
  folder = null
  home = null
  seenStamp = 0
  events.clear()
  running = null
  isPending = false
  stopTimers()

  on('session.start', async ($, e, next) => {
    const result = await next(e)
    await readSwitches($)
    await mirrorDismissed($, await storedDismissed($))
    // The refresh at the start covers every stamp written before it.
    seenStamp = Math.max(seenStamp, await newStamp($))
    stopTimers()
    refresher = $.clock.every(REFRESH_MS, () => {
      void refresh($)
    })
    switchPoll = $.clock.every(SWITCH_MS, async () => {
      try {
        const wasQuiet = isQuiet(await read($, switches))
        const isQuietNow = isQuiet(await readSwitches($))
        await mirrorDismissed($, await storedDismissed($))
        if (isQuietNow) {
          await update($, queue, value => (value === null ? value : null))
          return
        }
        const stamp = await newStamp($)
        if (stamp > 0) seenStamp = stamp
        if (wasQuiet || stamp > 0) void refresh($)
      } catch {
        // The next poll reads the file again.
      }
    })
    closePoll = $.clock.every(CLOSE_POLL_MS, async () => {
      try {
        await pollCloses($)
      } catch {
        // The next poll reads the files again.
      }
    })
    $.clock.after(0, () => {
      void refresh($)
    })
    return result
  })

  // A `gh pr` command may have added or removed the label, and a `gh api` labels
  // command on a watched repository did. The turn does not wait for the refresh.
  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const result = await next(e)
    try {
      const repos = watched((await storedRepos($))?.list ?? [])
      const isLabel = labelTrigger(e.command, outputOf(result), repos)
      if (isLabel || isGhPr(e.command)) refreshSoon($, isLabel || isGhPrChange(e.command))
    } catch {
      // The next timer refresh picks the change up.
    }
    return result
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const state = await read($, queue)
    const flags = await read($, switches)
    if (e.props.hasSurvey || state === null || flags.isOff || flags.isHidden) return next(e)
    const { Box, Button, Link, Text } = $.ui.resolve(e)
    if (state.failure !== null) {
      return (
        <Box>
          <Text dimColor>{failureLine(state.failure)}</Text>
        </Box>
      )
    }
    const dismissedKeys = new Set(await read($, dismissed))
    const waiting: PullRequest[] = []
    const gone: PullRequest[] = []
    for (const pr of state.prs) {
      const isDismissed = dismissedKeys.has(prKey(pr.repo, pr.number))
      ;(isDismissed ? gone : waiting).push(pr)
    }
    if (waiting.length === 0 && gone.length === 0) return next(e)
    const isShowingGone = gone.length > 0 && (await read($, showDismissed))
    const unread = state.unread.length
    const note = unread === 0 ? '' : ` · ${unread} ${unread === 1 ? 'repository' : 'repositories'} could not be read`
    const goneNote = gone.length === 0 ? '' : ` · ${gone.length} dismissed`
    const header = (
      <Box>
        {waiting.length > 0 ? (
          <Text>
            {waiting.length} waiting for review{note}{goneNote}{' '}
          </Text>
        ) : (
          <Text dimColor>
            {gone.length} dismissed{note}{' '}
          </Text>
        )}
        {gone.length > 0 && (
          <Button
            key="dismissed"
            label={isShowingGone ? 'Hide dismissed' : 'Show dismissed'}
            onPress={() => update($, showDismissed, value => !value)}
          />
        )}
      </Box>
    )
    const now = await $.clock.now()
    const shown = waiting.slice(0, MAX_ROWS)
    const more = waiting.length - shown.length
    const shownGone = isShowingGone ? gone.slice(0, MAX_ROWS) : []
    const moreGone = isShowingGone ? gone.length - shownGone.length : 0
    return (
      <Box flexDirection="column">
        {header}
        {shown.map(pr => {
          const key = prKey(pr.repo, pr.number)
          return (
            <Box>
              <Text>
                <Link href={pr.url} label={`${key} ${pr.title}`} />
                <Text dimColor>{row(pr, now)} </Text>
              </Text>
              <Button
                key={`dismiss:${key}`}
                label="Dismiss"
                onPress={() => changeDismissed($, list => withKey(list, key))}
              />
            </Box>
          )
        })}
        {more > 0 && <Text dimColor>and {more} more</Text>}
        {shownGone.map(pr => {
          const key = prKey(pr.repo, pr.number)
          return (
            <Box>
              <Text dimColor>
                dismissed: <Link href={pr.url} label={`${key} ${pr.title}`} />{' '}
              </Text>
              <Button
                key={`restore:${key}`}
                label="Restore"
                onPress={() => changeDismissed($, list => list.filter(one => one !== key))}
              />
            </Box>
          )
        })}
        {moreGone > 0 && <Text dimColor>and {moreGone} more dismissed</Text>}
      </Box>
    )
  })
}
