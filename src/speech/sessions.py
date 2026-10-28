"""The Claude sessions that are open, listed the way speechctl and the voice bridge list them.

Claude Code keeps one file per running session in ~/.claude/sessions, named for the process
id. It carries the session id, the title shown in the app's sidebar, the working directory,
whether a turn is running and the kind. The .key files beside them hold secrets and are never
opened. Interactive sessions are the ones the sidebar shows; background sessions, the kind
start_session makes, are listed too and marked as such. Two sessions with one name are told
apart by a number, in process id order.

This follows Overmind's voice-bridge-hooks/sessions.py rule for rule, so the widget lists
exactly the sessions `speechctl speech <id> ...` can find, without importing from Overmind.
"""
import json
import os
import re

SESSIONS_DIR = os.path.expanduser('~/.claude/sessions')
PROC_DIR = '/proc'
KINDS = ('interactive', 'bg')


def _read_json(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def list_sessions(sessions_dir=None, proc_dir=None):
    """[{id, name, busy, background, pid, cwd}] for every live session, in pid order."""
    sessions_dir = sessions_dir or SESSIONS_DIR
    proc_dir = proc_dir or PROC_DIR
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
        cwd = str(entry.get('cwd') or '')
        sessions.append({
            'id': str(entry.get('sessionId') or ''),
            'name': str(entry.get('name') or '').strip() or os.path.basename(cwd),
            'busy': entry.get('status') == 'busy',
            'background': entry.get('kind') == 'bg',
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
