#!/usr/bin/env python3
"""Cases for a list that goes on after a table, a picture or a note between its items:
list-numbers.py keeps the items open, and list-markers.lua writes the table and the items
after it back into the list."""
from __future__ import annotations

import importlib.util
import pathlib
import shutil
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
FILTERS = [HERE / "drop-images.lua", HERE / "flatten-tables.lua", HERE / "list-markers.lua"]

# The Word file builders the list-numbers cases already use.
SPEC = importlib.util.spec_from_file_location("list_numbers_test", HERE / "list-numbers_test.py")
WORD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORD)
HIDDEN_SPEC = importlib.util.spec_from_file_location("hidden_text", HERE / "hidden-text.py")
HIDDEN = importlib.util.module_from_spec(HIDDEN_SPEC)
HIDDEN_SPEC.loader.exec_module(HIDDEN)

# A rule list whose lettered items are a level of the same definition, and one
# whose lettered and roman items are a definition of their own drawn under it.
ONE_DEFINITION = [
    WORD.abstract(1, WORD.level(0, left=720),
                  WORD.level(1, fmt="lowerLetter", text="%2.", left=1440),
                  WORD.level(2, fmt="lowerRoman", text="%3.", left=2160)),
    WORD.num(1, 1),
]
TWO_DEFINITIONS = [
    WORD.abstract(1, WORD.level(0, left=720)),
    WORD.abstract(2, WORD.level(0, fmt="lowerLetter", left=1440),
                  WORD.level(1, fmt="lowerRoman", text="%2.", left=2520)),
    WORD.num(1, 1), WORD.num(2, 2),
]
DIGITS = [
    WORD.abstract(1, WORD.level(0, left=720), WORD.level(1, text="%2.", left=1440)),
    WORD.num(1, 1),
]
BULLETS = [
    WORD.abstract(1, WORD.level(0, left=720),
                  WORD.level(1, fmt="bullet", text="\u2022", left=1440)), WORD.num(1, 1),
]


def table(*cells, indent=None, align=None):
    """A one-row table, set `indent` twentieths of a point from the margin."""
    properties = "" if indent is None else f'<w:tblInd w:w="{indent}" w:type="dxa"/>'
    if align:
        properties += f'<w:jc w:val="{align}"/>'
    grid = "".join('<w:gridCol w:w="1440"/>' for _ in cells)
    row = "".join(f"<w:tc>{WORD.para(cell)}</w:tc>" for cell in cells)
    return (f"<w:tbl><w:tblPr>{properties}</w:tblPr><w:tblGrid>{grid}</w:tblGrid>"
            f"<w:tr>{row}</w:tr></w:tbl>")


def empty_run(left):
    """A paragraph with no text that Pandoc still reads as one: it holds an
    empty formatted run, as a paragraph left after a picture does."""
    run = '<w:r><w:rPr><w:highlight w:val="yellow"/></w:rPr></w:r>'
    return f'<w:p><w:pPr><w:ind w:left="{left}"/></w:pPr>{run}</w:p>'


class Converting(unittest.TestCase):
    def setUp(self):
        self.work = pathlib.Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.work)

    def rewrite(self, body, definitions):
        source = self.work / "in.docx"
        visible, target = self.work / "visible.docx", self.work / "out.docx"
        WORD.docx(source, body, definitions)
        self.assertEqual(HIDDEN.main(["hidden-text.py", str(source), str(visible)]), 0)
        self.assertEqual(WORD.LIST.main(["list-numbers.py", str(visible), str(target)]), 0)
        return target

    def word(self, body, definitions) -> list[str]:
        """The lines convert.sh writes for a Word file, blank lines dropped."""
        command = ["pandoc", "-f", "docx", "-t", "gfm-raw_html-raw_attribute",
                   "--columns=100", "--wrap=auto"]
        command += [f"--lua-filter={path}" for path in FILTERS]
        command.append(str(self.rewrite(body, definitions)))
        out = subprocess.run(command, capture_output=True, text=True, check=True).stdout
        return [line for line in out.splitlines() if line.strip()]


