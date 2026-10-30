#!/usr/bin/env node
// Builds test packs on the local model, one job at a time.
//
//   node build-pack.mjs run --config <pipeline.json> --issue <n> [--change <m>] [--doc <path>]... [--resume]
//   node build-pack.mjs run --config <pipeline.json> --suite <code> [--resume]
//   node build-pack.mjs check --config <pipeline.json> --issue <n> [--change <m>] [--doc <path>]... [--allow-derived-rules]
//   node build-pack.mjs queue add --config <pipeline.json> (--issue <n> [--change <m>] [--doc <path>]... [--allow-derived-rules] | --suite <code>) [--resume] [--now]
//   node build-pack.mjs queue remove --config <pipeline.json> --job <id>
//   node build-pack.mjs queue fill --config <pipeline.json>
//   node build-pack.mjs queue check --config <pipeline.json>
//   node build-pack.mjs queue run --config <pipeline.json> [--cutoff HH:MM]
//   node build-pack.mjs queue start --config <pipeline.json> --job <id> [--cutoff HH:MM]
//   node build-pack.mjs queue status --config <pipeline.json> --job <id>
//   node build-pack.mjs queue summary --config <pipeline.json>
//   node build-pack.mjs report --config <pipeline.json> [--period day|week|auto] [--seed <n>]
//   node build-pack.mjs compare --reference <xlsx> --pack <xlsx> --rules <export> --doc <md> [--out <dir>] [--standard <md>] [--model --config <pipeline.json>]
//
// Console output is the content-free status lines only: phase names, pass or
// fail, reason codes, counts and timings. What the model wrote stays in each
// job's output folder.

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { runCompare, UsageError } from './compare.mjs';
import { fill, globFiles, loadConfig, MAX_TRIES } from './config.mjs';
import { modelClient } from './model.mjs';
import { createPauser } from './pause.mjs';
import { documentRules, USABLE_RULE_CODES } from './phases.mjs';
import { seededRandom, writeReports } from './report.mjs';
import { jobId, runJob } from './run.mjs';
import { lineArgs, sourceLines } from './sources.mjs';
import { jobLogs, readStatusLog, statusFields } from './status.mjs';

const USAGE = `usage:
  build-pack.mjs run --config <file> (--issue <n> [--change <m>] [--doc <path>]... [--allow-derived-rules] | --suite <code>) [--resume]
  build-pack.mjs check --config <file> --issue <n> [--change <m>] [--doc <path>]... [--allow-derived-rules]
  build-pack.mjs queue add --config <file> (--issue <n> [--change <m>] [--doc <path>]... [--allow-derived-rules] | --suite <code>) [--resume] [--now]
  build-pack.mjs queue remove --config <file> --job <id>
  build-pack.mjs queue fill --config <file>
  build-pack.mjs queue check --config <file>
  build-pack.mjs queue run --config <file> [--cutoff HH:MM]
  build-pack.mjs queue start --config <file> --job <id> [--cutoff HH:MM]
  build-pack.mjs queue status --config <file> --job <id>
  build-pack.mjs queue summary --config <file>
  build-pack.mjs report --config <file> [--period day|week|auto] [--seed <n>]
  build-pack.mjs compare --reference <xlsx> --pack <xlsx> --rules <export> --doc <md> [--out <dir>] [--standard <md>] [--model --config <file>]
exit codes of check and queue check: 0 every input present, 1 an input missing (or, for queue check, the queue stayed held, a source could not be read, or a check or the pre-check failed), 3 documents not named, so their rules are unchecked
exit codes of compare: 0 the comparison was written, 1 it failed while running, 2 bad arguments or unreadable input`;

export function parseArgs(argv) {
  const args = { docs: [] };
  for (let i = 0; i < argv.length; i += 1) {
    const flag = argv[i];
    const value = argv[i + 1];
    if (!flag.startsWith('--')) {
      (args.words ??= []).push(flag);
      continue;
    }
    // --resume, --now, --allow-derived-rules and --model take no value.
    if (flag === '--resume' || flag === '--now' || flag === '--allow-derived-rules' || flag === '--model') {
      args[flag.slice(2).replace(/-(\w)/g, (_, c) => c.toUpperCase())] = true;
      continue;
    }
    i += 1;
    if (flag === '--doc') args.docs.push(value);
    else args[flag.slice(2).replace(/-(\w)/g, (_, c) => c.toUpperCase())] = value;
  }
  return args;
}

