---
name: build-test-pack
description: Build a test pack workbook for one defect record and its change record by running a phased Build Test Pack procedure, each phase gated before the next, and writing the workbook a workbook standard defines, or one for a suite's whole approved rule set. Use when asked to build, make, or generate a test pack for a defect or a change. Also use to load an approved suite pack into the test management tool's test plan and test lab.
---

# Build Test Pack

Takes a `<issue-term>` number, a `<change-term>` number when the change has
one, and the source documents. `<invocation>` names both; the documents can be
named in the request, attached, or found in the repository.

When the repository names `<pipeline-config>`, the pack is built by the local
pipeline, not by the session: see "Running on the local model" below. The
session then reads none of the inputs and none of what the pipeline writes.

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
| `<full-coverage-objective>` | The objective whose set runs every card that comes from a requirement |
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
| `<pipeline-config>` | The local pipeline's config file, when packs are built on the local model |
| `<pipeline>` | The local pipeline's command, `node <this skill's folder>/local/build-pack.mjs` |

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

## Running on the local model

With `<pipeline-config>` set, the whole pack is built by `<pipeline>` against the
local model the config names, and no part of it passes through the session. The
pipeline runs intake and every phase below as fixed prompts that answer against
a JSON schema, checks each gate in code, and ends with `<pack-builder>`, feeding
any FAIL back to the model a bounded number of times. Its config names the
endpoint, which must be on the loopback interface, the model, the reference
documents and the methodology chapters each phase reads, the input commands
(`<rule-export>`, `<folder-export>`, the description and the document index),
and `<pack-builder>` and `<suite-merge>`, which it runs unchanged.

Each document's rules are checked in two places. Intake checks every document
it resolves, and stops with a code and the document's number when:

| Code | Meaning |
| --- | --- |
| `rule-export-failed` | `<rule-export>` failed for a reason other than the next row, so an outage never passes for a document with no rules |
| `rules-malformed` | the export is not the shape the rule master writes: the top level, `doc`, the prefix, the rule IDs and their uniqueness, the statuses, or an empty rule list; what is wrong goes to `detail.log` only |

Phase 2 reads the export again for each Included document whose rules intake
did not just export, so a job resumed after the rules were extracted sees them.
It writes a `stop-doc` status line per failing document, then stops with a
count and the document numbers under the first code that applies:
`rule-export-failed`, `rules-malformed` (both as above), then:

| Code | Meaning |
| --- | --- |
| `rules-not-extracted` | the export's error output matches the config's `noRules` pattern, its own way of saying the document has no rules in the master yet |

An export outage in Phase 2 for a document whose rules intake read keeps those
rules and leaves a `warn` status line.

A document that is only supporting context needs no rules: Phase 2 does not
read it again, and a missing or stale rule set on it never stops the job.

Values the master holds that the current procedure would not write (an older
category, a requirement type that names a category, a blank column, a page the
document cannot place) are warnings in `detail.log`, not a stop. So is `rules-stale`: the document's provenance revision date is later than
the day its rules were last confirmed (the export's `reviewed` or
`last_reviewed` day when it has one, else the newest `created` date on its
rules). A stale export leaves a `warn` status line with the document's number;
the session offers `<update-skill>` for it and does not stop the job. A document
that states no revision date is not checked.

`retired-rule-missing` is the same kind of warning, raised at the start of Phase 2
for each Included document: its text has struck-through (`~~...~~`) text that
states something, outside code, and no rule citing it is in its rule export. Each
span is one of three. A fragment is part of a sentence (it does not end in `.`,
`!`, `?` or `:`, inside the tildes or just after them, and does not fill its line, list item or table cell), such as
`~~90~~ 120 days` or `~~not~~`; it is a wording or value change and never
warns. A restated sentence is a whole sentence followed in its paragraph by a
live sentence holding two thirds of its significant words (four letters or
more, common words left out); it never warns either. Any other span is a
removal, and a retired rule cites it when the rule's `source_page` is the span's
page (the nearest `page-N` marker above it), a range or list holding that page,
or the heading above the span. A live sentence that says something else beside
a struck one does not cite it. The warning
leaves a `warn` status line with the document's number and a `Job Intake`
limitation saying removed behavior may be missing; the job goes on. The session
offers `<update-skill>` for it.

The rules are derived from the document in Phase 2 only when the job or the
config opts in, with `--allow-derived-rules` or `allowDerivedRules` in the
config, off by default. Use it only when the user chooses to go ahead without
extracted rules; Job Intake then records the limitation. A retired rule stays in
the pack with a summary that starts "Retired:", and Phase 3 classifies it like
any other rule: Direct Change only when the change description concerns that
removal, Not Impacted otherwise. Phase 6 gives every retired Direct Change rule a
card that verifies the behavior is gone.

### Before a job is run or queued

Before `run` or `queue add`, the session refreshes the source documents, as
"Refreshing the source documents" under "Inputs, and where they come from"
sets out, and then runs the input gates, which make no
model call and print content-free lines only:

```bash
<pipeline> check --config <pipeline-config> --issue <n> [--change <m>] [--doc <path>]... [--allow-derived-rules]
```

Each line reads `<input>  present|missing  <code>`: the issue number, the
description, and each document by number with the reason code for its rules
(`rules-ok`, `rules-derived`, `rules-stale`, `rules-not-extracted`,
`rules-malformed`, `rule-export-failed`, or `document-file` for a document that
is not in the repository). The exit code is 0 when every input is present, 1
when a required input is missing, and 3 when no `--doc` was given: the model
chooses the documents at intake, so only the candidates are counted and the
line `rules  unchecked  name-documents-with-doc` is printed. Pass the documents
the request names so their rules are checked before the job waits for the
night; a job with unchecked rules is queued only when the user chooses to.
What `check` found wrong with an export is in `<job-id>.check/detail.log` in
the pipeline's output folder, which a later run does not clear.

For every missing input, the session asks the user through `<ask-user>`:

- for each document without usable rules, offer `<extract-skill>`; for
  `rules-stale`, offer `<update-skill>`; for `rules-malformed`, offer
  `<update-skill>` and say the cause is in the check's `detail.log`, for the
  user to read;
- list the `<attached-only>` items, which `check` cannot see, and any rule
  extract to attach, and ask which the user has;
- offer to go ahead with limitations (`--allow-derived-rules` for a document
  with no extracted rules).

The job is run or queued only when the gates pass, or when the user explicitly
chooses to go ahead with limitations. The session never reads a document or a
rule to answer any of this. `queue add` for a job already queued merges
`--allow-derived-rules`, `--doc`, `--now` and `--resume` into its row and says
what it updated.

The session never reads the documents, the rules, the description, the pack
file, the workbook, or the job's `detail.log` and `work` folder. It runs or
queues the job and reports the content-free status lines: phase names, pass or
fail, reason codes, counts and timings.

```bash
<pipeline> check --config <pipeline-config> --issue <n> [--change <m>] [--doc <path>]... [--allow-derived-rules]
<pipeline> run --config <pipeline-config> --issue <n> [--change <m>] [--doc <path>]... [--allow-derived-rules] [--resume]
<pipeline> run --config <pipeline-config> --suite <code> [--resume]
<pipeline> queue add --config <pipeline-config> --issue <n> [--change <m>] [--doc <path>]... [--allow-derived-rules] [--resume]
<pipeline> queue start --config <pipeline-config> --job <job-id> [--cutoff HH:MM]
<pipeline> queue status --config <pipeline-config> --job <job-id>
<pipeline> queue summary --config <pipeline-config>
<pipeline> queue remove --config <pipeline-config> --job <job-id>
<pipeline> queue fill --config <pipeline-config>
<pipeline> report --config <pipeline-config> [--period day|week|auto] [--seed <n>]
```

After each phase passes, the job saves its state in its `work` folder. A job run
again with `--resume` starts at the phase that stopped it, with the phases
before it kept as they passed, so a fix made after a failure costs only the
phases left. Without `--resume` a job starts over from intake.

Phase 9 runs as four steps, each saved when it passes: `phase9-checklist`
(issues, coverage rows, assumptions, the fix rounds), `phase9-confidence` (the
overall level and each field of the assessment, one call per field),
`phase9-senior` (the senior review and tester notes, written last), and
`phase9-revalidate` (the rebuild and the revalidation). Each call thinks through
one part of the review, and a job resumed in Phase 9 keeps the steps that
passed.

A reasoning call can think for up to `model.reasoningOutput` tokens (40,960 by
default), which takes well over an hour at local generation speeds, inside a
`model.context` of 128,000 tokens by default, so a call waits up to
`model.timeoutMinutes` (150 by default). The model server's context has to be at
least `model.context` (128000 by default; a `pipeline.json` can change it), and
its own request time-out at least `model.timeoutMinutes`, or the server ends the
reply early and the call fails with `no-reply`. A window smaller than
`model.context` may not show up as an error at all: the server runs with context
shift on, so it can drop the start of a prompt that is too long and answer
anyway. A call that fails while thinking is retried once with thinking off.

Lemonade keeps the model's window as a saved recipe option on the user model,
not in `/etc/lemonade` or the systemd unit. In the commands below, `<endpoint>`
is `model.endpoint` (for example `http://localhost:13305/api/v1`) and `<model name>` is
`model.name` in the pipeline config.

