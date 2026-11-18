// The values the runner-health hooks module works with and keeps in the session's state.

// A runner service on this machine, from `systemctl list-units`.
export type LocalUnit = {
  // The systemd unit, such as `actions.runner.<org>.<name>.service`.
  unit: string
  // The runner's name: from its `.runner` file once read, else from the unit name.
  runner: string
  isActive: boolean
}

// A runner as GitHub reports it, already narrowed to the watched label.
export type ApiRunner = { name: string; isOnline: boolean; isBusy: boolean }

// A job that waits for a runner with the watched label.
export type QueuedJob = { repo: string; workflow: string; name: string; createdAt: number }

// Free space on one filesystem a runner writes to.
export type DiskFree = { mount: string; paths: string[]; freeBytes: number }

// One thing wrong. `fix` is a command the person can run, when there is one.
export type Problem = { kind: 'offline' | 'queued' | 'disk' | 'unreadable'; text: string; fix: string | null }

// What the band draws: the problems, and why part of the state could not be read.
export type Health = { problems: Problem[]; note: string | null }

// runner-health.json in the mods folder, with the defaults filled in.
export type Settings = {
  org: string
  repos: string[]
  label: string
  queuedMinutes: number
  freeGiB: number
}

// What the GitHub side last returned. A null list could not be read; `note` says why.
export type ApiState = { runners: ApiRunner[] | null; jobs: QueuedJob[] | null; note: string | null }

// What switches.json says about this plugin.
export type HealthSwitches = { isOff: boolean; isHidden: boolean }

declare module 'claude-code' {
  interface PluginState {
    'runner-health': {
      health: Health
      switches: HealthSwitches
    }
  }
}
