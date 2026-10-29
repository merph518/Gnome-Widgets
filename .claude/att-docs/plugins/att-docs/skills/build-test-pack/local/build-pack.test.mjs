// Runs the local pipeline end to end against the synthetic fixtures, with a
// model that answers every call from its schema and a stub builder.
//
//   node --test plugins/att-docs/skills/build-test-pack/local/build-pack.test.mjs

import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { addJob, claimStale, cutoffAfter, drainQueue, fillQueue, jobFrom, jobFromLine, jobStatus, lockHeld,
  parseArgs, readQueue, removeJob,
  summaryLines }
  from './build-pack.mjs';
import { loadConfig, RULE_SHAPE } from './config.mjs';
import { rulesStale, shapeProblems } from './rules.mjs';
import { createPauser, pausedPath } from './pause.mjs';
import { ModelError, localEndpoint, modelClient } from './model.mjs';
import { batches, setsOf, splitText } from './phases.mjs';
import { runJob } from './run.mjs';
import { renderReport, reportData, seededRandom, spotChecks, writeReports } from './report.mjs';
import { statusFields } from './status.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FIXTURES = path.join(HERE, 'fixtures');

const fixtureInputs = () => JSON.parse(fs.readFileSync(path.join(FIXTURES, 'pipeline.json'), 'utf8')).inputs;

/** A config over the fixtures whose output and queue land in a fresh temp folder. */
function fixtureConfig(overrides = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'build-pack-'));
  const raw = JSON.parse(fs.readFileSync(path.join(FIXTURES, 'pipeline.json'), 'utf8'));
  Object.assign(raw, { repoRoot: FIXTURES, output: path.join(dir, 'out'),
    queue: { file: path.join(dir, 'queue.json') } }, overrides);
  const file = path.join(dir, 'pipeline.json');
  fs.writeFileSync(file, JSON.stringify(raw));
  return loadConfig(file);
}

/** A value of the schema's shape: every enum value once where a list's length is the enum's. */
function sample(schema, key = 'text') {
  if (schema.enum) return schema.enum[0];
  if (schema.type === 'boolean') return true;
  if (schema.type === 'integer') return 1;
  if (schema.type === 'string') return schema.pattern ? 'MOD' : `${key} value`;
  if (schema.type === 'array') {
    const item = schema.items;
    const keyed = item.type === 'object' && Object.entries(item.properties)
      .find(([, p]) => p.enum && p.enum.length === schema.minItems);
    if (keyed) {
      return keyed[1].enum.map((value) => ({ ...sample(item, key), [keyed[0]]: value }));
    }
    if (item.enum) return [...item.enum];
    return Array.from({ length: Math.max(1, schema.minItems ?? 1) }, () => sample(item, key));
  }
  return Object.fromEntries(Object.entries(schema.properties).map(([k, p]) => [k, sample(p, k)]));
}

/**
 * A model that answers from each call's schema. `answers` overrides a reply by
 * the schema name's prefix (the phase and step), as a value or a function of
 * the sampled reply. Every call is recorded.
 */
function fakeModel(answers = {}) {
  const calls = [];
  return {
    calls,
    countTokens: async (text) => Math.ceil(text.length / 3),
    async json(request) {
      calls.push(request);
      let value = sample(request.schema);
      // Two empty lists keep the gates quiet: no conflicts, nothing missing.
      if ('conflicts' in value) value.conflicts = [];
      if ('missing' in value) value.missing = [];
      if ('assumptionsToProceed' in value) value.assumptionsToProceed = [];
      if (Array.isArray(value.uncovered)) value.uncovered = [];
      if (Array.isArray(value.skipped)) value.skipped = [];
      // A card call gets one card for each scenario it is offered.
      const offered = value.cards?.[0]?.scenario !== undefined
        && request.schema.properties.cards.items.properties.scenario.enum;
      if (offered) value.cards = offered.map((id) => ({ ...value.cards[0], scenario: id }));
      const [, override] = Object.entries(answers)
        .find(([prefix]) => request.schemaName.startsWith(prefix)) ?? [];
      if (override) value = typeof override === 'function' ? override(value, calls) : override;
      return { value, usage: { promptTokens: 10, outputTokens: 5, ms: 1 } };
    },
  };
}

const read = (file) => fs.readFileSync(file, 'utf8');
const statusLines = (outDir) => read(path.join(outDir, 'status.log')).trim().split('\n')
  .map((line) => JSON.parse(line));

// Text from the fixtures that must never reach the status log or the console.
const CONTENT = ['Patron', 'renew', 'Renewal', 'BR-LIB', 'fines', 'Overdue', 'expiry', 'value'];

function assertContentFree(text) {
  for (const word of CONTENT) assert.ok(!text.includes(word), `status text carries "${word}"`);
}

test('an issue pack builds end to end on the local model alone', async () => {
  const config = fixtureConfig();
  const model = fakeModel({ intake: (value) => ({ ...value,
    documents: ['docs/LIB/UC01-Card-Renewal.md'] }) });
  const result = await runJob(config, { issue: '501', change: '7001' }, { model, echo: false });
  assert.equal(result.ok, true, JSON.stringify(result));
  assert.ok(fs.existsSync(result.workbook));
  const pack = JSON.parse(read(result.packPath));
  assert.equal(pack.issue, '501');
  assert.equal(pack.change, '7001');
  // Intake picked documents from the index; the export gave the master's IDs, the retired one kept.
  assert.deepEqual(pack.rules.map((rule) => rule.id).sort(), [
    'BR-LIB.UC01-001', 'BR-LIB.UC01-002', 'BR-LIB.UC01-003', 'BR-LIB.UC01-004', 'BR-LIB.UC01-005',
    'BR-LIB.UC01-006',
  ]);
  // The retired rule keeps its place, says it was removed, and goes to Phase 3 like any other.
  const retired = pack.rules.find((rule) => rule.id === 'BR-LIB.UC01-006');
  assert.match(retired.summary, /^Retired: this rule was removed/);
  const scoped = model.calls.filter((call) => call.schemaName.startsWith('phase3'))
    .flatMap((call) => Object.keys(call.schema.properties.rules.properties));
  assert.ok(scoped.includes('BR-LIB.UC01-006'));
  const phase1 = model.calls.find((call) => call.schemaName.startsWith('phase1'));
  assert.match(phase1.user, /\[retired\] BR-LIB\.UC01-006/);
  assert.ok(pack.testCards.every((card) => /^TC-MOD-501-\d{3}$/.test(card.id)));
  const phases = statusLines(result.outDir).filter((l) => l.event === 'pass').map((l) => l.phase);
  assert.deepEqual(phases, ['intake', 'phase1', 'phase2', 'phase3', 'phase4', 'phase5', 'phase6',
    'phase7', 'phase8', 'phase9-checklist', 'phase9-senior', 'phase9-confidence',
    'phase9-revalidate', 'phase10', 'done']);
  // Reasoning is on for the judgment phases and off for extraction.
  const thinking = new Map(model.calls.map((c) => [c.schemaName.split('_')[0], c.reasoning]));
  assert.deepEqual(Object.fromEntries(thinking), { intake: false, phase1: true, phase3: true,
    phase4: true, phase5: true, phase6: false, phase7: false, phase9: true, phase10: false });
  assertContentFree(read(path.join(result.outDir, 'status.log')));
});

test('a suite pack builds through the repository\'s merge', async () => {
  const config = fixtureConfig();
  const result = await runJob(config, { suite: 'LIB' }, { model: fakeModel(), echo: false });
  assert.equal(result.ok, true, JSON.stringify(result));
  const pack = JSON.parse(read(result.packPath));
  assert.equal(pack.suite, 'LIB');
  assert.equal(pack.rules.length, 8);
  assert.ok(pack.rules.every((rule) => rule.impact === 'Regression'));
  assert.equal(pack.objectives.find((r) => r.objective === 'Core Change Validation').applicable, false);
  // Cards are written one document at a time, each named by its number.
  const cardCalls = statusLines(result.outDir).filter((l) => l.event === 'call' && l.phase === 'phase6');
  assert.deepEqual([...new Set(cardCalls.map((l) => l.step.split('-')[1]))], ['d1', 'd2']);
  // The merge sees cards as the builder knows them, without the design pass's marks.
  assert.ok(pack.testCards.every((card) => !('scenario' in card) && !('breakIt' in card)));
  assertContentFree(read(path.join(result.outDir, 'status.log')));
});

// Scenario design: the inventory, the card batches, and the sets the cards land in.

const INTAKE = { intake: (value) => ({ ...value, documents: ['docs/LIB/UC01-Card-Renewal.md'] }) };
const lib = (extra = {}, overrides = {}) => ({ model: fakeModel({ ...INTAKE, ...extra }),
  config: fixtureConfig(overrides) });
const runLib = ({ model, config }) => runJob(config, { issue: '501', change: '7001' },
  { model, echo: false });
const phase6Pass = (outDir) => statusLines(outDir).find((l) => l.event === 'pass' && l.phase === 'phase6');

/** An inventory reply of the given scenarios; each takes the rule at its index unless it names a `rule` index. */
const inventory = (specs) => (value) => {
  const ids = value.scenarios[0].rules;
  return { ...value, scenarios: specs.map((spec, i) => ({ kind: 'decision', outcome: 'outcome',
    action: `action ${i}`, population: `population ${i}`, ...spec,
    rules: [ids[spec.rule ?? i % ids.length]] })) };
};
const BREAK = { kind: 'break' };
const titled = (value) => ({ ...value,
  cards: value.cards.map((card) => ({ ...card, title: `Card ${card.scenario}` })) });
const setCards = (pack, objective) => {
  const set = pack.testSets.find((row) => row.objective === objective);
  return set ? set.cards.map((id) => pack.testCards.find((c) => c.id === id).title).sort() : [];
};
const withMaster = (rules) => {
  const master = JSON.parse(read(path.join(FIXTURES, 'master.json')));
  for (const row of master.exports.find((e) => e.doc === 'docs/LIB/UC01-Card-Renewal.md').rules) rules(row);
  const name = `master-${process.pid}-${Date.now()}.json`;
  fs.writeFileSync(path.join(FIXTURES, name), JSON.stringify(master));
  return name;
};

