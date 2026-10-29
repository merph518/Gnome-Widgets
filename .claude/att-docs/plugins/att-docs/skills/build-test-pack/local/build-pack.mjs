#!/usr/bin/env node
// Builds test packs on the local model, one job at a time.
//
//   node build-pack.mjs run --config <pipeline.json> --issue <n> [--change <m>] [--doc <path>]... [--resume]
//   node build-pack.mjs run --config <pipeline.json> --suite <code> [--resume]
//   node build-pack.mjs queue add --config <pipeline.json> (--issue <n> [--change <m>] | --suite <code>) [--resume] [--now]
//   node build-pack.mjs queue run --config <pipeline.json> [--cutoff HH:MM]
//   node build-pack.mjs queue start --config <pipeline.json> --job <id> [--cutoff HH:MM]
//   node build-pack.mjs queue status --config <pipeline.json> --job <id>
//   node build-pack.mjs queue summary --config <pipeline.json>
//
// Console output is the content-free status lines only: phase names, pass or
// fail, reason codes, counts and timings. What the model wrote stays in each
// job's output folder.

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadConfig } from './config.mjs';
import { createPauser } from './pause.mjs';
import { jobId, runJob } from './run.mjs';
import { statusFields } from './status.mjs';

const USAGE = `usage:
  build-pack.mjs run --config <file> (--issue <n> [--change <m>] [--doc <path>]... | --suite <code>) [--resume]
  build-pack.mjs queue add --config <file> (--issue <n> [--change <m>] [--doc <path>]... | --suite <code>) [--resume] [--now]
  build-pack.mjs queue run --config <file> [--cutoff HH:MM]
  build-pack.mjs queue start --config <file> --job <id> [--cutoff HH:MM]
  build-pack.mjs queue status --config <file> --job <id>
  build-pack.mjs queue summary --config <file>`;

