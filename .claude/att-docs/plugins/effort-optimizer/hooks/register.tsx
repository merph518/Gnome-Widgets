// Picks a reasoning effort level for each typed prompt and offers it above the prompt.
//
// After a prompt starts a turn, a small model reads it and picks one of the five
// levels. In suggest mode, the default, the band above the prompt offers the pick
// and Switch applies it. In auto mode the pick is applied before the turn's first
// request goes out. A level is applied through the /config effort row when there is
// one the user may change; otherwise it is put on each main-chat request until the
// user changes the level themselves. switches.json in the configuration folder turns
// the plugin off or hides the band.

import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { EffortLevel, EffortMode, EffortSuggestion, EffortSwitches } from '../types'
import { NAMES, classifierRequest, configDir, isEffort, isEffortRow, optionFor, parsePick, parseSwitches } from './effort'

const mode = atom({ plugin: 'effort-optimizer', key: 'mode' } as const, 'suggest' as EffortMode)
const switches = atom({ plugin: 'effort-optimizer', key: 'switches' } as const, { isOff: false, isHidden: false } as EffortSwitches)
const suggestion = atom({ plugin: 'effort-optimizer', key: 'suggestion' } as const, null, { shape: 'suggestion-1' })
const hold = atom({ plugin: 'effort-optimizer', key: 'hold' } as const, null)
const turnLevel = atom({ plugin: 'effort-optimizer', key: 'turnLevel' } as const, null)

// The log keeps its newest lines up to this size.
const LOG_CHARS = 200_000

const USAGE = 'Usage: /effort-optimizer [suggest|auto]'

// Whether the user switched the log on.
let isLogging = false
// A typed prompt waiting for its turn to start, then the turn it started.
let pending: string | null = null
let bound: { turnId: string; text: string } | null = null
// The level the newest main-chat request carried before any change of ours.
let seen: EffortLevel | null = null
// Goes up with each prompt and each /clear, so a pick that comes back after
// either is dropped.
let pickGeneration = 0
let folder: string | null = null

async function configFolder($: EngineInterface): Promise<string> {
  folder ??= configDir(await $.env.get('HOME'), await $.env.get('CLAUDE_CONFIG_DIR'))
  return folder
}

async function log($: EngineInterface, line: string): Promise<void> {
  if (!isLogging) return
  try {
    const path = `${await configFolder($)}/mods-logs/effort-optimizer.log`
    const before = await $.fs.read(path).catch(() => '')
    const stamp = new Date(await $.clock.now()).toISOString()
    const text = `${before}${stamp} ${line}\n`
    await $.fs.write(path, text.length > LOG_CHARS ? text.slice(text.length - LOG_CHARS) : text)
  } catch {
    // A log that cannot be written never stops the plugin.
  }
}

async function readSwitches($: EngineInterface): Promise<EffortSwitches> {
  const path = `${await configFolder($)}/mods/switches.json`
  const text = await $.fs.read(path).then(
    value => (typeof value === 'string' ? value : undefined),
    () => undefined,
  )
  const value = parseSwitches(text)
  await update($, switches, () => value)
  return value
}

// Finds the /config effort row, when this build has one.
async function effortRow($: EngineInterface) {
  try {
    return (await $.config.list()).find(isEffortRow)
  } catch {
    return undefined
  }
}

async function lastReply($: EngineInterface): Promise<string> {
  try {
    const messages = await $.session.messages()
    return messages.findLast(message => message.role === 'assistant')?.text ?? ''
  } catch {
    return ''
  }
}

async function pick($: EngineInterface, text: string, signal?: AbortSignal) {
  const result = await $.model.complete(classifierRequest(text, await lastReply($)), signal ? { signal } : undefined)
  if (!result.isAnswered) {
    await log($, `no pick: ${result.reason}`)
    return null
  }
  const chosen = parsePick(result.text)
  await log($, chosen === null ? `no level in the reply: ${result.text.slice(0, 80)}` : `pick ${chosen.level}`)
  return chosen
}

