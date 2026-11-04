---
name: oversee-development
description: >-
  Work the issues labeled `ready-for-agent` oldest first, one issue at a time per session,
  unattended, opening one review-ready pull request per issue and never merging anything.
  Use when asked to run through the backlog, work issues while the user is away, or keep
  implementing issues on a loop - "/oversee-development", "work the backlog", "keep going
  through the issues".
---

# Oversee Development

Runs the backlog as a conductor. The conductor works each issue through the `/implement`
skill, either itself through the Skill tool or by handing the issue to a subagent that runs
`/implement`. The queue and the ledger hold the state between issues, so a session that is
compacted partway through the backlog carries on from them rather than from the transcript.

Arguments, all optional:

- `/oversee-development` runs until the queue is empty or a stop condition hits
- `/oversee-development 5` runs the next five issues, then reports and stops
- `/oversee-development voice` narrows the queue to issues that carry that label as well as
  `ready-for-agent`
- `/oversee-development resume` re-reads the ledger and continues, queue as-is

`oversee.sh` below is the script in this skill's folder, the base directory the Skill tool
prints when the skill loads. Run it by that absolute path.

`oversee.sh` needs gh 2.94 or newer, because the queue reads each issue's blockers with
`gh issue list --json blockedBy`. `init`, `refresh`, `next`, and `start` stop with the install
fix when gh is older. `finish`, `swap`, `status`, `adopt`, and `withdraw` do not read
blockers and run on any gh, so finished work is still recorded.

## What this never does

Never merges, never pushes to `main`, never closes an issue, and never deletes a branch or a
worktree. Every issue ends as an open, non-draft pull request with a self review recorded in
its body and no conflict against `main`, waiting for the user. `gh pr merge` is not part of
this workflow at any point, including when a pull request looks obviously safe and including
when the user is asleep.

## State

Two files under `.claude/oversee/` in the main checkout, driven by `oversee.sh`. They are
gitignored and shared by every worktree, and they are the memory of this skill: the
transcript is not. A session that is compacted, interrupted, or killed resumes from these
files with nothing else.

```bash
oversee.sh init [label]            # build the queue, once
oversee.sh refresh [label]         # rebuild it from the live backlog
oversee.sh next                    # refresh, then what to work or why nothing is
oversee.sh start <issue> <branch>
oversee.sh adopt <issue>           # claim an orphaned in-flight issue
oversee.sh withdraw <issue>        # take back this session's own start
oversee.sh finish <issue> <done|stalled|skipped> <pr|-> <note>
oversee.sh swap <issue> <from> <to>  # move a label, read back
oversee.sh status                  # counts and the tail of the ledger
```

`start` tags its ledger row with the session's id and process id, from
`CLAUDE_CODE_SESSION_ID` and `CLAUDE_PID`. That tag is how several conductor sessions share
one queue: each holds its own in-flight issue and passes over the others'.

An issue's area is the word before the colon in its title (`voice: speechctl commands ...`
is area `voice`). Two issues in one area never run together, because they edit the same
folder: `next` defers the second until the first one's pull request is merged or closed.
A title with no such prefix has no area and is never deferred.

`next` prints one of these:

- `NEXT <issue> <area> <title>` work it
- `INFLIGHT <issue> ... branch <name> mine` this session's unfinished issue, resume it
  before anything else
- `INFLIGHT <issue> ... branch <name> orphan` an unfinished issue whose session has exited,
  adopt and resume it
- `ELSEWHERE <issue> ... branch <name>` in flight in another live session, printed for the
  record; its area is held until it finishes
- `DEFER <issue> ... area held by <PR or issue>` skipped this pass, printed for the record
- `DEFER <issue> ... blocked by #<n>` skipped this pass because an open issue blocks it,
  printed for the record; it is served once the blockers close
- `BLOCKED` everything left is deferred behind an unmerged pull request, an issue in flight
  elsewhere, or an open blocker
- `EMPTY` queue exhausted

## 1. Resume before anything else

Always start here, on every invocation, including the first.

```bash
oversee.sh status
oversee.sh next
```

`INFLIGHT` means a previous session never recorded the issue as finished. For a `mine` row,
first check with `ListAgents` whether a subagent of this session is still working the issue.
If one is, wait for its report and handle it as step 3 does, rather than resuming the issue a
second time. For an `orphan` row, run `oversee.sh adopt <issue>` first, so no third session
adopts it too. Do not restart the issue: find out how far it got, with two cheap calls and no
file reading.

```bash
gh pr list --head <branch> --state all --json number,state
git ls-remote origin "refs/heads/<branch>"
```

