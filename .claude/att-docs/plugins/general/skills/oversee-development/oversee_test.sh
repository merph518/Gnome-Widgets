#!/usr/bin/env bash
# Cases for oversee.sh. A stub gh reads issues and pull requests from files in the sandbox,
# and the queue and ledger live in a throwaway git repository, so nothing real is touched.
# usage: bash oversee_test.sh
set -uo pipefail

command -v jq > /dev/null || { echo "jq is required"; exit 1; }

HERE="$(cd "$(dirname "$0")" && pwd)"
SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT
mkdir -p "$SANDBOX/bin" "$SANDBOX/repo"
export PATH="$SANDBOX/bin:$PATH"
export FIXTURES="$SANDBOX/fixtures"
mkdir -p "$FIXTURES"

# gh stub: `issue list` and `pr list` read the fixture files, `issue view <n>` one issue, and
# `api` moves labels in a per-issue file. --jq is applied with jq, as gh does. `--version`
# prints GH_VERSION, so a case can run oversee.sh against an older gh.
cat > "$SANDBOX/bin/gh" <<'STUB'
#!/usr/bin/env bash
jqx=.
args=("$@")
for ((i = 0; i < ${#args[@]}; i++)); do
  [ "${args[i]}" = --jq ] && jqx=${args[i + 1]}
done
if [ "$1" = --version ]; then
  printf 'gh version %s (2026-01-01)\nhttps://github.com/cli/cli/releases/tag/v%s\n' \
    "${GH_VERSION:-2.94.0}" "${GH_VERSION:-2.94.0}"
  exit 0
fi
case "$1 $2" in
  "issue list") jq -r "$jqx" "$FIXTURES/issues.json" ;;
  "pr list") jq -r "$jqx" "$FIXTURES/prs.json" ;;
  "issue view") jq -c ".[] | select(.number == $3)" "$FIXTURES/issues.json" | jq -r "$jqx" ;;
  "api "*)
    method=GET; for a in "$@"; do [ "$a" = DELETE ] && method=DELETE; [ "$a" = POST ] && method=POST; done
    url=; for a in "$@"; do [[ $a == repos/* ]] && url=$a; done
    n=${url#*/issues/}; n=${n%%/*}
    f="$FIXTURES/labels-$n"; touch "$f"
    if [ "$method" = DELETE ]; then
      name=${url##*/labels/}; name=${name//%20/ }
      grep -vxF "$name" "$f" > "$f.new"; mv "$f.new" "$f"
    else
      for a in "$@"; do [[ $a == labels\[\]=* ]] && echo "${a#'labels[]='}" >> "$f"; done
      jq -Rn '[inputs | {name: .}]' < "$f" | jq -r "$jqx"
    fi ;;
esac
STUB
chmod +x "$SANDBOX/bin/gh"

git -C "$SANDBOX/repo" init -q
cd "$SANDBOX/repo" || exit 1
OS="$HERE/oversee.sh"
LEDGER="$SANDBOX/repo/.claude/oversee/ledger.tsv"
fails=0

check() {
  if [ "$1" = "$2" ]; then echo "ok   $3"; else
    echo "FAIL $3: got [$1], wanted [$2]"; fails=$((fails + 1)); fi
}
# usage: as <session> <pid> <args...>; runs oversee.sh as one conductor session.
as() { local s=$1 p=$2; shift 2; CLAUDE_CODE_SESSION_ID=$s CLAUDE_PID=$p bash "$OS" "$@"; }
first() { head -n 1 | cut -f1-2; }

echo '[
 {"number":5,"title":"voice: first","state":"OPEN","labels":[{"name":"enhancement"},{"name":"ready-for-agent"}]},
 {"number":6,"title":"voice: second","state":"OPEN","labels":[{"name":"ready-for-agent"}]},
 {"number":7,"title":"Install a thing","state":"OPEN","labels":[{"name":"ready-for-agent"}]},
 {"number":8,"title":"voice: waits","state":"OPEN","labels":[{"name":"Blocked"},{"name":"ready-for-agent"}]},
 {"number":9,"title":"att-docs: other area","state":"OPEN","labels":[{"name":"In Progress"},{"name":"ready-for-agent"}]},
 {"number":10,"title":"Tracking","state":"OPEN","labels":[{"name":"Tracker"},{"name":"ready-for-agent"}]},
 {"number":11,"title":"Not yet looked at","state":"OPEN","labels":[{"name":"needs-triage"}]},
 {"number":12,"title":"Waits on the reporter","state":"OPEN","labels":[{"name":"needs-info"}]},
 {"number":13,"title":"Needs a person","state":"OPEN","labels":[{"name":"ready-for-human"}]},
 {"number":14,"title":"Ready for an agent","state":"OPEN","labels":[{"name":"ready-for-agent"}]},
 {"number":15,"title":"Never triaged","state":"OPEN","labels":[{"name":"enhancement"}]},
 {"number":16,"title":"Waits on a blocker","state":"OPEN","labels":[{"name":"ready-for-agent"}],
  "blockedBy":{"nodes":[{"number":99,"state":"OPEN"},{"number":97}],"totalCount":2}},
 {"number":17,"title":"Blocker is closed","state":"OPEN","labels":[{"name":"ready-for-agent"}],
  "blockedBy":{"nodes":[{"number":98,"state":"CLOSED"}],"totalCount":1}}
]' > "$FIXTURES/issues.json"
echo '[]' > "$FIXTURES/prs.json"
LIVE=$$

# --- the queue
as A "$LIVE" init > /dev/null
check "$(cut -f1 "$SANDBOX/repo/.claude/oversee/queue.tsv" | tr '\n' ' ')" "5 6 7 14 16 17 " \
  "the queue holds the issues labeled ready-for-agent, oldest first, and drops excluded labels"
check "$(as A "$LIVE" next | first)" "NEXT	5" "next serves the oldest issue"
check "$(cut -f2 "$SANDBOX/repo/.claude/oversee/queue.tsv" | tr '\n' ' ')" "voice voice - - - - " \
  "an area is the word before the colon in the title"

# --- the gate and blockers
QUEUE="$SANDBOX/repo/.claude/oversee/queue.tsv"
check "$(awk -F'\t' '$1 == 15' "$QUEUE" | wc -l)" 0 "an issue without ready-for-agent is not queued"
check "$(awk -F'\t' '$1 == 16 {print $6}' "$QUEUE")" "#99 #97" \
  "the queue records an open blocker, and a blocker with no state counts as open"
check "$(awk -F'\t' '$1 == 17 {print $6}' "$QUEUE")" "-" "a closed blocker blocks nothing"
as A "$LIVE" init enhancement > /dev/null 2>&1
check "$?" 1 "init refuses to rebuild a queue that already has entries"
OVERSEE_FORCE=1 as A "$LIVE" init enhancement > /dev/null
check "$(cut -f1 "$QUEUE" | tr '\n' ' ')" "5 " \
  "a label argument needs both that label and ready-for-agent"
OVERSEE_FORCE=1 as A "$LIVE" init > /dev/null
check "$(cut -f1 "$QUEUE" | tr '\n' ' ')" "5 6 7 14 16 17 " "an init with no label widens it again"

# --- two sessions
as A "$LIVE" start 5 feat/issue-5-first
check "$?" 0 "start records the issue"
as B "$LIVE" start 5 feat/issue-5-other 2> /dev/null
check "$?" 1 "a second session cannot start an issue held by a live one"
check "$(as A "$LIVE" next | first)" "INFLIGHT	5" "the holder is told to resume its issue"
out=$(as B "$LIVE" next)
check "$(grep -c '^ELSEWHERE	5' <<< "$out")" 1 "another session sees the issue as in flight elsewhere"
check "$(grep -c '^DEFER	6.*area held by issue 5' <<< "$out")" 1 "an issue in the same area is deferred"
check "$(grep -c '^NEXT	7' <<< "$out")" 1 "an issue with no area is served"

# --- finish and an open pull request
as A "$LIVE" finish 5 done 20 "ready"
echo '[{"number":20}]' > "$FIXTURES/prs.json"
out=$(as B "$LIVE" next)
check "$(grep -c '^DEFER	6.*area held by PR #20' <<< "$out")" 1 \
  "a finished issue's open pull request holds its area"
echo '[]' > "$FIXTURES/prs.json"
check "$(as B "$LIVE" next | first)" "NEXT	6" "the area is free once the pull request closes"

# --- a start that is no longer workable
echo '[{"number":6,"title":"voice: second","state":"OPEN","labels":[{"name":"Blocked"},{"name":"ready-for-agent"}]},
 {"number":7,"title":"Install a thing","state":"OPEN","labels":[{"name":"ready-for-agent"}]}]' > "$FIXTURES/issues.json"
