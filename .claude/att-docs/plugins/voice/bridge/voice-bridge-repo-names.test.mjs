// Run with: node --test plugins/voice/bridge/voice-bridge-repo-names.test.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { after, test } from 'node:test';
import {
  checkoutKeys, currentRepo, readRepoNames, refreshRepoNames,
} from './voice-bridge-repo-names.mjs';
import { repoCheckout, repoNames, startSession } from './voice-bridge.mjs';

// Every scratch folder the tests make, removed once the file's tests finish.
const tempDirs = [];
after(() => {
  for (const dir of tempDirs) fs.rmSync(dir, { recursive: true, force: true });
});

function tempDir() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'voice-bridge-names-'));
  tempDirs.push(dir);
  return dir;
}

// A folder under codeDir that is a main checkout whose origin remote names repo.
function codeCheckout(codeDir, folder, repo) {
  const dir = path.join(codeDir, folder);
  fs.mkdirSync(path.join(dir, '.git'), { recursive: true });
  fs.writeFileSync(path.join(dir, '.git', 'HEAD'), 'ref: refs/heads/main\n');
  fs.writeFileSync(path.join(dir, '.git', 'config'),
    `[remote "origin"]\n\turl = https://github.com/${repo}.git\n`);
  return dir;
}

// A code folder holding a checkout whose remote still has the name its repository had before
// GitHub renamed it, beside one that was never renamed.
function renamedFolder() {
  const root = tempDir();
  const codeDir = path.join(root, 'Code');
  const widgets = codeCheckout(codeDir, 'conky-spotify-nowplaying', 'merph518/conky-widgets');
  const overmind = codeCheckout(codeDir, 'Overmind', 'merph518/Overmind');
  return { root, codeDir, widgets, overmind, file: path.join(root, 'state', 'repo-names.json') };
}

// gh as GitHub answers repo view, following the conky-widgets rename. calls records each
// repository asked about.
function fakeGh(calls = []) {
  const current = { 'merph518/conky-widgets': 'merph518/Gnome-Widgets',
    'merph518/overmind': 'merph518/Overmind' };
  return async ({ args }) => {
    calls.push(args[2]);
    if (!current[args[2]]) throw new Error('Could not resolve to a Repository');
    return JSON.stringify({ nameWithOwner: current[args[2]] });
  };
}

test('refreshRepoNames stores the current name of each remote and skips fresh ones', async () => {
  const { file } = renamedFolder();
  const calls = [];
  let clock = 1000;
  const gh = fakeGh(calls);
  const repos = ['merph518/conky-widgets', 'merph518/overmind', 'merph518/gone'];
  await refreshRepoNames(repos, { gh, file, now: () => clock });
  assert.deepEqual(readRepoNames(file), {
    'merph518/conky-widgets': { current: 'merph518/Gnome-Widgets', checkedAt: 1000 },
    'merph518/overmind': { current: 'merph518/Overmind', checkedAt: 1000 },
  });
  // A repository looked up lately is not asked about again; one that failed still is.
  calls.length = 0;
  clock += 60_000;
  await refreshRepoNames(repos, { gh, file, now: () => clock });
  assert.deepEqual(calls, ['merph518/gone']);
  assert.equal(currentRepo('merph518/conky-widgets', readRepoNames(file)),
    'merph518/Gnome-Widgets');
  // The same name in another case is no rename.
  assert.equal(currentRepo('merph518/overmind', readRepoNames(file)), null);
});

test('refreshRepoNames keeps the cache when gh fails', async () => {
  const { file } = renamedFolder();
  await refreshRepoNames(['merph518/conky-widgets'], { gh: fakeGh(), file, now: () => 1 });
  const failing = async () => { throw new Error('gh: not signed in'); };
  await refreshRepoNames(['merph518/conky-widgets'], { gh: failing, file, force: true });
  assert.equal(readRepoNames(file)['merph518/conky-widgets'].current, 'merph518/Gnome-Widgets');
  assert.deepEqual(readRepoNames(path.join(tempDir(), 'missing.json')), {});
});

