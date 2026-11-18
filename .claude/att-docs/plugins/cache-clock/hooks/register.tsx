// Counts down above the prompt until the chat's prompt cache goes cold.
//
// After each main-chat reply the plugin reads the session's transcript to learn
// which prompt cache the reply wrote to, five minutes or one hour, and the band
// counts down from the start of that reply's request. A cold chat over 150,000
// tokens is offered a handoff, which the handoff plugin picks up from a request
// file. /keepwarm pings the chat shortly before the cache goes cold, until the
// person types a prompt or a limit is reached. switches.json in the configuration
// folder turns the plugin off or hides the band.
//
// A reload of the module drops its timers; the next reply starts them again.

import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { CacheClock, CacheLength, CacheSwitches, KeepWarm } from '../types'
import {
  HOUR_MS,
  MAX_FAILURES,
  MAX_KEEP_WARM_MS,
  MAX_PINGS,
  PING_LEAD_MS,
  PING_RETRY_MS,
  configDir,
  formatLeft,
  isBig,
  keepWarmStop,
  leftMs,
  lengthMs,
  parseSwitches,
  pingAt,
  readCacheLength,
} from './clock'

const clock = atom({ plugin: 'cache-clock', key: 'clock' } as const, null as CacheClock | null)
const switches = atom({ plugin: 'cache-clock', key: 'switches' } as const, { isOff: false, isHidden: false } as CacheSwitches)
const isShown = atom({ plugin: 'cache-clock', key: 'isShown' } as const, true)
const tokens = atom({ plugin: 'cache-clock', key: 'tokens' } as const, 0)
const keepWarm = atom({ plugin: 'cache-clock', key: 'keepWarm' } as const, null as KeepWarm | null)
const isAsked = atom({ plugin: 'cache-clock', key: 'isAsked' } as const, false)

// The largest file $.fs.read takes.
const READ_LIMIT = 4 * 1024 * 1024
// How much of a larger transcript is read: under the 4 MiB a command's output is
// cut at, and far more than the newest reply's line.
const TAIL_BYTES = 4_000_000
const RETRY_MS = 2000
const TICK_MS = 1000
// switches.json is read again every this many ticks, so a change made in another
// chat shows within seconds.
const SWITCH_TICKS = 5

const PING = 'Reply with the single word: ok'

type Timer = { cancel: () => void }

let folder: string | null = null
let transcript: { sid: string; path: string } | null = null
// When the newest main-chat request went out, for the turn that is running.
let requestAt: number | null = null
let isTurnRunning = false
// Main-chat turns started this session, so a ping can tell a turn ran while it did.
let turnsStarted = 0
// A handoff request being written, so a second press does not write it again.
let isAsking = false
let ticker: Timer | null = null
let pinger: Timer | null = null
let rereader: Timer | null = null

async function configFolder($: EngineInterface): Promise<string> {
  folder ??= configDir(await $.env.get('HOME'), await $.env.get('CLAUDE_CONFIG_DIR'))
  return folder
}

async function readSwitches($: EngineInterface): Promise<CacheSwitches> {
  const text = await $.fs.read(`${await configFolder($)}/mods/switches.json`).then(
    value => (typeof value === 'string' ? value : undefined),
    () => undefined,
  )
  const value = parseSwitches(text)
  const before = await read($, switches)
  if (before.isOff !== value.isOff || before.isHidden !== value.isHidden) await update($, switches, () => value)
  return value
}

// Finds this session's transcript, <config>/projects/<project>/<session id>.jsonl.
async function findTranscript($: EngineInterface): Promise<string | null> {
  const sid = await $.session.id()
  if (transcript !== null && transcript.sid === sid) return transcript.path
  const projects = `${await configFolder($)}/projects`
  const entries = await $.fs.list(projects).catch(() => [])
  for (const entry of entries) {
    if (entry.kind !== 'dir') continue
    const path = `${projects}/${entry.name}/${sid}.jsonl`
    if (await $.fs.exists(path).catch(() => false)) {
      transcript = { sid, path }
      return path
    }
  }
  return null
}

