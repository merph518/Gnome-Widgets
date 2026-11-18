// The parts of the worktree sweeper that need no engine: the commands it runs, reading
// what worktree-cleanup.sh prints, and which rows the pane may offer to remove.

import type { SweepRow, SweepSwitches } from '../types'

export const NAME = 'worktree-sweeper'

// The header line `worktree-cleanup.sh --tsv` prints first.
export const HEADER = ['worktree', 'branch', 'pull request', 'uncommitted', 'unpushed', 'verdict', 'path'].join('\t')

// The script ships in this plugin's scripts folder. It runs through bash, so it works
// even when the plugin copy lost its executable bit.
export function scriptPath(pluginRoot: string): string {
  return `${pluginRoot.replace(/\/+$/, '')}/scripts/worktree-cleanup.sh`
}

export function listArgv(pluginRoot: string): string[] {
  return ['bash', scriptPath(pluginRoot), '--tsv']
}

export function removeArgv(pluginRoot: string, path: string): string[] {
  return ['bash', scriptPath(pluginRoot), '--remove-path', path]
}

export type Listing = { rows: SweepRow[] } | { error: string }

// Reads the script's --tsv output. Anything but the header followed by rows of seven
// cells is an error, so a script that changed its output never offers a wrong row.
export function parseTsv(stdout: string): Listing {
  const lines = stdout.split('\n').filter(line => line !== '')
  if (lines[0] !== HEADER) return { error: 'the script printed no header' }
  const rows: SweepRow[] = []
  for (const line of lines.slice(1)) {
    const cells = line.split('\t')
    if (cells.length !== 7) return { error: `a row has ${cells.length} cells, not 7: ${line}` }
    const [worktree, branch, pullRequest, uncommitted, unpushed, verdict, path] = cells as [
      string, string, string, string, string, string, string,
    ]
    rows.push({ worktree, branch, pullRequest, uncommitted, unpushed, verdict, path })
  }
  return { rows }
}

// What a listing's exit came to.
export function listingFrom(result: { exitCode: number; stdout: string; stderr: string }): Listing {
  if (result.exitCode === 64) return { error: 'This folder is not in a git repository.' }
  if (result.exitCode !== 0) {
    const why = result.stderr.trim() || `exit status ${result.exitCode}`
    return { error: `Could not list worktrees: ${why}` }
  }
  return parseTsv(result.stdout)
}

// Whether `folder` is `path` or sits inside it.
function isWithin(folder: string, path: string): boolean {
  const base = path.replace(/\/+$/, '')
  return folder === base || folder.startsWith(`${base}/`)
}

// Whether the worktree at `path` holds one of the folders this chat runs in.
export function holdsChat(path: string, folders: readonly string[]): boolean {
  return folders.some(folder => isWithin(folder, path))
}

// The script marks a row `remove` when it can go. The pane also holds back a worktree
// this chat runs in, which the script sees only when it runs from that worktree.
export function isOfferable(row: SweepRow, folders: readonly string[]): boolean {
  return row.verdict === 'remove' && !holdsChat(row.path, folders)
}

export function isThisChat(row: SweepRow, folders: readonly string[]): boolean {
  return holdsChat(row.path, folders)
}

export function bandText(count: number): string {
  return `${count} ${count === 1 ? 'worktree' : 'worktrees'} done · `
}

// The line --remove-path printed, or what went wrong when it printed none.
export function removalNote(path: string, result: { exitCode: number; stdout: string; stderr: string }): string {
  const line = result.stdout.split('\n').find(one => one.trim() !== '')
  if (line !== undefined) {
    const extra = result.exitCode === 0 ? '' : result.stderr.trim()
    return extra === '' ? line.trim() : `${line.trim()} (${extra.split('\n')[0]})`
  }
  const why = result.stderr.trim() || `exit status ${result.exitCode}`
  return `kept ${path}: ${why}`
}

// switches.json is a JSON object of on and off values that the mods switchboard
// writes. A missing or unreadable file leaves this plugin on and its band shown.
export function parseSwitches(text: string | undefined): SweepSwitches {
  const on: SweepSwitches = { isOff: false, isHidden: false }
  if (text === undefined) return on
  let value: unknown
  try {
    value = JSON.parse(text)
  } catch {
    return on
  }
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return on
  const record = value as Record<string, unknown>
  return { isOff: record[NAME] === false, isHidden: record[`${NAME}:hidden`] === true }
}

// Claude Code's configuration folder: CLAUDE_CONFIG_DIR when set, else ~/.claude.
export function configDir(home: string | undefined, configured: string | undefined): string {
  const dir = configured?.trim()
  if (dir) return dir.replace(/\/+$/, '')
  return `${home ?? ''}/.claude`
}
