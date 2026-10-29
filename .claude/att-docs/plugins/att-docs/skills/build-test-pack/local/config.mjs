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

/** How many times a job is tried before it is flagged and dropped from the queue. */
export const MAX_TRIES = 2;

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
  // rest of a 150k context adds up to a quarter hour, so a call waits up to two
  // and a half hours. The model server's context and its own request time-out
  // have to be at least as large.
  const model = {
    temperature: 0.1, context: 153600, maxOutput: 16384, reasoningOutput: 40960,
    timeoutMinutes: 150, ...raw.model,
  };
  localEndpoint(model.endpoint);
  if (!model.name) throw new Error('config model.name is missing');
  if (!Number.isFinite(model.temperature) || model.temperature < 0 || model.temperature > 0.2) {
    throw new Error('config model.temperature must be between 0 and 0.2');
  }
  for (const key of REQUIRED_REFERENCES) {
    if (!raw.reference?.[key]) throw new Error(`config reference.${key} is missing`);
  }
  for (const key of ['module', 'command']) {
    if (!raw.builder?.[key]) throw new Error(`config builder.${key} is missing`);
  }
  const pause = { units: [], scope: 'system', busyProcess: null, pollSeconds: 5, ...raw.pause };
  if (!Array.isArray(pause.units) || pause.units.some((unit) => typeof unit !== 'string' || !unit)) {
    throw new Error('config pause.units must be a list of unit names');
  }
  if (!['system', 'user'].includes(pause.scope)) {
    throw new Error("config pause.scope must be 'system' or 'user'");
  }
  if (!Number.isFinite(pause.pollSeconds) || pause.pollSeconds <= 0) {
    throw new Error('config pause.pollSeconds must be a positive number');
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
