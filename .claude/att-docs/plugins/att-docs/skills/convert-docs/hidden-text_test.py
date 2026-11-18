#!/usr/bin/env python3
"""Cases for hidden-text.py: Word's hidden runs never reach the Markdown."""
from __future__ import annotations

import importlib.util
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("hidden_text", HERE / "hidden-text.py")
HIDDEN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HIDDEN)

# The package parts the list-numbers cases build a Word file from.
PARTS_SPEC = importlib.util.spec_from_file_location("list_numbers_test", HERE / "list-numbers_test.py")
WORD = importlib.util.module_from_spec(PARTS_SPEC)
PARTS_SPEC.loader.exec_module(WORD)

NS = WORD.NS
STYLES = (
    f'<?xml version="1.0" encoding="UTF-8"?><w:styles xmlns:w="{NS}">'
    '<w:style w:type="character" w:styleId="Jump"><w:name w:val="Jump"/>'
    "<w:rPr><w:vanish/></w:rPr></w:style>"
    '<w:style w:type="character" w:styleId="JumpShown"><w:name w:val="Jump Shown"/>'
    '<w:basedOn w:val="Jump"/><w:rPr><w:vanish w:val="0"/></w:rPr></w:style>'
    '<w:style w:type="character" w:styleId="JumpChild"><w:name w:val="Jump Child"/>'
    '<w:basedOn w:val="Jump"/></w:style>'
    '<w:style w:type="paragraph" w:styleId="Hidden"><w:name w:val="Hidden"/>'
    "<w:rPr><w:vanish/></w:rPr></w:style>"
    '<w:style w:type="paragraph" w:styleId="Shown"><w:name w:val="Shown"/>'
    '<w:rPr><w:vanish w:val="0"/></w:rPr></w:style>'
    '<w:style w:type="table" w:styleId="HiddenGrid"><w:name w:val="Hidden Grid"/>'
    "<w:rPr><w:vanish/></w:rPr></w:style>"
    '<w:style w:type="table" w:styleId="HiddenGridChild"><w:name w:val="Hidden Grid Child"/>'
    '<w:basedOn w:val="HiddenGrid"/></w:style>'
    '<w:style w:type="table" w:styleId="ShownGrid"><w:name w:val="Shown Grid"/>'
    '<w:rPr><w:vanish w:val="0"/></w:rPr></w:style>'
    "</w:styles>"
)
# Document defaults that turn hidden text on, and the paragraph style that
# fills in for a paragraph naming none.
DEFAULTS_ON = ("<w:docDefaults><w:rPrDefault><w:rPr><w:vanish/></w:rPr></w:rPrDefault>"
               "</w:docDefaults>")
DEFAULT_PARAGRAPH = ('<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
                     '<w:name w:val="Normal"/><w:rPr><w:vanish/></w:rPr></w:style>')
DEFAULT_TABLE = ('<w:style w:type="table" w:default="1" w:styleId="TableNormal">'
                 '<w:name w:val="Normal Table"/><w:rPr><w:vanish/></w:rPr></w:style>')


def styled(defaults="", *extra):
    """STYLES with document defaults ahead of the styles and EXTRA styles after them."""
    out = STYLES.replace(f'xmlns:w="{NS}">', f'xmlns:w="{NS}">{defaults}', 1)
    return out.replace("</w:styles>", "".join(extra) + "</w:styles>")


JUMP = '<w:rStyle w:val="Jump"/>'
DELETION = 'w:author="Author" w:date="2005-10-17T13:20:00Z"'

# The application a file's extended properties name.
LIBREOFFICE = "LibreOffice/26.2.6.3$Linux_X86_64 LibreOffice_project/620$Build-3"
MS_WORD = "Microsoft Office Word"

# A first-level item of list 1, and the properties LibreOffice gives the
# paragraph after a deleted one.
LISTED = '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>'
COPIED = f'<w:widowControl/>{LISTED}<w:bidi w:val="0"/>'


def run(text, properties=""):
    rpr = f"<w:rPr>{properties}</w:rPr>" if properties else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{text}</w:t></w:r>'


def para(*runs):
    return f'<w:p>{"".join(runs)}</w:p>'


