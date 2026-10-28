# Waiting on something

Shared by `/release`, by `/implement`, by any pull request a session opens,
and by [ready-signal.md](ready-signal.md).
This file is the only place the catch-up script, the one-watcher rule and the
three minute floor are written out. A skill that needs any of them points
here rather than restating them.

Ported from PlaywrightTesting's `run-watch.md`, less the GitHub Actions run
tallies: this repository has no workflows. What a session waits on here is a
Launchpad build, a pull request merge, or a blocking issue.

## Record it in a ledger

Everything a session waits on goes through `scripts/catchup.py`. Nothing else
reads it: no `gh pr checks --watch`, no loop around `curl` on Launchpad, no
`sleep` between reads. Keep one ledger per session, in the session's
scratchpad directory, and record each row as the wait starts:

```bash
scripts/catchup.py add-lp    <ledger> <version>      "<short label>"
scripts/catchup.py add-pr    <ledger> <pr-number>    "<short label>"
scripts/catchup.py add-issue <ledger> <issue-number> "<short label>"
```

Each one reads its row once, prints a `waiting:` line with the link a reader
follows, and settles the row at once if it is already finished. Recording the
same key again replaces its row. Where several rows are open, the `waiting:`
lines are what the session lists, so the whole open set reads in one place.

To read the Launchpad rows once, without waiting:

```bash
scripts/catchup.py check <ledger>
```

`check` skips pull request and issue rows; those settle through `wait`.

## One watcher per session

When the session has nothing to do but wait, it runs exactly one watcher, and
that watcher is the script:

```bash
scripts/catchup.py wait <ledger>
```

Run it as a background Bash call and end the turn. It exits as soon as any row
finishes, after printing that row's result, and ends with

```
wait: <n> finished; <m> still open; act on the result, then run wait again
```

That exit is the session's cue to act on the finished row straight away. Once
it has acted, the session starts `wait` again on the same ledger whenever rows
are still open, and ends the turn. A row recorded while `wait` is running goes
into the ledger with an `add-` command, and the same watcher picks it up.
Never start a second one.

`wait --all` exits only when every row is done. Use it only when no single
result could change what the session does next.

## Waiting on a Launchpad build

`/release` records the version it uploaded as soon as `release-ppa.sh` prints
`Successfully uploaded packages.`:

```bash
scripts/catchup.py add-lp <ledger> X.Y.Z "release X.Y.Z"
```

The row reads Launchpad's public API, which needs no sign-in and does not count
against the GitHub rate limit. It settles as one of these:

- `lp: X.Y.Z published`: the source is `Published` and every build
  `Successfully built`. Done.
- `lp: X.Y.Z failed`: a build ended in a state that will not recover on its own
  (`Failed to build`, `Dependency wait`, `Failed to upload`, and so on). The
  tally carries the build log link to read.
- `lp: X.Y.Z gone`: the source was superseded or deleted.
- `lp: X.Y.Z rejected`: the version never showed up in the archive within 45
  minutes of being recorded. Launchpad mails its rejections to the no-reply
  maintainer address, so this is the only sign: usually a reused version or a
  signature problem.

While it is open, the row's state says where it is (`not in the archive yet`,
`source Pending; Currently building`, and so on), and `check` prints it.

## Waiting on a merge

A session that has sent the ready signal, per
[ready-signal.md](ready-signal.md), records the pull request and lets the
watcher wait for the merge:

```bash
scripts/catchup.py add-pr <ledger> <pr-number> "<short label>"
```

When it merges, `wait` prints

```
done: <label> - <pull request url>
  merged <sha> at <time>
pr: <number> merged
```

and exits. That exit is the cue to report the merge straight away, without
waiting for the user to mention it. `closed without
merging` means the user closed it: report that and do nothing else to the
branch.

## Blocked by another session

A session is blocked when the work it was asked for is held by another
session: the issue already has a branch or pull request from someone else, or
a change it needs sits in a pull request that has not merged.

1. Report who holds the work and what it is waiting on.
2. Record the blocker in the session's ledger, and make sure one `wait` is
   running on it:

   ```bash
   scripts/catchup.py add-issue <ledger> <blocking issue> "<short label>"
   ```

   The blocking issue is the one whose close means the way is clear. When the
   blocker is a pull request with no issue behind it, record the pull request
   with `add-pr` instead, and read its `pr: <number> merged` the same way.
3. End the turn. The watcher is the only thing running.

When `wait` prints `issue: <number> closed` and exits, the session starts the
deferred task over from the skill's first step, because the blocker may have
already done some or all of it. When the deferred task's own issue is now
closed, the holder finished it: report that and stop. A blocker closed as not
planned frees the work the same way; the session says so in its report.

A blocker whose hold ends without a close or a merge cannot be watched this
way. The session records no row, says so, and picks the task up when the user
invokes it again.

## Push notices

`wait` learns a pull request merged or an issue closed from GitHub's
`pull_request` and `issues` events, so the session wakes within seconds. The
events come through `gh webhook forward`, from the `cli/gh-webhook` extension.
The script never installs the extension, since this machine installs software
through apt only. When it is missing, `wait` says so and reads on the timer.

GitHub allows one forwarder hook per repository, so every `wait` on the
machine shares one forwarder. The first `wait` to start takes a lock under
`~/.cache/catchup/`, runs the forwarder, and writes each close to a shared
events file as one short line. Every `wait` reads that file every five seconds,
which costs no API calls. When the holder exits, the next `wait` takes over the
lock within a few seconds and starts its own forwarder.

Before starting a forwarder, the holder stops any forwarder process that
outlived its waiter, and deletes a hook one on this machine left behind or one
GitHub has marked inactive. A hook made on another machine is left alone: the
forwarder here is refused, retries after a delay that doubles from one minute
to ten, and `wait` reads on the timer meanwhile. Every five minutes the holder
confirms its hook is still on the repository and restarts the forwarder when it
is gone. A `webhook-forwarder.github.com` hook in the repository settings while
no `wait` runs on any machine is safe to delete.

A close sent while no forwarder is listening never arrives, so reads cover the
gaps. When a forwarder connects, every `wait` reads each open pull request and
issue once. While no forwarder is live, every timer check reads them too. Issue
rows are read on every timer check even while it is live, since a blocked
session can wait for days.

## The three minute floor

Three minutes is the floor for timer checks. `--interval` accepts a longer
value and silently raises a shorter one. While a Launchpad row is open, or the
push is down, `wait` checks every three minutes. While the push is live and
only pull request and issue rows are open, it checks every fifteen minutes,
just to catch a lost notice.

Accepting an upload takes a few minutes, the build about two, and publishing
another ten to thirty, so a Launchpad row is usually open for twenty to forty
minutes. That is normal and needs no check of its own.
