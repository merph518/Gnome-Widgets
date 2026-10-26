"""Tests for art_colours.py: the colour taken from a click on the album art, and keeping it
per artwork."""
import json
import os
import unittest
from unittest import mock

import support

import art_colours  # noqa: E402  (support puts src/ on the path)

import gi  # noqa: E402
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf, GLib  # noqa: E402

URL = 'https://i.scdn.co/image/ab67616d0000b273'


class ArtColoursTest(support.TempDirTest):

    def setUp(self):
        super().setUp()
        self.redirect(art_colours, COLOURS='conf/art-colours.json', COVER='cover.png',
                      COVER_URL='cover.url', BG='bg.txt')

    def cover(self, pixel, size=100):
        """Saves the shown cover, whose pixel (x, y) is pixel(x, y) -> (r, g, b), 0-255."""
        data = bytes(c for y in range(size) for x in range(size) for c in pixel(x, y))
        pb = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(data), GdkPixbuf.Colorspace.RGB,
                                             False, 8, size, size, size * 3)
        pb.savev(art_colours.COVER, 'png', [], [])
        with open(art_colours.COVER_URL, 'w') as f:
            f.write(URL)

    def test_the_colour_under_the_click(self):
        self.cover(lambda x, y: (255, 0, 0) if x < 50 else (0, 0, 255))
        self.assertEqual(art_colours.colour_at(art_colours.COVER, 0.2, 0.5), (1.0, 0.0, 0.0))
        self.assertEqual(art_colours.colour_at(art_colours.COVER, 0.8, 0.5), (0.0, 0.0, 1.0))

    def test_a_colour_the_cover_has_never_a_blend(self):
        # Right on the boundary the spot holds both colours; the pick is one of them.
        self.cover(lambda x, y: (255, 0, 0) if x < 50 else (0, 0, 255))
        self.assertIn(art_colours.colour_at(art_colours.COVER, 0.5, 0.5), [(1.0, 0.0, 0.0), (0.0, 0.0, 1.0)])

    def test_a_stray_pixel_is_not_the_colour(self):
        self.cover(lambda x, y: (255, 255, 255) if (x, y) == (50, 50) else (0, 128, 0))
        self.assertEqual(art_colours.colour_at(art_colours.COVER, 0.5, 0.5), (0.0, 128 / 255, 0.0))

    def test_the_edges_clamp(self):
        self.cover(lambda x, y: (0, 0, 255))
        for fx, fy in ((0, 0), (1, 1), (-0.1, 1.2)):
            with self.subTest(fx=fx, fy=fy):
                self.assertEqual(art_colours.colour_at(art_colours.COVER, fx, fy), (0.0, 0.0, 1.0))

    def test_a_pick_sets_the_background_and_is_kept_for_the_art(self):
        self.cover(lambda x, y: (0, 0, 255))
        self.assertEqual(art_colours.pick(0.5, 0.5), (0.0, 0.0, 1.0))
        self.assertEqual(support.read(art_colours.BG), '0.000 0.000 1.000\n')
        self.assertEqual(art_colours.chosen(URL), (0.0, 0.0, 1.0))
        self.assertIsNone(art_colours.chosen('https://i.scdn.co/image/other'))
        self.assertEqual(os.listdir(os.path.dirname(art_colours.COLOURS)), ['art-colours.json'])

    def test_a_later_pick_replaces_the_earlier_and_others_stay(self):
        os.makedirs(os.path.dirname(art_colours.COLOURS))
        with open(art_colours.COLOURS, 'w') as f:
            json.dump({'other': [0.5, 0.5, 0.5], URL: [1, 0, 0]}, f)
        self.cover(lambda x, y: (0, 0, 255))
        art_colours.pick(0.5, 0.5)
        self.assertEqual(art_colours.load(), {'other': [0.5, 0.5, 0.5], URL: [0.0, 0.0, 1.0]})

    def test_the_placeholder_keeps_no_pick(self):
        self.cover(lambda x, y: (0, 0, 255))
        with open(art_colours.COVER_URL, 'w') as f:
            f.write(art_colours.NO_ART_URL)
        self.assertIsNone(art_colours.pick(0.5, 0.5))
        self.assertEqual(art_colours.load(), {})
        self.assertFalse(os.path.exists(art_colours.BG))

    def test_a_cover_changing_under_the_pick_keeps_nothing(self):
        self.cover(lambda x, y: (0, 0, 255))
        sample = art_colours.colour_at

        def changed(*args):
            os.remove(art_colours.COVER_URL)          # as fetch_cover does before the new cover
            return sample(*args)
        with mock.patch.object(art_colours, 'colour_at', changed):
            self.assertIsNone(art_colours.pick(0.5, 0.5))
        self.assertEqual(art_colours.load(), {})
        self.assertFalse(os.path.exists(art_colours.BG))

    def test_no_cover_is_no_pick(self):
        self.assertIsNone(art_colours.pick(0.5, 0.5))
        self.assertFalse(os.path.exists(art_colours.BG))

    def test_a_bad_file_or_entry_is_no_choice(self):
        os.makedirs(os.path.dirname(art_colours.COLOURS))
        for text in ('not json', '[1, 2]', json.dumps({URL: 'red'}), json.dumps({URL: [1, 2]})):
            with self.subTest(text=text):
                with open(art_colours.COLOURS, 'w') as f:
                    f.write(text)
                self.assertIsNone(art_colours.chosen(URL))
        self.assertIsNone(art_colours.chosen(''))


if __name__ == '__main__':
    unittest.main()
