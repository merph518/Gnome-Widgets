# conky-spotify-nowplaying

Everything a session waits on (a Launchpad build, a pull request merge, a
blocking issue) goes through `scripts/catchup.py` with one watcher per session.
How is in `.claude/skills/_shared/run-watch.md`.

Every pull request a session opens gets its own self review before it is
handed over, and ends in the ready signal. The loop is in
`.claude/skills/_shared/self-review.md`, the signal and its gates in
`.claude/skills/_shared/ready-signal.md`, and the static checks every push
passes in `.claude/skills/_shared/static-checks.md`.

A layout, control or look to decide is put to the user as a page of mockups
and a question, before any drawing code. How is in
`.claude/skills/_shared/ui-options.md`.

Issues are filed with `/create-issue`, titled `[<area>] <description>` and
labelled by area and kind. They are worked end to end with
`/implement <number>`: claim, branch, work, pull request, self review,
handoff, and cleanup after the merge.

The skills `implement`, `implement-with-speech` and `voice-bridge-hooks` are
thin extensions of the general skills in
[merph518/Overmind](https://github.com/merph518/Overmind), vendored at
`.claude/att-docs/` and pinned by `.claude/att-docs.lock`. The vendored copy is
never edited here; the pin moves with `scripts/overmind-sync.sh <tag>`.