// Applies `level` from now on: to the rest of turn `turnId`, and to later turns
// through the effort row or, failing that, the hold. `base` is the level the
// requests carry now, used when no request has been seen since a reload.
// Returns what was done, and whether anything was.
async function apply($: EngineInterface, level: EffortLevel, turnId: string, base: EffortLevel | null) {
  const row = await effortRow($)
  const option = row === undefined ? undefined : optionFor(row, level)
  if (row !== undefined && option === undefined) {
    await log($, `${level} is not offered by ${row.key}; nothing changed`)
    return { isApplied: false, note: `${NAMES[level]} is not offered by /config; nothing changed` }
  }
  await update($, turnLevel, () => ({ turnId, level }))
  let why = 'no effort setting'
  if (row !== undefined && row.isLocked) why = 'effort setting locked'
  if (row !== undefined && option !== undefined && !row.isLocked) {
    const result = await $.config.set({ key: row.key, value: option }).catch((error: unknown) => ({
      deny: String(error),
    }))
    if (result.deny === undefined) {
      await update($, hold, () => null)
      await log($, `set ${row.key} to ${option}`)
      return { isApplied: true, note: `${NAMES[level]} effort set in /config` }
    }
    why = `setting refused: ${result.deny}`
  }
  await update($, hold, () => ({ level, base: seen ?? base }))
  await log($, `holding ${level} per request (${why})`)
  return { isApplied: true, note: `${NAMES[level]} effort sent with each request (${why})` }
}

// Suggest mode: asks for a pick without holding up the turn, then offers it.
async function suggest($: EngineInterface, id: number, turnId: string, text: string, current: EffortLevel) {
  const chosen = await pick($, text)
  if (chosen === null || id !== pickGeneration) return
  if (chosen.level === current) {
    await update($, suggestion, () => null)
    return
  }
  const offer: EffortSuggestion = {
    id,
    turnId,
    level: chosen.level,
    current,
    why: chosen.why,
    phase: 'offer',
    note: '',
  }
  await update($, suggestion, () => offer)
}

async function press($: EngineInterface) {
  const offer = await read($, suggestion)
  if (offer === null || offer.phase !== 'offer') return
  // offer.current may be a level we hold; the hold's own base is what requests carry.
  const base = (await read($, hold))?.base ?? offer.current
  const { note } = await apply($, offer.level, offer.turnId, base)
  await update($, suggestion, value => (value?.id === offer.id ? { ...value, phase: 'applied' as const, note } : value))
}

async function dismiss($: EngineInterface, id: number) {
  await update($, suggestion, value => (value?.id === id ? null : value))
}

