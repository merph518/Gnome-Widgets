---
name: implement
description: >-
  Implement a GitHub issue in Overmind end to end: read it, label it `In Progress`,
  work it in an isolated worktree, run the affected test files locally, open a linked
  pull request, review that pull request itself, then hand it to the user. Use when
  asked to implement, work on, pick up, or start an Overmind issue by number.
---

# Implement

## Base

Read [the general skill](../../../plugins/general/skills/implement/SKILL.md), which lives in this repository rather than in a vendored copy, first and follow it, except where this file overrides it.

## Paths

**Every question to the user goes through the `AskUserQuestion` tool. Never ask only in
reply text: the user does not see it there.**

| Placeholder | Value here |
| --- | --- |
| `<asking-note>` | Every question goes through the `AskUserQuestion` tool, never only in reply text, because the user will not see it there |
| `<in-progress-label>` | `In Progress` |
| `<ready-label>` | `Manual Review Needed` |
| `<preflight>` | In the main checkout: `node --version`, `python3 --version`, `gh --version` and `gh auth status` must succeed, and a change whose tests import `dotenv` also needs `node -e "require.resolve('dotenv')"` to succeed. On a failure, label the issue `Blocked` and comment with the failed command and its exact fix: `apt install nodejs` or `apt install python3` for a missing tool, GitHub's official apt repository with its signing key for a missing `gh`, `gh auth login` for authentication, `npm install` in the main checkout for `dotenv` |
| `<label-script>` | None. Under Overrides, Labels |
| `<labels-note>` | Under Overrides, Labels |
| `<area-label-rule>` | A title starting `[Tooling]` carries the `Tooling` label; add it when missing, under the same gate |
| `<reference-docs>` | `README.md` and `docs/` |
| `<ownership-unit>` | The folder the issue names: `plugins/<group>/skills/<name>/`, `plugins/voice/bridge/`, `plugins/<group>/hooks/`, or a root file |
| `<ownership-rules>` | Under Overrides, Section 3 |
| `<main-checkout>` | `~/Code/Overmind`, read-only |
| `<worktree-script>` | The `EnterWorktree` tool, under Overrides, Section 3 |
| `<edit-guard>` | The harness worktree guard, under Overrides, Section 3 |
| `<dependency-setup>` | `package.json` needs only `dotenv`. There is no lockfile, so run `npm install` in the worktree when a test imports it. `node_modules` is gitignored |
| `<shell-text-note>` | Under Overrides, Section 3 |
| `<branch-types>` | `feat`, `fix`, `chore`, `docs`, `ci` |
| `<default-branch>` | `main`. Never merge, never push to `main`, never force-push |
| `<follow-up-note>` | `gh issue create` in `merph518/Overmind`. When a write is refused, put the text in the pull request body under `Follow-ups` |
| `<sampling-note>` | Not applicable here, because nothing is dispatched; Section 6 below runs every affected test file |
| `<discovery-rules>` | Not applicable here, because there is no test data discovery |
| `<schema-source>` | Not applicable here, because there is no database schema to confirm |
| `<project-exclusion>` | Not applicable here, because there are no test projects |
| `<writing-rules>` | `repo-writing`, under Added gates |
| `<repo-constraints>` | None beyond the writing rules and the README rule under Repository notes |
| `<test-accounts>` | Not applicable here, because there are no test accounts |
| `<static-checks>` | Local checks, under Overrides, Section 5 |
| `<pr-checks>` | None yet: there is no `ci.yml`. Static checks are local |
| `<test-dispatch>` | Not applicable here, because nothing is dispatched. Tests run locally, under Overrides, Section 6 |
| `<test-run-rules>` | Not applicable here, because there are no test families or run counts |
| `<shared-env>` | Not applicable here, because there is no shared test environment |
| `<branch-age-note>` | Before opening the pull request and before marking it ready, merge `origin/main` into the branch when it is behind. Never rebase, and never force-push |
| `<run-watch>` | No run watcher, because nothing is dispatched. After the ready signal, wait for the merge with a background command that has no command substitution: `until gh pr view <n> --json state --jq .state | grep -qvx OPEN; do sleep 120; done; gh pr view <n> --json state --jq .state`. When working under `oversee-development`, record the opened pull request on its ledger with `bash plugins/general/skills/oversee-development/oversee.sh finish <N> done <pr> "<note>"`, where `<pr>` is the pull request number. Outside it, only that wait |
| `<baseline-rules>` | Not applicable here, because there is no baseline |
| `<artifact-read>` | Not applicable here, because there are no run artifacts |
| `<failure-snapshot>` | Not applicable here, because there are no failure snapshots |
| `<deviation-note>` | Not applicable here, because there is no app under test |
| `<deviation-records>` | Not applicable here, because there is no app under test |
| `<fix-cycle-budget>` | Three cycles on one failure, then record it on the issue and stop |
| `<investigation-log>` | Not applicable here, because no skill records red runs |
| `<mergeability-note>` | Under Overrides, Section 7 |
| `<self-review>` | Under Overrides, Section 7 |
| `<ready-signal>` | Under Overrides, Section 7, Ready signal. A pull request reported ready carries `Manual Review Needed`, read back |
| `<skip-ledger>` | Not applicable here, because there is no skip ledger |
| `<instructions-file>` | None: Overmind has no `CLAUDE.md`. The `README.md` is the standing reference |
| `<post-merge-checks>` | None |
| `<pairing>` | None |
| `<merge-cleanup>` | Nothing runs automatically. Removing the worktree after the merge, with `git worktree remove` from the main checkout, is the user's |

