#!/usr/bin/env python3
"""Cases for slides.py: what a deck's slides turn into in Markdown."""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from xml.sax.saxutils import escape

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import slides  # noqa: E402

P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

CT = "application/vnd.openxmlformats-officedocument.presentationml"

MASTER = (
    f'<p:sldMaster xmlns:p="{P}" xmlns:a="{A}" xmlns:r="{R}"><p:cSld><p:spTree/></p:cSld>'
    '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
    '<p:txStyles><p:titleStyle/><p:bodyStyle>'
    '<a:lvl1pPr><a:buChar char="&#8226;"/></a:lvl1pPr>'
    '<a:lvl2pPr><a:buChar char="-"/></a:lvl2pPr>'
    '</p:bodyStyle><p:otherStyle/></p:txStyles></p:sldMaster>'
)


def layout(placeholders: str = "") -> str:
    return (f'<p:sldLayout xmlns:p="{P}" xmlns:a="{A}" xmlns:r="{R}">'
            f'<p:cSld><p:spTree>{placeholders}</p:spTree></p:cSld></p:sldLayout>')


def para(text: str = "", lvl: int = 0, bullet: str | None = None, br: bool = False) -> str:
    """One `a:p`. `bullet` is `none`, `char`, or an autonumber scheme such as
    `arabicPeriod` or `arabicPeriod:3` for a start."""
    props = ""
    if bullet == "none":
        props = "<a:buNone/>"
    elif bullet == "char":
        props = '<a:buChar char="&#8226;"/>'
    elif bullet:
        scheme, _, start = bullet.partition(":")
        at = f' startAt="{start}"' if start else ""
        props = f'<a:buAutoNum type="{scheme}"{at}/>'
    ppr = f'<a:pPr lvl="{lvl}">{props}</a:pPr>' if (lvl or props) else ""
    runs = "".join(
        f"<a:r><a:t>{escape(piece)}</a:t></a:r>" + ("<a:br/>" if br and i == 0 else "")
        for i, piece in enumerate(text.split("\n") if br else [text]) if piece
    )
    return f"<a:p>{ppr}{runs}</a:p>"


def shape(name: str, *paragraphs: str, ph: str | None = None, lst: str = "") -> str:
    placeholder = f"<p:nvPr>{ph}</p:nvPr>" if ph else "<p:nvPr/>"
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="2" name="{name}"/><p:cNvSpPr/>{placeholder}'
            f'</p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle>{lst}</a:lstStyle>'
            f'{"".join(paragraphs)}</p:txBody></p:sp>')


def title(text: str) -> str:
    return shape("Title 1", para(text), ph='<p:ph type="title"/>')


def body(*paragraphs: str, idx: int = 1) -> str:
    return shape("Content Placeholder 2", *paragraphs, ph=f'<p:ph idx="{idx}"/>')


def group(*shapes: str) -> str:
    return (f'<p:grpSp><p:nvGrpSpPr><p:cNvPr id="9" name="Group 9"/><p:cNvGrpSpPr/>'
            f'<p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>{"".join(shapes)}</p:grpSp>')


def picture() -> str:
    return ('<p:pic><p:nvPicPr><p:cNvPr id="4" name="Picture 3"/><p:cNvPicPr/><p:nvPr/>'
            '</p:nvPicPr><p:blipFill/><p:spPr/></p:pic>')


def table(rows: list[list[str]], merged: set[tuple[int, int]] = frozenset()) -> str:
    out = []
    for r, row in enumerate(rows):
        cells = []
        for c, cell in enumerate(row):
            attr = ' hMerge="1"' if (r, c) in merged else ""
            paras = "".join(para(text) for text in cell.split("\n"))
            cells.append(f"<a:tc{attr}><a:txBody><a:bodyPr/>{paras}</a:txBody></a:tc>")
        out.append(f'<a:tr h="1">{"".join(cells)}</a:tr>')
    return (f'<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="5" name="Table 4"/>'
            f'<p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr><p:xfrm/>'
            f'<a:graphic><a:graphicData><a:tbl><a:tblGrid/>{"".join(out)}</a:tbl>'
            f'</a:graphicData></a:graphic></p:graphicFrame>')


