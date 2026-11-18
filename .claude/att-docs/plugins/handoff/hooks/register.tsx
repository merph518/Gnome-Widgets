// Writes a handoff of a long chat and offers a fresh chat started from it.
//
// Once the context passes OFFER_AT tokens, a band above the prompt offers Refresh.
// Refresh reads the chat, saves a plain draft, then has a fork of the chat write the
// full handoff, removes anything that looks like a secret, and saves it under
// handoffs/ in the configuration folder. The band then offers Copy, Open file and
// Start new chat with it. /handoff writes one at once, /fresh shows the band, and the
// model can show it through the `refresh` tool. Another plugin asks for a handoff by
// creating handoffs/.request-<session id>. switches.json in the configuration folder
// turns the plugin off or hides the band.

import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { HandoffRun, HandoffSwitches } from '../types'
import {
  OFFER_AT,
  SNOOZE,
  STEPS,
  WRITE_UP,
  clipboardCommands,
  configDir,
  detached,
  draftFrom,
  newChatLink,
  parseSwitches,
  scrub,
  stamp,
} from './handoff'

const run = atom({ plugin: 'handoff', key: 'run' } as const, null, { shape: 'run-1' })
const switches = atom({ plugin: 'handoff', key: 'switches' } as const, { isOff: false, isHidden: false } as HandoffSwitches)
const offerAt = atom({ plugin: 'handoff', key: 'offerAt' } as const, OFFER_AT)
const tokens = atom({ plugin: 'handoff', key: 'tokens' } as const, null as number | null)

// How often the request folder is checked for a request file.
const POLL_MS = 5000
// The log keeps its newest lines up to this size.
const LOG_CHARS = 200_000
const PASTE = 'Paste with Ctrl+Shift+V in a terminal, or Ctrl+V elsewhere.'

// Goes up with each run and each /clear, so a run that finishes after either is dropped.
let generation = 0
let poll: { cancel: () => void } | null = null
let folder: string | null = null

async function configFolder($: EngineInterface): Promise<string> {
  folder ??= configDir(await $.env.get('HOME'), await $.env.get('CLAUDE_CONFIG_DIR'))
  return folder
}

async function handoffDir($: EngineInterface): Promise<string> {
  return `${await configFolder($)}/handoffs`
}

async function log($: EngineInterface, line: string): Promise<void> {
  try {
    const path = `${await handoffDir($)}/handoff.log`
    const before = await $.fs.read(path).catch(() => '')
    const stampNow = new Date(await $.clock.now()).toISOString()
    const text = `${before}${stampNow} ${line}\n`
    await $.fs.write(path, text.length > LOG_CHARS ? text.slice(text.length - LOG_CHARS) : text)
  } catch {
    // A log that cannot be written never stops the plugin.
  }
}

async function readSwitches($: EngineInterface): Promise<HandoffSwitches> {
  const text = await $.fs.read(`${await configFolder($)}/mods/switches.json`).then(
    value => (typeof value === 'string' ? value : undefined),
    () => undefined,
  )
  const value = parseSwitches(text)
  await update($, switches, () => value)
  return value
}

// Changes the run on the band only while it is still run `id`.
async function patch($: EngineInterface, id: number, change: Partial<HandoffRun>) {
  await update($, run, value => (value !== null && value.id === id ? { ...value, ...change } : value))
}

function newRun(id: number, phase: HandoffRun['phase']): HandoffRun {
  return { id, phase, step: 0, draftPath: null, path: null, note: '' }
}

// Shows the offer, unless a handoff is already under way or finished on the band.
async function offer($: EngineInterface) {
  await update($, run, value => (value === null || value.phase === 'failed' ? newRun(generation, 'offer') : value))
}

// Shows the offer for /fresh and the refresh tool, and says what the switches allowed.
async function show($: EngineInterface): Promise<'off' | 'hidden' | 'shown'> {
  const state = await readSwitches($)
  if (state.isOff) return 'off'
  await offer($)
  return state.isHidden ? 'hidden' : 'shown'
}

async function isRunning($: EngineInterface): Promise<boolean> {
  return (await read($, run))?.phase === 'running'
}

