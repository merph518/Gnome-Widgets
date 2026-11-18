// The values the handoff hooks module keeps in the session's state.

// `offer` asks whether to write a handoff; `running` shows the five steps;
// `done` offers the finished handoff; `failed` says why and keeps the draft.
export type HandoffPhase = 'offer' | 'running' | 'done' | 'failed'

export type HandoffRun = {
  // Counts up with each run and each /clear, so a run that finishes late is dropped.
  id: number
  phase: HandoffPhase
  // The step under way, 0 to 4; 5 once all five are done.
  step: number
  // The saved draft and handoff, once written.
  draftPath: string | null
  path: string | null
  // A line under the steps: what went wrong, or what Copy, Open file or Start new
  // chat did.
  note: string
}

// What switches.json says about this plugin.
export type HandoffSwitches = { isOff: boolean; isHidden: boolean }

declare module 'claude-code' {
  interface PluginState {
    handoff: {
      run: Shaped<HandoffRun | null>
      switches: HandoffSwitches
      // The context size, in tokens, at which the band is offered next.
      offerAt: number
      // The context size the last response reported, or null before the first.
      tokens: number | null
    }
  }
}
