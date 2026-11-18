---
name: repo-hooks
description: Reusable repository session hooks for pull request checks, ready-label checks, merge reminders, stray files, tests, formatting, and persistent implement loops. Use when wiring or configuring these hooks or diagnosing their behavior.
---

# Repo hooks

The `general` plugin registers repository hooks in its hooks module,
`hooks/register.tsx`. Their settings
are sections of `.claude/skills/repo-hooks/extension.json`. The stray-file and
implement-loop hooks run by default and accept `false` to turn them off; the other hooks
run only when their section is present.

The scripts are in `plugins/general/hooks/`, beside `register.tsx` and the runner
`run.sh`. Each has a `_test.sh` or `_test.py` beside it. The module hands each event to
`run.sh` with the event's JSON on stdin and reads the script's answer from its exit code
and stdout: exit 2 with a reason on stderr, or a JSON object (`hookSpecificOutput`,
`decision` and `reason`, `continue`, `systemMessage`). A PreToolUse payload is built
from the tool call; it has no `agent_id`, and its `transcript_path` and
`permission_mode` are the ones the session's last event gave. A script that fails with
any exit but 2 says so in the transcript and the event goes on. `register.test.tsx` tests the module
with `claude plugin test plugins/general`.

| Event | Matcher | Section and script | Timeout |
| --- | --- | --- | --- |
| PreToolUse | `Bash` | `prTestingGate pr_testing_gate.py` | 90 |
| PreToolUse | `Bash` | `--default-on strayFiles stray_files_gate.py` | 30 |
| PostToolUse | `Bash` | `mergeWatchReminder remind-pr-merge-watch.sh` | 10 |
| PostToolUse | `Edit\|Write` | `prettierOnSave prettier-on-save.sh` | 60 |
| PostToolUse | `Edit\|Write` | `testOnEdit test-on-edit.sh` | 180 |
| Stop | (none) | `readyLabelGate ready_label_gate.py` | 90 |
| Stop | (none) | `--default-on implementLoop implement_loop.py` | 30 |
| SessionStart | `startup\|resume\|compact\|clear\|fork` | `--default-on implementLoop implement_loop.py` | 30 |

While this session's oversee loop is active or paused, a row above the prompt shows its
state and scope with a Pause or Resume button. The row rereads the loop's marker at
session start, after each stop, after a Bash command that runs `loop.py` or
`oversee.sh`, and every 30 seconds while it shows. It reads nothing in a repository
with no `.claude/oversee/loops` folder.

## Wiring

Install the plugin and write the extension file:

```
claude plugin install general@att-docs --scope user
```

A repository that vendors this repository instead registers the vendored runner in its
own `.claude/settings.json`, once per hook, with the same matcher, timeout, section and
script that the table above gives it:

```json
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "Bash", "hooks": [
        { "type": "command", "timeout": 90,
          "command": "bash \"$CLAUDE_PROJECT_DIR/.claude/att-docs/plugins/general/hooks/run.sh\" prTestingGate pr_testing_gate.py" } ] }
    ]
  }
}
```

When a project's settings name `plugins/general/hooks/run.sh`, the plugin copy steps
aside for configured hooks. Default-on hooks step aside only when the settings register
that hook. A vendoring repository adds `plugins/general/hooks` and
`plugins/general/skills/oversee-development` to its copied paths for the loop hook.

The runner runs each script from the repository root (`CLAUDE_PROJECT_DIR`, or the
working directory) and hands it the extension file as `--config <file>`. A script run by
hand with a missing `--config` exits 64.

## The extension file

One JSON object. Each hook reads only its own section, and a path in it is relative to
the repository root.

```json
{
  "prTestingGate": {
    "checker": ["node", "--no-warnings=ExperimentalWarning", "--import", "tsx", "scripts/check-pr-testing.ts"],
    "checkerLabel": "npm run check:pr-testing -- <file>",
    "failureMarker": "The ## Testing section cannot be parsed"
  },
  "readyLabelGate": {
    "label": "Manual Review Needed"
  },
  "mergeWatchReminder": {
    "ledgerTool": "scripts/catchup.py"
  },
  "testOnEdit": {
    "testDir": "src/tests",
    "testName": "<name>.test<ext>",
    "extensions": [".ts"],
    "command": ["node", "--no-warnings=ExperimentalWarning", "--import", "tsx", "--test"],
    "tailLines": 10
  },
  "prettierOnSave": {
    "globs": ["*.ts", "*.tsx"],
    "command": ["npx", "prettier", "--write"]
  }
}
```

## PR testing gate

