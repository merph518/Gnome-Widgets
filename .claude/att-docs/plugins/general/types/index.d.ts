// The values the general plugin's hooks module keeps in the session's state.

// What the last classic event said about the session, for the PreToolUse payload.
export type GeneralSession = {
  sessionId: string
  transcriptPath: string
  permissionMode?: string
}

// This session's oversee loop marker, as `loop.py --session <id> status` prints it.
export type GeneralLoop = {
  state: 'active' | 'paused' | 'stopped' | 'absent' | string
  label?: string | null
  milestone?: string | null
  continuations?: number
  reason?: string | null
}

// This session's oversee loop board, as `loop.py --session <id> board` prints it: the
// issue being worked, the queue in serve order, and the finished issues, newest first.
// A null field was empty or "-" in the file.
export type GeneralBoard = {
  session: string
  state: string
  repo: string | null
  current: {
    issue: number
    title: string | null
    phase: 'working' | 'waiting on runs'
    branch: string | null
    since: string | null
  } | null
  queued: {
    issue: number
    title: string | null
    area: string | null
    blockers: string | null
    waits: string | null
  }[]
  finished: {
    issue: number
    title: string | null
    status: string
    pr: number | null
    note: string | null
    at: string | null
  }[]
  // Finished issues past the board's limit.
  more: number
}

declare module 'claude-code' {
  interface PluginState {
    general: {
      session: GeneralSession | null
      loop: Shaped<GeneralLoop | null>
      board: Shaped<GeneralBoard | null>
    }
  }
}