as B "$LIVE" start 6 feat/issue-6-second 2> /dev/null
check "$?" 1 "start refuses an issue that picked up an excluded label"
check "$(tail -n 1 "$LEDGER" | cut -f2-3)" "6	skipped" "and records it as skipped"
check "$(as B "$LIVE" next | first)" "NEXT	7" "next passes over it"

# --- withdraw
as B "$LIVE" start 7 feat/issue-7-install
as B "$LIVE" withdraw 7
check "$(as B "$LIVE" next | first)" "NEXT	7" "a withdrawn start puts the issue back in the queue"
as A "$LIVE" withdraw 7 2> /dev/null
check "$?" 1 "withdraw refuses when the issue has no start row"

# --- an orphan
sleep 0 & DEAD=$!; wait "$DEAD"
as C "$DEAD" start 7 feat/issue-7-install
check "$(as A "$LIVE" next | first)" "INFLIGHT	7" "a start whose process has exited is served as an orphan"
check "$(as A "$LIVE" next | cut -f6)" "orphan" "and is marked orphan"
as A "$LIVE" adopt 7
check "$(as A "$LIVE" next | cut -f6)" "mine" "adopt makes the issue the session's own"

# --- label swap
printf 'In Progress\nenhancement\n' > "$FIXTURES/labels-7"
check "$(as A "$LIVE" swap 7 "In Progress" Blocked)" "enhancement,Blocked" \
  "swap moves a label and reads the labels back"