def slide(*shapes: str, hidden: bool = False) -> str:
    show = ' show="0"' if hidden else ""
    return (f'<p:sld xmlns:p="{P}" xmlns:a="{A}" xmlns:r="{R}" xmlns:mc="{MC}"{show}>'
            f'<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/>'
            f'<p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>{"".join(shapes)}</p:spTree></p:cSld>'
            f'</p:sld>')


def deck(path: pathlib.Path, slides_xml: list[str], order: list[int] | None = None,
         layout_xml: str | None = None) -> pathlib.Path:
    """Writes a deck whose part slideN.xml holds slides_xml[N-1], shown in ORDER
    (1-based part numbers, default as listed). LibreOffice opens it too."""
    order = order or list(range(1, len(slides_xml) + 1))
    overrides = [("/ppt/presentation.xml", "presentation.main"),
                 ("/ppt/slideMasters/slideMaster1.xml", "slideMaster"),
                 ("/ppt/slideLayouts/slideLayout1.xml", "slideLayout")]
    overrides += [(f"/ppt/slides/slide{n}.xml", "slide")
                  for n in range(1, len(slides_xml) + 1)]
    parts = {
        "[Content_Types].xml":
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-'
            'package.relationships+xml"/><Default Extension="xml" '
            'ContentType="application/xml"/>'
            + "".join(f'<Override PartName="{name}" ContentType="{CT}.{kind}+xml"/>'
                      for name, kind in overrides) + "</Types>",
        "_rels/.rels": f'<Relationships xmlns="{PKG}"><Relationship Id="rId1" '
                       f'Type="{REL}/officeDocument" Target="ppt/presentation.xml"/>'
                       '</Relationships>',
        "ppt/slideMasters/slideMaster1.xml": MASTER,
        "ppt/slideMasters/_rels/slideMaster1.xml.rels":
            f'<Relationships xmlns="{PKG}"><Relationship Id="rId1" '
            f'Type="{REL}/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
            '</Relationships>',
        "ppt/slideLayouts/slideLayout1.xml": layout_xml or layout(),
        "ppt/slideLayouts/_rels/slideLayout1.xml.rels":
            f'<Relationships xmlns="{PKG}"><Relationship Id="rId1" '
            f'Type="{REL}/slideMaster" Target="../slideMasters/slideMaster1.xml"/>'
            '</Relationships>',
    }
    ids, rels = [], []
    for position, number in enumerate(order):
        ids.append(f'<p:sldId id="{256 + position}" r:id="rId{100 + number}"/>')
        rels.append(f'<Relationship Id="rId{100 + number}" Type="{REL}/slide" '
                    f'Target="slides/slide{number}.xml"/>')
    for number, xml in enumerate(slides_xml, start=1):
        parts[f"ppt/slides/slide{number}.xml"] = xml
        parts[f"ppt/slides/_rels/slide{number}.xml.rels"] = (
            f'<Relationships xmlns="{PKG}"><Relationship Id="rId1" '
            f'Type="{REL}/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
            '</Relationships>')
    parts["ppt/presentation.xml"] = (
        f'<p:presentation xmlns:p="{P}" xmlns:r="{R}"><p:sldMasterIdLst>'
        '<p:sldMasterId id="2147483648" r:id="rIdMaster"/></p:sldMasterIdLst>'
        f'<p:sldIdLst>{"".join(ids)}</p:sldIdLst><p:sldSz cx="9144000" cy="6858000"/>'
        '<p:notesSz cx="6858000" cy="9144000"/></p:presentation>')
    rels.append(f'<Relationship Id="rIdMaster" Type="{REL}/slideMaster" '
                'Target="slideMasters/slideMaster1.xml"/>')
    parts["ppt/_rels/presentation.xml.rels"] = (
        f'<Relationships xmlns="{PKG}">{"".join(rels)}</Relationships>')
    with zipfile.ZipFile(path, "w") as archive:
        for name, xml in parts.items():
            archive.writestr(name, xml)
    return path