class RewriteTest(Converting):
    def items(self, body, definitions):
        """(text, level, number) of each paragraph in a list of the document's own."""
        return [(text, level, number)
                for text, level, number in WORD.drawn(self.rewrite(body, definitions))
                if isinstance(number, int) and number < WORD.LIST.UNNUMBERED_START]

    def frames(self, body, definitions):
        """The levels of the empty items put after each table."""
        return [level for _, level, number in WORD.drawn(self.rewrite(body, definitions))
                if isinstance(number, int) and number >= WORD.LIST.RESUMED_START]

    def test_the_items_after_a_table_in_an_item_keep_their_level_and_count(self):
        body = [WORD.para("rule", 1, 0), WORD.para("first", 1, 1), WORD.para("second", 1, 1),
                table("cell", indent=1440), WORD.para("third", 1, 1), WORD.para("next", 1, 0)]
        self.assertEqual(self.items(body, ONE_DEFINITION), [
            ("rule", 0, 1), ("first", 1, 1), ("second", 1, 2), ("third", 1, 3), ("next", 0, 2),
        ])
        # One empty item for the rule and one for the lettered item the table is in.
        self.assertEqual(self.frames(body, ONE_DEFINITION), [0, 1])

    def test_a_table_that_ends_the_list_is_followed_by_no_empty_items(self):
        body = [WORD.para("rule", 1, 0), WORD.para("first", 1, 1),
                table("cell", indent=1440), WORD.para("next", 1, 0)]
        self.assertEqual(self.frames(body, ONE_DEFINITION), [])

    def test_an_item_that_counts_on_after_text_at_the_margin_keeps_its_level(self):
        body = [WORD.para("rule", 1, 0), WORD.para("first", 2), WORD.para("second", 2),
                WORD.para("at the margin"), WORD.para("third", 2), WORD.para("next", 1, 0)]
        self.assertEqual(self.items(body, TWO_DEFINITIONS), [
            ("rule", 0, 1), ("first", 1, 1), ("second", 1, 2), ("third", 1, 3), ("next", 0, 2),
        ])

    def test_a_list_that_starts_again_after_text_at_the_margin_stays_there(self):
        definitions = TWO_DEFINITIONS + [WORD.num(3, 2, overrides=[(0, 1)])]
        body = [WORD.para("rule", 1, 0), WORD.para("first", 2), WORD.para("second", 2),
                WORD.para("at the margin"), WORD.para("again", 3), WORD.para("next", 1, 0)]
        self.assertEqual(self.items(body, definitions), [
            ("rule", 0, 1), ("first", 1, 1), ("second", 1, 2), ("again", 0, 1), ("next", 0, 2),
        ])

    def test_an_item_that_counts_on_after_a_heading_stays_at_the_margin(self):
        body = [WORD.para("rule", 1, 0), WORD.para("first", 2), WORD.para("second", 2),
                WORD.para("Section", style="Heading1"), WORD.para("third", 2)]
        self.assertEqual(self.items(body, TWO_DEFINITIONS), [
            ("rule", 0, 1), ("first", 1, 1), ("second", 1, 2), ("third", 0, 3),
        ])

    # A level drawn without a number: Pandoc still reads its paragraph as an item.
    UNNUMBERED = [WORD.abstract(9, WORD.level(0, fmt="none", text="")), WORD.num(9, 9)]

    def test_an_item_that_counts_on_after_a_numbered_heading_stays_at_the_margin(self):
        definitions = TWO_DEFINITIONS + [WORD.abstract(8, WORD.level(0)), WORD.num(8, 8)]
        body = [WORD.para("rule", 1, 0), WORD.para("first", 2), WORD.para("second", 2),
                WORD.para("Section", 8, style="Heading1"), WORD.para("third", 2)]
        self.assertEqual(self.items(body, definitions), [
            ("rule", 0, 1), ("first", 1, 1), ("second", 1, 2), ("Section", 0, 1),
            ("third", 0, 3),
        ])

    def test_a_level_drawn_without_a_number_after_a_table_ends_the_list(self):
        body = [WORD.para("rule", 1, 0), WORD.para("first", 2), table("cell", indent=1440),
                WORD.para("unnumbered", 9), WORD.para("second", 2), WORD.para("next", 1, 0)]
        definitions = TWO_DEFINITIONS + self.UNNUMBERED
        self.assertEqual(self.items(body, definitions), [
            ("rule", 0, 1), ("first", 1, 1), ("unnumbered", 0, 1), ("second", 0, 2),
            ("next", 0, 2),
        ])
        self.assertEqual(self.frames(body, definitions), [])

    def test_a_table_after_a_level_drawn_without_a_number_ends_the_list(self):
        body = [WORD.para("rule", 1, 0), WORD.para("first", 2),
                WORD.para("unnumbered", 9, left=1440), table("cell", indent=1440),
                WORD.para("second", 2), WORD.para("next", 1, 0)]
        definitions = TWO_DEFINITIONS + self.UNNUMBERED
        self.assertEqual(self.items(body, definitions), [
            ("rule", 0, 1), ("first", 1, 1), ("unnumbered", 0, 1), ("second", 0, 2),
            ("next", 0, 2),
        ])
        self.assertEqual(self.frames(body, definitions), [])


