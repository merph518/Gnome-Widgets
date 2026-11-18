#!/usr/bin/env python3
"""Cases for list-numbers.py: the numbers and nesting Pandoc draws after the rewrite."""
from __future__ import annotations

import importlib.util
import pathlib
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
SCRIPT = HERE / "list-numbers.py"
SPEC = importlib.util.spec_from_file_location("list_numbers", SCRIPT)
LIST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LIST)

NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = "{" + NS + "}"

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
    'relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
    'officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-'
    'officedocument.wordprocessingml.numbering+xml"/>'
    '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-'
    'officedocument.wordprocessingml.styles+xml"/>'
    "</Types>"
)
RELS = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/officeDocument" Target="word/document.xml"/></Relationships>'
)
DOCUMENT_RELS = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/numbering" Target="numbering.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/styles" Target="styles.xml"/></Relationships>'
)
STYLES = (
    f'<?xml version="1.0" encoding="UTF-8"?><w:styles xmlns:w="{NS}">'
    '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>'
    '<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/>'
    '<w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr></w:style>'
    "</w:styles>"
)


def level(ilvl, fmt="decimal", text=None, left=None, hanging=360, start=1, restart=None):
    """A list level. `start` None leaves the start out of the definition."""
    text = text or f"%{ilvl + 1}."
    indent = "" if left is None else (
        f'<w:pPr><w:ind w:left="{left}" w:hanging="{hanging}"/></w:pPr>')
    restart = "" if restart is None else f'<w:lvlRestart w:val="{restart}"/>'
    start = "" if start is None else f'<w:start w:val="{start}"/>'
    return (f'<w:lvl w:ilvl="{ilvl}">{start}<w:numFmt w:val="{fmt}"/>'
            f'{restart}<w:lvlText w:val="{text}"/>{indent}</w:lvl>')


def abstract(abstract_id, *levels):
    return f'<w:abstractNum w:abstractNumId="{abstract_id}">{"".join(levels)}</w:abstractNum>'


def num(num_id, abstract_id, overrides=()):
    body = "".join(
        f'<w:lvlOverride w:ilvl="{ilvl}"><w:startOverride w:val="{start}"/></w:lvlOverride>'
        for ilvl, start in overrides
    )
    return f'<w:num w:numId="{num_id}"><w:abstractNumId w:val="{abstract_id}"/>{body}</w:num>'


def para(text, num_id=None, ilvl=0, left=None, hanging=None, style=None):
    ppr = ""
    if style:
        ppr += f'<w:pStyle w:val="{style}"/>'
    if num_id is not None:
        ppr += f'<w:numPr><w:ilvl w:val="{ilvl}"/><w:numId w:val="{num_id}"/></w:numPr>'
    if left is not None:
        hang = "" if hanging is None else f' w:hanging="{hanging}"'
        ppr += f'<w:ind w:left="{left}"{hang}/>'
    ppr = f"<w:pPr>{ppr}</w:pPr>" if ppr else ""
    return f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"


def table(*paragraphs):
    return f'<w:tbl><w:tr><w:tc>{"".join(paragraphs)}</w:tc></w:tr></w:tbl>'


def docx(path, body, definitions=None):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("_rels/.rels", RELS)
        archive.writestr("word/_rels/document.xml.rels", DOCUMENT_RELS)
        archive.writestr("word/styles.xml", STYLES)
        archive.writestr(
            "word/document.xml",
            f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{NS}">'
            f'<w:body>{"".join(body)}</w:body></w:document>',
        )
        if definitions is not None:
            archive.writestr(
                "word/numbering.xml",
                f'<?xml version="1.0" encoding="UTF-8"?><w:numbering xmlns:w="{NS}">'
                f'{"".join(definitions)}</w:numbering>',
            )