export function parseArgs(argv) {
  const args = { docs: [] };
  for (let i = 0; i < argv.length; i += 1) {
    const flag = argv[i];
    const value = argv[i + 1];
    if (!flag.startsWith('--')) {
      (args.words ??= []).push(flag);
      continue;
    }
    // --resume and --now take no value.
    if (flag === '--resume' || flag === '--now') {
      args[flag.slice(2)] = true;
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
    return { suite: args.suite, ...(args.resume ? { resume: true } : {}) };
  }
  if (!/^\d+$/.test(args.issue ?? '')) throw new Error('--issue takes a number');
  if (args.change !== undefined && !/^[A-Za-z0-9_-]+$/.test(args.change)) {
    throw new Error('--change takes a change number');
  }
  return { issue: args.issue, ...(args.change ? { change: args.change } : {}),
    ...(args.docs.length ? { docs: args.docs } : {}),
    ...(args.descriptionFile ? { descriptionFile: args.descriptionFile } : {}),
    ...(args.resume ? { resume: true } : {}) };
}

const queuePath = (config) => config.at(config.queue.file);

export function readQueue(config) {
  const file = queuePath(config);
  if (!fs.existsSync(file)) return { jobs: [] };
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

function writeQueue(config, queue) {
  const file = queuePath(config);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const temp = `${file}.tmp`;
  fs.writeFileSync(temp, `${JSON.stringify(queue, null, 1)}\n`);
  fs.renameSync(temp, file);
}

export function addJob(config, job, now = new Date()) {
  const queue = readQueue(config);
  const id = jobId(job);
  const open = queue.jobs.find((row) => row.id === id && ['queued', 'running'].includes(row.status));
  if (open) {
    // A request to start now marks a row that is waiting for tonight, and a
    // resume asked for with it rides along.
    if (job.now && open.status === 'queued' && !open.now) {
      Object.assign(open, { now: true }, job.resume ? { resume: true } : {});
      writeQueue(config, queue);
      return { id, added: false, marked: true };
    }
    return { id, added: false, running: open.status === 'running' };
  }
  queue.jobs.push({ id, ...job, status: 'queued', added: now.toISOString() });
  writeQueue(config, queue);
  return { id, added: true };
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
 * failed job is marked failed with its phase, and the next one starts.
 *
 * With `start` set, the queue runs only in the window from start to cutoff: a
 * run that begins outside it, such as a timer catching up after the machine
 * slept through the night, takes no job. A job left running by a run that
 * died is marked failed as interrupted.
 *
 * With `only` set to a job ID, the run takes that job's queued row first; with
 * no queued row of that ID it takes nothing. With `nowOnly` set, the jobs after
 * it are only rows marked `now`, those a user asked to start in the daytime,
 * and a row waiting for the nightly run stays queued. When a live process
 * holds the queue, a run first waits `settleMs` and tries once more, so a
 * holder that is finishing is not mistaken for a long one. Then, with `wait`
 * set, the run polls every `pollMs` until it gets the queue or the cutoff
 * passes, so a nightly run behind a daytime job still works the night's rows.
 * Without `wait`, `onBusy` is called and the row stays queued; a holder that
 * works every row, or every `now` row, takes it in its turn.
 */
export async function drainQueue(config, { cutoff = config.queue.cutoff, start = null,
  only = null, nowOnly = false, wait = false, onBusy = () => {}, run = runJob,
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
      Object.assign(row, { status: 'failed', finished: clock().toISOString(),
        reason: 'interrupted' });
    }
    if (interrupted.length) writeQueue(config, stale);
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

async function drainJobs(config, { stopAt, only, nowOnly, run, clock, pauser }) {
  const done = [];
  let first = only;
  let paused = false;
  for (;;) {
    if (clock() >= stopAt) break;
    const queue = readQueue(config);
    const next = queue.jobs.find((row) => row.status === 'queued'
      && (first ? row.id === first : !nowOnly || row.now));
    if (!next) break;
    first = null;
    if (!paused) {
      paused = true;
      await pauser.pause();
    }
    next.status = 'running';
    next.started = clock().toISOString();
    writeQueue(config, queue);
    const { id, status, added, started, now: _now, ...job } = next;
    let result;
    try {
      result = await run(config, { ...job, id });
    } catch (error) {
      result = { ok: false, phase: 'setup', reason: 'error', ms: 0 };
    }
    const after = readQueue(config);
    let row = after.jobs.find((r) => r.id === id && r.status === 'running');
    if (!row) {
      // The row was taken out of the queue file while the job ran.
      row = { id, ...job, added, started };
      after.jobs.push(row);
    }
    Object.assign(row, {
      status: result.ok ? 'passed' : 'failed', finished: clock().toISOString(),
      ms: result.ms, phase: result.ok ? 'done' : result.phase, reason: result.reason ?? null,
      workbook: result.workbook ?? null, outDir: result.outDir ?? null,
    });
    writeQueue(config, after);
    done.push(row);
  }
  return done;
}

/** The morning summary: one content-free line per job. */
export function summaryLines(queue) {
  return queue.jobs.map((row) => {
    const minutes = row.ms ? `${Math.round(row.ms / 60000)} min` : '';
    const where = row.status === 'failed' ? `stopped at ${row.phase} (${row.reason})`
      : row.status === 'passed' ? row.workbook ?? '' : '';
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
    const entries = fs.readFileSync(log, 'utf8').trim().split('\n').flatMap((line) => {
      try {
        return [JSON.parse(line)];
      } catch {
        return [];
      }
    });
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

async function main(argv) {
  const args = parseArgs(argv);
  const [command, sub] = args.words ?? [];
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
  if (command === 'queue' && sub === 'add') {
    const { id, added, marked, running } = addJob(config,
      { ...jobFrom(args), ...(args.now ? { now: true } : {}) });
    if (added) console.log(`queued ${id}`);
    else if (marked) console.log(`${id} is marked to start now`);
    else console.log(running ? `${id} is already running` : `${id} is already queued`);
    return 0;
  }
  if (command === 'queue' && sub === 'run') {
    // A cutoff given on the command line is a deliberate run, outside the nightly window.
    const done = await drainQueue(config, args.cutoff ? { cutoff: args.cutoff, wait: true, pause }
      : { cutoff: config.queue.cutoff, start: config.queue.start, wait: true, pause });
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
        : `the queue is running; ${args.job} stays queued and starts in its turn`);
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
