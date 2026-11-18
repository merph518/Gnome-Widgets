import { expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'
import type { Engine } from 'claude-code/testing'

const CFG = '/home/me/.claude'
const SWITCHES = `${CFG}/mods/switches.json`

const json = (value: unknown) => JSON.stringify(value)
const plugin = (name: string, description = '') => json({ name, description })
const HOOKS = json({ modules: ['./register.tsx'] })

// A machine with three installed Overmind mods, one skills-only plugin, a mod from
// somewhere else in the mods folder, and this plugin itself loaded as a dev mod.
function files(): Record<string, string> {
  return {
    [`${CFG}/plugins/installed_plugins.json`]: json({
      version: 2,
      plugins: {
        'effort-optimizer@att-docs': [{ scope: 'user', installPath: '/cache/eo' }],
        'model-router@att-docs': [{ scope: 'user', installPath: '/cache/mr' }],
        'general@att-docs': [{ scope: 'user', installPath: '/cache/gen' }],
        'att-docs@att-docs': [{ scope: 'user', installPath: '/cache/docs' }],
      },
    }),
    [`${CFG}/settings.json`]: json({
      enabledPlugins: {
        'effort-optimizer@att-docs': true,
        'model-router@att-docs': true,
        'general@att-docs': true,
        'att-docs@att-docs': true,
      },
    }),
    '/cache/eo/.claude-plugin/plugin.json': plugin('effort-optimizer'),
    '/cache/eo/hooks/hooks.json': HOOKS,
    '/cache/eo/hooks/register.tsx': "read('mods/switches.json'); on('ui.render', { component: 'AbovePrompt' }, h)",
    '/cache/mr/.claude-plugin/plugin.json': plugin('model-router'),
    '/cache/mr/hooks/hooks.json': json({ modules: ['./model-router.ts'] }),
    '/cache/mr/hooks/model-router.ts': 'const path = `${dir}/mods/switches.json`; const m = `${dir}/mods/.open-${NAME}`',
    '/cache/mr/hooks/pane.tsx': "on('ui.render', { component: 'Pane', requestId: PANE }, h)",
    '/cache/gen/.claude-plugin/plugin.json': plugin('general'),
    '/cache/gen/hooks/hooks.json': HOOKS,
    '/cache/gen/hooks/register.tsx': 'export const register = () => {}',
    '/cache/gen/hooks/register.test.tsx': "// mentions switches.json, but only in a test",
    '/cache/docs/.claude-plugin/plugin.json': plugin('att-docs'),
    [`${CFG}/mods/clock/.claude-plugin/plugin.json`]: plugin('clock', 'A clock in a pane'),
    [`${CFG}/mods/clock/hooks/hooks.json`]: HOOKS,
    [`${CFG}/mods/clock/hooks/register.tsx`]: "on('ui.render', { component: 'Pane', requestId: 'clock' }, h)",
    [`${CFG}/dev-mods/s1/mods/.claude-plugin/plugin.json`]: plugin('mods'),
    [`${CFG}/dev-mods/s1/mods/hooks/hooks.json`]: HOOKS,
    [`${CFG}/dev-mods/s1/mods/hooks/register.tsx`]: "switches.json component: 'Pane'",
  }
}

// Stands in for the engine and the file system beneath the plugin.
function engine(on: On, extra: Record<string, string> = {}, env: Record<string, string> = {}, session = 's1') {
  const fs = { ...files(), ...extra }
  const seen = { opened: [] as string[], closed: [] as string[], reads: [] as string[], toasts: [] as string[], hold: undefined as Promise<void> | undefined }
  const isDir = (path: string) => Object.keys(fs).some(file => file.startsWith(`${path}/`))
  mock.env(on, { HOME: '/home/me', ...env })
  mock.store(on)
  const clock = mock.clock(on)
  on('session.id', () => (session === '' ? { deny: 'no session' } : { value: session }) as never)
  on('session.root', () => ({ value: '/repo' }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('command.register', () => ({ value: { command: 'mods' } }))
  on('ui.open', (_, e) => {
    seen.opened.push(e.id)
    return { value: { isPlaced: true } }
  })
  on('ui.close', (_, e) => {
    seen.closed.push(e.id)
    return { value: undefined } as never
  })
  // The panes the engine has open: those opened and not closed since.
  on('ui.panes', () => ({
    value: seen.opened.filter(id => !seen.closed.includes(id)).map(id => ({ id, isPlaced: true })),
  }) as never)
  on('ui.toast', (_, e) => {
    seen.toasts.push(e.text)
    return { value: undefined } as never
  })
  on('fs.read', async (_, e) => {
    seen.reads.push(e.path)
    // A read of switches.json can be held back, to answer after a later read.
    const hold = e.path === SWITCHES ? seen.hold : undefined
    const result = e.path in fs ? { value: fs[e.path] as string } : { deny: 'ENOENT' }
    if (hold !== undefined) await hold
    return result
  })
  on('fs.exists', (_, e) => ({ value: e.path in fs || isDir(e.path) }))
  on('fs.list', (_, e) => {
    if (!isDir(e.path)) return { deny: 'ENOENT' }
    const names = new Set(
      Object.keys(fs)
        .filter(file => file.startsWith(`${e.path}/`))
        .map(file => file.slice(e.path.length + 1).split('/')[0] as string),
    )
    return {
      value: [...names].map(name => ({
        name,
        // A linked plugin folder lists as `other`.
        kind: `${e.path}/${name}` in fs ? ('file' as const) : name.startsWith('link') ? ('other' as const) : ('dir' as const),
        size: 0,
        mtimeMs: 0,
        isLink: name.startsWith('link'),
      })),
    }
  })
  on('fs.write', (_, e) => {
    fs[e.path] = e.text
    return { value: undefined }
  })
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>engine</Text>
  })
  return { fs, seen, clock }
}

const PANE = {
  plugin: 'mods',
  component: 'Pane',
  requestId: 'mods',
  surface: 'desktop',
  props: {
    title: 'Mods',
    isFocused: false,
    bodyColumns: 60,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 40 },
    view: {},
  },
} as never