test('the scenario inventory is asked first and its scenarios and earlier cards reach every card call', async () => {
  const run = lib({
    phase6_scenarios: inventory([{}, {}, {}, {}, BREAK]),
    // Each call writes only two cards, so the next call has cards to be shown.
    phase6_cards: (value) => titled({ ...value, cards: value.cards.slice(0, 2) }),
  }, { cardScenariosPerCall: 2 });
  const result = await runLib(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  const steps = run.model.calls.map((c) => c.schemaName).filter((n) => n.startsWith('phase6'));
  assert.equal(steps[0], 'phase6_scenarios_d1');
  const cardCalls = run.model.calls.filter((c) => c.schemaName.startsWith('phase6_cards_d1'));
  assert.ok(cardCalls.length >= 3);
  // Each call is shown the inventory's scenarios that are still open.
  assert.match(cardCalls[0].user, /S1 \| decision \| rules \S+ \| population 0 \| action 0 \| outcome/);
  assert.match(cardCalls[1].user, /S3 \| decision \| rules \S+ \| population 2 \| action 2/);
  assert.ok(!cardCalls[1].user.includes('population 0'));
  assert.ok(!cardCalls[0].user.includes('Card S1'));
  assert.match(cardCalls[1].user, /Cards written so far[^]*Card S1 \| S1 \| rules /);
  // A card names a scenario that is still open, and no other.
  assert.deepEqual(cardCalls[1].schema.properties.cards.items.properties.scenario.enum,
    ['S3', 'S4', 'S5']);
  const pack = JSON.parse(read(result.packPath));
  assert.deepEqual(pack.testCards.map((c) => c.title).sort(), ['Card S1', 'Card S2', 'Card S3',
    'Card S4', 'Card S5']);
  assert.equal(phase6Pass(result.outDir).scenarios, 5);
});

test('the inventory asks for control, isolation, combined, persistence and break scenarios', async () => {
  const run = lib();
  const result = await runLib(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  const call = run.model.calls.find((c) => c.schemaName === 'phase6_scenarios_d1');
  const kinds = ['control', 'isolation', 'combined', 'persistence'];
  const props = call.schema.properties;
  assert.ok([...kinds, 'break'].every((k) => props.scenarios.items.properties.kind.enum.includes(k)));
  assert.deepEqual([...props.kindChecks.required].sort(), [...kinds, 'break'].sort());
  assert.deepEqual(Object.keys(props.kindChecks.properties).sort(), [...kinds, 'break'].sort());
  for (const kind of [...kinds, 'break']) assert.ok(call.user.includes(kind), `the task names ${kind}`);
  assert.ok(props.scenarios.maxItems >= 1);
  // The fake lists only a control scenario, so the other three kinds are noted.
  const pack = JSON.parse(read(result.packPath));
  for (const kind of kinds.slice(1)) {
    assert.ok(pack.assumptions.some((a) => a.assumption.includes(`no ${kind} scenario`)));
  }
  assert.ok(!pack.assumptions.some((a) => a.assumption.includes('no control scenario')));
  // The break pass found one, so its note is gone.
  assert.ok(run.model.calls.some((c) => c.schemaName === 'phase6_scenarios_d1_break'));
  assert.ok(!pack.assumptions.some((a) => a.assumption.includes('no break scenario')));
});

test('scenarios and cards that repeat the same kind, rules, population and action collapse to one', async () => {
  const run = lib({
    phase6_scenarios: inventory([{ population: 'A patron, renewing!', action: 'Renew', rule: 0 },
      { population: 'a patron renewing', action: 'renew.', rule: 0 },
      { population: 'Another patron', rule: 1 }, { ...BREAK, rule: 2 }]),
    // The first card is written twice.
    phase6_cards: (value) => titled({ ...value, cards: [value.cards[0], ...value.cards] }),
  });
  const result = await runLib(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  const pack = JSON.parse(read(result.packPath));
  assert.deepEqual(pack.testCards.map((c) => c.title).sort(), ['Card S1', 'Card S2', 'Card S3']);
  // One scenario dropped from the inventory, one repeated card.
  const pass = phase6Pass(result.outDir);
  assert.equal(pass.duplicates, 2);
  assert.equal(pass.scenarios, 3);
});

test('the same population and action under another kind is a different scenario', async () => {
  const run = lib({ phase6_scenarios: inventory([{ kind: 'control', population: 'p', action: 'a', rule: 0 },
    { kind: 'isolation', population: 'p', action: 'a', rule: 0 }, { ...BREAK, rule: 1 }]) });
  const result = await runLib(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  assert.equal(phase6Pass(result.outDir).scenarios, 3);
});

test('a scenario no card covers is asked for once more, then recorded and its rule gets a gap row', async () => {
  const run = lib({
    phase6_scenarios: inventory([{}, {}, {}]),
    phase6_cards: (value) => titled({ ...value, cards: value.cards.filter((c) => c.scenario === 'S1') }),
  });
  const result = await runLib(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  const again = run.model.calls.filter((c) => c.schemaName.startsWith('phase6_cards_d1_1b'));
  assert.equal(again.length, 1);
  assert.deepEqual(again[0].schema.properties.cards.items.properties.scenario.enum, ['S2', 'S3']);
  assert.match(again[0].user, /needs a card/);
  const pass = phase6Pass(result.outDir);
  assert.equal(pass.retried, 1);
  assert.equal(pass.unsettled, 2);
  const pack = JSON.parse(read(result.packPath));
  for (const id of ['S2', 'S3']) {
    assert.ok(pack.assumptions.some((a) => a.assumption.startsWith(`No test card covers scenario ${id}:`)
      && /no skipped entry/.test(a.why)));
  }
  const missing = pack.coverage.filter((row) => row.status === 'Missing').map((row) => row.ruleId);
  assert.ok(missing.includes('BR-LIB.UC01-002') && missing.includes('BR-LIB.UC01-003'));
});

test('a gap on a rule in one batch does not settle another scenario on that rule', async () => {
  const gap = { ruleId: 'BR-LIB.UC01-001', status: 'Missing', gap: 'gap', recommendation: 'fix' };
  const run = lib({
    phase6_scenarios: inventory([{ rule: 0 }, { rule: 1 }, { rule: 0 }, { ...BREAK, rule: 2 }]),
    // Batch 1 and its retry write a card for S2 only and report a gap on rule 1.
    phase6_cards: (value, calls) => (calls.at(-1).schemaName.startsWith('phase6_cards_d1_1')
      ? { ...titled(value), cards: titled(value).cards.filter((c) => c.scenario === 'S2'), uncovered: [gap] }
      : titled(value)),
  }, { cardScenariosPerCall: 2 });
  const result = await runLib(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  const second = run.model.calls.find((c) => c.schemaName === 'phase6_cards_d1_2');
  assert.ok(second.schema.properties.cards.items.properties.scenario.enum.includes('S3'));
  const pack = JSON.parse(read(result.packPath));
  assert.ok(pack.testCards.some((c) => c.title === 'Card S3'));
  // S1 stayed open and a later call covered it; nothing is recorded as lost.
  assert.deepEqual(pack.testCards.map((c) => c.title).sort(), ['Card S1', 'Card S2', 'Card S3', 'Card S4']);
  assert.equal(phase6Pass(result.outDir).unsettled, 0);
});

test('a later card on a rule does not unsettle a scenario already skipped', async () => {
  const run = lib({
    phase6_scenarios: inventory([{ rule: 0 }, { rule: 0, population: 'other' }, { ...BREAK, rule: 1 }]),
    phase6_cards: (value, calls) => (calls.at(-1).schemaName === 'phase6_cards_d1_1'
      ? { ...value, cards: [], skipped: [{ scenario: 'S1', how: 'gap', reason: 'cannot be tested' }] }
      : titled(value)),
  }, { cardScenariosPerCall: 1 });
  const result = await runLib(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  assert.equal(phase6Pass(result.outDir).unsettled, 0);
  const pack = JSON.parse(read(result.packPath));
  assert.ok(!pack.assumptions.some((a) => a.assumption.includes('scenario S1')));
  assert.deepEqual(pack.testCards.map((c) => c.title).sort(), ['Card S2', 'Card S3']);
});

test('a rule only an existing test covers says so, and points at the test', async () => {
  const run = lib({
    phase6_scenarios: inventory([{}, {}, {}, { ...BREAK, rule: 3 }]),
    phase6_cards: (value) => titled({ ...value, cards: value.cards.filter((c) => c.scenario !== 'S2'),
      skipped: [{ scenario: 'S2', how: 'reused', reason: 'Existing renewal test' }] }),
  });
  const result = await runLib(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  assert.equal(run.model.calls.filter((c) => c.schemaName.startsWith('phase6_cards_d1_1b')).length, 0);
  assert.equal(phase6Pass(result.outDir).unsettled, 0);
  const pack = JSON.parse(read(result.packPath));
  const row = pack.coverage.find((r) => r.ruleId === 'BR-LIB.UC01-002');
  assert.equal(row.status, 'Missing');
  assert.match(row.gap, /Covered only by the existing test Existing renewal test; confirm it and reuse it/);
});

test('the card call reserves room for the scenarios, the cards so far and the existing tests', async () => {
  const name = `existing-tests-${process.pid}.md`;
  fs.writeFileSync(path.join(FIXTURES, name), 'An existing test of the renewal screen. '.repeat(190));
  try {
    const inputs = { ...fixtureInputs(), existingTests: name };
    const model = { endpoint: 'http://localhost:13305/api/v1', name: 'test-model', context: 9000,
      maxOutput: 800, reasoningOutput: 800 };
    const run = lib({}, { inputs, model });
    const result = await runLib(run);
    assert.equal(result.ok, true, JSON.stringify(result));
    const doc = read(path.join(FIXTURES, 'docs/LIB/UC01-Card-Renewal.md'));
    const phrase = doc.split('\n').find((line) => line.length > 40).slice(0, 40);
    const inventoryCall = run.model.calls.find((c) => c.schemaName === 'phase6_scenarios_d1');
    const cardCall = run.model.calls.find((c) => c.schemaName === 'phase6_cards_d1_1');
    // The inventory carries no existing tests, so the document fits whole; the card call does not.
    assert.ok(inventoryCall.user.includes(phrase));
    assert.ok(!cardCall.user.includes(phrase));
    assert.match(cardCall.user, /Document text\s+- points value/);
  } finally {
    fs.rmSync(path.join(FIXTURES, name), { force: true });
  }
});

test('rules too large for one inventory call go in batches, each shown the scenarios so far', async () => {
  const name = withMaster((row) => { row.rule_summary = `${row.rule_summary} ${'x'.repeat(30000)}`; });
  try {
    const inputs = { ...fixtureInputs(), ruleExport: ['node', 'export.mjs', '--doc', '{doc}', '--master', name] };
    const run = lib({}, { inputs });
    const result = await runLib(run);
    assert.equal(result.ok, true, JSON.stringify(result));
    const calls = run.model.calls.filter((c) => /^phase6_scenarios_d1_\d$/.test(c.schemaName));
    assert.ok(calls.length >= 2, `${calls.length} inventory calls`);
    assert.ok(!calls[0].user.includes('population value'));
    assert.match(calls[1].user, /Scenarios listed so far\s+- S1 \| control \| rules .* \| population value/);
    // Each call may name only the rules it was given.
    const first = calls[0].schema.properties.scenarios.items.properties.rules.items.enum;
    const second = calls[1].schema.properties.scenarios.items.properties.rules.items.enum;
    assert.ok(first.every((id) => !second.includes(id)));
  } finally {
    fs.rmSync(path.join(FIXTURES, name), { force: true });
  }
});

// S1 and S2 are requirement cards, S3 is quality-derived and names both special sets.
const SETS = (value) => ({ ...value, cards: value.cards.map((card) => {
  const base = ['Core Change Validation', 'Workflow Validation', 'Negative / Exclusion', 'Regression Testing'];
  const row = { S1: ['Requirement', base], S2: ['Requirement', base],
    S3: ['Quality', [...base, 'Full Coverage Required Run', 'BREAK IT']] }[card.scenario];
  return { ...card, title: `Card ${card.scenario}`, derivation: row[0], objectives: row[1] };
}) });

test('Full Coverage holds every requirement card and BREAK IT only the break scenarios, in several sets at once', async () => {
  const run = lib({ phase6_scenarios: inventory([{}, BREAK, {}]), phase6_cards: SETS });
  const result = await runLib(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  const pack = JSON.parse(read(result.packPath));
  // One card per scenario, and no card twice in a set.
  assert.deepEqual(setCards(pack, 'Full Coverage Required Run'), ['Card S1', 'Card S2']);
  assert.deepEqual(setCards(pack, 'BREAK IT'), ['Card S2']);
  // The BREAK IT card is also in its ordinary sets and in Full Coverage.
  assert.deepEqual(setCards(pack, 'Core Change Validation'), ['Card S1', 'Card S2', 'Card S3']);
  assert.ok(pack.testSets.every((set) => set.cards.length === new Set(set.cards).size));
});

test('exclusiveSets keeps a BREAK IT card in the BREAK IT set alone', async () => {
  const run = lib({ phase6_scenarios: inventory([{}, BREAK, {}]), phase6_cards: SETS },
    { exclusiveSets: true });
  const result = await runLib(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  const pack = JSON.parse(read(result.packPath));
  assert.deepEqual(setCards(pack, 'BREAK IT'), ['Card S2']);
  assert.deepEqual(setCards(pack, 'Full Coverage Required Run'), ['Card S1']);
  assert.deepEqual(setCards(pack, 'Core Change Validation'), ['Card S1', 'Card S3']);
});

test('with no break scenario listed, a targeted pass asks for break scenarios only and writes their cards', async () => {
  const run = lib({
    phase6_scenarios_d1_break: inventory([{ ...BREAK, population: 'junk input', action: 'enter junk', rule: 0 }]),
    phase6_scenarios: inventory([{}, {}]),
    phase6_cards: titled,
  });
  const result = await runLib(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  const pass = run.model.calls.find((c) => c.schemaName === 'phase6_scenarios_d1_break');
  assert.deepEqual(pass.schema.properties.scenarios.items.properties.kind.enum, ['break']);
  assert.ok(!('kindChecks' in pass.schema.properties));
  assert.match(pass.user, /Scenarios listed so far[^]*S1 \| decision/);
  const pack = JSON.parse(read(result.packPath));
  assert.deepEqual(setCards(pack, 'BREAK IT'), ['Card S3']);
  assert.equal(pack.objectives.find((r) => r.objective === 'BREAK IT').applicable, true);
  assert.equal(pack.testCards.length, 3);
});

test('with no break scenario at all, BREAK IT stops being applicable', async () => {
  // The break pass returns only what the document already has.
  const run = lib({ phase6_scenarios: inventory([{}, {}]), phase6_cards: titled });
  const result = await runLib(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  const pack = JSON.parse(read(result.packPath));
  assert.equal(pack.objectives.find((r) => r.objective === 'BREAK IT').applicable, false);
  assert.deepEqual(setCards(pack, 'BREAK IT'), []);
});

// No card names Workflow Validation.
const NO_WORKFLOW = (value) => ({ ...titled(value), cards: titled(value).cards.map((card) => ({ ...card,
  objectives: ['Core Change Validation', 'Negative / Exclusion', 'Regression Testing'] })) });

test('an ordinary objective no card names is put to the model against the cards written, and none is added', async () => {
  const run = lib({ phase6_scenarios: inventory([{}, {}, BREAK]), phase6_cards: NO_WORKFLOW });
  const result = await runLib(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  const asked = run.model.calls.filter((c) => c.schemaName.startsWith('phase6_objective'));
  assert.deepEqual(asked.map((c) => c.schemaName), ['phase6_objective_2']);
  assert.deepEqual(asked[0].schema.properties.cards.items.enum, ['C1', 'C2', 'C3']);
  const pack = JSON.parse(read(result.packPath));
  assert.equal(pack.testCards.length, 3);
  assert.deepEqual(setCards(pack, 'Workflow Validation'), ['Card S1', 'Card S2', 'Card S3']);
});

test('an ordinary objective no card serves is dropped when the model names none', async () => {
  const run = lib({ phase6_scenarios: inventory([{}, {}, BREAK]), phase6_cards: NO_WORKFLOW,
    phase6_objective: (value) => ({ ...value, cards: [] }) });
  const result = await runLib(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  const pack = JSON.parse(read(result.packPath));
  const row = pack.objectives.find((r) => r.objective === 'Workflow Validation');
  assert.equal(row.applicable, false);
  assert.deepEqual(setCards(pack, 'Workflow Validation'), []);
});

test('Full Coverage is applicable whenever a requirement card exists', async () => {
  const run = lib({
    phase5: (value) => {
      value.objectives['Full Coverage Required Run'].applicable = false;
      return value;
    },
    phase6_scenarios: inventory([{}, BREAK]), phase6_cards: titled,
  });
  const result = await runLib(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  const pack = JSON.parse(read(result.packPath));
  const row = pack.objectives.find((r) => r.objective === 'Full Coverage Required Run');
  assert.equal(row.applicable, true);
  assert.equal(row.reason, 'Applicable: this set holds every requirement-derived card.');
  assert.deepEqual(setCards(pack, 'Full Coverage Required Run'), ['Card S1', 'Card S2']);
});

test('Full Coverage stays not applicable when exclusiveSets leaves no card for it', async () => {
  const run = lib({
    phase5: (value) => {
      value.objectives['Full Coverage Required Run'].applicable = false;
      return value;
    },
    phase6_scenarios: inventory([BREAK, { ...BREAK, population: 'other' }]), phase6_cards: titled,
  }, { exclusiveSets: true });
  const result = await runLib(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  const pack = JSON.parse(read(result.packPath));
  const row = pack.objectives.find((r) => r.objective === 'Full Coverage Required Run');
  assert.equal(row.applicable, false);
  assert.deepEqual(setCards(pack, 'Full Coverage Required Run'), []);
  assert.deepEqual(setCards(pack, 'BREAK IT'), ['Card S1', 'Card S2']);
});

test('a reason that ends in a period does not double it in a coverage gap', async () => {
  const run = lib({
    phase6_scenarios: inventory([{}, {}, {}, { ...BREAK, rule: 3 }]),
    phase6_cards: (value) => titled({ ...value, cards: value.cards.filter((c) => c.scenario !== 'S2'),
      skipped: [{ scenario: 'S2', how: 'reused', reason: 'Existing renewal test.' }] }),
  });
  const result = await runLib(run);
  const pack = JSON.parse(read(result.packPath));
  assert.ok(!pack.coverage.some((r) => /\.\./.test(r.gap)));
});

test('a card left in no set never lands in BREAK IT', () => {
  const objectives = (...names) => names.map((objective) => ({ objective, applicable: true }));
  const ctx = (...names) => ({ fullCoverageObjective: 'F', breakItObjective: 'B', config: {},
    job: {}, pack: { objectives: objectives(...names) } });
  const quality = { objectives: ['B'], derivation: 'Quality', breakIt: false };
  assert.deepEqual(setsOf(ctx('F', 'B', 'O'), quality), ['O']);
  assert.deepEqual(setsOf(ctx('F', 'B'), quality), ['F']);
  assert.deepEqual(setsOf(ctx('B'), quality), []);
  assert.deepEqual(setsOf(ctx('F', 'B', 'O'), { ...quality, breakIt: true, objectives: ['O'] }), ['O', 'B']);
});

test('the set objectives and the cards per call come from config, with the usual names as defaults', () => {
  const config = fixtureConfig();
  assert.equal(config.cardScenariosPerCall, 4);
  assert.equal(config.exclusiveSets, false);
  assert.equal(config.fullCoverageObjective, null);
  const named = fixtureConfig({ fullCoverageObjective: 'Full Run', breakItObjective: 'Abuse',
    cardScenariosPerCall: 2, exclusiveSets: true });
  assert.deepEqual([named.fullCoverageObjective, named.breakItObjective, named.cardScenariosPerCall,
    named.exclusiveSets], ['Full Run', 'Abuse', 2, true]);
  assert.throws(() => fixtureConfig({ cardScenariosPerCall: 0 }), /cardScenariosPerCall/);
  assert.throws(() => fixtureConfig({ exclusiveSets: 'yes' }), /exclusiveSets/);
  assert.throws(() => fixtureConfig({ cardRulesPerCall: 4 }), /cardScenariosPerCall/);
});

test('a failed gate stops the run with a content-free status line', async () => {
  const config = fixtureConfig();
  const model = fakeModel({ phase1: (value) => ({ ...value,
    conflicts: ['UC01 page 4 and the defect record disagree on the renewal expiry'] }) });
  const result = await runJob(config, { issue: '501', change: '7001' }, { model, echo: false });
  assert.equal(result.ok, false);
  assert.equal(result.phase, 'phase1');
  assert.equal(result.reason, 'gate:source-conflict');
  const last = statusLines(result.outDir).at(-1);
  assert.equal(last.event, 'fail');
  assert.equal(last.conflicts, 1);
  assertContentFree(read(path.join(result.outDir, 'status.log')));
  // The conflict's text stays in the local detail log.
  assert.ok(read(path.join(result.outDir, 'detail.log')).includes('renewal expiry'));
  assert.ok(!fs.readdirSync(result.outDir).some((name) => name.endsWith('.xlsx')));
});

test('a missing description stops intake', async () => {
  const config = fixtureConfig();
  const result = await runJob(config, { issue: '999' }, { model: fakeModel(), echo: false });
  assert.equal(result.ok, false);
  assert.equal(result.reason, 'gate:missing-inputs');
});

test('a builder FAIL goes back to the model and the repair is applied', async () => {
  const config = fixtureConfig();
  const model = fakeModel({
    phase6_cards: (value) => ({ ...value, cards: value.cards.map((card) => ({ ...card, title: 'REJECT' })) }),
    phase8_repair: (value) => ({ ...value, coverage: [], limitations: [],
      cards: value.cards.map((card) => ({ ...card, title: 'Repaired title' })) }),
  });
  const result = await runJob(config, { issue: '501', change: '7001' }, { model, echo: false });
  assert.equal(result.ok, true, JSON.stringify(result));
  assert.ok(result.repairs >= 1);
  const repair = model.calls.find((c) => c.schemaName.startsWith('phase8_repair'));
  assert.ok(repair.user.includes('rejected title'));
  const pack = JSON.parse(read(result.packPath));
  assert.ok(pack.testCards.every((card) => card.title === 'Repaired title'));
});

test('repairs are bounded: a FAIL the model cannot fix stops the run', async () => {
  const config = fixtureConfig();
  const model = fakeModel({
    phase6_cards: (value) => ({ ...value, cards: value.cards.map((card) => ({ ...card, title: 'REJECT' })) }),
    phase8_repair: (value) => ({ ...value, coverage: [], limitations: [],
      cards: value.cards.map((card) => ({ ...card, title: 'REJECT' })) }),
  });
  const result = await runJob(config, { issue: '501', change: '7001' }, { model, echo: false });
  assert.equal(result.ok, false);
  assert.equal(result.reason, 'gate:builder-fail');
  assert.equal(model.calls.filter((c) => c.schemaName.startsWith('phase8_repair')).length, 2);
});

test('a prompt too big for the context is refused, not truncated', async () => {
  const config = fixtureConfig({ model: { endpoint: 'http://localhost:1/v1', name: 'm',
    context: 3000, maxOutput: 500, reasoningOutput: 500 } });
  const model = fakeModel();
  const result = await runJob(config, { issue: '501', change: '7001' }, { model, echo: false });
  assert.equal(result.ok, false);
  // Intake fits; the documents do not, even as digests, and nothing is cut to make them.
  assert.match(result.reason, /too-big/);
});

test('only a loopback endpoint is accepted', () => {
  assert.equal(localEndpoint('http://localhost:13305/api/v1/'), 'http://localhost:13305/api/v1');
  assert.equal(localEndpoint('http://127.0.0.1:8001'), 'http://127.0.0.1:8001');
  for (const url of ['https://api.anthropic.com/v1', 'http://192.168.1.5:13305/v1',
    'http://localhost.example.com/v1', 'not a url']) {
    assert.throws(() => localEndpoint(url));
  }
  assert.throws(() => fixtureConfig({ model: { endpoint: 'https://api.openai.com/v1', name: 'm' } }),
    /loopback/);
});

test('the client contacts only the configured endpoint and the loopback backend', async () => {
  const urls = [];
  const fetchImpl = async (url, options) => {
    urls.push(String(url));
    if (String(url).endsWith('/health')) {
      return { json: async () => ({ all_models_loaded: [{ model_name: 'm',
        backend_url: 'http://127.0.0.1:8001/v1' }] }) };
    }
    if (String(url).endsWith('/tokenize')) return { json: async () => ({ tokens: [1, 2, 3] }) };
    const body = JSON.parse(options.body);
    assert.equal(body.response_format.type, 'json_schema');
    assert.equal(body.chat_template_kwargs.enable_thinking, true);
    return { ok: true, json: async () => ({ choices: [{ finish_reason: 'stop',
      message: { content: '{"a":1}' } }], usage: { prompt_tokens: 3, completion_tokens: 2 } }) };
  };
  const client = modelClient({ endpoint: 'http://localhost:13305/api/v1', name: 'm', fetchImpl });
  assert.equal(await client.countTokens('three tokens here'), 3);
  const { value } = await client.json({ system: 's', user: 'u', schema: { type: 'object' },
    schemaName: 'x', reasoning: true, maxTokens: 10 });
  assert.deepEqual(value, { a: 1 });
  for (const url of urls) {
    assert.ok(/^http:\/\/(localhost:13305|127\.0\.0\.1:8001)\//.test(url), url);
  }
});

test('no pipeline module reaches the network except the model client', () => {
  for (const name of fs.readdirSync(HERE).filter((n) => n.endsWith('.mjs') && !n.endsWith('.test.mjs'))) {
    const source = read(path.join(HERE, name));
    if (name === 'model.mjs') continue;
    assert.ok(!/\bfetch\(|node:https?|node:net|https?:\/\//.test(source), `${name} reaches the network`);
  }
});

test('a cut-off reply is retried once with thinking off', async () => {
  let calls = 0;
  const fetchImpl = async (url, options) => {
    calls += 1;
    const body = JSON.parse(options.body);
    const finish = body.chat_template_kwargs.enable_thinking ? 'length' : 'stop';
    return { ok: true, json: async () => ({ choices: [{ finish_reason: finish,
      message: { content: '{"ok":true}' } }], usage: {} }) };
  };
  const config = fixtureConfig();
  const { ask } = await import('./phases.mjs');
  const logs = { status() {}, detail() {} };
  const ctx = { config, calls: 0, tokens: { prompt: 0, output: 0 }, logs, job: { id: 'j' },
    model: { ...modelClient({ endpoint: 'http://localhost:1/v1', name: 'm', fetchImpl }),
      countTokens: async () => 10 } };
  const value = await ask(ctx, { phase: 'phase1', step: 's', reasoning: true, inputs: [],
    schema: { type: 'object' }, task: 't' });
  assert.deepEqual(value, { ok: true });
  assert.equal(calls, 2);
});

test('splitting keeps every character and stays under the limit', () => {
  const text = Array.from({ length: 200 }, (_, i) => `Paragraph ${i} ${'word '.repeat(i % 40)}`)
    .join('\n\n') + `\n\n${'x'.repeat(5000)}`;
  const pieces = splitText(text, 300);
  assert.ok(pieces.length > 1);
  assert.ok(pieces.every((piece) => piece.length <= 900));
  assert.equal(pieces.join('').replace(/\s/g, ''), text.replace(/\s/g, ''));
  const groups = batches(Array.from({ length: 10 }, (_, i) => i), () => 'abc', 100, 4);
  assert.deepEqual(groups.map((g) => g.length), [4, 4, 2]);
});

test('status fields take only short codes', () => {
  assert.doesNotThrow(() => statusFields({ phase: 'phase6', step: 'cards-UC01-1', ms: 4 }));
  assert.throws(() => statusFields({ reason: 'BR-LIB.UC01-004 is a Direct Change, no card covers it' }));
  assert.throws(() => statusFields({ note: 'a "quoted" value' }));
});

test('the queue runs jobs in order, marks failures, and stops at the cutoff', async () => {
  const config = fixtureConfig();
  assert.throws(() => jobFrom(parseArgs(['--issue', 'abc'])));
  assert.deepEqual(jobFrom(parseArgs(['--issue', '501', '--change', '7001'])),
    { issue: '501', change: '7001' });
  addJob(config, { issue: '501', change: '7001' });
  assert.equal(addJob(config, { issue: '501', change: '7001' }).added, false);
  addJob(config, { suite: 'LIB' });
  addJob(config, { issue: '777' });
  let t = new Date('2026-10-27T22:00:00');
  const clock = () => t;
  const ran = [];
  const run = async (_config, job) => {
    ran.push(job.id);
    t = new Date(t.getTime() + 4.5 * 3600000);
    return job.suite ? { ok: false, phase: 'phase3', reason: 'gate:unclassified-rule', ms: 1 }
      : { ok: true, ms: 1, workbook: '/out/w.xlsx' };
  };
  const done = await drainQueue(config, { cutoff: '07:00', run, clock });
  // 22:00 starts the first job, 02:30 the second; 07:00 has passed when it ends.
  assert.deepEqual(ran, ['issue-501-change-7001', 'suite-LIB']);
  assert.equal(done.length, 2);
  const queue = readQueue(config);
  assert.deepEqual(queue.jobs.map((row) => row.status), ['passed', 'queued', 'queued']);
  const lines = summaryLines(queue);
  assert.match(lines[1], /retry after stopping at phase3 \(gate:unclassified-rule\)/);
  assert.equal(cutoffAfter(new Date('2026-10-27T22:00:00'), '07:00').getDate(), 28);
  assert.throws(() => cutoffAfter(new Date(), '7am'), /HH:MM/);
});

test('the nightly queue takes no job outside its window and retries interrupted rows at once', async () => {
  const config = fixtureConfig();
  addJob(config, { issue: '501' });
  addJob(config, { issue: '777' });
  const queue = readQueue(config);
  queue.jobs[0].status = 'running';
  fs.writeFileSync(config.at(config.queue.file), JSON.stringify(queue));
  const ran = [];
  const run = async (_config, job) => { ran.push(job.id); return { ok: true, ms: 1 }; };
  // A timer catching up at 08:00 is past the cutoff and before the start.
  const morning = () => new Date('2026-10-28T08:00:00');
  assert.deepEqual(await drainQueue(config, { cutoff: '07:00', start: '22:00', run, clock: morning }), []);
  assert.deepEqual(ran, []);
  const night = () => new Date('2026-10-28T23:00:00');
  await drainQueue(config, { cutoff: '07:00', start: '22:00', run, clock: night });
  // An interrupted run counts as a failed try, and the row is taken again by this very run.
  assert.deepEqual(ran, ['issue-501', 'issue-777']);
  const rows = readQueue(config).jobs;
  assert.deepEqual(rows.map((row) => row.status), ['passed', 'passed']);
  assert.deepEqual(rows[0].failures.map((f) => f.reason), ['interrupted']);
  assert.equal(rows[0].notBefore, undefined);
});

test('a job started on request runs first, then other start-now rows, within the configured cutoff', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'build-pack-q-'));
  const config = fixtureConfig({ queue: { file: path.join(dir, 'queue.json'), cutoff: '05:30' } });
  addJob(config, { issue: '100' });
  addJob(config, { issue: '200', now: true });
  addJob(config, { issue: '9415', now: true });
  const ran = [];
  let t = new Date('2026-10-28T14:00:00');
  const run = async (_config, job) => {
    ran.push(job.id);
    t = new Date(t.getTime() + 3600000);
    return { ok: true, ms: 1 };
  };
  const done = await drainQueue(config, { only: 'issue-9415', nowOnly: true, run, clock: () => t });
  // issue-100 is queued for the nightly run and stays queued.
  assert.deepEqual(ran, ['issue-9415', 'issue-200']);
  assert.equal(done.length, 2);
  assert.deepEqual(readQueue(config).jobs.map((row) => row.status), ['queued', 'passed', 'passed']);
  // queue add --now marks a row that is waiting for tonight; a run without nowOnly takes it.
  assert.equal(addJob(config, { issue: '100', now: true }).added, false);
  assert.equal(readQueue(config).jobs[0].now, true);
  // A job ID with no queued row takes nothing, and the rest of the queue waits.
  addJob(config, { issue: '77' });
  assert.deepEqual(await drainQueue(config, { only: 'issue-1', nowOnly: true, run, clock: () => t }), []);
  assert.equal(readQueue(config).jobs.at(-1).status, 'queued');
  // The cutoff is the config's 05:30: a clock that reads 04:00 when the cutoff
  // is set and 06:00 when the job would start leaves the job queued.
  addJob(config, { issue: '55' });
  const reads = [new Date('2026-10-29T04:00:00'), new Date('2026-10-29T06:00:00')];
  const clock = () => reads.shift() ?? reads.at(-1) ?? new Date('2026-10-29T06:00:00');
  assert.deepEqual(await drainQueue(config, { only: 'issue-55', nowOnly: true, run, clock }), []);
  assert.equal(readQueue(config).jobs.at(-1).status, 'queued');
});

test('a start request while another run holds the queue leaves the row queued', async () => {
  const config = fixtureConfig();
  addJob(config, { issue: '9415' });
  // This process is alive, so it stands in for the holder.
  const lock = `${config.at(config.queue.file)}.lock`;
  fs.writeFileSync(lock, String(process.pid));
  assert.equal(lockHeld(config), true);
  let busy = 0;
  const run = async () => { throw new Error('must not run'); };
  assert.deepEqual(await drainQueue(config, { only: 'issue-9415', onBusy: () => { busy += 1; }, run }), []);
  assert.equal(busy, 1);
  assert.match(jobStatus(config, 'issue-9415')[0], /issue-9415  queued  queue held/);
  fs.rmSync(lock);
});

test('a lock file left by a dead process is not a holder', async () => {
  const config = fixtureConfig();
  addJob(config, { issue: '9415' });
  const lock = `${config.at(config.queue.file)}.lock`;
  const run = async () => ({ ok: true, ms: 1 });
  // A dead PID, an empty file, PID 0, junk, and a live PID with another start time.
  for (const text of ['2147483646', '', '0', 'abc', `${process.pid} 1`]) {
    fs.writeFileSync(lock, text);
    assert.equal(lockHeld(config), false, `lock text "${text}"`);
    addJob(config, { issue: '9415' });
    const done = await drainQueue(config, { only: 'issue-9415', run });
    assert.equal(done.length, 1, `lock text "${text}"`);
    assert.equal(fs.existsSync(lock), false);
    assert.deepEqual(fs.readdirSync(path.dirname(lock)).filter((f) => f.includes('.lock')), []);
  }
});

test('a queue run behind a holder waits for the queue, and a start retries once', async () => {
  const config = fixtureConfig();
  addJob(config, { issue: '100' });
  const lock = `${config.at(config.queue.file)}.lock`;
  fs.writeFileSync(lock, String(process.pid));
  let t = new Date('2026-10-28T22:00:00');
  const naps = [];
  // Each nap is half an hour on the clock; the holder lets go on the third.
  const sleep = async (ms) => {
    naps.push(ms);
    t = new Date(t.getTime() + 1800000);
    if (naps.length === 3) fs.rmSync(lock);
  };
  const ran = [];
  const run = async (_config, job) => { ran.push(job.id); return { ok: true, ms: 1 }; };
  const done = await drainQueue(config, { wait: true, run, sleep, clock: () => t,
    settleMs: 5, pollMs: 7 });
  assert.deepEqual(naps, [5, 7, 7]);
  assert.deepEqual(ran, ['issue-100']);
  assert.equal(done.length, 1);
  // A holder that never lets go ends the wait at the cutoff, with nothing run.
  addJob(config, { issue: '200' });
  fs.writeFileSync(lock, String(process.pid));
  t = new Date('2026-10-28T22:00:00');
  let busy = 0;
  assert.deepEqual(await drainQueue(config, { wait: true, run, sleep: async () => {
    t = new Date(t.getTime() + 4 * 3600000);
  }, clock: () => t, onBusy: () => { busy += 1; } }), []);
  assert.equal(busy, 1);
  // A start waits once, then reports busy; a holder that finishes in that wait is not busy.
  let napped = 0;
  await drainQueue(config, { only: 'issue-200', nowOnly: true, run, onBusy: () => { busy += 1; },
    sleep: async () => { napped += 1; } });
  assert.equal(napped, 1);
  assert.equal(busy, 2);
  fs.rmSync(lock);
  assert.equal((await drainQueue(config, { run })).length, 1);
});

test('queue add says what it did to a row already open', () => {
  const config = fixtureConfig();
  addJob(config, { issue: '100' });
  assert.deepEqual(addJob(config, { issue: '100' }), { id: 'issue-100', added: false, running: false });
  assert.deepEqual(addJob(config, { issue: '100', now: true, resume: true }),
    { id: 'issue-100', added: false, marked: true, merged: ['resume'] });
  // Derived rules and the named documents are merged into the open row too.
  assert.deepEqual(addJob(config, { issue: '100', allowDerivedRules: true, docs: ['docs/a.md'] }),
    { id: 'issue-100', added: false, merged: ['allowDerivedRules', 'docs'] });
  assert.deepEqual(addJob(config, { issue: '100', allowDerivedRules: true, docs: ['docs/a.md'] }),
    { id: 'issue-100', added: false, running: false });
  const [row] = readQueue(config).jobs;
  assert.equal(row.now, true);
  assert.equal(row.resume, true);
  assert.equal(row.allowDerivedRules, true);
  assert.deepEqual(row.docs, ['docs/a.md']);
  Object.assign(row, { status: 'running' });
  fs.writeFileSync(config.at(config.queue.file), JSON.stringify({ jobs: [row] }));
  assert.equal(addJob(config, { issue: '100', now: true }).running, true);
});

test('a nightly row stays queued after a start, and a plain run still takes every row', async () => {
  const config = fixtureConfig();
  addJob(config, { issue: '100' });
  addJob(config, { issue: '9415', now: true });
  const ran = [];
  const run = async (_config, job) => { ran.push([job.id, job.now]); return { ok: true, ms: 1 }; };
  await drainQueue(config, { only: 'issue-9415', nowOnly: true, run });
  assert.deepEqual(ran, [['issue-9415', undefined]]);
  assert.deepEqual(readQueue(config).jobs.map((row) => row.status), ['queued', 'passed']);
  await drainQueue(config, { run });
  assert.deepEqual(readQueue(config).jobs.map((row) => row.status), ['passed', 'passed']);
});

test('a run releases only its own lock', async () => {
  const config = fixtureConfig();
  addJob(config, { issue: '9415' });
  const lock = `${config.at(config.queue.file)}.lock`;
  // Another holder replaces the lock while the job runs.
  const run = async () => { fs.writeFileSync(lock, `${process.pid} other`); return { ok: true, ms: 1 }; };
  await drainQueue(config, { run });
  assert.equal(fs.readFileSync(lock, 'utf8'), `${process.pid} other`);
});

test('clearing a stale lock never removes a lock another starter just took', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'build-pack-lock-'));
  const lock = path.join(dir, 'queue.json.lock');
  // The file still holds what was judged stale: it goes.
  fs.writeFileSync(lock, '2147483646');
  assert.equal(claimStale(lock, '2147483646'), true);
  assert.equal(fs.existsSync(lock), false);
  // The file now holds a live holder's text: it stays.
  fs.writeFileSync(lock, `${process.pid}`);
  assert.equal(claimStale(lock, '2147483646'), false);
  assert.equal(fs.readFileSync(lock, 'utf8'), `${process.pid}`);
  assert.deepEqual(fs.readdirSync(dir), ['queue.json.lock']);
  // Nothing to remove counts as cleared.
  fs.rmSync(lock);
  assert.equal(claimStale(lock, 'x'), true);
});

test('job status shows the row and the last status line, and nothing else', async () => {
  const config = fixtureConfig();
  assert.deepEqual(jobStatus(config, 'issue-9415'), ['issue-9415  not queued  queue free']);
  addJob(config, { issue: '9415' });
  const queue = readQueue(config);
  Object.assign(queue.jobs[0], { status: 'running', started: '2026-10-28T10:00:00.000Z' });
  fs.writeFileSync(config.at(config.queue.file), JSON.stringify(queue));
  const dir = path.join(config.output, 'issue-9415');
  fs.mkdirSync(dir, { recursive: true });
  const logPath = path.join(dir, 'status.log');
  // The last line of an earlier attempt is not this attempt's.
  fs.writeFileSync(logPath, `${JSON.stringify({ at: '2026-10-27T10:00:00.000Z', job: 'issue-9415',
    phase: 'phase5', event: 'fail' })}\n`);
  assert.deepEqual(jobStatus(config, 'issue-9415'), ['issue-9415  running  queue free']);
  fs.appendFileSync(logPath,
    `${JSON.stringify({ at: '2026-10-28T10:01:00.000Z', job: 'issue-9415', phase: 'phase2', event: 'start' })}\n`);
  // A line cut off mid-write is skipped.
  fs.appendFileSync(logPath, '{"at":"2026-10-28T10:02:0');
  assert.deepEqual(jobStatus(config, 'issue-9415'),
    ['issue-9415  running  queue free', 'job=issue-9415 phase=phase2 event=start']);
  fs.appendFileSync(logPath, `\n${JSON.stringify({ at: '2026-10-28T10:03:00.000Z', reason: 'Patron "renewal" text' })}\n`);
  assert.throws(() => jobStatus(config, 'issue-9415'), /short code/);
});

test('the client refuses redirects, so a prompt cannot be handed to another host', async () => {
  const seen = [];
  const fetchImpl = async (url, options) => {
    seen.push(options.redirect);
    if (url.endsWith('/health')) return { ok: true, json: async () => ({ all_models_loaded: [] }) };
    return { ok: true, json: async () => ({ choices: [{ finish_reason: 'stop',
      message: { content: '{}' } }], usage: {} }) };
  };
  const client = modelClient({ endpoint: 'http://localhost:1/v1', name: 'm', fetchImpl });
  await client.countTokens('x');
  await client.json({ system: 's', user: 'u', schema: {}, schemaName: 'n', maxTokens: 1 });
  assert.ok(seen.length >= 2 && seen.every((value) => value === 'error'));
});

test('one row per key is asked for as an object, so no key repeats or goes missing', async () => {
  const { understandingSchema, unkey } = await import('./schemas.mjs');
  const schema = understandingSchema({ documents: ['A doc', 'B doc'], keys: ['UC01', 'UC02'],
    inclusions: ['Included'], suite: false });
  assert.deepEqual(schema.properties.modules.required, ['UC01', 'UC02']);
  const reply = unkey(schema, { modules: { UC01: { module: 'M', abbreviation: 'MA' },
    UC02: { module: 'N', abbreviation: 'NA' } } });
  assert.deepEqual(reply.modules.map((row) => row.document), ['UC01', 'UC02']);
});

test('a reply with no JSON body is a no-reply error that carries none of the body', async () => {
  const fetchImpl = async () => ({ ok: true,
    json: async () => { throw new SyntaxError('Unexpected token < in "<html>Renewal"'); } });
  const client = modelClient({ endpoint: 'http://localhost:1/v1', name: 'm', fetchImpl });
  await assert.rejects(client.json({ system: 's', user: 'u', schema: {}, schemaName: 'n',
    maxTokens: 1 }), (error) => error.code === 'no-reply' && !/Renewal/.test(error.message));
});

test('a failed rule export stops intake unless it says the document has no rules yet', async () => {
  const failing = ['node', '-e', 'process.stderr.write("{doc} is not in the doc map"); process.exit(1)'];
  const outage = fixtureConfig({ inputs: { ...fixtureInputs(), ruleExport: failing } });
  const stopped = await runJob(outage, { issue: '501', change: '7001' },
    { model: fakeModel(), echo: false });
  assert.equal(stopped.ok, false);
  assert.equal(stopped.reason, 'gate:rule-export-failed');
  assertContentFree(read(path.join(stopped.outDir, 'status.log')));

  const noRules = fixtureConfig({ inputs: { ...fixtureInputs(), ruleExport: failing,
    noRules: 'is not in the doc map' } });
  const refused = await runJob(noRules, { issue: '501', change: '7001' },
    { model: fakeModel(), echo: false });
  assert.equal(refused.reason, 'gate:rules-not-extracted');

  const allowed = fixtureConfig({ allowDerivedRules: true, inputs: noRules.inputs });
  const model = fakeModel();
  const derived = await runJob(allowed, { issue: '501', change: '7001' }, { model, echo: false });
  assert.equal(derived.ok, true);
  assert.ok(model.calls.some((call) => /derive/.test(call.schemaName)));

  // A job can opt in on its own, too.
  const byJob = await runJob(noRules, { issue: '501', change: '7001', allowDerivedRules: true },
    { model: fakeModel(), echo: false });
  assert.equal(byJob.ok, true);
});

const exportFrom = (master) => ['node', 'export.mjs', '--master', master, '--doc', '{doc}'];
const withExport = (master) => fixtureConfig({ inputs: { ...fixtureInputs(), ruleExport: exportFrom(master) } });
const issueJob = (docs) => ({ issue: '501', change: '7001', docs });

/** A model whose Phase 1 marks the named documents as context only. */
const contextOnly = (...names) => fakeModel({ phase1: (value) => {
  for (const name of names) if (value.sourceDocuments) value.sourceDocuments[name].inclusion = 'Supporting Context Only';
  return value;
} });

test('an Included document with no map entry stops Phase 2 with rules-not-extracted', async () => {
  const config = fixtureConfig();
  const model = fakeModel();
  const result = await runJob(config, issueJob(['docs/OTHER/UC09-Unmapped.md']), { model, echo: false });
  assert.equal(result.ok, false);
  assert.equal(result.phase, 'phase2');
  assert.equal(result.reason, 'gate:rules-not-extracted');
  const last = statusLines(result.outDir).at(-1);
  assert.equal(last.documents, 1);
  assert.equal(last.numbers, '1');
  assertContentFree(read(path.join(result.outDir, 'status.log')));
  assert.ok(!model.calls.some((call) => /derive/.test(call.schemaName)));
});

test('a context-only document with no rules does not stop the job', async () => {
  const config = fixtureConfig();
  const model = contextOnly('UC09-Unmapped');
  const result = await runJob(config, issueJob(['docs/LIB/UC01-Card-Renewal.md',
    'docs/OTHER/UC09-Unmapped.md']), { model, echo: false });
  assert.equal(result.ok, true, JSON.stringify(result));
});

test('every Included document without rules is reported in one stop', async () => {
  const config = fixtureConfig();
  const result = await runJob(config, issueJob(['docs/OTHER/UC09-Unmapped.md',
    'docs/LIB/UC01-Card-Renewal.md', 'docs/OTHER/UC03-Lost-Cards.md']),
  { model: fakeModel(), echo: false });
  assert.equal(result.reason, 'gate:rules-not-extracted');
  const last = statusLines(result.outDir).at(-1);
  assert.deepEqual([last.documents, last.numbers], [2, '1 3']);
});

test('a job resumed after the rules are extracted reads the new export', async () => {
  const config = fixtureConfig();
  const job = issueJob(['docs/OTHER/UC09-Unmapped.md']);
  const stopped = await runJob(config, job, { model: fakeModel(), echo: false });
  assert.equal(stopped.phase, 'phase2');
  config.inputs = { ...config.inputs, ruleExport: exportFrom('exports/fixed.json') };
  const resumed = await runJob(config, { ...job, resume: true }, { model: fakeModel(), echo: false });
  assert.equal(resumed.ok, true, JSON.stringify(resumed));
  assert.deepEqual(JSON.parse(read(resumed.packPath)).rules.map((rule) => rule.id), ['BR-LIB.UC09-001']);
});

/** A rule export that appends each document it is asked for to `log`, then runs the fixture export. */
const loggedExport = (log) => ['node', '-e',
  'const fs = require("fs"); const d = process.argv[2]; fs.appendFileSync(process.argv[1], d + "\\n");'
  + ' const r = require("child_process").spawnSync("node", ["export.mjs", "--doc", d],'
  + ' { stdio: "inherit" }); process.exit(r.status);', log, '{doc}'];

test('queue add --now on a queued row marks it and exits 0', () => {
  const config = fixtureConfig();
  const add = (...args) => spawnSync(process.execPath, [path.join(HERE, 'build-pack.mjs'), 'queue', 'add',
    '--config', config.file, '--issue', '100', ...args], { encoding: 'utf8' });
  assert.match(add().stdout, /queued issue-100/);
  const again = add('--now');
  assert.equal(again.status, 0, again.stderr);
  assert.match(again.stdout, /marked to start now/);
  const derived = add('--allow-derived-rules');
  assert.equal(derived.status, 0, derived.stderr);
  assert.match(derived.stdout, /updated allowDerivedRules/);
});

test('a run whose intake read usable rules does not export them again in Phase 2', async () => {
  const log = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'exports-')), 'log');
  const config = fixtureConfig();
  config.inputs = { ...config.inputs, ruleExport: loggedExport(log) };
  const model = contextOnly('UC02 Overdue Fines');
  const result = await runJob(config, issueJob(['docs/LIB/UC01-Card-Renewal.md',
    'docs/LIB/UC02-Overdue-Fines.md']), { model, echo: false });
  assert.equal(result.ok, true, JSON.stringify(result));
  assert.deepEqual(read(log).trim().split('\n').sort(),
    ['docs/LIB/UC01-Card-Renewal.md', 'docs/LIB/UC02-Overdue-Fines.md']);
});

test('Phase 2 names each failing document and stops under the most basic code', async () => {
  const config = fixtureConfig();
  const job = issueJob(['docs/OTHER/UC09-Unmapped.md', 'docs/OTHER/UC03-Lost-Cards.md']);
  const first = await runJob(config, job, { model: fakeModel(), echo: false });
  assert.equal(first.reason, 'gate:rules-not-extracted');
  // The export now fails outright for document 1 while document 2 is still unmapped.
  config.inputs = { ...config.inputs, ruleExport: ['node', '-e',
    'if (process.argv[1].includes("UC09")) { process.stderr.write("boom"); process.exit(1); }'
    + ' const r = require("child_process").spawnSync("node", ["export.mjs", "--doc", process.argv[1]],'
    + ' { stdio: "inherit" }); process.exit(r.status);', '{doc}'] };
  const again = await runJob(config, { ...job, resume: true }, { model: fakeModel(), echo: false });
  assert.equal(again.reason, 'gate:rule-export-failed');
  const lines = statusLines(again.outDir);
  assert.deepEqual(lines.filter((l) => l.event === 'stop-doc').slice(-2).map((l) => [l.document, l.reason]),
    [[1, 'rule-export-failed'], [2, 'rules-not-extracted']]);
  const last = lines.at(-1);
  assert.deepEqual([last.documents, last.numbers], [2, '1 2']);
});

test('an export outage in Phase 2 keeps the rules intake read and warns', async () => {
  const config = fixtureConfig();
  const job = issueJob(['docs/LIB/UC01-Card-Renewal.md', 'docs/OTHER/UC09-Unmapped.md']);
  const first = await runJob(config, job, { model: fakeModel(), echo: false });
  assert.equal(first.reason, 'gate:rules-not-extracted');
  config.inputs = { ...config.inputs, ruleExport: ['node', '-e',
    'const d = process.argv[1]; if (d.includes("UC01")) { process.stderr.write("boom"); process.exit(1); }'
    + ' const r = require("child_process").spawnSync("node", ["export.mjs", "--doc", d,'
    + ' "--master", "exports/fixed.json"], { stdio: "inherit" }); process.exit(r.status);', '{doc}'] };
  const again = await runJob(config, { ...job, resume: true }, { model: fakeModel(), echo: false });
  assert.equal(again.ok, true, JSON.stringify(again));
  assert.ok(statusLines(again.outDir).some((l) => l.event === 'warn' && l.reason === 'rule-export-failed'
    && l.document === 1));
  const ids = JSON.parse(read(again.packPath)).rules.map((rule) => rule.id);
  assert.ok(ids.includes('BR-LIB.UC01-001') && ids.includes('BR-LIB.UC09-001'));
});

test('a checkpoint written without document paths resumes without re-reading the export', async () => {
  const config = fixtureConfig();
  const job = issueJob(['docs/OTHER/UC09-Unmapped.md']);
  const first = await runJob(config, job, { model: fakeModel(), echo: false });
  assert.equal(first.phase, 'phase2');
  const file = path.join(first.outDir, 'work', 'checkpoint.json');
  const saved = JSON.parse(read(file));
  for (const doc of saved.state.documents) delete doc.file;
  fs.writeFileSync(file, JSON.stringify(saved));
  // The document keeps the rules it had (none), so Phase 2 derives them rather than crashing.
  const model = fakeModel();
  config.allowDerivedRules = true;
  const resumed = await runJob(config, { ...job, resume: true }, { model, echo: false });
  assert.equal(resumed.ok, true, JSON.stringify(resumed));
  assert.ok(model.calls.some((call) => /derive/.test(call.schemaName)));
});

test('a structurally malformed export stops intake, and only detail.log says why', async () => {
  const config = withExport('exports/malformed.json');
  const result = await runJob(config, issueJob(['docs/LIB/UC01-Card-Renewal.md']),
    { model: fakeModel(), echo: false });
  assert.equal(result.phase, 'intake');
  assert.equal(result.reason, 'gate:rules-malformed');
  assert.equal(statusLines(result.outDir).at(-1).document, 1);
  assertContentFree(read(path.join(result.outDir, 'status.log')));
  assert.match(read(path.join(result.outDir, 'detail.log')), /rule_id does not read as/);
});

test('rows the master holds that the procedure would not write are warnings, not a stop', async () => {
  // A legacy category and requirement type, a page with no anchor, and a heading as the page.
  const config = withExport('exports/legacy.json');
  const result = await runJob(config, issueJob(['docs/LIB/UC01-Card-Renewal.md']),
    { model: fakeModel(), echo: false });
  assert.equal(result.ok, true, JSON.stringify(result));
  const detail = read(path.join(result.outDir, 'detail.log'));
  assert.match(detail, /rule_category "Data Entry" is not a current category/);
  assert.match(detail, /requirement_type "Workflow"/);
});

test('every structural and value check on an export is applied', () => {
  const doc = '- Pages: 3\n\n<a id="page-1"></a>\n# T\n## Intro\n';
  const rule = { rule_id: 'BR-X-001', name: 'BR-X-001 - n', status: 'active', path: 'p',
    requirement_type: 'Business Rule', rule_category: 'Validation', description: 'd',
    source_document: 's', source_page: '1', rule_summary: 'r', risk_level: 'High' };
  const check = (entry, text = doc) => shapeProblems({ doc: 'a.md', prefix: 'BR-X', rules: [rule],
    ...entry }, 'a.md', text, RULE_SHAPE);
  const rowWith = (change) => check({ rules: [{ ...rule, ...change }] });
  assert.deepEqual(check({}), { errors: [], warnings: [] });
  // Structure stops the job.
  assert.match(check({ doc: 'b.md' }).errors.join(), /not the requested path/);
  assert.match(check({ prefix: 'X' }).errors.join(), /prefix/);
  assert.match(check({ rules: [] }).errors.join(), /empty/);
  assert.match(rowWith({ rule_id: 'BR-Y-001' }).errors.join(), /rule_id does not read/);
  assert.match(check({ rules: [rule, rule] }).errors.join(), /appears twice/);
  assert.match(rowWith({ status: 'draft' }).errors.join(), /status/);
  assert.deepEqual(shapeProblems({ exports: [] }, 'a.md', doc, RULE_SHAPE).errors,
    ['the export holds no document']);
  // Values only warn.
  for (const [change, pattern] of [[{ description: ' ' }, /description is missing or blank/],
    [{ requirement_type: 'Workflow' }, /requirement_type/], [{ rule_category: 'Data Entry' }, /rule_category/],
    [{ risk_level: 'Severe' }, /risk_level/], [{ name: 'other' }, /name does not start/],
    [{ source_page: '4' }, /outside the document's 3 pages/], [{ source_page: 'Nowhere' }, /not a heading/]]) {
    const found = rowWith(change);
    assert.deepEqual(found.errors, []);
    assert.match(found.warnings.join(), pattern);
  }
  // A page with no anchor, a range inside the count, and a heading in an anchored document pass.
  for (const page of ['2', '1-3', '1, 3', 'Intro']) assert.deepEqual(rowWith({ source_page: page }).warnings, []);
  // With no page count, any page number passes.
  assert.deepEqual(rowWith({ source_page: '40' }).warnings.length, 1);
  assert.deepEqual(check({ rules: [{ ...rule, source_page: '40' }] }, '# T\n').warnings, []);
});

test('an export older than its document is a warning, and a review day outranks created', async () => {
  const config = withExport('exports/stale.json');
  const result = await runJob(config, issueJob(['docs/OTHER/UC03-Lost-Cards.md']),
    { model: fakeModel(), echo: false });
  assert.equal(result.ok, true, JSON.stringify(result));
  const lines = statusLines(result.outDir);
  assert.ok(lines.some((l) => l.event === 'warn' && l.reason === 'rules-stale' && l.document === 1));
  assertContentFree(read(path.join(result.outDir, 'status.log')));
  assert.match(read(path.join(result.outDir, 'detail.log')), /is stale/);
  // No revision date, or no confirming day, gives no answer.
  const dated = '- Revised: 2026-09-01, from the file\n';
  const entry = (extra, created) => [{ ...extra, rules: [{ created }] }];
  assert.equal(rulesStale(dated, entry({}, '2026-08-01')), true);
  assert.equal(rulesStale(dated, entry({}, '2026-09-01')), false);
  assert.equal(rulesStale(dated, entry({ reviewed: '2026-09-02' }, '2026-08-01')), false);
  assert.equal(rulesStale(dated, entry({ last_reviewed: '2026-08-15' }, '2026-09-05')), true);
  assert.equal(rulesStale('- Revised: not stated\n', entry({}, '2026-08-01')), false);
  assert.equal(rulesStale(dated, entry({}, undefined)), false);
});

test('check reports each input by code without a model call, and fails on a missing one', () => {
  const run = (args) => spawnSync(process.execPath, [path.join(HERE, 'build-pack.mjs'), 'check',
    '--config', path.join(FIXTURES, 'pipeline.json'), ...args], { encoding: 'utf8' });
  const good = run(['--issue', '501', '--change', '7001', '--doc', 'docs/LIB/UC01-Card-Renewal.md']);
  assert.equal(good.status, 0, good.stderr);
  assert.deepEqual(good.stdout.trim().split('\n'), [
    'issue-number  present  issue', 'description  present  found',
    'document-1  present  rules-ok']);

  const bad = run(['--issue', '999', '--doc', 'docs/OTHER/UC09-Unmapped.md',
    '--doc', 'docs/OTHER/UC03-Lost-Cards.md', '--doc', 'docs/none.md']);
  assert.equal(bad.status, 1);
  assert.deepEqual(bad.stdout.trim().split('\n'), [
    'issue-number  present  issue', 'description  missing  no-description',
    'document-1  missing  rules-not-extracted', 'document-2  missing  rules-not-extracted',
    'document-3  missing  document-file']);
  assertContentFree(bad.stdout);

  // The job's own opt-in makes a document with no rules usable.
  const derived = run(['--issue', '501', '--doc', 'docs/OTHER/UC09-Unmapped.md', '--allow-derived-rules']);
  assert.equal(derived.status, 0);
  assert.match(derived.stdout, /document-1  present  rules-derived/);

  // Without --doc the model picks the documents, so their rules are unchecked: exit 3.
  const open = run(['--issue', '501']);
  assert.match(open.stdout, /documents  present  candidates=2/);
  assert.match(open.stdout, /rules  unchecked  name-documents-with-doc/);
  assert.equal(open.status, 3);
  // A missing input outranks an unchecked one.
  assert.equal(run(['--issue', '999']).status, 1);
});

test('the check detail log is kept apart from the job folder a run clears', async () => {
  const config = withExport('exports/legacy.json');
  const job = issueJob(['docs/LIB/UC01-Card-Renewal.md']);
  const { checkJob } = await import('./build-pack.mjs');
  checkJob(config, job);
  const kept = path.join(config.output, 'issue-501-change-7001.check', 'detail.log');
  assert.match(read(kept), /warnings/);
  await runJob(config, job, { model: fakeModel(), echo: false });
  assert.ok(fs.existsSync(kept));
});

test('a resumed job starts at the phase that stopped it and keeps what passed', async (t) => {
  for (const job of [{ issue: '501', change: '7001' }, { suite: 'LIB' }]) {
    await t.test(job.suite ? 'suite' : 'issue', async () => {
      const config = fixtureConfig();
      const pick = { intake: (value) => ({ ...value, documents: ['docs/LIB/UC01-Card-Renewal.md'] }) };
      const failing = fakeModel({ ...pick, phase9_senior: () => {
        throw new ModelError('no-reply', 'model endpoint answered with no JSON');
      } });
      const first = await runJob(config, job, { model: failing, echo: false });
      assert.equal(first.ok, false);
      assert.equal(first.phase, 'phase9-senior');
      assert.equal(first.reason, 'model:no-reply');

      const model = fakeModel(pick);
      const result = await runJob(config, { ...job, resume: true }, { model, echo: false });
      assert.equal(result.ok, true, JSON.stringify(result));
      // The checklist passed before the failure, so only the calls after it run again.
      assert.deepEqual([...new Set(model.calls.map((c) => c.schemaName))],
        ['phase9_senior', 'phase9_confidence', 'phase9_revalidation', 'phase10_notes']);
      const lines = statusLines(result.outDir);
      assert.ok(lines.some((l) => l.event === 'resume' && l.phase === 'phase9-senior'
        && l.after === 'phase9-checklist'));
      assert.deepEqual(lines.filter((l) => l.event === 'pass').map((l) => l.phase).slice(-5),
        ['phase9-senior', 'phase9-confidence', 'phase9-revalidate', 'phase10', 'done']);
      // The pack carries what the first run's phases built.
      const pack = JSON.parse(read(result.packPath));
      assert.ok(pack.testCards.length > 0);
      assert.ok(pack.seniorReview);
      assert.ok(pack.reviewCoverage, 'the checklist\'s coverage rows survive the resume');
      assertContentFree(read(path.join(result.outDir, 'status.log')));
    });
  }
});

test('a job run again without resume starts over from intake', async () => {
  const config = fixtureConfig();
  const pick = { intake: (value) => ({ ...value, documents: ['docs/LIB/UC01-Card-Renewal.md'] }) };
  await runJob(config, { issue: '501' }, { model: fakeModel({ ...pick, phase9_checklist: () => {
    throw new ModelError('no-reply', 'x');
  } }), echo: false });
  const model = fakeModel(pick);
  const result = await runJob(config, { issue: '501' }, { model, echo: false });
  assert.equal(result.ok, true);
  assert.equal(model.calls[0].schemaName.split('_')[0], 'intake');
  assert.ok(!statusLines(result.outDir).some((l) => l.event === 'resume'));
});

test('a reasoning call that fails for any reason is retried once with thinking off', async () => {
  const thinking = [];
  const fetchImpl = async (url, options) => {
    const body = JSON.parse(options.body);
    thinking.push(body.chat_template_kwargs.enable_thinking);
    // A server that gives up at its own time-out ends the reply with no JSON.
    if (body.chat_template_kwargs.enable_thinking) {
      return { ok: true, json: async () => { throw new SyntaxError('Unexpected end of JSON input'); } };
    }
    return { ok: true, json: async () => ({ choices: [{ finish_reason: 'stop',
      message: { content: '{"ok":true}' } }], usage: {} }) };
  };
  const config = fixtureConfig();
  const { ask } = await import('./phases.mjs');
  const ctx = { config, calls: 0, tokens: { prompt: 0, output: 0 }, logs: { status() {}, detail() {} },
    job: { id: 'j' }, model: { ...modelClient({ endpoint: 'http://localhost:1/v1', name: 'm', fetchImpl }),
      countTokens: async () => 10 } };
  const value = await ask(ctx, { phase: 'phase9', step: 's', reasoning: true, inputs: [],
    schema: { type: 'object' }, task: 't' });
  assert.deepEqual(value, { ok: true });
  assert.deepEqual(thinking, [true, false]);
});

test('--resume takes no value and rides on the job', () => {
  assert.deepEqual(jobFrom(parseArgs(['--issue', '501', '--resume', '--change', '7001'])),
    { issue: '501', change: '7001', resume: true });
  assert.deepEqual(jobFrom(parseArgs(['--suite', 'LIB', '--resume'])), { suite: 'LIB', resume: true });
});

/** An exec stub: `active` units answer list-units, every call is recorded, `failing` stops fail. */
function fakeSystemctl(active, failing = []) {
  const calls = [];
  const exec = (command, args) => {
    calls.push([command, ...args]);
    if (args.includes('list-units')) {
      return { status: 0, stdout: active.map((unit) => `${unit} loaded active running Test\n`).join('') };
    }
    const unit = args.at(-1);
    return { status: failing.includes(`${args.at(-2)} ${unit}`) ? 1 : 0, stdout: '' };
  };
  return { calls, exec, verbs: () => calls.filter((c) => !c.includes('list-units')) };
}

/** A fake /proc with one process per [pid, comm, cgroup] row. */
function fakeProc(rows) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'build-pack-proc-'));
  for (const [pid, comm, cgroup] of rows) {
    fs.mkdirSync(path.join(root, String(pid)));
    fs.writeFileSync(path.join(root, String(pid), 'comm'), `${comm}\n`);
    fs.writeFileSync(path.join(root, String(pid), 'cgroup'), `0::${cgroup}\n`);
  }
  return root;
}

const pauseConfig = (pause = {}) => fixtureConfig({ pause: { units: ['gpu-*.service'], ...pause } });
const okRun = async () => ({ ok: true, ms: 1 });
const quiet = (sys, deps = {}) => (cfg) => createPauser(cfg, { exec: sys.exec, log: () => {}, ...deps });

test('idle units are stopped before the job and started after it', async () => {
  const config = pauseConfig();
  addJob(config, { issue: '1' });
  const sys = fakeSystemctl(['gpu-a.service', 'gpu-b.service']);
  const seen = [];
  const run = async () => { seen.push(sys.verbs().length); return { ok: true, ms: 1 }; };
  await drainQueue(config, { run, pause: quiet(sys) });
  assert.deepEqual(seen, [2]);
  assert.deepEqual(sys.verbs().map((c) => c.slice(-2).join(' ')),
    ['stop gpu-a.service', 'stop gpu-b.service', 'start gpu-a.service', 'start gpu-b.service']);
  // The system scope stops through sudo with the full path and never asks for a password.
  assert.deepEqual(sys.verbs()[0], ['sudo', '-n', '/usr/bin/systemctl', 'stop', 'gpu-a.service']);
  assert.ok(!fs.existsSync(pausedPath(config)));
});

test('the user scope stops and starts through systemctl --user', async () => {
  const config = pauseConfig({ scope: 'user' });
  const sys = fakeSystemctl(['gpu-a.service']);
  const pauser = createPauser(config, { exec: sys.exec, log: () => {} });
  await pauser.pause();
  await pauser.resume();
  assert.deepEqual(sys.calls.map((c) => c.join(' ')), [
    'systemctl --user list-units --plain --no-legend --state=active gpu-*.service',
    'systemctl --user stop gpu-a.service', 'systemctl --user start gpu-a.service']);
});

test('a busy unit is stopped only after its worker exits', async () => {
  const config = pauseConfig({ busyProcess: 'worker', pollSeconds: 5 });
  const proc = fakeProc([[100, 'worker', '/system.slice/gpu-a.service'],
    [101, 'worker', '/system.slice/other-gpu-a.service']]);
  const sys = fakeSystemctl(['gpu-a.service', 'gpu-b.service']);
  const sleeps = [];
  const sleep = async (ms) => {
    sleeps.push(ms);
    // gpu-b was idle and is already stopped; gpu-a's worker now finishes.
    assert.deepEqual(sys.verbs().map((c) => c.at(-1)), ['gpu-b.service']);
    fs.rmSync(path.join(proc, '100'), { recursive: true });
  };
  const pauser = createPauser(config, { exec: sys.exec, log: () => {}, procRoot: proc, sleep });
  await pauser.pause();
  assert.deepEqual(sleeps, [5000]);
  assert.deepEqual(sys.verbs().map((c) => c.slice(-2).join(' ')),
    ['stop gpu-b.service', 'stop gpu-a.service']);
  await pauser.resume();
  assert.equal(sys.verbs().filter((c) => c.includes('start')).length, 2);
});

test('with no pause config nothing is run', async () => {
  const config = fixtureConfig();
  addJob(config, { issue: '1' });
  const sys = fakeSystemctl(['gpu-a.service']);
  await drainQueue(config, { run: okRun, pause: quiet(sys) });
  assert.deepEqual(sys.calls, []);
});

test('a failed stop is logged, the job still runs, and that unit is never started', async () => {
  const config = pauseConfig();
  addJob(config, { issue: '1' });
  const sys = fakeSystemctl(['gpu-a.service', 'gpu-b.service'], ['stop gpu-a.service']);
  const lines = [];
  let ran = 0;
  const done = await drainQueue(config, { run: async () => { ran += 1; return { ok: true, ms: 1 }; },
    pause: quiet(sys, { log: (l) => lines.push(l) }) });
  assert.equal(ran, 1);
  assert.equal(done[0].status, 'passed');
  assert.ok(lines.includes('pause: stop failed gpu-a.service'));
  assert.deepEqual(sys.verbs().filter((c) => c.includes('start')).map((c) => c.at(-1)), ['gpu-b.service']);
});

test('units that were not active are never started', async () => {
  const config = pauseConfig();
  addJob(config, { issue: '1' });
  const sys = fakeSystemctl([]);
  await drainQueue(config, { run: okRun, pause: quiet(sys) });
  assert.deepEqual(sys.verbs(), []);
});

test('an empty queue stops nothing', async () => {
  const config = pauseConfig();
  const sys = fakeSystemctl(['gpu-a.service']);
  await drainQueue(config, { run: okRun, pause: quiet(sys) });
  assert.deepEqual(sys.calls, []);
});

test('units a dead run left stopped are started by the next run, even with no job', async () => {
  const config = pauseConfig();
  fs.writeFileSync(pausedPath(config), JSON.stringify(['gpu-a.service']));
  const sys = fakeSystemctl(['gpu-b.service']);
  await drainQueue(config, { run: okRun, pause: quiet(sys) });
  assert.deepEqual(sys.calls.map((c) => c.slice(-2).join(' ')), ['start gpu-a.service']);
  assert.ok(!fs.existsSync(pausedPath(config)));
});

test('a second resume does nothing, and each stop is recorded as it happens', async () => {
  const config = pauseConfig();
  const sys = fakeSystemctl(['gpu-a.service']);
  const pauser = createPauser(config, { exec: sys.exec, log: () => {} });
  await pauser.pause();
  assert.deepEqual(JSON.parse(fs.readFileSync(pausedPath(config), 'utf8')), ['gpu-a.service']);
  await pauser.resume();
  const calls = sys.calls.length;
  await pauser.resume();
  assert.equal(sys.calls.length, calls);
});

test('pause config is validated', () => {
  assert.throws(() => pauseConfig({ scope: 'machine' }), /pause.scope/);
  assert.throws(() => pauseConfig({ units: 'gpu.service' }), /pause.units/);
  assert.deepEqual(fixtureConfig().pause, { units: [], scope: 'system', busyProcess: null, pollSeconds: 5 });
});

/** A config whose queue has the given sources, over the fixtures. */
function sourcedConfig(sources, report = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'build-pack-src-'));
  return fixtureConfig({ queue: { file: path.join(dir, 'queue.json'), sources }, report });
}

test('a job line is a bare number pair, a suite, or the full command-line form', () => {
  assert.deepEqual(jobFromLine('9415'), { issue: '9415' });
  assert.deepEqual(jobFromLine('  9415 7001  '), { issue: '9415', change: '7001' });
  assert.deepEqual(jobFromLine('suite LIB'), { suite: 'LIB' });
  assert.deepEqual(jobFromLine('--issue 9415 --change 7001 --doc docs/LIB/a.md'),
    { issue: '9415', change: '7001', docs: ['docs/LIB/a.md'] });
  assert.equal(jobFromLine('# a note'), null);
  assert.equal(jobFromLine('   '), null);
  assert.throws(() => jobFromLine('9415 7001 extra'));
  assert.throws(() => jobFromLine('hello world'));
});

test('the queue fills itself from a folder of lists, and never queues a known job twice', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'build-pack-in-'));
  fs.writeFileSync(path.join(dir, 'build-12.txt'), '# build 12\n9415 7001\n501\nnot a job\n\nsuite LIB\n');
  fs.writeFileSync(path.join(dir, 'more.txt'), '501\n777\n');
  fs.writeFileSync(path.join(dir, '.hidden'), '999\n');
  const config = sourcedConfig([{ type: 'folder', path: dir }]);
  const first = fillQueue(config);
  assert.deepEqual(first.added, ['issue-9415-change-7001', 'issue-501', 'suite-LIB', 'issue-777']);
  assert.equal(first.invalid, 1);
  assert.equal(first.known, 1);
  assert.deepEqual(readQueue(config).jobs.map((row) => row.status), Array(4).fill('queued'));
  // A second pass adds nothing, whatever state the jobs are in now.
  const queue = readQueue(config);
  queue.jobs[1].status = 'passed';
  queue.jobs[2].status = 'failed';
  fs.writeFileSync(config.at(config.queue.file), JSON.stringify(queue));
  assert.deepEqual(fillQueue(config).added, []);
  // A job taken out by hand stays out while the folder still lists it.
  assert.equal(removeJob(config, 'issue-777').removed, true);
  assert.deepEqual(fillQueue(config).added, []);
  assert.equal(removeJob(config, 'issue-501').removed, false);
  assert.equal(summaryLines(readQueue(config)).some((line) => line.startsWith('issue-777')), false);
  // `queue add` still brings a removed job back.
  assert.equal(addJob(config, { issue: '777' }).added, true);
});

test('the queue fills from record file names and from a command, and a bad source is counted', () => {
  const config = sourcedConfig([
    { type: 'records', glob: 'issues/ISSUE_*.md' },
    { type: 'records', glob: 'issues/*.md', pattern: '^ISSUE_(\\d+)_(renewal)' },
    { type: 'command', command: ['node', '-e', 'console.log("600 6001"); console.log("suite LIB")'] },
    { type: 'command', command: ['node', '-e', 'process.exit(3)'] },
    { type: 'folder', path: path.join(os.tmpdir(), 'build-pack-no-such-folder') },
  ]);
  const result = fillQueue(config);
  // The second pattern's second group is read as a change number.
  assert.deepEqual(result.added, ['issue-501', 'issue-501-change-renewal', 'issue-600-change-6001',
    'suite-LIB']);
  assert.deepEqual(result.errors, ['command:source-command-failed', 'folder:source-missing']);
  assert.equal(result.known, 0);
});

test('a queue source is checked when the config loads', () => {
  const bad = (sources) => () => sourcedConfig(sources);
  assert.throws(bad('folder'), /queue.sources must be a list/);
  assert.throws(bad([{ type: 'folder' }]), /queue.sources takes/);
  assert.throws(bad([{ type: 'ftp', path: 'x' }]), /queue.sources takes/);
  assert.throws(bad([{ type: 'command', command: [] }]), /queue.sources takes/);
  assert.deepEqual(fixtureConfig().queue.sources, []);
});

test('a nightly run fills the queue once it holds it, and a run outside the window does not', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'build-pack-in-'));
  fs.writeFileSync(path.join(dir, 'list.txt'), '9415\n');
  const config = sourcedConfig([{ type: 'folder', path: dir }]);
  const ran = [];
  const run = async (_config, job) => { ran.push(job.id); return { ok: true, ms: 1 }; };
  const refill = (cfg) => fillQueue(cfg);
  await drainQueue(config, { cutoff: '07:00', start: '22:00', run, refill,
    clock: () => new Date('2026-10-28T08:00:00') });
  assert.deepEqual(readQueue(config).jobs, []);
  await drainQueue(config, { cutoff: '07:00', start: '22:00', run, refill,
    clock: () => new Date('2026-10-28T22:30:00') });
  assert.deepEqual(ran, ['issue-9415']);
});

test('a failed job retries once on the next night, resumed, and is dropped after the second failure', async () => {
  const config = fixtureConfig();
  addJob(config, { issue: '501', now: true });
  addJob(config, { issue: '777' });
  const ran = [];
  const outcomes = { 'issue-501': { ok: false, phase: 'phase3', reason: 'gate:unclassified-rule', ms: 60000 } };
  const run = async (_config, job) => {
    ran.push({ id: job.id, resume: job.resume === true, keys: Object.keys(job).sort() });
    return outcomes[job.id] ?? { ok: true, ms: 1, workbook: '/out/w.xlsx' };
  };
  const night = (day) => () => new Date(`2026-10-${day}T22:00:00`);
  await drainQueue(config, { cutoff: '07:00', run, clock: night(27) });
  // Night one: the failure is kept, 777 still runs, and 501 waits for the next night.
  assert.deepEqual(ran.map((r) => r.id), ['issue-501', 'issue-777']);
  let [row] = readQueue(config).jobs;
  assert.equal(row.status, 'queued');
  assert.equal(row.resume, true);
  assert.equal(row.now, undefined);
  assert.deepEqual(row.failures.map((f) => [f.phase, f.reason]), [['phase3', 'gate:unclassified-rule']]);
  assert.ok(new Date(row.notBefore) > night(27)());
  assert.match(summaryLines(readQueue(config))[0], /issue-501\s+queued\s+retry after stopping at phase3/);
  // The same night, a second run does not take it again.
  await drainQueue(config, { cutoff: '07:00', run, clock: night(27) });
  assert.equal(ran.length, 2);
  // The next night it runs again, resumed, with none of the queue's own fields on the job.
  outcomes['issue-501'] = { ok: false, phase: 'phase5', reason: 'model:no-reply', ms: 60000 };
  await drainQueue(config, { cutoff: '07:00', run, clock: night(28) });
  assert.equal(ran.length, 3);
  assert.equal(ran[2].resume, true);
  assert.deepEqual(ran[2].keys, ['id', 'issue', 'resume']);
  [row] = readQueue(config).jobs;
  assert.equal(row.status, 'failed');
  assert.deepEqual(row.failures.map((f) => f.reason), ['gate:unclassified-rule', 'model:no-reply']);
  assert.equal(row.notBefore, undefined);
  assert.match(summaryLines(readQueue(config))[0], /stopped at phase5 \(model:no-reply\), dropped after failing 2 times/);
  // A third night takes nothing: the job is out of the queue.
  await drainQueue(config, { cutoff: '07:00', run, clock: night(29) });
  assert.equal(ran.length, 3);
});

test('a job that fails once and then passes is a pass with its failure on record', async () => {
  const config = fixtureConfig();
  addJob(config, { issue: '501' });
  let attempt = 0;
  const run = async () => {
    attempt += 1;
    return attempt === 1 ? { ok: false, phase: 'phase2', reason: 'error', ms: 1 }
      : { ok: true, ms: 2, workbook: '/out/w.xlsx' };
  };
  await drainQueue(config, { cutoff: '07:00', run, clock: () => new Date('2026-10-27T22:00:00') });
  await drainQueue(config, { cutoff: '07:00', run, clock: () => new Date('2026-10-28T22:00:00') });
  const [row] = readQueue(config).jobs;
  assert.equal(row.status, 'passed');
  assert.equal(row.failures.length, 1);
});

test('queue remove takes a waiting job out and leaves a running one alone', () => {
  const config = fixtureConfig();
  addJob(config, { issue: '501' });
  addJob(config, { issue: '777' });
  const queue = readQueue(config);
  queue.jobs[1].status = 'running';
  fs.writeFileSync(config.at(config.queue.file), JSON.stringify(queue));
  assert.deepEqual(removeJob(config, 'issue-501'), { id: 'issue-501', removed: true });
  assert.deepEqual(removeJob(config, 'issue-777'), { id: 'issue-777', removed: false, running: true });
  assert.deepEqual(removeJob(config, 'issue-1'), { id: 'issue-1', removed: false, running: false });
  assert.deepEqual(readQueue(config).jobs.map((row) => row.status), ['removed', 'running']);
});

const NOW = new Date('2026-10-28T07:30:00');
const hoursAgo = (h) => new Date(NOW.getTime() - h * 3600000).toISOString();

/** A passed row with its status.log, as a run leaves them. */
function passedJob(config, id, { hours, confidence = 'High', pass = 12, limited = 0, ms = 3600000 }) {
  const outDir = path.join(config.output, id);
  fs.mkdirSync(outDir, { recursive: true });
  const line = (fields) => JSON.stringify({ at: hoursAgo(hours), job: id, ...fields });
  fs.writeFileSync(path.join(outDir, 'status.log'), [
    line({ phase: 'phase9-confidence', event: 'pass', confidence }),
    line({ phase: 'done', event: 'pass', sheetsPass: pass, sheetsLimited: limited, calls: 40 }),
  ].join('\n'));
  return { id, status: 'passed', finished: hoursAgo(hours), ms, workbook: `${outDir}/${id}.xlsx`, phase: 'done' };
}

function reportQueue(config) {
  const failLog = (id, fields) => {
    const outDir = path.join(config.output, id);
    fs.mkdirSync(outDir, { recursive: true });
    fs.writeFileSync(path.join(outDir, 'status.log'),
      `${JSON.stringify({ at: hoursAgo(2), job: id, phase: 'phase3', event: 'fail', ...fields })}\n`);
  };
  failLog('issue-300', { reason: 'gate:unclassified-rule', sheets: 2 });
  failLog('issue-400', { reason: 'model:no-reply' });
  failLog('issue-500', { reason: 'error' });
  return { jobs: [
    passedJob(config, 'issue-100', { hours: 5, confidence: 'Low' }),
    passedJob(config, 'issue-101', { hours: 6, limited: 2 }),
    passedJob(config, 'issue-102', { hours: 7 }),
    passedJob(config, 'issue-103', { hours: 8, confidence: 'Medium' }),
    passedJob(config, 'issue-104', { hours: 9 }),
    passedJob(config, 'issue-105', { hours: 24 * 3 }),
    // Failed once and waiting for tonight.
    { id: 'issue-400', status: 'queued', resume: true, notBefore: hoursAgo(1),
      failures: [{ at: hoursAgo(2), phase: 'phase5', reason: 'model:no-reply', ms: 120000 }] },
    // Failed twice and dropped.
    { id: 'issue-300', status: 'failed', phase: 'phase3', reason: 'gate:unclassified-rule', ms: 60000,
      finished: hoursAgo(2), failures: [
        { at: hoursAgo(26), phase: 'phase3', reason: 'gate:low-coverage', ms: 1 },
        { at: hoursAgo(2), phase: 'phase3', reason: 'gate:unclassified-rule', ms: 60000 }] },
    // Waiting, never tried.
    { id: 'issue-600', status: 'queued' },
    { id: 'issue-700', status: 'removed', finished: hoursAgo(3) },
    { id: 'issue-800', status: 'running' },
  ] };
}

test('the daily report lists each job, the queue depth and the failing jobs', () => {
  const config = fixtureConfig();
  const data = reportData(config, reportQueue(config), { period: 'day', now: NOW, random: seededRandom(1) });
  // Oldest first.
  assert.deepEqual(data.jobs.map((j) => [j.id, j.state]), [
    ['issue-104', 'PASS'], ['issue-103', 'PASS'], ['issue-102', 'PASS'], ['issue-101', 'PASS'],
    ['issue-100', 'PASS'], ['issue-400', 'RETRY'], ['issue-300', 'DROPPED']]);
  assert.deepEqual(data.counts, { pass: 5, fail: 0, retry: 1, dropped: 1 });
  assert.deepEqual(data.queue, { depth: 2, retrying: 1, running: 1 });
  assert.deepEqual(data.failing.map((j) => j.id), ['issue-400', 'issue-300']);
  const text = renderReport(data);
  assert.match(text, /^# Test pack report, daily, 2026-10-28/);
  assert.match(text, /\| issue-100 \| PASS \| - \| 12 \/ 0 \/ 0 \| Low \| 60 min \|/);
  assert.match(text, /\| issue-101 \| PASS WITH LIMITATIONS \| - \| 12 \/ 2 \/ 0 \| High \| 60 min \|/);
  assert.match(text, /\| issue-300 \| DROPPED \| phase3 gate:unclassified-rule \| - \/ - \/ 2 \| - \| 1 min \|/);
  assert.match(text, /\| issue-400 \| RETRY \| phase5 model:no-reply \| - \/ - \/ - \| - \| 2 min \|/);
  assert.match(text, /issue-300: failed 2 times, last at phase3 \(gate:low-coverage, then gate:unclassified-rule\)\. Dropped from the queue; it needs a person\./);
  assert.match(text, /issue-400: failed at phase5 \(model:no-reply\)\. Retries on its next run\./);
  assert.match(text, /Queue depth: 2 waiting \(1 of them retrying\), 1 running/);
  // The job from three days ago and the removed row are not in a daily report.
  assert.ok(!text.includes('issue-105'));
  assert.ok(!text.includes('issue-700'));
});

test('the weekly rollup covers seven days and counts them by day', () => {
  const config = fixtureConfig();
  const data = reportData(config, reportQueue(config), { period: 'week', now: NOW, random: seededRandom(1) });
  assert.equal(data.jobs.length, 8);
  assert.deepEqual(data.counts, { pass: 6, fail: 0, retry: 1, dropped: 1 });
  const text = renderReport(data);
  assert.match(text, /weekly rollup, 2026-10-28/);
  assert.match(text, /\| 2026-10-25 \| 1 \| 0 \|/);
});

test('spot checks put low confidence first, then PASS WITH LIMITATIONS, then a seeded sample', () => {
  const config = fixtureConfig();
  const queue = reportQueue(config);
  const pick = (seed) => reportData(config, queue,
    { period: 'day', now: NOW, random: seededRandom(seed) }).spot.map((s) => [s.id, s.why]);
  const first = pick(7);
  assert.deepEqual(first.slice(0, 2), [['issue-100', 'low-confidence'], ['issue-101', 'pass-with-limitations']]);
  assert.equal(first.length, 4);
  assert.ok(first.slice(2).every(([, why]) => why === 'random-sample'));
  assert.ok(first.slice(2).every(([id]) => ['issue-102', 'issue-103', 'issue-104'].includes(id)));
  // The same seed gives the same sample; the sample never repeats a priority pack.
  assert.deepEqual(pick(7), first);
  assert.equal(new Set(first.map(([id]) => id)).size, first.length);
  const seen = new Set();
  for (let seed = 0; seed < 30; seed += 1) pick(seed).slice(2).forEach(([id]) => seen.add(id));
  assert.ok(seen.size > 2);
  // The priority list is capped, and the sample size is a setting.
  const passed = ['a', 'b', 'c', 'd'].map((id) => ({ id, confidence: 'Low', limited: false, workbook: null }));
  assert.equal(spotChecks(passed, { maxPriority: 2, sample: 1 }, seededRandom(1)).length, 3);
  assert.equal(spotChecks(passed, { maxPriority: 4, sample: 5 }, seededRandom(1)).length, 4);
  assert.deepEqual(spotChecks([], { maxPriority: 4, sample: 5 }, seededRandom(1)), []);
});

test('the report holds codes and counts only, even when a log line carries text', () => {
  const config = fixtureConfig();
  const queue = reportQueue(config);
  const outDir = path.join(config.output, 'issue-101');
  fs.appendFileSync(path.join(outDir, 'status.log'), `\n${JSON.stringify({ at: hoursAgo(5.5), job: 'issue-101',
    phase: 'phase9-confidence', event: 'pass', confidence: 'Patron renewal text' })}\n`);
  queue.jobs[1].workbook = '/out/Patron renewal.xlsx';
  const text = renderReport(reportData(config, queue, { now: NOW, random: seededRandom(1) }));
  assertContentFree(text);
  assert.ok(text.includes('| other |'));
});

test('the report command writes the daily file, and the weekly rollup on the set weekday', () => {
  const config = fixtureConfig();
  const queue = reportQueue(config);
  const tuesday = new Date('2026-10-27T07:30:00');
  const monday = new Date('2026-10-26T07:30:00');
  assert.equal(monday.getDay(), 1);
  const names = (written) => written.map((w) => path.basename(w.file));
  assert.deepEqual(names(writeReports(config, queue, { now: tuesday })), ['daily-2026-10-27.md']);
  assert.deepEqual(names(writeReports(config, queue, { now: monday })),
    ['daily-2026-10-26.md', 'weekly-2026-10-26.md']);
  assert.deepEqual(names(writeReports(config, queue, { now: tuesday, period: 'week' })), ['weekly-2026-10-27.md']);
  assert.ok(fs.existsSync(path.join(config.output, 'reports', 'weekly-2026-10-27.md')));
  assert.throws(() => writeReports(config, queue, { period: 'month' }), /--period/);
  const other = fixtureConfig({ report: { weeklyDay: 2, dir: path.join(os.tmpdir(), 'build-pack-reports') } });
  assert.deepEqual(names(writeReports(other, queue, { now: tuesday })),
    ['daily-2026-10-27.md', 'weekly-2026-10-27.md']);
  assert.throws(() => fixtureConfig({ report: { weeklyDay: 9 } }), /report.weeklyDay/);
  assert.throws(() => fixtureConfig({ report: { sample: -1 } }), /report.sample/);
});

test('the command line fills the queue and writes the report', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'build-pack-in-'));
  fs.writeFileSync(path.join(dir, 'list.txt'), '9415\n');
  const config = sourcedConfig([{ type: 'folder', path: dir }]);
  const cli = (...args) => spawnSync('node', [path.join(HERE, 'build-pack.mjs'), ...args,
    '--config', config.file], { encoding: 'utf8' });
  const fillRun = cli('queue', 'fill');
  assert.equal(fillRun.status, 0);
  assert.match(fillRun.stdout, /queued issue-9415\nfilled 1 job\(s\), 0 already known, 0 unreadable line\(s\)/);
  assert.equal(cli('queue', 'remove', '--job', 'issue-9415').status, 0);
  assert.equal(cli('queue', 'remove', '--job', 'issue-9415').status, 1);
  const reportRun = cli('report', '--period', 'day', '--seed', '3');
  assert.equal(reportRun.status, 0);
  assert.match(reportRun.stdout, /wrote day report .*daily-\d{4}-\d\d-\d\d\.md\npassed=0 retrying=0 dropped=0 queued=0/);
});

