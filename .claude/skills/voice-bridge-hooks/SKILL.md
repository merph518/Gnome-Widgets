---
name: voice-bridge-hooks
description: The speech and voice tunnel hooks, run from the voice plugin with this repository's extension.json, which announce what a session needs, read replies aloud for /implement-with-speech, and feed the voice bridge the phone follows. Use when changing those hooks or their values, or working out why a session spoke, stayed quiet, or never reached the phone - "why did the stop not speak", "the ready announcement is wrong", "the phone missed that reply".
---

# Voice bridge hooks

## Base

Read
[the general skill](../../att-docs/plugins/voice/skills/voice-bridge-hooks/SKILL.md)
first and follow it, except where this file overrides it. The general skill is
the vendored copy pinned by `.claude/att-docs.lock`; never edit it here.

## Paths

| Placeholder | Value here |
| --- | --- |
| `<config>` | [extension.json](extension.json): the review label and its announcement, the ready line, the In Progress label, the start request and the spoken terms |
| `<hook-settings>` | The `voice` plugin's `hooks/hooks.json`, installed at user scope; this repository's `.claude/settings.json` registers none of them |
| `<entry-points>` | The plugin's own scripts. This repository keeps no shims |
| `<review-label>` | `Manual Review Needed`, per [ready-signal.md](../_shared/ready-signal.md) |
| `<ready-line>` | `PULL REQUEST <N> IS READY FOR YOUR REVIEW`, per [ready-signal.md](../_shared/ready-signal.md) |
| `<ledger-module>` | None. `scripts/catchup.py` keeps `label,key,link,state,tally` rows, not the run and branch rows the plugin's `transcript.py` reads, so `ledgerModule` and `scriptsDir` are left out of `extension.json` and a blocked session is not reported as waiting |
| `<bridge>` | The voice plugin's `voice-bridge.mjs`, run from the `~/Code/Overmind` checkout with `--config` naming this repository's `extension.json` |

The plugin runs from the plugin cache, except that its hook runner hands each
hook to the voice plugin folder the running bridge names, so the scripts follow
the `~/Code/Overmind` checkout. `hooks.json` still comes from the cache, so a pin
move that changes it is followed by `claude plugin update voice@att-docs`. A
change to the bridge itself goes to the Overmind repository.

## Overrides

None.

## Added gates

None.

## Repository notes

- [ready-signal.md](../_shared/ready-signal.md): the ready line and the label.
- [implement-with-speech](../implement-with-speech/SKILL.md): speech mode as a
  session sees it.
