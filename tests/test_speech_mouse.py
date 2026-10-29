"""The speech widget's controls (src/speech/mouse.py): which speechctl command a click, tap or
wheel step on each region runs, checked against a stub speechctl that records its arguments,
the gear that opens the settings menu, and the wheel and swipes that scroll the session list."""
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
VOICES = ['', 'en_GB-alan-medium', 'en_GB-jenny_dioco-medium', 'en_US-amy-medium', 'en_US-joe-medium',
          'en_US-ryan-high']
REGIONS = {'minimize': [484.0, 16.0, 506.0, 38.0], 'close': [506.0, 16.0, 540.0, 38.0],
           'skip': [429.0, 14.0, 455.0, 40.0], 'next': [455.0, 14.0, 481.0, 40.0],
           'list': [16, 94.0, 522, 238.0], 'list_scroll': [1, 24.0],
           'terminal': [16.0, 250.0, 522, 338.0], 'terminal_scroll': 4,
           # a session's name line, the line under it of its tag and pill, its issue numbers, and
           # with speech on its last line read: four rows for the first, two for the second
           'rows': [{'id': 'aaaa', 'speech': 'on', 'voice': '', 'top': 0.0, 'bottom': 96.0, 'head': 0.0,
                     'title': 'One'},
                    {'id': 'bbbb', 'speech': 'alerts', 'voice': 'en_US-amy-medium', 'top': 96.0, 'bottom': 144.0,
                     'head': 0.0, 'title': 'Two'}],
           'pause': [12.0, 339.0, 48.0, 375.0], 'volume': [78.0, 347.0, 170.0, 367.0],
           'volume_icon': [56.0, 347.0, 78.0, 367.0], 'volume_wheel': [56.0, 347.0, 170.0, 367.0],
           'volume_bar': [84.0, 164.0], 'gear': [500.0, 339.0, 522.0, 375.0],
           # the settings menu: the card's width from under the header, a title line, then rows of
           # 20 px from y 100 with room for five, and the global voice, as it lists them
           'menu': {'box': [16, 50.0, 522, 380.0], 'title': [60.0, 80.0], 'first': 100.0, 'row': 20.0,
                    'visible': 5, 'voices': VOICES[1:]}}


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
        self.redirect(speech_mouse, LIST_SCROLL='list-scroll', TERMINAL_SCROLL='terminal-scroll', CACHE='',
                      SETTINGS_MENU='settings-menu', CLOSE_CONFIRM='close-confirm', SPEAK='speak',
                      TERMINAL_LINKS='terminal-links')
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
        self.assertIn('gear', speech_mouse.BUTTONS)
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


class FakeSettings:
    """menu.Settings without the machine: what it holds, and what was set."""

    def __init__(self):
        self.voice_name, self.pace_value, self.scale_value = 'en_US-amy-medium', 0.85, 1.0
        self.collapsed, self.top, self.log = False, True, []

    def voice(self): return self.voice_name
    def pace(self): return self.pace_value
    def scale(self): return self.scale_value
    def collapse(self): return self.collapsed
    def on_top(self): return self.top
    def set_voice(self, name): self.voice_name = name; self.log.append(('voice', name))
    def set_pace(self, pace): self.pace_value = pace; self.log.append(('pace', pace))
    def set_scale(self, scale): self.scale_value = scale; self.log.append(('scale', scale))
    def set_collapse(self, on): self.collapsed = on; self.log.append(('collapse', on))
    def set_on_top(self, on): self.top = on; self.log.append(('on top', on))
    def reset_size(self): self.log.append(('reset',))
    def set_session_voice(self, sid, name): self.log.append(('session voice', sid, name))
    def set_session_speech(self, sid, value): self.log.append(('session speech', sid, value))


