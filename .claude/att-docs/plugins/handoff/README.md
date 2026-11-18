# handoff

Writes a handoff of a long chat and starts a fresh chat from it. The plugin has no
skills, only a hooks module, `hooks/register.tsx`. It is built for Linux, in the terminal
and in the desktop app.

## What it does

Once the chat's context reaches 250,000 tokens, a row above the prompt offers
**Refresh**. Refresh runs five steps, each with its own progress bar:

1. **Read the chat.**
2. **Save a draft.** A plain record of the chat, built without a model: what was asked,
   the files, skills and tools used, the links, and the last reply. It is saved as
   `handoffs/<time>-draft.md`, so a write-up that fails still leaves something to start
   from.
3. **Write the handoff.** A copy of the chat is asked to write the full handoff: what
   was asked, done and decided, the files, skills, tools and links, and the next steps.
4. **Remove secrets.**
5. **Save the handoff** as `handoffs/<time>-handoff.md`, and add a line to
   `handoffs/handoff.log`.

The row then offers:

- **Copy** puts the handoff on the clipboard, with `wl-copy` under Wayland and
  `xclip -selection clipboard` under X11. Paste it with Ctrl+Shift+V in a terminal, or
  Ctrl+V elsewhere.
- **Open file** opens the saved handoff with `xdg-open`.
- **Start new chat with it** opens `claude://code/new` with `xdg-open`, which starts a
  new chat in the desktop app with the handoff filled in. A handoff too long for the
  link (over 32,000 characters once encoded) fills in a line that names the saved file
  instead.
- **Close** hides the row until the context grows by another 100,000 tokens.

When the write-up fails, the row says why and offers **Open draft**.

`handoffs/` is in the Claude Code configuration folder: `~/.claude`, or
`CLAUDE_CONFIG_DIR` when that is set. `<time>` is the UTC time the handoff started, as
`YYYYMMDD-HHMMSS`.

## Commands and tool

| Command | Does |
| --- | --- |
| `/handoff` | Writes a handoff now, without waiting for the offer |
| `/fresh` | Shows the Refresh row |

The model can show the Refresh row too, through the plugin's `refresh` tool, when you
ask it for a handoff or a fresh chat.

## Asking for a handoff from another plugin

Another plugin asks for a handoff by creating an empty file named
`handoffs/.request-<session id>` in the configuration folder. The plugin checks for it
every five seconds, removes it, and writes the handoff as Refresh does. A request file
for another session is left alone.

## Secrets

Before the draft and the handoff are saved, copied or put in a link, text that looks
like a secret is replaced with `<secret removed>`:

- private key blocks;
- `Bearer <token>`;
- values of settings whose names hold `KEY`, `TOKEN`, `SECRET` or `PASSWORD`, such as
  `DB_PASSWORD=...`, `api_key=...` or `"client_secret": "..."`;
- keys and tokens with a known shape: Anthropic and OpenAI `sk-` keys, GitHub and GitLab
  tokens, AWS access key IDs, Slack tokens, Google API keys and JSON Web Tokens.

The check works by pattern, so a secret in an unusual shape can still get through. Read
a handoff before you share it.

## What stays on disk

Each draft and handoff holds a summary of the whole chat. They stay in `handoffs/` until
you delete them; the plugin never removes them.

## Requirements

Copy needs a clipboard tool from Ubuntu's own repositories:

```bash
sudo apt install wl-clipboard
```

```bash
sudo apt install xclip
```

`wl-clipboard` is for Wayland sessions and `xclip` for X11. Under Wayland the plugin
falls back to `xclip` when `wl-copy` is missing and an X display is available. With
neither installed, Copy names the package to install.

Open file and Start new chat need `xdg-open`, from the `xdg-utils` package, which Ubuntu
desktops install by default. Start new chat needs the Claude desktop app registered for
`claude://` links; `xdg-mime query default x-scheme-handler/claude` shows whether it is.

## Turning it off

The plugin reads `mods/switches.json` in the configuration folder:

```json
{
  "handoff": false,
  "handoff:hidden": true
}
```

- `"handoff": false` turns the plugin off: no row, no request files, and the commands
  say it is off.
- `"handoff:hidden": true` hides the row. `/handoff` and request files still work.

With no `switches.json`, or a file that is not a JSON object, the plugin stays on.
`/plugin disable handoff@att-docs` turns it off as well.

## Cost

Each handoff costs one model call over the whole chat, billed to the session like its
other requests. Most of the chat is usually read from the prompt cache.

## Install

```bash
claude plugin install handoff@att-docs --scope user
```

Then run `/reload-plugins` in an open session.

## Where the code came from

This plugin was written from scratch for this repository. It follows the behavior of a
handoff mod from a third-party pack of token-saving mods, ported to Linux. That mod
carries no license, so none of its code or text is used here. This plugin is released
under the MIT License in [LICENSE](../../LICENSE).

## Tests

```bash
claude plugin validate plugins/handoff
claude plugin test plugins/handoff
```
