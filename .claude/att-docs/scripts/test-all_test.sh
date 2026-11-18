#!/usr/bin/env bash
# Tests scripts/test-all.sh --changed-since in a throwaway repository: which test files
# run, the SKIP and Selection lines, and the fallback to every file.
#
# usage: bash scripts/test-all_test.sh
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
fails=0

check() {
  local name="$1" out="$2" want="$3"
  if [[ $out == *"$want"* ]]; then
    echo "ok    $name"
  else
    echo "FAIL  $name: no line '$want' in:"
    printf '%s\n' "$out" | sed 's/^/        /'
    fails=$((fails + 1))
  fi
}

check_not() {
  local name="$1" out="$2" unwanted="$3"
  if [[ $out == *"$unwanted"* ]]; then
    echo "FAIL  $name: '$unwanted' in:"
    printf '%s\n' "$out" | sed 's/^/        /'
    fails=$((fails + 1))
  else
    echo "ok    $name"
  fi
}

repo="$work/repo"
mkdir -p "$repo/scripts" "$repo/plugins/p/skills/x" "$repo/plugins/p/skills/y"
cp "$here/test-all.sh" "$here/select_tests.py" "$repo/scripts/"
printf 'exit 0\n' >"$repo/plugins/p/skills/x/x_test.sh"
printf 'exit 0\n' >"$repo/plugins/p/skills/y/y_test.sh"
printf 'exit 0\n' >"$repo/plugins/p/skills/x/back\\slash_test.sh"
cd "$repo"
git init -q -b main
git config user.email t@example.com
git config user.name t
git add -A
git commit -qm base

git switch -qc work
printf 'one\n' >plugins/p/skills/x/code.sh
git add -A
git commit -qm 'change x'

run() { bash scripts/test-all.sh --tests-only "$@" 2>&1 || true; }

out=$(run --changed-since main)
check "changed unit runs" "$out" "PASS  plugins/p/skills/x/x_test.sh"
check "a backslash in a path still runs" "$out" 'PASS  plugins/p/skills/x/back\slash_test.sh'
check "other unit skips with a reason" "$out" \
  "SKIP  plugins/p/skills/y/y_test.sh (no changed file in plugins/p/skills/y)"
check "selection is counted" "$out" "Selection: 2 of 3 test entries, from the change since main"
check "tally keeps its shape" "$out" "Tests: 2 passed, 0 failed"

out=$(run --changed-since no-such-rev)
check "bad rev falls back" "$out" \
  "Selection: every test file (could not read the change since no-such-rev)"
check "bad rev runs every file" "$out" "Tests: 3 passed, 0 failed"

# A selector that fails leaves the choice to running everything. The broken copy is not
# committed, so it is not part of the change.
cp scripts/select_tests.py "$work/select_tests.py"
printf 'import sys\nsys.exit(1)\n' >scripts/select_tests.py
out=$(run --changed-since main)
cp "$work/select_tests.py" scripts/select_tests.py
check "a failing selector falls back" "$out" \
  "Selection: every test file (could not read the change since main)"
check "a failing selector runs every file" "$out" "Tests: 3 passed, 0 failed"

out=$(run)
check "no flag runs every file" "$out" "Tests: 3 passed, 0 failed"
check_not "no flag prints no selection" "$out" "Selection:"

# main moves on after the branch, then the branch is merged onto it: the merge commit's
# first parent is main, so only the branch's change counts.
git switch -q main
printf 'two\n' >plugins/p/skills/y/code.sh
git add -A
git commit -qm 'change y on main'
git merge -q --no-ff work -m merge
out=$(run --changed-since HEAD^1)
check "merge commit diffs against its first parent" "$out" \
  "SKIP  plugins/p/skills/y/y_test.sh"
check "merge commit runs the branch's unit" "$out" "PASS  plugins/p/skills/x/x_test.sh"

git switch -q work
printf '# note\n' >>scripts/test-all.sh
git add -A
git commit -qm 'change the runner'
out=$(run --changed-since main)
check "a run-everything path says why" "$out" \
  "Selection: every test file (scripts/test-all.sh changed)"
check "a run-everything path runs every file" "$out" "Tests: 3 passed, 0 failed"

out=$(bash scripts/test-all.sh --changed-since 2>&1 || true)
check "a missing rev is a usage error" "$out" "usage:"

echo
if [ "$fails" -gt 0 ]; then
  echo "$fails failed"
  exit 1
fi
echo "all passed"
