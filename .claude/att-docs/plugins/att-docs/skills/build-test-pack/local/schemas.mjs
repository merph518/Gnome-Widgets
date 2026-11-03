// The JSON schemas each phase's model call answers against. llama.cpp turns
// them into a grammar, so a reply can only take these shapes. Lists of allowed
// values (rule IDs, document names, objectives) are passed in per call.

const str = { type: 'string' };
const strs = { type: 'array', items: str };
const obj = (properties, required = Object.keys(properties)) => ({
  type: 'object', properties, required, additionalProperties: false,
});
const oneOf = (values) => ({ type: 'string', enum: [...values] });
const listOf = (items, extra = {}) => ({ type: 'array', items, ...extra });

// A list with one row per known key is asked for as an object with one
// property per key: the grammar then requires every key exactly once, where a
// list of the right length can repeat one row and leave another out. `unkey`
// turns the reply back into the list, each row carrying its key in `field`.
const KEYED = new WeakMap();
const keyed = (field, keys, properties) => {
  const schema = obj(Object.fromEntries([...keys].map((key) => [key, obj(properties)])));
  KEYED.set(schema, field);
  return schema;
};

/** The reply with every keyed object turned back into its list of rows. */
export function unkey(schema, value) {
  if (!value || typeof value !== 'object' || !schema?.properties) return value;
  const out = { ...value };
  for (const [name, property] of Object.entries(schema.properties)) {
    const field = KEYED.get(property);
    if (field && out[name] && typeof out[name] === 'object') {
      out[name] = Object.entries(out[name]).map(([key, row]) => ({ [field]: key, ...row }));
    }
  }
  return out;
}

export const assumptionSchema = obj({ assumption: str, why: str, impact: str, clarification: str });

export const intakeSchema = obj({
  received: strs,
  secondaryRequests: strs,
  assumptionsToProceed: strs,
  decisionsRequired: strs,
});

/** The documents one batch of candidates holds that the change touches; a batch may hold none. */
export const documentPickSchema = (batch) => obj({ documents: listOf(oneOf(batch)) });

export const digestSchema = obj({ points: listOf(str, { minItems: 1 }) });

export function understandingSchema({ documents, keys, inclusions, suite }) {
  return obj({
    summary: obj({
      change: str, purpose: str, modules: str, existingBehavior: str, newBehavior: str,
      rulesIdentified: str, inScope: str, outOfScope: str, missingInformation: str,
      confidenceReason: str,
      confidence: oneOf(['High', 'Medium', 'Low']),
    }),
    ...(suite ? {} : {
      sourceDocuments: keyed('name', documents,
        { authority: str, informationObtained: str, directImpact: { type: 'boolean' },
          reason: str, inclusion: oneOf(inclusions) }),
    }),
    modules: keyed('document', keys,
      { module: str, abbreviation: { type: 'string', pattern: '^[A-Z0-9]{2,6}$' } }),
    conflicts: strs,
    blockingMissing: strs,
  });
}

/** One batch of rules read against the documents: which bear on the change, and what they show. */
export const phase1RulesSchema = (ids) => obj({
  rules: keyed('id', ids, { bearsOnChange: { type: 'boolean' } }),
  conflicts: strs,
  blockingMissing: strs,
  notes: str,
});

export const derivedRulesSchema = (risks) => obj({
  rules: listOf(obj({ statement: str, sourcePage: str, summary: str, risk: oneOf(risks) })),
});

/** Pairs of rules that require different behavior for the same thing. */
export const ruleConflictSchema = (ids) => obj({
  conflicts: listOf(obj({ rules: listOf(oneOf(ids), { minItems: 2, maxItems: 2 }), conflict: str })),
});

export const scopeSchema = (ids, impacts) => obj({
  rules: keyed('id', ids, { impact: oneOf(impacts), rationale: str }),
  assumptions: listOf(assumptionSchema),
  userReview: strs,
});

