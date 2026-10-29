#!/usr/bin/env python3
"""Run an isolated copy of the widgets for one working session, beside the user's own.

usage: scripts/isolated-widgets.py [--name NAME] [--installed] start [spotify|orchestrator] [--at X,Y]
       scripts/isolated-widgets.py [--name NAME] stop | status | path
       scripts/isolated-widgets.py [--name NAME] capture <out.png> [spotify|orchestrator]

  start     runs the checkout's launcher (--installed: the installed one, once a release has the
            window class suffix) in a copy of its own;
            no widget named starts both
  stop      stops that copy and removes everything it made; nothing else is touched
  status    what the copy runs, and where its window is
  capture   saves the copy's window as a PNG (scripts/capture-widget.py does the reading)
  path      the copy's folder: its home, its log (home/.cache/conky-widgets/run.log), its fixtures

NAME is the copy's name and defaults to the checkout's folder name, so each working session
(each worktree) has a copy of its own and two sessions never share one. Starting a copy that
runs already says so.

The copy is isolated by where it lives, so the launcher and the widgets run unchanged:
  - HOME is a folder of its own, so the launcher's pid file and lock, each widget's cache and
    config, its instance lock, its saved position and its logs are the copy's, and no Spotify
    login or token is there: the Spotify widget sends no Web API request, and has no heart
  - ~/.claude/sessions there holds fixture Claude sessions (three managed, with replies in
    their feeds from a minute to 40 minutes old, and one not managed), and $XDG_RUNTIME_DIR holds a
    speak-attention folder of fixture hook state beside links to everything else the desktop
    keeps there, so the orchestrator widget reads those and never a real session's files
  - there is no tray icon (CSN_NO_TRAY)
  - the windows have a class of their own (CSN_CLASS_SUFFIX), since each widget's mouse helper
    finds its window by class and two copies with one class would move each other's windows
  - the windows start at a position of their own on the built-in display (the primary monitor
    where there is none), a slot to the left of the last copy's, so they cover neither the
    user's widgets nor each other, and never the monitor the user works on
The user's copy and other sessions' copies are never read, stopped or captured: every path the
copy uses is under its folder, and the stop only signals processes that folder's launcher
started or fixture processes named for the copy.
"""
import argparse
import hashlib
import json
import os
import pwd
import re
import shutil
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
CHECKOUT = os.path.dirname(HERE)
LAUNCHER = os.path.join(CHECKOUT, 'bin', 'conky-widgets')
INSTALLED_LAUNCHER = '/usr/bin/conky-widgets'
INSTALLED_SRC = '/usr/share/conky-widgets'
REAL_HOME = pwd.getpwuid(os.getuid()).pw_dir          # HOME may already be a copy's
BASE = os.path.join(REAL_HOME, '.cache', 'conky-widgets-isolated')
WIDGETS = ('spotify', 'orchestrator')
ALIASES = {'speech': 'orchestrator'}     # the orchestrator's former name, which old commands still use
WM_CLASS = {'spotify': 'ConkySpotifyNowPlaying', 'orchestrator': 'ConkyOrchestrator'}
CARD_W = 1500                  # px a card and its shadow can span at the largest display scale
SLOT = 48                      # px between one copy's windows and the next's
ORCHESTRATOR_BELOW = 300       # px the orchestrator widget sits below the Spotify one, as the defaults do
FIXTURE_TAG = 'csn-isolated-fixture'


def default_name():
    return re.sub(r'[^\w.-]', '-', os.path.basename(CHECKOUT)) or 'checkout'


class Copy:
    """One isolated copy: where its files live and what it runs with."""

    def __init__(self, name, base=BASE):
        self.name, self.launcher = name, LAUNCHER
        self.root = os.path.join(base, name)
        self.home = os.path.join(self.root, 'home')
        self.runtime = os.path.join(self.root, 'run')
        self.hook_dir = os.path.join(self.runtime, 'speak-attention')
        self.sessions = os.path.join(self.home, '.claude', 'sessions')
        self.pids = os.path.join(self.root, 'fixture.pids')
        self.slot_file = os.path.join(self.root, 'slot')
        # added to each window's class: the user's copy and other copies keep the plain one
        self.suffix = 'Iso' + hashlib.sha1(name.encode()).hexdigest()[:8]

    def config(self, widget):
        if widget == 'spotify':
            return os.path.join(self.home, '.config', 'conky-spotify-nowplaying')
        return os.path.join(self.home, '.config', 'conky-widgets', 'orchestrator')

    def env(self):
        """The launcher's environment: the desktop's own variables, with HOME and
        XDG_RUNTIME_DIR the copy's and no tray."""
        env = dict(os.environ, HOME=self.home, XDG_RUNTIME_DIR=self.runtime, CSN_NO_TRAY='1',
                   CSN_CLASS_SUFFIX=self.suffix)
        for var in ('CSN_DIR', 'CSN_LAUNCHER', 'CSN_DPI', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME',
                    'XDG_DATA_HOME', 'XDG_STATE_HOME'):
            env.pop(var, None)       # the copy's HOME decides where its files go
        return env

    def exists(self):
        return os.path.isdir(self.home)