- To check the saved window, run `curl -s <endpoint>/models/<model name>` and
  read `recipe_options.ctx_size`. It works whether or not the model is loaded.
  To see what a loaded model is running with, read `recipe_options.ctx_size` in
  the matching `model_name` entry of `all_models_loaded` in `<endpoint>/health`;
  that list is empty when no model is loaded.
- To set it, load the model with the window saved:

        curl -sS --fail-with-body -X POST <endpoint>/load -H 'content-type: application/json' \
          -d '{"model_name":"<model name>","ctx_size":<model.context>,"llamacpp_backend":"<saved backend>","llamacpp_args":"<saved args>","save_options":true}'

  Take the backend and args from the model's saved `recipe_options`, carrying
  over every key it has and leaving out one that is not saved, because saving
  may replace the stored options. A rejected load prints the server's error and
  exits non-zero. The load reloads the model, so do it when no build is running.

A job takes an hour or more, so a request made during the day is queued.
`local/systemd/` holds a user timer that starts `queue run` at 22:00; the queue
runs one job at a time, puts a failed job back for a later run and moves on,
takes no new job past the cutoff (07:00 by default), takes none at all when the
timer only fires after the cutoff, and leaves a morning summary with one line
per job. "Running unattended" below covers how the queue fills, what a failure
does, and the daily report.
`queue run` given `--cutoff` runs whenever it is started. A stopped job's
status line names the phase and the gate; what the gate found is in the job's
own folder, for the user to read.

### Starting a job now, without reading it

When the user asks for a job to start now rather than at 22:00, the session
queues it and starts a unit for that one job, detached, and never sees what the
job reads or writes:

```bash
<pipeline> queue add --config <pipeline-config> --issue <n> [--change <m>] --now
systemctl --user start --no-block build-pack-now@<job-id>.service
```

`build-pack-now@.service` in `local/systemd/` is installed beside
`build-pack.service` and mirrors it: the same `EnvironmentFile`, and the same
`Nice=10`, so a daytime job does not take the machine at full priority. The unit
runs `/usr/bin/node`. The script and config paths come from
`~/.config/build-pack/env`, and so does everything else the job needs from its
environment: the unit gets the user manager's `PATH`, not the session's, so the
env file has to carry a full `PATH=` line (systemd does not expand `$PATH`
there) for a `<rule-export>` command that lives outside the system folders, and
any token that command reads, one `NAME=value` per line. Its instance name is
the job ID, and it runs `queue start --job <job-id>`, which runs that job's row
first and then any other row added with `--now`, until the configured
`queue.cutoff`. A row queued without `--now` is waiting for the nightly run and
stays queued; `queue add --now` for a job already waiting for tonight marks that
row to start now. `--no-block` returns at once; without it `systemctl` waits for
the whole run. The unit's output goes to the user's journal and the
job's own folder, never to the session.