class SettingsMenuTest(StubSpeechctl):
    """run_menu: the cursor, the keys and the pointer, over speech_mouse's menu.Menu."""

    def model(self):
        self.settings = FakeSettings()
        return speech_mouse.menu.Menu(REGIONS['rows'], VOICES[1:], self.settings)

    def show(self, *steps, model=None, timeout=False):
        """run_menu over the (seconds passed, events) of each call to events() (then none),
        returning the model and the SETTINGS_MENU contents it showed at each call."""
        steps, shown, clock = list(steps), [], {'t': 0.0}
        model = model or self.model()

        def events():
            if os.path.exists(speech_mouse.SETTINGS_MENU):
                shown.append(support.read(speech_mouse.SETTINGS_MENU))
            dt, batch = steps.pop(0) if steps else (speech_mouse.MENU_TIMEOUT + 1 if timeout else 0.0, [])
            clock['t'] += dt
            return batch
        speech_mouse.run_menu(model, lambda: REGIONS, events, now=lambda: clock['t'], sleep=lambda _: None)
        return model, shown

    def test_what_is_under_the_pointer_is_found_by_where_it_is(self):
        menu = REGIONS['menu']
        hit = lambda x, y, scroll=0, count=7: speech_mouse.menu_hit(menu, scroll, count, x, y)
        self.assertEqual([hit(100, 105), hit(100, 125), hit(100, 190)], [('row', 0), ('row', 1), ('row', 4)])
        self.assertEqual(hit(100, 105, scroll=2), ('row', 2))
        self.assertEqual(hit(100, 70), ('title',))
        self.assertEqual(hit(100, 205), ('panel',))                    # under the fifth row: the panel
        self.assertEqual(hit(100, 125, count=1), ('panel',))           # a row the page does not have
        self.assertIsNone(hit(10, 105))
        self.assertIsNone(hit(100, 400))

    def test_the_keys_move_the_cursor_and_enter_turns_a_setting(self):
        model, shown = self.show((1.0, [('key', 'down'), ('key', 'enter')]),       # Pace: the next preset
                                 (0.1, [('key', 'down'), ('key', 'space')]),       # Text scaling
                                 (0.1, [('key', 'down'), ('key', 'enter')]),       # Collapse when idle
                                 (0.1, [('key', 'down'), ('key', 'enter')]),       # Always on top
                                 (0.1, [('key', 'down'), ('key', 'enter')]),       # Reset widget size
                                 (0.1, [('key', 'up'), ('escape',)]))
        self.assertEqual(self.settings.log,
                         [('pace', 1.0), ('scale', 1.25), ('collapse', True), ('on top', False), ('reset',)])
        self.assertEqual(model.selected, 4)
        self.assertFalse(os.path.exists(speech_mouse.SETTINGS_MENU))

    def test_it_shows_the_cursor_the_page_and_its_rows_until_it_closes(self):
        _, shown = self.show((1.0, [('key', 'down')]), (0.1, [('escape',)]))
        head, title, *rows = shown[-1].split('\n')
        self.assertEqual((head, title), ('1 0', 'Settings'))
        self.assertEqual(rows[0], 'Default voice\tamy \u203a\t')
        self.assertIn('Collapse when idle\tfalse\t', rows)
        self.assertIn('Sessions\t2 \u203a\t', rows)

    def test_a_press_on_a_row_changes_it_and_one_on_the_title_goes_back(self):
        model, _ = self.show((1.0, [('press', 100, 165)]),                         # Collapse when idle
                             (0.1, [('press', 100, 105)]),                         # Default voice: its page
                             (0.1, [('press', 100, 125)]),                         # the second voice, back at the first page
                             (0.1, [('press', 100, 190)]),                         # Always on top
                             (0.1, [('wheel', 1)] * 6 + [('key', 'enter')]),   # Sessions: its page
                             (0.1, [('press', 100, 70)]),                          # the title: back
                             (0.1, [('escape',)]))
        self.assertEqual(self.settings.log, [('collapse', True), ('voice', 'en_GB-jenny_dioco-medium'), ('on top', False)])
        self.assertEqual(model.page, ('root', None))
        self.assertEqual(model.selected, 6)                                         # the cursor is back on the row that opened it

    def test_the_pointer_selects_the_row_under_it(self):
        model, _ = self.show((1.0, [('move', 100, 145)]), (0.1, [('escape',)]))
        self.assertEqual(model.selected, 2)
        model, _ = self.show((1.0, [('move', 100, 70)]), (0.1, [('escape',)]))      # the title is no row
        self.assertEqual(model.selected, 0)

    def test_a_session_has_its_speech_and_its_voice_on_a_page_of_its_own(self):
        model, shown = self.show((1.0, [('key', 'down')] * 6 + [('key', 'enter')]),         # Sessions
                                 (0.1, [('key', 'down'), ('key', 'enter')]),                # Two
                                 (0.1, [('key', 'enter')]),                                 # Speech: Alerts -> Off
                                 (0.1, [('key', 'down'), ('key', 'right')]),                # Voice: its page
                                 (0.1, [('key', 'down'), ('key', 'enter')]),                # the cursor starts on its voice, amy: the next
                                 (0.1, [('escape',)]))
        self.assertEqual(self.settings.log, [('session speech', 'bbbb', 'off'),
                                             ('session voice', 'bbbb', 'en_US-joe-medium')])
        self.assertEqual(model.page, ('session', 1))
        self.assertTrue(any(t.split('\n')[1] == 'Settings \u203a Sessions \u203a Two' for t in shown))

    def test_left_and_right_turn_a_value_and_never_close_the_menu(self):
        model, _ = self.show((1.0, [('key', 'down'), ('key', 'left')]),             # Pace: the one before
                             (0.1, [('key', 'down'), ('key', 'right')]),            # Text scaling: the next
                             (0.1, [('key', 'up'), ('key', 'up'), ('key', 'left')]),   # Default voice: nothing to turn, first page
                             (0.1, [('key', 'down'), ('key', 'down'), ('key', 'down'), ('key', 'left')]),  # Collapse: false -> true
                             (0.1, [('escape',)]))
        self.assertEqual(self.settings.log, [('pace', 0.7), ('scale', 1.25), ('collapse', True)])
        self.assertEqual(model.page, ('root', None))

    def test_right_opens_a_page_and_left_and_backspace_go_back_without_closing_at_the_first(self):
        model, _ = self.show((1.0, [('key', 'right')]), (0.1, [('key', 'left')]), (0.1, [('key', 'right')]),
                             (0.1, [('key', 'backspace')]), (0.1, [('key', 'backspace')]), (0.1, [('key', 'left')]),
                             (0.1, [('escape',)]))
        self.assertEqual(model.page, ('root', None))
        self.assertEqual(model.selected, 0)

    def test_the_wheel_moves_the_cursor_and_the_rows_scroll_with_it(self):
        model, shown = self.show((1.0, [('wheel', 1)] * 6), (0.1, [('escape',)]))
        self.assertEqual((model.selected, model.top), (6, 2))                        # five rows show
        self.assertEqual(shown[-1].split('\n')[0], '6 2')

    def test_a_press_just_after_it_opens_answers_nothing(self):
        # the second click of a double click on the gear
        self.show((0.1, [('press', 100, 165)]), (speech_mouse.CONFIRM_ARMED, [('press', 100, 165)]),
                  (0.1, [('escape',)]))
        self.assertEqual(self.settings.log, [('collapse', True)])

    def test_the_timeout_closes_it_and_each_event_starts_it_again(self):
        self.show(timeout=True)
        self.assertFalse(os.path.exists(speech_mouse.SETTINGS_MENU))
        model, _ = self.show((15.0, [('move', 100, 125)]), (15.0, []), (4.0, [('key', 'down')]), (0.1, [('escape',)]))
        self.assertEqual(model.selected, 2)                      # still open at 34 s: 15 s after the move

    def test_it_closes_when_the_card_no_longer_has_a_menu(self):
        speech_mouse.run_menu(self.model(), lambda: {}, lambda: [], now=lambda: 0.0, sleep=lambda _: None)

    def test_the_file_goes_however_it_ends(self):
        def events():
            raise RuntimeError('x')
        with self.assertRaises(RuntimeError):
            speech_mouse.run_menu(self.model(), lambda: REGIONS, events, now=lambda: 0.0, sleep=lambda _: None)
        self.assertFalse(os.path.exists(speech_mouse.SETTINGS_MENU))

    def test_a_menu_a_killed_run_left_is_cleared_at_start(self):
        speech_mouse.write_menu(self.model(), 5)
        speech_mouse.start()
        self.assertFalse(os.path.exists(speech_mouse.SETTINGS_MENU))