def styled_para(style, *runs):
    return f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>{"".join(runs)}</w:p>'


def table(style, *paragraphs):
    """A one-cell table in table style STYLE, or in none when STYLE is empty."""
    properties = f'<w:tblPr><w:tblStyle w:val="{style}"/></w:tblPr>' if style else ""
    return f'<w:tbl>{properties}<w:tr><w:tc>{"".join(paragraphs)}</w:tc></w:tr></w:tbl>'


def deleted_item(text, properties=LISTED):
    """A list item whose text and mark are deleted with their changes tracked."""
    return (f'<w:p><w:pPr>{properties}<w:rPr><w:del w:id="1" {DELETION}/></w:rPr></w:pPr>'
            f'<w:del w:id="2" {DELETION}><w:r><w:delText>{text}</w:delText></w:r></w:del></w:p>')


def copied(*runs, properties=COPIED):
    """The paragraph after a deleted item, holding the copy LibreOffice gives it."""
    return f'<w:p><w:pPr>{properties}</w:pPr>{"".join(runs)}</w:p>'


def application(path, name):
    """Names NAME as the application that wrote the Word file at PATH."""
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr(
            "docProps/app.xml",
            '<?xml version="1.0" encoding="UTF-8"?><Properties xmlns="http://schemas.'
            'openxmlformats.org/officeDocument/2006/extended-properties">'
            f"<Application>{name}</Application></Properties>")


def docx(path, *paragraphs, styles=STYLES, app=None):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", WORD.CONTENT_TYPES)
        archive.writestr("_rels/.rels", WORD.RELS)
        archive.writestr("word/_rels/document.xml.rels", WORD.DOCUMENT_RELS)
        archive.writestr("word/styles.xml", styles)
        archive.writestr(
            "word/document.xml",
            f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{NS}">'
            f'<w:body>{"".join(paragraphs)}</w:body></w:document>',
        )
    if app is not None:
        application(path, app)


