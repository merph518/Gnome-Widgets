// Two logs per job. status.log is the one a session may be shown: phase names,
// pass or fail, reason codes, counts and timings, and nothing else. detail.log
// holds what the model and the builder actually said, and stays in the job's
// output folder on this machine.

import fs from 'node:fs';
import path from 'node:path';

/** Field values a status line may carry: numbers, booleans, and short codes. */
const SAFE = /^[A-Za-z0-9 _.:/=+-]{0,80}$/;

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

export function jobLogs(outDir, { echo = true } = {}) {
  fs.mkdirSync(outDir, { recursive: true });
  const statusPath = path.join(outDir, 'status.log');
  const detailPath = path.join(outDir, 'detail.log');
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
  };
}