def drawn(path):
    """What Pandoc's reader makes of each paragraph: (text, level, number), with
    level None for a paragraph continuing the item above and number None for one
    outside any list. Counts by instance and level as the reader does."""
    with zipfile.ZipFile(path) as archive:
        document = ET.fromstring(archive.read("word/document.xml"))
        numbering = ET.fromstring(archive.read("word/numbering.xml"))
    abstracts = {a.get(W + "abstractNumId"): a for a in numbering.findall(W + "abstractNum")}
    links = {n.get(W + "numId"): n.find(W + "abstractNumId").get(W + "val")
             for n in numbering.findall(W + "num")}
    counts, out = {}, []
    for paragraph in document.iter(W + "p"):
        text = "".join(t.text or "" for t in paragraph.iter(W + "t"))
        num_pr = paragraph.find(f"{W}pPr/{W}numPr")
        if num_pr is None:
            out.append((text, None, None))
            continue
        num_id = num_pr.find(W + "numId").get(W + "val")
        ilvl = int(num_pr.find(W + "ilvl").get(W + "val"))
        lvl = next((x for x in abstracts[links[num_id]].findall(W + "lvl")
                    if int(x.get(W + "ilvl")) == ilvl), None)
        if lvl is None:
            out.append((text, None, "continues"))
            continue
        start = int(lvl.find(W + "start").get(W + "val"))
        number = counts[(num_id, ilvl)] + 1 if (num_id, ilvl) in counts else start
        counts = {k: v for k, v in counts.items() if k[1] <= ilvl}
        counts[(num_id, ilvl)] = number
        out.append((text, ilvl, number))
    return out


class Rewriting(unittest.TestCase):
    def setUp(self):
        self.work = pathlib.Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.work)

    def rewrite(self, body, definitions):
        source, target = self.work / "in.docx", self.work / "out.docx"
        docx(source, body, definitions)
        self.assertEqual(LIST.main(["list-numbers.py", str(source), str(target)]), 0)
        return target

    def items(self, body, definitions):
        return [(t, lvl, n) for t, lvl, n in drawn(self.rewrite(body, definitions))
                if n is not None]


