"""Tests for the tray menu's model: each widget's Show tick follows its own hidden flag
whichever way the flag changed (the menu, the widget's – and × buttons, the launcher), one
widget's buttons leave the other alone, and the speech settings and speechctl."""
import json
import os
import shutil
import stat
import sys
from unittest import mock

import support

sys.path.insert(0, support.SRC)
import tray_model  # noqa: E402

from test_launcher import launcher  # noqa: E402


class FlagsTest(support.TempDirTest):
    """Both widgets running, with every path the three sources write in the test's HOME."""

    def setUp(self):
        super().setUp()
        for folder in ('.cache', '.config'):
            self.addCleanup(shutil.rmtree, os.path.join(support.HOME, folder), ignore_errors=True)
        for widget in tray_model.WIDGETS:
            launcher.flag(os.path.join(tray_model.UP, widget), True)
        patcher = mock.patch.object(tray_model.subprocess, 'Popen')
        self.popen = patcher.start()
        self.addCleanup(patcher.stop)
        self.mouse = support.load_conky_mouse()     # set up for the Spotify widget
        self.mouse.x11.reset_mock()

    def ticks(self):
        return {widget: tray_model.shown(widget) for widget in tray_model.WIDGETS}

    def test_the_tray_and_the_launcher_agree_on_the_flags(self):
        for widget in tray_model.WIDGETS:
            self.assertEqual(tray_model.hidden_file(widget), launcher.hidden_file(widget))
            self.assertEqual(tray_model.autostart_file(widget), launcher.autostart_file(widget))
        self.assertEqual(tray_model.UP, launcher.UP)
        self.assertEqual(tray_model.hidden_file('spotify'), self.mouse.HIDDEN)

    def test_ticks_follow_the_menu(self):
        tray_model.show('speech', False)
        self.assertEqual(self.ticks(), {'spotify': True, 'speech': False})
        tray_model.show('speech', True)
        self.assertEqual(self.ticks(), {'spotify': True, 'speech': True})
        self.popen.assert_not_called()                     # both were running

    def test_ticks_follow_the_launcher(self):
        with mock.patch.object(launcher.sys, 'argv', ['conky-widgets', 'spotify', 'hide']):
            launcher.main()
        self.assertEqual(self.ticks(), {'spotify': False, 'speech': True})
        with mock.patch.object(launcher.sys, 'argv', ['conky-widgets', 'spotify', 'show']):
            launcher.main()
        self.assertEqual(self.ticks(), {'spotify': True, 'speech': True})

    def test_ticks_follow_the_buttons(self):
        for button in ('minimize', 'close'):
            with self.subTest(button=button):
                self.mouse.press(1, 0x111, button)
                self.assertEqual(self.ticks(), {'spotify': False, 'speech': True})
                tray_model.show('spotify', True)

    def test_one_widgets_buttons_leave_the_others_window_and_flag_alone(self):
        for button in ('minimize', 'close'):
            with self.subTest(button=button), \
                    mock.patch.object(self.mouse.hooks, 'press') as hook, \
                    mock.patch('subprocess.Popen') as popen:
                self.mouse.x11.reset_mock()
                self.mouse.press(1, 0x111, button)
                self.mouse.x11.XUnmapWindow.assert_called_once_with(1, 0x111)
                self.mouse.x11.XMapWindow.assert_not_called()
                self.assertFalse(os.path.exists(tray_model.hidden_file('speech')))
                hook.assert_not_called()
                popen.assert_not_called()                  # × starts nothing, stopping included
                tray_model.show('spotify', True)

    def test_a_tick_starts_a_widget_that_is_not_running(self):
        launcher.flag(os.path.join(tray_model.UP, 'speech'), False)
        tray_model.set_hidden('speech', True)
        self.assertFalse(tray_model.shown('speech'))
        tray_model.show('speech', True)
        self.assertFalse(os.path.exists(tray_model.hidden_file('speech')))
        self.assertEqual(self.popen.call_args[0][0][1:], ['speech', 'start'])

    def test_a_stopped_widget_is_not_ticked(self):
        launcher.flag(os.path.join(tray_model.UP, 'speech'), False)
        self.assertEqual(self.ticks(), {'spotify': True, 'speech': False})

    def test_each_widget_has_its_own_size_and_on_top(self):
        self.assertNotEqual(tray_model.size_file('spotify'), tray_model.size_file('speech'))
        tray_model.set_on_top('speech', False)
        self.assertEqual((tray_model.on_top('spotify'), tray_model.on_top('speech')), (True, False))
        self.assertEqual(tray_model.on_top_file('spotify'), self.mouse.ON_TOP)


