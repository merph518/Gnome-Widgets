// Stops the configured systemd units while a job runs and starts them again
// afterward, so a job has the machine's memory and GPU for the model. Units
// that were not running when the run began are never started. Output names
// units from the config and nothing else.

import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

/** Runs one command with an argument array, never a shell. */
function defaultExec(command, args) {
  const result = spawnSync(command, args, { encoding: 'utf8' });
  return { status: result.status, stdout: result.stdout ?? '' };
}

// A unit name from systemctl is passed on as an argument, so only plain names go on.
const UNIT_NAME = /^[A-Za-z0-9][A-Za-z0-9@_.:\\-]*$/;

/** The state file lives beside the queue file, so a later run that takes the queue finds it. */
export const pausedPath = (config) => `${config.at(config.queue.file)}.paused`;

function readPaused(file) {
  try {
    const units = JSON.parse(fs.readFileSync(file, 'utf8'));
    return Array.isArray(units) ? units.filter((u) => typeof u === 'string' && UNIT_NAME.test(u)) : [];
  } catch {
    return [];
  }
}

/** True when a process named `busyProcess` runs inside the unit's cgroup. */
function unitBusy(procRoot, unit, busyProcess) {
  let pids;
  try {
    pids = fs.readdirSync(procRoot).filter((name) => /^\d+$/.test(name));
  } catch {
    return false;
  }
  for (const pid of pids) {
    try {
      if (fs.readFileSync(path.join(procRoot, pid, 'comm'), 'utf8').trim() !== busyProcess) continue;
      const groups = fs.readFileSync(path.join(procRoot, pid, 'cgroup'), 'utf8').split('\n');
      // The unit's cgroup path ends in its name; a longer name that merely ends the same way is not it.
      if (groups.some((line) => line.endsWith(`/${unit}`) || line.includes(`/${unit}/`))) return true;
    } catch {
      // The process exited while it was read.
    }
  }
  return false;
}

/**
 * A pauser for one run. `pause()` stops the active units the config names,
 * waiting for a busy one to go idle first; `resume()` starts every unit this
 * run stopped, plus those a run that died left in the state file. Neither
 * throws: a failed stop or start is logged and the run carries on.
 *
 * `leftover` is true for a run that holds the queue lock, the only run that
 * may restore what a dead holder stopped.
 */
export function createPauser(config, { exec = defaultExec, log = console.log, procRoot = '/proc',
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)), leftover = true } = {}) {
  const { units: patterns, scope, busyProcess, pollSeconds } = config.pause;
  const user = scope === 'user';
  const file = pausedPath(config);
  const systemctl = (...args) => (user ? exec('systemctl', ['--user', ...args])
    : exec('sudo', ['-n', '/usr/bin/systemctl', ...args]));
  const stopped = [];
  const inherited = leftover ? readPaused(file) : [];
  let cancelled = false;
  let resumed = false;

  const record = () => {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, `${JSON.stringify([...new Set([...inherited, ...stopped])])}\n`);
  };

  const stopOne = (unit) => {
    const result = systemctl('stop', unit);
    if (result.status !== 0) {
      log(`pause: stop failed ${unit}`);
      return;
    }
    stopped.push(unit);
    record();
    log(`pause: stopped ${unit}`);
  };

  const activeUnits = () => {
    // Listing is read-only, so it needs no sudo.
    const result = exec('systemctl', [...(user ? ['--user'] : []), 'list-units', '--plain',
      '--no-legend', '--state=active', ...patterns]);
    if (result.status !== 0) {
      log('pause: list failed');
      return [];
    }
    return [...new Set(result.stdout.split('\n').map((line) => line.trim().split(/\s+/)[0])
      .filter((unit) => UNIT_NAME.test(unit ?? '')))];
  };

  return {
    async pause() {
      if (!patterns.length || cancelled || resumed) return;
      let waiting = activeUnits();
      while (waiting.length && !cancelled) {
        const busy = [];
        for (const unit of waiting) {
          if (busyProcess && unitBusy(procRoot, unit, busyProcess)) busy.push(unit);
          else stopOne(unit);
        }
        waiting = busy;
        if (waiting.length) {
          log(`pause: waiting for ${waiting.join(' ')}`);
          await sleep(pollSeconds * 1000);
        }
      }
    },
    async resume() {
      if (resumed) return;
      resumed = true;
      cancelled = true;
      for (const unit of new Set([...inherited, ...stopped])) {
        const result = systemctl('start', unit);
        log(result.status === 0 ? `pause: started ${unit}` : `pause: start failed ${unit}`);
      }
      if (inherited.length || stopped.length) fs.rmSync(file, { force: true });
    },
  };
}
