# Putting UI options to the user

Shared by any session that has a layout, a control or a look to decide, inside
`/implement` or outside it. The user picks how a widget looks; a session never
settles a layout alone as a judgment call. The options are shown as a page the
user can look at, from the desk or the phone, and the choice is asked once the
page is up. This is done before any drawing or layout code is written.

## First, look at what is there

Look at which copies run, as `/implement` Section 6 does:
`pgrep -af 'nowplaying.py|speechqueue.py'`. A capture is taken as the widget
today only when the widget the change draws runs from the installed package
(`/usr/share`) or from a checkout whose `HEAD` is `origin/main`; a copy from any
other branch may show an unmerged change. Then capture it:

```bash
scripts/capture-widget.py <scratchpad>/mockup-source.png <widget>   # speech or spotify
```

and read it with the `Read` tool, so the mockups start from the widget as it is
drawn today: its colours, its fonts, its spacing and the rows around the part
that changes. This capture is only for the mockups; Section 6 still takes its
own before capture at the run. Read the drawing code for that part,
`src/<widget>/draw.lua`, and the colours and fonts in `src/common/theme.lua`, so
a mockup shows what the code can draw. Capturing only reads the window; it never
starts or stops a widget.

When there is no such copy, or the capture fails (the widget is hidden, or
only the other widget runs), do not start, stop or show one. Draw the mockups
from the code and the theme alone, and say on the page that no capture was
used.

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
`Judgment calls`, since the user made them. Section 6's after capture is read
next to the mockups of those options as well as its own before capture.
