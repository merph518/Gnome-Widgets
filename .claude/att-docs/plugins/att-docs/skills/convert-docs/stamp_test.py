#!/usr/bin/env python3
"""Cases for stamp.clean: what it takes off Pandoc's output."""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
SPEC = importlib.util.spec_from_file_location("stamp", HERE / "stamp.py")
STAMP = importlib.util.module_from_spec(SPEC)
# Its dataclasses look their module up by name while the module loads.
sys.modules["stamp"] = STAMP
SPEC.loader.exec_module(STAMP)


class BulletGlyphTest(unittest.TestCase):
    def test_a_glyph_a_slide_drew_goes(self):
        self.assertEqual(STAMP.clean("- • First point\n"), "- First point\n")
        self.assertEqual(STAMP.clean("- o Second point\n"), "- Second point\n")

    def test_a_word_opening_with_o_keeps_its_o(self):
        text = "1.  open the To-Do Detail window\n- one row for each child\n- only this\n"
        self.assertEqual(STAMP.clean(text), text)

    def test_a_bare_o_or_one_before_a_tab_goes(self):
        self.assertEqual(STAMP.clean("text\n- o\n- next\n"), "text\n-\n- next\n")
        self.assertEqual(STAMP.clean("- o\tThird point\n"), "- Third point\n")

    def test_of_and_or_keep_their_o(self):
        text = "- of the stage\n- or the case\n"
        self.assertEqual(STAMP.clean(text), text)


class PagesLineTest(unittest.TestCase):
    def layout(self, **kept):
        return STAMP.pages.Layout(
            10, [], "as LibreOffice lays the document out", **kept)

    def test_a_plain_layout_names_its_source(self):
        self.assertEqual(STAMP.pages_line(self.layout(), []),
                         "- Pages: 10, as LibreOffice lays the document out")

    def test_a_disagreement_is_named(self):
        self.assertEqual(
            STAMP.pages_line(self.layout(marked=6, stored=10), []),
            "- Pages: 10, as LibreOffice lays the document out"
            " (Word's last layout marked 6, its stored count says 10)")

    def test_the_disagreement_comes_before_the_missed_pages(self):
        self.assertEqual(
            STAMP.pages_line(self.layout(marked=6, stored=10), [4]),
            "- Pages: 10, as LibreOffice lays the document out"
            " (Word's last layout marked 6, its stored count says 10),"
            " no marker for page 4, whose opening text was not found")

    def test_an_unread_picture_is_named_beside_the_missed_pages(self):
        self.assertEqual(
            STAMP.pages_line(self.layout(), [4], unread=1),
            "- Pages: 10, as LibreOffice lays the document out,"
            " no marker for page 4, whose opening text was not found,"
            " and the document holds a picture whose text was not read,"
            " which may be where it opens")

    def test_an_unread_picture_with_every_page_found_says_nothing(self):
        self.assertEqual(STAMP.pages_line(self.layout(), [], unread=1),
                         "- Pages: 10, as LibreOffice lays the document out")


if __name__ == "__main__":
    unittest.main()