## Overrides

### Section 2, labels

There is no label script. Add a label with the response as the read-back; it lists the
issue's labels:

```bash
gh api repos/merph518/Overmind/issues/<N>/labels -f "labels[]=In Progress"
```

Remove one the same way:

```bash
gh api -X DELETE repos/merph518/Overmind/issues/<N>/labels/In%20Progress
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

An issue that cannot be worked now, because it waits on another issue, on something
only the user can do, or on code that is leaving this repository, gets the `Blocked`
label, added the same way as `In Progress`, and this session's `In Progress` comes off
it with the delete command above. The report names what blocks it, and so does
a comment on the issue when the harness allows one. In a loop over issues, read each
`Blocked` issue's comment again before stopping: when what it waited on has settled,
remove the label and take the issue up. `Blocked` here also covers an issue waiting on
another issue or pull request in this repository.

Cut the branch with the `EnterWorktree` tool, which creates `.claude/worktrees/<name>`
from `origin/main`, then rename it: `git branch -m <type>/issue-<N>-<slug>`.

The harness worktree guard blocks a write outside the worktree. It also refuses
`git -C`, `cd` into the main checkout, and complex shell constructs. Keep shell commands
simple, use absolute worktree paths, and put scripts and long text (commit messages,
pull request bodies) in files in the session's scratchpad directory.

### Section 5, static checks

There are no CI checks, so these run locally on the changed files before every commit:

- Every changed JSON file parses: `python3 -m json.tool <file>`.
- `node --check <file>` on each changed `.mjs` or `.js` file.
- `python3 -m py_compile <file>` on each changed `.py` file.
- `bash -n <file>` on each changed `.sh` file.
- A changed `SKILL.md` keeps valid `name` and `description` frontmatter.

The final pass in step 7 runs the same list on every file the branch changed.

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
- The body has, in order: `Closes #<N>`, Why, What changes, Verification (the static
  checks and each test file run with its result), Judgment calls, Pre-existing failures
  fixed, Overlap, Self review, Settled decisions, then the attribution lines the session
  gives.
- Never merge the pull request, never push to `main`, and never force-push. The user
  merges.
- `gh pr edit` fails on a Projects classic deprecation. Edit a body with
  `gh api -X PATCH repos/merph518/Overmind/pulls/<n> -F "body=@<file>"`.
- Mergeability: `gh pr view <n> --json mergeable,mergeStateStatus`. Resolve a conflict by
  merging `origin/main` into the branch, never by rebase plus force-push.
- Self review: Sonnet implements and Opus reviews every change, including the final fix.
  Spawn an Opus review agent on the diff, and run the `code-review` skill on the pull
  request number. Fix real findings and review again, for at most three passes. The
  fixes from the last pass still get an Opus review before the pull request is marked
  ready; this replaces the general skill's rule that the third pass's fixes get no
  fourth review. If that review finds another real bug, fix it, have Opus review that
  fix, and say in the report that the loop ran past three passes. A fifth pass that
  still finds a real bug stops the work and asks through `AskUserQuestion`.
- Ready signal: never leave the pull request in draft. When the loop ends, mark it ready
  with `gh pr ready <n>`, add the label through the issues endpoint, and read it back:

  ```bash
  gh api repos/merph518/Overmind/issues/<n>/labels -f "labels[]=Manual Review Needed"
  gh pr view <n> --json labels --jq '[.labels[].name]'
  ```

  A report that calls a pull request ready without the label reading back is wrong; fix
  the label first. A commit pushed after the label is a new change: remove the label with
  `gh api -X DELETE repos/merph518/Overmind/issues/<n>/labels/Manual%20Review%20Needed`
  (a 404 means it was not on yet) and add it again only once the review of that commit
  is clean.
- Ready check: at the start of every pass of a loop over issues, and before any final
  report, list the open pull requests that are not drafts and lack the label:

  ```bash
  gh pr list --state open --limit 200 --json number,isDraft,labels --jq '[.[] | select(.isDraft | not) | select(any(.labels[]; .name == "Manual Review Needed") | not) | .number]'
  ```

  Label this session's own pull request on that list once its review is clean. Report
  another session's only when its body already has a `Self review` section and no
  session holds it (`ListAgents`, the issue's `In Progress` label); one still in review
  is not yet ready.

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
runners: `tablet-runner-1` to `tablet-runner-4` (Linux) and `pw-ci-runner-desktop-1` to
`pw-ci-runner-desktop-5` (Windows). All nine carry the label `overmind`, so a job's
`runs-on` includes `self-hosted` and `overmind`; add `Linux` for a job that needs the
tablets alone. Never use a GitHub-hosted runner (`ubuntu-latest`, `windows-latest`,
`macos-latest` or any other), and never target `pw-windows-runner-1` or the
`pw-linux-runner-*` machines (label `playwright`). Before adding or editing a workflow,
confirm the names and labels with
`gh api orgs/merph518/actions/runners --jq '.runners[] | "\(.name) \(.status) \([.labels[].name] | join(","))"'`,
and before opening the pull request run `grep -rn runs-on .github/workflows` and check
every line against this rule. Only one session edits the workflows at a time: read the
open pull requests' files first, per Section 3.

### Releases

release-please reads conventional commits on `main`. Never bump a version, and never
edit `.release-please-manifest.json`, `CHANGELOG.md`, or a `plugin.json` version by hand.

## Repository notes

- A change that alters the layout or the extension contract updates `README.md` in the
  same pull request.
- Follow-ups that need a write the harness refuses go in the pull request body under
  `Follow-ups`.