@unittest.skipUnless(shutil.which("pandoc"), "pandoc is not installed")
class PandocTest(Converting):
    def test_a_table_in_a_lettered_item_leaves_the_items_after_it_nested(self):
        body = [WORD.para("The grid holds:", 1, 0), WORD.para("Name", 1, 1),
                WORD.para("Status, one of:", 1, 1), table("Open", "Closed", indent=1440),
                WORD.para("Date", 1, 1), WORD.para("Owner", 1, 1),
                WORD.para("The next rule.", 1, 0)]
        self.assertEqual(self.word(body, ONE_DEFINITION), [
            "1.  The grid holds:", r"    - a\. Name", r"    - b\. Status, one of:",
            "      | Open | Closed |", "      |------|--------|",
            r"    - c\. Date", r"    - d\. Owner", "2.  The next rule.",
        ])

    def test_a_table_and_a_note_under_a_lettered_item_stay_in_the_rule(self):
        note = ('<w:p><w:pPr><w:ind w:left="720" w:firstLine="720"/></w:pPr>'
                "<w:r><w:t>Note: the code is required.</w:t></w:r></w:p>")
        body = [WORD.para("The grid holds:", 1), WORD.para("Name", 2),
                WORD.para("Status, one of:", 2),
                WORD.para("Open", 2, 1),
                WORD.para("Closed, with a code:", 2, 1),
                table("Code", "Meaning", indent=2718), note,
                WORD.para("Date", 2),
                WORD.para("Owner", 2), WORD.para("The next rule.", 1)]
        self.assertEqual(self.word(body, TWO_DEFINITIONS), [
            "1.  The grid holds:", r"    - a\. Name",
            r"    - b\. Status, one of:",
            r"      - i\. Open",
            r"      - ii\. Closed, with a code:",
            "        | Code | Meaning |", "        |------|---------|",
            "      Note: the code is required.",
            r"    - c\. Date", r"    - d\. Owner",
            "2.  The next rule.",
        ])

    def test_a_note_at_the_margin_between_lettered_items_is_written_inside_the_rule(self):
        body = [WORD.para("The grid holds:", 1), WORD.para("Name", 2), WORD.para("Status", 2),
                WORD.para("Note: sorted by name."), WORD.para("Date", 2),
                WORD.para("The next rule.", 1)]
        self.assertEqual(self.word(body, TWO_DEFINITIONS), [
            "1.  The grid holds:", r"    - a\. Name", r"    - b\. Status",
            "    Note: sorted by name.", r"    - c\. Date", "2.  The next rule.",
        ])

    def test_a_table_at_the_margin_between_lettered_items_is_written_inside_the_rule(self):
        body = [WORD.para("The grid holds:", 1), WORD.para("Name", 2), WORD.para("Status", 2),
                table("Open", "Closed"), WORD.para("Date", 2), WORD.para("The next rule.", 1)]
        self.assertEqual(self.word(body, TWO_DEFINITIONS), [
            "1.  The grid holds:", r"    - a\. Name", r"    - b\. Status",
            "    | Open | Closed |", "    |------|--------|",
            r"    - c\. Date", "2.  The next rule.",
        ])

    def test_a_paragraph_with_no_text_between_lettered_items_keeps_them_together(self):
        body = [WORD.para("The grid holds:", 1, 0), WORD.para("Name", 1, 1),
                empty_run(2880), WORD.para("Status", 1, 1), WORD.para("The next rule.", 1, 0)]
        self.assertEqual(self.word(body, ONE_DEFINITION), [
            "1.  The grid holds:", r"    - a\. Name", r"    - b\. Status", "2.  The next rule.",
        ])

    def test_a_blank_paragraph_and_a_table_in_an_item_stay_in_it(self):
        body = [WORD.para("The grid holds:", 1, 0), WORD.para("Name", 1, 1),
                empty_run(1440), table("Open", "Closed", indent=1440), empty_run(1440),
                WORD.para("Status", 1, 1), WORD.para("The next rule.", 1, 0)]
        self.assertEqual(self.word(body, ONE_DEFINITION), [
            "1.  The grid holds:", r"    - a\. Name",
            "      | Open | Closed |", "      |------|--------|",
            r"    - b\. Status", "2.  The next rule.",
        ])

    def test_a_table_in_a_numbered_sub_item_leaves_one_list_after_it(self):
        body = [WORD.para("The steps:", 1, 0), WORD.para("Open the window", 1, 1),
                WORD.para("Pick a status", 1, 1), table("Open", "Closed", indent=1440),
                WORD.para("Save", 1, 1), WORD.para("The next rule.", 1, 0)]
        self.assertEqual(self.word(body, DIGITS), [
            "1.  The steps:", "    1.  Open the window", "    2.  Pick a status",
            "        | Open | Closed |", "        |------|--------|",
            "    3.  Save", "2.  The next rule.",
        ])

    def test_a_table_in_a_bullet_leaves_the_bullets_after_it_nested(self):
        body = [WORD.para("The fields:", 1, 0), WORD.para("Type", 1, 1),
                table("Home", "Work", indent=1440), WORD.para("Street", 1, 1),
                WORD.para("The next rule.", 1, 0)]
        self.assertEqual(self.word(body, BULLETS), [
            "1.  The fields:", "    - Type", "      | Home | Work |", "      |------|------|",
            "    - Street", "2.  The next rule.",
        ])

    def test_a_table_in_a_rule_with_its_sub_items_after_it_stays_in_the_rule(self):
        body = [WORD.para("The statuses are:", 1, 0), table("Open", "Closed", indent=720),
                WORD.para("Name", 1, 1), WORD.para("The next rule.", 1, 0)]
        self.assertEqual(self.word(body, ONE_DEFINITION), [
            "1.  The statuses are:", "    | Open | Closed |", "    |------|--------|",
            r"    - a\. Name", "2.  The next rule.",
        ])

    def test_two_tables_in_an_item_stay_in_it(self):
        body = [WORD.para("The grid holds:", 1, 0), WORD.para("Name", 1, 1),
                table("Open", "Closed", indent=1440), table("Old", "New", indent=1440),
                WORD.para("Status", 1, 1), WORD.para("The next rule.", 1, 0)]
        self.assertEqual(self.word(body, ONE_DEFINITION), [
            "1.  The grid holds:", r"    - a\. Name",
            "      | Open | Closed |", "      |------|--------|",
            "      | Old | New |", "      |-----|-----|",
            r"    - b\. Status", "2.  The next rule.",
        ])

    def test_a_table_set_in_the_middle_stays_in_the_item_above_it(self):
        body = [WORD.para("The grid holds:", 1, 0), WORD.para("Name", 1, 1),
                table("Open", "Closed", align="center"), WORD.para("Status", 1, 1),
                WORD.para("The next rule.", 1, 0)]
        self.assertEqual(self.word(body, ONE_DEFINITION), [
            "1.  The grid holds:", r"    - a\. Name",
            "      | Open | Closed |", "      |------|--------|",
            r"    - b\. Status", "2.  The next rule.",
        ])

    def test_a_table_after_the_last_item_of_a_list_is_written_after_the_list(self):
        body = [WORD.para("The grid holds:", 1, 0), WORD.para("Name", 1, 1),
                table("Open", "Closed", indent=1440), WORD.para("The next rule.", 1, 0)]
        self.assertEqual(self.word(body, ONE_DEFINITION), [
            "1.  The grid holds:", r"    - a\. Name",
            "| Open | Closed |", "|------|--------|", "2.  The next rule.",
        ])

    def test_a_paragraph_under_a_rule_after_its_table_keeps_both_in_the_rule(self):
        body = [WORD.para("The statuses are:", 1, 0), table("Open", "Closed", indent=720),
                WORD.para("Note: one of the two.", left=720), WORD.para("The next rule.", 1, 0)]
        self.assertEqual(self.word(body, ONE_DEFINITION), [
            "1.  The statuses are:", "    | Open | Closed |", "    |------|--------|",
            "    Note: one of the two.", "2.  The next rule.",
        ])

    def test_a_lettered_list_that_starts_again_after_a_note_at_the_margin_stays_there(self):
        definitions = TWO_DEFINITIONS + [WORD.num(3, 2, overrides=[(0, 1)])]
        body = [WORD.para("The grid holds:", 1), WORD.para("Name", 2), WORD.para("Status", 2),
                WORD.para("Note: sorted by name."), WORD.para("Date", 3)]
        self.assertEqual(self.word(body, definitions), [
            "1.  The grid holds:", r"    - a\. Name", r"    - b\. Status",
            "Note: sorted by name.", r"- a\. Date",
        ])

    def test_a_table_under_a_list_whose_text_is_at_the_margin_ends_the_list(self):
        definitions = [WORD.abstract(1, WORD.level(0, left=0)), WORD.num(1, 1)]
        body = [WORD.para("The first step.", 1), table("Open", "Closed", indent=0),
                WORD.para("Text after the steps."), WORD.para("The second step.", 1)]
        self.assertEqual(self.word(body, definitions), [
            "1.  The first step.", "| Open | Closed |", "|------|--------|",
            "Text after the steps.", "2.  The second step.",
        ])

    def test_a_heading_after_a_table_in_an_item_leaves_the_table_after_the_list(self):
        definitions = ONE_DEFINITION + [
            WORD.abstract(9, WORD.level(0, fmt="none", text="")), WORD.num(9, 9)]
        body = [WORD.para("The statuses are:", 1, 0), table("Open", "Closed", indent=720),
                WORD.para("Assumptions", 9, style="Heading1"),
                WORD.para("Nothing is assumed.", left=720)]
        self.assertEqual(self.word(body, definitions), [
            "1.  The statuses are:", "| Open | Closed |", "|------|--------|",
            "# Assumptions", "> Nothing is assumed.",
        ])


