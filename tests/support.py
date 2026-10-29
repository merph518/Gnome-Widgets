"""Loads the widget's modules for testing, away from the real cache and the desktop.

Importing this first points HOME at a throwaway directory, so every path the modules
work out from ~ at import time lands there rather than in the user's ~/.cache and
~/.config. Tests still point the paths they write to at their own temporary directory.
"""
import atexit
import ctypes
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src')
sys.path.insert(0, os.path.join(SRC, 'common'))
sys.path.insert(0, os.path.join(SRC, 'spotify'))
sys.path.insert(0, os.path.join(SRC, 'speech'))

HOME = tempfile.mkdtemp(prefix='conky-spotify-nowplaying-test-home-')
atexit.register(shutil.rmtree, HOME, ignore_errors=True)
os.environ['HOME'] = HOME


def load_nowplaying():
    """nowplaying runs `xrdb -query` at import to find the display scale; answer it
    with nothing, which means scale 1, so the import needs no X server."""
    if 'nowplaying' not in sys.modules:
        with mock.patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0, stdout='')):
            import nowplaying  # noqa: F401
    return sys.modules['nowplaying']


def load_speechqueue():
    """speechqueue runs `xrdb -query` at import, like nowplaying: answered with nothing."""
    if 'speechqueue' not in sys.modules:
        with mock.patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0, stdout='')):
            import speechqueue  # noqa: F401
    return sys.modules['speechqueue']


class SpeechFixture:
    """A speaking hook's state folder, Claude's sessions folder and a /proc, under `root`,
    for speechqueue and the speech widget's mouse helper to read. Sessions are added with
    session(), managed unless managed=False, their replies with feed() and the hook's other files
    with file(); every pid added is alive unless stale=True."""

    def __init__(self, root):
        self.speak = os.path.join(root, 'speak-attention')
        self.sessions = os.path.join(root, 'sessions')
        self.proc = os.path.join(root, 'proc')
        self.ledgers = os.path.join(root, 'ledgers')
        for d in (self.speak, self.sessions, self.proc, self.ledgers):
            os.makedirs(d)

    def alive(self, pid, state='S'):
        os.makedirs(os.path.join(self.proc, str(pid)), exist_ok=True)
        with open(os.path.join(self.proc, str(pid), 'stat'), 'w') as f:
            f.write(f'{pid} (proc) {state} 1 1')

    def process(self, pid, ppid, *argv):
        """A live process `pid` under `ppid`, running `argv`."""
        self.alive(pid)
        task = os.path.join(self.proc, str(ppid), 'task', str(ppid))
        os.makedirs(task, exist_ok=True)
        with open(os.path.join(task, 'children'), 'a') as f:
            f.write(f'{pid} ')
        with open(os.path.join(self.proc, str(pid), 'cmdline'), 'wb') as f:
            f.write(b''.join(a.encode() + b'\0' for a in argv))

    def session(self, pid, sid, name, kind='interactive', status='idle', stale=False, socket=True, spare=False, waiting_for=None, managed=True):
        entry = {'pid': pid, 'sessionId': sid, 'name': name, 'cwd': f'/home/user/{name}',
                 'kind': kind, 'status': status}
        if spare:
            entry['spare'] = True
        if waiting_for:
            entry['waitingFor'] = waiting_for
        if socket:
            entry['messagingSocketPath'] = f'/tmp/{sid}.sock'
        with open(os.path.join(self.sessions, f'{pid}.json'), 'w') as f:
            json.dump(entry, f)
        if managed:
            self.file(f'{sid}.managed')
        if not stale:
            self.alive(pid)

    def file(self, name, text=''):
        with open(os.path.join(self.speak, name), 'w') as f:
            f.write(text)

    def feed(self, sid, at, text, markdown=None, name='A session'):
        """Appends a reply to session `sid`'s feed as the hook writes it: a JSON line."""
        with open(os.path.join(self.speak, f'{sid}.feed'), 'a') as f:
            f.write(json.dumps({'session': sid, 'name': name, 'text': text,
                                'markdown': text if markdown is None else markdown, 'at': at}) + '\n')

    def ledger(self, sid, *rows, project='-home-user-project'):
        """Session `sid`'s catchup.py ledger under ledgers/, a (key, state) per row."""
        folder = os.path.join(self.ledgers, project, sid, 'scratchpad')
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, 'ledger'), 'w') as f:
            f.writelines(f'label\t{key}\thttps://example.test\t{state}\t\n' for key, state in rows)

    def branch_ledger(self, sid, name, *rows, project='-home-user-project'):
        """Session `sid`'s ledger as the other repositories' catchup.py writes it, scratchpad/`name`,
        a (key, state) per row with a branch column after the label."""
        folder = os.path.join(self.ledgers, project, sid, 'scratchpad')
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, name), 'w') as f:
            f.writelines(f'label\tfeat/branch\t{key}\thttps://github.com/o/r/pull/{key.split(":")[-1]}'
                         f'\t{state}\tadded now\t\n' for key, state in rows)

    def sweep(self, sid, *states, project='-home-user-project'):
        """A skill's own ledger for session `sid`, scratchpad/sweep/ledger.tsv: a GitHub
        Actions run per state, in that format's columns."""
        folder = os.path.join(self.ledgers, project, sid, 'scratchpad', 'sweep')
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, 'ledger.tsv'), 'w') as f:
            f.writelines(f'spec {i}\tbranch\t{i}\thttps://github.com/o/r/actions/runs/{i}/job/1'
                         f'\t{state}\t\tlabel\n' for i, state in enumerate(states))

