// Reads the consuming repository's pipeline config: where its reference
// material, documents, exports, builder and queue are. Every path in it is
// relative to the repository root, which is `repoRoot` relative to the config
// file itself.

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { localEndpoint } from './model.mjs';

const REQUIRED_REFERENCES = ['procedure', 'workbookStandard', 'implementationGuide'];

// The shape of a rule export's rows. A consumer whose rule master differs
// overrides any of these under `ruleShape` in its config.
export const RULE_SHAPE = {
  matrixColumns: ['path', 'requirement_type', 'rule_category', 'name', 'description',
    'source_document', 'source_page', 'rule_summary', 'risk_level'],
  categories: ['Validation', 'Workflow', 'State Transition', 'Security', 'Batch', 'Reporting',
    'Event Generation', 'Conditional Display', 'Navigation', 'Integration', 'Data Integrity',
    'Calculation', 'Notification', 'Role Restriction', 'Timing/Temporal'],
  riskLevels: ['High', 'Medium', 'Low'],
  statuses: ['active', 'retired', 'superseded'],
  requirementType: 'Business Rule',
  prefixPattern: '^BR-',
  ruleIdPattern: '\\d{3}',
};

/** The `phase` names a reasoning call carries; `model.reasoningOutputByPhase` is keyed by them. */
export const REASONING_PHASES = ['phase1', 'phase3', 'phase4', 'phase5', 'phase9'];

/** How many times a job is tried before it is flagged and dropped from the queue. */
export const MAX_TRIES = 2;

/** The reason a run stops when memory stays low; such a stop is not one of a job's tries. */
export const MEMORY_STOP = 'memory:low';

/** The failures that count toward MAX_TRIES: a stop for low memory says nothing about the job. */
export const countedTries = (failures = []) => failures.filter((f) => f.reason !== MEMORY_STOP).length;

/** How many low-memory stops in a row a job gets before it is dropped for a person to look at. */
export const MAX_MEMORY_STOPS = 3;

/** The low-memory stops at the end of a job's failures; a failure of any other kind resets the count. */
export const memoryStops = (failures = []) => {
  let stops = 0;
  for (let i = failures.length - 1; i >= 0 && failures[i].reason === MEMORY_STOP; i -= 1) stops += 1;
  return stops;
};

const fill = (template, values) => String(template).replace(/\{(\w+)\}/g, (whole, key) =>
  (values[key] === undefined ? whole : String(values[key])));
export { fill };

