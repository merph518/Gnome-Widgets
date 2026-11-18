#!/usr/bin/env python3
"""Cases for drop-images.lua: the placeholder a picture leaves, the space a paragraph
opens with, and where emphasis starts in a word. A last case reads the converted
text back for code blocks the source does not hold."""
from __future__ import annotations

import base64
import importlib.util
import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
FILTERS = [HERE / "drop-images.lua", HERE / "flatten-tables.lua", HERE / "list-markers.lua"]

# The Word file builders the list-numbers cases already use.
SPEC = importlib.util.spec_from_file_location("list_numbers_test", HERE / "list-numbers_test.py")
WORD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORD)
HIDDEN_SPEC = importlib.util.spec_from_file_location("hidden_text", HERE / "hidden-text.py")
HIDDEN = importlib.util.module_from_spec(HIDDEN_SPEC)
HIDDEN_SPEC.loader.exec_module(HIDDEN)

BOOKMARK = '<w:bookmarkStart w:id="1" w:name="_Ref1"/><w:bookmarkEnd w:id="1"/>'
BOLD_ITALIC = "<w:b/><w:i/>"

# A one-pixel PNG, and the parts a Word file needs to hold it.
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA"
                       "60e6kgAAAABJRU5ErkJggg==")
PICTURE_NAMESPACES = (
    f'xmlns:w="{WORD.NS}" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture" '
    'xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office"')
PICTURE_RELATIONSHIP = (
    '<Relationship Id="rIdImg" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/image" Target="media/image1.png"/>')
CAPTION_STYLE = ('<w:style w:type="paragraph" w:styleId="Caption"><w:name w:val="caption"/>'
                 "</w:style>")


def run(text, properties=""):
    properties = f"<w:rPr>{properties}</w:rPr>" if properties else ""
    return f'<w:r>{properties}<w:t xml:space="preserve">{text}</w:t></w:r>'


def para(content, num_id=None, ilvl=0):
    """A paragraph built from the runs and bookmarks given."""
    ppr = ""
    if num_id is not None:
        ppr = (f'<w:pPr><w:numPr><w:ilvl w:val="{ilvl}"/><w:numId w:val="{num_id}"/>'
               f"</w:numPr></w:pPr>")
    return f"<w:p>{ppr}{content}</w:p>"


def picture(name="Picture 1", descr=None, title=None, floating=False):
    """A run holding a picture: inline, the shape LibreOffice writes for a .doc
    picture, or floating, anchored to its paragraph."""
    described = "" if descr is None else f' descr="{descr}"'
    titled = "" if title is None else f' title="{title}"'
    if floating:
        opening = (
            '<wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" relativeHeight="1"'
            ' behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1">'
            '<wp:simplePos x="0" y="0"/>'
            '<wp:positionH relativeFrom="column"><wp:posOffset>0</wp:posOffset></wp:positionH>'
            '<wp:positionV relativeFrom="paragraph"><wp:posOffset>0</wp:posOffset></wp:positionV>'
            '<wp:extent cx="95250" cy="85725"/><wp:wrapNone/>')
        closing = "</wp:anchor>"
    else:
        opening = ('<wp:inline distT="0" distB="0" distL="0" distR="0">'
                   '<wp:extent cx="95250" cy="85725"/>')
        closing = "</wp:inline>"
    return (
        f'<w:r><w:drawing>{opening}'
        f'<wp:docPr id="1" name="{name}"{described}{titled}/>'
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic><pic:nvPicPr><pic:cNvPr id="0" name="image1.png"/><pic:cNvPicPr/></pic:nvPicPr>'
        '<pic:blipFill><a:blip r:embed="rIdImg"/><a:stretch><a:fillRect/></a:stretch>'
        '</pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="95250" cy="85725"/>'
        '</a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
        f"</a:graphicData></a:graphic>{closing}</w:drawing></w:r>")


def vml_picture():
    """A run holding a picture in the older VML form. Pandoc reads no alt text from it."""
    return ('<w:r><w:pict><v:shape id="_x0000_i1025" type="#_x0000_t75" alt="Pin icon"'
            ' style="width:9pt;height:9pt"><v:imagedata r:id="rIdImg" o:title=""/></v:shape>'
            "</w:pict></w:r>")


