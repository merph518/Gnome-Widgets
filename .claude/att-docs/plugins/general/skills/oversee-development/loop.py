#!/usr/bin/env python3
"""Manage per-session oversee loop markers in the shared checkout."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone

SESSION = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,199}\Z')


def valid_session(value):
    return isinstance(value, str) and SESSION.fullmatch(value) is not None


def state_dir(cwd):
    result = subprocess.run(['git', 'rev-parse', '--path-format=absolute', '--git-common-dir'],
                            cwd=cwd, capture_output=True, text=True, check=True)
    return Path(result.stdout.strip()).parent / '.claude' / 'oversee'


@contextmanager
def locked(directory, timeout=None):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'loops.lock').open('a') as lock:
        if timeout is None:
            fcntl.flock(lock, fcntl.LOCK_EX)
        else:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('loop marker lock is busy')
                    time.sleep(0.05)
        yield


def marker_path(directory, session):
    if not valid_session(session):
        raise ValueError('a valid session ID is required (pass --session)')
    return directory / 'loops' / (session + '.json')


def load(directory, session):
    path = marker_path(directory, session)
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) and value.get('session') == session else None
    except (FileNotFoundError, json.JSONDecodeError, UnicodeError):
        return None


def save(directory, marker):
    path = marker_path(directory, marker['session'])
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.loop-')
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(marker, out, ensure_ascii=False)
            out.write('\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def now():
    return datetime.now(timezone.utc).isoformat()


# Control characters, which a title or note could carry into the pane.
CONTROL = re.compile(r'[\x00-\x1f\x7f-\x9f]')
GITHUB_REMOTE = re.compile(r'(?:git@github\.com:|ssh://git@github\.com/|https://github\.com/)'
                           r'([^/\s]+)/([^/\s]+?)(?:\.git)?/?\Z')
# Ledger statuses that end an issue's run. A later start row takes it back.
FINISHED = ('done', 'stalled', 'skipped')


def clean(value):
    value = CONTROL.sub('', value).strip()
    return None if value in ('', '-') else value


def number(value):
    value = (clean(value) or '').lstrip('#')
    return int(value) if value.isdigit() else None


def read_rows(path, width, whole_lines_only):
    """Tab-separated rows of a file, padded to width with "-". A missing file is empty.

    oversee.sh appends whole ledger lines, so an unterminated last line is a write still
    under way and is left out when whole_lines_only is set.
    """
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except (FileNotFoundError, NotADirectoryError):
        return []
    lines = text.split('\n')
    if whole_lines_only or text.endswith('\n'):
        lines = lines[:-1]
    rows = []
    for line in lines:
        if line.strip() == '':
            continue
        cells = line.split('\t')
        rows.append(cells + ['-'] * (width - len(cells)))
    return rows


def repo_url(main):
    """The GitHub address of the main checkout's origin remote, or None."""
    ran = subprocess.run(['git', 'remote', 'get-url', 'origin'], cwd=main,
                         capture_output=True, text=True)
    match = GITHUB_REMOTE.match(ran.stdout.strip()) if ran.returncode == 0 else None
    return f'https://github.com/{match.group(1)}/{match.group(2)}' if match else None