as A "$LIVE" finish 7 done - "ok"
check "$(as A "$LIVE" next | first)" "EMPTY" "next reports EMPTY when nothing is left"

# --- an issue that waits on a blocker, or loses its label
echo '[
 {"number":30,"title":"Waits","state":"OPEN","labels":[{"name":"ready-for-agent"}],
  "blockedBy":{"nodes":[{"number":99,"state":"OPEN"}],"totalCount":1}},
 {"number":31,"title":"Untriaged","state":"OPEN","labels":[]}
]' > "$FIXTURES/issues.json"
out=$(as A "$LIVE" next)
check "$(grep -c '^DEFER	30	-	Waits	blocked by #99' <<< "$out")" 1 \
  "an issue with an open blocker is deferred and the blocker is named"
check "$(grep -c '31' <<< "$out")" 0 "an issue that is not ready-for-agent prints no line"
check "$(tail -n 1 <<< "$out")" "BLOCKED" "next reports BLOCKED when what is left waits on a blocker"
as A "$LIVE" start 30 feat/issue-30-waits 2> /dev/null
check "$?" 1 "start refuses an issue that still has an open blocker"
check "$(tail -n 1 "$LEDGER" | cut -f6)" "not workable at start: blocked by #99" "and records the blocker"
echo '[{"number":30,"title":"Waits","state":"OPEN","labels":[],
  "blockedBy":{"nodes":[{"number":99,"state":"CLOSED"}],"totalCount":1}}]' > "$FIXTURES/issues.json"
as A "$LIVE" start 30 feat/issue-30-waits 2> /dev/null
check "$?" 1 "start refuses an issue that lost ready-for-agent"
check "$(tail -n 1 "$LEDGER" | cut -f6)" "not workable at start: not labeled ready-for-agent" \
  "and records the missing label"
check "$(as A "$LIVE" next)" "EMPTY" "a skipped issue stays out while the label is missing"
echo '[{"number":30,"title":"Waits","state":"OPEN","labels":[{"name":"ready-for-agent"}],
  "blockedBy":{"nodes":[{"number":99,"state":"CLOSED"}],"totalCount":1}}]' > "$FIXTURES/issues.json"
check "$(as A "$LIVE" next | first)" "NEXT	30" "the issue is served again once the label is back and the blocker closed"

