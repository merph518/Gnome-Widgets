// Finds the GitHub repository a tracker tool's spoken repo means, with or without a local
// checkout of it.
//
// Issues, pull requests, milestones, labels and runs need only the repository's owner/name:
// gh reads it from GH_REPO wherever it runs. So a spoken name is matched against every
// repository the user and the user's organizations own, by its current GitHub name. A name
// GitHub does not know, such as a checkout's folder or the name a repository had before a
// rename, is then looked for among the local checkouts, and the checkout's remote is followed
// through GitHub's redirect to the repository's current name.

// How long a full listing of the owners' repositories is kept before it is read again, and how
// long a listing that missed an owner, or failed, is left before it is tried again.
export const LISTING_TTL_MS = 10 * 60 * 1000;
export const LISTING_RETRY_MS = 60 * 1000;

// A repository or folder name with the case and the punctuation said around it dropped, so
// "Family-Bot", "family bot" and "FamilyBot" are one name.
export const nameKey = text => String(text ?? '').toLowerCase().replace(/[^a-z0-9]/g, '');

// The same, with a leading "the" dropped too, so "RPG Club API" finds TheRPGClub-api.
const looseKey = text => nameKey(text).replace(/^the/, '');

// What gh says when a repository does not exist or cannot be seen.
const NO_SUCH_REPO = /could not resolve to a repository|not found/i;

// What has been read through each gh, kept apart so a gh that answers differently starts
// fresh: the last listing, the time and error of the last failed one, and each owner/name
// already followed to its current name, by its lowercased form.
const known = new WeakMap();
function knownFor(gh) {
  if (!known.has(gh)) known.set(gh, { listing: null, failed: null, current: new Map() });
  return known.get(gh);
}

const lines = text => String(text ?? '').split('\n').map(line => line.trim()).filter(Boolean);

// Every repository the user and the user's organizations own, as
// { repos: [{ repo, fork }], owners, missed }: owners every account asked, missed the ones gh
// could not list, such as an organization that wants single sign-on. A full listing is kept
// for LISTING_TTL_MS and one that missed an owner for LISTING_RETRY_MS. A listing that fails
// outright gives the last one kept, or is thrown when there is none, and gh is not asked again
// until LISTING_RETRY_MS has passed.
export async function ownedRepos(gh, { cwd, now = Date.now() } = {}) {
  const kept = knownFor(gh);
  const { listing, failed } = kept;
  const keep = listing?.missed.length ? LISTING_RETRY_MS : LISTING_TTL_MS;
  if (listing && now - listing.at < keep) return listing;
  if (failed && now - failed.at < LISTING_RETRY_MS) {
    if (listing) return listing;
    throw failed.error;
  }
  try {
    const user = lines(await gh({ cwd, args: ['api', 'user', '--jq', '.login'] }));
    const missed = [];
    const orgs = lines(await gh({ cwd,
      args: ['api', 'user/orgs', '--paginate', '--jq', '.[].login'] })
      .catch(() => missed.push('the organizations') && ''));
    const owners = [...new Set([...user, ...orgs])];
    const repos = [];
    for (const owner of owners) {
      const rows = await gh({ cwd, args: ['repo', 'list', owner, '--limit', '1000',
        '--json', 'nameWithOwner,isFork', '--jq', '.[] | "\\(.nameWithOwner) \\(.isFork)"'] })
        .catch(() => missed.push(owner) && '');
      for (const row of lines(rows)) {
        const [repo, fork] = row.split(' ');
        repos.push({ repo, fork: fork === 'true' });
      }
    }
    kept.listing = { at: now, repos, owners, missed };
    kept.failed = null;
    return kept.listing;
  } catch (error) {
    kept.failed = { at: now, error };
    if (listing) return listing;
    throw error;
  }
}

// The current owner/name of a repository by any name GitHub redirects from, or null when
// GitHub has no such repository. Any other failure is thrown.
async function currentName(gh, cwd, repo) {
  const { current } = knownFor(gh);
  const key = repo.toLowerCase();
  if (!current.has(key)) {
    let name;
    try {
      name = lines(await gh({ cwd, args: ['repo', 'view', repo,
        '--json', 'nameWithOwner', '--jq', '.nameWithOwner'] }))[0] || repo;
    } catch (error) {
      if (!NO_SUCH_REPO.test(error.message)) throw error;
      name = null;
    }
    current.set(key, name);
  }
  return current.get(key);
}

const andList = names => (names.length > 1
  ? `${names.slice(0, -1).join(', ')} and ${names.at(-1)}` : names[0]);

// The owned repositories a spoken name means: by owner/name, by name, or by owner and name
// said together; failing those, by name with a leading "the" dropped. Where a name is shared,
// a fork gives way to the repository that is not one.
function matching(repos, text) {
  const key = nameKey(text);
  if (!key) return [];
  const short = ({ repo }) => repo.split('/')[1];
  let found = text.includes('/') ? repos.filter(({ repo }) => nameKey(repo) === key)
    : repos.filter(row => [short(row), row.repo].some(name => nameKey(name) === key));
  if (!found.length && !text.includes('/')) {
    found = repos.filter(row => looseKey(short(row)) === looseKey(text));
  }
  const sources = found.filter(row => !row.fork);
  return (found.length > 1 && sources.length ? sources : found).map(({ repo }) => repo);
}

// The repository a spoken repo means, as { repo, dir }: repo its current owner/name, dir the
// local checkout of it or null when there is none. checkout(name) returns the checkout a name
// means, { dir, repo }, or throws when none or two match. Throws an error worded to be read
// aloud when no repository matches, or more than one does.
export async function resolveTrackerRepo(said, { gh, cwd, checkout, now = Date.now() }) {
  const text = String(said ?? '').trim();
  let listing = null;
  try {
    listing = await ownedRepos(gh, { cwd, now });
  } catch {
    // Offline, or gh signed out: the local checkouts can still answer.
  }
  const found = listing ? matching(listing.repos, text) : [];
  if (found.length > 1) {
    throw new Error(`More than one repository is called ${text}: ${andList(found)}. `
      + 'Say the owner and the repository name.');
  }
  const local = name => {
    try {
      return checkout(name);
    } catch {
      return null;
    }
  };
  if (found.length === 1) {
    const [repo] = found;
    return { repo, dir: local(repo)?.dir ?? local(repo.split('/')[1])?.dir ?? null };
  }
  const near = local(text);
  if (near?.repo) {
    const repo = await currentName(gh, cwd, near.repo).catch(() => null);
    return { repo: repo ?? near.repo, dir: near.dir };
  }
  // An owner/name outside the listing, such as a repository the user collaborates on, is
  // asked of GitHub directly.
  if (text.includes('/')) {
    let repo;
    try {
      repo = await currentName(gh, cwd, text);
    } catch {
      throw new Error(`GitHub could not be asked about ${text}.`);
    }
    if (repo) return { repo, dir: null };
  }
  if (!listing) {
    throw new Error(`No checkout of ${text} was found, and GitHub could not be asked for `
      + 'the rest.');
  }
  const searched = listing.owners.filter(owner => !listing.missed.includes(owner));
  const missed = listing.missed.length
    ? ` GitHub could not list ${andList(listing.missed)}.` : '';
  throw new Error(`No repository called ${text} was found in `
    + `${searched.length ? andList(searched) : 'the accounts gh is signed in to'}.${missed}`);
}
