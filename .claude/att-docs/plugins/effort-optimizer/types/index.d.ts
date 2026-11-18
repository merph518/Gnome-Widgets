// The values the effort-optimizer hooks module keeps in the session's state.

export type EffortLevel = 'low' | 'medium' | 'high' | 'xhigh' | 'max'

// `suggest` shows a band to switch from; `auto` switches by itself.
export type EffortMode = 'suggest' | 'auto'

// The pick for one prompt, as the band above the prompt shows it.
export type EffortSuggestion = {
  // Counts up with each prompt, so a pick that comes back late is dropped.
  id: number
  // The turn the pick was made for.
  turnId: string
  level: EffortLevel
  // The level the turn's first request carried, when it had one.
  current: EffortLevel | null
  // A short reason from the model, or ''.
  why: string
  // `offer` shows the Switch button; `applied` shows what was done.
  phase: 'offer' | 'applied'
  note: string
}

// A level sent on each main-chat request, used when the effort setting cannot be
// changed. It is let go once the request's own level is no longer `base`, which means
// the user changed the level.
export type EffortHold = { level: EffortLevel; base: EffortLevel | null }

// What switches.json says about this plugin.
export type EffortSwitches = { isOff: boolean; isHidden: boolean }

declare module 'claude-code' {
  interface PluginState {
    'effort-optimizer': {
      mode: EffortMode
      switches: EffortSwitches
      suggestion: Shaped<EffortSuggestion | null>
      hold: EffortHold | null
      turnLevel: { turnId: string; level: EffortLevel } | null
    }
  }
}
