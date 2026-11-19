#!/usr/bin/env python3
"""Cases for picture-text.py: reading the text records of EMF and WMF pictures,
laying them out as rows and columns, and putting them into a Word file where the
picture was, so Pandoc and the filters write them as a table."""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile

HERE = pathlib.Path(__file__).resolve().parent


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PT = load("picture_text", "picture-text.py")
IMAGES = load("drop_images_test", "drop-images_test.py")
WORD = IMAGES.WORD
PAGES = load("pages", "pages.py")

ETO_CLIPPED = 0x0004
ETO_GLYPH_INDEX = 0x0010


# EMF records.

def record(kind, payload=b""):
    return struct.pack("<II", kind, 8 + len(payload)) + payload


def emf_header():
    body = bytearray(100)
    body[32:36] = b" EMF"
    return record(PT.EMR_HEADER, bytes(body))


def font(handle, height):
    return record(PT.EMR_EXTCREATEFONTINDIRECTW, struct.pack("<Ii", handle, height) + bytes(92))


def select(handle):
    return record(PT.EMR_SELECTOBJECT, struct.pack("<I", handle))


def align(mode):
    return record(PT.EMR_SETTEXTALIGN, struct.pack("<I", mode))


def text_w(x, y, string, advance=10, options=ETO_CLIPPED, wide=True, raw=None):
    """An EMR_EXTTEXTOUTW (or A), each character `advance` wide."""
    encoded = raw if raw is not None else string.encode("utf-16-le" if wide else "cp1252")
    count = len(string)
    fixed = 76  # through offDx, record header included
    offset = fixed
    padded = encoded + bytes(-len(encoded) % 4)
    dx_offset = offset + len(padded)
    payload = (bytes(16) + struct.pack("<Iff", 1, 1.0, 1.0)
               + struct.pack("<iiIII", x, y, count, offset, options)
               + bytes(16) + struct.pack("<I", dx_offset)
               + padded + struct.pack(f"<{count}i", *([advance] * count)))
    return record(PT.EMR_EXTTEXTOUTW if wide else PT.EMR_EXTTEXTOUTA, payload)


def small_text(x, y, string):
    encoded = string.encode("utf-16-le")
    payload = struct.pack("<iiIIIff", x, y, len(string), 0x0100, 1, 1.0, 1.0) + encoded
    payload += bytes(-len(payload) % 4)
    return record(PT.EMR_SMALLTEXTOUT, payload)


def emf_plus(*kinds):
    """An EMR_COMMENT holding one EMF+ record of each type given, each with no data."""
    records = b"".join(struct.pack("<HHII", kind, 0, 12, 0) for kind in kinds)
    return record(PT.EMR_COMMENT, struct.pack("<I", 4 + len(records)) + b"EMF+" + records)


def emf(*records):
    return emf_header() + b"".join(records) + record(PT.EMR_EOF, bytes(12))


def grid_emf(rows, top=0, row_height=20, column_width=100, height=12):
    """Cells as text records, one per filled cell, row by row; an empty cell
    draws nothing."""
    out = []
    for r, cells in enumerate(rows):
        for c, cell in enumerate(cells):
            if cell:
                out.append(text_w(c * column_width, top + r * row_height, cell, advance=6))
    return out


# WMF records.

