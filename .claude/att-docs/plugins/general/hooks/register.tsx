// The general plugin's repository hooks, and the oversee loop's row above the prompt.
//
// HOOKS lists every script and the event it answers. Each hook hands the event to its
// scripts through run.sh, with the event's JSON on stdin, and reads their answers with
// classic.ts. run.sh reads the repository's .claude/skills/repo-hooks/extension.json
// switches and steps aside where the repository's own settings register the script.
// Each hook runs its scripts beside next(e), so the plugins and settings hooks beneath
// still see the event, and adds their answers to the result next(e) gave.

import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, Timer } from 'claude-code'

import type { GeneralLoop, GeneralSession } from '../types'
import { combine, merge, parseHookOutput, toolInput } from './classic'
import type { HookOutput } from './classic'

const session = atom({ plugin: 'general', key: 'session' } as const, null)
const loop = atom({ plugin: 'general', key: 'loop' } as const, null, { shape: 'loop-1' })

const SECOND = 1000
// How often the row rereads the loop's marker while a loop is active or paused, so a
// change made from another terminal shows.
const LOOP_POLL_MS = 30 * SECOND

type Script = { args: readonly string[]; timeoutMs: number; status?: string }

// Each entry is `run.sh <args>`, in the order a run starts them.
const HOOKS = {
  PreToolUse: {
    Bash: [
      { args: ['prTestingGate', 'pr_testing_gate.py'], timeoutMs: 90 * SECOND },
      { args: ['--default-on', 'strayFiles', 'stray_files_gate.py'], timeoutMs: 30 * SECOND },
    ],
  },
  PostToolUse: {
    Bash: [{ args: ['mergeWatchReminder', 'remind-pr-merge-watch.sh'], timeoutMs: 10 * SECOND }],
    EditOrWrite: [
      { args: ['prettierOnSave', 'prettier-on-save.sh'], timeoutMs: 60 * SECOND, status: 'Formatting...' },
      { args: ['testOnEdit', 'test-on-edit.sh'], timeoutMs: 180 * SECOND, status: 'Running related tests...' },
    ],
  },
  Stop: [{ args: ['--default-on', 'implementLoop', 'implement_loop.py'], timeoutMs: 30 * SECOND }],
  SessionStart: [{ args: ['--default-on', 'implementLoop', 'implement_loop.py'], timeoutMs: 30 * SECOND }],
} satisfies Record<string, Record<string, Script[]> | Script[]>

// Runs loop.py for this session, but only in a repository that has loop state: the
// script makes its state folder whenever it runs, and a repository that never ran a
// loop should not gain one. With no state it prints nothing and exits 0.
const LOOP_PY =
  'd=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || exit 0; ' +
  'test -d "${d%/*}/.claude/oversee/loops" || exit 0; exec python3 "$0" "$@"'

// The loop row's refresh, running while a loop is active or paused.
let loopPoll: Timer | undefined

// The engine's own environment names no session, so the scripts get it here.
async function hookEnv($: EngineInterface): Promise<Record<string, string>> {
  return {
    CLAUDE_PROJECT_DIR: await $.session.root(),
    CLAUDE_PLUGIN_ROOT: $.plugin.root,
    CLAUDE_CODE_SESSION_ID: await $.session.id(),
  }
}

// Runs `run.sh <args>` with the payload on stdin. A script that cannot start or runs
// past its time gives no answer, and the event goes on without it; one that fails
// with any exit but 2 says so in the transcript.
async function runHook(
  $: EngineInterface,
  event: string,
  args: readonly string[],
  payload: unknown,
  timeoutMs: number,
): Promise<HookOutput | undefined> {
  try {
    const ran = await $.process.run(['bash', `${$.plugin.root}/hooks/run.sh`, ...args], {
      stdin: JSON.stringify(payload),
      env: await hookEnv($),
      timeoutMs,
    })
    if (ran.exitCode !== 0 && ran.exitCode !== 2) {
      $.ui.log(`${args.at(-1)} failed (exit ${ran.exitCode})${ran.stderr.trim() ? `: ${ran.stderr.trim()}` : ''}`)
    }
    return parseHookOutput(event, ran.exitCode, ran.stdout, ran.stderr)
  } catch (error) {
    $.ui.log(`${args.at(-1)} did not finish: ${String(error)}`)
    return undefined
  }
}

