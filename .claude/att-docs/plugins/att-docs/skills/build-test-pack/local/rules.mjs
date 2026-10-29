// Checks a document's rule export before any card is designed. `shapeProblems`
// separates what makes an export unusable (its structure) from what only
// deserves a look (values the master holds that the current procedure would not
// write, such as an older category). `rulesStale` says whether the rules
// predate the document. The caller decides what stops a job.

// A source_page value: one page, a range, or several of either.
const PAGE_REF = /^\d+(?:-\d+)?(?:, \d+(?:-\d+)?)*$/;
// The provenance lines a converted document states its revision date and page
// count on: "- Revised: 2025-10-06, from the revision history table", or
// "not stated"; "- Pages: 42".
const REVISED_LINE = /^- Revised: (\d{4}-\d{2}-\d{2})\b/m;
const PAGES_LINE = /^- Pages: (\d+)\b/m;
const DAY = /^\d{4}-\d{2}-\d{2}$/;

const isText = (value) => typeof value === 'string';
const normal = (text) => String(text).replace(/\s+/g, ' ').trim().toLowerCase();
const escaped = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** The ISO day the provenance block gives as the document's revision date, or null. */
export function revisedDate(markdown) {
  return REVISED_LINE.exec(markdown)?.[1] ?? null;
}

/**
 * What is wrong with an export of one document, as { errors, warnings } lines
 * for detail.log. Errors are structural: the top level, `doc`, the prefix, the
 * rule IDs and their uniqueness, the statuses, and an empty rules list. The
 * master also holds rows with older categories, requirement types that name a
 * category, blank columns and pages the document cannot place, so those are
 * warnings. A folder export is `{ exports: [...] }`, and each of its entries is
 * checked the same way.
 */
export function shapeProblems(json, docPath, markdown, shape) {
  const entries = Array.isArray(json?.exports) ? json.exports : [json];
  if (!entries.length) return { errors: ['the export holds no document'], warnings: [] };
  const context = {
    docPath, shape,
    pages: Number(PAGES_LINE.exec(markdown)?.[1] ?? 0),
    headings: new Set([...markdown.matchAll(/^#+\s+(.+)$/gm)].map((m) => normal(m[1]))),
  };
  const found = { errors: [], warnings: [] };
  for (const entry of entries) entryProblems(entry, context, found);
  return found;
}

function entryProblems(entry, { docPath, shape, pages, headings }, { errors, warnings }) {
  if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
    errors.push('the export is not an object');
    return;
  }
  if (entry.doc !== docPath) errors.push(`doc "${entry.doc}" is not the requested path`);
  const prefixOk = isText(entry.prefix) && new RegExp(shape.prefixPattern).test(entry.prefix);
  if (!prefixOk) errors.push(`prefix "${entry.prefix}" does not match ${shape.prefixPattern}`);
  if (!Array.isArray(entry.rules) || !entry.rules.length) {
    errors.push('rules is missing or empty');
    return;
  }
  const idPattern = prefixOk
    ? new RegExp(`^${escaped(entry.prefix)}-${shape.ruleIdPattern}$`) : null;
  const seen = new Set();
  entry.rules.forEach((rule, i) => {
    const where = `rule ${i + 1} (${rule?.rule_id ?? 'no rule_id'})`;
    const fail = (text) => errors.push(`${where}: ${text}`);
    const warn = (text) => warnings.push(`${where}: ${text}`);
    if (idPattern && !idPattern.test(rule?.rule_id ?? '')) fail('rule_id does not read as <prefix>-NNN');
    if (seen.has(rule?.rule_id)) fail('rule_id appears twice');
    seen.add(rule?.rule_id);
    if (!shape.statuses.includes(rule?.status)) {
      fail(`status "${rule?.status}" is not one of ${shape.statuses.join(', ')}`);
    }
    for (const column of shape.matrixColumns) {
      if (!isText(rule?.[column]) || !rule[column].trim()) warn(`${column} is missing or blank`);
    }
    if (isText(rule?.requirement_type) && rule.requirement_type !== shape.requirementType) {
      warn(`requirement_type "${rule.requirement_type}" is not "${shape.requirementType}"`);
    }
    if (isText(rule?.rule_category) && !shape.categories.includes(rule.rule_category)) {
      warn(`rule_category "${rule.rule_category}" is not a current category`);
    }
    if (isText(rule?.risk_level) && !shape.riskLevels.includes(rule.risk_level)) {
      warn(`risk_level "${rule.risk_level}" is not one of ${shape.riskLevels.join(', ')}`);
    }
    if (isText(rule?.name) && !rule.name.startsWith(`${rule.rule_id} - `)) {
      warn(`name does not start with "${rule.rule_id} - "`);
    }
    if (isText(rule?.source_page) && rule.source_page.trim()) {
      const problem = pageProblem(rule.source_page.trim(), pages, headings);
      if (problem) warn(problem);
    }
  });
}

/**
 * Why a source_page is unlikely to be a place in the document, or null. A page
 * reference is checked against the page count when the document states one,
 * 1 through N, since a page whose anchor the conversion could not place still
 * exists. Anything else has to be a heading.
 */
function pageProblem(value, pages, headings) {
  if (PAGE_REF.test(value)) {
    const numbers = value.split(/[-,] ?/).map(Number);
    return pages && numbers.some((n) => n < 1 || n > pages)
      ? `source_page "${value}" is outside the document's ${pages} pages` : null;
  }
  return headings.has(normal(value)) ? null : `source_page "${value}" is not a heading in the document`;
}

/**
 * Whether the document was revised after its rules were last confirmed. The
 * confirmation is the export's document-level `reviewed` (or `last_reviewed`)
 * day when it carries one, else the newest `created` day on its rules. A
 * document that states no revision date, or an export with neither day, gives
 * no answer, and the check passes.
 */
export function rulesStale(markdown, entries) {
  const revised = revisedDate(markdown);
  const reviewed = entries.map((entry) => entry.reviewed ?? entry.last_reviewed)
    .filter((day) => DAY.test(day)).sort().at(-1);
  const created = entries.flatMap((entry) => entry.rules ?? []).map((rule) => rule.created)
    .filter((day) => DAY.test(day)).sort().at(-1);
  const confirmed = reviewed ?? created;
  return Boolean(revised && confirmed && revised > confirmed);
}