class SessionVoiceTest(StubSpeechctl):
    def path(self, sid='aaaa'):
        return os.path.join(speech_mouse.SPEAK, sid + '.voice')

    def test_a_voice_is_kept_in_the_sessions_file_and_the_global_one_removes_it(self):
        speech_mouse.set_session_voice('aaaa', 'en_US-joe-medium')
        self.assertEqual(support.read(self.path()), 'en_US-joe-medium')
        speech_mouse.set_session_voice('aaaa', 'en_US-amy-medium')
        self.assertEqual(support.read(self.path()), 'en_US-amy-medium')
        speech_mouse.set_session_voice('aaaa', '')
        self.assertFalse(os.path.exists(self.path()))
        speech_mouse.set_session_voice('aaaa', '')                  # already the global one: nothing to say
        self.assertNotIn('voice for aaaa', support.read(conky_mouse.LOG) if os.path.exists(conky_mouse.LOG) else '')

    def test_another_sessions_file_is_left_alone(self):
        speech_mouse.set_session_voice('aaaa', 'en_US-joe-medium')
        speech_mouse.set_session_voice('bbbb', '')
        self.assertTrue(os.path.exists(self.path()))

    def test_an_id_that_is_a_path_writes_nothing(self):
        for sid in ('', '../x', 'a/b'):
            speech_mouse.set_session_voice(sid, 'en_US-joe-medium')
        self.assertFalse(os.path.exists(speech_mouse.SPEAK))

    def test_a_session_speech_choice_runs_speechctl(self):
        speech_mouse.set_session_speech('aaaa', 'off')
        self.assertEqual(self.ran(), ['speech aaaa off'])

    def open(self, regions=REGIONS):
        with mock.patch.object(speech_mouse, 'declare'), \
                mock.patch.object(speech_mouse, 'grab', return_value=(True, False)) as grab, \
                mock.patch.object(speech_mouse, 'ungrab') as ungrab, \
                mock.patch.object(speech_mouse, 'focus_window', return_value=(True, False)) as focus, \
                mock.patch.object(speech_mouse, 'set_accepts_input') as accepts, \
                mock.patch.object(speech_mouse, 'x_events'), \
                mock.patch.object(speech_mouse, 'run_menu') as run, \
                mock.patch.object(conky_mouse, 'touch_opcode', return_value=None):
            speech_mouse.open_menu('d', 'win', 1, regions)
        self.focus, self.accepts = focus, accepts
        return grab, ungrab, run

    def test_opening_holds_the_pointer_and_always_lets_it_go(self):
        grab, ungrab, run = self.open()
        self.assertTrue(grab.called and ungrab.called and run.called)
        self.assertIn('keyboard not held, focus taken', support.read(conky_mouse.LOG))
        self.focus.assert_called_once_with('d', 'win')                 # the focus conky's window never accepts
        self.accepts.assert_called_once_with('d', 'win', False)        # and given back as it was
        model = run.call_args.args[0]
        self.assertEqual([x['id'] for x in model.sessions], ['aaaa', 'bbbb'])
        self.assertEqual(model.voices, VOICES[1:])

    def test_without_a_menu_in_the_regions_nothing_opens(self):
        grab, ungrab, run = self.open({k: v for k, v in REGIONS.items() if k != 'menu'})
        self.assertFalse(grab.called or run.called)

    def test_focus_is_asked_for_from_the_window_manager_and_taken(self):
        x11 = conky_mouse.x11
        x11.reset_mock()
        x11.XDefaultRootWindow.return_value = 77
        speech_mouse.focus_window('d', 555, sleep=lambda _: None)
        names = [c[0] for c in x11.method_calls]
        self.assertLess(names.index('XSetWMHints'), names.index('XSendEvent'))   # accept input first
        self.assertLess(names.index('XSendEvent'), names.index('XSetInputFocus'))
        self.assertEqual(x11.XSendEvent.call_args.args[1], 77)                   # to the root window, as a pager does
        self.assertEqual(x11.XSetInputFocus.call_args.args[1], 555)

    def test_the_gear_opens_the_menu(self):
        with mock.patch.object(speech_mouse, 'open_menu') as opened, \
                mock.patch.object(conky_mouse, 'scale', return_value=2), \
                mock.patch.object(conky_mouse, 'load_regions', return_value=REGIONS):
            speech_mouse.press('d', 'win', 'gear')
        opened.assert_called_once_with('d', 'win', 2, REGIONS)


