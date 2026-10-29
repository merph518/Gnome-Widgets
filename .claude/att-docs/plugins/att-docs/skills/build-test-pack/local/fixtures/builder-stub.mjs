// A small stand-in for a repository's pack builder, with the same exports the
// pipeline reads and the same command-line shape:
//
//   node builder-stub.mjs <pack.json> --out <dir>
//
// It checks enough to exercise the pipeline's gates and repairs: card IDs and
// rules, objectives against sets, coverage against cards, and blank review
// sheets. A card titled REJECT fails, so a test can drive a repair.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const SHEET_ORDER = ['Dashboard', 'Job Intake', 'Executive Summary', 'Impact Analysis',
  'Objective Matrix', 'Test Cards Markdown', 'Test Lab Markdown', 'Coverage Matrix', 'Assumptions',
  'Senior Tester Review', 'Tester Notes', 'Confidence Assessment', 'Workbook Validation'];
export const OBJECTIVES = ['Core Change Validation', 'Workflow Validation', 'Negative / Exclusion',
  'Regression Testing', 'Full Coverage Required Run', 'BREAK IT'];
export const IMPACT_CLASSES = ['Direct Change', 'Indirect Impact', 'Regression', 'Not Impacted'];
export const COVERAGE_STATUSES = ['Covered', 'Partially Covered', 'Weakly Covered', 'Missing',
  'Not Applicable'];
export const CONFIDENCE_LEVELS = ['High', 'Medium', 'Low'];
export const DERIVATIONS = ['Requirement', 'Quality'];
export const INCLUSIONS = ['Included', 'Supporting Context Only', 'Excluded'];

const list = (v) => (Array.isArray(v) ? v : v == null || v === '' ? [] : [v]);
const blank = (v) => list(v).every((x) => String(x ?? '').trim() === '');

export function ruleCoverage(pack) {
  return list(pack.rules).map((rule) => {
    const cards = list(pack.testCards).filter((c) => list(c.rules).includes(rule.id));
    const row = list(pack.coverage).find((r) => r.ruleId === rule.id);
    return { rule, cards: cards.map((c) => c.id),
      status: row?.status ?? (cards.length ? 'Covered' : rule.impact === 'Not Impacted'
        ? 'Not Applicable' : 'Missing') };
  });
}

export function buildPack(pack) {
  const key = pack.suite || pack.issue;
  if (!key || blank(pack.changeDescription) || !list(pack.rules).length
    || !['READY', 'READY WITH ASSUMPTIONS']
    .includes(pack.intake?.readiness)) {
    return { stop: { phase: 'Phase 1', missing: ['inputs'] } };
  }
  const problems = new Map(SHEET_ORDER.map((s) => [s, []]));
  const add = (sheet, text) => problems.get(sheet).push(text);
  const ruleIds = new Set(list(pack.rules).map((r) => r.id));
  const ids = new Set();
  const pattern = new RegExp(`^TC-[A-Z0-9]+-${key}-\\d{3}$`);
  for (const card of list(pack.testCards)) {
    if (ids.has(card.id)) add('Test Cards Markdown', `${card.id} repeats`);
    ids.add(card.id);
    if (!pattern.test(card.id)) add('Test Cards Markdown', `${card.id} is off the pattern`);
    if (card.title === 'REJECT') add('Test Cards Markdown', `${card.id} has a rejected title`);
    for (const id of list(card.rules)) if (!ruleIds.has(id)) add('Test Cards Markdown', `${card.id} names ${id}`);
    if (!list(pack.testSets).some((s) => list(s.cards).includes(card.id))) {
      add('Test Lab Markdown', `${card.id} is in no set`);
    }
  }
  for (const objective of OBJECTIVES) {
    const row = list(pack.objectives).find((r) => r.objective === objective);
    const used = list(pack.testSets).some((s) => s.objective === objective);
    if (!row || typeof row.applicable !== 'boolean') add('Objective Matrix', `${objective} undecided`);
    else if (row.applicable !== used) add('Objective Matrix', `${objective} disagrees with the sets`);
  }
  for (const row of ruleCoverage(pack)) {
    if (row.status === 'Covered' && !row.cards.length) add('Coverage Matrix', `${row.rule.id} covered by nothing`);
    if (['Missing', 'Not Applicable'].includes(row.status) && row.cards.length) {
      add('Coverage Matrix', `${row.rule.id} has cards but reads ${row.status}`);
    }
    if (row.rule.impact === 'Direct Change' && !row.cards.length
      && !String(pack.limitations?.['Coverage Matrix'] ?? '').includes(row.rule.id)) {
      add('Coverage Matrix', `${row.rule.id} is a Direct Change no card covers`);
    }
  }
  if (Object.values(pack.seniorReview ?? {}).some(blank) || !pack.seniorReview) {
    add('Senior Tester Review', 'fields are blank');
  }
  if (!pack.testerNotes) add('Tester Notes', 'fields are blank');
  if (!CONFIDENCE_LEVELS.includes(pack.confidence?.overall)) add('Confidence Assessment', 'no overall');
  if (blank(pack.executiveSummary?.confidence)) add('Executive Summary', 'confidence is blank');
  if (!list(pack.assumptions).length && blank(pack.limitations?.Assumptions)) {
    add('Assumptions', 'fields are blank and no limitation says why');
  }
  const validation = SHEET_ORDER.map((sheet) => {
    const found = problems.get(sheet);
    const status = found.length ? 'FAIL' : blank(pack.limitations?.[sheet]) ? 'PASS'
      : 'PASS WITH LIMITATIONS';
    return [sheet, 'Yes', 'Yes', status, found.join('\n')];
  });
  const fileName = pack.suite ? `${pack.suite}_Suite_Pack.xlsx` : `ISSUE${pack.issue}_Pack.xlsx`;
  return { fileName, sheets: [], validation, failed: validation.filter((r) => r[3] === 'FAIL') };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const [packPath, , outDir] = process.argv.slice(2);
  const built = buildPack(JSON.parse(fs.readFileSync(packPath, 'utf8')));
  if (built.stop) {
    console.error('STOP at Phase 1');
    process.exit(1);
  }
  for (const [sheet, , , status] of built.validation) console.log(`${status.padEnd(22)} ${sheet}`);
  if (built.failed.length) process.exit(1);
  fs.writeFileSync(path.join(outDir, built.fileName), 'stub workbook\n');
}
