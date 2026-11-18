#!/usr/bin/env python3
"""Cases for pages.py: where page markers land, and how Word's layout is read."""
from __future__ import annotations

import importlib.util
import pathlib
import shutil
import sys
import tempfile
import unittest
import unittest.mock
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pages  # noqa: E402
import stamp  # noqa: E402

# Word files whose blank paragraph LibreOffice gave a deleted list item's list.
_COPIES_SPEC = importlib.util.spec_from_file_location(
    "hidden_text_test", HERE / "hidden-text_test.py")
COPIES = importlib.util.module_from_spec(_COPIES_SPEC)
_COPIES_SPEC.loader.exec_module(COPIES)

# Decks built in code, with the reader they are read by.
import slides_test as DECK  # noqa: E402


def without_markup(path: pathlib.Path) -> None:
    """Sets the Word file at PATH to show its tracked changes accepted, as
    LibreOffice's copy of a .doc file does, so a layout leaves deletions out."""
    with zipfile.ZipFile(path) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    parts["word/settings.xml"] = (
        f'<w:settings xmlns:w="{COPIES.NS}">'
        '<w:revisionView w:insDel="0" w:formatting="0"/></w:settings>').encode()
    parts["[Content_Types].xml"] = parts["[Content_Types].xml"].replace(
        b"</Types>", b'<Override PartName="/word/settings.xml" ContentType="application/'
        b'vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/></Types>')
    parts["word/_rels/document.xml.rels"] = parts["word/_rels/document.xml.rels"].replace(
        b"</Relationships>", b'<Relationship Id="rIdSettings" Type="http://schemas.'
        b'openxmlformats.org/officeDocument/2006/relationships/settings" '
        b'Target="settings.xml"/></Relationships>')
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in parts.items():
            archive.writestr(name, data)


BODY = "\n".join([
    "## Brief Description",
    "",
    "The worker opens the report from the home page and picks a county.",
    "",
    "| Field | Value |",
    "|---|---|",
    "| County Name | the county the worker is assigned to |",
    "| Office Code | the office within that county |",
    "",
    "```",
    "SELECT ID_PERSON",
    "FROM PERSON",
    "```",
    "",
    "Closing paragraph that wraps over",
    "two lines of the converted text.",
    "",
])


def layout(*starts: str) -> pages.Layout:
    return pages.Layout(len(starts) + 1, list(starts), "from the PDF")


def markers(markdown: str) -> list[tuple[int, str]]:
    lines = markdown.split("\n")
    return [(i, lines[i + 2]) for i, line in enumerate(lines) if pages.MARKER.match(line)]


class Place(unittest.TestCase):
    def test_page_one_opens_the_body(self):
        placed = pages.place(BODY, layout())
        self.assertEqual(placed.markdown.split("\n")[0], '<a id="page-1"></a>*Page 1*')

    def test_a_page_opening_mid_table_marks_the_whole_table(self):
        placed = pages.place(BODY, layout("Office Code the office within"))
        self.assertEqual(markers(placed.markdown)[1][1], "| Field | Value |")

    def test_a_page_opening_in_a_code_block_marks_the_fence(self):
        placed = pages.place(BODY, layout("FROM PERSON Closing paragraph"))
        self.assertEqual(markers(placed.markdown)[1][1], "```")

    def test_a_page_opening_mid_paragraph_marks_the_paragraph(self):
        placed = pages.place(BODY, layout("two lines of the converted text"))
        self.assertEqual(markers(placed.markdown)[1][1], "Closing paragraph that wraps over")

    def test_pages_land_in_order_and_a_missing_page_is_reported(self):
        placed = pages.place(BODY, layout(
            "The worker opens the report", "text the body never kept at all",
            "Closing paragraph that wraps",
        ))
        self.assertEqual(placed.missed, [3])
        found = [line for line in placed.markdown.split("\n") if pages.MARKER.match(line)]
        self.assertEqual([m.split('"')[1] for m in found], ["page-1", "page-2", "page-4"])

    def test_a_pdf_page_links_to_that_page(self):
        placed = pages.place(BODY, layout("Closing paragraph that wraps"), "https://x/a.pdf")
        self.assertIn(
            '<a id="page-2"></a>*[Page 2](https://x/a.pdf#page=2)*', placed.markdown
        )

    def test_a_later_line_matches_when_the_first_was_not_kept(self):
        start = "Screen Print label\nThe worker opens the report from the home page"
        self.assertEqual(pages.place(BODY, layout(start)).missed, [])

    def test_a_page_opening_in_an_indented_block_marks_its_list_item(self):
        body = "12. The rule text\n\n    1. The first sub-rule of twelve\n\n13. Next rule\n"
        placed = pages.place(body, layout("The first sub-rule of twelve"))
        self.assertEqual(markers(placed.markdown)[1][1], "12. The rule text")

    TABLES = "\n".join([
        "| Field Name | Value Shown |", "| Medical exam is due | a |", "",
        "| Field Name | Value Shown |", "| Medical exam is overdue | b |", "",
    ])

    def test_a_short_piece_in_two_blocks_is_no_match(self):
        start = "Label the body never kept\nField Name Value Shown"
        self.assertEqual(pages.place(self.TABLES, layout(start)).missed, [2])

    def test_the_block_holding_more_of_the_opening_wins(self):
        start = "Label the body never kept\nField Name Value Shown\nMedical exam is overdue"
        placed = pages.place(self.TABLES, layout(start))
        self.assertEqual(placed.missed, [])
        lines = placed.markdown.split("\n")
        at = lines.index('<a id="page-2"></a>*Page 2*')
        self.assertEqual(lines[at + 3], "| Medical exam is overdue | b |")