def real_runtime_dir():
    return os.environ.get('CSN_REAL_RUNTIME_DIR') or os.environ.get('XDG_RUNTIME_DIR') \
        or f'/run/user/{os.getuid()}'


def link_runtime(copy, real):
    """The copy's $XDG_RUNTIME_DIR: a link to everything the desktop keeps in `real` (the
    session bus, the Wayland socket, ...) except the hooks' folder, which is the
    copy's own fixture. Links, not copies, so a socket still reaches its server."""
    os.makedirs(copy.runtime, mode=0o700, exist_ok=True)
    try:
        entries = os.listdir(real)
    except OSError:
        entries = []
    for entry in entries:
        if entry == 'speak-attention':
            continue
        link = os.path.join(copy.runtime, entry)
        if not os.path.lexists(link):
            try:
                os.symlink(os.path.join(real, entry), link)
            except OSError:
                pass


BUILT_IN = re.compile(r'(eDP|LVDS|DSI)', re.I)    # the names xrandr gives a laptop's own panel


def monitor_of(listing):
    """(x, y, width, height) of the monitor a copy goes on, in `xrandr --listmonitors` output:
    the built-in display, else the primary (starred) monitor, else the first one; a 1920x1080
    screen at the origin when it lists none. A copy goes on the built-in display so it never
    covers the monitor the user works on."""
    found = re.findall(r'^\s*\d+: \+?(\*?)(\S+) (\d+)/\d+x(\d+)/\d+\+(-?\d+)\+(-?\d+)', listing, re.M)
    built_in = [m for m in found if BUILT_IN.match(m[1])]
    starred = [m for m in found if m[0]]
    w, h, x, y = map(int, (built_in or starred or found or [('', '', '1920', '1080', '0', '0')])[0][2:])
    return x, y, w, h


def taken_slots(base, skip):
    """The slots the other copies under `base` hold."""
    slots = set()
    try:
        names = os.listdir(base)
    except OSError:
        return slots
    for name in names:
        if name == skip:
            continue
        try:
            with open(os.path.join(base, name, 'slot')) as f:
                slots.add(int(f.read()))
        except (OSError, ValueError):
            pass
    return slots


def position_for(slot, monitor, widget, at=None):
    """Where the card of `widget` starts, in root coordinates: the right of the monitor, each
    slot a step further left and down, so a copy covers neither the user's widgets (which sit at
    the left by default) nor another copy's."""
    if at:
        x, y = at
    else:
        mx, my, mw, _ = monitor
        x, y = mx + mw - CARD_W - slot * SLOT, my + 80 + slot * SLOT
    return x, y + (ORCHESTRATOR_BELOW if widget == 'orchestrator' else 0)


def fixture_sessions(copy, pids):
    """[(pid, id, name, busy, cwd, managed)] of the fixture Claude sessions, one per pid. The
    last one is not managed, so the widget does not list it."""
    spec = [('Feed widget', True, CHECKOUT, True),
            ('Waiting on tests', True, os.path.join(copy.home, 'project-a'), True),
            ('Retry fix', False, os.path.join(copy.home, 'project-b'), True),
            ('Not managed', False, os.path.join(copy.home, 'project-c'), False)]
    return [(pid, f'00000000-0000-4000-8000-00000000000{i}', name, busy, cwd, managed)
            for i, (pid, (name, busy, cwd, managed)) in enumerate(zip(pids, spec), 1)]


def write(path, text=''):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(text)


def fixture_feeds(sessions, now):
    """{session id: [(epoch seconds, text, markdown)]} of the replies each fixture session's feed
    holds: the first replied a minute ago (its row carries the line), the second 25 minutes
    ago (its row shows only the age) and the third has not replied."""
    return {sessions[0][1]: [(now - 2400, 'Opened the pull request for the feed. Tests pass locally.', ''),
                             (now - 60, 'The feed lists replies from managed sessions only. Next I am removing the '
                                  'playback controls.', 'The feed lists replies from **managed** sessions only.\n\n'
                                  'Next I am removing the playback controls.')],
            sessions[1][1]: [(now - 1500, 'Started the test run. Twelve of forty files are done, no failures so far.', '')]}


