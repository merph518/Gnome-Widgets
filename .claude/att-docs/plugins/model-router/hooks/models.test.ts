import { expect, test } from 'claude-code/testing'

import { family } from './pane'
import { requestModelId } from './models'
import type { Tiers } from './models'
import { rankOf, readJudgement, route } from './policy'
import type { PolicyConfig } from './policy'

const TIERS: Tiers = { fast: 'claude-haiku-5-5', balanced: 'claude-sonnet-5-5', deep: 'claude-opus-5-5' }

// The family each id belongs to, the name the pane shows for it, and where it
// sits on the tier ladder. Fable sits with the deep tier: there is no tier above it.
const CASES = [
  { id: 'claude-haiku-5-5', name: 'Haiku', rank: 0 },
  { id: 'claude-sonnet-5-5', name: 'Sonnet', rank: 1 },
  { id: 'claude-opus-5-5[1m]', name: 'Opus', rank: 2 },
  { id: 'claude-fable-5-2', name: 'Fable', rank: 2 },
]

test('rankOf and family() read the same family from a Haiku, Sonnet, Opus and Fable id', () => {
  for (const { id, name, rank } of CASES) {
    expect(family(id)).toBe(name)
    expect(rankOf(id, TIERS)).toBe(rank)
    // With no configured tier to match, the rank comes from the family alone.
    expect(rankOf(id, { fast: '', balanced: '', deep: '' })).toBe(rank)
  }
})

test('an id of no known family keeps its own name and has no rank', () => {
  expect(family('gpt-5')).toBe('gpt-5')
  expect(family(undefined)).toBe('unknown')
  expect(rankOf('gpt-5', TIERS)).toBe(null)
  expect(rankOf('', TIERS)).toBe(null)
})

test('a family alias resolves to its id, and Fable, with no id here, is left as written', () => {
  expect(requestModelId('Sonnet')).toBe('claude-sonnet-5-5')
  expect(requestModelId('fable')).toBe('fable')
  expect(requestModelId('claude-opus-5-5')).toBe('claude-opus-5-5')
})

const POLICY: PolicyConfig = { tiers: TIERS, minUpgradeConfidence: 0.3, minDowngradeConfidence: 0.6 }
const answer = (tier: string, confidence: number, risky = 0.01) =>
  readJudgement(JSON.stringify({ tier, confidence, risky }))

test('a move off Fable is a move down, and needs the 0.6 bar', () => {
  expect(route(answer('fast', 0.59), { model: 'claude-fable-5-2' }, POLICY).model).toBe(null)
  expect(route(answer('fast', 0.6), { model: 'claude-fable-5-2' }, POLICY).model).toBe('claude-haiku-5-5')
})

test('a deep or risky answer keeps a task on Fable', () => {
  expect(route(answer('deep', 0.95), { model: 'claude-fable-5-2' }, POLICY).model).toBe(null)
  expect(route(answer('fast', 0.9, 0.9), { model: 'claude-fable-5-2' }, POLICY).model).toBe(null)
})
