import { expect, test } from 'claude-code/testing'

import {
  applySwitch,
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

test('switches.json reads as a map of the true and false values, or as unreadable', () => {
  expect(parseSwitches(undefined)).toEqual({ isReadable: true, values: {} })
  expect(parseSwitches('{"a": false, "a:hidden": true, "b": 3}')).toEqual({
    isReadable: true,
    values: { a: false, 'a:hidden': true },
  })
  expect(parseSwitches('not json').isReadable).toBe(false)
  expect(parseSwitches('[false]').isReadable).toBe(false)
  expect(parseSwitches('null').isReadable).toBe(false)
})

test('a switch change keeps every other key, and On or Shown removes the key', () => {
  const text = '{\n  "other": false,\n  "keep": "a string another tool wrote"\n}\n'
  const off = applySwitch(text, 'effort-optimizer', { isOff: true })
  expect(JSON.parse(off ?? '')).toEqual({ other: false, keep: 'a string another tool wrote', 'effort-optimizer': false })
  expect(off?.endsWith('\n')).toBe(true)

  const hidden = applySwitch(off ?? undefined, 'effort-optimizer', { isHidden: true })
  expect(JSON.parse(hidden ?? '')['effort-optimizer:hidden']).toBe(true)

  const on = applySwitch(hidden ?? undefined, 'effort-optimizer', { isOff: false, isHidden: false })
  expect(JSON.parse(on ?? '')).toEqual({ other: false, keep: 'a string another tool wrote' })

  expect(JSON.parse(applySwitch(undefined, 'x', { isOff: true }) ?? '')).toEqual({ x: false })
})

test('an unreadable switches.json is never overwritten', () => {
  expect(applySwitch('{broken', 'x', { isOff: true })).toBeNull()
  expect(applySwitch('[1]', 'x', { isOff: true })).toBeNull()
})

test('a hooks.json counts only with a non-empty modules list', () => {
  expect(hooksModules('{ "modules": ["./register.tsx"] }')).toEqual(['./register.tsx'])
  expect(hooksModules('{ "modules": [] }')).toEqual([])
  expect(hooksModules('{ "hooks": {} }')).toEqual([])
  expect(hooksModules('nope')).toEqual([])
})

test('features are read from the source text', () => {
  const band = "on('ui.render', { component: 'AbovePrompt' }, h)\nconst path = `${dir}/mods/switches.json`"
  const pane = 'on("ui.render", { component: "Pane", requestId: PANE }, h)\nconst marker = `${dir}/mods/.open-${NAME}-${session}`'
  expect(scanFeatures([band])).toEqual({ hasSwitch: true, hasBand: true, hasPane: false, canReopen: false })
  expect(scanFeatures([band, pane])).toEqual({ hasSwitch: true, hasBand: true, hasPane: true, canReopen: true })
  expect(scanFeatures(['export const register = () => {}'])).toEqual({
    hasSwitch: false,
    hasBand: false,
    hasPane: false,
    canReopen: false,
  })
})

const NONE = { hasSwitch: false, hasBand: false, hasPane: false, canReopen: false }

test('an Overmind mod takes its title, group and tip from the catalog', () => {
  const row = rowFor({ name: 'effort-optimizer', description: 'ignored', path: '/p/eo', alsoAt: [] }, { ...NONE, hasSwitch: true, hasBand: true })
  expect(row.title).toBe('Effort optimizer')
  expect(row.group).toBe('token savers')
  expect(row.tip).not.toBe('')
})

test('worktree-sweeper is a chat tool with its own title and tip', () => {
  const row = rowFor({ name: 'worktree-sweeper', description: 'ignored', path: '/p/ws', alsoAt: [] }, { hasSwitch: true, hasBand: true, hasPane: true, canReopen: true })
  expect(row.title).toBe('Worktree sweeper')
  expect(row.group).toBe('chat tools')
  expect(row.tip).toMatch(/worktree-cleanup\.sh/)
})

test('pin-drift is a display mod with its own title and tip', () => {
  const row = rowFor({ name: 'pin-drift', description: 'ignored', path: '/p/pd', alsoAt: [] }, { hasSwitch: true, hasBand: true, hasPane: true, canReopen: true })
  expect(row.title).toBe('Pin drift')
  expect(row.group).toBe('display')
  expect(row.tip).toMatch(/latest tag/)
})

test('any other mod shows its own name and description, grouped by what it draws', () => {
  const found = { name: 'clock', description: 'A clock in a pane', path: '/p/clock', alsoAt: ['/q/clock'] }
  expect(rowFor(found, { ...NONE, hasPane: true })).toEqual({
    name: 'clock',
    title: 'clock',
    group: 'display',
    tip: 'A clock in a pane',
    path: '/p/clock',
    alsoAt: ['/q/clock'],
    features: { ...NONE, hasPane: true },
  })
  expect(rowFor(found, { ...NONE, hasSwitch: true, hasPane: true }).group).toBe('display')
  expect(rowFor(found, NONE).group).toBe('chat tools')
})

test('the configuration folder is CLAUDE_CONFIG_DIR when set, else ~/.claude', () => {
  expect(configDir('/home/me', undefined)).toBe('/home/me/.claude')
  expect(configDir('/home/me', '')).toBe('/home/me/.claude')
  expect(configDir('/home/me', '/cfg/')).toBe('/cfg')
  expect(configDir(undefined, undefined)).toBeNull()
  expect(configDir('/home/me', '~/cc')).toBe('/home/me/cc')
  expect(configDir('/home/me', '~')).toBe('/home/me')
  expect(configDir('/', undefined)).toBe('/.claude')
  expect(configDir('/home/me', '~//cc')).toBe('/home/me/cc')
})

test('CLAUDE_CODE_PLUGIN_DIRS splits on colons and drops empty parts', () => {
  expect(splitPathList(undefined)).toEqual([])
  expect(splitPathList('/a::/b/ ')).toEqual(['/a', '/b'])
})

const INSTALLED = JSON.stringify({
  version: 2,
  plugins: {
    'effort-optimizer@att-docs': [{ scope: 'user', installPath: '/cache/eo' }],
    'model-router@att-docs': [{ scope: 'user', installPath: '/cache/mr' }],
    'local@att-docs': [
      { scope: 'project', projectPath: '/elsewhere', installPath: '/cache/other' },
      { scope: 'local', projectPath: '/repo', installPath: '/cache/local' },
    ],
    'broken@att-docs': 'not a list',
  },
})

test('installed plugins count when settings.json turns them on, user-wide or for this project', () => {
  const settings = '{"enabledPlugins": {"effort-optimizer@att-docs": true, "model-router@att-docs": false, "local@att-docs": true, "broken@att-docs": true}}'
  expect(installedPaths(INSTALLED, [settings], '/repo')).toEqual(['/cache/eo', '/cache/local'])
  expect(installedPaths(INSTALLED, ['{}', settings], '/repo')).toEqual(['/cache/eo', '/cache/local'])
  expect(installedPaths(INSTALLED, ['nope'], '/repo')).toEqual([])
  expect(installedPaths('nope', [settings], '/repo')).toEqual([])
  expect(installedPaths(undefined, [settings], '/repo')).toEqual([])
})

test('a name found twice keeps the first folder and notes the others', () => {
  const found = dedupe([
    { name: 'a', description: 'dev copy', path: '/dev/a', alsoAt: [] },
    { name: 'b', description: '', path: '/x/b', alsoAt: [] },
    { name: 'a', description: 'installed', path: '/cache/a', alsoAt: [] },
    { name: 'a', description: 'installed', path: '/dev/a', alsoAt: [] },
  ])
  expect(found).toEqual([
    { name: 'a', description: 'dev copy', path: '/dev/a', alsoAt: ['/cache/a'] },
    { name: 'b', description: '', path: '/x/b', alsoAt: [] },
  ])
})

test('the reopen marker is named for the mod and the chat', () => {
  expect(markerPath('/home/me/.claude', 'model-router', 's1')).toBe('/home/me/.claude/mods/.open-model-router-s1')
})