The nightly timer is left as it is. The queue is held by one process at a time:
while it is held, a 22:00 `queue run` waits, polling every 30 seconds, and
works the night's queue as soon as the holder finishes; it gives up only when
the cutoff passes. A oneshot unit stays activating for its whole run, so a
second start of the same instance merges into it at any point while it runs. A
job already running under the nightly service is not refused by systemd, but
`queue start` finds the queue held and the row `running`, says `<job-id> is
already running`, and takes nothing. `queue add` prints `queued`, `marked to
start now` for a row it set to start now, `<job-id> is already queued; updated
<fields>` when it merged options into a waiting row, `already running`, or
`already queued`. A row
marked `running` whose process is gone counts as a failed try, `interrupted`,
for the next run that takes the queue. A run that works every queued row takes
the job again at once; a `queue start` run works only rows marked `--now`, so it
leaves the job for the night. The lock and the duplicate-ID check in
`queue add` are what stop a job from starting twice. The lock records the
holder's PID and start time, so a lock file left by a crash, or one whose PID
another process has since taken, is not a holder.

If another `queue run` or `queue start` already holds the queue, `queue start`
waits a couple of seconds, tries once more, and then takes nothing, says so, and
exits. The job stays `queued`. A `queue run` that holds the queue works every
queued row, oldest first, and takes this one when it is due and has not failed in
that run. A `queue start` works only rows marked `--now`, so it takes this one
only if it was queued with `--now`. Either way the row stays `queued`: that is
not a failed start. If the holder was a nightly run, wait for it; if it was a
start-now run and the row is not marked, start it again when the run ends or let
tonight's run take it.

The session reads the outcome with one command, which prints only the row's
status, whether a live process holds the queue, and the last status line the
job wrote (phase, event, reason code, counts, timings):

```bash
<pipeline> queue status --config <pipeline-config> --job <job-id>
```

A unit needs a moment to take the queue and mark the row `running`, so the
session repeats the command every few seconds for up to a minute before it
decides anything. `running` with the queue `held` is a start. `queued` with the
queue `held` is the case above. `queued` with the queue `free` after the minute
means the unit did not start; `systemctl --user is-active
build-pack-now@<job-id>.service` and the exit code in `systemctl --user show -p
Result build-pack-now@<job-id>.service` say why, and the session reports that
without opening the journal. `running` with the queue `free` is a row left by a
dead process: report it, and the next run marks it `interrupted`. `failed`
with the queue `free` is a job that stopped in its first phase and has already
released the queue; the status line names the phase and the reason code, and
the session reports them. `failed` or `passed` is final, whether the queue
shows `held` or `free`; the queue may be held by another job's run. `not queued`
means no row has that job ID, so the `--job` value or the `queue add` is wrong.
A lock file is not evidence of a live process; `queue status` checks the
process. The status line shown is the current attempt's; a resumed job shows
nothing until it writes its first line.

Later checks use the same command, and only it. They never read the journal,
`status.log` or anything else in the job's folder directly. Resume a stopped job
the same way, with `--resume` on the `queue add`.

### Freeing the machine for a job

A job needs the machine's memory and GPU for the model server. The optional
`pause` block in the pipeline config names systemd units to stop while a job
runs and start again afterward:

```json
"pause": {
  "units": ["<unit-pattern>"],
  "scope": "system",
  "busyProcess": "<worker process name>",
  "pollSeconds": 5
}
```

`units` takes unit names or patterns, as `systemctl list-units` does. Only
units that are active when the run begins are stopped, and only those are
started again. `scope` is `system` (the default) or `user`. With no `units`,
nothing is stopped and no command runs.

The stop comes when the first job is about to start, so a run with an empty
queue leaves the units alone. If `busyProcess` is set, a unit with a process of
that name inside its cgroup is busy: the run polls every `pollSeconds` and
stops it once the worker has finished, and never stops it while it works. The
first job waits until every unit is stopped, so it never shares the machine
with a busy one. The
units stopped are listed in a `.paused` file beside the queue file as each one
stops. The units start again when the run ends, however it ends, and also when
the process gets SIGTERM, SIGINT or SIGHUP. If a run dies before it can do
that, the next run that takes the queue finds the file and starts those units
at its end, even when it has no job to run. A stop or start that fails is
logged as `pause: stop failed <unit>` or `pause: start failed <unit>` and the
run carries on; a unit that would not stop is not started later. A `run`
outside the queue stops and starts the units the same way, but holds no queue
lock, so it leaves a dead run's `.paused` file for the next queue run.

With scope `system`, the commands run as `sudo -n /usr/bin/systemctl`, so the
user running the queue needs a sudoers rule that needs no password. List each
unit and each verb on its own, for example:

```
<user> ALL=(root) NOPASSWD: /usr/bin/systemctl stop <unit>, /usr/bin/systemctl start <unit>
```

A `*` in a sudoers argument also matches spaces, so a pattern there can allow
more than the unit it was meant for. Listing the units is safer. With scope
`user`, no sudo is involved.

### Running unattended

A week of nightly runs needs no one at the keyboard. The queue fills itself,
a failed job tries once more, and a report tells the maintainer what to look at.
The session does not read the report's sources any more than it reads a job's
folder; it passes on the report's lines.

**The queue fills itself.** The config's `queue.sources` lists where new jobs
are named. Each night, after `queue run` takes the queue and before it takes a
job, every source is read and each job it names that the queue has not seen is
queued. A source is one of:

```json
"queue": {
  "sources": [
    { "type": "folder", "path": "<folder>" },
    { "type": "records", "glob": "<records-glob>", "pattern": "<file-name-regex>" },
    { "type": "command", "command": ["<program>", "<argument>"] }
  ]
}
```

