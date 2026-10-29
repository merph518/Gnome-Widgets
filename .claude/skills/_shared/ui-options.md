# Putting UI options to the user

Shared by any session that has a layout, a control or a look to decide, inside
`/implement` or outside it. The user picks how a widget looks; a session never
settles a layout alone and records it under `Judgment calls`. The options are
shown as a page the user can look at, from the desk or the phone, and the
choice is asked once the page is up. This is done before any drawing or layout
code is written.

## First, look at what is there

Capture the widget being changed, `speech` or `spotify` (the script's default):

```bash
scripts/capture-widget.py <scratchpad>/widget-before.png speech
```

and read it with the `Read` tool, so the mockups start from the widget as it is
drawn today: its colours, its fonts, its spacing and the rows around the part
that changes. This is also the before capture `/implement` Section 6 compares
against, so it is not taken twice. Read the drawing code for that part,
`src/<widget>/draw.lua`, and the colours and fonts in `src/common/theme.lua`, so
a mockup shows what the code can draw. Capturing only reads the window; it never
starts or stops a widget.

When the widget is not running, the capture fails: do not start one. Draw the
mockups from the code and the theme alone, and say on the page that no capture
was taken.

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

The page is a mockup, not the widget: HTML and CSS that look like it are enough,
and it is never wired to anything on the machine.

## The question

Right after publishing, ask with `AskUserQuestion`, in the same turn:

- The question names the issue, the decision and the page by its title, so it
  stands on its own on the phone. The link goes in the turn's text just before
  the question, never in the question itself, because in speech mode the
  question is read aloud word for word.
- One option per section of the page, with the same letters and names, the
  recommended one first and marked `(Recommended)`.
- Each option's `description` says what it is and its cost in one or two
  sentences, and its `preview` is a few lines of text sketch of the row, so the
  choice can be made from the question alone.
- Decisions that are not about looks (where data comes from, say) are not put as
  separate questions when the page already says what the session will do; they
  go under `Judgment calls` as usual.

The answer is the layout. The pull request's `Judgment calls` names the page and
the option picked, and the after capture of the run is read next to the mockup
of that option as well as the before capture.
