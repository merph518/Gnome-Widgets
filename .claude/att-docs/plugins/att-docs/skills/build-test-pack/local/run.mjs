// Runs one job, intake through Phase 10, and writes its pack, its workbook and
// its two logs to the job's own output folder. After each phase passes, the
// job's state goes to work/checkpoint.json, so a job run again with `resume`
// starts at the phase that stopped it.

import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import { fill, loadReference } from './config.mjs';
import { ModelError, modelClient } from './model.mjs';
import { jobLogs } from './status.mjs';
import * as P from './phases.mjs';

/** The objective config names for a set, else the usual name if the builder lists it, else none. */
const setObjective = (named, builder, usual) => named ?? (builder.OBJECTIVES.includes(usual) ? usual : null);

const DEFAULTS = {
  IMPACT_CLASSES: ['Direct Change', 'Indirect Impact', 'Regression', 'Not Impacted'],
  COVERAGE_STATUSES: ['Covered', 'Partially Covered', 'Weakly Covered', 'Missing', 'Not Applicable'],
  CONFIDENCE_LEVELS: ['High', 'Medium', 'Low'],
  DERIVATIONS: ['Requirement', 'Quality'],
  INCLUSIONS: ['Included', 'Supporting Context Only', 'Excluded'],
};

/** A job's id: its issue and change, or its suite, plus when it was added. */
export const jobId = (job) => (job.suite ? `suite-${job.suite}` : `issue-${job.issue}`
  + (job.change ? `-change-${job.change}` : ''));

/** The builder's validation lines, counted by status. Its notes stay in detail.log. */
function countStatuses(stdout) {
  const counts = { pass: 0, limited: 0, fail: 0 };
  for (const line of stdout.split('\n')) {
    if (line.startsWith('PASS WITH LIMITATIONS')) counts.limited += 1;
    else if (line.startsWith('PASS')) counts.pass += 1;
    else if (line.startsWith('FAIL')) counts.fail += 1;
  }
  return counts;
}

/** The phases in the order a job runs them; a checkpoint names the last one passed. */
export const PHASES = ['intake', 'phase1', 'phase2', 'phase3', 'phase4', 'phase5', 'phase6',
  'phase7', 'phase8', 'phase9-checklist', 'phase9-confidence', 'phase9-senior',
  'phase9-revalidate', 'phase10'];

// What a run builds for itself from the config; everything else on ctx is the job's state.
const SETUP = new Set(['config', 'job', 'logs', 'builder', 'suiteMerge', 'model', 'ref', 'private',
  'existingTests', 'riskLevels', 'coreObjective', 'suiteSetOrder', 'suiteRunSets', 'fullCoverageObjective', 'breakItObjective', 'rulesFresh']);

const checkpointPath = (outDir) => path.join(outDir, 'work', 'checkpoint.json');

function readCheckpoint(outDir) {
  try {
    const saved = JSON.parse(fs.readFileSync(checkpointPath(outDir), 'utf8'));
    return PHASES.includes(saved.phase) ? saved : null;
  } catch {
    return null;
  }
}