test('a failure during the day is taken by tonight, and one at night waits for the next night', async () => {
  const config = fixtureConfig();
  addJob(config, { issue: '501', now: true });
  const ran = [];
  const run = async (_config, job) => {
    ran.push(job.id);
    return { ok: false, phase: 'phase4', reason: 'model:http', ms: 1 };
  };
  const at = (text) => () => new Date(text);
  // A start request at 10:00 fails; the run does not take the job again, and it carries no wait.
  await drainQueue(config, { only: 'issue-501', nowOnly: true, run, clock: at('2026-10-28T10:00:00') });
  assert.deepEqual(ran, ['issue-501']);
  let [row] = readQueue(config).jobs;
  assert.equal(row.status, 'queued');
  assert.equal(row.notBefore, undefined);
  // Tonight's run at 22:00 takes it, and its second failure drops it.
  await drainQueue(config, { cutoff: '07:00', start: '22:00', run, clock: at('2026-10-28T22:00:00') });
  assert.equal(ran.length, 2);
  [row] = readQueue(config).jobs;
  assert.equal(row.status, 'failed');
  // A failure at 23:00 waits until after that night's cutoff, then the next run takes it.
  addJob(config, { issue: '777' });
  await drainQueue(config, { cutoff: '07:00', start: '22:00', run, clock: at('2026-10-28T23:00:00') });
  const retry = readQueue(config).jobs.find((r) => r.id === 'issue-777');
  assert.equal(retry.status, 'queued');
  assert.equal(new Date(retry.notBefore).getTime(), new Date('2026-10-29T07:00:00').getTime());
  await drainQueue(config, { cutoff: '07:00', start: '22:00', run, clock: at('2026-10-29T22:00:00') });
  assert.equal(ran.length, 4);
});

