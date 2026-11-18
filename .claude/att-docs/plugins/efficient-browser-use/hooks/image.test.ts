import { expect, test } from 'claude-code/testing'
import { findImages, frameLine, imageTokens, leaveAlone, parseShrink, parseSize, parseThumb, replaceImages, rewriteFrames } from './image'

test('an unscaled screenshot line is rewritten to the shrunk size and the old frame', () => {
  expect(rewriteFrames('Screenshot size: 800x600', [{ w: 400, h: 300 }])).toBe(
    'Screenshot size: 400x300 0.5-scale view; coordinate frame: 800x600.',
  )
})

test('a line that already names a frame keeps that frame', () => {
  expect(rewriteFrames('[computer:screenshot] Screenshot size: 1000x800 0.8-scale view; coordinate frame: 1250x1000.', [{ w: 512, h: 410 }])).toBe(
    '[computer:screenshot] Screenshot size: 512x410 0.41-scale view; coordinate frame: 1250x1000.',
  )
})

test('several screenshot lines pair with the shrunk pictures in order; a null leaves its line', () => {
  const text = 'a Screenshot size: 1600x900\nb Screenshot size: 300x200\nc Screenshot size: 1200x1200'
  expect(rewriteFrames(text, [{ w: 800, h: 450 }, null, { w: 600, h: 600 }])).toBe(
    'a Screenshot size: 800x450 0.5-scale view; coordinate frame: 1600x900.\nb Screenshot size: 300x200\nc Screenshot size: 600x600 0.5-scale view; coordinate frame: 1200x1200.',
  )
})

test('frameLine words a line for a screenshot that had none', () => {
  expect(frameLine({ w: 1280, h: 800 }, { w: 640, h: 400 })).toBe('Screenshot size: 640x400 0.5-scale view; coordinate frame: 1280x800.')
})

test('images are found in the MCP SDK form, the API form and a Read result', () => {
  const mcp = { content: [{ type: 'text', text: 'hi' }, { type: 'image', data: 'AAA', mimeType: 'image/png' }] }
  const api = [{ type: 'image', source: { type: 'base64', media_type: 'image/jpeg', data: 'BBB' } }]
  const read = { type: 'image', file: { base64: 'CCC', type: 'image/webp', originalSize: 3 } }
  expect(findImages(mcp).map(i => [i.base64, i.mime])).toEqual([['AAA', 'image/png']])
  expect(findImages(api).map(i => [i.base64, i.mime])).toEqual([['BBB', 'image/jpeg']])
  expect(findImages(read).map(i => [i.base64, i.mime])).toEqual([['CCC', 'image/webp']])
  expect(findImages({ stdout: 'x' })).toEqual([])
  expect(findImages('text')).toEqual([])
})

test('replaceImages swaps each picture in its own form and leaves the input alone', () => {
  const mcp = { content: [{ type: 'image', data: 'AAA', mimeType: 'image/png' }, { type: 'text', text: 'Screenshot size: 1600x900' }] }
  const out = replaceImages(mcp, [{ base64: 'small', mime: 'image/png', w: 800, h: 450, inW: 1600, inH: 900 }]) as typeof mcp
  expect(out.content[0]).toEqual({ type: 'image', data: 'small', mimeType: 'image/png' })
  expect(out.content[1]).toEqual({ type: 'text', text: 'Screenshot size: 800x450 0.5-scale view; coordinate frame: 1600x900.' })
  expect(mcp.content[0]?.data).toBe('AAA')

  const read = { type: 'image', file: { base64: 'CCC', type: 'image/gif', originalSize: 3, dimensions: { originalWidth: 1200, originalHeight: 800 } } }
  const r = replaceImages(read, [{ base64: 'png', mime: 'image/png', w: 600, h: 400, inW: 1200, inH: 800 }]) as typeof read
  expect(r.file).toEqual({
    base64: 'png',
    type: 'image/png',
    originalSize: 3,
    dimensions: { originalWidth: 1200, originalHeight: 800, displayWidth: 600, displayHeight: 400 },
  })
})

test('a browser screenshot with no size line gets one appended', () => {
  const mcp = { content: [{ type: 'image', data: 'AAA', mimeType: 'image/jpeg' }] }
  const out = replaceImages(mcp, [{ base64: 'b', mime: 'image/jpeg', w: 640, h: 400, inW: 1280, inH: 800 }], { addFrame: true }) as { content: unknown[] }
  expect(out.content[1]).toEqual({ type: 'text', text: 'Screenshot size: 640x400 0.5-scale view; coordinate frame: 1280x800.' })
})

test('a picture can become words', () => {
  const api = { content: [{ type: 'image', source: { type: 'base64', media_type: 'image/png', data: 'B' } }] }
  const out = replaceImages(api, [{ text: 'A login form.' }]) as { content: unknown[] }
  expect(out.content[0]).toEqual({ type: 'text', text: 'A login form.' })
})

test('zoom, Claude’s own scale and a batch holding either are left alone', () => {
  expect(leaveAlone({ action: 'zoom' })).toBe(true)
  expect(leaveAlone({ action: 'screenshot', scale: 0.4 })).toBe(true)
  expect(leaveAlone({ action: 'screenshot' })).toBe(false)
  expect(leaveAlone({ actions: [{ name: 'computer', input: { action: 'screenshot' } }, { name: 'computer', input: { action: 'zoom' } }] })).toBe(true)
  expect(leaveAlone({ actions: [{ name: 'computer', input: { action: 'screenshot' } }] })).toBe(false)
  expect(leaveAlone({ file_path: '/a.png' })).toBe(false)
})

test('the script output is read line by line', () => {
  expect(parseShrink('NOIM\n', 3)).toEqual({ kind: 'noim' })
  expect(parseShrink('IN 400 300\nSKIP\n', 0)).toEqual({ kind: 'skip', inW: 400, inH: 300 })
  expect(parseShrink('IN 1600 900\nOUT 800 450\nQUJD\n', 0)).toEqual({ kind: 'out', inW: 1600, inH: 900, w: 800, h: 450, base64: 'QUJD' })
  expect(parseShrink('IN 1600 900\nOUT 800 450\n\n', 0).kind).toBe('bad')
  expect(parseShrink('', 4).kind).toBe('bad')
  expect(parseThumb('THUMB 160 90\nUE5H\n', 0)).toEqual({ w: 160, h: 90, png: 'UE5H' })
  expect(parseThumb('nope', 1)).toBe(null)
})

test('a picture costs about w*h/750 tokens', () => {
  expect(imageTokens(1600, 900)).toBe(1920)
  expect(imageTokens(800, 450)).toBe(480)
})

test('the size mode\'s output is read', () => {
  expect(parseSize('IN 1600 900\n', 0)).toEqual({ kind: 'size', w: 1600, h: 900 })
  expect(parseSize('NOIM\n', 3)).toEqual({ kind: 'noim' })
  expect(parseSize('', 4).kind).toBe('bad')
  expect(parseSize('OUT 1 1\n', 0).kind).toBe('bad')
})