const DEV_ONLY = {
  [`${CFG}/dev-mods/s1/devonly/.claude-plugin/plugin.json`]: plugin('devonly'),
  [`${CFG}/dev-mods/s1/devonly/hooks/hooks.json`]: HOOKS,
}
// A plugin straight under dev-mods, which a chat with no id would read as its own.
const DEV_ROOT = {
  [`${CFG}/dev-mods/devonly/.claude-plugin/plugin.json`]: plugin('devonly'),
  [`${CFG}/dev-mods/devonly/hooks/hooks.json`]: HOOKS,
}

async function openMods($: Engine) {
  await $.session.start({ cwd: '/repo', surface: 'desktop', isInteractive: true } as never)
  return $.command.run({ command: 'mods', args: '', origin: { kind: 'composer' } } as never)
}

const texts = async (ui: { findAll: (q: { type: string }) => Promise<{ text?: string }[]> }) =>
  (await ui.findAll({ type: 'Text' })).map(one => one.text ?? '')

test('/mods opens the pane and lists the installed mods under their groups', async ($, on) => {
  const { seen } = engine(on)
  await openMods($)
  expect(seen.opened).toEqual(['mods'])

  const ui = await $.ui.mount(PANE)
  const all = (await texts(ui)).join('\n')
  for (const words of ['Token savers', 'Effort optimizer', 'Model router', 'Chat tools', 'General', 'Display', 'clock']) {
    expect(all).toContain(words)
  }
  expect(all.indexOf('Token savers')).toBeLessThan(all.indexOf('Effort optimizer'))
  expect(all.indexOf('Display')).toBeLessThan(all.indexOf('clock'))
  // A plugin with no hooks module is not a mod, and the switchboard leaves itself out.
  expect(all).not.toContain('att-docs')
  expect(all).not.toMatch(/^mods$/m)
  await ui.unmount()
})

test('Off and On write switches.json and keep what other mods keep there', async ($, on) => {
  const { fs } = engine(on, { [SWITCHES]: json({ other: false }) })
  await openMods($)
  const ui = await $.ui.mount(PANE)

  await ui.press({ key: 'switch-effort-optimizer' })
  expect(JSON.parse(fs[SWITCHES] as string)).toEqual({ other: false, 'effort-optimizer': false })
  expect((await ui.find({ type: 'Button', key: 'switch-effort-optimizer' }))?.text).toBe('Turn on')

  await ui.press({ key: 'switch-effort-optimizer' })
  expect(JSON.parse(fs[SWITCHES] as string)).toEqual({ other: false })
  expect((await ui.find({ type: 'Button', key: 'switch-effort-optimizer' }))?.text).toBe('Turn off')
  await ui.unmount()
})

