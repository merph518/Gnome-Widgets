#!/usr/bin/env bash
# usage: speak-attention.sh --config <extension.json> < <hook payload>
# Speaks the session's name and what it needs. Reads the hook payload on
# stdin and handles three events:
#   Stop                           the turn ended with no background work due to
#                                  wake it, and stop_attention.py says what it
#                                  needs from the user, or an earlier stop held
#                                  back by background work owes what it held
#   PreToolUse  AskUserQuestion    the session is about to ask a question
#   PostToolUse Bash               a pull request got the review label
# The extension file names the review label (reviewLabel), the words spoken once it
# lands (reviewAnnouncement), and the words the voice would misread (spokenTerms). A
# missing --config exits 64.
# With speech mode on, the reply is read aloud instead, and the other announcements
# stay quiet. It starts off. Each text block is read as it lands: a PreToolUse for any
# tool reads what was written ahead of that call, and the Stop reads the rest. An
# AskUserQuestion call's question and options are read with the text ahead of it, and
# a wrap-up question with its buttons after the closing reply.
# /implement-with-speech turns it on for the session, typed (UserPromptSubmit) or
# called through the Skill tool (PostToolUse Skill), and a typed /implement turns
# it off. A Skill call to implement leaves it alone, since /implement-with-speech
# hands its work to that skill.
# Outside speech mode, a session a phone follows through the voice bridge still sends its
# text to the voice feed ahead of each tool call, and reads none of it aloud.
# Anything else exits quietly, as does a machine without jq or python3, or with
# neither Piper nor spd-say to speak.
# The label case asks ready_line.py, which holds the same rules for the ready signal, so
# the two never disagree on what a label add is.

# When the hook started, in epoch ms: an event the app delivers from then on
# starts a turn after this stop.
stop_at=$(date +%s%3N)

if [[ ${1:-} == --config && -f ${2:-} ]]; then
  config=$2
  shift 2
else
  echo "speak-attention.sh: --config <extension.json> is required" >&2
  exit 64
fi

for bin in jq python3; do
  command -v "$bin" >/dev/null || exit 0
done

input=$(cat)
# Every tool call runs this hook, and outside speech mode only a question says anything,
# and a followed session's text goes to the voice feed, so a call leaves before the payload
# is parsed when no session has speech mode on and no phone follows one.
# The bridge touches voice-bridge/follow/<socket name> as the phone polls; a marker idle
# longer than FOLLOW_IDLE_SECONDS in voice_bridge_reply.py no longer counts.
follow_dir=${XDG_RUNTIME_DIR:-/tmp}/voice-bridge/follow
# usage: followed; succeeds while a phone follows this session.
followed() {
  local key=${CLAUDE_CODE_MESSAGING_SOCKET:-}
  [[ $key == *.sock ]] || return 1
  key=${key##*/}
  [[ -e "$follow_dir/${key%.sock}" && -n $(find "$follow_dir/${key%.sock}" -mmin -30 -print -quit \
    2>/dev/null) ]]
}
if [[ $input == *'"hook_event_name":"PreToolUse"'* &&
  $input != *'"tool_name":"AskUserQuestion"'* ]] &&
  ! compgen -G "${XDG_RUNTIME_DIR:-/tmp}/speak-attention/*.replies" >/dev/null &&
  ! followed; then
  exit 0
fi
field() { jq -r "$1 // empty" <<<"$input"; }
here=$(dirname "$(readlink -f "$0")")
ready_line() {
  python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import hook_config
hook_config.use(sys.argv.pop(2)); import ready_line as e
'"$1" "$here" "$config" "${@:2}"
}

event=$(field .hook_event_name)
tool=$(field .tool_name)
transcript=$(field .transcript_path)
[[ -f "$transcript" ]] || transcript=/dev/null

# A stop held quiet by background work owes the user the announcement it
# skipped. The marker carries that debt to the next stop that would otherwise
# stay quiet, and any announcement pays it.
session=$(field .session_id)
owed=${XDG_RUNTIME_DIR:-/tmp}/speak-attention/${session:-none}.owed
# The marker that holds speech mode on for this session.
replies=${owed%.owed}.replies

# usage: speech_mode <command>; sets the mode for the slash command a prompt opens with.
speech_mode() {
  [[ -n "$session" ]] || return 0
  case $1 in
    /implement-with-speech)
      mkdir -p "${replies%/*}" && : > "$replies" &&
        python3 "$here/speak_pending.py" "$transcript" "$cursor" seen 2>/dev/null
      ;;
    /implement) rm -f "$replies" "$cursor" "$queue" ;;
  esac
}