# --- the gh version
GH_VERSION=2.93.9 CLAUDE_CODE_SESSION_ID=A CLAUDE_PID=$LIVE bash "$OS" next > /dev/null 2> "$SANDBOX/err"
check "$?" 1 "next stops on a gh older than 2.94"
check "$(grep -c 'needs gh 2.94 or newer' "$SANDBOX/err")" 1 "and says which gh it needs"
GH_VERSION=2.100.1 CLAUDE_CODE_SESSION_ID=A CLAUDE_PID=$LIVE bash "$OS" next > /dev/null 2>&1
check "$?" 0 "a two-digit minor above 94 is accepted"
GH_VERSION=3.0.0 CLAUDE_CODE_SESSION_ID=A CLAUDE_PID=$LIVE bash "$OS" next > /dev/null 2>&1
check "$?" 0 "a newer major is accepted"
GH_VERSION=2.93.9 CLAUDE_CODE_SESSION_ID=A CLAUDE_PID=$LIVE bash "$OS" status > /dev/null 2>&1
check "$?" 0 "an old gh does not stop commands that only read the ledger"

# --- a milestone: its own repository, so the state is separate
R2="$SANDBOX/repo2"
mkdir -p "$R2"
git -C "$R2" init -q
cd "$R2" || exit 1
LEDGER2="$R2/.claude/oversee/ledger.tsv"
QUEUE2="$R2/.claude/oversee/queue.tsv"
FILTER2="$R2/.claude/oversee/filter"
M="Wave One"
RA=ready-for-agent
sleep 0 & DEAD2=$!; wait "$DEAD2"

# mk <number> <title> <labels, comma separated> <milestone or -> [body]
mk() {
  jq -n --argjson n "$1" --arg t "$2" --arg l "$3" --arg m "$4" --arg b "${5:-}" '{
    number: $n, title: $t, state: "OPEN", body: $b,
    labels: ($l | split(",") | map(select(. != "") | {name: .})),
    milestone: (if $m == "-" then null else {title: $m} end)}'
}
fixture() { jq -s . > "$FIXTURES/issues.json"; }
fresh() { rm -rf "$R2/.claude/oversee"; echo '[]' > "$FIXTURES/prs.json"; }
order() { cut -f1 "$QUEUE2" | tr '\n' ' '; }

# --- the milestone filter
fresh
{ mk 1 "In the milestone" "$RA" "$M"
  mk 2 "No milestone" "$RA" -
  mk 3 "Another milestone" "$RA" "Wave Two"
  mk 4 "Blocked one" "$RA,Blocked" "$M"
  mk 5 "Held one" "$RA,In Progress" "$M"
  mk 6 "Tracking" "$RA,Tracker" "$M"; } | fixture
as A "$LIVE" init --milestone "$M" > /dev/null
check "$(order)" "1 " "a milestone queues only its ready issues"
check "$(wc -l < "$R2/.claude/oversee/open" | tr -d ' ')" 6 "the open list still holds every open issue"
check "$(as A "$LIVE" next | first)" "NEXT	1" "next serves the issue in the milestone"
as A "$LIVE" start 1 feat/issue-1 2> /dev/null
as A "$LIVE" finish 1 done - "ok"
check "$(as A "$LIVE" next | first)" "EMPTY" "issues outside the milestone are never served"

fresh
mk 1 "Titled apart" "$RA" "Voice Bridge" | fixture
as A "$LIVE" init --milestone Voice > /dev/null 2> "$SANDBOX/err"
check "$(order)" "" "a milestone title matches whole, not as a prefix"
check "$(grep -c 'no open issue in milestone "Voice"' "$SANDBOX/err")" 1 \
  "an empty milestone warns on stderr"
check "$(as A "$LIVE" next 2> /dev/null | first)" "EMPTY" "and next ends at EMPTY"

fresh
{ mk 1 "Plain" "$RA" -; mk 2 "voice: second" "$RA" -; } | fixture
as A "$LIVE" init > /dev/null
check "$(awk -F'\t' '{print NF, $7, $8}' "$QUEUE2" | sort -u)" "8 - -" \
  "without a milestone the queue has eight columns and no waits or pick"
check "$(as A "$LIVE" next | head -n 1 | awk -F'\t' '{print NF}')" 4 "and NEXT has no pick column"
check "$(sed -n 2p "$FILTER2")" "" "and the filter has no milestone line"

