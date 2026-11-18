// The /mods switchboard: a pane that lists every mod on this computer and switches
// each one on or off in every chat.
//
// /mods looks for mods where Claude Code loads them from: this chat's dev mods, the
// folders in CLAUDE_CODE_PLUGIN_DIRS, the mods folder in the configuration folder,
// and the installed plugins that settings.json turns on. A mod is a plugin whose
// hooks.json lists a module. What each one can do is read from its source: a switch
// when it reads switches.json, Show/Hide when it draws a band or a pane, and Reopen
// when its pane opens again on a marker file. The switches live in
// mods/switches.json, which every mod that honors them reads for itself, so a change
// reaches every open chat once each mod reads the file again.

import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { ModGroup, ModRow, SwitchChange } from '../types'
import {
  applySwitch,
  asObject,
  configDir,
  dedupe,
  hooksModules,
  installedPaths,
  markerPath,
  parseSwitches,
  rowFor,
  scanFeatures,
  splitPathList,
} from './mods'
import type { FoundMod, Switches } from './mods'

// This plugin's own name, left out of the list.
const SELF = 'mods'
const PANE = 'mods'
const TITLE = 'Mods'
const GROUPS: readonly { group: ModGroup; heading: string }[] = [
  { group: 'token savers', heading: 'Token savers' },
  { group: 'chat tools', heading: 'Chat tools' },
  { group: 'display', heading: 'Display' },
]
// How often the open pane reads switches.json again, to show a change made in
// another chat.
const POLL_MS = 3000
// The source files a mod's features are read from.
const SOURCE = /\.(tsx?|jsx?|mjs|cjs|mts|cts)$/
const TEST = /\.test\.[a-z]+$/

const rows = atom({ plugin: 'mods', key: 'rows' } as const, [] as ModRow[], { shape: 'rows-1' })
const switches = atom({ plugin: 'mods', key: 'switches' } as const, { isReadable: true, values: {} } as Switches)
const note = atom({ plugin: 'mods', key: 'note' } as const, '')
// This chat's session id, which a Reopen marker names; empty when there is none.
const chat = atom({ plugin: 'mods', key: 'chat' } as const, '')

let poll: { cancel: () => void } | null = null
let lastSwitches: string | undefined
// Each read of switches.json is numbered, so a slow read never replaces what a
// later one found.
let readsStarted = 0
let newestApplied = 0

async function readText($: EngineInterface, path: string): Promise<string | undefined> {
  return $.fs.read(path).then(
    value => (typeof value === 'string' ? value : undefined),
    () => undefined,
  )
}

async function listNames($: EngineInterface, path: string): Promise<string[]> {
  return $.fs.list(path).then(
    entries => entries.map(entry => entry.name).sort(),
    () => [],
  )
}

async function configFolder($: EngineInterface): Promise<string | null> {
  return configDir(await $.env.get('HOME'), await $.env.get('CLAUDE_CONFIG_DIR'))
}

async function sessionId($: EngineInterface): Promise<string> {
  return $.session.id().catch(() => '')
}

// The mod in `folder`, or null when the folder holds no plugin with a hooks module.
async function modAt($: EngineInterface, folder: string): Promise<FoundMod | null> {
  const manifest = await readText($, `${folder}/.claude-plugin/plugin.json`)
  const hooks = await readText($, `${folder}/hooks/hooks.json`)
  if (manifest === undefined || hooks === undefined || hooksModules(hooks).length === 0) return null
  const record = asObject(manifest)
  if (record === null) return null
  const { name, description } = record
  if (typeof name !== 'string' || name === '') return null
  return { name, description: typeof description === 'string' ? description : '', path: folder, alsoAt: [] }
}

// The plugin folders inside `folder`: the folder itself when it is one, else each
// child that is.
async function pluginFolders($: EngineInterface, folder: string): Promise<string[]> {
  if (await $.fs.exists(`${folder}/.claude-plugin/plugin.json`).catch(() => false)) return [folder]
  return (await listNames($, folder)).map(name => `${folder}/${name}`)
}

// The source files under `folder`, at any depth, leaving out tests and node_modules.
async function sourceFiles($: EngineInterface, folder: string): Promise<string[]> {
  const files: string[] = []
  const entries = await $.fs.list(folder).catch(() => [])
  for (const entry of [...entries].sort((a, b) => a.name.localeCompare(b.name))) {
    const path = `${folder}/${entry.name}`
    if (entry.kind === 'dir') {
      if (entry.name !== 'node_modules') files.push(...(await sourceFiles($, path)))
    } else if (SOURCE.test(entry.name) && !TEST.test(entry.name)) {
      files.push(path)
    }
  }
  return files
}

async function scan($: EngineInterface): Promise<ModRow[]> {
  const config = await configFolder($)
  const session = await sessionId($)
  const root = await $.session.root().catch(() => '')
  const folders: string[] = []
  if (config !== null && session !== '') folders.push(...(await pluginFolders($, `${config}/dev-mods/${session}`)))
  for (const dir of splitPathList(await $.env.get('CLAUDE_CODE_PLUGIN_DIRS'))) {
    folders.push(...(await pluginFolders($, dir)))
  }
  if (config !== null) {
    folders.push(...(await listNames($, `${config}/mods`)).map(name => `${config}/mods/${name}`))
    const settings: string[] = []
    for (const path of [`${config}/settings.json`, `${root}/.claude/settings.json`, `${root}/.claude/settings.local.json`]) {
      const text = root === '' && !path.startsWith(config) ? undefined : await readText($, path)
      if (text !== undefined) settings.push(text)
    }
    folders.push(...installedPaths(await readText($, `${config}/plugins/installed_plugins.json`), settings, root))
  }
  const found: FoundMod[] = []
  for (const folder of folders) {
    const mod = await modAt($, folder)
    if (mod !== null && mod.name !== SELF) found.push(mod)
  }
  const result: ModRow[] = []
  for (const mod of dedupe(found)) {
    const sources: string[] = []
    for (const file of await sourceFiles($, `${mod.path}/hooks`)) {
      const text = await readText($, file)
      if (text !== undefined) sources.push(text)
    }
    result.push(rowFor(mod, scanFeatures(sources)))
  }
  return result
}

