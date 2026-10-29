---
name: implement
description: >-
  Implement a GitHub issue end to end: read it, label it `In Progress`, branch
  from origin/main in the session's own worktree, do the work, run it, open a
  linked pull request, review that pull request itself, then hand it to the
  user. Use when asked to implement, work on, pick up, or start an issue by
  number - "/implement 12", "work issue 12", "start on #12".
---

# Implement

## Base

Read
[the general skill](../../att-docs/plugins/general/skills/implement/SKILL.md)
first and follow it, except where this file overrides it. The general skill is the
vendored copy pinned by `.claude/att-docs.lock`; never edit it here. The general
skill is written for a repository with a test suite and a CI runner; this
repository has neither, so most of what follows says which of its sections do not
apply and what replaces them.

## Paths

| Placeholder | Value here |
| --- | --- |
| `<asking-note>` | None. Questions go through `AskUserQuestion` directly |
| `<in-progress-label>` | `In Progress` |
| `<ready-label>` | `Manual Review Needed`, per [ready-signal.md](../_shared/ready-signal.md) |
| `<label-script>` | None. The inline `gh issue edit` and read-back, under Overrides, Section 2 (add) and Section 10 (remove) |
| `<labels-note>` | Under Overrides, Section 2 |
| `<area-label-rule>` | The area and kind labels of [/create-issue](../create-issue/SKILL.md): one area label and one kind label on every issue. An issue missing its area label gets it from `/create-issue` section 5 before work starts |
| `<reference-docs>` | `README.md` and the code, under Overrides, Section 1 |
| `<ownership-unit>` | The files the issue's diff changes |
| `<ownership-rules>` | Under Overrides, Section 2, which replaces the general skill's "Find out what other sessions own" |
| `<main-checkout>` | `~/Code/conky-spotify-nowplaying` |
| `<worktree-script>` | `/new-branch`, inside the worktree the app made, under Overrides, Section 3 |
| `<edit-guard>` | None |
| `<dependency-setup>` | None. Every dependency comes from apt |
| `<shell-text-note>` | Scripts, commit messages and bodies are passed as files from the scratchpad, never inline in the shell |
| `<branch-types>` | `fix`, `feat`, `chore`, `docs` |
| `<default-branch>` | `main` |
| `<follow-up-note>` | [/create-issue](../create-issue/SKILL.md) |
| `<branch-age-note>` | None. The mergeability check in `<mergeability-note>` stands in |
| `<post-merge-checks>` | None |
| `<sampling-note>` | None. There are no specs to sample |
| `<writing-rules>` | Comments say how the code works now and why, never its history or which issue asked for it |
| `<repo-constraints>` | Under Overrides, Section 4 |
| `<static-checks>` | [static-checks.md](../_shared/static-checks.md) |
| `<run-watch>` | [run-watch.md](../_shared/run-watch.md) and `scripts/catchup.py` |
| `<mergeability-note>` | [ready-signal.md](../_shared/ready-signal.md#the-mergeability-check-comes-first) |
| `<self-review>` | [self-review.md](../_shared/self-review.md) |
| `<ready-signal>` | [ready-signal.md](../_shared/ready-signal.md) |
| `<instructions-file>` | `CLAUDE.md` |
| `<merge-cleanup>` | Under Overrides, Section 10 |

Every other placeholder in the general skill belongs to a test suite, a
dispatch runner, a ledger of runs or a second tracker. This repository has none
of them, so the rules that use them are void, per the first override below.

## Overrides

### What does not apply

The two non-negotiable gates about dispatched test runs and deviation records,
all of Section 6 except "Failures already on the default branch get fixed",
Section 8, and every rule elsewhere that names a dispatch, a spec, a title
filter, a baseline, a deviation record, a skip ledger, an investigation log, a
shared test environment, test accounts or a pull request check job are void
here. The runtime verification is the widget run in Section 6 below, and the
static checks in `<static-checks>` stand in for `<pr-checks>`.

"Failures already on the default branch get fixed" applies to the static checks
and the widget run: a check that fails because of something already on `main` is
fixed on this branch, kept to what turns the check green, without a question
(`<sampling-note>` and baselines in it are void). The exception is a cause in a
file another open pull request changes, with nothing fixing it there: put the
failure on that pull request's issue and ask with `AskUserQuestion` whether to
fix it here or wait; a fix that merges comes in through the mergeability check
in `<mergeability-note>`, which stands in for `<branch-age-note>`. In place of
the fix cycle budget, a failure two fix attempts do not turn green is put to
the user with `AskUserQuestion`, not parked. Each fix is named under
`Pre-existing failures fixed` in the pull request body and in the Section 9
report.

The first gate still holds in these terms: no pull request is opened before the
Section 6 run is done, except for a change to documentation, skills or
`scripts/` alone, which owes no run, and the pull request says so.

### Section 1: Read the issue

The code, the README and the issue's own evidence decide what the issue means;
there is no functional specification to search. An issue found closed by a
session restarting after a block means the holder finished it: report that and
stop, instead of going on with other issues. The repository name in any
GitHub query comes from `{owner}` and `{repo}` or the current checkout, never a
literal.

### Section 2: Claim the issue

Read what is already out before claiming, and only then claim:

```bash
git fetch origin --prune
gh issue list --state open --label "In Progress" --json number,title
gh pr list --state open --json number,headRefName,files \
  --jq '.[]|"\(.number) \(.headRefName): \([.files[].path]|join(", "))"'
git branch -r --list "origin/*issue-<N>-*"
gh api graphql -F n=<N> -F owner='{owner}' -F name='{repo}' -f query='query($n: Int!, $owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) { issue(number: $n) {
  closedByPullRequestsReferences(first: 10) { nodes { number headRefName } } } } }' \
  --jq '.data.repository.issue.closedByPullRequestsReferences.nodes'
```

The last read lists the pull requests set to close this issue, whatever their
branch is called. A branch whose pull request already merged or was closed holds
nothing: GitHub keeps branches after a merge here, so a reopened issue can still
have one. Read it with `gh pr list --state all --head <branch> --json number,state`.

- The label, branch or pull request is this session's own, from earlier in the
  conversation (the branch is the one checked out here) -> nobody else holds
  it. Carry on from wherever the work stands.
- Otherwise, the issue already carrying `In Progress`, or having a branch or open
  pull request, means another session holds it. Do not cut a second branch, and
  leave the label alone. Take the blocked path in
  [run-watch.md](../_shared/run-watch.md#blocked-by-another-session), watching
  this issue, and end the turn.
- An open pull request changes a file this issue needs to change -> not a hold,
  but the second one to merge resolves the conflict. Name that pull request in
  this one's body.
- Nothing overlaps -> say in one line what was checked, and go on.

The label is made on first use and never deleted, and the claim is read back,
since an edit that silently failed is no claim:

```bash
gh label create "In Progress" --color FBCA04 \
  --description "A session is working on this" 2>/dev/null || true
gh issue edit <N> --add-label "In Progress"
gh issue view <N> --json labels --jq '[.labels[].name] | join(", ")'
```

This replaces the general skill's rule that a label that does not exist is never
created, and its "Section 3, Find out what other sessions own", which does not
apply: a session that finds the issue held blocks and ends the turn instead of
working the next one.

### Section 3: Branch

The desktop app starts each session in its own worktree under
`.claude/worktrees/`, so the branch is cut right there with `/new-branch`,
named `<type>/issue-<N>-<slug>`. A session sitting in the main checkout makes a
worktree first with the `EnterWorktree` tool, since that checkout is shared
with every other session. `/new-branch` verifies the base.

### Section 4: Do the work

Keep the general skill's scope rules (the whole scope, the scope guard, the
scope check-in). Void its paragraphs on test data discovery, tests that can
never run, and observed-value constraints. The repository's own constraints:

- Match the code around the change: its comment density, naming and idiom.
- A layout, control or look the issue leaves open is put to the user per
  [ui-options.md](../_shared/ui-options.md) before any drawing code. This adds
  a stop to the general skill's third gate: such a choice is asked, not settled
  as a judgment call.
- A new file the installed program reads at runtime is listed in
  `debian/install`, and a new runtime dependency is in `debian/control`
  (installed with apt, as every dependency is on this machine).
- A user-visible change is described in the README, and no README step is left
  describing the old behaviour.

### Section 5 and Section 6: Check it and run it

Section 5 is `<static-checks>`, including the build it asks for when packaging
could break. Section 6, apart from "Failures already on the default branch get
fixed", is replaced by this:

A change that touches `src/`, `bin/`, `packaging/` or `debian/` is run, per
[static-checks.md](../_shared/static-checks.md#then-a-run), as an isolated copy of
the widgets that belongs to this session, started from the checkout. The copy has its
own home, so its cache, config, pid file and window position are its own; its orchestrator
widget reads fixture Claude sessions and plays no sound; it has no tray icon, no
Spotify login and so sends no Web API request; and its windows have a class and a
position of their own, on the built-in display, so a copy never covers the monitor
the user works on. Any number of them run beside the user's copy and each
other, so a session never waits for another session's widget, and never stops,
replaces, restarts or captures one: the user's copy (installed, or from another
worktree) and every other session's copy are not this session's to touch, and
there is nothing to stop first. The script
(`scripts/isolated-widgets.py`) names the copy after the checkout folder, so each
worktree has one.

```bash
scripts/isolated-widgets.py start          # both widgets, from this checkout's src/
scripts/isolated-widgets.py status
scripts/isolated-widgets.py capture <scratchpad>/widget-after.png spotify   # or orchestrator
RUN=$(scripts/isolated-widgets.py path)/home/.cache
grep -iE 'error|critical|traceback|lua' "$RUN/conky-widgets/run.log"
grep 'api:' "$RUN/conky-spotify-nowplaying/nowplaying.log"      # must print nothing
scripts/isolated-widgets.py stop           # removes the copy and its files
```

`start` takes `spotify` or `orchestrator` to start one widget, `--at X,Y` for the position and
`--installed` to run the installed launcher instead of the checkout's (refused while the
installed widgets predate the window class suffix), which is how a change to how the program
finds its files is checked installed, as in `/release` step 4, without touching the user's copy. A visual change takes its before capture from an isolated copy of
`origin/main` (a second copy named for it, from a checkout of `origin/main`, with
`--name`), not from the copy on the desk, and its after capture from this session's copy, read with
the `Read` tool side by side.