fresh
{ mk 1 "voice: both" "$RA,voice" "$M"
  mk 2 "Only the milestone" "$RA" "$M"
  mk 3 "voice: only the label" "$RA,voice" "Wave Two"; } | fixture
as A "$LIVE" init voice --milestone "$M" > /dev/null
check "$(order)" "1 " "a label and a milestone are both required"
as A "$LIVE" init --milestone > /dev/null 2>&1
check "$?" 1 "--milestone without a value exits 1"
OVERSEE_FORCE=1 as A "$LIVE" init one two > /dev/null 2>&1
check "$?" 1 "a second label exits 1"

# --- dependencies in the issue body
fresh
{ mk 40 "Dependent" "$RA" "$M" $'## Depends on\n\n- #42 for the data. The rest is free.\n'
  mk 41 "Independent" "$RA" "$M"
  mk 42 "Dependency" "$RA" "$M"; } | fixture
as A "$LIVE" init --milestone "$M" > /dev/null
check "$(order)" "42 40 41 " "an issue others wait on is queued ahead of them"
check "$(as A "$LIVE" next | first)" "NEXT	42" "next serves the dependency first"
as A "$LIVE" start 42 feat/issue-42 2> /dev/null
as A "$LIVE" finish 42 done 20 "ready"
echo '[{"number":20}]' > "$FIXTURES/prs.json"
out=$(as A "$LIVE" next)
check "$(grep -c '^DEFER	40.*waits on #42 (pull request 20 open)' <<< "$out")" 1 \
  "a dependent waits while its dependency's pull request is open"
check "$(grep -c '^NEXT	41' <<< "$out")" 1 "and the independent issue is served"
{ mk 40 "Dependent" "$RA" "$M" $'## Depends on\n\n- #42 for the data.\n'
  mk 41 "Independent" "$RA" "$M"; } | fixture
check "$(as A "$LIVE" next | first)" "NEXT	40" "the dependent is served once the dependency closes"

fresh
{ mk 50 "Waits" "$RA" "$M" $'Depends on #60\nDepends on #61\nDepends on owner/repo#63\nDepends on #64\n'
  mk 60 "Open outside" "needs-triage" "Wave Two"
  mk 64 "Tracking" "Tracker" "$M"; } | fixture
as A "$LIVE" init --milestone "$M" > /dev/null
check "$(awk -F'\t' '$1 == 50 {print $7}' "$QUEUE2")" "#60" \
  "only an open dependency waits; closed, cross-repository and tracker references do not"
out=$(as A "$LIVE" next)
check "$(grep -c '^DEFER	50.*waits on #60$' <<< "$out")" 1 "next names the open dependency"
check "$(tail -n 1 <<< "$out")" "BLOCKED" "and ends at BLOCKED"

fresh
body=$'Depends on: #1, #2\n- Blocked by #3 and #4\n**Depends on** #5\n## Blocked by\n- #6\n'
body+=$'## Notes\nRelated to #7 for later.\n- #9 is related\n```\nDepends on #8\n```\n'
{ for n in 1 2 3 4 5 6 7 8 9; do mk "$n" "Dep $n" "needs-triage" "$M"; done
  mk 10 "Many" "$RA" "$M" "$body"; } | fixture
as A "$LIVE" init --milestone "$M" > /dev/null
check "$(awk -F'\t' '$1 == 10 {print $7}' "$QUEUE2")" "#1 #2 #3 #4 #5 #6" \
  "dependency lines are read in line, list and section forms, and prose and code are not"

fresh
{ mk 80 "Root" "$RA" "$M"
  mk 81 "Chain 1" "$RA" "$M" "Depends on #80"
  mk 82 "Chain 2" "$RA" "$M" "Depends on #81"
  mk 83 "Chain 3" "$RA" "$M" "Depends on #82"
  mk 90 "Fan root" "$RA" "$M"
  mk 91 "Fan 1" "$RA" "$M" "Depends on #90"
  mk 92 "Fan 2" "$RA" "$M" "Depends on #90"; } | fixture
as A "$LIVE" init --milestone "$M" > /dev/null
check "$(order)" "80 81 90 82 83 91 92 " "dependents are counted through the whole chain"