export const register: Register = (on, options) => {
  isLogging = options.log === true
  pending = null
  bound = null
  seen = null
  pickGeneration = 0
  folder = null

  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'effort-optimizer',
      description: 'Show or switch the effort optimizer between suggest and auto mode',
      argumentHint: '[suggest|auto]',
      immediate: true,
    })
    const stored = await $.store.get('mode')
    await update($, mode, () => (stored === 'auto' ? 'auto' : 'suggest'))
    await readSwitches($)
    const row = await effortRow($)
    await log($, row === undefined ? 'no effort row in /config' : `effort row ${row.key}${row.isLocked ? ' (locked)' : ''}`)
    return next(e)
  })

  on('session.end', async ($, e, next) => {
    if (e.reason === 'clear') {
      pending = null
      bound = null
      seen = null
      // A pick still out for the old conversation is dropped when it returns.
      pickGeneration += 1
      await update($, suggestion, () => null)
      await update($, hold, () => null)
      await update($, turnLevel, () => null)
    }
    return next(e)
  })

  // Watches typed prompts and never changes them. A prompt typed while a turn runs
  // joins that turn, which already has its level.
  on('prompt.submit', async ($, e, next) => {
    pending = null
    // composer is the terminal and bridge a remote-control client. sdk is the
    // desktop app, but also `claude -p` and scripts, which draw on no surface.
    const typed =
      e.origin.kind === 'composer' ||
      e.origin.kind === 'bridge' ||
      (e.origin.kind === 'sdk' && (await $.session.surfaces()).length > 0)
    if (e.command === undefined && e.isMeta !== true && e.turnId === undefined && typed && e.text.trim() !== '') {
      if (!(await readSwitches($)).isOff) {
        pending = e.text.trim()
        pickGeneration += 1
        await update($, suggestion, () => null)
      }
    }
    return next(e)
  }).catch(($, e, next) => next(e))

  on('turn.start', ($, e, next) => {
    if (e.agentId === undefined) {
      bound = pending !== null && pending === e.text.trim() ? { turnId: e.turnId, text: pending } : null
      pending = null
    }
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    const current = await read($, turnLevel)
    if (current !== null && current.turnId === e.turnId) {
      await update($, turnLevel, () => null)
    }
    return next(e)
  })

  on('turn.step', async function* ($, e, next) {
    let level: EffortLevel | null = null
    try {
      if (e.agentId === undefined && isEffort(e.effort) && !(await read($, switches)).isOff) {
        const own = e.effort
        const held = await read($, hold)
        if (held !== null && own !== held.base) {
          await update($, hold, () => null)
          await log($, `level changed by hand to ${own}; stopped sending ${held.level}`)
        }
        seen = own
        if (e.index === 0 && bound !== null && bound.turnId === e.turnId) {
          const { text } = bound
          bound = null
          const id = pickGeneration
          if ((await read($, mode)) === 'auto') {
            const chosen = await pick($, text, next.signal)
            if (chosen === null) {
              await update($, hold, () => null)
            } else if (chosen.level !== own) {
              const result = await apply($, chosen.level, e.turnId, own)
              let { note } = result
              const held = await read($, hold)
              if (!result.isApplied && held !== null) {
                await update($, hold, () => null)
                note = `${NAMES[chosen.level]} is not offered by /config; stopped sending ${NAMES[held.level]}`
              }
              const applied: EffortSuggestion = {
                id,
                turnId: e.turnId,
                level: chosen.level,
                current: own,
                why: chosen.why,
                phase: 'applied',
                note,
              }
              await update($, suggestion, () => applied)
            } else {
              await update($, hold, () => null)
            }
          } else {
            const current = (await read($, hold))?.level ?? own
            $.clock.after(0, () => {
              suggest($, id, e.turnId, text, current).catch((error: unknown) => log($, `no offer: ${String(error)}`))
            })
          }
        }
        const forTurn = await read($, turnLevel)
        level = forTurn !== null && forTurn.turnId === e.turnId ? forTurn.level : ((await read($, hold))?.level ?? null)
        if (level === own) level = null
      }
    } catch (error) {
      await log($, `step left as it was: ${String(error)}`)
      level = null
    }
    if (level === null) return yield* next(e)
    await log($, `request ${e.turnId}#${e.index}: ${String(e.effort)} -> ${level}`)
    return yield* next({ ...e, effort: level })
  })

  on('command.run', { command: 'effort-optimizer' }, async ($, e) => {
    const arg = e.args.trim().toLowerCase()
    const off = (await read($, switches)).isOff ? ' It is switched off in switches.json.' : ''
    if (arg === '') {
      const row = await effortRow($)
      const held = await read($, hold)
      const via = row === undefined ? 'per request (no effort setting)' : row.isLocked ? 'per request (effort setting locked)' : `/config ${row.key}`
      const holding = held === null ? '' : ` Holding ${NAMES[held.level]}.`
      return { text: `Effort optimizer: ${await read($, mode)} mode; applies levels through ${via}.${holding}${off}` }
    }
    if (arg !== 'suggest' && arg !== 'auto') return { text: USAGE }
    await $.store.set('mode', arg)
    await update($, mode, () => arg)
    await update($, hold, () => null)
    await update($, turnLevel, () => null)
    await update($, suggestion, () => null)
    await log($, `mode ${arg}`)
    const what = arg === 'auto' ? 'picks a level and applies it before each typed prompt runs' : 'offers a level above the prompt'
    return { text: `Effort optimizer: ${arg} mode. It ${what}.${off}` }
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const offer = await read($, suggestion)
    const state = await read($, switches)
    if (e.props.hasSurvey || offer === null || state.isOff || state.isHidden) return next(e)
    const { Box, Button, Text } = $.ui.resolve(e)
    if (offer.phase === 'applied') {
      return (
        <Box>
          <Text dimColor>Effort: {offer.note}</Text>
        </Box>
      )
    }
    const now = offer.current === null ? '' : ` (now ${NAMES[offer.current]})`
    const why = offer.why === '' ? '' : ` · ${offer.why}`
    return (
      <Box>
        <Text dimColor>
          Effort: {NAMES[offer.level]} fits this prompt{now}
          {why}{' '}
        </Text>
        <Button key="switch" label={`Switch to ${NAMES[offer.level]}`} onPress={() => press($)} />
        <Text> </Text>
        <Button key="dismiss" label="Dismiss" onPress={() => dismiss($, offer.id)} />
      </Box>
    )
  })
}
