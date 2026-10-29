# Putting UI options to the user

Shared by any session that has a layout, a control or a look to decide, inside
`/implement` or outside it. The user picks how a widget looks; a session never
settles a layout alone as a judgment call. The options are shown as a page the
user can look at, from the desk or the phone, and the choice is asked once the
page is up. This is done before any drawing or layout code is written.

## First, look at what is there

The widget as it is today comes from an isolated copy of `origin/main`, never from
the copy on the desk: that copy may be the user's, or another session's unmerged
branch, and a session does not capture either. Start one from a checkout of
`origin/main` (a worktree or a temporary `git worktree add --detach` of it, removed
afterwards) under a name of its own, capture it, and stop it:

```bash
MAIN="main-$(basename "$PWD")"     # a name of this session's own
git fetch origin main
git worktree add --detach <scratchpad>/main-checkout origin/main
<scratchpad>/main-checkout/scripts/isolated-widgets.py --name "$MAIN" start <widget>
<scratchpad>/main-checkout/scripts/isolated-widgets.py --name "$MAIN" \
  capture <scratchpad>/mockup-source.png <widget>   # speech or spotify
<scratchpad>/main-checkout/scripts/isolated-widgets.py --name "$MAIN" stop
git worktree remove --force <scratchpad>/main-checkout
```

and read it with the `Read` tool, so the mockups start from the widget as it is
drawn today: its colours, its fonts, its spacing and the rows around the part
that changes. The speech copy shows fixture sessions, so a mockup of it starts from
those rows. This capture is only for the mockups; Section 6 still takes its
own after capture at the run. Read the drawing code for that part,
`src/<widget>/draw.lua`, and the colours and fonts in `src/common/theme.lua`, so
a mockup shows what the code can draw. Capturing only reads the copy's own window;
it never touches the user's copy or another session's.

When the isolated copy cannot be started or the capture fails (nothing is
playing, so the Spotify widget shows no card), draw the mockups from the code
and the theme alone, and say on the page that no capture was used.

## The page

One Artifact, a plain HTML page published with the `Artifact` tool, titled for
what is being decided, such as "Clickable Session Rows". It is a page of
mockups to compare, not a design canvas, so the quickstart is called with
intent `other` and the page is written by hand. It holds:

- A short opening: the issue number, what is being decided, and what stays as it
  is whatever the choice (a control keeping its clicks, say).
- One section per option, two to four of them, each a letter and a short name
  ("Option A, Issue number after the title"). Each draws a slice of the real
  widget in its own colours and fonts, with real content from the capture (the
  user's own session titles and labels, or the track and artist playing), never
  placeholders. Several rows or frames, showing every state the change has, and
  the pointer state drawn where hovering matters. For #123 the states were a
  session with no issue, one with an issue, one with a pull request ready and
  one with several; for a Spotify change they might be playing, paused, idle
  and no cover art.
- Under each option, a plain note of what it costs or gives up: room lost, a
  meaning it clashes with, data it needs that the widget does not have.
- A closing line with the recommendation and why, and where any data comes from
  when that is part of the choice.

When the issue leaves more than one look open (where a badge goes, and its
colour), each is a numbered decision on the page with its own options, named
by number and letter (1A, 1B, 2A). At most four decisions go to the user at
once, as `AskUserQuestion` takes four questions; more than that is split into
pages asked one after another.

The page is a mockup, not the widget: HTML and CSS that look like it are enough,
and it is never wired to anything on the machine.

## The question

Right after publishing, ask with `AskUserQuestion`, in the same turn, one
question a decision on the page (the tool takes up to four):

- The question names the issue, the decision and the page, with its link, so
  it stands on its own on the phone: in some modes the voice bridge passes on
  the question alone. The speech hooks read a bare link as "the following
  link", so it costs a few words aloud.
- One option per option on the page, with the same names, the recommended one
  first and marked `(Recommended)`. Read aloud, a question carries at most its
  option labels, so each label carries the gist on its own ("A: number pill
  after the title", not "A").
- Each option's `description` says what it is and its cost in one or two
  sentences, and its `preview` is a few lines of text sketch of the row, for
  whoever answers on a screen.
- Decisions that are not about looks (where data comes from, say) are not put as
  separate questions when the page already says what the session will do; they
  go under `Judgment calls` as usual.

The answer is the layout. The pull request body names the page and the
options picked (1A, 2B) under its own `UI choices` heading, apart from
`Judgment calls`, since the user made them. Section 6's after capture, from the session's own isolated copy, is read
next to the mockups of those options as well as its own before capture.
