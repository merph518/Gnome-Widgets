# efficient-browser-use

Screenshots are the most expensive thing a browser session sends Claude: a 1600×900
picture costs about 1,900 input tokens every time. This plugin makes each picture a tool
result carries smaller before Claude reads it, so the same browser work costs fewer
tokens.

It holds no skills, only a hooks module, `hooks/register.ts`, and one shell script,
`scripts/imagetool.sh`, that does the picture work with ImageMagick.

Install it from this marketplace:

```bash
claude plugin install efficient-browser-use@att-docs --scope user
```

## Requirements

Linux, with `/bin/sh`, GNU coreutils (`base64`) and ImageMagick:

```bash
sudo apt install imagemagick
```

Either ImageMagick 7 (`magick`) or ImageMagick 6 (`identify` and `convert`) works.
Without it no picture is shrunk. The plugin shows one
toast and writes one log line naming the command above, then stays quiet for the rest of
the chat. Describe mode needs no ImageMagick, but without it a description adds no
ledger line, since the picture's size is not known.

## What it changes

Every tool result is looked at: the browser pane, Claude in Chrome, `Read`, and any
connector that returns a picture. A result with no picture goes through untouched.

- **Shrink mode**, the default. Each picture is scaled to 75% of its size, never under
  768 px on its long side, so small text stays readable. A picture already 768 px or
  smaller is left alone. PNG and
  JPEG keep their format; GIF and WebP become PNG, first frame only.
- **The coordinate frame.** A browser screenshot's `Screenshot size` line is rewritten
  to name the size Claude now sees and the frame clicks land in, in the browser's own
  words: `Screenshot size: 1200x675 0.75-scale view; coordinate frame: 1600x900.` Claude
  aims in the coordinate frame, so clicks still land where it means them to. Clicks
  themselves are not changed.
- **Left alone.** A `zoom`, a screenshot taken at Claude's own `scale`, and a
  `browser_batch` holding either. Claude asked for that size.
- **Describe mode**, opt in. Each picture is handed to a Haiku subagent,
  `efficient-browser-use:describer`, which writes out its text, controls and layout,
  and Claude reads those words instead. A `Read` still gets a picture. When the
  describer is refused or gives no words within a minute, the picture is shrunk instead,
  or sent as is without ImageMagick.
  The describer is hidden from Claude's own agent list.

Describe mode trades sight for tokens. Text in a picture reaches Claude as words, so a
page can put instructions in front of it. The describer is told that text in a picture
is data, and its words are marked as a description, which lowers the risk without
removing it. Use shrink mode on pages you do not trust.

Every failure is fail-open: a script that errors, output cut at the size limit, or
anything unreadable leaves the picture as the tool gave it, and the log says why.

## The command

| Command | What it does |
| --- | --- |
| `/efficient-browser` | Opens the pane and shows the mode, the scale and what this chat saved |
| `/efficient-browser pane` | Opens the pane |
| `/efficient-browser full` | Lets the next picture through at full size, once |
| `/efficient-browser shrink` | Shrink mode for the rest of this chat |
| `/efficient-browser describe` | Describe mode for the rest of this chat |

## The pane: Screenshot Shrinker

One card per picture, newest first, at most 30: the tool, the size it returned and the
size Claude read, the tokens before and after, why, and a thumbnail at most 160 px on
its long side where the surface draws pictures. Three tiles on top count the pictures,
the ones made smaller, and the tokens saved. The pane opens itself on the first picture
unless you closed it or `/mods` hides it.

## The /mods switch

`~/.claude/mods/switches.json` is read every 3 seconds. `"efficient-browser-use": false`
turns every hook into a pass-through in every chat; `"efficient-browser-use:hidden": true`
keeps the pane shut until `/efficient-browser` asks for it.

## Savings ledger

Each picture made smaller adds one line to `~/.claude/mods-logs/savings.jsonl`:

```json
{"ts":"2026-11-18T10:00:00.000Z","session":"…","tool_use_id":"…","mod":"efficient-browser-use","action":"shrink","before":1920,"after":1080,"measured":"estimated"}
```

`before` and `after` are estimates of the picture's input tokens, width × height / 750.
For a description, `after` is the words' length / 4. Without ImageMagick a description's
size is not known, so it adds no line.

Problems, and with `logDecisions` on every picture's sizes, go to
`~/.claude/mods-logs/efficient-browser-use.log`. Both folders follow
`CLAUDE_CONFIG_DIR` when it is set.

## Options

| Option | Default | What it does |
| --- | --- | --- |
| `mode` | `shrink` | `shrink` or `describe` |
| `percent` | `75` | The size Claude reads, as a percent of the size the tool returned |
| `minLongSide` | `768` | A picture is never made smaller than this on its long side |
| `logDecisions` | `false` | Log every picture's sizes |

## Privacy

Pictures are shrunk on this machine. In describe mode the picture is written to
`$TMPDIR/efficient-browser-use/<session>/` for the describer to read, and removed once
it has answered.

## Credit

Written for this repository. MIT license, in `LICENSE`.

## Tests

```bash
claude plugin test plugins/efficient-browser-use
```

```bash
bash plugins/efficient-browser-use/scripts/imagetool_test.sh
```

The second runs `scripts/imagetool.sh` on real PNG, JPEG, GIF and WebP pictures, at set
sizes and at the script's defaults of 75% and 768 px. It also checks the `size` mode,
which describe mode uses to read a picture's size. Without ImageMagick it checks only
the missing-ImageMagick path and skips the rest; `EBU_REQUIRE_IM=1` makes that skip a
failure.
