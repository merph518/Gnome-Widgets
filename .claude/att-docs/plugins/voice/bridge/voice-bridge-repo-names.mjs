// The other names a local checkout answers to: the name its repository has on GitHub now, when
// the repository was renamed after the checkout's origin remote was written, and any aliases
// the config file gives it. GitHub redirects an old remote, so git and gh keep working after a
// rename and only a match on the spoken name breaks; this is what mends that match.
import fs from 'node:fs';
import path from 'node:path';

// How long a repository's looked-up name is trusted before a miss looks it up again.
export const RENAME_CHECK_MS = 24 * 60 * 60 * 1000;

// A repository or folder name with the case and the punctuation said around it dropped, so
// "Gnome-Widgets", "GNOME widgets" and "gnomewidgets" are one name.
export const repoKey = text => String(text ?? '').toLowerCase().replace(/[^a-z0-9]/g, '');

// The cache file as { repos: { 'owner/old': { current: 'Owner/New', checkedAt } } }, keyed by
// the lowercase owner/name an origin remote names. An unreadable file reads as empty.
export function readRepoNames(file) {
  try {
    const stored = JSON.parse(fs.readFileSync(file, 'utf8'));
    return stored && typeof stored.repos === 'object' && stored.repos ? stored.repos : {};
  } catch {
    return {};
  }
}

function writeRepoNames(file, repos) {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const temp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(temp, `${JSON.stringify({ repos }, null, 2)}\n`, { mode: 0o600 });
  fs.renameSync(temp, file);
}

// Asks GitHub for the current owner/name of each repository in repos, as gh follows a
// rename's redirect, and stores the answers in file. A repository looked up within maxAge is
// left alone unless force is set. A lookup that fails, for a repository that is gone or with
// gh signed out, keeps whatever the cache held. Returns the cache as it now stands.
export async function refreshRepoNames(repos, {
  gh, file, cwd, now = Date.now, maxAge = RENAME_CHECK_MS, force = false,
}) {
  const cached = readRepoNames(file);
  const due = [...new Set(repos.filter(Boolean).map(repo => repo.toLowerCase()))]
    .filter(repo => force || !cached[repo] || now() - cached[repo].checkedAt >= maxAge);
  if (!due.length) return cached;
  const answers = await Promise.all(due.map(async repo => {
    try {
      const text = await gh({ cwd, args: ['repo', 'view', repo, '--json', 'nameWithOwner'] });
      const current = JSON.parse(text).nameWithOwner;
      return typeof current === 'string' && current.includes('/') ? [repo, current] : null;
    } catch {
      return null;
    }
  }));
  // Read again, so an answer another refresh stored while these ran is kept.
  const stored = readRepoNames(file);
  let changed = false;
  for (const answer of answers) {
    if (!answer) continue;
    stored[answer[0]] = { current: answer[1], checkedAt: now() };
    changed = true;
  }
  if (changed) writeRepoNames(file, stored);
  return stored;
}

// The repository's current owner/name for an origin remote's owner/name, or null when the
// cache holds no other name for it.
export function currentRepo(repo, renamed = {}) {
  const current = renamed[String(repo ?? '').toLowerCase()]?.current;
  return current && current.toLowerCase() !== String(repo).toLowerCase() ? current : null;
}

// Every key a checkout { folder, repo } answers to, for a spoken name without an owner and for
// one with: its folder, its remote's repository name, the current name GitHub gives that
// repository, and each alias in aliases that names the checkout by folder or owner/name, such
// as { "GNOME widgets": "conky-spotify-nowplaying" }.
export function checkoutKeys(checkout, { renamed = {}, aliases = {} } = {}) {
  const repos = [checkout.repo, currentRepo(checkout.repo, renamed)].filter(Boolean);
  const names = [checkout.folder, ...repos.map(repo => repo.split('/')[1])];
  const own = new Set([checkout.folder, ...repos].map(repoKey));
  for (const [alias, target] of Object.entries(aliases ?? {})) {
    if (own.has(repoKey(target))) names.push(alias);
  }
  return { names: new Set(names.map(repoKey)), full: new Set(repos.map(repoKey)) };
}
