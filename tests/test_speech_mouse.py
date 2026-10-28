"""The speech widget's controls (src/speech/mouse.py): which speechctl command a click, tap or
wheel step on each region runs, checked against a stub speechctl that records its arguments,
and the wheel and swipes that scroll the session list."""
import os
import subprocess
import unittest
from unittest import mock

import support

conky_mouse = support.load_conky_mouse()
speech_mouse = support.load_speech_mouse()
tray_model = speech_mouse.tray_model

# As speechqueue.py writes them: two sessions, the first On (two rows of 24 px), the second
# Alerts (one row), the list from y 94 to 142 with one row scrolled out of view at most.
REGIONS = {'minimize': [484.0, 16.0, 506.0, 38.0], 'close': [506.0, 16.0, 540.0, 38.0],
           'skip': [429.0, 14.0, 455.0, 40.0], 'next': [455.0, 14.0, 481.0, 40.0],
           'list': [16, 94.0, 522, 142.0], 'list_scroll': [1, 24.0],
           'rows': [{'id': 'aaaa', 'speech': 'on', 'top': 0.0, 'bottom': 48.0,
                     'on': [410.0, 440.0], 'alerts': [440.0, 489.0], 'off': [489.0, 522]},
                    {'id': 'bbbb', 'speech': 'alerts', 'top': 48.0, 'bottom': 72.0,
                     'on': [410.0, 440.0], 'alerts': [440.0, 489.0], 'off': [489.0, 522]}],
           'pause': [12.0, 339.0, 48.0, 375.0], 'voice_prev': [478.0, 346.0, 500.0, 368.0],
           'voice_next': [500.0, 346.0, 522.0, 368.0], 'volume': [78.0, 347.0, 170.0, 367.0],
           'volume_wheel': [56.0, 347.0, 170.0, 367.0], 'volume_bar': [84.0, 164.0],
           'voice': [406.0, 346.0, 522.0, 368.0]}


def centre(r):
    return (r[0] + r[2]) / 2, (r[1] + r[3]) / 2


class StubSpeechctl(support.TempDirTest):
    """A speechctl that appends its arguments to a file, named by tray_model's setting."""

    def setUp(self):
        super().setUp()
        ctl, self.calls = support.stub_speechctl(self.dir)
        with open(os.path.join(self.dir, 'speechctl-path'), 'w') as f:
            f.write(ctl)
        self.redirect(tray_model, SPEECHCTL='speechctl-path')
        self.redirect(speech_mouse, LIST_SCROLL='list-scroll', CACHE='')
        self.redirect(conky_mouse, LOG='mouse.log')
        popen = subprocess.Popen

        def run_through(*args, **kwargs):
            # speechctl runs unwaited; waited here, so its runs land in order
            p = popen(*args, **kwargs)
            p.wait()
            return p
        patcher = mock.patch.object(tray_model.subprocess, 'Popen', side_effect=run_through)
        patcher.start()
        self.addCleanup(patcher.stop)

    def ran(self):
        """The stub's arguments, a line a run."""
        return support.read(self.calls).splitlines() if os.path.exists(self.calls) else []

    def scroll_to(self, rows):
        with open(speech_mouse.LIST_SCROLL, 'w') as f:
            f.write(str(rows))


class ButtonsTest(StubSpeechctl):
    def test_each_button_runs_its_command(self):
        want = {'skip': 'skip', 'next': 'next', 'pause': 'toggle',
                'voice_prev': 'voice prev', 'voice_next': 'voice next'}
        for name, args in want.items():
            with self.subTest(name=name):
                x, y = centre(REGIONS[name])
                self.assertEqual(speech_mouse_region(x, y), name)
                self.assertIn(name, speech_mouse.BUTTONS)
                speech_mouse.press(None, None, name)
                self.assertEqual(self.ran()[-1], args)

    def test_without_a_speechctl_nothing_runs_and_it_is_logged(self):
        os.remove(os.path.join(self.dir, 'speechctl-path'))
        with mock.patch.object(tray_model.shutil, 'which', return_value=None):
            speech_mouse.press(None, None, 'skip')
        self.assertIn('speechctl skip: no speechctl', support.read(conky_mouse.LOG))


