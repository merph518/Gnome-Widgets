"""The speech widget's controls (src/speech/mouse.py): which speechctl command a click, tap or
wheel step on each region runs, checked against a stub speechctl that records its arguments,
and the wheel and swipes that scroll the session list."""
import json
import os
import shutil
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
           'pause': [12.0, 339.0, 48.0, 375.0], 'volume': [78.0, 347.0, 170.0, 367.0],
           'volume_icon': [56.0, 347.0, 78.0, 367.0], 'volume_wheel': [56.0, 347.0, 170.0, 367.0],
           'volume_bar': [84.0, 164.0],
           'voice': [440.0, 345.0, 522.0, 369.0],
           # the open list: four rows of 26 px of the six voices, the third (amy) current
           'menu': {'box': [450.0, 223.0, 522, 335], 'item_h': 26.0, 'rows': 4, 'pad': 4,
                    'names': ['en_GB-alan-medium', 'en_GB-jenny_dioco-medium', 'en_US-amy-medium',
                              'en_US-joe-medium', 'en_US-lessac-medium', 'en_US-ryan-high'],
                    'current': 2}}


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
        self.redirect(speech_mouse, LIST_SCROLL='list-scroll', CACHE='', VOICE_MENU='voice-menu',
                      CLOSE_CONFIRM='close-confirm')
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
        want = {'skip': 'skip', 'next': 'next', 'pause': 'toggle'}
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


class MuteTest(StubSpeechctl):
    """The speaker: the first click mutes, keeping the volume, and the next restores it."""

    def setUp(self):
        super().setUp()
        self.redirect(tray_model, SPEAK='speak')
        self.redirect(speech_mouse, VOLUME_BEFORE_MUTE='before-mute')
        os.makedirs(tray_model.SPEAK)

    def volume_is(self, level):
        with open(os.path.join(tray_model.SPEAK, 'settings.json'), 'w') as f:
            json.dump({'volume': level}, f)

    def click(self):
        speech_mouse.press(None, None, 'volume_icon')

    def test_a_click_mutes_and_the_next_restores_the_volume(self):
        self.volume_is(1.4)
        self.click()
        self.assertEqual(self.ran(), ['volume 0'])
        self.assertEqual(support.read(speech_mouse.VOLUME_BEFORE_MUTE), '1.4')
        self.volume_is(0)                               # speechctl has set it
        self.click()
        self.assertEqual(self.ran(), ['volume 0', 'volume 1.4'])
        self.assertFalse(os.path.exists(speech_mouse.VOLUME_BEFORE_MUTE))

    def test_the_level_is_kept_across_a_restart_while_muted(self):
        with open(speech_mouse.VOLUME_BEFORE_MUTE, 'w') as f:
            f.write('0.8')
        self.volume_is(0)
        self.click()                                    # a fresh process: only the file remembers
        self.assertEqual(self.ran(), ['volume 0.8'])

    def test_a_click_at_zero_with_nothing_kept_restores_the_default(self):
        self.volume_is(0)                               # the slider dragged to its left end
        self.click()
        self.assertEqual(self.ran(), [f'volume {tray_model.DEFAULT_VOLUME}'])
        self.assertFalse(os.path.exists(speech_mouse.VOLUME_BEFORE_MUTE))

    def test_muting_at_zero_does_not_overwrite_the_kept_level(self):
        with open(speech_mouse.VOLUME_BEFORE_MUTE, 'w') as f:
            f.write('1.6')
        self.volume_is(0)
        self.click()
        self.assertEqual(self.ran(), ['volume 1.6'])

    def test_the_slider_after_a_mute_follows_the_new_level_and_the_next_click_mutes_it(self):
        self.volume_is(1.4)
        self.click()
        self.volume_is(0.6)                             # dragged or wheeled up from the mute
        self.click()
        self.assertEqual(self.ran(), ['volume 0', 'volume 0'])
        self.assertEqual(support.read(speech_mouse.VOLUME_BEFORE_MUTE), '0.6')

    def test_the_stubbed_press_is_logged(self):
        self.volume_is(1.0)
        self.click()
        self.assertIn('speechctl volume 0', support.read(conky_mouse.LOG))


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

    def test_a_preview_a_killed_run_left_is_cleared_at_start(self):
        with open(speech_mouse.VOLUME_PREVIEW, 'w') as f:
            f.write('0.5000')
        speech_mouse.start()
        self.assertFalse(os.path.exists(speech_mouse.VOLUME_PREVIEW))

    def test_a_press_on_the_slider_sets_the_volume_and_the_speaker_mutes_it(self):
        x, y = centre(REGIONS['volume'])
        self.assertEqual(speech_mouse_region(x, y), 'volume')
        self.assertNotIn('volume', speech_mouse.BUTTONS)
        self.assertEqual(speech_mouse_region(64, 357), 'volume_icon')   # the speaker
        self.assertIn('volume_icon', speech_mouse.BUTTONS)              # pressed, not dragged
        with mock.patch.object(speech_mouse, 'set_volume') as set_volume:
            self.assertTrue(speech_mouse.pull_control('d', 'root', 'win', 1, REGIONS, 'volume',
                                                      'track', (x, y, (1000 + x, 500 + y)), False))
        set_volume.assert_called_once()