/** The job a command line names, or an error saying what it lacks. */
export function jobFrom(args) {
  if (args.suite && args.issue) throw new Error('a job names an issue or a suite, not both');
  if (args.suite) {
    if (!/^[A-Za-z0-9_-]+$/.test(args.suite)) throw new Error('--suite takes a suite code');
    if (args.allowDerivedRules) throw new Error('--allow-derived-rules does not apply to a suite');
    return { suite: args.suite, ...(args.resume ? { resume: true } : {}) };
  }
  if (!/^\d+$/.test(args.issue ?? '')) throw new Error('--issue takes a number');
  if (args.change !== undefined && !/^[A-Za-z0-9_-]+$/.test(args.change)) {
    throw new Error('--change takes a change number');
  }
  return { issue: args.issue, ...(args.change ? { change: args.change } : {}),
    ...(args.docs.length ? { docs: args.docs } : {}),
    ...(args.descriptionFile ? { descriptionFile: args.descriptionFile } : {}),
    ...(args.allowDerivedRules ? { allowDerivedRules: true } : {}),
    ...(args.resume ? { resume: true } : {}) };
}

/**
 * The input gates for an issue job, with no model call: one line per input,
 * `<input>  present|missing  <code>`, whether every required input is
 * present, and whether the documents' rules went unchecked. Documents are named by number and nothing from a document or a
 * rule reaches the lines; what was wrong with a rule export goes to the
 * check's own detail.log. Without `--doc`, the model chooses the documents at
 * intake, so their rules are not checked here.
 */
export function checkJob(config, job) {
  const lines = [];
  let unchecked = false;
  const add = (input, present, code) => lines.push(
    { input, present, text: `${input}  ${present ? 'present' : 'missing'}  ${code}` });
  add('issue-number', /^\d+$/.test(job.issue ?? ''), 'issue');
  const descriptionFiles = job.descriptionFile ? [config.at(job.descriptionFile)]
    : config.inputs.description ? globFiles(config.root, fill(config.inputs.description, job)) : [];
  const description = descriptionFiles.filter((f) => fs.existsSync(f))
    .map((f) => fs.readFileSync(f, 'utf8')).join('').trim();
  add('description', Boolean(description), description ? 'found' : 'no-description');
  if (job.docs?.length) {
    const logs = jobLogs(path.join(config.output, `${jobId(job)}.check`), { echo: false });
    const ctx = { config, job, logs };
    job.docs.forEach((doc, i) => {
      const file = config.at(doc);
      if (!fs.existsSync(file) || !fs.statSync(file).isFile()) {
        add(`document-${i + 1}`, false, 'document-file');
        return;
      }
      const { code } = documentRules(ctx, file);
      add(`document-${i + 1}`, USABLE_RULE_CODES.includes(code), code);
    });
  } else {
    const candidates = config.inputs.documentIndex
      ? globFiles(config.root, fill(config.inputs.documentIndex, job)) : [];
    add('documents', candidates.length > 0, candidates.length ? `candidates=${candidates.length}` : 'no-candidates');
    if (candidates.length) unchecked = true;
  }
  if (unchecked) lines.push({ input: 'rules', present: true, text: 'rules  unchecked  name-documents-with-doc' });
  return { lines: lines.map((line) => line.text), ok: lines.every((line) => line.present), unchecked };
}

const queuePath = (config) => config.at(config.queue.file);

export function readQueue(config) {
  const file = queuePath(config);
  if (!fs.existsSync(file)) return { jobs: [] };
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

/** Writes a whole file at once, so a reader never sees half of it. */
function writeAtomic(file, text) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  // A temp name per process, so two writers never share one.
  const temp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(temp, text);
  fs.renameSync(temp, file);
}

function writeQueue(config, queue) {
  writeAtomic(queuePath(config), `${JSON.stringify(queue, null, 1)}\n`);
}

