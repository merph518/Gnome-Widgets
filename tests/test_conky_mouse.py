"""Tests for conky-mouse.py's placement (keeping the window on screen across monitors, and
on its own monitor as monitors come and go and the display scale changes), resizing (which edges a press drags, and the size settings a drag leads to), and the wheel
over plain lyrics and over the volume slider."""
import os
import time
import unittest
from unittest import mock

import support

conky_mouse = support.load_conky_mouse()
spotify_mouse = support.load_spotify_mouse()

W, H = 545, 200   # about the widget's size
# Two 1920x1080 monitors side by side, and a third above the first one.
MONITORS = [(0, 0, 1920, 1080, True, 'DP-1'), (1920, 0, 1920, 1080, False, 'DP-2'),
            (0, -1080, 1920, 1080, False, 'DP-3')]


class ClampToMonitorTest(unittest.TestCase):

    def clamp(self, x, y, monitors=MONITORS):
        with mock.patch.object(conky_mouse, 'monitors', return_value=monitors):
            return conky_mouse.clamp_to_monitor(x, y, W, H)

    def test_no_monitors_leaves_the_position_alone(self):
        self.assertEqual(self.clamp(-5000, 9000, monitors=[]), (-5000, 9000))

    def test_on_screen_position_is_kept(self):
        for pos in ((100, 100), (0, 0), (1920 - W, 1080 - H), (2500, 400), (100, -900)):
            with self.subTest(pos=pos):
                self.assertEqual(self.clamp(*pos), pos)

    def test_overhanging_edges_are_pulled_in(self):
        self.assertEqual(self.clamp(-50, 500), (0, 500))                      # left edge
        self.assertEqual(self.clamp(3840 - W + 60, 500), (3840 - W, 500))     # right edge of the second
        self.assertEqual(self.clamp(2500, 1080 - H + 40), (2500, 1080 - H))   # bottom of the second

    def test_straddling_two_monitors_moves_onto_the_one_holding_the_centre(self):
        # Centre at x = 1700 + 272 = 1972: on the second monitor.
        self.assertEqual(self.clamp(1700, 300), (1920, 300))
        # Centre at x = 1600 + 272 = 1872: on the first.
        self.assertEqual(self.clamp(1600, 300), (1920 - W, 300))
        # Straddling the first and the one above it, centre below the seam.
        self.assertEqual(self.clamp(300, -60), (300, 0))

    def test_off_screen_window_goes_to_the_nearest_monitor(self):
        self.assertEqual(self.clamp(5000, 500), (3840 - W, 500))    # far right: the second
        self.assertEqual(self.clamp(-3000, 400), (0, 400))          # far left: the first
        self.assertEqual(self.clamp(2500, 3000), (2500, 1080 - H))  # below the second
        self.assertEqual(self.clamp(500, -4000), (500, -1080))      # above: the one on top


class PositionTest(support.TempDirTest):

    def setUp(self):
        super().setUp()
        self.redirect(conky_mouse, CONF='.', POSITION='position')

    def test_saved_with_its_anchor_and_read_back(self):
        anchor = conky_mouse.anchor_for(2500, 400, W, H, MONITORS, 1)
        self.assertEqual(anchor, ('DP-2', 580, 400, 1920, 1))
        conky_mouse.save_position(2500, 400, anchor)
        self.assertEqual(support.read(conky_mouse.POSITION), '2500 400 DP-2 580 400 1920 1\n')
        self.assertEqual(conky_mouse.load_position(), (2500, 400, anchor))

    def test_a_file_without_a_whole_anchor_reads_without_one(self):
        for text in ('2044 12\n', '2044 12 eDP-1 2044 12 192\n', '2044 12 eDP-1 a b c d\n',
                     '2044 12 eDP-1 2044 12 0 2\n', '2044 12 eDP-1 2044 12 3072 0\n'):
            with self.subTest(text=text):
                with open(conky_mouse.POSITION, 'w') as f:
                    f.write(text)
                self.assertEqual(conky_mouse.load_position(), (2044, 12, None))
        conky_mouse.save_position(2044, 12, None)
        self.assertEqual(support.read(conky_mouse.POSITION), '2044 12\n')

    def test_missing_or_bad_file_is_no_position(self):
        self.assertIsNone(conky_mouse.load_position())
        for text in ('left top\n', '2044\n'):
            with self.subTest(text=text):
                with open(conky_mouse.POSITION, 'w') as f:
                    f.write(text)
                self.assertIsNone(conky_mouse.load_position())

    def test_no_anchor_without_monitors(self):
        self.assertIsNone(conky_mouse.anchor_for(100, 100, W, H, [], 1))


def doubled(mons):
    return [(x * 2, y * 2, w * 2, h * 2, p, n) for x, y, w, h, p, n in mons]