async function write($: EngineInterface): Promise<void> {
  if (await isRunning($)) return
  generation += 1
  const id = generation
  await update($, run, () => newRun(id, 'running'))
  let draftPath: string | null = null
  try {
    const messages = await $.session.messages()
    if (id !== generation) return
    await patch($, id, { step: 1 })

    const dir = await handoffDir($)
    const name = stamp(await $.clock.now())
    draftPath = `${dir}/${name}-draft.md`
    await $.fs.write(draftPath, scrub(draftFrom(messages)))
    if (id !== generation) return
    await patch($, id, { step: 2, draftPath })

    const reply = await $.model.fork({ prompt: WRITE_UP })
    if (id !== generation) return
    if (!reply.isAnswered || reply.text.trim() === '') {
      const why = reply.isAnswered ? 'empty-reply' : reply.reason
      await patch($, id, { phase: 'failed', note: `The handoff was not written (${why}). The draft is saved at ${draftPath}.` })
      await log($, `failed (${why}); draft ${draftPath}`)
      return
    }
    await patch($, id, { step: 3 })

    const text = scrub(reply.text.trim())
    await patch($, id, { step: 4 })

    const path = `${dir}/${name}-handoff.md`
    if (id !== generation) return
    await $.fs.write(path, `${text}\n`)
    await patch($, id, { phase: 'done', step: STEPS.length, path, note: `Saved to ${path}` })
    await log($, `saved ${path}`)
  } catch (error) {
    if (id !== generation) return
    const kept = draftPath === null ? '' : ` The draft is saved at ${draftPath}.`
    await patch($, id, { phase: 'failed', note: `The handoff was not written: ${String(error)}.${kept}` })
    await log($, `failed: ${String(error)}`)
  }
}

function startWrite($: EngineInterface) {
  $.clock.after(0, () => {
    write($).catch(() => undefined)
  })
}

// Runs `argv` without holding the band open on it. Returns its exit status, 127 when
// the command is not installed.
async function runDetached($: EngineInterface, argv: readonly string[], stdin?: string): Promise<number> {
  const result = await $.process.run(detached(argv), { timeoutMs: 10_000, ...(stdin === undefined ? {} : { stdin }) })
  return result.exitCode
}

async function savedText($: EngineInterface, path: string): Promise<string> {
  const text = await $.fs.read(path)
  return scrub(typeof text === 'string' ? text : '')
}

async function copy($: EngineInterface, id: number, path: string) {
  let note: string
  try {
    const text = await savedText($, path)
    const commands = clipboardCommands({
      WAYLAND_DISPLAY: await $.env.get('WAYLAND_DISPLAY'),
      DISPLAY: await $.env.get('DISPLAY'),
      XDG_SESSION_TYPE: await $.env.get('XDG_SESSION_TYPE'),
    })
    const first = commands[0]
    if (first === undefined) {
      note = 'Copy failed: there is no Wayland or X11 display to copy to.'
    } else {
      // With every command missing, the note names the package for the session's own
      // display server, the first command tried.
      note = `Copy failed: install ${first.apt} (sudo apt install ${first.apt}).`
      for (const command of commands) {
        const code = await runDetached($, command.argv, text)
        if (code === 0) {
          note = `Copied. ${PASTE}`
          break
        }
        if (code !== 127) note = `Copy failed: ${command.argv[0]} exited with status ${code}.`
      }
    }
  } catch (error) {
    note = `Copy failed: ${String(error)}`
  }
  await patch($, id, { note })
}

async function open($: EngineInterface, id: number, target: string, what: string) {
  let note: string
  try {
    const code = await runDetached($, ['xdg-open', target])
    note =
      code === 0
        ? what
        : code === 127
          ? 'Could not open it: install xdg-utils (sudo apt install xdg-utils).'
          : `Could not open it: xdg-open exited with status ${code}.`
  } catch (error) {
    note = `Could not open it: ${String(error)}`
  }
  await patch($, id, { note })
}

async function startNew($: EngineInterface, id: number, path: string) {
  try {
    await open($, id, newChatLink(await savedText($, path), path), 'Opened a new chat with the handoff.')
  } catch (error) {
    await patch($, id, { note: `Could not start a new chat: ${String(error)}` })
  }
}

// Closing hides the band until the context grows by SNOOZE tokens more.
async function close($: EngineInterface, id: number) {
  const now = await read($, tokens)
  const next = Math.max(OFFER_AT, (now ?? 0) + SNOOZE)
  await update($, offerAt, () => next)
  await update($, run, value => (value !== null && value.id === id && value.phase !== 'running' ? null : value))
}

async function checkRequest($: EngineInterface) {
  try {
    if ((await read($, switches)).isOff) return
    // A request that arrives during a run waits for the check after it.
    if (await isRunning($)) return
    const path = `${await handoffDir($)}/.request-${await $.session.id()}`
    if (!(await $.fs.exists(path))) return
    await $.process.run(['rm', '-f', path])
    await log($, `request file ${path}`)
    await write($)
  } catch {
    // The next check tries again.
  }
}