class VoiceMenuTest(StubSpeechctl):
    NAMES = REGIONS['menu']['names']

    def menu_at(self, y, scroll=0, x=480):
        return speech_mouse.menu_at(REGIONS['menu'], x, y, scroll)

    def show(self, *batches, now=None, menu=None):
        """run_menu over the batches of events one call each gives (then none), returning the
        pick and the VOICE_MENU contents it showed after each batch but the last."""
        batches, shown, calls = list(batches), [], []

        def events():
            calls.append(1)
            if len(calls) > 1:
                shown.append(support.read(speech_mouse.VOICE_MENU)
                             if os.path.exists(speech_mouse.VOICE_MENU) else None)
            return batches.pop(0) if batches else []
        clock = mock.Mock(side_effect=now) if now else mock.Mock(return_value=0.0)
        picked = speech_mouse.run_menu(menu or REGIONS['menu'], events, now=clock, sleep=lambda _: None)
        return picked, shown

    def test_the_voice_drop_down_is_a_control_and_not_a_button(self):
        x, y = centre(REGIONS['voice'])
        self.assertEqual(speech_mouse_region(x, y), 'voice')
        self.assertNotIn('voice', speech_mouse.BUTTONS)

    def test_a_row_is_found_by_where_it_is_and_the_scroll(self):
        # rows from y 227 (the box's top and its padding), 26 px each
        self.assertEqual([self.menu_at(228), self.menu_at(252), self.menu_at(253), self.menu_at(330)],
                         [0, 0, 1, 3])
        self.assertEqual(self.menu_at(228, scroll=2), 2)
        self.assertEqual(self.menu_at(330, scroll=2), 5)

    def test_off_the_rows_is_no_voice(self):
        self.assertIsNone(self.menu_at(225))                 # the padding above the first row
        self.assertIsNone(self.menu_at(332))                 # and below the fourth
        self.assertIsNone(self.menu_at(228, x=449))          # left of the list
        self.assertIsNone(self.menu_at(228, x=523))

    def test_with_fewer_voices_than_rows_only_the_voices_are_rows(self):
        menu = dict(REGIONS['menu'], names=self.NAMES[:2])
        self.assertEqual(speech_mouse.menu_at(menu, 480, 228, 0), 0)
        self.assertIsNone(speech_mouse.menu_at(menu, 480, 228 + 2 * 26, 0))

    def test_scrolling_stays_within_the_voices(self):
        menu = REGIONS['menu']
        self.assertEqual([speech_mouse.menu_scroll(menu, 0, -1), speech_mouse.menu_scroll(menu, 0, 1),
                          speech_mouse.menu_scroll(menu, 2, 1), speech_mouse.menu_scroll(menu, 2, 5)],
                         [0, 1, 2, 2])

    def test_a_press_on_a_voice_picks_it(self):
        picked, _ = self.show([('press', 480, 253)])
        self.assertEqual(picked, 'en_GB-jenny_dioco-medium')

    def test_a_press_anywhere_else_closes_it_without_a_pick(self):
        self.assertIsNone(self.show([('press', 300, 100)])[0])
        self.assertIsNone(self.show([('press', 480, 356)])[0])     # on the drop down itself

    def test_escape_closes_it(self):
        self.assertIsNone(self.show([('escape',), ('press', 480, 253)])[0])

    def test_it_shows_the_scroll_and_the_voice_under_the_pointer_until_it_closes(self):
        picked, shown = self.show([('move', 480, 253)], [('wheel', True)], [('move', 480, 280)],
                                 [('press', 480, 228)])
        # amy, the current voice, is in view without scrolling; the wheel then scrolls a voice
        self.assertEqual(shown, ['0 1', '1 2', '1 3'])
        self.assertEqual(picked, 'en_GB-jenny_dioco-medium')       # the second voice, once scrolled
        self.assertFalse(os.path.exists(speech_mouse.VOICE_MENU))

    def test_it_opens_with_a_current_voice_below_the_rows_in_view(self):
        _, shown = self.show([], [('escape',)], menu=dict(REGIONS['menu'], current=5))
        self.assertEqual(shown, ['2 -1'])                   # scrolled as far as it goes

    def test_a_swipe_scrolls_by_the_rows_it_gives(self):
        _, shown = self.show([('scroll', 1)], [('scroll', 5)], [('scroll', -1)], [('escape',)])
        self.assertEqual(shown, ['1 -1', '2 -1', '1 -1'])

    def test_a_wheel_step_moves_the_highlight_to_the_voice_now_under_the_pointer(self):
        _, shown = self.show([('move', 480, 253)], [('wheel', True)], [('wheel', True)], [('escape',)])
        self.assertEqual(shown, ['0 1', '1 2', '2 3'])

    def test_each_event_starts_the_timeout_again(self):
        # 20 s from the last event, not from opening: a wheel step at 15 s keeps it open at 30 s
        t, calls = [0.0], []

        def events():
            calls.append(t[0])
            t[0] = (15.0, 30.0, 34.0)[len(calls) - 1]
            return [[('wheel', True)], [], [('press', 480, 228)]][len(calls) - 1]
        picked = speech_mouse.run_menu(REGIONS['menu'], events, now=lambda: t[0], sleep=lambda _: None)
        self.assertEqual(picked, 'en_GB-jenny_dioco-medium')       # one voice scrolled, so the second

    def test_it_closes_itself_when_nothing_is_done(self):
        picked, _ = self.show(now=[0.0, 5.0, 10.0, 20.5])
        self.assertIsNone(picked)
        self.assertFalse(os.path.exists(speech_mouse.VOICE_MENU))

    def test_the_file_goes_however_it_ends(self):
        calls = []

        def events():
            calls.append(os.path.exists(speech_mouse.VOICE_MENU))
            if len(calls) > 1:
                raise RuntimeError('x')
            return [('move', 480, 228)]
        with self.assertRaises(RuntimeError):
            speech_mouse.run_menu(REGIONS['menu'], events, now=lambda: 0.0, sleep=lambda _: None)
        self.assertEqual(calls, [False, True])
        self.assertFalse(os.path.exists(speech_mouse.VOICE_MENU))

    def test_a_click_opens_the_list_and_a_drag_moves_the_widget(self):
        x, y = centre(REGIONS['voice'])
        for moved, opens in ((False, True), (True, False)):
            with self.subTest(moved=moved):
                steps = [(x + (40 if moved else 0), y, True), (x, y, False)]
                track = mock.Mock(side_effect=steps + [steps[-1]] * 50)
                with mock.patch.object(conky_mouse.time, 'sleep'), \
                        mock.patch.object(conky_mouse, 'drag', return_value=(0, 0, 1, 1)) as drag, \
                        mock.patch.object(conky_mouse, 'remember'), \
                        mock.patch.object(speech_mouse, 'open_menu') as open_menu:
                    self.assertTrue(speech_mouse.pull_control('d', 'root', 'win', 1, REGIONS, 'voice',
                                                              track, (x, y, (x, y)), False))
                self.assertEqual((open_menu.called, drag.called), (opens, not opens))

    def open(self, picked, regions=REGIONS):
        with mock.patch.object(speech_mouse, 'declare'), \
                mock.patch.object(speech_mouse, 'grab', return_value=(True, False)) as grab, \
                mock.patch.object(speech_mouse, 'ungrab') as ungrab, \
                mock.patch.object(speech_mouse, 'x_events'), \
                mock.patch.object(speech_mouse, 'run_menu', return_value=picked), \
                mock.patch.object(conky_mouse, 'touch_opcode', return_value=None):
            speech_mouse.open_menu('d', 'win', 1, regions)
        return grab, ungrab

    def test_a_voice_picked_is_set_through_speechctl_and_logged(self):
        grab, ungrab = self.open('en_US-joe-medium')
        self.assertEqual(self.ran(), ['voice en_US-joe-medium'])
        self.assertIn('speechctl voice en_US-joe-medium', support.read(conky_mouse.LOG))
        self.assertTrue(grab.called and ungrab.called)

    def test_picking_the_current_voice_or_nothing_sets_nothing(self):
        self.open('en_US-amy-medium')
        self.open(None)
        self.assertEqual(self.ran(), [])
        self.assertIn('keyboard not held', support.read(conky_mouse.LOG))

    def test_without_voices_there_is_no_list_to_open(self):
        grab, _ = self.open('en_US-joe-medium', regions={k: v for k, v in REGIONS.items() if k != 'menu'})
        self.assertFalse(grab.called)
        self.assertEqual(self.ran(), [])

    def test_a_list_a_killed_run_left_is_cleared_at_start(self):
        with open(speech_mouse.VOICE_MENU, 'w') as f:
            f.write('0 -1')
        speech_mouse.start()
        self.assertFalse(os.path.exists(speech_mouse.VOICE_MENU))


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