async function readTranscript($: EngineInterface, path: string): Promise<string> {
  try {
    const { size } = await $.fs.stat(path)
    if (size <= READ_LIMIT) {
      const text = await $.fs.read(path)
      return typeof text === 'string' ? text : ''
    }
    // $.fs.read takes no range, so a larger transcript is read through tail. The
    // first line it prints is usually cut short; the reader skips it.
    const { exitCode, stdout } = await $.process.run(['tail', '-c', String(TAIL_BYTES), path])
    return exitCode === 0 ? stdout : ''
  } catch {
    return ''
  }
}

async function detect($: EngineInterface): Promise<CacheLength> {
  const path = await findTranscript($)
  if (path === null) return { kind: 'unknown', at: null }
  return readCacheLength(await readTranscript($, path))
}

function stopTimers() {
  ticker?.cancel()
  ticker = null
  pinger?.cancel()
  pinger = null
  rereader?.cancel()
  rereader = null
}

// Redraws the band each second while the cache is warm; the redraw that shows it
// cold is the last.
async function startTicker($: EngineInterface) {
  ticker?.cancel()
  let ticks = 0
  const timer = $.clock.every(TICK_MS, async () => {
    ticks += 1
    if (ticks % SWITCH_TICKS === 0) await readSwitches($).catch(() => undefined)
    $.ui.invalidate('ui.render')
    const state = await read($, clock)
    if (state === null || leftMs(state.lastAt, state.kind, await $.clock.now()) === 0) {
      timer.cancel()
      if (ticker === timer) ticker = null
    }
  })
  ticker = timer
}

async function stopKeepWarm($: EngineInterface, note: string) {
  pinger?.cancel()
  pinger = null
  await update($, keepWarm, value => (value === null || !value.isOn ? value : { ...value, isOn: false, note }))
}

// Sets the next ping for the cache as it stands, when keep warm is on.
// `retry` is a ping after one that did not read the cache: when it starts and how
// long the last ping took.
async function schedulePing($: EngineInterface, retry?: { at: number; tookMs: number }) {
  pinger?.cancel()
  pinger = null
  const state = await read($, clock)
  const warm = await read($, keepWarm)
  if (state === null || warm === null || !warm.isOn) return
  const now = await $.clock.now()
  if (leftMs(state.lastAt, state.kind, now) === 0) return
  const due = retry?.at ?? pingAt(state.lastAt, state.kind)
  // A retry that would not end before the cache goes cold, if it takes as long as
  // the last ping did, would write the whole chat to the cache again.
  if (retry !== undefined && due + retry.tookMs >= state.lastAt + lengthMs(state.kind)) {
    await stopKeepWarm($, 'too close to cold to try again')
    return
  }
  pinger = $.clock.after(Math.max(0, due - now), () => {
    ping($).catch(() => undefined)
  })
}

async function ping($: EngineInterface) {
  pinger = null
  const warm = await read($, keepWarm)
  const state = await read($, clock)
  // A running turn writes the cache itself; its end sets the next ping.
  if (warm === null || !warm.isOn || state === null || isTurnRunning) return
  if ((await readSwitches($)).isOff) return stopKeepWarm($, 'switched off')
  const now = await $.clock.now()
  const stop = keepWarmStop(warm, now)
  if (stop !== null) return stopKeepWarm($, stop)
  // No effort is named, so the fork reads the chat's cache on every model.
  const turnsBefore = turnsStarted
  const result = await $.model.fork({ prompt: PING })
  const after = await read($, keepWarm)
  // A turn that started meanwhile wrote the cache and set the next ping itself.
  if (after === null || !after.isOn || turnsStarted !== turnsBefore) return
  if (!result.isAnswered && result.reason === 'nothing-to-fork') return stopKeepWarm($, 'nothing to keep warm')
  if (result.isAnswered && result.usage.cache_read_input_tokens > 0) {
    const counted = { ...after, pings: after.pings + 1, failures: 0 }
    await update($, keepWarm, () => counted)
    await update($, clock, value => (value === null ? value : { ...value, lastAt: now }))
    await startTicker($)
    if (counted.pings >= MAX_PINGS) return stopKeepWarm($, `${MAX_PINGS} pings sent`)
    return schedulePing($)
  }
  const counted = { ...after, failures: after.failures + 1 }
  await update($, keepWarm, () => counted)
  const stopNow = keepWarmStop(counted, now)
  if (stopNow !== null) return stopKeepWarm($, stopNow)
  const ended = await $.clock.now()
  await schedulePing($, { at: ended + PING_RETRY_MS, tookMs: ended - now })
}

