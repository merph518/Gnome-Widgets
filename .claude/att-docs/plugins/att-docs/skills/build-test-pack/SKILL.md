---
name: build-test-pack
description: Build a test pack workbook for one defect record and its change record by running a phased Build Test Pack procedure, each phase gated before the next, and writing the workbook a workbook standard defines, or one for a suite's whole approved rule set. Use when asked to build, make, or generate a test pack for a defect or a change. Also use to load an approved suite pack into the test management tool's test plan and test lab.
---

# Build Test Pack

Takes a `<issue-term>` number, a `<change-term>` number when the change has
one, and the source documents. `<invocation>` names both; the documents can be
named in the request, attached, or found in the repository.

The procedure and the standard are the reference material's, and they live only
in `<reference-dir>`. This skill is how they run in a repository: which of the
procedure's inputs come from where, what each phase writes into the pack file,
and the builder that turns that file into the workbook.

The consuming repository's extension supplies the values below. Where it names
none, ask the user rather than guessing.

| Placeholder | Meaning |
| --- | --- |
| `<issue-term>` | What the repository calls the defect record a pack is built for |
| `<change-term>` | What it calls the change record that fixes it |
| `<invocation>` | An example request that names an issue and its change |
| `<suite-invocation>` | An example request for a suite pack |
| `<suites>` | The suites a suite pack can be built for |
| `<reference-dir>` | The folder that holds the procedure, the standard, and their companions |
| `<procedure>` | The phased Build Test Pack procedure: the phases, their order, the stop conditions |
| `<phase-count>` | How many numbered phases `<procedure>` has |
| `<workbook-standard>` | The workbook standard: name, sheets, columns, objectives, status values |
| `<sheet-count>` | How many sheets `<workbook-standard>` defines |
| `<objective-count>` | How many testing objectives `<workbook-standard>` defines |
| `<intake-procedure>` | The job intake read before Phase 1 |
| `<job-type>` | The job type code and name intake classifies this request as |
| `<understanding-gate>` | Phase 1's procedure: source authority order, the PASS conditions |
| `<rule-intake-procedure>` | Phase 2's procedure |
| `<scope-procedure>` | Phase 3's procedure |
| `<validation-procedure>` | Phase 9's validation checklist |
| `<revalidation-procedure>` | Phase 9's revalidation |
| `<implementation-guide>` | The traceability and reuse rules every phase keeps |
| `<methodology>` | The testing methodology the phases lean on |
| `<methodology-chapters>` | Which `<methodology>` chapter covers which subject |
| `<glossary>` | The reference material's terms |
| `<manifest>` | The reference archive's own list of SHA-256 fingerprints |
| `<manifest-check>` | The test that checks every reference document against `<manifest>` |
| `<shipped-paths>` | The paths that ship beyond the repository and so may not carry reference text |
| `<component-map>` | Where each repository component `<procedure>` expects loaded is found |
| `<gold-packs>` | Hand-built packs read for shape and depth |
| `<description-source>` | Where the change or defect description comes from |
| `<rule-export>` | The command that exports one document's rules from the master |
| `<folder-export>` | The command that exports a suite folder's rules |
| `<process-docs>` | Where process descriptions live and how one is found |
| `<design-docs>` | Where design and module specifications live |
| `<attached-only>` | Inputs with no copy in the repository, attached by the user |
| `<existing-tests>` | Where existing test plan and test lab assets come from |
| `<existing-automation>` | Where existing automated tests for the same screen live |
| `<test-tool>` | The test management tool that holds the test plan and the test lab |
| `<id-fields>` | The pack fields that name the issue, the change, whether a change applies, and the change description |
| `<pack-file>` | The pack file's name for an issue pack |
| `<suite-pack-file>` | The pack file's name for a suite pack |
| `<case-id>` | The test case ID pattern for an issue pack |
| `<suite-case-id>` | The test case ID pattern for a suite pack |
| `<suite-workbook-name>` | The workbook's name for a suite pack |
| `<rule-code-example>` | How a card file's code is read from a rule's prefix, with an example |
| `<derived-rule-example>` | An example name for a rule the master does not hold |
| `<dashboard-sheet>` | The sheet with the counts and the coverage percentage |
| `<objective-sheet>` | The sheet that relates objectives to cards and sets |
| `<upload-sheet>` | The sheet that is the `<test-tool>` test plan import |
| `<rule-matrix-sheet>` | The sheet that maps every rule to its tests |
| `<coverage-sheet>` | The sheet with each rule's coverage status and gap |
| `<validation-sheet>` | The sheet that carries each sheet's validation status |
| `<cards-sheet>` | The sheet that carries the test card titles |
| `<notes-sheet>` | The sheet that carries tester notes |
| `<confidence-sheet>` | The sheet that carries the confidence assessment |
| `<intake-sheet>` | The sheet that carries job intake |
| `<core-objective>` | The objective that tests the change itself |
| `<break-objective>` | The objective that tries to break the change, run last |
| `<suite-merge>` | The command that merges a suite pack's card files and narrative |
| `<pack-builder>` | The command that builds the workbook from a pack file |
| `<testpack-command>` | The command that loads a suite pack into `<test-tool>`, dry run by default |
| `<committed-pack>` | Where an approved suite pack file is committed |
| `<pack-source>` | Where `<testpack-command>` reads the pack file from |
| `<upload-script>` | The script that does the load |
| `<rule-upload>` | The command that loads a suite's rules and records their `<test-tool>` ids |
| `<plan-folder>` | The test plan folder a suite's tests go under |
| `<lab-folder>` | The test lab folder a suite's sets go under |
| `<tool-roots>` | The root folders of the two trees, which always exist |
| `<shared-folders>` | The folders the first suite creates and the rest reuse |
| `<name-substitutes>` | Characters `<test-tool>` refuses in a test name, and what replaces each |
| `<ask-user>` | How the session asks the user for a missing input |
| `<follow-up>` | How a gap in the repository's own tooling is filed |
| `<docs-root>` | The documents folder, one folder per suite |
| `<writing-gates>` | The checks text under `<docs-root>` passes before it is committed |
| `<send-file>` | How the finished file is sent to a user following from another device |
| `<extract-skill>` | The skill that extracts a document's rules for the first time |
| `<update-skill>` | The skill that updates a document's rules in the master |
| `<scratchpad>` | A scratch directory outside the repository |

