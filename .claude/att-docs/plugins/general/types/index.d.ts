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

declare module 'claude-code' {
  interface PluginState {
    general: {
      session: GeneralSession | null
      loop: Shaped<GeneralLoop | null>
    }
  }
}
