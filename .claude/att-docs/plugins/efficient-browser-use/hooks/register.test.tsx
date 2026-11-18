import { expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'
import type { Engine } from 'claude-code/testing'

// imagetool.sh's own behavior is tested on real pictures in scripts/imagetool_test.sh.
// Here the script is played by the stub below, through its output contract.

type Run = { stdout: string; exitCode?: number; isStdoutTruncated?: boolean }

type Setup = {
  /** What `imagetool.sh shrink` prints for each call, in turn; the last repeats. */
  shrink?: Run[]
  /** What `imagetool.sh size` prints. */
  size?: Run
  thumb?: Run
  /** What a tool answers, by tool name. */
  results?: Record<string, unknown>
  /** What the describer answers; null for a refusal. */
  describer?: string | null
  /** Only this many describer runs answer; later ones are refused. */
  describeOnly?: number
  switches?: string
}

const DESCRIBER_OFFER = {
  agent: 'efficient-browser-use:describer',
  description: 'Describes one picture in words for a model that cannot see it.',
  source: 'plugin',
  provider: { plugin: 'efficient-browser-use', tier: 'append' },
}

const NOIM = { stdout: 'NOIM\n', exitCode: 3 }

const TWO = {
  content: [
    { type: 'image', data: 'QQ==', mimeType: 'image/png' },
    { type: 'image', data: 'Qg==', mimeType: 'image/png' },
  ],
  isError: false,
}

const BIG = { stdout: 'IN 1600 900\nOUT 800 450\nU01BTEw=\n' }
// A real 1x1 PNG: the pane's Image checks the PNG signature.
const PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
const THUMB = { stdout: `THUMB 160 90\n${PNG}\n` }

const SCREENSHOT = {
  content: [
    { type: 'image', data: 'RlVMTA==', mimeType: 'image/png' },
    { type: 'text', text: 'Screenshot size: 1600x900' },
  ],
  isError: false,
}

function engine($: Engine, on: On, setup: Setup = {}) {
  const seen = {
    scripts: [] as { mode: string; args: readonly string[]; stdin?: string }[],
    toasts: [] as string[],
    agents: [] as Record<string, unknown>[],
    registered: [] as string[],
    opened: 0,
    files: {} as Record<string, string>,
    /** Whether Claude was offered the describer while the plugin was spawning it. */
    offeredDuringSpawn: [] as boolean[],
  }
  if (setup.switches !== undefined) seen.files['/home/me/.claude/mods/switches.json'] = setup.switches
  mock.env(on, { HOME: '/home/me', TMPDIR: '/tmp/t' })
  mock.store(on)
  const clock = mock.clock(on)
  let shrinkCall = 0
  on('session.id', () => ({ value: 's1' }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('command.register', () => ({ value: { command: 'efficient-browser' } }))
  on('agent.register', (_, e) => {
    seen.registered.push(e.name)
    return { value: { agent: `efficient-browser-use:${e.name}` } }
  })
  on('ui.open', () => {
    seen.opened += 1
    return { value: undefined } as never
  })
  on('ui.close', () => ({ value: undefined }) as never)
  on('ui.log', () => ({ value: undefined }) as never)
  on('ui.status', () => ({ value: undefined }) as never)
  on('ui.toast', (_, e) => {
    seen.toasts.push(e.text)
    return { value: undefined } as never
  })
  on('fs.exists', (_, e) => ({ value: e.path in seen.files }))
  on('fs.read', (_, e) => (e.path in seen.files ? { value: seen.files[e.path] as string } : { deny: 'no such file' }))
  on('fs.write', (_, e) => {
    seen.files[e.path] = e.text
    return { value: undefined }
  })
  on('process.run', (_, e) => {
    const ok = (stdout = '', exitCode = 0, isStdoutTruncated = false) => ({
      value: { exitCode, stdout, stderr: '', isStdoutTruncated, isStderrTruncated: false },
    })
    const [first, second, third] = e.argv
    if (first === '/bin/sh' && second?.endsWith('/scripts/imagetool.sh')) {
      seen.scripts.push({ mode: third ?? '', args: e.argv.slice(3), stdin: e.init?.stdin })
      if (third === 'thumb') {
        const t: Run = setup.thumb ?? THUMB
        return ok(t.stdout, t.exitCode ?? 0)
      }
      if (third === 'size') {
        const t: Run = setup.size ?? { stdout: 'IN 1600 900\n' }
        return ok(t.stdout, t.exitCode ?? 0)
      }
      const list = setup.shrink ?? [BIG]
      const r = list[Math.min(shrinkCall++, list.length - 1)] as Run
      return ok(r.stdout, r.exitCode ?? 0, r.isStdoutTruncated ?? false)
    }
    // appendFile and writePicture: sh -c <script> sh <path>
    const path = e.argv[4]
    if (first === '/bin/sh' && path) {
      if (second === '-c' && third?.includes('base64 -d')) seen.files[path] = `picture:${e.init?.stdin ?? ''}`
      else seen.files[path] = (seen.files[path] ?? '') + (e.init?.stdin ?? '')
    }
    if (first === '/bin/rm') delete seen.files[e.argv[2] as string]
    return ok()
  })
  on('agent.spawn', async (_, e) => {
    seen.agents.push(e as unknown as Record<string, unknown>)
    // Claude's own agent listing, asked while the plugin's spawn is under way.
    const offer = await $.agent.offer(DESCRIBER_OFFER as never)
    seen.offeredDuringSpawn.push(offer.isOffered)
    if (setup.describer === null) return { deny: 'refused' }
    if (setup.describeOnly !== undefined && seen.agents.length > setup.describeOnly) return { deny: 'refused' }
    // A hook's spawn gets no agentId here: the describer run is known by its Read.
    const agentId = `agent-${seen.agents.length}`
    const file = /in (\S+)\.$/.exec(String((e as { prompt?: unknown }).prompt))?.[1]
    const answer = setup.describer ?? 'A login form with two fields.'
    void Promise.resolve()
      .then(() => $.tool.call({ tool: 'Read', file_path: file, agentId } as never))
      .then(() => $.turn.complete({ answer, durationMs: 10, isAborted: false, turnId: 't1', agentId, reason: 'answer' } as never))
    return { model: 'haiku' }
  })
  on('turn.complete', () => ({ text: '' }))
  on('agent.offer', () => ({ isOffered: true }))
  on('tool.call', (_, e) => {
    const result = setup.results?.[e.tool] ?? SCREENSHOT
    return { ref: 1, text: 'core text', result } as never
  })
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>engine</Text>
  })
  return { seen, clock }
}

async function start($: Engine) {
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true } as never)
}

