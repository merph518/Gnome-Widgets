# General coding standards

The rules that hold in every repository that vendors this one. A repository's own
`CODING_STANDARDS.md` links this file and adds only what is true of that repository.
Each line names a rule and, where one exists, links its source; the source is the
authority, not this file.

A rule in a repository's own `CODING_STANDARDS.md` overrides the rule here that it
contradicts. A documented rule, here or there, overrides the code-smell baseline. Anything
a repository's lint, type check or link check already enforces is not a review finding.

## Text

- Comments, skip reasons and log strings say how the code works now. They never name an
  issue, a pull request, a run or a session, and never contrast current behavior with what
  the code used to do:
  [what the text may never name and narrate](../../plugins/att-docs/skills/repo-writing/SKILL.md).
- Plain American English, and no em dashes:
  [words the reader would reach for and the prose-tell pass](../../plugins/att-docs/skills/repo-writing/SKILL.md).

## Code

- Follow the repository's lint and format configuration. After each change, run lint, the
  type check and the affected tests, and fix what they report.
- Keep source lines under 100 characters, unless the repository's formatter sets another
  width.
- Shared values (constants, flags, identifiers) live in one place. Look for an existing
  helper or constant before adding a new one, and do not repeat a magic number across
  files.
- Use no deprecated commands, functions or APIs. Check the framework's current
  documentation before writing against it, so the approach is not out of date.
- Never hand-edit generated output, such as a build folder, or a vendored copy. Regenerate
  the output, and move a vendored copy's pin with its sync script:
  [How a repository uses it](../../README.md#how-a-repository-uses-it).
- When a defect that was reported could have been caught by a lint rule, say so and propose
  the rule.

## Git and pull requests

- Work on a branch and open a pull request when the work is done. Never commit to the
  default branch directly:
  [Open the pull request](../../plugins/general/skills/implement/SKILL.md#7-open-the-pull-request).
- Use non-destructive git only. Never force-push, and never rewrite the history of a branch
  that is already pushed.
- Close each issue with its own `Closes #<N>` line in the pull request body. A list of
  numbers on one line is not reliably linked.
- Stage the files a change meant to touch by name, and keep build artifacts and junk out of
  the commit:
  [Before every commit](../../plugins/general/skills/implement/SKILL.md#before-every-commit).
- Never read `.env` files or other files that hold secrets.
