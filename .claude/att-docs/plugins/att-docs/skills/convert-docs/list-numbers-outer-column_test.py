#!/usr/bin/env python3
"""Cases for list-numbers.py: what Word draws at an outer column after a list
item stays out of that item."""
from __future__ import annotations

import importlib.util
import pathlib
import shutil
import subprocess
import unittest

HERE = pathlib.Path(__file__).resolve().parent

# The Word file builders the list-numbers cases already use.
SPEC = importlib.util.spec_from_file_location("list_numbers_test", HERE / "list-numbers_test.py")
WORD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORD)

abstract, level, num, para, drawn = WORD.abstract, WORD.level, WORD.num, WORD.para, WORD.drawn

# Rules numbered at the margin, and a lettered list under them whose second
# level is a digit list. `second` is where that level's number is drawn.
RULES = abstract(1, level(0, left=360))


def lettered(second, start=2):
    return abstract(2, level(0, fmt="lowerLetter", text="%1)", left=720),
                    level(1, left=second + 360, start=start))


# Steps whose numbers hang left of the text around them, and bullets drawn at
# the column of that text.
STEPS = [abstract(1, level(0, left=720)), abstract(2, level(0, fmt="bullet", left=1080)),
         num(1, 1), num(2, 2)]

# LibreOffice leaves an empty formatted run in a blank paragraph, and Pandoc
# keeps a paragraph that holds one.
BLANK = ('<w:p><w:pPr><w:ind w:left="720"/></w:pPr>'
         '<w:r><w:rPr><w:highlight w:val="yellow"/></w:rPr></w:r></w:p>')


class DeeperLevelTest(WORD.Rewriting):
    def test_a_deeper_level_drawn_beside_the_rule_its_item_is_under_leaves_the_item(self):
        # Word draws the lettered item at 360 and the level under it at the
        # margin, in the column of the rules' numbers and numbered with digits
        # as they are, so that level is a run of rules.
        definitions = [RULES, lettered(0), num(1, 1), num(2, 2)]
        body = [para("rule one", 1), para("rule two", 1), para("lettered", 2, 0),
                para("second two", 2, 1), para("rule three", 2, 1)]
        self.assertEqual(self.items(body, definitions), [
            ("rule one", 0, 1), ("rule two", 0, 2), ("lettered", 1, 1),
            ("second two", 0, 2), ("rule three", 0, 3),
        ])

    def test_a_paragraphs_own_indent_draws_the_deeper_level_beside_the_rule(self):
        # The level is defined under the lettered item. Each paragraph's own
        # indent draws it at the margin.
        definitions = [RULES, lettered(1440), num(1, 1), num(2, 2)]
        body = [para("rule one", 1), para("lettered", 2, 0),
                para("second two", 2, 1, left=360, hanging=360),
                para("rule three", 2, 1, left=1440, hanging=1440)]
        self.assertEqual(self.items(body, definitions), [
            ("rule one", 0, 1), ("lettered", 1, 1), ("second two", 0, 2), ("rule three", 0, 3),
        ])

    def test_the_same_kind_of_number_in_the_items_number_column_is_beside_the_item(self):
        # The third level is numbered with digits and drawn in the column of
        # the rules' numbers, so Word draws its items as more rules.
        definitions = [abstract(1, level(0, left=360),
                                level(1, fmt="lowerLetter", text="%2)", left=720),
                                level(2, left=360, start=3)), num(1, 1)]
        body = [para("rule one", 1), para("rule two", 1), para("lettered", 1, 1),
                para("rule three", 1, 2), para("rule four", 1, 2)]
        self.assertEqual(self.items(body, definitions), [
            ("rule one", 0, 1), ("rule two", 0, 2), ("lettered", 1, 1),
            ("rule three", 0, 3), ("rule four", 0, 4),
        ])

    def test_letters_and_bullets_in_the_items_number_column_stay_under_the_item(self):
        for fmt in ("lowerLetter", "bullet"):
            definitions = [abstract(1, level(0, left=360), level(1, fmt=fmt, left=360)),
                           num(1, 1)]
            body = [para("rule one", 1), para("under it", 1, 1), para("rule two", 1)]
            self.assertEqual(self.items(body, definitions), [
                ("rule one", 0, 1), ("under it", 1, 1), ("rule two", 0, 2),
            ], fmt)

    def test_letters_drawn_left_of_their_rules_number_stay_under_the_rule(self):
        # The letters sit left of the number of the rule they follow, beside no
        # item they could be one more of.
        definitions = [abstract(1, level(0, left=1620), level(1, fmt="lowerLetter", left=1440)),
                       num(1, 1)]
        body = [para("rule one", 1), para("lettered", 1, 1), para("rule two", 1)]
        self.assertEqual(self.items(body, definitions), [
            ("rule one", 0, 1), ("lettered", 1, 1), ("rule two", 0, 2),
        ])

    def test_a_list_at_the_text_of_the_items_first_line_is_under_the_item(self):
        # The rule hangs far to the right, and a tab stop it sets right after
        # its number is where Word starts its text. A list drawn at that stop
        # is under the rule. Without the stop it is left of the rule's text.
        definitions = [abstract(1, level(0, left=1440, hanging=1440)),
                       abstract(2, level(0, fmt="lowerLetter", left=720)), num(1, 1), num(2, 2)]
        for stops, depth in (('<w:tabs><w:tab w:val="left" w:pos="360"/></w:tabs>', 1), ("", 0)):
            rule = (f'<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>'
                    f'{stops}</w:pPr><w:r><w:t>rule</w:t></w:r></w:p>')
            body = [rule, para("lettered", 2)]
            self.assertEqual(self.items(body, definitions), [
                ("rule", 0, 1), ("lettered", depth, 1),
            ], stops)

    def test_another_kind_of_number_in_the_column_of_the_items_number_stays_under_it(self):
        definitions = [RULES, lettered(360), num(1, 1), num(2, 2)]
        body = [para("rule one", 1), para("lettered", 2, 0), para("under it", 2, 1),
                para("rule two", 1)]
        self.assertEqual(self.items(body, definitions), [
            ("rule one", 0, 1), ("lettered", 1, 1), ("under it", 2, 2), ("rule two", 0, 2),
        ])

    def test_a_deeper_level_drawn_past_the_items_text_stays_under_the_item(self):
        definitions = [RULES, lettered(1080), num(1, 1), num(2, 2)]
        body = [para("rule one", 1), para("lettered", 2, 0), para("under it", 2, 1),
                para("rule two", 1)]
        self.assertEqual(self.items(body, definitions), [
            ("rule one", 0, 1), ("lettered", 1, 1), ("under it", 2, 2), ("rule two", 0, 2),
        ])


