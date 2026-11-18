#!/usr/bin/env bash
# Runs every test file in the repository, then the static checks.
#
#   bash scripts/test-all.sh                run the tests, then the static checks
#   bash scripts/test-all.sh --tests-only   run only the tests
#   bash scripts/test-all.sh --checks-only  run only the static checks
#   bash scripts/test-all.sh --changed-since <rev>
#                                           run only the test files that the change
#                                           from <rev> to HEAD can affect, then the
#                                           static checks; combines with --tests-only
#
# A test file is *.test.mjs (node --test), *_test.py (python3), *_test.sh (bash), or a
# plugin's hooks/*.test.tsx (claude plugin test on the plugin folder, skipped where the
# claude command is not installed).
# node_modules, .git and .claude/worktrees are skipped. A failing file does not stop
# the run; the script prints one line per file and a summary, and exits 1 if anything
# failed.
#
# With --changed-since, scripts/select_tests.py picks the files from the paths that
# changed between the merge base of <rev> and HEAD, and prints a SKIP line for each file
# it leaves out. When the change cannot be read, every file runs.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

usage() {
  echo "usage: $0 [--tests-only | --checks-only] [--changed-since <rev>]" >&2
  exit 2
}

run_tests=1
run_checks=1
changed_since=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --tests-only) run_checks=0 ;;
    --checks-only) run_tests=0 ;;
    --changed-since) [ "$#" -ge 2 ] && [ -n "$2" ] || usage; changed_since=$2; shift ;;
    *) usage ;;
  esac
  shift
done
[ "$run_tests" -eq 1 ] || [ "$run_checks" -eq 1 ] || usage

export PYTHONDONTWRITEBYTECODE=1
passed=0
failed=0
failed_names=()

run_one() {
  local kind="$1" file="$2" log status
  log="$(mktemp)"
  status=0
  # stdin is /dev/null: the loop below feeds the file list on stdin, and a test that
  # reads stdin would swallow the rest of the list.
  case "$kind" in
    node) node --test "$file" >"$log" 2>&1 </dev/null || status=$? ;;
    python) python3 "$file" >"$log" 2>&1 </dev/null || status=$? ;;
    bash) bash "$file" >"$log" 2>&1 </dev/null || status=$? ;;
    mod) claude plugin test "$file" >"$log" 2>&1 </dev/null || status=$? ;;
  esac
  if [ "$status" -eq 0 ]; then
    echo "PASS  $file"
    passed=$((passed + 1))
  else
    echo "FAIL  $file (exit $status)"
    # A long log puts its failures above the tail, so they are listed first.
    grep -E '^(FAIL|not ok)' "$log" | sed 's/^/      /' | head -n 20 || true
    sed 's/^/      /' "$log" | tail -n 40
    failed=$((failed + 1))
    failed_names+=("$file")
  fi
  rm -f "$log"
}

find_tests() {
  find . \( -name node_modules -o -path ./.git -o -path ./.claude/worktrees \) -prune -o \
    -type f -name "$1" -print | sed 's|^\./||' | sort
}

# Every test entry as `<kind><TAB><path>`. A mod entry is a plugin folder, run with
# `claude plugin test`.
list_tests() {
  find_tests '*.test.mjs' | sed 's/^/node\t/'
  find_tests '*_test.py' | sed 's/^/python\t/'
  find_tests '*_test.sh' | sed 's/^/bash\t/'
  if command -v claude >/dev/null; then
    find_tests '*.test.tsx' | { grep '^plugins/[^/]*/hooks/' || true; } | cut -d/ -f1-2 |
      sort -u | sed 's/^/mod\t/'
  fi
}

# Writes the entries to run to the file $1, in list_tests' order. With --changed-since,
# prints a SKIP line for each entry left out and a Selection line saying how many ran.
pick_tests() {
  local out="$1" entries changed base picks
  entries=$(list_tests)
  if [ -z "$changed_since" ]; then
    printf '%s\n' "$entries" >"$out"
    return
  fi
  changed=$(mktemp)
  if ! base=$(git merge-base "$changed_since" HEAD 2>/dev/null) ||
     ! git diff -z --name-only --no-renames "$base" HEAD >"$changed" 2>/dev/null ||
     ! picks=$(printf '%s\n' "$entries" | cut -f2 |
               python3 -I scripts/select_tests.py "$changed"); then
    echo "Selection: every test file (could not read the change since $changed_since)"
    rm -f "$changed"
    printf '%s\n' "$entries" >"$out"
    return
  fi
  rm -f "$changed"
  local verdict entry reason total=0 run=0
  : >"$out"
  while IFS=$'\t' read -r verdict entry reason; do
    case "$verdict" in
      ALL) echo "Selection: every test file ($entry)" ;;
      SKIP) echo "SKIP  $entry ($reason)"; total=$((total + 1)) ;;
      RUN)
        total=$((total + 1)); run=$((run + 1))
        printf '%s\n' "$entries" | E=$entry awk -F'\t' '$2 == ENVIRON["E"]' >>"$out"
        ;;
    esac
  done <<<"$picks"
  echo "Selection: $run of $total test entries, from the change since $changed_since"
}

if [ "$run_tests" -eq 1 ]; then
  echo "== Tests"
  command -v claude >/dev/null || echo "SKIP  hooks module tests (no claude command)"
  picked=$(mktemp)
  pick_tests "$picked"
  while IFS=$'\t' read -r kind f; do
    [ -n "$f" ] && run_one "$kind" "$f"
  done <"$picked"
  rm -f "$picked"
  echo
  echo "Tests: $passed passed, $failed failed"
fi

if [ "$run_checks" -eq 1 ]; then
  echo
  echo "== Static checks"
  if python3 -I scripts/validate.py; then
    echo "Static checks: passed"
  else
    echo "Static checks: failed"
    failed=$((failed + 1))
    failed_names+=("static checks")
  fi
fi

echo
if [ "$failed" -gt 0 ]; then
  echo "FAILED:"
  printf '  %s\n' "${failed_names[@]}"
  exit 1
fi
echo "All passed"
