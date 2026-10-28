"""speechqueue.py: the speech widget's state, read from fixture files, and the files it writes.

The golden samples under tests/golden/speech/<case>/ are what render() writes for each
case. After a change to the layout that is meant, write them again with
    SPEECH_GOLDEN=write python3 -m unittest tests.test_speechqueue
and read the diff before committing it.
"""
import json
import os
import shutil
import subprocess
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
                            ('LABELS', os.path.join(self.root, 'labels.json')),
                            ('LAST', os.path.join(self.root, 'last-lines.json')), ('_last', None),
                            ('HEARD', os.path.join(self.root, 'last-heard.json')), ('_heard', None),
                            ('LEDGERS', self.f.ledgers),
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
        self.assertTrue(s[0]['busy'])
        self.assertTrue(s[2]['background'])

    def test_a_queued_question_is_a_tag_not_a_line(self):
        self.f.session(100, ME, 'One')
        self.f.queue(ME, 'Question: Open the pull request? Options: yes or no.')
        s = self.state()['sessions'][0]
        self.assertEqual((s['queued'], s['question']), (1, True))
        self.assertIn('question', speechqueue.session_line(s).split('\t')[4].split(','))

    def test_an_on_session_keeps_its_last_line_and_others_have_none(self):
        self.three()
        line = lambda sid: next(speechqueue.session_line(x) for x in self.state()['sessions']
                                if x['id'] == sid).split('\t')[7]
        self.assertEqual(line(ME), speechqueue.NOTHING_SAID)
        self.assertEqual(line(OTHER), '')
        self.f.now(ME, 'Claude Voice Widget', 'Pass 1 is pushed.')
        self.assertEqual(line(ME), 'Pass 1 is pushed.')
        self.f.now(ME, 'Claude Voice Widget', 'Question: Open it? Options: yes or no.')
        self.assertEqual(line(ME), 'Pass 1 is pushed.')
        os.remove(os.path.join(self.f.speak, 'now.json'))
        self.assertEqual(line(ME), 'Pass 1 is pushed.')
        speechqueue._last = None                       # a restart reads it back from LAST
        self.assertEqual(line(ME), 'Pass 1 is pushed.')

    def test_waiting_on_ci_or_a_merge_by_the_sessions_ledger(self):
        self.three()
        flags = lambda sid: next(speechqueue.session_line(x) for x in self.state()['sessions']
                                 if x['id'] == sid).split('\t')[4].split(',')
        self.assertEqual(flags(OTHER), ['idle'])
        self.f.ledger(OTHER, ('pr:107', 'done'), ('pr:111', 'open'))
        self.assertEqual(flags(OTHER), ['waiting: merge'])
        self.f.ledger(OTHER, ('pr:111', 'open'), ('lp:2.1.0', 'open'))
        self.assertEqual(flags(OTHER), ['waiting: ci'])
        self.f.ledger(OTHER, ('pr:111', 'done'), ('issue:12', 'open'))
        self.assertEqual(flags(OTHER), ['idle'])                  # nothing it shows
        self.f.ledger(ME, ('pr:111', 'open'))
        self.assertEqual(flags(ME), ['busy'])                     # working, not waiting
        self.f.ledger(QUIET, ('pr:5', 'open'))
        self.assertEqual(flags(QUIET), ['waiting: merge'])        # one tag: waiting over bg

    def test_waiting_on_tests_while_a_test_run_is_under_the_session(self):
        self.three()
        flags = lambda sid: next(speechqueue.session_line(x) for x in self.state()['sessions']
                                 if x['id'] == sid).split('\t')[4]
        self.f.process(110, 100, 'bash', '-c', 'python3 -m unittest discover -s tests')
        self.assertEqual(flags(OTHER), 'idle')                    # the shell's -c is not one
        self.f.process(111, 110, '/usr/bin/python3', '-m', 'unittest', 'discover', '-s', 'tests')
        self.f.ledger(OTHER, ('pr:111', 'open'))
        self.assertEqual(flags(OTHER), 'waiting: tests')          # over waiting on a merge
        self.f.process(210, 200, 'python3', 'scripts/catchup_test.py')
        self.assertEqual(flags(QUIET), 'waiting: tests')          # over bg
        self.f.process(310, 300, 'npx', 'playwright', 'test')
        self.assertEqual(flags(ME), 'busy')                       # its own turn runs them

    def test_waiting_on_tests_while_a_ci_run_is_open_in_a_skills_ledger(self):
        self.three()
        flags = lambda sid: next(speechqueue.session_line(x) for x in self.state()['sessions']
                                 if x['id'] == sid).split('\t')[4]
        self.f.sweep(OTHER, 'done', 'done')
        self.assertEqual(flags(OTHER), 'idle')
        self.f.ledger(OTHER, ('pr:111', 'open'))
        self.f.sweep(OTHER, 'done', 'in_progress', 'waiting')
        self.assertEqual(flags(OTHER), 'waiting: tests')          # over waiting on a merge

    def test_waiting_on_a_systemd_unit_a_shell_polls(self):
        self.three()
        flags = lambda sid: next(speechqueue.session_line(x) for x in self.state()['sessions']
                                 if x['id'] == sid).split('\t')[4]
        loop = 'while systemctl --user is-active -q {} ; do sleep 60; done'
        self.f.process(110, 100, '/bin/bash', '-c', loop.format('build-pack-now'))
        self.assertEqual(flags(OTHER), 'waiting: local ai')
        self.f.process(210, 200, '/bin/bash', '-c', loop.format('nightly.service'))
        self.assertEqual(flags(QUIET), 'waiting: nightly.service')   # a unit with no tag
        self.f.process(211, 200, 'pytest')
        self.assertEqual(flags(QUIET), 'waiting: tests')          # a test run over a unit
        self.f.sweep(OTHER, 'in_progress')
        self.assertEqual(flags(OTHER), 'waiting: tests')          # a CI run over a unit too

    def test_what_counts_as_a_test_run(self):
        runs = (['pytest', '-q'], ['python3', '-I', '-m', 'pytest'], ['python3', 'tests/test_x.py'],
                ['python3', '-W', 'ignore', 'test_x.py'],
                ['bash', 'speechctl_test.sh'], ['./speechctl_test.sh'], ['npm', 'test'],
                ['npm', 'run', 'test'], ['go', 'test', './...'], ['cargo', 'test'],
                ['node', 'node_modules/.bin/playwright', 'test'])
        others = ([], ['grep', 'unittest'], ['bash', '-c', 'pytest'], ['python3', 'speechqueue.py'],
                  ['python3', '-m'], ['npm', 'install'], ['go', 'build'], ['playwright', 'show-report'])
        for argv in runs:
            self.assertTrue(speechqueue.is_test_run(argv), argv)
        for argv in others:
            self.assertFalse(speechqueue.is_test_run(argv), argv)

    def test_one_tag_a_question_first(self):
        self.three()
        flags = lambda sid: next(speechqueue.session_line(x) for x in self.state()['sessions']
                                 if x['id'] == sid).split('\t')[4]
        self.assertEqual((flags(ME), flags(OTHER), flags(QUIET)), ('busy', 'idle', 'bg'))
        self.f.queue(ME, 'Question: Merge it? Options: yes or no.')
        self.f.ledger(ME, ('pr:111', 'open'))
        self.assertEqual(flags(ME), 'question')                   # over busy and waiting
        self.f.queue(QUIET, 'Question: Which one?')
        self.assertEqual(flags(QUIET), 'question')                # over bg

    def test_the_second_row_drops_the_hooks_speaker(self):
        self.three()
        line = lambda: next(speechqueue.session_line(x) for x in self.state()['sessions']
                            if x['id'] == ME).split('\t')[7]
        self.f.now(ME, 'Claude Voice Widget', 'Claude Voice Widget session says: PR 110 merged.')
        self.assertEqual(line(), 'PR 110 merged.')
        self.assertEqual(speechqueue.last_lines(None, {ME})[ME],
                         'Claude Voice Widget session says: PR 110 merged.')   # kept whole
        self.f.now(ME, 'Claude Voice Widget', 'It says: nothing here, mid-line it stays.')
        self.assertEqual(line(), 'It says: nothing here, mid-line it stays.')     # not the hook's
        self.assertEqual(speechqueue.without_speaker('The log says nothing.'), 'The log says nothing.')
        self.assertEqual(speechqueue.without_speaker('Overmind session says: '), 'Overmind session says: ')

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