class RewriteTest(Rewriting):
    def test_instances_on_one_definition_share_a_count(self):
        definitions = [abstract(8, level(0)), num(13, 8, [(0, 1)]), num(8, 8)]
        body = [para("first", 13), para("second", 8), para("third", 8)]
        self.assertEqual(self.items(body, definitions),
                         [("first", 0, 1), ("second", 0, 2), ("third", 0, 3)])

    def test_start_override_applies_on_first_use_only(self):
        definitions = [abstract(1, level(0)), num(3, 1, [(0, 5)]), num(4, 1)]
        body = [para("a", 3), para("b", 3), para("c", 4)]
        self.assertEqual([n for _, _, n in self.items(body, definitions)], [5, 6, 7])

    def test_a_level_that_names_no_start_counts_from_zero(self):
        # FAR 1.0 Family Led Assessment Guide: Word draws each rating scale 0 to
        # 3, on a definition whose first level names no start.
        definitions = [abstract(1, level(0, text="%1", left=864, start=None)), num(1, 1)]
        body = [para("stable", 1), para("some difficulty", 1), para("at risk", 1)]
        self.assertEqual([n for _, _, n in self.items(body, definitions)], [0, 1, 2])

    def test_a_deeper_first_item_counts_the_level_above_once(self):
        definitions = [
            abstract(2, level(0, left=720)),
            abstract(1, level(0, left=720), level(1, left=1440), level(2, left=1800)),
            num(5, 2), num(23, 1),
        ]
        body = [para("rule a", 5), para("rule b", 5), para("grid one", 23, 2),
                para("grid two", 23, 2), para("rule c", 23, 0)]
        self.assertEqual(self.items(body, definitions), [
            ("rule a", 0, 1), ("rule b", 0, 2),
            ("grid one", 1, 1), ("grid two", 1, 2),
            ("rule c", 0, 2),
        ])

    def test_another_definition_indented_under_an_item_nests(self):
        definitions = [
            abstract(1, level(0, left=720)),
            abstract(2, level(0, fmt="lowerRoman", text="%1.", left=1620)),
            num(1, 1), num(2, 2),
        ]
        body = [para("one", 1), para("two", 1), para("sub i", 2), para("sub ii", 2),
                para("three", 1)]
        self.assertEqual(self.items(body, definitions), [
            ("one", 0, 1), ("two", 0, 2), ("sub i", 1, 1), ("sub ii", 1, 2), ("three", 0, 3),
        ])

    def test_another_definition_at_the_same_indent_is_a_sibling_list(self):
        definitions = [
            abstract(1, level(0, left=720)), abstract(2, level(0, left=720)),
            num(1, 1), num(2, 2),
        ]
        body = [para("one", 1), para("two", 1), para("other", 2)]
        self.assertEqual(self.items(body, definitions)[-1], ("other", 0, 1))

    def test_an_indented_paragraph_continues_the_item_above(self):
        definitions = [abstract(1, level(0, left=720)), num(1, 1)]
        body = [para("one", 1), para("more about one", left=720), para("two", 1)]
        self.assertEqual(drawn(self.rewrite(body, definitions)), [
            ("one", 0, 1), ("more about one", None, "continues"), ("two", 0, 2),
        ])

    def test_a_blank_paragraph_before_a_continuing_one_joins_the_item(self):
        definitions = [abstract(1, level(0, left=720)), num(1, 1)]
        body = [para("one", 1), para("", left=720), para(""), para("more about one", left=720),
                para("two", 1)]
        self.assertEqual(drawn(self.rewrite(body, definitions)), [
            ("one", 0, 1), ("", None, "continues"), ("", None, "continues"),
            ("more about one", None, "continues"), ("two", 0, 2),
        ])

    def test_a_blank_paragraph_joins_the_item_the_next_paragraph_continues(self):
        definitions = [
            abstract(1, level(0, left=720)), abstract(2, level(0, fmt="bullet", left=1440)),
            num(1, 1), num(2, 2),
        ]
        body = [para("rule", 1), para("bullet", 2), para("", left=1440),
                para("more about the rule", left=720)]
        target = self.rewrite(body, definitions)
        with zipfile.ZipFile(target) as archive:
            document = ET.fromstring(archive.read("word/document.xml"))
        levels = [p.find(f"{W}pPr/{W}numPr/{W}ilvl").get(W + "val")
                  for p in document.iter(W + "p")]
        self.assertEqual(levels, ["0", "1", "0", "1"])
        self.assertEqual(drawn(target)[2:], [
            ("", None, "continues"),
            ("more about the rule", 1, LIST.UNNUMBERED_START),
        ])

    def test_a_blank_paragraph_not_followed_by_a_continuing_one_stays_outside(self):
        definitions = [abstract(1, level(0, left=720)), num(1, 1)]
        body = [para("one", 1), para("", left=720), para("two", 1), para("", left=720),
                para("At the margin."), para("three", 1), para("", left=720),
                table(para("cell")), para("", left=720), para("after the table", left=720)]
        self.assertEqual(drawn(self.rewrite(body, definitions)), [
            ("one", 0, 1), ("", None, None), ("two", 0, 2), ("", None, None),
            ("At the margin.", None, None), ("three", 0, 3), ("", None, None),
            ("cell", None, None), ("", None, None), ("after the table", None, None),
        ])

    def test_a_paragraph_after_a_sub_list_continues_the_item_the_sub_list_is_under(self):
        body = [para("rule", 2, 0), para("first", 2, 1), para("second", 2, 1),
                para("Note: about the rule", left=720), para("next rule", 2, 0)]
        self.assertEqual(drawn(self.rewrite(body, self.BULLETS)), [
            ("rule", 0, 1), ("first", 1, 1), ("second", 1, 2),
            ("Note: about the rule", 1, LIST.UNNUMBERED_START), ("next rule", 0, 2),
        ])

    def test_a_paragraph_nearer_the_last_sub_items_text_continues_that_sub_item(self):
        # The rule's text starts at 720 and the sub-item's at 1440. Halfway
        # between, the paragraph stays where Pandoc joins it.
        for left in (1440, 1320, 1080):
            body = [para("rule", 2, 0), para("first", 2, 1), para("second", 2, 1),
                    para("more about second", left=left), para("next rule", 2, 0)]
            self.assertEqual(drawn(self.rewrite(body, self.BULLETS))[3],
                             ("more about second", None, "continues"), left)

    def test_a_first_line_indent_to_the_sub_items_text_continues_that_sub_item(self):
        indented = ('<w:p><w:pPr><w:ind w:left="720" w:firstLine="720"/></w:pPr>'
                    "<w:r><w:t>more about second</w:t></w:r></w:p>")
        body = [para("rule", 2, 0), para("first", 2, 1), para("second", 2, 1), indented]
        self.assertEqual(drawn(self.rewrite(body, self.BULLETS))[3],
                         ("more about second", None, "continues"))

    def test_a_hanging_paragraph_after_a_sub_list_goes_where_its_first_line_starts(self):
        # The first line starts at the rule's text and the rest at the
        # sub-item's. A tab ahead of the first words carries them to the rest.
        body = [para("rule", 2, 0), para("first", 2, 1), para("second", 2, 1),
                para("Note: about the rule", left=1440, hanging=720)]
        self.assertEqual(drawn(self.rewrite(body, self.BULLETS))[3],
                         ("Note: about the rule", 1, LIST.UNNUMBERED_START))
        tabbed = ('<w:p><w:pPr><w:ind w:left="1440" w:hanging="720"/></w:pPr>'
                  "<w:r><w:tab/><w:t>more about second</w:t></w:r></w:p>")
        body = [para("rule", 2, 0), para("first", 2, 1), para("second", 2, 1), tabbed]
        self.assertEqual(drawn(self.rewrite(body, self.BULLETS))[3],
                         ("more about second", None, "continues"))

    def test_a_tab_carries_a_paragraph_after_a_sub_list_to_the_next_tab_stop(self):
        # The paragraph is indented to the rule's text. A tab ahead of its
        # first words carries them to the stop it sets, or to Word's default
        # stop, and both sit nearer the sub-item's text than the rule's.
        for stops in ('<w:tabs><w:tab w:val="clear" w:pos="720"/>'
                      '<w:tab w:val="left" w:pos="1335"/></w:tabs>', ""):
            tabbed = (f'<w:p><w:pPr>{stops}<w:ind w:left="720"/></w:pPr>'
                      "<w:r><w:tab/><w:t>more about second</w:t></w:r></w:p>")
            body = [para("rule", 2, 0), para("first", 2, 1), para("second", 2, 1), tabbed]
            self.assertEqual(drawn(self.rewrite(body, self.BULLETS))[3],
                             ("more about second", None, "continues"), stops)

    def test_an_items_text_starts_at_a_tab_stop_short_of_its_hanging_indent(self):
        # The sub-item hangs far to the right, and a tab stop it sets right
        # after its letter is where Word starts its text. A paragraph at that
        # stop continues the sub-item. Without the stop it lines up with the
        # rule.
        definitions = [
            abstract(1, level(0, left=720)), abstract(2, level(0, fmt="lowerLetter", left=4215)),
            num(1, 1), num(2, 2),
        ]
        for stops, expected in (
                ('<w:tabs><w:tab w:val="left" w:pos="1335"/></w:tabs>',
                 ("more about the sub-item", None, "continues")),
                ("", ("more about the sub-item", 1, LIST.UNNUMBERED_START))):
            item = (f'<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="2"/></w:numPr>'
                    f'{stops}<w:ind w:left="4215" w:hanging="3135"/></w:pPr>'
                    "<w:r><w:t>sub-item</w:t></w:r></w:p>")
            body = [para("rule", 1), item, para("more about the sub-item", left=1335)]
            self.assertEqual(drawn(self.rewrite(body, definitions))[2], expected, stops)

    def test_a_paragraph_back_at_the_rule_follows_one_left_with_the_sub_item(self):
        body = [para("rule", 2, 0), para("first", 2, 1), para("more about first", left=1320),
                para("Note: about the rule", left=720)]
        self.assertEqual(drawn(self.rewrite(body, self.BULLETS))[2:], [
            ("more about first", None, "continues"),
            ("Note: about the rule", 1, LIST.UNNUMBERED_START),
        ])

    def test_a_second_paragraph_after_a_sub_list_continues_the_first(self):
        body = [para("rule", 2, 0), para("first", 2, 1),
                para("Note: about the rule", left=720), para("more of the note", left=720)]
        self.assertEqual(drawn(self.rewrite(body, self.BULLETS))[2:], [
            ("Note: about the rule", 1, LIST.UNNUMBERED_START),
            ("more of the note", None, "continues"),
        ])

    def test_a_paragraph_after_sub_lists_two_deep_sits_under_the_item_it_starts_nearest(self):
        # The texts start at 720, 1440 and 2160. A paragraph halfway between
        # two of them goes with the deeper one.
        definitions = [
            abstract(1, level(0, left=720), level(1, left=1440), level(2, left=2160)),
            num(1, 1),
        ]
        nested = [para("rule", 1, 0), para("sub", 1, 1), para("deeper", 1, 2)]
        for left, level_of_its_list in ((720, 1), (1000, 1), (1080, 2), (1440, 2), (1700, 2)):
            out = self.rewrite(nested + [para("after", left=left)], definitions)
            self.assertEqual(drawn(out)[-1], ("after", level_of_its_list, LIST.UNNUMBERED_START),
                             left)
        out = self.rewrite(nested + [para("after", left=1800)], definitions)
        self.assertEqual(drawn(out)[-1], ("after", None, "continues"))

    def test_a_sub_list_keeps_its_count_across_a_paragraph_of_the_item_above(self):
        definitions = [abstract(1, level(0, left=720), level(1, left=1440)), num(1, 1)]
        body = [para("rule", 1, 0), para("sub one", 1, 1), para("sub two", 1, 1),
                para("Note: about the rule", left=720), para("sub three", 1, 1)]
        out = self.rewrite(body, definitions)
        self.assertEqual(drawn(out)[-1], ("sub three", 1, 3))
        with zipfile.ZipFile(out) as archive:
            document = ET.fromstring(archive.read("word/document.xml"))
        ids = [n.get(W + "val") for n in document.iter(W + "numId")]
        self.assertEqual(ids[4], ids[2])
        self.assertNotEqual(ids[3], ids[2])

    def test_text_at_the_margin_ends_the_nesting(self):
        definitions = [
            abstract(1, level(0, left=720)), abstract(2, level(0, left=1440)),
            num(1, 1), num(2, 2),
        ]
        body = [para("one", 1), para("A paragraph at the margin."), para("indented", 2)]
        self.assertEqual(drawn(self.rewrite(body, definitions))[1:], [
            ("A paragraph at the margin.", None, None), ("indented", 0, 1),
        ])

    def test_level_restart_zero_keeps_counting_across_shallower_items(self):
        definitions = [
            abstract(1, level(0, left=720), level(1, left=1440, restart=0)), num(1, 1),
        ]
        body = [para("top", 1, 0), para("x", 1, 1), para("y", 1, 1), para("next", 1, 0),
                para("z", 1, 1)]
        self.assertEqual(self.items(body, definitions)[-1], ("z", 1, 3))

    def test_text_after_an_unindented_list_stays_at_the_margin(self):
        definitions = [abstract(1, level(0)), num(1, 1)]
        body = [para("step one", 1), para("step two", 1), para("Body text.", left=0),
                para("More body text.", style="Normal")]
        self.assertEqual(drawn(self.rewrite(body, definitions))[2:], [
            ("Body text.", None, None), ("More body text.", None, None),
        ])

    def test_a_hanging_paragraph_that_starts_at_the_numbers_ends_the_item(self):
        # PLC 4.0 Resource Characteristics: a title between two lists hangs back
        # to the column their numbers sit in, so Word draws it level with them.
        definitions = [abstract(1, level(0, left=360)), abstract(2, level(0, left=360)),
                       num(1, 1), num(2, 2)]
        body = [para("one", 1), para("two", 1), para("Business Rules", left=360, hanging=360),
                para("first", 2)]
        self.assertEqual(drawn(self.rewrite(body, definitions))[2:], [
            ("Business Rules", None, None), ("first", 0, 1),
        ])

    def test_a_tab_carries_a_hanging_paragraph_into_the_item(self):
        tabbed = ('<w:p><w:pPr><w:ind w:left="720" w:hanging="720"/></w:pPr>'
                  "<w:r><w:tab/><w:t>more about one</w:t></w:r></w:p>")
        definitions = [abstract(1, level(0, left=720)), num(1, 1)]
        body = [para("one", 1), tabbed, para("two", 1)]
        self.assertEqual(drawn(self.rewrite(body, definitions)), [
            ("one", 0, 1), ("more about one", None, "continues"), ("two", 0, 2),
        ])

    def test_spaces_carry_a_hanging_paragraph_toward_the_item(self):
        # The first line hangs back to the numbers. Five spaces typed ahead of
        # its words bring them within reach of the item's text, one does not.
        definitions = [abstract(1, level(0, left=720)), num(1, 1)]
        for spaces, mark in ((5, "continues"), (1, None)):
            text = " " * spaces + "more about one"
            body = [para("one", 1), para(text, left=648, hanging=288), para("two", 1)]
            self.assertEqual(drawn(self.rewrite(body, definitions)), [
                ("one", 0, 1), (text, None, mark), ("two", 0, 2),
            ], spaces)

    # Numbering that names no list is how a paragraph is taken out of one.
    UNLISTED = ('<w:p><w:pPr><w:numPr><w:numId w:val="0"/></w:numPr>{indent}</w:pPr>'
                "<w:r><w:t>{text}</w:t></w:r></w:p>")

    def test_a_paragraph_taken_out_of_every_list_at_the_margin_ends_the_item(self):
        definitions = [abstract(1, level(0, left=720)), num(1, 1)]
        body = [para("one", 1), self.UNLISTED.format(indent="", text="at the margin"),
                para("two", 1)]
        self.assertEqual(drawn(self.rewrite(body, definitions)), [
            ("one", 0, 1), ("at the margin", None, None), ("two", 0, 2),
        ])

    def test_a_paragraph_taken_out_of_every_list_under_an_item_continues_it(self):
        definitions = [abstract(1, level(0, left=720)), num(1, 1)]
        body = [para("one", 1),
                self.UNLISTED.format(indent='<w:ind w:left="720"/>', text="more about one"),
                para("two", 1)]
        self.assertEqual(drawn(self.rewrite(body, definitions)), [
            ("one", 0, 1), ("more about one", None, "continues"), ("two", 0, 2),
        ])

    def test_a_paragraph_taken_out_of_every_list_away_from_an_item_is_left_alone(self):
        definitions = [abstract(1, level(0, left=720)), num(1, 1)]
        body = [para("Body text."),
                self.UNLISTED.format(indent='<w:ind w:left="720"/>', text="indented"),
                para("one", 1)]
        with zipfile.ZipFile(self.rewrite(body, definitions)) as archive:
            document = ET.fromstring(archive.read("word/document.xml"))
        ids = [p.find(f"{W}pPr/{W}numPr/{W}numId") for p in document.iter(W + "p")]
        self.assertEqual([None if i is None else i.get(W + "val") for i in ids[:2]], [None, "0"])

    def test_a_heading_ends_the_list(self):
        definitions = [abstract(1, level(0, left=720)), num(1, 1)]
        body = [para("one", 1), para("Next part", style="Heading1"),
                para("indented after the heading", left=720)]
        self.assertEqual(drawn(self.rewrite(body, definitions))[1:], [
            ("Next part", None, None), ("indented after the heading", None, None),
        ])

    # FCI 1.1.2.1 Edit Placement Information: Word draws the sixth bullet of a
    # rule's sub-list in a heading style, and its own numbering keeps it a bullet.
    BULLETS = [
        abstract(1, level(0, left=720),
                 level(1, fmt="bullet", text="\u2022", left=1440)), num(2, 1),
    ]

    def test_a_heading_its_numbering_puts_in_a_list_is_an_item(self):
        body = [para("rule", 2, 0), para("first", 2, 1), para("second", 2, 1),
                para("third", 2, 1, style="Heading1"), para("next rule", 2, 0)]
        out = self.rewrite(body, self.BULLETS)
        self.assertEqual(drawn(out), [
            ("rule", 0, 1), ("first", 1, 1), ("second", 1, 2), ("third", 1, 3),
            ("next rule", 0, 2),
        ])
        with zipfile.ZipFile(out) as archive:
            document = ET.fromstring(archive.read("word/document.xml"))
        self.assertEqual(list(document.iter(W + "pStyle")), [])

    def test_headings_in_a_row_in_a_list_are_items(self):
        body = [para("one", 2, 0, style="Heading1"), para("two", 2, 0),
                para("three", 2, 0, style="Heading1"), para(""),
                para("four", 2, 0, style="Heading1")]
        self.assertEqual(self.items(body, self.BULLETS), [
            ("one", 0, 1), ("two", 0, 2), ("three", 0, 3), ("four", 0, 4),
        ])

    def test_a_numbered_heading_over_its_own_sub_items_stays_a_heading(self):
        body = [para("Navigation", 2, 0, style="Heading1"), para("from the tree", 2, 1),
                para("from the detail", 2, 1), para("Combining", 2, 0, style="Heading1")]
        out = self.rewrite(body, self.BULLETS)
        with zipfile.ZipFile(out) as archive:
            document = ET.fromstring(archive.read("word/document.xml"))
        self.assertEqual([s.get(W + "val") for s in document.iter(W + "pStyle")],
                         ["Heading1", "Heading1"])

    def test_headings_of_a_list_that_numbers_sections_stay_headings(self):
        # PLC 1.3 Placement Evaluation: Word numbers its section headings on the
        # list that numbers the rules before them, so the rules end at 3 and the
        # next section heading is 4.
        body = [para("rule one", 2, 0), para("rule two", 2, 0),
                para("Database Requirements", 2, 0, style="Heading1"), table(para("cell")),
                para("Testing Conditions", 2, 0, style="Heading1")]
        out = self.rewrite(body, self.BULLETS)
        with zipfile.ZipFile(out) as archive:
            document = ET.fromstring(archive.read("word/document.xml"))
        self.assertEqual([s.get(W + "val") for s in document.iter(W + "pStyle")],
                         ["Heading1", "Heading1"])

    def test_a_heading_its_style_numbers_stays_a_heading(self):
        definitions = [abstract(1, level(0, left=720)), num(1, 1), num(3, 1)]
        body = [para("Section", 3, style="Heading2"), para("item", 1)]
        out = self.rewrite(body, definitions)
        with zipfile.ZipFile(out) as archive:
            document = ET.fromstring(archive.read("word/document.xml"))
        self.assertEqual([s.get(W + "val") for s in document.iter(W + "pStyle")], ["Heading2"])

    def test_tables_and_headings_are_left_as_they_are(self):
        definitions = [abstract(1, level(0, left=720)), num(1, 1)]
        body = [para("Heading", 1, style="Heading1"), table(para("cell", 1)), para("after", 1)]
        out = self.rewrite(body, definitions)
        with zipfile.ZipFile(out) as archive:
            document = ET.fromstring(archive.read("word/document.xml"))
        ids = [p.find(f"{W}pPr/{W}numPr/{W}numId").get(W + "val") for p in document.iter(W + "p")]
        self.assertEqual(ids[:2], ["1", "1"])
        self.assertEqual(drawn(out)[-1], ("after", 0, 3))

    def test_a_file_without_numbering_is_copied(self):
        source, target = self.work / "in.docx", self.work / "out.docx"
        docx(source, [para("plain")])
        self.assertEqual(LIST.main(["list-numbers.py", str(source), str(target)]), 0)
        self.assertEqual(source.read_bytes(), target.read_bytes())

    def test_a_file_that_is_not_a_zip_fails(self):
        source = self.work / "in.rtf"
        source.write_text("{\\rtf1 plain}")
        self.assertEqual(LIST.main(["list-numbers.py", str(source), str(self.work / "o")]), 1)


