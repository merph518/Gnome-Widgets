#!/usr/bin/env python3
"""Cases for list-markers.lua: the labels Word draws on letter and roman lists."""
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

DELETION = 'w:author="Author" w:date="2005-10-17T13:20:00Z"'


def convert(source: pathlib.Path, reader: str) -> list[str]:
    """The lines convert.sh's Pandoc call writes, blank lines dropped."""
    command = ["pandoc", "-f", reader, "-t", "gfm-raw_html-raw_attribute",
               "--columns=100", "--wrap=auto"]
    command += [f"--lua-filter={path}" for path in FILTERS] + [str(source)]
    out = subprocess.run(command, capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line.strip()]


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

    def test_a_digit_list_is_left_as_a_list(self):
        self.assertEqual(self.markdown("1. one\n2. two\n\n    1. sub\n"), [
            "1.  one", "2.  two", "    1.  sub",
        ])

    def test_a_letter_list_in_a_table_cell_stays_text(self):
        text = ("+------+------+\n| Name | Rule |\n+======+======+\n| x    | a. y |\n"
                "|      | b. z |\n+------+------+\n")
        lines = self.markdown(text)
        self.assertEqual(lines[-1], "| x    | y; z |")


if __name__ == "__main__":
    unittest.main()