- `folder`: every file in the folder is a list of jobs, one per line. The
  maintainer drops a list there.
- `records`: one job per record file, such as the SIR records in the
  repository's documents folder. The first group of `pattern` (case-insensitive,
  matched against the file name) is the issue number and an optional second
  group is the change number. A file name the pattern does not read is counted
  as an unreadable line and skipped. Without a `pattern`, a name that starts
  with `SIR` or `ISSUE`, an optional `-`, `_` or space, and the issue number is
  read; a change is read only when `change` or `CR` follows, then a number that
  starts with a digit, as in `SIR-9415-change-7001.md` or `ISSUE_9415_CR7001.md`.
  `SIR-9415-credit-limit.md` is issue 9415 with no change. A name where `change`
  or `CR` stands alone after the issue number but no valid change number follows,
  such as `SIR-9415-CR-CHG7001.md` or `SIR-9415-CR-7001,7002.md`, is counted as an
  unreadable line and not queued, so the issue is never queued without the change
  it names. So is a title that begins with one of those words, such as
  `SIR-9415-change-password.md` or `SIR-9415-CR-screen.md`; the pattern cannot
  tell it from a bad change number. Rename the file or add the job by hand.
- `command`: a program that prints job lines, such as one that lists the build's
  SIR/CR from the requirements tool. It runs in the repository root, and a
  non-zero exit reads as an unreadable source.

A job line is `<issue>`, `<issue> <change>`, `suite <code>`, or the full
`queue add` form, such as `--issue 9415 --doc <path>`. Blank lines and lines
that start with `#` are skipped, and a line that is not a job is counted and
skipped. Jobs queued this way are not checked when they are queued, so the
pre-check below is what catches a bad one before the night. A job whose
documents have no usable rules otherwise fails at intake, retries once, and is
dropped with a gate reason code (for example `gate:rules-not-extracted`);
the report shows it. A job already in the queue file in any state (waiting, passed, failed
or removed) is never queued again, so a list can stay in the folder after its
jobs have run. `queue fill` does the same read by hand and prints which jobs it
queued, how many it already knew, and which sources it could not read. A source
that lists every record in the repository queues every one of them the first
time, so point a `records` source at the open ones.

**The queue is checked at 18:00.** `queue check` changes nothing in the
queue. It runs the `check` input gates, with no model call, on every waiting
issue row and on every job the sources would queue tonight, and writes the
lines to `precheck.txt` in the pipeline output folder: a `checked <local time>`
line, a `sources` line with the counts `queue fill` would print, then one line
per input, `<job-id>  <input>  present|missing  <code>`, with the codes
`check` prints. The sources are read, not filled, so a source line fixed after
the check still counts at the nightly fill. A suite row reads
`<job-id>  suite  refused`, since `check` takes issue jobs only. A row queued
without `--doc` reads `rules  unchecked` when the document index has
candidates, and `documents  missing  no-candidates` when it has none. A row
still marked running while no run holds the queue reads `running  stale-row`
and is checked too: the nightly run counts it as a failed try, `interrupted`,
and takes it again. On its last try that settle drops it instead, so it reads
`running  stale-row-dropped` and is not checked. A row whose check throws reads
`check  failed  <error name>`, and a queue file that does not parse ends the
lines with `precheck  failed  <error name>`.

A run that holds the queue is waited for, up to an hour; after that the file
reads `queue  held  precheck-skipped`, and a run that takes the queue mid-check
stops it before the next row with `queue  held  precheck-stopped`; a rule
export already going finishes first. While the check runs the file
reads `precheck  running`, and the final `checked` time is when the queue
was read, after any wait. A check stopped part way never leaves the last
day's lines standing. The exit code is like `check`'s: 1 when an input is
missing, a source could not be read, a check or the pre-check failed, or the
queue stayed held, and 3 when some rows' rules went unchecked; the unit fails
on 1 only.
`local/systemd/build-pack-check.timer` starts it at 18:00, four hours before
the nightly run at the default `queue.start`, so a job with a missing input can
be fixed or removed with `queue remove` first; a host with an earlier
`queue.start` moves the timer to match. A check the machine slept through is
not made up.

**A failed job tries once more.** The first time a job fails, its row goes back
to waiting with the failure kept (phase and reason code). A job that failed
during the night is not retaken that night; the next nightly run takes it and
resumes from the phase that stopped it. A job that failed in the daytime, such as
one started on request, is taken by that evening's run. A job that fails a
second time stays `failed`, is never taken again, and is flagged in the report
with both reasons. A run that died mid-job counts as a failed try with the
reason `interrupted` and no wait. A run that works every queued row takes it at
once; a `queue start` run works only rows marked `--now`, so it leaves the row
for the night. `queue start --job <job-id>` on a job waiting for its retry runs
it without waiting, and so does a `--now` row under a `queue start`. `queue add
--now` only marks the row; the start comes from `queue start`. `queue add` on a
dropped job is how a person puts it back.

**The report.** `report` reads the queue file and each job's `status.log`, and
writes `daily-<date>.md`; on the configured weekday (`report.weeklyDay`, 1 for
Monday) it writes `weekly-<date>.md`, the same layout over seven days with a
count for each day. The files go in the output folder's `reports/` folder, or in
`report.dir`. Like the status lines, they hold job IDs, reason codes, counts,
confidence ratings and run times, and nothing a document or the model said, so
a file can be opened or sent anywhere. Each has:

- a summary: jobs passed, jobs waiting to retry, jobs dropped, and the queue's
  depth;
- a table with each job's result (PASS, PASS WITH LIMITATIONS, RETRY or
  DROPPED), the phase and reason code of the gate that stopped it, the sheet
  counts (pass, limited, fail), the confidence rating and the run time;
- the jobs that keep failing, with every reason code and whether each retries or
  has been dropped;
- a spot-check list: packs rated Low confidence first, then PASS WITH
  LIMITATIONS, up to `report.maxPriority` (6), then `report.sample` (2) more
  chosen at random from the other passed packs. `--seed <n>` or `report.seed`
  makes the random choice repeatable.

