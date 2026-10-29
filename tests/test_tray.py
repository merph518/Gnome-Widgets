"""Tests for the tray menu's model: each widget's Show tick follows its own hidden flag
whichever way the flag changed (the menu, the widget's – and × buttons, the launcher), one
widget's buttons leave the other alone."""
import os
import shutil
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
