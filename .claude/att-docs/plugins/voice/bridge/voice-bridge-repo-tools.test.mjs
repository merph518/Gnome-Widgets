// Run with: node --test plugins/voice/bridge/voice-bridge-repo-tools.test.mjs
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import {
  callTool, fastForwardRepository, loadRepoTools, resetExtension, runGit, useExtension,
} from './voice-bridge.mjs';

const GIT_ENV = {
  ...process.env, GIT_AUTHOR_NAME: 'Test', GIT_AUTHOR_EMAIL: 'test@example.com',
  GIT_COMMITTER_NAME: 'Test', GIT_COMMITTER_EMAIL: 'test@example.com',
};
const gitIn = (cwd, ...args) => execFileSync('git', args,
  { cwd, env: GIT_ENV, stdio: ['ignore', 'pipe', 'pipe'] }).toString().trim();

const MODULE = `
export function register(core) {
  return { tools: [{
    definition: { name: 'echo_repo', description: 'Echoes.', inputSchema: { type: 'object' } },
    call: async (args, context) => JSON.stringify({
      args, root: core.repoRoot(), field: core.extension.greeting,
      helpers: Object.keys(core.helpers).length > 5, cwd: context.tracker.cwd,
    }),
  }] };
}
`;

// A scratch repository whose extension file names a tool module, or none.
function scratchRepository(t, { bridge } = {}) {
  const repo = fs.mkdtempSync(path.join(os.tmpdir(), 'repo-tools-'));
  t.after(() => fs.rmSync(repo, { recursive: true, force: true }));
  execFileSync('git', ['init', '-q', repo]);
  fs.mkdirSync(path.join(repo, '.claude', 'skills', 'voice-bridge-hooks'), { recursive: true });
  fs.mkdirSync(path.join(repo, 'scripts'));
  fs.writeFileSync(path.join(repo, 'scripts', 'tools.mjs'), MODULE);
  const file = path.join(repo, '.claude', 'skills', 'voice-bridge-hooks', 'extension.json');
  fs.writeFileSync(file, JSON.stringify({ greeting: 'hello', ...(bridge && { bridge }) }));
  t.after(resetExtension);
  return { repo: fs.realpathSync(repo), file };
}

const context = repo => ({
  paths: { bridgeDir: os.tmpdir() }, config: { roots: [repo] }, pages: new Map(),
});

test('a repository tool module adds its tools and is called with the bridge helpers', async t => {
  const { repo, file } = scratchRepository(t, { bridge: { module: 'scripts/tools.mjs' } });
  useExtension(file);
  assert.deepEqual(await loadRepoTools(), ['echo_repo']);
  const said = JSON.parse(await callTool('echo_repo', { a: 1 }, context(repo)));
  assert.deepEqual(said, {
    args: { a: 1 }, root: repo, field: 'hello', helpers: true, cwd: repo,
  });
});

test('a repository with no tool module adds no tools', async t => {
  const { repo, file } = scratchRepository(t);
  useExtension(file);
  assert.deepEqual(await loadRepoTools(), []);
  await assert.rejects(callTool('echo_repo', {}, context(repo)));
});

// An origin with one commit, a checkout of it, and a second commit pushed to origin.
function behindCheckout(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'repo-update-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const origin = path.join(root, 'origin');
  const work = path.join(root, 'work');
  const checkout = path.join(root, 'checkout');
  fs.mkdirSync(origin);
  gitIn(origin, 'init', '--quiet', '--bare', '--initial-branch=main');
  gitIn(root, 'clone', '--quiet', origin, work);
  fs.writeFileSync(path.join(work, 'a.txt'), '1\n');
  gitIn(work, 'add', '-A');
  gitIn(work, 'commit', '--quiet', '-m', 'one');
  gitIn(work, 'push', '--quiet', 'origin', 'HEAD:main');
  gitIn(root, 'clone', '--quiet', origin, checkout);
  fs.writeFileSync(path.join(work, 'a.txt'), '2\n');
  gitIn(work, 'commit', '--quiet', '-am', 'two');
  gitIn(work, 'push', '--quiet', 'origin', 'HEAD:main');
  return { checkout, target: gitIn(work, 'rev-parse', 'HEAD') };
}

test('the repository checkout fast-forwards when it is clean and on main', async t => {
  const { checkout, target } = behindCheckout(t);
  const said = await fastForwardRepository({ checkout, git: runGit, branch: 'main' });
  assert.equal(said, `The repository checkout is now at ${target.slice(0, 7)}.`);
  assert.equal(gitIn(checkout, 'rev-parse', 'HEAD'), target);
  assert.equal(await fastForwardRepository({ checkout, git: runGit, branch: 'main' }),
    'The repository checkout is already current.');
});

test('the repository checkout is left alone when dirty or off main', async t => {
  const { checkout, target } = behindCheckout(t);
  fs.writeFileSync(path.join(checkout, 'a.txt'), 'mine\n');
  assert.match(await fastForwardRepository({ checkout, git: runGit, branch: 'main' }),
    /^The repository checkout was left as it was: it has local changes\.$/);
  gitIn(checkout, 'checkout', '--quiet', '.');
  gitIn(checkout, 'checkout', '--quiet', '-b', 'topic');
  assert.match(await fastForwardRepository({ checkout, git: runGit, branch: 'main' }),
    /left as it was: it is on topic, not main\.$/);
  assert.notEqual(gitIn(checkout, 'rev-parse', 'HEAD'), target);
});

test('a repository tool may not take the name of a bridge tool', async t => {
  const { repo, file } = scratchRepository(t, { bridge: { module: 'scripts/tools.mjs' } });
  fs.writeFileSync(path.join(repo, 'scripts', 'tools.mjs'),
    MODULE.replace("'echo_repo'", "'list_sessions'"));
  useExtension(file);
  await assert.rejects(loadRepoTools(), /already a bridge tool/);
});