/** The areas the impact analysis covers: the pack key and the label the prompts show. */
export const IMPACT_AREAS = [['windows', 'Windows, pages and tabs'],
  ['businessFunctions', 'Business functions'], ['upstream', 'Upstream'],
  ['downstream', 'Downstream'], ['data', 'Data'], ['security', 'Security and roles'],
  ['batch', 'Batch'], ['notices', 'Notices'], ['reports', 'Reports'],
  ['interfaces', 'Interfaces']];

export const impactSchema = obj({
  executiveSummary: obj({
    scope: str, modules: str, sourceDocuments: str, strategy: str, execution: str, risks: str,
  }),
  impacts: obj(Object.fromEntries(IMPACT_AREAS.map(([key]) => [key, listOf(str, { maxItems: 8 })]))),
});

export const riskSchema = (ids, risks) => obj({
  rules: keyed('id', ids, { risk: oneOf(risks) }),
});

export const objectivesSchema = (objectives, { evidence = [] } = {}) => obj({
  objectives: keyed('objective', objectives, { applicable: { type: 'boolean' }, reason: str }),
  // One row per configured evidence rule: whether the change holds it, and the quote that shows it.
  ...(evidence.length ? { evidence: keyed('id', evidence, { holds: { type: 'boolean' }, quote: str }) } : {}),
});

/** The kinds of scenario the source can support. All ten are asked for in every inventory. */
export const REQUIRED_SCENARIO_KINDS = ['control', 'isolation', 'combined', 'persistence',
  'negative', 'role', 'state-change', 'manual-batch', 'navigation', 're-entry'];
// A break scenario tries to break the change; it is asked for when a BREAK IT set is in play.
export const SCENARIO_KINDS = [...REQUIRED_SCENARIO_KINDS, 'break', 'decision'];

// Each scenario is a population, an action and an expected outcome. `kindChecks`
// makes the reply answer for every required kind: what its scenario tests, or
// why the source supports none.
export const scenarioInventorySchema = ({ ids, kinds = SCENARIO_KINDS,
  required = REQUIRED_SCENARIO_KINDS, maxItems }) => obj({
  scenarios: listOf(obj({
    rules: listOf(oneOf(ids), { minItems: 1 }),
    kind: oneOf(kinds),
    population: str,
    action: str,
    outcome: str,
  }), { minItems: 1, ...(maxItems ? { maxItems } : {}) }),
  ...(required.length ? { kindChecks: keyed('kind', required, { note: str }) } : {}),
});

// `scenarios` names the scenario ids a card may cover.
export function cardSchema({ ids, objectives, derivations, scenarios }) {
  const ruleList = listOf(oneOf(ids));
  return obj({
    title: str,
    ...(scenarios ? { scenario: oneOf(scenarios) } : {}),
    mission: str,
    focus: listOf(str, { minItems: 1 }),
    expected: str,
    rules: listOf(oneOf(ids), { minItems: 1 }),
    objectives: listOf(oneOf(objectives), { minItems: 1 }),
    derivation: oneOf(derivations),
    steps: listOf(obj({ description: str, expected: str, rules: ruleList }), { minItems: 1 }),
  });
}

// The two answers to whether a card's Expected Result follows from its rules.
export const VERDICTS = ['follows', 'does not follow'];

// One row per card in the call; the reason comes first, so the verdict follows from it.
export const verificationSchema = (refs) => obj({
  cards: keyed('card', refs, { why: str, verdict: oneOf(VERDICTS) }),
});

// A scenario no card is written for is skipped: an existing test covers it, or no card can.
export const SKIP_REASONS = ['reused', 'gap'];

export const cardsSchema = ({ ids, objectives, derivations, uncoveredStatuses, scenarios }) => obj({
  cards: listOf(cardSchema({ ids, objectives, derivations, scenarios })),
  uncovered: listOf(obj({
    ruleId: oneOf(ids), status: oneOf(uncoveredStatuses), gap: str, recommendation: str,
  })),
  ...(scenarios ? { skipped: listOf(obj({
    scenario: oneOf(scenarios), how: oneOf(SKIP_REASONS), reason: str })) } : {}),
  reuse: strs,
  assumptions: listOf(assumptionSchema),
});

