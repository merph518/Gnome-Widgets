// The build, phase by phase, as fixed local-model calls. Each phase writes its
// fields of the pack, its gate runs in code, and a failed gate throws a
// GateError whose code is the only thing the status log records about why.

import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { estimateTokens, ModelError } from './model.mjs';
import { fill, globFiles } from './config.mjs';
import * as S from './schemas.mjs';

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
  const promptTokens = await ctx.model.countTokens(`${system}\n${user}`);
  if (promptTokens + maxTokens + 512 > ctx.config.model.context) {
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
const room = (ctx, reasoning, refs) => ctx.config.model.context
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

/**
 * One document's rules from the rule export. A failure the config's `noRules`
 * pattern matches is the export saying the document has no rules yet, so they
 * are derived from its text; any other failure stops intake, since a pack built
 * from derived rules alone would hide the outage.
 */
function exportedRules(ctx, file, number) {
  const { inputs } = ctx.config;
  if (!inputs.ruleExport) return [];
  const failure = {};
  const raw = runCommand(ctx, inputs.ruleExport, { doc: relative(ctx, file) }, { failure });
  if (raw === null) {
    if (inputs.noRules && new RegExp(inputs.noRules).test(failure.stderr)) return [];
    throw new GateError('intake', 'rule-export-failed', { document: number });
  }
  return exportsOf(JSON.parse(raw)).flatMap((doc) => list(doc.rules))
    .filter((rule) => rule.status === undefined || rule.status === 'active');
}

const exportsOf = (json) => (Array.isArray(json?.exports) ? json.exports : json ? [json] : []);
const stripId = (rule) => String(rule.name ?? '').replace(`${rule.rule_id} - `, '');
const relative = (ctx, file) => path.relative(ctx.config.root, file);
const firstHeading = (text) => (String(text).match(/^#+\s+(.+)$/m)?.[1] ?? '').slice(0, 120);

// ---------------------------------------------------------------------------
// Intake

export async function intake(ctx) {
  const { job, config, pack, ref } = ctx;
  const ids = config.idFields;
  const codeMissing = [];
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
    pack[ids.description] = ctx.description;
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
      + ' List the inputs received and the inputs missing, what the missing ones leave out,'
      + ' and the assumptions needed to proceed.',
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
    missing: union('missing'), assumptionsToProceed: union('assumptionsToProceed'),
    missingImpact: answers.map((a) => a.missingImpact).filter((t) => !blank(t)).join('\n') };
  if (choices.length) ctx.documentPaths = answer.documents.map((doc) => config.at(doc));

  if (!job.suite) {
    ctx.documents = [];
    for (const file of ctx.documentPaths ?? []) {
      if (!fs.existsSync(file)) {
        codeMissing.push('document-file');
        continue;
      }
      const rules = exportedRules(ctx, file, ctx.documents.length + 1);
      ctx.documents.push({
        key: path.basename(file).replace(/\.[^.]+$/, ''),
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

  const missing = [...list(answer.missing)];
  pack.intake = {
    received: list(answer.received),
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
    pack.limitations['Job Intake'] = answer.missingImpact || 'Some inputs were missing at intake.';
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
  const full = rules((rule) => `- ${rule.rule_id ?? rule.id}: ${rule.name ?? ''} | ${rule.rule_summary
    ?? rule.summary ?? ''}`);
  if (estimateTokens(full) <= budget) return full;
  const named = rules((rule) => `- ${rule.rule_id ?? rule.id}: ${rule.name ?? ''}`);
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
      + ' today is the defect under test, not a conflict.'
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

export async function phase2(ctx) {
  const { pack, ref } = ctx;
  const risks = ctx.riskLevels;
  const rules = [];
  let derived = 0;
  for (const doc of ctx.documents.filter((d) => d.inclusion === 'Included')) {
    if (doc.rules.length) {
      for (const rule of doc.rules) {
        rules.push({
          id: rule.rule_id, name: stripId(rule), module: doc.module, sourceDocument: doc.name,
          sourcePage: String(rule.source_page ?? '') || 'N/A', summary: rule.rule_summary,
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
        + ' not touch is Not Impacted. Record each ambiguity as an assumption.',
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

  const unrated = pack.rules.filter((rule) => !rule.risk);
  const groups = batches(unrated, ruleLine, room(ctx, false, refs) - fixed, 60);
  for (const [i, group] of groups.entries()) {
    const rated = await ask(ctx, {
      phase: 'phase4', step: `risk-${i + 1}`, reasoning: false, refs,
      task: 'Give each rule its risk level from the impact analysis.',
      inputs: [['Change description', ctx.description], ['Rules', asLines(group.map(ruleLine))]],
      schema: S.riskSchema(group.map((rule) => rule.id), ctx.riskLevels),
    });
    const byId = new Map(rated.rules.map((row) => [row.id, row.risk]));
    for (const rule of group) {
      if (!byId.has(rule.id)) throw new GateError('phase4', 'unrated-rule');
      rule.risk = byId.get(rule.id);
    }
  }
  return { impacted: impacted.length, rated: unrated.length };
}

// ---------------------------------------------------------------------------
// Phase 5, Testing Objective Selection

export async function phase5(ctx) {
  const { pack, ref, job } = ctx;
  const objectives = ctx.builder.OBJECTIVES;
  const refs = [...ref.core, ...ref.chapters('5')];
  const answer = await ask(ctx, {
    phase: 'phase5', step: 'objectives', reasoning: true, refs,
    task: `Decide every one of the ${objectives.length} testing objectives: applicable or not,`
      + ' with a reason each.'
      + (job.suite ? ` This is a suite pack with no change under test, so ${ctx.coreObjective}`
        + ' is not applicable.' : ''),
    inputs: [['Change description', ctx.description],
      ['Executive summary', JSON.stringify(pack.executiveSummary)],
      ['Rules by impact', Object.entries(pack.rules.reduce((acc, rule) => ({
        ...acc, [rule.impact]: (acc[rule.impact] ?? 0) + 1 }), {}))
        .map(([impact, n]) => `- ${impact}: ${n}`).join('\n')]],
    schema: S.objectivesSchema(objectives),
  });
  const decided = new Map(answer.objectives.map((row) => [row.objective, row]));
  if (objectives.some((objective) => !decided.has(objective))) {
    throw new GateError('phase5', 'objective-undecided');
  }
  pack.objectives = objectives.map((objective) => decided.get(objective));
  if (job.suite) {
    const core = decided.get(ctx.coreObjective);
    core.applicable = false;
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

async function designBatch(ctx, doc, group, objectives, index, extra = '') {
  const refs = [...ctx.ref.core, ...ctx.ref.chapters('6')];
  const ids = group.map((rule) => rule.id);
  const lines = asLines(group.map((rule) => `${ruleLine(rule)} | ${rule.impact} | risk ${rule.risk}`));
  const budget = room(ctx, false, refs) - estimateTokens(lines + ctx.description) - 3000;
  // A document too long to send whole goes as its digest; the call's own size
  // check refuses anything that still does not fit.
  const docText = estimateTokens(doc.text) <= budget ? doc.text : await digestDocument(ctx, doc);
  const existing = ctx.existingTests ?? '';
  return ask(ctx, {
    phase: 'phase6', step: `cards-d${doc.number}-${index}`, reasoning: false, refs,
    task: 'Design reusable test cards for these rules: one card per business decision. Focus'
      + ' items and steps are actions; expected results are observable business behavior.'
      + ' Name on each card and each step only the rules it checks. Mark cards that come'
      + ' from quality thinking rather than a stated rule as Quality. A rule no card can'
      + ' cover goes in uncovered with its gap. A card an existing test already covers is'
      + ` named in reuse instead of written again.${extra}`,
    inputs: [['Change description', ctx.description], ['Document', doc.name],
      ['Rules', lines], ['Document text', docText], ['Existing tests', existing]],
    schema: S.cardsSchema({ ids, objectives, derivations: ctx.builder.DERIVATIONS,
      uncoveredStatuses: ['Partially Covered', 'Missing', 'Not Applicable'] }),
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

export async function phase6(ctx) {
  const { pack, job } = ctx;
  const objectives = cardObjectives(ctx);
  if (!objectives.length) throw new GateError('phase6', 'no-applicable-objective');
  const perCall = ctx.config.cardRulesPerCall ?? 4;
  ctx.designed = {};
  let cards = 0;
  let retried = 0;
  for (const doc of ctx.documents.filter((d) => d.inclusion === 'Included')) {
    const rules = pack.rules.filter((rule) => rule.sourceDocument === doc.name
      && rule.module === doc.module && rule.impact !== 'Not Impacted');
    const designed = { cards: [], uncovered: [], reuse: [], assumptions: [] };
    for (const [i, group] of batches(rules, ruleLine, 20000, perCall).entries()) {
      let answer = await designBatch(ctx, doc, group, objectives, i + 1);
      const allowed = new Set(group.map((rule) => rule.id));
      const reached = () => new Set([...answer.cards.flatMap((c) => c.rules),
        ...answer.uncovered.map((row) => row.ruleId)]);
      const left = group.filter((rule) => !reached().has(rule.id));
      if (left.length) {
        // One more try, told which rules it left with neither a card nor a gap.
        retried += 1;
        const again = await designBatch(ctx, doc, left, objectives, `${i + 1}b`,
          ' Every rule listed needs a card or an uncovered entry.');
        answer = { cards: [...answer.cards, ...again.cards],
          uncovered: [...answer.uncovered, ...again.uncovered],
          reuse: [...answer.reuse, ...again.reuse],
          assumptions: [...answer.assumptions, ...again.assumptions] };
      }
      designed.cards.push(...answer.cards.map((card) => tidyCard(card, allowed))
        .filter((card) => card.rules.length));
      // A rule a card covers needs no uncovered row.
      const covered = new Set(designed.cards.flatMap((card) => card.rules));
      designed.uncovered.push(...answer.uncovered.filter((row) => !covered.has(row.ruleId)));
      designed.reuse.push(...answer.reuse);
      designed.assumptions.push(...answer.assumptions);
    }
    // Rules that ended with neither a card nor a gap get one saying so.
    const reachedAll = new Set([...designed.cards.flatMap((c) => c.rules),
      ...designed.uncovered.map((row) => row.ruleId)]);
    for (const rule of rules.filter((r) => !reachedAll.has(r.id))) {
      designed.uncovered.push({ ruleId: rule.id, status: 'Missing',
        gap: 'The local design pass wrote no card for this rule.',
        recommendation: 'Design a card for this rule by hand.' });
    }
    cards += designed.cards.length;
    ctx.designed[doc.key] = designed;
  }

  if (!job.suite) {
    // An applicable objective no card names gets one targeted pass.
    for (const objective of objectives) {
      const used = Object.values(ctx.designed).some((d) => d.cards
        .some((card) => card.objectives.includes(objective)));
      if (used) continue;
      const doc = ctx.documents.find((d) => d.inclusion === 'Included'
        && pack.rules.some((r) => r.sourceDocument === d.name && r.impact !== 'Not Impacted'));
      if (!doc) break;
      const group = pack.rules.filter((rule) => rule.sourceDocument === doc.name
        && rule.impact !== 'Not Impacted').slice(0, perCall);
      const answer = await designBatch(ctx, doc, group, [objective], `obj-${objectives.indexOf(objective) + 1}`,
        ` Write at least one card that serves the objective ${objective}.`);
      const allowed = new Set(group.map((rule) => rule.id));
      const extra = answer.cards.map((card) => tidyCard(card, allowed)).filter((c) => c.rules.length);
      ctx.designed[doc.key].cards.push(...extra);
      cards += extra.length;
      if (!extra.length) {
        // No card could serve it, so the decision cannot stand as Applicable.
        const row = pack.objectives.find((r) => r.objective === objective);
        row.applicable = false;
        row.reason = `${row.reason} No test card could be designed for it in this run.`;
        ctx.droppedObjectives += 1;
      }
    }
  }
  return { cards, retried };
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
  const merged = ctx.suiteMerge.mergeSuitePack({ exportJson: ctx.exportJson,
    designed: ctx.designed, narrative });
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
 * Settles what code can settle before the builder looks: coverage rows that
 * disagree with the cards, a blank assumptions sheet, Direct Change rules no
 * card covers.
 */
export function reconcile(ctx, pack) {
  const covered = new Map();
  for (const card of list(pack.testCards)) {
    for (const id of list(card.rules)) {
      const entry = covered.get(id) ?? { requirement: false };
      if (card.derivation !== 'Quality') entry.requirement = true;
      covered.set(id, entry);
    }
  }
  const ruleIds = new Set(list(pack.rules).map((rule) => rule.id));
  const seen = new Set();
  const claims = ['Covered', 'Partially Covered', 'Weakly Covered'];
  pack.coverage = list(pack.coverage).filter((row) => {
    if (!ruleIds.has(row.ruleId) || seen.has(row.ruleId)) return false;
    const cards = covered.get(row.ruleId);
    if (cards && !claims.includes(row.status)) return false;
    if (!cards && claims.includes(row.status)) return false;
    if (row.status === 'Covered' && cards && !cards.requirement) row.status = 'Weakly Covered';
    seen.add(row.ruleId);
    return true;
  }).map((row) => ({ ...row,
    strength: blank(row.strength) ? (row.status === 'Partially Covered' ? 'Partial' : 'Weak') : row.strength,
    gap: blank(row.gap) && row.status !== 'Covered' ? 'Not stated by the review.' : row.gap,
    recommendation: blank(row.recommendation) && row.status !== 'Covered'
      ? 'Review this rule\'s coverage by hand.' : row.recommendation }));
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
    const built = { ...whole, failed: whole.failed.filter(([sheet]) => !deferred.includes(sheet)) };
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
  for (const fixed of answer.cards) {
    const card = pack.testCards.find((c) => c.id === fixed.id);
    if (!card) continue;
    const tidy = tidyCard(fixed, new Set(ruleIds.filter((id) => pack.rules
      .find((rule) => rule.id === id)?.module === card.module)));
    if (tidy.rules.length) Object.assign(card, { ...tidy, id: card.id, module: card.module,
      sourceDocument: card.sourceDocument });
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

/**
 * The references and pack view every review call reads, with the description
 * and any earlier review answers, compacted to fit or refused as too big.
 */
function reviewInputs(ctx, pack, extra = []) {
  const { ref } = ctx;
  const refs = [...ref.core, ref.docs.validation, ...ref.chapters('9')];
  const budget = room(ctx, true, refs) - estimateTokens(ctx.description) - 2000
    - estimateTokens(extra.map(([, text]) => text).join('\n'));
  const size = (view) => estimateTokens(view.map(([, text]) => text).join('\n'));
  let view = packView(ctx, pack, true);
  if (size(view) > budget) view = packView(ctx, pack, false);
  if (size(view) > budget) throw new GateError('phase9', 'pack-too-big-to-review');
  return { refs, inputs: [['Change description', ctx.description], ...view, ...extra] };
}

const issueText = (ctx) => list(ctx.reviewFindings)
  .map((row) => `- ${row.issue} (fix: ${row.fix})`).join('\n');

/**
 * Phase 9 runs as three calls, each a checkpoint of its own, so no one call
 * thinks through the whole review. The first runs the checklist: issues, the
 * coverage rows for rules not plainly Covered, and assumptions.
 */
export async function phase9Checklist(ctx, pack) {
  const answer = await ask(ctx, {
    phase: 'phase9', step: 'checklist', reasoning: true, ...reviewInputs(ctx, pack),
    task: 'Run the Validation checklist against this pack. List each issue and its fix.'
      + ' Give a coverage row for every rule that is not plainly Covered, with its strength,'
      + ' gap and recommendation. Add the assumptions the pack still needs.',
    schema: S.checklistSchema({ statuses: ctx.builder.COVERAGE_STATUSES }),
  });
  ctx.private('phase9-issues.json', answer.issues);
  ctx.reviewFindings = answer.issues;
  pack.assumptions = [...list(pack.assumptions), ...answer.assumptions];
  const ruleIds = new Set(list(pack.rules).map((rule) => rule.id));
  const reviewRows = answer.coverage.filter((row) => ruleIds.has(row.ruleId)
    && row.status !== 'Covered');
  const rows = new Map(list(pack.coverage).map((row) => [row.ruleId, row]));
  for (const row of reviewRows) rows.set(row.ruleId, row);
  pack.coverage = [...rows.values()];
  pack.reviewCoverage = reviewRows;
  return { issues: answer.issues.length, coverageRows: reviewRows.length };
}

/** The senior review questions and the tester notes, with the checklist's issues in view. */
export async function phase9SeniorReview(ctx, pack) {
  const answer = await ask(ctx, {
    phase: 'phase9', step: 'senior', reasoning: true,
    ...reviewInputs(ctx, pack, [['Checklist issues', issueText(ctx)]]),
    task: 'Answer the senior review questions for this pack and write the tester notes.',
    schema: S.seniorReviewSchema,
  });
  pack.seniorReview = answer.seniorReview;
  pack.testerNotes = answer.testerNotes;
  if (ctx.reuse.length) {
    pack.testerNotes.execution = [...list(pack.testerNotes.execution), ...ctx.reuse];
  }
  return {};
}

/** The confidence assessment, after the checklist and the senior review. */
export async function phase9Confidence(ctx, pack) {
  const answer = await ask(ctx, {
    phase: 'phase9', step: 'confidence', reasoning: true,
    ...reviewInputs(ctx, pack, [['Checklist issues', issueText(ctx)]]),
    task: 'Assess confidence in this pack. When overall confidence is Low, say what holds it'
      + ' down.',
    schema: S.confidenceSchema({ confidence: ctx.builder.CONFIDENCE_LEVELS }),
  });
  pack.confidence = answer.confidence;
  pack.limitations ??= {};
  if (answer.confidence.overall === 'Low') {
    pack.limitations['Confidence Assessment'] = answer.lowConfidenceReason
      || 'Overall confidence is Low.';
  }
  return { confidence: answer.confidence.overall };
}

export async function revalidate(ctx, pack) {
  const answer = await ask(ctx, {
    phase: 'phase9', step: 'revalidation', reasoning: true,
    refs: [...ctx.ref.core, ctx.ref.docs.revalidation],
    task: 'Revalidate the pack after the review\'s fixes: does it now pass, and what remains?',
    inputs: [['Change description', ctx.description], ...packView(ctx, pack, false)],
    schema: S.revalidationSchema,
  });
  ctx.private('phase9-revalidation.json', answer);
  return { passed: answer.passed, remaining: answer.remaining.length };
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
    ].join('\n')]],
    schema: S.improvementSchema,
  });
  pack.improvementNotes = answer.improvementNotes;
  return { notes: answer.improvementNotes.length };
}
