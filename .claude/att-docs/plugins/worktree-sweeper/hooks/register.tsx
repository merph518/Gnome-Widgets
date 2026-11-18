// Shows a band above the prompt when worktrees of this repository are done, and a pane
// that lists every worktree and removes the done ones.
//
// The listing and every removal run scripts/worktree-cleanup.sh from this plugin: the
// band and the pane show the cells of `worktree-cleanup.sh --tsv`, and Remove and
// Remove all done run `worktree-cleanup.sh --remove-path`, which checks the worktree
// again and removes it with `git worktree remove` without --force. The branch stays.
// The worktree this chat runs in is never offered.
//
// The listing runs when the chat starts, every ten minutes, when the pane opens, on
// Refresh, and after a removal. switches.json in the configuration folder turns the
// plugin off or hides the band, and an `.open-` file there opens the pane.

import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { SweepRow, SweepScan, SweepSwitches } from '../types'
import {
  NAME,
  bandText,
  configDir,
  holdsChat,
  isOfferable,
  isThisChat,
  listArgv,
  listingFrom,
  parseSwitches,
  removalNote,
  removeArgv,
} from './sweeper'

const PANE = NAME
const TITLE = 'Worktree sweeper'
const EMPTY: SweepScan = { phase: 'idle', rows: [], error: '', at: null }

const scan = atom({ plugin: 'worktree-sweeper', key: 'scan' } as const, EMPTY, { shape: 'scan-1' })
const switches = atom({ plugin: 'worktree-sweeper', key: 'switches' } as const, { isOff: false, isHidden: false } as SweepSwitches)
const busy = atom({ plugin: 'worktree-sweeper', key: 'busy' } as const, null as string | null)
const notes = atom({ plugin: 'worktree-sweeper', key: 'notes' } as const, [] as string[])
const isConfirming = atom({ plugin: 'worktree-sweeper', key: 'isConfirming' } as const, false)
const folders = atom({ plugin: 'worktree-sweeper', key: 'folders' } as const, [] as string[])

// How often switches.json and the `.open-` file are read.
const SWITCH_MS = 3000
// How often the worktrees are listed again. Each listing asks GitHub about every
// worktree's pull request, so it is not run on every turn.
const LIST_MS = 10 * 60 * 1000
const LIST_TIMEOUT_MS = 120_000
// Removing a worktree also deletes the files git ignores in it, which can be a large
// node_modules, so a removal gets the longest time a process may run.
const REMOVE_TIMEOUT_MS = 600_000

let timers: { cancel: () => void }[] = []
let config: string | null = null
let isListing = false
let isRemoving = false
let isListingAgain = false

async function configFolder($: EngineInterface): Promise<string> {
  config ??= configDir(await $.env.get('HOME'), await $.env.get('CLAUDE_CONFIG_DIR'))
  return config
}

async function readSwitches($: EngineInterface): Promise<SweepSwitches> {
  const text = await $.fs.read(`${await configFolder($)}/mods/switches.json`).then(
    value => (typeof value === 'string' ? value : undefined),
    () => undefined,
  )
  const value = parseSwitches(text)
  await update($, switches, () => value)
  return value
}

// The folders this chat runs in: its project root and its working directory.
async function chatFolders($: EngineInterface): Promise<{ root: string; list: string[] }> {
  const root = await $.session.root()
  const cwd = await $.session.cwd().catch(() => root)
  const list = cwd === root ? [root] : [root, cwd]
  await update($, folders, () => list)
  return { root, list }
}

// Lists the worktrees. A call made while a listing or a removal runs is folded into one
// more listing after it, so two presses never run the script twice at once.
async function list($: EngineInterface): Promise<void> {
  if (isListing || isRemoving) {
    isListingAgain = true
    return
  }
  isListing = true
  try {
    await update($, busy, () => 'Checking pull requests…')
    do {
      isListingAgain = false
      if ((await read($, switches)).isOff) break
      let next: SweepScan
      try {
        const { root } = await chatFolders($)
        const result = await $.process.run(listArgv($.plugin.root), { cwd: root, timeoutMs: LIST_TIMEOUT_MS })
        const listing = listingFrom(result)
        const at = await $.clock.now()
        next = 'rows' in listing ? { phase: 'ok', rows: listing.rows, error: '', at } : { phase: 'failed', rows: [], error: listing.error, at }
      } catch (error) {
        next = { phase: 'failed', rows: [], error: `Could not list worktrees: ${String(error)}`, at: await $.clock.now() }
      }
      await update($, scan, () => next)
    } while (isListingAgain)
  } finally {
    isListing = false
    await update($, busy, () => null)
  }
}

function startList($: EngineInterface) {
  $.clock.after(0, () => {
    list($).catch(() => undefined)
  })
}

async function offerable($: EngineInterface): Promise<SweepRow[]> {
  const current = await read($, scan)
  if (current.phase !== 'ok') return []
  const mine = await read($, folders)
  return current.rows.filter(row => isOfferable(row, mine))
}

// Removes each path in turn with --remove-path, which judges it again first, notes what
// the script said for each, and lists the worktrees again once at the end. The chat's
// folders are read again before each path, since a shell `cd` can move the chat into a
// worktree after the listing or while an earlier removal runs.
async function remove($: EngineInterface, paths: readonly string[]): Promise<void> {
  if (isRemoving || isListing || paths.length === 0) return
  isRemoving = true
  const said: string[] = []
  try {
    await update($, isConfirming, () => false)
    for (const path of paths) {
      const { root, list: mine } = await chatFolders($)
      if (holdsChat(path, mine)) {
        said.push(`kept ${path}: this chat runs here`)
        await update($, notes, () => [...said])
        continue
      }
      await update($, busy, () => `Removing ${path}…`)
      try {
        const result = await $.process.run(removeArgv($.plugin.root, path), { cwd: root, timeoutMs: REMOVE_TIMEOUT_MS })
        said.push(removalNote(path, result))
      } catch (error) {
        said.push(`kept ${path}: ${String(error)}`)
      }
      await update($, notes, () => [...said])
    }
  } finally {
    isRemoving = false
    await update($, busy, () => null)
  }
  await list($)
}

