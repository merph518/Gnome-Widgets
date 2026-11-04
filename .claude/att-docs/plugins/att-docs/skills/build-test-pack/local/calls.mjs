// A record of every model call a job makes: the prompt that went out, the reply that
// came back, the token counts and the timings. One file per call, in work/calls, named
// `<seq>-<step>-<attempt>.json`. The files hold document, rule and description text,
// as detail.log does, so they are never echoed to the console or to status.log.

import { createHash } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const CALLS_VERSION = 1;

/**
 * A hash of the whole prompt, so two calls with the same text hash alike on any
 * machine. The array keeps the system and user texts apart: moving a line from one
 * to the other changes the hash. The schema, the output cap and the temperature are
 * not part of it, so tuning a cap does not read as a prompt change.
 */
export function promptHash(system, user) {
  return `sha256:${createHash('sha256').update(JSON.stringify([system, user])).digest('hex')}`;
}

/**
 * A hash of the reply schema, kept apart from the prompt hash because the schema goes to
 * the model in the request, not in the prompt text. A schema change alone therefore shows
 * as a changed `schemaHash` with the same `promptHash`.
 */
export const schemaHash = (schema) =>
  `sha256:${createHash('sha256').update(JSON.stringify(schema)).digest('hex')}`;

/** The sequence number is five digits wide so a plain sort reads the calls in order. */
export const callFileName = (seq, step, attempt) =>
  `${String(seq).padStart(5, '0')}-${step}-${attempt}.json`;

/** The highest sequence number a call folder already holds, or 0 when it is new. */
function lastSeq(dir) {
  if (!fs.existsSync(dir)) return 0;
  return fs.readdirSync(dir).reduce((top, name) => {
    const seq = /^(\d+)-.*\.json$/.exec(name)?.[1];
    return seq ? Math.max(top, Number(seq)) : top;
  }, 0);
}

/**
 * Writes call records into `dir`. The first record of a run continues from the highest
 * number already in the folder, so a job resumed after a stop never overwrites the
 * calls it made before. A record that would land on an existing file throws instead
 * of replacing it, so the folder always holds the calls in the order they were made.
 */
export function callRecorder(dir) {
  let seq = null;
  return {
    /** Writes one call, adding its sequence number, and returns the file's path. */
    record({ step, attempt, thinking, maxTokens, system, user, schema, reply = null, errorCode = null,
      usage = null, startedAt, endedAt }) {
      fs.mkdirSync(dir, { recursive: true });
      seq ??= lastSeq(dir);
      seq += 1;
      const file = path.join(dir, callFileName(seq, step, attempt));
      const record = {
        version: CALLS_VERSION,
        seq,
        step,
        attempt,
        thinking: Boolean(thinking),
        maxTokens,
        promptHash: promptHash(system, user),
        schemaHash: schemaHash(schema),
        prompt: { system, user },
        reply,
        error: errorCode ? { code: errorCode } : null,
        usage: { promptTokens: usage?.promptTokens ?? 0, outputTokens: usage?.outputTokens ?? 0 },
        startedAt: startedAt.toISOString(),
        endedAt: endedAt.toISOString(),
        ms: usage?.ms ?? endedAt - startedAt,
      };
      fs.writeFileSync(file, `${JSON.stringify(record, null, 1)}\n`, { flag: 'wx' });
      return file;
    },
  };
}