class Decks(unittest.TestCase):
    """A deck's pages are its slides, found by the heading each one opens on."""

    def deck(self, folder: str, *slides_xml: str, name: str = "d.pptx") -> pathlib.Path:
        return DECK.deck(pathlib.Path(folder, name), list(slides_xml))

    def test_every_slide_is_marked_even_with_shared_titles_and_no_title(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.deck(folder, DECK.slide(DECK.title("Default View")),
                             DECK.slide(DECK.title("Default View")),
                             DECK.slide(DECK.title("Default View")), DECK.slide())
            layout = pages.layout_of(path)
            body = stamp.clean(DECK.slides.markdown(path))
        self.assertEqual((layout.pages, layout.label), (4, "one per slide shown in the deck"))
        placed = pages.place(body, layout)
        self.assertEqual(placed.missed, [])
        self.assertEqual([line for _, line in markers(placed.markdown)],
                         ["## Default View", "## Default View", "## Default View",
                          "## Slide 4"])

    def test_text_matching_a_later_title_does_not_take_its_marker(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.deck(
                folder,
                DECK.slide(DECK.title("Intro"),
                           DECK.shape("TextBox", DECK.para("Historical View"))),
                DECK.slide(DECK.title("Historical View")))
            layout = pages.layout_of(path)
            body = stamp.clean(DECK.slides.markdown(path))
        placed = pages.place(body, layout)
        self.assertEqual(markers(placed.markdown)[1][1], "## Historical View")

    def test_a_legacy_deck_is_read_through_its_modern_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            copy = self.deck(folder, DECK.slide(), DECK.slide())
            layout = pages.layout_of(pathlib.Path(folder, "d.ppt"), copy)
        self.assertEqual(layout.pages, 2)

    def test_a_deck_that_cannot_be_read_falls_back_to_a_render(self):
        with tempfile.TemporaryDirectory() as folder:
            broken = pathlib.Path(folder, "broken.pptx")
            broken.write_bytes(b"not a zip")
            with unittest.mock.patch.object(pages, "render", return_value=None) as render:
                self.assertIsNone(pages.layout_of(broken))
        render.assert_called_once()


class DeckLinks(unittest.TestCase):
    """A deck's markers link into a PDF beside it only when the page counts agree."""

    HOST = "https://example.test"
    WHERE = {"Deck.pdf": "/sites/Docs/Deck.pdf"}
    DECK_LAYOUT = pages.Layout(3, ["b", "c"], "one per slide shown in the deck",
                               headings=True)

    def link(self, pdf_pages: int, pdf: str | None = "Deck.pdf") -> str | None:
        with unittest.mock.patch.object(pages, "pdf_pages",
                                        return_value=["page"] * pdf_pages):
            return stamp.page_link(self.DECK_LAYOUT,
                                   pathlib.Path("/x", pdf) if pdf else None,
                                   self.WHERE, self.HOST)

    def test_a_pdf_with_one_page_per_slide_is_linked(self):
        self.assertEqual(self.link(3), "https://example.test/sites/Docs/Deck.pdf")

    def test_a_pdf_with_another_page_count_is_not(self):
        self.assertIsNone(self.link(4))

    def test_a_pdf_the_library_does_not_hold_is_not(self):
        self.assertIsNone(self.link(3, "Other.pdf"))

    def test_no_pdf_no_link(self):
        self.assertIsNone(self.link(3, None))


class Openings(unittest.TestCase):
    def test_running_header_page_number_and_bullets_come_off(self):
        page = "Process Description\n\nPage {n} of 3\nBody text of page {n}\n"
        lines = pages.opening_lines([page.format(n=n) for n in (1, 2, 3)])
        self.assertEqual(lines[1], ["Body text of page 2"])

    def test_a_two_page_header_comes_off(self):
        page = "Process Description\nDOCUMENTATION\nBody text of page {n}\n"
        lines = pages.opening_lines([page.format(n=n) for n in (1, 2)])
        self.assertEqual(lines[1], ["Body text of page 2"])

    def test_a_missing_tool_costs_the_pages_only(self):
        scratch = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        missing = pathlib.Path(scratch) / "none.pdf"
        with unittest.mock.patch.object(pages.subprocess, "run", side_effect=OSError):
            self.assertEqual(pages.pdf_pages(missing), [])
            self.assertIsNone(pages.render(missing, missing.parent))


class Word(unittest.TestCase):
    def docx(self, body: str, app: str | None = None) -> pathlib.Path:
        scratch = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        path = pathlib.Path(scratch) / "doc.docx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                "word/document.xml", f"<w:document><w:body>{body}</w:body></w:document>"
            )
            if app is not None:
                archive.writestr("docProps/app.xml", f"<Properties>{app}</Properties>")
        return path

    def marked(self, marks: int, app: str | None = None) -> pathlib.Path:
        """A Word file whose text carries MARKS rendered page breaks."""
        body = "<w:p><w:r><w:t>Opening text of the first page</w:t></w:r></w:p>" + "".join(
            f"<w:p><w:r><w:lastRenderedPageBreak/><w:t>Opening of page {n + 2}"
            "</w:t></w:r></w:p>" for n in range(marks))
        return self.docx(body, app)

    @staticmethod
    def word_app(pages: str) -> str:
        return (f"<Application>Microsoft Office Word</Application><Pages>{pages}</Pages>")

    def rendered(self, pages_in_render: int):
        """Stands in for LibreOffice: a render that lays the document out on N pages."""
        layout = pages.Layout(pages_in_render, ["x"] * (pages_in_render - 1),
                              "as LibreOffice lays the document out")
        render = unittest.mock.patch.object(pages, "render", return_value=pathlib.Path("r.pdf"))
        source = unittest.mock.patch.object(pages, "from_pdf", return_value=layout)
        listed = unittest.mock.patch.object(pages, "as_listed", side_effect=lambda p, w: p)
        self.addCleanup(unittest.mock.patch.stopall)
        return render.start(), source.start(), listed.start()

    def test_a_stored_count_above_the_marks_is_recorded(self):
        found = pages.from_word(self.marked(5, self.word_app("10")))
        self.assertEqual((found.pages, found.marked, found.stored), (6, 6, 10))

    def test_a_stored_count_below_the_marks_is_recorded(self):
        found = pages.from_word(self.marked(5, self.word_app("4")))
        self.assertEqual(found.stored, 4)

    def test_agreeing_counts_record_nothing(self):
        self.assertIsNone(pages.from_word(self.marked(5, self.word_app("6"))).stored)

    def test_a_count_word_did_not_write_is_not_compared(self):
        for app in (
            None, "<Pages>10</Pages>", "<Application>LibreOffice/7</Application><Pages>10</Pages>",
            self.word_app("many"), self.word_app("0"),
        ):
            with self.subTest(app=app):
                self.assertIsNone(pages.from_word(self.marked(5, app)).stored)
        self.assertIsNone(pages.from_word(self.marked(5, "<broken")).stored)

    def test_disagreeing_counts_send_the_document_to_libreoffice(self):
        render, _, _ = self.rendered(10)
        found = pages.layout_of(self.marked(5, self.word_app("10")))
        render.assert_called_once()
        self.assertEqual(found.label, "as LibreOffice lays the document out")
        self.assertEqual((found.pages, found.marked, found.stored), (10, 6, 10))

    def test_a_stored_count_below_the_marks_also_goes_to_libreoffice(self):
        render, _, _ = self.rendered(4)
        found = pages.layout_of(self.marked(5, self.word_app("4")))
        render.assert_called_once()
        self.assertEqual(found.pages, 4)

    def test_agreeing_counts_keep_the_word_layout(self):
        render, _, _ = self.rendered(10)
        found = pages.layout_of(self.marked(5, self.word_app("6")))
        render.assert_not_called()
        self.assertEqual(found.label, "as Word last laid the document out")

    def test_no_render_keeps_the_word_layout_with_its_disagreement(self):
        render, _, _ = self.rendered(10)
        render.return_value = None
        found = pages.layout_of(self.marked(5, self.word_app("10")))
        self.assertEqual((found.label, found.marked, found.stored),
                         ("as Word last laid the document out", 6, 10))

    def test_rendered_breaks_are_the_pages(self):
        path = self.docx(
            "<w:p><w:r><w:t>First page text</w:t></w:r></w:p>"
            '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'
            "<w:p><w:r><w:lastRenderedPageBreak/><w:t>Second &amp; page</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>still second</w:t><w:lastRenderedPageBreak/>"
            "<w:t xml:space=\"preserve\"> third</w:t></w:r></w:p>"
        )
        found = pages.from_word(path)
        self.assertEqual(found.pages, 3)
        self.assertTrue(found.starts[0].startswith("Second & page"))
        self.assertEqual(found.starts[1].strip(), "third")

    def test_a_file_word_never_laid_out_has_no_word_layout(self):
        path = self.docx('<w:p><w:r><w:t>a</w:t><w:br w:type="page"/><w:t>b</w:t></w:r></w:p>')
        self.assertIsNone(pages.from_word(path))


class Listed(unittest.TestCase):
    """A layout numbers a list the way the Markdown does."""

    def setUp(self):
        self.work = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def source(self, app):
        # Two rules deleted ahead of the list, then a rule on a page of its own.
        path = self.work / "rules.docx"
        COPIES.WORD.docx(path, [
            COPIES.deleted_item("Regional workers can open the window."),
            COPIES.deleted_item("State workers can open the window.", COPIES.COPIED),
            COPIES.copied(),
            COPIES.WORD.para("Any user with a role in the stage can view the milestones.", 1),
            '<w:p><w:pPr><w:pageBreakBefore/><w:numPr><w:ilvl w:val="0"/>'
            '<w:numId w:val="1"/></w:numPr></w:pPr>' + COPIES.run(
                "Upon window entry the milestones display for the first child.") + "</w:p>",
        ], [COPIES.WORD.abstract(1, COPIES.WORD.level(0, left=720)), COPIES.WORD.num(1, 1)])
        without_markup(path)
        COPIES.application(path, app)
        return path

    def test_libreoffices_copy_is_laid_out_without_the_copied_list(self):
        listed = pages.as_listed(self.source(COPIES.LIBREOFFICE), self.work)
        self.assertEqual(listed, self.work / "listed" / "rules.docx")

    def test_a_file_without_the_copy_is_laid_out_as_it_is(self):
        path = self.source(COPIES.MS_WORD)
        self.assertEqual(pages.as_listed(path, self.work), path)
        broken = self.work / "broken.docx"
        broken.write_text("not a zip archive", encoding="utf-8")
        self.assertEqual(pages.as_listed(broken, self.work / "other"), broken)

    @unittest.skipUnless(shutil.which("soffice") and shutil.which("pdftotext"),
                         "LibreOffice or pdftotext is not installed")
    def test_a_page_opens_on_the_number_the_markdown_gives_its_item(self):
        layout = pages.layout_of(self.source(COPIES.LIBREOFFICE))
        self.assertEqual(layout.pages, 2)
        self.assertTrue(layout.starts[0].lstrip().startswith("2."), layout.starts[0])


class SharePoint(unittest.TestCase):
    HOST = "https://example.test"
    LIB = "/sites/ExampleDocs/Application Development Documentation"

    def test_a_word_file_opens_in_the_browser(self):
        path = f"{self.LIB}/O/A [draft].doc"
        line = stamp.sharepoint_line("A [draft].doc", path, self.HOST)
        self.assertEqual(
            line,
            r"- SharePoint: [A \[draft\].doc](https://example.test/sites/"
            "ExampleDocs/Application%20Development%20Documentation/O/"
            "A%20%5Bdraft%5D.doc?web=1)",
        )

    def test_a_pdf_keeps_a_plain_address(self):
        url = stamp.sharepoint_url(f"{self.LIB}/a.pdf", self.HOST)
        self.assertTrue(url.startswith(f"{self.HOST}/sites/"))
        self.assertTrue(url.endswith("/a.pdf"))


class Title(unittest.TestCase):
    def test_a_source_named_without_spaces_takes_its_library_title(self):
        library = {"ACT-4.0-Activity-Entry.docx": "ACT 4.0 - Activity Entry.docx"}
        title = stamp.title_of([pathlib.Path("ACT-4.0-Activity-Entry.docx")], library)
        self.assertEqual(title, "ACT 4.0 - Activity Entry")

    def test_a_page_keeps_an_h1_that_is_its_own_name(self):
        with tempfile.TemporaryDirectory() as folder:
            page = pathlib.Path(folder, "Office-Detail-On-Line-Help.md")
            page.write_text("# Office Detail - On-Line Help\n\nbody\n", encoding="utf-8")
            self.assertEqual(stamp.page_title(page), "Office Detail - On-Line Help")

    def test_an_h1_naming_the_page_another_way_is_not_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            page = pathlib.Path(folder, "Home-On-Line-Help.md")
            page.write_text("# Home\n", encoding="utf-8")
            self.assertIsNone(stamp.page_title(page))
            self.assertIsNone(stamp.page_title(pathlib.Path(folder, "Missing.md")))


if __name__ == "__main__":
    unittest.main()
