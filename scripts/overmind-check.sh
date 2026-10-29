#!/usr/bin/env bash
# Fail when the vendored Overmind copy in .claude/att-docs differs from the tree
# .claude/att-docs.lock pins, so a hand edit cannot land.
# usage: scripts/overmind-check.sh [--remote]
# --remote also fetches the pinned tag (it needs read access to the Overmind
# repository) and fails unless it still points at the locked commit and tree,
# so a lock edited to match a hand edit fails too.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
LOCK=.claude/att-docs.lock
PREFIX=.claude/att-docs

lock() { sed -n "s/^$1=//p" "$LOCK"; }

fail() {
  echo "overmind-check: $1" >&2
  echo "overmind-check: move the pin with scripts/overmind-sync.sh <tag>, never by hand" >&2
  exit 1
}

case "${1:-}" in
  ""|--remote) ;;
  *) echo "usage: scripts/overmind-check.sh [--remote]" >&2; exit 2 ;;
esac

[ -f "$LOCK" ] || fail "$LOCK is missing"

# The tree is read from the index, which overmind-sync.sh fills, so the check
# passes before the sync is committed.
[ "$(git write-tree --prefix="$PREFIX/")" = "$(lock tree)" ] \
  || fail "$PREFIX differs from the tree $LOCK pins"
git diff --quiet -- "$PREFIX" \
  || fail "$PREFIX has changes that are not in the index"
[ -z "$(git ls-files --others --exclude-standard -- "$PREFIX")" ] \
  || fail "$PREFIX has files that are not in the index"

if [ "${1:-}" = "--remote" ]; then
  git fetch --quiet --no-tags "https://github.com/$(lock repo).git" "refs/tags/$(lock tag)" \
    || fail "could not fetch tag $(lock tag) from $(lock repo)"
  [ "$(git rev-parse 'FETCH_HEAD^{commit}')" = "$(lock commit)" ] \
    || fail "tag $(lock tag) no longer points at the locked commit"
  [ "$(git rev-parse 'FETCH_HEAD^{tree}')" = "$(lock tree)" ] \
    || fail "tag $(lock tag) no longer has the locked tree"
fi

