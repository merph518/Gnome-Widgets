// The parts of the cache clock that need no engine: reading the cache length from a
// transcript, the countdown, keep-warm limits and switches.json.

import type { CacheKind, CacheLength, CacheSwitches, KeepWarm } from '../types'

type Line = {
  isSidechain?: unknown
  timestamp?: unknown
  message?: { usage?: { cache_creation?: { ephemeral_1h_input_tokens?: unknown; ephemeral_5m_input_tokens?: unknown } } }
}

function tokens(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

function parse(line: string): Line | null {
  try {
    const value: unknown = JSON.parse(line)
    return value !== null && typeof value === 'object' && !Array.isArray(value) ? (value as Line) : null
  } catch {
    return null
  }
}

// Finds which prompt cache the main chat's newest reply wrote to. Transcript lines
// are read newest first; subagent lines (isSidechain) and lines that are cut short
// or not JSON are skipped, and so is a reply that wrote nothing to the cache.
export function readCacheLength(text: string): CacheLength {
  const lines = text.split('\n')
  for (let i = lines.length - 1; i >= 0; i -= 1) {
    const line = lines[i]?.trim() ?? ''
    if (line === '') continue
    const record = parse(line)
    if (record === null || record.isSidechain === true) continue
    const written = record.message?.usage?.cache_creation
    if (written === undefined || written === null || typeof written !== 'object') continue
    let kind: CacheKind | null = null
    if (tokens(written.ephemeral_1h_input_tokens) > 0) kind = '1h'
    else if (tokens(written.ephemeral_5m_input_tokens) > 0) kind = '5m'
    if (kind === null) continue
    const at = typeof record.timestamp === 'string' ? Date.parse(record.timestamp) : Number.NaN
    return { kind, at: Number.isNaN(at) ? null : at }
  }
  return { kind: 'unknown', at: null }
}

export const MINUTE_MS = 60_000
export const HOUR_MS = 60 * MINUTE_MS

// How long a cache lasts; an unknown length is counted as the shorter one, so the
// band never calls a cold cache warm.
export function lengthMs(kind: CacheKind): number {
  return kind === '1h' ? HOUR_MS : 5 * MINUTE_MS
}

// Milliseconds left before the cache written at `lastAt` goes cold; 0 once it is.
export function leftMs(lastAt: number, kind: CacheKind, now: number): number {
  return Math.max(0, lastAt + lengthMs(kind) - now)
}

// `m:ss`, rounding up so the band reads 0:00 only once the cache is cold.
export function formatLeft(ms: number): string {
  const seconds = Math.ceil(ms / 1000)
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

// The Claude Code configuration folder: CLAUDE_CONFIG_DIR when set, else ~/.claude.
export function configDir(home: string | undefined, configured: string | undefined): string {
  if (configured !== undefined && configured.trim() !== '') return configured.trim().replace(/\/+$/, '')
  return `${(home ?? '').replace(/\/+$/, '')}/.claude`
}

// What switches.json says: `"cache-clock": false` turns the plugin off and
// `"cache-clock:hidden": true` hides the band. A missing file, or one that is not a
// JSON object, leaves it on.
export function parseSwitches(text: string | undefined): CacheSwitches {
  const on: CacheSwitches = { isOff: false, isHidden: false }
  if (text === undefined) return on
  let value: unknown
  try {
    value = JSON.parse(text)
  } catch {
    return on
  }
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return on
  const record = value as Record<string, unknown>
  return { isOff: record['cache-clock'] === false, isHidden: record['cache-clock:hidden'] === true }
}

// A chat over this many tokens is offered a handoff once its cache is cold, since
// its next reply would write the whole chat to the cache again.
export const HANDOFF_TOKENS = 150_000

export function isBig(tokens: number): boolean {
  return tokens > HANDOFF_TOKENS
}

// Keep warm pings this long before the cache would go cold.
export const PING_LEAD_MS = 45_000
// After a ping that did not read the cache, the next try comes this much later.
export const PING_RETRY_MS = 10_000
export const MAX_PINGS = 30
export const MAX_FAILURES = 3
export const MAX_KEEP_WARM_MS = 2 * HOUR_MS

// When keep warm pings a cache written at `lastAt`.
export function pingAt(lastAt: number, kind: CacheKind): number {
  return lastAt + lengthMs(kind) - PING_LEAD_MS
}

// Why keep warm must stop now, or null while it may go on.
export function keepWarmStop(state: KeepWarm, now: number): string | null {
  if (state.pings >= MAX_PINGS) return `${MAX_PINGS} pings sent`
  if (state.failures >= MAX_FAILURES) return `${MAX_FAILURES} pings in a row did not read the cache`
  if (now - state.startedAt >= MAX_KEEP_WARM_MS) return `${MAX_KEEP_WARM_MS / HOUR_MS} hours passed`
  return null
}