export const register: Register = on => {
  generation = 0
  folder = null
  poll?.cancel()
  poll = null

  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'handoff', description: 'Write a handoff of this chat now', immediate: true })
    await $.command.register({ name: 'fresh', description: 'Show the band that offers a handoff and a fresh chat', immediate: true })
    await $.tool.register({
      name: 'refresh',
      description:
        'Shows the Refresh band above the prompt, which writes a handoff of this chat and offers to start a new chat from it. Call it when the user asks for a handoff, a refresh or a fresh chat.',
      inputSchema: { type: 'object', properties: {} },
      isDeferred: false,
    })
    await readSwitches($)
    poll?.cancel()
    poll = $.clock.every(POLL_MS, () => {
      checkRequest($).catch(() => undefined)
    })
    return next(e)
  })

  on('session.end', async ($, e, next) => {
    if (e.reason === 'clear') {
      generation += 1
      await update($, run, () => null)
      await update($, offerAt, () => OFFER_AT)
      await update($, tokens, () => null)
    }
    return next(e)
  })

  on('session.measure', async ($, e, next) => {
    if (e.changed.includes('context') && e.context.tokens !== undefined) {
      const count = e.context.tokens
      await update($, tokens, () => count)
      if (count >= (await read($, offerAt)) && !(await readSwitches($)).isOff) await offer($)
    }
    return next(e)
  })

  on('command.run', { command: 'handoff' }, async $ => {
    if ((await readSwitches($)).isOff) return { text: 'Handoff is switched off in switches.json.' }
    if (await isRunning($)) return { text: 'A handoff is already being written.' }
    startWrite($)
    return { text: `Writing a handoff to ${await handoffDir($)}. The band above the prompt shows its steps.` }
  })

  on('command.run', { command: 'fresh' }, async $ => {
    const text = {
      off: 'Handoff is switched off in switches.json.',
      hidden: 'The band is hidden in switches.json. Run /handoff to write a handoff.',
      shown: 'Refresh is above the prompt.',
    }
    return { text: text[await show($)] }
  })

  on('tool.call', { tool: 'mcp__handoff__refresh' }, async $ => {
    const result = {
      off: 'Handoff is switched off in switches.json, so nothing was shown.',
      hidden: 'The band is hidden in switches.json. The user can run /handoff to write a handoff.',
      shown: 'The Refresh band is now above the prompt. The user presses Refresh to write the handoff.',
    }
    return { result: result[await show($)] }
  }).catch(() => ({ result: 'The Refresh band could not be shown. The user can run /handoff instead.' }))

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const current = await read($, run)
    const state = await read($, switches)
    if (e.props.hasSurvey || current === null || state.isOff || state.isHidden) return next(e)
    const { Box, Button, Progress, Text } = $.ui.resolve(e)
    const id = current.id

    if (current.phase === 'offer') {
      const count = await read($, tokens)
      const size = count === null ? '' : ` The chat is at ${Math.round(count / 1000)}k tokens.`
      return (
        <Box>
          <Text dimColor>Handoff:{size} Write a handoff and start fresh? </Text>
          <Button key="refresh" label="Refresh" onPress={() => startWrite($)} />
          <Text> </Text>
          <Button key="close" label="Close" onPress={() => close($, id)} />
        </Box>
      )
    }

    const bars = STEPS.map((label, index) => {
      const isDone = index < current.step
      const isNow = index === current.step && current.phase === 'running'
      return (
        <Progress
          key={`step-${index}`}
          label={label}
          {...(isNow ? {} : { value: isDone ? 1 : 0 })}
          valueText={isDone ? 'done' : isNow ? 'working' : current.phase === 'failed' && index === current.step ? 'failed' : 'waiting'}
        />
      )
    })
    const path = current.path
    const draft = current.draftPath
    return (
      <Box flexDirection="column">
        <Text dimColor>Handoff</Text>
        {bars}
        {current.note === '' ? null : <Text dimColor>{current.note}</Text>}
        {current.phase === 'running' ? null : (
          <Box>
            {current.phase === 'done' && path !== null ? (
              <Box>
                <Button key="copy" label="Copy" onPress={() => copy($, id, path)} />
                <Text> </Text>
                <Button key="open" label="Open file" onPress={() => open($, id, path, `Opened ${path}`)} />
                <Text> </Text>
                <Button key="new" label="Start new chat with it" onPress={() => startNew($, id, path)} />
                <Text> </Text>
              </Box>
            ) : draft !== null ? (
              <Box>
                <Button key="open" label="Open draft" onPress={() => open($, id, draft, `Opened ${draft}`)} />
                <Text> </Text>
              </Box>
            ) : null}
            <Button key="close" label="Close" onPress={() => close($, id)} />
          </Box>
        )}
      </Box>
    )
  })
}
