---
name: implement-with-speech
description: >-
  Implement a GitHub issue exactly as /implement does, with every reply read
  aloud as it lands. Use when asked to implement an issue with speech -
  "/implement-with-speech 12", "work issue 12 out loud".
---

# Implement with speech

## Base

Read
[the general skill](../../att-docs/plugins/general/skills/implement-with-speech/SKILL.md)
first and follow it, except where this file overrides it. The general skill is the
vendored copy pinned by `.claude/att-docs.lock`; never edit it here.

## Paths

| Placeholder | Value here |
| --- | --- |
| `<speech-mechanism>` | The `voice` plugin's `speak-attention.sh` and its Stop hook, installed at user scope, under Overrides, Speech |
| `<voice-relay>` | The voice bridge, run from the `voice` plugin with this repository's [extension.json](../voice-bridge-hooks/extension.json) |
| `<reading-rules>` | The `spokenTerms` in that `extension.json`; questions, links and durations are read as the plugin's hook reads them |

## Overrides

### Speech

The `voice` plugin turns speech mode on when this skill starts, typed or called
through the `Skill` tool, and reads each reply aloud from its Stop hook. The
`Skill` call to `implement` resolves to [this repository's extension](../implement/SKILL.md).

### Say a thing once: the example

The example line reads "Waiting on PR 12 to merge." This repository has no
checks to wait on; what a session waits on is a pull request merge, a
Launchpad build, or a blocking issue, per
[run-watch.md](../_shared/run-watch.md).

## Added gates

None. Every gate is `/implement`'s.

## Repository notes

- [implement](../implement/SKILL.md), the skill this one runs.
- [voice-bridge-hooks](../voice-bridge-hooks/SKILL.md), the hooks and the bridge.
