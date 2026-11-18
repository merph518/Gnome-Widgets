// Shows above the prompt, in the Overmind repository only, when a release is pending or
// a repository that pins Overmind is behind the latest tag, and a pane that lists each
// of those repositories with its pinned tag, its open pin pull request and that pull
// request's checks.
//
// Every read goes through gh and only reads: consumers.json, the tags, the open
// release pull request, each consumer's .claude/att-docs.lock on its default branch,
// and the open pull requests of each consumer behind the latest tag or whose lock
// names an older name of this repository. A refresh runs when the chat starts, every
// ten minutes, when the pane opens, and on Refresh. What it finds is kept in the
// plugin's store, which every chat shares, so a chat that finds a result under ten
// minutes old uses it instead of asking GitHub again; after a read that failed in
// whole or in part it waits fifteen minutes. Refreshes never overlap: one asked for
// while another runs waits for it and then runs once.
//
// In any other repository no gh command runs and no band shows; the pane says why.
// switches.json in the configuration folder turns the plugin off, or hides the band
// and stops the timed reads, and an `.open-` file there opens the pane.

import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { ConsumerPin, Drift, DriftSwitches, PinPr } from '../types'
import {
  NAME,
  bandText,
  compareVersions,
  configDir,
  failureLine,
  fetchDrift,
  hasGaps,
  isBehind,
  isHomeRepo,
  isMovePr,
  namesOldRepo,
  OWNER,
  HOME_REPO,
  parseConsumers,
  parseSwitches,
  shortVersion,
} from './drift'
import type { GhResult } from './drift'

const PANE = NAME
const TITLE = 'Pin drift'

// The engine reads each atom's plugin and key as written, so they stay string literals.
const SWITCHED_ON: DriftSwitches = { isOff: false, isHidden: false }
const drift = atom({ plugin: 'pin-drift', key: 'drift' } as const, null as Drift | null)
const switches = atom({ plugin: 'pin-drift', key: 'switches' } as const, SWITCHED_ON)
const isHome = atom({ plugin: 'pin-drift', key: 'isHome' } as const, false)
const isBusy = atom({ plugin: 'pin-drift', key: 'isBusy' } as const, false)

export const REFRESH_MS = 10 * 60_000
// How long a result that failed is kept before GitHub is asked again.
export const RETRY_MS = 15 * 60_000
// How often switches.json and the `.open-` file are read.
export const SWITCH_MS = 3000
// How long one gh call may take before it is given up.
const GH_TIMEOUT_MS = 20_000
const GH = { timeoutMs: GH_TIMEOUT_MS, env: { GH_PROMPT_DISABLED: '1' } }
// The store key the result is kept under.
const STORE_KEY = 'drift'

type Timer = { cancel: () => void }
// Why a read runs: a timer or the chat starting, the pane opening, or Refresh. A hidden
// band skips the timer's reads; Refresh also skips a kept result that is still fresh.
type Ask = 'timer' | 'pane' | 'force'
const STRENGTH: Record<Ask, number> = { timer: 0, pane: 1, force: 2 }

let timers: Timer[] = []
let config: string | null = null
let root: string | null = null
let running: Promise<void> | null = null
let isPending = false
// What the next run was asked for by, the strongest ask winning while one waits.
let pendingAsk: Ask = 'timer'
// Counts the times the module registered, so a run from before a reload stops.
let registered = 0

async function configFolder($: EngineInterface): Promise<string> {
  config ??= configDir(await $.env.get('HOME'), await $.env.get('CLAUDE_CONFIG_DIR'))
  return config
}

async function readSwitches($: EngineInterface): Promise<DriftSwitches> {
  const text = await $.fs.read(`${await configFolder($)}/mods/switches.json`).then(
    value => (typeof value === 'string' ? value : undefined),
    () => undefined,
  )
  const value = parseSwitches(text)
  const before = await read($, switches)
  if (before.isOff !== value.isOff || before.isHidden !== value.isHidden) {
    await update($, switches, () => value)
  }
  return value
}

// $.process.run rejects when gh cannot start or runs past its timeout; that comes back
// as a result with no exit code and the reason in stderr.
function ghRunner($: EngineInterface) {
  return async (args: string[]): Promise<GhResult> => {
    try {
      const ran = await $.process.run(args, GH)
      return { exitCode: ran.exitCode, stdout: ran.stdout, stderr: ran.stderr }
    } catch (error) {
      return { exitCode: null, stdout: '', stderr: String(error) }
    }
  }
}

function asDrift(value: unknown): Drift | null {
  if (value === null || typeof value !== 'object') return null
  const record = value as Record<string, unknown>
  if (typeof record['at'] !== 'number' || !Array.isArray(record['consumers'])) return null
  return value as Drift
}

