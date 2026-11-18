---
name: implement
description: >-
  Implement a GitHub issue in Overmind end to end: read it, label it `In Progress`,
  work it in an isolated worktree, run the affected test files locally, open a linked
  pull request, review that pull request itself, then hand it to the user. Use when
  asked to implement, work on, pick up, or start an Overmind issue by number.
---

# Implement

## Applies to every pull request

This procedure is the standard for every pull request here, including documentation,
script and skill changes that start from no issue and sessions that were never asked to
implement one. `CLAUDE.md` at the root says so for every session.

A change with no issue skips the steps that need one: reading and claiming it, `issue-<N>`
in the branch name, `(#<N>)` in the title, `Closes #<N>`, the `Blocked` label on the
issue, and closing it after the merge. Name the branch `<type>/<slug>`, and treat the
folders from the `<ownership-unit>` row that hold the files the change touches as the
ownership unit when reading the board. The worktree (Section 3), the non-draft pull
request, the self review loop, and the `Manual Review Needed` label (Section 7) hold for
every pull request.

In this repository `/implement` is this full pull-request procedure: it builds code
changes with the `tdd` skill (see Test seams) and reviews every change with the
`code-review` skill (Section 7, Self review).

Exception to the non-draft rule above and the general skill's non-draft rule: a pull
request opened by the `implement-spec` skill (a user-scope skill that builds a whole
spec's issues on one integration branch) may stay a draft while its issues land. Its own
step 8 does not mark it ready: once its `code-review` pass ends, it goes through the
Section 7 self review loop, checks and the `Manual Review Needed` label, and Section 7
marks it ready. Its body has one `Closes #<N>` line per issue it closes.

## Harness substitutes

This procedure names tools that belong to one harness. When the harness lacks one, use
the substitute, and record each substitution in the pull request body under Judgment
calls, naming the tool missing and the substitute used:

| Tool named here | Substitute when it is absent |
| --- | --- |
| `EnterWorktree` | The Git fallback under Overrides, Section 3: a worktree at `.claude/worktrees/<name>` from `origin/main`. `.claude/worktrees/` is the one folder inside the main checkout that the main-checkout guard exempts |
| `AskUserQuestion` | The harness's own ask tool, with the same rule: never ask only in reply text |
| The Skill tool | Read the skill by its path under `.claude/skills/` or `plugins/*/skills/`, or by its `skill://<name>` URL, and follow it |
| `ListAgents` | Decide whether another session holds a unit or a pull request from the sources Section 3 lists: the issue's `In Progress` label, the open pull requests and their files, the oversee ledger and the file claims |

## Base

Read [the general skill](../../../plugins/general/skills/implement/SKILL.md), which lives in this repository rather than in a vendored copy, first and follow it, except where this file overrides it.

## Paths

**Every question to the user goes through the `AskUserQuestion` tool, or its substitute under
Harness substitutes. Never ask only in reply text: the user does not see it there.**

| Placeholder | Value here |
| --- | --- |
| `<asking-note>` | Every question goes through the `AskUserQuestion` tool, never only in reply text, because the user will not see it there. Without that tool, the harness's own ask tool, under Harness substitutes |
| `<in-progress-label>` | `In Progress` |
| `<ready-label>` | `Manual Review Needed` |
| `<preflight>` | In the main checkout: `node --version`, `python3 --version`, `gh --version` and `gh auth status` must succeed, `gh extension list` should list `cli/gh-webhook` (without it, `scripts/catchup.py wait` checks on its timer, so report it and go on), and a change whose tests import `dotenv` also needs `node -e "require.resolve('dotenv')"` to succeed. On a failure, label the issue `Blocked` and comment with the failed command and its exact fix: `apt install nodejs` or `apt install python3` for a missing tool, GitHub's official apt repository with its signing key for a missing `gh`, `gh auth login` for authentication, `gh extension install cli/gh-webhook`, run by the user, for the extension, `npm install` in the main checkout for `dotenv` |
| `<label-script>` | None. Under Overrides, Labels |
| `<labels-note>` | Under Overrides, Labels |
| `<area-label-rule>` | A title starting `[Tooling]` carries the `Tooling` label; add it when missing, under the same gate |
| `<reference-docs>` | `README.md` and `docs/` |
| `<ownership-unit>` | The folder the issue names: `plugins/<group>/skills/<name>/`, `plugins/<group>/hooks/`, or a root file |
| `<ownership-rules>` | Under Overrides, Section 3 |
| `<claim-script>` | `python3 plugins/general/skills/implement/claims.py`, under Overrides, Section 3 |
| `<main-checkout>` | `~/Code/Overmind`, read-only |
| `<worktree-script>` | `EnterWorktree` when available; otherwise the Git fallback under Overrides, Section 3, which cuts the worktree at `.claude/worktrees/<name>` from `origin/main` (see Harness substitutes) |
| `<edit-guard>` | The harness worktree guard when available; isolation is required without it, under Overrides, Section 3. The main-checkout guard exempts only `.claude/worktrees/`, so a fallback worktree goes there |
| `<dependency-setup>` | `package.json` needs only `dotenv`. There is no lockfile, so run `npm install` in the worktree when a test imports it. `node_modules` is gitignored |
| `<shell-text-note>` | Under Overrides, Section 3 |
| `<branch-types>` | `feat`, `fix`, `chore`, `docs`, `ci` |
| `<default-branch>` | `main`. Never merge, except a pin-only pull request under Added gates, Post-merge pin; never push to `main`, never force-push |
| `<follow-up-note>` | `gh issue create` in `merph518/Overmind-Mod`. When a write is refused, put the text in the pull request body under `Follow-ups` |
| `<sampling-note>` | Not applicable here, because nothing is dispatched; Section 6 below runs every affected test file |
| `<writing-rules>` | `repo-writing`, under Added gates |
| `<repo-constraints>` | None beyond the writing rules and the README rule under Repository notes |
| `<static-checks>` | Local checks, under Overrides, Section 5 |
| `<pr-checks>` | The `test-all` job in `.github/workflows/ci.yml` runs the static checks and the test files the change can affect (`scripts/select_tests.py` picks them) on a pull request and again on each push to its branch, and every test file on a push to `main`. The ready signal waits for it, under Overrides, Section 7, Ready signal. This replaces the general skill's wording that a pull request check runs static checks only: the local runs in Section 6 still go green before the pull request opens |
| `<test-dispatch>` | Not applicable here, because nothing is dispatched. Tests run locally, under Overrides, Section 6 |
| `<branch-age-note>` | Before opening the pull request and before marking it ready, merge `origin/main` into the branch when it is behind, and as soon as `<claim-script> sync` prints a file. Never rebase, and never force-push |
| `<run-watch>` | No run watcher, because nothing is dispatched. After the label, record the pull request on the session's ledger with `python3 scripts/catchup.py add-pr <scratchpad>/catchup.tsv <n>` and keep one `python3 scripts/catchup.py wait <scratchpad>/catchup.tsv` running in the background until it hands back with the merge, under Overrides, Section 7. When working under `oversee-development`, record the opened pull request on its ledger with `bash plugins/general/skills/oversee-development/oversee.sh finish <N> done <pr> "<note>"`, where `<pr>` is the pull request number. Outside it, only that wait |
| `<fix-cycle-budget>` | Three cycles on one failure, then record it on the issue and stop |
| `<mergeability-note>` | Under Overrides, Section 7 |
| `<self-review>` | Under Overrides, Section 7 |
| `<ready-signal>` | Under Overrides, Section 7, Ready signal. A pull request reported ready carries `Manual Review Needed`, read back. The recap's opening sentence is under Overrides, Section 9 |
| `<instructions-file>` | `CLAUDE.md` at the root, for the rule that every pull request follows this procedure. `README.md` for the layout and the extension contract |
| `<post-merge-checks>` | The post-merge pin, under Added gates: the release, the plugin update, and closing and merging the pin pull requests the automation app opens. It runs after the merge, not before the pull request is ready |
| `<pairing>` | None |
| `<merge-cleanup>` | Nothing runs automatically. Removing the worktree after the merge, with `git worktree remove` from the main checkout, is the user's |

Every placeholder this table does not list is not applicable here, because there is no
app under test, runner dispatch, baseline, shared test environment, test account, schema
source, test data discovery, skip ledger or deviation record. Overrides, Section 6 says
what runs instead.

## Overrides

### Plan and review

Each change goes through these steps, in order:

| Step | Produces |
| --- | --- |
| Planning and design advice, before any code is written | The approach, the files to change, the test seams, the risks, and the edge cases, acceptance checks, and open questions of the general skill's step 4 |
| Writing the code and its tests | The change, built from the plan |
| Reviewing every change, including the last fix | A list of real findings, or none |
| Fixing review findings | A fix that is itself reviewed |

Before coding, spawn an agent with the issue or task and the files it touches, and ask it
for the plan and design advice: the approach, the files to change, the test seams, the
risks, and the general skill's step 4 list of edge cases, acceptance checks, and open
questions. The session posts that list as the general skill's step 4 says, puts the
answers to its open questions in it, and passes it in full to every agent that builds
from it and to every review agent. Build from that plan and record in the pull request
body, under Judgment calls, any place the code departed from it. A fix for a review
finding is reviewed like any other change.

### Models

A step that asks for a model the harness will not let the session choose (a subagent
call that rejects a per-call model, for example) still runs, on the best model the
harness offers. Do not skip the step, and do not withhold the ready signal for this
reason alone. Record each such step in the pull request body twice: under Judgment calls
and under Self review, naming the step, the model wanted and the model used.

### Test seams

The plan names the test seams. This overrides the `tdd` skill's step of confirming
seams with the user: when the code is built with `tdd`, the seams the plan names count as
confirmed, so an unattended run does not stop to ask. A seam the plan did not name is
asked through `AskUserQuestion` (or, in a subagent, returned in its report).

### Section 2, labels

There is no label script. Add a label with the response as the read-back; it lists the
issue's labels:

```bash
gh api repos/merph518/Overmind-Mod/issues/<N>/labels -f "labels[]=In Progress"
```

Remove one the same way:

```bash
gh api -X DELETE repos/merph518/Overmind-Mod/issues/<N>/labels/In%20Progress
```

A label that does not exist is never created. If the add is refused for that reason,
stop and tell the user.

### Section 3, ownership and the worktree

The unit is the folder the issue names. Before branching, read the open issues labeled
`In Progress`, each open pull request's files, and the oversee ledger:

```bash
gh issue list --state open --label "In Progress" --json number,title,url
gh pr list --state open --json number,headRefName,body
gh pr view <n> --json files
bash plugins/general/skills/oversee-development/oversee.sh status
```

Another session holding the unit, or an open pull request already closing the issue (a
branch name containing `issue-<N>-`, or `Closes #<N>` in its body), means defer and pick the next
issue. An issue labeled `Tracker` is not worked itself; work its open child issues. An `In Progress`
label with no open pull request and no session holding it is stale: ask through
`AskUserQuestion` before taking the issue over.

Claims: the board above sees only open pull requests, so claim files before editing them,
per the general skill's "Claim shared files". Claims live in the main checkout's git
directory, so every worktree shares them. `claims.py` takes the session from
`CLAUDE_CODE_SESSION_ID`, then `PI_SESSION_ID`; a session with neither passes
`--session <id>` to every call. Pass `--pid <pid of the session>` too when it is known;
without a pid a claim goes stale after twelve hours, so release it when the work ends or
stops without a pull request. The files most often wanted by two sessions are `CLAUDE.md`,
`README.md` and the two implement `SKILL.md` files: claim one of them right before its
first edit and edit it in one pass.

An issue that cannot be worked now, because it waits on another issue, on something
only the user can do, or on code that is leaving this repository, gets the `Blocked`
label, added the same way as `In Progress`, and this session's `In Progress` comes off
it with the delete command above. The report names what blocks it, and so does
a comment on the issue when the harness allows one. In a loop over issues, read each
`Blocked` issue's comment again before stopping: when what it waited on has settled,
remove the label and take the issue up. `Blocked` here also covers an issue waiting on
another issue or pull request in this repository.

When `EnterWorktree` is available, fetch `origin/main`, then use the tool to create
`.claude/worktrees/<name>` from `origin/main`. Rename the branch in the worktree:
`git branch -m <type>/issue-<N>-<slug>`.

When `EnterWorktree` is unavailable, after the label read-back and ownership checks,
run these commands from the main checkout:

```bash
git fetch origin main
git worktree add -b <type>/issue-<N>-<slug> ~/Code/Overmind/.claude/worktrees/<name> origin/main
```

Keep the path under `.claude/worktrees/`: the main-checkout guard exempts only that
folder, so a worktree elsewhere inside the main checkout has its writes refused. Run the
second command only if the fetch succeeds. Use a new worktree name and branch; if creation
fails, stop rather than reuse either. For a change without an issue, use `<type>/<slug>` as
the branch name.
Run the base verification in the general skill's step 3, Cut the branch, before editing.
All subsequent file operations and commands target that worktree; the main checkout's
files and checked-out branch stay untouched.

The harness worktree guard, when available, blocks a write outside the worktree. It also
refuses `git -C`, `cd` into the main checkout, and complex shell constructs. Keep shell
commands simple, use absolute worktree paths, and put scripts and long text (commit
messages, pull request bodies) in files in the session's scratchpad directory.

A session that loads extensions from `.omp/settings.json` runs `guard-main-checkout.sh`
through `scripts/omp-guard-hook.mjs`, and nothing else: the outright refusal of `git -C`,
of a `cd` into the main checkout and of complex shell constructs above belongs to the
other harness. The guard follows `cd` and `git -C` only to find where a branch-changing
git verb acts. Such a session has no tool that moves it into the worktree: pass the
worktree as the `cwd` of every shell call and name its files by absolute path. The
operator's `/move <path>` or a launch with `--cwd <path>` rebinds the session itself.

### Section 5, static checks

These run locally before every commit, so a push does not wait on CI to find what a local
check would have shown:

- `python3 scripts/validate.py` checks the plugin and marketplace JSON, `SKILL.md`
  frontmatter, relative Markdown links, and the syntax of every `.py`, `.mjs`, `.js` and
  `.sh` file in the tree.
- Every other changed JSON file parses: `python3 -m json.tool <file>`. `validate.py`
  parses JSON only in the plugin and marketplace files.

The final pass in step 7 runs both, with `json.tool` on every JSON file the branch changed.

### Section 6, running the affected tests

There is no app under test, no test runner dispatch, no shared environment, no test
accounts, no schema source, no data discovery, no skip ledger, no deviation records, no
failure snapshot and no baseline. The dispatch, baseline, deviation gate and artifact
reading parts of step 6 do not apply, and neither does the deviation gate in step 7.
Wherever steps 6 and 7 wait on a green dispatch, they wait on these local runs instead.

Runtime verification is running the affected test files locally in the worktree:

- `node --test <file>.test.mjs`
- `python3 <file>_test.py`
- `bash <file>_test.sh` (this includes each hooks folder's `run_test.sh`)
- Find every test of a folder with `git ls-files <folder>`. Pass test files by name:
  running a directory fails.

Every test file next to a changed file, and every test file that imports a changed
shared module, must pass. A change with no test gets one when the code is executable.
A diff with no executable code (Markdown, JSON data) runs no test; the report says so.

### Section 7, the pull request

- Every commit subject on the branch is a conventional commit, `<type>: <summary>`.
  Pull requests here land as merge commits, so release-please reads each branch commit
  from `main`. The title follows the same form, and is the one commit release-please
  reads if the pull request is squash merged. Mark a breaking change to the extension
  contract with `!`.
- The body has, in order: `Closes #<N>` (one line per issue closed), Why, What changes,
  Verification (the static checks and each test file run with its result), Judgment
  calls, Pre-existing failures fixed, Overlap, Self review, Settled decisions, then the
  attribution lines the session gives.
  Tool substitutions (see Harness substitutes) are recorded in one place, Judgment calls.
  The `pr` skill may be loaded when a body is written; this section's order wins. The
  `pr` skill's Summary section goes under What changes and its before/after Evidence
  under Verification; its Merge Danger section (Door and Blast Radius) goes under
  Judgment calls.
- Never merge the pull request, never push to `main`, and never force-push. The user
  merges. The one exception is a pin-only bump pull request, under Added gates, Post-merge
  pin.
- `gh pr edit` fails on a Projects classic deprecation. Edit a body with
  `gh api -X PATCH repos/merph518/Overmind-Mod/pulls/<n> -F "body=@<file>"`.
- Mergeability: `gh pr view <n> --json mergeable,mergeStateStatus`. Resolve a conflict by
  merging `origin/main` into the branch, never by rebase plus force-push.
- Self review: every change is reviewed, including the final fix (see Plan and review
  above). Spawn a review agent on the diff, and run the `code-review` skill with
  `origin/<default-branch>` as its fixed point. Fix real findings and review again, for at
  most three passes. The fixes from the last pass still get a review before the pull
  request is marked ready; this replaces the general skill's rule that the third pass's
  fixes get no fourth review. If that review finds another real bug, fix it, have a review
  agent review that fix, and say in the report that the loop ran past three passes. A
  fifth pass that still finds a real bug stops the work and asks through `AskUserQuestion`.
  The body's Self review section names the model used for each pass, and for the
  review of the last fix, with the fallback from Models where a model could not be chosen.
- Ready signal: never leave the pull request in draft. When the loop ends, mark it ready
  with `gh pr ready <n>`. The label is added only when every check on the pull request has
  passed on the current head. Wait on the checks with `scripts/catchup.py`, which keeps a
  ledger of the runs and pull requests this session waits on. Use one ledger per session,
  `<scratchpad>/catchup.tsv`. After each push, record the `CI` run on the pull request's
  head commit, then start one `wait` as a background command:

  ```bash
  python3 scripts/catchup.py add-checks <scratchpad>/catchup.tsv <n>
  python3 scripts/catchup.py wait <scratchpad>/catchup.tsv
  ```

  `add-checks` reads the head from the branch, waits up to two minutes for its run to
  appear, and drops the row an earlier push left behind. Exit 1 means the pull request is
  not open or could not be read. Exit 3 means no run was found, and the message says why.
  On a conflict with the base, merge `origin/main`, push, and run `add-checks` again. When
  the conflict state is not yet worked out, run `add-checks` again at once. Otherwise
  check that the push landed (`git status -sb`) and run it once more. If it still finds
  no run, ask through `AskUserQuestion`. `wait` listens for GitHub's notices through
  `gh webhook forward` and checks on a timer when no notice comes. It hands back when a
  row finishes, and when a pull request it holds turns `conflicting`; a conflict is
  handled like the one above. For a finished run it prints the `test-all` tally, and for
  a failed run the error lines and the path of the saved log. `python3
  scripts/catchup.py check <scratchpad>/catchup.tsv` reads the ledger once without waiting.
  If `wait` has not handed back after thirty minutes (offline runners keep a run queued),
  read it with `check` and ask through `AskUserQuestion`. Merging `origin/main` into the
  branch, or any push, starts the checks again, so `add-checks` and the wait repeat after it.

  A check that fails is a real failure to fix, then the fix is reviewed and pushed
  like any other fix; the label stays off until the rerun passes. This holds for a docs-only
  branch too: `test-all` runs the static checks and the test files the branch can affect
  on every pull request, so a failure already on `main` that shows there is fixed here,
  and the body's Verification reports the CI result. A check that reads `cancel` (a newer
  push cancels the older run, and a run past its timeout reads the same) is not a pass:
  when the head is current, rerun it once with
  `gh run rerun <run-id>`, and ask through `AskUserQuestion` if it cancels again. Once
  every check reads `pass` on the current head, add the label through the issues endpoint
  and read it back:

  ```bash
  gh api repos/merph518/Overmind-Mod/issues/<n>/labels -f "labels[]=Manual Review Needed"
  gh pr view <n> --json labels --jq '[.labels[].name]'
  ```

  After the label reads back, record the pull request with `add-pr` and keep one `wait`
  running for the merge, per `<run-watch>`. When it hands back with `pr: <n>
  conflicting`, remove the label, merge `origin/main`, push, and start again from
  `add-checks`. A report that calls a pull request ready without the label reading back
  is wrong; fix the label first. A label on this session's own pull request whose checks
  are pending or red is wrong too: remove it. A commit pushed after the label is a new change: remove the label with
  `gh api -X DELETE repos/merph518/Overmind-Mod/issues/<n>/labels/Manual%20Review%20Needed`
  (a 404 means it was not on yet) and add it again only once the review of that commit
  is clean and its checks have passed.
- Ready check: at the start of every pass of a loop over issues, and before any final
  report, list the open pull requests that are not drafts and lack the label:

  ```bash
  gh pr list --state open --limit 200 --json number,isDraft,labels --jq '[.[] | select(.isDraft | not) | select(any(.labels[]; .name == "Manual Review Needed") | not) | .number]'
  ```

  Label this session's own pull request on that list once its review is clean and its
  checks have passed. Report another session's only when its body already has a
  `Self review` section and no session holds it (`ListAgents`, the issue's `In Progress`
  label); one still in review is not yet ready. Before any final report, also read
  `gh pr checks` for each of this session's own labeled pull requests, since a later
  "Update branch" merge or push can turn one red, and remove the label from one that is
  not passing. In a loop over issues, the wait runs in the background while the loop works
  the next issue; the next pass's ready check picks the pull request up when its checks
  finish.

### Section 9, the sidebar status

- The desktop app shows the first sentence of the session's last `mcp__ccd_turn__wrap_up`
  recap under its name in the sidebar. Open every recap, on any later turn too, with
  "Ready for Manual Review." while this session has opened at least one pull request that
  is still open, and every such pull request is not a draft, has the
  `Manual Review Needed` label read back, and passes `gh pr checks` on its current head.
  Merged or closed pull requests and another session's pull requests do not count.
  Otherwise open with what is true. The report still closes with the ready signal as
  before. Where the harness has no such recap tool, skip this rule.

## Added gates

### Shipped text

Skill and README text is vendored into work-side repositories. Before each commit, read
[repo-writing](../../../plugins/att-docs/skills/repo-writing/SKILL.md) and apply it to
what the diff adds. Shipped text never names this side's tracker issue numbers,
assistants or sessions (including in code comments), describes how things work now, and
uses plain American English. Overmind has no config for its scan scripts, so they are
not run here. Commit messages and the pull request body are exempt.

### CI runners

All CI in this repository, now and in the future, runs only on the owner's self-hosted
runners that carry the label `overmind`: `tablet-runner-1` to `tablet-runner-4` and
`pw-linux-runner-1` to `pw-linux-runner-6` (Linux), and `pw-ci-runner-desktop-1` to
`pw-ci-runner-desktop-5` (Windows). A job's `runs-on` includes `self-hosted` and
`overmind` and never names `playwright`. Add `Linux` for a job that needs a POSIX shell
(it lands on a tablet or a Linux Playwright runner) and `Windows` for one that needs the
desktops. Never use a GitHub-hosted runner (`ubuntu-latest`, `windows-latest`,
`macos-latest` or any other), and never target `pw-windows-runner-1`, which carries
`playwright` but not `overmind`. Before adding or editing a workflow,
confirm the names and labels with
`gh api orgs/merph518/actions/runners --jq '.runners[] | "\(.name) \(.status) \([.labels[].name] | join(","))"'`,
and before opening the pull request run `grep -rn runs-on .github/workflows` and check
every line against this rule. Only one session edits the workflows at a time: read the
open pull requests' files first, per Section 3.

### Post-merge pin

A pull request that changes functionality ends with a pin cut. The automation GitHub App
opens the pin pull request in every consumer listed in `.github/consumers.json` once the
tag exists (README, Pin pull requests), so this session never opens one and never hands
one to a session in another repository or to the user. It waits for them, closes the
superseded ones and merges the pin-only ones. The step runs after the merge, from the
wait in `<run-watch>`, for a pull request with or without an issue, and the work is not
done until it finishes or is skipped.

- **Skip** a pull request whose diff is only documentation (`README.md`, `docs/`, other
  Markdown that no skill reads) or only tests. A change to a `SKILL.md`, a script, a
  hook, a workflow, or a `plugin.json` changes functionality. Say in the
  final report that the step was skipped and why.
- **Cut the pin.** A pin is a release tag, and this session never tags. First read the
  newest tag with `git ls-remote --tags --sort=-v:refname origin 'v*'`, taking the first
  line that does not end in `^{}` and never using `gh release view`, because a tag can
  exist without a GitHub release. Keep it as the tag from before the merge. Then read
  the release workflow's run on the merge commit
  (`gh run list --workflow release.yml --commit <merge sha> --json conclusion,status,url`),
  waiting until that run appears and has finished or shows `skipped`, for up to thirty
  minutes, after which the run's link is reported and the step stops. A `cancelled` run
  is reported to the user with its link: stop there, run nothing below, and take
  neither branch below. Say that a newer push most likely replaced it and that the pin
  comes from the newer release run, so this session cuts none for this pull request. For any other result, take the branch that fits:
  - The workflow ran. Look for the open release pull request with
    `gh pr list --state open --head release-please--branches--main --json number,title`.
    When it lists this pull request in its changelog, ask the user through
    `AskUserQuestion` to merge it, because this skill merges only pin-only bump pull
    requests. When there is none, or it does not list this pull request, because the change merged as a type
    release-please ignores (it reads only `feat`, `fix` and `perf`), report that no pin
    was cut and why, and run nothing below. A failed run is reported the same way, with
    the run's link.
  - The workflow is skipped. The tag is cut by hand, an exception to the README's rule
    that holds only while the workflow is off, and any release pull request left open is
    ignored: ask the user through `AskUserQuestion` to cut it. The app's jobs run only
    from the release workflow, so a hand-cut tag opens no pin pull requests. Report that,
    with the README's repeat command for the user to run once the tag is pushed,
    `gh workflow run pin-consumers.yml -f tag=<new tag>`, which uses the App's secrets
    and which this session never starts. The repeat only redoes the app's own step; no
    bump is asked of anyone. Then update the installed plugins, skip the steps below that
    read, close or merge the pin pull requests for that tag, and run the one that reports
    a repository the app does not know. When the workflow runs again, resync the manifest
    to that tag, under Releases below.

  After the user answered the question about the release pull request or the tag, read
  the newest tag again. A merged release pull request is tagged only once the release run
  it starts has gone through its queue, so poll every minute for up to thirty minutes
  before deciding, and stop early when the release run on the release pull request's merge
  commit has completed with a conclusion other than `cancelled`; a cancelled run is
  replaced by a later one, so keep polling. After a hand-cut tag one read is enough, with no
  poll. For a release pull request, read its merge commit with
  `gh pr view <release pr number> --json mergeCommit --jq .mergeCommit.oid`, using the
  number from the `gh pr list` call above, and its run with
  `gh run list --workflow release.yml --commit <release merge sha> --json conclusion,status`.
  An empty merge commit means the user did not merge it: skip the poll. When the newest tag
  is still not above the one from before the merge, report that the pin was not cut and run
  nothing below.
- **Update the installed plugins.** Once the newest tag is above the one from before the
  merge, bring this machine's installed plugins to it, so the next new session lists the
  new skills. The update changes Claude Code's plugin folder through the `claude` command,
  not by editing files, which is the one exception to the rule below that this session
  writes only inside its worktree. Read
  `~/.claude/plugins/known_marketplaces.json` first.
  - When the `att-docs` source has a `ref`, the marketplace is pinned and an update stays on
    that tag. Run nothing, and report the README's remove, add and install commands to the
    user, because removing the marketplace uninstalls the plugins this session runs from.
  - Otherwise run `claude plugin marketplace update att-docs`, then
    `claude plugin update <name>@att-docs --scope user` for `att-docs` and `general`.
    Add the same update with `--scope project` or `--scope local` for each plugin that
    `~/.claude/plugins/installed_plugins.json` lists for the main checkout's path: from
    a worktree the command reaches the main checkout's entry, and no command reaches a
    worktree's own entry. For each other repository with entries in that file, report the
    same update commands, with that entry's scope, for the user to run there.
  - The update applies to sessions started afterward. Report what ran and its result.
- **Wait for the app, then find its pull requests.** The jobs start after the release run
  that made the tag, so wait for that run to finish. Read the tag's commit with
  `git ls-remote origin 'refs/tags/<new tag>' 'refs/tags/<new tag>^{}'` and take the last
  line: a lightweight tag has no `^{}` line, and an annotated one lists the commit it
  points to last. Then run
  `gh run list --workflow release.yml --limit 20 --json databaseId,headSha,conclusion,status,createdAt,url`
  and take the run that created the tag: the run whose `headSha` is the tag's commit, or,
  when that run was cancelled because a newer push replaced it, the earliest run created
  after it that is not cancelled. The tag exists once the `release-please` job finishes,
  while the pin jobs appear later, so wait for that run to reach `completed`
  (`gh run view <id> --json status,conclusion,jobs`) and only then read its jobs. A run
  that has not appeared within ten minutes, or has not completed within thirty because an
  offline runner leaves it queued, is reported, not waited for any longer. When the run
  never appeared, or has no `pin <consumer>` job that ran (it completed with a failed
  `pin-consumers / plan` job or with none, or it is still unfinished with its jobs not
  started), report what there is: the run's link or that none exists, the failed job when
  there is one, and the full rerun command
  `gh workflow run pin-consumers.yml -f tag=<new tag>`. Then skip the per-consumer reading
  and the close and merge steps for that tag; the report of a repository the app does not
  know and the final report still run. Otherwise the run has one job per consumer, with a
  name ending in `pin <consumer>`, and a job that is not `completed` counts as never
  finished. The consumers are `git show origin/main:.github/consumers.json`. For each
  consumer, read the open pull request for the tag:
  `gh pr list --repo merph518/<consumer> --head overmind/pin-<new tag> --state open --json number,title,url`.
  - A consumer whose job succeeded and has no open pull request was already on the tag or a
    newer one, or its pull request was merged or closed already. That is not a failure.
  - A consumer with no job in the run, for example one added to the file afterward, and no
    open pull request is reported with the rerun command below.
  - A consumer whose job failed, was cancelled, or never finished, and has no open pull
    request, is reported with the run's link and the rerun command
    `gh workflow run pin-consumers.yml -f tag=<new tag> -f consumer=<consumer>`; the others go
    ahead. This session starts the rerun only when the user asks. A consumer that has an
    open pull request is handled below whatever its job did.
  - A pull request from the branch `overmind/move-<tag>` moves a repository, not a
    release, and is left alone.
- **Report a repository the app does not know.** The app never sees a repository missing
  from `.github/consumers.json`, so list the owner's repositories with
  `gh repo list merph518 --no-archived --limit 100 --json name --jq '.[].name'` (raise the
  limit when it returns 100 names) and keep each one whose lock names Overmind:
  `gh api repos/merph518/<name>/contents/.claude/att-docs.lock -H "Accept: application/vnd.github.raw"`
  has a `repo=` line naming `merph518/Overmind-Mod` or an earlier location of it. A 404 means
  the repository does not pin Overmind. Read the list fresh each time. Report each one
  that pins Overmind and is not in the file, so the user can add it, except `AI-Health-Coach`
  and `TheRPGClub-bot`, which the file leaves out on purpose (`CLAUDE.md`, Other Repos). A
  listed repository that no longer pins Overmind needs no report: its job fails and the
  failure is reported above.
- **Close the pin pull requests it supersedes.** For each pin pull request found above,
  run `close_superseded_pins.py` from this skill's folder in the Overmind checkout (add
  `--dry-run` first to see the list):

  ```bash
  python3 .claude/skills/implement/close_superseded_pins.py <owner/repo> <new tag> <new pull request number>
  ```

  It requires the new pull request to be open with the new tag in its title. It then closes
  each other open pin pull request in that repository that targets an earlier version, with
  a comment naming the new pull request, and deletes its branch. It never closes the new
  pull request, a pin pull request for the same or a newer version, or a pull request whose
  title is not a pin bump, so a repository ends with one open pin pull request, the newest.
  A pull request it could not close, or whose branch it could not delete, is reported with
  the reason.
