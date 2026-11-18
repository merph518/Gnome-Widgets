// The parts of the mods switchboard that need no engine: reading and changing
// switches.json, finding mods in the places Claude Code loads them from, and reading
// what each mod can do from its source.

import type { ModFeatures, ModGroup, ModRow, SwitchChange } from '../types'

// What switches.json holds: `"<name>": false` turns a mod off in every chat, and
// `"<name>:hidden": true` keeps its band or pane out of sight. Only true and false
// values are kept; anything else in the file is left alone when it is written.
export type Switches = { isReadable: boolean; values: Record<string, boolean> }

// The JSON object in `text`, or null when it is not one.
export function asObject(text: string): Record<string, unknown> | null {
  let value: unknown
  try {
    value = JSON.parse(text)
  } catch {
    return null
  }
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

// A missing file reads as no switches. A file that is not a JSON object is unreadable.
export function parseSwitches(text: string | undefined): Switches {
  if (text === undefined) return { isReadable: true, values: {} }
  const record = asObject(text)
  if (record === null) return { isReadable: false, values: {} }
  const values: Record<string, boolean> = {}
  for (const [key, value] of Object.entries(record)) {
    if (typeof value === 'boolean') values[key] = value
  }
  return { isReadable: true, values }
}

// Returns the new text of switches.json, or null when the old text is not a JSON
// object: writing over it would drop what other mods keep there. Off writes `false`
// and Hidden writes `true`; On and Shown remove the key, so the file holds only
// what differs from the default.
export function applySwitch(text: string | undefined, name: string, change: SwitchChange): string | null {
  const record = text === undefined ? {} : asObject(text)
  if (record === null) return null
  const next: Record<string, unknown> = { ...record }
  if (change.isOff === true) next[name] = false
  if (change.isOff === false) delete next[name]
  if (change.isHidden === true) next[`${name}:hidden`] = true
  if (change.isHidden === false) delete next[`${name}:hidden`]
  return `${JSON.stringify(next, null, 2)}\n`
}

// The modules a hooks.json lists. A mod is a plugin with at least one.
export function hooksModules(text: string): string[] {
  const record = asObject(text)
  const modules = record?.['modules']
  if (!Array.isArray(modules)) return []
  return modules.filter((one): one is string => typeof one === 'string' && one !== '')
}

// The words in a mod's source that show what it can do. A mod gets a working switch
// only when its own code reads switches.json.
const SWITCH = /switches\.json/
const BAND = /component:\s*['"]AbovePrompt['"]/
const PANE = /component:\s*['"]Pane['"]/
const REOPEN = /\.open-/

export function scanFeatures(sources: readonly string[]): ModFeatures {
  const has = (pattern: RegExp) => sources.some(source => pattern.test(source))
  const hasPane = has(PANE)
  return { hasSwitch: has(SWITCH), hasBand: has(BAND), hasPane, canReopen: hasPane && has(REOPEN) }
}

// The mods this repository ships, with the title, group and tip the pane shows.
// Any other mod shows its own plugin.json name and description.
export const CATALOG: Readonly<Record<string, { title: string; group: ModGroup; tip: string }>> = {
  'effort-optimizer': {
    title: 'Effort optimizer',
    group: 'token savers',
    tip: 'Suggests a reasoning effort level above the prompt for each prompt you type. Off sends every request at the level you set.',
  },
  'model-router': {
    title: 'Model router',
    group: 'token savers',
    tip: "Picks each subagent's model from how hard its task is. Off leaves every subagent on the model it asked for.",
  },
  'review-queue': {
    title: 'Review queue',
    group: 'display',
    tip: 'Shows above the prompt how many pull requests wait for your review, with each one\'s CI state and age. Off runs no gh calls.',
  },
  'runner-health': {
    title: 'Runner health',
    group: 'display',
    tip: 'Shows a row above the prompt when a CI runner is stopped or offline, a job waits too long for one, or a runner disk is low. Off stops the checks.',
  },
  'pin-drift': {
    title: 'Pin drift',
    group: 'display',
    tip: 'Shows above the prompt, in the Overmind repository only, when a release is pending or a repository that pins Overmind is behind the latest tag, with a pane listing each pin and its pin pull request. Off runs no gh calls.',
  },
  general: {
    title: 'General',
    group: 'chat tools',
    tip: "The repository hooks that read a repository's extension.json.",
  },
  'worktree-sweeper': {
    title: 'Worktree sweeper',
    group: 'chat tools',
    tip: 'Shows a band above the prompt when worktrees are done, and a pane that removes them with the checks worktree-cleanup.sh runs. Off stops it from asking GitHub about pull requests.',
  },
}

// A mod as it was found, before its features are read.
export type FoundMod = { name: string; description: string; path: string; alsoAt: string[] }

export function rowFor(found: FoundMod, features: ModFeatures): ModRow {
  const known = CATALOG[found.name]
  const group: ModGroup = known?.group ?? (features.hasBand || features.hasPane ? 'display' : 'chat tools')
  return {
    name: found.name,
    title: known?.title ?? found.name,
    group,
    tip: known?.tip ?? found.description,
    path: found.path,
    alsoAt: found.alsoAt,
    features,
  }
}

// The Claude Code configuration folder: CLAUDE_CONFIG_DIR when set, with a leading
// `~` read as HOME, else ~/.claude.
export function configDir(home: string | undefined, configured: string | undefined): string | null {
  const clean = (path: string) => path.replace(/\/{2,}/g, '/').replace(/(.)\/$/, '$1')
  const set = configured?.trim() ?? ''
  if (set !== '' && set !== '~' && !set.startsWith('~/')) return clean(set)
  if (home === undefined || home === '') return null
  return clean(set === '' ? `${home}/.claude` : `${home}/${set.slice(1)}`)
}

// A colon-separated list of folders, as CLAUDE_CODE_PLUGIN_DIRS holds it.
export function splitPathList(text: string | undefined): string[] {
  if (text === undefined) return []
  return text
    .split(':')
    .map(part => part.trim().replace(/(.)\/+$/, '$1'))
    .filter(part => part !== '')
}

// The folders of the installed plugins a settings file turns on. installed_plugins.json
// lists each `name@marketplace` with one entry per scope; a user entry counts
// everywhere, a project or local entry only in the project it was installed for.
// `settings` are the settings files' texts, the later one winning for each plugin.
export function installedPaths(installed: string | undefined, settings: readonly string[], root: string): string[] {
  const record = installed === undefined ? null : asObject(installed)
  const plugins = record?.['plugins']
  if (typeof plugins !== 'object' || plugins === null || Array.isArray(plugins)) return []
  const enabled: Record<string, boolean> = {}
  for (const text of settings) {
    const value = asObject(text)?.['enabledPlugins']
    if (typeof value !== 'object' || value === null || Array.isArray(value)) continue
    for (const [key, on] of Object.entries(value)) {
      if (typeof on === 'boolean') enabled[key] = on
    }
  }
  const paths: string[] = []
  for (const [key, entries] of Object.entries(plugins as Record<string, unknown>)) {
    if (enabled[key] !== true || !Array.isArray(entries)) continue
    const entry = entries.find((one: unknown) => {
      if (typeof one !== 'object' || one === null) return false
      const { scope, projectPath, installPath } = one as Record<string, unknown>
      if (typeof installPath !== 'string') return false
      return scope === 'user' || projectPath === root
    }) as { installPath: string } | undefined
    if (entry !== undefined) paths.push(entry.installPath)
  }
  return paths
}

// One row per name. The first folder found wins, in the order Claude Code prefers
// them; any other folder holding a mod of that name is noted under it.
export function dedupe(found: readonly FoundMod[]): FoundMod[] {
  const byName = new Map<string, FoundMod>()
  for (const mod of found) {
    const first = byName.get(mod.name)
    if (first === undefined) byName.set(mod.name, { ...mod, alsoAt: [...mod.alsoAt] })
    else if (first.path !== mod.path && !first.alsoAt.includes(mod.path)) first.alsoAt.push(mod.path)
  }
  return [...byName.values()]
}

// The empty file that asks a mod to open its pane again in one chat.
export function markerPath(config: string, name: string, session: string): string {
  return `${config}/mods/.open-${name}-${session}`
}