export function addJob(config, job, now = new Date()) {
  const queue = readQueue(config);
  const id = jobId(job);
  const open = queue.jobs.find((row) => row.id === id && ['queued', 'running'].includes(row.status));
  if (open) {
    if (open.status === 'running') return { id, added: false, running: true };
    // A request on a row that is waiting for tonight changes what it will run:
    // start-now, resume, derived rules and the named documents ride along.
    const merged = [];
    if (job.now && !open.now) merged.push('now');
    if (job.resume && !open.resume) merged.push('resume');
    if (job.allowDerivedRules && !open.allowDerivedRules) merged.push('allowDerivedRules');
    if (job.docs?.length && JSON.stringify(job.docs) !== JSON.stringify(open.docs)) merged.push('docs');
    for (const field of merged) open[field] = job[field];
    if (merged.length) writeQueue(config, queue);
    if (!merged.length) return { id, added: false, running: false };
    const rest = merged.filter((field) => field !== 'now');
    return { id, added: false, ...(merged.includes('now') ? { marked: true } : {}),
      ...(rest.length ? { merged: rest } : {}) };
  }
  queue.jobs.push({ id, ...job, status: 'queued', added: now.toISOString() });
  writeQueue(config, queue);
  return { id, added: true };
}

/**
 * Takes a waiting job out of the queue. The row stays as `removed`, so a
 * source that still lists the job does not queue it again.
 */
export function removeJob(config, id, now = new Date()) {
  const queue = readQueue(config);
  const row = queue.jobs.findLast((r) => r.id === id && ['queued', 'running'].includes(r.status));
  if (!row) return { id, removed: false, running: false };
  if (row.status === 'running') return { id, removed: false, running: true };
  Object.assign(row, { status: 'removed', finished: now.toISOString() });
  delete row.notBefore;
  writeQueue(config, queue);
  return { id, removed: true };
}

/** The job a source line names, or null for a blank or comment line. */
export function jobFromLine(line) {
  const text = line.trim();
  if (!text || text.startsWith('#')) return null;
  return jobFrom(parseArgs(lineArgs(text)));
}

/**
 * Queues every job the configured sources list that the queue has not seen.
 * A job already in the queue file in any state, queued, passed, failed or
 * removed, is not queued again; `queue add` is how a finished or dropped job
 * is run once more. A source that cannot be read, or a line that is not a
 * job, is counted and skipped so the other sources still fill the queue.
 */
export function fillQueue(config, now = new Date()) {
  const { jobs, ...result } = sourceJobs(config);
  for (const job of jobs) addJob(config, job, now);
  return { added: jobs.map(jobId), ...result };
}

/**
 * The jobs the configured sources list that the queue has not seen, without
 * queueing them, with the counts `fillQueue` reports.
 */
export function sourceJobs(config) {
  const seen = new Set(readQueue(config).jobs.map((row) => row.id));
  const result = { jobs: [], known: 0, invalid: 0, errors: [] };
  for (const source of config.queue.sources) {
    const { lines, error, invalid = 0 } = sourceLines(config, source);
    result.invalid += invalid;
    if (error) result.errors.push(`${source.type}:${error}`);
    for (const line of lines) {
      let job;
      try {
        job = jobFromLine(line);
      } catch {
        result.invalid += 1;
        continue;
      }
      if (!job) continue;
      const id = jobId(job);
      if (seen.has(id)) {
        result.known += 1;
        continue;
      }
      seen.add(id);
      result.jobs.push(job);
    }
  }
  return result;
}

/** The first moment at or after `from` whose clock reads HH:MM. */
export function cutoffAfter(from, hhmm) {
  const time = /^([01]?\d|2[0-3]):([0-5]\d)$/.exec(String(hhmm));
  if (!time) throw new Error('a queue time reads HH:MM');
  const [h, m] = [Number(time[1]), Number(time[2])];
  const at = new Date(from);
  at.setHours(h, m, 0, 0);
  if (at <= from) at.setDate(at.getDate() + 1);
  return at;
}

const lockPath = (config) => `${queuePath(config)}.lock`;

/** A process's start time in clock ticks since boot (Linux), or null where /proc has none. */
function processStart(pid) {
  try {
    const stat = fs.readFileSync(`/proc/${pid}/stat`, 'utf8');
    // The command name in field 2 may hold spaces, so count from the last ")".
    return stat.slice(stat.lastIndexOf(')') + 2).split(' ')[19] ?? null;
  } catch {
    return null;
  }
}

/** What a lock file holds: the holder's PID and, where known, its start time. */
const lockText = () => [process.pid, processStart(process.pid)].filter(Boolean).join(' ');

/**
 * True when the lock text names a live process. An empty or malformed file
 * names none. A PID alone proves little once PIDs are reused, so the start
 * time is compared when the file carries one.
 */
