import { expect, test } from 'claude-code/testing'

import { requestCost, runCost, sumUsage, totalTokens, usd } from './pricing'

const usage = (input: number, output = 0, cacheRead = 0, cacheWrite = 0) => ({
  input_tokens: input,
  output_tokens: output,
  cache_read_input_tokens: cacheRead,
  cache_creation_input_tokens: cacheWrite,
})

// Compared at the ledger's rounding, since float sums are not exact.
const rounded = (value: number | null) => (value === null ? null : usd(value))

test('one request costs its tokens at the model’s list price', () => {
  // Opus: $4 in, $20 out, $0.20 cache read, $5 cache write, per million.
  expect(rounded(requestCost('claude-opus-5-5', usage(1_000_000, 100_000, 500_000, 200_000)))).toBe(7.1)
  // A context suffix or an alias prices as the plain id.
  expect(rounded(requestCost('claude-opus-5-5[1m]', usage(1_000_000)))).toBe(4)
  expect(rounded(requestCost('sonnet', usage(1_000_000)))).toBe(2)
})

test('a Haiku prompt over 100K tokens takes the long-prompt card, but summed counts never do', () => {
  expect(rounded(requestCost('claude-haiku-5-5', usage(200_000)))).toBe(0.1)
  expect(rounded(requestCost('claude-haiku-5-5', usage(200_000), false))).toBe(0.02)
  expect(rounded(requestCost('claude-haiku-5-5', usage(100_000)))).toBe(0.01)
})

test('a model with no price costs nothing known', () => {
  expect(requestCost('claude-fable-5-2', usage(1000))).toBe(null)
  expect(runCost('claude-fable-5-2', [usage(1000)], null)).toBe(null)
})

test('a run costs each request it made, or its summed counts when none were seen', () => {
  const steps = [usage(200_000), usage(50_000)]
  // 200K at the long card ($0.10) plus 50K at the short one ($0.005).
  expect(rounded(runCost('claude-haiku-5-5', steps, null))).toBe(0.105)
  expect(rounded(runCost('claude-haiku-5-5', [], usage(250_000)))).toBe(0.025)
  expect(runCost('claude-haiku-5-5', [], null)).toBe(null)
  expect(sumUsage(steps)).toEqual(usage(250_000))
  expect(totalTokens(usage(1, 2, 3, 4))).toBe(10)
  expect(usd(0.12345678)).toBe(0.123457)
})
