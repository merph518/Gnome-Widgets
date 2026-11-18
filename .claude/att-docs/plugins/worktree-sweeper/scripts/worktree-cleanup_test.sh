#!/usr/bin/env bash
# Runs worktree-cleanup.sh against a scratch repository with one worktree per case and a stub
# gh that answers from files, so no real worktree, remote or pull request is touched.
# usage: bash plugins/worktree-sweeper/scripts/worktree-cleanup_test.sh
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT
export HOME="$SANDBOX/home" GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
mkdir -p "$HOME"

M="$SANDBOX/main"
REMOTE="$SANDBOX/remote.git"
PRS="$SANDBOX/prs"
mkdir -p "$M/scripts" "$SANDBOX/bin" "$PRS"
cp "$HERE/worktree-cleanup.sh" "$M/scripts/"
SCRIPT="$M/scripts/worktree-cleanup.sh"

# gh pr list --head <branch> ...: print the file for that branch, or fail when it holds FAIL.
cat >"$SANDBOX/bin/gh" <<'SH'
#!/usr/bin/env bash
branch=
while [ $# -gt 0 ]; do
  [ "$1" = --head ] && branch=$2
  shift
done
file="$PRS_DIR/${branch//\//_}.json"
[ -f "$file" ] || { echo '[]'; exit 0; }
grep -q FAIL "$file" && exit 1
cat "$file"
# A <branch>.then file replaces the answer after the first call.
[ -f "${file%.json}.then" ] && mv "${file%.json}.then" "$file"
exit 0
SH
chmod +x "$SANDBOX/bin/gh"
export PATH="$SANDBOX/bin:$PATH" PRS_DIR="$PRS"

git init -q --bare "$REMOTE"
git -C "$M" init -q -b main
git -C "$M" commit -q --allow-empty -m init
git -C "$M" remote add origin "$REMOTE"
git -C "$M" push -q origin main

fails=0
check() { # name expected actual
  if [ "$2" != "$3" ]; then
    echo "FAIL $1: expected [$2] got [$3]" >&2
    fails=$((fails + 1))
  else
    echo "ok   $1"
  fi
}
has() { # name needle haystack
  case "$3" in *"$2"*) echo "ok   $1" ;; *) echo "FAIL $1: [$2] not in [$3]" >&2; fails=$((fails + 1)) ;; esac
}

# usage: wt <branch>   a worktree under .claude/worktrees with one pushed commit
wt() {
  git -C "$M" worktree add -q -b "$1" "$M/.claude/worktrees/$1"
  git -C "$M/.claude/worktrees/$1" commit -q --allow-empty -m "work on $1"
  git -C "$M" push -q origin "$1"
}
head_of() { git -C "$M/.claude/worktrees/$1" rev-parse HEAD; }
# usage: pr <branch> <state> <number> [oid]
pr() {
  printf '[{"number":%s,"state":"%s","isCrossRepository":false,"headRefOid":"%s"}]\n' "$3" "$2" "${4:-$(head_of "$1")}" \
    >"$PRS/${1//\//_}.json"
}
row() { grep -E "^$1 " <<<"$out"; }
# A setting that hides untracked files from a plain `git status` must not hide them here.
git -C "$M" config status.showUntrackedFiles no

wt merged-clean;  pr merged-clean MERGED 11
wt merged-dirty;  pr merged-dirty MERGED 12
echo scratch >"$M/.claude/worktrees/merged-dirty/notes.txt"
wt merged-ahead;  pr merged-ahead MERGED 13
git -C "$M/.claude/worktrees/merged-ahead" commit -q --allow-empty -m "after the merge"
wt merged-then-open; pr merged-then-open MERGED 14
jq '. + [{"number":15,"state":"OPEN","isCrossRepository":false,"headRefOid":"abc"}]' "$PRS/merged-then-open.json" \
  >"$PRS/x" && mv "$PRS/x" "$PRS/merged-then-open.json"
wt still-open;    pr still-open OPEN 16
wt abandoned;     pr abandoned CLOSED 17
wt no-pr
wt offline;       echo FAIL >"$PRS/offline.json"
wt locked-one;    pr locked-one MERGED 18
git -C "$M" worktree lock "$M/.claude/worktrees/locked-one"
wt race;          pr race MERGED 21
printf '[{"number":21,"state":"OPEN","isCrossRepository":false,"headRefOid":"x"}]\n' >"$PRS/race.then"
wt feat/slashed;  pr feat/slashed MERGED 19
git -C "$M" worktree add -q --detach "$M/.claude/worktrees/loose"
wt forked;        printf '[{"number":22,"state":"MERGED","isCrossRepository":true,"headRefOid":"%s"}]\n' \
  "$(head_of forked)" >"$PRS/forked.json"
