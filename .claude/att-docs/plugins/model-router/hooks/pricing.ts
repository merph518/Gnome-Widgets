/**
 * model-router: list prices, and what a run cost at them.
 *
 * Pure: no `$` and no I/O. The hooks module reads the counts and writes the
 * ledger; this module only does the arithmetic.
 */
import { canonicalModel, MODELS } from './models'

/** USD per million tokens. Cache writes are the 5-minute rate (1.25x input). */
export interface Price {
  input: number
  output: number
  cacheRead: number
  cacheWrite: number
}

/**
 * List prices as of 2026-10-06. Haiku 5.5
 * has a second card for a prompt over 100K tokens.
 */
export const PRICE_DATE = '2026-10-06'
const PRICES: Record<string, { small: Price; large?: Price }> = {
  [MODELS.opus.id]: { small: { input: 4, output: 20, cacheRead: 0.2, cacheWrite: 5 } },
  [MODELS.sonnet.id]: { small: { input: 2, output: 10, cacheRead: 0.2, cacheWrite: 2.5 } },
  [MODELS.haiku.id]: {
    small: { input: 0.1, output: 0.5, cacheRead: 0.01, cacheWrite: 0.125 },
    large: { input: 0.5, output: 2.5, cacheRead: 0.05, cacheWrite: 0.625 },
  },
}

/** One request's token counts, as the API reports them. */
export interface StepUsage {
  input_tokens: number
  output_tokens: number
  cache_read_input_tokens: number
  cache_creation_input_tokens: number
}

/** All four counts added up. */
export function totalTokens(usage: StepUsage): number {
  return (
    usage.input_tokens + usage.output_tokens + usage.cache_read_input_tokens + usage.cache_creation_input_tokens
  )
}

/**
 * What one request would cost on a model at list price, or null for a model
 * with no price here. The prompt size picks Haiku's rate card.
 */
export function requestCost(model: string, usage: StepUsage, oneRequest = true): number | null {
  const card = PRICES[canonicalModel(model)]
  if (!card) return null
  // A turn's summed counts are not one prompt: only a single request's size
  // can pick the long-prompt card.
  const prompt = usage.input_tokens + usage.cache_read_input_tokens + usage.cache_creation_input_tokens
  const price = oneRequest && prompt > 100_000 && card.large ? card.large : card.small
  return (
    (usage.input_tokens * price.input +
      usage.output_tokens * price.output +
      usage.cache_read_input_tokens * price.cacheRead +
      usage.cache_creation_input_tokens * price.cacheWrite) /
    1_000_000
  )
}

/** Dollars rounded for a ledger line. */
export function usd(value: number): number {
  return Math.round(value * 1_000_000) / 1_000_000
}

/**
 * What a run cost on a model: request by request when the steps were seen,
 * else from the turn's summed counts at the short-prompt rate. Null for a
 * model with no price here, or when there are no counts at all.
 */
export function runCost(model: string, steps: readonly StepUsage[], summed: StepUsage | null): number | null {
  if (steps.length > 0) {
    let total = 0
    for (const step of steps) {
      const cost = requestCost(model, step)
      if (cost === null) return null
      total += cost
    }
    return total
  }
  return summed ? requestCost(model, summed, false) : null
}

/** The four counts of many requests, added up. */
export function sumUsage(steps: readonly StepUsage[]): StepUsage {
  const sum: StepUsage = { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }
  for (const step of steps) {
    sum.input_tokens += step.input_tokens
    sum.output_tokens += step.output_tokens
    sum.cache_read_input_tokens += step.cache_read_input_tokens
    sum.cache_creation_input_tokens += step.cache_creation_input_tokens
  }
  return sum
}