// Starts the countdown for a reply whose request went out at `lastAt`. The
// reply's transcript line can land a moment after the turn ends, so when the
// newest line found is older than the request, the transcript is read once more
// two seconds later.
async function restart($: EngineInterface, lastAt: number) {
  const found = await detect($)
  await update($, clock, () => ({ lastAt, kind: found.kind }))
  await update($, isAsked, () => false)
  await update($, keepWarm, value => {
    if (value === null || !value.isOn) return null
    return value.isArmed ? { ...value, isArmed: false, startedAt: lastAt } : value
  })
  await startTicker($)
  await schedulePing($)
  rereader?.cancel()
  rereader = null
  if (found.at !== null && found.at >= lastAt) return
  rereader = $.clock.after(RETRY_MS, async () => {
    rereader = null
    const again = await detect($)
    if (again.at === null || again.at < lastAt) return
    const current = await read($, clock)
    if (current?.lastAt !== lastAt || current.kind === again.kind) return
    await update($, clock, () => ({ lastAt, kind: again.kind }))
    await schedulePing($)
  })
}

// Leaves the request file the handoff plugin looks for. A write that fails leaves
// the button up to try again.
async function askHandoff($: EngineInterface) {
  if (isAsking) return
  isAsking = true
  try {
    if (await read($, isAsked)) return
    const path = `${await configFolder($)}/handoffs/.request-${await $.session.id()}`
    await $.fs.write(path, String(await $.clock.now()))
    await update($, isAsked, () => true)
  } catch {
    $.ui.toast('The handoff request could not be written.')
  } finally {
    isAsking = false
  }
}