class Case(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def md(self, slides_xml: list[str], **kwargs) -> str:
        return slides.markdown(deck(self.dir / "deck.pptx", slides_xml, **kwargs))


class FreeShapes(Case):
    def test_rectangles_without_placeholders_all_reach_the_markdown(self) -> None:
        out = self.md([slide(
            shape("Rectangle 2", para("Stage Summary")),
            shape("Rectangle 3", para("Trigger: Stage Summary button")),
            shape("Rectangle 9", para("Mode is always read-only from Stage Summary",
                                      bullet="char")),
        )])
        self.assertEqual(out, (
            "# Slide 1\n\n"
            "Stage Summary\n\n"
            "Trigger: Stage Summary button\n\n"
            "- Mode is always read-only from Stage Summary\n"))

    def test_text_boxes_beside_a_title_keep_their_lists(self) -> None:
        out = self.md([slide(
            title("Default View"),
            shape("TextBox 3", para("The default view shows the current year.")),
            shape("TextBox 4",
                  para("Sequence"),
                  para("Open the student", bullet="arabicPeriod"),
                  para("Pick a year", lvl=1, bullet="char"),
                  para("Pick a term", lvl=1, bullet="char"),
                  para("Save", bullet="arabicPeriod")),
        )])
        self.assertEqual(out, (
            "# Default View\n\n"
            "The default view shows the current year.\n\n"
            "Sequence\n\n"
            "1. Open the student\n"
            "   - Pick a year\n"
            "   - Pick a term\n"
            "2. Save\n"))

    def test_the_title_leads_wherever_it_sits_in_the_shape_tree(self) -> None:
        out = self.md([slide(shape("TextBox 1", para("Body text")), title("Late Title"))])
        self.assertEqual(out, "# Late Title\n\nBody text\n")

    def test_grouped_shapes_appear_in_place(self) -> None:
        out = self.md([slide(
            shape("A", para("before")),
            group(shape("B", para("inner one")), group(shape("C", para("inner two")))),
            shape("D", para("after")),
        )])
        self.assertEqual(out, "# Slide 1\n\nbefore\n\ninner one\n\ninner two\n\nafter\n")

    def test_alternate_content_is_read_from_its_fallback(self) -> None:
        wrapped = (f'<mc:AlternateContent><mc:Choice Requires="x">'
                   f'{shape("New", para("choice text"))}</mc:Choice>'
                   f'<mc:Fallback>{shape("Old", para("fallback text"))}</mc:Fallback>'
                   '</mc:AlternateContent>')
        self.assertEqual(self.md([slide(wrapped)]), "# Slide 1\n\nfallback text\n")

    def test_line_break_inside_a_paragraph(self) -> None:
        out = self.md([slide(shape("A", para("first\nsecond", br=True)))])
        self.assertEqual(out, "# Slide 1\n\nfirst\\\nsecond\n")

    def test_markdown_syntax_in_slide_text_is_escaped(self) -> None:
        out = self.md([slide(shape("A", para("# not a heading"), para("1. not a list"),
                                   para("- dash"), para("a *star* and STUDENT_ID")))])
        self.assertEqual(out, (
            "# Slide 1\n\n\\# not a heading\n\n1\\. not a list\n\n\\- dash\n\n"
            "a \\*star\\* and STUDENT_ID\n"))

    def test_footer_date_and_slide_number_placeholders_are_left_out(self) -> None:
        out = self.md([slide(
            title("T"),
            shape("Footer", para("Company confidential"), ph='<p:ph type="ftr" idx="11"/>'),
            shape("Number", para("7"), ph='<p:ph type="sldNum" idx="12"/>'),
            shape("Date", para("1/2/2024"), ph='<p:ph type="dt" idx="10"/>'),
        )])
        self.assertEqual(out, "# T\n")


class Bullets(Case):
    def test_body_placeholder_is_bulleted_from_the_master(self) -> None:
        out = self.md([slide(title("T"), body(para("one"), para("two", lvl=1)))])
        self.assertEqual(out, "# T\n\n- one\n  - two\n")

    def test_bu_none_in_a_body_placeholder_is_a_paragraph(self) -> None:
        out = self.md([slide(title("T"), body(para("plain", bullet="none"), para("item")))])
        self.assertEqual(out, "# T\n\nplain\n\n- item\n")

    def test_bu_none_on_the_layout_placeholder_is_inherited(self) -> None:
        placeholder = shape("Body", ph='<p:ph idx="1"/>',
                            lst="<a:lvl1pPr><a:buNone/></a:lvl1pPr>")
        out = self.md([slide(title("T"), body(para("plain")))],
                      layout_xml=layout(placeholder))
        self.assertEqual(out, "# T\n\nplain\n")

    def test_bu_none_in_the_shapes_own_list_style_wins(self) -> None:
        own = shape("Body", para("plain"), ph='<p:ph idx="1"/>',
                    lst="<a:lvl1pPr><a:buNone/></a:lvl1pPr>")
        self.assertEqual(self.md([slide(own)]), "# Slide 1\n\nplain\n")

    def test_numbering_starts_at_and_resumes_after_a_nested_bullet(self) -> None:
        out = self.md([slide(shape("A",
            para("three", bullet="arabicPeriod:3"),
            para("nested", lvl=1, bullet="char"),
            para("four", bullet="arabicPeriod"),
        ))])
        self.assertEqual(out, "# Slide 1\n\n3. three\n   - nested\n4. four\n")

    def test_a_plain_paragraph_restarts_the_numbering(self) -> None:
        out = self.md([slide(shape("A",
            para("one", bullet="arabicPeriod"), para("break"),
            para("again", bullet="arabicPeriod"),
        ))])
        self.assertEqual(out, "# Slide 1\n\n1. one\n\nbreak\n\n1. again\n")

    def test_lettered_and_roman_items_carry_their_label(self) -> None:
        out = self.md([slide(shape("A",
            para("first", bullet="alphaLcParenR"), para("second", bullet="alphaLcParenR"),
            para("big", bullet="romanUcPeriod:4"),
        ))])
        self.assertEqual(out, "# Slide 1\n\n- a) first\n- b) second\n- IV. big\n")


class Order(Case):
    def test_slides_follow_the_presentation_order_not_file_names(self) -> None:
        out = self.md([slide(title("Part one")), slide(title("Part two"))], order=[2, 1])
        self.assertEqual(out, "# Part two\n\n# Part one\n")

    def test_hidden_slides_are_left_out_and_numbering_counts_shown_slides(self) -> None:
        path = deck(self.dir / "d.pptx", [slide(), slide(title("Hidden"), hidden=True),
                                          slide()])
        self.assertEqual(slides.markdown(path), "# Slide 1\n\n# Slide 2\n")
        self.assertEqual(slides.headings(path), ["Slide 1", "Slide 2"])

    def test_image_only_and_empty_slides_keep_their_heading(self) -> None:
        out = self.md([slide(picture()), slide(shape("Empty", para()))])
        self.assertEqual(out, "# Slide 1\n\n# Slide 2\n")

    def test_title_syntax_is_escaped_without_a_line_start_escape(self) -> None:
        out = self.md([slide(title("*Key* step 1. of C#"))])
        self.assertEqual(out, "# \\*Key\\* step 1. of C\\#\n")

    def test_a_title_with_nothing_to_match_on_is_numbered(self) -> None:
        path = deck(self.dir / "d.pptx", [slide(title("--")), slide(title("Real"))])
        self.assertEqual(slides.headings(path), ["Slide 1", "Real"])


class Tables(Case):
    def test_table_becomes_a_pipe_table(self) -> None:
        out = self.md([slide(table(
            [["Field", "Rule"], ["Year", "Required\nFour digits"], ["A|B", "x"]],
        ))])
        self.assertEqual(out, (
            "# Slide 1\n\n"
            "| Field | Rule |\n"
            "| ---- | ---- |\n"
            "| Year | Required; Four digits |\n"
            "| A\\|B | x |\n"))

    def test_merged_continuation_cells_are_empty(self) -> None:
        out = self.md([slide(table([["Wide", "ghost"], ["a", "b"]], merged={(0, 1)}))])
        self.assertIn("| Wide |  |\n", out)


TOOLS = ("pandoc", "soffice", "pdftotext", "pdfinfo", "git")


@unittest.skipUnless(all(shutil.which(tool) for tool in TOOLS),
                     "convert.sh needs " + ", ".join(TOOLS))
class ConvertRun(Case):
    """convert.sh on whole decks, from the source folder to the stamped Markdown."""

    def run_convert(self, name: str, make) -> tuple[str, str]:
        repo = self.dir / "repo"
        group = repo / "todo" / "Deck"
        group.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "words.txt").write_text(
            "\n".join("stage summary trigger button mode always read only from default "
                       "view shows current year sequence open student pick save the "
                       "is a of".split()) + "\n", encoding="utf-8")
        (repo / "extension.json").write_text(json.dumps({
            "todoRoot": "todo", "appsRoot": "apps", "futureFolder": "Future",
            "words": "words.txt", "collisions": "collisions.tsv",
            "sharePointHost": "https://example.invalid",
        }), encoding="utf-8")
        make(group / name)
        run = subprocess.run(
            ["bash", str(HERE / "convert.sh"), "--config", str(repo / "extension.json"),
             "--keep-sources", "--converted", "2024-01-02 03:04Z"],
            capture_output=True, text=True, check=False, timeout=600)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        out = repo / "apps" / "Deck" / (pathlib.Path(name).stem + ".md")
        self.assertTrue(out.is_file(), run.stdout + run.stderr)
        return out.read_text(encoding="utf-8"), run.stdout

    SLIDES = [
        slide(shape("Rectangle 2", para("Stage Summary")),
              shape("Rectangle 3", para("Trigger: Stage Summary button")),
              shape("Rectangle 9", para("Mode is always read-only from Stage Summary",
                                        bullet="char"))),
        slide(picture()),
        slide(title("Default View"),
              shape("TextBox 3", para("The default view shows the current year.")),
              shape("TextBox 4", para("Sequence"),
                    para("Open the student", bullet="arabicPeriod"),
                    para("Pick a year", lvl=1, bullet="char"),
                    para("Save", bullet="arabicPeriod"))),
    ]

    def check(self, text: str, log: str) -> None:
        for expected in ["Trigger: Stage Summary button",
                         "- Mode is always read-only from Stage Summary",
                         "The default view shows the current year.",
                         "1. Open the student\n   - Pick a year\n2. Save"]:
            self.assertIn(expected, text)
        self.assertEqual(
            [line for line in text.split("\n") if line.startswith("<a id=\"page-")],
            ['<a id="page-1"></a>*Page 1*', '<a id="page-2"></a>*Page 2*',
             '<a id="page-3"></a>*Page 3*'])
        self.assertIn("3 page(s) one per slide shown in the deck, 0 not found", log)

    def test_a_deck_of_text_boxes_converts_with_a_marker_per_slide(self) -> None:
        self.check(*self.run_convert("Layout.pptx", lambda path: deck(path, self.SLIDES)))

    def test_a_legacy_deck_goes_through_a_modern_copy(self) -> None:
        def make(path: pathlib.Path) -> None:
            modern = deck(self.dir / "Layout.pptx", self.SLIDES)
            subprocess.run(["soffice", "--headless", "--convert-to", "ppt", "--outdir",
                            str(path.parent), str(modern)],
                           capture_output=True, check=True, timeout=300)
        self.check(*self.run_convert("Layout.ppt", make))