def board(directory, session, limit):
    """What the status row's pane lists: this loop's current issue, its queue, and the
    finished issues of the shared ledger, newest first. Reads only; creates nothing.

    The queue is the one oversee.sh serves this session: its own snapshot while its loop
    is active or paused, the shared queue otherwise.
    """
    marker = load(directory, session) if (directory / 'loops').is_dir() else None
    state = (marker or {}).get('state', 'absent')
    queue_file = directory / 'loops' / f'{session}.queue.tsv' if state in ('active', 'paused') \
        else directory / 'queue.tsv'
    queue = [row for row in read_rows(queue_file, 8, False) if number(row[0]) is not None]
    titles = {number(row[0]): clean(row[2]) for row in queue}

    latest = {}
    for position, row in enumerate(read_rows(directory / 'ledger.tsv', 6, True)):
        issue = number(row[1])
        if issue is None or len(row) < 6 or clean(row[2]) is None:
            continue
        latest[issue] = (position, row)

    current = None
    owner = f'session {session} '
    for issue, (position, row) in latest.items():
        if row[2] in ('start', 'runs') and owner in row[5] and \
                (current is None or position > current[0]):
            current = (position, {
                'issue': issue, 'title': titles.get(issue),
                'phase': 'working' if row[2] == 'start' else 'waiting on runs',
                'branch': clean(row[3]), 'since': clean(row[0]),
            })

    queued = []
    seen = set()
    for row in queue:
        issue = number(row[0])
        status = latest[issue][1][2] if issue in latest else None
        if status not in (None, 'withdrawn') or issue in seen:
            continue
        seen.add(issue)
        queued.append({'issue': issue, 'title': titles[issue], 'area': clean(row[1]),
                       'blockers': clean(row[5]), 'waits': clean(row[6])})

    finished = sorted(((position, issue, row) for issue, (position, row) in latest.items()
                       if row[2] in FINISHED), reverse=True)
    return {
        'session': session,
        'state': state,
        'repo': repo_url(directory.parent.parent),
        'current': current[1] if current else None,
        'queued': queued,
        'finished': [{'issue': issue, 'title': titles.get(issue), 'status': row[2],
                      'pr': number(row[4]), 'note': clean(row[5]), 'at': clean(row[0])}
                     for _, issue, row in finished[:limit]],
        'more': max(0, len(finished) - limit),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', default=os.environ.get('CLAUDE_CODE_SESSION_ID'))
    commands = parser.add_subparsers(dest='command', required=True)
    start = commands.add_parser('start')
    start.add_argument('--milestone')
    start.add_argument('label', nargs='?')
    stop = commands.add_parser('stop')
    stop.add_argument('reason')
    pause = commands.add_parser('pause')
    pause.add_argument('reason')
    commands.add_parser('resume')
    status = commands.add_parser('status')
    status.add_argument('--all', action='store_true')
    board_command = commands.add_parser('board')
    board_command.add_argument('--limit', type=int, default=20)
    args = parser.parse_args()
    if not valid_session(args.session):
        parser.error('a valid session ID is required (pass --session)')
    try:
        directory = state_dir(Path.cwd())
        if args.command == 'board':
            # Takes no lock: the lock file would create state where a loop never ran.
            shown = board(directory, args.session, max(0, args.limit))
            print(json.dumps(shown, ensure_ascii=False))
            return 0
        with locked(directory):
            marker = load(directory, args.session)
            if args.command == 'status' and args.all:
                paths = sorted((directory / 'loops').glob('*.json'))
                markers = [load(directory, path.stem) for path in paths if valid_session(path.stem)]
                print(json.dumps([item for item in markers if item is not None], ensure_ascii=False))
                return 0
            if args.command == 'start':
                if marker and marker.get('state') in ('active', 'paused'):
                    raise ValueError('this session already has an active or paused loop')
                marker = dict(session=args.session, state='active', started=now(),
                              label=args.label, milestone=args.milestone, reason='')
            elif args.command == 'status':
                print(json.dumps(marker or {'session': args.session, 'state': 'absent'}, ensure_ascii=False))
                return 0
            elif not marker:
                raise ValueError('this session has no loop')
            elif args.command == 'stop':
                if not args.reason.strip():
                    raise ValueError('stop requires a reason')
                marker.update(state='stopped', reason=args.reason)
            elif args.command == 'pause':
                if not args.reason.strip():
                    raise ValueError('pause requires a reason')
                if marker.get('state') != 'active':
                    raise ValueError('only an active loop can be paused')
                marker.update(state='paused', reason=args.reason)
            elif args.command == 'resume':
                if marker.get('state') != 'paused':
                    raise ValueError('only a paused loop can be resumed; start a new loop otherwise')
                marker.update(state='active', reason='', continuations=0)
                marker.pop('ledger_progress', None)
            save(directory, marker)
            print(json.dumps(marker, ensure_ascii=False))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f'loop.py: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