@unittest.skipUnless(shutil.which("pandoc"), "pandoc is not installed")
class PandocTest(Rewriting):
    def markdown(self, body, definitions):
        """What Pandoc writes with the filter that reads the rewrite's marks."""
        target = self.rewrite(body, definitions)
        return subprocess.run(["pandoc", "-f", "docx", "-t", "gfm",
                               f"--lua-filter={HERE / 'list-markers.lua'}", str(target)],
                              capture_output=True, text=True, check=True).stdout

    def test_pandoc_draws_the_word_numbers(self):
        definitions = [
            abstract(2, level(0, left=720)),
            abstract(1, level(0, left=720), level(1, left=1440), level(2, left=1800)),
            abstract(8, level(0, fmt="lowerRoman", text="%1.", left=1620)),
            num(5, 2), num(23, 1), num(13, 8),
        ]
        body = [para("rule a", 5), para("rule b", 5), para("grid i", 13), para("grid ii", 13),
                para("more", left=720), para("sub", 23, 2), para("rule c", 23, 0)]
        lines = [line for line in self.markdown(body, definitions).splitlines()
                 if line.strip() not in ("", "&nbsp;", "<!-- -->")]
        # The paragraph after the roman list lines up with rule b's text, so it
        # is drawn under rule b, between the two sub-lists.
        self.assertEqual(lines, [
            "1.  rule a", "2.  rule b", r"    - i\. grid i", r"    - ii\. grid ii",
            "    more", "    1.  sub", "2.  rule c",
        ])

    def test_an_indented_paragraph_after_a_blank_one_stays_in_its_item(self):
        definitions = [abstract(1, level(0, left=720)), num(1, 1)]
        # LibreOffice leaves an empty formatted run in a blank paragraph, and
        # Pandoc keeps a paragraph that holds one.
        run = '<w:r><w:rPr><w:highlight w:val="yellow"/></w:rPr></w:r>'
        indented = f'<w:p><w:pPr><w:ind w:left="720"/></w:pPr>{run}</w:p>'
        page_break = f'<w:p>{run}<w:r><w:br w:type="page"/></w:r></w:p>'
        body = [para("one", 1), indented, para("more about one", left=720), para("two", 1),
                page_break, para("more about two", left=1080), para("three", 1)]
        lines = [line for line in self.markdown(body, definitions).splitlines()
                 if line.strip() not in ("", '<span class="mark"></span>')]
        self.assertEqual(lines, [
            "1.  one", "    more about one", "2.  two", "    more about two", "3.  three",
        ])

    def test_a_paragraph_after_a_sub_list_and_a_blank_one_is_drawn_under_the_rule(self):
        definitions = [
            abstract(1, level(0, left=720)), abstract(2, level(0, fmt="bullet", left=1440)),
            num(1, 1), num(2, 2),
        ]
        run = '<w:r><w:rPr><w:highlight w:val="yellow"/></w:rPr></w:r>'
        blank = f'<w:p><w:pPr><w:ind w:left="1440"/></w:pPr>{run}</w:p>'
        body = [para("rule", 1), para("bullet", 2), blank, para("more about the rule", left=720),
                para("next rule", 1)]
        lines = [line for line in self.markdown(body, definitions).splitlines()
                 if line.strip() not in ("", '<span class="mark"></span>')]
        # The blank paragraph keeps the list open, and the paragraph after it
        # lines up with the rule's text, so it is drawn under the rule.
        self.assertEqual(lines, [
            "1.  rule", "    - bullet", "    more about the rule", "2.  next rule",
        ])

    def test_a_heading_inside_a_bullet_list_is_drawn_as_a_bullet(self):
        body = [para("rule", 2, 0), para("first", 2, 1),
                para("second", 2, 1, style="Heading1"), para("next rule", 2, 0)]
        lines = [line for line in self.markdown(body, RewriteTest.BULLETS).splitlines()
                 if line.strip() not in ("", "<!-- -->")]
        self.assertEqual(lines, [
            "1.  rule", "    - first", "    - second", "2.  next rule",
        ])

    def test_pandoc_draws_a_list_from_zero(self):
        definitions = [abstract(1, level(0, text="%1", left=864, start=None)), num(1, 1)]
        body = [para("stable", 1), para("some difficulty", 1)]
        lines = [line for line in self.markdown(body, definitions).splitlines() if line.strip()]
        self.assertEqual(lines, ["0.  stable", "1.  some difficulty"])

    def test_pandoc_draws_a_paragraph_taken_out_of_every_list_at_the_margin(self):
        definitions = [abstract(1, level(0, left=720)), num(1, 1)]
        body = [para("one", 1),
                RewriteTest.UNLISTED.format(indent="", text="at the margin"), para("two", 1)]
        lines = [line for line in self.markdown(body, definitions).splitlines() if line.strip()]
        self.assertEqual(lines, ["1.  one", "at the margin", "2.  two"])


if __name__ == "__main__":
    unittest.main()