class VolumeSliderTest(StubSpeechctl):
    def setUp(self):
        super().setUp()
        self.redirect(speech_mouse, VOLUME_PREVIEW='volume-preview')

    def drag(self, *xs, s=1):
        """Drags along the slider at root xs (the card's left at root 1000), let go at the last,
        and returns the previews draw.lua was shown along the way."""
        steps = [(x, 857, True) for x in xs] + [(xs[-1], 857, False)]
        shown = []

        def sleep(_):
            if os.path.exists(speech_mouse.VOLUME_PREVIEW):
                shown.append(support.read(speech_mouse.VOLUME_PREVIEW))
        with mock.patch.object(conky_mouse, 'card_of', return_value=(1000, 500, 545, 400)), \
                mock.patch.object(conky_mouse, 'geometry'), \
                mock.patch.object(speech_mouse.time, 'sleep', side_effect=sleep):
            speech_mouse.set_volume('d', 'win', REGIONS, s, mock.Mock(side_effect=steps))
        return shown

    def test_a_drag_previews_each_level_and_sets_where_it_is_let_go(self):
        shown = self.drag(1050, 1124, 1200)
        self.assertEqual(shown[:3], ['0.0000', '0.5000', '1.0000'])      # clamped at the ends
        self.assertEqual(self.ran(), ['volume 2.0'])                      # once, at the end
        self.assertIn('speechctl volume 2.0', support.read(conky_mouse.LOG))
        self.assertFalse(os.path.exists(speech_mouse.VOLUME_PREVIEW))   # gone once let go

    def test_a_click_sets_a_tenth_at_a_time(self):
        self.drag(1084 + 49)                       # 0.6125 along: 1.225, a tenth is 1.2
        self.assertEqual(self.ran(), ['volume 1.2'])

    def test_the_slider_follows_the_display_scale(self):
        self.drag(1000 + 104 * 2, s=2)                    # a quarter along at scale 2
        self.assertEqual(self.ran(), ['volume 0.5'])

    def test_a_press_on_the_slider_sets_the_volume_and_the_speaker_does_not(self):
        x, y = centre(REGIONS['volume'])
        self.assertEqual(speech_mouse_region(x, y), 'volume')
        self.assertNotIn('volume', speech_mouse.BUTTONS)
        self.assertIsNone(speech_mouse_region(64, 357))                 # the speaker
        with mock.patch.object(speech_mouse, 'set_volume') as set_volume:
            self.assertTrue(speech_mouse.pull_control('d', 'root', 'win', 1, REGIONS, 'volume',
                                                      'track', (x, y, (1000 + x, 500 + y)), False))
        set_volume.assert_called_once()


def speech_mouse_region(x, y, s=1):
    """The button region_at would find, looking through the speech widget's regions."""
    for name in speech_mouse.REGIONS_ORDER:
        r = REGIONS.get(name)
        if r and r[0] * s <= x <= r[2] * s and r[1] * s <= y <= r[3] * s:
            return name
    return None


class SegmentsTest(StubSpeechctl):
    def press(self, x, y, s=1, touch=False, moved=False):
        """A press at card (x, y) logical px that lifts where it went down, or after a drag."""
        steps = [(x * s + (40 if moved else 0), y * s, True), (x * s, y * s, False)]
        track = mock.Mock(side_effect=steps + [steps[-1]] * 50)
        with mock.patch.object(conky_mouse.time, 'sleep'), \
                mock.patch.object(conky_mouse, 'drag', return_value=(0, 0, 1, 1)) as drag, \
                mock.patch.object(conky_mouse, 'remember'):
            hit = speech_mouse.pull_control(None, None, None, s, REGIONS, None, track,
                                            (x * s, y * s, (x * s, y * s)), touch)
        return hit, drag.called

    def test_a_click_on_each_segment_sets_the_session(self):
        self.assertEqual(self.press(425, 106), (True, False))       # the first row's On
        self.assertEqual(self.press(460, 106), (True, False))       # its Alerts
        self.assertEqual(self.press(500, 154 - 12), (True, False))  # the second row's Off
        self.assertEqual(self.ran(), ['speech aaaa on', 'speech aaaa alerts', 'speech bbbb off'])

    def test_a_tap_does_the_same_at_scale_2(self):
        self.assertEqual(self.press(460, 106, s=2, touch=True), (True, False))
        self.assertEqual(self.ran(), ['speech aaaa alerts'])

    def test_the_second_row_and_the_name_are_not_the_control(self):
        self.assertEqual(self.press(460, 130), (False, False))      # under the first row's segments
        self.assertEqual(self.press(200, 106), (False, False))      # on its name
        self.assertEqual(self.press(460, 300), (False, False))      # off the list

    def test_the_list_scrolled_a_row_moves_the_rows_up(self):
        self.scroll_to(1)
        self.press(500, 94 + 48 - 24 + 6)                           # the second row, now 24 px up
        self.assertEqual(self.ran(), ['speech bbbb off'])

    def test_a_drag_from_a_segment_moves_the_widget_and_sets_nothing(self):
        self.assertEqual(self.press(425, 106, moved=True), (True, True))
        self.assertEqual(self.ran(), [])


