#!/usr/bin/env python3
"""Cases for check-list-numbers.py: which converted list numbers disagree with the source."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import pathlib
import shutil
import tempfile
import unittest
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
SCRIPT = HERE / "check-list-numbers.py"
SPEC = importlib.util.spec_from_file_location("check_list_numbers", SCRIPT)
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)

# The Word file builders, and a numbered paragraph deleted with its changes tracked.
MARKERS_SPEC = importlib.util.spec_from_file_location(
    "list_markers_test", HERE / "list-markers_test.py")
MARKERS = importlib.util.module_from_spec(MARKERS_SPEC)
MARKERS_SPEC.loader.exec_module(MARKERS)
WORD = MARKERS.WORD
# The paragraphs LibreOffice writes around a deleted list item.
COPIES_SPEC = importlib.util.spec_from_file_location(
    "hidden_text_test", HERE / "hidden-text_test.py")
COPIES = importlib.util.module_from_spec(COPIES_SPEC)
COPIES_SPEC.loader.exec_module(COPIES)

# Three rules, the second deleted whole with its changes tracked: Word numbers
# the third rule 2.
DEFINITIONS = [WORD.abstract(1, WORD.level(0, left=720)), WORD.num(1, 1)]
BODY = [
    WORD.para("The window opens with the case list already filled in.", 1),
    MARKERS.deleted_para("The Go To menu holds a link to the progress notes.", 1),
    WORD.para("The Help menu holds the About Connections item.", 1),
]
PAGE = ("1.  The window opens with the case list already filled in.\n\n"
        "2.  The Help menu holds the About Connections item.\n")

# A text export the way LibreOffice writes one: labels drawn, sub-items indented.
EXPORT = """Case Summary

    1. The window will display the case name and the case number.

    2. The grid lists every stage of the case in date order.
        i. The Stage column holds the stage name.
        ii. The Status column holds the stage status.

    3. The user can launch Person Detail from any row.

    1.3 Assumptions for the summary window as written today

    4. (SIR 101) When the user has selected the allegation of neglect, first case
    5. ~~Struck~~ text in the source.
    6. (SIR 101) When the user has selected the allegation of neglect, second case