const BROWSER = 'mcp__Claude_Browser__computer'
const shot = ($: Engine, input: Record<string, unknown> = {}) => $.tool.call({ tool: BROWSER, action: 'screenshot', ...input } as never)

const pane = ($: Engine) =>
  $.ui.mount({
    plugin: 'efficient-browser-use',
    surface: 'terminal',
    component: 'Pane',
    requestId: 'efficient-browser-use',
    props: { title: 'Screenshot Shrinker', isFocused: true, bodyColumns: 80 } as never,
  })

type Mcp = { content: Record<string, unknown>[] }
const LEDGER = '/home/me/.claude/mods-logs/savings.jsonl'
const LOG = '/home/me/.claude/mods-logs/efficient-browser-use.log'

test('a browser screenshot reaches Claude shrunk, with the screenshot line naming the old frame', async ($, on) => {
  const { seen, clock } = engine($, on)
  await start($)
  const r = await shot($)
  await clock.settle()

  const shrinkRuns = seen.scripts.filter(s => s.mode === 'shrink')
  expect(shrinkRuns.length).toBe(1)
  expect(shrinkRuns[0]?.args).toEqual(['75', '768'])
  expect(shrinkRuns[0]?.stdin).toBe('RlVMTA==')
  const result = r.result as Mcp
  expect(result.content[0]).toEqual({ type: 'image', data: 'U01BTEw=', mimeType: 'image/png' })
  expect(result.content[1]).toEqual({ type: 'text', text: 'Screenshot size: 800x450 0.5-scale view; coordinate frame: 1600x900.' })
  expect(r.ref).toBe(undefined)
})

test('the pane shows a card with both sizes and the tokens saved', async ($, on) => {
  const { seen, clock } = engine($, on)
  await start($)
  await shot($)
  await clock.settle()

  expect(seen.opened > 0).toBe(true)
  const ui = await pane($)
  expect(await ui.find({ type: 'Text', text: '1600×900 → 800×450' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: '1,920 → 480 tokens' })).toBeDefined()
})