`local/systemd/build-pack-report.timer` writes the report at 07:30 each morning,
half an hour after the queue's default cutoff.

**Maintainer runbook.** Every command below is `<pipeline> <command> --config
<pipeline-config>`, run on the host that holds the timer.

- Add a job. Put its number on a line in a file in the source folder, or run
  `queue add --issue <n> [--change <m>]`. To run a dropped job again, run
  `queue add` for it. Anyone who can write to the source folder can name the
  documents the model will read (`--doc` on a line), so keep that folder
  writable only by people trusted with the repository's documents.
- Remove a job. Run `queue remove --job <job-id>`, and take its line out of the
  source so it is not a surprise later; the job stays out of the queue either
  way. A job that is running cannot be removed; remove it after it finishes.
  `queue remove` and `queue fill` take the queue's lock, so while a run holds the
  queue they say so and exit; run them again when it ends.
- Read the report. Open the newest file in the reports folder. Start with
  "Jobs that keep failing": a DROPPED job needs a person, and its reason code and
  phase say where to look. A RETRY job needs nothing yet. Then open the
  workbooks in the spot-check list and judge them. Packs with Low confidence or
  limitations come first because they are where the model was least sure. A
  queue depth that grows night over night means the jobs take longer than the
  night allows.
- Restart the model server. Find its unit name: the port in the config's
  `model.endpoint` says which service listens, and `systemctl --user list-units
  --type=service` (or `systemctl list-units --type=service` for a system unit)
  shows it. Check that it is up with `systemctl --user status <model-server-unit>`,
  then restart it with `systemctl --user restart <model-server-unit>`. Do it
  while no job is running (`queue status --job <job-id>` shows `held` while one
  is). A restart during a job makes the call in flight fail, and the job takes
  an ordinary failed try (`model:network`, `model:http` or `model:no-reply`),
  so it is retried like any other failure; only a pipeline process that died
  itself leaves an `interrupted` row. After a restart, the server's context size
  and request time-out must still be at least `model.context` and
  `model.timeoutMinutes`. Lemonade keeps the window as a saved recipe option on
  the model, so read `recipe_options.ctx_size` from
  `<endpoint>/models/<model name>` (`<endpoint>` and `<model name>` as defined
  above) to confirm it is still at least
  `model.context`; `/health` shows nothing until the model is loaded.
- Move the timer to another host. On the new host install the repository, the
  model server, the pipeline config and the env file at
  `~/.config/build-pack/env`, then copy `build-pack.service`, `build-pack.timer`,
  `build-pack-check.service`, `build-pack-check.timer`,
  `build-pack-report.service` and `build-pack-report.timer` to
  `~/.config/systemd/user/` and run `systemctl --user daemon-reload` and
  `systemctl --user enable --now build-pack.timer build-pack-check.timer build-pack-report.timer`. Run
  `loginctl enable-linger <user>` on the new host as well, or user timers stop
  when that user logs out and the night's run never starts. Copy the queue file
  (`queue.file`) and the pipeline's output folder (the jobs' status logs and the
  reports) from the old host so the queue and its history carry over, and run
  `queue status` for a waiting job to check it is read. Then
  `systemctl --user disable --now build-pack.timer build-pack-check.timer build-pack-report.timer` on
  the old host. Two hosts with the timer on would build the same jobs twice,
  since the queue lock is per host.

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
| Business rule matrix | the business rule master, through `<rule-export>`, one call per process description; `check` reports whether each document's rules are usable before a job runs |
| Process description | `<process-docs>` |
| Design or module specification | `<design-docs>` |
| `<attached-only>` | attached by the user; there is no copy in the repository |
| Existing `<test-tool>` test plan and test lab assets | `<existing-tests>` |
| Existing automation | `<existing-automation>` |

### Refreshing the source documents

Before a job is checked, run, or queued, the session makes sure every document
the pack relies on is current. A candidate document that intake picks later
is checked the same way before Phase 1 passes, in a session build. A pack built from a stale converted copy gets its
rules, its conflicts, and its scope from text the change has already replaced.

1. **Find the documents.** In a session build, every document the
   `<issue-term>`, the `<change-term>`, or their thread comments name or point
   to, plus the candidate documents intake picks. For a job on the local
   pipeline the session reads none of those, so the documents are the ones the
   request names with `--doc`; a document the model picks at intake is not
   covered, and the user is told so.
2. **Check each against the library** with `doc-watch`'s lookup
   (`payload --mode lookup --name <file>`, then `lookup`), which reports each
   named document's Modified time to the minute. Each `<file>` is the library
   file name from the converted copy's `Source` line; a document with no
   converted copy is named as the request or the description gives it. A result
   with `readable` false is the unreachable case in step 5. A document that comes
   back `held`, `no_suite`, or `not_found` goes to the user through `<ask-user>`
   rather than being guessed at; one that comes back `ignored` is left as it is. A document is **missing** when
   no converted copy exists. It is **stale** when the library copy was modified
   at or after the converted copy's `Converted` minute, compared to the minute and
   not by day. A converted copy whose `Converted` line holds only a date has no
   time to compare, so a library copy modified on that day or later is stale. In
   a session build a document is also stale when the `<change-term>` says it was
   updated after the converted copy's `Revised` date.
3. **Download, convert, and use the new copy, without asking.** For each missing
   or stale document, download it through `doc-watch`'s download handler, place
   it with `place --keep-resaved` so a same-day edit is not dropped as a re-save,
   convert it with `convert-docs`, and run the job on the new conversion. This
   is a standing approval for this case only; `doc-watch`'s other downloads
   still ask first. A conversion that needs a hand merge stops for the user.
4. **Keep a record.** Put each refreshed document on a `<download-branch>`
   branch with its `library.tsv` row, and open a pull request for it, so the
   repository copy catches up through the usual review. Name every refreshed
   document in the pack's intake notes.