test('checkoutKeys answers to the folder, the old and new names, and aliases', () => {
  const checkout = { folder: 'conky-spotify-nowplaying', repo: 'merph518/conky-widgets' };
  const renamed = { 'merph518/conky-widgets': { current: 'merph518/Gnome-Widgets' } };
  const aliases = { 'GNOME widget board': 'conky-spotify-nowplaying',
    Widgets: 'merph518/Gnome-Widgets', Other: 'elsewhere' };
  const keys = checkoutKeys(checkout, { renamed, aliases });
  assert.deepEqual([...keys.names].sort(), ['conkyspotifynowplaying', 'conkywidgets',
    'gnomewidgetboard', 'gnomewidgets', 'widgets']);
  assert.deepEqual([...keys.full].sort(), ['merph518conkywidgets', 'merph518gnomewidgets']);
});

test('repoCheckout finds a checkout by its repository\'s current GitHub name', async () => {
  const { codeDir, widgets, overmind, file } = renamedFolder();
  // Before the lookup only the old name and the folder match.
  assert.throws(() => repoCheckout('GNOME widgets', codeDir, repoNames({ repoNamesFile: file })),
    /No checkout of GNOME widgets was found\. A session can start in overmind and conky-widgets/);
  await refreshRepoNames(['merph518/conky-widgets', 'merph518/overmind'],
    { gh: fakeGh(), file });
  const names = repoNames({ repoNamesFile: file });
  for (const said of ['GNOME widgets', 'Gnome-Widgets', 'merph518/Gnome-Widgets',
    'conky widgets', 'merph518/conky-widgets', 'conky-spotify-nowplaying']) {
    const found = repoCheckout(said, codeDir, names);
    assert.equal(found.dir, widgets, said);
    assert.equal(found.repo, 'merph518/gnome-widgets', said);
    assert.equal(found.name, 'gnome-widgets', said);
  }
  assert.equal(repoCheckout('Overmind', codeDir, names).dir, overmind);
  assert.throws(() => repoCheckout('Nowhere', codeDir, names),
    /A session can start in overmind and gnome-widgets\./);
});

test('repoCheckout matches an alias from the config file', () => {
  const { codeDir, widgets, file } = renamedFolder();
  const names = repoNames({ repoNamesFile: file },
    { repoAliases: { 'desktop widgets': 'conky-spotify-nowplaying' } });
  assert.equal(repoCheckout('Desktop Widgets', codeDir, names).dir, widgets);
});

test('start_session looks up renamed repositories when a spoken name misses', async () => {
  const { root, codeDir, widgets, file } = renamedFolder();
  const paths = {
    sessionsDir: path.join(root, 'sessions'), procDir: path.join(root, 'proc'),
    bridgeDir: path.join(root, 'bridge'), projectsDir: path.join(root, 'projects'),
    startedFile: path.join(root, 'state', 'started.json'), repoNamesFile: file,
  };
  fs.mkdirSync(paths.sessionsDir, { recursive: true });
  const calls = [];
  const launches = [];
  const context = {
    paths, config: { roots: ['/repo'], startDir: '/repo', codeDir },
    startClaude: async launch => launches.push(launch), startWaitMs: 0,
    tracker: { cwd: '/repo', gh: fakeGh(calls) },
  };
  await startSession({ name: 'Widgets', request: 'check', repo: 'GNOME widgets' }, context);
  assert.equal(launches[0].cwd, widgets);
  assert.deepEqual(calls.sort(), ['merph518/conky-widgets', 'merph518/overmind']);
  // The old name still works, from the cache, with no lookup.
  calls.length = 0;
  await startSession({ name: 'Old', request: 'check', repo: 'conky-widgets' }, context);
  assert.equal(launches[1].cwd, widgets);
  assert.deepEqual(calls, []);
  // A name nothing answers to is still refused, after one more lookup at most.
  await assert.rejects(startSession({ name: 'Lost', request: 'x', repo: 'Nowhere' }, context),
    /No checkout of Nowhere was found\. A session can start in overmind and gnome-widgets\./);
  assert.equal(launches.length, 2);
});
