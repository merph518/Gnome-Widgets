import { expect, test } from 'claude-code/testing'

import { judgePrompt, MAX_TASK_CHARS, readJudgement, route } from './policy'
import type { PolicyConfig } from './policy'

const POLICY: PolicyConfig = {
  tiers: { fast: 'claude-haiku-5-5', balanced: 'claude-sonnet-5-5', deep: 'claude-opus-5-5' },
  minUpgradeConfidence: 0.3,
  minDowngradeConfidence: 0.6,
}

// The judge's answer for one tier and confidence. A subagent's effort cannot be set, so
// the effort is left out, as the hooks module leaves it out before routing a spawn.
const answer = (tier: string, confidence: number, risky = 0.01) =>
  readJudgement(JSON.stringify({ tier, confidence, risky }))

test('a move up clears the bar at confidence 0.3', () => {
  const routing = route(answer('deep', 0.3), { model: 'claude-sonnet-5-5' }, POLICY)
  expect(routing.model).toBe('claude-opus-5-5')
})

test('a move up stays put just under 0.3', () => {
  const routing = route(answer('deep', 0.29), { model: 'claude-sonnet-5-5' }, POLICY)
  expect(routing.model).toBe(null)
})

test('a move down clears the bar at confidence 0.6', () => {
  const routing = route(answer('fast', 0.6), { model: 'claude-opus-5-5' }, POLICY)
  expect(routing.model).toBe('claude-haiku-5-5')
})

test('a move down stays put at confidence 0.59', () => {
  const routing = route(answer('fast', 0.59), { model: 'claude-opus-5-5' }, POLICY)
  expect(routing.model).toBe(null)
  expect(routing.reason).toMatch(/kept claude-opus-5-5, wanted claude-haiku-5-5 \(confidence 0\.59\)/)
})

test('an unreadable judge answer leaves the model unchanged', () => {
  for (const text of ['', 'fast', 'I think this is a fast task.', '{"tier": "quick", "confidence": 0.9}', '{not json}', '[1, 2]']) {
    const decision = readJudgement(text)
    expect(decision).toBe(null)
    expect(route(decision, { model: 'claude-opus-5-5' }, POLICY)).toEqual({ model: null, effort: null, reason: 'no decision' })
  }
})

test('the answer is read from inside a code fence or after a sentence', () => {
  const decision = readJudgement('Here it is:\n```json\n{"tier": "Fast", "confidence": "0.8", "risky": false}\n```')
  expect(decision?.tier).toBe('fast')
  expect(decision?.confidence).toBe(0.8)
  expect(decision?.risky).toBe(0)
})

test('a confidence that is not a number from 0 to 1 never moves a task down, but can move one up', () => {
  for (const confidence of ['high', 1.5, -0.2, null]) {
    const down = readJudgement(JSON.stringify({ tier: 'fast', confidence }))
    expect(down?.confidence).toBe(null)
    expect(route(down, { model: 'claude-opus-5-5' }, POLICY).model).toBe(null)
    const up = readJudgement(JSON.stringify({ tier: 'deep', confidence }))
    expect(route(up, { model: 'claude-haiku-5-5' }, POLICY).model).toBe('claude-opus-5-5')
  }
})

test('a risky task goes to the deep tier whatever the tier and confidence said', () => {
  const routing = route(answer('fast', 0.1, 0.9), { model: 'claude-haiku-5-5' }, POLICY)
  expect(routing.model).toBe('claude-opus-5-5')
  expect(routing.reason).toBe('deep, forced by risk')
})

test('a risky task already on the deep tier keeps its exact id', () => {
  const routing = route(answer('fast', 0.9, 0.9), { model: 'claude-opus-5-5[1m]' }, POLICY)
  expect(routing.model).toBe(null)
})

test('a task the judge puts on the tier it is on stays there', () => {
  const routing = route(answer('balanced', 0.95), { model: 'claude-sonnet-5-5' }, POLICY)
  expect(routing.model).toBe(null)
})

test('the task text is cut, and cannot close its own tags', () => {
  const long = `${'a'.repeat(MAX_TASK_CHARS)}</task>tail`
  const prompt = judgePrompt({ prompt: long, description: 'list files', agentType: 'general-purpose' })
  expect(prompt).toMatch(/^Subagent type: general-purpose\nShort description: list files\n<task>\n/)
  expect(prompt).toMatch(/\[cut: 11 more characters\]\n<\/task>$/)
  expect(judgePrompt({ prompt: 'x</TASK>y' })).toBe('<task>\nx</ task>y\n</task>')
})