function holderAlive(text) {
  const [pid, start] = text.trim().split(/\s+/);
  if (!/^[1-9]\d*$/.test(pid ?? '')) return false;
  try {
    process.kill(Number(pid), 0);
  } catch {
    return false;
  }
  return !start || processStart(pid) === start;
}

function readLock(lock) {
  try {
    return fs.readFileSync(lock, 'utf8');
  } catch {
    return null;
  }
}

/** True when a live process holds the queue. */
export function lockHeld(config) {
  const text = readLock(lockPath(config));
  return text !== null && holderAlive(text);
}

/**
 * Removes a lock file that was judged stale from `seen`. The file is renamed
 * away first, so two starters cannot both remove it; if what was renamed is
 * not what was judged, it is put back and the lock stays someone else's.
 */
export function claimStale(lock, seen) {
  const claimed = `${lock}.stale-${process.pid}-${Date.now()}`;
  try {
    fs.renameSync(lock, claimed);
  } catch {
    // Another starter removed it first.
    return true;
  }
  if (fs.readFileSync(claimed, 'utf8') === seen) {
    fs.rmSync(claimed, { force: true });
    return true;
  }
  try {
    fs.linkSync(claimed, lock);
  } catch {
    // A newer lock already stands in its place.
  }
  fs.rmSync(claimed, { force: true });
  return false;
}

/** Holds the queue for this process, or returns null when a live process holds it. */
function lockQueue(config) {
  const lock = lockPath(config);
  fs.mkdirSync(path.dirname(lock), { recursive: true });
  const text = lockText();
  // A lock that vanishes between the failed create and the read was just
  // released, so that pass is retried; the bound only stops a runaway loop.
  for (let tries = 0; tries < 5; tries += 1) {
    // The text is written before the file appears under the lock's name, so no
    // other starter reads an empty lock.
    const temp = `${lock}.${process.pid}.tmp`;
    fs.writeFileSync(temp, text);
    try {
      fs.linkSync(temp, lock);
      // Only this process's own lock is removed; if the file was replaced,
      // it belongs to another holder.
      return () => {
        if (readLock(lock) === text) fs.rmSync(lock, { force: true });
      };
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
    } finally {
      fs.rmSync(temp, { force: true });
    }
    const seen = readLock(lock);
    if (seen === null) continue;
    if (holderAlive(seen) || !claimStale(lock, seen)) return null;
  }
  return null;
}

/**
 * Works the queue one job at a time, oldest first, until it is empty or the
 * cutoff passes. A job already running when the cutoff passes finishes. A
 * failed job goes back to waiting, with its phase and reason kept, and the next
 * one starts; a run does not take a job again that failed in it.
 *
 * With `start` set, the queue runs only in the window from start to cutoff: a
 * run that begins outside it, such as a timer catching up after the machine
 * slept through the night, takes no job. A job left running by a run that
 * died counts as a failed try, `interrupted`, and has no wait; a run that works
 * every queued row takes it again at once, while one that works only `now`
 * rows leaves it for the night, since the failed try cleared its mark.
 *
 * With `only` set to a job ID, the run takes that job's queued row first; with
 * no queued row of that ID it takes nothing. With `nowOnly` set, the jobs after
 * it are only rows marked `now`, those a user asked to start in the daytime,
 * and a row waiting for the nightly run stays queued. When a live process
 * holds the queue, a run first waits `settleMs` and tries once more, so a
 * holder that is finishing is not mistaken for a long one. Then, with `wait`
 * set, the run polls every `pollMs` until it gets the queue or the cutoff
 * passes, so a nightly run behind a daytime job still works the night's rows.
 * Without `wait`, `onBusy` is called and the row stays queued. A holder that
 * works every row takes it when it is due and has not failed in that run; a
 * holder that works only `now` rows takes it only if it is marked `now`.
 *
 * A job that fails during the night is queued again for the next nightly run,
 * and one that fails in the daytime for tonight's, resumed from the phase that
 * stopped it either way; one that has failed MAX_TRIES times stays failed and
 * is not taken again. With `refill` set, it is called once the queue is held and
 * before the first job is taken, to add the jobs the configured sources list.
 */