class Labels(Fixture):
    def repo(self, name, url=None):
        top = os.path.join(self.root, 'code', name)
        os.makedirs(os.path.join(top, '.git'))
        with open(os.path.join(top, '.git', 'config'), 'w') as f:
            f.write('[core]\n\tbare = false\n')
            if url:
                f.write(f'[remote "origin"]\n\turl = {url}\n\tfetch = +refs/heads/*\n')
        return top

    def test_short_label_takes_initials_then_the_last_word(self):
        for name, label in (('Overmind', 'OVER'), ('LaundryBot', 'LBOT'), ('ATT-Test-Pack-Gen', 'ATPG'),
                            ('fagerteam-health-coach', 'FHCO'), ('a-b-c-d-e', 'ABCD'), ('', '')):
            with self.subTest(name=name):
                self.assertEqual(speechqueue.short_label(name), label)

    def test_repo_name_is_the_origin_remote_from_a_worktree_subfolder(self):
        top = self.repo('old-folder', 'https://github.com/someone/Gnome-Widgets.git')
        gitdir = os.path.join(top, '.git', 'worktrees', 'wt')
        os.makedirs(gitdir)
        with open(os.path.join(gitdir, 'commondir'), 'w') as f:
            f.write('../..\n')
        wt = os.path.join(top, '.claude', 'worktrees', 'wt')
        os.makedirs(os.path.join(wt, 'src'))
        with open(os.path.join(wt, '.git'), 'w') as f:
            f.write(f'gitdir: {gitdir}\n')
        self.assertEqual(speechqueue.repo_name(os.path.join(wt, 'src')), 'Gnome-Widgets')

    def test_repo_name_follows_a_relative_gitdir(self):
        top = self.repo('Overmind')
        os.makedirs(os.path.join(top, '.git', 'worktrees', 'wt'))
        with open(os.path.join(top, '.git', 'worktrees', 'wt', 'commondir'), 'w') as f:
            f.write('../..\n')
        wt = os.path.join(top, 'wt')
        os.makedirs(wt)
        with open(os.path.join(wt, '.git'), 'w') as f:
            f.write('gitdir: ../.git/worktrees/wt\n')
        self.assertEqual(speechqueue.repo_name(wt), 'Overmind')

    def test_repo_name_without_a_remote_is_the_folder(self):
        self.assertEqual(speechqueue.repo_name(self.repo('LaundryBot')), 'LaundryBot')

    def test_labels_file_wins_without_case_and_is_cut_to_length(self):
        top = self.repo('x', 'git@github.com:someone/Overmind.git')
        self.assertEqual(speechqueue.session_label(top, {'overmind': 'OVMD'}), 'OVMD')
        self.assertEqual(speechqueue.session_label(top, {'Overmind': 'TOOLONG'}), 'TOOL')
        self.assertEqual(speechqueue.session_label(top, {}), 'OVER')

    def test_the_label_is_the_last_field_of_the_session_line(self):
        self.f.session(100, ME, 'One')
        with open(speechqueue.LABELS, 'w') as f:
            json.dump({'One': 'ONE'}, f)
        s = self.state()['sessions'][0]
        self.assertEqual(speechqueue.session_line(s).split('\t')[6], s['label'])