`pr_testing_gate.py`, PreToolUse on Bash, section `prTestingGate`. It reads the body
file of `gh pr create` or `gh pr edit` (`--body-file <path>`, `-F <path>`) and of
`gh api ... pulls[/<N>] -F body=@<path>`, runs the repository's checker on it, and denies
the call with the checker's output as the reason when the body fails. A body passed
inline that carries a `## Testing` heading is denied with a pointer at `--body-file`,
since the checker cannot read it. A body read from stdin is not checked. The hook sees
through `cd`, `NAME=value` and `export` earlier in the same command when it works out the
file's path.

Keys:

- `checker`, required: the checker as a list of words. The body file's path is added as
  the last word and the command runs from the repository root. Exit 0 means the body is
  fine, exit 1 means the Testing section is malformed, and any other exit means the
  checker could not read the file. Without a `checker` the hook lets everything through.
- `checkerLabel`: how a denial names the command, with `<file>` for the path. Defaults to
  the checker's words followed by the path.
- `failureMarker`: text the checker prints when it rejects a body. When set, an exit 1
  without it is reported as a checker that could not run (a missing dependency, for
  example) instead of a failed body.

## Ready-label gate

`ready_label_gate.py`, Stop, section `readyLabelGate`. When the session's final reply
says a pull request is ready for review and the turn opened or pushed to one, it reads
that pull request's labels with `gh`. A pull request without the review label blocks the
stop. The reason names it and gives the commands that add the label and read it back:

```
gh api repos/<owner>/<repo>/issues/<n>/labels -f "labels[]=Manual Review Needed"
gh pr view <n> --repo <owner>/<repo> --json labels --jq '[.labels[].name]'
```

With the label, with no pull request in the turn, or with a reply that does not report
one ready, the stop goes through. The section may be an empty object to take every
default.

The turn is everything after the last prompt the person typed; a background task's
notification or a message from another session does not start a new one. A pull request
counts as opened or pushed to when a Bash command in that turn is `gh pr create` (the
URL it printed on a line of its own), `gh pr ready <n>`, or `git push`, with or without
`gh -R <owner>/<repo>`. A push, or `gh pr ready` with no number, is looked up with
`gh pr list --head <branch>` for the branch checked out in the folder the push ran in:
the session's folder, moved by an earlier `cd` in the same command and by `git -C <dir>`.
A `cd` to a variable the hook cannot read leaves the folder unknown, and the lookup runs
in the repository root. `gh pr ready -R <owner>/<repo>` with no number looks in that
repository. A command that only mentions `gh pr create`, in a `grep` for example, does
not count. When the reply names some of the pull requests by number, only those are
checked. The final reply is the stop event's `last_assistant_message`, or the last text
the transcript holds for the turn.

A `gh` call that fails, or a `gh` that is not installed, lets the stop through with a
note in the transcript saying the label was not checked. A subagent's stop is not
checked. The hook still checks a stop that another hook already continued, such as the
oversee loop's, and caps the blocks instead: after `maxBlocks` blocks for one pull request
in one session, it only reports that pull request in the transcript.

Keys, all optional:

- `label`: the label a ready pull request carries. Defaults to `Manual Review Needed`.
- `readyPattern`: a regular expression, matched without regard to case, that marks the
  final reply as a ready report. Defaults to
  `\b(ready for (manual )?review|marked (it )?ready|review-ready)\b`. A match up to
  two words after `not`, `never`, `n't`, `will` or `'ll` does not count, so "not quite
  yet ready" and "will mark it ready" are not ready reports. An invalid expression falls
  back to the default with a note.
- `maxBlocks`: how many times one pull request may block a stop in one session. Defaults
  to 2.

When the ready-label gate and the implement loop both block one stop, both reasons reach
the model.

## Stray-file gate

`stray_files_gate.py`, PreToolUse on Bash, section `strayFiles`. It refuses three calls:
`git add -A`, `git add --all` and `git add .`; a `git add` that names a build artifact or
junk file, with or without `-f`; and a `git commit` while the index holds one. The denial
lists the files and says how to leave them out: `git restore --staged <path>`, a
`.gitignore` entry when the pattern is not ignored yet, and a note to the user of which
file was left out and why. A hook runs for a delegated agent's Bash calls too, so a
subagent's commit gets the same check.

Unlike the other hooks it runs in every repository: the runner takes `--default-on`, and a
missing extension file or section means every default. Set `"strayFiles": false` to turn
it off. A repository that vendors this one registers it as
`run.sh --default-on strayFiles stray_files_gate.py`.

Junk is a path with a folder, or the path itself, named `__pycache__`, `node_modules`,
`coverage`, `htmlcov`, `test-results`, `playwright-report`, `.nyc_output`,
`.pytest_cache`, `.mypy_cache`, `.ruff_cache` or `.idea`, or a file name matching `*.pyc`,
`*.pyo`, `.coverage`, `.coverage.*`, `.DS_Store`, `Thumbs.db`, `*.swp`, `*.swo`, `*~`,
`*.log`, `*.tmp`, `*.temp`, `*.orig` or `*.rej`. A file the repository already tracks is
left alone, and so is a staged deletion.