"""


def numbers(markdown):
    differ, found, missing = CHECK.compare(markdown, EXPORT)
    return [(number, label) for _, number, label, _ in differ], found, missing


class CompareTest(unittest.TestCase):
    def test_numbers_that_follow_the_source_agree(self):
        markdown = (
            "1.  The window will display the case name and the case number.\n\n"
            "2.  The grid lists every stage of the case in date order.\n\n"
            "    1.  The Stage column holds the stage name.\n\n"
            "3.  The user can launch Person Detail from any row.\n"
        )
        self.assertEqual(numbers(markdown), ([], 3, 0))

    def test_a_restarted_list_differs(self):
        markdown = (
            "1.  The window will display the case name and the case number.\n\n"
            "&nbsp;\n\n"
            "1.  The grid lists every stage of the case in date order.\n\n"
            "2.  The user can launch Person Detail from any row.\n"
        )
        self.assertEqual(numbers(markdown)[0], [(1, "2"), (2, "3")])

    def test_a_sub_item_at_the_margin_is_read_by_its_label(self):
        agree = "2.  The Status column holds the stage status.\n"
        self.assertEqual(numbers(agree), ([], 1, 0))
        differ = "5.  The Status column holds the stage status.\n"
        self.assertEqual(numbers(differ)[0], [(5, "ii")])

    def test_a_level_number_is_read_by_its_last_part(self):
        self.assertEqual(numbers("3.  **Assumptions for the summary window as written today**\n"),
                         ([], 1, 0))

    def test_an_escaped_number_is_read(self):
        markdown = "3\\. The user can launch Person Detail from any row.\n"
        self.assertEqual(numbers(markdown), ([], 1, 0))

    def test_items_opening_alike_are_matched_in_order(self):
        markdown = (
            "4.  (SIR 101) When the user has selected the allegation of neglect, first case\n\n"
            "5.  ~~Struck~~ text in the source.\n\n"
            "6.  (SIR 101) When the user has selected the allegation of neglect, second case\n"
        )
        self.assertEqual(numbers(markdown), ([], 3, 0))

    def test_an_item_the_source_does_not_hold_is_counted_not_failed(self):
        markdown = "7.  A sentence the conversion wrote differently.\n"
        self.assertEqual(numbers(markdown), ([], 0, 1))

    def test_an_earlier_item_opening_alike_does_not_excuse_a_restart(self):
        export = ("    1. The Save pushbutton will be enabled when the page loads.\n"
                  "    2. The Cancel pushbutton closes the window without saving.\n"
                  "    3. The Save pushbutton will be enabled when the page loads.\n")
        markdown = ("1.  The Save pushbutton will be enabled when the page loads.\n\n"
                    "2.  The Cancel pushbutton closes the window without saving.\n\n"
                    "1.  The Save pushbutton will be enabled when the page loads.\n")
        differ, found, _ = CHECK.compare(markdown, export)
        self.assertEqual([(n, label) for _, n, label, _ in differ], [(1, "3")])
        self.assertEqual(found, 3)

    def test_an_item_with_no_labelled_copy_ahead_is_not_found(self):
        # Item 3's copy in the export carries no label, as a table cell's would.
        export = (
            "    1. (Build 4 2026) When the user has selected the allegation, the window opens.\n"
            "    2. The Cancel pushbutton closes the window without saving.\n"
            "(Build 4 2026) When the user has selected the allegation, a tab opens.\n"
            "    4. The Cancel pushbutton closes the window without saving.\n"
        )
        markdown = (
            "2.  The Cancel pushbutton closes the window without saving.\n\n"
            "3.  (Build 4 2026) When the user has selected the allegation, a tab opens.\n\n"
            "4.  The Cancel pushbutton closes the window without saving.\n"
        )
        self.assertEqual(CHECK.compare(markdown, export), ([], 2, 1))

    def test_an_earlier_item_opening_alike_with_the_same_number_is_found(self):
        export = ("    1. The Save pushbutton will be enabled when the page loads.\n"
                  "    2. The Cancel pushbutton closes the window without saving.\n")
        markdown = ("2.  The Cancel pushbutton closes the window without saving.\n\n"
                    "1.  The Save pushbutton will be enabled when the page loads.\n")
        self.assertEqual(CHECK.compare(markdown, export), ([], 2, 0))

    def test_a_later_copy_with_the_number_does_not_hide_a_shifted_list(self):
        # The second list repeats the first item's opening under number 2; the
        # first list, numbered one high throughout, still differs on every item.
        export = ("    1. The window will display the case name and number.\n"
                  "    2. The Cancel pushbutton closes the window without saving.\n"
                  "    1. Zeta item text here for list two.\n"
                  "    2. The window will display the case name and number.\n"
                  "    3. Last item text in list two goes here.\n")
        markdown = ("2.  The window will display the case name and number.\n\n"
                    "3.  The Cancel pushbutton closes the window without saving.\n\n"
                    "4.  Zeta item text here for list two.\n")
        differ, found, missing = CHECK.compare(markdown, export)
        self.assertEqual([(n, label) for _, n, label, _ in differ],
                         [(2, "1"), (3, "2"), (4, "1")])
        self.assertEqual((found, missing), (3, 0))

    def test_an_unpaired_opening_far_ahead_does_not_reopen_earlier_items(self):
        # The first item pairs with the second "Intro" copy, leaving the first
        # one unpaired; item 3's own copy still carries no label.
        export = (
            "    1. Intro text that repeats later in the document.\n"
            "    1. Some other heading list item text.\n"
            "    2. Intro text that repeats later in the document.\n"
            "    1. (Build 4 2026) When the user has selected the allegation, the window opens.\n"
            "    2. The Cancel pushbutton closes the window without saving.\n"
            "(Build 4 2026) When the user has selected the allegation, a tab opens.\n"
            "    4. The Cancel pushbutton closes the window without saving.\n"
        )
        markdown = (
            "2.  Intro text that repeats later in the document.\n\n"
            "2.  The Cancel pushbutton closes the window without saving.\n\n"
            "3.  (Build 4 2026) When the user has selected the allegation, a tab opens.\n\n"
            "4.  The Cancel pushbutton closes the window without saving.\n"
        )
        self.assertEqual(CHECK.compare(markdown, export), ([], 3, 1))

    def test_an_item_whose_first_line_is_short_pairs_with_its_longer_copy(self):
        export = ("    1. The window shows the value from https://example.org/very/long/path/"
                  "to/page and more.\n"
                  "    2. Second item text that is long enough here.\n")
        markdown = ("5.  The window shows the value from\n"
                    "    <https://example.org/very/long/path/to/page> and more.\n\n"
                    "6.  Second item text that is long enough here.\n")
        differ, found, missing = CHECK.compare(markdown, export)
        self.assertEqual([(n, label) for _, n, label, _ in differ], [(5, "1"), (6, "2")])
        self.assertEqual((found, missing), (2, 0))

    def test_an_item_never_pairs_with_a_later_item_that_only_opens_alike(self):
        # Items 166 to 170 open with the same 48 characters. Item 167's own copy
        # is not a labelled item in the export, and the export's 170 has no
        # Markdown item; 167 is not in the source, not numbered 170.
        rule = "Upon a successful save when the Event type is {} a Shadow Code is made"
        codes = {166: "M910", 167: "M960", 168: "M980", 169: "M981", 170: "M982"}
        markdown = "\n\n".join(f"{n}.  {rule.format(code)}"
                                 for n, code in codes.items() if n != 170) + "\n"
        export = "\n".join(f"    {n}. {rule.format(code)}"
                           for n, code in codes.items() if n != 167) + "\n"
        self.assertEqual(CHECK.compare(markdown, export), ([], 3, 1))

    def test_items_opening_alike_pair_in_order_when_copies_are_missing(self):
        rule = "Upon a successful save when the Event type is {} a Shadow Code is made"
        codes = {166: "M910", 167: "M960", 168: "M980", 169: "M981", 170: "M982",
                 173: "M960 - Child Ends Absence or"}
        markdown = "\n\n".join(f"{n}.  {rule.format(code)}" for n, code in codes.items()) + "\n"
        for dropped in ({167}, {168, 169}):
            export = "\n".join(f"    {n}. {rule.format(code)}"
                               for n, code in codes.items() if n not in dropped) + "\n"
            differ, found, missing = CHECK.compare(markdown, export)
            self.assertEqual(differ, [])
            self.assertEqual((found, missing), (6 - len(dropped), len(dropped)))

    def test_items_that_differ_past_a_mark_are_different_items(self):
        self.assertFalse(CHECK.same_item(
            "upon a successful save when the event type is m960 - child ends absence or",
            "upon a successful save when the event type is m960 a shadow code is made"))
        self.assertTrue(CHECK.same_item(
            "the window shows the value of the case field taken from <https://example.org>",
            "the window shows the value of the case field taken from https://example.org."))

    def test_a_copy_that_wraps_or_hyphenates_sooner_still_pairs(self):
        export = ("    4. The Children Search rules apply when the user selects the Search push-\n"
                  "       button from the Workload window.\n")
        markdown = ("4.  The Children Search rules apply when the user selects the Search pushbutton\n"
                    "    from the Workload window.\n")
        self.assertEqual(CHECK.compare(markdown, export), ([], 1, 0))

    def test_short_items_and_fenced_code_are_skipped(self):
        markdown = ("1.  Yes\n\n```\n"
                    "9.  The window will display the case name and the case number.\n```\n")
        self.assertEqual(numbers(markdown), ([], 0, 0))


class LabelTest(unittest.TestCase):
    def test_label_values(self):
        self.assertEqual(CHECK.label_values("12"), {12})
        self.assertEqual(CHECK.label_values("c"), {3, 100})
        self.assertEqual(CHECK.label_values("iv"), {4})
        self.assertEqual(CHECK.label_values("aa"), {27})
        self.assertEqual(CHECK.label_values("2.10"), {10})


class MainTest(unittest.TestCase):
    def setUp(self):
        self.work = pathlib.Path(tempfile.mkdtemp())
        (self.work / "source.txt").write_text(EXPORT, encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.work)

    def run_check(self, markdown):
        page = self.work / "page.md"
        page.write_text(markdown, encoding="utf-8")
        return CHECK.main(["check-list-numbers.py", str(page), str(self.work / "source.txt")])

    def test_exit_codes(self):
        self.assertEqual(self.run_check("3.  The user can launch Person Detail from any row.\n"), 0)
        self.assertEqual(self.run_check("1.  The user can launch Person Detail from any row.\n"), 2)
        self.assertEqual(CHECK.main(["check-list-numbers.py", str(self.work / "page.md"),
                                     str(self.work / "missing.txt")]), 1)
        self.assertEqual(CHECK.main(["check-list-numbers.py"]), 64)


class SourceTest(unittest.TestCase):
    def setUp(self):
        self.work = pathlib.Path(tempfile.mkdtemp())
        self.source = self.work / "rules.docx"
        WORD.docx(self.source, BODY, DEFINITIONS)

    def tearDown(self):
        shutil.rmtree(self.work)

    def test_a_paragraph_deleted_with_its_changes_tracked_is_not_read(self):
        work = self.work / "work"
        work.mkdir()
        with zipfile.ZipFile(CHECK.as_printed(self.source, work)) as archive:
            document = archive.read("word/document.xml").decode("utf-8")
        self.assertEqual(document.count("</w:p>"), 2)
        self.assertNotIn("progress notes", document)
        self.assertIn("About Connections", document)

    def test_a_byte_order_mark_does_not_hide_the_first_item(self):
        export = self.work / "export.txt"
        export.write_text("\ufeff" + EXPORT.split("\n", 2)[2], encoding="utf-8")
        self.assertEqual(CHECK.text_export(export).splitlines()[0],
                         "    1. The window will display the case name and the case number.")

    def test_a_file_hidden_text_cannot_read_is_read_as_it_is(self):
        broken = self.work / "broken.docx"
        broken.write_text("not a zip archive", encoding="utf-8")
        work = self.work / "work"
        work.mkdir()
        self.assertEqual(CHECK.as_printed(broken, work), broken)

    @unittest.skipUnless(shutil.which("soffice"), "LibreOffice is not installed")
    def test_numbers_after_a_deleted_paragraph_agree_with_word(self):
        self.assertEqual(CHECK.compare(PAGE, CHECK.text_export(self.source)), ([], 2, 0))
        page = self.work / "page.md"
        page.write_text(PAGE, encoding="utf-8")
        self.assertEqual(CHECK.main(["check-list-numbers.py", str(page), str(self.source)]), 0)

    @unittest.skipUnless(shutil.which("soffice"), "LibreOffice is not installed")
    def test_numbers_after_an_empty_item_libreoffice_copied_agree_with_word(self):
        # LibreOffice's copy of a .doc file: the blank paragraph after two deleted
        # rules carries their list, and Word numbers the first rule left 1.
        source = self.work / "copied.docx"
        WORD.docx(source, [
            COPIES.deleted_item("Regional workers can open the window."),
            COPIES.deleted_item("State workers can open the window.", COPIES.COPIED),
            COPIES.copied(),
            WORD.para("Any user with a role in the stage can view the milestones.", 1),
            WORD.para("Selecting another child shows the milestones of that child.", 1),
        ], DEFINITIONS)
        COPIES.application(source, COPIES.LIBREOFFICE)
        page = self.work / "page.md"
        page.write_text("1.  Any user with a role in the stage can view the milestones.\n\n"
                        "2.  Selecting another child shows the milestones of that child.\n",
                        encoding="utf-8")
        self.assertEqual(CHECK.main(["check-list-numbers.py", str(page), str(source)]), 0)

    @unittest.skipUnless(shutil.which("soffice"), "LibreOffice is not installed")
    def test_a_legacy_file_is_read_through_its_docx_copy(self):
        legacy = CHECK.libreoffice(self.source, "doc", "doc", self.work / "legacy")
        work = self.work / "work"
        work.mkdir()
        self.assertEqual(CHECK.as_printed(legacy, work), work / "visible" / "rules.docx")


# Word's render of a source whose list LibreOffice counts differently: Word
# carries the count on at 51, LibreOffice starts the list again at 2.
WORD_RENDER = (
    "Children Search\n\n"
    "    50. The Children Search window lists every child on the workload.\n"
    "    51. The following rules are applicable for the Search buttons on the\n"
    "        Children Search window.\n"
    "    52. The Clear pushbutton empties every search field on the window.\n"
    "\f   7\n"
)
LIBREOFFICE_EXPORT = (
    "Children Search\n\n"
    "    50. The Children Search window lists every child on the workload.\n"
    "    2. The following rules are applicable for the Search buttons on the Children Search window.\n"
    "    3. The Clear pushbutton empties every search field on the window.\n"
)
AS_WORD = ("50. The Children Search window lists every child on the workload.\n\n"
           "51. The following rules are applicable for the Search buttons on the\n"
           "    Children Search window.\n\n"
           "52. The Clear pushbutton empties every search field on the window.\n")


class WordRenderTest(unittest.TestCase):
    def test_pdf_text_reads_as_the_export_does(self):
        self.assertEqual(CHECK.pdf_text("\ufb01eld \u00adlist non\u2011breaking\f2. Next"),
                         "field list non-breaking\n2. Next")

    def test_word_and_libreoffice_disagreements_are_listed(self):
        rows = CHECK.disagreements(AS_WORD, LIBREOFFICE_EXPORT, CHECK.pdf_text(WORD_RENDER))
        self.assertEqual([(line, word, other) for line, word, other, _ in rows],
                         [(3, "51", "2"), (6, "52", "3")])

    def test_a_page_number_or_running_line_is_not_an_item(self):
        text = CHECK.pdf_text("    3. The Clear pushbutton empties the window.\n\n"
                              "Workload Mockups & Design    Page 7 of 12\n\f\n      7\n"
                              "    4. The Search pushbutton runs the search.\n")
        self.assertEqual([label for label, _ in CHECK.export_items(text)], ["3", "4"])

    def test_a_sub_item_at_the_margin_is_read_by_its_label_in_the_render(self):
        render = CHECK.pdf_text("    2. The grid lists every stage of the case in date order.\n"
                                "         i. The Stage column holds the stage name.\n"
                                "        ii. The Status column holds the stage status.\n"
                                "         b) The Owner column holds the case owner.\n")
        markdown = ("2.  The grid lists every stage of the case in date order.\n\n"
                    "2.  The Status column holds the stage status.\n\n"
                    "2.  The Owner column holds the case owner.\n")
        self.assertEqual(CHECK.compare(markdown, render), ([], 3, 0))
        differ = CHECK.compare(markdown.replace("2.  The Status", "3.  The Status"), render)[0]
        self.assertEqual([(n, label) for _, n, label, _ in differ], [(3, "ii")])

    def test_markdown_numbered_as_word_prints_agrees_with_word(self):
        differ, found, missing = CHECK.compare(AS_WORD, CHECK.pdf_text(WORD_RENDER))
        self.assertEqual((differ, found, missing), ([], 3, 0))


class WordMainTest(unittest.TestCase):
    def setUp(self):
        self.work = pathlib.Path(tempfile.mkdtemp())
        (self.work / "source.txt").write_text(LIBREOFFICE_EXPORT, encoding="utf-8")
        (self.work / "render.txt").write_text(WORD_RENDER, encoding="utf-8")
        self.page = self.work / "page.md"

    def tearDown(self):
        shutil.rmtree(self.work)

    def run_check(self, markdown, *extra):
        self.page.write_text(markdown, encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            status = CHECK.main(["check-list-numbers.py", str(self.page),
                                 str(self.work / "source.txt"), *extra])
        return status, out.getvalue()

    def test_numbered_as_word_prints_passes_and_names_the_disagreement(self):
        status, out = self.run_check(AS_WORD, "--word", str(self.work / "render.txt"))
        self.assertEqual(status, 0)
        self.assertIn("page.md:3: Word numbers it 51, LibreOffice numbers it 2", out)
        self.assertIn("2 where Word and LibreOffice differ", out)
        self.assertIn("render.txt", out)

    def test_numbered_as_libreoffice_counts_differs_from_word(self):
        markdown = AS_WORD.replace("51. ", "2. ").replace("52. ", "3. ")
        status, out = self.run_check(markdown, "--word", str(self.work / "render.txt"))
        self.assertEqual(status, 2)
        self.assertIn("page.md:3: numbered 2, Word numbers it 51", out)

    def test_without_a_render_libreoffice_is_the_reference(self):
        status, out = self.run_check(AS_WORD)
        self.assertEqual(status, 2)
        self.assertIn("the source numbers it 2", out)
        self.assertNotIn("Word", out)

    def test_a_wrong_call(self):
        self.assertEqual(self.run_check(AS_WORD, "--word")[0], 64)
        self.assertEqual(self.run_check(AS_WORD, "--word", "a.pdf", "b.pdf")[0], 64)

    def test_a_render_that_cannot_be_read_leaves_the_export_the_reference(self):
        (self.work / "broken.pdf").write_text("not a PDF", encoding="utf-8")
        for name in ("none.pdf", "broken.pdf"):
            status, out = self.run_check(AS_WORD, "--word", str(self.work / name))
            self.assertEqual(status, 2)
            self.assertIn(f"cannot read {name} (", out)
            self.assertIn("the source numbers it 2", out)

    def test_a_render_with_no_list_items_finds_nothing(self):
        (self.work / "empty.txt").write_text("Workload\n\nNo lists here.\n\f  3\n",
                                             encoding="utf-8")
        status, out = self.run_check(AS_WORD, "--word", str(self.work / "empty.txt"))
        self.assertEqual(status, 0)
        self.assertIn("0 found, 0 differ, 3 not in the source", out)
        self.assertIn("0 where Word and LibreOffice differ", out)

    def test_a_render_libreoffice_made_is_not_word(self):
        self.assertTrue(CHECK.libreoffice_made("Creator: Writer\nProducer: LibreOffice 24.2\n"))
        self.assertFalse(CHECK.libreoffice_made(
            "Creator: Microsoft\u00ae Word for Microsoft 365\nProducer: Microsoft\u00ae Word\n"))
        self.assertFalse(CHECK.libreoffice_made("Producer: Writer's Guild Press\n"))

    @unittest.skipUnless(shutil.which("soffice") and shutil.which("pdfinfo"),
                         "LibreOffice or pdfinfo is not installed")
    def test_a_libreoffice_pdf_falls_back_to_the_export(self):
        source = self.work / "rules.docx"
        WORD.docx(source, BODY, DEFINITIONS)
        pdf = CHECK.libreoffice(source, "pdf", "pdf", self.work / "lo")
        status, out = self.run_check(AS_WORD, "--word", str(pdf))
        self.assertEqual(status, 2)
        self.assertIn("LibreOffice made", out)


class ConvertCallTest(unittest.TestCase):
    def test_convert_passes_the_group_pdf_to_the_check(self):
        script = (HERE / "convert.sh").read_text(encoding="utf-8")
        call = script[script.index('"$HERE/check-list-numbers.py"'):]
        call = call[:call.index(")\"")]
        self.assertIn('${word[@]+"${word[@]}"}', call)
        self.assertIn('word=(--word "$linked")', script)


if __name__ == "__main__":
    unittest.main()
