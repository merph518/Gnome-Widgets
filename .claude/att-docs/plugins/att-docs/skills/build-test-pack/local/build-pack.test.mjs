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
import { rulesStale, shapeProblems, struckSpans, uncitedStruck } from './rules.mjs';
import { createPauser, pausedPath } from './pause.mjs';
import { ModelError, localEndpoint, modelClient } from './model.mjs';
import { almDescriptions, batches, documentInputs, dropUnfoundedAssumptions, expectedProblems, phase5,
  resultsAgree, setsOf, splitText } from './phases.mjs';
import { runJob } from './run.mjs';
import { renderReport, reportData, seededRandom, spotChecks, writeReports } from './report.mjs';
import { statusFields } from './status.mjs';
import { readPack } from './pack.mjs';

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
      // The checklist finds nothing unless a test plants a finding, so no fix round runs.
      if (request.schemaName.startsWith('phase9_checklist')) value.issues = [];
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
    'phase7', 'phase8', 'phase9-checklist', 'phase9-confidence', 'phase9-senior',
    'phase9-revalidate', 'phase10', 'done']);
  // Reasoning is on for the judgment phases and off for extraction.
  const thinking = new Map(model.calls.map((c) => [c.schemaName.split('_')[0], c.reasoning]));
  // Phase 4 ends on its risk rating, an extraction; its impact analysis thinks.
  assert.deepEqual(Object.fromEntries(thinking), { intake: false, phase1: true, phase3: true,
    phase4: false, phase5: true, phase6: false, phase7: false, phase9: true, phase10: false });
  assert.equal(model.calls.find((c) => c.schemaName.startsWith('phase4_impact')).reasoning, true);
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
// The fixture's retired rule is one the change does not concern, so no card is owed for it.
const NOT_REMOVAL = { phase3: (value) => {
  value.rules['BR-LIB.UC01-006'] &&= { ...value.rules['BR-LIB.UC01-006'], impact: 'Not Impacted' };
  return value;
} };
const lib = (extra = {}, overrides = {}) => ({ model: fakeModel({ ...INTAKE, ...NOT_REMOVAL, ...extra }),
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
    context: 6000, maxOutput: 500, reasoningOutput: 500 } });
  const model = fakeModel();
  const result = await runJob(config, { issue: '501', change: '7001' }, { model, echo: false });
  assert.equal(result.ok, false);
  // Intake fits; the documents do not, even as digests, and nothing is cut to make them.
  assert.equal(result.reason, 'gate:documents-too-big');
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
      countTokens: async () => 10, contextWindow: async () => null } };
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

const STRUCK_DOC = 'docs/OTHER/UC05-Struck-Warning.md';

test('struck-through text no retired rule cites is a warning and a limitation, not a stop', async () => {
  const config = withExport('master-struck.json');
  const result = await runJob(config, issueJob([STRUCK_DOC]), { model: fakeModel(), echo: false });
  assert.equal(result.ok, true, JSON.stringify(result));
  const lines = statusLines(result.outDir);
  const warn = lines.filter((l) => l.event === 'warn' && l.reason === 'retired-rule-missing');
  assert.deepEqual(warn.map((l) => [l.phase, l.document]), [['phase2', 1]]);
  assertContentFree(read(path.join(result.outDir, 'status.log')));
  assert.match(read(path.join(result.outDir, 'detail.log')), /struck-through text[^]*page 2/);
  const pack = JSON.parse(read(result.packPath));
  assert.match(pack.limitations['Job Intake'], /Struck-through text in UC05 Struck Warning has no rule citing it/);
});

test('a retired rule that cites the page of the struck-through text leaves no warning', async () => {
  const config = withExport('master-struck-retired.json');
  const result = await runJob(config, issueJob([STRUCK_DOC]), { model: fakeModel(), echo: false });
  assert.equal(result.ok, true, JSON.stringify(result));
  assert.ok(!statusLines(result.outDir).some((l) => l.reason === 'retired-rule-missing'));
  assert.ok(!JSON.parse(read(result.packPath)).limitations?.['Job Intake']);
});

const shape = (spans) => spans.map(({ page, heading }) => ({ page, heading }));

test('a struck removal is cited by a retired rule at its page, range or heading', () => {
  const paged = '<a id="page-1"></a>\n\n- ~~Old option one~~\n\n<a id="page-3"></a>\n\n- ~~Old option two~~\n';
  const rule = (extra) => ({ status: 'active', ...extra });
  assert.deepEqual(shape(struckSpans(paged)), [{ page: 1, heading: null }, { page: 3, heading: null }]);
  // An active rule on the page is not a retired one.
  assert.equal(uncitedStruck(paged, [rule({ source_page: '1' })]).length, 2);
  assert.equal(uncitedStruck(paged, [rule({ status: 'retired', source_page: '1' })]).length, 1);
  // A range or list holds the page.
  assert.equal(uncitedStruck(paged, [rule({ status: 'retired', source_page: '1, 3' })]).length, 0);
  assert.equal(uncitedStruck(paged, [rule({ status: 'retired', source_page: '2-4' })]).length, 1);
  // A rule cites the heading the span sits under.
  const flat = '# Doc\n\n## Warning\n\n- ~~Old option~~\n';
  assert.deepEqual(shape(struckSpans(flat)), [{ page: null, heading: 'warning' }]);
  assert.equal(uncitedStruck(flat, [rule({ status: 'retired', source_page: 'Warning' })]).length, 0);
  assert.equal(uncitedStruck(flat, [rule({ status: 'retired', source_page: '1' })]).length, 1);
  assert.equal(uncitedStruck('plain text', []).length, 0);
});

test('a fragment edit or a restated sentence needs no retired rule, and a removal does', () => {
  const active = [{ status: 'active', source_page: '1', rule_summary: 'The loan is saved at once.' }];
  const warns = (text) => uncitedStruck(`<a id="page-1"></a>\n\n${text}\n`, active).length;
  // The issue's own case: the live sentence says something else, so the warning was removed.
  assert.equal(warns('~~A warning appears before the loan is saved.~~ The loan is saved at once.'), 1);
  // The live sentence restates the struck one with a changed value.
  assert.equal(warns('~~A warning appears after 90 days.~~ A warning appears after 120 days.'), 0);
  // Part of a sentence: a value or a word changed.
  assert.equal(warns('The cue shows ~~90~~ 120 days'), 0);
  assert.equal(warns('The page ~~may~~ must show it.'), 0);
  assert.equal(warns('The page is ~~not~~ saved.'), 0);
  // A whole list item or table cell is a removal.
  assert.equal(warns('- ~~Print the receipt~~'), 1);
  assert.equal(warns('1. ~~Print the receipt~~'), 1);
  assert.equal(warns('| Print | ~~Receipt printed~~ | Yes |'), 1);
  // The full stop outside the tildes still ends a sentence.
  assert.equal(warns('~~A warning appears before the loan is saved~~. The loan is saved at once.'), 1);
  // "e.g." does not end the live sentence, so the restatement is read whole.
  assert.equal(warns('~~Show the cue e.g. the warning banner.~~ Show the cue e.g. the warning banner too.'), 0);
  // A sentence that starts with a number is a new sentence.
  assert.equal(warns('~~A warning appears before the loan is saved.~~ The loan is saved. 3 warning appears before loan.'), 1);
  // In a table the live sentence is in the same cell, not in the next row.
  assert.equal(warns('| ~~Print the receipt.~~ | Yes |\n| Print the receipt. | No |'), 1);
  assert.equal(warns('| ~~Print the receipt.~~ Print the receipt now. | Yes |'), 0);
  // A struck sentence followed by another struck one has no live sentence.
  assert.equal(warns('~~Print the receipt.~~ ~~Show the balance.~~'), 2);
});

test('a struck heading is still the heading its spans sit under', () => {
  const text = '## ~~Save Warning~~\n\n- ~~Old item~~\n';
  const retired = [{ status: 'retired', source_page: 'Save Warning' }];
  assert.deepEqual(struckSpans(text).map((s) => s.heading), ['save warning', 'save warning']);
  assert.equal(uncitedStruck(text, retired).length, 0);
  assert.equal(uncitedStruck(text, []).length, 2);
});

test('a span wrapped over a line break is read whole, and a lone mark pairs with nothing', () => {
  const text = '<a id="page-1"></a>\n\nThe ~~warning with Yes and\nNo buttons~~ is gone; ~~second span~~ too.\n\n'
    + 'A ~~left open\n\nblank line~~ is not a span.\n\n'
    + 'approx ~~5 units\nnext ~~real removed~~ end\n';
  assert.deepEqual(struckSpans(text).map((s) => s.text),
    ['warning with Yes and\nNo buttons', 'second span', 'real removed']);
});

test('struck text in code is not read, an unclosed fence hides nothing after it, and headings in code are not headings', () => {
  const text = '<a id="page-1"></a>\n\n## Real\n\n```\n## Fake heading\nx ~~in fence~~ y\n```\n\n'
    + 'Use `~~in code~~` here, ~~a real one~~.\n\n~~~\n~~also fenced~~\n~~~\n';
  assert.deepEqual(struckSpans(text).map(({ page, heading, text: t }) => ({ page, heading, t })),
    [{ page: 1, heading: 'real', t: 'a real one' }]);
  // A fence with no close is not a block.
  const open = '## Real\n\n```\nafter ~~kept~~ here\n';
  assert.deepEqual(struckSpans(open).map((s) => s.text), ['kept']);
});

// A retired rule the change concerns is tested by a card that verifies the behavior is gone.
const RETIRED = 'BR-LIB.UC05-003';
const struckRun = (extra = {}) => lib({
  intake: (value) => ({ ...value, documents: [STRUCK_DOC] }),
  // The inventory names the live rules only.
  phase6_scenarios: (value) => ({ ...value, scenarios: [
    { kind: 'decision', rules: ['BR-LIB.UC05-001'], population: 'p0', action: 'a0', outcome: 'o' },
    { kind: 'decision', rules: ['BR-LIB.UC05-002'], population: 'p1', action: 'a1', outcome: 'o' }] }),
  phase6_cards: titled,
  ...extra,
}, { inputs: { ...fixtureInputs(), ruleExport: exportFrom('master-struck-retired.json') } });