def linked(content):
    """Content inside a hyperlink to an outside address."""
    return f'<w:hyperlink r:id="rIdLink">{content}</w:hyperlink>'


def cell(*paragraphs):
    return f"<w:tc>{''.join(paragraphs)}</w:tc>"


def table(*rows):
    """A two-column table, one list of cells per row."""
    grid = '<w:tblGrid><w:gridCol w:w="2000"/><w:gridCol w:w="2000"/></w:tblGrid>'
    return f"<w:tbl>{grid}{''.join(f'<w:tr>{"".join(cells)}</w:tr>' for cells in rows)}</w:tbl>"


def pictured_docx(path, body, definitions=None):
    """A Word file like WORD.docx's, with one picture part the body's pictures show."""
    content_types = WORD.CONTENT_TYPES.replace(
        '<Default Extension="xml"',
        '<Default Extension="png" ContentType="image/png"/><Default Extension="xml"')
    relationships = WORD.DOCUMENT_RELS.replace(
        "</Relationships>",
        PICTURE_RELATIONSHIP + '<Relationship Id="rIdLink" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/hyperlink" Target="https://example.com/" '
        'TargetMode="External"/></Relationships>')
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", WORD.RELS)
        archive.writestr("word/_rels/document.xml.rels", relationships)
        archive.writestr("word/styles.xml", WORD.STYLES.replace("</w:styles>",
                                                                CAPTION_STYLE + "</w:styles>"))
        archive.writestr("word/media/image1.png", PNG)
        archive.writestr(
            "word/document.xml",
            f'<?xml version="1.0" encoding="UTF-8"?><w:document {PICTURE_NAMESPACES}>'
            f"<w:body>{''.join(body)}</w:body></w:document>")
        if definitions is not None:
            archive.writestr(
                "word/numbering.xml",
                f'<?xml version="1.0" encoding="UTF-8"?><w:numbering xmlns:w="{WORD.NS}">'
                f"{''.join(definitions)}</w:numbering>")


def nodes(node, kind: str) -> int:
    """How many nodes of one kind a Pandoc tree holds."""
    if isinstance(node, dict):
        return (node.get("t") == kind) + sum(nodes(v, kind) for v in node.values())
    if isinstance(node, list):
        return sum(nodes(value, kind) for value in node)
    return 0


def rules(start):
    """A digit list that counts from `start`, with a letter list under each item."""
    return [
        WORD.abstract(1, WORD.level(0, left=720, start=start),
                      WORD.level(1, fmt="lowerLetter", text="%2.", left=1440)),
        WORD.num(1, 1),
    ]


def code_blocks(node) -> int:
    """How many code blocks a Pandoc tree holds."""
    return nodes(node, "CodeBlock")


def tree(source, reader: str, text: str | None = None):
    command = ["pandoc", "-f", reader, "-t", "json"] + ([] if source is None else [str(source)])
    return json.loads(subprocess.run(
        command, input=text, capture_output=True, text=True, check=True).stdout)


def written(source: pathlib.Path, reader: str) -> str:
    """What convert.sh's Pandoc call writes."""
    command = ["pandoc", "-f", reader, "-t", "gfm-raw_html-raw_attribute",
               "--columns=100", "--wrap=auto"]
    command += [f"--lua-filter={path}" for path in FILTERS] + [str(source)]
    return subprocess.run(command, capture_output=True, text=True, check=True).stdout


class WordCase(unittest.TestCase):
    """Builds a Word file and converts it as convert.sh does."""

    def setUp(self):
        self.work = pathlib.Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.work)

    def numbered(self, body, definitions=None, build=WORD.docx) -> pathlib.Path:
        """The Word file Pandoc reads in convert.sh: built, then rewritten twice."""
        source = self.work / "in.docx"
        visible, target = self.work / "visible.docx", self.work / "out.docx"
        build(source, body, definitions)
        self.assertEqual(HIDDEN.main(["hidden-text.py", str(source), str(visible)]), 0)
        self.assertEqual(WORD.LIST.main(["list-numbers.py", str(visible), str(target)]), 0)
        return target

    def word(self, body, definitions=None, build=WORD.docx) -> list[str]:
        text = written(self.numbered(body, definitions, build), "docx")
        return [line for line in text.splitlines() if line.strip()]


