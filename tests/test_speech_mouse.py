"""The speech widget's mouse handling (src/speech/mouse.py): the wheel and swipes that scroll the
session list, the links and names that open a browser tab or the close prompt, and that prompt."""
import json
import os
import shutil
import unittest
from unittest import mock

import support

conky_mouse = support.load_conky_mouse()
speech_mouse = support.load_speech_mouse()

# As speechqueue.py writes them: two sessions, the first with a line of its last reply under it
# (two rows of 24 px), the second a row of its own, the list from y 94 to 142 with one row scrolled
# out of view at most.
REGIONS = {'minimize': [484.0, 16.0, 506.0, 38.0], 'close': [506.0, 16.0, 540.0, 38.0],
           'list': [16, 94.0, 522, 238.0], 'list_scroll': [1, 24.0],
           'terminal': [16.0, 250.0, 522, 338.0], 'terminal_scroll': 4,
           'rows': [{'id': 'aaaa', 'top': 0.0, 'bottom': 96.0, 'head': 0.0, 'title': 'One'},
                    {'id': 'bbbb', 'top': 96.0, 'bottom': 144.0, 'head': 0.0, 'title': 'Two'}]}


def centre(r):
    return (r[0] + r[2]) / 2, (r[1] + r[3]) / 2


class MouseTest(support.TempDirTest):
    """Each test's own cache files and mouse log."""

    def setUp(self):
        super().setUp()
        self.redirect(speech_mouse, LIST_SCROLL='list-scroll', TERMINAL_SCROLL='terminal-scroll', CACHE='',
                      CLOSE_CONFIRM='close-confirm', TERMINAL_LINKS='terminal-links')
        self.redirect(conky_mouse, LOG='mouse.log')

    def scroll_to(self, rows):
        with open(speech_mouse.LIST_SCROLL, 'w') as f:
            f.write(str(rows))


class FocusTest(MouseTest):
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


class ControlsTest(MouseTest):
    def test_the_widget_has_no_controls_of_its_own_beyond_the_window_buttons_and_the_divider(self):
        self.assertEqual(speech_mouse.BUTTONS, ())
        self.assertEqual(speech_mouse.REGIONS_ORDER, ('minimize', 'close', 'divider'))
        for name in ('press', 'speechctl', 'open_menu', 'set_volume', 'toggle_mute'):
            self.assertFalse(hasattr(speech_mouse, name), name)


ISSUE = 'https://github.com/o/r/issues/123'
ISSUE2 = 'https://github.com/o/r/issues/131'
PR = 'https://github.com/o/r/pull/'


class LinksTest(MouseTest):
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


class CloseTest(MouseTest):
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


class WheelTest(MouseTest):
    def wheel(self, name_or_xy, down, s=1):
        x, y = centre(REGIONS[name_or_xy]) if isinstance(name_or_xy, str) else name_or_xy
        return speech_mouse.wheel(REGIONS, s, x * s, y * s, down)

    def test_over_the_rest_of_the_list_it_scrolls_a_row_within_its_range(self):
        self.assertEqual(self.wheel((200, 106), True), 'list')
        self.assertEqual(support.read(speech_mouse.LIST_SCROLL), '1')
        self.wheel((200, 106), True)
        self.assertEqual(support.read(speech_mouse.LIST_SCROLL), '1')   # the last row
        self.wheel((200, 106), False)
        self.wheel((200, 106), False)
        self.assertEqual(support.read(speech_mouse.LIST_SCROLL), '0')

    def test_over_the_terminal_it_counts_steps_for_draw_lua_and_nowhere_else(self):
        self.assertEqual(self.wheel('terminal', True), 'terminal')
        self.wheel('terminal', True)
        self.wheel('terminal', False)
        self.assertEqual(support.read(speech_mouse.TERMINAL_SCROLL), '1')
        self.assertIsNone(self.wheel((300, 245), True))              # just above it: not the terminal
        self.assertEqual(support.read(speech_mouse.TERMINAL_SCROLL), '1')

    def test_a_terminal_with_nothing_to_scroll_takes_the_wheel_and_writes_nothing(self):
        regions = dict(REGIONS, terminal_scroll=0)
        x, y = centre(REGIONS['terminal'])
        self.assertEqual(speech_mouse.wheel(regions, 1, x, y, True), 'terminal')
        self.assertFalse(os.path.exists(speech_mouse.TERMINAL_SCROLL))

    def test_anywhere_else_it_does_nothing(self):
        self.assertIsNone(self.wheel((300, 60), True))
        self.assertIsNone(self.wheel((300, 244), True))              # the gap between the list and the terminal

    def test_the_areas_follow_the_display_scale(self):
        self.assertEqual(self.wheel('terminal', True, s=2), 'terminal')
        self.assertIsNone(speech_mouse.wheel(REGIONS, 2, 100, 244 * 2, True))   # between them at 2x


class SwipeTest(MouseTest):
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