export function loadConfig(configPath) {
  const file = path.resolve(configPath);
  const raw = JSON.parse(fs.readFileSync(file, 'utf8'));
  const root = path.resolve(path.dirname(file), raw.repoRoot ?? '.');
  const at = (relative) => (relative ? path.resolve(root, relative) : undefined);
  // A reasoning call can think for 40k tokens, about 100 minutes at the 7 tokens a
  // second a 27B model makes on a single GPU, and reading a prompt that fills the
  // rest of a 128,000-token context adds up to a quarter hour, so a call waits up
  // to two and a half hours. The pipeline budgets each prompt against the smaller
  // of `context` (128000 by default) and the model server's own window; the
  // server's request time-out has to be at least as long as the call waits.
  const model = {
    temperature: 0.1, context: 128000, maxOutput: 16384, reasoningOutput: 40960,
    timeoutMinutes: 150, ...raw.model,
  };
  // The reply cap for the retry of a thinking call that ran out its output budget; it
  // answers with thinking off, so it never needs more than a plain call's maxOutput.
  if (raw.model?.retryOutput === undefined) model.retryOutput = Math.min(8192, model.maxOutput);
  localEndpoint(model.endpoint);
  if (!model.name) throw new Error('config model.name is missing');
  if (!Number.isFinite(model.temperature) || model.temperature < 0 || model.temperature > 0.2) {
    throw new Error('config model.temperature must be between 0 and 0.2');
  }
  if (raw.model?.retryOutput !== undefined && (!Number.isInteger(model.retryOutput)
    || model.retryOutput < 1024 || model.retryOutput > model.maxOutput)) {
    throw new Error('config model.retryOutput must be a whole number from 1024 to model.maxOutput');
  }
  if (raw.model?.reasoningOutputByPhase !== undefined) {
    const byPhase = model.reasoningOutputByPhase;
    if (!byPhase || typeof byPhase !== 'object' || Array.isArray(byPhase)) {
      throw new Error('config model.reasoningOutputByPhase must be an object of phase caps');
    }
    for (const [phase, cap] of Object.entries(byPhase)) {
      if (!REASONING_PHASES.includes(phase)) {
        throw new Error(`config model.reasoningOutputByPhase.${phase} is not a reasoning phase`
          + ` (${REASONING_PHASES.join(', ')})`);
      }
      if (!Number.isInteger(cap) || cap < 1024 || cap > model.reasoningOutput) {
        throw new Error(`config model.reasoningOutputByPhase.${phase} must be a whole number`
          + ' from 1024 to model.reasoningOutput');
      }
    }
  }
  for (const key of REQUIRED_REFERENCES) {
    if (!raw.reference?.[key]) throw new Error(`config reference.${key} is missing`);
  }
  for (const key of ['module', 'command']) {
    if (!raw.builder?.[key]) throw new Error(`config builder.${key} is missing`);
  }
  const pause = { units: [], scope: 'system', busyProcess: null, pollSeconds: 5, maxWaitMinutes: 60, ...raw.pause };
  if (!Array.isArray(pause.units) || pause.units.some((unit) => typeof unit !== 'string' || !unit)) {
    throw new Error('config pause.units must be a list of unit names');
  }
  if (!['system', 'user'].includes(pause.scope)) {
    throw new Error("config pause.scope must be 'system' or 'user'");
  }
  if (!Number.isFinite(pause.pollSeconds) || pause.pollSeconds <= 0) {
    throw new Error('config pause.pollSeconds must be a positive number');
  }
  // Run once when a queue run ends, to unload the model; an empty command turns it off.
  if (raw.release !== undefined
    && (!raw.release || typeof raw.release !== 'object' || Array.isArray(raw.release))) {
    throw new Error('config release must be an object');
  }
  const release = { command: ['lemonade', 'unload'], timeoutSeconds: 60, ...raw.release };
  if (!Array.isArray(release.command)
    || release.command.some((word) => typeof word !== 'string' || !word)) {
    throw new Error('config release.command must be a list of words');
  }
  if (!Number.isFinite(release.timeoutSeconds) || release.timeoutSeconds <= 0) {
    throw new Error('config release.timeoutSeconds must be a positive number');
  }
  if (!Number.isFinite(pause.maxWaitMinutes) || pause.maxWaitMinutes < 0) {
    throw new Error('config pause.maxWaitMinutes must be a number of minutes, 0 or more');
  }
  // Desktop apps closed before a queue run. Scope patterns must start with a literal app- or
  // snap. prefix and end in .scope, so a pattern can never match a service or a system unit.
  const closeAppsKeys = ['scopes', 'onNow', 'keepIfRunning'];
  if (raw.closeApps !== undefined && (!raw.closeApps || typeof raw.closeApps !== 'object'
    || Array.isArray(raw.closeApps) || Object.keys(raw.closeApps).some((key) => !closeAppsKeys.includes(key)))) {
    throw new Error(`config closeApps must be an object with only ${closeAppsKeys.join(', ')}`);
  }
  const closeApps = { scopes: [], onNow: false, keepIfRunning: ['claude'], ...raw.closeApps };
  const scopePattern = /^(app-|snap\.)(?=[^*?]*[A-Za-z0-9])[A-Za-z0-9@_.:\\*?-]+\.scope$/;
  if (!Array.isArray(closeApps.scopes)
    || closeApps.scopes.some((scope) => typeof scope !== 'string' || !scopePattern.test(scope))) {
    throw new Error('config closeApps.scopes must be a list of app-*.scope or snap.*.scope patterns with a literal part');
  }
  if (typeof closeApps.onNow !== 'boolean') throw new Error('config closeApps.onNow must be true or false');
  if (!Array.isArray(closeApps.keepIfRunning)
    || closeApps.keepIfRunning.some((name) => typeof name !== 'string' || !name || Buffer.byteLength(name) > 15)) {
    // The kernel cuts a process name to 15 characters, so a longer one could never match.
    throw new Error('config closeApps.keepIfRunning must be a list of process names of up to 15 characters');
  }
  // The floor and ceiling come from the measured night in docs/runners/TestPackOffloadPlan.md:
  // available memory fell to 4.6 GiB and swap held about 68% (cold, speeds steady) all night,
  // so both defaults sit just past a healthy run. Measure again after changing the swap setup.
  const memoryKeys = ['enabled', 'minAvailableMiB', 'maxSwapPercent', 'pollSeconds', 'waitMinutes'];
  if (raw.memory !== undefined && (!raw.memory || typeof raw.memory !== 'object' || Array.isArray(raw.memory)
    || Object.keys(raw.memory).some((key) => !memoryKeys.includes(key)))) {
    throw new Error(`config memory must be an object with only ${memoryKeys.join(', ')}`);
  }
  const memory = { enabled: true, minAvailableMiB: 3072, maxSwapPercent: 85, pollSeconds: 30,
    waitMinutes: 20, ...raw.memory };
  if (typeof memory.enabled !== 'boolean') throw new Error('config memory.enabled must be true or false');
  if (!Number.isInteger(memory.minAvailableMiB) || memory.minAvailableMiB < 1) {
    throw new Error('config memory.minAvailableMiB must be a positive whole number');
  }
  if (!Number.isFinite(memory.maxSwapPercent) || memory.maxSwapPercent < 0 || memory.maxSwapPercent > 100) {
    throw new Error('config memory.maxSwapPercent must be a number from 0 to 100');
  }
  if (!Number.isFinite(memory.pollSeconds) || memory.pollSeconds <= 0) {
    throw new Error('config memory.pollSeconds must be a positive number');
  }
  if (!Number.isInteger(memory.waitMinutes) || memory.waitMinutes < 0) {
    throw new Error('config memory.waitMinutes must be a whole number of 0 or more');
  }
  if (raw.cardRulesPerCall !== undefined) {
    throw new Error('config cardRulesPerCall is replaced by cardScenariosPerCall');
  }
  if (!Number.isInteger(raw.cardScenariosPerCall ?? 4) || (raw.cardScenariosPerCall ?? 4) < 1) {
    throw new Error('config cardScenariosPerCall must be a positive whole number');
  }
  if (raw.exclusiveSets !== undefined && typeof raw.exclusiveSets !== 'boolean') {
    throw new Error('config exclusiveSets must be true or false');
  }
  const moduleAbbreviations = raw.moduleAbbreviations ?? {};
  for (const [name, abbreviation] of Object.entries(moduleAbbreviations)) {
    if (!/^[A-Z0-9]{2,6}$/.test(abbreviation)) {
      throw new Error(`config moduleAbbreviations.${name} must be 2 to 6 upper-case letters or digits`);
    }
  }
  const output = raw.output ?? path.join(os.homedir(), '.local/share/build-pack');
  const outputDir = path.resolve(root, output.replace(/^~(?=\/)/, os.homedir()));
  // Where new jobs are listed; each source is read before the nightly run takes a job.
  const queue = { file: '.build-pack-queue.json', start: '22:00', cutoff: '07:00', sources: [],
    ...raw.queue };
  if (!Array.isArray(queue.sources)) throw new Error('config queue.sources must be a list');
  for (const source of queue.sources) {
    if (source?.type === 'folder' && source.path) continue;
    if (source?.type === 'records' && source.glob) continue;
    if (source?.type === 'command' && Array.isArray(source.command) && source.command.length) continue;
    throw new Error('config queue.sources takes folder (path), records (glob) or command (command list)');
  }
  const report = { weeklyDay: 1, sample: 2, maxPriority: 6, ...raw.report };
  if (!Number.isInteger(report.weeklyDay) || report.weeklyDay < 0 || report.weeklyDay > 6) {
    throw new Error('config report.weeklyDay must be a day number from 0 (Sunday) to 6');
  }
  for (const key of ['sample', 'maxPriority']) {
    if (!Number.isInteger(report[key]) || report[key] < 0) {
      throw new Error(`config report.${key} must be a whole number`);
    }
  }
  if (report.seed !== undefined && !/^-?\d+$/.test(String(report.seed))) {
    throw new Error('config report.seed must be a whole number');
  }
  report.dir = path.resolve(root, (report.dir ?? path.join(outputDir, 'reports'))
    .replace(/^~(?=\/)/, os.homedir()));
  return {
    file,
    root,
    at,
    model,
    reference: raw.reference,
    terms: { issue: 'issue', change: 'change', ...raw.terms },
    idFields: {
      issue: 'issue', change: 'change', changeApplies: 'changeApplies',
      description: 'changeDescription', ...raw.idFields,
    },
    packFile: raw.packFile ?? '{issue}_pack.json',
    suitePackFile: raw.suitePackFile ?? '{suite}_pack.json',
    inputs: raw.inputs ?? {},
    // Off unless the config or a job opts in: a document with no extracted rules
    // stops intake instead of having rules derived from its text.
    allowDerivedRules: raw.allowDerivedRules === true,
    ruleShape: { ...RULE_SHAPE, ...raw.ruleShape },
    builder: { retries: 3, ...raw.builder },
    // A document's code or module name to the abbreviation its cards and rules carry as their
    // module, such as INV; a document not listed takes the module and abbreviation Phase 1 names.
    moduleAbbreviations,
    suiteMerge: raw.suiteMerge,
    // Scenarios written per card call.
    cardScenariosPerCall: raw.cardScenariosPerCall ?? 4,
    // The sets an issue pack's cards are assigned to; null finds the objective
    // by its usual name in the builder's list, if it has one.
    fullCoverageObjective: raw.fullCoverageObjective ?? null,
    breakItObjective: raw.breakItObjective ?? null,
    // false: a card may sit in several sets. true: a BREAK IT card sits only in the BREAK IT set.
    exclusiveSets: raw.exclusiveSets === true,
    output: outputDir,
    pause,
    closeApps,
    release,
    memory,
    queue,
    report,
  };
}