The log should hold nothing but conky's startup chatter. The orchestrator widget shows three
fixture sessions (On, Alerts, Off); the Spotify widget shows whatever the Spotify app plays
now, read through `playerctl`, without a heart (no login). When nothing is playing, say so
and say what could not be looked at. Stop the copy when the run is done, and say in the
report that the copy was stopped and the user's was not touched.

A session never sends a Web API request of its own to test or debug: no `spotify_api.py
status` or `toggle`, no `curl`. The isolated copy has no token, so it sends none either; a
run that needs the heart or the library index to be seen is not run by a session, and the
report says what was left to the user.

### Section 7: Open the pull request

The general skill's second gate is void. Its first gate is the Section 6 run
above. The title is `<summary> (#<N>)`, with no type prefix. The body carries
`Closes #<N>`, what changed and why, a test plan that says what was actually
run and what was not, `Judgment calls` (each decision the issue left open, what
was chosen, what it beat and what decided it; none reads "none"), `UI choices`
when a look was put to the user per [ui-options.md](../_shared/ui-options.md)
(the page and the options picked), `Pre-existing failures fixed` (each, or
"none"), any open pull request touching the same files, by number, and the
`Self review` and `Settled decisions` sections the review fills in. Push with
`git push -u origin HEAD` and open it non-draft with the body passed as a file.

