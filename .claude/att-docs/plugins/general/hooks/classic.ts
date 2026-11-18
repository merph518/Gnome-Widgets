// Reads what a hook script printed and turns it into the answer a function hook gives.
// A script answers with a JSON object on stdout (hookSpecificOutput, decision and
// reason, continue, systemMessage), or exits 2 with the reason on stderr. Nothing here
// touches the engine, so the tests call it directly.

import type { PermissionRequestDecision } from 'claude-code'

export type HookOutput = {
  // PreToolUse: refuse the call, ask the user, or let it through without a prompt.
  deny?: string
  ask?: string
  allow?: true
  // Stop, UserPromptSubmit and other events: block, with the reason the model reads.
  block?: string
  // Text handed to the model with the event.
  context: string[]
  // systemMessage: a line for the user.
  systemMessage?: string
  // continue: false, with its stopReason.
  stop?: { reason?: string }
  // PermissionRequest: the answer to the prompt.
  decision?: PermissionRequestDecision
  sessionTitle?: string
}

type Json = Record<string, unknown>

function isObject(value: unknown): value is Json {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function text(value: unknown): string | undefined {
  return typeof value === 'string' && value !== '' ? value : undefined
}

// The events whose plain (non-JSON) stdout reaches the model as context.
const PLAIN_CONTEXT = new Set(['SessionStart', 'UserPromptSubmit'])

export function parseHookOutput(
  event: string,
  exitCode: number,
  stdout: string,
  stderr: string,
): HookOutput {
  const out: HookOutput = { context: [] }
  if (exitCode === 2) {
    const reason = stderr.trim() || stdout.trim() || 'blocked by a hook'
    if (event === 'PreToolUse') {
      out.deny = reason
    } else if (event === 'PostToolUse') {
      out.context.push(reason)
    } else {
      out.block = reason
    }
    return out
  }
  if (exitCode !== 0) {
    return out
  }
  const trimmed = stdout.trim()
  if (trimmed === '') {
    return out
  }
  let parsed: unknown
  try {
    parsed = trimmed.startsWith('{') ? JSON.parse(trimmed) : undefined
  } catch {
    parsed = undefined
  }
  if (!isObject(parsed)) {
    if (PLAIN_CONTEXT.has(event)) {
      out.context.push(trimmed)
    }
    return out
  }
  out.systemMessage = text(parsed.systemMessage)
  if (parsed.continue === false) {
    out.stop = { reason: text(parsed.stopReason) }
  }
  const specific = isObject(parsed.hookSpecificOutput) ? parsed.hookSpecificOutput : {}
  const context = text(specific.additionalContext)
  if (context !== undefined) {
    out.context.push(context)
  }
  out.sessionTitle = text(specific.sessionTitle)
  const reason = text(specific.permissionDecisionReason) ?? text(parsed.reason)
  const permission = specific.permissionDecision
  if (event === 'PreToolUse') {
    if (permission === 'deny' || parsed.decision === 'block') {
      out.deny = reason ?? 'refused by a hook'
    } else if (permission === 'ask') {
      out.ask = reason ?? 'a hook asks before this runs'
    } else if (permission === 'allow' || parsed.decision === 'approve') {
      out.allow = true
    }
  } else if (parsed.decision === 'block' && event === 'PostToolUse') {
    // The tool has already run, so the reason reaches the model as context.
    out.context.push(text(parsed.reason) ?? 'blocked by a hook')
  } else if (parsed.decision === 'block') {
    out.block = text(parsed.reason) ?? 'blocked by a hook'
  }
  if (event === 'PermissionRequest' && isObject(specific.decision)) {
    const decision = specific.decision
    if (decision.behavior === 'allow') {
      out.decision = {
        behavior: 'allow',
        ...(isObject(decision.updatedInput) ? { updatedInput: decision.updatedInput } : {}),
      }
    } else if (decision.behavior === 'deny') {
      out.decision = {
        behavior: 'deny',
        ...(text(decision.message) !== undefined ? { message: decision.message as string } : {}),
        ...(decision.interrupt === true ? { interrupt: true as const } : {}),
      }
    }
  }
  return out
}

// The keys a tool call's envelope carries beside the tool's own arguments.
const RESERVED = new Set(['tool', 'tool_use_id', 'agentId', 'requestMeta', 'consent'])

export function toolInput(e: Record<string, unknown>): Record<string, unknown> {
  const input: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(e)) {
    if (!RESERVED.has(key)) {
      input[key] = value
    }
  }
  return input
}

// Joins the outputs of scripts that answer one event: the first refusal wins, contexts
// add up.
export function combine(outputs: readonly (HookOutput | undefined)[]): HookOutput {
  const all: HookOutput = { context: [] }
  for (const one of outputs) {
    if (one === undefined) {
      continue
    }
    all.context.push(...one.context)
    all.deny ??= one.deny
    all.ask ??= one.ask
    all.allow ??= one.allow
    all.block ??= one.block
    all.stop ??= one.stop
    all.decision ??= one.decision
    all.sessionTitle ??= one.sessionTitle
    all.systemMessage =
      all.systemMessage === undefined
        ? one.systemMessage
        : one.systemMessage === undefined
          ? all.systemMessage
          : `${all.systemMessage}\n${one.systemMessage}`
  }
  return all
}

type Mergeable = { additionalContext?: string[]; block?: string; preventContinuation?: true; stopReason?: string }

// Adds a script's answer to the result next(e) gave: contexts add up, and two blocks
// both reach the model, so neither reason is lost.
export function merge<R extends Mergeable>(beneath: R, output: HookOutput | undefined): R {
  if (output === undefined) {
    return beneath
  }
  const out: Mergeable = { ...beneath }
  if (output.context.length > 0) {
    out.additionalContext = [...(beneath.additionalContext ?? []), ...output.context]
  }
  if (output.block !== undefined) {
    out.block = beneath.block === undefined ? output.block : `${beneath.block}\n\n${output.block}`
  }
  if (output.stop !== undefined && beneath.preventContinuation === undefined) {
    out.preventContinuation = true
    if (output.stop.reason !== undefined) out.stopReason = output.stop.reason
  }
  return out as R
}
