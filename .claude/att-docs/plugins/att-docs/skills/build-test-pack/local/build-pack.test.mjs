// Runs the local pipeline end to end against the synthetic fixtures, with a
// model that answers every call from its schema and a stub builder.
//
//   node --test plugins/att-docs/skills/build-test-pack/local/build-pack.test.mjs

import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { addJob, claimStale, cutoffAfter, drainQueue, jobFrom, jobStatus, lockHeld, parseArgs, readQueue,
  summaryLines }
  from './build-pack.mjs';
import { loadConfig } from './config.mjs';
import { createPauser, pausedPath } from './pause.mjs';
import { ModelError, localEndpoint, modelClient } from './model.mjs';
import { batches, splitText } from './phases.mjs';
import { runJob } from './run.mjs';
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
  // Intake picked documents from the index; the export gave the master's IDs, retired ones dropped.
  assert.deepEqual(pack.rules.map((rule) => rule.id).sort(), [
    'BR-LIB.UC01-001', 'BR-LIB.UC01-002', 'BR-LIB.UC01-003', 'BR-LIB.UC01-004', 'BR-LIB.UC01-005',
  ]);
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
  assertContentFree(read(path.join(result.outDir, 'status.log')));
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
    phase6: (value) => ({ ...value, cards: value.cards.map((card) => ({ ...card, title: 'REJECT' })) }),
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
    phase6: (value) => ({ ...value, cards: value.cards.map((card) => ({ ...card, title: 'REJECT' })) }),
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
  assert.deepEqual(queue.jobs.map((row) => row.status), ['passed', 'failed', 'queued']);
  const lines = summaryLines(queue);
  assert.match(lines[1], /stopped at phase3 \(gate:unclassified-rule\)/);
  assert.equal(cutoffAfter(new Date('2026-10-27T22:00:00'), '07:00').getDate(), 28);
  assert.throws(() => cutoffAfter(new Date(), '7am'), /HH:MM/);
});

test('the nightly queue takes no job outside its window and fails interrupted rows', async () => {
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
  assert.deepEqual(ran, ['issue-777']);
  const rows = readQueue(config).jobs;
  assert.deepEqual(rows.map((row) => [row.status, row.reason]),
    [['failed', 'interrupted'], ['passed', null]]);
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
    { id: 'issue-100', added: false, marked: true });
  const [row] = readQueue(config).jobs;
  assert.equal(row.now, true);
  assert.equal(row.resume, true);
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
  const model = fakeModel();
  const derived = await runJob(noRules, { issue: '501', change: '7001' }, { model, echo: false });
  assert.equal(derived.ok, true);
  assert.ok(model.calls.some((call) => /derive/.test(call.schemaName)));
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
