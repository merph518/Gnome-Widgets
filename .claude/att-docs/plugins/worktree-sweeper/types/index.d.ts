// The values the worktree-sweeper hooks module keeps in the chat's state.

// One worktree as `worktree-cleanup.sh --tsv` lists it. Every cell is the script's own
// text, so the pane shows what the script's table shows.
export type SweepRow = {
  worktree: string
  branch: string
  pullRequest: string
  uncommitted: string
  unpushed: string
  // `remove`, or `keep: <reasons>`.
  verdict: string
  // The absolute path, which `--remove-path` takes.
  path: string
}

// `idle` before the first listing; `ok` holds the rows of the last one; `failed` holds
// why it failed, and no row is offered then.
export type SweepScan = {
  phase: 'idle' | 'ok' | 'failed'
  rows: SweepRow[]
  error: string
  // When the last listing finished, in milliseconds since the epoch.
  at: number | null
}

// What switches.json says about this plugin.
export type SweepSwitches = { isOff: boolean; isHidden: boolean }

declare module 'claude-code' {
  interface PluginState {
    'worktree-sweeper': {
      scan: Shaped<SweepScan>
      switches: SweepSwitches
      // What runs now: a listing, a removal of a path, or nothing.
      busy: string | null
      // The lines --remove-path printed for the last Remove or Remove all.
      notes: string[]
      // Remove all done was pressed once and waits for its confirmation.
      isConfirming: boolean
      // The folders this chat runs in, so its own worktree is never offered.
      folders: string[]
    }
  }
}