export async function drainQueue(config, { cutoff = config.queue.cutoff, start = null,
  only = null, nowOnly = false, wait = false, onBusy = () => {}, run = runJob, refill = null,
  clock = () => new Date(), sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  settleMs = 2000, pollMs = 30000, pause = (cfg) => createPauser(cfg) } = {}) {
  const stopAt = cutoffAfter(clock(), cutoff);
  if (start && cutoffAfter(clock(), start) < stopAt) return [];
  let unlock = lockQueue(config);
  if (!unlock) {
    await sleep(settleMs);
    unlock = lockQueue(config);
  }
  while (!unlock && wait && clock() < stopAt) {
    await sleep(pollMs);
    unlock = lockQueue(config);
  }
  if (!unlock) {
    onBusy();
    return [];
  }
  try {
    const stale = readQueue(config);
    const interrupted = stale.jobs.filter((row) => row.status === 'running');
    for (const row of interrupted) {
      settleRow(row, { ok: false, phase: 'unknown', reason: 'interrupted', ms: 0 }, clock(), config);
    }
    if (interrupted.length) writeQueue(config, stale);
    if (refill) refill(config);
    return await drainLocked(config, { stopAt, only, nowOnly, run, clock, pause });
  } finally {
    unlock();
  }
}

async function drainLocked(config, { pause, ...rest }) {
  // Made now so units a dead holder left stopped are found and restored even
  // when no job runs; nothing is stopped until a job is about to start.
  const pauser = pause(config);
  try {
    return await drainJobs(config, { ...rest, pauser });
  } finally {
    await pauser.resume();
  }
}

/** True when `at` falls in the nightly window, from the configured start to the cutoff. */
function inNightWindow(config, at) {
  return cutoffAfter(at, config.queue.start) > cutoffAfter(at, config.queue.cutoff);
}

// What a finished attempt does to its row. A first failure puts the job back in
// the queue to resume. One that failed during the night waits until that
// night's cutoff has passed, so only the next nightly run takes it; one that
// failed in the daytime is taken by tonight's run. A row found running after
// its run died has no wait; a run that works every queued row takes it at once,
// and one that works only `now` rows leaves it for the night.
function settleRow(row, result, at, config) {
  const failures = [...(row.failures ?? [])];
  if (!result.ok) {
    failures.push({ at: at.toISOString(), phase: result.phase ?? 'unknown',
      reason: result.reason ?? 'error', ms: result.ms ?? 0 });
  }
  for (const field of ['started', 'now', 'finished', 'ms', 'phase', 'reason', 'workbook', 'outDir',
    'notBefore']) delete row[field];
  // A failed revalidation is the review's verdict on the finished pack; a resume would skip
  // every phase and build the same pack again, so the job is not retried.
  const retry = result.reason !== 'gate:revalidation-failed';
  if (!result.ok && retry && failures.length < MAX_TRIES) {
    const wait = result.reason !== 'interrupted' && inNightWindow(config, at);
    Object.assign(row, { status: 'queued', resume: true, failures,
      ...(wait ? { notBefore: cutoffAfter(at, config.queue.cutoff).toISOString() } : {}) });
    return;
  }
  Object.assign(row, {
    status: result.ok ? 'passed' : 'failed', finished: at.toISOString(),
    ms: result.ms, phase: result.ok ? 'done' : result.phase, reason: result.reason ?? null,
    workbook: result.workbook ?? null, outDir: result.outDir ?? null,
    ...(failures.length ? { failures } : {}),
  });
}

async function drainJobs(config, { stopAt, only, nowOnly, run, clock, pauser }) {
  const done = [];
  let first = only;
  let paused = false;
  // A job that failed in this run waits for a later one.
  const tried = new Set();
  for (;;) {
    if (clock() >= stopAt) break;
    const queue = readQueue(config);
    // A request to start a job now, by its ID or with --now, ignores the wait for the next nightly run.
    const next = queue.jobs.find((row) => row.status === 'queued' && !tried.has(row.id)
      && (!row.notBefore || clock() >= new Date(row.notBefore)
        || row.id === first || (nowOnly && row.now))
      && (first ? row.id === first : !nowOnly || row.now));
    if (!next) break;
    first = null;
    if (!paused) {
      paused = true;
      await pauser.pause();
    }
    // Stopping the units can take minutes, so the row is claimed in a fresh read of the
    // queue file, which keeps a job added in the meantime.
    const fresh = readQueue(config);
    const claimed = fresh.jobs.find((row) => row.id === next.id && row.status === 'queued');
    if (!claimed) continue;
    claimed.status = 'running';
    claimed.started = clock().toISOString();
    writeQueue(config, fresh);
    const { id, status, added, started, now: _now, failures, notBefore, ...job } = claimed;
    let result;
    try {
      result = await run(config, { ...job, id });
    } catch (error) {
      result = { ok: false, phase: 'setup', reason: 'error', ms: 0 };
    }
    const after = readQueue(config);
    let row = after.jobs.find((r) => r.id === id && r.status === 'running');
    if (!row) {
      // The queue file was replaced while the job ran and no longer holds its running row.
      row = { id, ...job, added, started, ...(failures ? { failures } : {}) };
      after.jobs.push(row);
    }
    settleRow(row, result, clock(), config);
    tried.add(id);
    writeQueue(config, after);
    done.push(row);
  }
  return done;
}

