// The build, phase by phase, as fixed local-model calls. Each phase writes its
// fields of the pack, its gate runs in code, and a failed gate throws a
// GateError whose code is the only thing the status log records about why.

import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { estimateTokens, ModelError } from './model.mjs';
import { fill, globFiles, RULE_SHAPE } from './config.mjs';
import * as S from './schemas.mjs';
import { revisedDate, rulesStale, shapeProblems, uncitedStruck } from './rules.mjs';
import { readSheet } from './pack.mjs';
import { readXlsx } from './xlsx.mjs';
import { checkPack } from './pack-checks.mjs';

export class GateError extends Error {
  constructor(phase, code, counts = {}) {
    super(`${phase}: ${code}`);
    this.phase = phase;
    this.code = code;
    this.counts = counts;
  }
}

const SYSTEM = `You are one step of a fixed pipeline that builds a software test pack.
The reference material below is the procedure, the workbook standard and the
rules the pack follows; keep every rule it gives for the step you are asked to do.
Do only this step. Answer with JSON matching the schema and nothing else.
Write your own analysis of the inputs. Never copy reference wording into the answer.
Every rule ID you name must be one the step gives you, written exactly as given.`;

const section = (label, text) => `## ${label}\n\n${String(text).trim()}\n`;
const asLines = (rows) => rows.join('\n');
const list = (value) => (Array.isArray(value) ? value
  : value === undefined || value === null || value === '' ? [] : [value]);
const blank = (value) => list(value).every((item) => String(item ?? '').trim() === '');

/** Splits text on paragraph boundaries into pieces of at most `tokens` estimated tokens. */
export function splitText(text, tokens) {
  if (!(tokens > 0)) throw new ModelError('window-too-small', 'the model server window leaves no room for text');
  const limit = tokens * 3;
  const pieces = [];
  let current = '';
  for (const paragraph of String(text).split(/\n\s*\n/)) {
    // A paragraph longer than a piece is cut on line breaks, then on characters.
    const parts = paragraph.length <= limit ? [paragraph]
      : paragraph.split('\n').flatMap((line) => (line.length <= limit ? [line]
        : line.match(new RegExp(`[\\s\\S]{1,${limit}}`, 'g'))));
    for (const part of parts) {
      if (current && current.length + part.length + 2 > limit) {
        pieces.push(current);
        current = '';
      }
      current = current ? `${current}\n\n${part}` : part;
    }
  }
  if (current) pieces.push(current);
  return pieces;
}

/** Groups items into batches whose rendered text stays under `tokens`, at most `max` each. */
export function batches(items, render, tokens, max = Infinity) {
  const out = [];
  let current = [];
  let size = 0;
  for (const item of items) {
    const cost = estimateTokens(render(item));
    if (current.length && (size + cost > tokens || current.length >= max)) {
      out.push(current);
      current = [];
      size = 0;
    }
    current.push(item);
    size += cost;
  }
  if (current.length) out.push(current);
  return out;
}

/** The window every prompt is budgeted against: the smaller of the config's and the server's. */
const budgetWindow = (ctx) => ctx.window ?? ctx.config.model.context;

/**
 * The least room a prompt must leave for inputs once the core references and the
 * reply are in. Documents are split at `room - 1000`, so a window this small
 * leaves pieces of about a page or more. When `maxOutput` is larger than
 * `reasoningOutput` the split room can be smaller; a piece with no room is a
 * `window-too-small` error from `splitText`, not a silent failure.
 */
const MIN_INPUT_ROOM = 2000;

/**
 * Reads the model server's context size and sets ctx.window to the smaller of
 * it and `model.context`. Asked again on every call, so a reload at another
 * size is picked up; each distinct smaller size is logged once. A size marked
 * as a guess can only lower the window, never raise it, and never fails the
 * job: one that leaves no room counts as unread. A size that cannot be
 * read keeps the last server-based window in force, and the config's applies
 * until one has been read; it is logged once. A window
 * with no room left for a prompt is a `window-too-small` error.
 */
export async function readWindow(ctx, phase) {
  const configured = ctx.config.model.context;
  if (typeof ctx.model.contextWindow !== 'function') {
    delete ctx.window;
    return;
  }
  const read = await ctx.model.contextWindow();
  const before = ctx.window ?? configured;
  const { reasoningOutput, maxOutput } = ctx.config.model;
  const floor = Math.max(reasoningOutput, maxOutput) + 2048 + estimateTokens(SYSTEM);
  const tooSmall = () => ctx.window - floor <= 0
    || room(ctx, true, ctx.ref?.core ?? []) < MIN_INPUT_ROOM;
  let server = read?.size ?? null;
  // An unreadable size keeps the last server-based window; the config's applies
  // only until one has been read. A guess never raises the window, and a guess
  // that would leave no room is treated as unknown: only a sure size fails a job.
  ctx.window = !server ? before
    : read.guess ? Math.min(before, server) : Math.min(configured, server);
  if (server && read.guess && tooSmall()) {
    ctx.window = before;
    server = null;
  }
  const noted = ctx.windowNoted ?? (ctx.windowNoted = new Set());
  if (!server && !noted.has('unknown')) {
    noted.add('unknown');
    ctx.logs.status({ job: ctx.job.id, phase, event: 'warn', reason: 'server-window-unknown' });
  } else if (server && server < configured && !noted.has(server) && (!read.guess || server < before)) {
    noted.add(server);
    ctx.logs.status({ job: ctx.job.id, phase, event: 'warn', reason: 'server-window',
      context: configured, serverContext: server, ...(read.guess ? { guess: true } : {}) });
  }
  if (tooSmall()) {
    throw new ModelError('window-too-small', 'the model server window leaves no room for a prompt');
  }
}

/**
 * The pipeline's one way to call the model. Checks the token count first and
 * throws `too-big` rather than truncating, retries a failed call once with
 * thinking off, and logs only counts and timings.
 */
export async function ask(ctx, { phase, step, reasoning, refs = [], inputs, schema, task }) {
  const system = [SYSTEM, ...refs.filter(Boolean).map((text, i) => section(`Reference ${i + 1}`, text))]
    .join('\n');
  const user = [section('Task', task), ...inputs.filter(([, text]) => !blank(text))
    .map(([label, text]) => section(label, text))].join('\n');
  const maxTokens = reasoning ? ctx.config.model.reasoningOutput : ctx.config.model.maxOutput;
  await readWindow(ctx, phase);
  const promptTokens = await ctx.model.countTokens(`${system}\n${user}`);
  if (promptTokens + maxTokens + 512 > budgetWindow(ctx)) {
    throw Object.assign(new ModelError('too-big', 'prompt does not fit the context'),
      { promptTokens });
  }
  let think = reasoning;
  for (let attempt = 1; attempt <= 2; attempt += 1) {
    ctx.calls += 1;
    try {
      const { value, usage } = await ctx.model.json({
        system, user, schema, schemaName: `${phase}_${step}`.replace(/\W+/g, '_'),
        reasoning: think, maxTokens: think ? ctx.config.model.reasoningOutput : ctx.config.model.maxOutput,
      });
      ctx.logs.status({ job: ctx.job.id, phase, step, event: 'call', attempt, reasoning: think,
        promptTokens: usage.promptTokens, outputTokens: usage.outputTokens, ms: usage.ms });
      ctx.logs.detail(`${phase} ${step} reply`, value);
      ctx.tokens.prompt += usage.promptTokens;
      ctx.tokens.output += usage.outputTokens;
      return S.unkey(schema, value);
    } catch (error) {
      if (!(error instanceof ModelError) || attempt === 2) throw error;
      ctx.logs.status({ job: ctx.job.id, phase, step, event: 'retry', reason: error.code,
        outputTokens: error.usage?.outputTokens ?? 0, ms: error.usage?.ms ?? 0 });
      // A call that failed while thinking most often thought too long: it ran out
      // the output budget or the server's time. The retry answers without it.
      think = false;
    }
  }
  throw new Error('unreachable');
}

/** Room left for inputs in one call, after the reference and the reply. */
const room = (ctx, reasoning, refs) => budgetWindow(ctx)
  - (reasoning ? ctx.config.model.reasoningOutput : ctx.config.model.maxOutput)
  - estimateTokens(SYSTEM + refs.join('\n')) - 2048;

function runCommand(ctx, template, values, { failure } = {}) {
  const argv = template.map((part) => fill(part, values));
  const result = spawnSync(argv[0], argv.slice(1), { cwd: ctx.config.root, encoding: 'utf8',
    maxBuffer: 512 * 1024 * 1024 });
  if (result.status !== 0) {
    ctx.logs.detail(`command ${argv[0]} failed`, `${result.stderr}`);
    if (failure) failure.stderr = `${result.stderr ?? ''}${result.error?.message ?? ''}`;
    return null;
  }
  return result.stdout;
}

/** The codes whose rules a job can use: exported, derived by choice, or exported but old. */
export const USABLE_RULE_CODES = ['rules-ok', 'rules-derived', 'rules-stale'];
/** The codes that stop intake: the export is missing or not an export. */
const INTAKE_STOPS = ['rule-export-failed', 'rules-malformed'];
/** The codes that stop Phase 2 for an Included document. */
const PHASE2_STOPS = ['rule-export-failed', 'rules-malformed', 'rules-not-extracted'];

/**
 * One document's rules from the rule export, as { code, rules }. A failure the
 * config's `noRules` pattern matches is the export saying the document has no
 * rules yet: `rules-not-extracted`, or `rules-derived` when the job or config
 * allows Phase 2 to derive them from the text. Any other failure is
 * `rule-export-failed`, since a pack built from derived rules alone would hide
 * the outage. An export that parses is checked for structure
 * (`rules-malformed`); the values the master holds that the procedure would not
 * write, and an export older than the document (`rules-stale`), are warnings:
 * they go to detail.log, and the stale one also leaves a content-free status
 * line naming the document `number`. Retired rules are kept.
 */
export function documentRules(ctx, file, number) {
  const { inputs, ruleShape } = ctx.config;
  if (!inputs.ruleExport) return { code: 'rules-ok', rules: [] };
  const doc = relative(ctx, file);
  const failure = {};
  const raw = runCommand(ctx, inputs.ruleExport, { doc }, { failure });
  if (raw === null) {
    if (!inputs.noRules || !new RegExp(inputs.noRules).test(failure.stderr)) {
      return { code: 'rule-export-failed', rules: [] };
    }
    const allowed = ctx.job.allowDerivedRules ?? ctx.config.allowDerivedRules;
    return { code: allowed ? 'rules-derived' : 'rules-not-extracted', rules: [] };
  }
  const text = fs.readFileSync(file, 'utf8');
  let json;
  try {
    json = JSON.parse(raw);
  } catch {
    ctx.logs.detail(`rule export of document ${doc}`, 'the export is not JSON');
    return { code: 'rules-malformed', rules: [] };
  }
  const { errors, warnings } = shapeProblems(json, doc, text, ruleShape);
  if (errors.length) {
    ctx.logs.detail(`rule export of document ${doc} is malformed`, errors.join('\n'));
    return { code: 'rules-malformed', rules: [] };
  }
  if (warnings.length) ctx.logs.detail(`rule export of document ${doc}: warnings`, warnings.join('\n'));
  const rules = exportsOf(json).flatMap((entry) => list(entry.rules))
    .filter((rule) => rule.status !== 'superseded');
  if (rulesStale(text, exportsOf(json))) {
    ctx.logs.detail(`rule export of document ${doc} is stale`,
      `revised ${revisedDate(text)}; the rules were last confirmed earlier`);
    if (number) {
      ctx.logs.status({ job: ctx.job.id, phase: 'rules', event: 'warn', reason: 'rules-stale',
        document: number });
    }
    return { code: 'rules-stale', rules };
  }
  return { code: 'rules-ok', rules };
}