test('an explicit start request takes a job that is waiting for the next night', async () => {
  const config = fixtureConfig();
  addJob(config, { issue: '501' });
  addJob(config, { issue: '777' });
  const queue = readQueue(config);
  for (const row of queue.jobs) {
    Object.assign(row, { resume: true, notBefore: '2026-10-29T07:00:00.000Z',
      failures: [{ at: '2026-10-28T23:00:00.000Z', phase: 'phase4', reason: 'model:http', ms: 1 }] });
  }
  fs.writeFileSync(config.at(config.queue.file), JSON.stringify(queue));
  const ran = [];
  const run = async (_config, job) => { ran.push(job.id); return { ok: true, ms: 1 }; };
  const clock = () => new Date('2026-10-28T10:00:00');
  // Nothing marked now: the waiting rows stay waiting.
  await drainQueue(config, { nowOnly: true, run, clock });
  assert.deepEqual(ran, []);
  addJob(config, { issue: '501', now: true });
  addJob(config, { issue: '777', now: true });
  await drainQueue(config, { only: 'issue-501', nowOnly: true, run, clock });
  // The named job runs first and the other start-now row follows it.
  assert.deepEqual(ran, ['issue-501', 'issue-777']);
});

test('the default record pattern reads a change only when it starts with a digit', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'build-pack-rec-'));
  for (const name of ['SIR-9415-credit-limit.md', 'SIR-9416-Create-account.md', 'SIR-9417-crash-on-save.md',
    'SIR-9418-change-7001.md', 'ISSUE_9419_CR7002_renewal.md', 'SIR-9421-changes-to-fees.md',
    'SIR-9422-CR-CHG7001.md', 'SIR-9423-CR-7001,7002.md', 'SIR-9424-CR-7001(1).md',
    'SIR-9425-change-password.md', 'notes.md']) {
    fs.writeFileSync(path.join(dir, name), 'x');
  }
  const config = fixtureConfig({ repoRoot: dir, queue: { file: path.join(dir, 'queue.json'),
    sources: [{ type: 'records', glob: '*.md' }] } });
  const result = fillQueue(config);
  assert.deepEqual([...result.added].sort(), ['issue-9415', 'issue-9416', 'issue-9417',
    'issue-9418-change-7001', 'issue-9419-change-7002', 'issue-9421']);
  // A name the pattern does not read, or one with a change word and no valid change number, is
  // counted and not queued as the issue alone.
  assert.equal(result.invalid, 5);
});