Bind the pull request to the session's PR bar: call `mcp__ccd_pr__get_status`
and, when it does not report it, `mcp__ccd_pr__bind_pr` with its URL. Then run
the mergeability check in `<mergeability-note>` and resolve any conflict before
going on. Never `gh pr merge`, and never commit to `main`. The user merges.

"Review it yourself before handing it over" follows `<self-review>`, whose
loop, minor findings and settled decisions are the general skill's. Every pass reads the
whole pull request at the branch head, not only the commits since the last
pass, per `<self-review>`. A fix owes `<static-checks>` in place of the
dispatches and the pull request check job, and the Section 6 run again when it
touches `src/`, `bin/`, `packaging/` or `debian/`. The general skill's "final
pass" of the checks is `<static-checks>` on the branch head once the review
ends, per [self-review.md](../_shared/self-review.md#when-it-ends).

### Section 9: Report

Void the paragraphs on skips, the skip ledger and deviations. Report instead
what was run and what it showed, anything not verified, the judgment calls
one line each, each pre-existing failure fixed, apart from the issue's own
changes, and, after a run from
the checkout, that the isolated copy was stopped. End with the ready
signal from `<ready-signal>`, which also puts the `Manual Review Needed` label
on the pull request. Then record the pull request with
`scripts/catchup.py add-pr` and leave the one `wait` running in the background,
per [run-watch.md](../_shared/run-watch.md#waiting-on-a-merge).

### Section 10: After the merge

Take the claim off the issue first and read it back, so a label left behind
(by a stop below, say) does not make every later session stand down:

```bash
gh issue edit <N> --remove-label "In Progress"
gh issue view <N> --json state,labels --jq '.state, [.labels[].name]'
```

Item 4 (leave the branch) is replaced: delete the branch on origin and locally,
leaving the worktree in place.

```bash
gh pr view <pr> --json state --jq .state      # must print MERGED
git status --short                            # must print nothing
git fetch origin
git switch --detach origin/main
git branch -D <branch>
git push origin --delete <branch>
```

The worktree lets go of the branch first, since git will not delete a
checked-out branch. `-D` because the check above already proved the merge,
whatever merge method the user picked. When `git status` lists anything, stop
before the switch: the worktree stays on its branch, nothing is deleted, and the
changes are reported.

Item 6 (archive the session) does not apply. `closed without merging` means the
user closed it: report it, take the label off the issue if it is still open, and
leave the branch alone.

## Added gates

`<static-checks>` before every push, and the UI options rule under Section 4.

## Repository notes

- [static-checks.md](../_shared/static-checks.md), [self-review.md](../_shared/self-review.md),
  [ready-signal.md](../_shared/ready-signal.md), [run-watch.md](../_shared/run-watch.md) and
  [ui-options.md](../_shared/ui-options.md).
- [/create-issue](../create-issue/SKILL.md), [/new-branch](../new-branch/SKILL.md) and
  [/release](../release/SKILL.md).
- [implement-with-speech](../implement-with-speech/SKILL.md), which runs this skill with
  speech on.
