# Self review

Shared by any pull request a session opens, inside a skill or outside one.
Ported from PlaywrightTesting's `self-review.md`. Before a session hands a pull
request to the user, it reviews the pull request itself, fixes every real bug the
review finds, and reviews it again until a pass finds none, or for at most
three passes. Only then does it send the ready signal from
[ready-signal.md](ready-signal.md). The user's review starts from a pull
request the session has already read as a reviewer, not as its author, and
found clean.

## When it starts

The self review starts once the pull request is open, the static checks in
[static-checks.md](static-checks.md) pass on the branch head, and the pull
request is mergeable, per [ready-signal.md](ready-signal.md). The review ends
in the signal.

## One pass

A pass always reads the whole pull request as it stands at the branch head,
not just the commits since the last pass. A fix can break something the fix
commit alone does not show.

1. Run the `code-review` skill on the pull request at `high`, with neither
   `--comment` nor `--fix`:

   ```
   Skill  skill: "code-review"  args: "high <pr-number>"
   ```

   Reviewing the pull request by number reads the diff as GitHub has it, which
   is the diff the user will read.
2. Read the diff once more against this repository's own rules, which a
   general review does not know:

   - `CLAUDE.md`, and the user's rule that software is installed with apt
     only: no `pip install`, snap, flatpak, AppImage or `curl | sh` in the
     README, a skill, or a script;
   - a new file the installed program needs at runtime that is missing from
     `debian/install`, or a new runtime dependency missing from
     `debian/control`;
   - a user-visible change the README does not describe, or a README step that
     no longer matches the code;
   - comments and log strings that describe history rather than how the code
     works now;
   - the pull request body: what changed, why, and a test plan that says what
     was actually run and what was not;
   - a look the change settles that the user did not pick: one the issue left
     open needs a `UI choices` section, per [ui-options.md](ui-options.md), and a
     fix that changes a look the user picked is put to them the same way
     rather than settled here.
3. Check every finding before acting on it. On every pass but the first, read
   the [Settled decisions](#settled-decisions) section first. Read the code the
   finding names; when running the program can settle it (an isolated copy, as
   in `/implement` Section 6, or the installed smoke test in `/release` step 4),
   the run settles it. A
   finding sorts into one of three kinds:

   - A real bug: it names a concrete way the change goes wrong that a real
     caller or real data can reach (a case that breaks, a path that only
     exists under `/usr`, a step skipped), or a rule it breaks that can be
     quoted from `CLAUDE.md` or a skill. It is fixed.
   - A minor finding: a nitpick, a cost with nothing behind it but taste (a
     duplicated helper, dead code), or an edge case that holds in principle
     but that nothing in this repository reaches. It is noted in the pull
     request body and left unfixed, per [Minor findings](#minor-findings).
   - A false positive: it does not hold up, including a preference with no
     cost behind it. Note it, with the reason. `code-review` at `high` is tuned
     to surface too much rather than too little, so this check is what lets
     the loop end.

## The loop

1. Run a pass.
2. No real bug holds: the loop is over. Go to [When it ends](#when-it-ends).
3. Otherwise fix every real bug, on the branch, rerun the static checks from
   [static-checks.md](static-checks.md), run the widget again when the fix
   touches `src/`, `bin/`, `packaging/` or `debian/`, and push. None is set aside for the
   user to pick up at review, and none is filed away for later.
4. Go back to 1, for at most three passes. The third pass's fixes get no
   fourth review: the static checks and the run for what they touch stand in
   for it, and the loop ends there.

Minor findings and false positives never keep the loop going.

### Minor findings

A minor finding is listed under the `Self review` heading with the pass that
raised it, so the user sees it at review, and is left alone. It owes no commit.

## Settled decisions

The pull request body carries a `Settled decisions` heading beside
`Self review`, written by the first pass whatever it found, with "none" under
it until a pass settles something. Every finding a pass sorts gets one line
there: a false positive, a minor finding, a real bug fixed, a judgment call a
pass makes on a finding, and a scope question the user answered, with the
answer quoted. Each line holds:

- the code it names, by file and the function, field or value at issue;
- what was decided, and the evidence that settled it: the line quoted, the
  rule quoted, the run that answered it, or for a fix, the commit that made it;
- the commit it was checked against: the commit the pass read, or for a fix,
  the fix commit.

A later pass reads this section before sorting a finding. A finding that makes
the same claim about the same code, unchanged since that commit, is settled and
does not count against a clean pass. A different defect in the same function, or
the same claim against code that has changed, is checked again from scratch.
`Judgment calls` keeps the decisions made while building the change, before
review.

A finding that holds but whose fix is the user's call, such as a scope line
the issue does not draw or two behaviours the README does not choose between,
is put to the user with `AskUserQuestion` rather than guessed at. The session
applies the answer and carries on with the loop. The question is not the
ready signal: the pull request is still not handed over.

The findings never go up as review comments on the pull request. Comments are
the user's review, and a thread the session opens on its own pull request only
pads the list the user has to read.

## The `Self review` section

The pull request body carries a `Self review` heading, updated after each
pass. It says how many passes ran, and lists each finding by pass: what it
was, and the commit that fixed it, or the reason it was a false positive. The
last pass is listed as clean, or, when it was the third, as ending the loop
with its fixes. A first pass that found nothing reads "one pass,
no findings" rather than dropping the heading.

Patch the body through the API from a scratchpad file, which sidesteps
`gh pr edit` failing on some `gh` releases and keeps the text out of shell
quoting:

```bash
gh api -X PATCH repos/{owner}/{repo}/pulls/<pr-number> -F body=@<scratchpad>/pr-body.md
```

## Commits after the handoff

Commits pushed after the ready signal, for the user's review comments or
anything else, send the pull request back through the loop, starting with a
full pass once the static checks pass. The signal goes out
again only on a pass that ends the loop.

## When it ends

The review ends on a pass that finds no real bug, or on the third pass, with the static checks passing
on the branch head and the pull request still reading as mergeable, per
[ready-signal.md](ready-signal.md#the-mergeability-check-comes-first). A
sibling branch can merge while the review runs, so read it again rather than
trusting the read from before. A conflict resolved at that point is a new
commit that owes the static checks and a look at the merge result, not a
further pass beyond the cap. Then the session sends the ready
signal, per [ready-signal.md](ready-signal.md).

The report above the signal says in a line or two how many passes ran and what
they found and fixed.
