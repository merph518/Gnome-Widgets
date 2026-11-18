/**
 * model-router: the model families and ids the plugin knows.
 *
 * The one place a model id or family word is written. The judge, the tier
 * defaults and the price card all read this table. `plugin.json`'s
 * tier defaults cannot import it, so a test checks they match.
 */

export type Tier = 'fast' | 'balanced' | 'deep'

export interface Tiers {
  fast: string
  balanced: string
  deep: string
}

export const TIER_ORDER: readonly Tier[] = ['fast', 'balanced', 'deep']

export type Family = 'haiku' | 'sonnet' | 'opus' | 'fable'

interface FamilyRow {
  /** The name a person reads. */
  label: string
  /** Where the family sits on TIER_ORDER. */
  rank: number
  /** The full id its alias stands for, when the plugin uses one. */
  id?: string
}

/**
 * Every family, in the order an id is matched against them. Fable ranks with
 * the deep tier: the ladder has nothing above deep, so a move off Fable counts
 * as a move down and a risky task keeps it, the way a deep-tier id is kept.
 * Fable has no id here because no tier defaults to it and it has no price.
 */
export const MODELS = {
  haiku: { label: 'Haiku', rank: 0, id: 'claude-haiku-5-5' },
  sonnet: { label: 'Sonnet', rank: 1, id: 'claude-sonnet-5-5' },
  opus: { label: 'Opus', rank: 2, id: 'claude-opus-5-5' },
  fable: { label: 'Fable', rank: 2 },
} as const satisfies Record<Family, FamilyRow>

const FAMILIES = Object.keys(MODELS) as Family[]

/** The family a model id or alias belongs to, by its family word, or null. */
export function familyOf(model: string | undefined): Family | null {
  if (!model) return null
  const lowered = model.toLowerCase()
  return FAMILIES.find(f => lowered.includes(f)) ?? null
}

/** The family name of a model id (Haiku, Sonnet, Opus, Fable); any other id as it is. */
export function family(model: string | undefined): string {
  if (!model) return 'unknown'
  const f = familyOf(model)
  return f ? MODELS[f].label : model
}

/** Where a model id's family sits on TIER_ORDER, or null for no known family. */
export function familyRank(model: string | undefined): number | null {
  const f = familyOf(model)
  return f ? MODELS[f].rank : null
}

/** What each tier runs on when its setting is unset. plugin.json repeats these. */
export const DEFAULT_TIERS: Tiers = {
  fast: MODELS.haiku.id,
  balanced: MODELS.sonnet.id,
  deep: MODELS.opus.id,
}

/** The model that judges every task, as `$.model.complete` takes it. */
export const JUDGE_MODEL = 'haiku'

/** The judge's id for the ledger, which prices the judge call by it. */
export const JUDGE_MODEL_ID = MODELS[JUDGE_MODEL].id

/**
 * The full id a family alias names on the main loop.
 *
 * `agent.spawn` takes an alias (`haiku`) the way the Agent tool does, but
 * `turn.step`'s `model` is the id the engine already resolved for the request
 * and goes to the API as written: an alias there is refused ("There's an
 * issue with the selected model (haiku)"). So the tiers stay aliases in the
 * options, and only a main-loop rewrite resolves them, here.
 *
 * Returns a full id as given, or the id behind a family alias. Anything else
 * is returned unchanged for the engine to judge.
 */
export function requestModelId(model: string): string {
  const alias = model.trim().toLowerCase()
  const row: FamilyRow | undefined = FAMILIES.includes(alias as Family) ? MODELS[alias as Family] : undefined
  return row?.id ?? model
}

/** A model id without a context suffix (`[1m]`), an alias read as its id. */
export function canonicalModel(model: string): string {
  return requestModelId(model.replace(/\[[^\]]*\]$/, '').trim())
}
