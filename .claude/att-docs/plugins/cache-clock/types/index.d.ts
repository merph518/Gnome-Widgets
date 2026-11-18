// The values the cache-clock hooks module keeps in the session's state.

// Which prompt cache the main chat's newest reply wrote to. `unknown` is counted as
// five minutes.
export type CacheKind = '1h' | '5m' | 'unknown'

// What a transcript says: the cache length, and when the deciding reply was written
// (milliseconds since the epoch), or null when no reply decided it.
export type CacheLength = { kind: CacheKind; at: number | null }

// The countdown the band draws: the cache was last written at `lastAt` and lasts the
// length `kind` names.
export type CacheClock = { lastAt: number; kind: CacheKind }

// Keep warm, on from /keepwarm until a typed prompt or one of its limits stops it.
export type KeepWarm = {
  isOn: boolean
  // Turned on while the cache was cold: it waits for the next reply, and a typed
  // prompt does not stop it.
  isArmed: boolean
  // When it started: /keepwarm, or the reply an armed keep warm waited for.
  startedAt: number
  // Pings that read the cache.
  pings: number
  // Pings in a row that did not.
  failures: number
  // Why it stopped, or ''.
  note: string
}

// What switches.json says about this plugin.
export type CacheSwitches = { isOff: boolean; isHidden: boolean }

declare module 'claude-code' {
  interface PluginState {
    'cache-clock': {
      clock: CacheClock | null
      switches: CacheSwitches
      isShown: boolean
      tokens: number
      keepWarm: KeepWarm | null
      isAsked: boolean
    }
  }
}
