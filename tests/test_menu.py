"""menu.py: the settings menu's pages, what each row shows and what Enter does on it."""
import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402,F401  (puts src/ on the path)
import menu  # noqa: E402

VOICES = ['en_GB-alan-medium', 'en_US-amy-medium', 'en_US-joe-medium']
SESSIONS = [{'id': 'aaaa', 'title': 'One', 'speech': 'on', 'voice': ''},
            {'id': 'bbbb', 'title': 'Two', 'speech': 'alerts', 'voice': 'en_US-joe-medium'}]


class Fake:
    def __init__(self):
        self.v, self.p, self.sc, self.col, self.top, self.log = 'en_US-amy-medium', 0.85, 1.0, False, True, []

    def voice(self): return self.v
    def pace(self): return self.p
    def scale(self): return self.sc
    def collapse(self): return self.col
    def on_top(self): return self.top
    def set_voice(self, name): self.v = name; self.log.append(('voice', name))
    def set_pace(self, pace): self.p = pace; self.log.append(('pace', pace))
    def set_scale(self, scale): self.sc = scale; self.log.append(('scale', scale))
    def set_collapse(self, on): self.col = on; self.log.append(('collapse', on))
    def set_on_top(self, on): self.top = on; self.log.append(('on top', on))
    def reset_size(self): self.log.append(('reset',))
    def set_session_voice(self, sid, name): self.log.append(('session voice', sid, name))
    def set_session_speech(self, sid, value): self.log.append(('session speech', sid, value))


class MenuTest(unittest.TestCase):
    def setUp(self):
        self.fake = Fake()
        self.menu = menu.Menu(SESSIONS, VOICES, self.fake)

    def test_a_voice_is_its_speaker(self):
        self.assertEqual(menu.voice_label('en_US-amy-medium'), 'amy')
        self.assertEqual(menu.voice_label('my-voice'), 'my-voice')

    def test_the_first_page_lists_the_widgets_settings_with_their_values(self):
        self.assertEqual(self.menu.title(), 'Settings')
        self.assertEqual(self.menu.rows(), [
            ('Default voice', 'amy ›', ''), ('Pace', '0.85', ''), ('Text scaling', '100%', ''),
            ('Collapse when idle', 'false', ''), ('Always on top', 'true', ''), ('Reset widget size', '›', ''),
            ('Sessions', '2 ›', '')])

    def test_enter_turns_a_setting_to_its_next_value_and_wraps(self):
        for row, want in ((1, ('pace', 1.0)), (2, ('scale', 1.25)), (3, ('collapse', True)),
                          (4, ('on top', False)), (5, ('reset',))):
            self.menu.activate(row)
            self.assertEqual(self.fake.log[-1], want)
        self.fake.p = 1.4                                         # the last preset: round to the first
        self.menu.activate(1)
        self.assertEqual(self.fake.log[-1], ('pace', 0.6))
        self.fake.p = 0.9                                         # not a preset: the first
        self.menu.activate(1)
        self.assertEqual(self.fake.log[-1], ('pace', 0.6))

    def test_the_default_voice_page_marks_the_voice_in_use_and_picking_one_goes_back(self):
        self.menu.activate(0)
        self.assertEqual(self.menu.title(), 'Settings › Default voice')
        self.assertEqual(self.menu.selected, 0)
        self.assertEqual([r[2] for r in self.menu.rows()], ['', 'current', ''])
        self.menu.activate(2)
        self.assertEqual(self.fake.log, [('voice', 'en_US-joe-medium')])
        self.assertEqual((self.menu.page, self.menu.selected), (('root', None), 0))

    def test_the_sessions_page_lists_each_with_its_speech_and_a_session_has_a_page(self):
        self.menu.activate(6)
        self.assertEqual(self.menu.rows(), [('One', 'On ›', ''), ('Two', 'Alerts ›', '')])
        self.menu.activate(1)
        self.assertEqual(self.menu.title(), 'Settings › Sessions › Two')
        self.assertEqual(self.menu.rows(), [('Speech', 'Alerts', ''), ('Voice', 'joe ›', '')])
        self.menu.activate(0)                                      # Alerts -> Off, kept on the page
        self.assertEqual(self.fake.log, [('session speech', 'bbbb', 'off')])
        self.assertEqual(self.menu.rows()[0], ('Speech', 'Off', ''))
        self.menu.activate(0)
        self.menu.activate(0)                                      # Off -> On -> Alerts
        self.assertEqual(self.fake.log[-1], ('session speech', 'bbbb', 'alerts'))

    def test_a_sessions_voice_page_starts_on_its_voice_and_default_removes_it(self):
        self.menu.activate(6)
        self.menu.activate(1)
        self.menu.activate(1)
        self.assertEqual(self.menu.title(), 'Settings › Sessions › Two › Voice')
        self.assertEqual(self.menu.selected, 3)                    # Default, alan, amy, joe
        self.assertEqual([r[0] for r in self.menu.rows()], ['Default', 'alan', 'amy', 'joe'])
        self.menu.activate(0)
        self.assertEqual(self.fake.log, [('session voice', 'bbbb', '')])
        self.assertEqual(self.menu.page, ('session', 1))
        self.assertEqual(self.menu.rows()[1], ('Voice', 'Default ›', ''))

    def test_back_returns_to_the_row_that_opened_the_page_and_stops_at_the_first(self):
        self.menu.select(6)
        self.menu.activate()
        self.menu.activate(1)
        self.assertTrue(self.menu.back())
        self.assertEqual((self.menu.page, self.menu.selected), (('sessions', None), 1))
        self.assertTrue(self.menu.back())
        self.assertEqual((self.menu.page, self.menu.selected), (('root', None), 6))
        self.assertFalse(self.menu.back())

    def test_the_cursor_stays_in_the_page_and_the_rows_scroll_to_keep_it_shown(self):
        self.menu.move(10, 3)
        self.assertEqual((self.menu.selected, self.menu.top), (6, 4))
        self.menu.move(-10, 3)
        self.assertEqual((self.menu.selected, self.menu.top), (0, 0))
        self.menu.move(3, 3)
        self.assertEqual((self.menu.selected, self.menu.top), (3, 1))

    def test_without_sessions_the_page_says_so_and_opens_nothing(self):
        empty = menu.Menu([], VOICES, self.fake)
        empty.activate(6)
        self.assertEqual(empty.rows(), [('No Claude sessions open', '', '')])
        empty.activate(0)
        self.assertEqual(empty.page, ('sessions', None))


if __name__ == '__main__':
    unittest.main()
