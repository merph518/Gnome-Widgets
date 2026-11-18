# worktree-sweeper

Shows a band above the prompt when worktrees of the repository are done, and a pane that
removes them. The plugin has no skills, only a hooks module, `hooks/register.tsx`, and
the script it runs, `scripts/worktree-cleanup.sh`.

## What it does

- **Band.** When at least one worktree can go, a row above the prompt says so, such as
  `5 worktrees done · Review`. **Review** opens the pane.
- **Pane.** `/worktree-sweeper` opens it too. It lists every worktree besides the main
  checkout with the cells of the script's table: the worktree, its branch, the state of
  its pull request, the counts of uncommitted paths and unpushed commits, and the
  verdict, which is `remove` or `keep:` with the reasons.
- **Remove**, on each row marked `remove`, runs
  `worktree-cleanup.sh --remove-path <path>`. The script reads the worktree again and
  removes it with `git worktree remove` without `--force` only when it can still go. The
  branch stays. The line the script prints, `removed <path>` or `kept <path>: <reason>`,
  shows under the rows.
- **Remove all done** asks for a confirmation, then runs the same command for each row
  marked `remove`, one after the other, and goes on past a worktree it keeps.
- **Refresh** lists the worktrees again. **Close** closes the pane.

A worktree is never offered when this chat runs in it: the script keeps the worktree it
runs from, and the pane also holds back a row whose folder holds this chat's working
directory.

Removing a worktree deletes the files git ignores in it, such as `node_modules` or
`.env` files, along with it.

## The rules

The rules for what can go live in `scripts/worktree-cleanup.sh`, and the pane shows the
script's own verdicts. A worktree can go when its pull request merged, it has no
uncommitted or untracked file, every commit on it is at or below the head the pull
request merged, and it is not locked or missing. A pull request state the script cannot
read is never a reason to remove. See the comment at the top of the script.

The script also runs by hand:

```
bash scripts/worktree-cleanup.sh             # the table
bash scripts/worktree-cleanup.sh --remove    # ask about each worktree that can go
bash scripts/worktree-cleanup.sh --tsv       # the rows, split by tabs, with the absolute path last
bash scripts/worktree-cleanup.sh --remove-path <path>
```

## When it lists

Listing asks GitHub about each worktree's pull request, so it does not run on every
turn. It runs when the chat starts, every ten minutes, when the pane opens, on
**Refresh**, and after a removal. A request to list made while a listing or a removal runs
waits for it and lists once more afterward; the Remove buttons are not shown while
either runs. A listing that fails shows why in the pane, and
nothing is offered until a listing succeeds.

The script runs from the chat's project folder and needs `git`, `gh` (signed in) and
`jq`. Without `gh` or `jq`, every row reads `pull request state unknown` and nothing is
offered.

## switches.json

The `mods` plugin's pane writes `<config>/mods/switches.json`, which this plugin reads
every 3 seconds:

- `"worktree-sweeper": false` turns it off: no listing, no band, and the pane says it is
  off.
- `"worktree-sweeper:hidden": true` hides the band and stops the ten-minute listing. The
  pane still opens with `/worktree-sweeper`.

**Reopen** in `/mods` writes `<config>/mods/.open-worktree-sweeper-<session id>`, which
opens the pane and is removed.

The timers that read switches.json, look for that file and list every ten minutes start
when the chat starts. After the plugin reloads in the middle of a chat they wait for the
next chat; `/worktree-sweeper` still works.

## Install

```
claude plugin install worktree-sweeper@att-docs --scope user
```

## Tests

```
claude plugin test plugins/worktree-sweeper
bash plugins/worktree-sweeper/scripts/worktree-cleanup_test.sh
```