- A pull request exists: `finish <issue> done <pr> "resumed"`, move on.
- Branch pushed, no pull request: finish it with `/implement`, resuming from the existing
  branch rather than cutting a new one.
- No branch at all: `finish <issue> skipped - "session died before branching"`, swap the
  `In Progress` label off with `oversee.sh swap`, and let the queue serve it again later.

## 2. Build the queue

When `status` reports zero queued entries:

```bash
oversee.sh init          # or: oversee.sh init voice
```

`next` rebuilds the queue from the live backlog on every call, through `refresh`, so an
issue filed since the last call is in the queue it serves from. When the backlog read fails,
`next` says so on stderr and serves the last queue. The rebuild keeps every open issue the
ledger already names, whatever its labels: an issue in flight or waiting on an open pull
request still holds its area though `In Progress` would drop it.

A `skipped` issue is served again once the reason it was skipped is gone:

- a note starting `not workable at start:` names a label, a blocker, or a closed state, so
  the issue comes back once the live backlog lists it without an excluded label; it is then
  served only if it carries `ready-for-agent` and has no open blocker, like any other issue
- any other note comes back once every issue or pull request number it names is closed
- a note that names no other issue or pull request stays skipped, since nothing `next` can
  read says the reason is gone
- no skip comes back on a call whose backlog read failed

`done` and `stalled` rows and in-flight rows are never served again. When `next` prints
`BLOCKED` or `EMPTY`, that is the stop in step 5.

This reads issue numbers, titles, labels, and blockers. Nothing else. An issue's body is
read by `/implement` when that issue comes up, never all of them at once.

The queue holds only cleared issues, the ones labeled `ready-for-agent`.
`/oversee-development <label>` also requires that label, so an issue needs both. It drops
issues labeled `In Progress`, `Blocked`, `Tracker`, `Already Done`, `DO NOT MERGE`,
`question`, `wontfix`, `duplicate`, `needs-triage`, `needs-info`, `ready-for-human`, and
`invalid`, even when they also carry `ready-for-agent`, and orders what is left oldest
issue first, by issue number. An issue that is not cleared is never served, so a backlog
nobody has labeled ends the run at `EMPTY`.

An issue with an open blocker is not served. A blocker is another issue that GitHub's issue
dependencies list as blocking it, and it counts until that issue is closed. A `Blocked by:`
line in an issue body is not read. `next` prints a `DEFER` line naming the blockers and
serves the issue once they have all closed. The `Blocked` label is separate: it marks an
issue waiting on something it cannot get for itself, such as another issue or pull request,
a person, or a service. A person or the `implement` skill removes it.

## 3. The loop, one issue at a time per session

One issue worked at a time within a session, finished before the next. That keeps each pull
request reviewable. Other conductor sessions may work the same queue alongside, each with its
own one issue; `next` keeps them apart by passing over every issue in flight elsewhere and
deferring any issue in the same area.

For each `NEXT`:

```bash
oversee.sh start <issue> <type>/issue-<issue>-<short-description>
```

`start` reads the issue's state, labels, and blockers again, since the queue is a snapshot.
When the issue has closed, picked up an excluded label, lost `ready-for-agent`, or gained an
open blocker since, it records the issue as `skipped` and exits non-zero: run `next` again
rather than starting the issue. It also exits non-zero,
writing nothing, when another live session already started the issue: two sessions can read
the same `NEXT`, and the ledger lock lets only the first `start` through. Run `next` again
then too.

A session that started an issue and cannot work it after all, before any label or branch,
takes the start back with `oversee.sh withdraw <issue>`. That puts the issue back the way it
was before the start, so the queue serves it again, where `finish ... skipped` would record
a verdict on the issue.

Then run `/implement <issue>` on the branch `start` recorded, in this session with the Skill
tool or in a subagent. Run it in this session when the user is watching and may want to step
in, since a subagent's work does not show in the session; use a subagent to keep the
conductor's context small over a long queue. Follow that skill exactly, including its self
review of the pull request before the handoff. The self review runs at most three passes,
and only a real bug sends it round again: an unattended run that keeps reviewing past that
spends the time the next issue needed. When the work the issue asks for is already on main,
cut no branch and take the Already done path below.

