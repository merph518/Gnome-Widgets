# mods

A switchboard for the mods on this computer. `/mods` opens a side pane that lists every
mod Claude Code can load, and switches each one on or off in every open chat. The
plugin has no skills, only a hooks module, `hooks/register.tsx`.

## What it does

`/mods` looks for mods in the places Claude Code loads them from, in this order:

1. This chat's dev mods, `<config>/dev-mods/<session id>/`.
2. The folders in `CLAUDE_CODE_PLUGIN_DIRS`, separated by colons. A folder can be one
   plugin or a folder of plugins.
3. The folders under `<config>/mods/`.
4. The installed plugins in `<config>/plugins/installed_plugins.json` that `enabledPlugins`
   turns on in `<config>/settings.json`, or in the project's `.claude/settings.json` or
   `.claude/settings.local.json`. A project or local install counts only in the project
   it was installed for.

`<config>` is `CLAUDE_CONFIG_DIR` when it is set, with a leading `~` read as your home
folder, and `~/.claude` otherwise. A mod is a plugin whose `hooks/hooks.json` lists at
least one module. Plugins with only skills are not listed, and neither is this plugin.
When two folders hold a mod with the same `plugin.json` name, the first one in the order
above is listed, with the others noted under it.

The pane groups the mods under **Token savers**, **Chat tools** and **Display**. The
mods this repository ships have their own title and tip. Any other mod shows its
`plugin.json` name and description, under Display when it draws a band or a pane and
under Chat tools otherwise.

What a row offers comes from reading the mod's source files in `hooks/` (test files
are skipped):

| The source | The row offers |
| --- | --- |
| reads `switches.json` | **Turn off** and **Turn on** |
| reads `switches.json` and draws a band above the prompt or a pane | **Hide** and **Show** |
| draws a pane and reads an `.open-` marker | **Reopen**, while the mod is on |

The source files are read from `hooks/` and every folder under it, except
`node_modules`. A mod whose source never mentions `switches.json` says so, and its row
has no **Turn off** or **Hide**: only its own code can honor a switch. **Reopen** needs a
chat to name, so it is missing when the pane cannot read this chat's session id.

**Close** at the bottom closes the pane. `/mods` opens it again and reads the mods
afresh.

## switches.json

The switches live in `<config>/mods/switches.json`:

```json
{
  "effort-optimizer": false,
  "model-router:hidden": true
}
```

- `"<name>": false` turns a mod off in every chat. **Turn on** removes the key.
- `"<name>:hidden": true` keeps a mod's band or pane out of sight. **Show** removes
  the key.

Every other key in the file is kept. The pane reads the file again right before each
change, so a change made in another chat is not lost. When the file is not a JSON
object, the pane says so and changes nothing until it is fixed.

Each mod reads the file for itself. `effort-optimizer` and `model-router` read it every
3 seconds, so a switch reaches every open chat within a few seconds. While the pane is
open it reads the file every 3 seconds too, so a change made in another chat shows up.

**Reopen** writes an empty file, `<config>/mods/.open-<name>-<session id>`, that asks
that mod to open its pane again in this chat. What happens next is up to the mod:
`model-router` opens its pane and removes the file.

## Install

```
claude plugin install mods@att-docs --scope user
```

Then run `/reload-plugins`, or start a new chat, and run `/mods`.

## Where the code came from

The plugin was written for this repository from a description of how a `/mods`
switchboard behaves: the `switches.json` keys and the `.open-` marker files. No code
was copied from another project. It is released under the MIT license, the same as the
rest of this repository.

## Tests

```
claude plugin validate plugins/mods
claude plugin test plugins/mods
```