5. **When the library cannot be reached**, such as on an overnight run with no
   signed-in browser, the job does not build from a copy that might be stale
   without saying so. This skill stops: the session does not run or queue the
   job, and reports which documents need refreshing. In an attended session
   the user may choose to go ahead anyway; Job Intake then lists each document
   under `<intake-sheet>` limitations as built without a check against the
   library. The local pipeline has no such flag, so a job on it waits until the
   documents are refreshed.

The session reads the library's listing and each copy's provenance block for
the check, never a document's content.

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
`<extract-skill>` for it first, or, when the user chooses to go ahead without,
derive the rules in Phase 2 from the document itself and record that in Job
Intake as a limitation. Never invent a rule ID: a
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
| `revalidation` | 9 | `{ passed, remaining[] }`, set only when revalidation fails; the builder shows `<validation-sheet>` as FAIL with `remaining`, and still writes the workbook |
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

**Job Intake.** In a session build, the source documents were refreshed first,
as "Refreshing the source documents" above sets out; name each refreshed
document in the intake notes. Classify the request (`<job-type>`), inventory every input
against the table above, and set `intake.readiness`. What intake records as
missing is what it did not receive, not the procedure's list of preferred
inputs: a converted document whose provenance path is in a CAMP Designs folder counts
as the CAMP document, and its revision date counts as the updated design. The
change description in `<id-fields>` holds only the record's ALM short and long
descriptions. The four required inputs
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
interfaces. This fills `executiveSummary` and the risk on each rule. Every Direct
Change, Indirect Impact and Regression rule is rated from the impact analysis,
with the master's `risk_level` as its starting value; a Not Impacted rule keeps
the master's, or is rated when the master gave none. A suite pack has no change
to rate against, so it keeps the approved risks and rates only a rule with none.
Code then raises any Direct Change rule below the first configured risk level,
High by default, to that level and lists each one it raised in detail.log.

**Phase 5, Testing Objective Selection.** Decide all `<objective-count>`
objectives, each with a reason. None is left out. A change that includes the
stage closure submit after a FATL downgrade makes Integration Testing
applicable. Phase 5 sees the ALM description fields plus the lines of the
impacted rules that hold both terms, as many as fit, and detail.log says how
many did not. The reply says whether the change includes the submit and, when
it does, quotes the sentence that says so. Code accepts the answer only when the
quote appears word for word (whitespace and case aside) in the ALM descriptions
or in a Direct Change or Indirect Impact rule (read as its name and summary),
and the one quote holds a FATL downgrade, a stage closure and a submit; then
Integration Testing is applicable, with that reason. Otherwise the model's own
answer for it stands, and detail.log says the evidence was rejected. Assumptions
that cite a rule ID the pack does not hold, or a count of rules or cards it does
not have, are dropped before the build.

**Phase 6, Reusable Test Design.** One card per business decision, per the
`<methodology>` chapters on decisions and on test cards. Test case IDs are
`<case-id>`. Focus steps are actions; the expected result is observable business
behavior. Mark quality-derived cards. A card an existing `<test-tool>` asset or
manual test already covers is reused by name in `<notes-sheet>` rather than
written again.

Design scenarios first, then cards. For each Included document, list the
distinct scenarios its impacted rules call for before any card is written. A
scenario is one population, one action and its expected outcome, and names the
rules it checks. The list has to include, wherever the document supports them:

- a control, a population the change must not affect, such as the plain save;
- isolation, where another record's state must not leak into this one;
- a combined scenario, where conditions overlap;
- persistence, closing and reopening the record;
- in an issue pack with a `<break-objective>` set, a break scenario, which tries
  to break the change with bad input, a wrong order, a boundary or a repeated
  action.

Every other scenario is a plain decision. A kind the document does not support
is recorded as an assumption with the reason. Rules too many for one call are
taken in batches, each shown the scenarios listed so far, and a reply holds at
most one scenario per 150 tokens of the output limit; an assumption says when
the limit was reached. Two scenarios with the same kind, rules, population and
action are one; the second is dropped and counted.

Write the cards in batches of scenarios (`cardScenariosPerCall` in the config,
four by default). Each call is shown the scenarios still open, meaning those
with no card, reuse entry or skip yet, the rules they name, and the cards
written so far. Each card names the one open scenario it covers. A scenario is
settled only by a card, or by a `skipped` entry that says an existing test
covers it (`reused`, naming the test) or that no card can (`gap`, with the
reason); a rule gap reported for one scenario never settles another. A card
whose scenario repeats an earlier card's kind, rules, population and action is
dropped and counted. A scenario still open after its batch is asked for once
more; if it is still open, an assumption names it, and any of its rules with no
card get a `Missing` coverage row. A rule only an existing test covers gets a
`Missing` row whose gap names that test and says to confirm and reuse it.

A retired rule Phase 3 classified Direct Change is marked in the scenario and
card prompts as removed: its card verifies the behavior is gone, and the
Expected Result, final step included, says it is absent (for a removed warning,
that the warning and its Yes and No buttons do not appear); the Expected Result
check reads such a rule as removed and passes a card that states the absence.
When no scenario names and no card cites
such a rule once its document's cards are written, code adds a scenario for it
and asks for the card, twice at most; a rule still without a card reads
`Missing` and the `<coverage-sheet>` limitation names it.

Then check each card's Expected Result: one call per batch of up to eight
cards is shown each card, with its steps, and the rules it cites with their
source wording (the summary, and the master's description when it adds to
it), and answers `follows` or `does not follow` for every card with a reason.
The prompt gives a default for conflicting rules: a rule that blocks an action
outranks one that allows it, so the action stays blocked, unless a cited rule
says it is an exception to the block or overrides it; Reset restores the saved
value, never the edited one. A card that follows its rules but whose final step
words the result differently (see Phase 8 for what counts as agreeing) is kept,
and code copies the card's Expected Result into that final step; only a card
that does not follow is redone. A call too big for its room is split, and a card
too big alone is asked again with rule summaries only; if that is still too
big, the card is kept and an assumption says it was not checked.

