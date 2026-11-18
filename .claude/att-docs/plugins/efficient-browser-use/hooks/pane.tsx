// The "Screenshot Shrinker" pane: one card per picture the mod looked at, with the size the
// tool returned, the size Claude read, the tokens that saved, and a 160 px thumbnail.
import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'
import type { PictureCard } from '../types'
import { shrinkerSvg } from './mascot'

type On = Parameters<Register>[0]

export const PANE = 'efficient-browser-use'
export const PANE_TITLE = 'Screenshot Shrinker'
const MAX_CARDS = 30

const ACCENT = '#d97757'
const GOOD = '#16a34a'
const BAD = '#dc2626'

export const cardsAtom = atom({ plugin: 'efficient-browser-use', key: 'cards' } as const, [] as PictureCard[], { shape: 'cards-1' })
// How many pictures are being worked on now: a result can carry several.
export const busyAtom = atom({ plugin: 'efficient-browser-use', key: 'busy' } as const, 0)
export const offAtom = atom({ plugin: 'efficient-browser-use', key: 'off' } as const, false)

// Module variables start over on a reload; the cards live in $.state.
let seq = 0
// The person closed the pane: the mod stops opening it until /efficient-browser asks.
let closed = false
// switches.json says "efficient-browser-use:hidden": the mod never opens the pane by itself.
let switchHidden = false

export function resetPane() {
  seq = 0
  closed = false
  switchHidden = false
}

export function setSwitchHidden(hidden: boolean) {
  switchHidden = hidden
}

/** asked: the person asked for the pane (a command, or Open in /mods). That always opens it. */
export async function openPane($: EngineInterface, asked = false) {
  if (asked) closed = false
  else if (closed || switchHidden) return
  try {
    await $.ui.open({ id: PANE, title: PANE_TITLE })
  } catch {
    // The pane is a nicety: no picture waits on it.
  }
}

export async function closePane($: EngineInterface) {
  try {
    await $.ui.close({ id: PANE })
  } catch {
    // Not open.
  }
}

export async function addCard($: EngineInterface, card: Omit<PictureCard, 'id' | 'at'>): Promise<string> {
  const at = await $.clock.now()
  const list = (await read($, cardsAtom)) ?? []
  seq = Math.max(seq, ...list.map(c => Number(c.id) || 0)) + 1
  const id = String(seq)
  await update($, cardsAtom, l => [{ ...card, id, at }, ...(l ?? [])].slice(0, MAX_CARDS))
  return id
}

/** true when work on a picture starts, false when it ends. */
export async function setBusy($: EngineInterface, busy: boolean) {
  await update($, busyAtom, n => Math.max(0, (typeof n === 'number' ? n : 0) + (busy ? 1 : -1)))
}

export async function setOff($: EngineInterface, off: boolean) {
  await update($, offAtom, () => off)
}

const count = (n: number) => n.toLocaleString('en-US')

export function registerPane(on: On) {
  on('ui.close', async ($, e, next) => {
    if (e.id === PANE && e.origin.kind === 'person') closed = true
    return next(e)
  }).catch(($, e, next) => next(e))

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const els = $.ui.resolve(e)
    const { Box, Text } = els
    if (await read($, offAtom)) return <Text dimColor>Turned off. Open /mods to turn it on.</Text>
    const Svg = e.surface !== 'terminal' && 'Svg' in els ? els.Svg : null
    const Image = 'Image' in els ? els.Image : null
    const width = Math.max(32, e.props.bodyColumns)
    const cards = (await read($, cardsAtom)) ?? []
    const busy = ((await read($, busyAtom)) ?? 0) > 0
    const cw = width - 4

    const changed = cards.filter(c => c.outcome === 'shrunk' || c.outcome === 'described')
    const saved = changed.reduce((n, c) => n + (c.before - c.after), 0)
    const tiles = [
      { label: 'Pictures', value: count(cards.length) },
      { label: 'Made smaller', value: count(changed.length) },
      { label: 'Tokens saved', value: count(saved) },
    ]
    const tileW = Math.floor((width - (tiles.length - 1)) / tiles.length)

    const mascot = Svg ? (
      <Box key="mascot" width={12} flexShrink={0}>
        <Svg source={shrinkerSvg(busy)} alt="Claude holding a picture frame that shrinks" width={72} height={48} />
      </Box>
    ) : (
      <Box key="mascot" width={6} flexShrink={0}>
        <Text color={ACCENT}>{busy ? '▟█▙▣' : '▟█▙▫'}</Text>
      </Box>
    )

    const card = (c: PictureCard) => {
      const size =
        c.outW !== undefined && c.outH !== undefined ? `${c.inW}×${c.inH} → ${c.outW}×${c.outH}` : c.inW && c.inH ? `${c.inW}×${c.inH}` : 'size unknown'
      const end =
        c.outcome === 'shrunk' || c.outcome === 'described'
          ? { text: `${count(c.before)} → ${count(c.after)} tokens`, color: GOOD }
          : c.outcome === 'failed'
            ? { text: 'Sent at full size', color: BAD }
            : { text: `${count(c.before)} tokens, unchanged`, color: undefined }
      // A terminal cell is about 8 px wide and 16 px tall.
      const thumb =
        Image && c.thumb && c.thumbW && c.thumbH ? (
          <Box key={`th-${c.id}`} flexShrink={0} marginRight={1}>
            <Image
              key={`img-${c.id}`}
              source={{ png: c.thumb }}
              columns={Math.max(1, Math.min(20, Math.round(c.thumbW / 8)))}
              rows={Math.max(1, Math.min(10, Math.round(c.thumbH / 16)))}
              alt={`thumbnail, ${size}`}
            />
          </Box>
        ) : null
      return (
        <Box key={`c-${c.id}`} flexDirection="column" width={width} marginBottom={1} borderStyle="round" borderDimColor paddingX={1}>
          <Box flexDirection="row" justifyContent="space-between" width={cw}>
            <Text bold wrap="truncate-end">
              {c.tool}
            </Text>
            <Text dimColor>{size}</Text>
          </Box>
          <Box flexDirection="row" width={cw}>
            {thumb}
            <Box flexDirection="column" flexGrow={1}>
              <Text bold color={end.color}>
                {end.text}
              </Text>
              <Text dimColor wrap="wrap">
                {c.why}
              </Text>
            </Box>
          </Box>
        </Box>
      )
    }

    return (
      <Box flexDirection="column" width={width}>
        <Box key="header" flexDirection="row" gap={1} width={width} marginBottom={1}>
          {mascot}
          <Box flexDirection="column" width={width - 13}>
            <Text bold color={busy ? ACCENT : undefined}>
              {busy ? 'Shrinking a picture…' : PANE_TITLE}
            </Text>
            <Text dimColor wrap="wrap">
              Screenshots and other pictures reach Claude smaller.
            </Text>
          </Box>
        </Box>
        <Box key="tiles" flexDirection="row" gap={1} width={width} marginBottom={1}>
          {tiles.map(t => (
            <Box key={`t-${t.label}`} flexDirection="column" borderStyle="round" paddingX={1} width={tileW}>
              <Text dimColor wrap="truncate-end">
                {t.label}
              </Text>
              <Text bold color={ACCENT} wrap="truncate-end">
                {t.value}
              </Text>
            </Box>
          ))}
        </Box>
        {cards.length === 0 ? (
          <Text key="empty" dimColor wrap="wrap">
            Cards show up here when a tool returns a picture.
          </Text>
        ) : (
          cards.map(card)
        )}
      </Box>
    )
  })
}
