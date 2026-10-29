"""The managed Claude sessions that are open, listed the way speechctl and the voice bridge list them.

Claude Code keeps one file per running session in ~/.claude/sessions, named for the process
id. It carries the session id, the title shown in the app's sidebar, the working directory,
whether a turn is running and the kind. The .key files beside them hold secrets and are never
opened. Interactive sessions are the ones the sidebar shows; background sessions, the kind
start_session makes, are listed too and marked as such. Two sessions with one name are told
apart by a number, in process id order.

Only managed sessions are listed: the ones whose <id>.managed marker is in the speaking hook's
folder, $XDG_RUNTIME_DIR/speak-attention/. Overmind's hooks write it for every session that runs
the implement skill and the voice bridge for every session it starts, and `speechctl sessions
--json` reports it as `managed`. A session with no marker is not managed, as one with no
`managed` field is; this reads the marker itself, so the widget never runs speechctl for it.

This follows Overmind's voice-bridge-hooks/sessions.py rule for which sessions it lists, so the
widget finds the sessions `speechctl speech <id> ...` can, without importing from Overmind; the
widget decides itself which of them it shows (not the spares, `spare` in the file) and reads
whether each waits on input (`status: waiting`).
"""
import json
import os
import re

SESSIONS_DIR = os.path.expanduser('~/.claude/sessions')
PROC_DIR = '/proc'
SPEAK_DIR = os.path.join(os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}', 'speak-attention')
KINDS = ('interactive', 'bg')


def _read_json(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def list_sessions(sessions_dir=None, proc_dir=None, speak_dir=None):
    """[{id, name, busy, background, needs_input, spare, pid, cwd}] for every live managed session, in pid order."""
    sessions_dir = sessions_dir or SESSIONS_DIR
    proc_dir = proc_dir or PROC_DIR
    speak_dir = speak_dir or SPEAK_DIR
    try:
        files = os.listdir(sessions_dir)
    except OSError:
        return []
    sessions = []
    for name in files:
        # only <pid>.json; the .key files beside them are secrets and are never opened
        if not re.fullmatch(r'\d+\.json', name):
            continue
        entry = _read_json(os.path.join(sessions_dir, name))
        if not isinstance(entry, dict):
            continue
        if not entry.get('messagingSocketPath') or entry.get('kind') not in KINDS:
            continue
        try:
            pid = int(entry.get('pid'))
        except (TypeError, ValueError):
            continue
        # the file can outlive its process, so the process has to still be there
        if not os.path.exists(os.path.join(proc_dir, str(pid))):
            continue
        sid = str(entry.get('sessionId') or '')
        # a session id is a file name; one that is not cannot name a marker
        if not re.fullmatch(r'[\w-]+', sid) or not os.path.exists(os.path.join(speak_dir, sid + '.managed')):
            continue
        cwd = str(entry.get('cwd') or '')
        sessions.append({
            'id': sid,
            'name': str(entry.get('name') or '').strip() or os.path.basename(cwd),
            'busy': entry.get('status') == 'busy',
            'background': entry.get('kind') == 'bg',
            'needs_input': entry.get('status') == 'waiting',     # blocked on a question or a permission prompt in the CLI
            'spare': bool(entry.get('spare')),                   # a background job kept ready, with no work yet
            'pid': pid,
            'cwd': cwd,
        })
    sessions.sort(key=lambda s: s['pid'])
    seen = {}
    for s in sessions:
        base = s['name'].lower()
        seen[base] = seen.get(base, 0) + 1
        if seen[base] > 1:
            s['name'] = '%s %d' % (s['name'], seen[base])
    return sessions