A card that fails is designed again once through a card call for its scenario
alone, told the reason and the Expected Result that failed, and checked again.
If it still fails, or the redesign returns no card, the card is removed. When
the redesign answers with a `skipped` entry for the scenario, the scenario is
settled with that skip and its reason; otherwise it is settled as removed. An
assumption names the card and gives the reason, and each of its rules no other
card covers gets a `Missing` coverage row whose gap gives the reason (a rule an
existing test covers keeps its row naming that test). This runs before the
objective passes below, so a removed card never counts toward an objective, and
before Phase 7, so no set holds it. The Phase 6 status line adds `redesigned`
and `removed`, as numbers.

An applicable objective that no card serves gets one targeted pass. Cards that
pass adds are checked the same way. For an
ordinary objective, the model is shown the cards written and names those that
serve it; the objective is added to them, no card is written, and the objective
is marked not applicable if none is named. For `<break-objective>`, a break-only
inventory adds new break scenarios, each with one card; the objective is marked
not applicable if there are none. `<full-coverage-objective>` needs no pass,
since it holds every requirement card; Phase 6 marks it not applicable when no
requirement-derived card exists.

**Phase 7, Test Lab / Execution Design.** Group cards into test sets, one
objective per set, in the order they should run: `<core-objective>` first,
`<break-objective>` last. In an issue pack, the `<full-coverage-objective>` set
holds every card that comes from a requirement, and the pack marks that
objective applicable whenever one exists and a card lands in the set, even if
Phase 5 did not. The
`<break-objective>` set holds only cards written for break scenarios (`breakIt`,
set by the pipeline from the scenario's kind, never by the model). A card can
sit in more than one set. The config key `exclusiveSets` set to `true` keeps a
BREAK IT card in the `<break-objective>` set alone. A card left with no set,
because none of its objectives is applicable, is left out and an assumption
names it. The config keys `fullCoverageObjective` and `breakItObjective` name
the two sets; without them the pipeline uses the builder's objectives named
`Full Coverage Required Run` and `BREAK IT`. A Build name the user has not
supplied stays the literal `<Build Name>` and is recorded as a limitation.

**Phase 8, Workbook generation.** Run the builder:

```bash
<pack-builder> <scratchpad>/<pack-file> --out <scratchpad>
```

It prints one line per worksheet with its validation status and writes the
workbook only when no sheet is FAIL, except the `revalidation` FAIL on `<validation-sheet>` that Phase 9 sets. A FAIL names the defect: a card naming a
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
step names. Before each build the pipeline also compares every card's Expected
Result with its final step's expected result, and reports a mismatch as a failed
`Test Card Expected Results` sheet beside the builder's own. The repair call
sees the card in full, and the problem tells it to keep the card's Expected
Result and change the final step's expected result to say the same. A repair
that changes a card's Expected Result is checked against the rules again with
the same verification call; if the card does not follow, the change is undone,
the final step included, and an assumption says so. The card is never removed
at this phase. The two agree when they are equal once case and
punctuation are set aside, or when one holds the other as whole words and the
longer side adds no negation (`no`, `not`, `never`, `cannot`, `without`, `none`,
`nothing`, `n't`) and no condition (`unless`, `until`, `only`, `except`); a
blank on either side is a mismatch. The check lives in the pipeline, not in the
builder, so it runs the same whichever builder is configured. Card design asks
for the same words in both places. The pipeline also checks the pack against
itself on every build, for whichever builder is configured. Four problems fail
the sheet beside the builder's own and go to the repair call: a Covered row with
a blank Gap or Recommendation; a card that cites a rule the Rule-to-Test Matrix
does not list; an Objective Matrix row that lists a card its test sets do not
hold; and a High-risk Not Impacted rule with no regression card and no reason in
its Coverage Matrix gap (text the pipeline wrote because the review gave none
is not a reason). A problem the builder already failed for the same card or rule
is not reported twice. Three more are only written to `detail.log` as a warning
line, because the builder lays those cells out itself and a repair cannot change
them: a Dashboard count that differs from its sheet (the label belongs to the
builder, and only a label that says impacted is read as leaving out Not
Impacted rules), a Rule-to-Test set column that leaves out a set one of its
cards is in, and a confidence level that differs across the Executive Summary,
Dashboard and Confidence Assessment. Before the builder runs, code settles what
it can: the summary's confidence is set to the overall one, and a Covered row
the review left blank reads "Not reviewed; coverage rests on the card mapping"
with the card IDs, and "Confirm in review that the cards exercise this rule."
A High-risk Not Impacted rule is never filled that way. `<validation-sheet>` itself reads PASS WITH
LIMITATIONS when any sheet does. Fix the pack and run it again. A sheet that
cannot be completed gets a `limitations` entry saying why, and validates PASS
WITH LIMITATIONS. The
`<upload-sheet>` test name is the test case ID alone, as `<workbook-standard>`
gives it; the title travels in `<cards-sheet>`.

**Phase 9, Quality Review.** Build the workbook, read it back as text (every
card, step and Expected Result, and the other sheets), and run
`<validation-procedure>` against that text, in parts when it is longer than one
call holds. A workbook read in parts opens each part with an index of the rules
that part shows and the cards that cite them, and each part judges a rule's
coverage from that index. When the builder writes no workbook for the review's
draft, the review reads the pack summary instead and a `warn` status line says so; the
senior review and the confidence calls read that summary too whenever the
workbook needs more than one part. List issues and fixes. A fix names the card or
rule to change and what to change it to; one that is blank, a placeholder such as
N/A, or names no card in the pack is not applied. Each other one goes
through the Phase 8 repair, which may change cards only here: the pack's coverage
rows and limitations stay as they were. The pack is rebuilt, and the checklist
reads the rebuilt workbook again, for at most two rounds. When the rules came
from document text because the rule export held none, checklist item OPS-009 runs
limited for those documents' rules and an assumption names them. Write the
`confidence` fields from the finished workbook, the overall level first and then each
field in a call of its own that sees the fields already written, and the `seniorReview`
and `testerNotes` last, with the confidence assessment in view. A field that repeats
another field's text, or cites a card or rule ID of an ID family the pack uses that the
workbook does not hold, is asked for once more with what was wrong; a second refusal stops
the job with `gate:review-field-unsupported`. Then run `<revalidation-procedure>` over the
rebuilt workbook. Fill `seniorReview`, `testerNotes`, `confidence` and `coverage` before
the final build. `<procedure>` stops on Low confidence at the Project Understanding Gate,
before anything is built. A Low rating here is allowed, but only with a
`limitations` entry for `<confidence-sheet>` saying what holds it down, and
`executiveSummary.confidence` has to match it. If revalidation does not pass,
`revalidation` holds what remains, `<validation-sheet>` reads FAIL with those
items, and the job stops with `gate:revalidation-failed`. Phase 10 and the
final build still run, so the workbook is written with the FAIL for the
reviewer; the report lists the job as failed. The queue does not retry such a
job, because a resume would skip every phase and build the same pack again; fix
the cause and queue it again, without `--resume`.

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

## Comparing a pack with a reference pack

`<pipeline> compare` scores a built pack against a reference pack, the rule
export and the converted document. It needs no job config and no model unless
`--model` is given:

```bash
<pipeline> compare --reference <xlsx> --pack <xlsx> --rules <export> --doc <md> \
  [--out <dir>] [--standard <md>] [--model --config <pipeline-config>]
```

- `--rules` is a rule export (`{ doc, prefix, rules }` or a folder export's
  `{ exports }`) or a Business Rules workbook with the export's nine columns.
- `--doc` is the converted document. Text written `~~like this~~` is read as
  retired; the page anchors place each line.
- `--standard` adds the workbook standard's worksheets and listed columns to
  the format check.
- `--out` is where `compare.json` (the scorecard) and `compare.md` (the report)
  are written. It defaults to the pack's folder, and an earlier `compare.json`
  or `compare.md` there is overwritten.

The report has three parts, and the reference is checked for truth the same way
as the pack:

- **Format**: the sheet inventory and order, the title, subtitle and header
  rows, the header names, the test case ID shape, and the ALM step style
  (step names, where Expected Result and rule references sit). The score is the
  share of the reference's format checks the pack matches.
- **Truth**: each rule row is matched to an approved rule by ID, else by the
  words it shares with the rule's summary, name or quoted text (a Dice share of
  at least 0.4). A row of several statements is also split at commas, semicolons
  and "and", each statement is matched to its best rule, and the row maps to
  every rule a statement picked. A row that says clearly more than another rule
  does is also mapped to that rule when it holds all that rule's less common
  words. A row that matches no rule must match struck-through text
  (a retired rule) or it is not in the source. An approved rule whose quoted
  text sits mostly in struck-through text, and less in live text, counts as
  retired by the document even when the export says active; the pack must
  record each one. A rule row that is not marked retired but uses wording found
  only in struck-through text (a word used more than once there and never in
  live text) is reported as untrue, with the document line; a negation such as
  "no warning" or "without the retired prompt" excuses the words in its own
  clause. Also reported: rule IDs a card cites that no Impact Analysis row,
  matrix or approved rule holds; risk and page that differ from the approved
  rule; and each card's Expected Result against the Expected Result of its last
  ALM step, flagged when one expects the change to go through and the other
  expects it stopped, or when they share almost no words.