class BodyTextAcrossTablesTest(Converting):
    """Text at the column of the text ahead of a list ends it, and a table in
    an item or a note the list takes back changes neither way."""

    LEAD = [WORD.para("Lead-in.", left=1440), WORD.para("rule", 1, 0), WORD.para("first", 1, 1)]
    GAP = WORD.para("", left=1440)

    def closing(self, body):
        return [row for row in WORD.drawn(self.rewrite(body, ONE_DEFINITION))
                if row[0] == "Closing."]

    def test_text_before_a_table_and_more_of_the_list_stays_in_the_item(self):
        for indent in (0, 1440):
            with self.subTest(indent=indent):
                body = self.LEAD + [WORD.para("second", 1, 1), self.GAP,
                                    WORD.para("Closing.", left=1440), table("cell", indent=indent),
                                    WORD.para("third", 1, 1), WORD.para("next", 1, 0)]
                self.assertEqual(self.closing(body), [("Closing.", None, "continues")])

    def test_text_before_a_table_and_more_of_a_top_level_list_ends_the_list(self):
        # Nothing reopens a list at the margin after a table, so the item after
        # it starts a new list and the text before it is text of the body.
        for indent in (0, None):
            with self.subTest(indent=indent):
                body = [WORD.para("Lead-in.", left=720), WORD.para("rule one", 1, 0),
                        WORD.para("rule two", 1, 0), WORD.para("", left=720),
                        WORD.para("Closing.", left=720), table("cell", indent=indent),
                        WORD.para("rule three", 1, 0)]
                self.assertEqual(self.closing(body), [("Closing.", None, None)])

    def test_text_before_a_table_and_the_next_rule_ends_the_list(self):
        # The lettered list ended at the table, and the rule after it is no
        # lettered item that takes it up again.
        body = self.LEAD + [WORD.para("second", 1, 1), self.GAP, WORD.para("Closing.", left=1440),
                            table("cell", indent=0), WORD.para("next", 1, 0)]
        self.assertEqual(self.closing(body), [("Closing.", None, None)])

    def test_a_table_in_an_item_leaves_the_text_after_the_list_outside_it(self):
        body = self.LEAD + [table("cell", indent=1440), WORD.para("second", 1, 1), self.GAP,
                            WORD.para("Closing.", left=1440)]
        self.assertEqual(self.closing(body), [("Closing.", None, None)])

    def test_a_note_the_list_takes_back_leaves_the_text_after_the_list_outside_it(self):
        body = self.LEAD + [WORD.para("note"), WORD.para("second", 1, 1), self.GAP,
                            WORD.para("Closing.", left=1440)]
        self.assertEqual(self.closing(body), [("Closing.", None, None)])


if __name__ == "__main__":
    unittest.main()