class BodyTextTest(WORD.Rewriting):
    def after(self, body, count):
        """How the last `count` paragraphs are drawn."""
        return drawn(self.rewrite(body, STEPS))[-count:]

    def test_text_at_the_column_of_the_text_ahead_of_a_list_ends_the_list(self):
        # The text around the steps is indented to 720, where the steps' own
        # text starts, and their numbers hang left of it. What follows the last
        # step at 720, after a blank paragraph, is that text going on, and the
        # bullets after it are a list of the body.
        body = [para("Lead-in.", left=720), para("step one", 1), para("step two", 1), BLANK,
                para("Closing.", left=720), BLANK, para("A title", left=720),
                para("bullet", 2)]
        self.assertEqual(self.after(body, 5), [
            ("", None, None), ("Closing.", None, None), ("", None, None),
            ("A title", None, None), ("bullet", 0, 1),
        ])

    def test_text_at_that_column_between_two_items_stays_in_the_item(self):
        body = [para("Lead-in.", left=720), para("step one", 1), BLANK,
                para("more about one", left=720), para("step two", 1)]
        self.assertEqual(self.after(body, 3), [
            ("", None, "continues"), ("more about one", None, "continues"), ("step two", 0, 2),
        ])

    def test_text_right_under_the_last_item_stays_in_the_item(self):
        # No blank paragraph sets it off from the step.
        body = [para("Lead-in.", left=720), para("step one", 1), para("step two", 1),
                para("more about two", left=720)]
        self.assertEqual(self.after(body, 1), [("more about two", None, "continues")])

    def test_text_after_a_sub_list_of_the_last_item_goes_to_the_item_it_starts_nearest(self):
        # A lettered item was read after the step, so the paragraph is placed
        # as any paragraph after a sub-list is: under the step, after the
        # letters. A second one, after another blank paragraph, stays with it.
        definitions = [abstract(1, level(0, left=720), level(1, fmt="lowerLetter", left=1440)),
                       num(1, 1)]
        body = [para("Lead-in.", left=720), para("step one", 1), para("lettered", 1, 1), BLANK,
                para("more about one", left=720), BLANK, para("and more", left=720)]
        self.assertEqual(drawn(self.rewrite(body, definitions))[-3:], [
            ("more about one", 1, WORD.LIST.UNNUMBERED_START), ("", None, "continues"),
            ("and more", None, "continues"),
        ])

    def test_text_before_a_list_drawn_beside_the_last_item_stays_in_the_item(self):
        # The list after the paragraph is of another definition, and Word draws
        # it in the column of the steps' numbers with the same kind of number,
        # so the steps go on and the paragraph is still inside step one.
        definitions = STEPS + [abstract(3, level(0, left=720)), num(3, 3)]
        body = [para("Lead-in.", left=720), para("step one", 1), BLANK,
                para("more about one", left=720), para("another step", 3)]
        self.assertEqual(drawn(self.rewrite(body, definitions))[-2:], [
            ("more about one", None, "continues"), ("another step", 0, 1),
        ])

    def test_text_before_a_sub_item_of_the_last_item_stays_in_the_item(self):
        definitions = [abstract(1, level(0, left=720), level(1, fmt="lowerLetter", left=1440)),
                       num(1, 1)]
        body = [para("Lead-in.", left=720), para("step one", 1), BLANK,
                para("more about one", left=720), para("lettered", 1, 1)]
        self.assertEqual(drawn(self.rewrite(body, definitions))[-2:], [
            ("more about one", None, "continues"), ("lettered", 1, 1),
        ])

    def test_text_before_a_sub_list_and_a_later_item_stays_in_the_item(self):
        # The bullets after the paragraph are a list of their own, and the
        # steps go on after them, so the paragraph is still inside step one.
        body = [para("Lead-in.", left=720), para("step one", 1), BLANK,
                para("more about one", left=720), para("bullet", 2), para("step two", 1)]
        self.assertEqual(self.after(body, 3), [
            ("more about one", None, "continues"), ("bullet", 1, 1), ("step two", 0, 2),
        ])

    def test_text_drawn_past_the_last_items_text_stays_in_the_item(self):
        # The paragraph ahead of the list is indented to 1440. The one after
        # the last step starts there too, past the step's text at 720, so Word
        # draws it inside the step.
        body = [para("Lead-in.", left=1440), para("step one", 1), para("step two", 1), BLANK,
                para("more about two", left=1440)]
        self.assertEqual(self.after(body, 1), [("more about two", None, "continues")])

    def test_text_indented_past_the_text_ahead_of_the_list_stays_in_the_item(self):
        body = [para("Lead-in.", left=0), para("step one", 1), BLANK,
                para("more about one", left=720)]
        self.assertEqual(self.after(body, 1), [("more about one", None, "continues")])

    def test_a_list_with_no_text_ahead_of_it_keeps_its_indented_paragraph(self):
        body = [para("step one", 1), BLANK, para("more about one", left=720)]
        self.assertEqual(self.after(body, 1), [("more about one", None, "continues")])

    def test_text_ahead_of_a_heading_or_a_table_does_not_set_the_column(self):
        for between in (para("Section", style="Heading1"), WORD.table(para("cell"))):
            body = [para("Lead-in.", left=720), between, para("step one", 1), BLANK,
                    para("more about one", left=720)]
            self.assertEqual(self.after(body, 1), [("more about one", None, "continues")])

    def test_text_inside_an_item_does_not_set_the_column(self):
        # The paragraph at 1080 is in rule one, so it is not text of the body,
        # and the paragraph after the lettered item at 1080 stays in that item.
        definitions = [abstract(1, level(0, left=360)),
                       abstract(2, level(0, fmt="lowerLetter", left=1080)), num(1, 1), num(2, 2)]
        body = [para("Lead-in.", left=0), para("rule one", 1), para("more", left=1080),
                para("lettered", 2), BLANK, para("more about it", left=1080)]
        self.assertEqual(drawn(self.rewrite(body, definitions))[-1:], [
            ("more about it", None, "continues"),
        ])