def speech_mouse_region(x, y, s=1):
    """The button region_at would find, looking through the speech widget's regions."""
    for name in speech_mouse.REGIONS_ORDER:
        r = REGIONS.get(name)
        if r and r[0] * s <= x <= r[2] * s and r[1] * s <= y <= r[3] * s:
            return name
    return None


ISSUE = 'https://github.com/o/r/issues/123'
ISSUE2 = 'https://github.com/o/r/issues/131'
PR = 'https://github.com/o/r/pull/'


class LinksTest(StubSpeechctl):
    """A click on an issue or pull request number in a message's header in the terminal opens it
    in a browser tab, and one on a session's name asks to close it."""

    def setUp(self):
        super().setUp()
        rows = [dict(r) for r in REGIONS['rows']]
        rows[0].update(name=[92.0, 200.0])
        rows[1].update(name=[92.0, 180.0])
        # two numbers on the header of the message at line 4 of the terminal: an issue and a pull request
        self.regions = dict(REGIONS, rows=rows, terminal_links={'4': [{'id': 'aaaa', 'issue': ISSUE},
                                                                       {'id': 'aaaa', 'issue': PR + '151'}]})
        with open(speech_mouse.TERMINAL_LINKS, 'w') as f:
            f.write('4 1 300.0 260.0 340.0 276.0\n4 2 360.0 260.0 400.0 276.0\n')
        self.opened = []
        speech_mouse.opened.clear()
        speech_mouse.opening.clear()

    def open(self, row):
        speech_mouse.open_links(row, 'issue', popen=lambda args, **kw: self.opened.append(args[1:]) or mock.Mock())
        return self.opened.pop() if self.opened else None

    def test_a_number_opens_its_url(self):
        self.assertEqual(self.open({'id': 'aaaa', 'issue': ISSUE2}), [ISSUE2])

    def test_without_chrome_the_link_goes_to_xdg_open(self):
        def popen(args, **kwargs):
            if args[0] == speech_mouse.BROWSER:
                raise FileNotFoundError(args[0])
            self.opened.append(args)
            return mock.Mock()
        speech_mouse.open_links({'id': 'aaaa', 'issue': PR + '151'}, 'issue', popen=popen)
        self.assertEqual(self.opened, [['xdg-open', PR + '151']])

    def test_each_number_in_a_terminal_header_is_a_link_and_the_name_closes_the_session(self):
        at = lambda x, y: (lambda hit: hit and (hit[0].get('issue'), hit[0]['id'], hit[1]))(
            speech_mouse.link_at(self.regions, 1, x, y))
        self.assertEqual(at(320, 268), (ISSUE, 'aaaa', 'issue'))
        self.assertEqual(at(380, 268), (PR + '151', 'aaaa', 'issue'))
        self.assertIsNone(at(350, 268))                           # between the two numbers
        self.assertIsNone(at(320, 290))                           # under them
        self.assertEqual(at(150, 106), (None, 'aaaa', 'close'))   # the name, on its line
        self.assertIsNone(at(210, 106))                           # right of the name
        self.assertEqual(at(120, 94 + 96 + 12), (None, 'bbbb', 'close'))
        self.assertIsNone(at(120, 94 + 96 + 36))                  # not a second line

    def test_a_click_on_a_number_opens_it(self):
        opened = []
        thread = lambda target, args, daemon: mock.Mock(start=lambda: target(*args))
        with mock.patch.object(speech_mouse.threading, 'Thread', side_effect=thread), \
                mock.patch.object(speech_mouse, 'open_links', side_effect=lambda r, k: opened.append((r['id'], r['issue']))):
            for x, y in ((320, 268), (380, 268)):
                track = mock.Mock(return_value=(x, y, False))
                self.assertTrue(speech_mouse.pull_control(None, None, None, 1, self.regions, None, track,
                                                          (x, y, (x, y)), False))
            track = mock.Mock(return_value=(350, 268, False))
            self.assertFalse(speech_mouse.pull_control(None, None, None, 1, self.regions, None, track,
                                                       (350, 268, (350, 268)), False))    # off a number
        self.assertEqual(opened, [('aaaa', ISSUE), ('aaaa', PR + '151')])
        self.assertEqual(self.ran(), [])

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
                speech_mouse.open_once({'id': 'aaaa', 'issue': ISSUE}, 'issue', now=lambda t=t: t)
            speech_mouse.opening.clear()
            speech_mouse.open_once({'id': 'aaaa', 'issue': ISSUE}, 'issue', now=lambda: 103.6)    # 3.6 s on: again
            speech_mouse.open_once({'id': 'aaaa', 'issue': ISSUE2}, 'issue', now=lambda: 103.7)   # another number
        self.assertEqual(len(started), 3)

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
                mock.patch.object(speech_mouse, 'focus_window', return_value=(True, False)), \
                mock.patch.object(speech_mouse, 'set_accepts_input'), \
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

    def test_over_the_volume(self):
        self.assertEqual([self.wheel('volume', True), self.wheel((64, 357), False)], ['volume', 'volume'])
        self.assertEqual(self.ran(), ['volume down', 'volume up'])

    def test_over_the_rest_of_the_list_it_scrolls_a_row_within_its_range(self):
        self.assertEqual(self.wheel((200, 106), True), 'list')
        self.assertEqual(support.read(speech_mouse.LIST_SCROLL), '1')
        self.wheel((200, 106), True)
        self.assertEqual(support.read(speech_mouse.LIST_SCROLL), '1')   # the last row
        self.wheel((200, 106), False)
        self.wheel((200, 106), False)
        self.assertEqual(support.read(speech_mouse.LIST_SCROLL), '0')
        self.assertEqual(self.ran(), [])

    def test_over_the_terminal_it_counts_steps_for_draw_lua_and_nowhere_else(self):
        self.assertEqual(self.wheel('terminal', True), 'terminal')
        self.wheel('terminal', True)
        self.wheel('terminal', False)
        self.assertEqual(support.read(speech_mouse.TERMINAL_SCROLL), '1')
        self.assertIsNone(self.wheel((300, 245), True))              # just above it: not the terminal
        self.assertEqual(support.read(speech_mouse.TERMINAL_SCROLL), '1')
        self.assertEqual(self.ran(), [])

    def test_a_terminal_with_nothing_to_scroll_takes_the_wheel_and_writes_nothing(self):
        regions = dict(REGIONS, terminal_scroll=0)
        x, y = centre(REGIONS['terminal'])
        self.assertEqual(speech_mouse.wheel(regions, 1, x, y, True), 'terminal')
        self.assertFalse(os.path.exists(speech_mouse.TERMINAL_SCROLL))

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


if __name__ == '__main__':
    unittest.main()