@unittest.skipUnless(shutil.which('lua5.3'), 'lua5.3 is not installed')
class SharedColours(unittest.TestCase):
    """Both widgets' draw.lua, loaded side by side, with the Spotify widget's bg.txt driven
    through a light colour, a dark one and away again: each frame they give conky the same
    title and text colours, white on Spotify's #181818 while there is no bg.txt."""

    HARNESS = """
package.preload['cairo'] = function() return true end
cairo_text_extents_t = {create = function() return {} end}
cairo_font_extents_t = cairo_text_extents_t
conky_info = {update_interval = 0.05}
local function load(path)
    dofile(path)
    return conky_widget, conky_fg
end
local spotify_widget, spotify_fg = load(SPOTIFY)
local speech_widget, speech_fg = load(SPEECH)
local theme, T = package.loaded.theme, 1000
theme.now = function() return T end
theme.BOOT = 'boot-1'
local function put(path, text)
    if text then local f = assert(io.open(path, 'w')); f:write(text); f:close()
    else os.remove(path) end
end
for _, step in ipairs(STEPS) do
    put(step.path, step.text)
    if step.late then speech_widget, speech_fg = load(SPEECH) end
    for _ = 1, step.frames do
        spotify_widget(); speech_widget()
        T = T + 0.05
        print(table.concat({spotify_fg('title'), spotify_fg('text'),
                            speech_fg('title'), speech_fg('text')}, '\\t'))
    end
end
"""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix='speech-colours-')
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.spotify = os.path.join(self.home, '.cache', 'conky-spotify-nowplaying')
        self.setting = os.path.join(self.home, '.config', 'conky-widgets', 'speech', 'background')
        os.makedirs(self.spotify)
        os.makedirs(os.path.dirname(self.setting))
        self.bg = os.path.join(self.spotify, 'bg.txt')

    def frames(self, steps):
        """Each frame's colours, as (Spotify's title, its text, speech's title, its text)."""
        lua = ', '.join('{path = %s, text = %s, frames = %d, late = %s}' % (
            json.dumps(path), json.dumps(text) if text is not None else 'nil', n,
            'true' if late else 'false')
            for path, text, n, *late in steps)
        script = (self.HARNESS
                  .replace('SPOTIFY', json.dumps(os.path.join(support.SRC, 'spotify', 'draw.lua')))
                  .replace('SPEECH', json.dumps(os.path.join(support.SRC, 'speech', 'draw.lua')))
                  .replace('STEPS', '{' + lua + '}'))
        out = subprocess.run(['lua5.3', '-'], input=script, capture_output=True, text=True,
                             check=True, env=dict(os.environ, HOME=self.home)).stdout
        return [tuple(line.split('\t')) for line in out.splitlines()]

    def test_both_widgets_pick_the_same_colours(self):
        frames = self.frames([(self.bg, None, 20),               # no bg.txt yet
                              (self.bg, '0.950 0.900 0.800', 40),  # a light cover
                              (self.bg, '0.157 0.275 0.549', 40),  # a dark one
                              (self.bg, None, 40)])              # gone again
        self.assertEqual(len(frames), 140)
        for i, f in enumerate(frames):
            self.assertEqual(f[:2], f[2:], f'frame {i}')
        self.assertEqual(frames[0][0], '${color ffffff}')       # white on #181818
        self.assertEqual(frames[59][0], '${color 121212}')      # near-black on the light cover
        self.assertEqual(frames[99][0], '${color ffffff}')
        self.assertEqual(frames[-1][0], '${color ffffff}')      # back to the fallback
        with open(self.bg, 'w') as f:
            f.write('0.188 0.424 0.463')
        self.frames([(self.bg, '0.188 0.424 0.463', 5)])
        with open(self.bg) as f:
            self.assertEqual(f.read(), '0.188 0.424 0.463')     # read, never written

    def test_a_widget_started_part_way_shows_the_same_colour(self):
        # bg.txt as art_colours.py writes it: black to white from 1000 s, the harness's first
        # frame. The speech widget, loaded again half a second in with its own #181818, takes
        # the near-black text the light grey there needs from its first frame, as the Spotify
        # widget does, rather than fading from #181818 under white.
        fade = '1.000 1.000 1.000 0.000 0.000 0.000 1000.000 boot-1'
        frames = self.frames([(self.bg, fade, 10), (self.bg, fade, 30, True)])
        for i, f in enumerate(frames):
            self.assertEqual(f[:2], f[2:], f'frame {i}')
        self.assertEqual(frames[0][0], '${color ffffff}')
        self.assertEqual(frames[10][2], '${color 121212}')

    def test_the_fade_takes_wall_clock_time(self):
        # 20 frames of 0.05 s: one second in, the fade is 95% of the way, so near-black text
        fade = '0.950 0.900 0.800 0.094 0.094 0.094 1000.000 boot-1'
        frames = self.frames([(self.bg, fade, 21)])
        self.assertEqual(frames[0][0], '${color ffffff}')
        self.assertEqual(frames[20][0], '${color 121212}')

    def test_a_fade_from_another_boot_is_finished(self):
        # written before a reboot at 999.5 s: the new boot's clock reads 1000 s, half a second
        # on, but the fade is long done, so the light colour's near-black text from the start
        fade = '0.950 0.900 0.800 0.094 0.094 0.094 999.500 boot-0'
        self.assertEqual(self.frames([(self.bg, fade, 1)])[0][0], '${color 121212}')

    def test_falling_back_to_an_earlier_colour_fades_again(self):
        # #181818 without bg.txt, a timed fade to a light colour, then bg.txt gone: back to
        # #181818 over a second, not at once
        fade = '0.950 0.900 0.800 0.094 0.094 0.094 1000.000 boot-1'
        frames = self.frames([(self.bg, None, 2), (self.bg, fade, 40), (self.bg, None, 25)])
        self.assertEqual(frames[41][0], '${color 121212}')
        self.assertEqual(frames[43][0], '${color 121212}')     # still light just after
        self.assertEqual(frames[-1][0], '${color ffffff}')

    def test_the_setting_names_another_file(self):
        other = os.path.join(self.home, 'other.txt')
        frames = self.frames([(self.setting, '~/other.txt\n', 0),
                              (other, '0.950 0.900 0.800', 40)])
        self.assertEqual(frames[-1][0], '${color ffffff}')      # Spotify's still on #181818
        self.assertEqual(frames[-1][2], '${color 121212}')      # speech follows other.txt


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

    def test_after_a_line_the_header_and_full_bar_stay(self):
        self.three()
        self.f.now(ME, 'Claude Voice Widget', 'Done.', hook_pid=9001)
        os.utime(os.path.join(self.f.speak, 'now.json'), (998.0, 998.0))
        self.f.wav(9001, 6.0)
        speechqueue.render(self.state(), now=1000.0)
        os.remove(os.path.join(self.f.speak, 'now.json'))
        self.f.file(OTHER + '.queue', '')
        text = speechqueue.render(self.state(), now=1010.0)
        self.assertIn('Claude Voice Widget says:', text)
        self.assertNotIn('Speech idle', text)
        with open(speechqueue.DRAW) as f:
            progress = next(l for l in f if l.startswith('progress ')).split()
        self.assertEqual(progress[5:], ['6.000', '6.000', '0'])

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