ISSUE = 'https://github.com/o/r/issues/123'
ISSUE2 = 'https://github.com/o/r/issues/131'
PR = 'https://github.com/o/r/pull/'


class LinksTest(StubSpeechctl):
    """A click on an issue number under a session's repository name opens that issue, one on its
    pill its ready pull requests, and one on its name asks to close it; with nothing to open,
    the issue numbers and the pill are not click areas."""

    def setUp(self):
        super().setUp()
        rows = [dict(r) for r in REGIONS['rows']]
        # two issue numbers, the first on the block's first line and the second on its next
        rows[0].update(issues=[[25.0, 5.0, 60.0, 19.0, ISSUE], [25.0, 29.0, 60.0, 43.0, ISSUE2]],
                       name=[96.0, 200.0], link=[200.0, 260.0], branch='feat/issue-123-x',
                       prs=[PR + '151', PR + '152'])
        rows[1].update(name=[96.0, 180.0])
        self.regions = dict(REGIONS, rows=rows)
        self.opened = []
        speech_mouse.opened.clear()
        speech_mouse.opening.clear()

    def gh(self, states):
        """A gh that answers `gh pr view <link>` with states[link]: (state, labels)."""
        def run(args, **kwargs):
            state, labels, *head = states.get(args[3], ('MERGED', []))
            out = json.dumps({'state': state, 'labels': [{'name': n} for n in labels],
                              'headRefName': head[0] if head else 'feat/issue-123-x'})
            return subprocess.CompletedProcess(args, 0, out, '')
        return run

    def open(self, row, states, kind='prs'):
        speech_mouse.open_links(row, kind, run=self.gh(states),
                                popen=lambda args, **kw: self.opened.append(args[1:]) or mock.Mock())
        return self.opened.pop() if self.opened else None

    def test_ready_pull_requests_open_and_the_rest_do_not(self):
        row = self.regions['rows'][0]
        ready = ('OPEN', ['Manual Review Needed'])
        self.assertEqual(self.open(row, {PR + '151': ready, PR + '152': ready}), [PR + '151', PR + '152'])
        self.assertEqual(self.open(row, {PR + '151': ready, PR + '152': ('OPEN', [])}), [PR + '151'])

    def test_another_sessions_pull_request_in_the_ledger_is_not_opened(self):
        ready = ('OPEN', ['Manual Review Needed'])
        blocker = ('OPEN', ['Manual Review Needed'], 'fix/issue-140-other')
        self.assertEqual(self.open(self.regions['rows'][0], {PR + '151': blocker, PR + '152': ready}),
                         [PR + '152'])
        self.assertIsNone(self.open(self.regions['rows'][0], {PR + '151': blocker}))

    def test_with_none_ready_the_pill_opens_nothing_and_not_the_issue(self):
        self.assertIsNone(self.open(self.regions['rows'][0], {}))
        self.assertIn('aaaa: no ready pull request to open', support.read(conky_mouse.LOG))

    def test_an_issue_number_opens_its_issue(self):
        self.assertEqual(self.open(dict(self.regions['rows'][0], issue=ISSUE2), {}, 'issue'), [ISSUE2])

    def test_each_issue_number_is_a_link_on_any_line_and_the_name_and_pill_only_on_the_first(self):
        at = lambda x, y: (lambda hit: hit and (hit[0]['id'], hit[0].get('issue'), hit[1]))(
            speech_mouse.link_at(self.regions, 1, x, y))
        self.assertEqual(at(50, 106), ('aaaa', ISSUE, 'issue'))
        self.assertEqual(at(50, 130), ('aaaa', ISSUE2, 'issue'))  # the next line of the block
        self.assertEqual(at(150, 106), ('aaaa', None, 'close'))   # the name
        self.assertEqual(at(230, 106), ('aaaa', None, 'prs'))     # the pill, where the name's span ends
        self.assertIsNone(at(50, 122))                          # between the two issue numbers
        self.assertIsNone(at(80, 106))                          # between the issue numbers and the name
        self.assertIsNone(at(270, 106))                         # past the pill
        self.assertIsNone(at(150, 130))                         # the name's second line
        self.assertIsNone(at(50, 154 - 12))                     # a session without issues
        self.assertEqual(at(120, 154 - 12), ('bbbb', None, 'close'))   # a name without pull requests
        self.assertIsNone(at(200, 154 - 12))                    # and no pill after it
        self.assertIsNone(at(425, 106))                         # the setting

    def test_a_click_on_a_link_opens_it_and_the_setting_keeps_its_own(self):
        opened = []
        thread = lambda target, args, daemon: mock.Mock(start=lambda: target(*args))
        with mock.patch.object(speech_mouse.threading, 'Thread', side_effect=thread), \
                mock.patch.object(speech_mouse, 'open_links', side_effect=lambda r, k: opened.append((r['id'], k))):
            for x in (50, 200, 425):
                track = mock.Mock(return_value=(x, 106, False))
                hit = speech_mouse.pull_control(None, None, None, 1, self.regions, None, track,
                                                (x, 106, (x, 106)), False)
                self.assertTrue(hit)
            track = mock.Mock(return_value=(50, 142, False))
            self.assertFalse(speech_mouse.pull_control(None, None, None, 1, self.regions, None, track,
                                                       (50, 142, (50, 142)), False))    # a box without an issue
        self.assertEqual(opened, [('aaaa', 'issue'), ('aaaa', 'prs')])
        self.assertEqual(self.ran(), ['speech aaaa on'])

    def test_a_click_on_the_name_asks_to_close_it_and_opens_nothing(self):
        closed = []
        with mock.patch.object(speech_mouse, 'close_session', side_effect=lambda *a: closed.append(a[4]['id'])), \
                mock.patch.object(speech_mouse, 'open_once') as open_once:
            track = mock.Mock(return_value=(150, 106, False))
            self.assertTrue(speech_mouse.pull_control('d', 'root', 'win', 1, self.regions, None, track,
                                                      (150, 106, (150, 106)), False))
        self.assertEqual((closed, open_once.called), (['aaaa'], False))

    def test_a_second_click_soon_after_or_while_it_opens_does_nothing(self):
        started, clock = [], mock.Mock()
        with mock.patch.object(speech_mouse.threading, 'Thread',
                               side_effect=lambda **kw: mock.Mock(start=lambda: started.append(kw))):
            for t in (100.0, 100.3, 103.5):            # the first still opening at 103.5
                clock.return_value = t
                speech_mouse.open_once(self.regions['rows'][0], 'prs', now=clock)
            speech_mouse.open_once(self.regions['rows'][0], 'issue', now=clock)   # the box: its own
            speech_mouse.opening.clear()               # they have opened
            speech_mouse.open_once(self.regions['rows'][0], 'prs', now=clock)
        self.assertEqual(len(started), 3)

    def test_a_second_issue_number_opens_while_the_first_is_a_double_click_away(self):
        started, clock = [], mock.Mock(return_value=100.0)
        first, second = (dict(self.regions['rows'][0], issue=i) for i in (ISSUE, ISSUE2))
        with mock.patch.object(speech_mouse.threading, 'Thread',
                               side_effect=lambda **kw: mock.Mock(start=lambda: started.append(kw))):
            speech_mouse.open_once(first, 'issue', now=clock)
            speech_mouse.open_once(first, 'issue', now=clock)       # the same number again: a double click
            speech_mouse.open_once(second, 'issue', now=clock)      # another number of the same session
        self.assertEqual([kw['args'][0]['issue'] for kw in started], [ISSUE, ISSUE2])

    def test_a_pull_request_gh_cannot_read_is_not_opened(self):
        def fails(args, **kwargs):
            raise FileNotFoundError('gh')
        speech_mouse.open_links(self.regions['rows'][0], 'prs', run=fails,
                                popen=lambda args, **kw: self.opened.append(args[1:]) or mock.Mock())
        self.assertEqual(self.opened, [])
        self.assertIn('gh could not read it', support.read(conky_mouse.LOG))

    def test_without_a_branch_no_pull_request_is_its_own(self):
        ready = ('OPEN', ['Manual Review Needed'])
        row = dict(self.regions['rows'][0], branch='')
        self.assertIsNone(self.open(row, {PR + '151': ready}))

    def test_without_chrome_each_link_goes_to_xdg_open(self):
        def popen(args, **kwargs):
            if args[0] == speech_mouse.BROWSER:
                raise FileNotFoundError(args[0])
            self.opened.append(args)
            return mock.Mock()
        ready = ('OPEN', ['Manual Review Needed'])
        speech_mouse.open_links(self.regions['rows'][0], 'prs', run=self.gh({PR + '151': ready, PR + '152': ready}),
                                popen=popen)
        self.assertEqual(self.opened, [['xdg-open', PR + '151'], ['xdg-open', PR + '152']])

    def test_a_finger_dragged_from_a_name_moves_the_widget_unless_the_list_scrolls(self):
        regions = dict(self.regions, list_scroll=[0, 24.0])
        steps = [(240, 106, True), (200, 106, False)]
        for regions, swiped in ((regions, False), (self.regions, True)):
            track = mock.Mock(side_effect=steps + [steps[-1]] * 50)
            with mock.patch.object(conky_mouse.time, 'sleep'), \
                    mock.patch.object(conky_mouse, 'drag', return_value=(0, 0, 1, 1)) as drag, \
                    mock.patch.object(conky_mouse, 'remember'), \
                    mock.patch.object(speech_mouse, 'swipe') as swipe:
                speech_mouse.pull_control(None, None, None, 1, regions, None, track,
                                          (200, 106, (200, 106)), True)
            self.assertEqual((swipe.called, drag.called), (swiped, not swiped))