fresh
{ mk 70 "Cycle a" "$RA" "$M" "Depends on #71"
  mk 71 "Cycle b" "$RA" "$M" "Depends on #70"; } | fixture
as A "$LIVE" init --milestone "$M" > /dev/null
out=$(as A "$LIVE" next)
check "$(grep -c '^DEFER' <<< "$out")" 2 "a dependency cycle defers both issues"
check "$(tail -n 1 <<< "$out")" "BLOCKED" "and ends at BLOCKED"

# --- ranking
fresh
{ mk 1 "Low" "$RA" "$M" "Priority: low"
  mk 2 "Unstated" "$RA" "$M"
  mk 3 "Critical" "$RA" "$M" "- **Priority:** P0"
  mk 4 "High" "$RA" "$M" "Priority: high"
  mk 5 "High by heading" "$RA" "$M" $'## Priority\n\nHigh\n'
  mk 6 "First word wins" "$RA" "$M" $'Priority: low\nPriority: critical'; } | fixture
as A "$LIVE" init --milestone "$M" > /dev/null
check "$(order)" "3 4 5 2 1 6 " "stated priority orders the queue, and none ranks as medium"

fresh
{ mk 1 "High" "$RA" "$M" "Priority: high"
  mk 2 "Low root" "$RA" "$M" "Priority: low"
  mk 3 "Unstated" "$RA" "$M" "Depends on #2"; } | fixture
as A "$LIVE" init --milestone "$M" > /dev/null
check "$(order)" "2 1 3 " "an issue others wait on is served ahead of a higher priority"

fresh
{ mk 100 "Tracking" "Tracker" "$M" $'- [ ] #112\n- [ ] #111\n3. #113\n- #114\n'
  for n in 111 112 113 114 115; do mk "$n" "Item $n" "$RA" "$M"; done; } | fixture
as A "$LIVE" init --milestone "$M" > /dev/null
check "$(order)" "112 111 113 114 115 " "a tracker lists the order, plain bullets excepted"
{ mk 100 "Tracking" "Tracker" "$M" $'- [ ] #112\n- [ ] #111\n3. #113\n- #114\n'
  for n in 111 112 113 114; do mk "$n" "Item $n" "$RA" "$M"; done
  mk 115 "Item 115" "$RA" "$M" "Priority: high"; } | fixture
OVERSEE_FORCE=1 as A "$LIVE" init --milestone "$M" > /dev/null
check "$(order)" "115 112 111 113 114 " "stated priority ranks above tracker order"
{ mk 100 "Tracking" "Tracker" "$M" $'- [ ] #112\n- [ ] #111\n'
  mk 111 "Item 111" "$RA" "$M"
  mk 112 "Item 112" "$RA,Blocked" "$M"; } | fixture
check "$(as A "$LIVE" next | first)" "NEXT	111" "tracker order ranks and never gates"

# --- the pick reason, resume, and the ledger
fresh
{ mk 1 "Root" "$RA" "$M"; mk 2 "Leaf" "$RA" "$M" "Depends on #1"; } | fixture
as A "$LIVE" init --milestone "$M" > /dev/null
check "$(as A "$LIVE" next | head -n 1 | cut -f5)" "pick: unblocks 1 open issue" \
  "next gives the reason for the pick"
as A "$LIVE" start 1 feat/issue-1-root
check "$(tail -n 1 "$LEDGER2" | cut -f6)" "session A pid $LIVE; pick: unblocks 1 open issue" \
  "start records the owner and the reason without being told"
check "$(as A "$LIVE" status | grep -c 'pick: unblocks')" 1 "status shows the reason"
fresh
{ mk 1 "Root" "$RA" -; } | fixture
as A "$LIVE" init > /dev/null
as A "$LIVE" start 1 feat/issue-1-root
check "$(tail -n 1 "$LEDGER2" | cut -f6)" "session A pid $LIVE" \
  "without a milestone the note is the owner tag alone"

fresh
{ mk 1 "Root" "$RA" "$M"; mk 2 "Leaf" "$RA" "$M" "Depends on #1"; } | fixture
as A "$LIVE" init --milestone "$M" > /dev/null
as C "$DEAD2" start 1 feat/issue-1-root
as A "$LIVE" adopt 1
check "$(tail -n 1 "$LEDGER2" | cut -f6 | grep -c 'adopted; pick: unblocks 1 open issue')" 1 \
  "adopt keeps the reason"