export async function runJob(config, job, { model, echo = true, now = Date.now } = {}) {
  const id = job.id ?? jobId(job);
  const outDir = path.join(config.output, id);
  const saved = job.resume ? readCheckpoint(outDir) : null;
  // A job run again from the start begins with an empty folder, so no file from
  // the last run is read as this one's. A resumed job keeps its folder and logs.
  if (!saved) fs.rmSync(outDir, { recursive: true, force: true });
  fs.mkdirSync(path.join(outDir, 'work'), { recursive: true });
  const logs = jobLogs(outDir, { echo });
  const started = now();
  const builderModule = await import(pathToFileURL(config.at(config.builder.module)).href);
  if (typeof builderModule.buildPack !== 'function' || !Array.isArray(builderModule.OBJECTIVES)) {
    throw new Error('config builder.module exports no buildPack and OBJECTIVES');
  }
  const suiteMerge = job.suite && config.suiteMerge?.module
    ? await import(pathToFileURL(config.at(config.suiteMerge.module)).href) : null;
  if (job.suite && typeof suiteMerge?.mergeSuitePack !== 'function') {
    throw new Error('a suite job needs suiteMerge.module exporting mergeSuitePack');
  }
  const builder = { ...DEFAULTS, ...builderModule };
  const ctx = {
    config, job: { ...job, id }, logs, builder, suiteMerge,
    model: model ?? modelClient(config.model),
    ref: loadReference(config),
    pack: {},
    riskLevels: config.riskLevels ?? ['High', 'Medium', 'Low'],
    coreObjective: config.coreObjective ?? builder.OBJECTIVES[0],
    fullCoverageObjective: setObjective(config.fullCoverageObjective, builder, 'Full Coverage Required Run'),
    breakItObjective: setObjective(config.breakItObjective, builder, 'BREAK IT'),
    suiteSetOrder: suiteMerge?.SUITE_SET_ORDER ?? builder.OBJECTIVES.slice(1),
    suiteRunSets: config.suiteMerge?.runSets ?? ['Regression Testing', 'Full Coverage Required Run'],
    calls: 0, repairs: 0, droppedObjectives: 0, derived: 0, reviewIssues: 0, reuse: [],
    tokens: { prompt: 0, output: 0 },
    private(name, value) {
      fs.writeFileSync(path.join(outDir, 'work', name), `${JSON.stringify(value, null, 1)}\n`);
    },
  };
  if (config.inputs.existingTests) {
    const { globFiles } = await import('./config.mjs');
    ctx.existingTests = globFiles(config.root, fill(config.inputs.existingTests, job))
      .map((file) => fs.readFileSync(file, 'utf8')).join('\n\n');
  }

  // The merged suite pack is a separate object from ctx.pack once Phase 7 passes.
  let pack = ctx.pack;
  const done = saved ? PHASES.indexOf(saved.phase) : -1;
  if (saved) {
    Object.assign(ctx, saved.state);
    pack = saved.pack ?? ctx.pack;
    logs.status({ job: id, phase: PHASES[done + 1] ?? 'done', event: 'resume', after: saved.phase });
  }
  const checkpoint = (name) => {
    const state = Object.fromEntries(Object.entries(ctx).filter(([key]) => !SETUP.has(key)));
    const temp = `${checkpointPath(outDir)}.tmp`;
    fs.writeFileSync(temp, JSON.stringify({ phase: name, state,
      pack: pack === ctx.pack ? undefined : pack }));
    fs.renameSync(temp, checkpointPath(outDir));
  };

  let phase = 'intake';
  const step = async (name, fn) => {
    phase = name;
    if (PHASES.indexOf(name) <= done) return {};
    const t = now();
    logs.status({ job: id, phase: name, event: 'start' });
    const counts = await fn();
    logs.status({ job: id, phase: name, event: 'pass', ms: now() - t, ...counts });
    checkpoint(name);
    return counts;
  };
  const packName = fill(job.suite ? config.suitePackFile : config.packFile, job);
  const packPath = path.join(outDir, packName);
  let written = null;
  try {
    await step('intake', () => P.intake(ctx));
    await step('phase1', () => P.phase1(ctx));
    await step('phase2', async () => {
      const counts = await P.phase2(ctx);
      ctx.derived = counts.derived;
      return counts;
    });
    await step('phase3', () => P.phase3(ctx));
    await step('phase4', () => P.phase4(ctx));
    await step('phase5', () => P.phase5(ctx));
    await step('phase6', () => P.phase6(ctx));
    await step('phase7', async () => {
      const counts = await P.phase7(ctx);
      if (job.suite) pack = P.mergeSuite(ctx);
      return counts;
    });
    // The first build checks everything Phase 9 does not fill; the review's
    // sheets wait for it.
    await step('phase8', async () => {
      await P.phase8(ctx, pack, 'build', P.REVIEW_SHEETS);
      return { repairs: ctx.repairs };
    });
    await step('phase9-checklist', async () => {
      const counts = await P.phase9Checklist(ctx, pack);
      ctx.reviewIssues = counts.issues;
      const fixes = await P.phase9Fix(ctx, pack);
      return { ...counts, fixRounds: fixes.rounds };
    });
    await step('phase9-confidence', () => P.phase9Confidence(ctx, pack));
    await step('phase9-senior', () => P.phase9SeniorReview(ctx, pack));
    await step('phase9-revalidate', async () => {
      delete pack.revalidation;
      await P.phase8(ctx, pack, 'rebuild');
      const again = await P.revalidate(ctx, pack);
      return { revalidated: again.passed, remaining: again.remaining };
    });
    await step('phase10', () => P.phase10(ctx, pack));
    pack = P.reconcile(ctx, pack);
    fs.writeFileSync(packPath, `${JSON.stringify(pack, null, 1)}\n`);

    // The final write goes through the repository's own builder command, as the skill runs it.
    phase = 'phase8';
    const argv = config.builder.command.map((part) => fill(part, { pack: packPath, out: outDir }));
    const result = spawnSync(argv[0], argv.slice(1), { cwd: config.root, encoding: 'utf8' });
    logs.detail('builder final', `${result.stdout}\n${result.stderr}`);
    const counts = countStatuses(result.stdout);
    // A pack whose revalidation failed builds with Workbook Validation FAIL, and the
    // workbook is written so the reviewer can see what remains; any other FAIL is a build failure.
    const failLines = result.stdout.split('\n').filter((line) => line.startsWith('FAIL'));
    const revalidationFailed = pack.revalidation?.passed === false;
    const onlyValidation = failLines.length > 0
      && failLines.every((line) => /Workbook Validation\s*$/.test(line));
    if (result.status !== 0 && !(revalidationFailed && onlyValidation)) {
      throw new P.GateError('phase8', 'builder-final-fail', { sheets: counts.fail });
    }
    const workbook = fs.readdirSync(outDir).find((name) => name.endsWith('.xlsx')) ?? null;
    if (revalidationFailed) {
      // A workbook that does not show the FAIL is removed rather than left reading PASS.
      if (workbook && !onlyValidation) fs.rmSync(path.join(outDir, workbook));
      else if (workbook) written = path.join(outDir, workbook);
      phase = 'phase9-revalidate';
      throw new P.GateError('phase9', 'revalidation-failed', { remaining: pack.revalidation.remaining.length });
    }
    const summary = { job: id, phase: 'done', event: 'pass', ms: now() - started,
      calls: ctx.calls, promptTokens: ctx.tokens.prompt, outputTokens: ctx.tokens.output,
      sheetsPass: counts.pass, sheetsLimited: counts.limited, repairs: ctx.repairs };
    logs.status(summary);
    return { ok: true, id, outDir, packPath, workbook: workbook && path.join(outDir, workbook),
      ...summary };
  } catch (error) {
    const reason = error instanceof P.GateError ? `gate:${error.code}`
      : error instanceof ModelError ? `model:${error.code}` : 'error';
    logs.detail('stopped', error.stack ?? String(error));
    const counts = error instanceof P.GateError ? error.counts : {};
    logs.status({ job: id, phase, event: 'fail', reason, ms: now() - started, calls: ctx.calls,
      ...counts });
    if (Object.keys(ctx.pack).length) {
      fs.writeFileSync(path.join(outDir, 'work', 'partial-pack.json'),
        `${JSON.stringify(ctx.pack, null, 1)}\n`);
    }
    return { ok: false, id, outDir, phase, reason, ms: now() - started, packPath, workbook: written };
  }
}
