#!/usr/bin/env bash
# usage: run.sh <script> [args...] < <hook payload>
# Runs one voice-bridge-hooks script for a session in any repository. hooks.json calls it
# for every voice bridge hook, so the plugin's hooks work at user scope without the
# repository carrying a hook entry of its own.
#
# The repository's extension file is .claude/skills/voice-bridge-hooks/extension.json; a
# repository without one gets defaults.json. A repository whose own settings still
# register these scripts keeps them, and this runner steps aside so a hook never fires
# twice.
here=$(dirname "$(readlink -f "$0")")
skill=$(cd "$here/../skills/voice-bridge-hooks" && pwd) || exit 0
script=${1:?usage: run.sh <script> [args...]}
shift
project=${CLAUDE_PROJECT_DIR:-$PWD}

# usage: registers <settings file>; succeeds when a hook command in it runs a voice script.
registers() {
  jq -e '[.hooks[]?[]?.hooks[]?.command // empty]
    | any(test("voice_bridge_reply|speak-attention"))' "$1" >/dev/null 2>&1
}
for settings in "$project/.claude/settings.json" "$project/.claude/settings.local.json" \
  "$HOME/.claude/settings.json"; do
  registers "$settings" && exit 0
done

config=$project/.claude/skills/voice-bridge-hooks/extension.json
[[ -f $config ]] || config=$skill/defaults.json

case $script in
  *.sh) exec bash "$skill/$script" --config "$config" "$@" ;;
  *) exec python3 "$skill/$script" --config "$config" "$@" ;;
esac