- **Floor**: each reference card is matched to the pack cards that test the
  same scenario. A card's scenario is the controls it presses (names found in
  the document and the rules: capitalized terms after "select" or "click", and
  the names listed before "buttons"), the verbs its steps open with (search,
  export, save and the like), the words it uses, what it rules out ("no
  substantiated ... allegation"), and whether it involves another one of the
  same thing. A word counts for more the fewer cards use it, and only words the
  document and rules use count toward a match. Two cards can stand for each
  other unless one rules out something the other runs on, or only one involves
  another one. The rules the two cards cite count as much as the wording: cards
  that cite the same rules and read alike match, and citing different rules
  never lowers a score. A reference card that no compatible pack card shares an
  action with is listed as unmatched, or as a reference error when its own text
  uses retired wording. A card matched by several pack cards is covered when
  they hold, together, at least half of its features; otherwise it is partly
  covered, and the report names the pack cards combined. Pack cards with the
  same actions and the same wording as the first card of a group, or the same
  cited rules as any card in it, are counted as repeats. The report gives the sets and
  cards per set, and whether the Full Coverage set holds every
  requirement-derived card.

Consistency checks that need no source also run on both workbooks: Dashboard
counts against the sheets, the confidence level on the Dashboard, Executive
Summary and Confidence Assessment, matrix rows citing a card the pack lacks or
the row's sets do not hold, and Objective Matrix rows listing a card their set
lacks. A check whose column is missing is reported as not checked, with the
column named, not as zero problems.

With `--model`, which also needs `--config` for the endpoint, the report adds
two questions the word checks cannot settle: whether each card's Expected
Result follows from the rules it cites, and whether an unmatched reference card
is the same scenario as the nearest pack card. Without `--model` the report
says they were not run and no model is called.

**Limits.** The thresholds were set against one reference and pack pair and
have not been checked on others: 0.4 Dice for matching a rule row to a rule,
half of a rule's words in struck text for a retired rule, 0.7 for a clause of a
merged row matching a rule, 0.95 and 0.5 for the extra rules a merged row
covers, 0.3 for a pack card testing a reference card's scenario, 0.7 for two
cards being the same test by wording alone, half of a card's features for
covered rather than partly covered, and 0.1 Dice between an Expected Result and
its last step. Two cards that differ only by one more kind of case (a child with
two allegation types against one) can still be counted as repeats. Treat a
count from the report as a guide to read the lists behind it, not as a grade.

The console prints only counts and the output names. Exit codes: 0 the
comparison was written, 1 it failed while running, 2 bad arguments or an input
that could not be read.

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
