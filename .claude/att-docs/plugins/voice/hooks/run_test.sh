#!/usr/bin/env bash
# usage: bash run_test.sh
# Tests run.sh against a stand-in skill folder, so no real hook script runs.
set -u
here=$(dirname "$(readlink -f "$0")")
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
fail=0
export HOME=$work/nohome
mkdir -p "$HOME"

mkdir -p "$work/plugin/hooks" "$work/plugin/skills/voice-bridge-hooks"
cp "$here/run.sh" "$work/plugin/hooks/run.sh"
printf '{}\n' >"$work/plugin/skills/voice-bridge-hooks/defaults.json"
printf '%s\n' 'import sys; print("py", *sys.argv[1:], sys.stdin.read().strip())' \
  >"$work/plugin/skills/voice-bridge-hooks/probe.py"
printf '%s\n' 'echo "sh $* $(cat)"' >"$work/plugin/skills/voice-bridge-hooks/probe.sh"
run="$work/plugin/hooks/run.sh"
defaults="$work/plugin/skills/voice-bridge-hooks/defaults.json"

# usage: check <name> <expected> <actual>
check() {
  if [[ $2 != "$3" ]]; then
    echo "FAIL $1: expected [$2] got [$3]" >&2
    fail=1
  fi
}

mkdir -p "$work/bare"
check "defaults when the project has no extension" "py --config $defaults attention payload" \
  "$(CLAUDE_PROJECT_DIR=$work/bare "$run" probe.py attention <<<payload)"

mkdir -p "$work/own/.claude/skills/voice-bridge-hooks"
printf '{}\n' >"$work/own/.claude/skills/voice-bridge-hooks/extension.json"
check "the project's extension wins" \
  "sh --config $work/own/.claude/skills/voice-bridge-hooks/extension.json x payload" \
  "$(CLAUDE_PROJECT_DIR=$work/own "$run" probe.sh x <<<payload)"

mkdir -p "$work/hooked/.claude"
printf '%s\n' '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"x/voice_bridge_reply.py"}]}]}}' \
  >"$work/hooked/.claude/settings.json"
out=$(CLAUDE_PROJECT_DIR=$work/hooked "$run" probe.py attention <<<payload)
check "steps aside when the project registers the hooks" "" "$out"
CLAUDE_PROJECT_DIR=$work/hooked "$run" probe.py attention <<<payload
check "the step-aside exit code" 0 $?

mkdir -p "$work/local/.claude"
printf '%s\n' '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"x/speak-attention.sh"}]}]}}' \
  >"$work/local/.claude/settings.local.json"
check "steps aside for local settings too" "" \
  "$(CLAUDE_PROJECT_DIR=$work/local "$run" probe.py attention <<<payload)"

mkdir -p "$work/allowed/.claude"
printf '%s\n' '{"permissions":{"allow":["Bash(scripts/speak-attention_test.sh)"]}}' \
  >"$work/allowed/.claude/settings.json"
check "a permission naming a script is not a hook" "py --config $defaults x payload" \
  "$(CLAUDE_PROJECT_DIR=$work/allowed "$run" probe.py x <<<payload)"

mkdir -p "$work/home/.claude"
printf '%s\n' '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"x/speak-attention.sh"}]}]}}' \
  >"$work/home/.claude/settings.json"
check "steps aside for user-scope settings" "" \
  "$(HOME=$work/home CLAUDE_PROJECT_DIR=$work/bare "$run" probe.py x <<<payload)"

printf '%s\n' 'import sys; sys.exit(3)' >"$work/plugin/skills/voice-bridge-hooks/fail.py"
CLAUDE_PROJECT_DIR=$work/bare "$run" fail.py </dev/null
check "the script's exit code passes through" 3 $?

exit $fail
