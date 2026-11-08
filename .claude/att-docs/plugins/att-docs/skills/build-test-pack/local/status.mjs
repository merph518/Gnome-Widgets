// Three records per job. status.log is the one a session may be shown: phase names,
// pass or fail, reason codes, counts and timings, and nothing else. detail.log
// holds what the model and the builder actually said, and work/calls holds each
// model call's full prompt and reply. The last two stay in the job's output folder
// on this machine.

import fs from 'node:fs';
import path from 'node:path';

import { callRecorder } from './calls.mjs';
import { stepKey } from './config.mjs';

/** Field values a status line may carry: numbers, booleans, and short codes. A sandbox job's ID joins its source and label with `~`. */
export const FIELD_MAX = 80;
const SAFE = new RegExp(`^[A-Za-z0-9 _.:/=+~-]{0,${FIELD_MAX}}$`);

/** The parsed lines of a status.log; a line cut off mid-write is skipped, and a missing log is empty. */
export function readStatusLog(file) {
  let text;
  try {
    text = fs.readFileSync(file, 'utf8');
  } catch {
    return [];
  }
  return text.trim().split('\n').flatMap((line) => {
    try {
      return [JSON.parse(line)];
    } catch {
      return [];
    }
  });
}

/**
 * One status line's fields, checked. A string field has to be a code from the
 * pipeline itself (a phase name, a reason code, a job id), never text that
 * came from a document, a rule, the model or the builder.
 */
export function statusFields(fields) {
  for (const [key, value] of Object.entries(fields)) {
    if (typeof value === 'number' || typeof value === 'boolean' || value === null) continue;
    if (typeof value !== 'string' || !SAFE.test(value)) {
      throw new Error(`status field ${key} is not a short code`);
    }
  }
  return fields;
}

/**
 * A stop's counts cut to fit a status line: a string count longer than a field
 * allows keeps the first space-separated numbers that fit, each whole, and a
 * string with no space to cut at becomes empty. The count beside it, such as
 * `documents`, still holds the full total.
 */
export function fitCounts(counts) {
  const limit = FIELD_MAX;
  const fitted = {};
  for (const [key, value] of Object.entries(counts)) {
    if (typeof value !== 'string' || value.length <= limit) {
      fitted[key] = value;
      continue;
    }
    const cut = value.slice(0, limit + 1).lastIndexOf(' ');
    fitted[key] = cut > 0 ? value.slice(0, cut) : '';
  }
  return fitted;
}

/**
 * What one run did with its thinking steps, from its status lines: the steps it
 * asked with thinking on, keyed `<phase>.<step>` without an index or repeat
 * suffix, and each one cut at its output budget, with that budget.
 */
export function runCuts(entries) {
  const asked = new Set();
  const cut = new Map();
  for (const entry of entries) {
    if (entry.attempt !== 1 || entry.reasoning !== true
      || !['call', 'retry', 'call-fail'].includes(entry.event)) continue;
    const step = `${entry.phase}.${stepKey(entry.step)}`;
    asked.add(step);
    if (entry.reason === 'length') cut.set(step, entry.maxTokens ?? null);
  }
  return { asked: [...asked], cut: [...cut].map(([step, budget]) => ({ step, budget })) };
}

/**
 * The thinking steps cut at their output budget on the last two or more runs that
 * asked them, in a row, from runs oldest first. Each has its latest budget and how
 * many runs in a row cut it. A run that never asked a step, such as one resumed past
 * its phase, neither breaks nor extends the streak.
 */
export function repeatedCuts(runs) {
  const streaks = new Map();
  for (const run of runs) {
    const cut = new Map((run.cut ?? []).map((entry) => [entry.step, entry.budget]));
    for (const step of run.asked ?? []) {
      streaks.set(step, cut.has(step)
        ? { budget: cut.get(step), runs: (streaks.get(step)?.runs ?? 0) + 1 } : { runs: 0 });
    }
  }
  return [...streaks].filter(([, streak]) => streak.runs >= 2)
    .map(([step, { budget, runs }]) => ({ step, budget, runs }));
}

/** A job's recorded runs, oldest first, from the `cuts` each of its queue rows holds. */
export const recordedRuns = (queue, id) => queue.jobs.filter((row) => row.id === id)
  .flatMap((row) => row.cuts ?? []);

export function jobLogs(outDir, { echo = true } = {}) {
  fs.mkdirSync(outDir, { recursive: true });
  const statusPath = path.join(outDir, 'status.log');
  const detailPath = path.join(outDir, 'detail.log');
  const calls = callRecorder(path.join(outDir, 'work', 'calls'));
  return {
    statusPath,
    detailPath,
    /** A content-free line, written to status.log and echoed to the console. */
    status(fields) {
      const line = JSON.stringify({ at: new Date().toISOString(), ...statusFields(fields) });
      fs.appendFileSync(statusPath, `${line}\n`);
      if (echo) console.log(line);
    },
    /** Anything else. Never echoed. */
    detail(label, value) {
      const text = typeof value === 'string' ? value : JSON.stringify(value, null, 1);
      fs.appendFileSync(detailPath, `--- ${new Date().toISOString()} ${label}\n${text}\n`);
    },
    /** One model call's prompt, reply, counts and timings, in work/calls. Never echoed. */
    call: (fields) => calls.record(fields),
  };
}
