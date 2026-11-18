// What the plugin does to a tool result, with no engine calls: finding the pictures in it,
// swapping them, rewriting the screenshot size line, and reading imagetool.sh's output.

/** A picture as found in a tool result: its base64 and its media type. */
export type Found = { base64: string; mime: string }

/** A smaller copy of a picture: its new bytes and size, and the size it had. */
export type Shrunk = { base64: string; mime: string; w: number; h: number; inW: number; inH: number }

/** A picture written out in words. */
export type Words = { text: string }

/** What takes a picture's place: a smaller copy, words, or null to keep it as it was. */
export type Swap = Shrunk | Words | null

type Obj = Record<string, unknown>
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v)

// ---- Where pictures sit ----
// An MCP result holds content blocks, either in the SDK's form ({ type: 'image', data,
// mimeType }) or the API's ({ type: 'image', source: { type: 'base64', media_type, data } }),
// as a bare array or under `content`. Read answers { type: 'image', file: { base64, type } }.

function blocksOf(result: unknown): unknown[] | null {
  if (Array.isArray(result)) return result
  if (isObj(result) && Array.isArray(result.content)) return result.content
  return null
}

function blockImage(block: unknown): Found | null {
  if (!isObj(block) || block.type !== 'image') return null
  if (typeof block.data === 'string') return { base64: block.data, mime: typeof block.mimeType === 'string' ? block.mimeType : 'image/png' }
  const src = block.source
  if (isObj(src) && src.type === 'base64' && typeof src.data === 'string') {
    return { base64: src.data, mime: typeof src.media_type === 'string' ? src.media_type : 'image/png' }
  }
  return null
}

function readImage(result: unknown): Found | null {
  if (!isObj(result) || result.type !== 'image' || !isObj(result.file)) return null
  const f = result.file
  return typeof f.base64 === 'string' ? { base64: f.base64, mime: typeof f.type === 'string' ? f.type : 'image/png' } : null
}

/** Every picture in a tool result, in order. */
export function findImages(result: unknown): Found[] {
  const read = readImage(result)
  if (read) return [read]
  const blocks = blocksOf(result)
  if (!blocks) return []
  return blocks.map(blockImage).filter((f): f is Found => f !== null)
}

// ---- The screenshot size line ----
// The browser tools state the picture's size after each screenshot:
//   Screenshot size: 800x600
//   Screenshot size: 240x183 0.3-scale view; coordinate frame: 800x609.
// A click's coordinate is read in the coordinate frame, so a shrunk picture keeps the
// frame of the full one and says how much smaller it is.

const SIZE_LINE = /Screenshot size: (\d+)x(\d+)(?: [\d.]+-scale view; coordinate frame: (\d+)x(\d+)\.?)?/g

const ratio = (n: number) => String(Math.round(n * 100) / 100)

/** The line for a picture shown at `shown` whose clicks land in `frame`. */
export function frameLine(frame: { w: number; h: number }, shown: { w: number; h: number }): string {
  return `Screenshot size: ${shown.w}x${shown.h} ${ratio(shown.w / frame.w)}-scale view; coordinate frame: ${frame.w}x${frame.h}.`
}

type Cursor = { next: number; used: Set<number> }

function rewriteWith(text: string, sizes: readonly ({ w: number; h: number } | null)[], at: Cursor): string {
  return text.replace(SIZE_LINE, (line, w, h, fw, fh) => {
    const i = at.next++
    const shown = sizes[i]
    if (!shown) return line
    at.used.add(i)
    const frame = fw && fh ? { w: Number(fw), h: Number(fh) } : { w: Number(w), h: Number(h) }
    return frameLine(frame, shown)
  })
}

/** Rewrites each size line in `text` for the picture at the same place in `sizes`; null keeps a line. */
export function rewriteFrames(text: string, sizes: readonly ({ w: number; h: number } | null)[]): string {
  return rewriteWith(text, sizes, { next: 0, used: new Set() })
}

// ---- Swapping ----

const isShrunk = (s: Swap): s is Shrunk => s !== null && 'base64' in s

function swapBlock(block: unknown, s: Swap): unknown {
  if (s === null || !isObj(block)) return block
  if (!isShrunk(s)) return { type: 'text', text: s.text }
  if (typeof block.data === 'string') return { ...block, data: s.base64, mimeType: s.mime }
  return { ...block, source: { ...(block.source as Obj), media_type: s.mime, data: s.base64 } }
}

/**
 * A copy of `result` with the i-th picture replaced by `swaps[i]`, and the screenshot
 * size lines rewritten to match. `addFrame` appends a size line for a shrunk picture
 * that had none, for a browser screenshot. The input is not changed.
 */