export const register: Register = on => {
  folder = null
  transcript = null
  requestAt = null
  isTurnRunning = false
  stopTimers()

  on('session.start', async ($, e, next) => {
    const result = await next(e)
    await $.command.register({
      name: 'keepwarm',
      description: 'Keep the prompt cache warm with a short ping before it goes cold, until you type a prompt',
      argumentHint: '[on|off]',
      immediate: true,
    })
    await $.command.register({
      name: 'cacheclock',
      description: 'Show or hide the prompt cache countdown above the prompt',
      argumentHint: '[show|hide]',
      immediate: true,
    })
    const stored = await $.store.get('isShown')
    await update($, isShown, () => stored !== false)
    await readSwitches($)
    const usage = await $.session.usage().catch(() => undefined)
    const count = usage?.context.tokens
    if (count !== undefined) await update($, tokens, () => count)
    // A resumed chat counts from its newest reply in the transcript.
    const found = await detect($)
    if (found.at !== null) {
      const at = found.at
      await update($, clock, value => value ?? { lastAt: at, kind: found.kind })
      await startTicker($)
    }
    return result
  })

  on('session.end', async ($, e, next) => {
    if (e.reason === 'clear') {
      stopTimers()
      transcript = null
      requestAt = null
      await update($, clock, () => null)
      await update($, keepWarm, () => null)
      await update($, isAsked, () => false)
    }
    return next(e)
  })

  on('session.measure', async ($, e, next) => {
    const count = e.context.tokens
    if (count !== undefined) await update($, tokens, () => count)
    return next(e)
  })

  // A prompt the person typed stops keep warm. It never changes the prompt.
  on('prompt.submit', async ($, e, next) => {
    // composer is the terminal, and bridge is a remote-control client. sdk is the
    // desktop app, but also `claude -p` and scripts, which draw on no surface.
    const typed =
      e.origin.kind === 'composer' ||
      e.origin.kind === 'bridge' ||
      (e.origin.kind === 'sdk' && (await $.session.surfaces()).length > 0)
    if (typed && e.command === undefined && e.isMeta !== true) {
      if ((await read($, keepWarm))?.isArmed !== true) await stopKeepWarm($, 'you typed a prompt')
      await readSwitches($)
    }
    return next(e)
  }).catch(($, e, next) => next(e))

  on('turn.start', async ($, e, next) => {
    if (e.agentId === undefined) {
      isTurnRunning = true
      turnsStarted += 1
      requestAt = null
    }
    return next(e)
  })

  on('turn.step', async function* ($, e, next) {
    if (e.agentId === undefined) requestAt = await $.clock.now()
    return yield* next(e)
  })

  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    if (e.agentId === undefined) {
      isTurnRunning = false
      // A turn with no usage made no request, so the cache was not written.
      if (e.usage !== undefined) await restart($, requestAt ?? (await $.clock.now()))
      else await schedulePing($)
    }
    return result
  })

  on('command.run', { command: 'keepwarm' }, async ($, e) => {
    const arg = e.args.trim().toLowerCase()
    if (arg !== '' && arg !== 'on' && arg !== 'off') return { text: 'Usage: /keepwarm [on|off]' }
    const current = await read($, keepWarm)
    const turnOn = arg === '' ? !(current?.isOn ?? false) : arg === 'on'
    if (!turnOn) {
      await stopKeepWarm($, 'turned off')
      return { text: 'Keep warm is off.' }
    }
    if ((await read($, switches)).isOff) return { text: 'Cache clock is switched off in switches.json.' }
    const startedAt = await $.clock.now()
    const state = await read($, clock)
    const isArmed = state === null || leftMs(state.lastAt, state.kind, startedAt) === 0
    await update($, keepWarm, () => ({ isOn: true, isArmed, startedAt, pings: 0, failures: 0, note: '' }))
    await schedulePing($)
    const when = isArmed ? 'The cache is cold now, so it starts after the next reply. ' : ''
    return {
      text:
        `Keep warm is on. ${when}${PING_LEAD_MS / 1000} seconds before the cache would go cold, it sends a one-word ping, ` +
        'which reads the whole chat from the cache and is billed like any request. ' +
        `It stops when you type a prompt, after ${MAX_PINGS} pings, after ${MAX_KEEP_WARM_MS / HOUR_MS} hours, ` +
        `or after ${MAX_FAILURES} pings in a row that do not read the cache.`,
    }
  })

  on('command.run', { command: 'cacheclock' }, async ($, e) => {
    const arg = e.args.trim().toLowerCase()
    if (arg !== '' && arg !== 'show' && arg !== 'hide') return { text: 'Usage: /cacheclock [show|hide]' }
    const show = arg === '' ? !(await read($, isShown)) : arg === 'show'
    await update($, isShown, () => show)
    await $.store.set('isShown', show)
    return { text: show ? 'Cache clock shown.' : 'Cache clock hidden.' }
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const state = await read($, clock)
    const flags = await read($, switches)
    if (e.props.hasSurvey || state === null || flags.isOff || flags.isHidden || !(await read($, isShown))) return next(e)
    const { Box, Button, Text } = $.ui.resolve(e)
    const left = leftMs(state.lastAt, state.kind, await $.clock.now())
    const warm = await read($, keepWarm)
    let keep = ''
    if (warm?.isOn === true) keep = ` · keep warm on (${warm.pings}/${MAX_PINGS})`
    else if (warm !== null && warm.note !== '') keep = ` · keep warm stopped: ${warm.note}`
    if (left > 0) {
      const kind = state.kind === 'unknown' ? '5m?' : state.kind
      return (
        <Box>
          <Text dimColor>
            Cache warm · {formatLeft(left)} left ({kind}){keep}
          </Text>
        </Box>
      )
    }
    const big = isBig(await read($, tokens))
    const asked = await read($, isAsked)
    if (!big || asked) {
      return (
        <Box>
          <Text dimColor>
            Cache cold{asked ? ' · handoff asked for' : ''}
            {keep}
          </Text>
        </Box>
      )
    }
    return (
      <Box>
        <Text dimColor>Cache cold · the next reply writes the whole chat to the cache again{keep} </Text>
        <Button key="handoff" label="Hand off to a new chat" onPress={() => askHandoff($)} />
      </Box>
    )
  })
}
