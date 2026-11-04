// Runs a slice of a finished or stopped job in a sandbox, so a change to one
// phase is tried against a real job's state without a full run. The sandbox is
// a copy of the job's folder under the ID `<job>~<label>`; the job's own
// folder, queue row and workbook are only read.

import fs from 'node:fs';
import path from 'node:path';
import { PHASES, readCheckpoint, readSnapshot, snapshotPath } from './run.mjs';

/** What a sandbox label may hold; it ends up in a folder name and in status lines. */
const LABEL = /^[A-Za-z0-9_-]+$/;

/** The queue row's fields that name a job's documents and options, as `jobFrom` makes them. */
const PARAMETERS = ['issue', 'change', 'suite', 'docs', 'descriptionFile', 'allowDerivedRules'];

/** The sandbox ID for a job: its label, or the time as `YYYYMMDDTHHMMSS`. */
export function sandboxId(source, label, at) {
  if (label !== undefined && !LABEL.test(label)) throw new Error('--as takes letters, digits, "_" and "-"');
  const stamp = at.toISOString().replace(/[-:]/g, '').replace(/\..*$/, '');
  return `${source}~${label ?? stamp}`;
}

/** The phases a slice runs, checked against the pipeline's phase list. */
export function sliceRange({ from, until = from }) {
  for (const [flag, name] of [['--from', from], ['--until', until]]) {
    if (!PHASES.includes(name)) throw new Error(`${flag} takes one of: ${PHASES.join(', ')}`);
  }
  if (PHASES.indexOf(from) > PHASES.indexOf(until)) throw new Error('--from comes after --until');
  return { from, until };
}

/**
 * The job fields a slice runs with: the source job's queue row when it has one,
 * else the ones its ID gives. A sandbox's ID starts with the ID of the job it
 * came from, so a slice of a sandbox finds the same row. Phases after intake
 * read the documents from the checkpoint, so the ID is enough for them.
 */
export function jobParameters(rows, sourceId) {
  const base = sourceId.split('~')[0];
  const row = rows.findLast((r) => r.id === base);
  if (row) return Object.fromEntries(PARAMETERS.filter((key) => row[key] !== undefined).map((key) => [key, row[key]]));
  const issue = /^issue-(\d+)(?:-change-([A-Za-z0-9_-]+))?$/.exec(base);
  if (issue) return { issue: issue[1], ...(issue[2] ? { change: issue[2] } : {}) };
  const suite = /^suite-([A-Za-z0-9_-]+)$/.exec(base);
  if (suite) return { suite: suite[1] };
  throw new Error(`${sourceId} is not a job ID`);
}

/**
 * Copies the source job's folder to the sandbox and points the sandbox's
 * checkpoint at the snapshot of the phase before `from`, so a run with
 * `resume` starts at `from`. The pack and workbook the source built are not
 * copied: the slice builds neither. Snapshots from `from` on are left behind,
 * so none of them stands in for a phase the sandbox has not run. A slice from
 * intake starts over and needs no snapshot. Throws, with nothing written, when
 * the source has no folder, the sandbox exists, or the snapshot is missing.
 */
export function prepareSandbox(config, sourceId, sandboxName, from) {
  const source = path.join(config.output, sourceId);
  const sandbox = path.join(config.output, sandboxName);
  if (!fs.existsSync(source)) throw new Error(`${sourceId} has no output folder`);
  if (fs.existsSync(sandbox)) throw new Error(`${sandboxName} already exists; give another --as label`);
  if (from === 'intake') return false;
  const before = PHASES[PHASES.indexOf(from) - 1];
  if (!readSnapshot(source, before)) {
    throw new Error(`${sourceId} has no snapshot for ${before} (work/checkpoints/${before}.json); `
      + `run the job through ${before} first`);
  }
  const later = new Set(PHASES.slice(PHASES.indexOf(from)).map((name) => snapshotPath(source, name)));
  const skipped = new Set([path.join(source, 'work', 'checkpoint.json'),
    path.join(source, 'work', 'partial-pack.json')]);
  const keptLogs = new Set(['status.log', 'detail.log']);
  fs.cpSync(source, sandbox, {
    recursive: true,
    filter: (file) => {
      if (later.has(file) || skipped.has(file)) return false;
      // A file in the job's folder itself, other than its logs, is a pack or a workbook.
      return path.dirname(file) !== source || fs.statSync(file).isDirectory() || keptLogs.has(path.basename(file));
    },
  });
  const checkpoint = path.join(sandbox, 'work', 'checkpoint.json');
  fs.copyFileSync(snapshotPath(source, before), `${checkpoint}.tmp`);
  fs.renameSync(`${checkpoint}.tmp`, checkpoint);
  // A snapshot the resume would read as an earlier phase would run more than was asked.
  if (readCheckpoint(sandbox)?.phase !== before) {
    fs.rmSync(sandbox, { recursive: true, force: true });
    throw new Error(`the ${before} snapshot of ${sourceId} cannot be resumed from; run the job through ${before} again`);
  }
  return true;
}