def write_fixtures(copy, pids):
    """The fixture hook state and Claude sessions for `pids` alive processes: the first session
    replied a minute ago and 40 minutes before, the second 25 minutes ago and the third not at
    all, as <id>.feed holds them, and the fourth is not a managed session. The first three carry
    the .managed marker."""
    shutil.rmtree(copy.sessions, ignore_errors=True)
    shutil.rmtree(copy.hook_dir, ignore_errors=True)
    os.makedirs(copy.sessions)
    os.makedirs(copy.hook_dir)
    sessions = fixture_sessions(copy, pids)
    feeds = fixture_feeds(sessions, time.time())
    for pid, sid, name, busy, cwd, managed in sessions:
        write(os.path.join(copy.sessions, f'{pid}.json'), json.dumps({
            'pid': pid, 'sessionId': sid, 'name': name, 'cwd': cwd, 'kind': 'interactive',
            'status': 'busy' if busy else 'idle', 'messagingSocketPath': f'/nonexistent/{sid}.sock'}))
        if managed:
            write(os.path.join(copy.hook_dir, f'{sid}.managed'))
            write(os.path.join(copy.hook_dir, f'{sid}.feed'), ''.join(
                json.dumps({'session': sid, 'name': name, 'text': text, 'markdown': markdown or text, 'at': int(at)})
                + '\n' for at, text, markdown in feeds.get(sid, [])))


def argv0(pid):
    try:
        with open(f'/proc/{pid}/cmdline', 'rb') as f:
            return f.read().split(b'\0')[0].decode(errors='replace')
    except OSError:
        return None