/** The morning summary: one content-free line per job. */
export function summaryLines(queue) {
  return queue.jobs.filter((row) => row.status !== 'removed').map((row) => {
    const minutes = row.ms ? `${Math.round(row.ms / 60000)} min` : '';
    const last = row.failures?.at(-1);
    const where = row.status === 'failed' ? `stopped at ${row.phase} (${row.reason})`
      + (row.failures?.length >= MAX_TRIES ? `, dropped after failing ${MAX_TRIES} times` : '')
      : row.status === 'passed' ? row.workbook ?? ''
        : row.status === 'queued' && last ? `retry after stopping at ${last.phase} (${last.reason})` : '';
    return [row.id, row.status, minutes, where].filter(Boolean).join('  ');
  });
}

/**
 * One job's state in content-free fields: its row's status, the last status
 * line its run wrote, and whether a live process holds the queue.
 */
export function jobStatus(config, id) {
  const row = readQueue(config).jobs.findLast((r) => r.id === id);
  const lines = [`${id}  ${row ? row.status : 'not queued'}  queue ${lockHeld(config) ? 'held' : 'free'}`];
  const log = path.join(config.output, id, 'status.log');
  if (row?.started && fs.existsSync(log)) {
    // A line cut off mid-write does not parse and is skipped. A resumed job
    // appends to its earlier log, so only a line written since this row
    // started belongs to this attempt.
    const entries = readStatusLog(log);
    const last = entries.at(-1);
    if (last && new Date(last.at) >= new Date(row.started)) {
      // statusFields refuses any value that is not a short code, so a line that
      // carried text throws here instead of reaching the console.
      const { at, ...fields } = statusFields(last);
      lines.push(Object.entries(fields).map(([k, v]) => `${k}=${v}`).join(' '));
    }
  }
  return lines;
}

/**
 * The queue's pre-check, which changes nothing in the queue. It runs the input
 * gates of `check`, with no model call, on every waiting row and on every job
 * the sources would queue tonight, and returns content-free lines, each
 * starting with a job ID, and an exit code like `check`'s: 1 when the queue
 * stayed held, a source could not be read, an input is missing or a check or
 * the pre-check itself failed, 3 when some rows'
 * rules went unchecked, else 0, and `at`, when the queue was read. The sources are read, not filled, so a line
 * fixed after the check still counts at the nightly fill.
 *
 * It holds no lock. While a run holds the queue it waits, polling every
 * `pollMs` up to `waitMs`, and then skips. With the queue free, a row still marked running was left by a run that died; the
 * nightly run settles it and runs it again, so it is checked too, unless that
 * was its last try and the settle drops it. A run that takes the queue
 * stops the check before its next row; a rule export already going finishes
 * first. A suite row
 * is refused, since `check` takes issue jobs only.
 */