class Misreadings(Case):
    """Slide text that Markdown, or the cleanup after it, would otherwise misread."""

    def test_text_only_in_a_choice_branch_is_read(self) -> None:
        wrapped = (f'<mc:AlternateContent><mc:Choice Requires="x">'
                   f'{shape("New", para("choice text"))}</mc:Choice>'
                   f'<mc:Fallback>{picture()}</mc:Fallback></mc:AlternateContent>')
        self.assertEqual(self.md([slide(wrapped)]), "# Slide 1\n\nchoice text\n")

    def test_an_inline_equation_keeps_its_fallback_text(self) -> None:
        equation = (f'<a:p><a:r><a:t>Rate is </a:t></a:r><mc:AlternateContent>'
                    f'<mc:Choice Requires="a14"><a:t>ignored</a:t></mc:Choice>'
                    f'<mc:Fallback><a:r><a:t>x/2</a:t></a:r></mc:Fallback>'
                    f'</mc:AlternateContent><a:r><a:t> per hour</a:t></a:r></a:p>')
        out = self.md([slide(shape("A", equation))])
        self.assertEqual(out, "# Slide 1\n\nRate is x/2 per hour\n")

    def test_a_powerpoint_equation_keeps_its_math_text(self) -> None:
        # PowerPoint keeps the equation's text in Office Math under the first
        # choice and draws the fallback as a picture holding a space.
        equation = (
            '<a:p><a:r><a:t>Rate is </a:t></a:r><mc:AlternateContent>'
            '<mc:Choice xmlns:a14="http://schemas.microsoft.com/office/drawing/2010/main"'
            ' Requires="a14"><a14:m><m:oMathPara'
            ' xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
            '<m:oMath><m:r><m:t>x</m:t></m:r><m:r><m:t>/2</m:t></m:r></m:oMath>'
            '</m:oMathPara></a14:m></mc:Choice>'
            '<mc:Fallback><a:r><a:t> </a:t></a:r></mc:Fallback>'
            '</mc:AlternateContent><a:r><a:t> per hour</a:t></a:r></a:p>')
        out = self.md([slide(shape("A", equation))])
        self.assertEqual(out, "# Slide 1\n\nRate is x/2 per hour\n")

    def test_equation_lines_stay_apart_and_strict_math_is_read(self) -> None:
        for math in ("http://schemas.openxmlformats.org/officeDocument/2006/math",
                     "http://purl.oclc.org/ooxml/officeDocument/math"):
            with self.subTest(math=math):
                equation = (
                    '<a:p><mc:AlternateContent>'
                    '<mc:Choice xmlns:a14="http://schemas.microsoft.com/office/drawing/2010/main"'
                    f' Requires="a14"><a14:m><m:oMathPara xmlns:m="{math}">'
                    '<m:oMath><m:r><m:t>a=1</m:t></m:r></m:oMath>'
                    '<m:oMath><m:r><m:t>b=2</m:t></m:r></m:oMath>'
                    '</m:oMathPara></a14:m></mc:Choice>'
                    '<mc:Fallback><a:r><a:t> </a:t></a:r></mc:Fallback>'
                    '</mc:AlternateContent></a:p>')
                self.assertEqual(self.md([slide(shape("A", equation))]),
                                 "# Slide 1\n\na=1 b=2\n")

    def test_a_title_with_nothing_to_match_on_keeps_its_text(self) -> None:
        self.assertEqual(self.md([slide(title("??"))]), "# Slide 1\n\n??\n")

    def test_a_title_in_another_script_is_the_heading(self) -> None:
        self.assertEqual(self.md([slide(title("Αρχή"))]), "# Αρχή\n")

    def test_fences_rules_and_setext_lines_are_escaped(self) -> None:
        out = self.md([slide(shape("A", para("~~~"), para("---"), para("Total\n===", br=True),
                                   para("~~gone~~")))])
        self.assertEqual(out, (
            "# Slide 1\n\n\\~\\~\\~\n\n\\---\n\nTotal\\\n\\===\n\n"
            "\\~\\~gone\\~\\~\n"))

    def test_a_number_label_after_a_bullet_is_text(self) -> None:
        out = self.md([slide(shape("A", para("one", bullet="arabicParenR"),
                                   para("two", bullet="arabicParenR")))])
        self.assertEqual(out, "# Slide 1\n\n- 1\\) one\n- 2\\) two\n")

    def test_a_nested_list_starting_past_one_opens_after_a_blank_line(self) -> None:
        out = self.md([slide(shape("A", para("a", bullet="char"),
                                   para("b", lvl=1, bullet="arabicPeriod:3"),
                                   para("c", lvl=1, bullet="arabicPeriod")))])
        self.assertEqual(out, "# Slide 1\n\n- a\n\n  3. b\n  4. c\n")

    def test_a_slide_hidden_as_false_is_left_out(self) -> None:
        hidden = slide(title("Hidden")).replace("<p:sld ", '<p:sld show="false" ', 1)
        self.assertEqual(self.md([slide(title("Shown")), hidden]), "# Shown\n")

    def test_a_placeholder_without_a_layout_index_match_matches_by_type(self) -> None:
        placeholder = shape("Body", ph='<p:ph type="body" idx="7"/>',
                            lst="<a:lvl1pPr><a:buNone/></a:lvl1pPr>")
        own = shape("Body", para("plain"), ph='<p:ph type="body" idx="1"/>')
        self.assertEqual(self.md([slide(own)], layout_xml=layout(placeholder)),
                         "# Slide 1\n\nplain\n")

    def test_cleanup_leaves_escaped_slide_text_alone(self) -> None:
        import stamp
        path = deck(self.dir / "d.pptx", [
            slide(title("Results {draft}")),
            slide(title("[Beta]{x} plan"), shape("A", para("Use <img src=a> tags"))),
            slide(table([["| lead", "x"], ["a", "b"]])),
        ])
        cleaned = stamp.clean(slides.markdown(path))
        self.assertIn("## Results \\{draft}\n", cleaned)
        self.assertIn("## \\[Beta\\]\\{x} plan\n", cleaned)
        self.assertIn("Use \\<img src=a> tags", cleaned)
        self.assertIn("| \\| lead | x |\n", cleaned)