| Reference | What it governs |
| --- | --- |
| `<procedure>` | the `<phase-count>` phases, their order, the stop conditions |
| `<workbook-standard>` | the workbook: name, `<sheet-count>` sheets, columns, objectives, status values |
| `<intake-procedure>` | the intake read before Phase 1 |
| `<understanding-gate>` | Phase 1, source authority order, the PASS conditions |
| `<rule-intake-procedure>` | Phase 2 |
| `<scope-procedure>` | Phase 3 |
| `<validation-procedure>`, `<revalidation-procedure>` | Phase 9 |
| `<implementation-guide>` | traceability and reuse rules every phase keeps |
| `<methodology>` | the methodology, chapter by chapter as `<methodology-chapters>` gives it |
| `<glossary>` | the reference material's terms |

Read `<procedure>` and `<workbook-standard>` in full before Phase 1. Read each
procedure as its phase starts, and the `<methodology>` chapter a phase leans on
when the phase starts. A methodology too large to read whole is read by chapter
with a line range.

`<manifest>` is the reference archive's own list of SHA-256 fingerprints, and
`<manifest-check>` checks every reference document against it. A failing check
means the copy in the repository is no longer the one that was verified.

## Where the reference material may go

Nothing from `<reference-dir>` leaves that folder, and nothing under
`<shipped-paths>` may carry its text. The workbook holds the session's own
analysis of this change, never passages copied from the reference documents: no
procedure text, no methodology wording in a card or a note.

## What the procedure's repository components are

`<procedure>` names repository components it expects to have loaded.
`<component-map>` says where each one is in the repository, so none of them is
missing. Read `<gold-packs>` for shape and depth; do not copy their cards into a
new pack.

## Inputs, and where they come from