@unittest.skipUnless(shutil.which("pandoc"), "pandoc is not installed")
class LeadingSpaceTest(WordCase):
    def test_a_rule_opening_with_a_space_behind_a_bookmark_keeps_its_sub_list(self):
        body = [para(BOOKMARK + run(" ") + run("The grid will:"), 1, 0),
                para(run("hold a check box column"), 1, 1),
                para(run("allow sorting"), 1, 1),
                para(run("The next rule"), 1, 0)]
        for start, label, next_label in ((25, "25. ", "26. "), (1, "1.  ", "2.  ")):
            with self.subTest(start=start):
                target = self.numbered(body, rules(start))
                text = written(target, "docx")
                self.assertEqual([line for line in text.splitlines() if line.strip()], [
                    f"{label}The grid will:", r"    - a\. hold a check box column",
                    r"    - b\. allow sorting", f"{next_label}The next rule",
                ])
                read = tree(None, "gfm", text)
                self.assertEqual(code_blocks(read), 0)
                first_item = read["blocks"][0]["c"][1][0]
                self.assertEqual([block["t"] for block in first_item], ["Para", "BulletList"])

    def test_a_space_that_opens_emphasis_behind_a_bookmark_goes_too(self):
        body = [para(BOOKMARK + run(" (Later)", "<w:i/>") + run(" The grid will:"), 1, 0),
                para(run("allow sorting"), 1, 1)]
        self.assertEqual(self.word(body, rules(114)), [
            "114. *(Later)* The grid will:", r"     - a\. allow sorting",
        ])

    def test_a_lettered_item_opening_with_a_space_takes_one_space_after_its_letter(self):
        body = [para(run("The grid will:"), 1, 0),
                para(BOOKMARK + run(" ") + run("allow sorting"), 1, 1)]
        self.assertEqual(self.word(body, rules(1)), [
            "1.  The grid will:", r"    - a\. allow sorting",
        ])

    def test_a_paragraph_of_one_space_behind_a_bookmark_writes_nothing(self):
        body = [para(run("Above")), para(BOOKMARK + run(" ")), para(run("Below"))]
        self.assertEqual(self.word(body), ["Above", "Below"])

    def test_a_paragraph_that_reads_like_a_list_marker_behind_a_bookmark_stays_a_paragraph(self):
        for text, line in (("- not shown", r"\- not shown"), ("+ not shown", r"\+ not shown"),
                           ("1. Step one", r"1\. Step one"), ("1) Step one", r"1\) Step one")):
            with self.subTest(text=text):
                written_lines = self.word([para(BOOKMARK + run(" ") + run(text))])
                self.assertEqual(written_lines, [line])
                read = tree(None, "gfm", line)
                self.assertEqual([block["t"] for block in read["blocks"]], ["Para"])

    def test_a_space_inside_a_paragraph_stays(self):
        body = [para(run("One") + BOOKMARK + run(" ") + run("two", "<w:b/>"))]
        self.assertEqual(self.word(body), ["One **two**"])

    def test_a_picture_that_opens_an_item_leaves_its_placeholder_before_the_text(self):
        source = self.work / "in.md"
        source.write_text("- ![pin](pin.png) icon is shown\n- second\n", encoding="utf-8")
        self.assertEqual(written(source, "markdown").splitlines(),
                         [r"- \[picture: pin\] icon is shown", "- second"])


