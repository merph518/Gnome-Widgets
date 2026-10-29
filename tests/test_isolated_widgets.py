"""Tests for scripts/isolated-widgets.py: that a copy's files and fixtures stay inside its own
folder and read as the orchestrator widget reads the real ones, without a display."""
import importlib.machinery
import importlib.util
import os
import time
import unittest
from unittest import mock

import support

SCRIPT = os.path.join(os.path.dirname(support.SRC), 'scripts', 'isolated-widgets.py')


def load_script():
    loader = importlib.machinery.SourceFileLoader('isolated_widgets', SCRIPT)
    spec = importlib.util.spec_from_loader('isolated_widgets', loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


iso = load_script()


class IsolatedTest(support.TempDirTest):

    def setUp(self):
        super().setUp()
        self.copy = iso.Copy('one', base=os.path.join(self.dir, 'copies'))

    def test_the_environment_is_the_copys_own_with_no_tray(self):
        env = self.copy.env()
        self.assertEqual((env['HOME'], env['XDG_RUNTIME_DIR'], env['CSN_NO_TRAY']),
                         (self.copy.home, self.copy.runtime, '1'))
        self.assertNotIn(os.environ.get('HOME'), [env['HOME']])

    def test_the_copy_has_no_spotify_login(self):
        iso.link_runtime(self.copy, self.dir)
        self.assertFalse(os.path.exists(os.path.join(self.copy.config('spotify'), 'spotify-token.json')))
        self.assertTrue(self.copy.config('spotify').startswith(self.copy.home))

    def test_the_runtime_folder_links_the_desktops_entries_but_not_the_hooks_folder(self):
        real = os.path.join(self.dir, 'real')
        os.makedirs(os.path.join(real, 'speak-attention'))
        open(os.path.join(real, 'bus'), 'w').close()
        iso.link_runtime(self.copy, real)
        self.assertEqual(sorted(os.listdir(self.copy.runtime)), ['bus'])
        self.assertTrue(os.path.islink(os.path.join(self.copy.runtime, 'bus')))
        self.assertTrue(os.path.realpath(self.copy.runtime).startswith(self.dir))

    def test_the_built_in_display_is_where_a_copy_goes_else_the_primary_monitor_else_the_first(self):
        starred = ('Monitors: 2\n 0: +HDMI-1 1920/527x1080/296+1920+0  HDMI-1\n'
                   ' 1: +*DP-1 2560/600x1440/340+0+10  DP-1\n')
        self.assertEqual(iso.monitor_of(starred), (0, 10, 2560, 1440))
        unstarred = starred.replace('+*DP-1', '+DP-1')
        self.assertEqual(iso.monitor_of(unstarred), (1920, 0, 1920, 1080))
        self.assertEqual(iso.monitor_of(''), (0, 0, 1920, 1080))
        for name in ('eDP-1', 'LVDS-1', 'DSI-1', 'eDP-1-1'):
            with self.subTest(name):
                listing = (' 0: +*HDMI-1 5120/700x2880/390+5120+0  HDMI-1\n'
                           ' 1: +DP-1 5120/600x2880/340+0+0  DP-1\n'
                           f' 2: +{name} 3072/290x1920/180+10240+0  {name}\n')
                self.assertEqual(iso.monitor_of(listing), (10240, 0, 3072, 1920))

    def test_a_monitor_that_only_has_edp_in_its_name_is_not_the_built_in_display(self):
        listing = (' 0: +*HDMI-1 1920/527x1080/296+0+0  HDMI-1\n'
                   ' 1: +MEDP-1 2560/600x1440/340+1920+0  MEDP-1\n')
        self.assertEqual(iso.monitor_of(listing), (0, 0, 1920, 1080))

    def test_a_copy_stays_inside_the_built_in_display_for_the_first_slots(self):
        mon = iso.monitor_of(' 0: +*HDMI-1 5120/700x2880/390+5120+0  HDMI-1\n'
                             ' 1: +eDP-1 3072/290x1920/180+10240+0  eDP-1\n')
        for slot in range(4):
            for widget in ('spotify', 'orchestrator'):
                x, y = iso.position_for(slot, mon, widget)
                self.assertTrue(mon[0] <= x < mon[0] + mon[2] and mon[1] <= y < mon[1] + mon[3], (slot, widget))

    def test_each_slot_is_further_left_and_the_orchestrator_widget_sits_below_spotify(self):
        mon = (0, 0, 3000, 2000)
        s0, s1 = iso.position_for(0, mon, 'spotify'), iso.position_for(1, mon, 'spotify')
        self.assertEqual((s0[0] - s1[0], s1[1] - s0[1]), (iso.SLOT, iso.SLOT))
        self.assertEqual(iso.position_for(0, mon, 'orchestrator')[1] - s0[1], iso.ORCHESTRATOR_BELOW)
        self.assertEqual(iso.position_for(5, mon, 'spotify', at=(7, 8)), (7, 8))

    def test_a_copy_takes_the_first_slot_no_other_copy_holds(self):
        base = os.path.join(self.dir, 'copies')
        for name, slot in (('a', 0), ('b', 2)):
            iso.write(os.path.join(base, name, 'slot'), str(slot))
        self.assertEqual(iso.taken_slots(base, 'a'), {2})
        self.assertEqual(iso.taken_slots(base, 'c'), {0, 2})

    def test_the_fixture_feeds_show_a_recent_reply_an_older_one_and_none(self):
        orchestrator = support.load_orchestrator()
        iso.write_fixtures(self.copy, [os.getpid(), os.getppid(), 1, 2])
        state = orchestrator.read_state(self.copy.hook_dir, self.copy.sessions, now=time.time())
        rows = {s['name']: s for s in state['sessions']}
        self.assertEqual(sorted(rows), ['Feed widget', 'Retry fix', 'Waiting on tests'])
        self.assertEqual(rows['Feed widget']['age'], '1m')
        self.assertTrue(rows['Feed widget']['last'].startswith('The feed lists replies'))      # under ten minutes: a line too
        self.assertEqual((rows['Waiting on tests']['age'], rows['Waiting on tests']['last']), ('25m', ''))
        self.assertEqual((rows['Retry fix']['age'], rows['Retry fix']['last']), ('', ''))
        self.assertEqual([e['name'] for e in state['feed']], ['Feed widget', 'Waiting on tests', 'Feed widget'])

    def test_the_fixture_has_an_unmanaged_session_the_widget_does_not_list(self):
        iso.write_fixtures(self.copy, [os.getpid(), os.getppid(), 1, 2])
        sessions = iso.fixture_sessions(self.copy, [1, 2, 3, 4])
        self.assertEqual([x[-1] for x in sessions], [True, True, True, False])
        state = support.load_orchestrator().read_state(self.copy.hook_dir, self.copy.sessions)
        self.assertNotIn('Not managed', [s['name'] for s in state['sessions']])
        self.assertTrue(os.path.exists(os.path.join(self.copy.hook_dir, sessions[0][1] + '.managed')))
        self.assertFalse(os.path.exists(os.path.join(self.copy.hook_dir, sessions[3][1] + '.managed')))
        self.assertFalse(os.path.exists(os.path.join(self.copy.hook_dir, sessions[3][1] + '.feed')))

    def test_the_fixture_has_nothing_that_plays(self):
        iso.write_fixtures(self.copy, [os.getpid(), os.getppid(), 1, 2])
        self.assertEqual(sorted(f for f in os.listdir(self.copy.hook_dir) if not f.endswith(('.managed', '.feed'))), [])

    def test_only_a_process_named_for_the_copy_is_signalled_on_stop(self):
        iso.write(self.copy.pids, f'{os.getpid()}\n')           # this very process: not a fixture
        with mock.patch.object(iso.os, 'kill') as kill:
            iso.stop_fixture_processes(self.copy)
        kill.assert_not_called()
        self.assertFalse(iso.fixture_alive(self.copy))

    def test_fixture_processes_start_named_for_the_copy_and_stop(self):
        pids = iso.start_fixture_processes(self.copy, count=2)
        try:
            self.assertEqual([iso.argv0(p) for p in pids], [f'{iso.FIXTURE_TAG}:one'] * 2)
            self.assertTrue(iso.fixture_alive(self.copy))
        finally:
            iso.stop_fixture_processes(self.copy)

    def test_stop_removes_the_copys_folder_and_nothing_beside_it(self):
        beside = os.path.join(self.dir, 'copies', 'two')
        os.makedirs(beside)
        iso.write(os.path.join(self.copy.home, 'x'), '')
        with mock.patch.object(iso, 'run_launcher'), mock.patch.object(iso, 'supervisor_pid', return_value=None), \
                mock.patch('builtins.print'):
            iso.stop(self.copy)
        self.assertFalse(os.path.exists(self.copy.root))
        self.assertTrue(os.path.isdir(beside))

    def test_stopping_a_copy_that_does_not_exist_runs_nothing(self):
        with mock.patch.object(iso, 'run_launcher') as run, mock.patch('builtins.print'):
            iso.stop(self.copy)
        run.assert_not_called()

    def test_the_copys_windows_have_a_class_of_their_own(self):
        other = iso.Copy('two', base=self.copy.root)
        self.assertNotEqual(self.copy.suffix, other.suffix)
        self.assertEqual(self.copy.env()['CSN_CLASS_SUFFIX'], self.copy.suffix)
        tree = (f'     0xa00002 "conky": ("ConkySpotifyNowPlaying" "ConkySpotifyNowPlaying")  1x1+0+0  +0+0\n'
                f'     0x1c00002 "conky": ("ConkySpotifyNowPlaying{other.suffix}" "x")  1x1+0+0  +0+0\n'
                f'     0x2800002 "conky": ("ConkySpotifyNowPlaying{self.copy.suffix}" "x")  1x1+0+0  +0+0\n')
        with mock.patch.object(iso.subprocess, 'run', return_value=mock.Mock(stdout=tree)):
            self.assertEqual(iso.window_of(self.copy, 'spotify'), 0x2800002)
            self.assertIsNone(iso.window_of(self.copy, 'orchestrator'))

    def test_the_installed_widgets_are_refused_until_they_give_a_copy_its_own_class(self):
        iso.write(os.path.join(self.dir, 'old', 'spotify', 'conky.conf'), "own_window_class = 'X'\n")
        iso.write(os.path.join(self.dir, 'new', 'spotify', 'conky.conf'), "os.getenv('CSN_CLASS_SUFFIX')\n")
        self.assertFalse(iso.installed_has_class_suffix(os.path.join(self.dir, 'old')))
        self.assertTrue(iso.installed_has_class_suffix(os.path.join(self.dir, 'new')))
        self.assertFalse(iso.installed_has_class_suffix(os.path.join(self.dir, 'none')))
        with mock.patch.object(iso, 'installed_has_class_suffix', return_value=False), \
                mock.patch.object(iso, 'run_launcher') as run, self.assertRaises(SystemExit):
            iso.start(self.copy, ['spotify'], installed=True)
        run.assert_not_called()

    def test_a_name_that_would_leave_the_base_folder_is_refused(self):
        for name in ('.', '..', '.hidden', 'a/b', ''):
            with self.assertRaises(SystemExit), mock.patch.object(iso, 'stop') as stop:
                iso.main(['--name', name, 'stop'])
            stop.assert_not_called()

    def test_a_copy_that_does_not_stop_keeps_its_files(self):
        iso.write(os.path.join(self.copy.home, 'x'), '')
        with mock.patch.object(iso, 'run_launcher'), mock.patch.object(iso, 'supervisor_pid', return_value=1), \
                mock.patch.object(iso.time, 'sleep'), mock.patch.object(iso.time, 'monotonic', side_effect=[0, 1, 9]), \
                self.assertRaises(SystemExit):
            iso.stop(self.copy)
        self.assertTrue(os.path.exists(os.path.join(self.copy.home, 'x')))

    def test_the_environment_drops_the_desktops_xdg_base_folders(self):
        with mock.patch.dict(os.environ, {'XDG_CACHE_HOME': '/real/cache', 'XDG_CONFIG_HOME': '/real/config'}):
            env = self.copy.env()
        self.assertNotIn('XDG_CACHE_HOME', env)
        self.assertNotIn('XDG_CONFIG_HOME', env)

    def test_the_default_name_follows_the_checkout(self):
        self.assertEqual(iso.default_name(), os.path.basename(iso.CHECKOUT))


if __name__ == '__main__':
    unittest.main()