@unittest.skipUnless(shutil.which("pandoc"), "pandoc is not installed")
class PandocTest(WORD.Rewriting):
    def lines(self, body, definitions):
        """The lines Pandoc writes with the filter that reads the rewrite's marks."""
        target = self.rewrite(body, definitions)
        out = subprocess.run(["pandoc", "-f", "docx", "-t", "gfm",
                              f"--lua-filter={HERE / 'list-markers.lua'}", str(target)],
                             capture_output=True, text=True, check=True).stdout
        return [line for line in out.splitlines()
                if line.strip() not in ("", ">", '<span class="mark"></span>',
                                        '> <span class="mark"></span>')]

    def test_a_second_run_of_rules_is_written_at_the_rule_column(self):
        definitions = [RULES, lettered(0), num(1, 1), num(2, 2)]
        body = [para("rule one", 1), para("rule two", 1), para("lettered", 2, 0),
                para("second two", 2, 1), para("rule three", 2, 1)]
        # The second run starts again at 2, so a comment keeps it apart from
        # the list before it and a reader numbers it from 2.
        self.assertEqual(self.lines(body, definitions), [
            "1.  rule one", "2.  rule two", r"    - a\) lettered", "<!-- -->",
            "2.  second two", "3.  rule three",
        ])

    def test_text_after_the_last_step_is_written_outside_it(self):
        body = [para("Lead-in.", left=720), para("step one", 1), para("step two", 1), BLANK,
                para("Closing.", left=720), para("bullet", 2)]
        self.assertEqual(self.lines(body, STEPS), [
            "> Lead-in.", "1.  step one", "2.  step two", "> Closing.", "- bullet",
        ])


if __name__ == "__main__":
    unittest.main()
