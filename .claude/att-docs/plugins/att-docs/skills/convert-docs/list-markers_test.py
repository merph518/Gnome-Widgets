#!/usr/bin/env python3
"""Cases for list-markers.lua: the labels Word draws on letter and roman lists, and
the digit lists it keeps apart."""
from __future__ import annotations

import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys
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
sys.path.insert(0, str(HERE))
STAMP_SPEC = importlib.util.spec_from_file_location("stamp", HERE / "stamp.py")
STAMP = importlib.util.module_from_spec(STAMP_SPEC)
# Its dataclasses look their module up by name while the module loads.
sys.modules["stamp"] = STAMP
STAMP_SPEC.loader.exec_module(STAMP)

DELETION = 'w:author="Author" w:date="2005-10-17T13:20:00Z"'


def written(source: pathlib.Path, reader: str) -> str:
    """What convert.sh's Pandoc call writes."""
    command = ["pandoc", "-f", reader, "-t", "gfm-raw_html-raw_attribute",
               "--columns=100", "--wrap=auto"]
    command += [f"--lua-filter={path}" for path in FILTERS] + [str(source)]
    return subprocess.run(command, capture_output=True, text=True, check=True).stdout


def convert(source: pathlib.Path, reader: str) -> list[str]:
    """The lines convert.sh's Pandoc call writes, blank lines dropped."""
    return [line for line in written(source, reader).splitlines() if line.strip()]


def read_back(markdown: str) -> list[list[int]]:
    """The numbers a Markdown reader gives the items of each digit list at the
    margin, once the stamping step has cleaned the text."""
    tree = json.loads(subprocess.run(
        ["pandoc", "-f", "gfm", "-t", "json"], input=STAMP.clean(markdown),
        capture_output=True, text=True, check=True).stdout)
    return [[block["c"][0][0] + index for index in range(len(block["c"][1]))]
            for block in tree["blocks"] if block["t"] == "OrderedList"]


def deleted_para(text, num_id, ilvl=0):
    """A numbered paragraph deleted, mark and all, with its changes tracked."""
    return (f'<w:p><w:pPr><w:numPr><w:ilvl w:val="{ilvl}"/><w:numId w:val="{num_id}"/>'
            f'</w:numPr><w:rPr><w:del w:id="1" {DELETION}/></w:rPr></w:pPr>'
            f'<w:del w:id="2" {DELETION}><w:r><w:delText>{text}</w:delText></w:r></w:del></w:p>')