test('queue remove and queue fill by hand refuse while a run holds the queue', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'build-pack-in-'));
  fs.writeFileSync(path.join(dir, 'list.txt'), '9415\n');
  const config = sourcedConfig([{ type: 'folder', path: dir }]);
  addJob(config, { issue: '777' });
  const cli = (...args) => spawnSync('node', [path.join(HERE, 'build-pack.mjs'), 'queue', ...args,
    '--config', config.file], { encoding: 'utf8' });
  const lock = `${config.at(config.queue.file)}.lock`;
  fs.writeFileSync(lock, String(process.pid));
  const fillRun = cli('fill');
  assert.equal(fillRun.status, 1);
  assert.match(fillRun.stderr, /the queue is running/);
  assert.equal(cli('remove', '--job', 'issue-777').status, 1);
  assert.deepEqual(readQueue(config).jobs.map((row) => row.status), ['queued']);
  fs.rmSync(lock);
  assert.equal(cli('fill').status, 0);
  assert.equal(cli('remove', '--job', 'issue-777').status, 0);
  assert.equal(fs.existsSync(lock), false);
});

test('a report seed must be a whole number', () => {
  assert.throws(() => fixtureConfig({ report: { seed: 'abc' } }), /report.seed/);
  assert.doesNotThrow(() => fixtureConfig({ report: { seed: 7 } }));
  assert.throws(() => seededRandom('x'), /--seed/);
});