class ResolveTest(unittest.TestCase):

    SAVED = (2500, 400, ('DP-2', 580, 400, 1920, 1))

    def test_unchanged_monitors_keep_the_position(self):
        self.assertEqual(conky_mouse.resolve(self.SAVED, MONITORS, 1), self.SAVED)

    def test_follows_its_monitor_when_another_is_removed(self):
        # The first monitor unplugged: the second slides over to x = 0.
        mons = [(0, 0, 1920, 1080, True, 'DP-2')]
        self.assertEqual(conky_mouse.resolve(self.SAVED, mons, 1), (580, 400, self.SAVED[2]))

    def test_follows_its_monitor_when_one_is_added_before_it(self):
        mons = [(0, 0, 3072, 1920, False, 'eDP-1')] + [(x + 3072, y, w, h, p, n) for x, y, w, h, p, n in MONITORS]
        self.assertEqual(conky_mouse.resolve(self.SAVED, mons, 1)[:2], (3072 + 1920 + 580, 400))

    def test_its_monitor_gone_keeps_where_it_was(self):
        mons = [MONITORS[0]]
        self.assertEqual(conky_mouse.resolve(self.SAVED, mons, 1), self.SAVED)
        with mock.patch.object(conky_mouse, 'monitors', return_value=mons):   # then kept on screen
            self.assertEqual(conky_mouse.clamp_to_monitor(2500, 400, W, H), (1920 - W, 400))

    def test_a_scale_change_follows_its_monitors_width(self):
        self.assertEqual(conky_mouse.resolve(self.SAVED, doubled(MONITORS), 2),
                         (3840 + 1160, 800, ('DP-2', 1160, 800, 3840, 2)))

    def test_its_monitor_scaled_before_xft_dpi_follows(self):
        # XWayland's coordinates and Xft.dpi change a moment apart: the width decides.
        self.assertEqual(conky_mouse.resolve(self.SAVED, doubled(MONITORS), 1)[:2], (3840 + 1160, 800))

    def test_text_scaling_alone_moves_nothing(self):
        # Large Text raises Xft.dpi but not the scale or any monitor's width.
        self.assertEqual(conky_mouse.resolve(self.SAVED, MONITORS, conky_mouse.scale_of(120))[:2], (2500, 400))

    def test_its_monitor_gone_scales_with_the_display(self):
        self.assertEqual(conky_mouse.resolve(self.SAVED, doubled(MONITORS)[:1], 2),
                         (5000, 800, ('DP-2', 1160, 800, 3840, 2)))

    def test_and_back_again(self):
        there = conky_mouse.resolve(self.SAVED, doubled(MONITORS), 2)
        self.assertEqual(conky_mouse.resolve(there, MONITORS, 1), self.SAVED)
        there = conky_mouse.resolve(self.SAVED, doubled(MONITORS)[:1], 2)
        self.assertEqual(conky_mouse.resolve(there, MONITORS, 1), self.SAVED)

    def test_without_an_anchor_nothing_moves(self):
        self.assertEqual(conky_mouse.resolve((2044, 12, None), MONITORS, 2), (2044, 12, None))


class MonitorsTest(unittest.TestCase):

    def test_names_and_the_primary_are_read(self):
        out = (' 0: +*DP-9 3840/480x2160/270+6912+0  DP-9\n'
               ' 1: +eDP-1 3072/290x1920/180+0+0  eDP-1\n')
        with mock.patch('subprocess.run', return_value=mock.Mock(stdout='Monitors: 2\n' + out)):
            self.assertEqual(conky_mouse.monitors(), [(6912, 0, 3840, 2160, True, 'DP-9'),
                                                      (0, 0, 3072, 1920, False, 'eDP-1')])

    def test_dpi_is_none_when_xrdb_has_none(self):
        with mock.patch('subprocess.run', return_value=mock.Mock(stdout='Xft.dpi:\t192\n')):
            self.assertEqual((conky_mouse.dpi(), conky_mouse.scale()), (192, 2))
        with mock.patch('subprocess.run', return_value=mock.Mock(stdout='')):
            self.assertEqual((conky_mouse.dpi(), conky_mouse.scale()), (None, 1))
        self.assertEqual([conky_mouse.scale_of(v) for v in (96, 120, 192, None)], [1, 1, 2, 1])