class HiddenTextTest(unittest.TestCase):
    def setUp(self):
        self.work = pathlib.Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.work)

    def visible(self, *paragraphs, styles=STYLES, app=None):
        source, target = self.work / "in.docx", self.work / "out.docx"
        docx(source, *paragraphs, styles=styles, app=app)
        self.assertEqual(HIDDEN.main(["hidden-text.py", str(source), str(target)]), 0)
        with zipfile.ZipFile(target) as archive:
            document = archive.read("word/document.xml").decode("utf-8")
        return target, document

    def lists(self, *paragraphs, app=LIBREOFFICE):
        """Each paragraph left after the rewrite: its text and the list it is in."""
        _, document = self.visible(*paragraphs, app=app)
        out = []
        for paragraph in ET.fromstring(document).iter(WORD.W + "p"):
            num_id = paragraph.find(f"{WORD.W}pPr/{WORD.W}numPr/{WORD.W}numId")
            out.append(("".join(t.text or "" for t in paragraph.iter(WORD.W + "t")),
                        None if num_id is None else num_id.get(WORD.W + "val")))
        return out

    def test_an_empty_paragraph_given_a_deleted_items_list_leaves_the_list(self):
        self.assertEqual(self.lists(
            para(run("Business Rules:")),
            deleted_item("Regional workers can open the window."),
            deleted_item("State workers can open the window.", COPIED),
            copied(),
            copied(run("Any user with a role in the stage can view the milestones."),
                   properties=LISTED)),
            [("Business Rules:", None), ("", "0"),
             ("Any user with a role in the stage can view the milestones.", "1")])

    def test_a_paragraph_given_a_deleted_items_list_keeps_it_with_text(self):
        self.assertEqual(
            self.lists(deleted_item("Old rule."), copied(run(" These dates are checked."))),
            [(" These dates are checked.", "1")])

    def test_an_empty_item_keeps_its_list_without_libreoffices_copy(self):
        # Its own properties, which Word draws as an empty item.
        self.assertEqual(self.lists(deleted_item("Go To Progress Notes"),
                                    copied(properties=LISTED)), [("", "1")])
        # A file Word wrote holds every paragraph's own properties.
        for app in (MS_WORD, None):
            self.assertEqual(self.lists(deleted_item("Old rule."), copied(), app=app),
                             [("", "1")])

    def test_an_empty_paragraph_keeps_a_list_of_its_own(self):
        other = COPIED.replace('w:numId w:val="1"', 'w:numId w:val="2"')
        self.assertEqual(self.lists(deleted_item("Old rule."), copied(properties=other)),
                         [("", "2")])

    def test_a_picture_is_something_word_prints(self):
        picture = "<w:r><w:drawing/></w:r>"
        self.assertEqual(self.lists(deleted_item("Old rule."), copied(picture)), [("", "1")])

    def test_the_layout_copy_takes_the_blank_out_of_its_list_and_keeps_the_rest(self):
        source, target = self.work / "in.docx", self.work / "listed.docx"
        hidden = run("Exi", "<w:vanish/>")
        paragraphs = [deleted_item("Old rule."), copied(hidden),
                      copied(run("Any user can view the milestones."), properties=LISTED)]
        docx(source, *paragraphs, app=LIBREOFFICE)
        self.assertEqual(HIDDEN.unlist_copied_blanks(source, target), 1)
        with zipfile.ZipFile(target) as archive:
            document = ET.fromstring(archive.read("word/document.xml"))
        numbers = [p.find(f"{WORD.W}pPr/{WORD.W}numPr/{WORD.W}numId").get(WORD.W + "val")
                   for p in document.iter(WORD.W + "p")]
        self.assertEqual(numbers, ["1", "0", "1"])
        self.assertIn("Old rule.", ET.tostring(document, encoding="unicode"))
        self.assertIn("Exi", ET.tostring(document, encoding="unicode"))
        docx(source, *paragraphs, app=MS_WORD)
        self.assertEqual(HIDDEN.unlist_copied_blanks(source, target), 0)

    @unittest.skipUnless(shutil.which("pandoc"), "pandoc is not installed")
    def test_the_rule_after_an_empty_copied_item_takes_words_number(self):
        source = self.work / "rules.docx"
        visible, target = self.work / "visible.docx", self.work / "numbered.docx"
        WORD.docx(source, [
            para(run("Business Rules:")),
            deleted_item("Regional workers can open the window."),
            deleted_item("State workers can open the window.", COPIED),
            copied(),
            WORD.para("Any user with a role in the stage can view the milestones.", 1),
            WORD.para("Selecting another child shows the milestones of that child.", 1),
        ], [WORD.abstract(1, WORD.level(0, left=720)), WORD.num(1, 1)])
        application(source, LIBREOFFICE)
        self.assertEqual(HIDDEN.main(["hidden-text.py", str(source), str(visible)]), 0)
        self.assertEqual(WORD.LIST.main(["list-numbers.py", str(visible), str(target)]), 0)
        out = subprocess.run(["pandoc", "-f", "docx", "-t", "gfm", str(target)],
                             capture_output=True, text=True, check=True).stdout
        self.assertEqual([line for line in out.splitlines() if line.strip()], [
            "Business Rules:",
            "1.  Any user with a role in the stage can view the milestones.",
            "2.  Selecting another child shows the milestones of that child.",
        ])

    def test_a_run_hidden_directly_goes(self):
        _, document = self.visible(para(run("Contents"), run("Contents_2", "<w:vanish/>")))
        self.assertIn("Contents<", document)
        self.assertNotIn("Contents_2", document)

    def test_a_run_hidden_through_its_character_style_goes(self):
        _, document = self.visible(para(
            run("Call Entry Window"), run("Call_Entry_Window", '<w:rStyle w:val="JumpChild"/>')))
        self.assertNotIn("Call_Entry_Window", document)

    def test_a_run_shown_by_its_own_value_or_its_style_stays(self):
        _, document = self.visible(para(
            run("shown", '<w:vanish w:val="false"/>'),
            run("styled", '<w:rStyle w:val="JumpShown"/>'),
            run("direct wins", '<w:rStyle w:val="Jump"/><w:vanish w:val="0"/>')))
        for text in ("shown", "styled", "direct wins"):
            self.assertIn(text, document)

    def test_a_run_hidden_through_its_paragraph_style_goes(self):
        _, document = self.visible(
            '<w:p><w:pPr><w:pStyle w:val="Hidden"/></w:pPr>'
            f'{run("Exi")}</w:p>', para(run("After")))
        self.assertNotIn("Exi", document)
        self.assertIn("After", document)

    def test_paragraph_and_character_styles_that_both_hide_cancel(self):
        _, document = self.visible(
            '<w:p><w:pPr><w:pStyle w:val="Hidden"/></w:pPr>'
            f'{run("both", JUMP)}'
            f'{run("paragraph only")}</w:p>')
        self.assertIn("both", document)
        self.assertNotIn("paragraph only", document)

    def test_the_document_defaults_hide_a_run_no_style_speaks_for(self):
        styles = STYLES.replace(
            f'xmlns:w="{NS}">',
            f'xmlns:w="{NS}"><w:docDefaults><w:rPrDefault><w:rPr><w:vanish/>'
            "</w:rPr></w:rPrDefault></w:docDefaults>", 1)
        _, document = self.visible(
            para(run("default"), run("shown", '<w:vanish w:val="0"/>')), styles=styles)
        self.assertNotIn("default", document)
        self.assertIn("shown", document)

    def test_a_table_style_that_hides_hides_its_cell_text(self):
        _, document = self.visible(table("HiddenGrid", para(run("cellgone"))), para(run("after")))
        self.assertNotIn("cellgone", document)
        self.assertIn("after", document)

    def test_a_table_style_based_on_a_hiding_one_hides_its_cell_text(self):
        _, document = self.visible(table("HiddenGridChild", para(run("cellgone"))))
        self.assertNotIn("cellgone", document)

    def test_a_table_style_and_a_hiding_paragraph_style_cancel(self):
        _, document = self.visible(table(
            "HiddenGrid", styled_para("Hidden", run("cellshown")), para(run("cellgone"))))
        self.assertIn("cellshown", document)
        self.assertNotIn("cellgone", document)

    def test_the_inner_table_style_decides_for_a_nested_table(self):
        inner = table("ShownGrid", para(run("inner")))
        _, document = self.visible(table("HiddenGrid", para(run("outer")), inner))
        self.assertIn("inner", document)
        self.assertNotIn("outer", document)

    def test_a_text_box_in_a_cell_does_not_take_the_table_style(self):
        box = ('<w:r><w:rPr><w:vanish w:val="0"/></w:rPr><w:pict><w:txbxContent>'
               + para(run("boxed")) + "</w:txbxContent></w:pict></w:r>")
        _, document = self.visible(table("HiddenGrid", para(box, run("cell"))))
        self.assertIn("boxed", document)
        self.assertNotIn("cell<", document)

    def test_a_runs_own_value_beats_the_table_style(self):
        _, document = self.visible(table(
            "HiddenGrid", para(run("own", '<w:vanish w:val="0"/>'), run("styled"))))
        self.assertIn("own", document)
        self.assertNotIn("styled", document)

    def test_a_table_style_the_file_lacks_takes_the_default_table_style(self):
        styles = styled("", DEFAULT_TABLE)
        for named in ("NoSuchStyle", ""):
            _, document = self.visible(table(named, para(run("cellgone"))),
                                       para(run("after")), styles=styles)
            self.assertNotIn("cellgone", document)
            self.assertIn("after", document)

    def test_a_paragraph_with_no_style_takes_the_hiding_default_paragraph_style(self):
        styles = styled("", DEFAULT_PARAGRAPH)
        _, document = self.visible(
            para(run("gone")), styled_para("Shown", run("named")),
            styled_para("NoSuchStyle", run("missing")), para(run("both", JUMP)), styles=styles)
        self.assertNotIn("gone", document)
        self.assertNotIn("missing", document)
        self.assertIn("named", document)
        self.assertIn("both", document)

    def test_the_last_default_paragraph_style_wins_and_a_false_one_is_not_a_default(self):
        off = DEFAULT_PARAGRAPH.replace('w:default="1"', 'w:default="0"')
        _, document = self.visible(para(run("stays")), styles=styled("", off))
        self.assertIn("stays", document)
        shown = ('<w:style w:type="paragraph" w:default="1" w:styleId="Body">'
                 '<w:name w:val="Body"/></w:style>')
        _, document = self.visible(para(run("stays")),
                                   styles=styled("", DEFAULT_PARAGRAPH, shown))
        self.assertIn("stays", document)

    def test_a_default_style_with_no_type_is_a_paragraph_style(self):
        typeless = DEFAULT_PARAGRAPH.replace(' w:type="paragraph"', "")
        _, document = self.visible(para(run("gone")), styles=styled("", typeless))
        self.assertNotIn("gone", document)

    def test_a_paragraph_naming_a_style_of_another_type_takes_the_default(self):
        _, document = self.visible(
            styled_para("Jump", run("stays")), styles=styled("", DEFAULT_PARAGRAPH))
        self.assertNotIn("stays", document)
        _, document = self.visible(styled_para("Jump", run("stays")))
        self.assertIn("stays", document)

    def test_a_style_with_no_id_speaks_for_no_run(self):
        nameless = '<w:style w:type="character"><w:rPr><w:vanish/></w:rPr></w:style>'
        _, document = self.visible(para(run("stays")), styles=styled("", nameless))
        self.assertIn("stays", document)

    def test_a_file_with_no_styles_part_hides_only_what_a_run_says(self):
        whole, source = self.work / "whole.docx", self.work / "in.docx"
        docx(whole, para(run("shown"), run("gone", "<w:vanish/>")))
        with zipfile.ZipFile(whole) as read, zipfile.ZipFile(source, "w") as archive:
            for name in read.namelist():
                if name != "word/styles.xml":
                    archive.writestr(name, read.read(name))
        target = self.work / "out.docx"
        self.assertEqual(HIDDEN.main(["hidden-text.py", str(source), str(target)]), 0)
        with zipfile.ZipFile(target) as archive:
            document = archive.read("word/document.xml").decode("utf-8")
        self.assertIn("shown", document)
        self.assertNotIn("gone", document)

    def test_the_defaults_on_with_both_styles_hiding_hide(self):
        _, document = self.visible(
            styled_para("Hidden", run("x", JUMP)), styles=styled(DEFAULTS_ON))
        self.assertNotIn("x<", document)

    def test_the_defaults_on_with_both_styles_showing_hide(self):
        _, document = self.visible(
            styled_para("Shown", run("x", '<w:rStyle w:val="JumpShown"/>')),
            styled_para("Shown", run("one")), styles=styled(DEFAULTS_ON))
        self.assertNotIn("x<", document)
        self.assertIn("one", document)

    def test_each_combination_of_levels_matches_words_toggle_rule(self):
        # (defaults, table, paragraph, character, hidden): None is a level that
        # says nothing, which takes the defaults' value.
        table_ids = {True: "HiddenGrid", False: "ShownGrid"}
        para_ids = {True: "Hidden", False: "Shown"}
        char_ids = {True: "Jump", False: "JumpShown"}
        cases = [
            (False, None, None, None, False), (False, True, None, None, True),
            (False, True, True, None, False), (False, None, True, None, True),
            (False, None, True, True, False), (False, True, True, True, True),
            (False, False, True, None, True), (False, False, False, False, False),
            (True, None, None, None, True), (True, None, True, True, True),
            (True, None, False, False, True), (True, None, False, None, False),
            (True, None, True, None, True), (True, False, None, None, False),
            (True, False, False, True, True), (True, False, False, False, False),
            (True, True, True, True, True),
        ]
        for defaults, table_style, paragraph, character, hidden in cases:
            with self.subTest(defaults=defaults, table=table_style, paragraph=paragraph,
                              character=character):
                runs = run("x", f'<w:rStyle w:val="{char_ids[character]}"/>' if character
                           is not None else "")
                if paragraph is None:
                    body = para(runs)
                else:
                    body = styled_para(para_ids[paragraph], runs)
                if table_style is not None:
                    body = table(table_ids[table_style], body)
                _, document = self.visible(
                    body, para(run("after", '<w:vanish w:val="0"/>')),
                    styles=styled(DEFAULTS_ON if defaults else ""))
                self.assertEqual("x<" not in document, hidden)
                self.assertIn("after", document)

    def test_spec_vanish_alone_stays(self):
        _, document = self.visible(para(run("Heading text", "<w:specVanish/>")))
        self.assertIn("Heading text", document)

    def test_a_paragraph_whose_mark_is_deleted_joins_the_next(self):
        mark = ('<w:pPr><w:pStyle w:val="Gone"/>'
                f'<w:rPr><w:del w:id="1" {DELETION}/></w:rPr></w:pPr>')
        _, document = self.visible(
            f'<w:p>{mark}{run("Kept ")}<w:del w:id="2" {DELETION}>{run("cut")}</w:del></w:p>',
            '<w:p><w:pPr><w:pStyle w:val="Stays"/></w:pPr>' f'{run("joined.")}</w:p>')
        self.assertEqual(document.count("<w:p>"), 1)
        self.assertNotIn("Gone", document)
        self.assertLess(document.index("Stays"), document.index("Kept "))
        self.assertLess(document.index("Kept "), document.index("joined."))

    def test_a_numbered_paragraph_deleted_whole_leaves_no_paragraph(self):
        mark = ('<w:pPr><w:numPr><w:ilvl w:val="1"/><w:numId w:val="4"/></w:numPr>'
                f'<w:rPr><w:del w:id="1" {DELETION}/></w:rPr></w:pPr>')
        moved = ('<w:pPr><w:numPr><w:ilvl w:val="1"/><w:numId w:val="4"/></w:numPr>'
                 f'<w:rPr><w:moveFrom w:id="3" {DELETION}/></w:rPr></w:pPr>')
        _, document = self.visible(
            f'<w:p>{mark}<w:del w:id="2" {DELETION}><w:r><w:delText>Go To</w:delText></w:r>'
            "</w:del></w:p>",
            f'<w:p>{moved}<w:moveFrom w:id="4" {DELETION}>{run("Moved")}</w:moveFrom></w:p>',
            para(run("Help")))
        self.assertEqual(document.count("<w:p>"), 1)
        self.assertNotIn("numId", document)

    def test_a_deleted_mark_with_no_paragraph_after_it_stays(self):
        mark = f'<w:pPr><w:rPr><w:del w:id="1" {DELETION}/></w:rPr></w:pPr>'
        cell = f'<w:tc><w:p>{mark}{run("last in cell")}</w:p></w:tc>'
        _, document = self.visible(
            f"<w:tbl><w:tr>{cell}</w:tr></w:tbl>", f"<w:p>{mark}{run('before table')}</w:p>",
            f"<w:tbl><w:tr><w:tc>{para(run('x'))}</w:tc></w:tr></w:tbl>")
        self.assertIn("last in cell", document)
        self.assertIn("before table", document)
        self.assertEqual(document.count("<w:p>"), 3)

    def test_a_hidden_run_in_a_table_goes(self):
        cell = f'<w:tc>{para(run("cell"), run("Jump_Name", "<w:vanish/>"))}</w:tc>'
        _, document = self.visible(f"<w:tbl><w:tr>{cell}</w:tr></w:tbl>", para(run("end")))
        self.assertIn("cell", document)
        self.assertNotIn("Jump_Name", document)

    @unittest.skipUnless(shutil.which("pandoc"), "pandoc is not installed")
    def test_a_field_whose_code_is_hidden_keeps_working(self):
        def field(kind, hidden=""):
            rpr = "<w:rPr><w:vanish/></w:rPr>" if hidden else ""
            return f'<w:r>{rpr}<w:fldChar w:fldCharType="{kind}"/></w:r>'
        code = ('<w:r><w:rPr><w:vanish/></w:rPr><w:instrText xml:space="preserve">'
                ' HYPERLINK "http://x.y" </w:instrText></w:r>')
        target, document = self.visible(para(
            run("See "), field("begin", "hidden"), code, field("separate", "hidden"),
            run("link"), field("end"), run(" now")))
        self.assertEqual(document.count("<w:fldChar "), 3)
        self.assertIn("HYPERLINK", document)
        out = subprocess.run(["pandoc", "-f", "docx", "-t", "gfm", str(target)],
                             capture_output=True, text=True, check=True).stdout
        self.assertEqual(out.strip(), "See [link](http://x.y) now")

    def route(self, source):
        """Runs convert.sh's Word route on SOURCE with a Pandoc that records its input.

        Returns the bytes Pandoc was given."""
        script = (HERE / "convert.sh").read_text()
        at = script.index("\nrun_pandoc() {")
        function = script[at:script.index("\n}\n", at) + 3]
        tools = self.work / "tools"
        tools.mkdir()
        (tools / "pandoc").write_text(
            "#!/bin/sh\n"
            'while [ "$#" -gt 0 ]; do\n'
            '  if [ "$2" = "-o" ]; then cp "$1" "$RECORD"; printf text > "$3"; exit 0; fi\n'
            "  shift\n"
            "done\n"
            "exit 1\n")
        (tools / "pandoc").chmod(0o755)
        (self.work / "work").mkdir()
        runner = self.work / "route.sh"
        runner.write_text("set -uo pipefail\nPANDOC_TO=gfm\n" + function +
                          'run_pandoc docx "$1" "$2"\n')
        record = self.work / "recorded.docx"
        result = subprocess.run(
            ["bash", str(runner), str(source), str(self.work / "body.md")],
            capture_output=True, text=True,
            env={"PATH": f"{tools}:{os.environ['PATH']}", "HERE": str(HERE),
                 "WORK": str(self.work / "work"), "RECORD": str(record)})
        self.assertEqual(result.returncode, 0, result.stderr)
        return record.read_bytes()

    def test_convert_gives_pandoc_the_file_without_its_hidden_text(self):
        source = self.work / "in.docx"
        docx(source, para(run("shown"), run("Jump_Name", "<w:vanish/>")))
        recorded = self.work / "seen.docx"
        recorded.write_bytes(self.route(source))
        with zipfile.ZipFile(recorded) as archive:
            document = archive.read("word/document.xml").decode("utf-8")
        self.assertIn("shown", document)
        self.assertNotIn("Jump_Name", document)

    def test_convert_gives_pandoc_the_original_when_the_script_refuses_the_file(self):
        source = self.work / "in.docx"
        whole = self.work / "whole.docx"
        docx(whole, para(run("shown")))
        with zipfile.ZipFile(whole) as read, zipfile.ZipFile(source, "w") as archive:
            for name in read.namelist():
                archive.writestr(name, f'<w:document xmlns:w="{NS}"><w:body>'
                                 if name == "word/document.xml" else read.read(name))
        # The script and the step after it both refuse a part that is cut short.
        self.assertEqual(
            HIDDEN.main(["hidden-text.py", str(source), str(self.work / "out.docx")]), 1)
        self.assertEqual(self.route(source), source.read_bytes())

    def test_convert_numbers_the_lists_before_the_list_markers_filter(self):
        script = (HERE / "convert.sh").read_text()
        hidden = script.index('"$HERE/hidden-text.py" "$input" "$WORK/visible.docx"')
        numbers = script.index('"$HERE/list-numbers.py"')
        markers = script.index('--lua-filter="$HERE/list-markers.lua"')
        self.assertLess(hidden, numbers)
        self.assertLess(numbers, markers)

    def test_a_file_that_is_not_a_zip_fails(self):
        source = self.work / "in.rtf"
        source.write_text("{\\rtf1 plain}")
        self.assertEqual(HIDDEN.main(["hidden-text.py", str(source), str(self.work / "o")]), 1)

    @unittest.skipUnless(shutil.which("pandoc"), "pandoc is not installed")
    def test_a_hidden_paragraph_writes_no_line(self):
        target, _ = self.visible(
            para(run("Before the table.")),
            para(run("Exi", '<w:rFonts w:cs="Arial"/><w:vanish/>')),
            para(run("By selecting "), run("omeHome", "<w:vanish/>"), run("the button.")))
        out = subprocess.run(["pandoc", "-f", "docx", "-t", "gfm", str(target)],
                             capture_output=True, text=True, check=True).stdout
        self.assertEqual([line for line in out.splitlines() if line.strip()],
                         ["Before the table.", "By selecting the button."])


if __name__ == "__main__":
    unittest.main()