def start_fixture_processes(copy, count=4):
    """`count` processes that do nothing, for the fixture sessions to be the pids of. Their
    argv[0] names the copy, which is how stop knows them again."""
    pids = []
    for _ in range(count):
        proc = subprocess.Popen(
            ['bash', '-c', 'exec -a "$0" sleep infinity', f'{FIXTURE_TAG}:{copy.name}'],
            start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        pids.append(proc.pid)
        proc.returncode = 0            # left running on purpose; stop signals it by pid
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and any(argv0(p) != f'{FIXTURE_TAG}:{copy.name}' for p in pids):
        time.sleep(0.02)       # bash has not exec'd sleep yet
    write(copy.pids, '\n'.join(map(str, pids)) + '\n')
    return pids


def stop_fixture_processes(copy):
    try:
        with open(copy.pids) as f:
            pids = [int(line) for line in f.read().split()]
    except (OSError, ValueError):
        return
    for pid in pids:
        if argv0(pid) == f'{FIXTURE_TAG}:{copy.name}':       # not a recycled pid
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass


def fixture_alive(copy):
    try:
        with open(copy.pids) as f:
            return any(argv0(int(p)) == f'{FIXTURE_TAG}:{copy.name}' for p in f.read().split())
    except (OSError, ValueError):
        return False


def run_launcher(copy, *args, installed=False, quiet=False):
    launcher = INSTALLED_LAUNCHER if installed else copy.launcher
    out = subprocess.run([launcher, *args], env=copy.env(), capture_output=True, text=True)
    if not quiet and out.stdout.strip():
        print(out.stdout.strip())
    if out.returncode:
        print(out.stderr.strip(), file=sys.stderr)
    return out


def supervisor_pid(copy):
    try:
        with open(os.path.join(copy.home, '.cache', 'conky-widgets', 'run.pid')) as f:
            pid = int(f.read())
        with open(f'/proc/{pid}/cmdline', 'rb') as f:
            return pid if b'_run' in f.read().split(b'\0') else None
    except (OSError, ValueError):
        return None


def monitor():
    out = subprocess.run(['xrandr', '--listmonitors'], capture_output=True, text=True)
    return monitor_of(out.stdout if out.returncode == 0 else '')


def installed_has_class_suffix(src=INSTALLED_SRC):
    """Whether the installed widgets add CSN_CLASS_SUFFIX to their window class; one that
    does not would give the copy the user's class, and the two copies' mouse helpers would
    move each other's windows."""
    try:
        with open(os.path.join(src, 'spotify', 'conky.conf')) as f:
            return 'CSN_CLASS_SUFFIX' in f.read()
    except OSError:
        return False


def start(copy, widgets, at=None, installed=False):
    if installed and not installed_has_class_suffix():
        sys.exit('the installed widgets do not give a copy its own window class (they predate '
                 'CSN_CLASS_SUFFIX); start the checkout\'s copy instead')
    running = supervisor_pid(copy)
    os.makedirs(copy.home, exist_ok=True)
    if not os.path.exists(copy.slot_file):
        taken = taken_slots(os.path.dirname(copy.root), copy.name)
        slot = next(s for s in range(1000) if s not in taken)
        write(copy.slot_file, str(slot))
    with open(copy.slot_file) as f:
        slot = int(f.read())
    link_runtime(copy, real_runtime_dir())
    if 'orchestrator' in widgets and not (running and fixture_alive(copy)):
        write_fixtures(copy, start_fixture_processes(copy))
    mon = monitor()
    for widget in widgets:
        position = os.path.join(copy.config(widget), 'position')
        if not os.path.exists(position) or not running:
            x, y = position_for(slot, mon, widget, at)
            write(position, f'{x} {y}\n')
    for widget in widgets:
        out = run_launcher(copy, widget, 'start', installed=installed, quiet=True)
        print(f'{widget}: {out.stdout.strip() or "start failed"}')
    print(f'isolated copy "{copy.name}": {copy.root}')


def stop(copy, installed=False):
    if not copy.exists():
        print(f'no isolated copy "{copy.name}"')
        return
    run_launcher(copy, 'stop', installed=installed, quiet=True)
    deadline = time.monotonic() + 5           # the launcher stops it with the last widget
    while time.monotonic() < deadline and supervisor_pid(copy):
        time.sleep(0.1)
    if supervisor_pid(copy):                  # keep its files: they are how a later stop finds it
        sys.exit(f'the copy "{copy.name}" did not stop; its files are left in {copy.root}')
    stop_fixture_processes(copy)
    shutil.rmtree(copy.root, ignore_errors=True)
    print(f'stopped "{copy.name}" and removed {copy.root}')


def status(copy):
    if not copy.exists():
        print(f'no isolated copy "{copy.name}"')
        return
    print(f'isolated copy "{copy.name}": {copy.root}')
    out = run_launcher(copy, 'status', quiet=True)
    print(out.stdout.strip())
    for widget in WIDGETS:
        xid = window_of(copy, widget)
        if xid:
            print(f'{widget} window: {xid:#x}')


def window_of(copy, widget):
    """The copy's window of `widget`, found by the class only its windows have; None when
    there is none (not started, or hidden)."""
    tree = subprocess.run(['xwininfo', '-root', '-tree'], capture_output=True, text=True).stdout
    m = re.search(rf'^\s*(0x[0-9a-f]+) .*"{WM_CLASS[widget]}{copy.suffix}"', tree, re.M)
    return int(m.group(1), 16) if m else None


def capture(copy, out, widget):
    xid = window_of(copy, widget)
    if xid is None:
        sys.exit(f'no {widget} window for the isolated copy "{copy.name}"; is it running and showing?')
    return subprocess.run([sys.executable, os.path.join(HERE, 'capture-widget.py'), out, widget,
                           '--window', f'{xid:#x}']).returncode


def main(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--name', default=os.environ.get('CSN_ISO_NAME') or default_name())
    parser.add_argument('--installed', action='store_true')
    parser.add_argument('--at')
    parser.add_argument('command', nargs='?')
    parser.add_argument('rest', nargs='*')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'\w[\w.-]*', args.name):     # never '.' or '..': stop removes the folder
        sys.exit('the name is letters, digits, dots, dashes and underscores, starting with a letter or digit')
    copy = Copy(args.name)
    cmd, rest = args.command, [ALIASES.get(w, w) for w in args.rest]
    if cmd == 'start':
        widgets = [w for w in rest if w in WIDGETS] or list(WIDGETS)
        at = tuple(map(int, args.at.split(','))) if args.at else None
        start(copy, widgets, at, args.installed)
    elif cmd == 'stop':
        stop(copy, args.installed)
    elif cmd == 'status':
        status(copy)
    elif cmd == 'path':
        print(copy.root)
    elif cmd == 'capture' and rest and rest[1:2] in ([], ['spotify'], ['orchestrator']):
        sys.exit(capture(copy, rest[0], rest[1] if len(rest) > 1 else 'spotify'))
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
