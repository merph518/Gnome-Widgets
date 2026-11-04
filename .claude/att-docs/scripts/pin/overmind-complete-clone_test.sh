#!/usr/bin/env bash
# Cases for overmind-complete-clone.sh. A local repository that allows filtered clones
# stands in for the remote, and a blobless clone of it stands in for a runner workspace
# a sparse checkout left behind. Nothing touches the network.
# usage: bash overmind-complete-clone_test.sh
set -uo pipefail

command -v git > /dev/null || { echo "git is required"; exit 1; }

HERE="$(cd "$(dirname "$0")" && pwd)"
SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT

export HOME="$SANDBOX/home"
mkdir -p "$HOME"
export GIT_CONFIG_GLOBAL="$SANDBOX/gitconfig"
git config --global user.name tester
git config --global user.email tester@example.com
git config --global init.defaultBranch main
unset GH_TOKEN

fails=0
check() {
  if [ "$1" = "$2" ]; then echo "ok   $3"; else
    echo "FAIL $3: got [$1], wanted [$2]"; fails=$((fails + 1)); fi
}

ORIGIN="$SANDBOX/origin"
git init -q "$ORIGIN"
echo one > "$ORIGIN/a.md"
git -C "$ORIGIN" add -A && git -C "$ORIGIN" commit -q -m one && git -C "$ORIGIN" tag v0.1.0
echo two > "$ORIGIN/a.md"
git -C "$ORIGIN" add -A && git -C "$ORIGIN" commit -q -m two && git -C "$ORIGIN" tag v0.2.0
# Without these the server ignores the filter and the clone comes out complete.
git -C "$ORIGIN" config uploadpack.allowFilter true
git -C "$ORIGIN" config uploadpack.allowAnySHA1InWant true

# usage: make_partial <dir>; a blobless clone, as a sparse checkout leaves.
make_partial() { git clone -q --filter=blob:none "file://$ORIGIN" "$1" 2> /dev/null; }
# usage: missing <dir>; how many objects the clone lacks.
missing() { git -C "$1" rev-list --objects --all --missing=print | grep -c '^?' || true; }
# usage: consumer_fetch <dir>; a fresh repository with no history fetches the tag from the
# directory, as the sync script does, and so asks for every object.
consumer_fetch() {
  local c
  c="$(mktemp -d "$SANDBOX/consumer.XXXXXX")"
  git init -q "$c"
  git -C "$c" commit -q --allow-empty -m init
  git -C "$c" fetch --no-tags -- "$1" refs/tags/v0.2.0 2>&1
}

# usage: run_complete [<directory>]; the script under test.
run_complete() { bash "$HERE/overmind-complete-clone.sh" "$@"; }

# The precondition: a partial clone that really lacks objects, and cannot serve them.
PARTIAL="$SANDBOX/partial"
make_partial "$PARTIAL"
before="$(missing "$PARTIAL")"
if [ "$before" -eq 0 ]; then
  echo "FAIL the blobless clone lacks no objects, so the cases below prove nothing"
  exit 1
fi
check "$(git -C "$PARTIAL" config --get remote.origin.promisor)" true "the clone is marked as a partial clone"
out="$(consumer_fetch "$PARTIAL")"
case "$out" in *"promisor remote"*) r=failed ;; *) r=served ;; esac
check "$r" failed "a partial clone cannot serve the tag to a fresh consumer"

# Completing it.
out="$(run_complete "$PARTIAL")"
check "$?" 0 "completing a partial clone succeeds"
check "$out" "completed: fetched every object" "it says it fetched"
check "$(missing "$PARTIAL")" 0 "no object is missing afterwards"
check "$(git -C "$PARTIAL" config --get remote.origin.promisor || echo unset)" unset "the partial clone mark is gone"
check "$(git -C "$PARTIAL" config --get remote.origin.partialclonefilter || echo unset)" unset "the clone's filter is gone"
check "$(git -C "$PARTIAL" tag --list | sort | tr '\n' ' ')" "v0.1.0 v0.2.0 " "the tags are kept"
out="$(consumer_fetch "$PARTIAL")"
check "$?" 0 "a fresh consumer can fetch the tag afterwards"
check "$(git -C "$PARTIAL" show v0.1.0:a.md)" one "the history-only file is readable"

# A second run finds a full checkout and does nothing.
cfg="$(git -C "$PARTIAL" config --local --list)"
out="$(run_complete "$PARTIAL")"
check "$?" 0 "a second run succeeds"
check "$out" "skipped: full checkout" "a second run says it skipped"
check "$(git -C "$PARTIAL" config --local --list)" "$cfg" "a second run changes no configuration"