class Failures(Case):
    def test_a_strict_deck_is_read(self) -> None:
        path = deck(self.dir / "strict.pptx", [slide(title("Strict title"))])
        with zipfile.ZipFile(path) as archive:
            parts = {name: archive.read(name) for name in archive.namelist()}
        for name, data in parts.items():
            for old, new in slides.STRICT.items():
                data = data.replace(new.encode(), old.encode())
            parts[name] = data
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in parts.items():
                archive.writestr(name, data)
        self.assertEqual(slides.markdown(path), "# Strict title\n")

    def test_a_deck_showing_no_slides_fails(self) -> None:
        path = deck(self.dir / "none.pptx", [slide(hidden=True)])
        target = self.dir / "out.md"
        result = subprocess.run(
            [sys.executable, str(HERE / "slides.py"), str(path), str(target)],
            capture_output=True, text=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(target.exists())

    def test_malformed_slide_fails_without_writing(self) -> None:
        path = deck(self.dir / "bad.pptx", ["<p:sld"])
        target = self.dir / "out.md"
        result = subprocess.run(
            [sys.executable, str(HERE / "slides.py"), str(path), str(target)],
            capture_output=True, text=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(target.exists())

    def test_command_line_writes_the_markdown(self) -> None:
        path = deck(self.dir / "ok.pptx", [slide(title("Hello"))])
        target = self.dir / "out.md"
        subprocess.run([sys.executable, str(HERE / "slides.py"), str(path), str(target)],
                       check=True)
        self.assertEqual(target.read_text(encoding="utf-8"), "# Hello\n")


if __name__ == "__main__":
    unittest.main()