Keys, all optional:

- `patterns`: more junk, as globs. A word ending in `/` names a folder, a word with a `/`
  in it is matched against the whole path from the repository root, and any other word is
  matched against the file name.
- `allow`: globs for paths to let through although they match, matched against the whole
  path. A fixture that is a log on purpose goes here.
- `allowBulkAdd`: `true` to let `git add -A` and `git add .` through. The junk checks
  stay.

The checks read the repository the call runs in, moved by a `cd` earlier in the same
command and by `git -C <dir>`. A hook runs before the command, so a `git add <folder>` is
checked through git's own dry run, and `git add src && git commit` in one call is covered.
`git commit -a` also stages tracked files, which the gate does not look at.

## Merge-watch reminder

`remind-pr-merge-watch.sh`, PostToolUse on Bash, section `mergeWatchReminder`. After a
command that runs `gh pr create` and prints a pull request URL on a line of its own, it
adds a reminder to the session's context, one per pull request opened. It stays quiet for
a command that only mentions `gh pr create`, and for a URL buried in other output.

Keys, at least one of which must be set:

- `ledgerTool`: the repository's catch-up ledger script. The default wording tells the
  session to run `<ledgerTool> add-pr <ledger> <N> "<label>"` and to keep one
  `<ledgerTool> wait <ledger>` running in the background until the pull request merges.
- `message`: the whole reminder, replacing the default. `<N>` stands for the pull request
  number and `<ledgerTool>` for the tool. A repository whose ledger commands differ from
  the default, or whose reminder points at its own procedure, writes the full text here.

## Unit test on edit

`test-on-edit.sh`, PostToolUse on Edit|Write, section `testOnEdit`. For an edited source
file it looks for its test file under `testDir`, runs the test command on it, and puts the
last lines of the output in the session's context when the test fails. A passing run, a
file with no test file, an extension not listed, and a file outside the repository stay
quiet.

Keys:

- `testDir`, required: where to look for the test file.
- `command`, required: the test command as a list of words. The test file's path is added
  last.
- `testName`: the test file's name, with `<name>` for the edited file's name without its
  extension and `<ext>` for the extension. Defaults to `<name>.test<ext>`. The first match
  under `testDir`, in name order, runs.
- `extensions`: the edited files that have tests, with the dot. The longest match is
  stripped to make `<name>`. Defaults to `[".ts"]`.
- `tailLines`: how many of the last output lines a failure reports. Defaults to 10.

## Prettier on save

`prettier-on-save.sh`, PostToolUse on Edit|Write, section `prettierOnSave`. It formats an
edited file that matches a glob, when the repository has a Prettier config. A formatter
that fails never blocks the edit, and the hook prints nothing. The section may be an empty
object to take every default.

Keys, all optional:

- `globs`: bash patterns matched against the edited file's path from the repository root,
  where `*` also matches a slash. Defaults to `["*.ts", "*.tsx"]`.
- `command`: the formatter as a list of words. The file's path is added last. Defaults to
  `["npx", "prettier", "--write"]`.
- `configFiles`: the file names that count as a Prettier config, looked for in the edited
  file's folder and each folder above it up to the repository root. Defaults to the names
  Prettier reads (`.prettierrc` and its variants, `prettier.config.*`). A `package.json`
  with a `prettier` key also counts, whatever this says. A repository with no config at
  all gets no formatting.

## Persistent implement loop

`implement_loop.py` runs on `SessionStart` and `Stop`. It supplies the session ID,
restores an active loop's instructions, and continues that loop at a turn boundary.
Set `"implementLoop": false` to disable it. The loop's state, recovery, and commands
are described in `oversee-development`.

Vendoring repositories register both events using `--default-on implementLoop
implement_loop.py`, with the matchers in the table above. Registering only one
event leaves the plugin registration for the other in place.

## Tests

```
bash plugins/general/hooks/run_test.sh
bash plugins/general/hooks/remind-pr-merge-watch_test.sh
bash plugins/general/hooks/test-on-edit_test.sh
bash plugins/general/hooks/prettier-on-save_test.sh
python3 plugins/general/hooks/stray_files_gate_test.py
python3 plugins/general/hooks/implement_loop_test.py
python3 plugins/general/hooks/pr_testing_gate_test.py
python3 plugins/general/hooks/ready_label_gate_test.py
```

All of them need `jq`, and the Python tests need `python3`. None needs a repository's
own checker, formatter or test runner: they use stand-ins.