test('Hide and Show write the hidden key for a mod that draws a band or pane', async ($, on) => {
  const { fs } = engine(on)
  await openMods($)
  const ui = await $.ui.mount(PANE)

  await ui.press({ key: 'hide-effort-optimizer' })
  expect(JSON.parse(fs[SWITCHES] as string)).toEqual({ 'effort-optimizer:hidden': true })
  await ui.press({ key: 'hide-effort-optimizer' })
  expect(JSON.parse(fs[SWITCHES] as string)).toEqual({})
  await ui.unmount()
})

test('Reopen asks a pane mod to open its pane again in this chat', async ($, on) => {
  const { fs } = engine(on)
  await openMods($)
  const ui = await $.ui.mount(PANE)

  expect(await ui.find({ type: 'Button', key: 'reopen-effort-optimizer' })).toBeUndefined()
  await ui.press({ key: 'reopen-model-router' })
  expect(fs[`${CFG}/mods/.open-model-router-s1`]).toBe('')
  await ui.unmount()
})

test('a mod that never reads switches.json says so and gets no switch', async ($, on) => {
  engine(on)
  await openMods($)
  const ui = await $.ui.mount(PANE)

  expect(await ui.find({ type: 'Button', key: 'switch-general' })).toBeUndefined()
  expect(await ui.find({ type: 'Button', key: 'switch-clock' })).toBeUndefined()
  expect((await texts(ui)).join('\n')).toMatch(/does not read switches\.json/i)
  await ui.unmount()
})

test('an unreadable switches.json is shown and never written over', async ($, on) => {
  const { fs } = engine(on, { [SWITCHES]: '{ not json' })
  await openMods($)
  const ui = await $.ui.mount(PANE)

  expect(await ui.find({ type: 'Button', key: 'switch-effort-optimizer' })).toBeUndefined()
  expect((await texts(ui)).join('\n')).toMatch(/switches\.json is not a JSON object/)
  expect(fs[SWITCHES]).toBe('{ not json')
  await ui.unmount()
})

test('a switch flipped in another chat shows in the open pane within a few seconds', async ($, on) => {
  const { fs, seen, clock } = engine(on)
  await openMods($)
  fs[SWITCHES] = json({ 'model-router': false })
  await clock.advance(3000)

  const ui = await $.ui.mount(PANE)
  expect((await ui.find({ type: 'Button', key: 'switch-model-router' }))?.text).toBe('Turn on')

  // Closed, the pane stops reading the file until /mods opens it again.
  await ui.press({ key: 'close' })
  await ui.unmount()
  const before = seen.reads.filter(path => path === SWITCHES).length
  await clock.advance(9000)
  expect(seen.reads.filter(path => path === SWITCHES).length).toBe(before)
  expect(seen.closed).toEqual(['mods'])
})

test('CLAUDE_CODE_PLUGIN_DIRS and dev mods are read before the installed copies', async ($, on) => {
  const extra = {
    '/work/eo/.claude-plugin/plugin.json': plugin('effort-optimizer'),
    '/work/eo/hooks/hooks.json': HOOKS,
    '/work/eo/hooks/register.tsx': 'switches.json',
  }
  engine(on, extra, { CLAUDE_CODE_PLUGIN_DIRS: '/work/eo' })
  await openMods($)
  const ui = await $.ui.mount(PANE)
  const all = (await texts(ui)).join('\n')
  expect(all).toContain('/work/eo')
  expect(all).toContain('/cache/eo')
  await ui.unmount()
})

test('Reopen needs a chat to name, and no dev mods are read without one', async ($, on) => {
  engine(on, DEV_ROOT, {}, '')
  await openMods($)
  let ui = await $.ui.mount(PANE)
  expect(await ui.find({ type: 'Button', key: 'reopen-model-router' })).toBeUndefined()
  await ui.unmount()

  // Without a chat there is no dev mods folder to read.
  ui = await $.ui.mount(PANE)
  expect((await texts(ui)).join('\n')).toContain('clock')
  expect((await texts(ui)).join('\n')).not.toContain('devonly')
  await ui.unmount()
})

test("this chat's dev mods are listed when there is a chat", async ($, on) => {
  engine(on, DEV_ONLY)
  await openMods($)
  const ui = await $.ui.mount(PANE)
  expect((await texts(ui)).join('\n')).toContain('devonly')
  await ui.unmount()
})

test('a slow read from before a switch press does not undo it', async ($, on) => {
  const { seen, clock } = engine(on)
  await openMods($)
  let release = () => {}
  seen.hold = new Promise<void>(resolve => {
    release = resolve
  })
  await clock.advance(3000)
  seen.hold = undefined

  const ui = await $.ui.mount(PANE)
  await ui.press({ key: 'switch-model-router' })
  release()
  // Let the held read finish.
  for (let turn = 0; turn < 20; turn++) await Promise.resolve()
  expect((await ui.find({ type: 'Button', key: 'switch-model-router' }))?.text).toBe('Turn on')
  await ui.unmount()
})