async function readSwitches($: EngineInterface): Promise<string | undefined> {
  const number = ++readsStarted
  const config = await configFolder($)
  const text = config === null ? undefined : await readText($, `${config}/mods/switches.json`)
  if (number < newestApplied) return text
  newestApplied = number
  if (text !== lastSwitches) {
    lastSwitches = text
    await update($, switches, () => parseSwitches(text))
  }
  return text
}

function startPoll($: EngineInterface) {
  poll ??= $.clock.every(POLL_MS, () => {
    readSwitches($).catch(() => undefined)
  })
}

function stopPoll() {
  poll?.cancel()
  poll = null
}

async function closePane($: EngineInterface) {
  stopPoll()
  await $.ui.close({ id: PANE }).catch(() => undefined)
}

async function change($: EngineInterface, name: string, what: SwitchChange) {
  const config = await configFolder($)
  if (config === null) return
  // Read again right before the write, so a change made in another chat since the
  // pane last read the file is kept.
  const text = await readSwitches($)
  const next = applySwitch(text, name, what)
  if (next === null) return
  await $.fs.write(`${config}/mods/switches.json`, next)
  await readSwitches($)
}

async function reopen($: EngineInterface, row: ModRow) {
  const config = await configFolder($)
  const session = await sessionId($)
  if (config === null || session === '') return
  const path = markerPath(config, row.name, session)
  if (!(await $.fs.exists(path).catch(() => false))) await $.fs.write(path, '')
  $.ui.toast(`Asked ${row.title} to open its pane.`)
}

async function refresh($: EngineInterface) {
  const found = await scan($)
  await update($, rows, () => found)
  await readSwitches($)
  const config = await configFolder($)
  const session = await sessionId($)
  await update($, chat, () => session)
  await update($, note, () => (config === null ? 'HOME is not set, so no configuration folder was found.' : ''))
}

export const register: Register = on => {
  stopPoll()
  lastSwitches = undefined
  readsStarted = 0
  newestApplied = 0

  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'mods',
      description: 'List the mods on this computer and switch them on or off in every chat',
    })
    // A reload stops the timer but can leave the pane open: start it again.
    const panes = await $.ui.panes().catch(() => [])
    if (panes.some(pane => pane.id === PANE)) startPoll($)
    return next(e)
  })

  on('command.run', { command: 'mods' }, async $ => {
    await refresh($)
    const opened = await $.ui.open({ id: PANE, title: TITLE })
    startPoll($)
    const count = (await read($, rows)).length
    const where = opened.isPlaced ? '' : ` The pane is open but not drawn: ${opened.reason}.`
    return { text: `Mods pane opened: ${count} ${count === 1 ? 'mod' : 'mods'} found.${where}` }
  })

  on('ui.close', async ($, e, next) => {
    if (e.id === PANE) stopPoll()
    return next(e)
  }).catch(($, e, next) => next(e))

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Button, Text } = $.ui.resolve(e)
    const list = await read($, rows)
    const state = await read($, switches)
    const footer = await read($, note)
    const session = await read($, chat)
    const values = state.values
    const lines = []
    if (list.length === 0) lines.push(<Text dimColor>No mods found.</Text>)
    if (!state.isReadable) {
      lines.push(<Text color="red">switches.json is not a JSON object, so nothing can be switched until it is fixed.</Text>)
    }
    for (const { group, heading } of GROUPS) {
      const members = list.filter(row => row.group === group)
      if (members.length === 0) continue
      lines.push(<Text bold>{heading}</Text>)
      for (const row of members) {
        const isOff = values[row.name] === false
        const isHidden = values[`${row.name}:hidden`] === true
        const { hasSwitch, hasBand, hasPane, canReopen } = row.features
        const status = !hasSwitch ? '' : isOff ? ' · Off' : isHidden ? ' · On, hidden' : ' · On'
        lines.push(
          <Box flexDirection="column">
            <Text>
              {row.title}
              {status}
            </Text>
            {row.tip !== '' && <Text dimColor>{row.tip}</Text>}
            {!hasSwitch && <Text dimColor>Does not read switches.json, so it cannot be switched from here.</Text>}
            <Text dimColor>{[row.path, ...row.alsoAt.map(path => `also at ${path}`)].join(' · ')}</Text>
            {hasSwitch && state.isReadable && (
              <Box>
                <Button
                  key={`switch-${row.name}`}
                  label={isOff ? 'Turn on' : 'Turn off'}
                  onPress={() => change($, row.name, { isOff: !isOff })}
                />
                {(hasBand || hasPane) && (
                  <Button
                    key={`hide-${row.name}`}
                    label={isHidden ? 'Show' : 'Hide'}
                    onPress={() => change($, row.name, { isHidden: !isHidden })}
                  />
                )}
              </Box>
            )}
            {canReopen && !isOff && session !== '' && (
              <Button key={`reopen-${row.name}`} label="Reopen" onPress={() => reopen($, row)} />
            )}
          </Box>,
        )
      }
    }
    if (footer !== '') lines.push(<Text dimColor>{footer}</Text>)
    lines.push(<Button key="close" label="Close" onPress={() => closePane($)} />)
    return <Box flexDirection="column">{lines}</Box>
  })
}