def wmf_record(function, params):
    params += bytes(len(params) % 2)
    return struct.pack("<IH", (6 + len(params)) // 2, function) + params


def wmf(*records, placeable=True):
    head = struct.pack("<HHHIHIH", 1, 9, 0x0300, 0, 0, 0, 0)
    out = head + b"".join(records) + struct.pack("<IH", 3, 0)
    if placeable:
        out = struct.pack("<I", PT.WMF_PLACEABLE) + bytes(18) + out
    return out


def wmf_textout(x, y, string):
    raw = string.encode("cp1252")
    return wmf_record(PT.META_TEXTOUT,
                      struct.pack("<h", len(raw)) + raw + bytes(len(raw) % 2)
                      + struct.pack("<hh", y, x))


def wmf_exttextout(x, y, string, rect=False):
    raw = string.encode("cp1252")
    options = ETO_CLIPPED if rect else 0
    params = struct.pack("<hhhH", y, x, len(raw), options) + (bytes(8) if rect else b"")
    params += raw + bytes(len(raw) % 2) + struct.pack(f"<{len(raw)}h", *([7] * len(raw)))
    return wmf_record(PT.META_EXTTEXTOUT, params)


class ReadEmf(unittest.TestCase):
    def test_wide_text_with_its_point_and_width(self):
        reading = PT.emf_text(emf(text_w(5, 40, "Field", advance=8)))
        self.assertEqual([(t.string, t.x, t.y, t.left, t.right) for t in reading.texts],
                         [("Field", 5, 40, 5, 45)])
        self.assertFalse(reading.unread)

    def test_odd_length_and_non_ascii(self):
        reading = PT.emf_text(emf(text_w(0, 0, "Café")))
        self.assertEqual([t.string for t in reading.texts], ["Café"])

    def test_ansi_text_is_windows_1252(self):
        reading = PT.emf_text(emf(text_w(0, 0, "naïve", wide=False)))
        self.assertEqual([t.string for t in reading.texts], ["naïve"])

    def test_small_text_out(self):
        reading = PT.emf_text(emf(small_text(3, 4, "ID")))
        self.assertEqual([(t.string, t.x, t.y) for t in reading.texts], [("ID", 3, 4)])

    def test_right_alignment_ends_at_the_point(self):
        reading = PT.emf_text(emf(align(PT.TA_RIGHT), text_w(100, 0, "42", advance=5)))
        self.assertEqual((reading.texts[0].left, reading.texts[0].right), (90, 100))

    def test_font_height_follows_the_selected_font(self):
        reading = PT.emf_text(emf(font(1, -14), select(1), text_w(0, 0, "A")))
        self.assertEqual(reading.texts[0].height, 14)

    def test_glyph_indexes_are_unread(self):
        reading = PT.emf_text(emf(text_w(0, 0, "AB", options=ETO_GLYPH_INDEX)))
        self.assertEqual(reading.texts, [])
        self.assertTrue(reading.unread)

    def test_text_drawn_only_as_emf_plus_is_unread(self):
        for kind in (PT.EMF_PLUS_DRAW_STRING, PT.EMF_PLUS_DRAW_DRIVER_STRING):
            with self.subTest(kind=hex(kind)):
                reading = PT.emf_text(emf(emf_plus(0x4008, kind)))
                self.assertEqual(reading.texts, [])
                self.assertTrue(reading.unread)

    def test_emf_plus_text_beside_text_records_that_were_read_is_not_unread(self):
        for kind in (PT.EMF_PLUS_DRAW_STRING, PT.EMF_PLUS_DRAW_DRIVER_STRING):
            with self.subTest(kind=hex(kind)):
                reading = PT.emf_text(emf(emf_plus(kind), text_w(0, 0, "Hello")))
                self.assertEqual([t.string for t in reading.texts], ["Hello"])
                self.assertFalse(reading.unread)

    def test_emf_plus_text_beside_only_blank_text_records_is_unread(self):
        reading = PT.emf_text(emf(emf_plus(PT.EMF_PLUS_DRAW_STRING), text_w(0, 0, "  ")))
        self.assertEqual(reading.texts, [])
        self.assertTrue(reading.unread)

    def test_emf_plus_records_that_draw_no_text_are_not_unread(self):
        reading = PT.emf_text(emf(emf_plus(0x4008, 0x4015)))
        self.assertFalse(reading.unread)

    def test_a_comment_that_is_not_emf_plus_is_ignored(self):
        reading = PT.emf_text(emf(record(PT.EMR_COMMENT, struct.pack("<I", 16) + b"GDIC"
                                         + struct.pack("<HHII", PT.EMF_PLUS_DRAW_STRING,
                                                       0, 12, 0))))
        self.assertFalse(reading.unread)

    def test_a_comment_too_short_to_name_emf_plus_is_ignored(self):
        reading = PT.emf_text(emf(record(PT.EMR_COMMENT, struct.pack("<I", 4))))
        self.assertFalse(reading.unread)

    def test_glyph_indexes_beside_text_that_was_read_stay_unread(self):
        reading = PT.emf_text(emf(text_w(0, 0, "Kept"),
                                  text_w(0, 20, "AB", options=ETO_GLYPH_INDEX)))
        self.assertEqual([t.string for t in reading.texts], ["Kept"])
        self.assertTrue(reading.unread)

    def test_blank_strings_are_dropped(self):
        self.assertEqual(PT.emf_text(emf(text_w(0, 0, "   "))).texts, [])

    def test_a_flipped_axis_turns_the_lines_round(self):
        flipped = emf(record(PT.EMR_SETWINDOWEXTEX, struct.pack("<ii", 100, -100)),
                      text_w(0, 10, "low"), text_w(0, 50, "high"))
        lines = PT.lines_of(PT.emf_text(flipped).texts)
        self.assertEqual([PT.line_text(line) for line in lines], ["high", "low"])

    def test_corrupt_records_end_the_reading(self):
        good = text_w(0, 0, "kept")
        for tail in (struct.pack("<II", 84, 0), struct.pack("<II", 84, 4000),
                     struct.pack("<II", 84, 12) + bytes(4)):
            with self.subTest(tail=tail):
                reading = PT.emf_text(emf_header() + good + tail)
                self.assertEqual([t.string for t in reading.texts], ["kept"])

    def test_string_offset_past_the_record_is_skipped(self):
        broken = bytearray(text_w(0, 0, "gone"))
        struct.pack_into("<I", broken, 48, 4000)
        reading = PT.emf_text(emf(bytes(broken), text_w(0, 20, "kept")))
        self.assertEqual([t.string for t in reading.texts], ["kept"])

    def test_not_an_emf(self):
        self.assertEqual(PT.picture_text(IMAGES.PNG).texts, [])


class ReadWmf(unittest.TestCase):
    def test_both_text_records_with_and_without_the_placeable_header(self):
        for placeable in (True, False):
            with self.subTest(placeable=placeable):
                data = wmf(wmf_textout(10, 20, "Odd"), wmf_exttextout(30, 40, "Even", rect=True),
                           wmf_exttextout(50, 60, "Bare"), placeable=placeable)
                reading = PT.picture_text(data)
                self.assertEqual([(t.string, t.x, t.y) for t in reading.texts],
                                 [("Odd", 10, 20), ("Even", 30, 40), ("Bare", 50, 60)])
                self.assertEqual(reading.texts[1].right - reading.texts[1].left, 28)


class Layout(unittest.TestCase):
    def grid(self, rows, **kw):
        texts = PT.emf_text(emf(*grid_emf(rows, **kw))).texts
        return [PT.grid_of(block) for block in PT.blocks_of(PT.lines_of(texts))]

    def test_rows_and_columns(self):
        self.assertEqual(self.grid([["A", "B"], ["C", "D"]]), [[["A", "B"], ["C", "D"]]])

    def test_a_blank_cell_keeps_its_column(self):
        self.assertEqual(self.grid([["A", "B", "C"], ["D", "", "F"]]),
                         [[["A", "B", "C"], ["D", "", "F"]]])

    def test_a_cell_drawn_in_two_records_is_one_cell(self):
        texts = PT.emf_text(emf(text_w(0, 0, "Name", advance=6), text_w(100, 0, "First", advance=6),
                                text_w(134, 0, "part", advance=6), text_w(0, 20, "x", advance=6),
                                text_w(100, 20, "y", advance=6))).texts
        self.assertEqual(PT.grid_of(PT.lines_of(texts)), [["Name", "First part"], ["x", "y"]])

    def test_a_wide_gap_starts_a_second_table(self):
        first = [[f"r{r}c{c}" for c in range(6)] for r in range(14)]
        second = [[f"s{r}c{c}" for c in range(4)] for r in range(8)]
        records = grid_emf(first) + grid_emf(second, top=14 * 20 + 20)
        texts = PT.emf_text(emf(*records)).texts
        grids = [PT.grid_of(block) for block in PT.blocks_of(PT.lines_of(texts))]
        self.assertEqual(grids, [first, second])

    def test_a_raised_cell_stays_on_its_line_without_a_font_height(self):
        rows = [wmf_exttextout(0, r * 100, f"a{r}") for r in range(4)]
        rows += [wmf_exttextout(500, r * 100 + 1, f"b{r}") for r in range(4)]
        texts = PT.picture_text(wmf(*rows)).texts
        self.assertEqual(PT.grid_of(PT.lines_of(texts)), [[f"a{r}", f"b{r}"] for r in range(4)])
        bare = [wmf_textout(0, r * 100, f"a{r}") for r in range(4)]
        bare += [wmf_textout(500, r * 100 + 1, f"b{r}") for r in range(4)]
        lines = PT.lines_of(PT.picture_text(wmf(*bare)).texts)
        self.assertEqual([PT.line_text(line) for line in lines], [f"a{r} b{r}" for r in range(4)])

    def test_one_line_is_not_a_grid(self):
        self.assertEqual(self.grid([["A", "B"]]), [None])


class Rewrite(unittest.TestCase):
    """Word files holding vector pictures, rewritten and converted as convert.sh does."""

    def picture_docx(self, body, media, name="image1.emf"):
        path = self.dir / "in.docx"
        IMAGES.pictured_docx(path, body)
        with zipfile.ZipFile(path) as archive:
            parts = {info.filename: archive.read(info) for info in archive.infolist()}
        rels = parts["word/_rels/document.xml.rels"].decode()
        parts["word/_rels/document.xml.rels"] = rels.replace(
            "media/image1.png", f"media/{name}").replace(
            "</Relationships>",
            '<Relationship Id="rIdPng" Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/image" Target="media/image1.png"/></Relationships>').encode()
        parts[f"word/media/{name}"] = media
        with zipfile.ZipFile(path, "w") as archive:
            for part, data in parts.items():
                archive.writestr(part, data)
        return path

    def convert(self, path):
        out = self.dir / "out.docx"
        counts = PT.rewrite(path, out)
        return counts, IMAGES.written(out, "docx")

    def setUp(self):
        if not shutil.which("pandoc"):
            self.skipTest("pandoc is not installed")
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)

    def test_a_pasted_range_becomes_two_tables(self):
        first = [["Element", "Source", "Note"], ["Name", "Intake", "Required"],
                 ["Birth date", "Intake", ""]]
        second = [["Column", "Meaning"], ["FC_FLAG", "In foster care"]]
        media = emf(*(grid_emf(first) + grid_emf(second, top=100)))
        body = [IMAGES.para(IMAGES.run("Data Element Source")), IMAGES.para(IMAGES.picture())]
        counts, text = self.convert(self.picture_docx(body, media))
        self.assertEqual(counts, (1, 0))
        self.assertEqual(text, (
            "Data Element Source\n\n"
            "| Element    | Source | Note     |\n"
            "|------------|--------|----------|\n"
            "| Name       | Intake | Required |\n"
            "| Birth date | Intake |          |\n\n"
            "| Column  | Meaning        |\n"
            "|---------|----------------|\n"
            "| FC_FLAG | In foster care |\n"))

    def test_text_not_in_a_grid_is_a_paragraph(self):
        media = emf(text_w(0, 0, "Approved by the board"))
        counts, text = self.convert(self.picture_docx([IMAGES.para(IMAGES.picture())], media))
        self.assertEqual(counts, (1, 0))
        self.assertEqual(text.strip(), "Approved by the board")

    def test_a_picture_in_a_sentence_becomes_words(self):
        media = emf(text_w(0, 0, "Save"))
        body = [IMAGES.para(IMAGES.run("Press the ") + IMAGES.picture()
                            + IMAGES.run(" button."))]
        _, text = self.convert(self.picture_docx(body, media))
        self.assertEqual(text.strip(), "Press the Save button.")

    def test_a_picture_in_a_link_or_an_insertion_keeps_the_words_around_it(self):
        media = emf(text_w(0, 0, "Save"))
        for wrap in (IMAGES.linked, lambda inner: f'<w:ins w:id="1" w:author="a">{inner}</w:ins>'):
            with self.subTest(wrap=wrap):
                body = [IMAGES.para(IMAGES.run("Press ")
                                    + wrap(IMAGES.run("the link ") + IMAGES.picture())
                                    + IMAGES.run(" now."))]
                counts, text = self.convert(self.picture_docx(body, media))
                self.assertEqual(counts, (1, 0))
                self.assertIn("the link", text)
                self.assertIn("Save", text)
                self.assertIn("now.", text)

    def test_a_picture_with_its_older_fallback_is_read_once(self):
        media = emf(text_w(0, 0, "Hello"))
        both = ('<w:r><mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/'
                'markup-compatibility/2006"><mc:Choice Requires="wps">'
                + IMAGES.picture()[len("<w:r>"):-len("</w:r>")]
                + "</mc:Choice><mc:Fallback>"
                + IMAGES.vml_picture()[len("<w:r>"):-len("</w:r>")]
                + "</mc:Fallback></mc:AlternateContent></w:r>")
        for body in ([IMAGES.para(IMAGES.run("See ") + both)], [IMAGES.para(both)]):
            with self.subTest(body=body):
                counts, text = self.convert(self.picture_docx(body, media))
                self.assertEqual(counts, (1, 0))
                self.assertEqual(text.count("Hello"), 1)

    def test_a_link_holding_two_pictures_keeps_the_one_not_read(self):
        media = emf(text_w(0, 0, "Read"))
        body = [IMAGES.para(IMAGES.linked(
            IMAGES.picture() + IMAGES.picture().replace("rIdImg", "rIdPng")))]
        counts, text = self.convert(self.picture_docx(body, media))
        self.assertEqual(counts, (1, 0))
        self.assertIn("Read", text)
        self.assertIn("Picture", text)

    def test_the_same_picture_twice_is_put_back_twice(self):
        media = emf(text_w(0, 0, "Twice"))
        body = [IMAGES.para(IMAGES.picture()), IMAGES.para(IMAGES.run("between")),
                IMAGES.para(IMAGES.picture())]
        counts, text = self.convert(self.picture_docx(body, media))
        self.assertEqual(counts, (2, 0))
        self.assertEqual(text.split(), ["Twice", "between", "Twice"])

    def test_readable_and_unreadable_text_in_one_picture_is_both(self):
        media = emf(text_w(0, 0, "Kept"), text_w(0, 20, "AB", options=ETO_GLYPH_INDEX))
        counts, text = self.convert(self.picture_docx([IMAGES.para(IMAGES.picture())], media))
        self.assertEqual(counts, (1, 1))
        self.assertEqual(text.strip(), "Kept")

    def test_a_picture_in_a_text_box_is_read_once_and_the_box_stays(self):
        media = emf(text_w(0, 0, "Boxed"))
        box = ('<w:r><w:pict><v:shape id="box"><v:textbox><w:txbxContent>'
               + IMAGES.para(IMAGES.picture()) + IMAGES.para(IMAGES.run("Box words"))
               + "</w:txbxContent></v:textbox></v:shape></w:pict></w:r>")
        other = emf(text_w(0, 0, "Outside"))
        body = [IMAGES.para(IMAGES.picture().replace("rIdImg", "rIdOut") + box)]
        path = self.picture_docx(body, media)
        with zipfile.ZipFile(path) as archive:
            parts = {info.filename: archive.read(info) for info in archive.infolist()}
        parts["word/_rels/document.xml.rels"] = parts["word/_rels/document.xml.rels"].replace(
            b"</Relationships>",
            b'<Relationship Id="rIdOut" Type="http://schemas.openxmlformats.org/officeDocument/'
            b'2006/relationships/image" Target="media/image2.emf"/></Relationships>')
        parts["word/media/image2.emf"] = other
        with zipfile.ZipFile(path, "w") as archive:
            for part, data in parts.items():
                archive.writestr(part, data)
        out = self.dir / "out.docx"
        self.assertEqual(PT.rewrite(path, out), (2, 0))
        with zipfile.ZipFile(out) as archive:
            document = archive.read("word/document.xml").decode()
        # Pandoc does not read a text box drawn in the older form, so the box is
        # checked in the file it is given.
        box_xml = document[document.index("<w:txbxContent>"):document.index("</w:txbxContent>")]
        self.assertIn("Boxed", box_xml)
        self.assertIn("Box words", box_xml)
        self.assertNotIn("Outside", box_xml)
        self.assertEqual(IMAGES.written(out, "docx").strip(), "Outside")

    def test_a_wmf_picture_in_the_older_form(self):
        media = wmf(wmf_textout(0, 0, "Legacy"))
        _, text = self.convert(self.picture_docx([IMAGES.para(IMAGES.vml_picture())], media,
                                                 name="image1.wmf"))
        self.assertEqual(text.strip(), "Legacy")

    def test_a_png_keeps_its_placeholder(self):
        body = [IMAGES.para(IMAGES.picture().replace("rIdImg", "rIdPng"))]
        counts, text = self.convert(self.picture_docx(body, emf()))
        self.assertEqual(counts, (0, 0))
        self.assertEqual(text.strip(), "\\[Picture\\]")

    def test_a_png_beside_a_recovered_picture_keeps_its_own_paragraph(self):
        media = emf(text_w(0, 0, "Read"))
        body = [IMAGES.para(IMAGES.picture() + IMAGES.picture().replace("rIdImg", "rIdPng"))]
        counts, text = self.convert(self.picture_docx(body, media))
        self.assertEqual(counts, (1, 0))
        self.assertEqual([part.strip() for part in text.strip().split("\n\n")],
                         ["Read", "\\[Picture\\]"])

    def test_glyph_index_text_is_counted_unread_and_keeps_its_placeholder(self):
        media = emf(text_w(0, 0, "AB", options=ETO_GLYPH_INDEX))
        counts, text = self.convert(self.picture_docx([IMAGES.para(IMAGES.picture())], media))
        self.assertEqual(counts, (0, 1))
        self.assertEqual(text.strip(), "\\[Picture\\]")

    def test_a_picture_drawing_its_text_both_as_emf_and_emf_plus_is_recovered(self):
        media = emf(emf_plus(PT.EMF_PLUS_DRAW_STRING), text_w(0, 0, "Both ways"))
        counts, text = self.convert(self.picture_docx([IMAGES.para(IMAGES.picture())], media))
        self.assertEqual(counts, (1, 0))
        self.assertEqual(text.strip(), "Both ways")

    def test_text_drawn_only_as_emf_plus_is_unread_and_keeps_its_placeholder(self):
        media = emf(emf_plus(PT.EMF_PLUS_DRAW_DRIVER_STRING))
        counts, text = self.convert(self.picture_docx([IMAGES.para(IMAGES.picture())], media))
        self.assertEqual(counts, (0, 1))
        self.assertEqual(text.strip(), "\\[Picture\\]")

    def text_box(self, choice=None, fallback=None):
        """A run holding a text box under mc:AlternateContent, the drawing form
        in its Choice and the older form in its Fallback, each holding the
        paragraph given, or no Choice when none is given."""
        mc = PT.MC[1:-1]
        wps = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
        out = f'<w:r><mc:AlternateContent xmlns:mc="{mc}" xmlns:wps="{wps}">'
        if choice is not None:
            out += ('<mc:Choice Requires="wps"><w:drawing><wps:wsp><wps:txbx><w:txbxContent>'
                    + choice + "</w:txbxContent></wps:txbx></wps:wsp></w:drawing></mc:Choice>")
        return (out + '<mc:Fallback><w:pict><v:shape id="box"><v:textbox><w:txbxContent>'
                + fallback + "</w:txbxContent></v:textbox></v:shape></w:pict></mc:Fallback>"
                "</mc:AlternateContent></w:r>")

    def rewritten(self, path):
        out = self.dir / "out.docx"
        counts = PT.rewrite(path, out)
        with zipfile.ZipFile(out) as archive:
            return counts, archive.read("word/document.xml").decode()

    def test_a_text_box_written_in_both_forms_is_counted_once(self):
        inside = IMAGES.para(IMAGES.picture())
        box = self.text_box(choice=inside, fallback=inside)
        path = self.picture_docx([IMAGES.para(IMAGES.run("Before") + box)],
                                 emf(text_w(0, 0, "Boxed")))
        counts, document = self.rewritten(path)
        self.assertEqual(counts, (1, 0))
        self.assertEqual(document.count("Boxed"), 2)

    def test_unread_text_in_a_text_box_written_in_both_forms_is_counted_once(self):
        inside = IMAGES.para(IMAGES.picture())
        box = self.text_box(choice=inside, fallback=inside)
        path = self.picture_docx([IMAGES.para(IMAGES.run("Before") + box)],
                                 emf(text_w(0, 0, "AB", options=ETO_GLYPH_INDEX)))
        self.assertEqual(self.rewritten(path)[0], (0, 1))

    def test_a_fallback_picture_the_drawing_does_not_hold_is_counted(self):
        box = self.text_box(choice=IMAGES.para(IMAGES.run("Words")),
                            fallback=IMAGES.para(IMAGES.picture()))
        path = self.picture_docx([IMAGES.para(IMAGES.run("Before") + box)],
                                 emf(text_w(0, 0, "AB", options=ETO_GLYPH_INDEX)))
        self.assertEqual(self.rewritten(path)[0], (0, 1))

    def test_a_fallback_with_no_choice_is_counted(self):
        box = self.text_box(fallback=IMAGES.para(IMAGES.picture()))
        path = self.picture_docx([IMAGES.para(IMAGES.run("Before") + box)],
                                 emf(text_w(0, 0, "Alone")))
        self.assertEqual(self.rewritten(path)[0], (1, 0))

    def test_a_line_drawing_is_neither_recovered_nor_unread(self):
        counts, text = self.convert(self.picture_docx([IMAGES.para(IMAGES.picture())], emf()))
        self.assertEqual(counts, (0, 0))
        self.assertEqual(text.strip(), "\\[Picture\\]")

    def test_a_picture_in_a_table_cell_leaves_the_cell_a_closing_paragraph(self):
        media = emf(*grid_emf([["A", "B"], ["C", "D"]]))
        body = [IMAGES.table([IMAGES.cell(IMAGES.para(IMAGES.picture())),
                              IMAGES.cell(IMAGES.para(IMAGES.run("x")))])]
        path = self.picture_docx(body, media)
        out = self.dir / "out.docx"
        self.assertEqual(PT.rewrite(path, out), (1, 0))
        with zipfile.ZipFile(out) as archive:
            document = archive.read("word/document.xml").decode()
        self.assertRegex(document, r"</w:tbl><w:p ?/></w:tc>")
        text = IMAGES.written(out, "docx")
        for cell in "ABCD":
            self.assertIn(cell, text)

    def test_the_report_and_an_unchanged_file(self):
        path = self.dir / "plain.docx"
        WORD.docx(path, [WORD.para("Nothing drawn")])
        out = self.dir / "out.docx"
        report = self.dir / "report.txt"
        self.assertEqual(PT.main(["picture-text.py", str(path), str(out), "--report",
                                  str(report)]), 0)
        self.assertEqual(report.read_text(), "recovered 0\nunread 0\n")
        self.assertIn("Nothing drawn", IMAGES.written(out, "docx"))

    def test_a_file_that_is_not_a_zip_exits_1(self):
        path = self.dir / "not.docx"
        path.write_text("text")
        self.assertEqual(PT.main(["picture-text.py", str(path), str(self.dir / "o.docx")]), 1)

    def test_the_page_step_finds_a_page_that_opens_on_the_table(self):
        rows = [["Element", "Source"], ["Name", "Intake"]]
        body = [IMAGES.para(IMAGES.run("Heading text")), IMAGES.para(IMAGES.picture())]
        path = self.picture_docx(body, emf(*grid_emf(rows)))
        layout = PAGES.Layout(pages=2, label="test", starts=["Element Source Name Intake"])
        before = PAGES.place(IMAGES.written(path, "docx"), layout)
        self.assertEqual(before.missed, [2])
        _, text = self.convert(path)
        self.assertEqual(PAGES.place(text, layout).missed, [])