wt broken-index;  pr broken-index MERGED 23
echo garbage >"$(git -C "$M/.claude/worktrees/broken-index" rev-parse --absolute-git-dir)/index"

out="$(cd "$M" && "$SCRIPT" 2>&1 </dev/null)"; rc=$?
check "listing exits 0" 0 "$rc"
has "header names the columns" "pull request" "$out"
has "merged and clean can go" "merged-clean" "$(row .claude/worktrees/merged-clean)"
check "merged and clean verdict" 1 "$(row .claude/worktrees/merged-clean | grep -c 'remove$')"
has "merged row shows the pull request number" "MERGED #11" "$out"
has "uncommitted work keeps it" "1 uncommitted path(s)" "$(row .claude/worktrees/merged-dirty)"
has "a commit after the merge keeps it" "1 unpushed commit(s)" "$(row .claude/worktrees/merged-ahead)"
has "an open pull request wins over a merged one" "pull request open" "$(row .claude/worktrees/merged-then-open)"
has "open pull request keeps it" "pull request open" "$(row .claude/worktrees/still-open)"
has "closed pull request keeps it" "closed without merging" "$(row .claude/worktrees/abandoned)"
has "no pull request keeps it" "no pull request" "$(row .claude/worktrees/no-pr)"
has "an unreadable pull request state keeps it" "pull request state unknown" "$(row .claude/worktrees/offline)"
has "a merged pull request from a fork does not count" "no pull request" "$(row .claude/worktrees/forked)"
has "git status failing keeps it" "uncommitted changes cannot be ruled out" "$(row .claude/worktrees/broken-index)"
has "a locked worktree is kept" "locked" "$(row .claude/worktrees/locked-one)"
has "a detached worktree is listed" "(detached)" "$(row .claude/worktrees/loose)"
check "a branch with a slash can go" 1 "$(row .claude/worktrees/feat/slashed | grep -c 'remove$')"
has "listing offers --remove" "Run with --remove" "$out"
check "the listing removes nothing" yes "$([ -d "$M/.claude/worktrees/merged-clean" ] && echo yes || echo no)"

# --remove with no answer removes nothing.
exists() { [ -d "$M/.claude/worktrees/$1" ] && echo yes || echo no; }
out="$(cd "$M" && "$SCRIPT" --remove 2>&1 </dev/null)"
check "empty input keeps merged-clean" yes "$(exists merged-clean)"
has "empty input says kept" "kept $M/.claude/worktrees/merged-clean" "$out"
# The listing above used up the race answer; put it back for the run that removes.
printf '[{"number":21,"state":"MERGED","isCrossRepository":false,"headRefOid":"%s"}]\n' "$(head_of race)" >"$PRS/race.json"
printf '[{"number":21,"state":"OPEN","isCrossRepository":false,"headRefOid":"x"}]\n' >"$PRS/race.then"

out="$(cd "$M" && printf 'n\nn\nn\n' | "$SCRIPT" --remove 2>&1)"
check "no answers keep merged-clean" yes "$(exists merged-clean)"
check "no answers keep the slashed branch" yes "$(exists feat/slashed)"
printf '[{"number":21,"state":"MERGED","isCrossRepository":false,"headRefOid":"%s"}]\n' "$(head_of race)" >"$PRS/race.json"
printf '[{"number":21,"state":"OPEN","isCrossRepository":false,"headRefOid":"x"}]\n' >"$PRS/race.then"

# Yes to everything: the removable ones go, a worktree whose pull request reopened between the
# listing and the answer is kept, and nothing else is touched.
out="$(cd "$M" && printf 'y\ny\ny\ny\n' | "$SCRIPT" --remove 2>&1)"
check "merged-clean is removed" no "$(exists merged-clean)"
check "the slashed branch's worktree is removed" no "$(exists feat/slashed)"
has "removal is reported" "removed $M/.claude/worktrees/merged-clean" "$out"
check "a pull request that reopened keeps its worktree" yes "$(exists race)"
has "the recheck names the reason" "kept $M/.claude/worktrees/race: pull request open" "$out"
for d in merged-dirty merged-ahead merged-then-open still-open abandoned no-pr offline locked-one loose forked broken-index; do
  check "$d is untouched" yes "$(exists $d)"
done
check "the branch of a removed worktree stays" merged-clean \
  "$(git -C "$M" branch --list merged-clean --format '%(refname:short)')"