test('Reopen is hidden while a pane mod is off', async ($, on) => {
  engine(on, { [SWITCHES]: json({ 'model-router': false }) })
  await openMods($)
  const ui = await $.ui.mount(PANE)
  expect(await ui.find({ type: 'Button', key: 'reopen-model-router' })).toBeUndefined()
  await ui.unmount()
})

test('a pane mod with no switch can still be reopened, even when switches.json is unreadable', async ($, on) => {
  const { fs } = engine(on, {
    [SWITCHES]: '{ not json',
    [`${CFG}/mods/clock/hooks/marker.ts`]: 'const marker = `${dir}/mods/.open-clock-${session}`',
  })
  await openMods($)
  const ui = await $.ui.mount(PANE)
  expect(await ui.find({ type: 'Button', key: 'switch-clock' })).toBeUndefined()
  await ui.press({ key: 'reopen-clock' })
  expect(fs[`${CFG}/mods/.open-clock-s1`]).toBe('')
  await ui.unmount()
})

test('features are read from source files in folders under hooks/', async ($, on) => {
  engine(on, {
    [`${CFG}/mods/deep/.claude-plugin/plugin.json`]: plugin('deep'),
    [`${CFG}/mods/deep/hooks/hooks.json`]: HOOKS,
    [`${CFG}/mods/deep/hooks/register.tsx`]: "import { pane } from './ui/pane'; read('switches.json')",
    [`${CFG}/mods/deep/hooks/ui/pane.tsx`]: "on('ui.render', { component: 'Pane', requestId: 'deep' }, h)",
  })
  await openMods($)
  const ui = await $.ui.mount(PANE)
  expect(await ui.find({ type: 'Button', key: 'hide-deep' })).toBeDefined()
  await ui.unmount()
})

test('a linked plugin folder counts, and the switch key is the plugin.json name', async ($, on) => {
  const { fs } = engine(on, {
    [`${CFG}/mods/link-to-timer/.claude-plugin/plugin.json`]: plugin('timer', 'A timer'),
    [`${CFG}/mods/link-to-timer/hooks/hooks.json`]: HOOKS,
    [`${CFG}/mods/link-to-timer/hooks/register.tsx`]: 'switches.json',
  })
  await openMods($)
  const ui = await $.ui.mount(PANE)
  await ui.press({ key: 'switch-timer' })
  expect(JSON.parse(fs[SWITCHES] as string)).toEqual({ timer: false })
  await ui.unmount()
})

test('a broken plugin.json or hooks.json leaves that folder out', async ($, on) => {
  engine(on, {
    [`${CFG}/mods/bad1/.claude-plugin/plugin.json`]: '{ nope',
    [`${CFG}/mods/bad1/hooks/hooks.json`]: HOOKS,
    [`${CFG}/mods/bad2/.claude-plugin/plugin.json`]: plugin('bad2'),
    [`${CFG}/mods/bad2/hooks/hooks.json`]: '{ nope',
  })
  await openMods($)
  const ui = await $.ui.mount(PANE)
  const all = (await texts(ui)).join('\n')
  expect(all).not.toContain('bad1')
  expect(all).not.toContain('bad2')
  expect(all).toContain('clock')
  await ui.unmount()
})

test('after Close, /mods starts reading switches.json again', async ($, on) => {
  const { fs, clock } = engine(on)
  await openMods($)
  const ui = await $.ui.mount(PANE)
  await ui.press({ key: 'close' })
  await ui.unmount()

  await $.command.run({ command: 'mods', args: '', origin: { kind: 'composer' } } as never)
  fs[SWITCHES] = json({ 'model-router': false })
  await clock.advance(3000)
  const again = await $.ui.mount(PANE)
  expect((await again.find({ type: 'Button', key: 'switch-model-router' }))?.text).toBe('Turn on')
  await again.unmount()
})

test('a chat that starts while the pane is open reads switches.json every 3 seconds', async ($, on) => {
  const { seen, clock } = engine(on)
  seen.opened.push('mods')
  await $.session.start({ cwd: '/repo', surface: 'desktop', isInteractive: true } as never)
  const before = seen.reads.filter(path => path === SWITCHES).length
  await clock.advance(3000)
  expect(seen.reads.filter(path => path === SWITCHES).length).toBeGreaterThan(before)
})