class ConvertRun(unittest.TestCase):
    """convert.sh on a Word file holding pictures, with LibreOffice and the PDF
    tools stubbed out, so only Pandoc and the steps around it run."""

    def setUp(self):
        if not shutil.which("pandoc"):
            self.skipTest("pandoc is not installed")
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.repo = self.dir / "repo"
        self.suite = self.repo / "todo" / "OCS"
        self.suite.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        (self.repo / "words.txt").write_text("plain\n", encoding="utf-8")
        (self.repo / "extension.json").write_text(json.dumps({
            "todoRoot": "todo", "appsRoot": "apps", "futureFolder": "Future",
            "words": "words.txt", "collisions": "collisions.tsv",
            "sharePointHost": "https://example.invalid"}), encoding="utf-8")
        stubs = self.dir / "stubs"
        stubs.mkdir()
        for tool in ("soffice", "pdftotext", "pdfinfo"):
            (stubs / tool).write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            (stubs / tool).chmod(0o755)
        self.env = {**os.environ, "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}"}

    def convert(self, media, secondary=None):
        rewrite = Rewrite()
        rewrite.dir = self.dir
        for name, picture in (("Foster.docx", media), ("Foster.docm", secondary)):
            if picture is None:
                continue
            path = rewrite.picture_docx(
                [IMAGES.para(IMAGES.run("Data Element Source")), IMAGES.para(IMAGES.picture()),
                 IMAGES.para(IMAGES.picture().replace("rIdImg", "rIdPng"))], picture)
            shutil.move(path, self.suite / name)
        run = subprocess.run(
            ["bash", str(HERE / "convert.sh"), "--config", str(self.repo / "extension.json"),
             "--converted", "2024-01-02 03:04Z", "--keep-sources"],
            capture_output=True, text=True, check=False, timeout=600, env=self.env)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        return run.stdout, (self.repo / "apps" / "OCS" / "Foster.md").read_text(encoding="utf-8")

    def test_recovered_text_reaches_the_document_and_the_log(self):
        log, markdown = self.convert(emf(*grid_emf([["Element", "Source"], ["Name", "Intake"]])))
        self.assertIn("| Element | Source |", markdown)
        self.assertIn("| Name    | Intake |", markdown)
        self.assertIn("\\[Picture\\]", markdown)
        self.assertIn("text of 1 picture(s) put back where the picture was", log)
        self.assertNotIn("hold text that was not read", log)
        self.assertIn("with picture text put back 1, with picture text not read 0", log)

    def test_a_second_format_adds_nothing_to_the_counts(self):
        log, markdown = self.convert(emf(*grid_emf([["Element", "Source"], ["Name", "Intake"]])),
                                     secondary=emf(text_w(0, 0, "AB", options=ETO_GLYPH_INDEX)))
        self.assertIn("| Element | Source |", markdown)
        self.assertIn(".docm holds", log)
        self.assertIn("text of 1 picture(s) put back where the picture was", log)
        self.assertNotIn("hold text that was not read", log)
        self.assertIn("with picture text put back 1, with picture text not read 0", log)

    def test_unread_text_is_logged(self):
        log, markdown = self.convert(emf(text_w(0, 0, "AB", options=ETO_GLYPH_INDEX)))
        self.assertNotIn("|", markdown.split("Data Element Source", 1)[1])
        self.assertIn("1 picture(s) hold text that was not read, restore it by hand", log)
        self.assertIn("with picture text put back 0, with picture text not read 1", log)


if __name__ == "__main__":
    unittest.main()