/** The existing cards that serve an objective, by reference. */
export const objectiveCardsSchema = (refs) => obj({ cards: listOf(oneOf(refs)) });

export const setScopesSchema = (objectives) => obj({
  sets: keyed('objective', objectives, { scope: str }),
});

// The sections of the Validation checklist; each issue the checklist raises names one.
export const VALIDATION_SECTIONS = ['Requirements Matrix Integrity', 'Rule Integrity',
  'Test Card Structure', 'Coverage Completeness', 'Traceability', 'Consistency'];

export const checklistSchema = ({ statuses }) => obj({
  issues: listOf(obj({ section: oneOf(VALIDATION_SECTIONS), issue: str, fix: str })),
  coverage: listOf(obj({
    ruleId: str, status: oneOf(statuses), strength: str, gap: str, recommendation: str,
  })),
  assumptions: listOf(assumptionSchema),
});

export const seniorReviewSchema = obj({
  seniorReview: obj({
    missed: str, businessBehavior: str, upstreamDownstream: str, obviousFirst: str,
    qualityDerived: str,
  }),
  testerNotes: obj({
    testData: str, execution: str, regressionTargets: str, breakIt: str, screenshots: str,
    sqlValidation: str, knownRisks: str, cautions: str,
  }),
});

/** The overall confidence level, with the reason for every level and the criteria it meets. */
export const confidenceOverallSchema = ({ confidence }) => obj({
  overall: oneOf(confidence), reason: str, criteria: strs,
});

/** The least a confidence field says: shorter than this is a label, not a sentence. */
export const CONFIDENCE_FIELD_MIN_CHARS = 60;

/** One prose field of the Confidence Assessment, written on its own. */
export const confidenceFieldSchema = (field) => obj({
  [field]: { type: 'string', minLength: CONFIDENCE_FIELD_MIN_CHARS },
});

// The assessment steps of the confidence procedure, in the order they are walked.
export const CONFIDENCE_STEPS = ['rules', 'decisions', 'coverage', 'regression', 'qualityDerived',
  'breakIt', 'professionalReview', 'residualRisk'];
export const CONFIDENCE_VERDICTS = ['strong', 'partial', 'weak'];

/** One verdict and its evidence for each assessment step. */
export const confidenceStepsSchema = obj({
  steps: keyed('step', CONFIDENCE_STEPS, { verdict: oneOf(CONFIDENCE_VERDICTS), evidence: str }),
});

// The seven checks of the Revalidation procedure; revalidation gives one verdict for each.
export const REVALIDATION_CHECKS = ['All issues resolved', 'No regressions introduced',
  'Requirement ID references preserved', 'Requirements Matrix integrity preserved',
  'Traceability complete',
  'No uncovered Requirement IDs remain unless explicitly documented',
  'Test pack is ready for ALM execution'];
// The verdict for a check the part of the workbook in view does not show.
export const NOT_SHOWN = 'not shown in this part';

export const revalidationSchema = ({ verdicts = ['pass', 'fail'] } = {}) => obj({
  checks: keyed('check', REVALIDATION_CHECKS, { why: str, verdict: oneOf(verdicts), fix: str }),
});

export const repairSchema = ({ cardIds, ids, objectives, derivations, statuses, sheets,
  assumptions }) => obj({
  cards: listOf({
    ...cardSchema({ ids, objectives, derivations }),
    properties: { id: oneOf(cardIds.length ? cardIds : ['none']),
      ...cardSchema({ ids, objectives, derivations }).properties },
    required: ['id', ...cardSchema({ ids, objectives, derivations }).required],
  }, { minItems: cardIds.length, maxItems: cardIds.length }),
  coverage: listOf(obj({
    ruleId: oneOf(ids), status: oneOf(statuses), strength: str, gap: str, recommendation: str,
  })),
  limitations: listOf(obj({ sheet: oneOf(sheets), text: str })),
  ...(assumptions ? { assumptions: listOf(assumptionSchema) } : {}),
});

export const improvementSchema = obj({
  improvementNotes: listOf(obj({ gap: str, impact: str, recommendation: str, component: str })),
});
