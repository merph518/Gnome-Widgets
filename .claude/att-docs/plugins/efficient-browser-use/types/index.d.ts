/** What happened to one picture. */
export type Outcome = 'shrunk' | 'described' | 'skipped' | 'failed'

/** One picture the plugin looked at, as the pane shows it. Newest first. */
export type PictureCard = {
  /** The pane's own id for the card: a running number. */
  id: string
  /** Milliseconds since the epoch. */
  at: number
  /** The tool whose result carried the picture, short: `Claude_Browser computer`, `Read`. */
  tool: string
  outcome: Outcome
  /** The picture's size as the tool returned it. */
  inW: number
  inH: number
  /** The size Claude read, when it was shrunk. */
  outW?: number
  outH?: number
  /** About what the picture cost in input tokens before, and what Claude read after. */
  before: number
  after: number
  /** One plain sentence: what was done and why. */
  why: string
  /** A PNG at most 160 px on its long side, base64; absent when none could be drawn. */
  thumb?: string
  thumbW?: number
  thumbH?: number
}

declare module 'claude-code' {
  interface PluginState {
    'efficient-browser-use': {
      /** Newest first, capped. */
      cards: Shaped<PictureCard[]>
      /** How many pictures are being worked on now: the mascot moves while it is above 0. */
      busy: number
      /** True while switches.json turns the mod off. */
      off: boolean
    }
  }
}