// Runs scripts one after another, so the related tests run on the formatted file,
// showing each one's status line while it runs.
async function runAll(
  $: EngineInterface,
  event: string,
  scripts: readonly Script[],
  payload: unknown,
): Promise<HookOutput> {
  const outputs: (HookOutput | undefined)[] = []
  for (const script of scripts) {
    if (script.status !== undefined) $.ui.status(script.status)
    outputs.push(await runHook($, event, script.args, payload, script.timeoutMs))
    if (script.status !== undefined) $.ui.status(undefined)
  }
  const all = combine(outputs)
  tell($, all)
  return all
}

// A script's systemMessage is a line for the user, shown in the transcript.
function tell($: EngineInterface, output: HookOutput): void {
  if (output.systemMessage !== undefined) {
    $.ui.log(output.systemMessage)
  }
}

async function remember(
  $: EngineInterface,
  e: { session_id?: string; transcript_path?: string; permission_mode?: string },
) {
  if (typeof e.session_id === 'string' && typeof e.transcript_path === 'string' && e.transcript_path !== '') {
    const known: GeneralSession = {
      sessionId: e.session_id,
      transcriptPath: e.transcript_path,
      permissionMode: e.permission_mode,
    }
    await update($, session, () => known)
  }
}

// The base fields of a classic payload, for PreToolUse, whose event carries only the
// tool call. The transcript path and permission mode are the ones the session's last
// classic event gave, left out when that event was for another session id.
async function baseFields($: EngineInterface): Promise<Record<string, unknown>> {
  const id = await $.session.id()
  const known = await read($, session)
  const same = known !== null && known.sessionId === id
  return {
    session_id: id,
    ...(same ? { transcript_path: known.transcriptPath } : {}),
    cwd: await $.session.cwd(),
    ...(same && known.permissionMode !== undefined ? { permission_mode: known.permissionMode } : {}),
  }
}

async function loopPy($: EngineInterface, args: readonly string[]) {
  return $.process.run(
    [
      'bash',
      '-c',
      LOOP_PY,
      `${$.plugin.root}/skills/oversee-development/loop.py`,
      '--session',
      await $.session.id(),
      ...args,
    ],
    { cwd: await $.session.cwd(), timeoutMs: 10 * SECOND },
  )
}

// Reads this session's oversee loop marker for the row above the prompt.
async function refreshLoop($: EngineInterface): Promise<void> {
  let value: GeneralLoop | null = null
  try {
    const ran = await loopPy($, ['status'])
    const marker: unknown = ran.exitCode === 0 && ran.stdout.trim() !== '' ? JSON.parse(ran.stdout) : null
    if (typeof marker === 'object' && marker !== null && 'state' in marker) {
      value = marker as GeneralLoop
    }
  } catch {
    value = null
  }
  await update($, loop, () => value)
  const shown = value !== null && (value.state === 'active' || value.state === 'paused')
  if (shown) {
    loopPoll ??= $.clock.every(LOOP_POLL_MS, () => void refreshLoop($))
  } else {
    loopPoll?.cancel()
    loopPoll = undefined
  }
}

async function loopCommand($: EngineInterface, args: readonly string[]): Promise<void> {
  try {
    const ran = await loopPy($, args)
    if (ran.exitCode !== 0) {
      $.ui.toast(`Oversee loop: ${ran.stderr.trim() || `exit ${ran.exitCode}`}`)
    }
  } catch (error) {
    $.ui.toast(`Oversee loop: ${String(error)}`)
  }
  await refreshLoop($)
}