| `<procedure>` input | Source |
| --- | --- |
| `<issue-term>` number, `<change-term>` number | the request |
| `<change-term>` or `<issue-term>` description | `<description-source>` |
| Business rule matrix | the business rule master, through `<rule-export>`, one call per process description |
| Process description | `<process-docs>` |
| Design or module specification | `<design-docs>` |
| `<attached-only>` | attached by the user; there is no copy in the repository |
| Existing `<test-tool>` test plan and test lab assets | `<existing-tests>` |
| Existing automation | `<existing-automation>` |

### A suite pack

`<suite-invocation>` builds one pack for a suite's whole approved rule set
rather than for an issue. The suites are `<suites>`. There is no issue or
change, so the pack sets `suite` to the suite's code and `suiteInput` to what it
used in their place, and the change description in `<id-fields>` describes the
rule set. The rules come from one folder export, `<folder-export>`, and the
sources are that folder's documents. The builder then names the workbook
`<suite-workbook-name>`, test case IDs read `<suite-case-id>`, and
`<dashboard-sheet>` shows the suite and its input where an issue pack shows the
issue and the change.

A suite pack has no change under test. Phase 3 classes every rule `Regression`,
`<core-objective>` is Not Applicable, and `<rule-matrix-sheet>` has to reach
every active rule, covered or with the reason it is not. The suite's rule count
runs to hundreds, so Phase 6 can fan out to subagents, one group of documents
each, writing one card file per document, `<code>.json` after the code its rule
prefix carries (`<rule-code-example>`), holding `cards`, `uncovered`, `reuse`
and `assumptions`. The session writes the rest of the pack, plus `suite`,
`modules` (each code's module name and abbreviation, in run order) and
`sourceAuthority` (what the suite's documents are), into a narrative file, and
merges:

```bash
<suite-merge> --export <scratchpad>/export.json \
  --cards <scratchpad>/cards --narrative <scratchpad>/narrative.json \
  --out <scratchpad>/<suite-pack-file>
```

The merge numbers the IDs, adds every requirement card to the regression and
full coverage sets, builds one set per objective in run order, and decides
applicability from those sets, so none of it can disagree with the cards.

A process description with no rules in the master has none to export: run
`<extract-skill>` for it first, or derive the rules in Phase 2 from the document
itself and record that in Job Intake as a limitation. Never invent a rule ID: a
rule the master does not hold is named by its source and statement, and that
name goes in the rule's `id`, which is how the cards refer to it, for example
`<derived-rule-example>`. A source with no page numbers, such as a sign-off
document, gives `N/A` as `sourcePage`.

## The pack file

Every phase writes its output into one JSON file in the scratchpad,
`<scratchpad>/<pack-file>`, and the builder reads only that file. Its fields, by
the phase that fills them:

| Field | Phase | Shape |
| --- | --- | --- |
| `<id-fields>` | intake | the change-applies field is false when the change has no `<change-term>` |
| `suite`, `suiteInput` | intake | a suite pack only, in place of the issue and change numbers |
| `sourceDocuments` | 1 | `{ name, inclusion, authority, reason }`; inclusion is `Included`, `Supporting Context Only` or `Excluded` |
| `intake` | intake, 1 | `{ received, missing, authority, contextOnly, assumptionsToProceed, readiness }`; readiness `READY` or `READY WITH ASSUMPTIONS` builds, the other two stop |
| `rules` | 2, 3 | `{ id, name, module, sourceDocument, sourcePage, summary, risk, impact, rationale }`; impact is `Direct Change`, `Indirect Impact`, `Regression` or `Not Impacted` |
| `executiveSummary` | 4 | `{ scope, modules, sourceDocuments, strategy, execution, risks, confidence }` |
| `objectives` | 5 | `{ objective, applicable, reason }` for each of `<workbook-standard>`'s `<objective-count>` |
| `testCards` | 6 | `{ id, title, module, sourceDocument, mission, focus[], expected, rules[], objectives[], derivation, steps[] }`; derivation is `Requirement` or `Quality`; each step is `{ description, expected, rules[] }` |
| `testSets` | 7 | `{ number, name, objective, scope, ruleSummary[], cards[] }` |
| `coverage` | 9 | `{ ruleId, status, strength, gap, recommendation }`, only where a rule is not plainly Covered |
| `assumptions` | 9 | `{ assumption, why, impact, clarification }` |
| `seniorReview` | 9 | `{ missed, businessBehavior, upstreamDownstream, obviousFirst, qualityDerived }` |
| `testerNotes` | 9 | `{ testData, execution, regressionTargets, breakIt, screenshots, sqlValidation, knownRisks, cautions }` |
| `confidence` | 9 | `{ overall, coverage, remainingRisks, assumptions, regressionScope, breakItScope, manualReview }`; overall is `High`, `Medium` or `Low` |
| `limitations` | any | `{ "<sheet name>": "<why it is not complete>" }` |
| `improvementNotes` | 10 | `{ gap, impact, recommendation, component }` |

The builder works out the rest: the `<dashboard-sheet>` counts and coverage
percentage, the `<objective-sheet>`'s related cards and sets, both Markdown
columns, every `<upload-sheet>` row, the `<rule-matrix-sheet>`, the derived
columns of the `<coverage-sheet>`, the assumption IDs, and
`<validation-sheet>`. Do not type those into the pack; a hand-typed count is one
that drifts from the cards.

## The phases

`<procedure>` governs. What follows is how each phase runs and what it leaves in
the pack. After each phase, check its outputs against the procedure, record the
phase as passed in the running summary, and only then start the next.
`<procedure>` asks for one phase per response unless the user wants a condensed
run; in a session working on its own, run the phases in order in one pass, but
never merge two phases' work, and stop at the first gate that fails.

**Job Intake.** Classify the request (`<job-type>`), inventory every input
against the table above, and set `intake.readiness`. The four required inputs
are the `<issue-term>` number, the `<change-term>` number when the change has
one, the description, and either rules in the master or a source document to
derive them from. One missing is found here and stops the run at Phase 1, the
gate `<procedure>` names for it, before any summary is written: ask only for
what is missing, through `<ask-user>`. The builder refuses a pack missing one
the same way, printing `STOP at Phase 1` and the missing inputs.

**Phase 1, Project Understanding Gate.** Write the Project Understanding Summary
in the conversation: change, purpose, modules, existing and new behavior, rules
identified, in and out of scope, missing information, confidence. Rank every
source by the gate's authority order and give each an inclusion decision with a
reason; drop what cannot be justified. Two included sources that conflict stop
the workflow: name the conflict and ask. Low confidence stops it too. No test
design starts before this gate passes.

**Phase 2, Business Rule / Requirement Intake.** Build `rules` from the included
sources only. Rule IDs come from the master export exactly as held; source page
is the rule's `source_page`. Merge duplicate wording, never unrelated rules. An
unresolved conflict or an untraceable rule stops here.

**Phase 3, Change Scope Analysis.** The `<change-term>` description is the
lens. Set each rule's `impact` and `rationale`. A process description's full
baseline is not the change: rules the change does not touch are `Not Impacted`
or left out, and the count left out is said in the summary. Note ambiguities as
assumptions.

**Phase 4, Impact Analysis.** Modules, windows, business functions, upstream and
downstream effects, data, security and roles, batch, notices, reports and
interfaces. This fills `executiveSummary` and the risk on each rule.

**Phase 5, Testing Objective Selection.** Decide all `<objective-count>`
objectives, each with a reason. None is left out.

**Phase 6, Reusable Test Design.** One card per business decision, per the
`<methodology>` chapters on decisions and on test cards. Test case IDs are
`<case-id>`. Focus steps are actions; the expected result is observable business
behavior. Mark quality-derived cards. A card an existing `<test-tool>` asset or
manual test already covers is reused by name in `<notes-sheet>` rather than
written again.

**Phase 7, Test Lab / Execution Design.** Group cards into test sets, one
objective per set, in the order they should run: `<core-objective>` first,
`<break-objective>` last. A Build name the user has not supplied stays the
literal `<Build Name>` and is recorded as a limitation.

**Phase 8, Workbook generation.** Run the builder:

```bash
<pack-builder> <scratchpad>/<pack-file> --out <scratchpad>
```

It prints one line per worksheet with its validation status and writes the
workbook only when no sheet is FAIL. A FAIL names the defect: a card naming a
rule the pack does not hold, a repeated rule or test case ID, a test case ID off
the pattern, an objective with no true-or-false decision or one that disagrees
with the test sets, a rule marked covered that no card covers or marked
otherwise when a card does, a rule with no coverage and no gap, a rule taken
from a source that is not Included, a risk, derivation, inclusion or objective
off its list, or a sheet with blank fields. It also fails a rule marked Covered
that only quality-derived cards cover, a module abbreviation two modules share,
test sets out of run order, an executive summary confidence that disagrees with
the overall one, missing intake inputs with no `<intake-sheet>` limitation, and
a Direct Change rule no card covers unless a `<coverage-sheet>` limitation names
its rule ID. A design step that names no rules traces the card's rules no other
step names. `<validation-sheet>` itself reads PASS WITH LIMITATIONS when any
sheet does. Fix the pack and run it again. A sheet that cannot be completed gets
a `limitations` entry saying why, and validates PASS WITH LIMITATIONS. The
`<upload-sheet>` test name is the test case ID alone, as `<workbook-standard>`
gives it; the title travels in `<cards-sheet>`.

**Phase 9, Quality Review.** Run `<validation-procedure>` against the pack, list
issues and fixes, apply them to the pack, rebuild, then run
`<revalidation-procedure>`. Fill `seniorReview`, `testerNotes`, `confidence` and
`coverage` before the final build. `<procedure>` stops on Low confidence at the
Project Understanding Gate, before anything is built. A Low rating here is
allowed, but only with a `limitations` entry for `<confidence-sheet>` saying
what holds it down, and `executiveSummary.confidence` has to match it.

**Phase 10, Repository Improvement Notes.** Record what the reference material,
this skill, or the repository's sources lacked during the run in
`improvementNotes`, and say them in the report. `<workbook-standard>` gives them
no worksheet, so the builder leaves them out of the workbook. A gap in the
repository's own tooling is filed through `<follow-up>`.

## Where the workbook lands

The scratchpad, or a path the user names. It goes under `<docs-root>/<suite>`
only when the user asks for that, and then `<writing-gates>` apply to it. Send
the finished file to the user with `<send-file>` when the session is followed
from another device, and give its path either way.

## Loading a suite pack into the test tool

A suite pack the user has approved goes into `<test-tool>` through
`<testpack-command>`, a dry run first and a send only when the user asks for
one:

```bash
<testpack-command> --doc <committed-pack>
<testpack-command> --doc <committed-pack> --send
```

The pack file is read from `<pack-source>`. `<upload-script>` does the work:

- Each test card becomes a manual test in the test plan under `<plan-folder>`,
  named for its test case ID and title, with one design step per pack step and
  a coverage link to each rule requirement the card names. `<test-tool>`
  refuses some characters in a test name, and `<name-substitutes>` gives what
  the name carries in their place.
- Each test set becomes a set in the test lab under `<lab-folder>`, holding an
  instance of every card it names, in the pack's order.
- The requirement ids come from the master, which records them when
  `<rule-upload>` loads the suite's rules. A rule the master holds no
  `<test-tool>` id for refuses the whole run, so the rules go up first.
- Every folder on either path that `<test-tool>` lacks is created,
  `<tool-roots>` aside. The first suite to run creates `<shared-folders>` and
  the rest reuse it.
- Everything is looked up before anything is written, so a repeat dry run plans
  no writes. What `<test-tool>` holds that the pack does not name is reported
  and left in place. The send ends by planning again and fails if anything is
  still missing.

Moving the tests and sets out of the staging folders is the reviewer's job in
`<test-tool>`. Test runs and results stay out.

## What stays out

- An issue pack is not uploaded to `<test-tool>`. Its `<upload-sheet>` is the
  test plan import the user loads by hand.
- The business rule master is read, never changed. A rule found missing from it
  is an `<update-skill>` or `<extract-skill>` job, filed or run separately.
- `<gold-packs>` are not edited.

## Report

Say which phases passed, where any stopped and what it needs, the workbook path,
the `<validation-sheet>` result per sheet that is not PASS, the assumptions, and
the improvement notes.
