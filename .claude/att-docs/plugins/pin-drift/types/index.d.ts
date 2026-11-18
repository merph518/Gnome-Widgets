// The values the pin-drift hooks module keeps in the session's state.

// A pull request's checks, from its status check rollup: any failure is failing,
// else any check still going is running, else passing; `none` when it has no checks.
export type CiState = 'passing' | 'failing' | 'running' | 'none'

// An open pull request that moves a consumer's pin, from a branch named
// `overmind/pin-<tag>` or `overmind/move-<tag>`.
export type PinPr = {
  number: number
  url: string
  branch: string
  // The tag the branch moves the pin to, such as `v0.32.3`.
  tag: string
  ci: CiState
}

// One repository that pins Overmind, as its lock on the default branch reads.
export type ConsumerPin = {
  // The repository's name, without the owner.
  name: string
  // The pinned tag, such as `v0.31.4`; null when the lock could not be read or its
  // tag is not vMAJOR.MINOR.PATCH.
  pinned: string | null
  // The lock's repo= line as written; null when it has none.
  lockRepo: string | null
  // Why pinned is null.
  note: string | null
  // The newest open pin pull request that would move the pin. Looked up only for a
  // consumer behind the latest tag, or one whose lock names an older repository name.
  pr: PinPr | null
  // True when that lookup ran and its pull requests could not be read.
  isPrUnknown: boolean
}

// The open release pull request whose version is above the latest tag.
export type Pending = { version: string; number: number; url: string; title: string }

// Why gh failed: not installed, signed out, no network, the API rate limit, or
// anything else.
export type DriftFailure = 'missing' | 'signed-out' | 'offline' | 'rate-limited' | 'failed'

// What one refresh found.
export type Drift = {
  // The highest vMAJOR.MINOR.PATCH tag; null only with a failure.
  latest: string | null
  pending: Pending | null
  // True when the release pull requests could not be read, so pending says nothing.
  isReleaseUnknown: boolean
  // In the order consumers.json lists them.
  consumers: ConsumerPin[]
  // Set when the tags could not be read, so there is nothing to compare, or when gh
  // was missing, signed out, offline or rate limited partway through, which stopped
  // the remaining reads.
  failure: DriftFailure | null
  // When the refresh ran, in milliseconds since the epoch.
  at: number
}

// What switches.json says about this plugin.
export type DriftSwitches = { isOff: boolean; isHidden: boolean }

declare module 'claude-code' {
  interface PluginState {
    'pin-drift': {
      drift: Drift | null
      switches: DriftSwitches
      isHome: boolean
      isBusy: boolean
    }
  }
}