# usage: command_of <prompt>; prints the slash command the prompt opens with, from
# its first word or, for a command the app expanded, its command-name tag.
command_of() {
  local flat tags
  flat=$(tr '\n' ' ' <<<"$1")
  tags='^[[:space:]]*(<command-message>[^<]*</command-message>[[:space:]]*)?'
  tags+='<command-name>([^<]*)</command-name>'
  if [[ $flat =~ $tags ]]; then
    printf '%s' "${BASH_REMATCH[2]}"
  elif [[ $flat =~ ^[[:space:]]*(/[^[:space:]]+) ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
  fi
}

# usage: speakable; reads Markdown on stdin and prints it as plain sentences. Code
# blocks and file links say nothing worth hearing, so they go, and a bare URL is
# read as "the following link" so its sentence still ends. A link whose
# text is words, such as a session title, keeps its text, and an owner/repo#N
# link is read as its number. A link to a workflow run says only the words of its
# text, a bare run URL says nothing, and run and job ids are dropped. A duration
# such as 7.0s, 30 min or 1h30m is read with its units spelled out, and the words in
# the extension file's spokenTerms are read as it says them aloud.
speakable() {
  python3 -c '
import json, re, sys
EXT = "ts|js|mjs|md|sh|py|json|ya?ml|tsv|csv|sql|txt|html|css|xlsx"
RUN_URL = r"https?://\S*/actions/runs/\S*"
def link(m):
    text = m.group(1).strip("`")
    if re.fullmatch(RUN_URL, m.group(2)):
        return " " if re.fullmatch(r"[\d\s#-]*", text) else text
    ref = re.fullmatch(r"[\w.-]+/[\w.-]+#(\d+)", text)
    if ref:
        return ref.group(1)
    if "/" in text or re.fullmatch(r"(?![A-Z][a-z]+\.)\S+\.(" + EXT + r")(:\d+)?", text):
        return " "
    return m.group(1)
UNITS = {"h": "hour", "hr": "hour", "hrs": "hour", "m": "minute", "min": "minute",
         "mins": "minute", "s": "second", "sec": "second", "secs": "second"}
# a one-letter unit has to touch its number, so "option 1 m" is left alone, and
# an m ahead of a plural noun, as in "3m rows", is a million rather than minutes.
# Short words and ones ending in -is, -as, -us or -ss, such as "is" or "plus",
# are not plural nouns.
PLURAL = r" [a-z]{2,}[^\Waiusx]s\b"
PART = r"(\d+(?:\.\d+)?)(?:(h|m(?!" + PLURAL + r")|s)|\s?(hrs|hr|mins|min|secs|sec))"
def duration(m):
    text = m.group(0)
    # "the 1990s" is a decade, while "the 30s cap" is still seconds
    if m.string.endswith("the ", 0, m.start()) and re.fullmatch(r"\d{3}0s", text):
        return text
    # "1000s of rows" is a count, while "30s of idle time" is still seconds
    if m.string.startswith(" of ", m.end()) and re.fullmatch(r"\d+00s", text):
        return text
    words = []
    for n, letter, word in re.findall(PART, text):
        words.append(n + " " + UNITS[letter or word] + ("" if n == "1" else "s"))
    return " ".join(words)
DURATION = r"\b(?:" + PART + r")+\b"
# words the voice would otherwise misread, and how they are said
with open(sys.argv[1], encoding="utf-8") as f:
    SAID = json.load(f).get("spokenTerms") or {}
t = sys.stdin.read()
t = re.sub(r"```.*?(```|$)", " ", t, flags=re.S)
t = re.sub(r"\[([^\]]*)\]\(([^)]*)\)", link, t)
t = re.sub(r"<?" + RUN_URL + r"[^\s.,;:!?)]>?", " ", t)
t = re.sub(r"<?https?://\S*[^\s.,;:!?)]>?", "the following link", t)
# run and job ids carry nothing worth hearing: "run 39694323023" is read as "run".
# Three digits or more, so a count such as "run 2 minutes apart" stays.
t = re.sub(r"\b([Rr]uns?|[Jj]obs?) #?\d{3,}(?:-\d+)?\b", r"\1", t)
t = re.sub(r"\b\d{8,}(?:-\d+)?\b", " ", t)
t = re.sub(DURATION, duration, t)
if SAID:
    t = re.sub(r"\b(" + "|".join(map(re.escape, SAID)) + r")\b", lambda m: SAID[m.group(1)], t)
t = re.sub(r"^\s*\|?[\s:|-]+\|[\s:|-]*$", " ", t, flags=re.M)
t = re.sub(r"[`*#>|\[\]]", " ", t)
print(re.sub(r" ([.,;:!?])", r"\1", " ".join(t.split())))' "$config"
}

# usage: session_name; prints the name the voice gives the session: its latest title,
# the one set by hand first, else the folder, then "session" said once.
session_name() {
  local title
  title=$(tac "$transcript" | grep -m1 '"type":"custom-title"' |
    jq -r '.customTitle // empty' 2>/dev/null)
  [[ -z "$title" ]] && title=$(tac "$transcript" | grep -m1 '"type":"ai-title"' |
    jq -r '.aiTitle // empty' 2>/dev/null)
  [[ -z "$title" ]] && title=$(basename "$(field .cwd)")
  shopt -s nocasematch
  [[ $title =~ ^((.*[^[:space:]_-])[[:space:]_-]+)?session[[:space:]]*$ ]] &&
    title=${BASH_REMATCH[2]}
  shopt -u nocasematch
  printf '%s' "${title:+$title }session" | speakable
}

dir=${XDG_RUNTIME_DIR:-/tmp}/speak-attention
wav=$dir/$$.wav
trap 'rm -f "$wav"' EXIT

# usage: say <text>; speaks it and returns once it has played.
# Piper speaks when it and its voice model are installed; SPEAK_PIPER_MODEL names the
# model, and SPEAK_PIPER_LENGTH its pace, faster below 1. Only the pipx install counts,
# since the apt package named piper is an unrelated GTK app. pw-play plays with the
# Speech role, since a role's saved volume applies to every stream that carries it.
# Piper renders at 0.8 volume, below where its peaks clip, and the stream plays at 1.2
# to make up the level. Once Piper has rendered, pw-play's exit status is not checked,
# so a clip that played and then failed is never spoken a second time.
say() {
  local piper=$HOME/.local/bin/piper args
  local model=${SPEAK_PIPER_MODEL:-$HOME/.local/share/piper/en_US-amy-medium.onnx}
  local pace=${SPEAK_PIPER_LENGTH:-0.85}
  if [[ -x "$piper" && -f "$model" ]] && command -v pw-play >/dev/null &&
    "$piper" -m "$model" --length-scale "$pace" --volume 0.8 -f "$wav" \
      <<<"$1" >/dev/null 2>&1 8>&- 9>&-; then
    pw-play --media-role=Speech --volume 1.2 "$wav" >/dev/null 2>&1 8>&- 9>&-
    return 0
  fi
  # Speech Dispatcher speaks when Piper cannot: RHVoice when its module is installed,
  # else the default. SPEAK_VOICE picks one of its voices (spd-say -o rhvoice -L lists
  # them).
  command -v spd-say >/dev/null || return 0
  args=(--wait)
  if spd-say -O 2>/dev/null 8>&- 9>&- | grep -qx rhvoice; then
    args+=(-o rhvoice -l en -y "${SPEAK_VOICE:-Slt}")
  else
    args+=(-r -10)
  fi
  # The text goes as one argument, which the kernel caps at 128 KiB, so a longer reply
  # is cut short rather than not spoken at all. The cap counts characters, up to four
  # bytes each.
  spd-say "${args[@]}" -- "${1:0:30000}" >/dev/null 2>&1 8>&- 9>&- || true
}

# One clip plays at a time: hooks that fire together wait on this lock. An announcement
# that waits two minutes stays quiet rather than talk over the clip still playing; a
# reply waits fifteen, since the reply ahead of it can run for several.
# usage: hold_voice <seconds>; returns 1 when the wait runs out.
hold_voice() {
  if { mkdir -p "$dir" && exec 9>"$dir/speak.lock"; } 2>/dev/null; then
    flock -w "$1" 9 || return 1
  fi
}

# In speech mode the reply text goes on a queue, one line per block, and whichever hook
# holds the voice reads the queue in order, so blocks that land while one is playing are
# read after it and never out of turn. The cursor lock keeps two hooks that fire
# together from queueing the same block twice. The same blocks, as written, go to the
# voice bridge's feed for this session as one entry per hook, and the bridge makes them
# speakable for a phone following it. A followed session outside speech mode takes the same
# path with nothing queued or spoken. A block the speaker finds nothing to say in still
# goes, and the bridge decides what of it the phone hears.
queue=${replies%.replies}.queue
cursor=${replies%.replies}.cursor

# usage: await_text_row; the app writes transcript rows in batches, so a tool call can
# start before the text ahead of it is on disk. The call's own row lands with or after
# that text, so the hook, which runs async, waits up to fifteen seconds for it.
await_text_row() {
  local id
  id=$(field .tool_use_id)
  if [[ $event == PreToolUse && -n "$id" && -f "$transcript" ]]; then
    for _ in {1..30}; do
      grep -qF "\"$id\"" "$transcript" && break
      sleep 0.5
    done
  fi
}

# usage: read_aloud; queues the turn's unread text and reads the queue. Outside speech mode
# only the voice feed gets the text, while a phone follows the session, and nothing is
# queued or spoken.
read_aloud() {
  local fields name='' chunk text line
  local args=("$here/speak_pending.py" "$transcript" "$cursor")
  [[ $event == Stop ]] && args+=(stop "$(field .last_assistant_message)")
  await_text_row
  mkdir -p "$dir"
  {
    flock -w 30 8 || return 0
    mapfile -d '' fields < <(python3 "${args[@]}" 2>/dev/null)
    [[ ${fields[0]:-0} == 1 ]] && name="$(session_name) says: "
    local pushed=$name
    for chunk in "${fields[@]:1}"; do
      pushed+=$chunk$'\n\n'
      [[ -e "$replies" ]] || continue
      text=$(speakable <<<"$chunk")
      [[ -n "$text" ]] || continue
      printf '%s\n' "$name$text" >> "$queue"
      name=
    done
    [[ ${#fields[@]} -gt 1 ]] &&
      python3 "$here/voice_bridge_reply.py" --config "$config" push <<<"$pushed" 2>/dev/null
  } 8>"$cursor.lock"
  [[ -e "$replies" ]] || return 0
  rm -f "$owed"
  [[ -s "$queue" ]] || return 0
  hold_voice 900 || return 0
  while line=$( {
    flock -w 30 8 && [[ -s "$queue" ]] && head -n 1 "$queue" && sed -i 1d "$queue"
  } 8>"$cursor.lock"); do
    say "$line"
  done
}

# In speech mode the replies are the only voice, and the announcements stay quiet,
# since the replies say what they would. Text with nothing left to say once its code
# and URLs are gone is quiet too. The events that set the mode still run.
if [[ -n "$session" && -e "$replies" ]]; then
  [[ $event == Stop || $event == PreToolUse ]] && { read_aloud; exit 0; }
  [[ $event:$tool =~ ^(UserPromptSubmit:|PostToolUse:Skill)$ ]] || exit 0
fi

# Outside speech mode a followed session still sends its mid-turn text to the voice feed,
# ahead of each tool call. The bridge's Stop hook feeds the final reply, so the Stop only
# marks the turn's text as sent. A question is announced aloud after its text goes.
if [[ -n "$session" && ($event == PreToolUse || $event == Stop) ]] && followed; then
  if [[ $event == Stop ]]; then
    mkdir -p "$dir"
    { flock -w 30 8 && python3 "$here/speak_pending.py" "$transcript" "$cursor" stop \
      "$(field .last_assistant_message)" >/dev/null 2>&1; } 8>"$cursor.lock"
  else
    read_aloud
    [[ $tool != AskUserQuestion ]] && exit 0
  fi
fi

case "$event:$tool" in
  UserPromptSubmit:)
    speech_mode "$(command_of "$(field .prompt)")"
    exit 0
    ;;
  PostToolUse:Skill)
    [[ $(field .tool_input.skill) == implement-with-speech ]] &&
      speech_mode /implement-with-speech
    exit 0
    ;;
  Stop:)
    # stop_attention.py says what this turn needs from the user. Exit 3 is
    # quiet: the label already spoke, or an automated event started the turn
    # and nothing waits on the user. A crash still speaks.
    what=$(python3 "$here/stop_attention.py" --config "$config" <<<"$input" 2>/dev/null)
    case $? in
      0) ;;
      3) what= ;;
      *) what="finished" ;;
    esac
    # Quiet while background work is due to wake the session, since the turn
    # goes on when it does, and an announcement it holds back is owed. The hook
    # command execs this script, so its parent is the session process, whose
    # start time marks work a restart ended.
    if STOP_AT=$stop_at python3 "$here/background_pending.py" "$transcript" "$PPID" \
      >/dev/null 2>&1; then
      [[ -n "$what" && -n "$session" ]] && mkdir -p "${owed%/*}" &&
        printf '%s' "$what" > "$owed"
      exit 0
    fi
    if [[ -z "$what" ]]; then
      [[ -n "$session" && -s "$owed" ]] || exit 0
      what=$(cat "$owed")
    fi
    ;;
  PreToolUse:AskUserQuestion)
    what="has a question"
    ;;
  PostToolUse:Bash)
    cmd=$(field .tool_input.command)
    { IFS= read -r label; IFS= read -r announced; } < <(
      jq -r '.reviewLabel // "", .reviewAnnouncement // ""' "$config" 2>/dev/null)
    [[ -n $label && -n $announced ]] || exit 0
    # A quick look for the label's words, however the command spaces them, before the
    # full check.
    grep -qiE "${label// /'(\s|%20|\+)+'}" <<<"$cmd" || exit 0
    # The command adds the label, and its output shows the add went through.
    out=$(field .tool_response.stdout)
    pr=$(ready_line 'n = e.labeled_numbers(sys.argv[2])
added = e.LABEL_ADDED.search(sys.stdin.read())
sys.exit(1) if n is None or not added else print(" ".join(n))' "$cmd" <<<"$out" 2>/dev/null) ||
      exit 0
    what="has pull request ${pr:+$pr }$announced"
    ;;
  *)
    exit 0
    ;;
esac

[[ -n "$session" ]] && rm -f "$owed"

# Outside speech mode the voice only draws the user to the session, which carries the
# detail in text.
hold_voice 120 || exit 0
say "$(session_name) $what"
