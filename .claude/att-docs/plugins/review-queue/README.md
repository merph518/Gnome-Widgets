# review-queue

Shows above the prompt the pull requests that wait for your review. The plugin has no
skills, only a hooks module, `hooks/register.tsx`.

## What it does

A pull request waits for review when it is open and carries the `Manual Review Needed`
label.

- **Count.** A line above the prompt reads `N waiting for review`. With no pull request
  waiting, there is no band.
- **List.** Under the count, always shown, one line per pull request, oldest first: the
  repository, the number and the title as a link, then the CI state and how long ago it
  was opened. A draft says so. The CI state is `failing` when any check failed,
  `running` while a check is still going, `passing` once every check passed, skipped or
  came back neutral, and `no checks` when there are none. The list shows 8 pull requests
  and counts the rest.
- **Dismiss.** Each line has a **Dismiss** button. A dismissed pull request leaves the
  count and the list in every open chat: the plugin keeps the dismissals in its store,
  and each chat reads them every 15 seconds. The count line then adds `N dismissed`, and
  **Show dismissed** lists them, each with **Restore**. When every waiting pull request
  is dismissed, the band is one dim `N dismissed` line. A dismissal is dropped once a
  refresh no longer lists its pull request, because it merged, closed or lost the label.
- **Opening a pull request.** Clicking its link opens it in the browser. On the
  terminal the link works where the terminal supports links (OSC 8); elsewhere the
  terminal prints the address after the title.
- **Watched repositories.** `merph518/Overmind-Mod`, and each repository named in its
  `.github/consumers.json`. The plugin reads that file from GitHub with `gh api` at most
  once an hour and keeps the list, so it uses the last list it read when GitHub cannot
  be reached, and `Overmind-Mod` alone before it has read one.
- **Refreshes.** Once when the chat starts, and 3 seconds after a shell command that runs
  `gh pr` or adds or removes the label through `gh api
  repos/<owner>/<repo>/issues/<n>/labels` on a watched repository. An add counts when the
  command's answer lists the label. When the command can change the label or the pull
  request (the `gh api` label commands, and `gh pr create`, `edit`, `merge`, `close`,
  `reopen` and `ready`), the refresh also marks the store, and every other open chat
  refreshes on its next 15-second check, so a newly labeled pull request reaches them
  within about 20 seconds. `gh` placeholders such as `repos/{owner}/{repo}/...` count
  as a watched repository. Each refresh runs `gh pr list` once per
  repository, one after another. A refresh never holds up a reply, and one asked for
  while another runs waits for it.
- **Backstop.** Every 15 minutes the band refreshes on its own. A label added or removed
  in the GitHub web UI, on another machine, or by a script that calls GitHub itself
  rather than through a chat's shell command, and a change of CI state, show only then.
- **Merged elsewhere.** While `scripts/catchup.py wait` runs for a watched repository, it
  writes each pull request close to `~/.cache/catchup/<owner>__<repo>/events.jsonl`
  (renamed to `events.jsonl.old` past a megabyte). While pull requests wait, the plugin
  checks those files for their repositories every 5 seconds, from disk, and drops a row
  whose pull request closed after the refresh that listed it, with no `gh` call. A
  merge in the web UI then leaves the band within about 10 seconds. With no waiter
  running for a repository, the backstop refresh clears it. The plugin never starts a
  forwarder of its own.
- **When gh fails.** When no repository can be read, the row shows one dim line saying
  why: `gh` is not installed, is signed out, or cannot reach GitHub. The next refresh
  that reads a repository replaces it. When some repositories read and others do not,
  the row adds how many could not be read.

The plugin needs the GitHub CLI, `gh`, signed in to an account that can read the
watched repositories. It only reads: it never reviews, labels or merges.

## Turning it off

The plugin reads `mods/switches.json` in the Claude Code configuration folder
(`~/.claude`, or `CLAUDE_CONFIG_DIR` when that is set) at the start, before each
refresh, and every 15 seconds:

```json
{
  "review-queue": false,
  "review-queue:hidden": true
}
```

- `"review-queue": false` turns the plugin off: no row and no `gh` calls.
- `"review-queue:hidden": true` hides the row, and `gh` is not called while it is
  hidden.

With no `switches.json`, or a file that is not a JSON object, the plugin stays on. The
`/mods` pane lists it under Display, with **Turn off** and **Hide**.
`/plugin disable review-queue@att-docs` turns it off as well.

## Install

```
claude plugin install review-queue@att-docs --scope user
```

Then run `/reload-plugins` in an open session.

## Tests

```
claude plugin validate plugins/review-queue
claude plugin test plugins/review-queue
```