export async function precheckQueue(config, { clock = () => new Date(),
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  waitMs = 60 * 60000, pollMs = 30000 } = {}) {
  const giveUp = clock().getTime() + waitMs;
  while (lockHeld(config)) {
    if (clock().getTime() >= giveUp) return { lines: ['queue  held  precheck-skipped'], code: 1, at: clock() };
    await sleep(pollMs);
  }
  const lines = [];
  const at = clock();
  let missing = false;
  let unchecked = false;
  try {
    const rows = readQueue(config).jobs.filter((row) => ['queued', 'running'].includes(row.status));
    const { jobs, ...fill } = sourceJobs(config);
    lines.push(`sources  ${fillSummary({ added: jobs, ...fill }, 'would queue')}`);
    // A source that cannot be read leaves its jobs out of tonight's queue.
    missing = fill.errors.length > 0;
    for (const job of [...rows, ...jobs]) {
      if (lockHeld(config)) {
        lines.push('queue  held  precheck-stopped');
        missing = true;
        break;
      }
      const id = jobId(job);
      if (job.status === 'running') {
        // Settling counts the interrupted try; on its last try the row is dropped, not run.
        if ((job.failures?.length ?? 0) + 1 >= MAX_TRIES) {
          lines.push(`${id}  running  stale-row-dropped`);
          continue;
        }
        lines.push(`${id}  running  stale-row`);
      }
      if (job.suite) {
        lines.push(`${id}  suite  refused`);
        continue;
      }
      let checked;
      try {
        checked = checkJob(config, job);
      } catch (error) {
        // The error's name only: a message could carry a path or a document's text.
        checked = { lines: [`check  failed  ${error.name}`], ok: false, unchecked: false };
      }
      for (const line of checked.lines) lines.push(`${id}  ${line}`);
      missing ||= !checked.ok;
      unchecked ||= checked.unchecked;
    }
  } catch (error) {
    // A queue file that does not parse, say: the lines so far stand.
    lines.push(`precheck  failed  ${error.name}`);
    missing = true;
  }
  return { lines, code: missing ? 1 : unchecked ? 3 : 0, at };
}

/** Where the pre-check writes its lines: the output folder, beside the job folders. */
export const precheckPath = (config) => path.join(config.output, 'precheck.txt');