async function openPane($: EngineInterface): Promise<void> {
  await $.ui.open({ id: PANE, title: TITLE })
  startList($)
}

// Open in /mods writes an empty file named for this mod and this chat: open the pane and
// remove the file.
async function checkOpen($: EngineInterface): Promise<void> {
  if ((await read($, switches)).isOff) return
  const path = `${await configFolder($)}/mods/.open-${NAME}-${await $.session.id()}`
  if (!(await $.fs.exists(path).catch(() => false))) return
  await $.process.run(['rm', '-f', path])
  await openPane($)
}

async function poll($: EngineInterface): Promise<void> {
  const before = await read($, switches)
  const now = await readSwitches($)
  if (before.isOff && !now.isOff) startList($)
  await checkOpen($)
}

export const register: Register = on => {
  for (const timer of timers) timer.cancel()
  timers = []
  config = null
  isListing = false
  isRemoving = false
  isListingAgain = false

  on('session.start', async ($, e, next) => {
    await $.command.register({ name: NAME, description: 'List the worktrees of this repository and remove the done ones', immediate: true })
    const state = await readSwitches($)
    timers = [
      $.clock.every(SWITCH_MS, () => {
        poll($).catch(() => undefined)
      }),
      $.clock.every(LIST_MS, () => {
        read($, switches)
          .then(now => (now.isOff || now.isHidden ? undefined : list($)))
          .catch(() => undefined)
      }),
    ]
    if (!state.isOff && !state.isHidden) startList($)
    return next(e)
  })

  on('command.run', { command: NAME }, async $ => {
    if ((await readSwitches($)).isOff) return { text: 'Worktree sweeper is switched off in switches.json. Open /mods to turn it on.' }
    await openPane($)
    return { text: 'The worktree sweeper pane is open.' }
  })

  on('ui.close', async ($, e, next) => {
    if (e.id === PANE) {
      await update($, isConfirming, () => false)
      await update($, notes, () => [])
    }
    return next(e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const state = await read($, switches)
    if (e.props.hasSurvey || state.isOff || state.isHidden) return next(e)
    const count = (await offerable($)).length
    if (count === 0) return next(e)
    const { Box, Button, Text } = $.ui.resolve(e)
    return (
      <Box>
        <Text dimColor>{bandText(count)}</Text>
        <Button key="review" label="Review" onPress={() => openPane($)} />
      </Box>
    )
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Button, Text } = $.ui.resolve(e)
    const state = await read($, switches)
    const close = <Button key="close" label="Close" onPress={() => $.ui.close({ id: PANE })} />
    if (state.isOff) {
      return (
        <Box flexDirection="column">
          <Text>Worktree sweeper is turned off. Open /mods to turn it on.</Text>
          {close}
        </Box>
      )
    }
    const current = await read($, scan)
    const mine = await read($, folders)
    const working = await read($, busy)
    const said = await read($, notes)
    const confirming = await read($, isConfirming)
    const ready = current.phase === 'ok' ? current.rows.filter(row => isOfferable(row, mine)) : []
    const paths = ready.map(row => row.path)

    const rows = current.rows.map((row, index) => (
      <Box key={`row-${index}`} flexDirection="column">
        <Text bold>{row.worktree}</Text>
        <Text dimColor>
          {row.branch} · {row.pullRequest} · uncommitted {row.uncommitted} · unpushed {row.unpushed}
        </Text>
        <Text>
          {row.verdict}
          {isThisChat(row, mine) ? ' (this chat runs here)' : ''}
        </Text>
        {working === null && isOfferable(row, mine) ? (
          <Button key={`remove-${index}`} label="Remove" onPress={() => remove($, [row.path])} />
        ) : null}
      </Box>
    ))

    const footer =
      working !== null ? (
        <Text dimColor>{working}</Text>
      ) : (
        <Box>
          {paths.length === 0 ? null : confirming ? (
            <Box>
              <Button key="confirm-all" label={`Remove ${paths.length}`} onPress={() => remove($, paths)} />
              <Text> </Text>
              <Button key="cancel-all" label="Cancel" onPress={() => update($, isConfirming, () => false)} />
              <Text> </Text>
            </Box>
          ) : (
            <Box>
              <Button key="remove-all" label={`Remove all done (${paths.length})`} onPress={() => update($, isConfirming, () => true)} />
              <Text> </Text>
            </Box>
          )}
          <Button key="refresh" label="Refresh" onPress={() => startList($)} />
          <Text> </Text>
          {close}
        </Box>
      )

    return (
      <Box flexDirection="column">
        {current.phase === 'idle' ? <Text dimColor>The worktrees have not been listed yet.</Text> : null}
        {current.phase === 'failed' ? <Text>{current.error}</Text> : null}
        {current.phase === 'ok' && current.rows.length === 0 ? <Text dimColor>No worktrees besides the main checkout.</Text> : null}
        {rows}
        {said.map(line => (
          <Text dimColor>
            {line}
          </Text>
        ))}
        {confirming && working === null ? (
          <Text>Each worktree goes with any files git ignores in it, such as node_modules or .env files.</Text>
        ) : null}
        {footer}
        <Text dimColor>Remove runs the same checks as worktree-cleanup.sh --remove. The branch stays.</Text>
      </Box>
    )
  })
}