@unittest.skipUnless(shutil.which("pandoc"), "pandoc is not installed")
class MarkerTest(unittest.TestCase):
    def setUp(self):
        self.work = pathlib.Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.work)

    def markdown(self, text: str) -> list[str]:
        source = self.work / "in.md"
        source.write_text(text, encoding="utf-8")
        return convert(source, "markdown")

    def word(self, body, definitions) -> list[str]:
        """What convert.sh writes for a Word file: its two rewrites, then Pandoc."""
        source = self.work / "in.docx"
        visible, target = self.work / "visible.docx", self.work / "out.docx"
        WORD.docx(source, body, definitions)
        self.assertEqual(HIDDEN.main(["hidden-text.py", str(source), str(visible)]), 0)
        self.assertEqual(WORD.LIST.main(["list-numbers.py", str(visible), str(target)]), 0)
        return convert(target, "docx")

    def test_a_word_letter_list_under_a_numbered_item_keeps_its_letters(self):
        definitions = [
            WORD.abstract(1, WORD.level(0, left=720),
                          WORD.level(1, fmt="lowerLetter", text="%2.", left=1440)),
            WORD.num(1, 1),
        ]
        body = [WORD.para("The grid holds these columns:", 1, 0),
                WORD.para("Select check box", 1, 1), WORD.para("Resource Name", 1, 1),
                WORD.para("The grid is sorted.", 1, 0)]
        self.assertEqual(self.word(body, definitions), [
            "1.  The grid holds these columns:", r"    - a\. Select check box",
            r"    - b\. Resource Name", "2.  The grid is sorted.",
        ])

    def test_a_letter_list_word_continues_across_rules_keeps_counting(self):
        definitions = [
            WORD.abstract(1, WORD.level(0, left=720),
                          WORD.level(1, fmt="lowerLetter", text="%2.", left=1440, restart=0)),
            WORD.num(1, 1),
        ]
        body = [WORD.para("Rule four", 1, 0), WORD.para("first", 1, 1),
                WORD.para("Rule five", 1, 0), WORD.para("second", 1, 1)]
        self.assertEqual(self.word(body, definitions), [
            "1.  Rule four", r"    - a\. first", "2.  Rule five", r"    - b\. second",
        ])

    def test_a_word_roman_list_keeps_its_numerals(self):
        definitions = [
            WORD.abstract(1, WORD.level(0, left=720)),
            WORD.abstract(2, WORD.level(0, fmt="lowerRoman", text="%1.", left=1620)),
            WORD.num(1, 1), WORD.num(2, 2),
        ]
        body = [WORD.para("one", 1), WORD.para("sub one", 2), WORD.para("sub two", 2),
                WORD.para("two", 1)]
        self.assertEqual(self.word(body, definitions), [
            "1.  one", r"    - i\. sub one", r"    - ii\. sub two", "2.  two",
        ])

    def test_an_item_deleted_with_its_changes_tracked_takes_no_letter(self):
        definitions = [
            WORD.abstract(1, WORD.level(0, left=720),
                          WORD.level(1, fmt="lowerLetter", text="%2.", left=1440)),
            WORD.num(1, 1),
        ]
        body = [WORD.para("Menu Items:", 1, 0), WORD.para("File Close", 1, 1),
                deleted_para("Go To Progress Notes", 1, 1),
                deleted_para("Go To Contacts", 1, 1), WORD.para("Help About", 1, 1),
                WORD.para("Technical Note", 1, 0)]
        self.assertEqual(self.word(body, definitions), [
            "1.  Menu Items:", r"    - a\. File Close", r"    - b\. Help About",
            "2.  Technical Note",
        ])

    def test_upper_case_and_delimiters_follow_the_list(self):
        # The writer escapes punctuation that could open Markdown syntax.
        self.assertEqual(self.markdown("A) first\nB) second\n\n(iv) fourth\n(v) fifth\n"), [
            r"- A\) first", r"- B\) second", r"- \(iv\) fourth", r"- \(v\) fifth",
        ])

    def test_a_letter_list_starting_late_runs_past_z(self):
        self.assertEqual(self.markdown("c. third\nd. fourth\n")[0], r"- c\. third")
        definitions = [
            WORD.abstract(1, WORD.level(0, fmt="lowerLetter", text="%1.", left=720, start=26)),
            WORD.num(1, 1),
        ]
        body = [WORD.para("last", 1), WORD.para("next", 1)]
        # The writer escapes `z.`, which could open a list, and leaves `aa.`.
        self.assertEqual(self.word(body, definitions), [r"- z\. last", "- aa. next"])

    def test_the_rest_of_an_item_stays_nested_under_its_label(self):
        text = ("1.  rule\n\n    a.  item\n\n        more about it\n\n        i.  deeper\n\n"
                "    b.  next\n")
        self.assertEqual(self.markdown(text), [
            "1.  rule", r"    - a\. item", "      more about it", r"      - i\. deeper",
            r"    - b\. next",
        ])

    def test_a_bullet_list_under_a_lettered_item_stays_under_it(self):
        text = ("1.  rule\n\n    a.  returned\n\n        - Mother\n        - Father\n\n"
                "    b.  next\n")
        self.assertEqual(self.markdown(text), [
            "1.  rule", r"    - a\. returned", "      - Mother", "      - Father",
            r"    - b\. next",
        ])

    def test_an_item_opening_with_a_list_keeps_its_label_first(self):
        text = "a.  - inner one\n    - inner two\nb.  plain\n"
        self.assertEqual(self.markdown(text), [
            r"- a\.", "  - inner one", "  - inner two", r"- b\. plain",
        ])

    def test_a_labeled_list_joins_the_bullet_lists_beside_it(self):
        text = "- Funding\n- Placement\n\na. If navigation\n\n- Adoption\n"
        self.assertEqual(self.markdown(text), [
            "- Funding", "- Placement", r"- a\. If navigation", "- Adoption",
        ])

    def test_two_plain_bullet_lists_stay_apart(self):
        source = self.work / "in.native"
        source.write_text('[BulletList [[Plain [Str "one"]]], BulletList [[Plain [Str "two"]]]]',
                          encoding="utf-8")
        self.assertEqual(convert(source, "native"), ["- one", "&nbsp;", "- two"])

    def native(self, text: str) -> list[str]:
        source = self.work / "in.native"
        source.write_text(text, encoding="utf-8")
        return convert(source, "native")

    def test_two_digit_lists_in_a_row_stay_apart(self):
        text = ('[OrderedList (2,Decimal,Period) [[Plain [Str "title"]]],'
                ' OrderedList (1,Decimal,Period) [[Plain [Str "one"]], [Plain [Str "two"]]]]')
        self.assertEqual(self.native(text), ["2.  title", "<!-- -->", "1.  one", "2.  two"])

    def test_digit_lists_in_a_row_under_an_item_stay_apart(self):
        text = ('[OrderedList (1,Decimal,Period) [[Plain [Str "rule"],'
                ' OrderedList (1,Decimal,Period) [[Plain [Str "first"]]],'
                ' OrderedList (1,Decimal,Period) [[Plain [Str "again"]]]]]]')
        self.assertEqual(self.native(text), [
            "1.  rule", "    1.  first", "    <!-- -->", "    1.  again",
        ])

    def test_a_paragraph_left_empty_keeps_two_digit_lists_apart(self):
        # A paragraph holding only a bookmark writes nothing once the bookmark is unwrapped.
        text = ('[OrderedList (1,Decimal,Period) [[Plain [Str "one"]]],'
                ' Para [Span ("_Ref1",[],[]) []],'
                ' OrderedList (1,Decimal,Period) [[Plain [Str "again"]]]]')
        self.assertEqual(self.native(text), ["1.  one", "<!-- -->", "1.  again"])

    def test_a_digit_list_that_counts_on_from_the_one_before_takes_no_comment(self):
        text = ('[OrderedList (1,Decimal,Period) [[Plain [Str "one"]], [Plain [Str "two"]]],'
                ' Para [Span ("_Ref1",[],[]) []],'
                ' OrderedList (3,Decimal,Period) [[Plain [Str "three"]]]]')
        self.assertEqual(self.native(text), ["1.  one", "2.  two", "3.  three"])

    def test_a_digit_list_and_a_lettered_list_in_a_row_take_no_comment(self):
        text = ('[OrderedList (1,Decimal,Period) [[Plain [Str "one"]]],'
                ' OrderedList (1,LowerAlpha,Period) [[Plain [Str "first"]]]]')
        self.assertEqual(self.native(text), ["1.  one", r"- a\. first"])

    def test_a_reader_counts_a_word_list_after_a_numbered_title_from_its_own_start(self):
        # FA Home Demographics: a section title numbered on one list, then the
        # section's rules numbered from 1 on another at the same indent.
        definitions = [WORD.abstract(1, WORD.level(0, left=720)),
                       WORD.abstract(2, WORD.level(0, left=720)), WORD.num(1, 1), WORD.num(2, 2)]
        body = [WORD.para("Change Description", 1), WORD.para("What the change is."),
                WORD.para("Business Rules", 1), WORD.para("first rule", 2),
                WORD.para("second rule", 2)]
        source = self.work / "in.docx"
        target = self.work / "out.docx"
        WORD.docx(source, body, definitions)
        self.assertEqual(WORD.LIST.main(["list-numbers.py", str(source), str(target)]), 0)
        self.assertEqual(read_back(written(target, "docx")), [[1], [2], [1, 2]])

    def test_a_digit_list_is_left_as_a_list(self):
        self.assertEqual(self.markdown("1. one\n2. two\n\n    1. sub\n"), [
            "1.  one", "2.  two", "    1.  sub",
        ])

    def test_a_letter_list_in_a_table_cell_stays_text(self):
        text = ("+------+------+\n| Name | Rule |\n+======+======+\n| x    | a. y |\n"
                "|      | b. z |\n+------+------+\n")
        lines = self.markdown(text)
        self.assertEqual(lines[-1], "| x    | y; z |")

    BULLETS = [
        WORD.abstract(1, WORD.level(0, left=720),
                      WORD.level(1, fmt="bullet", text="\u2022", left=1440)), WORD.num(1, 1),
    ]

    def test_a_paragraph_after_a_sub_list_is_written_under_the_rule(self):
        body = [WORD.para("The required fields are:", 1, 0), WORD.para("Type", 1, 1),
                WORD.para("Street", 1, 1), WORD.para("Note: Type is required.", left=720),
                WORD.para("The next rule.", 1, 0)]
        self.assertEqual(self.word(body, self.BULLETS), [
            "1.  The required fields are:", "    - Type", "    - Street",
            "    Note: Type is required.", "2.  The next rule.",
        ])

    def test_a_paragraph_nearer_the_last_sub_items_text_stays_under_it(self):
        body = [WORD.para("The required fields are:", 1, 0), WORD.para("Type", 1, 1),
                WORD.para("Street", 1, 1), WORD.para("Both lines of it.", left=1320),
                WORD.para("Note: Type is required.", left=720),
                WORD.para("The next rule.", 1, 0)]
        self.assertEqual(self.word(body, self.BULLETS), [
            "1.  The required fields are:", "    - Type", "    - Street",
            "      Both lines of it.", "    Note: Type is required.", "2.  The next rule.",
        ])

    def test_two_paragraphs_after_a_sub_list_are_both_written_under_the_rule(self):
        body = [WORD.para("The required fields are:", 1, 0), WORD.para("Type", 1, 1),
                WORD.para("Note: Type is required.", left=720),
                WORD.para("See the standards.", left=720), WORD.para("Street", 1, 1),
                WORD.para("The next rule.", 1, 0)]
        self.assertEqual(self.word(body, self.BULLETS), [
            "1.  The required fields are:", "    - Type", "    Note: Type is required.",
            "    See the standards.", "    - Street", "2.  The next rule.",
        ])

    def test_a_letter_list_goes_on_after_a_paragraph_of_the_rule(self):
        definitions = [
            WORD.abstract(1, WORD.level(0, left=720),
                          WORD.level(1, fmt="lowerLetter", text="%2.", left=1440)),
            WORD.num(1, 1),
        ]
        body = [WORD.para("The grid holds:", 1, 0), WORD.para("Name", 1, 1),
                WORD.para("Status", 1, 1), WORD.para("Note: sorted by name.", left=720),
                WORD.para("Date", 1, 1), WORD.para("The next rule.", 1, 0)]
        self.assertEqual(self.word(body, definitions), [
            "1.  The grid holds:", r"    - a\. Name", r"    - b\. Status",
            "    Note: sorted by name.", r"    - c\. Date", "2.  The next rule.",
        ])

    def test_a_paragraph_after_sub_lists_two_deep_is_written_where_it_lines_up(self):
        definitions = [
            WORD.abstract(1, WORD.level(0, left=720), WORD.level(1, left=1440),
                          WORD.level(2, fmt="bullet", text="\u2022", left=2160)),
            WORD.num(1, 1),
        ]
        nested = [WORD.para("Rule", 1, 0), WORD.para("Step", 1, 1), WORD.para("Detail", 1, 2)]
        self.assertEqual(
            self.word(nested + [WORD.para("About the rule.", left=720)], definitions),
            ["1.  Rule", "    1.  Step", "        - Detail", "    About the rule."])
        self.assertEqual(
            self.word(nested + [WORD.para("About the step.", left=1440)], definitions),
            ["1.  Rule", "    1.  Step", "        - Detail", "        About the step."])

    def test_a_list_at_the_highest_start_word_takes_stays_a_list(self):
        self.assertEqual(self.markdown("32767. last\n"), ["32767. last"])


if __name__ == "__main__":
    unittest.main()