class ResizeEdgesTest(unittest.TestCase):

    def edges(self, x, y, s=1):
        return conky_mouse.resize_edges(x, y, W * s, H * s, s)

    def test_inside_is_a_move(self):
        for pos in ((W // 2, H // 2), (6, 6), (W - 7, H - 7), (30, 100)):
            with self.subTest(pos=pos):
                self.assertEqual(self.edges(*pos), '')

    def test_edges(self):
        self.assertEqual(self.edges(0, H // 2), 'l')
        self.assertEqual(self.edges(W - 1, H // 2), 'r')
        self.assertEqual(self.edges(W // 2, 5), 't')
        self.assertEqual(self.edges(W // 2, H - 6), 'b')

    def test_corners_reach_along_both_edges(self):
        self.assertEqual(self.edges(0, 0), 'lt')
        self.assertEqual(self.edges(W - 1, 20), 'rt')        # on the right edge, near the top
        self.assertEqual(self.edges(20, H - 1), 'lb')        # on the bottom edge, near the left
        self.assertEqual(self.edges(W - 23, H - 1), 'rb')
        self.assertEqual(self.edges(W - 25, H - 1), 'b')     # just past the corner's reach

    def test_bands_follow_the_display_scale(self):
        self.assertEqual(self.edges(11, H, 2), 'l')          # 6 px band, doubled
        self.assertEqual(self.edges(12, H, 2), '')
        self.assertTrue(set(conky_mouse.CURSORS) >= {self.edges(x, y, 2) for x in (0, W, 2 * W - 1)
                                                      for y in (0, H, 2 * H - 1)} - {''})


class CardTest(unittest.TestCase):

    def test_the_card_is_the_window_less_the_shadow_on_every_side(self):
        m = conky_mouse.SHADOW
        self.assertEqual(conky_mouse.card_of((100, 200, W, H), 1), (100 + m, 200 + m, W - 2 * m, H - 2 * m))
        self.assertEqual(conky_mouse.card_of((100, 200, W, H), 2),
                         (100 + 2 * m, 200 + 2 * m, W - 4 * m, H - 4 * m))
        for s in (1, 2):
            self.assertEqual(conky_mouse.window_of(conky_mouse.card_of((100, 200, W, H), s), s),
                             (100, 200, W, H))

    def test_the_shadow_is_off_the_card(self):
        self.assertTrue(conky_mouse.on_card(0, 0, W, H))
        self.assertTrue(conky_mouse.on_card(W - 1, H - 1, W, H))
        for x, y in ((-1, 10), (10, -1), (W, 10), (10, H)):
            with self.subTest(x=x, y=y):
                self.assertFalse(conky_mouse.on_card(x, y, W, H))

    def test_the_arrow_has_a_cursor_of_its_own(self):
        self.assertIn('', conky_mouse.CURSORS)


class CardPlacementTest(unittest.TestCase):
    # At scale 2 the window has 32 px of shadow on every side of the card.
    MON = (0, 0, 3840, 2160)

    def patch(self, **values):
        for name, value in values.items():
            patcher = mock.patch.object(conky_mouse, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_drag_saves_where_the_card_ends_up(self):
        self.patch(geometry=mock.Mock(side_effect=[(100, 200, 1304, 730), (500, 600, 1304, 730)]),
                   pointer=mock.Mock(return_value=(0, 0, 0)), monitor_for=mock.Mock(return_value=self.MON),
                   log=mock.Mock())
        self.assertEqual(conky_mouse.drag(None, 0, 1, 2, conky_mouse.follow_pointer(None, 0)), (532, 632, 1240, 666))

    def test_a_drag_from_the_art_follows_the_pointer_from_the_press(self):
        # The pointer is already past the click slop when the drag starts; the window
        # still moves by all of it, from where the button went down.
        moves = []
        self.patch(geometry=mock.Mock(side_effect=[(100, 200, 1304, 730), (110, 200, 1304, 730)]),
                   pointer=mock.Mock(side_effect=[(510, 300, conky_mouse.BUTTON1_MASK), (510, 300, 0)]),
                   monitor_for=mock.Mock(return_value=self.MON), log=mock.Mock(),
                   x11=mock.Mock(XMoveWindow=lambda d, w, x, y: moves.append((x, y))))
        conky_mouse.drag(None, 0, 1, 2, conky_mouse.follow_pointer(None, 0), (500, 300))
        self.assertEqual(moves, [(110, 200)])

    def test_a_resize_moves_the_window_round_the_resized_card_and_saves_the_card(self):
        # Dragging the left edge 100 px left at scale 2 widens the card by 100 and moves it left.
        moves = []
        old, new = (505, 63, 1.0), (555, 63, 1.0)
        # the window at the start, then conky's at the new size, then moved, as long as asked
        geometries = [(1000, 100, 1304, 730), (1000, 100, 1404, 730), (900, 100, 1404, 730)]
        self.patch(geometry=mock.Mock(side_effect=lambda d, w: geometries.pop(0) if len(geometries) > 1
                                      else geometries[0]),
                   pointer=mock.Mock(side_effect=[(500, 300, conky_mouse.BUTTON1_MASK),
                                                  (400, 300, conky_mouse.BUTTON1_MASK), (400, 300, 0)]),
                   monitor_for=mock.Mock(return_value=self.MON), log=mock.Mock(), outline=mock.Mock(return_value=[]),
                   place_outline=mock.Mock(), cover=mock.Mock(), uncover=mock.Mock(),
                   set_input_shape=mock.Mock(), x11=mock.Mock(XMoveWindow=lambda d, w, x, y: moves.append((x, y))))
        self.patch(widget_size=mock.Mock(load=mock.Mock(return_value=old), save=mock.Mock(),
                                         clamp=conky_mouse.widget_size.clamp, LIMITS=conky_mouse.widget_size.LIMITS))
        placed = conky_mouse.resize(None, 0, 1, 'l', 2, {'lyrics': [0, 0, 1, 1]},
                                    conky_mouse.follow_pointer(None, 0))
        conky_mouse.widget_size.load.assert_called_once_with(conky_mouse.SIZE)    # this widget's file
        conky_mouse.widget_size.save.assert_called_once_with(new, conky_mouse.SIZE)
        conky_mouse.place_outline.assert_called_with(None, [], 932, 132, 1340, 666, 4)   # the card
        self.assertEqual(moves, [(900, 100)])                                           # the window
        conky_mouse.set_input_shape.assert_called_once_with(None, 1, 1404, 730, 2)
        self.assertEqual(placed, (932, 132, 1340, 666))


class DraggedTest(unittest.TestCase):
    ROOM = 10 ** 6            # the monitor's room left over; most tests stay well inside it

    def dragged(self, edges, dx, dy, settings=(505, 63, 1.0), s=1, room=(ROOM, ROOM)):
        return conky_mouse.dragged(settings, edges, dx, dy, *room, s)

    def test_side_edges_change_the_width_only(self):
        self.assertEqual(self.dragged('r', 100, 999), (605, 63, 1.0))
        self.assertEqual(self.dragged('l', 100, 999), (405, 63, 1.0))
        self.assertEqual(self.dragged('r', 100, 0, s=2), (555, 63, 1.0))          # display scale

    def test_top_and_bottom_change_the_lyrics_height_only(self):
        self.assertEqual(self.dragged('b', 999, 42), (505, 105, 1.0))
        self.assertEqual(self.dragged('t', 999, 42), (505, 21, 1.0))
        self.assertEqual(self.dragged('t', 0, -84, s=2), (505, 105, 1.0))

    def test_corners_change_both_and_never_the_text(self):
        self.assertEqual(self.dragged('rb', 50, 20, (505, 63, 1.5)), (555, 83, 1.5))
        self.assertEqual(self.dragged('lt', 50, 20, (505, 63, 0.7)), (455, 43, 0.7))

    def test_limits(self):
        self.assertEqual(self.dragged('r', -999, 0), (400, 63, 1.0))
        self.assertEqual(self.dragged('b', 0, -999), (505, 16, 1.0))

    def test_growth_stops_at_the_monitor(self):
        self.assertEqual(self.dragged('r', 500, 0, room=(120, 0)), (625, 63, 1.0))
        self.assertEqual(self.dragged('b', 0, 500, room=(0, 50)), (505, 113, 1.0))
        self.assertEqual(self.dragged('rb', 500, 500, s=2, room=(100, 40)), (555, 83, 1.0))

    def test_shrinking_needs_no_room(self):
        self.assertEqual(self.dragged('r', -100, 0, room=(0, 0)), (405, 63, 1.0))
        self.assertEqual(self.dragged('lt', 20, 20, room=(0, 0)), (485, 43, 1.0))


class ResizedTest(unittest.TestCase):
    START, OLD = (1000, 100, 1090, 400), (505, 63, 1.0)

    def resized(self, edges, new, lyrics=True):
        return conky_mouse.resized(self.START, edges, self.OLD, new, 2, lyrics)

    def test_the_edges_across_from_the_dragged_ones_stay_put(self):
        self.assertEqual(self.resized('r', (555, 63, 1.0)), (1000, 100, 1190, 400))
        self.assertEqual(self.resized('l', (555, 63, 1.0)), (900, 100, 1190, 400))
        self.assertEqual(self.resized('b', (505, 13 + 63, 1.0)), (1000, 100, 1090, 426))
        self.assertEqual(self.resized('t', (505, 43, 1.0)), (1000, 140, 1090, 360))
        self.assertEqual(self.resized('lt', (455, 83, 1.0)), (1100, 60, 990, 440))

    def test_without_lyrics_the_height_stays(self):
        self.assertEqual(self.resized('rb', (555, 163, 1.0), lyrics=False), (1000, 100, 1190, 400))


class WithoutIdleEdgesTest(unittest.TestCase):

    def test_no_lyrics_leaves_only_the_width_to_change(self):
        for edges, want in (('t', ''), ('b', ''), ('rb', 'r'), ('lt', 'l'), ('r', 'r')):
            with self.subTest(edges=edges):
                self.assertEqual(spotify_mouse.without_idle_edges(edges, {'lyrics': False}), want)
                self.assertEqual(spotify_mouse.without_idle_edges(edges, {'lyrics': True}), edges)
                self.assertEqual(spotify_mouse.without_idle_edges(edges, {}), want)   # not written yet


class ScrollLyricsTest(support.TempDirTest):
    # Lyrics at x 22..545, y 160..223 (logical px), whose last offset is 5.
    REGIONS = {'lyrics': [22, 160, 545, 223], 'lyrics_scroll': ['1234', 5]}

    def setUp(self):
        super().setUp()
        self.redirect(spotify_mouse, LYRICS_SCROLL='lyrics-scroll')

    def wheel(self, down, regions=REGIONS, x=100, y=180, s=1):
        return spotify_mouse.scroll_lyrics(regions, s, x, y, down)

    def shown(self):
        return support.read(spotify_mouse.LYRICS_SCROLL)

    def test_the_wheel_moves_a_line_at_a_time_from_the_top(self):
        self.assertEqual([self.wheel(True), self.wheel(True), self.wheel(False)], [1, 2, 1])
        self.assertEqual(self.shown(), '1234 1')

    def test_it_stops_at_the_first_and_the_last_line(self):
        self.assertEqual(self.wheel(False), 0)
        for _ in range(8):
            self.wheel(True)
        self.assertEqual(self.shown(), '1234 5')

    def test_an_offset_past_a_shrunken_range_steps_back_from_its_end(self):
        with open(spotify_mouse.LYRICS_SCROLL, 'w') as f:
            f.write('1234 34')
        self.assertEqual(self.wheel(False), 4)

    def test_an_offset_for_other_lyrics_starts_from_the_top(self):
        with open(spotify_mouse.LYRICS_SCROLL, 'w') as f:
            f.write('999 4')
        self.assertEqual(self.wheel(True), 1)
        self.assertEqual(self.shown(), '1234 1')

    def test_outside_the_lyrics_or_over_synced_ones_it_does_nothing(self):
        synced = dict(self.REGIONS, lyrics_scroll=None)
        for regions, x, y in ((self.REGIONS, 100, 150), (self.REGIONS, 10, 180), (synced, 100, 180),
                              ({'lyrics': None, 'lyrics_scroll': None}, 100, 180), ({}, 100, 180)):
            with self.subTest(regions=regions, x=x, y=y):
                self.assertIsNone(self.wheel(True, regions, x, y))
        self.assertFalse(os.path.exists(spotify_mouse.LYRICS_SCROLL))

    def test_the_area_follows_the_display_scale(self):
        self.assertIsNone(self.wheel(True, y=400))          # below the lyrics at scale 1
        self.assertEqual(self.wheel(True, y=400, s=2), 1)


class SwipeTest(support.TempDirTest):
    # Lyrics at x 22..545, y 160..223 (logical px), last offset 5, 20 px a line.
    REGIONS = {'lyrics': [22, 160, 545, 223], 'lyrics_scroll': ['1234', 5, 20.0]}

    def setUp(self):
        super().setUp()
        self.redirect(spotify_mouse, LYRICS_SCROLL='lyrics-scroll')
        self.redirect(conky_mouse, LOG='mouse.log')

    def finger(self, *ys):
        """A tracker that is down at each y in turn (root px), then lifted at the last."""
        steps = [(300, y, True) for y in ys] + [(300, ys[-1], False)]
        return mock.Mock(side_effect=steps)

    def swipe(self, *ys, s=1):
        with mock.patch.object(conky_mouse.time, 'sleep'):
            spotify_mouse.swipe(self.REGIONS, s, 100 * s, 180 * s, 500, self.finger(*ys))
        return support.read(spotify_mouse.LYRICS_SCROLL).split()[1]

    def test_a_line_for_each_row_the_finger_moves(self):
        self.assertEqual([spotify_mouse.swipe_lines(dy, 20) for dy in (0, -19, -20, -59, 19, 40)],
                         [0, 0, 1, 2, 0, -2])
        self.assertEqual(spotify_mouse.swipe_lines(-50, 0), 0)

    def test_up_shows_later_lines_and_back_down_earlier_ones(self):
        self.assertEqual(self.swipe(500, 470, 440), '3')     # 60 px up: three lines on
        self.assertEqual(self.swipe(500, 520), '2')          # 20 px down: one back
        self.assertIn('swipe: -1 lines', support.read(conky_mouse.LOG))

    def test_it_stops_at_the_last_line(self):
        self.assertEqual(self.swipe(500, 300), '5')

    def test_movement_before_the_first_read_still_scrolls(self):
        self.assertEqual(self.swipe(440), '3')               # already 60 px up when first read

    def test_rows_follow_the_display_scale(self):
        self.assertEqual(self.swipe(500, 460, s=2), '1')     # 40 px at scale 2: one row

    def test_only_static_lyrics_with_a_row_height_are_scrollable(self):
        self.assertTrue(spotify_mouse.scrollable(self.REGIONS, 1, 100, 180))
        self.assertFalse(spotify_mouse.scrollable(self.REGIONS, 1, 100, 150))       # above them
        self.assertFalse(spotify_mouse.scrollable(dict(self.REGIONS, lyrics_scroll=None), 1, 100, 180))
        self.assertFalse(spotify_mouse.scrollable(dict(self.REGIONS, lyrics_scroll=['1234', 5]), 1, 100, 180))
        self.assertFalse(spotify_mouse.scrollable({}, 1, 100, 180))


class VolumeTest(support.TempDirTest):
    # The track at x 280..344 on the top row's centre line y 29.5, the speaker from x 256.
    REGIONS = {'volume_icon': [252, 19.5, 274, 39.5], 'volume': [274, 19.5, 350, 39.5],
               'volume_wheel': [252, 19.5, 350, 39.5],
               'volume_bar': [280, 344], 'lyrics': [22, 160, 545, 223], 'lyrics_scroll': ['1234', 5]}

    def setUp(self):
        super().setUp()
        self.redirect(spotify_mouse, LYRICS_SCROLL='lyrics-scroll', VOLUME_PREVIEW='volume-preview',
                      VOLUME_BEFORE_MUTE='before-mute', CACHE='')
        self.redirect(conky_mouse, LOG='mouse.log')
        patcher = mock.patch.object(spotify_mouse.subprocess, 'run')
        self.run_ = patcher.start()
        self.addCleanup(patcher.stop)

    def volumes(self):
        return [c.args[0][4] for c in self.run_.call_args_list]

    def test_the_wheel_over_the_slider_or_speaker_steps_spotifys_volume(self):
        self.assertEqual(spotify_mouse.wheel(self.REGIONS, 1, 300, 30, True), 'volume')
        self.assertEqual(spotify_mouse.wheel(self.REGIONS, 2, 260 * 2, 30 * 2, False), 'volume')
        self.assertEqual(self.run_.call_args_list[0].args[0][:4], ['playerctl', '-p', 'spotify', 'volume'])
        self.assertEqual(self.volumes(), ['0.05-', '0.05+'])
        self.assertIn('volume: wheel up', support.read(conky_mouse.LOG))

    def test_the_wheel_elsewhere_still_scrolls_static_lyrics(self):
        self.assertEqual(spotify_mouse.wheel(self.REGIONS, 1, 100, 180, True), 1)
        self.assertIsNone(spotify_mouse.wheel(self.REGIONS, 1, 400, 30, True))   # the heart, past it
        self.assertIsNone(spotify_mouse.wheel({}, 1, 300, 30, True))              # no slider
        self.run_.assert_not_called()

    def drag(self, *xs, s=1):
        """Drags along the slider at root xs (the card's left at root 1000), let go at the last."""
        steps = [(x, 530, True) for x in xs] + [(xs[-1], 530, False)]
        with mock.patch.object(conky_mouse, 'card_of', return_value=(1000, 500, 545, 200)), \
                mock.patch.object(conky_mouse, 'geometry'), \
                mock.patch.object(spotify_mouse.time, 'sleep'):
            spotify_mouse.set_volume('d', 'win', self.REGIONS, s, mock.Mock(side_effect=steps))

    def test_a_drag_sets_the_volume_as_it_moves_and_logs_where_it_ends(self):
        self.drag(1280, 1312, 1312, 1400)
        self.assertEqual(self.volumes(), ['0.00', '0.50', '1.00'])   # once per level, clamped
        self.assertIn('volume: 1.00', support.read(conky_mouse.LOG))
        self.assertFalse(os.path.exists(spotify_mouse.VOLUME_PREVIEW))  # gone once let go

    def test_the_slider_follows_the_display_scale(self):
        self.drag(1000 + 296 * 2, s=2)                    # a quarter along at scale 2
        self.assertEqual(self.volumes(), ['0.25'])

    def test_a_press_on_the_slider_sets_the_volume(self):
        with mock.patch.object(spotify_mouse, 'set_volume') as set_volume:
            self.assertTrue(spotify_mouse.pull_control('d', 'root', 'win', 1, self.REGIONS, 'volume',
                                                       'track', (300, 30, (1300, 530)), False))
        set_volume.assert_called_once()
        self.assertEqual(conky_mouse.region_at(self.REGIONS, 1, 300, 30), 'volume')
        self.assertEqual(conky_mouse.region_at(self.REGIONS, 1, 260, 30), 'volume_icon')   # the speaker
        self.assertIn('volume_icon', spotify_mouse.BUTTONS)                    # pressed, not dragged

    def playing_at(self, level):
        """Has playerctl report `level` as Spotify's volume."""
        self.run_.return_value = mock.Mock(stdout=f'{level}\n')

    def sent(self):
        """The levels set so far (the read is not one)."""
        return [c.args[0][4] for c in self.run_.call_args_list if len(c.args[0]) > 4]

    def click(self):
        spotify_mouse.press('d', 'win', 'volume_icon')

    def test_a_click_on_the_speaker_mutes_and_the_next_restores_the_volume(self):
        self.playing_at(0.72)
        self.click()
        self.assertEqual(self.sent(), ['0'])
        self.assertEqual(support.read(spotify_mouse.VOLUME_BEFORE_MUTE), '0.7200')
        self.assertIn('volume: mute (was 0.72)', support.read(conky_mouse.LOG))
        self.playing_at(0.0)
        self.click()
        self.assertEqual(self.sent(), ['0', '0.72'])
        self.assertFalse(os.path.exists(spotify_mouse.VOLUME_BEFORE_MUTE))
        self.assertIn('volume: unmute (0.72)', support.read(conky_mouse.LOG))

    def test_the_level_is_kept_across_a_restart_while_muted(self):
        with open(spotify_mouse.VOLUME_BEFORE_MUTE, 'w') as f:
            f.write('0.3000')
        self.playing_at(0.0)
        self.click()                                    # a fresh process: only the file remembers
        self.assertEqual(self.sent(), ['0.30'])

    def test_a_click_at_zero_with_nothing_kept_restores_half(self):
        self.playing_at(0.0)                            # the slider dragged to its left end
        self.click()
        self.assertEqual(self.sent(), ['0.50'])

    def test_muting_at_zero_does_not_overwrite_the_kept_level(self):
        with open(spotify_mouse.VOLUME_BEFORE_MUTE, 'w') as f:
            f.write('0.9000')
        self.playing_at(0.0)
        self.click()
        self.assertEqual(self.sent(), ['0.90'])

    def test_the_slider_after_a_mute_follows_the_new_level_and_the_next_click_mutes_it(self):
        self.playing_at(0.8)
        self.click()
        self.playing_at(0.25)                           # dragged or wheeled up from the mute
        self.click()
        self.assertEqual(self.sent(), ['0', '0'])
        self.assertEqual(support.read(spotify_mouse.VOLUME_BEFORE_MUTE), '0.2500')

    def test_a_click_with_spotify_unreadable_does_nothing(self):
        self.run_.return_value = mock.Mock(stdout='')
        self.click()
        self.assertEqual(self.sent(), [])
        self.assertFalse(os.path.exists(spotify_mouse.VOLUME_BEFORE_MUTE))
        self.assertIn('unreadable', support.read(conky_mouse.LOG))


class TapTest(unittest.TestCase):
    # The play button at x 176..208, y 112..144 (logical px).
    REGIONS = {'play': [176.0, 112.0, 208.0, 144.0], 'next': [211.0, 112.0, 235.0, 144.0]}

    def tap(self, end, s=1):
        """A finger down on play at card (190, 128), root (1190, 728), lifted at root `end`."""
        finger = mock.Mock(side_effect=[(1190, 728, True), (*end, False)])
        with mock.patch.object(conky_mouse.time, 'sleep'):
            return conky_mouse.tap(self.REGIONS, s, 190 * s, 128 * s, (1190, 728), 'play', finger)

    def test_lifting_on_the_control_presses_it(self):
        self.assertTrue(self.tap((1190, 728)))
        self.assertTrue(self.tap((1200, 740)))               # moved, but still on it
        self.assertTrue(self.tap((1200, 750), s=2))          # 22 px at scale 2: still on it

    def test_lifting_off_it_does_not(self):
        self.assertFalse(self.tap((1190, 760)))              # below it
        self.assertFalse(self.tap((1215, 728)))              # on next instead


class PullTest(unittest.TestCase):
    REGIONS = {'lyrics': [22, 160, 545, 223], 'lyrics_scroll': ['1234', 5, 20.0],
               'seek': [278.0, 118.0, 388, 142.0], 'duration': 172.5, 'art': [20, 20, 138, 138]}

    def pull(self, hit, edges, at=(100, 180), touch=False, regions=REGIONS, click=True):
        names = ('seek', 'resize', 'swipe', 'drag', 'remember', 'pick_colour', 'clicked')
        theirs = ('seek', 'swipe', 'pick_colour')          # the Spotify widget's own
        with mock.patch.multiple(conky_mouse, **{n: mock.DEFAULT for n in names if n not in theirs}) as m, \
                mock.patch.multiple(spotify_mouse, **{n: mock.DEFAULT for n in theirs}) as t:
            m.update(t)
            m['resize'].return_value = m['drag'].return_value = (1, 2, 3, 4)
            m['clicked'].return_value = click
            conky_mouse.pull('d', 'root', 'win', 1, regions, hit, edges, 'track', (*at, (600, 500)), touch)
            self.calls = m
            return {n for n in names if m[n].called and n != 'clicked'}

    def test_seek_then_art_then_edges_then_lyrics_then_a_move(self):
        self.assertEqual(self.pull('seek', ''), {'seek'})
        self.assertEqual(self.pull('seek', 'r', regions=dict(self.REGIONS, duration=None)),
                         {'resize', 'remember'})              # no track length: the edge wins
        self.assertEqual(self.pull('art', ''), {'pick_colour'})
        self.assertEqual(self.pull(None, 'b', touch=True), {'resize', 'remember'})
        self.assertEqual(self.pull(None, '', touch=True), {'swipe'})
        self.assertEqual(self.pull(None, '', (100, 100), touch=True), {'drag', 'remember'})   # above the lyrics

    def test_the_mouse_moves_the_widget_from_the_lyrics(self):
        self.assertEqual(self.pull(None, ''), {'drag', 'remember'})

    def test_a_drag_from_the_art_moves_the_widget_from_the_press(self):
        self.assertEqual(self.pull('art', '', click=False), {'drag', 'remember'})
        self.assertEqual(self.calls['drag'].call_args.args[-1], (600, 500))

    def test_a_finger_gets_more_slop_on_the_art_than_the_mouse(self):
        self.pull('art', '')
        self.assertEqual(self.calls['clicked'].call_args.args[-1], conky_mouse.CLICK_SLOP)
        self.pull('art', '', touch=True)
        self.assertEqual(self.calls['clicked'].call_args.args[-1], conky_mouse.TAP_SLOP)
        self.assertGreater(conky_mouse.TAP_SLOP, conky_mouse.CLICK_SLOP)


class TouchTest(unittest.TestCase):

    def test_the_mask_sets_one_bit_per_event_type(self):
        mask = conky_mouse.touch_mask(conky_mouse.XI_TOUCH_BEGIN, conky_mouse.XI_TOUCH_UPDATE,
                                      conky_mouse.XI_TOUCH_END)
        self.assertEqual(mask, bytes([0, 0, 0b11100]))      # bits 18, 19 and 20

    def test_the_device_event_matches_the_c_layout(self):
        # XIDeviceEvent on x86-64 (XInput2.h): root_x at byte 88, flags at 120.
        self.assertEqual(conky_mouse.XIDeviceEvent.root_x.offset, 88)
        self.assertEqual(conky_mouse.XIDeviceEvent.flags.offset, 120)
        self.assertEqual(conky_mouse.XGenericEventCookie.data.offset, 48)

    def track(self, events, start=(10, 20)):
        """A Touch for touch id 7 at `start`, reading `events`: (evtype, id, x, y) each."""
        touch = conky_mouse.Touch('d', 131, 7, *start)
        queue = list(events)
        pending = mock.patch.object(conky_mouse.x11, 'XPending', side_effect=lambda d: len(queue))
        nxt = mock.patch.object(conky_mouse.x11, 'XNextEvent')
        read = mock.patch.object(conky_mouse, 'touch_event',
                                 side_effect=lambda d, ev, op: (lambda e: (e[0], e[1], 0, e[2], e[3], 0, 0))(queue.pop(0)))
        with pending, nxt, read:
            return touch()

    def test_it_follows_its_own_finger_until_it_lifts(self):
        B, U, E = conky_mouse.XI_TOUCH_BEGIN, conky_mouse.XI_TOUCH_UPDATE, conky_mouse.XI_TOUCH_END
        self.assertEqual(self.track([]), (10, 20, True))
        self.assertEqual(self.track([(U, 7, 15.4, 25.6)]), (15, 26, True))
        self.assertEqual(self.track([(U, 7, 15, 25), (E, 7, 30, 40)]), (30, 40, False))
        self.assertEqual(self.track([(B, 8, 99, 99), (U, 8, 99, 99)]), (10, 20, True))   # another finger

    def test_a_finger_with_no_end_counts_as_lifted_in_the_end(self):
        touch = conky_mouse.Touch('d', 131, 7, 10, 20)
        touch.last -= conky_mouse.TOUCH_TIMEOUT + 1
        with mock.patch.object(conky_mouse.x11, 'XPending', return_value=0):
            self.assertEqual(touch(), (10, 20, False))


class ArtClickTest(unittest.TestCase):
    HELD, UP = conky_mouse.BUTTON1_MASK, 0

    def test_released_in_place_is_a_click(self):
        pointer = mock.Mock(side_effect=[(102, 101, self.HELD), (103, 101, self.UP)])
        with mock.patch.object(conky_mouse, 'pointer', pointer):
            self.assertTrue(conky_mouse.clicked((100, 100), 1, conky_mouse.follow_pointer(None, 0)))

    def test_moving_past_the_slop_is_a_drag(self):
        pointer = mock.Mock(side_effect=[(102, 100, self.HELD), (105, 100, self.HELD)])
        with mock.patch.object(conky_mouse, 'pointer', pointer):
            self.assertFalse(conky_mouse.clicked((100, 100), 1, conky_mouse.follow_pointer(None, 0)))

    def test_the_slop_follows_the_display_scale(self):
        pointer = mock.Mock(side_effect=[(107, 100, self.HELD), (107, 100, self.UP)])
        with mock.patch.object(conky_mouse, 'pointer', pointer):
            self.assertTrue(conky_mouse.clicked((100, 100), 2, conky_mouse.follow_pointer(None, 0)))

    def test_a_tap_lifted_in_place_is_a_click(self):
        finger = mock.Mock(side_effect=[(102, 101, True), (103, 101, False)])
        self.assertTrue(conky_mouse.clicked((100, 100), 1, finger))
        finger = mock.Mock(side_effect=[(110, 100, True)])
        self.assertFalse(conky_mouse.clicked((100, 100), 1, finger))

    def test_the_art_is_a_region(self):
        regions = {'art': [20, 20, 138, 138], 'heart': None}
        self.assertEqual(conky_mouse.region_at(regions, 2, 100, 100), 'art')
        self.assertIsNone(conky_mouse.region_at(regions, 2, 300, 100))
        self.assertIsNone(conky_mouse.region_at({'art': None}, 1, 50, 50))

    def test_a_click_picks_at_its_place_on_the_art(self):
        with mock.patch.object(spotify_mouse.art_colours, 'pick', return_value=(0.1, 0.2, 0.3)) as pick, \
                mock.patch.object(conky_mouse, 'log') as log:
            spotify_mouse.pick_colour([20, 20, 120, 120], 45, 95)
        pick.assert_called_once_with(0.25, 0.75)
        log.assert_called_once_with('art colour: 0.25,0.75 -> 0.100 0.200 0.300')

    def test_a_failed_pick_is_logged_not_raised(self):
        with mock.patch.object(spotify_mouse.art_colours, 'pick', side_effect=OSError('gone')), \
                mock.patch.object(conky_mouse, 'log') as log:
            spotify_mouse.pick_colour([20, 20, 120, 120], 70, 70)
        self.assertIn('failed', log.call_args[0][0])


class ConfigureTest(unittest.TestCase):

    def test_the_widget_names_its_folders_launcher_and_window(self):
        self.assertEqual(spotify_mouse.NAME, 'conky-spotify-nowplaying')
        self.assertTrue(conky_mouse.POSITION.endswith('/.config/conky-spotify-nowplaying/position'))
        self.assertTrue(conky_mouse.REGIONS.endswith('/.cache/conky-spotify-nowplaying/regions.json'))
        self.assertEqual(conky_mouse.WM_CLASS, 'ConkySpotifyNowPlaying')
        self.assertEqual(conky_mouse.SIZE, os.path.join(conky_mouse.CONF, 'size'))
        self.assertEqual(conky_mouse.HEIGHT_REGION, 'lyrics')     # resizing from the top or bottom

    def test_its_buttons_come_with_minimize_and_close(self):
        self.assertEqual(set(conky_mouse.BUTTONS), {'heart', 'play', 'prev', 'next', 'volume_icon', 'minimize', 'close'})

    def test_the_widget_gets_the_helper_to_share_its_window_handling(self):
        self.assertIs(spotify_mouse.core, conky_mouse)
        self.assertIs(conky_mouse.hooks, spotify_mouse)

    def test_controls_are_looked_through_in_the_widgets_order(self):
        regions = {'seek': [0, 0, 100, 100], 'art': [0, 0, 100, 100]}
        self.assertEqual(conky_mouse.region_at(regions, 1, 50, 50), 'seek')


class LogTest(support.TempDirTest):

    def test_a_line_starts_with_the_date_and_the_time(self):
        self.redirect(conky_mouse, LOG='mouse.log')
        days = {time.strftime('%F')}
        conky_mouse.log('press at 10,20')
        days.add(time.strftime('%F'))                  # the test may straddle midnight
        line = support.read(conky_mouse.LOG)
        self.assertRegex(line, r'^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d press at 10,20\n$')
        self.assertIn(line[:10], days)


if __name__ == '__main__':
    unittest.main()