// The consumers to read when consumers.json cannot be read through gh: the ones the
// last result listed, else this checkout's own copy of the file.
async function fallbackConsumers($: EngineInterface, kept: Drift | null): Promise<string[]> {
  if (kept !== null && kept.consumers.length > 0) {
    return kept.consumers.map(consumer => consumer.name)
  }
  if (root === null) return []
  const text = await $.fs.read(`${root}/.github/consumers.json`).then(
    value => (typeof value === 'string' ? value : undefined),
    () => undefined,
  )
  return text === undefined ? [] : (parseConsumers(text) ?? [])
}

function isFresh(kept: Drift, now: number): boolean {
  return now - kept.at < (hasGaps(kept) ? RETRY_MS : REFRESH_MS)
}

async function refreshOnce($: EngineInterface, ask: Ask) {
  if (!(await read($, isHome))) return
  const flags = await readSwitches($)
  if (flags.isOff) {
    await update($, drift, value => (value === null ? value : null))
    return
  }
  if (flags.isHidden && ask === 'timer') return
  const now = await $.clock.now()
  const kept = asDrift(await $.store.get(STORE_KEY).catch(() => undefined))
  if (kept !== null && ask !== 'force' && isFresh(kept, now)) {
    await update($, drift, () => kept)
    return
  }
  await update($, isBusy, () => true)
  try {
    const value = await fetchDrift(ghRunner($), () => fallbackConsumers($, kept), now)
    // Turned off while gh ran: the result is not shown.
    if ((await read($, switches)).isOff) return
    await $.store.set(STORE_KEY, value).catch(() => undefined)
    await update($, drift, () => value)
  } finally {
    await update($, isBusy, () => false)
  }
}

function refresh($: EngineInterface, ask: Ask = 'timer'): Promise<void> {
  if (STRENGTH[ask] > STRENGTH[pendingAsk]) pendingAsk = ask
  if (running !== null) {
    isPending = true
    return running
  }
  // A run started before the module registered again neither loops on nor clears
  // the newer run's guard.
  const generation = registered
  let run!: Promise<void>
  run = (async () => {
    try {
      do {
        isPending = false
        const next = pendingAsk
        pendingAsk = 'timer'
        await refreshOnce($, next).catch(() => undefined)
      } while (isPending && generation === registered)
    } finally {
      if (running === run) running = null
    }
  })()
  running = run
  return run
}

function startRefresh($: EngineInterface, ask: Ask = 'timer') {
  $.clock.after(0, () => {
    void refresh($, ask)
  })
}

async function openPane($: EngineInterface): Promise<void> {
  await $.ui.open({ id: PANE, title: TITLE })
  startRefresh($, 'pane')
}

// Open in /mods writes an empty file named for this mod and this chat: open the pane and
// remove the file.
async function checkOpen($: EngineInterface): Promise<void> {
  if ((await read($, switches)).isOff) return
  const path = `${await configFolder($)}/mods/.open-${NAME}-${await $.session.id()}`
  if (!(await $.fs.exists(path).catch(() => false))) return
  await $.process.run(['rm', '-f', path])
  await openPane($)
}

async function poll($: EngineInterface): Promise<void> {
  const before = await read($, switches)
  const now = await readSwitches($)
  if (now.isOff) await update($, drift, value => (value === null ? value : null))
  else if (before.isOff || (before.isHidden && !now.isHidden)) startRefresh($)
  await checkOpen($)
}

async function readHome($: EngineInterface): Promise<boolean> {
  try {
    const repo = await $.session.repo()
    root = repo?.root ?? null
    return isHomeRepo(repo?.remote ?? null)
  } catch {
    root = null
    return false
  }
}

// How long ago, in whole minutes, hours or days.
function formatAge(ms: number): string {
  const minutes = Math.floor(Math.max(0, ms) / 60_000)
  if (minutes < 60) return `${minutes}m`
  if (minutes < 24 * 60) return `${Math.floor(minutes / 60)}h`
  return `${Math.floor(minutes / (24 * 60))}d`
}

function ciLabel(pr: PinPr): string {
  return pr.ci === 'none' ? 'no checks' : `CI ${pr.ci}`
}

function prLabel(pr: PinPr): string {
  return `${isMovePr(pr) ? 'move' : 'pin'} pull request #${pr.number} (${pr.tag})`
}

const PRS_UNREAD = 'pin pull requests could not be read'