test('a job added while the units are being stopped is kept', async () => {
  const config = fixtureConfig();
  addJob(config, { issue: '501' });
  const pause = () => ({
    pause: async () => { addJob(config, { issue: '777' }); },
    resume: async () => {},
  });
  const run = async () => ({ ok: true, ms: 1 });
  await drainQueue(config, { cutoff: '07:00', run, pause, clock: () => new Date('2026-10-28T10:00:00') });
  assert.deepEqual(readQueue(config).jobs.map((row) => [row.id, row.status]),
    [['issue-501', 'passed'], ['issue-777', 'passed']]);
});

test('a start-only run leaves an interrupted row for the night', async () => {
  const config = fixtureConfig();
  addJob(config, { issue: '501', now: true });
  addJob(config, { issue: '777', now: true });
  const queue = readQueue(config);
  queue.jobs[0].status = 'running';
  fs.writeFileSync(config.at(config.queue.file), JSON.stringify(queue));
  const ran = [];
  const run = async (_config, job) => { ran.push(job.id); return { ok: true, ms: 1 }; };
  await drainQueue(config, { only: 'issue-777', nowOnly: true, run, clock: () => new Date('2026-10-28T10:00:00') });
  assert.deepEqual(ran, ['issue-777']);
  const [interrupted] = readQueue(config).jobs;
  assert.equal(interrupted.status, 'queued');
  assert.equal(interrupted.now, undefined);
});

test('a change token with no separator before it is still read, or counted when its number is bad', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'build-pack-rec-'));
  for (const name of ['SIR-9415CR7001.md', 'SIR-9416.CR7002.md', 'SIR-9417Create-account.md',
    'SIR-9418credit-limit.md', 'SIR-9419crash-on-save.md', 'SIR-9420changes-to-fees.md',
    'SIR-9421CR-CHG7001.md', 'SIR-9422.change.md']) {
    fs.writeFileSync(path.join(dir, name), 'x');
  }
  const config = fixtureConfig({ repoRoot: dir, queue: { file: path.join(dir, 'queue.json'),
    sources: [{ type: 'records', glob: '*.md' }] } });
  const result = fillQueue(config);
  assert.deepEqual([...result.added].sort(), ['issue-9415-change-7001', 'issue-9416-change-7002',
    'issue-9417', 'issue-9418', 'issue-9419', 'issue-9420']);
  assert.equal(result.invalid, 2);
});
