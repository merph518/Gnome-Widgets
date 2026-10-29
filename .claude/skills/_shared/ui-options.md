# Putting UI options to the user

Shared by any session that has a layout, a control or a look to decide, inside
`/implement` or outside it. The user picks how a widget looks; a session never
settles a layout alone and records it under `Judgment calls`. The options are
shown as a page the user can look at, from the desk or the phone, and the
choice is asked once the page is up. This is done before any drawing or layout
code is written.

## First, look at what is there

Capture the running widget with `scripts/capture-widget.py <scratchpad>/before.png
<spotify|speech>` and read it with the `Read` tool, so the mockups start from the
widget as it is drawn today: its colours, its fonts, its spacing and the rows
around the one that changes. Read the drawing code for the part that changes
(`draw.lua`, the `draw_*` functions) so a mockup shows what the code can draw.
Capturing is reading only; it never starts or stops a widget.

## The page

One Artifact, published with the `Artifact` tool (start with
`action: "quickstart"`, intent `other`), titled for what is being decided, such
as "Clickable Session Rows". It holds:

- A short opening: the issue number, what is being decided, and what stays as it
  is whatever the choice (a control keeping its clicks, say).
- One section per option, two to four of them, each a letter and a short name
  ("Option A, Issue number after the title"). Each draws a slice of the real
  widget in its own colours and fonts, with real content: the user's own session
  titles, repository labels and tags, not placeholders. Several rows, showing
  every state the change has (here: no issue, an issue, one pull request ready,
  several ready), and the pointer state drawn on one row where hovering matters.
- Under each option, a plain note of what it costs or gives up: room lost, a
  meaning it clashes with, data it needs that the widget does not have.
- A closing line with the recommendation and why, and where any data comes from
  when that is part of the choice.

The page is a mockup, not the widget: HTML and CSS that look like it are enough,
and it is never wired to anything on the machine.

## The question

Right after publishing, ask with `AskUserQuestion`, in the same turn:

- The question names the issue, the decision and the page's link, so it stands
  on its own on the phone.
- One option per section of the page, with the same letters and names, the
  recommended one first and marked `(Recommended)`.
- Each option's `description` says what it is and its cost in one or two
  sentences, and its `preview` is a few lines of text sketch of the row, so the
  choice can be made from the question alone.
- Decisions that are not about looks (where data comes from, say) are not put as
  separate questions when the page already says what the session will do; they
  go under `Judgment calls` as usual.

The answer is the layout. The pull request's `Judgment calls` names the page and
the option picked, and the after capture of the run is compared with the
mockup of that option.