# Running from inside a worktree never removes that worktree.
wt inside; pr inside MERGED 20
out="$(cd "$M/.claude/worktrees/inside" && "$SCRIPT" 2>&1 </dev/null)"
has "the current worktree is kept" "this is where the script runs" "$(grep -E 'worktrees/inside ' <<<"$out")"
out="$(cd "$M/.claude/worktrees/inside" && printf 'y\ny\ny\n' | "$SCRIPT" --remove 2>&1)"
check "the current worktree stays after --remove" yes "$([ -d "$M/.claude/worktrees/inside" ] && echo yes || echo no)"

# A bad option exits 64.
"$SCRIPT" --bogus >/dev/null 2>&1
check "unknown option exits 64" 64 "$?"

# A repository with no other worktree.
SOLO="$SANDBOX/solo"
git init -q -b main "$SOLO"
git -C "$SOLO" commit -q --allow-empty -m init
out="$(cd "$SOLO" && "$SCRIPT" 2>&1)"
has "no worktrees says so" "No worktrees besides the main checkout" "$out"

# --tsv: the table's rows, one per line, cells split by tabs, with the absolute path last.
TAB=$'\t'
HEADER="worktree${TAB}branch${TAB}pull request${TAB}uncommitted${TAB}unpushed${TAB}verdict${TAB}path"
tsv="$(cd "$M" && "$SCRIPT" --tsv 2>/dev/null </dev/null)"; rc=$?
check "--tsv exits 0" 0 "$rc"
check "--tsv starts with the header" "$HEADER" "$(head -n 1 <<<"$tsv")"
table="$(cd "$M" && "$SCRIPT" 2>/dev/null </dev/null | sed '/^$/,$d')"
check "--tsv rows match the table" "$table" "$(cut -f1-6 <<<"$tsv" | column -t -s "$TAB")"
bad_paths=0
while IFS="$TAB" read -r -a cells; do
  p=${cells[6]:-}
  case "$p" in /*) [ -d "$p" ] || bad_paths=$((bad_paths + 1)) ;; *) bad_paths=$((bad_paths + 1)) ;; esac
  [ "${#cells[@]}" -eq 7 ] || bad_paths=$((bad_paths + 1))
done < <(tail -n +2 <<<"$tsv")
check "every --tsv row has seven cells and an absolute path that exists" 0 "$bad_paths"
check "--tsv marks the dirty worktree kept" 1 \
  "$(grep -c "^.claude/worktrees/merged-dirty${TAB}.*${TAB}keep: 1 uncommitted path(s)${TAB}" <<<"$tsv")"
check "--tsv marks the worktree ahead of the merge kept" 1 \
  "$(grep -c "^.claude/worktrees/merged-ahead${TAB}.*${TAB}keep: 1 unpushed commit(s)${TAB}" <<<"$tsv")"
tsv="$(cd "$M/.claude/worktrees/inside" && "$SCRIPT" --tsv 2>/dev/null </dev/null)"
check "--tsv from inside a worktree keeps it" 1 \
  "$(grep -c "^.claude/worktrees/inside${TAB}.*this is where the script runs" <<<"$tsv")"
check "--tsv prints only the header with no other worktree" "$HEADER" "$(cd "$SOLO" && "$SCRIPT" --tsv 2>&1)"
out="$(cd "$SANDBOX" && "$SCRIPT" --tsv 2>/dev/null)"; rc=$?
check "--tsv outside a repository exits 64" 64 "$rc"
check "--tsv outside a repository prints nothing on stdout" "" "$out"

# --remove-path: one worktree, checked again, removed without --force, the branch kept.
wt rp-clean;  pr rp-clean MERGED 31
wt rp-dirty;  pr rp-dirty MERGED 32
echo scratch >"$M/.claude/worktrees/rp-dirty/notes.txt"
wt rp-ahead;  pr rp-ahead MERGED 33
git -C "$M/.claude/worktrees/rp-ahead" commit -q --allow-empty -m "after the merge"
wt rp-locked; pr rp-locked MERGED 34
git -C "$M" worktree lock "$M/.claude/worktrees/rp-locked"
wt rp-open;   pr rp-open OPEN 35
wt rp-slash;  pr rp-slash MERGED 36
wt rp-rel;    pr rp-rel MERGED 37
wt rp-dots;   pr rp-dots MERGED 38
wt rp-link;   pr rp-link MERGED 39
ln -s "$M/.claude/worktrees/rp-link" "$SANDBOX/link-to-rp-link"

rp() { # <cwd> <arg>...: sets out and rc
  out="$(cd "$1" && shift && "$SCRIPT" --remove-path "$@" 2>/dev/null </dev/null)"
  rc=$?
}
rp "$M" "$M/.claude/worktrees/rp-clean"
check "--remove-path removes a done worktree" 0 "$rc"
check "--remove-path says removed" "removed $M/.claude/worktrees/rp-clean" "$out"
check "--remove-path deletes the folder" no "$(exists rp-clean)"
check "--remove-path keeps the branch" rp-clean "$(git -C "$M" branch --list rp-clean --format '%(refname:short)')"
rp "$M" "$M/.claude/worktrees/rp-dirty"
check "--remove-path keeps uncommitted work" 1 "$rc"
check "--remove-path names the uncommitted path" "kept $M/.claude/worktrees/rp-dirty: 1 uncommitted path(s)" "$out"
check "the dirty worktree is still there" yes "$(exists rp-dirty)"
rp "$M" "$M/.claude/worktrees/rp-ahead"
check "--remove-path keeps a commit after the merge" 1 "$rc"
has "--remove-path names the unpushed commit" "1 unpushed commit(s)" "$out"
check "the worktree ahead of the merge is still there" yes "$(exists rp-ahead)"
rp "$M" "$M/.claude/worktrees/rp-locked"
check "--remove-path keeps a locked worktree" "kept $M/.claude/worktrees/rp-locked: locked" "$out"
check "the locked worktree is still there" yes "$(exists rp-locked)"
rp "$M" "$M/.claude/worktrees/rp-open"
check "--remove-path keeps a worktree whose pull request is open" \
  "kept $M/.claude/worktrees/rp-open: pull request open" "$out"
rp "$M/.claude/worktrees/inside" "$M/.claude/worktrees/inside"
check "--remove-path never removes the worktree it runs from" 1 "$rc"
has "--remove-path says why" "this is where the script runs" "$out"
check "the current worktree is still there" yes "$(exists inside)"
rp "$M" "$M"
check "--remove-path refuses the main checkout" "kept $M: not a worktree of this repository" "$out"
check "--remove-path on the main checkout exits 1" 1 "$rc"
rp "$M" "$SANDBOX/nowhere"
check "--remove-path refuses an unknown path" "kept $SANDBOX/nowhere: not a worktree of this repository" "$out"
rp "$M" "$M/.claude/worktrees/rp-slash/"
check "--remove-path takes a trailing slash" 0 "$rc"
check "the worktree named with a trailing slash is removed" no "$(exists rp-slash)"
rp "$M" ".claude/worktrees/rp-rel"
check "--remove-path takes a path relative to where it runs" 0 "$rc"
check "the worktree named by a relative path is removed" no "$(exists rp-rel)"
rp "$M/.claude" "./worktrees/../worktrees/rp-dots//"
check "--remove-path takes ./, ../ and doubled slashes" 0 "$rc"
check "the worktree named with dots is removed" no "$(exists rp-dots)"
rp "$M" "$SANDBOX/link-to-rp-link"
check "--remove-path follows a symbolic link to the worktree" 0 "$rc"
check "the worktree named through a link is removed" no "$(exists rp-link)"
(cd "$M" && "$SCRIPT" --remove-path >/dev/null 2>&1)
check "--remove-path with no path exits 64" 64 "$?"
(cd "$M" && "$SCRIPT" --tsv --remove >/dev/null 2>&1)
check "two options exit 64" 64 "$?"

# /mods offers a switch, Hide, and Reopen from what it finds in the hooks module's source.
MODULE="$HERE/../hooks/register.tsx"
for pattern in 'switches\.json' "component: 'AbovePrompt'" "component: 'Pane'" '\.open-'; do
  check "the hooks module carries what /mods reads: $pattern" 1 "$(grep -cm1 -E "$pattern" "$MODULE")"
done

# The path in scripts/ runs the plugin's copy.
WRAPPER="$HERE/../../../scripts/worktree-cleanup.sh"
"$WRAPPER" --bogus >/dev/null 2>&1
check "the wrapper passes the exit code through" 64 "$?"
check "the wrapper lists the same rows" "$(cd "$M" && "$SCRIPT" --tsv 2>/dev/null </dev/null)" \
  "$(cd "$M" && bash "$WRAPPER" --tsv 2>/dev/null </dev/null)"

if [ "$fails" -ne 0 ]; then
  echo "worktree-cleanup_test.sh: $fails failed" >&2
  exit 1
fi
echo "worktree-cleanup_test.sh: all passed"