test('a ledger line goes to savings.jsonl with the tokens before and after', async ($, on) => {
  const { seen, clock } = engine($, on)
  await start($)
  await shot($)
  await clock.settle()

  const lines = (seen.files[LEDGER] ?? '').trim().split('\n')
  expect(lines.length).toBe(1)
  const line = JSON.parse(lines[0] as string)
  expect(line.mod).toBe('efficient-browser-use')
  expect(line.before).toBe(1920)
  expect(line.after).toBe(480)
  expect(line.measured).toBe('estimated')
})

test('a zoom, a screenshot at Claude’s own scale and a batch with either are left alone', async ($, on) => {
  const { seen, clock } = engine($, on)
  await start($)
  const zoom = await shot($, { action: 'zoom', region: [0, 0, 10, 10] })
  const scaled = await shot($, { scale: 0.4 })
  const batch = await $.tool.call({
    tool: 'mcp__Claude_Browser__browser_batch',
    actions: [{ name: 'computer', input: { action: 'zoom' } }],
  } as never)
  await clock.settle()

  expect(seen.scripts.length).toBe(0)
  for (const r of [zoom, scaled, batch]) expect(r.ref).toBe(1)
})

test('a small picture is skipped and the result goes through as the tool gave it', async ($, on) => {
  const { seen, clock } = engine($, on, { shrink: [{ stdout: 'IN 400 300\nSKIP\n' }] })
  await start($)
  const r = await shot($)
  await clock.settle()

  expect(r.ref).toBe(1)
  expect(seen.files[LEDGER]).toBe(undefined)
})

test('without ImageMagick pictures pass through and one toast names the apt package', async ($, on) => {
  const { seen, clock } = engine($, on, { shrink: [{ stdout: 'NOIM\n', exitCode: 3 }] })
  await start($)
  const first = await shot($)
  const second = await shot($)
  await clock.settle()

  expect(first.ref).toBe(1)
  expect(second.ref).toBe(1)
  expect(seen.toasts.length).toBe(1)
  expect(seen.toasts[0]).toMatch(/sudo apt install imagemagick/)
  expect((seen.files[LOG] ?? '').match(/sudo apt install imagemagick/g)?.length).toBe(1)
})

test('output cut at the size limit or an error exit passes the picture through', async ($, on) => {
  const { clock } = engine($, on, { shrink: [{ ...BIG, isStdoutTruncated: true }, { stdout: '', exitCode: 4 }] })
  await start($)
  const cut = await shot($)
  const failed = await shot($)
  await clock.settle()

  expect(cut.ref).toBe(1)
  expect(failed.ref).toBe(1)
})

test('/efficient-browser full lets the next picture through at full size, and only that one', async ($, on) => {
  const { seen, clock } = engine($, on)
  await start($)
  await $.command.run({ command: 'efficient-browser', args: 'full' } as never)
  const full = await shot($)
  const next = await shot($)
  await clock.settle()

  expect(full.ref).toBe(1)
  expect(next.ref).toBe(undefined)
  expect(seen.scripts.filter(s => s.mode === 'shrink').length).toBe(1)
})

test('a Read of a picture gets the smaller picture and its display size', async ($, on) => {
  const read = { type: 'image', file: { base64: 'RlVMTA==', type: 'image/gif', originalSize: 9, dimensions: { originalWidth: 1600, originalHeight: 900 } } }
  const { clock } = engine($, on, { results: { Read: read } })
  await start($)
  const r = await $.tool.call({ tool: 'Read', file_path: '/a.gif' } as never)
  await clock.settle()

  expect((r.result as typeof read).file).toEqual({
    base64: 'U01BTEw=',
    type: 'image/png',
    originalSize: 9,
    dimensions: { originalWidth: 1600, originalHeight: 900, displayWidth: 800, displayHeight: 450 },
  })
})

test('a result with no picture is not touched', async ($, on) => {
  const { seen, clock } = engine($, on, { results: { Bash: { stdout: 'hi', stderr: '' } } })
  await start($)
  const r = await $.tool.call({ tool: 'Bash', command: 'echo hi' } as never)
  await clock.settle()

  expect(r.ref).toBe(1)
  expect(seen.scripts.length).toBe(0)
})

test('switches.json turns the plugin off', async ($, on) => {
  const { seen, clock } = engine($, on, { switches: '{"efficient-browser-use": false}' })
  await start($)
  const r = await shot($)
  await clock.settle()

  expect(r.ref).toBe(1)
  expect(seen.scripts.length).toBe(0)
})

