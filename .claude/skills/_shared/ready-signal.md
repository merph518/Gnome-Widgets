# The ready signal

Shared by any pull request a session opens, inside a skill or outside one.
Ported from PlaywrightTesting's `ready-signal.md`. A session that opened a pull
request ends its report with one line, so the user sees what is waiting on
them without reading back through the report. Its wording and the rules for
withholding it are written out here once.

It is the last line of the report, on its own, in capitals, with nothing else
on it:

```
PULL REQUEST <number> IS READY FOR YOUR REVIEW
```

It goes below everything else the report carries, the open questions
included.

Sending it also puts the `Manual Review Needed` label on the pull request, per
[The ready label](#the-ready-label).

The line waits on the static checks, the mergeability check, and the
session's own review of the pull request, per [self-review.md](self-review.md).

The line goes out in the turn the pull request becomes ready, even when the
session is in the middle of something longer. When several are ready, each
gets its own line.

## The ready label

The label goes on in the same turn as the line, first: the reply carrying the
line is written only once the label call has run, and a refused call means the
pull request is not ready, so the reply says so instead of sending the line.
The label is made on first use and never deleted, and goes on through the
issues endpoint, because `gh pr edit` fails on some `gh` releases:

```bash
gh label create "Manual Review Needed" --color D93F0B \
  --description "A pull request is waiting on the user's review" 2>/dev/null || true
gh api -X POST repos/{owner}/{repo}/issues/<number>/labels \
  -f "labels[]=Manual Review Needed" --jq '[.[].name] | join(", ")'
```

The output is the read-back: the label is on when its name comes back in it.

The label follows the line. When the user leaves feedback on the pull request,
whether a review comment, a requested-changes review, or a word in chat that
they reviewed it, the label comes off as soon as the session reads that
feedback, before any work on it starts, and goes back on only with the line:

```bash
gh api -X DELETE "repos/{owner}/{repo}/issues/<number>/labels/Manual%20Review%20Needed" \
  --jq '[.[].name] | join(", ")'
```

A pull request that no longer carries the label, because the user removed it,
has nothing to remove, which is not a failed removal. The merge takes the pull
request out of the user's list, so [implement](../implement/SKILL.md) section 10
leaves it alone.

## When it is withheld

The line says the pull request needs nothing further from the session. So it
is withheld while a static check fails, while the pull request conflicts with
its base, and while the self review in [self-review.md](self-review.md) has not
ended. The order is always: static checks and mergeability, self review, ready
signal.

A task that opened no pull request says nothing in its place. There is no
variant of the line for work that did not reach one.

## The static checks come first

The static checks are the list in [static-checks.md](static-checks.md), with
the build and the run it asks for. They pass on the branch head before every
push to a pull request and again before the self review starts.

## The mergeability check comes first

Straight after `gh pr create`, and again when the self review ends, read the
pull request's state without being asked:

```bash
gh pr view <number> --json mergeable,mergeStateStatus
```

`MERGEABLE` means the check is done. `UNKNOWN` means GitHub has not worked it
out yet, which is usual for a few seconds after `gh pr create` or a push:
read it again after a short pause, and treat it as not yet checked until it
says one or the other. `CONFLICTING` means the session resolves the conflicts
now, on its own, before it reports anything:

```bash
git fetch origin
git merge origin/<base>
git diff --name-only --diff-filter=U
```

Read both sides of every hunk before writing the resolution. The resolution is
almost always the union of the two, in the order the surrounding file already
uses, rather than either side winning; one that drops the other side's work is
a silent revert of a merged branch. Never rebase and never force-push: the
branch is pushed, so a merge commit is the correct shape. Rerun the static
checks, push, and read the state again, since the second read is what proves
the resolution took. The report names the file that conflicted and what the
union kept.

## A stacked pull request

A pull request cut from another unmerged branch, per `/new-branch`, targets
that parent branch. This repository does not delete branches on merge, so
GitHub never moves the child to `main` when the parent merges. When the child
is opened, record the parent in the session's ledger with
`scripts/catchup.py add-pr`, unless it is there already, since a parent
another session opened is not. When the watcher prints the parent's
`pr: <number> merged`, retarget the child before anything else, and read its
mergeability again:

```bash
gh api -X PATCH repos/{owner}/{repo}/pulls/<child> -f base=main
```

A child left on its merged parent would merge into a dead branch, and its work
would never reach `main`. The report above a child's ready signal names its
parent, so the user merges the parent first.

## Listening for the merge

Once the line is sent, the session records the pull request with
`scripts/catchup.py add-pr` and leaves the one watcher running, per
[run-watch.md](run-watch.md#waiting-on-a-merge). The merge arrives as a push
from GitHub, and the session acts on it without the user having to report it.