fresh
{ mk 1 "voice: one" "$RA,voice" "$M"
  mk 2 "Two" "$RA" "$M"
  mk 3 "Three" "$RA" -; } | fixture
as A "$LIVE" init --milestone "$M" > /dev/null
as B "$LIVE" refresh > /dev/null
check "$(order)" "1 2 " "a bare refresh keeps the milestone"
check "$(as B "$LIVE" status | grep -c '^scope: milestone "Wave One"')" 1 "status shows the scope"
as B "$LIVE" refresh voice > /dev/null
check "$(order)" "1 " "a refresh with a label keeps the milestone"
check "$(sed -n 1,2p "$FILTER2" | tr '\n' '|')" "voice|Wave One|" "and the filter holds both"
OVERSEE_FORCE=1 as B "$LIVE" init > /dev/null
check "$(order)" "1 2 3 " "a forced bare init drops the milestone"

fresh
{ mk 40 "In flight" "$RA" "$M"; mk 41 "Outside" "$RA" -; } | fixture
as A "$LIVE" init --milestone "$M" > /dev/null
as A "$LIVE" start 40 feat/issue-40
{ mk 40 "In flight" "In Progress" "Wave Two"; mk 41 "Outside" "$RA" -; } | fixture
check "$(as A "$LIVE" next | first)" "INFLIGHT	40" "an issue the ledger names stays in flight when it leaves the milestone"
check "$(as B "$LIVE" next | grep -c '^NEXT')" 0 "and nothing outside the milestone is served"

fresh
{ mk 40 "Moved" "$RA" "$M"; } | fixture
as A "$LIVE" init --milestone "$M" > /dev/null
mk 40 "Moved" "$RA" "Wave Two" | fixture
as A "$LIVE" start 40 feat/issue-40 2> /dev/null
check "$?" 1 "start refuses an issue that left the milestone"
check "$(tail -n 1 "$LEDGER2" | cut -f6)" "not workable at start: not in milestone Wave One" \
  "and records the milestone"

fresh
{ mk 1 "voice: first" "$RA" "$M"; mk 2 "voice: second" "$RA" "$M"; } | fixture
as A "$LIVE" init --milestone "$M" > /dev/null
as A "$LIVE" start 1 feat/issue-1
as A "$LIVE" finish 1 done 20 "ready"
echo '[{"number":20}]' > "$FIXTURES/prs.json"
check "$(as A "$LIVE" next | grep -c '^DEFER	2.*area held by PR #20')" 1 \
  "a milestone issue waits for an open pull request in its area"

fresh
{ mk 1 "In" "$RA" "$M"; mk 2 "Out" "$RA" -; } | fixture
as A "$LIVE" refresh --milestone "$M" > /dev/null
check "$(as A "$LIVE" next | first)" "NEXT	1" "refresh --milestone on empty state scopes the first next"
as A "$LIVE" finish 1 done - "ok"
check "$(as A "$LIVE" next | first)" "EMPTY" "and nothing outside the milestone is served after"

fresh
{ for n in 1 2 3 4 5; do mk "$n" "Dep $n" "needs-triage" "$M"; done
  mk 10 "Markers" "$RA" "$M" $'+ Depends on #1\n1. Depends on #2\n2) Blocked by #3\n* Depends on #4\n'
  mk 11 "Plain bullet" "$RA" "$M" $'- Blocked by #5\n'; } | fixture
as A "$LIVE" init --milestone "$M" > /dev/null
check "$(awk -F'\t' '$1 == 10 {print $7}' "$QUEUE2")" "#1 #2 #3 #4" \
  "plus, numbered and star markers open a dependency line"
check "$(awk -F'\t' '$1 == 11 {print $7}' "$QUEUE2")" "#5" "and so does a dash"

fresh
{ mk 40 "Moved" "$RA" "$M"; } | fixture
as A "$LIVE" init --milestone "$M" > /dev/null
mk 40 "Moved" "$RA" "Wave Two" | fixture
as A "$LIVE" start 40 feat/issue-40 2> /dev/null
mk 40 "Moved" "$RA" "$M" | fixture
check "$(as A "$LIVE" next | first)" "NEXT	40" "an issue skipped for leaving the milestone returns with it"

