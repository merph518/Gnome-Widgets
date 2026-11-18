---
name: day-recap
description: >-
  Give an end-of-day recap across Overmind and every repository that pins it: what merged
  today, what is still open, and what needs the user, on screen or read aloud. Use when
  asked for an end-of-day recap, what happened today, or to wrap up the day - "/day-recap",
  "recap my day", "what got done today".
---

# Day Recap

## Base

Read [the general skill](../../../plugins/general/skills/day-recap/SKILL.md), which lives in
this repository rather than in a vendored copy, first and follow it, except where this file
overrides it.

## Paths

| Placeholder | Value here |
| --- | --- |
| `<recap-script>` | `plugins/general/skills/day-recap/recap.py`, run by its absolute path in the main checkout or the current worktree |
| `<recap-config>` | `.claude/skills/day-recap/extension.json`, which lists `repos`: Overmind (`merph518/Overmind-Mod`) and every repository in `.github/consumers.json`. The labels keep the general skill's defaults, which match this repository's |

## Overrides

None. Every rule is the general skill's rule.

## Added gates

None. The recap only reads.

## Repository notes

- [`.github/consumers.json`](../../../.github/consumers.json) names the repositories that pin
  Overmind. A repository added there is added to `repos` too, and `extension_test.py` in this
  folder fails until it is.
- `CLAUDE.md`, under "Other Repos", lists more repositories on this machine that are not in
  `consumers.json`. They are not in `repos`.
