# Overmind

These rules are for the `merph518/Overmind` repository itself. In a vendored copy under
`.claude/att-docs/`, ignore this file.

## Every pull request follows the implement procedure

The procedure in `.claude/skills/implement/SKILL.md` is the standard for every pull request
in this repository, whether or not it starts from an issue and whether or not a session
was asked to implement one. At the start of any change, before editing anything, read that
file and the general skill it builds on, `plugins/general/skills/implement/SKILL.md`, and
follow them. The section "Applies to every pull request" in the first file says which
steps to skip when there is no issue.

Two parts are easy to miss:

- The self review loop runs on every pull request, with an Opus review of every change,
  including the last fix. Section 7 sets the pass limit.
- When the loop ends, add the `Manual Review Needed` label and read it back. A pull request
  reported ready without the label is not ready.