- **Merge each pin-only pull request once its checks pass.** This is the one exception to
  the rule that a session never merges. A pin-only pull request has a diff of only the
  lock, `.claude/att-docs.lock`, and the vendored files under `.claude/att-docs/`. The
  app's pull requests are that, and the code they bring in was reviewed in this
  repository, so they need no review, ready label or confirm. For each pin pull request
  found above, run `merge_pin_pr.py` from this skill's folder in the Overmind checkout, in
  the background, one per repository:

  ```bash
  python3 .claude/skills/implement/merge_pin_pr.py <owner/repo> <pull request number>
  ```

  A consumer moving its pin across a minor version checks its extension first, per the
  README's Releases section. Before running it for a consumer, read the tag that consumer
  pins on its default branch: the `tag=` line of
  `gh api repos/merph518/<consumer>/contents/.claude/att-docs.lock -H "Accept: application/vnd.github.raw"`.
  Drop any `\r` from the line. When the new tag's major and minor versions, compared as a
  pair, are above that tag's, do not run `merge_pin_pr.py` for that consumer: report its
  pull request as waiting on the user, with that reason. Do the same when the lock cannot
  be read or its tag is not `vMAJOR.MINOR.PATCH`, because an unknown tag is no proof that
  no minor version was crossed. Read the lock before the pull request merges.

  It reads the pull request again and acts only on a pin-only one: an open, non-draft pull
  request from a branch in the same repository into its default branch, with a pin title,
  whose changed files, and the files any rename moved from, are the lock and vendored
  files alone, with the lock changed, not removed or renamed, and naming the same
  repository as before, the title's tag, and the commit that tag points to. Any other
  pull request is left as it is (exit 2, verdict `review`). It waits up to an hour for the
  checks and for any branch rule blocking the merge to clear, giving each new head commit
  five minutes for its checks to start, and merges that commit when every check has
  passed, or when none has started, with the repository's allowed merge method, deleting
  the branch. A failing check, a wait still unfinished at the deadline, a conflict, a
  branch behind its base, a hundred checks or more, a pull request or lock it cannot read,
  or a refused merge leaves the pull request open with a comment saying why and the
  `Manual Review Needed` label, so it shows as waiting on the user (exit 1, verdict
  `flagged`). `--dry-run` judges the pull request
  as it stands, without waiting, and writes nothing.
- **Report** one line per tag, not per repository: the tag, how many repositories it
  merged in, and each pull request left waiting on the user with its reason, such as
  `v1.4.0 pinned in 6 repositories; Gnome-Widgets #12 waits on you, a check failed`.
  A consumer whose `pin` job failed, was cancelled or never finished, or that has no job
  in the run, and has no open pull request, is named on that line with the run's link and
  the rerun command, and the others still go ahead. When the run could not be read, the
  line says so, with the link and the rerun command. A repository the app does not know
  is named once.

### Releases

release-please reads conventional commits on `main`. Never bump a version, and never
edit `.release-please-manifest.json`, `CHANGELOG.md`, or a `plugin.json` version by hand.
The one exception is a resync: when a tag was cut by hand and the manifest is behind it,
a `chore:` pull request sets the manifest and the `plugin.json` versions to that
tag. It changes no other version.

## Repository notes

- A change that alters the layout or the extension contract updates `README.md` in the
  same pull request.
- Follow-ups that need a write the harness refuses go in the pull request body under
  `Follow-ups`.
