"""Tests for the launcher: which widget each command acts on, the old Spotify command line
that still works, and the supervisor's choice of which processes to start again, and when."""
import importlib.machinery
import importlib.util
import itertools
import os
import shutil
import subprocess
import unittest
from unittest import mock

import support

BINS = os.path.join(os.path.dirname(support.SRC), 'bin')
BIN = os.path.join(BINS, 'conky-widgets')


def load_launcher():
    loader = importlib.machinery.SourceFileLoader('launcher', BIN)
    spec = importlib.util.spec_from_loader('launcher', loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


launcher = load_launcher()


class Proc:
    """A stand-in for a child process: running until it is ended or exits with `code`."""

    def __init__(self, name):
        self.name, self.returncode, self.ended = name, None, False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.ended, self.returncode = True, -15

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.terminate()


class LauncherTest(support.TempDirTest):
    """A launcher whose folders are in self.dir and whose supervisor is a flag."""

    def setUp(self):
        super().setUp()
        self.redirect(launcher, SHARED_CACHE='shared', PIDFILE='shared/run.pid',
                      WANTED='shared/wanted', UP='shared/up', AUTOSTART_DIR='autostart')
        self.supervisor = None                              # the pid of a running supervisor
        self.legacy = {}                                    # widget -> pid of a pre-bundle supervisor
        self.spawned, self.killed = [], []
        for name, value in (
                ('cache_dir', lambda w: os.path.join(self.dir, 'cache', w)),
                ('conf_dir', lambda w: os.path.join(self.dir, 'conf', w)),
                ('running_pid', lambda: self.supervisor),
                ('legacy_pid', lambda w: self.legacy.get(w)),
                ('installed', lambda w: True),
                ('terminate', self.terminate),
                ('notify', lambda *a: None)):
            patcher = mock.patch.object(launcher, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(launcher.subprocess, 'Popen', side_effect=self.popen)
        patcher.start()
        self.addCleanup(patcher.stop)

    def popen(self, cmd, **kwargs):
        self.spawned.append(cmd)
        self.supervisor = 4242
        return mock.Mock(pid=4242)

    def terminate(self, pid):
        self.killed.append(pid)
        if pid == self.supervisor:
            self.supervisor = None
        self.legacy = {w: p for w, p in self.legacy.items() if p != pid}

    def run_main(self, *args):
        with mock.patch.object(launcher.sys, 'argv', ['conky-widgets', *args]), \
                mock.patch('builtins.print'):
            launcher.main()

    def hidden(self, widget):
        return os.path.exists(os.path.join(self.dir, 'cache', widget, 'hidden'))


class CommandsTest(LauncherTest):

    def test_a_widget_has_its_own_state_folders(self):
        self.assertTrue(launcher.WIDGETS['speech']['cache'].endswith('/.cache/conky-widgets/speech'))
        self.assertTrue(launcher.WIDGETS['speech']['conf'].endswith('/.config/conky-widgets/speech'))

    def test_the_spotify_widget_keeps_the_folders_and_autostart_entry_it_had(self):
        spotify = launcher.WIDGETS['spotify']
        self.assertEqual((spotify['conf'], spotify['cache'], spotify['autostart']),
                         ('~/.config/conky-spotify-nowplaying', '~/.cache/conky-spotify-nowplaying',
                          'conky-spotify-nowplaying.desktop'))

    def test_start_runs_one_supervisor_for_every_widget(self):
        self.run_main('spotify', 'start')
        self.run_main('speech', 'start')
        self.assertEqual(len(self.spawned), 1)
        self.assertEqual(launcher.wanted(), ['spotify', 'speech'])

    def test_the_supervisor_is_findable_before_it_writes_its_own_pid(self):
        self.run_main('spotify', 'start')
        self.assertEqual(open(launcher.PIDFILE).read(), '4242')

    def test_flags_left_by_a_supervisor_that_did_not_exit_are_not_started(self):
        launcher.flag(os.path.join(launcher.WANTED, 'speech'), True)
        self.run_main('spotify', 'start')
        self.assertEqual(launcher.wanted(), ['spotify'])

    def test_start_twice_is_already_running(self):
        self.run_main('spotify', 'start')
        self.run_main('spotify', 'start')
        self.assertEqual(len(self.spawned), 1)

    def test_start_and_restart_keep_a_hidden_widget_hidden(self):
        launcher.set_hidden('spotify', True)
        self.run_main('spotify', 'start')
        self.assertTrue(self.hidden('spotify'))
        self.run_main('restart')
        self.assertTrue(self.hidden('spotify'))

    def test_the_app_grid_entry_starts_a_hidden_widget_shown(self):
        launcher.set_hidden('spotify', True)
        self.run_main('spotify')
        self.assertEqual(launcher.wanted(), ['spotify'])
        self.assertFalse(self.hidden('spotify'))

    def test_a_widget_that_is_not_installed_is_not_started(self):
        with mock.patch.object(launcher, 'installed', lambda w: w != 'speech'):
            self.run_main('speech', 'start')
        self.assertEqual((self.spawned, launcher.wanted()), ([], []))

    def test_stop_ends_only_that_widget(self):
        self.run_main('spotify', 'start')
        self.run_main('speech', 'start')
        self.run_main('speech', 'stop')
        self.assertEqual((launcher.wanted(), self.killed), (['spotify'], []))
        self.assertTrue(launcher.is_running('spotify'))
        self.assertFalse(launcher.is_running('speech'))

    def test_stopping_the_last_widget_ends_the_supervisor(self):
        self.run_main('spotify', 'start')
        self.run_main('spotify', 'stop')
        self.assertEqual(self.killed, [4242])

    def test_restart_starts_the_widget_again(self):
        self.run_main('spotify', 'start')
        self.run_main('spotify', 'restart')
        self.assertEqual((len(self.spawned), launcher.wanted()), (2, ['spotify']))

    def test_restart_with_no_widget_starts_the_running_ones_again(self):
        self.run_main('spotify', 'start')
        self.run_main('speech', 'start')
        self.run_main('restart')
        self.assertEqual((len(self.spawned), launcher.wanted()), (2, ['spotify', 'speech']))

    def test_restart_with_no_widget_leaves_a_stopped_one_stopped(self):
        self.run_main('restart')
        self.assertEqual((self.spawned, launcher.wanted()), ([], []))

    def test_a_supervisor_from_before_the_bundle_is_replaced_by_start(self):
        self.legacy['spotify'] = 777
        self.run_main('spotify', 'start')
        self.assertEqual(self.killed, [777])
        self.assertEqual((len(self.spawned), launcher.wanted()), (1, ['spotify']))

    def test_a_supervisor_from_before_the_bundle_counts_as_running_and_is_stopped(self):
        self.legacy['spotify'] = 777
        self.assertTrue(launcher.is_running('spotify'))
        self.run_main('spotify', 'stop')
        self.assertEqual(self.killed, [777])

    def test_toggle_shows_then_minimizes_then_shows(self):
        self.run_main('speech')                             # not running: starts, showing
        self.assertEqual(launcher.wanted(), ['speech'])
        self.assertFalse(self.hidden('speech'))
        self.run_main('speech')                             # showing: minimizes
        self.assertTrue(self.hidden('speech'))
        self.run_main('speech', 'toggle')                   # minimized: shows
        self.assertFalse(self.hidden('speech'))
        self.assertEqual(self.killed, [])                   # never stops it

    def test_show_and_hide_name_a_widget(self):
        self.run_main('spotify', 'hide')
        self.assertTrue(self.hidden('spotify'))
        self.assertFalse(self.hidden('speech'))
        self.run_main('spotify', 'show')
        self.assertFalse(self.hidden('spotify'))

    def test_show_and_hide_with_no_widget_act_on_every_running_widget(self):
        self.run_main('spotify', 'start')
        self.run_main('speech', 'start')
        self.run_main('hide')
        self.assertTrue(self.hidden('spotify') and self.hidden('speech'))
        self.run_main('show')
        self.assertFalse(self.hidden('spotify') or self.hidden('speech'))

    def test_hide_with_no_widget_leaves_a_stopped_widget_alone(self):
        self.run_main('spotify', 'start')
        self.run_main('hide')
        self.assertFalse(self.hidden('speech'))

    def test_stop_with_no_widget_ends_all(self):
        self.run_main('spotify', 'start')
        self.run_main('speech', 'start')
        self.run_main('stop')
        self.assertEqual((launcher.wanted(), self.killed), ([], [4242]))

    def test_autostart_is_one_entry_per_widget(self):
        with mock.patch.object(launcher.shutil, 'which', return_value='/usr/bin/conky-widgets'):
            self.run_main('speech', 'autostart', 'on')
            self.run_main('spotify', 'autostart', 'on')
        speech = support.read(os.path.join(self.dir, 'autostart', 'conky-widgets-speech.desktop'))
        spotify = support.read(os.path.join(self.dir, 'autostart', 'conky-spotify-nowplaying.desktop'))
        self.assertIn('Exec=/usr/bin/conky-widgets speech start\n', speech)
        self.assertIn('Exec=/usr/bin/conky-widgets spotify start\n', spotify)
        self.run_main('speech', 'autostart', 'off')
        self.assertFalse(os.path.exists(os.path.join(self.dir, 'autostart', 'conky-widgets-speech.desktop')))
        self.assertTrue(os.path.exists(os.path.join(self.dir, 'autostart', 'conky-spotify-nowplaying.desktop')))

    def test_a_command_for_no_such_widget_is_a_usage_error(self):
        for args in (('nothing', 'start'), (), ('start',), ('speech', 'login'), ('spotify', 'autostart', 'maybe')):
            with self.subTest(args=args), self.assertRaises(SystemExit):
                self.run_main(*args)

    def test_login_is_the_spotify_widgets(self):
        with mock.patch.object(launcher.os, 'execv') as execv:
            self.run_main('spotify', 'login')
        self.assertTrue(execv.call_args[0][1][1].endswith('/spotify/spotify_api.py'))
        self.assertEqual(execv.call_args[0][1][2], 'login')


class ShimTest(support.TempDirTest):
    """bin/conky-spotify-nowplaying, which the app-grid entry and the autostart entry of
    an older version still run."""

    def run_shim(self, *args):
        bin_dir = os.path.join(self.dir, 'bin')
        os.makedirs(bin_dir)
        shutil.copy(os.path.join(BINS, 'conky-spotify-nowplaying'), bin_dir)
        stub = os.path.join(bin_dir, 'conky-widgets')
        with open(stub, 'w') as f:
            f.write('#!/bin/sh\nfor a in "$@"; do echo "$a"; done\n')
        os.chmod(stub, 0o755)
        link = os.path.join(self.dir, 'link')
        os.symlink(os.path.join(bin_dir, 'conky-spotify-nowplaying'), link)   # found through a link too
        out = subprocess.run([link, *args], capture_output=True, text=True, check=True).stdout
        return out.split()

    def test_every_old_command_is_the_same_command_for_spotify(self):
        for args in ((), ('start',), ('stop',), ('restart',), ('status',), ('show',), ('hide',), ('login',),
                     ('autostart', 'on'), ('autostart', 'off')):
            with self.subTest(args=args):
                shutil.rmtree(os.path.join(self.dir, 'bin'), ignore_errors=True)
                if os.path.lexists(os.path.join(self.dir, 'link')):
                    os.remove(os.path.join(self.dir, 'link'))
                self.assertEqual(self.run_shim(*args), ['spotify', *args])

    def test_the_commands_exist_in_the_launcher(self):
        for command in ('start', 'stop', 'restart', 'status', 'show', 'hide', 'login', 'autostart'):
            self.assertIn(command, launcher.__doc__)


class SuperviseTest(LauncherTest):

    def run_supervisor(self, passes, at_pass, widgets=('spotify',), stops=False):
        """Runs supervise() for `passes` passes, calling at_pass(n, procs) after each; returns
        every process it started, in order."""
        for widget in widgets:
            launcher.flag(os.path.join(launcher.WANTED, widget), True)
        self.envs = []
        dpis = itertools.chain(['Xft.dpi:\t192\n'], itertools.repeat('Xft.dpi:\t96\n'))
        started, clock, count = [], [1000.0], [0]

        def popen(cmd, cwd, env):
            self.envs.append(env.get('CSN_DPI'))
            name = os.path.basename(cmd[1]).split('.')[0] if cmd[0] != 'conky' else 'conky'
            started.append(Proc(name))
            return started[-1]

        def sleep(seconds):
            clock[0] += seconds
            if seconds == 0.5:                          # the end of a pass
                count[0] += 1
                at_pass(count[0], started)
                if count[0] >= passes:
                    raise StopIteration

        with mock.patch.object(launcher.subprocess, 'Popen', side_effect=popen), \
                mock.patch.object(launcher.time, 'sleep', side_effect=sleep), \
                mock.patch.object(launcher.time, 'monotonic', side_effect=lambda: clock[0]), \
                mock.patch.object(launcher.signal, 'signal'), \
                mock.patch.object(launcher.subprocess, 'run',
                                  side_effect=lambda *a, **k: mock.Mock(stdout=next(dpis))):
            if stops:                                   # at_pass tells it to shut down
                launcher.supervise()
            else:
                with self.assertRaises(StopIteration):
                    launcher.supervise()
        return started

    def names(self, procs):
        return [p.name for p in procs]

    def test_a_scale_change_starts_nowplaying_and_conky_again(self):
        def at_pass(n, procs):
            if n == 5:
                next(p for p in procs if p.name == 'conky-mouse').returncode = launcher.RESCALED
        started = self.run_supervisor(8, at_pass)
        self.assertEqual(self.names(started[:4]), ['nowplaying', 'conky', 'conky-mouse', 'tray'])
        self.assertTrue(started[0].ended and started[1].ended)
        self.assertFalse(started[3].ended)                          # the tray keeps running
        self.assertEqual(sorted(self.names(started[4:])), ['conky', 'conky-mouse', 'nowplaying'])
        # conky-mouse.py compares with the Xft.dpi nowplaying.py started at, read again on its restart.
        self.assertEqual(self.envs[2], '192')
        self.assertEqual(self.names(started[4:]), ['nowplaying', 'conky', 'conky-mouse'])
        self.assertEqual(self.envs[4:], ['96', '96', '96'])

    def test_any_other_exit_starts_only_that_one_again(self):
        def at_pass(n, procs):
            if n == 5:
                next(p for p in procs if p.name == 'conky-mouse').returncode = 1
        started = self.run_supervisor(8, at_pass)
        self.assertEqual(self.names(started[4:]), ['conky-mouse'])
        self.assertFalse(any(p.ended for p in started))


    def test_each_widget_has_its_own_processes_and_goes_when_it_is_no_longer_wanted(self):
        def at_pass(n, procs):
            if n == 5:
                launcher.flag(os.path.join(launcher.WANTED, 'speech'), False)
        with mock.patch.object(launcher, 'processes', lambda w: [] if w == launcher.BUNDLE else [
                ('nowplaying', ['py', f'{w}-contents.py']), ('conky', ['conky', '-c', w])]):
            started = self.run_supervisor(8, at_pass, widgets=('spotify', 'speech'))
        self.assertEqual(self.names(started), ['spotify-contents', 'conky', 'speech-contents', 'conky'])
        self.assertEqual([p.ended for p in started], [False, False, True, True])
        self.assertTrue(os.path.exists(os.path.join(launcher.UP, 'spotify')))
        self.assertFalse(os.path.exists(os.path.join(launcher.UP, 'speech')))

    def test_a_scale_change_in_one_widget_leaves_the_other_alone(self):
        def at_pass(n, procs):
            if n == 5:
                procs[5].returncode = launcher.RESCALED          # speech's mouse helper
        with mock.patch.object(launcher, 'processes', lambda w: [] if w == launcher.BUNDLE else [
                ('nowplaying', ['py', f'{w}-contents.py']), ('conky', ['conky', '-c', w]),
                ('mouse', ['py', f'{w}-mouse.py'])]):
            started = self.run_supervisor(8, at_pass, widgets=('spotify', 'speech'))
        self.assertEqual(self.names(started[:6]),
                         ['spotify-contents', 'conky', 'spotify-mouse', 'speech-contents', 'conky', 'speech-mouse'])
        self.assertEqual([p.ended for p in started[:6]], [False, False, False, True, True, False])
        self.assertEqual(self.names(started[6:]), ['speech-contents', 'conky', 'speech-mouse'])

    def test_one_tray_serves_every_widget_and_goes_with_the_last(self):
        tray_ended = {}

        def at_pass(n, procs):
            tray = next((p for p in procs if p.name == 'tray'), None)
            tray_ended[n] = tray and tray.ended
            if n == 3:
                launcher.flag(os.path.join(launcher.WANTED, 'spotify'), False)
            if n == 5:
                launcher.flag(os.path.join(launcher.WANTED, 'speech'), False)
        with mock.patch.object(launcher, 'processes', lambda w: [
                ('tray', ['py', 'tray.py'])] if w == launcher.BUNDLE else [('conky', ['conky', '-c', w])]):
            started = self.run_supervisor(7, at_pass, widgets=('spotify', 'speech'))
        self.assertEqual(self.names(started), ['conky', 'conky', 'tray'])
        self.assertEqual((tray_ended[4], tray_ended[6]), (False, True))   # kept for speech, then gone
        self.assertEqual(os.listdir(launcher.UP), [])

    def test_no_tray_is_started_when_csn_no_tray_is_set(self):
        with mock.patch.dict(os.environ, {'CSN_NO_TRAY': '1'}), \
                mock.patch.object(launcher, 'processes', lambda w: [
                    ('tray', ['py', 'tray.py'])] if w == launcher.BUNDLE else [('conky', ['conky', '-c', w])]):
            started = self.run_supervisor(3, lambda n, procs: None)
        self.assertEqual(self.names(started), ['conky'])

    def test_the_tray_is_the_bundles_not_a_widgets(self):
        self.assertEqual([name for name, _ in launcher.processes(launcher.BUNDLE)], ['tray'])
        self.assertTrue(launcher.processes(launcher.BUNDLE)[0][1][1].endswith(os.path.join('src', 'tray.py')))
        self.assertNotIn('tray', [name for name, _ in launcher.processes('spotify')])

    def test_shutting_down_ends_every_process_and_removes_its_files(self):
        def at_pass(n, procs):
            if n == 2:
                launcher.signal.signal.call_args_list[0][0][1]()   # what SIGTERM calls
        started = self.run_supervisor(3, at_pass, widgets=('spotify', 'speech'), stops=True)
        self.assertTrue(started and all(p.ended for p in started))
        self.assertFalse(os.path.exists(launcher.PIDFILE))
        self.assertEqual(os.listdir(launcher.UP), [])


class RescaledTest(unittest.TestCase):

    def test_the_launcher_and_conky_mouse_agree_on_the_exit_status(self):
        self.assertEqual(launcher.RESCALED, support.load_conky_mouse().RESCALED)


if __name__ == '__main__':
    unittest.main()
