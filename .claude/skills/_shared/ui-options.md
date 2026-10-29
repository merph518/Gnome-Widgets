# Putting UI options to the user

Shared by any session that has a layout, a control or a look to decide, inside
`/implement` or outside it. The user picks how a widget looks; a session never
settles a layout alone as a judgment call. The options are rendered with the
real widget and shown on one Artifact page, which the user can look at from the
desk or the phone, and the choice is asked once the page is up. This is done
before the change itself is written.

## Render the options in the app

`scripts/render-option.py` draws an option with the real widget code, so the
user compares what the widget would put on screen, never a redraw of it. It
makes a temporary worktree of `origin/main`, applies the option's patch, runs an
isolated copy from it with fixture content, captures that copy's window and
removes both. Nothing of the user's own copy or another session's is read,
stopped or captured.

```bash
scripts/render-option.py <scratchpad>/today.png orchestrator            # the look as it is today
scripts/render-option.py <scratchpad>/option-A.png orchestrator --patch <scratchpad>/option-A.diff
```

The first call is the widget as drawn today, with its colours, fonts, spacing
and the rows around the part that changes; read it with the `Read` tool before
the options are drawn. The orchestrator copy shows fixture sessions, so a rendering of
it starts from those rows. The Spotify copy shows a card only while something is
playing.

Each option is a `git diff` against `origin/main` of the smallest change to
`src/` that draws it, written in a scratch worktree and never committed: read
`src/<widget>/draw.lua` and the colours and fonts in `src/common/theme.lua`, so
an option shows what the code can draw. A state the fixture rows do not have
(a session with a pull request ready, say) is added by the same patch editing
the fixtures in `scripts/isolated-widgets.py`, since the copy draws what they
hold. A pointer state cannot be rendered, as the pointer is the user's; it is
drawn as a text sketch in the question. The patch is throwaway; the real change
is written after the user answers, and may differ from it.

When the copy cannot be started or the capture fails (nothing is playing, so the
Spotify widget shows no card), say so and show the option as a few lines of text
sketch, on the page and in the question, instead; no redraw of it in CSS stands in for a rendering.

## The page

One Artifact, a plain HTML page published with the `Artifact` tool and titled
for what is being decided, such as "Clickable Session Rows". It is a page of
pictures to compare, not a design canvas, so the quickstart is called with
intent `other` and the page is written by hand. The pictures are the PNGs
`scripts/render-option.py` produced, embedded as they are, never a CSS redraw
of the widget. They go up as the page's `files` (`"published/name.png":
"<source>"`), and the page references them by the published path. A source must
be under the session's working directory; the tool refuses a path outside it,
such as a job directory under `~/.claude`. The dependable choice is an untracked
folder inside the session's worktree (`mockups/`), never added to a commit: copy
the PNGs there before publishing. The session's scratchpad works only when the
tool lists one. Name each file for its option and state (`2A-issue.png`). The
page holds:

- A short opening: the issue number, what is being decided, and what stays as it
  is whatever the choice (a control keeping its clicks, say).
- The widget as it is today, from the first render, so every option reads
  against it.
- One section per numbered decision, two to four options each, each a letter and
  a short name ("Option 1A, Issue number after the title"). Each option shows
  its picture or pictures, captioned with the number-letter and the name, once
  per state the change has, with real content from the fixture or the capture
  (the session titles and labels, or the track and artist playing), never
  placeholders. For #123 the states were a session with no issue, one with an
  issue, one with a pull request ready and one with several; for a Spotify
  change they might be playing, paused, idle and no cover art. The recommended
  option is marked. A picture that serves two options (they differ only where
  the pointer is, say) says so under it rather than being rendered twice. Where
  hovering matters, the pointer state is a text sketch beside the picture, as it
  cannot be rendered.
- Under each option, a plain note of what it costs or gives up: room lost, a
  meaning it clashes with, data it needs that the widget does not have.
- A closing line with the recommendation and why, and where any data comes from
  when that is part of the choice.
- For an option whose render failed, a few lines of text sketch in place of the
  picture, with a note that it is a sketch.

When the issue leaves more than one look open (where a badge goes, and its
colour), each is a numbered decision with its own options, named by number and
letter (1A, 1B, 2A). At most four decisions go to the user at once, as
`AskUserQuestion` takes four questions; more than that is split into pages
asked one after another.

Loose screenshots sent with `SendUserFile` are not the presentation; the page
is. The page is never wired to anything on the machine.

## The question

Right after publishing, ask with `AskUserQuestion`, in the same turn, one
question a decision on the page (the tool takes up to four):

- The question names the issue, the decision and the page, with its link, so it
  stands on its own on the phone: in some modes the voice bridge passes on the
  question alone. The speech hooks read a bare link as "the following link", so
  it costs a few words aloud.
- One option per option on the page, with the same names, the recommended one
  first and marked `(Recommended)`. Read aloud, a question carries at most its
  option labels, so each label carries the gist on its own ("A: number pill
  after the title", not "A").
- Each option's `description` says what it is and its cost in one or two
  sentences, and its `preview` is a few lines of text sketch of the row, for
  whoever answers on a screen. An option whose render failed says so in the
  question and is only a sketch.
- Decisions that are not about looks (where data comes from, say) are not put as
  separate questions when the page already says what the session will do; they
  go under `Judgment calls` as usual.

The answer is the layout. The pull request body names the page and the options
picked (1A, 2B) under its own `UI choices` heading, apart from `Judgment calls`,
since the user made them. Section 6's after capture, from the session's own
isolated copy, is read next to the pictures of those options as well as its own
before capture.
