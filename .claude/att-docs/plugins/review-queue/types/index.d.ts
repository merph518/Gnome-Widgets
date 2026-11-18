// The values the review-queue hooks module keeps in the session's state.

// A pull request's checks, from its status check rollup: any failure is failing,
// else any check still going is running, else passing; `none` when it has no checks.
export type CiState = 'passing' | 'failing' | 'running' | 'none'

// One open pull request carrying the review label.
export type PullRequest = {
  // The repository's name, without the owner.
  repo: string
  number: number
  title: string
  url: string
  // When it was opened, in milliseconds since the epoch.
  createdAt: number
  isDraft: boolean
  ci: CiState
}

// Why gh could not read a repository: not installed, signed out, no network, or
// anything else.
export type QueueFailure = 'missing' | 'signed-out' | 'offline' | 'failed'

// What the last refresh found.
export type Queue = {
  // Oldest first.
  prs: PullRequest[]
  // Repositories gh could not read while others read.
  unread: string[]
  // Set when no repository could be read.
  failure: QueueFailure | null
  // When the refresh that found it started, in milliseconds since the epoch.
  at: number
}

// What switches.json says about this plugin.
export type QueueSwitches = { isOff: boolean; isHidden: boolean }

declare module 'claude-code' {
  interface PluginState {
    'review-queue': {
      queue: Queue | null
      switches: QueueSwitches
      // The dismissed pull requests, `repo#number`, as the store holds them.
      dismissed: string[]
      showDismissed: boolean
    }
  }
}