# A full checkout is left as it is: origin is unreachable, so any fetch would fail.
FULL="$SANDBOX/full"
git clone -q "file://$ORIGIN" "$FULL"
git -C "$FULL" remote set-url origin "$SANDBOX/nowhere"
cfg="$(git -C "$FULL" config --local --list)"
head="$(git -C "$FULL" rev-parse HEAD)"
out="$(run_complete "$FULL")"
check "$?" 0 "a full checkout succeeds without a fetch"
check "$out" "skipped: full checkout" "a full checkout is skipped"
check "$(git -C "$FULL" config --local --list)" "$cfg" "a full checkout keeps its configuration"
check "$(git -C "$FULL" rev-parse HEAD)" "$head" "a full checkout keeps its commit"

# The directory defaults to the current one.
make_partial "$SANDBOX/partial-cwd"
(cd "$SANDBOX/partial-cwd" && bash "$HERE/overmind-complete-clone.sh" > /dev/null)
check "$?" 0 "the current directory is used when none is given"
check "$(missing "$SANDBOX/partial-cwd")" 0 "the current directory is completed"

# The credential reaches git through the environment only.
TOKEN=ghs_sekretsekretsekret
ENCODED="$(printf 'x-access-token:%s' "$TOKEN" | base64 | tr -d '\n')"
make_partial "$SANDBOX/partial-token"
GH_TOKEN="$TOKEN" GIT_TRACE="$SANDBOX/trace" bash "$HERE/overmind-complete-clone.sh" "$SANDBOX/partial-token" > /dev/null 2>&1
check "$?" 0 "completing with a token succeeds"
check "$(missing "$SANDBOX/partial-token")" 0 "completing with a token fetches every object"
check "$(grep -c 'git fetch --quiet --refetch' "$SANDBOX/trace" || true)" 1 "the trace shows the fetch, so the token check below is not vacuous"
check "$(grep -rlE "$TOKEN|$ENCODED" "$SANDBOX/partial-token/.git/config" "$SANDBOX/trace" 2> /dev/null | wc -l)" 0 "neither the configuration nor the command lines hold the token"

# A failed fetch leaves the partial clone as it was, so a later run tries again.
make_partial "$SANDBOX/partial-fail"
git -C "$SANDBOX/partial-fail" remote set-url origin "$SANDBOX/nowhere"
GH_TOKEN="$TOKEN" bash "$HERE/overmind-complete-clone.sh" "$SANDBOX/partial-fail" > /dev/null 2>&1
check "$([ "$?" -ne 0 ] && echo yes)" yes "a failed fetch fails the script"
check "$(git -C "$SANDBOX/partial-fail" config --get remote.origin.promisor)" true "a failed fetch keeps the partial clone mark"
check "$(git -C "$SANDBOX/partial-fail" config --get remote.origin.partialclonefilter)" blob:none "a failed fetch keeps the clone's filter"
check "$(grep -c -E "$TOKEN|$ENCODED" "$SANDBOX/partial-fail/.git/config" || true)" 0 "a failed fetch leaves no token in the configuration"
git -C "$SANDBOX/partial-fail" remote set-url origin "file://$ORIGIN"
run_complete "$SANDBOX/partial-fail" > /dev/null 2>&1
check "$?" 0 "a later run completes the clone"
check "$(missing "$SANDBOX/partial-fail")" 0 "a later run fetches every object"

# A fetch cut short, as a cancelled or timed out job is, also leaves the mark in place.
# A git that waits in fetch stands in for a slow download.
make_partial "$SANDBOX/partial-cut"
REAL_GIT="$(command -v git)"
mkdir -p "$SANDBOX/slowbin"
printf '#!/usr/bin/env bash\nfor a in "$@"; do\n  if [ "$a" = fetch ]; then touch "%s/fetching"; exec sleep 60; fi\ndone\nexec "%s" "$@"\n' "$SANDBOX" "$REAL_GIT" > "$SANDBOX/slowbin/git"
chmod +x "$SANDBOX/slowbin/git"
PATH="$SANDBOX/slowbin:$PATH" bash "$HERE/overmind-complete-clone.sh" "$SANDBOX/partial-cut" > /dev/null 2>&1 &
pid=$!
for _ in $(seq 1 100); do [ -f "$SANDBOX/fetching" ] && break; sleep 0.1; done
check "$([ -f "$SANDBOX/fetching" ] && echo yes)" yes "the slow fetch started"
# bash runs a trap after its foreground command ends, so the fetch is signaled with it,
# as a runner signals the whole process tree.
pkill -TERM -P "$pid" 2> /dev/null
kill -TERM "$pid" 2> /dev/null
wait "$pid" 2> /dev/null
check "$(git -C "$SANDBOX/partial-cut" config --get remote.origin.promisor)" true "an interrupted fetch keeps the partial clone mark"
check "$(git -C "$SANDBOX/partial-cut" config --get remote.origin.partialclonefilter)" blob:none "an interrupted fetch keeps the clone's filter"

# More than one directory is a bad call.
out="$(run_complete "$PARTIAL" "$FULL" 2>&1)"
check "$?" 2 "a second directory is refused"

if [ "$fails" -gt 0 ]; then echo "$fails failed"; exit 1; fi
echo "all passed"