/** What a snapshot says about the pack: card IDs, coverage by status, confidence and open revalidation items. */
function packFacts(dir, phase) {
  const saved = readSnapshot(dir, phase);
  if (!saved) return null;
  const pack = saved.pack ?? saved.state?.pack ?? {};
  const coverage = {};
  for (const row of pack.coverage ?? []) coverage[row.status] = (coverage[row.status] ?? 0) + 1;
  return { cards: (pack.testCards ?? []).map((card) => card.id), coverage,
    confidence: pack.confidence?.overall ?? 'unrated', open: pack.revalidation?.remaining ?? [] };
}

/**
 * How the sandbox's pack at `phase` differs from the source job's. `lines` are
 * counts and codes only, for the console; `detail` adds the card IDs and the
 * open items, for the sandbox's detail.log.
 */
export function compareSnapshots(sourceDir, sandboxDir, phase) {
  const was = packFacts(sourceDir, phase);
  const now = packFacts(sandboxDir, phase);
  if (!now) return { lines: [`sandbox has no snapshot at ${phase}; nothing to compare`], detail: null };
  if (!was) return { lines: [`source has no snapshot at ${phase}; nothing to compare`], detail: null };
  const added = now.cards.filter((id) => !was.cards.includes(id));
  const removed = was.cards.filter((id) => !now.cards.includes(id));
  const statuses = [...new Set([...Object.keys(was.coverage), ...Object.keys(now.coverage)])];
  const changed = statuses.filter((status) => (was.coverage[status] ?? 0) !== (now.coverage[status] ?? 0));
  const lines = [
    `cards  source ${was.cards.length}  sandbox ${now.cards.length}  added ${added.length}  removed ${removed.length}`,
    `coverage  ${changed.length ? changed.map((status) => `${status} ${was.coverage[status] ?? 0} -> ${now.coverage[status] ?? 0}`).join('  ') : 'unchanged'}`,
    `confidence  ${was.confidence === now.confidence ? `unchanged ${now.confidence}` : `${was.confidence} -> ${now.confidence}`}`,
    `revalidation  open ${was.open.length} -> ${now.open.length}`,
  ];
  return { lines, detail: { phase, cardsAdded: added, cardsRemoved: removed, openBefore: was.open, openAfter: now.open } };
}

/**
 * The state of a sandbox job that has no queue row, read from its status log:
 * the lines since the slice began, and a row shaped as the queue's rows are.
 * The log starts with the source's lines, so a slice's own start is the last
 * `begin` or `resume` line; a slice from intake wrote a log of its own. Null
 * when the log holds no line of the slice.
 */
export function sandboxRun(entries) {
  const from = entries.findLastIndex((entry) => ['begin', 'resume'].includes(entry.event) && entry.phase !== 'release');
  const own = from >= 0 ? entries.slice(from) : entries;
  const mine = own.filter((entry) => entry.phase !== 'release');
  const last = mine.at(-1);
  if (!last) return null;
  const stopped = last.event === 'fail';
  const status = last.event === 'slice' ? 'passed' : !stopped ? 'running' : last.reason === 'cancelled' ? 'stopped' : 'failed';
  return { entries: own, row: { status, started: mine[0].at,
    ...(status === 'running' ? {} : { finished: last.at }),
    ...(stopped ? { phase: last.phase, reason: last.reason } : {}) } };
}