@unittest.skipUnless(shutil.which("pandoc"), "pandoc is not installed")
class PicturePlaceholderTest(WordCase):
    """A picture leaves plain text where it was, so the text says a picture was there."""

    def pictured(self, body, definitions=None) -> list[str]:
        return self.word(body, definitions, build=pictured_docx)

    def text_of(self, body, definitions=None) -> str:
        return written(self.numbered(body, definitions, build=pictured_docx), "docx")

    def assert_plain_text(self, text):
        """The written Markdown reads back with no picture and no link in it."""
        read = tree(None, "gfm", text)
        self.assertEqual(nodes(read, "Image"), 0, text)
        self.assertEqual(nodes(read, "Link"), 0, text)

    def test_a_picture_between_quote_marks_leaves_a_placeholder_between_them(self):
        body = [para(run("Click the \u2018") + picture(name="Image3") + run("\u2019 icon."))]
        text = self.text_of(body)
        self.assertEqual([line for line in text.splitlines() if line.strip()],
                         ["Click the \u2018\\[picture\\]\u2019 icon."])
        self.assert_plain_text(text)
        words = [node["c"] for node in tree(None, "gfm", text)["blocks"][0]["c"]
                 if node["t"] == "Str"]
        self.assertIn("\u2018[picture]\u2019", words)

    def test_a_picture_alone_in_its_paragraph_leaves_a_placeholder_line(self):
        body = [para(run("Screen Print (if applicable):")), para(picture()),
                para(run("Next section"))]
        text = self.text_of(body)
        self.assertEqual([line for line in text.splitlines() if line.strip()],
                         ["Screen Print (if applicable):", r"\[Picture\]", "Next section"])
        self.assert_plain_text(text)

    def test_alt_text_follows_the_placeholder(self):
        body = [para(run("the \u2018") + picture(descr="Pin icon") + run("\u2019 icon")),
                para(picture(descr="Agency  Access\nwindow"))]
        self.assertEqual(self.pictured(body), [
            "the \u2018\\[picture: Pin icon\\]\u2019 icon", r"\[Picture: Agency Access window\]",
        ])

    def test_alt_text_word_writes_for_itself_is_left_out(self):
        for descr in ("A screenshot of a computer&#xA;&#xA;Description automatically generated",
                      "A screenshot of a computer&#xA;&#xA;AI-generated content may be incorrect."):
            with self.subTest(descr=descr):
                body = [para(run("the \u2018") + picture(descr=descr) + run("\u2019 icon")),
                        para(picture(descr=descr))]
                self.assertEqual(self.pictured(body),
                                 ["the \u2018\\[picture\\]\u2019 icon", r"\[Picture\]"])

    def test_alt_text_that_only_mentions_generating_is_kept(self):
        body = [para(picture(descr="Report automatically generated nightly"))]
        self.assertEqual(self.pictured(body),
                         [r"\[Picture: Report automatically generated nightly\]"])

    def test_a_floating_picture_reads_like_an_inline_one(self):
        body = [para(run("the \u2018") + picture(descr="Pin", floating=True) + run("\u2019 icon")),
                para(picture(descr="Pin", floating=True))]
        self.assertEqual(self.pictured(body),
                         ["the \u2018\\[picture: Pin\\]\u2019 icon", r"\[Picture: Pin\]"])

    def test_an_older_vml_picture_leaves_a_placeholder(self):
        body = [para(run("the \u2018") + vml_picture() + run("\u2019 icon")), para(vml_picture())]
        self.assertEqual(self.pictured(body),
                         ["the \u2018\\[picture\\]\u2019 icon", r"\[Picture\]"])

    def test_a_heading_with_a_picture_takes_the_inline_placeholder(self):
        heading = WORD.para("Title", style="Heading1")
        body = [heading.replace("</w:r></w:p>", "</w:r>" + run(" ") + picture() + "</w:p>")]
        self.assertEqual(self.pictured(body), [r"# Title \[picture\]"])

    def test_a_picture_name_or_title_is_not_alt_text(self):
        body = [para(run("the \u2018") + picture(name="Picture 3", title="Lock")
                     + run("\u2019 icon"))]
        self.assertEqual(self.pictured(body), ["the \u2018\\[picture\\]\u2019 icon"])

    def test_two_pictures_alone_in_a_paragraph_leave_one_placeholder_each(self):
        body = [para(picture() + run(" ") + picture())]
        self.assertEqual(self.pictured(body), [r"\[Picture\] \[Picture\]"])

    def test_a_linked_picture_leaves_plain_text_and_no_link(self):
        body = [para(run("Link: ") + linked(picture()) + run(" after")), para(linked(picture()))]
        text = self.text_of(body)
        self.assertEqual([line for line in text.splitlines() if line.strip()],
                         [r"Link: \[picture\] after", r"\[Picture\]"])
        self.assert_plain_text(text)

    def test_a_link_with_text_and_a_picture_stays_a_link(self):
        body = [para(linked(run("Open ") + picture()))]
        self.assertEqual(self.pictured(body), [r"[Open \[picture\]](https://example.com/)"])

    def test_pictures_in_table_cells_leave_placeholders(self):
        body = [table([cell(para(run("Icon"))), cell(para(run("Meaning")))],
                      [cell(para(picture())),
                       cell(para(run("Icon \u2018") + picture() + run("\u2019 shown")),
                            para(picture()))])]
        text = self.text_of(body)
        self.assertIn(
            "| \\[Picture\\] | Icon \u2018\\[picture\\]\u2019 shown; \\[Picture\\] |", text)
        self.assert_plain_text(text)

    def test_a_picture_under_a_lettered_item_stays_in_the_item(self):
        body = [para(run("Step"), 1, 0), para(run("sub"), 1, 1),
                WORD.para("x", left=1440).replace("<w:r><w:t>x</w:t></w:r>", picture()),
                para(run("sub2"), 1, 1), para(run("Step 2"), 1, 0)]
        text = self.text_of(body, rules(1))
        self.assertEqual([line for line in text.splitlines() if line.strip()], [
            "1.  Step", r"    - a\. sub", r"      \[Picture\]", r"    - b\. sub2", "2.  Step 2",
        ])
        self.assertEqual(code_blocks(tree(None, "gfm", text)), 0)

    def test_a_numbered_item_that_opens_with_a_picture_keeps_it_before_the_text(self):
        body = [para(picture() + run(" icon is shown"), 1, 0)]
        self.assertEqual(self.pictured(body, rules(1)), [r"1.  \[picture\] icon is shown"])

    def test_a_captioned_picture_leaves_the_placeholder_and_the_caption(self):
        caption = ('<w:p><w:pPr><w:pStyle w:val="Caption"/></w:pPr>'
                   + run("Figure 1: The screen") + "</w:p>")
        body = [para(picture(descr="Agency Access")), caption]
        self.assertEqual(self.pictured(body), [r"\[Picture\]", "Figure 1: The screen"])

    def test_a_figure_keeps_its_text_and_its_caption(self):
        source = self.work / "in.html"
        source.write_text("<figure><p>Body</p><img src='a.png'><figcaption>Cap</figcaption>"
                          "</figure>", encoding="utf-8")
        self.assertEqual([line for line in written(source, "html").splitlines() if line.strip()],
                         ["Body", r"\[Picture\]", "Cap"])

    def test_a_markdown_picture_alone_leaves_a_placeholder_line(self):
        source = self.work / "in.md"
        source.write_text("Above\n\n![](a.png)\n\nBelow\n", encoding="utf-8")
        lines = [line for line in written(source, "markdown").splitlines() if line.strip()]
        self.assertEqual(lines, ["Above", r"\[Picture\]", "Below"])

    @unittest.skipUnless(shutil.which("soffice"), "soffice is not installed")
    def test_a_picture_saved_as_doc_and_converted_back_leaves_a_placeholder(self):
        # A .doc reaches Pandoc through LibreOffice, which writes the picture back
        # as an inline drawing with no alt text.
        body = [para(run("the \u2018") + picture(descr="Pin icon") + run("\u2019 header")),
                para(picture())]
        source = self.work / "in.docx"
        pictured_docx(source, body)
        profile = self.work / "profile"
        subprocess.run(["soffice", f"-env:UserInstallation=file://{profile}", "--headless",
                        "--convert-to", "doc", "--outdir", str(self.work / "doc"), str(source)],
                       capture_output=True, check=True, timeout=180)
        subprocess.run(["soffice", f"-env:UserInstallation=file://{profile}", "--headless",
                        "--convert-to", "docx", "--outdir", str(self.work / "back"),
                        str(self.work / "doc" / "in.doc")],
                       capture_output=True, check=True, timeout=180)
        text = written(self.work / "back" / "in.docx", "docx")
        lines = [line for line in text.splitlines() if line.strip()]
        self.assertNotIn("\u2018\u2019", text)
        self.assertEqual(len(lines), 2, text)
        self.assertEqual(lines, ["the \u2018\\[picture\\]\u2019 header", r"\[Picture\]"])