function describeLoop(marker: GeneralLoop): string {
  const scope = [marker.label ? `label ${marker.label}` : '', marker.milestone ? `milestone ${marker.milestone}` : '']
    .filter(Boolean)
    .join(', ')
  const parts = [`Oversee loop ${marker.state}`]
  if (scope !== '') parts.push(scope)
  if (marker.continuations) parts.push(`${marker.continuations} stop${marker.continuations === 1 ? '' : 's'} without progress`)
  if (marker.state === 'paused' && marker.reason) parts.push(marker.reason)
  return parts.join(' · ')
}

function bashCommand(input: unknown): string {
  return typeof input === 'object' && input !== null ? String((input as { command?: unknown }).command ?? '') : ''
}

export const register: Register = on => {
  on('classic.PreToolUse', { tool: 'Bash' }, async ($, e, next) => {
    const payload = {
      ...(await baseFields($)),
      hook_event_name: 'PreToolUse',
      tool_name: e.tool,
      tool_input: toolInput(e),
      tool_use_id: e.tool_use_id,
    }
    // The gates run in parallel with each other and with the hooks beneath.
    const [beneath, ...outputs] = await Promise.all([
      next(e),
      ...HOOKS.PreToolUse.Bash.map(script => runHook($, 'PreToolUse', script.args, payload, script.timeoutMs)),
    ])
    const gates = combine(outputs)
    tell($, gates)
    if (gates.deny !== undefined) {
      const reason = beneath.deny === undefined ? gates.deny : `${beneath.deny}\n\n${gates.deny}`
      const context = [...(beneath.additionalContext ?? []), ...gates.context]
      return { deny: reason, ...(context.length > 0 ? { additionalContext: context } : {}) }
    }
    // A tool call's result takes no stop, so a gate's `continue: false` is left out.
    return merge(beneath, { ...gates, stop: undefined })
  })

  on('classic.PostToolUse', async ($, e, next) => {
    await remember($, e)
    const isBash = e.tool_name === 'Bash'
    if (isBash && /\b(loop\.py|oversee\.sh)\b/.test(bashCommand(e.tool_input))) {
      void refreshLoop($)
    }
    const scripts = isBash
      ? HOOKS.PostToolUse.Bash
      : e.tool_name === 'Edit' || e.tool_name === 'Write'
        ? HOOKS.PostToolUse.EditOrWrite
        : []
    if (scripts.length === 0) {
      return next(e)
    }
    const [beneath, notes] = await Promise.all([next(e), runAll($, 'PostToolUse', scripts, e)])
    return merge(beneath, notes)
  })

  on('classic.SessionStart', async ($, e, next) => {
    await remember($, e)
    void refreshLoop($)
    const [beneath, output] = await Promise.all([next(e), runAll($, 'SessionStart', HOOKS.SessionStart, e)])
    return merge(beneath, output)
  })

  on('classic.UserPromptSubmit', async ($, e, next) => {
    await remember($, e)
    return next(e)
  })

  on('classic.Stop', async ($, e, next) => {
    await remember($, e)
    const [beneath, output] = await Promise.all([next(e), runAll($, 'Stop', HOOKS.Stop, e)])
    await refreshLoop($)
    return merge(beneath, output)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const marker = await read($, loop)
    if (e.props.hasSurvey || marker === null || (marker.state !== 'active' && marker.state !== 'paused')) {
      return next(e)
    }
    const { Box, Button, Text } = $.ui.resolve(e)
    const isActive = marker.state === 'active'
    return (
      <Box>
        <Text color={isActive ? 'success' : 'warning'}>{isActive ? '● ' : '‖ '}</Text>
        <Text dimColor>{describeLoop(marker)} </Text>
        {isActive ? (
          <Button key="pause" label="Pause" onPress={() => loopCommand($, ['pause', 'paused from the status row'])} />
        ) : (
          <Button key="resume" label="Resume" onPress={() => loopCommand($, ['resume'])} />
        )}
      </Box>
    )
  })
}