PROMPT = {'box': [109.0, 235.0, 429.0, 339.0], 'ok': [365.0, 299.0, 415.0, 325.0],
          'cancel': [284.0, 299.0, 357.0, 325.0]}
ROW = {'id': 'aaaa', 'pid': 4242, 'title': 'Widget Close Session', 'busy': True}


class CloseTest(StubSpeechctl):
    """The prompt a click on a session's name opens, and the end of the session OK confirms."""
    OK, CANCEL, ELSEWHERE = (390, 312), (320, 312), (200, 400)

    def show(self, *steps, timeout=False):
        """run_confirm over the (seconds passed, events) of each call to events() (then none),
        returning whether OK was pressed and the CLOSE_CONFIRM contents after each call."""
        steps, shown, clock = list(steps), [], {'t': 0.0}

        def events():
            if os.path.exists(speech_mouse.CLOSE_CONFIRM):
                shown.append(support.read(speech_mouse.CLOSE_CONFIRM))
            dt, batch = steps.pop(0) if steps else (speech_mouse.MENU_TIMEOUT + 1 if timeout else 0.0, [])
            clock['t'] += dt
            return batch
        return speech_mouse.run_confirm(PROMPT, ROW, events, now=lambda: clock['t'],
                                        sleep=lambda _: None), shown

    def test_the_buttons_are_found_by_where_they_are(self):
        self.assertEqual([speech_mouse.prompt_at(PROMPT, *xy) for xy in (self.OK, self.CANCEL, self.ELSEWHERE)],
                         ['ok', 'cancel', None])

    def test_a_press_on_ok_answers_yes_and_anything_else_no(self):
        for xy, answer in ((self.OK, True), (self.CANCEL, False), (self.ELSEWHERE, False), ((300, 250), False)):
            with self.subTest(xy=xy):
                self.assertEqual(self.show((1.0, [('press', *xy)]))[0], answer)

    def test_escape_and_the_timeout_answer_no(self):
        self.assertFalse(self.show((1.0, [('escape',), ('press', *self.OK)]))[0])
        self.assertFalse(self.show(timeout=True)[0])

    def test_a_press_just_after_it_opens_answers_nothing(self):
        # the second click of a double click on the name
        answer, _ = self.show((0.1, [('press', *self.OK)]), (0.1, [('press', *self.OK)]),
                              (speech_mouse.CONFIRM_ARMED, [('press', *self.CANCEL)]))
        self.assertFalse(answer)
        answer, _ = self.show((0.1, [('press', *self.OK)]), (speech_mouse.CONFIRM_ARMED, [('press', *self.OK)]))
        self.assertTrue(answer)

    def test_it_shows_the_session_and_the_button_under_the_pointer_until_it_closes(self):
        answer, shown = self.show((0.1, [('move', *self.CANCEL)]), (0.1, [('move', *self.OK)]),
                                  (0.1, [('move', *self.ELSEWHERE)]), (1.0, [('press', *self.OK)]))
        self.assertEqual(shown, ['0 1\nWidget Close Session', '2 1\nWidget Close Session',
                                 '1 1\nWidget Close Session', '0 1\nWidget Close Session'])
        self.assertTrue(answer)                                 # the press carries its own place
        self.assertFalse(os.path.exists(speech_mouse.CLOSE_CONFIRM))

    def test_the_file_goes_however_it_ends(self):
        def events():
            raise RuntimeError('x')
        with self.assertRaises(RuntimeError):
            speech_mouse.run_confirm(PROMPT, ROW, events, now=lambda: 0.0, sleep=lambda _: None)
        self.assertFalse(os.path.exists(speech_mouse.CLOSE_CONFIRM))

    def test_a_prompt_a_killed_run_left_is_cleared_at_start(self):
        speech_mouse.write_confirm(ROW, None)
        speech_mouse.start()
        self.assertFalse(os.path.exists(speech_mouse.CLOSE_CONFIRM))

    def sessions(self, sid='aaaa', pid=4242, running=True, started=8594608):
        """A sessions folder with Claude Code's file for pid 4242, which says the process started
        at tick 8594608, and a /proc whose pid 4242 started at tick `started`."""
        shutil.rmtree(os.path.join(self.dir, 'proc'), ignore_errors=True)
        os.makedirs(os.path.join(self.dir, 'sessions'), exist_ok=True)
        os.makedirs(os.path.join(self.dir, 'proc', '4242' if running else '1'), exist_ok=True)
        # as the kernel writes it: the name in brackets can hold spaces and brackets
        stat = f'4242 (claude (x) y) S 1 4242 4242 0 -1 4194560 100 0 0 0 1 1 0 0 20 0 9 0 {started} 1000 100 '
        with open(os.path.join(self.dir, 'proc', '4242' if running else '1', 'stat'), 'w') as f:
            f.write(stat)
        with open(os.path.join(self.dir, 'sessions', '4242.json'), 'w') as f:
            json.dump({'pid': pid, 'sessionId': sid, 'procStart': '8594608'}, f)
        return dict(sessions_dir=os.path.join(self.dir, 'sessions'), proc_dir=os.path.join(self.dir, 'proc'))

    def test_the_session_is_sent_sigterm(self):
        kill = mock.Mock()
        self.assertTrue(speech_mouse.end_session(ROW, kill=kill, **self.sessions()))
        kill.assert_called_once_with(4242, speech_mouse.signal.SIGTERM)
        self.assertIn('SIGTERM to session aaaa (Widget Close Session) pid 4242', support.read(conky_mouse.LOG))

    def test_a_pid_that_is_no_longer_that_session_is_not_signalled(self):
        for name, setup in (('another session', dict(sid='cccc')), ('not running', dict(running=False)),
                            ('another pid', dict(pid=1)), ('a process that started later', dict(started=9000000))):
            with self.subTest(name):
                kill = mock.Mock()
                self.assertFalse(speech_mouse.end_session(ROW, kill=kill, **self.sessions(**setup)))
                self.assertFalse(kill.called)
        kill = mock.Mock()
        self.assertFalse(speech_mouse.end_session(ROW, kill=kill, sessions_dir=os.path.join(self.dir, 'none'),
                                                  proc_dir=os.path.join(self.dir, 'proc')))
        self.assertFalse(speech_mouse.end_session(dict(ROW, id=''), kill=kill, **self.sessions()))
        self.assertFalse(kill.called)
        self.assertIn('close: session aaaa is no longer running as pid 4242', support.read(conky_mouse.LOG))

    def test_the_start_time_is_read_past_a_name_with_spaces_and_brackets(self):
        folders = self.sessions(started=777)
        self.assertEqual(speech_mouse.proc_start(4242, folders['proc_dir']), '777')

    def test_a_file_without_a_start_time_signals_nothing(self):
        folders = self.sessions()
        with open(os.path.join(folders['sessions_dir'], '4242.json'), 'w') as f:
            json.dump({'pid': 4242, 'sessionId': 'aaaa'}, f)
        kill = mock.Mock()
        self.assertFalse(speech_mouse.end_session(ROW, kill=kill, **folders))
        self.assertFalse(kill.called)

    def test_a_signal_that_fails_is_logged(self):
        kill = mock.Mock(side_effect=PermissionError('denied'))
        self.assertFalse(speech_mouse.end_session(ROW, kill=kill, **self.sessions()))
        self.assertIn('close: session aaaa pid 4242: denied', support.read(conky_mouse.LOG))

    def close(self, answer, regions=None):
        regions = dict(REGIONS, confirm=PROMPT) if regions is None else regions
        with mock.patch.object(speech_mouse, 'declare'), \
                mock.patch.object(speech_mouse, 'grab', return_value=(True, True)), \
                mock.patch.object(speech_mouse, 'ungrab') as ungrab, \
                mock.patch.object(speech_mouse, 'x_events'), \
                mock.patch.object(speech_mouse, 'run_confirm', return_value=answer), \
                mock.patch.object(speech_mouse, 'end_session') as end, \
                mock.patch.object(conky_mouse, 'touch_opcode', return_value=None):
            speech_mouse.close_session('d', 'win', 1, regions, ROW)
        return end, ungrab

    def test_only_a_confirmed_prompt_ends_the_session_and_the_grab_is_always_let_go(self):
        for answer in (True, False):
            with self.subTest(answer=answer):
                end, ungrab = self.close(answer)
                self.assertEqual((end.called, ungrab.called), (answer, True))
        self.assertIn('close prompt: OK', support.read(conky_mouse.LOG))
        self.assertIn('close prompt: not confirmed', support.read(conky_mouse.LOG))

    def test_without_a_prompt_in_the_regions_nothing_opens(self):
        end, ungrab = self.close(True, regions=dict(REGIONS))
        self.assertEqual((end.called, ungrab.called), (False, False))


class WheelTest(StubSpeechctl):
    def wheel(self, name_or_xy, down, s=1):
        x, y = centre(REGIONS[name_or_xy]) if isinstance(name_or_xy, str) else name_or_xy
        return speech_mouse.wheel(REGIONS, s, x * s, y * s, down)

    def test_over_the_volume_and_the_voice(self):
        self.assertEqual([self.wheel('volume', True), self.wheel((64, 357), False),
                          self.wheel('voice', True), self.wheel((450, 357), False)],
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