class SpeechTest(support.TempDirTest):

    def setUp(self):
        super().setUp()
        self.f = support.SpeechFixture(self.dir)
        self.redirect(tray_model, SPEAK='speak-attention', SPEECHCTL='speechctl-path')

    def write(self, name, content):
        self.f.file(name, content if isinstance(content, str) else json.dumps(content))

    def executable(self, name):
        path = os.path.join(self.dir, name)
        with open(path, 'w') as f:
            f.write('#!/bin/sh\n')
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        return path

    def test_settings_and_their_defaults(self):
        self.assertEqual(tray_model.speech_settings(), (tray_model.DEFAULT_VOICE, tray_model.DEFAULT_VOLUME))
        self.write('settings.json', {'voice': 'en_US-ryan-high', 'volume': 0.5})
        self.assertEqual(tray_model.speech_settings(), ('en_US-ryan-high', 0.5))
        self.write('settings.json', {'volume': 'loud'})
        self.assertEqual(tray_model.speech_settings(), (tray_model.DEFAULT_VOICE, tray_model.DEFAULT_VOLUME))

    def test_pace_from_settings_then_the_environment_then_the_default(self):
        with mock.patch.dict(os.environ, clear=False):
            os.environ.pop('SPEAK_PIPER_LENGTH', None)
            self.assertEqual(tray_model.speech_pace(), tray_model.DEFAULT_PACE)
            os.environ['SPEAK_PIPER_LENGTH'] = '0.7'
            self.assertEqual(tray_model.speech_pace(), 0.7)
            self.write('settings.json', {'pace': 1.2})
            self.assertEqual(tray_model.speech_pace(), 1.2)
            self.write('settings.json', {'pace': 'slow'})
            self.assertEqual(tray_model.speech_pace(), 0.7)

    def test_setting_the_pace_keeps_the_other_settings(self):
        self.write('settings.json', {'voice': 'en_US-ryan-high', 'volume': 0.5})
        tray_model.set_speech_pace(1.0)
        with open(os.path.join(tray_model.SPEAK, 'settings.json')) as f:
            self.assertEqual(json.load(f), {'voice': 'en_US-ryan-high', 'volume': 0.5, 'pace': 1.0})
        self.assertEqual(tray_model.speech_settings(), ('en_US-ryan-high', 0.5))
        self.assertEqual(tray_model.speech_pace(), 1.0)

    def test_setting_the_pace_starts_a_settings_file(self):
        tray_model.set_speech_pace(0.6)
        self.assertEqual(tray_model.speech_pace(), 0.6)
        self.assertEqual(sorted(f for f in os.listdir(tray_model.SPEAK) if f.startswith('.tmp')), [])

    def test_speechctl_from_the_configured_path_then_path(self):
        with mock.patch.object(tray_model.shutil, 'which', return_value='/usr/bin/speechctl'):
            self.assertEqual(tray_model.speechctl(), '/usr/bin/speechctl')
            configured = self.executable('my-speechctl')
            with open(tray_model.SPEECHCTL, 'w') as f:
                f.write(configured + '\n')
            self.assertEqual(tray_model.speechctl(), configured)
            os.remove(configured)                          # configured but gone: PATH's
            self.assertEqual(tray_model.speechctl(), '/usr/bin/speechctl')
            with open(tray_model.SPEECHCTL, 'w') as f:
                f.write(self.dir + '\n')                   # a folder is not a speechctl
            self.assertEqual(tray_model.speechctl(), '/usr/bin/speechctl')

    def test_without_speechctl_nothing_runs(self):
        with mock.patch.object(tray_model.shutil, 'which', return_value=None), \
                mock.patch.object(tray_model.subprocess, 'Popen') as popen:
            self.assertFalse(tray_model.run_speechctl('skip'))
            self.assertEqual(tray_model.voices(), [])
        popen.assert_not_called()

    def test_the_menu_items_call_speechctl(self):
        with mock.patch.object(tray_model.shutil, 'which', return_value='/usr/bin/speechctl'), \
                mock.patch.object(tray_model.subprocess, 'Popen') as popen:
            self.assertTrue(tray_model.run_speechctl('volume', '1.5'))
        self.assertEqual(popen.call_args[0][0], ['/usr/bin/speechctl', 'volume', '1.5'])

    def test_voices_are_the_first_word_of_each_line(self):
        out = 'en_US-amy-medium  (current)\n\nen_US-ryan-high\n'
        with mock.patch.object(tray_model.shutil, 'which', return_value='/usr/bin/speechctl'), \
                mock.patch.object(tray_model.subprocess, 'run', return_value=mock.Mock(stdout=out)):
            self.assertEqual(tray_model.voices(), ['en_US-amy-medium', 'en_US-ryan-high'])

    def test_the_current_voice_is_named_not_its_marker(self):
        out = '* en_US-amy-medium\n  en_US-lessac-medium\n  en_US-ryan-high\n'
        with mock.patch.object(tray_model.shutil, 'which', return_value='/usr/bin/speechctl'), \
                mock.patch.object(tray_model.subprocess, 'run', return_value=mock.Mock(stdout=out)):
            self.assertEqual(tray_model.voices(), ['en_US-amy-medium', 'en_US-lessac-medium', 'en_US-ryan-high'])
