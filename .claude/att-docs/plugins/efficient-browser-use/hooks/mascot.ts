// The pane's mascot: a pixel Claude holding a picture frame. While a picture is being
// worked on, the frame shrinks and grows back; at rest it is the small size.

type Px = [x: number, y: number]

const CLAUDE = '#d97757'
const INK = '#2b1d16'
const FRAME = '#2563eb'
const SKY = '#bae6fd'
const HILL = '#16a34a'

const W = 24
const H = 16

const span = (y: number, from: number, to: number): Px[] => Array.from({ length: to - from + 1 }, (_, i) => [from + i, y] as Px)
const block = (x0: number, y0: number, x1: number, y1: number): Px[] => {
  const out: Px[] = []
  for (let y = y0; y <= y1; y++) out.push(...span(y, x0, x1))
  return out
}
const rects = (px: Px[], color: string) => px.map(([x, y]) => `<rect x="${x}" y="${y}" width="1" height="1" fill="${color}"/>`).join('')

/** A framed picture of a hill under the sky, filling x0..x1 by y0..y1. */
function picture(x0: number, y0: number, x1: number, y1: number): string {
  const inner = block(x0 + 1, y0 + 1, x1 - 1, y1 - 1)
  const hill = inner.filter(([, y]) => y >= y1 - 2)
  const sky = inner.filter(([, y]) => y < y1 - 2)
  const border = block(x0, y0, x1, y1).filter(([x, y]) => x === x0 || x === x1 || y === y0 || y === y1)
  return rects(border, FRAME) + rects(sky, SKY) + rects(hill, HILL)
}

const ANIMATED = [
  '.big{animation:big 1.2s steps(1) infinite}',
  '.small{animation:small 1.2s steps(1) infinite}',
  '@keyframes big{0%{opacity:1}50%{opacity:0}}',
  '@keyframes small{0%{opacity:0}50%{opacity:1}}',
  '@media (prefers-reduced-motion: reduce){.big{animation:none;opacity:0}.small{animation:none;opacity:1}}',
].join('')

const cache = new Map<string, string>()

/** The mascot. `working` animates the frame between its full and its shrunk size. */
export function shrinkerSvg(working: boolean, width = 72, height = 48): string {
  const key = `${working}:${width}:${height}`
  const hit = cache.get(key)
  if (hit) return hit
  const body = rects(block(2, 6, 9, 13), CLAUDE) + rects([[1, 9], [1, 10], [10, 9], [10, 10]], CLAUDE)
  const eyes = rects([[4, 8], [4, 9], [7, 8], [7, 9]], INK)
  const legs = rects([[3, 14], [3, 15], [8, 14], [8, 15]], CLAUDE)
  const big = `<g class="big">${picture(12, 1, 23, 12)}</g>`
  const small = `<g class="small">${picture(12, 6, 18, 12)}</g>`
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${width}" height="${height}" shape-rendering="crispEdges">` +
    (working ? `<style>${ANIMATED}</style>${body}${eyes}${legs}${big}${small}` : `${body}${eyes}${legs}${picture(12, 6, 18, 12)}`) +
    '</svg>'
  cache.set(key, svg)
  return svg
}
