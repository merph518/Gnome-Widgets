# runner-health

Shows a row above the prompt when a self-hosted GitHub Actions runner needs attention.
While all is well, nothing shows. The plugin has no skills, only a hooks module,
`hooks/register.tsx`.

## What it does

The row names each problem and, where there is one, the command that fixes it:

- **A runner is stopped.** A runner service on this computer that is not running, such
  as `tablet-runner-2 is stopped: sudo systemctl start actions.runner.<org>.tablet-runner-2.service`.
  Two or more stopped services share one command that starts them all.
- **A runner is offline.** A runner on another computer that GitHub shows offline, such
  as `pw-ci-runner-desktop-3 is offline (another machine)`. There is no command, since
  the fix is on that computer. A service on this computer that has been running for 3
  minutes while GitHub still shows it offline gets the `systemctl restart` command.
- **A job waits for a runner.** A job that needs a runner with the watched label and has
  been queued for 10 minutes or more, whether the runners are offline or all busy, such as
  `merph518/Overmind-Mod job "CI / test-all" waiting 14 min for an overmind runner`.
- **A disk is low.** Under 5 GiB free on a disk the runners write to: the runners' work
  folders, which hold each job's checkout and temp folder, and `/tmp`.

Only runners that carry the watched label count, `overmind` by default; an offline runner
without it is left out. A busy runner is not a problem. Problems that do not fit the
width are counted at the end, as `+2 more`. The plugin never runs a fix itself.

## How runner state is read

The plugin reads two sources, because each sees something the other cannot.

- **This computer, every 15 seconds.** `systemctl list-units --all --plain --no-legend 'actions.runner.*.service'`
  lists the runner services and whether each is running. Each service's folder comes
  from `systemctl show -p WorkingDirectory`, and its `.runner` file there gives the
  runner's name and work folder. `df -P -k` reads the free space on each work folder and
  on `/tmp`. A service stopped by hand shows in the row within 15 seconds, long before
  GitHub marks the runner offline, and a service started again hides it as fast.
- **GitHub, every 2 minutes.** Through `gh api`, the plugin reads the organization's
  runners (`orgs/<org>/actions/runners`) and, for each watched repository, its queued and
  in-progress workflow runs and the jobs of those runs. This is the only way to see a
  runner on another computer or a job nobody picks up. The runners are registered to the
  organization, so the repository's own runners list is empty.

The GitHub answer is saved in `mods/.runner-health.json` in the Claude Code configuration
folder, and every open chat uses it until it is 2 minutes old, so several chats make one
set of calls. Right after a service starts, GitHub can still show its runner offline;
while the service has been running for less than 3 minutes, that is not shown.

### Token scope

Reading the organization's runners needs a token with the `admin:org` scope (on a
fine-grained token, the organization's "Self-hosted runners" read permission). `gh`
signs in without it by default. To add it:

```
gh auth refresh -s admin:org
```

### When runner state cannot be read

When there are no runner services on the computer and GitHub cannot be read, the row
shows one dim line that says why, such as
`Runner health: cannot read the runners: gh is not signed in: run gh auth login`. It does
not change from one check to the next, and after a failed call GitHub is not asked again
for 10 minutes. When only GitHub cannot be read, the services and disks on this computer
are still checked, and the reason is added to the row only while it shows a problem.

## Settings

Optional, in `mods/runner-health.json` in the configuration folder. Each value that is
set replaces its default:

```json
{
  "org": "merph518",
  "repos": ["merph518/Overmind-Mod"],
  "label": "overmind",
  "queuedMinutes": 10,
  "freeGiB": 5
}
```

- `org`: the organization whose runners are read.
- `repos`: the repositories whose queued jobs are checked, as `owner/name`. Each one adds
  two or more calls every 2 minutes.
- `label`: the runner label the jobs ask for.
- `queuedMinutes`: how long a job waits before it shows.
- `freeGiB`: the free space under which a disk shows.

## Turning it off

The plugin reads `mods/switches.json` in the configuration folder (`~/.claude`, or
`CLAUDE_CONFIG_DIR` when that is set) at each check:

```json
{
  "runner-health": false,
  "runner-health:hidden": true
}
```

- `"runner-health": false` turns the plugin off: no row and no checks.
- `"runner-health:hidden": true` hides the row; the checks go on.

`/mods` changes both. `/plugin disable runner-health@att-docs` turns it off as well.

## Install

```
claude plugin install runner-health@att-docs --scope user
```

Then run `/reload-plugins` in an open session. The checks need `systemctl` and `df`,
which Linux has, and `gh` signed in (`sudo apt install gh` from GitHub's apt repository).
Without `systemctl` only GitHub is read.

## Tests

```
claude plugin validate plugins/runner-health
tsc -p plugins/runner-health
claude plugin test plugins/runner-health
```

`tsc` needs the type declarations Claude Code writes to `.claude-plugin/types/` when it
loads the plugin from a working folder.