const exportsOf = (json) => (Array.isArray(json?.exports) ? json.exports : json ? [json] : []);
const stripId = (rule) => String(rule.name ?? '').replace(`${rule.rule_id} - `, '');
const relative = (ctx, file) => path.relative(ctx.config.root, file);
const firstHeading = (text) => (String(text).match(/^#+\s+(.+)$/m)?.[1] ?? '').slice(0, 120);

// ---------------------------------------------------------------------------
// Intake

// Labels no ordinary sentence starts with: they end a description in any record.
const ALM_LABELS = new Set(['detected by', 'detected on date', 'detected in release', 'assigned to',
  'closing date', 'closed in release', 'target release', 'defect id', 'priority', 'severity',
  'reproducible', 'attachments', 'history']);
// Words that are also ordinary text: they end a description only when written the way the
// record writes its own Short and Long Description labels, in bold or as headings.
const ALM_WORDS = new Set(['status', 'comments', 'comment', 'summary', 'name', 'id', 'subject',
  'module', 'project', 'owner', 'type']);

/**
 * The ALM short and long descriptions of a defect record, as one text, or the
 * whole record when it labels neither. A field is a heading or a `Label:` line
 * (bold or plain) named "Short Description" or "Long Description"; it runs to
 * the next heading or the next line that opens another ALM field. A label no
 * ordinary sentence starts with (Detected By, Priority and the like) opens one
 * in any record; a common word (Status, Name, Type) opens one only in the
 * record's own label style when that is bold. Other `Word:` lines stay in the field.
 */
export function almDescriptions(record) {
  const lines = String(record ?? '').split('\n');
  const field = /^\s*(?:#+\s*)?(?:\*\*)?([A-Za-z][A-Za-z ]*?)\s*(?:\*\*)?\s*(?::\s*(?:\*\*)?\s*(.*))?$/;
  const styleOf = (line) => (/^\s*#+\s/.test(line) ? 'heading' : line.includes('**') ? 'bold' : 'plain');
  // The style of the label that opened the field being read.
  let style = 'plain';
  const fields = new Map();
  let current = null;
  for (const line of lines) {
    const heading = /^\s*#+\s/.test(line);
    const match = field.exec(line);
    const name = match?.[1].trim().toLowerCase();
    const labeled = match && (heading || match[2] !== undefined);
    const opens = labeled && (name === 'short description' || name === 'long description'
      || ALM_LABELS.has(name) || (ALM_WORDS.has(name) && style !== 'plain' && styleOf(line) === style));
    if (opens && (name === 'short description' || name === 'long description')) {
      current = name.split(' ')[0];
      style = styleOf(line);
      fields.set(current, match[2] ? [match[2]] : []);
    } else if (opens || heading) {
      current = null;
    } else if (current) {
      fields.get(current).push(line);
    }
  }
  const parts = ['short', 'long'].map((key) => (fields.get(key) ?? []).join('\n').trim())
    .filter(Boolean);
  return parts.length ? parts.join('\n\n') : String(record ?? '').trim();
}

const CAMP_DESIGNS = /^CAMP[\s_-]*Designs$/i;
const decoded = (text) => { try { return decodeURIComponent(text); } catch { return text; } };

/**
 * The folders of the SharePoint path a converted document's provenance block
 * gives, outermost first; the file name is not one of them.
 */
function provenanceFolders(text) {
  const block = /\*\*Document provenance\*\*\s*\n((?:\s*-.*\n?)+)/.exec(String(text));
  if (!block) return [];
  return block[1].split('\n').filter((line) => /^\s*-\s*SharePoint\b/i.test(line))
    .flatMap((line) => {
      const url = /^.*\]\(([^)\s]+)/.exec(line)?.[1] ?? '';
      const segments = url.replace(/^(?:[a-z]+:\/\/)?(?:<[^>]*>|[^/]*)/i, '').split('?')[0].split('/').map(decoded);
      return segments.slice(0, -1);
    });
}

/**
 * What intake received from the documents it was given: the inputs it counts
 * as received, and the ones it lacks. A document whose provenance path is under
 * CAMP Designs is the CAMP document, and its revision date is the updated design.
 * Neither is missing unless the record's descriptions name a CAMP design.
 */
export function documentInputs(documents, description = '') {
  const received = [];
  const missing = [];
  const camp = list(documents).filter((doc) => provenanceFolders(doc.text).some((folder) => CAMP_DESIGNS.test(folder.trim())));
  if (camp.length) {
    received.push(...camp.map((doc) => `CAMP document: ${doc.name}`));
    const dated = camp.map((doc) => ({ doc, day: revisedDate(doc.text) })).filter((row) => row.day);
    if (dated.length) {
      received.push(...dated.map(({ doc, day }) => `Updated design: ${doc.name}, revised ${day}`));
    } else {
      missing.push('Updated design: the CAMP document gives no revision date.');
    }
  } else if (/\bCAMP\s+design/i.test(almDescriptions(description))) {
    // The record points at a CAMP design, and no received document comes from there.
    missing.push('CAMP document: the record names one, and no received document comes from CAMP Designs.');
    missing.push('Updated design: no CAMP document was received.');
  }
  for (const doc of list(documents)) {
    if (doc.ruleCode === 'rules-derived') {
      missing.push(`Business rules for ${doc.name}: none in the rule master, so they are derived from its text.`);
    }
  }
  return { received, missing };
}

export async function intake(ctx) {
  const { job, config, pack, ref } = ctx;
  const ids = config.idFields;
  const codeMissing = [];
  const missingFiles = [];
  let candidates = [];

  if (job.suite) {
    pack.suite = job.suite;
    const raw = runCommand(ctx, config.inputs.folderExport ?? [], { suite: job.suite });
    const exported = raw ? exportsOf(JSON.parse(raw)) : [];
    if (!exported.length) codeMissing.push('folder-export');
    ctx.exportJson = { exports: exported };
    const codeOf = new RegExp(config.suiteMerge?.codePattern ?? '^BR-[A-Z0-9]+\\.');
    ctx.documents = exported.map((doc) => {
      const active = list(doc.rules).filter((rule) => rule.status === 'active');
      const file = doc.doc ? config.at(doc.doc) : null;
      return {
        key: String(doc.prefix).replace(codeOf, ''),
        name: active[0]?.source_document ?? doc.doc,
        text: file && fs.existsSync(file) && fs.statSync(file).isFile()
          ? fs.readFileSync(file, 'utf8') : '',
        rules: active,
      };
    });
    const ruleCount = ctx.documents.reduce((n, doc) => n + doc.rules.length, 0);
    pack.suiteInput = `${config.terms.suiteInput ?? 'folder export of suite'} ${job.suite}`;
    pack[ids.description] = `The approved business rule set of suite ${job.suite}:`
      + ` ${ctx.documents.length} documents, ${ruleCount} active rules.`;
    ctx.description = pack[ids.description];
  } else {
    pack[ids.issue] = job.issue;
    if (job.change) pack[ids.change] = job.change;
    pack[ids.changeApplies] = Boolean(job.change);
    const descriptionFiles = job.descriptionFile ? [config.at(job.descriptionFile)]
      : config.inputs.description
        ? globFiles(config.root, fill(config.inputs.description, job)) : [];
    ctx.description = descriptionFiles.filter((f) => fs.existsSync(f))
      .map((f) => fs.readFileSync(f, 'utf8')).join('\n\n');
    // The model reads the whole record; the pack's change description is the ALM fields.
    pack[ids.description] = almDescriptions(ctx.description);
    if (blank(ctx.description)) codeMissing.push('description');
    if (!job.issue) codeMissing.push('issue-number');
    if (job.docs?.length) {
      ctx.documentPaths = job.docs.map((doc) => config.at(doc));
    } else {
      candidates = config.inputs.documentIndex
        ? globFiles(config.root, fill(config.inputs.documentIndex, job)).map((f) => relative(ctx, f))
        : [];
    }
  }

  // The model reads the description against the intake procedure; the
  // required-input check above stays in code.
  const choices = candidates;
  const index = choices.map((file) => {
    const text = fs.readFileSync(config.at(file), 'utf8').slice(0, 4000);
    return `- ${file}: ${firstHeading(text)}`;
  });
  const descriptionPieces = splitText(ctx.description, Math.max(2000,
    room(ctx, false, [...ref.core, ref.docs.intake]) - estimateTokens(asLines(index))));
  const answers = [];
  for (const [i, piece] of (descriptionPieces.length ? descriptionPieces : ['']).entries()) {
    answers.push(await ask(ctx, {
    phase: 'intake', step: `inventory-${i + 1}`, reasoning: false,
    refs: [...ref.core, ref.docs.intake],
    task: `Run Job Intake for this request.${choices.length ? ' Pick every candidate document'
      + ' the change touches: its process descriptions and design specifications.' : ''}`
      + ' List the inputs received and the assumptions needed to proceed.',
    inputs: [
      ['Request', job.suite ? `Suite pack for ${job.suite}` : `${config.terms.issue} ${job.issue}`
        + (job.change ? `, ${config.terms.change} ${job.change}` : `, no ${config.terms.change}`)],
      [descriptionPieces.length > 1 ? `Description, part ${i + 1} of ${descriptionPieces.length}`
        : 'Description', piece],
      ['Candidate documents', asLines(index)],
    ],
    schema: S.intakeSchema(choices),
    }));
  }
  // A description read in parts gives one answer per part; together they are the inventory.
  const union = (key) => [...new Set(answers.flatMap((a) => list(a[key])))];
  const answer = { documents: union('documents'), received: union('received'),
    assumptionsToProceed: union('assumptionsToProceed') };
  if (choices.length) ctx.documentPaths = answer.documents.map((doc) => config.at(doc));

  if (!job.suite) {
    ctx.documents = [];
    ctx.rulesFresh = true;
    for (const file of ctx.documentPaths ?? []) {
      if (!fs.existsSync(file)) {
        codeMissing.push('document-file');
        missingFiles.push(`Document file not found: ${relative(ctx, file)}`);
        continue;
      }
      const number = ctx.documents.length + 1;
      const { code, rules } = documentRules(ctx, file, number);
      if (INTAKE_STOPS.includes(code)) throw new GateError('intake', code, { document: number });
      ctx.documents.push({
        key: path.basename(file).replace(/\.[^.]+$/, ''),
        file,
        ruleCode: code,
        name: rules[0]?.source_document ?? path.basename(file).replace(/\.[^.]+$/, ''),
        text: fs.readFileSync(file, 'utf8'),
        rules,
      });
    }
    if (!ctx.documents.length) codeMissing.push('documents');
  }

  // Status lines name a document by its number, never by its name.
  (ctx.documents ?? []).forEach((doc, i) => { doc.number = i + 1; });
  const keys = (ctx.documents ?? []).map((doc) => doc.key);
  if (new Set(keys).size !== keys.length) throw new GateError('intake', 'document-key-shared');

  // What is missing is what the documents leave out, never a list of preferred inputs.
  const fromDocuments = job.suite ? { received: [], missing: [] } : documentInputs(ctx.documents, ctx.description);
  const READABLE = { 'folder-export': 'Rule export of the suite folder',
    description: 'Description of the defect or change', 'issue-number': 'Issue number',
    documents: 'Source documents' };
  const missing = [...new Set([...codeMissing.filter((code) => code !== 'document-file')
    .map((code) => READABLE[code] ?? code), ...missingFiles, ...fromDocuments.missing])]
    .map((text) => `${text.replace(/\.$/, '')}.`);
  pack.intake = {
    received: [...new Set([...list(answer.received), ...fromDocuments.received])],
    missing,
    authority: [],
    contextOnly: [],
    assumptionsToProceed: list(answer.assumptionsToProceed),
    readiness: codeMissing.length ? 'NOT READY'
      : list(answer.assumptionsToProceed).length || missing.length
        ? 'READY WITH ASSUMPTIONS' : 'READY',
  };
  if (missing.length) {
    pack.limitations ??= {};
    pack.limitations['Job Intake'] = `Not received at intake: ${missing.join(' ')}`;
  }
  if (codeMissing.length) {
    throw new GateError('intake', 'missing-inputs', { missing: codeMissing.length });
  }
  return { documents: ctx.documents.length,
    rules: ctx.documents.reduce((n, doc) => n + doc.rules.length, 0) };
}

// ---------------------------------------------------------------------------
// Phase 1, Project Understanding Gate

/** Each document as text that fits, or as a digest of its pieces when it does not. */
async function documentViews(ctx, refs, reserve) {
  const budget = room(ctx, true, refs) - reserve;
  const whole = ctx.documents.map((doc) => `### ${doc.name}\n\n${doc.text}`);
  if (estimateTokens(whole.join('\n\n')) <= budget) return whole;
  const views = [];
  for (const doc of ctx.documents) views.push(`### ${doc.name} (digest)\n\n${await digestDocument(ctx, doc)}`);
  // A digest set that still does not fit means the documents are too many for one call.
  if (estimateTokens(views.join('\n\n')) > budget) {
    throw new GateError('phase1', 'documents-too-big', { documents: views.length });
  }
  return views;
}

/** A document's digest, made once from every piece of its text. */
async function digestDocument(ctx, doc) {
  if (doc.digest) return doc.digest;
  const pieces = splitText(doc.text, room(ctx, false, []) - 1000);
  const points = [];
  for (const [i, piece] of pieces.entries()) {
    const digest = await ask(ctx, {
      phase: 'phase1', step: `digest-d${doc.number}-${i + 1}`, reasoning: false, refs: [],
      task: 'List the behavior, screens, modules, business rules and data this part of'
        + ' the document describes, one point each, with its page where the text gives one.',
      inputs: [['Document', doc.name], ['Text', piece]],
      schema: S.digestSchema,
    });
    points.push(...digest.points);
  }
  doc.digest = points.map((p) => `- ${p}`).join('\n');
  return doc.digest;
}

/**
 * The rules Phase 1 reads, as full lines, then names alone, then a count per
 * document, whichever first fits in half the call so the documents keep room.
 */
function phase1Rules(ctx, budget) {
  const rules = (line) => asLines(ctx.documents.flatMap((doc) => doc.rules).map(line));
  const tag = (rule) => (rule.status === 'retired' ? '[retired] ' : '');
  const full = rules((rule) => `- ${tag(rule)}${rule.rule_id ?? rule.id}: ${rule.name ?? ''} | ${rule.rule_summary
    ?? rule.summary ?? ''}`);
  if (estimateTokens(full) <= budget) return full;
  const named = rules((rule) => `- ${tag(rule)}${rule.rule_id ?? rule.id}: ${rule.name ?? ''}`);
  if (estimateTokens(named) <= budget) return named;
  return ctx.documents.map((doc) => `- ${doc.name}: ${doc.rules.length} rule(s)`).join('\n');
}

export async function phase1(ctx) {
  const { pack, ref, job } = ctx;
  const refs = [...ref.core, ref.docs.understandingGate];
  const ruleText = phase1Rules(ctx, Math.floor(room(ctx, true, refs) / 2));
  const views = await documentViews(ctx, refs,
    estimateTokens(ctx.description + ruleText) + 4000);
  const names = ctx.documents.map((doc) => doc.name);
  const answer = await ask(ctx, {
    phase: 'phase1', step: 'understanding', reasoning: true, refs,
    task: 'Run the Project Understanding Gate. Write the Project Understanding Summary,'
      + (job.suite ? '' : ' rank every source document by the authority order and decide its'
        + ' inclusion with a reason,')
      + ' name the module each document belongs to with a short upper-case abbreviation that'
      + ' no other module shares, and list every conflict between included sources.'
      + ' A conflict is two authoritative sources that require different behavior for the'
      + ' same thing. A defect record saying the system behaves differently from a document'
      + ' today is the defect under test, not a conflict. A rule marked [retired] describes'
      + ' behavior that was removed; it is not a conflict with the documents.'
      + ' Rate confidence honestly.',
    inputs: [['Change description', ctx.description],
      ['Business rules', ruleText],
      ['Source documents', views.join('\n\n')]],
    schema: S.understandingSchema({
      documents: names, keys: ctx.documents.map((doc) => doc.key),
      inclusions: ctx.builder.INCLUSIONS, suite: Boolean(job.suite),
    }),
  });
  ctx.private('phase1-summary.json', answer.summary);
  const modules = new Map(answer.modules.map((row) => [row.document, row]));
  const abbreviations = new Map();
  const byModule = new Map();
  for (const doc of ctx.documents) {
    const row = modules.get(doc.key);
    if (!row) throw new GateError('phase1', 'module-missing');
    doc.module = row.module;
    // A suite numbers its cards per document, so each document is its own
    // module with its own abbreviation, made unique by its code when two collide.
    if (job.suite && byModule.has(row.module)) doc.module = `${row.module} ${doc.key}`;
    if (job.suite && abbreviations.has(row.abbreviation)) {
      doc.abbreviation = `${row.abbreviation}${doc.key}`.replace(/[^A-Z0-9]/gi, '').toUpperCase();
      byModule.set(doc.module, doc.abbreviation);
    }
    // In an issue pack, two documents of one module share its first abbreviation.
    doc.abbreviation = byModule.get(doc.module) ?? row.abbreviation;
    byModule.set(doc.module, doc.abbreviation);
    const owner = abbreviations.get(doc.abbreviation);
    if (owner && owner !== doc.module) throw new GateError('phase1', 'abbreviation-shared');
    abbreviations.set(doc.abbreviation, doc.module);
  }
  if (job.suite) {
    for (const doc of ctx.documents) doc.inclusion = 'Included';
  } else {
    const decided = new Map(answer.sourceDocuments.map((row) => [row.name, row]));
    if (decided.size !== names.length) throw new GateError('phase1', 'inclusion-missing');
    pack.sourceDocuments = names.map((name) => decided.get(name));
    for (const doc of ctx.documents) doc.inclusion = decided.get(doc.name).inclusion;
    pack.intake.authority = pack.sourceDocuments.filter((d) => d.inclusion === 'Included')
      .map((d) => d.name);
    pack.intake.contextOnly = pack.sourceDocuments
      .filter((d) => d.inclusion === 'Supporting Context Only').map((d) => d.name);
    if (!pack.intake.authority.length) throw new GateError('phase1', 'no-included-source');
  }
  ctx.summary = answer.summary;
  // What a stopped gate found is the user's to read, in the job's own folder.
  ctx.private('phase1-conflicts.json', answer.conflicts);
  if (answer.conflicts.length) {
    throw new GateError('phase1', 'source-conflict', { conflicts: answer.conflicts.length });
  }
  if (answer.summary.confidence === 'Low') throw new GateError('phase1', 'low-confidence');
  return { included: ctx.documents.filter((d) => d.inclusion === 'Included').length };
}

const summaryText = (ctx) => Object.entries(ctx.summary ?? {})
  .map(([key, value]) => `${key}: ${value}`).join('\n');

// ---------------------------------------------------------------------------
// Phase 2, Business Rule / Requirement Intake

/**
 * Reads each Included document's rule export again, so a job resumed after the
 * user extracted or fixed the rules sees them, and stops when one still has
 * none usable. A run whose intake just exported a document with usable rules
 * keeps those rules, and so does a checkpoint with no file path for the
 * document. An export outage that follows a usable intake keeps the rules held
 * and leaves a warning. Every failing document gets a status line and the stop
 * names them all, under the most basic code among them. A context-only
 * document is not read again.
 */
function refreshRules(ctx) {
  const failing = [];
  for (const doc of ctx.documents) {
    if (doc.inclusion !== 'Included' || !doc.file) continue;
    const held = USABLE_RULE_CODES.includes(doc.ruleCode);
    if (held && ctx.rulesFresh) continue;
    const { code, rules } = documentRules(ctx, doc.file);
    if (code === 'rule-export-failed' && held) {
      ctx.logs.status({ job: ctx.job.id, phase: 'phase2', event: 'warn', reason: code,
        document: doc.number });
      continue;
    }
    doc.ruleCode = code;
    if (PHASE2_STOPS.includes(code)) failing.push({ number: doc.number, code });
    else doc.rules = rules;
  }
  if (!failing.length) return;
  for (const { number, code } of failing) {
    ctx.logs.status({ job: ctx.job.id, phase: 'phase2', event: 'stop-doc', document: number,
      reason: code });
  }
  const code = PHASE2_STOPS.find((c) => failing.some((row) => row.code === c));
  throw new GateError('phase2', code,
    { documents: failing.length, numbers: failing.map((row) => row.number).join(' ') });
}

const RETIRED_SUMMARY = 'Retired: this rule was removed from the master.';
const isRetired = (rule) => String(rule.summary ?? '').startsWith('Retired:');

/**
 * Warns for each Included document whose text has struck-through behavior that
 * no retired rule of its export cites (a fragment edit or a restated sentence
 * needs none), and records a limitation
 * under Job Intake. It runs at the start of Phase 2, once inclusion is decided
 * and the rules have been read again, so it judges the rules the pack uses. It
 * is a warning, never a stop: the status line names the document by number, the
 * detail log says where the spans sit.
 */
function warnUnretired(ctx) {
  const named = [];
  for (const doc of ctx.documents) {
    if (doc.inclusion !== 'Included' || !doc.text) continue;
    const spans = uncitedStruck(doc.text, doc.rules);
    if (!spans.length) continue;
    ctx.logs.status({ job: ctx.job.id, phase: 'phase2', event: 'warn', reason: 'retired-rule-missing',
      document: doc.number });
    ctx.logs.detail(`document ${doc.number} has struck-through text no retired rule cites`,
      spans.map((s) => (s.page === null ? `heading "${s.heading ?? 'none'}"` : `page ${s.page}`))
        .join('\n'));
    named.push(doc.name);
  }
  if (!named.length) return;
  const text = `Struck-through text in ${named.join(', ')} has no rule citing it,`
    + ' so removed behavior may be missing from the pack. Extract or update the rules for each of them.';
  ctx.pack.limitations ??= {};
  const held = ctx.pack.limitations['Job Intake'] ?? '';
  if (!held.includes(text)) ctx.pack.limitations['Job Intake'] = `${held} ${text}`.trim();
}

export async function phase2(ctx) {
  const { pack, ref } = ctx;
  const risks = ctx.riskLevels;
  const rules = [];
  let derived = 0;
  if (!ctx.job.suite) {
    refreshRules(ctx);
    warnUnretired(ctx);
  }
  for (const doc of ctx.documents.filter((d) => d.inclusion === 'Included')) {
    if (doc.rules.length) {
      for (const rule of doc.rules) {
        // A retired rule stays in the pack, marked in its summary as removed; Phase 3
        // decides whether the change concerns that removal.
        const retired = rule.status === 'retired';
        rules.push({
          id: rule.rule_id, name: stripId(rule), module: doc.module, sourceDocument: doc.name,
          sourcePage: String(rule.source_page ?? '') || 'N/A',
          summary: retired ? `${RETIRED_SUMMARY} ${rule.rule_summary ?? ''}`.trim() : rule.rule_summary,
          risk: risks.includes(rule.risk_level) ? rule.risk_level : undefined,
        });
      }
      continue;
    }
    // A document the master holds no rules for has them derived from its text,
    // each named by its source and statement, never given an invented ID.
    const refs = [...ref.core, ref.docs.ruleIntake];
    for (const [i, piece] of splitText(doc.text, room(ctx, false, refs) - 1000).entries()) {
      const answer = await ask(ctx, {
        phase: 'phase2', step: `derive-d${doc.number}-${i + 1}`, reasoning: false, refs,
        task: 'Extract every business rule this part of the document states. One rule per'
          + ' decision, a short statement naming it, the page it is on (N/A when the text'
          + ' has no pages), a one-sentence summary, and its risk.',
        inputs: [['Document', doc.name], ['Text', piece]],
        schema: S.derivedRulesSchema(risks),
      });
      for (const row of answer.rules) {
        derived += 1;
        ctx.derivedDocuments = [...new Set([...list(ctx.derivedDocuments), doc.name])];
        const page = String(row.sourcePage || 'N/A');
        rules.push({
          id: `${doc.key} ${page === 'N/A' ? '' : `p${page} `}${row.statement}`,
          name: row.statement, module: doc.module, sourceDocument: doc.name, sourcePage: page,
          summary: row.summary, risk: row.risk,
        });
      }
    }
  }
  const seen = new Set();
  for (const rule of rules) {
    if (seen.has(rule.id)) throw new GateError('phase2', 'duplicate-rule-id');
    seen.add(rule.id);
    if (blank(rule.summary) || blank(rule.name)) throw new GateError('phase2', 'untraceable-rule');
  }
  if (!rules.length) throw new GateError('phase2', 'no-rules');
  pack.rules = rules;
  return { rules: rules.length, derived };
}

// ---------------------------------------------------------------------------
// Phase 3, Change Scope Analysis

const ruleLine = (rule) => `- ${rule.id} | ${rule.name} | ${rule.module} | ${rule.summary}`;

export async function phase3(ctx) {
  const { pack, ref, job } = ctx;
  if (job.suite) {
    for (const rule of pack.rules) {
      rule.impact = 'Regression';
      rule.rationale = 'Suite baseline: approved rule held in the master';
    }
    return { regression: pack.rules.length };
  }
  const refs = [...ref.core, ref.docs.scope];
  const fixed = estimateTokens(ctx.description + summaryText(ctx)) + 2000;
  const groups = batches(pack.rules, ruleLine, room(ctx, true, refs) - fixed, 40);
  const byId = new Map(pack.rules.map((rule) => [rule.id, rule]));
  pack.assumptions ??= [];
  for (const [i, group] of groups.entries()) {
    const ids = group.map((rule) => rule.id);
    let answer = await ask(ctx, {
      phase: 'phase3', step: `scope-${i + 1}`, reasoning: true, refs,
      task: 'Classify each rule by the change description: Direct Change, Indirect Impact,'
        + ' Regression or Not Impacted, with a one-sentence rationale. A rule the change does'
        + ' not touch is Not Impacted. A rule whose summary starts with "Retired:" was removed'
        + ' from the master: it is a Direct Change only when the change description concerns'
        + ' that removal, and Not Impacted otherwise; for a Direct Change, the rationale says its'
        + ' removal is to be verified. Record each ambiguity as an assumption.',
      inputs: [['Change description', ctx.description], ['Project understanding', summaryText(ctx)],
        ['Rules', asLines(group.map(ruleLine))]],
      schema: S.scopeSchema(ids, ctx.builder.IMPACT_CLASSES),
    });
    const classified = new Map(answer.rules.map((row) => [row.id, row]));
    if (ids.some((id) => !classified.has(id))) {
      throw new GateError('phase3', 'unclassified-rule',
        { missing: ids.filter((id) => !classified.has(id)).length });
    }
    for (const row of answer.rules) {
      Object.assign(byId.get(row.id), { impact: row.impact, rationale: row.rationale });
    }
    pack.assumptions.push(...answer.assumptions);
    answer = null;
  }
  const counts = {};
  for (const rule of pack.rules) counts[rule.impact] = (counts[rule.impact] ?? 0) + 1;
  return { direct: counts['Direct Change'] ?? 0, indirect: counts['Indirect Impact'] ?? 0,
    regression: counts.Regression ?? 0, notImpacted: counts['Not Impacted'] ?? 0 };
}

// ---------------------------------------------------------------------------
// Phase 4, Impact Analysis

const moduleCounts = (rules) => {
  const counts = new Map();
  for (const rule of rules) counts.set(rule.module, (counts.get(rule.module) ?? 0) + 1);
  return [...counts].map(([module, n]) => `- ${module}: ${n} rule(s)`).join('\n');
};

export async function phase4(ctx) {
  const { pack, ref } = ctx;
  const refs = [...ref.core, ...ref.chapters('4')];
  const impacted = pack.rules.filter((rule) => rule.impact !== 'Not Impacted');
  const fixed = estimateTokens(ctx.description + summaryText(ctx)) + 2000;
  const ruleText = asLines(impacted.map((rule) => `${ruleLine(rule)} | ${rule.impact}`));
  const answer = await ask(ctx, {
    phase: 'phase4', step: 'impact', reasoning: true, refs,
    task: 'Run the Impact Analysis: modules, windows, business functions, upstream and'
      + ' downstream effects, data, security and roles, batch, notices, reports and interfaces.'
      + ' Fill the executive summary from it.',
    inputs: [['Change description', ctx.description], ['Project understanding', summaryText(ctx)],
      ['Source documents', ctx.documents.filter((d) => d.inclusion === 'Included')
        .map((d) => d.name).join('\n')],
      estimateTokens(ruleText) <= room(ctx, true, refs) - fixed
        ? ['Impacted rules', ruleText] : ['Impacted rules by module', moduleCounts(impacted)]],
    schema: S.impactSchema,
  });
  pack.executiveSummary = { ...answer.executiveSummary, confidence: '' };

  // Every impacted rule is rated from the impact analysis, with the master's risk as its
  // starting value; a rule the change does not touch keeps the master's, or is rated when
  // the master gave none.
  // A suite has no change to rate against, so it keeps the approved risks and rates only the gaps.
  const toRate = pack.rules.filter((rule) => !rule.risk
    || (!ctx.job.suite && rule.impact !== 'Not Impacted'));
  const rateLine = (rule) => `${ruleLine(rule)} | ${rule.impact} | master risk: ${rule.risk ?? 'none'}`;
  const rateFixed = estimateTokens(ctx.description + JSON.stringify(pack.executiveSummary)) + 2000;
  const groups = batches(toRate, rateLine, room(ctx, false, refs) - rateFixed, 60);
  for (const [i, group] of groups.entries()) {
    const rated = await ask(ctx, {
      phase: 'phase4', step: `risk-${i + 1}`, reasoning: false, refs,
      task: 'Give each rule its risk level from the impact analysis. A rule\'s master risk is'
        + ' where to start; keep it unless the impact analysis says the change makes it higher'
        + ' or lower.',
      inputs: [['Change description', ctx.description],
        ['Impact analysis', JSON.stringify(pack.executiveSummary)],
        ['Rules', asLines(group.map(rateLine))]],
      schema: S.riskSchema(group.map((rule) => rule.id), ctx.riskLevels),
    });
    const byId = new Map(rated.rules.map((row) => [row.id, row.risk]));
    for (const rule of group) {
      if (!byId.has(rule.id)) throw new GateError('phase4', 'unrated-rule');
      rule.risk = byId.get(rule.id);
    }
  }
  // A rule the change itself alters is never rated below the top level, the first of the
  // configured risk levels.
  const top = ctx.riskLevels[0];
  const raised = pack.rules.filter((rule) => rule.impact === 'Direct Change' && rule.risk !== top);
  if (raised.length) {
    ctx.logs.detail('phase4 raised risk', raised.map((rule) => `${rule.id}: ${rule.risk} to ${top}`)
      .join('\n'));
    for (const rule of raised) rule.risk = top;
  }
  return { impacted: impacted.length, rated: toRate.length, raised: raised.length };
}

// ---------------------------------------------------------------------------
// Phase 5, Testing Objective Selection

const FATL_DOWNGRADE = /\bFATLs?\b[^.\n]{0,80}\bdowngrad|\bdowngrad[^.\n]{0,80}\bFATLs?\b/i;
const CLOSURE_SUBMIT = /\bstage[ -]closures?\b[^.\n]{0,80}\bsubmi(?:t|ts|tted|tting|ssion)\b|\bsubmi(?:t|ts|tted|tting|ssion)\b[^.\n]{0,80}\bstage[ -]closures?\b/i;
const INTEGRATION = /^integration\b/i;
const squash = (text) => String(text ?? '').replace(/\s+/g, ' ').trim().toLowerCase();
/** Whether a text, with its whitespace squashed, holds a FATL downgrade and a stage closure submit. */
const namesBothTerms = (text) => FATL_DOWNGRADE.test(squash(text)) && CLOSURE_SUBMIT.test(squash(text));

/**
 * The Direct Change and Indirect Impact rules, as `name. summary` lines, whose
 * text holds a FATL downgrade and a stage closure submit, which are the only rules
 * a quote can come from, as many as fit `budget` tokens. The cap is logged.
 */
function quotableRules(ctx, budget) {
  const lines = list(ctx.pack.rules)
    .filter((rule) => ['Direct Change', 'Indirect Impact'].includes(rule.impact))
    .map((rule) => `- ${rule.name}. ${rule.summary}`)
    .filter(namesBothTerms);
  const kept = [];
  let used = 0;
  for (const line of lines) {
    used += estimateTokens(line);
    if (used > budget) break;
    kept.push(line);
  }
  if (kept.length < lines.length) {
    ctx.logs.detail('phase 5: rule lines left out to fit the model',
      `${lines.length - kept.length} of ${lines.length} rule lines did not fit`);
  }
  return kept;
}

/**
 * Whether the model's Phase 5 evidence that the change includes the stage
 * closure submit after a FATL downgrade holds: the answer says so, and its
 * quote appears word for word (whitespace and case aside) in the record's ALM
 * descriptions or in a Direct Change or Indirect Impact rule (as `name. summary`),
 * and holds a FATL downgrade, a stage closure and a submit in the one quote.
 * Returns { ok, why }.
 */
export function integrationEvidence(ctx, answer) {
  if (answer.stageClosureAfterDowngrade !== true) return { ok: false, why: 'not claimed' };
  const quote = squash(answer.stageClosureQuote);
  if (!quote) return { ok: false, why: 'no quote' };
  const sources = [almDescriptions(ctx.description), ...list(ctx.pack.rules)
    .filter((rule) => ['Direct Change', 'Indirect Impact'].includes(rule.impact))
    .flatMap((rule) => [rule.name, rule.summary, `${rule.name}. ${rule.summary}`])];
  if (!sources.some((source) => squash(source).includes(quote))) {
    return { ok: false, why: 'quote not in the description or an impacted rule' };
  }
  if (!namesBothTerms(quote)) {
    return { ok: false, why: 'quote lacks a FATL downgrade, a stage closure or a submit' };
  }
  return { ok: true, why: 'quoted' };
}

export async function phase5(ctx) {
  const { pack, ref, job } = ctx;
  const objectives = ctx.builder.OBJECTIVES;
  const refs = [...ref.core, ...ref.chapters('5')];
  const byImpact = Object.entries(pack.rules.reduce((acc, rule) => ({
    ...acc, [rule.impact]: (acc[rule.impact] ?? 0) + 1 }), {}))
    .map(([impact, n]) => `- ${impact}: ${n}`).join('\n');
  const quotable = job.suite ? [] : quotableRules(ctx, room(ctx, true, refs)
    - estimateTokens(`${ctx.description}${JSON.stringify(pack.executiveSummary)}${byImpact}`) - 1500);
  const answer = await ask(ctx, {
    phase: 'phase5', step: 'objectives', reasoning: true, refs,
    task: `Decide every one of the ${objectives.length} testing objectives: applicable or not,`
      + ' with a reason each.'
      + (job.suite ? ` This is a suite pack with no change under test, so ${ctx.coreObjective}`
        + ' is not applicable.'
        : ' A change makes Integration Testing applicable when the change'
        + ' includes the stage closure submit after a FATL downgrade. Say whether it does in'
        + ' stageClosureAfterDowngrade and, when it does, quote in stageClosureQuote, word for'
        + ' word, the sentence of the description or of a Direct Change or Indirect Impact rule'
        + ' that says so; the sentence holds the FATL downgrade, the stage closure and the submit.'),
    // The description is the ALM fields and the rule lines are the rules' own text: the
    // sentences integrationEvidence accepts a quote from.
    inputs: [['Change description', job.suite ? ctx.description : almDescriptions(ctx.description)],
      ['Direct Change and Indirect Impact rules', quotable.join('\n')],
      ['Executive summary', JSON.stringify(pack.executiveSummary)],
      ['Rules by impact', byImpact]],
    schema: S.objectivesSchema(objectives, { closure: !job.suite }),
  });
  const decided = new Map(answer.objectives.map((row) => [row.objective, row]));
  if (objectives.some((objective) => !decided.has(objective))) {
    throw new GateError('phase5', 'objective-undecided');
  }
  pack.objectives = objectives.map((objective) => decided.get(objective));
  if (job.suite) {
    const core = decided.get(ctx.coreObjective);
    core.applicable = false;
  } else if (answer.stageClosureAfterDowngrade === true) {
    const evidence = integrationEvidence(ctx, answer);
    const integration = decided.get(objectives.find((o) => INTEGRATION.test(o)));
    if (!evidence.ok) {
      ctx.logs.detail('phase 5: the stage closure evidence was rejected', evidence.why);
    } else if (integration && !integration.applicable) {
      integration.applicable = true;
      integration.reason = 'The change includes the stage closure submit after a FATL downgrade,'
        + ' so the window is tested together with the stage it closes.';
    }
  }
  return { applicable: pack.objectives.filter((row) => row.applicable).length };
}

// ---------------------------------------------------------------------------
// Phase 6, Reusable Test Design

/** Card objectives a document's cards may name. */
function cardObjectives(ctx) {
  if (ctx.job.suite) return ctx.suiteSetOrder;
  return ctx.pack.objectives.filter((row) => row.applicable).map((row) => row.objective);
}

const scenarioLine = (s) => `- ${s.id} | ${s.kind} | rules ${s.rules.join(', ')} | ${s.population} | ${s.action}`
  + ` | ${s.outcome}`;
const cardLine = (card) => `- ${card.title} | ${card.scenario} | rules ${card.rules.join(', ')}`;
const norm = (text) => String(text ?? '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();

/** What makes two scenarios, or two cards for them, the same test: kind, rules, who, and what is done. */
export const scenarioKey = (s) => [s.kind, [...new Set(s.rules)].sort().join(','), norm(s.population),
  norm(s.action)].join('|');

/** The document text for a call: whole if it fits beside what the call already carries, else its digest. */
async function documentText(ctx, doc, refs, carried) {
  const budget = room(ctx, false, refs) - estimateTokens(carried + ctx.description) - 3000;
  // A document too long to send whole goes as its digest; the call's own size
  // check refuses anything that still does not fit.
  return estimateTokens(doc.text) <= budget ? doc.text : digestDocument(ctx, doc);
}

/** A retired rule the change concerns: its card verifies the removed behavior is gone. */
const removedBehavior = (rule) => rule.impact === 'Direct Change' && isRetired(rule);
const REMOVED_SCENARIO = ' A rule whose summary starts with "Retired:" was removed: list a scenario'
  + ' that checks its behavior is gone.';
const REMOVED_CARD = ' A rule whose summary starts with "Retired:" was removed: its card verifies'
  + ' the behavior is gone, and its expected result, final step included, says the behavior is'
  + ' absent, such as a warning and its buttons not appearing.';

/** True when the pack has a BREAK IT set that its cards can fill. */
const breakItOn = (ctx) => !ctx.job.suite && ctx.breakItObjective != null
  && cardObjectives(ctx).includes(ctx.breakItObjective);

// Rules go to the inventory a quarter of the room at a time; a reply lists at most one scenario per 150 tokens.
const INVENTORY_SHARE = 4;
const SCENARIO_TOKENS = 150;

/**
 * The distinct scenarios a document's impacted rules call for. Rules that do
 * not fit one call go in batches, each shown the scenarios listed so far. Code
 * numbers the scenarios and drops any that repeats another's kind, rules,
 * population and action. With `only`, just that kind is asked for, and
 * `known` are the scenarios already listed.
 */
async function scenarioInventory(ctx, doc, rules, { only, known = [] } = {}) {
  const refs = [...ctx.ref.core, ...ctx.ref.chapters('6')];
  const required = only ? [] : [...S.REQUIRED_SCENARIO_KINDS, ...(breakItOn(ctx) ? ['break'] : [])];
  const maxItems = Math.max(1, Math.floor(ctx.config.model.maxOutput / SCENARIO_TOKENS));
  const line = (rule) => `${ruleLine(rule)} | ${rule.impact} | risk ${rule.risk}`;
  const groups = batches(rules, line, Math.max(1000, Math.floor(room(ctx, false, refs) / INVENTORY_SHARE)));
  const seen = new Set(known.map(scenarioKey));
  const scenarios = [];
  const notes = [];
  const checks = new Map();
  let dropped = 0;
  let capped = false;
  for (const [i, group] of groups.entries()) {
    const lines = asLines(group.map(line));
    const listed = asLines([...known, ...scenarios].map(scenarioLine));
    const answer = await ask(ctx, {
      phase: 'phase6', reasoning: false, refs,
      step: only ? `scenarios-d${doc.number}-${only}` : groups.length > 1
        ? `scenarios-d${doc.number}-${i + 1}` : `scenarios-d${doc.number}`,
      task: (only ? `List only the ${only} scenarios these rules and the document call for.`
        : 'List the distinct test scenarios these rules and the document call for.')
        + ' A scenario is one population (which records or users), one action, and the expected'
        + ' outcome, and it names the rules it checks. '
        + (only ? 'A break scenario tries to break the change with bad input, a wrong order, a'
          + ' boundary or a repeated action.'
          : 'Cover each of these kinds wherever the document supports it, and mark every other'
          + ' scenario a decision: control is a population the change must not affect, such as'
          + ' the plain save; isolation is another record\'s state that must not leak into this'
          + ' one; combined is conditions that overlap; persistence is closing and reopening the'
          + ' record' + (required.includes('break') ? '; break tries to break the change with bad'
          + ' input, a wrong order, a boundary or a repeated action' : '') + '. Under kindChecks,'
          + ' say for each of those kinds what its scenario tests, or why the document supports'
          + ' none.') + (group.some(removedBehavior) ? REMOVED_SCENARIO : '')
        + ' Never list a scenario already listed.',
      inputs: [['Change description', ctx.description], ['Document', doc.name], ['Rules', lines],
        ['Scenarios listed so far', listed],
        ['Document text', await documentText(ctx, doc, refs, lines + listed)]],
      schema: S.scenarioInventorySchema({ ids: group.map((rule) => rule.id), maxItems, required,
        kinds: only ? [only] : S.SCENARIO_KINDS }),
    });
    if (answer.scenarios.length >= maxItems) capped = true;
    for (const row of answer.scenarios) {
      const key = scenarioKey(row);
      if (seen.has(key)) {
        dropped += 1;
        continue;
      }
      seen.add(key);
      scenarios.push({ ...row, id: `S${known.length + scenarios.length + 1}`,
        rules: [...new Set(row.rules)] });
    }
    for (const check of answer.kindChecks ?? []) {
      checks.set(check.kind, [...(checks.get(check.kind) ?? []), check.note]);
    }
  }
  // A required kind with no scenario is said so, not left unmentioned.
  for (const kind of required.filter((k) => !scenarios.some((s) => s.kind === k))) {
    notes.push({ assumption: `${doc.name}: no ${kind} scenario was listed.`,
      why: (checks.get(kind) ?? []).join(' '), impact: `No card tests a ${kind} scenario for this document.`,
      clarification: 'Confirm the document supports none.' });
  }
  if (capped) {
    notes.push({ assumption: `${doc.name}: the scenario list reached its limit of ${maxItems}.`,
      why: 'One reply holds only so many scenarios.', impact: 'Some scenarios may be missing.',
      clarification: 'Check the list against the document by hand.' });
  }
  return { scenarios, notes, dropped };
}

/**
 * One card call. `focus` are the scenarios it is asked for; it may cover any
 * scenario in `open` (those with no card, reuse or skip yet), and no other.
 */
async function designBatch(ctx, doc, { focus, open, written }, objectives, index, extra = '',
  name = 'cards') {
  const refs = [...ctx.ref.core, ...ctx.ref.chapters('6')];
  const byId = new Map(ctx.pack.rules.map((rule) => [rule.id, rule]));
  const group = [...new Set(open.flatMap((s) => s.rules))].map((id) => byId.get(id));
  const ids = group.map((rule) => rule.id);
  const lines = asLines(group.map((rule) => `${ruleLine(rule)} | ${rule.impact} | risk ${rule.risk}`));
  const scenarios = asLines(open.map(scenarioLine));
  const cards = asLines(written.map(cardLine));
  const existing = ctx.existingTests ?? '';
  const docText = await documentText(ctx, doc, refs, [lines, scenarios, cards, existing].join('\n'));
  return ask(ctx, {
    phase: 'phase6', step: `${name}-d${doc.number}-${index}`, reasoning: false, refs,
    task: `Design reusable test cards for these scenarios: ${focus.map((s) => s.id).join(', ')}.`
      + ' Write one card per scenario, only for scenarios no card written so far covers, and name'
      + ' on each card the scenario it covers. Focus items and steps are actions; expected'
      + ' results are observable business behavior. A card\'s expected result is its final'
      + ' step\'s expected result, in the same words. Name on each card and each step only the'
      + ' rules it checks. Mark cards that come from quality thinking rather than a stated rule'
      + ' as Quality. A scenario an existing test already covers, or that no card can cover, is'
      + ' named in skipped with how (reused or gap) and the reason; reused names the test. A'
      + ` rule no card can cover goes in uncovered with its gap.`
      + `${group.some(removedBehavior) ? REMOVED_CARD : ''}${extra}`,
    inputs: [['Change description', ctx.description], ['Document', doc.name],
      ['Scenarios', scenarios], ['Rules', lines], ['Cards written so far', cards],
      ['Document text', docText], ['Existing tests', existing]],
    schema: S.cardsSchema({ ids, objectives, derivations: ctx.builder.DERIVATIONS,
      uncoveredStatuses: ['Partially Covered', 'Missing', 'Not Applicable'],
      scenarios: open.map((s) => s.id) }),
  });
}

/** A card with its rule lists cut to what the card may name, and every rule traced by a step. */
function tidyCard(card, allowed) {
  const rules = [...new Set(card.rules.filter((id) => allowed.has(id)))];
  const steps = card.steps.map((step) => ({ ...step,
    rules: [...new Set(list(step.rules).filter((id) => rules.includes(id)))] }));
  const named = steps.flatMap((step) => step.rules);
  const unnamed = steps.some((step) => !step.rules.length);
  const untraced = rules.filter((id) => !named.includes(id));
  // A step naming no rule traces the rest; without one, the last step takes them.
  if (untraced.length && !unnamed && steps.length) {
    steps[steps.length - 1].rules.push(...untraced);
  }
  return { ...card, rules, steps };
}

/**
 * The sets a card sits in: the objectives it names, Full Coverage when it
 * comes from a requirement, and BREAK IT only when the card is a BREAK IT
 * type (`breakIt`, set from its scenario's kind). With `exclusiveSets`, a
 * BREAK IT card sits in no other set. A card left in no set takes the first
 * ordinary objective, else Full Coverage; with neither, it has no set.
 */
export function setsOf(ctx, card) {
  const { fullCoverageObjective: full, breakItObjective: brk } = ctx;
  const applicable = cardObjectives(ctx);
  const breakIt = brk != null && applicable.includes(brk) && card.breakIt === true;
  if (breakIt && ctx.config.exclusiveSets) return [brk];
  const sets = list(card.objectives).filter((o) => applicable.includes(o) && o !== full && o !== brk);
  if (full != null && applicable.includes(full) && card.derivation !== 'Quality') sets.push(full);
  if (breakIt) sets.push(brk);
  if (!sets.length) {
    const other = applicable.find((o) => o !== full && o !== brk)
      ?? (full != null && applicable.includes(full) ? full : null);
    return other == null ? [] : [other];
  }
  return [...new Set(sets)];
}

const DROPPED = 'No test card could be designed for it in this run.';
const noStop = (text) => String(text).replace(/[.\s]+$/, '');

const docRules = (ctx, doc) => ctx.pack.rules.filter((rule) => rule.sourceDocument === doc.name
  && rule.module === doc.module && rule.impact !== 'Not Impacted');

/**
 * One document's scenarios, then its cards, one batch of scenarios at a time.
 * Given its earlier `designed` and `only`, it adds scenarios of that kind.
 * A scenario is settled by a card, by a skip saying an existing test covers it,
 * or by a skip saying no card can; each records how in its `settled`.
 */
async function designDocument(ctx, doc, rules, objectives, { designed, only } = {}) {
  const state = designed ?? { cards: [], uncovered: [], reuse: [], assumptions: [], scenarios: [] };
  const count = { retried: 0, duplicates: 0, unsettled: 0 };
  if (!rules.length) return { designed: state, ...count };
  const inventory = await scenarioInventory(ctx, doc, rules, { only, known: state.scenarios });
  const mine = inventory.scenarios;
  state.scenarios.push(...mine);
  state.assumptions.push(...inventory.notes);
  count.duplicates += inventory.dropped;
  const byScenario = new Map(mine.map((s) => [s.id, s]));
  const seen = new Set(state.cards.map((card) => card.key));
  const settled = (s) => Boolean(s.settled);
  const take = async (focus, index, extra) => {
    const open = mine.filter((s) => !settled(s));
    const answer = await designBatch(ctx, doc, { focus, open, written: state.cards },
      objectives, index, extra);
    const openIds = new Set(open.map((s) => s.id));
    for (const card of answer.cards) {
      const scenario = byScenario.get(card.scenario);
      if (!scenario || !openIds.has(scenario.id)) continue;
      const tidy = tidyCard(card, new Set(scenario.rules));
      if (!tidy.rules.length) continue;
      const key = scenarioKey(scenario);
      if (seen.has(key)) {
        count.duplicates += 1;
        continue;
      }
      seen.add(key);
      state.cards.push({ ...tidy, key, breakIt: scenario.kind === 'break' });
      scenario.settled ??= { how: 'card' };
    }
    for (const skip of answer.skipped ?? []) {
      const scenario = byScenario.get(skip.scenario);
      if (scenario && openIds.has(scenario.id)) {
        scenario.settled ??= { how: skip.how, reason: skip.reason };
      }
    }
    state.uncovered.push(...answer.uncovered);
    state.reuse.push(...answer.reuse);
    state.assumptions.push(...answer.assumptions);
  };
  const perCall = ctx.config.cardScenariosPerCall ?? 4;
  for (const [i, group] of batches(mine, scenarioLine, 20000, perCall).entries()) {
    const todo = group.filter((s) => !settled(s));
    if (!todo.length) continue;
    await take(todo, only ? `${only}-${i + 1}` : i + 1);
    const left = todo.filter((s) => !settled(s));
    if (!left.length) continue;
    // One more try, told which scenarios it left with no card, reuse entry or skip.
    count.retried += 1;
    await take(left, only ? `${only}-${i + 1}b` : `${i + 1}b`,
      ' Every scenario listed needs a card or a skipped entry.');
  }
  // A retired Direct Change rule is tested by a card that verifies its behavior is gone. One
  // no card cites and no scenario names, whatever the inventory listed, gets a scenario of its own.
  const cited = () => new Set(state.cards.flatMap((card) => card.rules));
  // A scenario settled by a card that does not cite the rule leaves the rule owed a scenario.
  const named = () => new Set(state.scenarios.filter((s) => s.settled?.how !== 'card')
    .flatMap((s) => s.rules));
  const removed = only ? [] : rules.filter((rule) => removedBehavior(rule) && !cited().has(rule.id)
    && !named().has(rule.id));
  if (removed.length) {
    const made = removed.map((rule, i) => ({ id: `S${state.scenarios.length + i + 1}`, kind: 'decision',
      rules: [rule.id], population: 'a record the removed behavior used to apply to',
      action: `check that the behavior of ${rule.id} is gone`,
      outcome: 'The removed behavior is absent' }));
    state.scenarios.push(...made);
    mine.push(...made);
    for (const s of made) byScenario.set(s.id, s);
    await take(made, 'removed');
    const left = made.filter((s) => !settled(s));
    if (left.length) {
      count.retried += 1;
      await take(left, 'removedb', ' Every scenario listed needs a card or a skipped entry.');
    }
  }
  for (const s of mine.filter((x) => !settled(x))) {
    count.unsettled += 1;
    state.assumptions.push({
      assumption: `No test card covers scenario ${s.id}: ${s.population}; ${s.action}.`,
      why: 'The local design pass wrote no card and no skipped entry for it after a second try.',
      impact: `Rules ${s.rules.join(', ')} are not tested for this scenario.`,
      clarification: 'Design a card for this scenario by hand.' });
  }
  // Rule rows: none for a rule a card covers, one for any other. A rule only an
  // existing test covers reads Missing and points at that test.
  const covered = new Set(state.cards.flatMap((card) => card.rules));
  const rows = new Map();
  for (const row of state.uncovered) {
    if (!covered.has(row.ruleId) && !rows.has(row.ruleId)) rows.set(row.ruleId, row);
  }
  for (const rule of rules.filter((r) => !covered.has(r.id) && !rows.has(r.id))) {
    const named = state.scenarios.filter((s) => s.rules.includes(rule.id));
    const reused = named.find((s) => s.settled?.how === 'reused');
    const skipped = named.find((s) => s.settled?.how === 'gap');
    rows.set(rule.id, reused ? reuseRow(rule.id, reused.settled.reason)
      : { ruleId: rule.id, status: 'Missing',
        gap: skipped ? `No card can cover this rule: ${noStop(skipped.settled.reason)}.`
          : 'The local design pass wrote no card for this rule.',
        recommendation: 'Design a card for this rule by hand.' });
  }
  state.uncovered = [...rows.values()];
  return { designed: state, ...count };
}

// Words that reverse or narrow a result. Extra words like these on one side of a
// containment make it a different result: "saved" is not "not saved".
const REVERSING = new Set(['no', 'not', 'never', 'cannot', 'without', 'none', 'nothing', 'unless',
  'until', 'only', 'except']);
// A negated contraction, which `norm` splits into "isn t".
const contractions = (text) => (text.match(/n t(?= |$)/g) ?? []).length;

/**
 * Whether a card's Expected Result and its final step's say the same: equal
 * once case and punctuation are set aside, or one holds the other whole words
 * and all with no word of the longer side that negates or conditions it
 * (no, not, never, cannot, without, none, nothing, n't, unless, until, only,
 * except). Anything else is a mismatch, and so is a blank on either side.
 */
export function resultsAgree(card) {
  const last = list(card.steps).at(-1);
  if (!last) return true;
  const [a, b] = [norm(card.expected), norm(last.expected)];
  if (!a || !b) return false;
  if (a === b) return true;
  const [short, long] = a.length <= b.length ? [a, b] : [b, a];
  if (!` ${long} `.includes(` ${short} `)) return false;
  const extra = long.split(' ');
  for (const word of short.split(' ')) extra.splice(extra.indexOf(word), 1);
  return !extra.some((word) => REVERSING.has(word)) && contractions(long) === contractions(short);
}

/** The cards whose Expected Result disagrees with their final step's, one line each. */
export const expectedProblems = (pack) => list(pack.testCards).filter((card) => !resultsAgree(card))
  .map((card) => `${card.id} Expected Result "${noStop(card.expected ?? '')}" does not agree with`
    + ` its final step's "${noStop(list(card.steps).at(-1).expected ?? '')}". Keep the card's`
    + ' Expected Result and change that step\'s expected result to say the same.');

// The sheet name a mismatch is reported under; the builder has no such sheet.
const EXPECTED_SHEET = 'Test Card Expected Results';

const VERIFY_CARDS = 8;
const VERIFY_RULE = 'precedence: when two rules conflict, a rule that blocks an action outranks one that'
  + ' allows it, so the action stays blocked, unless a cited rule says it is an exception to the block'
  + ' or overrides it; Reset restores the saved value, never the edited one.';

/** A rule's source wording: its summary, and the master's full description when that adds to it. */
function ruleWording(ctx, rule, short) {
  const raw = short ? null : ctx.documents.flatMap((doc) => list(doc.rules))
    .find((row) => (row.rule_id ?? row.id) === rule.id);
  const parts = [rule.summary, raw?.description].filter((text) => !blank(text));
  if (isRetired(rule)) parts.unshift('removed: the card must show this no longer happens');
  return [...new Set(parts)].join(' / ');
}

const cardView = (card) => [`Title: ${card.title}`, `Expected Result: ${card.expected}`,
  ...list(card.steps).map((step, i) => `Step ${i + 1}: ${step.description} => ${step.expected}`
    + ` (rules ${list(step.rules).join(', ')})`)].join('\n');

/**
 * Asks, per card, whether its Expected Result follows from the rules it cites
 * as their source wording states them. Cards go in batches that fit the
 * room. A batch that is too big is split; a card too big alone is asked again
 * with rule summaries only, and if that is too big too it is left unverified.
 * Returns `failed` (the reason for each card that does not follow, by card)
 * and `unverified` (the cards no call could hold).
 */
async function verifyCards(ctx, cards, step) {
  const failed = new Map();
  const unverified = [];
  if (!cards.length) return { failed, unverified };
  const refs = [...ctx.ref.core, ...ctx.ref.chapters('6')];
  const byId = new Map(ctx.pack.rules.map((rule) => [rule.id, rule]));
  const wording = (card, short) => list(card.rules).map((id) => byId.get(id)).filter(Boolean)
    .map((rule) => `- ${rule.id} | ${rule.name} | page ${rule.sourcePage}: ${ruleWording(ctx, rule, short)}`);
  const cost = (card) => `${cardView(card)}\n${asLines(wording(card))}`;
  const run = async (group, name, short) => {
    const labeled = group.map((card, n) => ({ card, label: `C${n + 1}` }));
    let answer;
    try {
      answer = await ask(ctx, {
        phase: 'phase6', step: name, reasoning: false, refs,
        task: 'For each card, decide whether its Expected Result follows from the rules the card'
          + ' cites, read as their source wording states them, and from nothing else. Apply this'
          + ` ${VERIFY_RULE} Answer "does not follow" when the Expected Result contradicts a rule,`
          + ' rests on an allowance that a block overrides, restores a value other than the saved one,'
          + ' or states what no cited rule supports; say in the reason what the rules require instead.'
          + ' A rule marked removed was taken out: a card citing it follows when its Expected Result'
          + ' states the behavior is absent, and does not follow when it expects the behavior.',
        inputs: [['Cards', labeled.map(({ card, label }) => `### ${label}\n${cardView(card)}`).join('\n\n')],
          ['Rules and their source wording',
            asLines([...new Set(group.flatMap((card) => wording(card, short)))])]],
        schema: S.verificationSchema(labeled.map((row) => row.label)),
      });
    } catch (error) {
      if (!(error instanceof ModelError) || error.code !== 'too-big') throw error;
      if (group.length > 1) {
        ctx.logs.status({ job: ctx.job.id, phase: 'phase6', step: name, event: 'split', cards: group.length });
        for (const [n, card] of group.entries()) await run([card], `${name}s${n + 1}`, short);
      } else if (!short) await run(group, `${name}short`, true);
      else unverified.push(group[0]);
      return;
    }
    const verdicts = new Map(answer.cards.map((row) => [row.card, row]));
    for (const { card, label } of labeled) {
      const row = verdicts.get(label);
      if (row?.verdict === 'does not follow') failed.set(card, row.why);
    }
  };
  for (const [i, group] of batches(cards, cost, room(ctx, false, refs) - 1500, VERIFY_CARDS).entries()) {
    await run(group, `${step}-${i + 1}`, false);
  }
  return { failed, unverified };
}

const reuseRow = (ruleId, reason) => ({ ruleId, status: 'Missing',
  gap: `Covered only by the existing test ${noStop(reason)}; confirm it and reuse it.`,
  recommendation: 'Confirm the existing test covers this rule and reuse it, or design a card.' });

/**
 * Takes a card out of a document's design. Its scenario is settled as removed,
 * or by the `skip` a redesign answered with. An assumption says why, and each
 * of its rules no other card covers gets a Missing row: the existing reuse row
 * when an existing test covers it, else one with the reason.
 */
function removeCard(state, card, why, skip) {
  state.cards = state.cards.filter((c) => c !== card);
  const scenario = state.scenarios.find((s) => s.id === card.scenario);
  const given = skip && !blank(skip.reason) ? skip.reason : why;
  if (scenario) scenario.settled = skip ? { how: skip.how, reason: given } : { how: 'removed', reason: why };
  const reason = noStop(blank(given) ? 'its Expected Result does not follow from the rules' : given);
  state.assumptions.push({
    assumption: `The card "${card.title}" was removed${scenario ? ` for scenario ${scenario.id}` : ''}:`
      + (skip ? ' its Expected Result did not follow from its rules, and the redesign wrote no card for it.'
        : ' its Expected Result did not follow from its rules after one redesign.'),
    why: `${reason}.`, impact: `Rules ${card.rules.join(', ')} lose this card.`,
    clarification: 'Design a card for them by hand, checking its Expected Result against the rules.' });
  const covered = new Set(state.cards.flatMap((c) => c.rules));
  const lost = card.rules.filter((id) => !covered.has(id));
  const rowFor = (ruleId) => {
    const reused = state.scenarios.find((s) => s.settled?.how === 'reused' && s.rules.includes(ruleId));
    const kept = state.uncovered.find((row) => row.ruleId === ruleId);
    if (reused) return kept ?? reuseRow(ruleId, reused.settled.reason);
    return { ruleId, status: 'Missing',
      gap: skip?.how === 'gap' ? `No card can cover this rule: ${reason}.`
        : `The card for this rule was removed: ${reason}.`,
      recommendation: 'Design a card for this rule by hand, checking its Expected Result against the rules.' };
  };
  state.uncovered = [...state.uncovered.filter((row) => !lost.includes(row.ruleId)), ...lost.map(rowFor)];
}

/**
 * Verifies the cards of a document that are not yet `verified`. A card that
 * does not follow is designed again once, told why, and verified again; if it still fails, or no
 * card comes back, it is removed. A card no call could hold is kept with an
 * assumption saying it was not verified. Returns the counts.
 */
async function verifyDocument(ctx, doc, objectives, verified, tag = '') {
  const count = { redesigned: 0, removed: 0 };
  const state = ctx.designed[doc.key];
  const pending = state.cards.filter((card) => !verified.has(card));
  const note = (card) => {
    verified.add(card);
    state.assumptions.push({
      assumption: `The card "${card.title}" was not checked against its rules.`,
      why: 'Its steps and rules are too large for one verification call.',
      impact: `Its Expected Result for rules ${card.rules.join(', ')} is unchecked.`,
      clarification: 'Check its Expected Result against the rules by hand.' });
  };
  // A card that follows its rules but whose final step words the result differently has
  // its final step set to the card's Expected Result; only a card that does not follow is redone.
  const align = (card) => {
    const last = list(card.steps).at(-1);
    if (last && !resultsAgree(card)) last.expected = card.expected;
  };
  const first = await verifyCards(ctx, pending, `verify-d${doc.number}${tag}`);
  first.unverified.forEach(note);
  for (const card of pending) {
    if (first.failed.has(card)) continue;
    verified.add(card);
    if (!first.unverified.includes(card)) align(card);
  }
  const byId = new Map(ctx.pack.rules.map((rule) => [rule.id, rule]));
  const redone = [];
  for (const [card, why] of first.failed) {
    const scenario = state.scenarios.find((s) => s.id === card.scenario);
    if (!scenario) {
      removeCard(state, card, why);
      count.removed += 1;
      continue;
    }
    count.redesigned += 1;
    const others = state.cards.filter((c) => c !== card);
    const answer = await designBatch(ctx, doc, { focus: [scenario], open: [scenario], written: others },
      objectives, scenario.id,
      ` An earlier card for scenario ${scenario.id} was rejected because its Expected Result does`
      + ` not follow from its rules: ${noStop(why)}. Its Expected Result was "${noStop(card.expected)}". Write the card again for`
      + ` ${scenario.id} only, with an Expected Result that follows from the rules, repeated`
      + ` as the final step's expected result, applying this ${VERIFY_RULE}`, 'redo');
    const fresh = answer.cards.find((c) => c.scenario === scenario.id);
    const tidy = fresh && tidyCard(fresh, new Set(scenario.rules.filter((id) => byId.has(id))));
    if (!tidy?.rules.length) {
      const skip = (answer.skipped ?? []).find((row) => row.scenario === scenario.id);
      removeCard(state, card, why, skip);
      count.removed += 1;
      continue;
    }
    const next = { ...tidy, key: card.key, breakIt: card.breakIt };
    state.cards[state.cards.indexOf(card)] = next;
    redone.push([card, next, why]);
  }
  const again = await verifyCards(ctx, redone.map(([, next]) => next), `reverify-d${doc.number}${tag}`);
  again.unverified.forEach(note);
  for (const [, next, why] of redone) {
    if (again.failed.has(next)) {
      removeCard(state, next, again.failed.get(next) || why);
      count.removed += 1;
    } else {
      verified.add(next);
      if (!again.unverified.includes(next)) align(next);
    }
  }
  return count;
}

export async function phase6(ctx) {
  const { pack, job } = ctx;
  const objectives = cardObjectives(ctx);
  if (!objectives.length) throw new GateError('phase6', 'no-applicable-objective');
  ctx.designed = {};
  const total = { retried: 0, duplicates: 0, unsettled: 0, scenarios: 0, redesigned: 0, removed: 0 };
  const add = (done) => {
    for (const key of ['retried', 'duplicates', 'unsettled', 'redesigned', 'removed']) {
      total[key] += done[key] ?? 0;
    }
  };
  // Cards whose Expected Result has been checked against their rules. A card is
  // checked before the objective passes below, so a removal never leaves an
  // objective served by a card that is gone.
  const verified = new Set();
  for (const doc of ctx.documents.filter((d) => d.inclusion === 'Included')) {
    const done = await designDocument(ctx, doc, docRules(ctx, doc), objectives);
    ctx.designed[doc.key] = done.designed;
    add(done);
    add(await verifyDocument(ctx, doc, objectives, verified));
  }

  if (!job.suite) {
    const drop = (objective) => {
      // No card could serve it, so the decision cannot stand as Applicable.
      const row = pack.objectives.find((r) => r.objective === objective);
      row.applicable = false;
      row.reason = `${row.reason} ${DROPPED}`;
      ctx.droppedObjectives += 1;
    };
    const allCards = () => Object.values(ctx.designed).flatMap((d) => d.cards);
    // An applicable objective no card serves gets one targeted pass.
    for (const [n, objective] of objectives.entries()) {
      const served = () => allCards().some((card) => setsOf(ctx, card).includes(objective));
      if (served()) continue;
      if (objective === ctx.fullCoverageObjective) {
        // It holds every requirement card, so none being there leaves it empty.
        drop(objective);
      } else if (objective === ctx.breakItObjective) {
        // New break scenarios, each with one card, in the first document that has scenarios.
        const doc = ctx.documents.find((d) => ctx.designed[d.key]?.scenarios.length);
        if (doc) {
          const done = await designDocument(ctx, doc, docRules(ctx, doc), objectives,
            { designed: ctx.designed[doc.key], only: 'break' });
          add(done);
          add(await verifyDocument(ctx, doc, objectives, verified, '-break'));
          if (served()) {
            const gone = `${doc.name}: no break scenario was listed.`;
            done.designed.assumptions = done.designed.assumptions
              .filter((a) => a.assumption !== gone);
          }
        }
        if (!served()) drop(objective);
      } else {
        // Ask which of the cards already written serve it; none new is written.
        const refs = allCards().map((card, i) => ({ card, ref: `C${i + 1}` }));
        const answer = refs.length ? await ask(ctx, {
          phase: 'phase6', step: `objective-${n + 1}`, reasoning: false,
          refs: [...ctx.ref.core, ...ctx.ref.chapters('6')],
          task: `Name the cards that serve the objective ${objective}. Name none if no card does.`,
          inputs: [['Change description', ctx.description], ['Objective', objective],
            ['Cards', asLines(refs.map(({ card, ref }) => `- ${ref} | ${card.title} | `
              + `${list(card.focus).join('; ')} | ${list(card.objectives).join(', ')}`))]],
          schema: S.objectiveCardsSchema(refs.map((r) => r.ref)),
        }) : { cards: [] };
        const named = new Set(answer.cards);
        for (const { card, ref } of refs) {
          if (named.has(ref)) card.objectives = [...new Set([...list(card.objectives), objective])];
        }
        if (!served()) drop(objective);
      }
    }
  }
  const cards = Object.values(ctx.designed).reduce((n, d) => n + d.cards.length, 0);
  total.scenarios = Object.values(ctx.designed).reduce((n, d) => n + d.scenarios.length, 0);
  return { cards, ...total };
}

// ---------------------------------------------------------------------------
// Phase 7, Test Lab / Execution Design, and the issue pack's assembly

function setSummary(cards) {
  return [...new Set(cards.map((card) => card.module))].map((module) => {
    const mine = cards.filter((card) => card.module === module);
    const ruleCount = new Set(mine.flatMap((card) => card.rules)).size;
    return `${module}: ${ruleCount} rule(s) on ${mine.length} card(s)`;
  });
}

export async function phase7(ctx) {
  const { pack, ref, job } = ctx;
  // An issue pack's cards take their sets first: Full Coverage and BREAK IT by rule.
  if (!job.suite) {
    const full = pack.objectives.find((row) => row.objective === ctx.fullCoverageObjective);
    const designedCards = Object.values(ctx.designed).flatMap((d) => d.cards);
    if (full && !full.applicable && designedCards.some((card) => card.derivation !== 'Quality')) {
      // Only when some card lands in the set; otherwise the old decision stands.
      const before = { ...full };
      full.applicable = true;
      if (designedCards.some((card) => setsOf(ctx, card).includes(full.objective))) {
        full.reason = 'Applicable: this set holds every requirement-derived card.';
        if (before.reason.endsWith(DROPPED)) ctx.droppedObjectives -= 1;
      } else Object.assign(full, before);
    }
    for (const d of Object.values(ctx.designed)) {
      d.cards = d.cards.filter((card) => {
        const sets = setsOf(ctx, card);
        if (sets.length) card.objectives = sets;
        else {
          d.assumptions.push({ assumption: `The card "${card.title}" was left out: no set takes it.`,
            why: 'Its objectives were not applicable and no other set could hold it.',
            impact: `Rules ${card.rules.join(', ')} lose this card.`,
            clarification: 'Design a card for them by hand.' });
        }
        return sets.length > 0;
      });
    }
  }
  const order = job.suite ? ctx.suiteSetOrder : ctx.builder.OBJECTIVES;
  const used = order.filter((objective) => Object.values(ctx.designed)
    .some((d) => d.cards.some((card) => list(card.objectives).includes(objective)
      || (job.suite && card.derivation !== 'Quality' && ctx.suiteRunSets.includes(objective)))));
  const answer = await ask(ctx, {
    phase: 'phase7', step: 'sets', reasoning: false, refs: ref.core,
    task: 'Write the scope of the test set for each objective: what it runs and why, in one'
      + ' or two sentences.',
    inputs: [['Change description', ctx.description],
      ['Objectives with test sets', used.map((o) => `- ${o}`).join('\n')]],
    schema: S.setScopesSchema(used),
  });
  const scopes = Object.fromEntries(answer.sets.map((row) => [row.objective, row.scope]));
  ctx.setScopes = Object.fromEntries(used.map((o) => [o, scopes[o] || `Runs the ${o} cards.`]));
  if (job.suite) return { sets: used.length };

  // Issue pack: number the cards per module, requirement cards first, and
  // build one set per objective in the standard's order.
  const testCards = [];
  const coverage = [];
  const counters = new Map();
  for (const doc of ctx.documents.filter((d) => d.inclusion === 'Included')) {
    const designed = ctx.designed[doc.key];
    if (!designed) continue;
    const ordered = [...designed.cards].sort((a, b) =>
      (a.derivation === 'Quality') - (b.derivation === 'Quality'));
    for (const card of ordered) {
      const n = (counters.get(doc.abbreviation) ?? 0) + 1;
      counters.set(doc.abbreviation, n);
      testCards.push({
        id: `TC-${doc.abbreviation}-${job.issue}-${String(n).padStart(3, '0')}`,
        title: card.title, module: doc.module, sourceDocument: doc.name, mission: card.mission,
        focus: card.focus, expected: card.expected, rules: card.rules,
        objectives: card.objectives, derivation: card.derivation, steps: card.steps,
      });
    }
    coverage.push(...designed.uncovered.map((row) => ({ ruleId: row.ruleId, status: row.status,
      strength: row.status === 'Partially Covered' ? 'Partial' : 'None', gap: row.gap,
      recommendation: row.recommendation })));
    pack.assumptions.push(...designed.assumptions);
    ctx.reuse.push(...designed.reuse.map((line) => `${doc.key}: ${line}`));
  }
  pack.testCards = testCards;
  pack.coverage = coverage;
  pack.testSets = used.map((objective, i) => {
    const cards = testCards.filter((card) => card.objectives.includes(objective));
    return { number: i + 1, name: `TS${String(i + 1).padStart(2, '0')} ${objective}`, objective,
      scope: ctx.setScopes[objective], ruleSummary: setSummary(cards), cards: cards.map((c) => c.id) };
  });
  return { sets: pack.testSets.length, cards: testCards.length };
}

/** The suite pack, from the card files and the narrative, through the repository's merge. */
export function mergeSuite(ctx) {
  const { pack } = ctx;
  const narrative = {
    suite: pack.suite, suiteInput: pack.suiteInput, crDescription: pack[ctx.config.idFields.description],
    intake: pack.intake, executiveSummary: pack.executiveSummary, objectives: pack.objectives,
    setScopes: ctx.setScopes, seniorReview: pack.seniorReview ?? {}, testerNotes: pack.testerNotes ?? {},
    confidence: pack.confidence ?? {}, limitations: pack.limitations, improvementNotes: pack.improvementNotes,
    assumptions: pack.assumptions ?? [], sourceAuthority: ctx.config.suiteMerge?.sourceAuthority
      ?? 'approved business rules held in the master',
    modules: Object.fromEntries(ctx.documents.map((doc) => [doc.key, [doc.module, doc.abbreviation]])),
  };
  // The merge reads cards as the builder knows them, without the design pass's marks.
  const designed = Object.fromEntries(Object.entries(ctx.designed).map(([key, d]) => [key,
    { ...d, cards: d.cards.map(({ scenario, breakIt, key, ...card }) => card) }]));
  const merged = ctx.suiteMerge.mergeSuitePack({ exportJson: ctx.exportJson, designed, narrative });
  // The merge carries the narrative's coverage rows only for uncovered rules;
  // the review's rows ride on top.
  const rows = new Map(merged.coverage.map((row) => [row.ruleId, row]));
  for (const row of pack.reviewCoverage ?? []) rows.set(row.ruleId, row);
  merged.coverage = [...rows.values()];
  // The merge's narrative names the description crDescription; the pack keeps
  // it under the field the repository's builder reads.
  merged[ctx.config.idFields.description] ??= pack[ctx.config.idFields.description];
  return merged;
}

// ---------------------------------------------------------------------------
// Phase 8, the builder, with bounded repairs

/**
 * Drops the assumptions that cite a rule ID the pack does not hold, or a count
 * of rules or cards the pack does not have. A count is checked against the
 * pack's totals, its counts by impact, risk, coverage status, derivation and
 * source document, and its set sizes. Returns how many were dropped.
 */
export function dropUnfoundedAssumptions(ctx, pack) {
  const rules = list(pack.rules);
  if (!rules.length || !list(pack.assumptions).length) return 0;
  const shape = ctx?.config?.ruleShape ?? RULE_SHAPE;
  const known = new Set([...rules.map((r) => r.id), ...list(pack.coverage).map((r) => r.ruleId),
    ...list(pack.testCards).flatMap((card) => list(card.rules)),
    ...list(ctx?.documents).flatMap((doc) => list(doc.rules).map((r) => r.rule_id))]);
  const idPattern = new RegExp(`\\b${String(shape.prefixPattern).replace(/^\^/, '')}[A-Z0-9.-]*?`
    + `${shape.ruleIdPattern}\\b`, 'g');
  const tally = (items, key) => Object.values(items.reduce((acc, item) => {
    const k = String(key(item)); acc[k] = (acc[k] ?? 0) + 1; return acc;
  }, {}));
  const cards = list(pack.testCards);
  const ruleCounts = new Set([rules.length, ...tally(rules, (r) => r.impact),
    ...tally(rules, (r) => r.risk), ...tally(rules, (r) => r.sourceDocument),
    ...tally(rules, (r) => r.module), ...tally(list(pack.coverage), (r) => r.status),
    rules.filter((r) => !String(r.summary ?? '').startsWith(RETIRED_SUMMARY)).length,
    rules.filter((r) => String(r.summary ?? '').startsWith(RETIRED_SUMMARY)).length]);
  const cardCounts = new Set([cards.length, ...tally(cards, (c) => c.derivation),
    ...tally(cards, (c) => c.module), ...list(pack.testSets).map((set) => list(set.cards).length)]);
  const QUALIFIER = '(?:(?:active|retired|impacted|direct change|indirect impact|regression|not impacted'
    + '|covered|partially covered|weakly covered|missing|uncovered|high|medium|low|new|existing|business)\\s+)*';
  const counted = new RegExp(`\\b(\\d+)\\s+${QUALIFIER}(rules?|BRs?|(?:test )?cards?|test cases?)\\b`, 'gi');
  // A number that names a section, step or page, ends a range, or is a year is not a count.
  const notCount = (text, index, n) => /\b(?:section|sections|step|steps|page|pages|chapter|row|rows)\s*$/i
    .test(text.slice(0, index)) || /\d\s*(?:to|through|-|–)\s*$|\bbetween\s+\d+\s+and\s*$/i.test(text.slice(0, index))
    || (/^(?:19|20)\d\d$/.test(n) && /\b(?:in|since|from|until)\s*$/i.test(text.slice(0, index)));
  const grounded = (text) => {
    for (const id of String(text).match(idPattern) ?? []) if (!known.has(id)) return false;
    for (const { 1: n, 2: noun, index } of String(text).matchAll(counted)) {
      if (Number(n) === 1 || notCount(text, index, n)) continue;
      const allowed = /rule|BR/i.test(noun) ? ruleCounts : cardCounts;
      if (!allowed.has(Number(n))) return false;
    }
    return true;
  };
  const before = pack.assumptions.length;
  pack.assumptions = pack.assumptions.filter((a) => {
    const ok = grounded([a.assumption, a.why, a.impact, a.clarification].filter(Boolean).join(' '));
    if (!ok) ctx?.logs?.detail?.('assumption dropped: it cites a rule or count the pack does not hold',
      String(a.assumption));
    return ok;
  });
  return before - pack.assumptions.length;
}

/**
 * Settles what code can settle before the builder looks: coverage rows that
 * disagree with the cards, assumptions citing rules or counts the pack does not
 * hold, a blank assumptions sheet, Direct Change rules no card covers.
 */
export function reconcile(ctx, pack) {
  dropUnfoundedAssumptions(ctx, pack);
  const covered = new Map();
  for (const card of list(pack.testCards)) {
    for (const id of list(card.rules)) {
      const entry = covered.get(id) ?? { requirement: false };
      if (card.derivation !== 'Quality') entry.requirement = true;
      covered.set(id, entry);
    }
  }
  const ruleIds = new Set(list(pack.rules).map((rule) => rule.id));
  const reviewed = new Set(list(pack.coverage).map((row) => row.ruleId));
  const seen = new Set();
  const claims = ['Covered', 'Partially Covered', 'Weakly Covered'];
  // A High-risk Not Impacted rule needs a regression card or a stated reason, which only a
  // person or the repair call can give, so its blanks are left for the Phase 8 check.
  const highRisk = new Set(list(pack.rules).filter((rule) => rule.impact === 'Not Impacted'
    && String(rule.risk).toLowerCase() === 'high').map((rule) => rule.id));
  const mapping = (id) => `Not reviewed; coverage rests on the card mapping (${list(pack.testCards)
    .filter((card) => list(card.rules).includes(id)).map((card) => card.id).join(', ')}).`;
  const confirm = 'Confirm in review that the cards exercise this rule.';
  pack.coverage = list(pack.coverage).filter((row) => {
    if (!ruleIds.has(row.ruleId) || seen.has(row.ruleId)) return false;
    const cards = covered.get(row.ruleId);
    // A review row that denies coverage a card gives is kept when it says why, so the builder
    // fails it and the repair call reads the review's own words.
    if (cards && !claims.includes(row.status) && blank(row.gap)) return false;
    if (!cards && claims.includes(row.status)) return false;
    if (row.status === 'Covered' && cards && !cards.requirement) row.status = 'Weakly Covered';
    seen.add(row.ruleId);
    return true;
  }).map((row) => ({ ...row,
    strength: blank(row.strength) ? (row.status === 'Partially Covered' ? 'Partial' : 'Weak') : row.strength,
    gap: blank(row.gap) && !(row.status === 'Covered' && highRisk.has(row.ruleId))
      ? (row.status === 'Covered' ? mapping(row.ruleId) : 'Not stated by the review.') : row.gap,
    recommendation: blank(row.recommendation) && !(row.status === 'Covered' && highRisk.has(row.ruleId))
      ? (row.status === 'Covered' ? confirm : 'Review this rule\'s coverage by hand.')
      : row.recommendation }));
  // A rule with a requirement card and no review row at all reads Covered, as the builder would
  // have it, and says that no one reviewed it.
  for (const rule of list(pack.rules)) {
    if (!covered.get(rule.id)?.requirement || seen.has(rule.id) || reviewed.has(rule.id)
      || highRisk.has(rule.id)) continue;
    pack.coverage.push({ ruleId: rule.id, status: 'Covered', strength: 'Strong',
      gap: mapping(rule.id), recommendation: confirm });
    seen.add(rule.id);
  }
  for (const rule of list(pack.rules)) {
    if (covered.has(rule.id) || seen.has(rule.id) || rule.impact === 'Not Impacted') continue;
    pack.coverage.push({ ruleId: rule.id, status: 'Missing', strength: 'None',
      gap: 'No test card covers this rule.', recommendation: 'Design a card for this rule.' });
  }
  const uncoveredDirect = list(pack.rules).filter((rule) => rule.impact === 'Direct Change'
    && !covered.has(rule.id)).map((rule) => rule.id);
  pack.limitations ??= {};
  if (uncoveredDirect.length) {
    pack.limitations['Coverage Matrix'] = `Direct Change rules with no test card: ${uncoveredDirect.join(', ')}.`;
  }
  if (!list(pack.assumptions).length && blank(pack.limitations.Assumptions)) {
    pack.limitations.Assumptions = 'No assumptions were needed to build this pack.';
  }
  const overall = pack.confidence?.overall;
  if (overall && pack.executiveSummary) pack.executiveSummary.confidence = overall;
  for (const [sheet, text] of Object.entries(pack.limitations)) {
    if (blank(text)) delete pack.limitations[sheet];
  }
  return pack;
}

/** The failed sheets' problems, as text for the model. */
const problemText = (built) => built.failed.map(([sheet, , , , notes]) => `${sheet}:\n${notes}`)
  .join('\n\n');

/** Sheets Phase 9 fills, which the build before the review leaves to it. */
export const REVIEW_SHEETS = ['Senior Tester Review', 'Tester Notes', 'Confidence Assessment',
  'Executive Summary'];

export async function phase8(ctx, pack, label = 'build', deferred = []) {
  const { builder } = ctx;
  for (let attempt = 0; ; attempt += 1) {
    reconcile(ctx, pack);
    const whole = builder.buildPack(pack);
    if (whole.stop) throw new GateError('phase8', 'builder-stop');
    // The pipeline's own check of each card's Expected Result against its final step,
    // reported beside the builder's sheets so the repair call reads it the same way.
    const mismatched = expectedProblems(pack);
    // The pipeline's own checks of the pack against itself, run for any builder.
    const { failed: checked, warnings } = checkPack(pack, whole);
    for (const { code, text } of warnings) ctx.logs.detail(`builder warning ${code} ${label} ${attempt}`, text);
    const built = { ...whole, failed: [...whole.failed.filter(([sheet]) => !deferred.includes(sheet)),
      ...checked.filter(([sheet]) => !deferred.includes(sheet)),
      ...(mismatched.length ? [[EXPECTED_SHEET, 'Yes', 'Yes', 'FAIL', mismatched.join('\n')]] : [])] };
    const failed = built.failed.length;
    const statuses = built.validation.map((row) => row[3]);
    ctx.logs.status({ job: ctx.job.id, phase: 'phase8', step: label, event: 'builder', attempt,
      failed, limited: statuses.filter((s) => s === 'PASS WITH LIMITATIONS').length,
      passed: statuses.filter((s) => s === 'PASS').length });
    if (!failed) return pack;
    ctx.logs.detail(`builder ${label} ${attempt}`, problemText(built));
    if (attempt >= ctx.config.builder.retries) {
      throw new GateError('phase8', 'builder-fail', { sheets: failed });
    }
    await repair(ctx, pack, built, `${label}-${attempt + 1}`);
  }
}

/** One repair call: the builder's FAIL text, the cards and rules it names, and their fixes. */
async function repair(ctx, pack, built, step) {
  const text = problemText(built);
  const cards = list(pack.testCards).filter((card) => text.includes(card.id));
  const ruleIds = list(pack.rules).map((rule) => rule.id);
  const named = list(pack.rules).filter((rule) => text.includes(rule.id)
    || cards.some((card) => card.rules.includes(rule.id)));
  const sheets = (ctx.builder.SHEET_ORDER ?? built.validation.map((row) => row[0]))
    .filter((sheet) => sheet !== 'Workbook Validation');
  const objectives = ctx.job.suite ? ctx.builder.OBJECTIVES
    : pack.objectives.filter((row) => row.applicable).map((row) => row.objective);
  const answer = await ask(ctx, {
    phase: 'phase8', step: `repair-${step}`, reasoning: false, refs: [ctx.ref.docs.workbookStandard],
    task: 'The workbook builder failed these sheets. Fix each problem: return every named card'
      + ' corrected in full, a coverage row for each rule whose coverage is wrong, and a'
      + ' limitation for a sheet that cannot be completed, saying why.',
    inputs: [['Builder problems', text],
      ['Cards named', cards.map((card) => JSON.stringify(card)).join('\n')],
      ['Rules named', asLines(named.map(ruleLine))]],
    schema: S.repairSchema({ cardIds: cards.map((card) => card.id), ids: ruleIds, objectives,
      derivations: ctx.builder.DERIVATIONS, statuses: ctx.builder.COVERAGE_STATUSES, sheets }),
  });
  const before = new Map(cards.map((card) => [card.id, card.expected]));
  for (const fixed of answer.cards) {
    const card = pack.testCards.find((c) => c.id === fixed.id);
    if (!card) continue;
    const tidy = tidyCard(fixed, new Set(ruleIds.filter((id) => pack.rules
      .find((rule) => rule.id === id)?.module === card.module)));
    if (tidy.rules.length) Object.assign(card, { ...tidy, id: card.id, module: card.module,
      sourceDocument: card.sourceDocument });
  }
  // A repair that changed a card's Expected Result is checked against the rules again; one
  // that does not follow is undone, final step included.
  const changed = cards.filter((card) => card.expected !== before.get(card.id));
  const { failed } = await verifyCards(ctx, changed, `recheck-${step}`);
  for (const card of failed.keys()) {
    const kept = before.get(card.id);
    card.expected = kept;
    const last = list(card.steps).at(-1);
    if (last) last.expected = kept;
    pack.assumptions ??= [];
    pack.assumptions.push({
      assumption: `The repair of card ${card.id} changed its Expected Result, and the change was undone.`,
      why: `${noStop(failed.get(card))}.`, impact: 'The card keeps the Expected Result checked in Phase 6.',
      clarification: 'Check the card by hand if the builder still reports it.' });
  }
  const rows = new Map(list(pack.coverage).map((row) => [row.ruleId, row]));
  for (const row of answer.coverage) rows.set(row.ruleId, row);
  pack.coverage = [...rows.values()];
  for (const { sheet, text: why } of answer.limitations) {
    if (!blank(why)) pack.limitations[sheet] = why;
  }
  ctx.repairs += 1;
}

// ---------------------------------------------------------------------------
// Phase 9, Quality Review

function packView(ctx, pack, detail) {
  const coverage = ctx.builder.ruleCoverage ? ctx.builder.ruleCoverage(pack) : [];
  const status = new Map(coverage.map((row) => [row.rule.id, row.status]));
  const rules = list(pack.rules).map((rule) => (detail
    ? `- ${rule.id} | ${rule.name} | ${rule.impact} | risk ${rule.risk} | ${status.get(rule.id) ?? ''}`
    : `- ${rule.id} | ${rule.impact} | ${status.get(rule.id) ?? ''}`));
  const cards = list(pack.testCards).map((card) => (detail
    ? `- ${card.id} | ${card.title} | ${card.derivation} | rules ${card.rules.join(', ')}`
    : `- ${card.id} | ${card.derivation} | ${card.rules.length} rule(s)`));
  const sets = list(pack.testSets).map((set) => `- ${set.name}: ${list(set.cards).length} card(s)`);
  return [['Rules', asLines(rules)], ['Test cards', asLines(cards)], ['Test sets', asLines(sets)],
    ['Executive summary', JSON.stringify(pack.executiveSummary)],
    ['Objectives', asLines(list(pack.objectives).map((row) =>
      `- ${row.objective}: ${row.applicable ? 'Applicable' : 'Not Applicable'}`))]];
}

/** Fix rounds the review runs between the checklist and the revalidation. */
const REVIEW_FIX_ROUNDS = 2;
/** The sheet name the review's findings are reported under to the repair call. */
const REVIEW_SHEET = 'Quality Review';

/**
 * The pack with the sheets Phase 9 has not filled yet standing in, so the
 * builder writes a workbook for the review to read.
 */
function draftPack(ctx, pack) {
  const draft = reconcile(ctx, structuredClone(pack));
  delete draft.revalidation;
  // A field the review has not written is blank, or an empty object a suite merge leaves.
  const standIn = (current, schema, over = {}) => ({
    ...Object.fromEntries(Object.keys(schema.properties).map((key) => [key, 'Pending review.'])),
    ...Object.fromEntries(Object.entries(current ?? {}).filter(([, value]) => !blank(value))),
    ...over });
  draft.seniorReview = standIn(draft.seniorReview, S.seniorReviewSchema.properties.seniorReview);
  draft.testerNotes = standIn(draft.testerNotes, S.seniorReviewSchema.properties.testerNotes);
  draft.confidence = standIn(draft.confidence,
    { properties: Object.fromEntries(['overall', ...CONFIDENCE_FIELDS.map(([field]) => field)].map((key) => [key, 0])) },
    ctx.builder.CONFIDENCE_LEVELS.includes(draft.confidence?.overall) ? {}
      : { overall: ctx.builder.CONFIDENCE_LEVELS[1] ?? ctx.builder.CONFIDENCE_LEVELS[0] });
  if (draft.executiveSummary) draft.executiveSummary.confidence ||= draft.confidence.overall;
  return draft;
}

/** The workbook the builder writes for the pack as it stands, read back as sheets. */
function builtSheets(ctx, pack) {
  const dir = path.join(ctx.config.output, ctx.job.id, 'work', 'review');
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, 'draft-pack.json');
  fs.writeFileSync(file, JSON.stringify(draftPack(ctx, pack)));
  runCommand(ctx, ctx.config.builder.command, { pack: file, out: dir });
  const book = fs.readdirSync(dir).find((name) => name.endsWith('.xlsx'));
  if (!book) throw new GateError('phase9', 'review-workbook-missing');
  return readXlsx(path.join(dir, book)).map(readSheet);
}

/**
 * The built workbook as text, one row to a line, in pieces that each fit
 * `tokens`. The sheets Phase 9 writes itself and the validation sheet are left out.
 */
function workbookPieces(ctx, pack, tokens) {
  const skip = new Set([...REVIEW_SHEETS, 'Workbook Validation']);
  const lines = builtSheets(ctx, pack).filter((sheet) => !skip.has(sheet.name)).flatMap((sheet) => [
    ...(sheet.title ? [`[${sheet.name}] ${sheet.title.text}`] : []),
    ...sheet.rows.map((row) => `[${sheet.name} row ${row.n}] ${Object.entries(row.cells)
      .filter(([, value]) => value).map(([header, value]) => `${header}: ${value}`).join(' | ')}`),
  ]).flatMap((line) => splitText(line, tokens));
  return batches(lines, (line) => line, tokens).map((group) => group.join('\n'));
}

/** Room for the workbook text in one review call, after the description and `extra`. */
const reviewBudget = (ctx, refs, extra) => room(ctx, true, refs) - estimateTokens(ctx.description)
  - 2000 - estimateTokens(extra.map(([, text]) => text).join('\n'));

/** Every rule with its impact and the cards that cite it, one line each. */
function rulesIndex(pack) {
  return list(pack.rules).map((rule) => {
    const cards = list(pack.testCards).filter((card) => list(card.rules).includes(rule.id))
      .map((card) => card.id);
    return { id: rule.id, line: `- ${rule.id} | ${rule.impact} | cards: ${cards.join(', ') || 'none'}` };
  });
}

/**
 * What the review calls read: one view per piece of the built workbook. A
 * workbook in several parts opens each part with an index of the rules that part
 * shows and the cards that cite them, so a part that shows a rule but not its
 * cards can still see them; the index takes at most a third of the room. A
 * builder that writes no workbook for the draft leaves the review the
 * `packView` summary, labeled as such, in parts that fit.
 */
function reviewViews(ctx, pack, refs, extra = []) {
  const budget = reviewBudget(ctx, refs, extra);
  if (budget < 1000) throw new GateError('phase9', 'pack-too-big-to-review');
  const piecesFor = (tokens) => {
    try {
      return { label: 'Built workbook', pieces: workbookPieces(ctx, pack, tokens) };
    } catch (error) {
      if (!(error instanceof GateError) || error.code !== 'review-workbook-missing') throw error;
      ctx.logs.status({ job: ctx.job.id, phase: 'phase9', event: 'warn', reason: error.code });
      return { label: 'Pack summary (no workbook was built to read)',
        pieces: splitText(packView(ctx, pack, true).map(([name, text]) => `${name}:\n${text}`)
          .join('\n\n'), tokens) };
    }
  };
  let { label, pieces } = piecesFor(budget);
  const index = rulesIndex(pack);
  const cap = Math.floor(budget / 3);
  if (pieces.length > 1) ({ label, pieces } = piecesFor(budget - cap));
  if (!pieces.length) throw new GateError('phase9', 'review-workbook-empty');
  if (pieces.length === 1) return [[[label, pieces[0]]]];
  return pieces.map((text, i) => {
    const lines = [];
    let used = 0;
    for (const row of index.filter((rule) => text.includes(rule.id))) {
      used += estimateTokens(row.line);
      if (used > cap) break;
      lines.push(row.line);
    }
    return [...(lines.length ? [['Rules in this part and the cards that cite them', asLines(lines)]] : []),
      [`${label}, part ${i + 1} of ${pieces.length}`, text]];
  });
}

/**
 * The references and workbook text every single-answer review call reads, with
 * the description and any earlier review answers. A workbook too long for one
 * call is summarized by `packView` for these calls; the checklist and the
 * revalidation read it in parts.
 */
function reviewInputs(ctx, pack, extra = []) {
  const { ref } = ctx;
  const refs = [...ref.core, ref.docs.validation, ...ref.chapters('9')];
  const views = reviewViews(ctx, pack, refs, extra);
  let view = views[0];
  if (views.length > 1) {
    const budget = reviewBudget(ctx, refs, extra);
    const size = (rows) => estimateTokens(rows.map(([, text]) => text).join('\n'));
    view = packView(ctx, pack, true);
    if (size(view) > budget) view = packView(ctx, pack, false);
    if (size(view) > budget) throw new GateError('phase9', 'pack-too-big-to-review');
  }
  return { refs, inputs: [['Change description', ctx.description], ...view, ...extra] };
}

const issueText = (ctx) => list(ctx.reviewFindings)
  .map((row) => `- ${row.issue} (fix: ${row.fix})`).join('\n');

/**
 * Phase 9 runs as four steps, each a checkpoint of its own, so no one call
 * thinks through the whole review. The first runs the checklist over the built
 * workbook, in parts when it is long: issues, the coverage rows for rules not
 * plainly Covered, and assumptions. `again` is a check after a fix round, which
 * replaces the issues and keeps the rest.
 */
export async function phase9Checklist(ctx, pack, { again = false } = {}) {
  const refs = [...ctx.ref.core, ctx.ref.docs.validation, ...ctx.ref.chapters('9')];
  const views = reviewViews(ctx, pack, refs);
  // Rules taken from document text leave the checklist no matrix export to check them against.
  const limited = ctx.derived > 0;
  const noExport = !ctx.config.inputs.ruleExport;
  const derivedFrom = list(ctx.derivedDocuments).join(', ') || 'some documents';
  const answers = [];
  for (const [i, view] of views.entries()) {
    answers.push(await ask(ctx, {
      phase: 'phase9', step: again ? 'checklist-again' : 'checklist', reasoning: true, refs,
      inputs: [['Change description', ctx.description], ...view],
      task: 'Run the Validation checklist against this pack. List each issue and its fix. A fix'
        + ' names the card or rule to change and what to change it to; leave it blank for an'
        + ' issue no change to the pack can settle. Give a coverage row for every rule that is'
        + ' not plainly Covered, with its strength, gap and recommendation. Add the assumptions'
        + ' the pack still needs.'
        + (views.length > 1 ? ` The workbook comes in ${views.length} parts; this is part`
          + ` ${i + 1}. Report what this part shows, and judge a rule's coverage only from the`
          + ' cards the rules index lists for it when this part shows them.' : '')
        + (limited ? (noExport
          ? ' The rules were derived from document text because no Requirements Matrix export'
            + ' was available, so run checklist item OPS-009 as limited and say so.'
          : ` The rule export held no rules for ${derivedFrom}, so their rules were derived from`
            + ' the document text; run checklist item OPS-009 as limited for those rules and say'
            + ' so.') : ''),
      schema: S.checklistSchema({ statuses: ctx.builder.COVERAGE_STATUSES }),
    }));
  }
  const issues = answers.flatMap((answer) => answer.issues);
  ctx.private(again ? 'phase9-issues-again.json' : 'phase9-issues.json', issues);
  ctx.reviewFindings = issues;
  if (again) return { issues: issues.length, coverageRows: 0 };
  pack.assumptions = [...list(pack.assumptions), ...answers.flatMap((answer) => answer.assumptions),
    ...(limited ? [{ assumption: noExport
      ? 'Checklist item OPS-009 ran limited: no Requirements Matrix export was available.'
      : `Checklist item OPS-009 ran limited for the rules of ${derivedFrom}: the rule export held`
        + ' none for them.',
    why: 'The rules were derived from document text, so there is no matrix to check them against.',
    impact: 'The matrix check covers only the rules in this pack.',
    clarification: noExport ? 'Export the Requirements Matrix and run the check again.'
      : 'Extract the rules for these documents and run the check again.' }] : [])];
  const ruleIds = new Set(list(pack.rules).map((rule) => rule.id));
  const reviewRows = answers.flatMap((answer) => answer.coverage).filter((row) =>
    ruleIds.has(row.ruleId) && row.status !== 'Covered');
  const rows = new Map(list(pack.coverage).map((row) => [row.ruleId, row]));
  for (const row of reviewRows) rows.set(row.ruleId, row);
  pack.coverage = [...rows.values()];
  pack.reviewCoverage = reviewRows;
  return { issues: issues.length, coverageRows: reviewRows.length };
}

/**
 * The fix loop between the checklist and the revalidation. Each finding with a
 * fix goes through `repair`, the pack is rebuilt, and the checklist reads the
 * rebuilt workbook again; at most two rounds. Findings left after the last
 * round stay in `ctx.reviewFindings` for the later calls.
 */
export async function phase9Fix(ctx, pack) {
  ctx.appliedFixes ??= [];
  let rounds = 0;
  while (rounds < REVIEW_FIX_ROUNDS) {
    const findings = list(ctx.reviewFindings).filter((row) => fixable(pack, row));
    if (!findings.length) break;
    rounds += 1;
    // The review's findings change cards only: coverage rows and limitations stay as the
    // pack had them, so a false finding cannot downgrade a rule or add a limitation.
    const kept = structuredClone({ coverage: pack.coverage, limitations: pack.limitations });
    for (const [n, group] of fixGroups(ctx, pack, findings).entries()) {
      const text = group.map((row) => `- ${row.issue}\n  Fix: ${row.fix}`).join('\n');
      await repair(ctx, pack, { failed: [[REVIEW_SHEET, 'Yes', 'Yes', 'FAIL', text]], validation: [] },
        `review-${rounds}-g${n + 1}`);
    }
    Object.assign(pack, kept);
    await phase8(ctx, pack, `review-${rounds}`, REVIEW_SHEETS);
    for (const row of findings) {
      const line = `- ${row.issue} (fix: ${row.fix})`;
      if (!ctx.appliedFixes.includes(line)) ctx.appliedFixes.push(line);
    }
    await phase9Checklist(ctx, pack, { again: true });
  }
  return { rounds };
}

/** A fix the review can hand to repair: not a placeholder, and it names a card the pack holds. */
function fixable(pack, row) {
  if (blank(row.fix) || /^\W*(n\/?a|none|nothing|no change|not applicable|no fix)\b/i.test(row.fix)) {
    return false;
  }
  const text = `${row.issue} ${row.fix}`;
  return list(pack.testCards).some((card) => text.includes(card.id));
}

/** The findings in groups whose named cards fit one repair call. */
function fixGroups(ctx, pack, findings) {
  const budget = Math.max(1000, room(ctx, false, [ctx.ref.docs.workbookStandard]) - 3000);
  const cost = (row) => estimateTokens(`${row.issue} ${row.fix}`) + list(pack.testCards)
    .filter((card) => `${row.issue} ${row.fix}`.includes(card.id))
    .reduce((n, card) => n + estimateTokens(JSON.stringify(card)) + estimateTokens(asLines(
      list(pack.rules).filter((rule) => list(card.rules).includes(rule.id)).map(ruleLine))), 0);
  const groups = [];
  let size = 0;
  for (const row of findings) {
    if (!groups.length || size + cost(row) > budget) {
      groups.push([]);
      size = 0;
    }
    groups.at(-1).push(row);
    size += cost(row);
  }
  return groups;
}

/**
 * The prose fields of the review sheets, as { name, text } rows: the Confidence
 * Assessment fields, the senior review answers and the tester notes.
 */
function reviewProse(pack) {
  const text = (value) => (Array.isArray(value) ? value.join(' ') : String(value ?? '')).trim();
  return [['Confidence Assessment', pack.confidence], ['Senior Tester Review', pack.seniorReview],
    ['Tester Notes', pack.testerNotes]].flatMap(([sheet, fields]) => Object.entries(fields ?? {})
    .filter(([field]) => field !== 'overall')
    .map(([field, value]) => ({ name: `${sheet} ${field}`, text: text(value) })));
}

// A short answer such as "Not applicable." or "None." is the right answer for more than one
// field, so only a text this long counts as one field repeating another.
const TWIN_MIN_CHARS = 40;
const sameText = (a, b) => {
  const flat = (text) => text.toLowerCase().split(/\s+/).join(' ');
  return flat(a).length >= TWIN_MIN_CHARS && flat(a) === flat(b);
};

/** The card and rule IDs a text cites that the pack does not hold, among the ID families it uses. */
function unknownIds(pack, text) {
  const known = new Set([...list(pack.testCards), ...list(pack.rules)].map((item) => item.id));
  const families = [...new Set([...known].map((id) => id.replace(/\d+$/, '')).filter((f) => f && f.endsWith('-')))];
  if (!families.length) return [];
  const escaped = families.map((family) => family.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const cited = String(text).match(new RegExp(`(?<![A-Za-z0-9.-])(?:${escaped.join('|')})\\d+`, 'g')) ?? [];
  return [...new Set(cited.filter((id) => !known.has(id)))];
}

/** What is wrong with one new field's text, or '': it repeats a field already written, or cites what the workbook lacks. */
function fieldProblem(pack, text, earlier) {
  if (!String(text ?? '').trim()) return 'it is blank';
  const twin = earlier.find((row) => row.text && sameText(row.text, String(text)));
  if (twin) return `it repeats the text of ${twin.name}; say something specific to this field`;
  const unknown = unknownIds(pack, text);
  if (unknown.length) return `it cites ${unknown.join(', ')}, which the workbook does not hold`;
  return '';
}

/** One confidence field, asked for on its own over the finished workbook; a refused text is asked for once more. */
async function writeConfidenceField(ctx, pack, field, task, extra) {
  let refusal = '';
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const earlier = reviewProse(pack);
    // The fields already written ride in `extra`, so the workbook is sized with them in view.
    const input = reviewInputs(ctx, pack, [...extra,
      ['Fields already written', asLines(earlier.map((row) => `- ${row.name}: ${row.text}`))]]);
    const answer = await ask(ctx, {
      phase: 'phase9', step: `confidence-${field}`, reasoning: true,
      ...input,
      task: `${task}${refusal}`,
      schema: S.confidenceFieldSchema(field),
    });
    const problem = fieldProblem(pack, answer[field], earlier);
    if (!problem) return String(answer[field]).trim();
    refusal = ` Your last answer for this field was refused: ${problem}.`;
  }
  throw new GateError('phase9', 'review-field-unsupported');
}

/** What each Confidence Assessment field says, in the order they are written. */
const CONFIDENCE_FIELDS = [
  ['coverage', 'State how well the cards cover the rules, from the Coverage Matrix of this workbook: how many rules are covered, partly covered or missing, and which ones.'],
  ['remainingRisks', 'Name the risks that remain after these cards, each tied to a rule or card in the workbook.'],
  ['assumptions', 'Summarize the assumptions this pack rests on, from its Assumptions sheet.'],
  ['regressionScope', 'Say what regression coverage the pack gives: which rules and sets guard behavior the change does not touch.'],
  ['breakItScope', 'Say what break-it coverage the pack gives, from its break-it cards, and what it does not try.'],
  ['manualReview', 'Say what a person must still check by hand, and why the pack cannot.'],
];

/**
 * The confidence assessment, written from the finished workbook after the checklist and
 * the fix rounds: the overall level first, then each field in a call of its own, each shown
 * the fields already written so no two say the same thing.
 */
export async function phase9Confidence(ctx, pack) {
  const extra = [['Checklist issues', issueText(ctx)]];
  const overall = await ask(ctx, {
    phase: 'phase9', step: 'confidence-overall', reasoning: true, ...reviewInputs(ctx, pack, extra),
    task: 'Rate overall confidence in this pack. When it is Low, say what holds it down.',
    schema: S.confidenceOverallSchema({ confidence: ctx.builder.CONFIDENCE_LEVELS }),
  });
  pack.confidence = { overall: overall.overall };
  for (const [field, task] of CONFIDENCE_FIELDS) {
    pack.confidence[field] = await writeConfidenceField(ctx, pack, field, task, extra);
  }
  pack.limitations ??= {};
  if (overall.overall === 'Low') {
    pack.limitations['Confidence Assessment'] = overall.lowConfidenceReason
      || 'Overall confidence is Low.';
  }
  return { confidence: overall.overall };
}

/**
 * The senior review questions and the tester notes, written last, with the checklist's
 * issues and the confidence assessment in view. An answer with a field that repeats another
 * or cites a card or rule the workbook lacks is asked for once more with what was wrong.
 */
export async function phase9SeniorReview(ctx, pack) {
  const input = reviewInputs(ctx, pack, [['Checklist issues', issueText(ctx)],
    ['Confidence assessment', JSON.stringify(pack.confidence)]]);
  let refusal = '';
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const answer = await ask(ctx, {
      phase: 'phase9', step: 'senior', reasoning: true, ...input,
      task: `Answer the senior review questions for this pack and write the tester notes. Each`
        + ` field says something of its own and names only cards and rules in the workbook.${refusal}`,
      schema: S.seniorReviewSchema,
    });
    const earlier = reviewProse({ confidence: pack.confidence });
    const fields = [...Object.entries(answer.seniorReview).map(([f, t]) => [`Senior Tester Review ${f}`, t]),
      ...Object.entries(answer.testerNotes).map(([f, t]) => [`Tester Notes ${f}`, t])];
    const problems = [];
    for (const [name, text] of fields) {
      const problem = fieldProblem(pack, Array.isArray(text) ? text.join(' ') : text, earlier);
      if (problem) problems.push(`${name}: ${problem}`);
      else earlier.push({ name, text: String(Array.isArray(text) ? text.join(' ') : text).trim() });
    }
    if (!problems.length) {
      pack.seniorReview = answer.seniorReview;
      pack.testerNotes = answer.testerNotes;
      if (ctx.reuse.length) {
        pack.testerNotes.execution = [...list(pack.testerNotes.execution), ...ctx.reuse];
      }
      return {};
    }
    refusal = ` Your last answer was refused: ${problems.join('; ')}.`;
  }
  throw new GateError('phase9', 'review-field-unsupported');
}

/**
 * Revalidation over the rebuilt workbook, in parts when it is long. A pack that
 * does not pass carries `revalidation` with what remains, which the builder
 * shows on its validation sheet as FAIL.
 */
export async function revalidate(ctx, pack) {
  const refs = [...ctx.ref.core, ctx.ref.docs.revalidation];
  const fixes = [['Fixes the review attempted (judge the workbook, not the attempt)',
    list(ctx.appliedFixes).join('\n')]];
  const views = reviewViews(ctx, pack, refs, fixes);
  let passed = true;
  const remaining = [];
  for (const view of views) {
    const answer = await ask(ctx, {
      phase: 'phase9', step: 'revalidation', reasoning: true, refs,
      task: 'Revalidate the pack after the review\'s fixes: does it now pass, and what remains?'
        + (views.length > 1 ? ` The workbook comes in ${views.length} parts; judge what this part`
          + ' shows, and a rule\'s coverage from the cards the rules index lists for it.' : ''),
      inputs: [['Change description', ctx.description], ...fixes, ...view],
      schema: S.revalidationSchema,
    });
    passed &&= answer.passed;
    remaining.push(...answer.remaining);
  }
  ctx.private('phase9-revalidation.json', { passed, remaining });
  if (passed) delete pack.revalidation;
  else pack.revalidation = { passed: false,
    remaining: remaining.length ? remaining : ['Revalidation did not pass.'] };
  return { passed, remaining: remaining.length };
}

// ---------------------------------------------------------------------------
// Phase 10, Repository Improvement Notes

export async function phase10(ctx, pack) {
  const answer = await ask(ctx, {
    phase: 'phase10', step: 'notes', reasoning: false, refs: ctx.ref.core,
    task: 'Record what the reference material, the pipeline, or the repository\'s sources'
      + ' lacked during this run: each gap, its impact, a recommendation, and the component.',
    inputs: [['Run facts', [
      `Inputs missing at intake: ${list(pack.intake?.missing).join('; ') || 'none'}`,
      `Rules derived from document text: ${ctx.derived}`,
      `Builder repair calls: ${ctx.repairs}`,
      `Objectives dropped for want of a card: ${ctx.droppedObjectives}`,
      `Rules with no card: ${list(pack.coverage).filter((r) => r.status === 'Missing').length}`,
      `Review issues found: ${ctx.reviewIssues}`,
      `Revalidation: ${pack.revalidation ? `failed, ${pack.revalidation.remaining.length} item(s) remain` : 'passed'}`,
    ].join('\n')]],
    schema: S.improvementSchema,
  });
  pack.improvementNotes = answer.improvementNotes;
  return { notes: answer.improvementNotes.length };
}