test('describe mode hands the picture to the describer and Claude reads its words', { options: { mode: 'describe' } }, async ($, on) => {
  const { seen, clock } = engine($, on)
  await start($)
  const r = await shot($)
  await clock.settle()

  expect(seen.registered).toEqual(['describer'])
  expect(seen.agents.length).toBe(1)
  expect(seen.agents[0]?.subagent_type).toBe('efficient-browser-use:describer')
  expect(String(seen.agents[0]?.prompt)).toMatch(/\/tmp\/t\/efficient-browser-use\/s1\/1\.png/)
  const result = r.result as Mcp
  expect(result.content[0]?.type).toBe('text')
  expect(String(result.content[0]?.text)).toMatch(/A login form with two fields\./)
  expect(seen.files[LEDGER]).toMatch(/"action":"describe"/)
})

test('describe mode reads the picture size with the size mode, not a full shrink', { options: { mode: 'describe' } }, async ($, on) => {
  const { seen, clock } = engine($, on)
  await start($)
  await shot($)
  await clock.settle()

  expect(seen.scripts.map(s => s.mode)).toEqual(['size', 'thumb'])
  const line = JSON.parse((seen.files[LEDGER] ?? '').trim())
  expect(line.before).toBe(1920)
  const ui = await pane($)
  expect(await ui.find({ type: 'Text', text: '1600×900' })).toBeDefined()
})

test('the describer is hidden from Claude and other agents are still offered', async ($, on) => {
  engine($, on)
  await start($)

  expect((await $.agent.offer(DESCRIBER_OFFER as never)).isOffered).toBe(false)
  const explore = { agent: 'Explore', description: 'Search', source: 'built-in', provider: { plugin: 'engine', tier: 'core' } }
  expect((await $.agent.offer(explore as never)).isOffered).toBe(true)
})

test('an offer of the describer while the plugin is spawning one is still refused', { options: { mode: 'describe' } }, async ($, on) => {
  const { seen, clock } = engine($, on, { results: { [BROWSER]: TWO } })
  await start($)
  await shot($)
  await clock.settle()

  expect(seen.agents.length).toBe(2)
  expect(seen.offeredDuringSpawn).toEqual([false, false])
})

test('with the default 75% a 1600x900 screenshot reaches Claude at 1200x675 and the pane shows both sizes', async ($, on) => {
  const { clock } = engine($, on, { shrink: [{ stdout: 'IN 1600 900\nOUT 1200 675\nU01BTEw=\n' }] })
  await start($)
  const r = await shot($)
  await clock.settle()

  expect((r.result as Mcp).content[1]).toEqual({ type: 'text', text: 'Screenshot size: 1200x675 0.75-scale view; coordinate frame: 1600x900.' })
  const ui = await pane($)
  expect(await ui.find({ type: 'Text', text: '1600×900 → 1200×675' })).toBeDefined()
})

test('describe mode falls back to shrinking when the describer is refused', { options: { mode: 'describe' } }, async ($, on) => {
  const { clock } = engine($, on, { describer: null })
  await start($)
  const r = await shot($)
  await clock.settle()

  expect((r.result as Mcp).content[0]).toEqual({ type: 'image', data: 'U01BTEw=', mimeType: 'image/png' })
})

test('describe mode still describes without ImageMagick, and logs no saving it cannot size', { options: { mode: 'describe' } }, async ($, on) => {
  const { seen, clock } = engine($, on, { shrink: [NOIM], size: NOIM })
  await start($)
  const first = await shot($)
  const second = await shot($)
  await clock.settle()

  for (const r of [first, second]) expect((r.result as Mcp).content[0]?.type).toBe('text')
  expect(seen.agents.length).toBe(2)
  expect(seen.toasts.length).toBe(1)
  expect(seen.toasts[0]).not.toMatch(/full size/)
  expect(seen.files[LEDGER]).toBe(undefined)
})

test('a picture the describer could not do keeps the words already written for the others', { options: { mode: 'describe' } }, async ($, on) => {
  const { clock } = engine($, on, { results: { [BROWSER]: TWO }, shrink: [NOIM], size: NOIM, describeOnly: 1 })
  await start($)
  const r = await shot($)
  await clock.settle()

  const content = (r.result as Mcp).content
  expect(content[0]?.type).toBe('text')
  expect(content[1]).toEqual({ type: 'image', data: 'Qg==', mimeType: 'image/png' })
})