@unittest.skipUnless(shutil.which("pandoc"), "pandoc is not installed")
class EmphasisStartTest(WordCase):
    """Where the mark goes when a run of bold italic text starts inside a word."""

    def test_emphasis_word_starts_one_letter_into_a_word_stays_there(self):
        body = [para(run("See P") + run("AGE 3 Display All", BOLD_ITALIC) + run(" for details."))]
        self.assertEqual(self.word(body), ["See P***AGE 3 Display All*** for details."])

    def test_one_emphasis_split_into_runs_inside_a_word_opens_at_the_word(self):
        body = [para(run("See ") + run("P", BOLD_ITALIC) + run("AGE 3 Display All", BOLD_ITALIC)
                     + run(" for details."))]
        self.assertEqual(self.word(body), ["See ***PAGE 3 Display All*** for details."])

    def test_runs_that_differ_only_in_size_inside_a_word_share_one_mark(self):
        body = [para(run("See ") + run("P", BOLD_ITALIC + '<w:sz w:val="22"/>')
                     + run("AGE 3", BOLD_ITALIC + '<w:sz w:val="24"/>') + run(" for details."))]
        self.assertEqual(self.word(body), ["See ***PAGE 3*** for details."])


@unittest.skipUnless(shutil.which("pandoc"), "pandoc is not installed")
class CodeBlockGuardTest(WordCase):
    """A reader of the converted text finds a code block only where the source has one."""

    def shapes(self):
        opening = BOOKMARK + run(" ") + run("The grid will:")
        sub_items = [para(run("hold a check box column"), 1, 1), para(run("allow sorting"), 1, 1)]
        for start in (1, 9, 10, 25, 99, 100, 114, 1000):
            yield f"rule {start}", [para(run("The grid will:"), 1, 0)] + sub_items, rules(start)
            yield f"rule {start}, space first", [para(opening, 1, 0)] + sub_items, rules(start)
            yield (f"rule {start}, two spaces first",
                   [para(BOOKMARK + run("  ") + run("The grid will:"), 1, 0)] + sub_items,
                   rules(start))
            yield (f"rule {start}, space in emphasis first",
                   [para(BOOKMARK + run(" (Later)", "<w:i/>") + run(" The grid will:"), 1, 0)]
                   + sub_items, rules(start))
            yield (f"rule {start}, sub-item with a space first",
                   [para(run("The grid will:"), 1, 0), para(opening, 1, 1),
                    para(run("allow sorting"), 1, 1)], rules(start))
            yield (f"rule {start}, paragraph under the sub-list",
                   [para(opening, 1, 0)] + sub_items
                   + [WORD.para("A note on the rule.", left=720),
                      para(run("The next rule"), 1, 0)], rules(start))

    def test_no_shape_of_rule_and_sub_list_reads_back_as_code(self):
        for name, body, definitions in self.shapes():
            with self.subTest(shape=name):
                target = self.numbered(body, definitions)
                text = written(target, "docx")
                self.assertEqual(code_blocks(tree(None, "gfm", text)),
                                 code_blocks(tree(target, "docx")), text)

    def test_code_in_the_source_is_still_code(self):
        source = self.work / "in.md"
        source.write_text("1.  Run this:\n\n    ``` text\n    start\n    ```\n\nAfter.\n",
                          encoding="utf-8")
        text = written(source, "markdown")
        self.assertEqual(code_blocks(tree(source, "markdown")), 1)
        self.assertEqual(code_blocks(tree(None, "gfm", text)), 1)


if __name__ == "__main__":
    unittest.main()
