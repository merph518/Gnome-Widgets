---
name: voice-bridge-hooks
description: The hook scripts that announce aloud what a session needs, read its replies aloud in speech mode, and hand its replies, questions and permission prompts to a voice bridge a phone follows. Use when wiring these hooks into a repository, changing what they say or when, or working out why a session spoke, stayed quiet, or never reached the phone.
---

# Voice bridge hooks

Scripts a session's hooks run. They speak the session's name and what it needs
when it stops, asks a question, or labels a pull request ready for review; read
each reply aloud while speech mode is on; and keep the files a voice bridge reads
to relay a session to a phone. The bridge itself is not part of this skill: it
reads and writes the files under `$XDG_RUNTIME_DIR/voice-bridge/` that
`voice_bridge_reply.py` describes.

The consuming repository's extension supplies the values below. Where it names
none, ask the user rather than guessing.

| Placeholder | Meaning |
| --- | --- |
| `<config>` | The extension's `extension.json`, which the scripts that read repository values take as `--config` |
| `<hook-settings>` | Where the hook commands that run these scripts are registered |
| `<entry-points>` | The paths the hook commands and the bridge call, when the repository keeps its own |
| `<review-label>` | The label the ready signal adds to a pull request |
| `<ready-line>` | The line a reply carries when a pull request is ready for review |
| `<ledger-module>` | The module that reads the run and pull request ledger a session waits on |
| `<bridge>` | The voice bridge that reads the files these scripts write |

## The scripts

All of them ship in this folder.

| Script | What it does | `--config` |
| --- | --- | --- |
| `speak-attention.sh` | Speaks on Stop, on an `AskUserQuestion` call, and when a Bash call adds `<review-label>`; reads replies aloud in speech mode; pushes a followed session's text to the bridge's feed | yes |
| `stop_attention.py` | Says what a stopped session needs from the user, or exits 3 to stay quiet | yes |
| `voice_bridge_reply.py` | Writes a stopped session's reply, its attention marks, its feed entries and its ready records for `<bridge>`, and answers a permission prompt with the answer the bridge relays | yes |
| `transcript.py` | Reads a session transcript; `blocked` prints the ledgers, issues and pull requests a session waits on | yes, for `blocked` |
| `ready_line.py` | Reads `<ready-line>` and a `<review-label>` add out of a reply and a command, imported by the three above | through its importer |
| `speak_pending.py` | Picks the text blocks a turn has not had read aloud yet | no |
| `background_pending.py` | Names the background work still due to wake a session, so a stop stays quiet | no |
| `hook_config.py` | Reads `<config>` | |
| `defaults.json` | The config for a repository with no extension file; the plugin's `hooks/run.sh` passes it | |

`--config <file>` comes first, ahead of a subcommand. A missing option, a missing
file, or a missing field exits 64. A module that imports `ready_line.py` or
`transcript.py` calls `hook_config.use(<file>)` first. Siblings are found beside
the script, so a script runs from this folder or from any copy of it.

## The config

`hook_config.py` lists every field. A path in the file is relative to the git
toplevel of the folder the file sits in.

- `reviewLabel`, `reviewAnnouncement`: the label, and the words spoken after
  "has pull request N" once a label add goes through.
- `readyLine`: `<ready-line>`, with `<N>` where the number goes. It is read in any
  case, with `#` or emphasis around the number.
- `spokenTerms`: words the voice would misread, such as acronyms, and how to say
  them.
- `scriptsDir`, `ledgerModule`: where `<ledger-module>` lives. It provides
  `read_ledger(path)`, whose rows carry `run`, `state`, `branch` and `title`, and
  `STATIC_CHECKS_NAME`, which starts the title of a pull request's checks row.
- `ledgerTool`, `ledgerSubcommands`, `dispatchTool`, `dispatchLedgerFlag`,
  `drivers`, `driverLedger`: the commands whose arguments name a ledger.

## What the scripts assume

- Pull requests are opened and labeled with a command line client whose create,
  edit and API calls `ready_line.py` and `voice_bridge_reply.py` recognize.
- Speech comes from Piper with a voice model when one is installed, else from
  Speech Dispatcher. A machine without `jq` and `python3`, or with neither
  speaker, stays quiet.
- Speech mode is turned on by the `implement-with-speech` skill and off by a
  typed `/implement`.

## Wiring

Register the hook commands in `<hook-settings>`, each calling a script, or its
entry point under `<entry-points>`, with `<config>`. A repository that keeps entry points at
its own paths makes each one a shim that hands over with `os.execv` or
`exec bash` and passes `--config`, so the process, its arguments, its input and
its exit code stay the hook's own.

### At user scope

The `voice` plugin registers every one of these hooks itself, in
`plugins/voice/hooks/hooks.json`, so a machine that installs the plugin at user
scope gets them in every repository without a hook entry in any of them:

```
claude plugin marketplace add merph518/Overmind
claude plugin install voice@att-docs --scope user
```

Each hook calls `hooks/run.sh`, which picks the config for the session's repository:

- `$CLAUDE_PROJECT_DIR/.claude/skills/voice-bridge-hooks/extension.json` when the
  repository has one. This is the path a repository's extension keeps its values at.
- `defaults.json` otherwise. It names a generic review label and ready line and no
  ledger, so the reply relay, the spoken replies and the attention announcements work and
  a session is never reported as waiting on a ledger.

A repository whose own `.claude/settings.json` or `settings.local.json` still registers
`voice_bridge_reply` or `speak-attention` keeps those hooks, and `run.sh` exits quietly
so no hook fires twice. A repository moves to the plugin by deleting its voice entries
and keeping its extension file.

Hook changes load when a session starts, so a session open during the switch keeps the
hooks it started with. The plugin runs from the plugin cache, not from a vendored copy,
so a pin move in a repository is followed by `claude plugin update voice@att-docs`. The plugin holds only this skill and
`voice-request`, so a session lists this skill once more as `voice:voice-bridge-hooks`
beside a repository's extension of it, and no copy of `implement`.

## Tests

From this folder, `python3 <script>_test.py` for each Python script and
`bash speak-attention_test.sh`. They read `test-config.json`, whose values are
examples, and `transcript_test.py` writes a stand-in ledger module into a scratch
git work tree.
