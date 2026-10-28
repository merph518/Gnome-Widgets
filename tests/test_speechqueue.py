"""speechqueue.py: the speech widget's state, read from fixture files, and the files it writes.

The golden samples under tests/golden/speech/<case>/ are what render() writes for each
case. After a change to the layout that is meant, write them again with
    SPEECH_GOLDEN=write python3 -m unittest tests.test_speechqueue
and read the diff before committing it.
"""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import support

speechqueue = support.load_speechqueue()
import sessions  # noqa: E402

GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'golden', 'speech')
OUTPUTS = ('widget.txt', 'draw.txt', 'regions.json', 'sessions.txt')
ME = '11111111-aaaa'
OTHER = '22222222-bbbb'
QUIET = '33333333-cccc'


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='speechqueue-test-')
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.f = support.SpeechFixture(self.root)
        cache = os.path.join(self.root, 'cache')
        for name, path in (('OUT', 'widget.txt'), ('DRAW', 'draw.txt'),
                           ('REGIONS', 'regions.json'), ('SESSIONS', 'sessions.txt')):
            p = mock.patch.object(speechqueue, name, os.path.join(cache, path))
            p.start()
            self.addCleanup(p.stop)
        for name, value in (('COLLAPSE', os.path.join(self.root, 'collapse-idle')),
                            ('SCALE', 1), ('clock', speechqueue.Clock())):
            p = mock.patch.object(speechqueue, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch('time.monotonic', return_value=1000.0)
        p.start()
        self.addCleanup(p.stop)
        try:
            os.remove(speechqueue.SIZE)
        except FileNotFoundError:
            pass
        self.cache = cache

    def state(self):
        return speechqueue.read_state(self.f.speak, self.f.sessions, self.f.proc)

    def three(self):
        """This session with speech on, another on Alerts with a line queued, a third Off."""
        self.f.session(300, ME, 'Claude Voice Widget', status='busy')
        self.f.session(100, OTHER, 'Release 1.2')
        self.f.session(200, QUIET, 'Docs pass', kind='bg')
        self.f.file(ME + '.replies')
        self.f.file(QUIET + '.muted')
        self.f.queue(OTHER, 'The build is green.')


class ReadState(Fixture):
    def test_sessions_sort_speech_on_first_then_by_pid(self):
        self.three()
        s = self.state()['sessions']
        self.assertEqual([x['id'] for x in s], [ME, OTHER, QUIET])
        self.assertEqual([x['speech'] for x in s], ['on', 'alerts', 'off'])
        self.assertEqual([x['queued'] for x in s], [0, 1, 0])
        self.assertEqual(s[1]['next'], 'The build is green.')
        self.assertTrue(s[0]['busy'])
        self.assertTrue(s[2]['background'])

    def test_both_markers_read_as_on(self):
        self.f.session(100, ME, 'One')
        self.f.file(ME + '.replies')
        self.f.file(ME + '.muted')
        self.assertEqual(self.state()['sessions'][0]['speech'], 'on')

    def test_stale_and_socketless_sessions_are_left_out(self):
        self.f.session(100, ME, 'Live')
        self.f.session(200, OTHER, 'Gone', stale=True)
        self.f.session(300, QUIET, 'No socket', socket=False)
        self.f.session(400, 'dddd', 'Other kind', kind='sdk')
        self.assertEqual([x['name'] for x in self.state()['sessions']], ['Live'])

    def test_duplicate_names_are_numbered_in_pid_order(self):
        self.f.session(300, QUIET, 'Widget')
        self.f.session(100, ME, 'Widget')
        self.f.session(200, OTHER, 'widget')
        names = {s['id']: s['name'] for s in sessions.list_sessions(self.f.sessions, self.f.proc)}
        self.assertEqual(names, {ME: 'Widget', OTHER: 'widget 2', QUIET: 'Widget 3'})

    def test_key_files_are_never_opened(self):
        self.f.session(100, ME, 'One')
        key = os.path.join(self.f.sessions, '100.key')
        with open(key, 'w') as fh:
            fh.write('secret')
        real = open

        def guarded(path, *a, **k):
            self.assertFalse(str(path).endswith('.key'), path)
            return real(path, *a, **k)

        with mock.patch('builtins.open', guarded):
            self.assertEqual(len(self.state()['sessions']), 1)

    def test_now_json_of_an_exited_hook_is_ignored(self):
        self.three()
        self.f.now(ME, 'Claude Voice Widget', 'Hello.', hook_pid=9001)
        shutil.rmtree(os.path.join(self.f.proc, '9001'))
        state = self.state()
        self.assertIsNone(state['now'])
        self.assertFalse(any(s['speaking'] for s in state['sessions']))
        self.assertTrue(os.path.exists(os.path.join(self.f.speak, 'now.json')))   # only reads

    def test_zombie_hook_is_not_alive(self):
        self.f.now(ME, 'One', 'Hello.', hook_pid=9001)
        self.f.alive(9001, state='Z')
        self.assertIsNone(self.state()['now'])

    def test_duration_from_the_wav_once_it_plays(self):
        self.f.now(ME, 'One', 'Hello.', hook_pid=9001)
        self.f.wav(9001, 2.5)
        self.assertAlmostEqual(self.state()['duration'], 2.5, places=3)
        self.f.now(ME, 'One', 'Hello.', hook_pid=9001, player_pid=None)
        self.assertIsNone(self.state()['duration'])                      # still rendering
        self.f.now(ME, 'One', 'Hello.', hook_pid=9001, engine='spd-say')
        self.assertIsNone(self.state()['duration'])

    def test_settings_voice_and_volume(self):
        self.assertEqual(self.state()['voice'], 'en_US-amy-medium')
        self.assertEqual(self.state()['volume'], 1.2)
        self.f.file('settings.json', json.dumps({'voice': 'en_GB-alan-low', 'volume': 0.75}))
        state = self.state()
        self.assertEqual((state['voice'], state['volume']), ('en_GB-alan-low', 0.8))
        self.assertEqual(speechqueue.voice_label(state['voice']), 'alan')
        self.assertEqual(speechqueue.voice_label('my-voice'), 'my-voice')


class ClockTest(unittest.TestCase):
    def test_paused_time_is_not_counted(self):
        c = speechqueue.Clock()
        n = {'clip': '1', 'published': 100.0, 'player_pid': 5}
        self.assertEqual(c.elapsed(n, False, 101.0), 1.0)
        self.assertEqual(c.elapsed(n, True, 102.0), 1.0)       # paused since the last tick
        self.assertEqual(c.elapsed(n, True, 104.0), 1.0)
        self.assertEqual(c.elapsed(n, False, 105.0), 2.0)
        self.assertEqual(c.elapsed(dict(n, clip='2', published=105.0), False, 106.0), 1.0)


class Golden(Fixture):
    def check(self, case, state, now=1000.0):
        text = speechqueue.render(state, now=now)
        speechqueue.write_atomic(speechqueue.OUT, text)
        folder = os.path.join(GOLDEN, case)
        if os.environ.get('SPEECH_GOLDEN') == 'write':
            os.makedirs(folder, exist_ok=True)
            for name in OUTPUTS:
                shutil.copy(os.path.join(self.cache, name), os.path.join(folder, name))
        for name in OUTPUTS:
            with open(os.path.join(folder, name)) as want, open(os.path.join(self.cache, name)) as got:
                self.assertEqual(got.read(), want.read(), f'{case}/{name}')

    def test_idle(self):
        self.three()
        self.f.file(OTHER + '.queue', '')
        self.check('idle', self.state())

    def test_playing(self):
        self.three()
        self.f.now(ME, 'Claude Voice Widget', 'The data layer is in: speechqueue.py writes the '
                   'widget, draw and regions files four times a second.', hook_pid=9001)
        os.utime(os.path.join(self.f.speak, 'now.json'), (998.0, 998.0))
        self.f.wav(9001, 6.0)
        self.check('playing', self.state())

    def test_paused(self):
        self.three()
        self.f.now(ME, 'Claude Voice Widget', 'Paused part way.', hook_pid=9001)
        os.utime(os.path.join(self.f.speak, 'now.json'), (998.0, 998.0))
        self.f.wav(9001, 4.0)
        self.f.file('paused')
        self.check('paused', self.state())

    def test_many_sessions_scroll(self):
        for i in range(8):
            self.f.session(100 + i, f'{i:08d}-eeee', f'Session {i}')
            self.f.queue(f'{i:08d}-eeee', f'Line {i}')
        self.check('scroll', self.state())

    def test_collapse_when_idle(self):
        self.three()
        self.f.file(OTHER + '.queue', '')
        with open(speechqueue.COLLAPSE, 'w') as fh:
            fh.write('on\n')
        self.check('collapse', self.state())


if __name__ == '__main__':
    unittest.main()
