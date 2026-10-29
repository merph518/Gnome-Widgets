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

export const intakeSchema = (candidates) => obj({
  ...(candidates.length ? { documents: listOf(oneOf(candidates), { minItems: 1 }) } : {}),
  received: strs,
  missing: strs,
  missingImpact: str,
  assumptionsToProceed: strs,
});

export const digestSchema = obj({ points: listOf(str, { minItems: 1 }) });

export function understandingSchema({ documents, keys, inclusions, suite }) {
  return obj({
    summary: obj({
      change: str, purpose: str, modules: str, existingBehavior: str, newBehavior: str,
      rulesIdentified: str, inScope: str, outOfScope: str, missingInformation: str,
      confidence: oneOf(['High', 'Medium', 'Low']),
    }),
    ...(suite ? {} : {
      sourceDocuments: keyed('name', documents,
        { inclusion: oneOf(inclusions), authority: str, reason: str }),
    }),
    modules: keyed('document', keys,
      { module: str, abbreviation: { type: 'string', pattern: '^[A-Z0-9]{2,6}$' } }),
    conflicts: strs,
  });
}

export const derivedRulesSchema = (risks) => obj({
  rules: listOf(obj({ statement: str, sourcePage: str, summary: str, risk: oneOf(risks) })),
});

export const scopeSchema = (ids, impacts) => obj({
  rules: keyed('id', ids, { impact: oneOf(impacts), rationale: str }),
  assumptions: listOf(assumptionSchema),
});

export const impactSchema = obj({
  executiveSummary: obj({
    scope: str, modules: str, sourceDocuments: str, strategy: str, execution: str, risks: str,
  }),
});

export const riskSchema = (ids, risks) => obj({
  rules: keyed('id', ids, { risk: oneOf(risks) }),
});

export const objectivesSchema = (objectives) => obj({
  objectives: keyed('objective', objectives, { applicable: { type: 'boolean' }, reason: str }),
});

export function cardSchema({ ids, objectives, derivations }) {
  const ruleList = listOf(oneOf(ids));
  return obj({
    title: str,
    mission: str,
    focus: listOf(str, { minItems: 1 }),
    expected: str,
    rules: listOf(oneOf(ids), { minItems: 1 }),
    objectives: listOf(oneOf(objectives), { minItems: 1 }),
    derivation: oneOf(derivations),
    steps: listOf(obj({ description: str, expected: str, rules: ruleList }), { minItems: 1 }),
  });
}

export const cardsSchema = ({ ids, objectives, derivations, uncoveredStatuses }) => obj({
  cards: listOf(cardSchema({ ids, objectives, derivations })),
  uncovered: listOf(obj({
    ruleId: oneOf(ids), status: oneOf(uncoveredStatuses), gap: str, recommendation: str,
  })),
  reuse: strs,
  assumptions: listOf(assumptionSchema),
});

export const setScopesSchema = (objectives) => obj({
  sets: keyed('objective', objectives, { scope: str }),
});

export const checklistSchema = ({ statuses }) => obj({
  issues: listOf(obj({ issue: str, fix: str })),
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

export const confidenceSchema = ({ confidence }) => obj({
  confidence: obj({
    overall: oneOf(confidence), coverage: str, remainingRisks: str, assumptions: str,
    regressionScope: str, breakItScope: str, manualReview: str,
  }),
  lowConfidenceReason: str,
});

export const revalidationSchema = obj({ passed: { type: 'boolean' }, remaining: strs });

export const repairSchema = ({ cardIds, ids, objectives, derivations, statuses, sheets }) => obj({
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
});

export const improvementSchema = obj({
  improvementNotes: listOf(obj({ gap: str, impact: str, recommendation: str, component: str })),
});