/** Files under the root that match a pattern with `*` and `**`, sorted. */
export function globFiles(root, pattern) {
  const parts = pattern.split('/');
  const toRegex = (part) => new RegExp(`^${part.replace(/[.+^${}()|[\]\\]/g, '\\$&')
    .replace(/\*/g, '[^/]*').replace(/\?/g, '[^/]')}$`);
  const found = [];
  const walk = (dir, rest) => {
    if (!rest.length) return;
    const [head, ...tail] = rest;
    let entries;
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    if (head === '**') {
      walk(dir, tail);
      for (const entry of entries) {
        if (entry.isDirectory()) walk(path.join(dir, entry.name), rest);
      }
      return;
    }
    const match = toRegex(head);
    for (const entry of entries) {
      if (!match.test(entry.name)) continue;
      const full = path.join(dir, entry.name);
      if (!tail.length && entry.isFile()) found.push(full);
      else if (tail.length && entry.isDirectory()) walk(full, tail);
    }
  };
  walk(root, parts);
  return [...new Set(found)].sort();
}

/**
 * The reference documents, read once. `chapters(phase)` gives the methodology
 * chapters config names for a phase, each cut from its heading to the next.
 */
export function loadReference(config) {
  const read = (key) => (config.reference[key]
    ? fs.readFileSync(config.at(config.reference[key]), 'utf8') : '');
  const docs = {};
  for (const key of ['procedure', 'workbookStandard', 'implementationGuide', 'glossary',
    'intake', 'understandingGate', 'ruleIntake', 'scope', 'validation', 'revalidation']) {
    docs[key] = read(key);
  }
  const methodology = config.reference.methodology;
  let methodologyLines = [];
  if (methodology?.file) {
    methodologyLines = fs.readFileSync(config.at(methodology.file), 'utf8').split('\n');
  }
  const heading = new RegExp(methodology?.heading ?? '^# Chapter (\\d+)');
  const skipBefore = methodology?.skipBefore ?? 0;

  /** Chapter n's text: its first heading past skipBefore, up to the next heading. */
  function chapter(n) {
    const start = methodologyLines.findIndex((line, i) => i >= skipBefore
      && heading.exec(line)?.[1] === String(n));
    if (start < 0) throw new Error(`methodology chapter ${n} not found`);
    let end = methodologyLines.findIndex((line, i) => i > start && heading.test(line));
    if (end < 0) end = methodologyLines.length;
    return methodologyLines.slice(start, end).join('\n');
  }

  return {
    docs,
    /** The procedure, standard and implementation guide, which every phase keeps. */
    core: [docs.procedure, docs.workbookStandard, docs.implementationGuide, docs.glossary]
      .filter(Boolean),
    chapters(phase) {
      return (methodology?.byPhase?.[phase] ?? []).map(chapter);
    },
  };
}
