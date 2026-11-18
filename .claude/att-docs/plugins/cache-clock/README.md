# cache-clock

Counts down above the prompt until the chat's prompt cache goes cold. The plugin has no
skills, only a hooks module, `hooks/register.tsx`.

## What it does

Each reply in the main chat writes the conversation to Anthropic's prompt cache, which
keeps it for five minutes or for one hour. While the cache is warm, the next reply reads
the chat from it at a fraction of the price. Once it goes cold, the next reply writes the
whole chat to the cache again.

- **Countdown.** After each reply, a row above the prompt shows how long the cache has
  left, such as `Cache warm · 4:12 left (5m)`, and then `Cache cold`. The count starts
  when the reply's request went out. Replies from subagents do not restart it, and a
  resumed chat counts from the time its newest reply was written.
- **Cache length.** The plugin reads the chat's transcript,
  `projects/<project>/<session id>.jsonl` in the configuration folder, and takes the
  length from the newest main-chat reply that wrote to the cache: one hour when it wrote
  to the one-hour cache, else five minutes. When no reply says, the row counts five
  minutes and shows `5m?`. A transcript over 4 MiB is read from its last 4,000,000 bytes
  with `tail`, which Linux and macOS have.
- **Handoff offer.** When the cache is cold and the chat holds over 150,000 tokens, the
  row offers **Hand off to a new chat**. The button writes
  `handoffs/.request-<session id>` in the configuration folder, which the handoff plugin
  picks up to write a handoff for a new chat. Without that plugin, the file does nothing.
  The offer comes back after the next reply.
- **Keep warm**, off until you turn it on with `/keepwarm`. 45 seconds before the cache
  would go cold, it sends the chat a one-word ping, so the cache is read and its time
  starts over. It does not ping while a reply is being written. It stops when you type a
  prompt, after 2 hours, after 30 pings, after 3 pings in a row that do not read the
  cache, when a retry would end after the cache goes cold, or on `/keepwarm off`. The row
  shows the pings sent and why it stopped. It is not remembered across sessions. Turned
  on while the cache is cold, it waits for the next reply, and the prompt you type for
  that reply does not stop it.

## Commands

| Command | Does |
| --- | --- |
| `/keepwarm` | Turns keep warm on, or off when it is on |
| `/keepwarm on`, `/keepwarm off` | Turns keep warm on or off |
| `/cacheclock` | Hides the row, or shows it when it is hidden |
| `/cacheclock show`, `/cacheclock hide` | Shows or hides the row; the choice is kept across sessions |

## Turning it off

The plugin reads `mods/switches.json` in the Claude Code configuration folder
(`~/.claude`, or `CLAUDE_CONFIG_DIR` when that is set) at the start, each time you type a
prompt, and every few seconds while the cache is warm:

```json
{
  "cache-clock": false,
  "cache-clock:hidden": true
}
```

- `"cache-clock": false` turns the plugin off: no row and no pings.
- `"cache-clock:hidden": true` hides the row.

With no `switches.json`, or a file that is not a JSON object, the plugin stays on.
`/plugin disable cache-clock@att-docs` turns it off as well.

## Cost

The countdown and the handoff offer cost nothing. Each keep-warm ping is a request over
the whole chat: it reads the chat from the cache, which is billed at about a tenth of
the normal input price, far less than writing a long chat to the cache again.
That is why keep warm stays off until you ask for it.

## Install

```
claude plugin install cache-clock@att-docs --scope user
```

Then run `/reload-plugins` in an open session.

## Where the code came from

This plugin was written from scratch for this repository. It follows the behavior of a
cache countdown mod from a third-party pack of token-saving mods. That mod carries no
license, so none of its code or text is used here. This plugin is released under the MIT
License in [LICENSE](../../LICENSE).

## Tests

```
claude plugin validate plugins/cache-clock
tsc -p plugins/cache-clock
claude plugin test plugins/cache-clock
```

`tsc` needs the type declarations Claude Code writes to `.claude-plugin/types/` when it
loads the plugin from a working folder.