/** A local clock reading, `YYYY-MM-DD HH:MM`, the time the timers are set in. */
export function localStamp(at) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())} `
    + `${pad(at.getHours())}:${pad(at.getMinutes())}`;
}

async function main(argv) {
  const args = parseArgs(argv);
  const [command, sub] = args.words ?? [];
  if (command === 'compare') return compareCommand(args);
  if (!args.config || !command) {
    console.error(USAGE);
    return 2;
  }
  const config = loadConfig(args.config);
  // While units are stopped, a signal starts them again before the process exits.
  const pausers = [];
  const track = (cfg, deps) => {
    const pauser = createPauser(cfg, deps);
    pausers.push(pauser);
    return pauser;
  };
  const onSignal = (name) => {
    Promise.all(pausers.map((p) => p.resume()))
      .finally(() => process.exit(128 + os.constants.signals[name]));
  };
  const handlers = ['SIGTERM', 'SIGINT', 'SIGHUP'].map((name) => [name, () => onSignal(name)]);
  for (const [name, handler] of handlers) process.on(name, handler);
  try {
    return await dispatch(args, command, sub, config, track);
  } finally {
    for (const [name, handler] of handlers) process.off(name, handler);
  }
}

/** Runs `fn` while this process holds the queue; null when a live process holds it. */
function withQueue(config, fn) {
  const unlock = lockQueue(config);
  if (!unlock) return null;
  try {
    return { value: fn() };
  } finally {
    unlock();
  }
}

function busyQueue() {
  console.error('the queue is running; try again when the run ends');
  return 1;
}

/** The fill's outcome in content-free counts and codes. */
function printFill(result) {
  for (const id of result.added) console.log(`queued ${id}`);
  console.log(fillSummary(result));
}

function fillSummary({ added, known, invalid, errors }, verb = 'filled') {
  return `${verb} ${added.length} job(s), ${known} already known, ${invalid} unreadable line(s)`
    + (errors.length ? `, source problems: ${errors.join(' ')}` : '');
}

/** The compare command: needs no job config unless --model asks for the endpoint. */
async function compareCommand(args) {
  try {
    const lines = await runCompare(args, {
      makeClient: (configPath) => {
        try {
          return modelClient(loadConfig(configPath).model);
        } catch {
          throw new UsageError('--config could not be read');
        }
      },
    });
    for (const line of lines) console.log(line);
    return 0;
  } catch (error) {
    if (error instanceof UsageError) throw error;
    // A failure while comparing is not a bad argument; the message names no content.
    console.error(`compare failed (${error.name})`);
    return 1;
  }
}

async function dispatch(args, command, sub, config, track) {
  const pause = (cfg) => track(cfg);
  if (command === 'run') {
    // No queue lock is held here, so this run leaves another holder's stopped units alone.
    const pauser = track(config, { leftover: false });
    try {
      await pauser.pause();
      const result = await runJob(config, jobFrom(args));
      return result.ok ? 0 : 1;
    } finally {
      await pauser.resume();
    }
  }
  if (command === 'check') {
    const job = jobFrom(args);
    if (job.suite) throw new Error('check takes an issue job');
    const { lines, ok, unchecked } = checkJob(config, job);
    for (const line of lines) console.log(line);
    return !ok ? 1 : unchecked ? 3 : 0;
  }
  if (command === 'queue' && sub === 'add') {
    const { id, added, marked, merged, running } = addJob(config,
      { ...jobFrom(args), ...(args.now ? { now: true } : {}) });
    if (added) console.log(`queued ${id}`);
    else if (marked || merged?.length) {
      if (marked) console.log(`${id} is marked to start now`);
      if (merged?.length) console.log(`${id} is already queued; updated ${merged.join(', ')}`);
    } else console.log(running ? `${id} is already running` : `${id} is already queued`);
    return 0;
  }
  if (command === 'queue' && sub === 'remove') {
    if (!args.job) throw new Error('--job takes a job ID');
    const held = withQueue(config, () => removeJob(config, args.job));
    if (!held) return busyQueue();
    const { removed, running } = held.value;
    console.log(removed ? `removed ${args.job}` : running ? `${args.job} is marked running; it cannot be removed`
      : `${args.job} is not waiting in the queue`);
    return removed ? 0 : 1;
  }
  if (command === 'queue' && sub === 'fill') {
    const held = withQueue(config, () => fillQueue(config));
    if (!held) return busyQueue();
    printFill(held.value);
    return 0;
  }
  if (command === 'queue' && sub === 'check') {
    // The file reads `running` until the check ends, so a check stopped part
    // way, by the unit's timeout say, does not leave yesterday's lines standing.
    const write = (at, lines) => writeAtomic(precheckPath(config),
      `${[`checked ${localStamp(at)}`, ...lines].join('\n')}\n`);
    write(new Date(), ['precheck  running']);
    const { lines, code, at } = await precheckQueue(config);
    for (const line of lines) console.log(line);
    write(at, lines);
    return code;
  }
  if (command === 'queue' && sub === 'run') {
    const fillFirst = (cfg) => printFill(fillQueue(cfg));
    // A cutoff given on the command line is a deliberate run, outside the nightly window.
    const done = await drainQueue(config, args.cutoff
      ? { cutoff: args.cutoff, wait: true, pause, refill: fillFirst }
      : { cutoff: config.queue.cutoff, start: config.queue.start, wait: true, pause,
        refill: fillFirst });
    console.log(`ran ${done.length} job(s)`);
    for (const line of summaryLines(readQueue(config))) console.log(line);
    return 0;
  }
  if (command === 'queue' && sub === 'start') {
    if (!args.job) throw new Error('--job takes a job ID');
    let busy = false;
    // The cutoff is the configured one unless the command line gives another;
    // the nightly window does not apply to a job started on request.
    const done = await drainQueue(config, { cutoff: args.cutoff ?? config.queue.cutoff,
      only: args.job, nowOnly: true, pause, onBusy: () => { busy = true; } });
    if (busy) {
      const row = readQueue(config).jobs.findLast((r) => r.id === args.job);
      console.log(row?.status === 'running' ? `${args.job} is already running`
        : `the queue is running; ${args.job} stays queued. A run that works every row takes it `
          + 'when it is due; one that works only start-now rows takes it only if it is marked now');
    } else {
      console.log(`ran ${done.length} job(s)`);
    }
    for (const line of jobStatus(config, args.job)) console.log(line);
    return 0;
  }
  if (command === 'queue' && sub === 'status') {
    if (!args.job) throw new Error('--job takes a job ID');
    for (const line of jobStatus(config, args.job)) console.log(line);
    return 0;
  }
  if (command === 'queue' && sub === 'summary') {
    for (const line of summaryLines(readQueue(config))) console.log(line);
    return 0;
  }
  if (command === 'report') {
    const seed = args.seed ?? config.report.seed;
    const random = seed === undefined ? Math.random : seededRandom(seed);
    for (const { period, file, counts, queue } of writeReports(config, readQueue(config),
      { period: args.period, random })) {
      console.log(`wrote ${period} report ${file}`);
      console.log(`passed=${counts.pass} retrying=${counts.retry} dropped=${counts.dropped} `
        + `queued=${queue.depth}`);
    }
    return 0;
  }
  console.error(USAGE);
  return 2;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  main(process.argv.slice(2)).then((code) => { process.exitCode = code; }, (error) => {
    // A setup error names the config field at fault, never document content.
    console.error(error.message);
    process.exitCode = 2;
  });
}