class WheelTest(StubSpeechctl):
    def wheel(self, name_or_xy, down, s=1):
        x, y = centre(REGIONS[name_or_xy]) if isinstance(name_or_xy, str) else name_or_xy
        return speech_mouse.wheel(REGIONS, s, x * s, y * s, down)

    def test_over_the_volume_and_the_voice(self):
        self.assertEqual([self.wheel('volume', True), self.wheel((64, 357), False),
                          self.wheel('voice', True), self.wheel((420, 357), False)],
                         ['volume', 'volume', 'voice', 'voice'])
        self.assertEqual(self.ran(), ['volume down', 'volume up', 'voice next', 'voice prev'])

    def test_over_a_setting_it_moves_a_segment_and_stops_at_the_ends(self):
        self.assertEqual(self.wheel((460, 106), True), 'setting')    # On -> Alerts
        self.assertEqual(self.wheel((460, 106), False), 'setting')   # On is the first: nothing
        self.wheel((460, 154 - 12), False)                           # Alerts -> On
        self.assertEqual(self.ran(), ['speech aaaa alerts', 'speech bbbb on'])

    def test_over_the_rest_of_the_list_it_scrolls_a_row_within_its_range(self):
        self.assertEqual(self.wheel((200, 106), True), 'list')
        self.assertEqual(support.read(speech_mouse.LIST_SCROLL), '1')
        self.wheel((200, 106), True)
        self.assertEqual(support.read(speech_mouse.LIST_SCROLL), '1')   # the last row
        self.wheel((200, 106), False)
        self.wheel((200, 106), False)
        self.assertEqual(support.read(speech_mouse.LIST_SCROLL), '0')
        self.assertEqual(self.ran(), [])

    def test_anywhere_else_it_does_nothing(self):
        self.assertIsNone(self.wheel((300, 60), True))
        self.assertIsNone(self.wheel((300, 357), True))              # the footer between them

    def test_the_areas_follow_the_display_scale(self):
        self.assertEqual(self.wheel('volume', True, s=2), 'volume')
        self.assertIsNone(speech_mouse.wheel(REGIONS, 2, 100, 357 * 2, True))   # left of it at 2x


class SwipeTest(StubSpeechctl):
    def test_a_finger_scrolls_the_list_a_row_per_row_moved(self):
        self.assertTrue(speech_mouse.scrollable(REGIONS, 1, 200, 106))
        self.assertFalse(speech_mouse.scrollable(dict(REGIONS, list_scroll=[0, 24.0]), 1, 200, 106))
        steps = [(300, y, True) for y in (500, 470, 440)] + [(300, 440, False)]
        with mock.patch.object(conky_mouse.time, 'sleep'), mock.patch.object(speech_mouse.time, 'sleep'):
            speech_mouse.swipe(REGIONS, 1, 200, 106, 500, mock.Mock(side_effect=steps))
        self.assertEqual(support.read(speech_mouse.LIST_SCROLL), '1')   # 60 px up, one row to scroll
        self.assertIn('swipe: 1 rows', support.read(conky_mouse.LOG))

    def test_a_swipe_from_a_segment_scrolls_and_sets_nothing(self):
        steps = [(300, 500, True), (300, 460, True), (300, 460, False)]
        track = mock.Mock(side_effect=steps)
        with mock.patch.object(conky_mouse.time, 'sleep'), mock.patch.object(speech_mouse.time, 'sleep'):
            self.assertTrue(speech_mouse.pull_control(None, None, None, 1, REGIONS, None, track,
                                                      (460, 106, (300, 500)), True))
        self.assertEqual(support.read(speech_mouse.LIST_SCROLL), '1')
        self.assertEqual(self.ran(), [])


if __name__ == '__main__':
    unittest.main()
