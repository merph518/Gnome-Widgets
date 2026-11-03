import test from 'node:test';
import assert from 'node:assert/strict';
import { controlsIn, docControls, dropRepeats, foldFollowUps, mergeRemovedScenarios, repeatsLeft } from './design-tidy.mjs';
import { impossibleSteps, stepRules, stepSchema } from './steps.mjs';

const DOC = { text: 'Selecting Save or Save & Close, the role is stored. Select Ok, the message closes. Select Reset, the saved value returns. '
  + 'Save is enabled only after the dropdown value changes. The sex abuse allegation blocks the role.' };
const RULES = [
  { id: 'R-30', summary: 'Selecting Save stores the role.' },
  { id: 'R-32', summary: 'The Save button is enabled only after the dropdown changes.' },
  { id: 'R-34', summary: 'Retired: selecting Save with a sex abuse allegation shows a warning.' },
  { id: 'R-35', summary: 'Retired: selecting Save & Close with a neglect allegation shows a warning.' },
  { id: 'R-36', summary: 'Retired: selecting Save with a fatality shows a warning.' },
];
const controls = docControls(DOC, RULES);

test('controlsIn finds the longest control first and counts it once', () => {
  assert.deepEqual(controlsIn('Select Save & Close, then Save', controls).sort(), ['Save', 'Save & Close']);
  assert.deepEqual(controlsIn('Select Save & Close', controls), ['Save & Close']);
});

test('absence checks of retired rules merge into one scenario per control', () => {
  const retired = new Set(['R-34', 'R-35', 'R-36']);
  const scenarios = [
    { id: 'S1', rules: ['R-34'], action: 'select Save', population: 'a role with a sex abuse allegation' },
    { id: 'S2', rules: ['R-36'], action: 'select Save', population: 'a role with a fatality' },
    { id: 'S3', rules: ['R-35'], action: 'select Save & Close', population: 'a role with a neglect allegation' },
    { id: 'S4', rules: ['R-30'], action: 'select Save', population: 'a role' },
    { id: 'S5', rules: ['R-34'], action: 'look at the screen', population: 'any role' },
  ];
  const { scenarios: out, merged } = mergeRemovedScenarios(scenarios, retired, controls);
  assert.deepEqual(out.map((s) => s.id), ['S1', 'S3', 'S4', 'S5']);
  assert.deepEqual(out[0].rules, ['R-34', 'R-36']);
  assert.deepEqual(merged, [{ into: 'S1', from: 'S2' }]);
  assert.match(out[0].action, /Save/);
});

const card = (title, first, expected, rules) => ({ title, rules, expected,
  steps: [{ description: first, expected: 'ok', rules }, { description: 'Check the result', expected, rules }] });

test('a card that only answers a message joins the card that raises it', () => {
  const error = card('Role blocked', 'Select the role', 'The error message Role blocked shows', ['R-34']);
  const ok = card('Ok closes it', 'Select Ok', 'The message closes', ['R-34']);
  const other = card('Other', 'Select Save', 'The role saves', ['R-30']);
  const { cards, folded } = foldFollowUps([error, ok, other]);
  assert.deepEqual(cards.map((c) => c.title), ['Role blocked', 'Other']);
  assert.equal(folded.length, 1);
  assert.equal(cards[0].steps.length, 4);
  assert.equal(cards[0].expected, 'The message closes');
});

test('a setup step that merely starts with Yes, No or Reset is not an answer to a message', () => {
  const error = card('Role blocked', 'Select the role', 'The error message Role blocked shows', ['R-34']);
  for (const first of ['Select Yes in the Active dropdown', 'Click the Reset Date field', 'Select No for the flag']) {
    const other = card('Dropdown', first, 'The value shows', ['R-34']);
    assert.equal(foldFollowUps([error, other]).cards.length, 2, first);
  }
  for (const first of ['Select Ok', 'Click the "Ok" button', 'Press Reset.', 'Select Yes on the message']) {
    const other = card('Answer', first, 'The message closes', ['R-34']);
    assert.equal(foldFollowUps([{ ...error }, other]).cards.length, 1, first);
  }
});

test('a card that answers a message with no card raising it shared by rule stays', () => {
  const ok = card('Ok closes it', 'Select Ok', 'The message closes', ['R-99']);
  const error = card('Role blocked', 'Select the role', 'The error message shows', ['R-34']);
  assert.equal(foldFollowUps([error, ok]).cards.length, 2);
});

const view = (title, focus, rules, mission = 'Check the sex abuse allegation blocks the role') => ({ title, mission, focus: [focus], rules,
  steps: [{ description: 'Select the role', expected: 'ok', rules }, { description: 'Select Save', expected: 'no save', rules }] });

test('a card that repeats another is dropped and its rules join the card that stays', () => {
  const cards = [
    view('Sex abuse allegation blocks the role', 'Select Save with a sex abuse allegation', ['R-34']),
    view('Sex abuse allegation blocks the role', 'Select Save with a sex abuse allegation', ['R-34', 'R-30']),
    view('Fatality warning', 'Select Save & Close with a fatality', ['R-36'], 'Check the fatality warning is gone'),
  ];
  const { cards: kept, dropped } = dropRepeats(cards, DOC, RULES);
  assert.equal(dropped.length, 1);
  assert.equal(kept.length, 2);
  assert.deepEqual(kept[0].rules, ['R-34', 'R-30']);
  assert.equal(repeatsLeft(kept, DOC, RULES), 0);
});

test('repeatsLeft counts a repeat that stands', () => {
  const cards = [view('Sex abuse allegation blocks the role', 'Select Save with a sex abuse allegation', ['R-34']),
    view('Sex abuse allegation blocks the role', 'Select Save with a sex abuse allegation', ['R-34'])];
  assert.equal(repeatsLeft(cards, DOC, RULES), 1);
});

test('stepRules adds a rule that governs a control the steps press, even when the card does not cite it', () => {
  const tc10 = { rules: ['R-30'], steps: [{ description: 'Leave the dropdown unchanged' }, { description: 'Select Save' }] };
  const shown = stepRules(tc10, RULES, controls).map((r) => r.id);
  assert.ok(shown.includes('R-30') && shown.includes('R-32'), shown.join());
});

test('stepSchema asks for one row per card with its steps, and impossibleSteps reads the no answers', () => {
  const schema = stepSchema(['C1', 'C2']);
  assert.deepEqual(schema.properties.cards.items.properties.card.enum, ['C1', 'C2']);
  assert.equal(schema.properties.cards.minItems, 2);
  const row = { card: 'C1', steps: [{ step: 1, possible: true, why: 'fine' }, { step: 2, possible: false, why: 'R-32 disables Save' }] };
  assert.deepEqual(impossibleSteps(row), [{ step: 2, why: 'R-32 disables Save' }]);
  assert.deepEqual(impossibleSteps(undefined), []);
});
