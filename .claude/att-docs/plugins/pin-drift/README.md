# pin-drift

Shows above the prompt, in the Overmind repository, when a release is waiting to be cut
or a repository that pins Overmind is behind the latest tag. The plugin has no skills,
only a hooks module, `hooks/register.tsx`.

## What it does

- **Band.** One row above the prompt, such as
  `0.32.4 pending · 2 consumers behind latest (Laundry-Bot 0.31.4, personal 0.30.0)`,
  with a **Details** button that opens the pane. Each part shows only when it applies:
  - `0.32.4 pending` when the open release pull request (label `autorelease: pending`)
    names a version above the latest tag.
  - `N consumers behind latest (...)` names each repository whose pin is below the
    latest tag, with its pinned version, in the order `.github/consumers.json` lists
    them. A narrow window drops names from the end (`+2 more`), then the list.
  - `release state unreadable` when the release pull requests could not be read, since
    the band cannot say whether a release is waiting.
  - `N locks unreadable` when a repository's lock could not be read, since the band
    cannot say that repository is current.

  With no release pending and every repository on the latest tag or a newer one, there
  is no row.
- **Pane.** `/pin-drift`, **Details**, or **Reopen** in `/mods` opens it. It shows the
  latest tag, the pending release with a link to its pull request, and one entry per
  repository:
  - `pinned 0.32.3 · on latest`, or `ahead of latest` for a newer pin.
  - `pinned 0.31.4 · behind 0.32.3 ·` then a link to the open pin pull request (the
    newest one from an `overmind/pin-<tag>` or `overmind/move-<tag>` branch) and its
    CI state, `no open pin pull request`, or `pin pull requests could not be read`. A pin
    pull request to a tag at or below the current pin is ignored as stale. The CI state
    is `CI failing` when any check failed, `CI running` while one is still going,
    `CI passing` once every check passed, skipped or came back neutral, and `no checks`
    when there are none.
  - `lock unreadable:` and why. GitHub answers the same way for a lock that is missing
    and for a private repository the signed-in account cannot see, so the note names
    both.
  - `lock names <repo>` when the lock's `repo=` line names an older name of this
    repository. GitHub redirects the old name, so the pin still works. For a repository
    on the latest tag, the line below links the open move pull request that rewrites
    the lock, when there is one.

  When `gh` fails partway through, the pane keeps what was read, shows the failure line at
  the top, and marks each lock it did not get to as not read. When the release
  pull requests could not be read, the pane says so.

  **Refresh** reads GitHub again at once; the footer says how long ago the last read
  ran.
- **When gh fails.** When `gh` is not installed, is signed out, cannot reach GitHub, or
  hit the API rate limit, the row shows one dim line saying why. This holds whether the
  failure came on the first read or partway through.

## Where it shows

Only in a clone of this repository: the chat's repository must have an `origin` remote
on github.com naming `merph518/Overmind-Mod`, or one of the older names GitHub
redirects (`merph518/Overmind`, `mfagerstrom/Overmind-Mod`, `mfagerstrom/Overmind`), in
any of the https, ssh or `git@github.com:` forms. Anywhere else there is no row and no
`gh` command runs; the pane, when opened, says it works only in this repository.

## How it reads the state

Every call is a read through the GitHub CLI, `gh`, signed in to an account that can read
this repository and every consumer:

1. `.github/consumers.json` from this repository's default branch. When that read fails,
   the list from the last result is used, then the checkout's own copy of the file.
2. The `v*` tags. The highest `vMAJOR.MINOR.PATCH` tag is the latest; any other tag is
   ignored.
3. The open pull requests from `release-please--branches--main`.
4. Each consumer's `.claude/att-docs.lock` on its default branch. The first `repo=` and
   `tag=` lines count, read as the pin script reads them: carriage returns are dropped
   and nothing is trimmed, so a tag with a trailing space
   makes the lock unreadable, as does any tag that is not `vMAJOR.MINOR.PATCH`. A
   leading byte order mark is dropped as well.
5. For each consumer behind the latest tag, or whose lock names an older repository
   name, its open pull requests (up to 50), to find the pin or move pull request and its
   checks. A pin pull request needs a tag above the current pin; a move pull request
   needs one at or above it.

A failure on one consumer does not stop the others, except when `gh` is missing, signed
out, offline or rate limited, which holds for every consumer alike: the reads stop
there, and what was read before is kept.

A read runs when the chat starts, every 10 minutes, when the pane opens, and on
**Refresh**. The result is kept in the plugin's store, which every chat shares, so a
chat that finds a result under 10 minutes old uses it without asking GitHub; after a
read that failed in whole or in part it waits 15 minutes. One read takes three calls,
plus one per consumer, plus one per consumer behind or under an older lock name. Reads
never overlap: one asked for while another runs waits for it, then runs once.

Between a release pull request merging and its tag appearing, the release no longer
shows as pending and the consumers are not yet behind, so the row can be empty for a few
minutes.

The plugin never writes to GitHub. It does not run `pin-consumers.yml`; run that
workflow by hand when a pin pull request is missing.

## Turning it off

The plugin reads `mods/switches.json` in the Claude Code configuration folder
(`~/.claude`, or `CLAUDE_CONFIG_DIR` when that is set) at the start and every 3 seconds:

```json
{
  "pin-drift": false,
  "pin-drift:hidden": true
}
```

- `"pin-drift": false` turns the plugin off: no row, no pane contents and no `gh` calls.
- `"pin-drift:hidden": true` hides the row and stops the timed reads. Opening the pane
  still reads the pins.

With no `switches.json`, or a file that is not a JSON object, the plugin stays on. The
`/mods` pane lists it under Display, with **Turn off**, **Hide** and **Reopen**.
`/plugin disable pin-drift@att-docs` turns it off as well.

## Install

```
claude plugin install pin-drift@att-docs --scope user
```

Then run `/reload-plugins` in an open session.

## Tests

```
claude plugin validate plugins/pin-drift
claude plugin test plugins/pin-drift
```