export function replaceImages(result: unknown, swaps: readonly Swap[], opts: { addFrame?: boolean } = {}): unknown {
  if (readImage(result)) {
    const s = swaps[0] ?? null
    if (!isShrunk(s)) return result
    const r = result as Obj
    const file = r.file as Obj
    const dims = isObj(file.dimensions) ? file.dimensions : {}
    return {
      ...r,
      file: {
        ...file,
        base64: s.base64,
        type: s.mime,
        dimensions: {
          ...dims,
          originalWidth: typeof dims.originalWidth === 'number' ? dims.originalWidth : s.inW,
          originalHeight: typeof dims.originalHeight === 'number' ? dims.originalHeight : s.inH,
          displayWidth: s.w,
          displayHeight: s.h,
        },
      },
    }
  }
  const blocks = blocksOf(result)
  if (!blocks) return result
  let n = 0
  const swapped = blocks.map(b => (blockImage(b) ? swapBlock(b, swaps[n++] ?? null) : b))
  const sizes = swaps.map(s => (isShrunk(s) ? { w: s.w, h: s.h } : null))
  const at: Cursor = { next: 0, used: new Set() }
  const out = swapped.map(b => (isObj(b) && b.type === 'text' && typeof b.text === 'string' ? { ...b, text: rewriteWith(b.text, sizes, at) } : b))
  if (opts.addFrame) {
    swaps.forEach((s, i) => {
      if (isShrunk(s) && !at.used.has(i)) out.push({ type: 'text', text: frameLine({ w: s.inW, h: s.inH }, s) })
    })
  }
  return Array.isArray(result) ? out : { ...(result as Obj), content: out }
}

// ---- Calls to leave alone ----

const asksOwnSize = (input: unknown) => isObj(input) && (input.action === 'zoom' || typeof input.scale === 'number')

/** A zoom, a screenshot at Claude's own scale, or a batch holding either. */
export function leaveAlone(input: unknown): boolean {
  if (asksOwnSize(input)) return true
  if (isObj(input) && Array.isArray(input.actions)) return input.actions.some(a => isObj(a) && asksOwnSize(a.input))
  return false
}

// ---- imagetool.sh output ----

export type ShrinkOutput =
  | { kind: 'noim' }
  | { kind: 'skip'; inW: number; inH: number }
  | { kind: 'out'; inW: number; inH: number; w: number; h: number; base64: string }
  | { kind: 'bad'; why: string }

const B64 = /^[A-Za-z0-9+/]+=*$/

export function parseShrink(stdout: string, exitCode: number): ShrinkOutput {
  if (exitCode === 3 && stdout.trim() === 'NOIM') return { kind: 'noim' }
  if (exitCode !== 0) return { kind: 'bad', why: `exit ${exitCode}` }
  const [first = '', second = '', third = ''] = stdout.split('\n')
  const inLine = /^IN (\d+) (\d+)$/.exec(first)
  if (!inLine) return { kind: 'bad', why: `no IN line: ${JSON.stringify(first.slice(0, 80))}` }
  const inW = Number(inLine[1])
  const inH = Number(inLine[2])
  if (second === 'SKIP') return { kind: 'skip', inW, inH }
  const outLine = /^OUT (\d+) (\d+)$/.exec(second)
  if (!outLine) return { kind: 'bad', why: `no OUT or SKIP line: ${JSON.stringify(second.slice(0, 80))}` }
  if (!B64.test(third)) return { kind: 'bad', why: 'no picture after the OUT line' }
  return { kind: 'out', inW, inH, w: Number(outLine[1]), h: Number(outLine[2]), base64: third }
}

export type SizeOutput = { kind: 'noim' } | { kind: 'size'; w: number; h: number } | { kind: 'bad'; why: string }

/** Reads `imagetool.sh size`: one IN line. */
export function parseSize(stdout: string, exitCode: number): SizeOutput {
  if (exitCode === 3 && stdout.trim() === 'NOIM') return { kind: 'noim' }
  if (exitCode !== 0) return { kind: 'bad', why: `exit ${exitCode}` }
  const first = stdout.split('\n')[0] ?? ''
  const m = /^IN (\d+) (\d+)$/.exec(first)
  return m ? { kind: 'size', w: Number(m[1]), h: Number(m[2]) } : { kind: 'bad', why: `no IN line: ${JSON.stringify(first.slice(0, 80))}` }
}

export function parseThumb(stdout: string, exitCode: number): { w: number; h: number; png: string } | null {
  if (exitCode !== 0) return null
  const [first = '', second = ''] = stdout.split('\n')
  const m = /^THUMB (\d+) (\d+)$/.exec(first)
  return m && B64.test(second) ? { w: Number(m[1]), h: Number(m[2]), png: second } : null
}

/** About what a picture costs the model in input tokens: width times height over 750. */
export const imageTokens = (w: number, h: number) => Math.ceil((w * h) / 750)

/** The media type a shrunk picture comes out as: JPEG stays JPEG, the rest become PNG. */
export const outMime = (mime: string) => (/jpe?g/i.test(mime) ? 'image/jpeg' : 'image/png')