export const register: Register = on => {
  registered += 1
  for (const timer of timers) timer.cancel()
  timers = []
  config = null
  root = null
  running = null
  isPending = false
  pendingAsk = 'timer'

  on('session.start', async ($, e, next) => {
    const result = await next(e)
    await $.command.register({
      name: NAME,
      description: 'Show which repositories pin an older Overmind tag',
      immediate: true,
    })
    const flags = await readSwitches($)
    const home = await readHome($)
    await update($, isHome, () => home)
    for (const timer of timers) timer.cancel()
    timers = [
      $.clock.every(SWITCH_MS, () => {
        poll($).catch(() => undefined)
      }),
    ]
    if (!home) return result
    timers.push(
      $.clock.every(REFRESH_MS, () => {
        void refresh($)
      }),
    )
    if (!flags.isOff) startRefresh($)
    return result
  })

  on('command.run', { command: NAME }, async $ => {
    if ((await readSwitches($)).isOff) {
      return { text: 'Pin drift is switched off in switches.json. Open /mods to turn it on.' }
    }
    await openPane($)
    return { text: 'The pin drift pane is open.' }
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const flags = await read($, switches)
    if (e.props.hasSurvey || flags.isOff || flags.isHidden) return next(e)
    if (!(await read($, isHome))) return next(e)
    const state = await read($, drift)
    if (state === null) return next(e)
    const { Box, Button, Text } = $.ui.resolve(e)
    if (state.failure !== null) {
      return (
        <Box>
          <Text dimColor>{failureLine(state.failure)}</Text>
        </Box>
      )
    }
    const text = bandText(state, e.props.bodyColumns)
    if (text === null) return next(e)
    return (
      <Box>
        <Text color="yellow">{text}</Text>
        <Text> </Text>
        <Button key="details" label="Details" onPress={() => openPane($)} />
      </Box>
    )
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Button, Link, Text } = $.ui.resolve(e)
    const close = <Button key="close" label="Close" onPress={() => $.ui.close({ id: PANE })} />
    if (!(await read($, isHome))) {
      return (
        <Box flexDirection="column">
          <Text>
            Pin drift reads the pins only in the Overmind repository ({OWNER}/{HOME_REPO}).
          </Text>
          {close}
        </Box>
      )
    }
    if ((await read($, switches)).isOff) {
      return (
        <Box flexDirection="column">
          <Text>Pin drift is turned off. Open /mods to turn it on.</Text>
          {close}
        </Box>
      )
    }
    const state = await read($, drift)
    const busy = await read($, isBusy)
    const now = await $.clock.now()

    const prLink = (pr: PinPr) => [
      <Link key="pr" href={pr.url} label={prLabel(pr)} />,
      ` · ${ciLabel(pr)}`,
    ]

    const row = (consumer: ConsumerPin, latest: string, index: number) => {
      const lines = []
      const pinned = consumer.pinned
      if (pinned === null) {
        const why = consumer.note ?? 'not read, because gh failed first'
        lines.push(<Text>lock unreadable: {why}</Text>)
      } else if (isBehind(consumer, latest)) {
        const head = `pinned ${shortVersion(pinned)} · behind ${shortVersion(latest)} · `
        lines.push(
          consumer.pr !== null ? (
            <Text>
              {head}
              {prLink(consumer.pr)}
            </Text>
          ) : (
            <Text>
              {head}
              {consumer.isPrUnknown === true ? PRS_UNREAD : 'no open pin pull request'}
            </Text>
          ),
        )
      } else {
        const where = compareVersions(pinned, latest) > 0 ? 'ahead of latest' : 'on latest'
        lines.push(<Text dimColor>pinned {shortVersion(pinned)} · {where}</Text>)
      }
      if (namesOldRepo(consumer)) {
        lines.push(<Text dimColor>lock names {consumer.lockRepo}</Text>)
        if (pinned !== null && !isBehind(consumer, latest)) {
          if (consumer.pr !== null) lines.push(<Text>{prLink(consumer.pr)}</Text>)
          else if (consumer.isPrUnknown === true) lines.push(<Text dimColor>{PRS_UNREAD}</Text>)
        }
      }
      return (
        <Box key={`consumer-${index}`} flexDirection="column">
          <Text bold>{consumer.name}</Text>
          {lines}
        </Box>
      )
    }

    let body
    if (state === null) {
      body = <Text dimColor>{busy ? 'Checking…' : 'The pins have not been read yet.'}</Text>
    } else if (state.latest === null) {
      body = <Text>{failureLine(state.failure ?? 'failed')}</Text>
    } else {
      const latest = state.latest
      const pending = state.pending
      let release
      if (pending !== null) {
        release = (
          <Text>
            {`Release ${pending.version} pending · `}
            <Link href={pending.url} label={`#${pending.number} ${pending.title}`} />
          </Text>
        )
      } else if (state.isReleaseUnknown === true) {
        release = <Text>The release pull requests could not be read.</Text>
      } else {
        release = <Text dimColor>No release pending</Text>
      }
      const empty = state.consumers.length === 0
      body = (
        <Box flexDirection="column">
          {state.failure === null ? null : <Text>{failureLine(state.failure)}</Text>}
          <Text>Latest tag {shortVersion(latest)}</Text>
          {release}
          {empty ? <Text dimColor>consumers.json lists no repositories.</Text> : null}
          {state.consumers.map((consumer, index) => row(consumer, latest, index))}
        </Box>
      )
    }

    const checked = state === null ? '' : `Checked ${formatAge(now - state.at)} ago`
    return (
      <Box flexDirection="column">
        {body}
        <Text dimColor>{busy ? 'Checking…' : checked}</Text>
        <Box>
          <Button key="refresh" label="Refresh" onPress={() => startRefresh($, 'force')} />
          <Text> </Text>
          {close}
        </Box>
        <Text dimColor>
          Pin pull requests come from pin-consumers.yml, which runs after each release.
        </Text>
      </Box>
    )
  })
}
