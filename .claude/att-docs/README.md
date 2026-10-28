# Overmind

The base for my Claude Code skills, at
[merph518/Overmind](https://github.com/merph518/Overmind). Every skill I use lives
here once, in general form, and works without any particular repository. Each
repository I work in extends the skills it needs with a thin layer of its own: its
paths, its naming rules, its gates, its tracker. The skill itself is never edited in
the repository that uses it.

This repository is private and for my own use.

## The idea

- **One copy of each skill.** A fix or an improvement lands here and reaches every
  repository on its next pin move.
- **Repositories extend, never fork.** A repository keeps only what is true of that
  repository. Everything else defers to the general skill.
- **Stable by default.** A repository pins one release of this repository, so a
  change here never changes a repository's behavior until I move its pin.

## Skills

| Group | Skill | Purpose |
| --- | --- | --- |
| `att-docs` | `test-plan-from-doc` | Turn a functional spec document into a structured test coverage plan |
| `att-docs` | `living-wiki` | Keep a documents folder publishable as a code wiki |
| `att-docs` | `convert-docs` | Convert source documents into wiki-quality Markdown with provenance |
| `att-docs` | `doc-watch` | Compare a document library with the converted set and download what changed |
| `att-docs` | `doc-impact` | Find the test plans and rules a document revision affects, and file the issues |
| `att-docs` | `repo-writing` | Check shipped text against the wording rules and run the humanizer pass |
| `att-docs` | `acronym-guide` | Keep a dictionary of the acronyms the shipped Markdown uses and gate on undefined ones |
| `att-docs` | `business-rule-extract` | Extract the business rules from a document that has none yet |
| `att-docs` | `business-rule-scan` | Check every business rule against the document it came from |
| `att-docs` | `business-rule-update` | Update a document's rules and stage the result for review |
| `att-docs` | `alm-mirror` | Copy an ALM requirements folder into a database table |
| `att-docs` | `build-test-pack` | Build a test pack workbook for a change from its documents and rules |
| `general` | `implement` | Take an issue to a reviewed pull request: claim it, work it in a worktree, test, open the PR, review it |
| `general` | `implement-with-speech` | Run implement with every reply read aloud |
| `voice` | `voice-bridge-hooks` | Session hooks that read replies aloud, announce held stops, and relay voice requests |
| `voice` | `voice-request` | Answer a request the user spoke on their phone and the voice bridge relayed |

## Layout

```
.claude-plugin/marketplace.json   marketplace entry, for a machine that installs a plugin
plugins/<group>/
  .claude-plugin/plugin.json
  skills/<name>/SKILL.md          the general skill, plus any scripts it runs
  shared/                         helpers and notes that more than one skill uses
docs/<subject>/                   documents that have no place in the AZDO repository
package.json                      dependencies the shared scripts import
```

`docs/` holds the documents about the harness on the repository side: the runners and
their registration under `docs/runners/`, and the tester hand-off plan under
`docs/hand-off/`. A consuming repository reads them from its vendored copy, at
`.claude/att-docs/docs/<subject>/`.

Skills are grouped into plugins by subject. `att-docs` holds the documentation
skills, `general` holds the workflow skills that serve any repository (implementing
issues), and `voice` holds the voice bridge hooks and the skill that answers a relayed
request. `voice` is its own group so it can be installed at user scope without adding
a second copy of `implement`. Further groups sit beside them and
follow the same layout and the same extension contract. A group's `hooks/hooks.json`
registers hooks when the plugin is installed.

A skill links to a shared file with a relative path, `../../shared/<file>`. The link
resolves the same way from a vendored copy and from a plugin cache.
`${CLAUDE_SKILL_DIR}` is not substituted when a file is only read, so a link never
uses it.

The ALM helpers in `shared/` (`alm-client.mjs`, `alm-text.mjs`, `alm-stub.mjs`) are
configured by the caller: `configure({ base, domain, project, usernameEnvs })` runs
before any call.

## Requirements

The scripts need `python3`, `bash`, and Node with this repository's `package.json`
dependencies installed. `convert-docs` also needs `pandoc`.

## How a repository uses it

1. **Install by vendoring.** The whole repository is copied into the consuming
   repository at `.claude/att-docs/`. Scripts are called by a path in the tree,
   which keeps CI jobs and `node` module resolution working, and no token or
   submodule initialization is needed on a runner. A sync script does the copy: it
   fetches a tag, removes the old copy, and reads the tag's tree under the prefix.
2. **Pin by tag and tree.** `.claude/att-docs.lock` records the repository
   (`merph518/Overmind`), the tag, the commit SHA, and the root tree SHA of the
   snapshot. A check compares the tree of `.claude/att-docs` with the recorded one,
   so a hand edit to a vendored file fails offline. Moving the pin is one pull
   request that reruns the sync script.
3. **Extend by a same-name skill.** `.claude/skills/<name>/SKILL.md` in the
   consuming repository has the skill's name and a description that carries that
   repository's trigger words. Skill discovery reads only `.claude/skills`, so the
   vendored copy is never registered and the two cannot collide. A machine that
   also has the plugin installed at user level can disable it in the project
   settings so a second copy at a different version is not loaded.

The repository name is read from the lock, so a move or rename of this repository
changes one line there. A lock that still names an earlier location needs that line
updated before its next sync.

A repository that does not vendor installs the plugin instead:

```
/plugin marketplace add merph518/Overmind
/plugin install att-docs@att-docs
/plugin install general@att-docs
```

The `voice` plugin registers the voice bridge hooks. Installed at user scope
(`claude plugin install voice@att-docs --scope user`), it gives a session in any
repository the reply relay, spoken replies and attention announcements, with no hook
entries in the repository. A repository adds its own values with an extension file at
`.claude/skills/voice-bridge-hooks/extension.json`. See the `voice-bridge-hooks`
skill's Wiring section.

The voice bridge server itself is in `plugins/voice/bridge/` and runs from a checkout of
this repository: `node plugins/voice/bridge/voice-bridge.mjs --config <extension.json>
serve`. The extension file also names the bridge's repository values: `inProgressLabel`,
`mainBranch`, `reviewLabel` and `startRequest` (with `<N>` for the issue number). A field
left out keeps its default, and the repository the file sits in is the one the bridge lists
sessions under. `systemd/` holds the user units; their `--config` path names the repository
the bridge serves. `update_bridge` fast-forwards this checkout and restarts the unit, and
fast-forwards the served repository's checkout too when it is clean and on its main branch,
since that repository's scripts and tool module are what the bridge runs for it.

A repository adds tools of its own with `"bridge": { "module": "<path>" }` in the same file.
The bridge imports that module, relative to the repository, and calls its
`register(core)`, which returns `{ tools: [{ definition, call(args, context) }] }`. `core`
holds `repoRoot()`, the extension file's `extension` fields, and a `helpers` object with
the bridge's own `runFile`, `runGh`, `runGit`, `spawnCaptured`, `ghJson`, `takeReadBack` and
`readBackRefusal`, among others. `context` has the call's `paths`, `config`, `pages`, `now`,
`gh`, `git` and `tracker`, plus any option the caller passes. A repository with no module is
offered none of them.

## Extension contract

An extension `SKILL.md` has these parts, in this order.

1. Frontmatter with the same `name` as the general skill, and a `description`
   written for the consuming repository.
2. **Base.** One line: read the general skill at
   `.claude/att-docs/plugins/<group>/skills/<name>/SKILL.md` first and follow it,
   except where the extension overrides it.
3. **Paths.** The values the general skill leaves as placeholders: roots, lists,
   output locations, identifiers.
4. **Overrides.** Each override names the general skill's section it replaces and
   says what applies instead. A rule the extension does not name is the general
   skill's rule.
5. **Added gates.** Checks the repository runs before a commit, such as its own text
   scan or review steps.
6. **Repository notes.** Links to notes that stay in the consuming repository.

### Script config

A skill that runs a script takes its inputs from an `extension.json` beside the
extension, passed with `--config <path>`:

```json
{ "base": "<name>", "docsRoot": "docs", "dataDir": "...", "suites": [] }
```

A path in the config is relative to the git toplevel of the config file's folder.
Scripts read data only. A rule that needs judgment lives in the extension's prose,
not in the config. `--config` comes before a Python subcommand, and a missing config
exits 64.

Scripts that ship here:

- `convert-docs`: converter, page markers, credential scan, word list
- `doc-watch`: `docwatch.py`, `page.js`
- `doc-impact`: `docimpact.py`
- `repo-writing`: text scan, payload guard. Its shell scripts read their config
  through `config-read.py`, so they need only `python3`.
- `acronym-guide`: scan, dictionary writer, term verifier
- `living-wiki`: `wiki.mjs`
- `voice-bridge-hooks`: the hook scripts

### Shims

A repository keeps its existing entry points when other tooling calls them. Each
becomes a short shim that calls the vendored script with `--config`, so callers do
not change. A Python shim hands over with `os.execv`, a Bash shim with `exec bash`,
and a Node shim splices `--config` into `process.argv` and imports the script, so
the exit code and the script's own paths stay right.

## What lives where

| Belongs here | Stays in the repository |
| --- | --- |
| Skill procedure, written in general terms | Document and test layout, suite list |
| Helpers that name no repository path, tool, tracker, or hook | Tracker, CI, and review conventions |
| Scripts, taking their inputs from `--config` | Data files (dictionaries, banned terms, page maps) |
| Notes every repository needs | Notes about that repository's own tooling |

A helper that mixes the two is split. The general part takes the
repository-specific part, such as where to find credentials, as an argument from the
caller.

## Adding a skill

1. Write it in general form here, with every repository-specific value as a
   placeholder in a table at the top.
2. Move any script it runs here and make it read its inputs from `--config`.
3. Add it to the table under [Skills](#skills).
4. Tag a release and move one repository's pin to it.
5. In that repository, replace the local skill with an extension that follows the
   contract above, and confirm a dry run behaves as it did before.

## Releases

A release is a tag, `vMAJOR.MINOR.PATCH`. A repository pins one tag. Changes to the
extension contract bump the minor version while the version is below 1.0.