test('a retired Direct Change rule no scenario names gets a scenario and a card that verifies it is gone', async () => {
  const run = struckRun();
  const result = await runLib(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  const asked = callsNamed(run, 'phase6_cards_d1_removed');
  assert.equal(asked.length, 1);
  assert.match(asked[0].user, /check that the behavior of BR-LIB\.UC05-003 is gone/);
  assert.match(asked[0].user, /verifies the behavior is gone/);
  assert.match(callsNamed(run, 'phase6_scenarios')[0].user, /list a scenario that checks its behavior is gone/);
  const pack = JSON.parse(read(result.packPath));
  assert.ok(pack.testCards.some((card) => card.rules.includes(RETIRED)));
  assert.ok(!pack.coverage.some((row) => row.ruleId === RETIRED && row.status === 'Missing'));
});

test('a retired Direct Change rule a card already cites needs no further call', async () => {
  const run = struckRun({ phase6_scenarios: (value) => ({ ...value, scenarios: [
    { kind: 'decision', rules: [RETIRED], population: 'p0', action: 'a0', outcome: 'o' }] }) });
  const result = await runLib(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  assert.equal(callsNamed(run, 'phase6_cards_d1_removed').length, 0);
});

test('a scenario the inventory made for a retired rule, however it settled, adds no further scenario', async () => {
  const run = struckRun({
    phase6_scenarios: (value) => ({ ...value, scenarios: [
      { kind: 'decision', rules: ['BR-LIB.UC05-001'], population: 'p0', action: 'a0', outcome: 'o' },
      { kind: 'decision', rules: [RETIRED], population: 'p1', action: 'a1', outcome: 'o' }] }),
    phase6_cards: (value) => titled({ ...value, cards: value.cards.filter((c) => c.scenario === 'S1'),
      skipped: [{ scenario: 'S2', how: 'reused', reason: 'An existing test covers it.' }] }),
  });
  const result = await runLib(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  assert.equal(callsNamed(run, 'phase6_cards_d1_removed').length, 0);
  assert.equal(phase6Pass(result.outDir).unsettled, 0);
});

test('a scenario for a retired rule that a card settled without citing it still owes a removed scenario', async () => {
  const run = struckRun({
    phase6_scenarios: (value) => ({ ...value, scenarios: [
      { kind: 'decision', rules: ['BR-LIB.UC05-001', RETIRED], population: 'p0', action: 'a0', outcome: 'o' }] }),
    // The card keeps only the live rule.
    phase6_cards: (value) => titled({ ...value, cards: value.cards.map((c) => (c.scenario !== 'S1' ? c : { ...c,
      rules: ['BR-LIB.UC05-001'], steps: c.steps.map((st) => ({ ...st, rules: ['BR-LIB.UC05-001'] })) })) }),
  });
  const result = await runLib(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  assert.equal(callsNamed(run, 'phase6_cards_d1_removed').length, 1);
});

test('verification reads a retired rule as removed, so a card stating the behavior is absent survives', async () => {
  // A verifier that rejects a card citing the retired rule unless its Expected Result says it is gone.
  const judgeRemoved = (value, calls) => {
    const user = calls.at(-1).user;
    const cards = {};
    for (const [, label, body] of user.matchAll(/### (C\d+)\n([\s\S]*?)(?=\n\n### C|\n## |$)/g)) {
      const bad = /BR-LIB\.UC05-003/.test(body) && !/Expected Result: [^\n]*(absent|gone)/.test(body);
      cards[label] = bad ? { why: 'The rule says it happens.', verdict: 'does not follow' }
        : { why: 'It follows.', verdict: 'follows' };
    }
    return { ...value, cards };
  };
  const run = struckRun({
    phase6_cards: (value) => titled({ ...value, cards: value.cards.map((card) => (card.rules.includes(RETIRED)
      ? { ...card, expected: 'The warning is absent',
        steps: card.steps.map((step, i, all) => (i === all.length - 1
          ? { ...step, expected: 'The warning is absent' } : step)) } : card)) }),
    phase6_verify: judgeRemoved,
  });
  const result = await runLib(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  const verify = callsNamed(run, 'phase6_verify');
  assert.ok(verify.length > 0);
  assert.ok(verify.some((call) => /removed: the card must show this no longer happens/.test(call.user)));
  assert.match(verify[0].user, /A rule marked removed was taken out/);
  const pack = JSON.parse(read(result.packPath));
  assert.ok(pack.testCards.some((card) => card.rules.includes(RETIRED) && /absent/.test(card.expected)));
});

test('a retired rule no card can cover is asked for twice, then recorded as a gap and a limitation', async () => {
  const run = struckRun({ phase6_cards: (value) => titled({ ...value,
    cards: value.cards.filter((card) => card.scenario !== 'S3') }) });
  const result = await runLib(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  assert.equal(callsNamed(run, 'phase6_cards_d1_removed').length, 2);
  const pack = JSON.parse(read(result.packPath));
  assert.ok(pack.coverage.some((row) => row.ruleId === RETIRED && row.status === 'Missing'));
  assert.match(pack.limitations['Coverage Matrix'], /BR-LIB\.UC05-003/);
  assert.ok(pack.assumptions.some((a) => a.assumption.startsWith('No test card covers scenario S3:')));
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
      // The checklist and the confidence passed before the failure, so only the calls after them run again.
      assert.deepEqual([...new Set(model.calls.map((c) => c.schemaName))],
        ['phase9_senior', 'phase9_revalidation', 'phase10_notes']);
      const lines = statusLines(result.outDir);
      assert.ok(lines.some((l) => l.event === 'resume' && l.phase === 'phase9-senior'
        && l.after === 'phase9-confidence'));
      assert.deepEqual(lines.filter((l) => l.event === 'pass').map((l) => l.phase).slice(-4),
        ['phase9-senior', 'phase9-revalidate', 'phase10', 'done']);
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

// Expected Results: the check against the final step, and the per-card verification.
// The conflicting-rule fixture: UC03-001 allows a borrow, UC03-002 blocks it, UC03-003 is a Reset,
// and UC03-004 is a supervisor override that is an exception to the block.

const [ALLOW, BLOCK, RESET, OVERRIDE] = ['BR-LIB.UC03-001', 'BR-LIB.UC03-002', 'BR-LIB.UC03-003',
  'BR-LIB.UC03-004'];
const REFUSED = 'The loan is refused with the message Account on hold';
const WRONG_LOAN = 'The loan goes ahead because the card is current';
const SAVED = 'The loan length shows the saved value';
const WRONG_RESET = 'The loan length shows the edited value';
const OVERRIDDEN = 'The loan is made and the supervisor reason code is recorded';

const holdRun = (extra = {}) => {
  const inputs = { ...fixtureInputs(), documentIndex: 'docs/HOLD/*.md',
    description: 'issues-hold/ISSUE_{issue}_*.md',
    ruleExport: ['node', 'export.mjs', '--doc', '{doc}', '--master', 'master-conflict.json'] };
  return lib({
    // The break pass is matched before the inventory, whose name it extends.
    ...(extra.phase6_scenarios_d1_break
      ? { phase6_scenarios_d1_break: extra.phase6_scenarios_d1_break } : {}),
    intake: (value) => ({ ...value, documents: ['docs/HOLD/UC03-Loan-Holds.md'] }),
    phase6_scenarios: (value) => ({ ...value, scenarios: [
      { kind: 'decision', rules: [ALLOW, BLOCK], population: 'a patron with a current card and a hold',
        action: 'borrow an item', outcome: 'refused' },
      { kind: 'decision', rules: [RESET], population: 'a patron editing the loan length',
        action: 'edit, then press Reset', outcome: 'saved value' },
      { kind: 'break', rules: [BLOCK], population: 'a patron with a hold', action: 'borrow again and again',
        outcome: 'refused' },
      { kind: 'decision', rules: [BLOCK, OVERRIDE], population: 'a patron with a hold and a supervisor',
        action: 'borrow with an override', outcome: 'allowed once' }] }),
    // No card is added to an objective after the cards are written.
    phase6_objective: (value) => ({ ...value, cards: [] }),
    ...extra }, { inputs });
};
const runHold = (run, job = {}) => runJob(run.config, { issue: '502', change: '7002', ...job },
  { model: run.model, echo: false });

/** The card for a scenario; `wrong` names the scenarios whose Expected Result is the wrong one. */
const holdCard = (scenario, wrong = []) => {
  // Only the Reset card names Workflow Validation.
  const [rules, right, bad, objectives] = {
    S1: [[ALLOW, BLOCK], REFUSED, WRONG_LOAN, ['Core Change Validation', 'Negative / Exclusion']],
    S2: [[RESET], SAVED, WRONG_RESET, ['Core Change Validation', 'Workflow Validation']],
    S3: [[BLOCK], REFUSED, WRONG_LOAN, ['Core Change Validation', 'Negative / Exclusion']],
    S4: [[BLOCK, OVERRIDE], OVERRIDDEN, REFUSED, ['Core Change Validation', 'Negative / Exclusion']],
  }[scenario];
  const expected = wrong.includes(scenario) ? bad : right;
  return { title: `Hold ${scenario}`, scenario, mission: 'mission', focus: ['focus'], expected, rules,
    objectives, derivation: 'Requirement',
    steps: [{ description: 'Act', expected, rules }] };
};
const holdCards = (wrong = []) => (value) => ({ ...value,
  cards: value.cards.map((card) => holdCard(card.scenario, wrong)) });

/** A verification reply that rejects any card whose text carries a wrong Expected Result. */
const judge = (value, calls) => {
  const cards = {};
  for (const [, label, body] of calls.at(-1).user.matchAll(/### (C\d+)\n([\s\S]*?)(?=\n\n### C|\n## |$)/g)) {
    const noException = /supervisor reason code/.test(body)
      && !/unless a cited rule says it is an exception/.test(calls.at(-1).user);
    const bad = noException || /because the card is current|edited value/.test(body);
    cards[label] = bad ? { why: noException ? 'The block wins.' : /current/.test(body)
      ? 'The hold blocks the loan, and a block outranks the allowance for a current card.'
      : 'Reset restores the saved value.', verdict: 'does not follow' }
      : { why: 'It follows.', verdict: 'follows' };
  }
  return { ...value, cards };
};
const callsNamed = (run, prefix) => run.model.calls.filter((c) => c.schemaName.startsWith(prefix));

/**
 * A run whose Phase 8 sees a card the design passes accepted but whose final step then
 * disagrees: the first run stops before Phase 7, its saved cards are changed, and the
 * job resumes into the builder.
 */
async function resumedWithMismatch(repair, answers = {}) {
  const first = holdRun({ phase6_cards: holdCards(), phase6_verify: judge,
    phase7_sets: () => { throw new Error('stop'); } });
  const stopped = await runHold(first);
  assert.equal(stopped.ok, false);
  const file = path.join(stopped.outDir, 'work', 'checkpoint.json');
  const saved = JSON.parse(read(file));
  const [designed] = Object.values(saved.state.designed);
  designed.cards.find((card) => card.scenario === 'S1').steps.at(-1).expected = 'The page shows nothing';
  fs.writeFileSync(file, JSON.stringify(saved));
  const second = { config: first.config, model: fakeModel({ ...INTAKE, phase8_repair: repair, ...answers }) };
  return { second, result: await runHold(second, { resume: true }) };
}

test('a card that agrees with its rules and its last step passes untouched, after one verification call', async () => {
  const run = holdRun({ phase6_cards: holdCards(), phase6_verify: judge });
  const result = await runHold(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  assert.equal(result.repairs, 0);
  const verify = callsNamed(run, 'phase6_verify');
  assert.equal(verify.length, 1);
  // Never an empty enum: one row per card in the call, two verdicts.
  const rows = verify[0].schema.properties.cards;
  assert.deepEqual(rows.required, ['C1', 'C2', 'C3', 'C4']);
  assert.deepEqual(rows.properties.C1.properties.verdict.enum, ['follows', 'does not follow']);
  // The call carries the card, the rules it cites and their wording, and says which rule wins.
  assert.match(verify[0].user, /Expected Result: The loan is refused with the message Account on hold/);
  assert.match(verify[0].user, /BR-LIB\.UC03-001 \|[^\n]*may borrow up to five items/);
  assert.match(verify[0].user, /BR-LIB\.UC03-002 \|[^\n]*blocks every new loan/);
  assert.match(verify[0].user, /blocks an action outranks one that allows it/);
  assert.match(verify[0].user, /Reset restores the saved value/);
  assert.equal(callsNamed(run, 'phase6_redo').length, 0);
  assert.equal(callsNamed(run, 'phase6_reverify').length, 0);
  const pass = phase6Pass(result.outDir);
  assert.equal(pass.redesigned, 0);
  assert.equal(pass.removed, 0);
  const pack = JSON.parse(read(result.packPath));
  assert.deepEqual(pack.testCards.map((c) => c.expected).sort(), [OVERRIDDEN, REFUSED, REFUSED, SAVED]);
});

test('the prompt makes the precedence a default, and the override card passes only with the exception clause', async () => {
  const run = holdRun({ phase6_cards: holdCards(), phase6_verify: judge });
  const result = await runHold(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  const verify = callsNamed(run, 'phase6_verify')[0];
  assert.match(verify.user, /unless a cited rule says it is an exception to the block or overrides it/);
  assert.match(verify.user, /BR-LIB\.UC03-004 \|[^\n]*override allows one loan despite a hold/);
  assert.match(verify.user, /Expected Result: The loan is made and the supervisor reason code is recorded/);
  const pack = JSON.parse(read(result.packPath));
  assert.ok(pack.testCards.some((c) => c.expected === OVERRIDDEN && c.rules.includes(OVERRIDE)));
  assert.equal(phase6Pass(result.outDir).redesigned, 0);
});

test('a card whose Expected Result follows the allowance is redesigned once, told why, and kept when it now follows', async () => {
  const run = holdRun({ phase6_cards: holdCards(['S1']), phase6_verify: judge,
    phase6_redo: holdCards(), phase6_reverify: judge });
  const result = await runHold(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  const redo = callsNamed(run, 'phase6_redo');
  assert.equal(redo.length, 1);
  assert.deepEqual(redo[0].schema.properties.cards.items.properties.scenario.enum, ['S1']);
  assert.match(redo[0].user, /a block outranks the allowance for a current card/);
  assert.match(redo[0].user, /The loan goes ahead because the card is current/);
  assert.equal(callsNamed(run, 'phase6_reverify').length, 1);
  const pass = phase6Pass(result.outDir);
  assert.equal(pass.redesigned, 1);
  assert.equal(pass.removed, 0);
  const pack = JSON.parse(read(result.packPath));
  const card = pack.testCards.find((c) => c.title === 'Hold S1');
  assert.equal(card.expected, REFUSED);
  assert.equal(card.steps.at(-1).expected, REFUSED);
  assert.equal(pack.testCards.length, 4);
  assert.ok(!pack.coverage.some((row) => row.status === 'Missing'));
});

test('a card that fails twice is removed, its rule reads Missing with the reason, and no set or objective points at it', async () => {
  const run = holdRun({ phase6_cards: holdCards(['S2']), phase6_verify: judge,
    phase6_redo: holdCards(['S2']), phase6_reverify: judge });
  const result = await runHold(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  const pass = phase6Pass(result.outDir);
  assert.equal(pass.redesigned, 1);
  assert.equal(pass.removed, 1);
  assert.equal(callsNamed(run, 'phase6_redo').length, 1);
  const pack = JSON.parse(read(result.packPath));
  assert.deepEqual(pack.testCards.map((c) => c.title).sort(), ['Hold S1', 'Hold S3', 'Hold S4']);
  const row = pack.coverage.find((r) => r.ruleId === RESET);
  assert.equal(row.status, 'Missing');
  assert.match(row.gap, /was removed: Reset restores the saved value/);
  assert.ok(pack.assumptions.some((a) => /Hold S2.*scenario S2/.test(a.assumption)
    && /Reset restores the saved value/.test(a.why)));
  // The rules the other cards cover keep their cards and get no Missing row.
  assert.ok(!pack.coverage.some((r) => [ALLOW, BLOCK].includes(r.ruleId) && r.status === 'Missing'));
  // Only the removed card named Workflow Validation: the objective is off and no set holds it.
  const workflow = pack.objectives.find((r) => r.objective === 'Workflow Validation');
  assert.equal(workflow.applicable, false);
  const ids = new Set(pack.testCards.map((c) => c.id));
  assert.ok(pack.testSets.every((set) => set.cards.every((id) => ids.has(id))));
  assert.ok(!pack.testSets.some((set) => set.objective === 'Workflow Validation'));
});

test('a redesign that comes back with no card removes the card the same way', async () => {
  const run = holdRun({ phase6_cards: holdCards(['S1']), phase6_verify: judge,
    phase6_redo: (value) => ({ ...value, cards: [] }) });
  const result = await runHold(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  assert.equal(callsNamed(run, 'phase6_reverify').length, 0);
  const pack = JSON.parse(read(result.packPath));
  assert.deepEqual(pack.testCards.map((c) => c.title).sort(), ['Hold S2', 'Hold S3', 'Hold S4']);
  assert.equal(pack.coverage.find((r) => r.ruleId === ALLOW).status, 'Missing');
});

test('a skip the redesign answers with settles the scenario and gives the rule its reason', async () => {
  const run = holdRun({ phase6_cards: holdCards(['S2']), phase6_verify: judge,
    phase6_redo: (value) => ({ ...value, cards: [],
      skipped: [{ scenario: 'S2', how: 'gap', reason: 'The page keeps no saved value to restore.' }] }) });
  const result = await runHold(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  const pack = JSON.parse(read(result.packPath));
  const row = pack.coverage.find((r) => r.ruleId === RESET);
  assert.equal(row.status, 'Missing');
  assert.match(row.gap, /No card can cover this rule: The page keeps no saved value to restore\./);
  assert.ok(pack.assumptions.some((a) => /Hold S2/.test(a.assumption)
    && /keeps no saved value/.test(a.why)));
});

test('a skip with a blank reason falls back to the verifier\'s reason', async () => {
  const run = holdRun({ phase6_cards: holdCards(['S2']), phase6_verify: judge,
    phase6_redo: (value) => ({ ...value, cards: [],
      skipped: [{ scenario: 'S2', how: 'gap', reason: ' ' }] }) });
  const result = await runHold(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  const pack = JSON.parse(read(result.packPath));
  assert.match(pack.coverage.find((r) => r.ruleId === RESET).gap, /No card can cover this rule: Reset restores the saved value\./);
});

test('a wrong card from the BREAK IT pass is checked too, and BREAK IT is dropped when it ends up empty', async () => {
  const run = holdRun({
    phase6_scenarios: (value) => ({ ...value, scenarios: [
      { kind: 'decision', rules: [ALLOW, BLOCK], population: 'a patron with a current card and a hold',
        action: 'borrow an item', outcome: 'refused' },
      { kind: 'decision', rules: [RESET], population: 'a patron editing the loan length',
        action: 'edit, then press Reset', outcome: 'saved value' }] }),
    phase6_scenarios_d1_break: (value) => ({ ...value, scenarios: [
      { kind: 'break', rules: [BLOCK], population: 'a patron with a hold', action: 'borrow again and again',
        outcome: 'refused' }] }),
    phase6_cards: holdCards(['S3']), phase6_verify: judge,
    phase6_redo: holdCards(['S3']), phase6_reverify: judge });
  const result = await runHold(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  // The break pass's calls carry their own step names.
  const names = run.model.calls.map((c) => c.schemaName);
  assert.ok(names.includes('phase6_verify_d1_1'));
  assert.ok(names.includes('phase6_verify_d1_break_1'));
  assert.ok(names.includes('phase6_reverify_d1_break_1'));
  const pass = phase6Pass(result.outDir);
  assert.equal(pass.redesigned, 1);
  assert.equal(pass.removed, 1);
  const pack = JSON.parse(read(result.packPath));
  assert.deepEqual(pack.testCards.map((c) => c.title).sort(), ['Hold S1', 'Hold S2']);
  assert.equal(pack.objectives.find((r) => r.objective === 'BREAK IT').applicable, false);
  assert.ok(!pack.testSets.some((set) => set.objective === 'BREAK IT'));
});

test('a card too big for one verification call is retried with summaries only', async () => {
  const run = holdRun({ phase6_cards: holdCards(), phase6_verify: judge });
  // The master's full description of the block rule is what makes a call too big.
  const count = run.model.countTokens;
  run.model.countTokens = async (text) => (text.includes('Staff clear the hold to lift') ? 1e9 : count(text));
  const result = await runHold(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  const names = run.model.calls.map((c) => c.schemaName);
  assert.ok(names.some((name) => /^phase6_verify_d1_1s\d+short$/.test(name)));
  const pack = JSON.parse(read(result.packPath));
  assert.equal(pack.testCards.length, 4);
  assert.ok(!pack.assumptions.some((a) => /was not checked against its rules/.test(a.assumption)));
});

test('a card too big even with summaries only is kept, with an assumption that it was not verified', async () => {
  const run = holdRun({ phase6_cards: holdCards(), phase6_verify: judge });
  const count = run.model.countTokens;
  run.model.countTokens = async (text) => (text.includes('### C') ? 1e9 : count(text));
  const result = await runHold(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  const pack = JSON.parse(read(result.packPath));
  assert.equal(pack.testCards.length, 4);
  assert.ok(pack.assumptions.some((a) => /was not checked against its rules/.test(a.assumption)));
  assert.equal(phase6Pass(result.outDir).removed, 0);
});

test('a card whose final step only words the result differently is kept and its step aligned, not redone', async () => {
  const wordier = (value) => ({ ...value, cards: value.cards.map((card) => {
    const made = holdCard(card.scenario);
    return card.scenario === 'S1' ? { ...made, steps: [{ ...made.steps[0],
      expected: `${REFUSED} and no loan record is created` }] } : made;
  }) });
  const run = holdRun({ phase6_cards: wordier, phase6_verify: judge });
  const result = await runHold(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  assert.equal(result.repairs, 0);
  // The card goes to the verification call like any other, and nothing is redone.
  assert.match(callsNamed(run, 'phase6_verify')[0].user, /and no loan record is created/);
  assert.equal(callsNamed(run, 'phase6_redo').length, 0);
  const pass = phase6Pass(result.outDir);
  assert.equal(pass.redesigned, 0);
  assert.equal(pass.removed, 0);
  const pack = JSON.parse(read(result.packPath));
  const card = pack.testCards.find((c) => c.title === 'Hold S1');
  assert.equal(card.expected, REFUSED);
  assert.equal(card.steps.at(-1).expected, REFUSED);
});

test('a card that does not follow is redone whether or not its final step agrees', async () => {
  const both = (value) => ({ ...value, cards: value.cards.map((card) => {
    const made = holdCard(card.scenario, ['S1']);
    return card.scenario === 'S1' ? { ...made, steps: [{ ...made.steps[0], expected: 'The page shows nothing' }] }
      : made;
  }) });
  const run = holdRun({ phase6_cards: both, phase6_verify: judge, phase6_redo: holdCards(),
    phase6_reverify: judge });
  const result = await runHold(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  assert.equal(callsNamed(run, 'phase6_redo').length, 1);
  assert.equal(phase6Pass(result.outDir).redesigned, 1);
});

test('a batch too big for one call is split, with one counts-only status line', async () => {
  const run = holdRun({ phase6_cards: holdCards(), phase6_verify: judge });
  const count = run.model.countTokens;
  let first = true;
  run.model.countTokens = async (text) => {
    if (first && text.includes('### C4')) {
      first = false;
      return 1e9;
    }
    return count(text);
  };
  const result = await runHold(run);
  assert.equal(result.ok, true, JSON.stringify(result));
  const split = statusLines(result.outDir).filter((l) => l.event === 'split');
  assert.equal(split.length, 1);
  assert.equal(split[0].cards, 4);
  assert.ok(callsNamed(run, 'phase6_verify').length >= 4);
});

test('an Expected Result that disagrees with its last step reaches repair, which is told to keep the card side', async () => {
  const { second, result } = await resumedWithMismatch((value) => ({ ...value, coverage: [], limitations: [],
    cards: value.cards.map((card) => ({ ...card, expected: REFUSED,
      steps: [{ description: 'Act', expected: REFUSED, rules: card.rules }] })) }));
  assert.equal(result.ok, true, JSON.stringify(result));
  assert.equal(result.repairs, 1);
  const repair = callsNamed(second, 'phase8_repair')[0];
  assert.match(repair.user, /Test Card Expected Results:\nTC-\S+ Expected Result "The loan is refused with the message Account on hold" does not agree with its final step's "The page shows nothing"\. Keep the card's Expected Result/);
  assert.match(repair.user, /change that step's expected result to say the same/);
  assert.equal(repair.schema.properties.cards.maxItems, 1);
  assert.deepEqual(expectedProblems(JSON.parse(read(result.packPath))), []);
});

test('a repair that changes an Expected Result is checked again, and undone when it no longer follows', async () => {
  const { second, result } = await resumedWithMismatch((value) => ({ ...value, coverage: [], limitations: [],
    cards: value.cards.map((card) => ({ ...card, expected: WRONG_LOAN,
      steps: [{ description: 'Act', expected: WRONG_LOAN, rules: card.rules }] })) }),
  { phase6_recheck: judge });
  assert.equal(result.ok, true, JSON.stringify(result));
  assert.equal(result.repairs, 1);
  assert.equal(callsNamed(second, 'phase6_recheck').length, 1);
  const pack = JSON.parse(read(result.packPath));
  const card = pack.testCards.find((c) => c.expected === REFUSED && c.steps.at(-1).expected === REFUSED
    && pack.assumptions.some((x) => x.assumption.includes(c.id)));
  assert.equal(card.expected, REFUSED);
  assert.equal(card.steps.at(-1).expected, REFUSED);
  assert.equal(pack.testCards.length, 4);
  assert.ok(pack.assumptions.some((a) => /repair of card TC-\S+ changed its Expected Result/.test(a.assumption)));
});

test('an unfixable mismatch stops the run at the builder gate', async () => {
  const { result } = await resumedWithMismatch((value) => ({ ...value, coverage: [], limitations: [],
    cards: value.cards.map((card) => ({ ...card, expected: 'Unchanged' })) }));
  assert.equal(result.ok, false);
  assert.equal(result.reason, 'gate:builder-fail');
});

test('results agree when equal or when one holds the other, after case and punctuation are set aside', () => {
  const card = (expected, last) => ({ expected, steps: [{ expected: 'first' }, { expected: last }] });
  assert.equal(resultsAgree(card('The loan is refused.', 'the loan is REFUSED')), true);
  assert.equal(resultsAgree(card('The loan is refused', 'The loan is refused with Account on hold')), true);
  assert.equal(resultsAgree(card('The loan is refused with Account on hold', 'The loan is refused')), true);
  // Only the last step counts.
  assert.equal(resultsAgree(card('first', 'The loan is refused')), false);
  // Whole words only: "no" is not inside "know".
  assert.equal(resultsAgree(card('no', 'I know')), false);
  assert.equal(resultsAgree(card('The loan goes ahead', 'The loan is refused')), false);
  assert.equal(resultsAgree(card('', 'The loan is refused')), false);
  assert.equal(resultsAgree(card('The loan is refused', ' ')), false);
  assert.equal(resultsAgree({ expected: 'anything', steps: [] }), true);
});

test('a containment that adds a negation or a condition is a mismatch', () => {
  const card = (expected, last) => ({ expected, steps: [{ expected: last }] });
  assert.equal(resultsAgree(card('Saved', 'Not saved')), false);
  assert.equal(resultsAgree(card('Error message is shown', 'No error message is shown')), false);
  assert.equal(resultsAgree(card('The loan is allowed', 'The loan is allowed only when no hold exists')), false);
  assert.equal(resultsAgree(card('The loan is allowed', 'The loan is allowed unless a hold exists')), false);
  assert.equal(resultsAgree(card('The loan is allowed', "The loan isn't allowed")), false);
  assert.equal(resultsAgree(card('The loan is allowed', 'The loan is allowed until the hold is set')), false);
  assert.equal(resultsAgree(card('The loan is refused', 'The loan is refused except for staff')), false);
  assert.equal(resultsAgree(card('The loan is allowed', "The loan is allowed and can't be undone")), false);
  assert.equal(resultsAgree(card("The loan isn't allowed", "The loan isn't allowed with a message")), true);
  // The same negation on both sides is not extra.
  assert.equal(resultsAgree(card('The loan is not allowed', 'The loan is not allowed with a message')), true);
  assert.equal(resultsAgree(card('The loan is refused', 'The loan is refused with the message Account on hold')), true);
});

// ---- Phase 9: the review reads the built workbook, fixes what it finds, and revalidates ----

const DOCS = { intake: (value) => ({ ...value, documents: ['docs/LIB/UC01-Card-Renewal.md'] }) };
const cardIdIn = (text) => /TC-[A-Z0-9]+-501-\d{3}/.exec(text)[0];
const checksFor = (model, name) => model.calls.filter((c) => c.schemaName.startsWith(name));

/** A checklist that flags the first card's step for as long as the dump shows it unfixed. */
const plantedChecklist = () => {
  let planted = null;
  return (value, calls) => {
    const { user } = calls.at(-1);
    planted ??= cardIdIn(user);
    return { ...value, issues: new RegExp(`Test Name: ${planted} [^\\n]*Description: description value`).test(user)
      ? [{ issue: `${planted} has a step that reads wrong`,
        fix: `Change step 1 of ${planted} to read Corrected step` }] : [] };
  };
};
const correctingRepair = (value) => ({ ...value, coverage: [], limitations: [],
  cards: value.cards.map((card) => ({ ...card,
    steps: card.steps.map((step, i) => (i ? step : { ...step, description: 'Corrected step' })) })) });
const failsRevalidation = { phase9_revalidation: (value) => ({ ...value, passed: false,
  remaining: ['Step 1 still reads wrong'] }) };

test('the review reads the built workbook, applies a fix through repair, and rereads the rebuilt one', async () => {
  const config = fixtureConfig();
  const model = fakeModel({ ...DOCS, phase9_checklist: plantedChecklist(), phase8_repair: correctingRepair });
  const result = await runJob(config, { issue: '501', change: '7001' }, { model, echo: false });
  assert.equal(result.ok, true, JSON.stringify(result));
  const [first, again] = checksFor(model, 'phase9_checklist');
  // The review input is the built workbook's rows: card Expected Results and ALM steps.
  assert.match(first.user, /\[Test Cards Markdown row \d+\] Test Case ID: TC-\S+ \| Test Case Title: .*Expected Result: expected value/);
  assert.match(first.user, /\[ALM Upload row \d+\] Test Name: TC-\S+ .*Description: description value \| Expected Result: /);
  assert.match(first.user, /\[Impact Analysis row \d+\] Rule ID: BR-LIB\.UC01-001/);
  assert.match(first.user, /\[Coverage Matrix row/);
  // The fix went through repair, and the next read is of the rebuilt workbook.
  assert.equal(checksFor(model, 'phase8_repair').length, 1);
  assert.match(checksFor(model, 'phase8_repair')[0].user, /Quality Review:\n- TC-\S+ has a step that reads wrong/);
  assert.match(again.user, /Description: Corrected step/);
  assert.ok(again.user.split('description value').length < first.user.split('description value').length);
  const pack = JSON.parse(read(result.packPath));
  assert.ok(pack.testCards.some((c) => c.steps[0].description === 'Corrected step'));
  assert.equal(pack.revalidation, undefined);
  // Revalidation reads the rebuilt workbook and the fixes applied.
  const [revalidation] = checksFor(model, 'phase9_revalidation');
  assert.match(revalidation.user, /Fixes the review attempted/);
  assert.match(revalidation.user, /Description: Corrected step/);
  const validation = readPack(result.workbook).sheet('Workbook Validation');
  assert.ok(validation.rows.every((row) => row.cells.Status !== 'FAIL'));
  assertContentFree(read(path.join(result.outDir, 'status.log')));
});

test('a finding repair cannot fix gets two rounds, then revalidation fails: Workbook Validation FAIL and a stop code', async () => {
  const config = fixtureConfig();
  const unfixed = (value) => ({ ...value, coverage: [], limitations: [] });
  const model = fakeModel({ ...DOCS, phase9_checklist: plantedChecklist(), phase8_repair: unfixed,
    ...failsRevalidation });
  const result = await runJob(config, { issue: '501', change: '7001' }, { model, echo: false });
  assert.equal(result.ok, false);
  assert.equal(result.reason, 'gate:revalidation-failed');
  assert.equal(result.phase, 'phase9-revalidate');
  // Two fix rounds at most, each followed by a read of the rebuilt workbook.
  assert.equal(checksFor(model, 'phase8_repair').length, 2);
  assert.equal(checksFor(model, 'phase9_checklist').length, 3);
  // The workbook is kept so the reviewer can see what remains, with the FAIL shown, never PASS.
  assert.ok(result.workbook && fs.existsSync(result.workbook));
  const rows = readPack(result.workbook).sheet('Workbook Validation').rows;
  const row = rows.find((r) => r.cells.Sheet === 'Workbook Validation');
  assert.equal(row.cells.Status, 'FAIL');
  assert.match(row.cells.Notes, /Step 1 still reads wrong/);
  const pack = JSON.parse(read(result.packPath));
  assert.equal(pack.revalidation.passed, false);
  const lines = statusLines(result.outDir);
  assert.equal(lines.findLast((l) => l.event === 'fail').reason, 'gate:revalidation-failed');
  assert.ok(!lines.some((l) => l.phase === 'done'));
  assertContentFree(read(path.join(result.outDir, 'status.log')));
});

test('a builder that does not show the FAIL leaves no workbook that reads PASS', async () => {
  const config = fixtureConfig({ builder: { module: 'builder-stub.mjs', retries: 2,
    command: ['node', 'builder-lax.mjs', '{pack}', '--out', '{out}'] } });
  const result = await runJob(config, { issue: '501', change: '7001' },
    { model: fakeModel({ ...DOCS, ...failsRevalidation }), echo: false });
  assert.equal(result.reason, 'gate:revalidation-failed');
  assert.equal(result.workbook, null);
  assert.ok(!fs.readdirSync(result.outDir).some((name) => name.endsWith('.xlsx')));
});

test('the morning report lists a revalidation-failed job as failing', () => {
  const at = new Date().toISOString();
  const queue = { jobs: [{ id: 'issue-9', status: 'queued', finished: null, ms: 5, phase: 'phase9-revalidate',
    reason: 'gate:revalidation-failed', workbook: '/out/w.xlsx',
    failures: [{ at, phase: 'phase9-revalidate', reason: 'gate:revalidation-failed', ms: 5 }] }] };
  const data = reportData(fixtureConfig(), queue, { now: new Date(Date.now() + 1000) });
  assert.equal(data.failing.length, 1);
  assert.deepEqual(data.failing[0].reasons, ['gate:revalidation-failed']);
});

test('with no Requirements Matrix export the checklist runs OPS-009 limited and the pack says so', async () => {
  const derivedModel = fakeModel({ intake: (value) => ({ ...value, documents: ['docs/OTHER/UC09-Unmapped.md'] }) });
  const derived = await runJob(fixtureConfig(), { issue: '501', change: '7001', allowDerivedRules: true },
    { model: derivedModel, echo: false });
  assert.equal(derived.ok, true, JSON.stringify(derived));
  assert.match(checksFor(derivedModel, 'phase9_checklist')[0].user, /OPS-009 as limited/);
  const pack = JSON.parse(read(derived.packPath));
  assert.ok(pack.assumptions.some((a) => /OPS-009 ran limited for the rules of/.test(a.assumption)));

  const exported = fakeModel(DOCS);
  const ok = await runJob(fixtureConfig(), { issue: '501', change: '7001' }, { model: exported, echo: false });
  assert.equal(ok.ok, true, JSON.stringify(ok));
  assert.doesNotMatch(checksFor(exported, 'phase9_checklist')[0].user, /OPS-009/);
  assert.ok(!JSON.parse(read(ok.packPath)).assumptions.some((a) => /OPS-009/.test(a.assumption)));
});

test('a workbook too long for one review call is read in parts, and a failing part fails revalidation', async () => {
  const config = fixtureConfig();
  // The room shrinks once the cards are built, so only the review's reads are split.
  const shrink = (value) => {
    Object.assign(config.model, { context: 7400, reasoningOutput: 1000, maxOutput: 500 });
    return value;
  };
  const longer = (value) => ({ ...value, cards: value.cards.map((c) => ({ ...c, title: 'Long title '.repeat(100) })) });
  const model = fakeModel({ ...DOCS, phase6_cards: longer, phase7: shrink, phase9_revalidation: (value, calls) => ({ ...value,
    remaining: [], passed: calls.filter((c) => c.schemaName.startsWith('phase9_revalidation')).length !== 2 }) });
  const result = await runJob(config, { issue: '501', change: '7001' }, { model, echo: false });
  const parts = checksFor(model, 'phase9_checklist');
  assert.ok(parts.length > 1, `${parts.length} checklist calls: ${JSON.stringify(result)}`);
  assert.match(parts[0].user, /Built workbook, part 1 of \d+/);
  assert.equal(result.reason, 'gate:revalidation-failed');
});

test('a placeholder fix, or one naming no card or rule, is not handed to repair', async () => {
  const flag = (fix) => () => ({ issues: [{ issue: 'The coverage reads thin', fix }], coverage: [], assumptions: [] });
  for (const fix of ['N/A', 'None needed', 'Review the pack again', 'Strengthen the coverage of BR-LIB.UC01-001']) {
    const model = fakeModel({ ...DOCS, phase9_checklist: flag(fix) });
    const result = await runJob(fixtureConfig(), { issue: '501', change: '7001' }, { model, echo: false });
    assert.equal(result.ok, true, JSON.stringify(result));
    assert.equal(checksFor(model, 'phase8_repair').length, 0, fix);
    assert.equal(checksFor(model, 'phase9_checklist').length, 1, fix);
  }
});

test('a fix round leaves the pack\'s coverage rows and limitations as they were', async () => {
  const model = fakeModel({ ...DOCS, phase9_checklist: plantedChecklist(),
    phase8_repair: (value) => ({ ...correctingRepair(value),
      coverage: [{ ruleId: 'BR-LIB.UC01-001', status: 'Missing', strength: 'Weak', gap: 'x', recommendation: 'y' }],
      limitations: [{ sheet: 'Coverage Matrix', text: 'A repair limitation.' }] }) });
  const result = await runJob(fixtureConfig(), { issue: '501', change: '7001' }, { model, echo: false });
  assert.equal(result.ok, true, JSON.stringify(result));
  const pack = JSON.parse(read(result.packPath));
  assert.ok(!pack.coverage.some((row) => row.ruleId === 'BR-LIB.UC01-001' && row.status === 'Missing'));
  assert.ok(!Object.values(pack.limitations ?? {}).includes('A repair limitation.'));
});

test('a draft the builder writes no workbook for leaves the review the pack summary, and says so', async () => {
  const config = fixtureConfig({ builder: { module: 'builder-stub.mjs', retries: 2,
    command: ['node', '-e', '0'] } });
  const model = fakeModel(DOCS);
  const result = await runJob(config, { issue: '501', change: '7001' }, { model, echo: false });
  assert.doesNotMatch(checksFor(model, 'phase9_checklist')[0].user, /\[ALM Upload row/);
  assert.ok(statusLines(result.outDir).some((l) => l.phase === 'phase9' && l.event === 'warn'
    && l.reason === 'review-workbook-missing'));
  assertContentFree(read(path.join(result.outDir, 'status.log')));
});

test('every part of a split workbook opens with the rules index, and a job missing rules says which documents', async () => {
  const config = fixtureConfig();
  const shrink = (value) => {
    Object.assign(config.model, { context: 7400, reasoningOutput: 1000, maxOutput: 500 });
    return value;
  };
  const longer = (value) => ({ ...value, cards: value.cards.map((c) => ({ ...c, title: 'Long title '.repeat(100) })) });
  const model = fakeModel({ ...DOCS, phase6_cards: longer, phase7: shrink });
  await runJob(config, { issue: '501', change: '7001' }, { model, echo: false });
  const parts = checksFor(model, 'phase9_checklist');
  assert.ok(parts.length > 1);
  for (const part of parts) assert.match(part.user, /Rules in this part and the cards that cite them[\s\S]*BR-LIB\.UC01-001 \| [^|]+ \| cards: /);
  const mixed = fakeModel({ intake: (value) => ({ ...value,
    documents: ['docs/LIB/UC01-Card-Renewal.md', 'docs/OTHER/UC09-Unmapped.md'] }) });
  await runJob(fixtureConfig(), { issue: '501', change: '7001', allowDerivedRules: true }, { model: mixed, echo: false });
  assert.match(checksFor(mixed, 'phase9_checklist')[0].user, /rule export held no rules for [^.]*UC09/);
});

test('a job whose revalidation failed is not retried by the queue', async () => {
  const config = fixtureConfig();
  addJob(config, { issue: '300', now: true });
  let runs = 0;
  const run = async () => {
    runs += 1;
    return { ok: false, id: 'issue-300', phase: 'phase9-revalidate', reason: 'gate:revalidation-failed',
      ms: 1, workbook: '/out/w.xlsx' };
  };
  const t = new Date('2026-10-28T14:00:00');
  await drainQueue(config, { nowOnly: true, run, clock: () => t });
  const [row] = readQueue(config).jobs;
  assert.equal(runs, 1);
  assert.equal(row.status, 'failed');
  assert.equal(row.workbook, '/out/w.xlsx');
});

test('Phase 4 rates the impacted rules from the impact analysis and raises a Direct Change rule below High', async () => {
  const model = fakeModel({ ...INTAKE, ...NOT_REMOVAL,
    phase3: (value) => {
      value.rules['BR-LIB.UC01-006'] &&= { ...value.rules['BR-LIB.UC01-006'], impact: 'Not Impacted' };
      value.rules['BR-LIB.UC01-001'] = { ...value.rules['BR-LIB.UC01-001'], impact: 'Direct Change' };
      value.rules['BR-LIB.UC01-002'] = { ...value.rules['BR-LIB.UC01-002'], impact: 'Indirect Impact' };
      return value;
    },
    phase4_risk: (value) => {
      for (const id of Object.keys(value.rules)) value.rules[id] = { ...value.rules[id], risk: 'Medium' };
      return value;
    } });
  const result = await runJob(fixtureConfig(), { issue: '501', change: '7001' }, { model, echo: false });
  assert.equal(result.ok, true, JSON.stringify(result));
  const pack = JSON.parse(read(result.packPath));
  const risk = (id) => pack.rules.find((rule) => rule.id === id).risk;
  // The Direct Change rule is raised to High; the Indirect one keeps what the analysis gave.
  assert.equal(risk('BR-LIB.UC01-001'), 'High');
  assert.equal(risk('BR-LIB.UC01-002'), 'Medium');
  assert.match(read(path.join(result.outDir, 'detail.log')),
    /phase4 raised risk[\s\S]*BR-LIB\.UC01-001: Medium to High/);
  // The rating call sees the impact and the master's risk, beside the impact analysis.
  const rating = model.calls.find((call) => call.schemaName.startsWith('phase4_risk'));
  assert.match(rating.user, /BR-LIB\.UC01-001 .*\| Direct Change \| master risk: \w+/);
  assert.match(rating.user, /Impact analysis/);
  assertContentFree(read(path.join(result.outDir, 'status.log')));
});

test('Phase 4 rates only the impacted rules when every rule carries a master risk', async () => {
  const model = fakeModel({ ...INTAKE, ...NOT_REMOVAL,
    phase3: (value) => {
      for (const id of Object.keys(value.rules)) value.rules[id] = { ...value.rules[id], impact: 'Not Impacted' };
      value.rules['BR-LIB.UC01-001'] = { ...value.rules['BR-LIB.UC01-001'], impact: 'Direct Change' };
      return value;
    } });
  // The pack with one impacted rule stops at the builder, after Phase 4 has rated its rules.
  await runJob(fixtureConfig(), { issue: '501', change: '7001' }, { model, echo: false });
  const rated = model.calls.filter((call) => call.schemaName.startsWith('phase4_risk'))
    .flatMap((call) => Object.keys(call.schema.properties.rules.properties));
  assert.deepEqual(rated, ['BR-LIB.UC01-001']);
});

test('a suite pack keeps the approved risks and rates no rule that has one', async () => {
  const model = fakeModel();
  const result = await runJob(fixtureConfig(), { suite: 'LIB' }, { model, echo: false });
  assert.equal(result.ok, true, JSON.stringify(result));
  const rated = model.calls.filter((call) => call.schemaName.startsWith('phase4_risk'));
  assert.equal(rated.length, 0);
  assert.doesNotMatch(read(path.join(result.outDir, 'detail.log')), /phase4 raised risk/);
});

test('the Phase 4 rating call carries the executive summary its batches are budgeted for', async () => {
  const config = fixtureConfig();
  const long = { phase4_impact: (value) => ({ ...value,
    executiveSummary: { ...value.executiveSummary, summary: 'Long summary. '.repeat(900) } }),
  phase3: (value) => {
    value.rules['BR-LIB.UC01-006'] &&= { ...value.rules['BR-LIB.UC01-006'], impact: 'Not Impacted' };
    value.rules['BR-LIB.UC01-001'] = { ...value.rules['BR-LIB.UC01-001'], impact: 'Direct Change' };
    return value;
  } };
  const model = fakeModel({ ...INTAKE, ...long });
  await runJob(config, { issue: '501', change: '7001' }, { model, echo: false });
  const rating = model.calls.find((call) => call.schemaName.startsWith('phase4_risk'));
  assert.ok(rating, 'Phase 4 made no rating call');
  assert.match(rating.user, /Long summary\./);
});

// ---- Phase 9: the confidence assessment field by field, and the senior review last ----

test('each Confidence Assessment field is written on its own from the finished workbook, before the senior review', async () => {
  const model = fakeModel(DOCS);
  const result = await runJob(fixtureConfig(), { issue: '501', change: '7001' }, { model, echo: false });
  assert.equal(result.ok, true, JSON.stringify(result));
  const names = [...new Set(model.calls.map((call) => call.schemaName))]
    .filter((name) => /^phase9_(confidence|senior)/.test(name));
  assert.deepEqual(names, ['phase9_confidence_overall', 'phase9_confidence_coverage',
    'phase9_confidence_remainingRisks', 'phase9_confidence_assumptions',
    'phase9_confidence_regressionScope', 'phase9_confidence_breakItScope',
    'phase9_confidence_manualReview', 'phase9_senior']);
  // A field call asks for that field alone and sees the fields already written.
  const second = model.calls.find((call) => call.schemaName === 'phase9_confidence_remainingRisks');
  assert.deepEqual(Object.keys(second.schema.properties), ['remainingRisks']);
  assert.match(second.user, /Fields already written[\s\S]*Confidence Assessment coverage: coverage value/);
  // The review of the finished workbook: card rows from the built workbook are in view.
  assert.match(second.user, /\[Test Cards Markdown row \d+\]/);
  // The senior review comes last and sees the confidence assessment.
  const senior = model.calls.find((call) => call.schemaName === 'phase9_senior');
  assert.match(senior.user, /Confidence assessment[\s\S]*"coverage":"coverage value"/);
  const pack = JSON.parse(read(result.packPath));
  assert.equal(pack.confidence.manualReview, 'manualReview value');
  assert.equal(pack.confidence.overall, 'High');
});

test('a field that repeats another is asked for again with what was wrong', async () => {
  const long = 'Every rule is covered by at least one card in this workbook.';
  const model = fakeModel({ ...DOCS,
    'phase9_confidence_coverage': () => ({ coverage: long }),
    'phase9_confidence_remainingRisks': (value, calls) => {
      const tries = calls.filter((call) => call.schemaName === 'phase9_confidence_remainingRisks').length;
      return tries === 1 ? { remainingRisks: long } : value;
    } });
  const result = await runJob(fixtureConfig(), { issue: '501', change: '7001' }, { model, echo: false });
  assert.equal(result.ok, true, JSON.stringify(result));
  const asks = model.calls.filter((call) => call.schemaName === 'phase9_confidence_remainingRisks');
  assert.equal(asks.length, 2);
  assert.match(asks[1].user, /refused: it repeats the text of Confidence Assessment coverage/);
  assert.equal(JSON.parse(read(result.packPath)).confidence.remainingRisks, 'remainingRisks value');
});

test('a field that cites a card the workbook lacks is refused, and a second refusal stops the job', async () => {
  const cited = (value) => ({ ...value, coverage: 'Card TC-MOD-501-999 covers it.' });
  const once = fakeModel({ ...DOCS, 'phase9_confidence_coverage': (value, calls) =>
    (calls.filter((call) => call.schemaName === 'phase9_confidence_coverage').length === 1 ? cited(value) : value) });
  const fixed = await runJob(fixtureConfig(), { issue: '501', change: '7001' }, { model: once, echo: false });
  assert.equal(fixed.ok, true, JSON.stringify(fixed));
  const asks = once.calls.filter((call) => call.schemaName === 'phase9_confidence_coverage');
  assert.match(asks[1].user, /refused: it cites TC-MOD-501-999, which the workbook does not hold/);

  const always = fakeModel({ ...DOCS, 'phase9_confidence_coverage': cited });
  const stopped = await runJob(fixtureConfig(), { issue: '501', change: '7001' }, { model: always, echo: false });
  assert.equal(stopped.ok, false);
  assert.equal(stopped.reason, 'gate:review-field-unsupported');
  assert.equal(stopped.phase, 'phase9-confidence');
  assertContentFree(read(path.join(stopped.outDir, 'status.log')));
});

test('a senior review answer with a repeated or unsupported field is asked for again', async () => {
  const model = fakeModel({ ...DOCS, phase9_senior: (value, calls) => {
    const tries = calls.filter((call) => call.schemaName === 'phase9_senior').length;
    return tries === 1
      ? { ...value, seniorReview: { ...value.seniorReview, missed: 'See BR-LIB.UC01-099.' } } : value;
  } });
  const result = await runJob(fixtureConfig(), { issue: '501', change: '7001' }, { model, echo: false });
  assert.equal(result.ok, true, JSON.stringify(result));
  const asks = model.calls.filter((call) => call.schemaName === 'phase9_senior');
  assert.equal(asks.length, 2);
  assert.match(asks[1].user, /Senior Tester Review missed: it cites BR-LIB\.UC01-099/);
  assert.equal(JSON.parse(read(result.packPath)).seniorReview.missed, 'missed value');
});

// ---------------------------------------------------------------------------
// Intake records only what is missing; the change description is the ALM fields.

const RECORD = [
  '# SIR 501', '', 'Status: Open', 'Short Description: Renewal counts from the wrong day', '',
  '## Long Description', '', 'A card renewed early loses days.', 'Both renewal paths take the fix.', '',
  '## Comments', '', 'Reviewer note that is not a description.', ''].join('\n');

test('the change description holds the ALM short and long descriptions only', () => {
  const text = almDescriptions(RECORD);
  assert.equal(text, 'Renewal counts from the wrong day\n\nA card renewed early loses days.\n'
    + 'Both renewal paths take the fix.');
  assert.ok(!text.includes('Reviewer note'));
  assert.ok(!text.includes('Status'));
});

test('a record that labels neither description is used whole', () => {
  assert.equal(almDescriptions('Plain record text.\n'), 'Plain record text.');
});

test('the pack takes the ALM descriptions while the model reads the whole record', async () => {
  const config = fixtureConfig();
  const file = path.join(path.dirname(config.output), 'record.md');
  fs.writeFileSync(file, RECORD);
  const model = fakeModel({ intake: (value) => ({ ...value, documents: ['docs/LIB/UC01-Card-Renewal.md'] }) });
  const result = await runJob(config, { issue: '501', change: '7001', descriptionFile: file },
    { model, echo: false });
  assert.equal(result.ok, true, JSON.stringify(result));
  const pack = JSON.parse(read(result.packPath));
  assert.equal(pack.changeDescription, almDescriptions(RECORD));
  assert.match(model.calls.find((c) => c.schemaName.startsWith('intake')).user, /Reviewer note/);
});

const provenance = (lines) => `# Design\n\n**Document provenance**\n\n${lines.join('\n')}\n\nBody.\n`;
const campDoc = (revised) => ({ name: 'Credit Design', text: provenance([
  '- Source: `Credit Design.doc`',
  '- SharePoint: [Credit Design.doc](<host>/sites/x/Shared%20Documents/CAMP%20Designs/Credit%20Design.doc?web=1)',
  `- Revised: ${revised}, from the revision history table`]) });

test('a document whose provenance path is under CAMP Designs is the CAMP document and its date the updated design', () => {
  const found = documentInputs([campDoc('2026-09-30')], 'The CAMP design changed.');
  assert.deepEqual(found.missing, []);
  assert.deepEqual(found.received, ['CAMP document: Credit Design',
    'Updated design: Credit Design, revised 2026-09-30']);
});

test('a CAMP document without a revision date leaves the updated design missing', () => {
  const doc = campDoc('x');
  doc.text = doc.text.replace(/- Revised:.*\n/, '- Revised: not stated\n');
  const found = documentInputs([doc], '');
  assert.equal(found.received.length, 1);
  assert.equal(found.missing.length, 1);
  assert.match(found.missing[0], /^Updated design/);
});

test('a record naming a CAMP design with no CAMP document lists both as missing, and one that does not lists neither', () => {
  const other = { name: 'Other', text: provenance(['- Source: `Other.doc`', '- Revised: 2026-01-01, x']) };
  assert.equal(documentInputs([other], 'See the CAMP design.').missing.length, 2);
  assert.deepEqual(documentInputs([other], 'A plain change.').missing, []);
});

test('a document with derived rules is listed as missing its rules', () => {
  const found = documentInputs([{ name: 'Doc', text: '', ruleCode: 'rules-derived' }], '');
  assert.match(found.missing[0], /^Business rules for Doc/);
});

test('intake lists nothing missing for a job whose inputs all arrived, whatever the model says', async () => {
  const config = fixtureConfig();
  const model = fakeModel({ intake: (value) => ({ ...value, documents: ['docs/LIB/UC01-Card-Renewal.md'],
    missing: ['OPS-008 preferred input'] }) });
  const result = await runJob(config, { issue: '501', change: '7001' }, { model, echo: false });
  const pack = JSON.parse(read(result.packPath));
  assert.deepEqual(pack.intake.missing, []);
  assert.equal(pack.intake.readiness, 'READY');
  assert.ok(!(pack.limitations ?? {})['Job Intake']);
});

test('assumptions citing rule IDs or counts the pack does not hold are dropped', () => {
  const rules = ['BR-ABC-001', 'BR-ABC-002', 'BR-ABC-003'].map((id, i) => ({ id, sourceDocument: 'Doc',
    module: 'MOD', impact: i ? 'Not Impacted' : 'Direct Change', risk: 'Low', summary: 's' }));
  const keep = (assumption) => ({ assumption, why: 'w', impact: 'i', clarification: 'c' });
  const pack = { rules, testCards: [{ rules: ['BR-ABC-001'], derivation: 'Requirement', module: 'MOD' }],
    coverage: [], assumptions: [
      keep('BR-ABC-001 is read as written.'), keep('BR-ABC-099 is read as written.'),
      keep('The 3 rules of the document are all read.'), keep('The 40 rules of the document are all read.'),
      keep('The 2 impacted rules are read.'), keep('The 7 test cards are read.'),
      keep('The 1 card is read.'), keep('OPS-009 ran limited.')] };
  assert.equal(dropUnfoundedAssumptions({}, pack), 3);
  assert.deepEqual(pack.assumptions.map((a) => a.assumption), [
    'BR-ABC-001 is read as written.', 'The 3 rules of the document are all read.',
    'The 2 impacted rules are read.', 'The 1 card is read.', 'OPS-009 ran limited.']);
});

/**
 * Phase 5 with a model that marks every objective not applicable and answers the
 * stage closure fields from `closure`; returns the Integration Testing row and the log.
 */
async function runPhase5(description, rules, closure, objectives = ['Core Change Validation', 'Integration Testing', 'BREAK IT'], context = 100000) {
  const model = fakeModel({ phase5: (value) => {
    for (const row of Object.values(value.objectives)) row.applicable = false;
    return { ...value, ...closure };
  } });
  const logged = [];
  const ctx = { pack: { rules, executiveSummary: {} }, ref: { core: [], chapters: () => [] },
    job: {}, builder: { OBJECTIVES: objectives }, coreObjective: 'Core Change Validation',
    description, model, calls: 0, tokens: { prompt: 0, output: 0 },
    config: { model: { context, reasoningOutput: 100, maxOutput: 100 } },
    logs: { detail: (label, text) => logged.push(`${label}: ${text}`), status() {} }, private() {} };
  await phase5(ctx);
  return { row: ctx.pack.objectives.find((row) => row.objective === 'Integration Testing'), logged, model };
}

const SENTENCE = 'The window submits the stage closure after a FATL downgrade.';
const claim = (quote) => ({ stageClosureAfterDowngrade: true, stageClosureQuote: quote });
const impacted = (impact, summary = SENTENCE) => ({ impact, name: 'Rule', summary });

test('a quote found in the ALM descriptions marks Integration Testing applicable', async () => {
  const { row, model } = await runPhase5(`Short Description: ${SENTENCE}`, [],
    claim('the window submits the  STAGE closure after a FATL downgrade.'));
  assert.equal(row.applicable, true);
  assert.match(row.reason, /stage closure submit after a FATL downgrade/);
  const asked = model.calls.find((c) => c.schemaName.startsWith('phase5'));
  assert.ok(asked.schema.properties.stageClosureQuote);
  assert.match(asked.user, /stageClosureQuote/);
});

test('a quote from a Direct Change rule is accepted, one from a Not Impacted rule is not', async () => {
  const ok = await runPhase5('x', [impacted('Direct Change')], claim(SENTENCE));
  assert.equal(ok.row.applicable, true);
  const no = await runPhase5('x', [impacted('Not Impacted')], claim(SENTENCE));
  assert.equal(no.row.applicable, false);
  assert.match(no.logged.join('\n'), /evidence was rejected/);
});

test('the prompt lists the impacted rules, and a quote from one is accepted when the description lacks the terms', async () => {
  const rule = { impact: 'Direct Change', name: 'Stage closure', summary: 'Submit the stage closure after a FATL downgrade.' };
  const notes = '**Short Description**: A label changes.\n**Comments**: The window submits the stage closure after a FATL downgrade.';
  const { row, model } = await runPhase5(notes, [rule, impacted('Not Impacted', 'Hidden rule text.')],
    claim('Stage closure. Submit the stage closure after a FATL downgrade.'));
  assert.equal(row.applicable, true);
  const user = model.calls.find((c) => c.schemaName.startsWith('phase5')).user;
  assert.match(user, /- Stage closure\. Submit the stage closure after a FATL downgrade\./);
  assert.ok(!user.includes('Hidden rule text'));
  assert.ok(!user.includes('Comments'));
  // A quote from the comments is outside the description the check reads.
  const rejected = await runPhase5(notes, [], claim('The window submits the stage closure after a FATL downgrade.'));
  assert.equal(rejected.row.applicable, false);
});

test('only the impacted rules that hold both terms reach the prompt, as many as fit', async () => {
  const other = Array.from({ length: 50 }, (_, i) => ({ impact: 'Direct Change', name: `Other ${i}`,
    summary: 'Unrelated behavior of the window.' }));
  const hit = { impact: 'Indirect Impact', name: 'Closure', summary: 'Submit the stage closure after a FATL downgrade.' };
  const small = await runPhase5('x', [...other, hit], claim(SENTENCE));
  const user = small.model.calls.find((c) => c.schemaName.startsWith('phase5')).user;
  assert.match(user, /- Closure\. Submit the stage closure after a FATL downgrade\./);
  assert.ok(!user.includes('Other 0.'));
  assert.ok(!small.logged.some((line) => /left out/.test(line)));
  const many = Array.from({ length: 40 }, (_, i) => ({ impact: 'Direct Change', name: `Closure ${i}`,
    summary: `Submit the stage closure after a FATL downgrade, and ${'check the window. '.repeat(3)}`.replace(/\. /g, ' ') + '.' }));
  const capped = await runPhase5('x', many, claim(SENTENCE), undefined, 5000);
  const cappedUser = capped.model.calls.find((c) => c.schemaName.startsWith('phase5')).user;
  const sent = (cappedUser.match(/^- Closure \d+\./gm) ?? []).length;
  assert.ok(sent > 0 && sent < 40, `sent ${sent}`);
  assert.match(capped.logged.join('\n'), new RegExp(`${40 - sent} of 40 rule lines did not fit`));
});

test('a rule summary with a line break or a long space run is listed and its quote accepted', async () => {
  for (const summary of ['After a FATL is downgraded, the stage closure\nis submitted again.',
    `After a FATL downgrade, the stage closure${' '.repeat(100)}is submitted again.`]) {
    const rule = { impact: 'Direct Change', name: 'Closure', summary };
    const { row, model } = await runPhase5('x', [rule],
      claim(`Closure. ${summary}`.replace(/\s+/g, ' ')));
    const user = model.calls.find((c) => c.schemaName.startsWith('phase5')).user;
    assert.match(user, /- Closure\. After a FATL/, summary);
    assert.equal(row.applicable, true, summary);
  }
});

test('plural FATLs and stage closures are accepted in a quote', async () => {
  for (const text of ['Submitting stage closures after FATL downgrades fails.',
    'After FATLs are downgraded, stage closure submit fails.']) {
    const { row } = await runPhase5(`Short Description: ${text}`, [], claim(text));
    assert.equal(row.applicable, true, text);
  }
});

test('a quote that is not in the record is rejected and logged', async () => {
  const { row, logged } = await runPhase5('A plain change.', [], claim(SENTENCE));
  assert.equal(row.applicable, false);
  assert.match(logged.join('\n'), /evidence was rejected: quote not in/);
});

test('a quote that names only one of the downgrade and the submit is rejected', async () => {
  for (const text of ['The window shows a new label after a FATL downgrade.',
    'The window submits the stage closure.']) {
    const { row, logged } = await runPhase5(`Short Description: ${text}`, [], claim(text));
    assert.equal(row.applicable, false, text);
    assert.match(logged.join('\n'), /lacks a FATL downgrade/);
  }
});

test('a missing quote or a false answer leaves the model\'s choice', async () => {
  assert.equal((await runPhase5(SENTENCE, [], claim(''))).row.applicable, false);
  const denied = await runPhase5(SENTENCE, [], { stageClosureAfterDowngrade: false, stageClosureQuote: SENTENCE });
  assert.equal(denied.row.applicable, false);
  assert.ok(!denied.logged.some((line) => /rejected/.test(line)));
});

test('an objective list without Integration Testing is unaffected by a valid claim', async () => {
  const { row } = await runPhase5(SENTENCE, [], claim(SENTENCE), ['Core Change Validation', 'BREAK IT']);
  assert.equal(row, undefined);
});

test('a long description keeps its own Word: lines and ends at the next ALM field', () => {
  const record = ['**Short Description**: Short text', '**Long Description:**', 'Steps to reproduce:',
    '1. Click OK: nothing happens', 'Expected Result: a save', 'Actual Result: none', 'Note: see log',
    '**Status**: Open', 'Comments:', 'Not part of it.'].join('\n');
  const text = almDescriptions(record);
  assert.match(text, /^Short text\n\nSteps to reproduce:/);
  assert.match(text, /Actual Result: none\nNote: see log$/);
  assert.ok(!/Open|Not part/.test(text));
});


test('only counts of rules or cards are checked, and dotted rule IDs and business rules are caught', () => {
  const rules = ['BR-LIB.UC01-001', 'BR-LIB.UC01-002'].map((id) => ({ id, sourceDocument: 'D', module: 'M',
    impact: 'Direct Change', risk: 'Low', summary: 's' }));
  const keep = (assumption) => ({ assumption, why: 'w', impact: 'i', clarification: 'c' });
  const logged = [];
  const pack = { rules, testCards: [], coverage: [], assumptions: [
    keep('Each card covers 1 rule.'), keep('Steps 1 to 3 cards are shared.'), keep('Section 5 rules apply.'),
    keep('In 2026 rules changed.'), keep('The 2 business rules are read.'),
    keep('The 40 business rules are read.'), keep('All 12 BRs are read.'),
    keep('BR-LIB.UC01-099 is read.'), keep('BR-LIB.UC01-002 is read.')] };
  assert.equal(dropUnfoundedAssumptions({ logs: { detail: (label, text) => logged.push(text) } }, pack), 3);
  assert.deepEqual(logged, ['The 40 business rules are read.', 'All 12 BRs are read.', 'BR-LIB.UC01-099 is read.']);
  assert.equal(pack.assumptions.length, 6);
});

test('CAMP Designs counts only as a folder, and only a CAMP design in the descriptions makes it missing', () => {
  const named = { name: 'CAMP Designs.doc', text: provenance(['- Source: `CAMP Designs.doc`',
    '- SharePoint: [x](<host>/sites/x/Other/CAMP%20Designs.doc?web=1)', '- Revised: 2026-01-01, x']) };
  assert.equal(documentInputs([named], '').received.length, 0);
  const other = { name: 'Other', text: provenance(['- Source: `Other.doc`', '- Revised: 2026-01-01, x']) };
  assert.deepEqual(documentInputs([other], 'Short Description: x\nStatus: CAMP only here').missing, []);
  assert.equal(documentInputs([other], 'Short Description: Update the CAMP design.').missing.length, 2);
});

test('a NOT READY partial pack names what code found missing', async () => {
  const config = fixtureConfig();
  const result = await runJob(config, { issue: '999' }, { model: fakeModel(), echo: false });
  assert.equal(result.reason, 'gate:missing-inputs');
  const pack = JSON.parse(read(path.join(result.outDir, 'work', 'partial-pack.json')));
  assert.equal(pack.intake.readiness, 'NOT READY');
  assert.ok(pack.intake.missing.includes('Description of the defect or change.'));
});

test('common words in a long description do not end it, and a bold Status does', () => {
  const plain = 'Long Description:\n1. Open the form\nName: Smith\n2. Save\nType: Rail\n3. Expect error\n'
    + 'Status: Open\nPriority: High\nComments: x';
  assert.equal(almDescriptions(plain), '1. Open the form\nName: Smith\n2. Save\nType: Rail\n3. Expect error\nStatus: Open');
  assert.equal(almDescriptions('Short Description: x\nSummary: the save fails'), 'x\nSummary: the save fails');
  const bold = '**Long Description**: a\nName: Smith\n**Status**: Open\nb';
  assert.equal(almDescriptions(bold), 'a\nName: Smith');
});

test('a number is skipped only as a section, step, page, range end or year', () => {
  const rules = ['BR-A-001', 'BR-A-002'].map((id) => ({ id, sourceDocument: 'D', module: 'M',
    impact: 'Direct Change', risk: 'Low', summary: 's' }));
  const keep = (assumption) => ({ assumption, why: 'w', impact: 'i', clarification: 'c' });
  const pack = { rules, testCards: [], coverage: [], assumptions: [
    keep('The checks apply to 40 rules.'), keep('Covered in 12 rules.'), keep('From 40 rules, 2 apply.'),
    keep('Rules 3 to 40 rules apply.'), keep('See page 9 rules.'), keep('Since 2026 rules changed.')] };
  dropUnfoundedAssumptions({}, pack);
  assert.deepEqual(pack.assumptions.map((a) => a.assumption),
    ['Rules 3 to 40 rules apply.', 'See page 9 rules.', 'Since 2026 rules changed.']);
});

test('missing inputs read as sentences, name the missing file and list it once', async () => {
  const config = fixtureConfig();
  const result = await runJob(config, { issue: '501', change: '7001',
    docs: ['docs/LIB/gone-1.md', 'docs/LIB/gone-2.md'] }, { model: fakeModel(), echo: false });
  const pack = JSON.parse(read(path.join(result.outDir, 'work', 'partial-pack.json')));
  const files = pack.intake.missing.filter((t) => t.startsWith('Document file not found'));
  assert.deepEqual(files, ['Document file not found: docs/LIB/gone-1.md.',
    'Document file not found: docs/LIB/gone-2.md.']);
  assert.match(pack.limitations['Job Intake'], /gone-1\.md\. Document file not found: docs\/LIB\/gone-2\.md\./);
});

test('an escaped bracket in a file name does not hide the CAMP Designs folder', () => {
  const doc = { name: 'A', text: provenance(['- Source: `A [v2](old).doc`',
    '- SharePoint: [A \\[v2\\](old).doc](<host>/sites/x/CAMP%20Designs/A.doc?web=1)', '- Revised: 2026-01-01, x']) };
  assert.equal(documentInputs([doc], '').received.length, 2);
});

test('the label style comes from the label that opened the current field', () => {
  assert.equal(almDescriptions('Short Description: x\n**Long Description**: a\n**Status**: Open\nb'), 'x\n\na');
  assert.equal(almDescriptions('**Short Description**: x\nLong Description: a\n**Status**: Open\nb'),
    'x\n\na\n**Status**: Open\nb');
  assert.equal(almDescriptions('**Long Description**\nShort Description: x\n**Status**: Open\ny'),
    'x\n**Status**: Open\ny');
});

test('a range with and keeps its number, a list of counts does not', () => {
  const rules = ['BR-A-001', 'BR-A-002'].map((id) => ({ id, sourceDocument: 'D', module: 'M',
    impact: 'Direct Change', risk: 'Low', summary: 's' }));
  const keep = (assumption) => ({ assumption, why: 'w', impact: 'i', clarification: 'c' });
  const pack = { rules, testCards: [], coverage: [], assumptions: [
    keep('Between 2 and 40 rules apply.'), keep('2 rules and 40 rules apply.')] };
  dropUnfoundedAssumptions({}, pack);
  assert.deepEqual(pack.assumptions.map((a) => a.assumption), ['Between 2 and 40 rules apply.']);
  const other = { ...pack, assumptions: ['BR-A-001 and 40 rules apply.', 'Section 4 and 40 rules apply.',
    'In 2025 and 40 rules apply.', 'Version 3 and 40 rules apply.'].map(keep) };
  assert.equal(dropUnfoundedAssumptions({}, other), 4);
});

test('the model defaults to a 128000-token context', () => {
  const { model } = fixtureConfig();
  assert.equal(model.context, 128000);
});

const LOADED = (extra = {}) => ({ all_models_loaded: [{ model_name: 'm a/b',
  backend_url: 'http://127.0.0.1:8001/v1', recipe_options: { ctx_size: 65536 }, ...extra }] });
const NOT_LOADED = { all_models_loaded: [] };
const windowClient = (routes, urls = []) => modelClient({ endpoint: 'http://localhost:13305/api/v1',
  name: 'm a/b', fetchImpl: async (url, options = {}) => {
    urls.push({ url: String(url), method: options.method ?? 'GET' });
    const hit = Object.entries(routes).find(([suffix]) => String(url).endsWith(suffix));
    if (!hit || hit[1] === 'throw') throw new Error('unreachable');
    const { status = 200, body = hit[1] } = typeof hit[1]?.status === 'number' ? hit[1] : {};
    return { ok: status >= 200 && status < 300, status, json: async () => body };
  } });

test('the context window comes from the backend, the loaded entry, or the saved options', async () => {
  assert.deepEqual(await windowClient({ '/health': LOADED(), '/props': 'throw' }).contextWindow(), { size: 65536, guess: false });
  const props = { default_generation_settings: { n_ctx: 32768 } };
  assert.deepEqual(await windowClient({ '/health': LOADED(), '/props': props }).contextWindow(), { size: 32768, guess: false });
  const saved = windowClient({ '/health': NOT_LOADED,
    '/models/m%20a%2Fb': { recipe_options: { ctx_size: 49152 } } });
  assert.deepEqual(await saved.contextWindow(), { size: 49152, guess: false });
});

test('the context window is null when nothing can be read', async () => {
  assert.equal(await windowClient({}).contextWindow(), null);
  assert.equal(await windowClient({ '/health': NOT_LOADED, '/models/m%20a%2Fb': {} }).contextWindow(), null);
});

const SAVED_SIZE = (size) => ({ recipe_options: { ctx_size: size } });

test('a failed health check reads the saved window as a guess', async () => {
  const client = windowClient({ '/health': 'throw', '/models/m%20a%2Fb': SAVED_SIZE(65536) });
  assert.deepEqual(await client.contextWindow(), { size: 65536, guess: true });
});

test('a health check that answers with an error or no loaded list gives a guess', async () => {
  const saved = { '/models/m%20a%2Fb': SAVED_SIZE(65536) };
  const busy = windowClient({ '/health': { status: 500, body: { error: 'busy' } }, ...saved });
  assert.deepEqual(await busy.contextWindow(), { size: 65536, guess: true });
  const noList = windowClient({ '/health': {}, ...saved });
  assert.deepEqual(await noList.contextWindow(), { size: 65536, guess: true });
  // The same body with a loaded model listed would be read as sure.
  const body = { status: 500, body: LOADED() };
  assert.deepEqual(await windowClient({ '/health': body, '/props': 'throw', ...saved }).contextWindow(),
    { size: 65536, guess: true });
});

test('a guess lowers the window but never raises a smaller one', async () => {
  const { readWindow } = await import('./phases.mjs');
  const config = fixtureConfig({ model: { endpoint: 'http://localhost:1/v1', name: 'm',
    context: 128000, maxOutput: 500, reasoningOutput: 500 } });
  const run = async (health, saved, window) => {
    const ctx = { config, job: { id: 'j' }, logs: { status() {}, detail() {} }, window,
      model: windowClient({ '/health': health, '/models/m%20a%2Fb': SAVED_SIZE(saved) }) };
    await readWindow(ctx, 'p');
    return ctx.window;
  };
  assert.equal(await run('throw', 65536, undefined), 65536);
  assert.equal(await run('throw', 128000, 32768), 32768);
  assert.equal(await run({ status: 500, body: { error: 'busy' } }, 65536, undefined), 65536);
  assert.equal(await run({ status: 500, body: { error: 'busy' } }, 128000, 32768), 32768);
  assert.equal(await run({}, 65536, undefined), 65536);
  assert.equal(await run({}, 128000, 32768), 32768);
});

test('the fallback window is per slot', async () => {
  const size = async (args) => (await windowClient({ '/health': LOADED({ recipe_options:
    { ctx_size: 131072, ...(args === undefined ? {} : { llamacpp_args: args }) } }), '/props': 'throw' })
    .contextWindow()).size;
  assert.equal(await size('--jinja -np 2'), 65536);
  assert.equal(await size('--parallel 4 --jinja'), 32768);
  assert.equal(await size('--jinja'), 131072);
  assert.equal(await size(undefined), 131072);
  assert.equal(await size('-np x'), 131072);
  const saved = windowClient({ '/health': NOT_LOADED, '/models/m%20a%2Fb':
    { recipe_options: { ctx_size: 131072, llamacpp_args: '-np 2' } } });
  assert.deepEqual(await saved.contextWindow(), { size: 65536, guess: false });
});

const windowReader = async (config, reads) => {
  const { readWindow } = await import('./phases.mjs');
  const warns = [];
  const ctx = { config, job: { id: 'j' }, model: { contextWindow: async () => reads.shift() },
    logs: { status: (fields) => { if (fields.event === 'warn') warns.push(fields); }, detail() {} } };
  return { ctx, warns, read: () => readWindow(ctx, 'p') };
};

test('a sure size after a guess raises the window back', async () => {
  const config = fixtureConfig({ model: { endpoint: 'http://localhost:1/v1', name: 'm',
    context: 128000, maxOutput: 500, reasoningOutput: 500 } });
  const { ctx, read } = await windowReader(config,
    [{ size: 32768, guess: true }, { size: 65536, guess: false }]);
  await read();
  assert.equal(ctx.window, 32768);
  await read();
  assert.equal(ctx.window, 65536);
});

test('a guess too small never fails a job, but a sure size that small does', async () => {
  const config = fixtureConfig({ model: { endpoint: 'http://localhost:1/v1', name: 'm',
    context: 20000, maxOutput: 500, reasoningOutput: 500 } });
  const { ctx, warns, read } = await windowReader(config,
    [{ size: 7000, guess: false }, { size: 2800, guess: true }, { size: 2800, guess: true }]);
  await read();
  await read();
  await read();
  assert.equal(ctx.window, 7000);
  assert.deepEqual(warns.map((w) => w.reason), ['server-window', 'server-window-unknown']);
  const first = await windowReader(config, [{ size: 2800, guess: true }]);
  await first.read();
  assert.equal(first.ctx.window, 20000);
  const sure = await windowReader(config, [{ size: 2800, guess: false }]);
  await assert.rejects(sure.read(),
    (error) => error instanceof ModelError && error.code === 'window-too-small');
});

test('a guess is logged only when it lowers the window, and carries the guess marker', async () => {
  const config = fixtureConfig({ model: { endpoint: 'http://localhost:1/v1', name: 'm',
    context: 20000, maxOutput: 500, reasoningOutput: 500 } });
  const same = await windowReader(config, [{ size: 9000, guess: false }, { size: 12000, guess: true }]);
  await same.read();
  await same.read();
  assert.equal(same.warns.filter((w) => w.reason === 'server-window').length, 1);
  assert.equal(same.warns[0].guess, undefined);
  const lower = await windowReader(config, [{ size: 9000, guess: false }, { size: 8000, guess: true }]);
  await lower.read();
  await lower.read();
  assert.equal(lower.ctx.window, 8000);
  assert.equal(lower.warns[1].reason, 'server-window');
  assert.equal(lower.warns[1].guess, true);
});

test('a loaded entry with no backend and no options reads no saved window', async () => {
  const urls = [];
  const client = windowClient({ '/health': { all_models_loaded: [{ model_name: 'm a/b' }] },
    '/models/m%20a%2Fb': { recipe_options: { ctx_size: 128000 } } }, urls);
  assert.equal(await client.contextWindow(), null);
  assert.ok(!urls.some(({ url }) => url.includes('/models/')), 'the saved route was requested');
});

test('reading the context window calls only loopback addresses, and only with GET', async () => {
  const urls = [];
  await windowClient({ '/health': LOADED(), '/props': 'throw' }, urls).contextWindow();
  await windowClient({ '/health': NOT_LOADED, '/models/m%20a%2Fb': {} }, urls).contextWindow();
  assert.ok(urls.some(({ url }) => url.endsWith('/props')));
  assert.ok(urls.some(({ url }) => url.endsWith('/models/m%20a%2Fb')));
  for (const { url, method } of urls) {
    assert.ok(/^http:\/\/(localhost:13305|127\.0\.0\.1:8001)\//.test(url), url);
    assert.equal(method, 'GET');
  }
});

test('a server window smaller than the config is the budget, and is warned about once', async () => {
  const { ask } = await import('./phases.mjs');
  const config = fixtureConfig({ model: { endpoint: 'http://localhost:1/v1', name: 'm',
    context: 20000, maxOutput: 500, reasoningOutput: 500 } });
  const warns = [];
  const ctx = { config, calls: 0, tokens: { prompt: 0, output: 0 }, job: { id: 'j' },
    logs: { status: (fields) => { if (fields.event === 'warn') warns.push(fields); }, detail() {} },
    model: { ...fakeModel(), contextWindow: async () => ({ size: 7000, guess: false }) } };
  const options = { phase: 'phase1', step: 's', reasoning: false, inputs: [['Doc', 'x'.repeat(30000)]],
    schema: { type: 'object' }, task: 't' };
  // About 10,000 tokens: fits 20000, not 7000.
  for (let i = 0; i < 2; i += 1) {
    await assert.rejects(ask(ctx, options), (error) => error instanceof ModelError && error.code === 'too-big');
  }
  assert.deepEqual(warns.map(({ reason, context, serverContext }) => ({ reason, context, serverContext })),
    [{ reason: 'server-window', context: 20000, serverContext: 7000 }]);
});

test('a server window with no room for a prompt fails the job', async () => {
  const config = fixtureConfig();
  const model = { ...fakeModel(), contextWindow: async () => ({ size: 1000, guess: false }) };
  const result = await runJob(config, { issue: '501', change: '7001' }, { model, echo: false });
  assert.equal(result.ok, false);
  assert.equal(result.reason, 'model:window-too-small');
});

test('an unreadable server window falls back to the config and is warned about once', async () => {
  const config = fixtureConfig();
  const model = { ...fakeModel(), contextWindow: async () => null };
  const result = await runJob(config, { issue: '501', change: '7001' }, { model, echo: false });
  assert.equal(result.ok, true, JSON.stringify(result));
  const warns = statusLines(result.outDir).filter((l) => l.reason === 'server-window-unknown');
  assert.equal(warns.length, 1);
});

test('a server window just above the reply and reserve but with no input room fails the job', async () => {
  // 2800 clears the reasoning reply, the 2048 reserve and the system text, with
  // almost nothing left for a document.
  const config = fixtureConfig({ model: { endpoint: 'http://localhost:1/v1', name: 'm',
    context: 20000, maxOutput: 500, reasoningOutput: 500 } });
  const model = { ...fakeModel(), contextWindow: async () => ({ size: 2800, guess: false }) };
  const { readWindow } = await import('./phases.mjs');
  const ctx = { config, job: { id: 'j' }, model, logs: { status() {}, detail() {} } };
  await assert.rejects(readWindow(ctx, 'intake'),
    (error) => error instanceof ModelError && error.code === 'window-too-small');
  const result = await runJob(config, { issue: '501', change: '7001' }, { model, echo: false });
  assert.equal(result.ok, false);
  assert.equal(result.reason, 'model:window-too-small');
});

test('splitText with no token budget is a window-too-small error', () => {
  for (const tokens of [0, -1, -500]) {
    assert.throws(() => splitText('some text', tokens),
      (error) => error instanceof ModelError && error.code === 'window-too-small');
  }
});

test('an unreadable window after a known smaller one keeps the smaller one', async () => {
  const { readWindow } = await import('./phases.mjs');
  const config = fixtureConfig({ model: { endpoint: 'http://localhost:1/v1', name: 'm',
    context: 20000, maxOutput: 500, reasoningOutput: 500 } });
  const sizes = [{ size: 7000, guess: false }, null, null];
  const warns = [];
  const ctx = { config, job: { id: 'j' }, model: { contextWindow: async () => sizes.shift() },
    logs: { status: (fields) => { if (fields.event === 'warn') warns.push(fields.reason); }, detail() {} } };
  await readWindow(ctx, 'phase1');
  await readWindow(ctx, 'phase1');
  await readWindow(ctx, 'phase1');
  assert.equal(ctx.window, 7000);
  assert.deepEqual(warns, ['server-window', 'server-window-unknown']);
});

test('the context window is read afresh on every call', async () => {
  const routes = { '/health': LOADED({ recipe_options: { ctx_size: 65536 } }), '/props': 'throw' };
  const client = windowClient(routes);
  assert.deepEqual(await client.contextWindow(), { size: 65536, guess: false });
  routes['/health'] = LOADED({ recipe_options: { ctx_size: 32768 } });
  assert.deepEqual(await client.contextWindow(), { size: 32768, guess: false });
});

test('the loaded entry whose model_name matches is the one used', async () => {
  const other = { model_name: 'other', backend_url: 'http://127.0.0.1:8002/v1',
    recipe_options: { ctx_size: 1111 } };
  const health = { all_models_loaded: [other, ...LOADED().all_models_loaded] };
  assert.deepEqual(await windowClient({ '/health': health, '/props': 'throw' }).contextWindow(), { size: 65536, guess: false });
  const reversed = { all_models_loaded: [...LOADED().all_models_loaded, other] };
  assert.deepEqual(await windowClient({ '/health': reversed, '/props': 'throw' }).contextWindow(), { size: 65536, guess: false });
});

test('a loaded model with no readable size does not fall back to the saved options', async () => {
  const urls = [];
  const client = windowClient({ '/health': LOADED({ recipe_options: {} }), '/props': 'throw',
    '/models/m%20a%2Fb': { recipe_options: { ctx_size: 128000 } } }, urls);
  assert.equal(await client.contextWindow(), null);
  assert.ok(!urls.some(({ url }) => url.endsWith('/models/m%20a%2Fb')));
});

test('the floor uses the larger reply, so a window only that floor rejects fails', async () => {
  const { readWindow } = await import('./phases.mjs');
  const accepts = async (cfg, size) => {
    try {
      await readWindow({ config: cfg, job: { id: 'j' }, model: { contextWindow: async () => ({ size, guess: false }) },
        logs: { status() {}, detail() {} } }, 'p');
      return true;
    } catch (error) {
      if (error instanceof ModelError && error.code === 'window-too-small') return false;
      throw error;
    }
  };
  const model = (maxOutput) => fixtureConfig({ model: { endpoint: 'http://localhost:1/v1', name: 'm',
    context: 20000, maxOutput, reasoningOutput: 500 } });
  // The smallest window that leaves input room when the reasoning reply is the only reserve.
  let least = 3000;
  while (!await accepts(model(500), least)) least += 1;
  // A larger plain reply raises the floor, so a window just above `least` is refused.
  assert.equal(await accepts(model(3000), least + 100), false);
  assert.equal(await accepts(model(3000), least + 3000), true);
});

test('a window that is zero, negative, fractional or text falls through to the next source', async () => {
  for (const bad of [0, -4096, 4096.5, '4096']) {
    const props = { default_generation_settings: { n_ctx: bad } };
    assert.deepEqual(await windowClient({ '/health': LOADED(), '/props': props }).contextWindow(), { size: 65536, guess: false },
      `props ${JSON.stringify(bad)}`);
    const saved = windowClient({ '/health': LOADED({ recipe_options: { ctx_size: bad } }), '/props': props,
      '/models/m%20a%2Fb': { recipe_options: { ctx_size: 49152 } } });
    assert.equal(await saved.contextWindow(), null, `loaded ${JSON.stringify(bad)}`);
    assert.equal(await windowClient({ '/health': NOT_LOADED,
      '/models/m%20a%2Fb': { recipe_options: { ctx_size: bad } } }).contextWindow(), null);
  }
});