fresh
{ mk 2 "Milestone only" "$RA" "$M"; mk 3 "Label only" "$RA,voice" -; } | fixture
as A "$LIVE" refresh voice > /dev/null
OVERSEE_FORCE=1 as A "$LIVE" init --milestone "$M" > /dev/null
check "$(as A "$LIVE" next | first)" "NEXT	2" "a forced init with a milestone drops a saved label"
OVERSEE_FORCE=1 as A "$LIVE" init voice > /dev/null
check "$(as A "$LIVE" next | first)" "NEXT	3" "a forced init with a label drops a saved milestone"
check "$(as A "$LIVE" status | grep -c '^scope: label voice$')" 1 \
  "status shows a scope that is a label alone"

fresh
{ mk 2 "Outside orphan" "$RA" -; mk 3 "Inside" "$RA" "$M"; mk 4 "Inside orphan" "$RA" "$M"; } |
  fixture
as A "$LIVE" init > /dev/null
as C "$DEAD2" start 2 feat/issue-2
as C "$DEAD2" start 4 feat/issue-4
OVERSEE_FORCE=1 as A "$LIVE" init --milestone "$M" > /dev/null
check "$(as A "$LIVE" next | first)" "INFLIGHT	4" "a milestone run adopts an orphan inside the milestone"
as A "$LIVE" finish 4 done - "ok"
check "$(as A "$LIVE" next | grep -v '^ELSEWHERE' | first)" "NEXT	3" "and never one outside it"
fresh
{ mk 2 "Outside orphan" "$RA" -; } | fixture
as A "$LIVE" init > /dev/null
as C "$DEAD2" start 2 feat/issue-2
check "$(as A "$LIVE" next | first)" "INFLIGHT	2" "without a milestone an orphan is served"

fresh
{ mk 2 "voice: outside orphan" "$RA" -; mk 3 "voice: inside" "$RA" "$M"; } | fixture
as A "$LIVE" init > /dev/null
as C "$DEAD2" start 2 feat/issue-2
OVERSEE_FORCE=1 as A "$LIVE" init --milestone "$M" > /dev/null
out=$(as A "$LIVE" next)
check "$(grep -c '^ELSEWHERE	2' <<< "$out")" 1 "an orphan outside the milestone is printed"
check "$(grep -c '^DEFER	3.*area held by issue 2 orphaned outside the milestone' <<< "$out")" 1 \
  "and holds its area against an issue inside the milestone"
check "$(tail -n 1 <<< "$out")" "BLOCKED" "and counts as busy"


fresh
{ for n in 21 22 23 24 25; do mk "$n" "Dep $n" "needs-triage" "$M"; done
  mk 20 "Prose" "$RA" "$M" \
    $'Intro. Depends on #21 but see #22 for context. **Blocked by**: #23 and #24.\nOther: #25\n'
  mk 26 "Cross" "$RA" "$M" "Depends on owner/repo#25 later"; } | fixture
as A "$LIVE" init --milestone "$M" > /dev/null
check "$(awk -F'\t' '$1 == 20 {print $7}' "$QUEUE2")" "#21 #23 #24" \
  "a dependency phrase mid-paragraph takes only the references that follow it"
check "$(awk -F'\t' '$1 == 26 {print $7}' "$QUEUE2")" "-" "a cross-repository reference stays skipped"

fresh
{ mk 31 "Unrelated" "$RA" "$M"
  mk 32 "Blocked natively" "$RA" "$M" |
    jq '.blockedBy = {nodes: [{number: 33, state: "OPEN"}], totalCount: 1}'
  mk 33 "Native blocker" "$RA" "$M"; } | fixture
as A "$LIVE" init --milestone "$M" > /dev/null
check "$(order)" "33 31 32 " "a native blocker ranks ahead of unrelated issues"
check "$(as A "$LIVE" next | head -n 1 | cut -f5)" "pick: unblocks 1 open issue" \
  "and the reason counts the issue it blocks"
cd "$SANDBOX/repo" || exit 1

if ((fails)); then echo "$fails failed"; exit 1; fi
echo "all passed"