def load_conky_mouse():
    """conky-mouse.py has a hyphen in its name, and loads libX11 at import: load it by
    path, with a stand-in for the library, set up for the Spotify widget."""
    if 'conky_mouse' not in sys.modules:
        spec = importlib.util.spec_from_file_location('conky_mouse', os.path.join(SRC, 'common', 'conky-mouse.py'))
        module = importlib.util.module_from_spec(spec)
        with mock.patch.object(ctypes, 'CDLL', return_value=mock.MagicMock()):
            spec.loader.exec_module(module)
        sys.modules['conky_mouse'] = module
        module.configure('spotify')
    return sys.modules['conky_mouse']


def load_spotify_mouse():
    """The Spotify widget's part of the mouse helper, which conky-mouse.py loads."""
    return load_conky_mouse().hooks


def load_speech_mouse():
    """The speech widget's part of the mouse helper, loaded as conky-mouse.py loads it, with
    conky-mouse.py (set up for the Spotify widget) as its core."""
    if 'speech_mouse' not in sys.modules:
        core = load_conky_mouse()
        sys.path.insert(0, os.path.join(SRC, 'speech'))
        spec = importlib.util.spec_from_file_location('speech_mouse', os.path.join(SRC, 'speech', 'mouse.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.core = core
        sys.modules['speech_mouse'] = module
    return sys.modules['speech_mouse']


class TempDirTest(unittest.TestCase):
    """Gives each test its own directory in self.dir, removed afterwards."""

    def setUp(self):
        super().setUp()
        self.dir = tempfile.mkdtemp(prefix='conky-spotify-nowplaying-test-')
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def redirect(self, module, **names):
        """Points module.<NAME> at <file> inside self.dir, for this test only."""
        for name, filename in names.items():
            patcher = mock.patch.object(module, name, os.path.join(self.dir, filename))
            patcher.start()
            self.addCleanup(patcher.stop)


def read(path):
    with open(path) as f:
        return f.read()


def response(body):
    """A stand-in for the context-managed response urlopen returns, reading `body` (bytes)."""
    r = mock.MagicMock()
    r.__enter__.return_value = io.BytesIO(body)
    r.__enter__.return_value.status = 200
    return r


def http_error(code, headers=None):
    # HTTPError is a temporary file wrapper that warns when collected unclosed. The code
    # under test reads only its status and headers, so it is closed up front.
    e = urllib.error.HTTPError('https://example.test/', code, 'error', headers or {}, None)
    e.close()
    return e