A subagent loads `/implement`, not this skill, so the conductor writes these rules into the
prompt it gives the subagent, along with the issue number and the branch. The subagent gets
no transcript and reads the issue body itself. It runs none of the `oversee.sh` commands,
label swaps or issue comments that steps 3 and 4 give the conductor; the labels `/implement`
sets itself stay with the subagent. Where `/implement` would ask the user a question, the
subagent stops and puts the question in its report instead. Its report gives the pull
request number, the outcome (`done`, `stalled`, or `already-done`), and any such question.
It sends the report once `/implement` reaches its ready signal and does not wait for the
merge. The conductor waits for that report before it runs `finish` or `next`, and never has two
subagents working issues at once. To answer a question, the conductor asks it with
`AskUserQuestion` and sends the answer to the same subagent with `SendMessage`; when that
subagent can no longer be reached, a new subagent resumes `/implement` from the pushed
branch with the question and answer in its prompt.

When `/implement` hands the pull request off, the issue ends in one of these:

- `done`: an open pull request, self reviewed
- `stalled`: the work cannot be finished, see step 4
- `already-done`: the work is on main already, see below

A point where `/implement` asks the user a question is a pause rather than an end, and is
never recorded with `finish`. Ask with `AskUserQuestion`, carry on with `/implement` on the
answer, and record the issue only once it ends `done`, `stalled`, or `already-done`.

Record it in one ledger line, a note under 120 characters, and move on:

```bash
oversee.sh finish <issue> <status> <pr|-> "<note>"
```

A `done` issue with a pull request number is ready for the user. Put the
`Manual Review Needed` label on that pull request before running `next`, through the issues
endpoint (`gh pr edit` fails here on the classic projects lookup). The output is the
read-back, and the label is on when its name comes back:

```bash
gh api -X POST repos/{owner}/{repo}/issues/<pr>/labels \
  -f "labels[]=Manual Review Needed" --jq '[.[].name] | join(", ")'
```

When the user leaves feedback on one of the open pull requests, take the label off that pull
request at once, before starting the requested work. Do the work, and put the label back only
when it is ready again.

### Already done

An `already-done` issue has its work on main already. The conductor never closes it. It
labels the issue `Already Done` and says where the work went. Write a comment to
`$CLAUDE_JOB_DIR/tmp/done-<N>.md` (or the session scratchpad) naming the commits or pull
request that delivered it, with one line on what each delivers. Then:

```bash
oversee.sh swap <N> "In Progress" "Already Done"
gh issue comment <N> --body-file <path>/done-<N>.md
oversee.sh finish <N> done <pr|-> "already done: <note>"
```

The read-back is the gate: `Already Done` is one of the labels the queue drops, so an issue
that never got it would be served again.

Once an issue is recorded, do not go back to its branch or diff. The pull request body
carries the detail, and the user reads it at review time.

## 4. Park, do not block

An issue that cannot be finished, because what it needs is outside its scope or outside the
repository, ends `stalled` and the queue keeps moving. Write a one-line note on where it
stuck, plus the branch name, to a file with the Write tool, then:

```bash
oversee.sh swap <N> "In Progress" Blocked
gh issue comment <N> --body-file <path>/stalled-<N>.md
oversee.sh finish <N> stalled - "<note>"
```

The read-back is the gate: a park that dropped `In Progress` but never landed `Blocked` puts
the issue back in the queue it just stalled out of, and one that kept `In Progress` holds
the area against every other session.

A stalled issue may still have an open pull request, if `/implement` landed part of the work
and left the rest. That is a normal outcome, and the pull request number goes in the ledger
row either way.

## 5. Stop conditions

Stop the loop, write the final report, and stop starting issues when any of these is true:

- `next` prints `EMPTY` or `BLOCKED`, which it does only after reading the live backlog
- the `/oversee-development <n>` limit is reached
- three issues stall in a row, which means something systemic rather than three hard issues:
  a service is down or a credential expired
- `gh` stops authenticating

`BLOCKED` is not an error. It means every remaining issue is in an area an unmerged pull
request from this run already changed, is in flight in another session, or waits on an open
blocker. The next move belongs to the user: review and merge, close the blocker, or both,
then run `/oversee-development resume`.

`EMPTY` with open issues left usually means none carries `ready-for-agent`. Label the ones
that are ready for unattended work, then run `/oversee-development` again.

## 6. Report

One block at the end, short enough to read on a phone:

```
worked <n> issues, <d> done, <s> stalled
open for review: #112 (issue 110), #113 (issue 108), ...
stalled: issue 109, needs a credential the session does not hold
blocked: 4 issues behind open PRs in voice
```

Then `oversee.sh status` is the durable version of the same thing, and it survives this
session ending.

## Token discipline

**The queue reads titles, never bodies.** An issue's body is read when that issue comes up
and not before.

**Record an issue in the ledger before running `next`**, so a compaction between issues
loses nothing the next one needs.

**Nothing carries past an issue that the ledger cannot hold.** If a fact matters past the
current issue, it goes in the ledger note, the pull request body, an issue comment, or a
memory file.
