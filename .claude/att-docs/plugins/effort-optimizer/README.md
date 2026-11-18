# effort-optimizer

Suggests a reasoning effort level for each prompt you type, and switches to it when you
ask. The plugin has no skills, only a hooks module, `hooks/register.tsx`.

## What it does

When a typed prompt starts a turn, a small, fast model reads the prompt (and the start of
the previous reply, so a short "yes, go ahead" is judged by what it agrees to) and picks
one of the five levels: low, medium, high, extra high or max.

- **Suggest mode**, the default. When the pick differs from the level the turn started
  at, a row above the prompt shows it, with a short reason and two buttons. **Switch to
  &lt;level&gt;** applies the level to the rest of the turn and to the turns after it.
  **Dismiss** hides the row. The turn never waits for the pick.
- **Auto mode.** The pick is made before the turn's first request goes out, and applied
  when it differs. The row above the prompt then says what was applied. Each prompt
  waits up to eight seconds for the pick; a pick that fails or times out leaves your
  level as it was.

Slash commands, prompts typed while a turn is running, background task notifications,
scripted runs such as `claude -p`, and subagent requests get no pick.

### How a level is applied

When `/config` has an effort row you are allowed to change, the plugin sets it there, so
the change is the same as one you would make yourself and it stays after the session. In
auto mode this means each pick that differs rewrites your `/config` effort setting. When
the row does not offer the picked level, nothing changes and the row above the prompt
says so.

When the row is locked by managed settings, refuses the change, or does not exist, the
plugin sends the level with each main-chat request instead. That lasts until you change
the effort level yourself, switch modes, or run `/clear`. Subagent requests keep their
own level. The row above the prompt says which path was taken.

## Command

| Command | Does |
| --- | --- |
| `/effort-optimizer` | Shows the mode and how levels are applied |
| `/effort-optimizer suggest` | Switches to suggest mode |
| `/effort-optimizer auto` | Switches to auto mode |

The mode is kept across sessions. Auto mode stays off until you turn it on, because it
changes your effort setting without asking.

## Turning it off

The plugin reads `mods/switches.json` in the Claude Code configuration folder
(`~/.claude`, or `CLAUDE_CONFIG_DIR` when that is set) each time you type a prompt:

```json
{
  "effort-optimizer": false,
  "effort-optimizer:hidden": true
}
```

- `"effort-optimizer": false` turns the plugin off: no picks, no row, no change to any
  request.
- `"effort-optimizer:hidden": true` hides the row above the prompt. Auto mode still
  applies its picks.

With no `switches.json`, or a file that is not a JSON object, the plugin stays on.
`/plugin disable effort-optimizer@att-docs` turns it off as well.

## Log

The `log` option, off by default, writes each pick and each effort change to
`mods-logs/effort-optimizer.log` in the configuration folder. Turn it on in `/config`
(`effort-optimizer.log`). The log keeps its newest 200,000 characters.

## Cost

Each typed prompt costs one short model call, billed to the session like its other
requests.

## Install

```
claude plugin install effort-optimizer@att-docs --scope user
```

Then run `/reload-plugins` in an open session.

## Where the code came from

This plugin was written from scratch for this repository. It follows the behavior of an
effort-picking mod from a third-party pack of token-saving mods. That mod carries no
license, so none of its code or text is used here. This plugin is released under the MIT
License in [LICENSE](../../LICENSE).

## Tests

```
claude plugin validate plugins/effort-optimizer
claude plugin test plugins/effort-optimizer
```
