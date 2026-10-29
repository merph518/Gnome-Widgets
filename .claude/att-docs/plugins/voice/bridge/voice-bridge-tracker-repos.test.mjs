// Run with: node --test plugins/voice/bridge/voice-bridge-tracker-repos.test.mjs
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { LISTING_RETRY_MS, LISTING_TTL_MS, resolveTrackerRepo }
  from './voice-bridge-tracker-repos.mjs';

// A gh that answers the lookup's calls: user and orgs, each owner's repositories unless the
// owner is in failing, and the current name of each repository in views. Records every call.
function lookupGh({ user = 'merph518', orgs = [], repos = [], forks = [], failing = [],
  views = {}, down = false } = {}) {
  const calls = [];
  const gh = async ({ args }) => {
    calls.push(args);
    if (down) throw new Error('could not connect to github.com');
    if (args[1] === 'user') return user;
    if (args[1] === 'user/orgs') return orgs.join('\n');
    if (args[1] === 'list') {
      if (failing.includes(args[2])) throw new Error('SAML enforcement');
      return [...repos.map(repo => `${repo} false`), ...forks.map(repo => `${repo} true`)]
        .filter(row => row.startsWith(`${args[2]}/`)).join('\n');
    }
    if (args[1] === 'view' && Object.hasOwn(views, args[2])) return views[args[2]];
    throw new Error('Could not resolve to a Repository');
  };
  return { gh, calls };
}

const noCheckout = () => {
  throw new Error('No checkout');
};

test('a fork gives way to the repository of the same name, and alone is found', async () => {
  const { gh } = lookupGh({ orgs: ['TheRPGClub'], repos: ['TheRPGClub/TheRPGClub-api'],
    forks: ['merph518/TheRPGClub-api', 'merph518/some-lib'] });
  assert.equal((await resolveTrackerRepo('TheRPGClub-api', { gh, checkout: noCheckout })).repo,
    'TheRPGClub/TheRPGClub-api');
  assert.equal((await resolveTrackerRepo('some-lib', { gh, checkout: noCheckout })).repo,
    'merph518/some-lib');
});

test('an owner gh cannot list is skipped, named in a miss, and asked again soon', async () => {
  const { gh, calls } = lookupGh({ orgs: ['Locked', 'TheRPGClub'], failing: ['Locked'],
    repos: ['TheRPGClub/TheRPGClub-www'] });
  assert.deepEqual(await resolveTrackerRepo('TheRPGClub-www', { gh, checkout: noCheckout,
    now: 0 }), { repo: 'TheRPGClub/TheRPGClub-www', dir: null });
  await assert.rejects(resolveTrackerRepo('Vault', { gh, checkout: noCheckout, now: 1 }),
    /^Error: No repository called Vault was found in merph518 and TheRPGClub\. GitHub could not list Locked\.$/);
  const listed = () => calls.filter(args => args[1] === 'user').length;
  assert.equal(listed(), 1);
  await resolveTrackerRepo('TheRPGClub-www', { gh, checkout: noCheckout, now: LISTING_RETRY_MS });
  assert.equal(listed(), 2);
});

test('an owner/name outside the listing is asked of GitHub directly', async () => {
  const { gh } = lookupGh({ repos: ['merph518/Overmind'],
    views: { 'someorg/shared': 'someorg/Shared' } });
  assert.deepEqual(await resolveTrackerRepo('someorg/shared', { gh, checkout: noCheckout }),
    { repo: 'someorg/Shared', dir: null });
  await assert.rejects(resolveTrackerRepo('someorg/missing', { gh, checkout: noCheckout }),
    /^Error: No repository called someorg\/missing was found in merph518\.$/);
});

test('a failed refresh keeps answering from the last listing', async () => {
  const fake = lookupGh({ repos: ['merph518/Overmind'] });
  let down = false;
  const gh = args => (down ? Promise.reject(new Error('timeout')) : fake.gh(args));
  assert.equal((await resolveTrackerRepo('Overmind', { gh, checkout: noCheckout, now: 0 })).repo,
    'merph518/Overmind');
  down = true;
  const later = LISTING_TTL_MS + 1;
  assert.equal((await resolveTrackerRepo('Overmind', { gh, checkout: noCheckout, now: later }))
    .repo, 'merph518/Overmind');
  await assert.rejects(resolveTrackerRepo('someorg/x', { gh, checkout: noCheckout, now: later }),
    /^Error: GitHub could not be asked about someorg\/x\.$/);
});

test('a listing that failed is not asked again until the retry wait passes', async () => {
  const { gh, calls } = lookupGh({ down: true });
  const checkout = () => ({ dir: '/code/bot', repo: 'merph518/bot' });
  await resolveTrackerRepo('bot', { gh, checkout, now: 0 });
  const asked = calls.filter(args => args[1] === 'user').length;
  await resolveTrackerRepo('bot', { gh, checkout, now: LISTING_RETRY_MS - 1 });
  assert.equal(calls.filter(args => args[1] === 'user').length, asked);
  await resolveTrackerRepo('bot', { gh, checkout, now: LISTING_RETRY_MS });
  assert.equal(calls.filter(args => args[1] === 'user').length, asked + 1);
});
