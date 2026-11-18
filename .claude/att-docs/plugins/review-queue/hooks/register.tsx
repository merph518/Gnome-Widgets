// Shows above the prompt how many open pull requests carry the review label, across
// this repository and the repositories that pin it, and lists them on request.
//
// The list of watched repositories is .github/consumers.json in this repository,
// read through gh at most once an hour and kept in the plugin's store, so a chat
// in any folder sees the same list. Each refresh runs one `gh pr list` per
// repository, one after another, from a timer: every five minutes, and a few
// seconds after a shell command that runs `gh pr`. A refresh asked for while one
// runs waits for it and then runs once, so refreshes never overlap and never hold
// up a turn. A gh call already running when the module reloads finishes on its own;
// the run it belongs to stops after it. switches.json in the configuration folder turns the plugin off or
// hides the band; while either is set, gh is not run.
//
// A reload of the module drops its timers; session.start starts them again.

import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { PullRequest, Queue, QueueFailure, QueueSwitches } from '../types'
import {
  HOUR_MS,
  MAX_ROWS,
  ciLabel,
  classifyFailure,
  configDir,
  consumersArgv,
  failureLine,
  formatAge,
  isGhPr,
  listArgv,
  parsePrList,
  parseRepos,
  parseSwitches,
  sortOldestFirst,
  watched,
} from './queue'

const queue = atom({ plugin: 'review-queue', key: 'queue' } as const, null as Queue | null)
const switches = atom({ plugin: 'review-queue', key: 'switches' } as const, { isOff: false, isHidden: false } as QueueSwitches)
const isOpen = atom({ plugin: 'review-queue', key: 'isOpen' } as const, false)

export const REFRESH_MS = 5 * 60_000
// switches.json is read this often, so a change made in another chat shows soon.
export const SWITCH_MS = 15_000
// How long after a `gh pr` command the refresh runs, so GitHub has the change.
export const GH_DELAY_MS = 3000
// How long one gh call may take before it is given up.
const GH_TIMEOUT_MS = 20_000
const GH = { timeoutMs: GH_TIMEOUT_MS, env: { GH_PROMPT_DISABLED: '1' } }

type Timer = { cancel: () => void }
type StoredRepos = { list: string[]; at: number }

let folder: string | null = null
let refresher: Timer | null = null
let switchPoll: Timer | null = null
let afterGh: Timer | null = null
let running: Promise<void> | null = null
let isPending = false
// Counts the times the module registered, so a run from before a reload stops.
let registered = 0

async function configFolder($: EngineInterface): Promise<string> {
  folder ??= configDir(await $.env.get('HOME'), await $.env.get('CLAUDE_CONFIG_DIR'))
  return folder
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

// The repositories to read. The list kept in the store is used while under an hour
// old; otherwise it is read again, and kept when that read fails.
async function watchedRepos($: EngineInterface): Promise<string[]> {
  const now = await $.clock.now()
  const stored = asStored(await $.store.get('repos').catch(() => undefined))
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
  const repos = await watchedRepos($)
  const prs: PullRequest[] = []
  const unread: string[] = []
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
  // Turned off or hidden while gh ran: the list is not kept.
  if (isQuiet(await read($, switches))) return
  const value: Queue =
    readCount === 0
      ? { prs: [], unread: [], failure: failure ?? 'failed' }
      : { prs: sortOldestFirst(prs), unread, failure: null }
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
  afterGh?.cancel()
  afterGh = null
}

function row(pr: PullRequest, now: number): string {
  const draft = pr.isDraft ? ' · draft' : ''
  return ` · ${ciLabel(pr.ci)} · ${formatAge(now - pr.createdAt)}${draft}`
}

export const register: Register = on => {
  registered += 1
  folder = null
  running = null
  isPending = false
  stopTimers()

  on('session.start', async ($, e, next) => {
    const result = await next(e)
    await readSwitches($)
    stopTimers()
    refresher = $.clock.every(REFRESH_MS, () => {
      void refresh($)
    })
    switchPoll = $.clock.every(SWITCH_MS, async () => {
      try {
        const wasQuiet = isQuiet(await read($, switches))
        const isQuietNow = isQuiet(await readSwitches($))
        if (isQuietNow) await update($, queue, value => (value === null ? value : null))
        else if (wasQuiet) void refresh($)
      } catch {
        // The next poll reads the file again.
      }
    })
    $.clock.after(0, () => {
      void refresh($)
    })
    return result
  })

  // A `gh pr` command may have added or removed the label. The turn does not wait
  // for the refresh.
  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const result = await next(e)
    try {
      if (isGhPr(e.command)) {
        afterGh?.cancel()
        afterGh = $.clock.after(GH_DELAY_MS, () => {
          afterGh = null
          void refresh($)
        })
      }
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
    if (state.prs.length === 0) return next(e)
    const open = await read($, isOpen)
    const unread = state.unread.length
    const note = unread === 0 ? '' : ` · ${unread} ${unread === 1 ? 'repository' : 'repositories'} could not be read`
    const header = (
      <Box>
        <Text>
          {state.prs.length} waiting for review{note}{' '}
        </Text>
        <Button key="toggle" label={open ? 'Hide list' : 'Show list'} onPress={() => update($, isOpen, value => !value)} />
      </Box>
    )
    if (!open) return header
    const now = await $.clock.now()
    const shown = state.prs.slice(0, MAX_ROWS)
    const more = state.prs.length - shown.length
    return (
      <Box flexDirection="column">
        {header}
        {shown.map(pr => (
          <Text>
            <Link href={pr.url} label={`${pr.repo}#${pr.number} ${pr.title}`} />
            <Text dimColor>{row(pr, now)}</Text>
          </Text>
        ))}
        {more > 0 && <Text dimColor>and {more} more</Text>}
      </Box>
    )
  })
}
