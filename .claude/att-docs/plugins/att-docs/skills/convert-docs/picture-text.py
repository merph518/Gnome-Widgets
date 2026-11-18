#!/usr/bin/env python3
"""Puts back the text a Word file holds inside a vector picture, so Pandoc writes it.

A range pasted from a spreadsheet as a picture arrives as an EMF or WMF part
under `word/media/`. Word prints it as a table, every cell readable, because the
picture holds each cell as a text record: the string and the point it is drawn
at. Pandoc's reader keeps only a reference to the picture, and the images filter
turns that into a `[Picture]` placeholder, so the table is lost and a page that
opens on it is a page whose opening text the Markdown never holds.

This step reads the text records of each EMF and WMF picture in the body and
puts the text where the picture was:

- A picture alone in its paragraph whose text lines up in at least two rows and
  two columns becomes a Word table, one per block of rows. A vertical gap wider
  than one and a half times the usual row spacing starts a new table, as a blank
  row between two ranges does. Its first row is the table's header.
- A picture alone in its paragraph whose text does not make a grid becomes one
  paragraph per line of text.
- A picture inside a line of text becomes its text, joined by spaces.

Lines are the text records whose points sit within half a font height of each
other. Columns come from the rows that hold more than one cell: the stretches of
the page their text covers, measured from each record's advance widths and text
alignment, are the columns, and a record goes in the column it overlaps most. A
blank cell draws nothing, so the cells beside it keep their own columns.

A picture with no text records, such as a line drawing or a bitmap, and every
picture that is not an EMF or a WMF, is left as it is for the images filter. A
picture whose text is there but cannot be read back as characters, because it
is drawn as glyph indexes or only as EMF+ records, is left too, and counted as
unread, so the run can say a picture held text that the Markdown does not.

Usage:
  picture-text.py IN OUT [--report FILE]

Writes OUT and exits 0. FILE, when given, gets two lines, `recovered N` and
`unread N`: the pictures whose text went in, and those whose text could not be
read. Exits 1 when IN is not a zip archive or its body is not well-formed XML.
"""
from __future__ import annotations

import copy
import io
import posixpath
import statistics
import struct
import sys
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
V = "{urn:schemas-microsoft-com:vml}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

BODY = "word/document.xml"
RELS = "word/_rels/document.xml.rels"

# ExtTextOut options.
ETO_OPAQUE = 0x0002
ETO_CLIPPED = 0x0004
ETO_GLYPH_INDEX = 0x0010
ETO_NO_RECT = 0x0100
ETO_SMALL_CHARS = 0x0200
ETO_PDY = 0x2000

# The horizontal part of a text alignment: left, right, or centered.
TA_HORIZONTAL = 0x0006
TA_RIGHT = 0x0002
TA_CENTER = 0x0006

# EMF record types.
EMR_HEADER = 1
EMR_EOF = 14
EMR_SETWINDOWEXTEX = 9
EMR_SETVIEWPORTEXTEX = 11
EMR_SETTEXTALIGN = 22
EMR_SELECTOBJECT = 37
EMR_COMMENT = 70
EMR_EXTCREATEFONTINDIRECTW = 82
EMR_EXTTEXTOUTA = 83
EMR_EXTTEXTOUTW = 84
EMR_SMALLTEXTOUT = 108
EMF_PLUS_DRAW_STRING = 0x401C

# WMF record functions.
META_EOF = 0x0000
META_SETTEXTALIGN = 0x012E
META_TEXTOUT = 0x0521
META_EXTTEXTOUT = 0x0A32
WMF_PLACEABLE = 0x9AC6CDD7

# A gap between rows this many times the usual spacing starts a new table.
TABLE_GAP = 1.5


@dataclass
class Text:
    """One text record: its string, the point it is drawn at, how far it runs
    to the right of its left edge, and the height of its font, 0 when unknown."""
    string: str
    x: float
    y: float
    left: float
    right: float
    height: float = 0.0


@dataclass
class Reading:
    """What one picture holds: the text records read, and whether it held text
    that could not be read back as characters."""
    texts: list[Text]
    unread: bool = False


def keep_prefixes(raw: bytes) -> None:
    # ElementTree writes ns0:, ns1: for every prefix it was not told about.
    for _, (prefix, uri) in ET.iterparse(io.BytesIO(raw), events=("start-ns",)):
        try:
            ET.register_namespace(prefix, uri)
        except ValueError:
            pass


def extent(x: float, width: float, align: int) -> tuple[float, float]:
    """The left and right edges of a string drawn at `x` with this alignment."""
    horizontal = align & TA_HORIZONTAL
    if horizontal == TA_CENTER:
        return x - width / 2, x + width / 2
    if horizontal == TA_RIGHT:
        return x - width, x
    return x, x + width


def is_emf(data: bytes) -> bool:
    return (len(data) >= 44 and struct.unpack_from("<I", data, 0)[0] == EMR_HEADER
            and data[40:44] == b" EMF")


def is_wmf(data: bytes) -> bool:
    if len(data) >= 4 and struct.unpack_from("<I", data, 0)[0] == WMF_PLACEABLE:
        return True
    if len(data) < 18:
        return False
    kind, header_words = struct.unpack_from("<HH", data, 0)
    return kind in (1, 2) and header_words == 9


def emf_plus_draws_string(data: bytes, start: int, end: int) -> bool:
    """Whether an EMR_COMMENT holding EMF+ records holds a DrawString."""
    at = start + 16
    if end - start < 16 or data[start + 12:start + 16] != b"EMF+":
        return False
    while at + 12 <= end:
        kind, _, size = struct.unpack_from("<HHI", data, at)
        if kind == EMF_PLUS_DRAW_STRING:
            return True
        if size < 12:
            return False
        at += size
    return False


def emf_text(data: bytes) -> Reading:
    """The text records of an EMF picture. A record that runs past the end, or
    one too short to hold what its type says, ends the reading."""
    reading = Reading([])
    if not is_emf(data):
        return reading
    fonts: dict[int, float] = {}
    font = 0.0
    align = 0
    window_y = viewport_y = 1
    at = 0
    while at + 8 <= len(data):
        kind, size = struct.unpack_from("<II", data, at)
        if size < 8 or size % 4 or at + size > len(data):
            break
        end = at + size
        try:
            if kind == EMR_EOF:
                break
            if kind == EMR_SETTEXTALIGN:
                align = struct.unpack_from("<I", data, at + 8)[0]
            elif kind == EMR_SETWINDOWEXTEX:
                window_y = struct.unpack_from("<i", data, at + 12)[0] or 1
            elif kind == EMR_SETVIEWPORTEXTEX:
                viewport_y = struct.unpack_from("<i", data, at + 12)[0] or 1
            elif kind == EMR_EXTCREATEFONTINDIRECTW:
                handle, height = struct.unpack_from("<Ii", data, at + 8)
                fonts[handle] = abs(height)
            elif kind == EMR_SELECTOBJECT:
                handle = struct.unpack_from("<I", data, at + 8)[0]
                if handle in fonts:
                    font = fonts[handle]
            elif kind == EMR_COMMENT:
                if emf_plus_draws_string(data, at, end):
                    reading.unread = True
            elif kind in (EMR_EXTTEXTOUTW, EMR_EXTTEXTOUTA):
                x, y, count, offset, options = struct.unpack_from("<iiIII", data, at + 36)
                dx_offset = struct.unpack_from("<I", data, at + 72)[0]
                if options & ETO_GLYPH_INDEX:
                    reading.unread = reading.unread or count > 0
                    continue
                wide = kind == EMR_EXTTEXTOUTW
                length = count * 2 if wide else count
                if count == 0 or at + offset + length > end:
                    continue
                raw = data[at + offset:at + offset + length]
                string = raw.decode("utf-16-le" if wide else "cp1252", errors="replace")
                width = 0.0
                step = 2 if options & ETO_PDY else 1
                if dx_offset and at + dx_offset + 4 * count * step <= end:
                    advances = struct.unpack_from(f"<{count * step}i", data, at + dx_offset)
                    width = float(sum(advances[::step]))
                left, right = extent(x, width, align)
                reading.texts.append(Text(string, x, y, left, right, font))
            elif kind == EMR_SMALLTEXTOUT:
                x, y, count, options = struct.unpack_from("<iiII", data, at + 8)
                if options & ETO_GLYPH_INDEX:
                    reading.unread = reading.unread or count > 0
                    continue
                offset = at + 36 + (0 if options & ETO_NO_RECT else 16)
                small = bool(options & ETO_SMALL_CHARS)
                length = count if small else count * 2
                if count == 0 or offset + length > end:
                    continue
                raw = data[offset:offset + length]
                string = raw.decode("cp1252" if small else "utf-16-le", errors="replace")
                left, right = extent(x, 0.0, align)
                reading.texts.append(Text(string, x, y, left, right, font))
        except struct.error:
            break
        finally:
            at = end
    # A window and a viewport whose heights differ in sign draw the picture
    # with y running up the page, so the order of its lines is turned round.
    if (window_y < 0) != (viewport_y < 0):
        for text in reading.texts:
            text.y = -text.y
    reading.texts = [text for text in reading.texts if text.string.strip()]
    return reading


def wmf_text(data: bytes) -> Reading:
    """The text records of a WMF picture, read as Windows-1252."""
    reading = Reading([])
    if not is_wmf(data):
        return reading
    start = 22 if struct.unpack_from("<I", data, 0)[0] == WMF_PLACEABLE else 0
    if start + 18 > len(data):
        return reading
    header_words = struct.unpack_from("<H", data, start + 2)[0]
    at = start + header_words * 2
    align = 0
    while at + 6 <= len(data):
        words, function = struct.unpack_from("<IH", data, at)
        size = words * 2
        if size < 6 or at + size > len(data):
            break
        end = at + size
        params = at + 6
        try:
            if function == META_EOF:
                break
            if function == META_SETTEXTALIGN:
                align = struct.unpack_from("<H", data, params)[0]
            elif function == META_TEXTOUT:
                count = struct.unpack_from("<h", data, params)[0]
                padded = count + (count & 1)
                if count > 0 and params + 2 + padded + 4 <= end:
                    raw = data[params + 2:params + 2 + count]
                    y, x = struct.unpack_from("<hh", data, params + 2 + padded)
                    left, right = extent(x, 0.0, align)
                    reading.texts.append(Text(raw.decode("cp1252", errors="replace"),
                                              x, y, left, right))
            elif function == META_EXTTEXTOUT:
                y, x, count, options = struct.unpack_from("<hhhH", data, params)
                offset = params + 8 + (8 if options & (ETO_OPAQUE | ETO_CLIPPED) else 0)
                if options & ETO_GLYPH_INDEX:
                    reading.unread = reading.unread or count > 0
                elif count > 0 and offset + count <= end:
                    raw = data[offset:offset + count]
                    width = 0.0
                    dx = offset + count + (count & 1)
                    if dx + 2 * count <= end:
                        width = float(sum(struct.unpack_from(f"<{count}h", data, dx)))
                    left, right = extent(x, width, align)
                    reading.texts.append(Text(raw.decode("cp1252", errors="replace"),
                                              x, y, left, right))
        except struct.error:
            break
        at = end
    reading.texts = [text for text in reading.texts if text.string.strip()]
    return reading


def picture_text(data: bytes) -> Reading:
    if is_emf(data):
        return emf_text(data)
    if is_wmf(data):
        return wmf_text(data)
    return Reading([])


def line_tolerance(texts: list[Text]) -> float:
    """How far apart two points may sit and still be on one line: half the font
    height, or, with no font height, one character's width, which is about the
    same. A picture that gives neither is measured by the spacing of its lines:
    half the gap that three in four gaps are no wider than, which skips the
    small steps a bold header or a raised cell puts between points of one line."""
    heights = [text.height for text in texts if text.height > 0]
    if heights:
        return statistics.median(heights) / 2
    advances = [(text.right - text.left) / len(text.string) for text in texts
                if text.right > text.left]
    if advances:
        return statistics.median(advances)
    ys = sorted({text.y for text in texts})
    gaps = sorted(b - a for a, b in zip(ys, ys[1:]))
    if not gaps:
        return 0
    return gaps[min(len(gaps) - 1, len(gaps) * 3 // 4)] / 2


def lines_of(texts: list[Text]) -> list[list[Text]]:
    """The records grouped into lines, top to bottom, each left to right."""
    if not texts:
        return []
    ordered = sorted(texts, key=lambda text: (text.y, text.left))
    tolerance = line_tolerance(texts)
    lines: list[list[Text]] = []
    for text in ordered:
        if lines and text.y - lines[-1][0].y <= tolerance:
            lines[-1].append(text)
        else:
            lines.append([text])
    for line in lines:
        line.sort(key=lambda text: text.left)
    return lines


def blocks_of(lines: list[list[Text]]) -> list[list[list[Text]]]:
    """The lines split into blocks wherever the gap between two lines is more
    than TABLE_GAP times the usual one."""
    if len(lines) < 3:
        return [lines] if lines else []
    tops = [line[0].y for line in lines]
    gaps = [b - a for a, b in zip(tops, tops[1:])]
    usual = statistics.median(gaps)
    blocks = [[lines[0]]]
    for gap, line in zip(gaps, lines[1:]):
        if usual > 0 and gap > usual * TABLE_GAP:
            blocks.append([])
        blocks[-1].append(line)
    return blocks


def columns_of(lines: list[list[Text]]) -> list[tuple[float, float]]:
    """The stretches the text of the lines holding more than one cell covers.
    Two stretches less than a character apart are one: a cell whose words are
    drawn in separate records leaves about a space between them."""
    texts = [text for line in lines if len(line) > 1 for text in line]
    spans = sorted((text.left, text.right) for text in texts)
    advances = [(text.right - text.left) / len(text.string) for text in texts
                if text.right > text.left]
    join = statistics.median(advances) if advances else 0
    columns: list[list[float]] = []
    for left, right in spans:
        if columns and left <= columns[-1][1] + join:
            columns[-1][1] = max(columns[-1][1], right)
        else:
            columns.append([left, right])
    return [(left, right) for left, right in columns]


def column_of(text: Text, columns: list[tuple[float, float]]) -> int:
    def overlap(column):
        return min(column[1], text.right) - max(column[0], text.left)

    def distance(column):
        middle = (text.left + text.right) / 2
        return 0 if column[0] <= middle <= column[1] else min(
            abs(middle - column[0]), abs(middle - column[1]))

    best = max(range(len(columns)), key=lambda index: overlap(columns[index]))
    if overlap(columns[best]) > 0:
        return best
    return min(range(len(columns)), key=lambda index: distance(columns[index]))


def grid_of(lines: list[list[Text]]) -> list[list[str]] | None:
    """The lines as rows of cells, or None when they make no grid of at least
    two rows and two columns."""
    columns = columns_of(lines)
    if len(lines) < 2 or len(columns) < 2:
        return None
    rows = []
    for line in lines:
        cells: list[list[str]] = [[] for _ in columns]
        for text in line:
            cells[column_of(text, columns)].append(text.string.strip())
        rows.append([" ".join(cell) for cell in cells])
    return rows


def line_text(line: list[Text]) -> str:
    return " ".join(text.string.strip() for text in line)


# Building the Word nodes that take a picture's place.

def run_of(text: str, properties=None):
    run = ET.Element(W + "r")
    if properties is not None:
        run.append(copy.deepcopy(properties))
    node = ET.SubElement(run, W + "t")
    node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    node.text = text
    return run


def paragraph_of(text: str, properties=None):
    paragraph = ET.Element(W + "p")
    if properties is not None:
        paragraph.append(copy.deepcopy(properties))
    paragraph.append(run_of(text))
    return paragraph


def table_of(rows: list[list[str]]):
    table = ET.Element(W + "tbl")
    table_properties = ET.SubElement(table, W + "tblPr")
    ET.SubElement(table_properties, W + "tblStyle").set(W + "val", "TableGrid")
    grid = ET.SubElement(table, W + "tblGrid")
    # Pandoc's reader counts a table's columns from the widths its grid gives.
    for _ in rows[0]:
        ET.SubElement(grid, W + "gridCol").set(W + "w", "2000")
    for index, cells in enumerate(rows):
        row = ET.SubElement(table, W + "tr")
        if index == 0:
            ET.SubElement(ET.SubElement(row, W + "trPr"), W + "tblHeader")
        for text in cells:
            cell = ET.SubElement(row, W + "tc")
            cell.append(paragraph_of(text) if text else ET.Element(W + "p"))
    return table


def blocks_for(reading: Reading, properties=None) -> list:
    """The tables and paragraphs that take the place of a picture alone in its
    paragraph."""
    out = []
    for block in blocks_of(lines_of(reading.texts)):
        grid = grid_of(block)
        if grid:
            out.append(table_of(grid))
        else:
            out.extend(paragraph_of(line_text(line), properties) for line in block)
    return out


def inline_text(reading: Reading) -> str:
    return " ".join(line_text(line) for line in lines_of(reading.texts))


# Finding the pictures.

def media_of(parts: dict[str, bytes]) -> dict[str, str]:
    """Relationship id to the part it names, for the body's relationships."""
    if RELS not in parts:
        return {}
    found = {}
    for relationship in ET.fromstring(parts[RELS]).iter(REL + "Relationship"):
        if relationship.get("TargetMode") == "External":
            continue
        target = relationship.get("Target", "")
        name = target.lstrip("/") if target.startswith("/") else posixpath.normpath(
            posixpath.join("word", target))
        found[relationship.get("Id")] = name
    return found


def own(node):
    """The nodes under `node`, leaving out the paragraphs of a text box, which
    are paragraphs of their own."""
    for child in node:
        if child.tag == W + "txbxContent":
            continue
        yield child
        yield from own(child)


def picture_ids(node) -> list[str]:
    nodes = [node, *own(node)]
    ids = [found.get(R + "embed") for found in nodes if found.tag == A + "blip"]
    ids += [found.get(R + "id") for found in nodes if found.tag == V + "imagedata"]
    # Word writes a picture twice in one run, as a drawing and as its older
    # fallback, under the same id.
    return list(dict.fromkeys(value for value in ids if value))


def visible_text(paragraph) -> str:
    return "".join(node.text or "" for node in own(paragraph) if node.tag == W + "t")


def kept(rest, properties) -> bool:
    """Whether what is left of a split paragraph holds anything past its
    properties: another picture, a text box, a bookmark."""
    return rest is not None and len(rest) > (0 if properties is None else 1)


class Pass:
    """One rewrite of the body, with the readings of each picture part cached."""

    def __init__(self, parts: dict[str, bytes]):
        self.parts = parts
        self.media = media_of(parts)
        self.readings: dict[str, Reading] = {}
        self.recovered = 0
        self.unread = 0

    def read(self, node) -> list[Reading]:
        """The text of each vector picture `node` holds whose text went in. A
        picture holding text that could not be read is counted as unread, even
        when the rest of its text went in."""
        found = []
        for rid in picture_ids(node):
            name = self.media.get(rid)
            if name is None or name not in self.parts:
                continue
            if name not in self.readings:
                self.readings[name] = picture_text(self.parts[name])
            reading = self.readings[name]
            if reading.unread:
                self.unread += 1
            if reading.texts:
                self.recovered += 1
                found.append(reading)
        return found

    def held(self, child, parents) -> list[Reading]:
        """The readings of the pictures a child of a paragraph holds. A child
        that is not a run, such as a link, gives up only the runs that held
        them."""
        if child.tag == W + "r":
            return self.read(child)
        found = []
        for run in [node for node in own(child) if node.tag == W + "r"]:
            readings = self.read(run)
            if readings:
                parents[run].remove(run)
                found.extend(readings)
        return found

    def paragraph(self, paragraph, parents) -> bool:
        if not visible_text(paragraph).strip():
            return self.alone(paragraph, parents)
        changed = False
        for run in [node for node in own(paragraph) if node.tag == W + "r"]:
            readings = self.read(run)
            if readings:
                # Only the run goes: a hyperlink or a tracked insertion around
                # it keeps the rest of its text.
                text = " ".join(inline_text(reading) for reading in readings)
                holder = parents[run]
                index = list(holder).index(run)
                holder.remove(run)
                holder.insert(index, run_of(text, run.find(W + "rPr")))
                changed = True
        return changed

    def alone(self, paragraph, parents) -> bool:
        """A paragraph with no text of its own is split at each picture whose
        text went in, and what is left keeps its own paragraph."""
        parent = parents[paragraph]
        properties = paragraph.find(W + "pPr")
        found = [(child, self.held(child, parents)) for child in paragraph
                 if child is not properties]
        if not any(readings for _, readings in found):
            return False
        out = []
        rest = None
        for child, readings in found:
            if readings:
                # A link or an insertion that held the picture keeps whatever
                # else it held, ahead of the picture's text.
                if child.tag != W + "r" and len(child):
                    if rest is None:
                        rest = ET.Element(W + "p")
                        if properties is not None:
                            rest.append(copy.deepcopy(properties))
                    rest.append(child)
                if kept(rest, properties):
                    out.append(rest)
                rest = None
                for reading in readings:
                    out.extend(blocks_for(reading, properties))
                continue
            if rest is None:
                rest = ET.Element(W + "p")
                if properties is not None:
                    rest.append(copy.deepcopy(properties))
            rest.append(child)
        if kept(rest, properties):
            out.append(rest)
        index = list(parent).index(paragraph)
        parent.remove(paragraph)
        for offset, node in enumerate(out):
            parent.insert(index + offset, node)
        # A table cell ends with a paragraph.
        if parent.tag == W + "tc" and parent[-1].tag != W + "p":
            parent.append(ET.Element(W + "p"))
        return True


def rewrite(source, target) -> tuple[int, int]:
    """Writes `target` and returns the pictures recovered and left unread."""
    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        parts = {info.filename: archive.read(info) for info in infos}
    rewrite_pass = Pass(parts)
    if BODY in parts:
        keep_prefixes(parts[BODY])
        root = ET.fromstring(parts[BODY])
        parents = {child: parent for parent in root.iter() for child in parent}
        changed = False
        for paragraph in [node for node in root.iter(W + "p")]:
            changed = rewrite_pass.paragraph(paragraph, parents) or changed
        if changed:
            parts[BODY] = ET.tostring(root, encoding="UTF-8", xml_declaration=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as out:
        for info in infos:
            out.writestr(info, parts[info.filename])
    return rewrite_pass.recovered, rewrite_pass.unread


def main(argv):
    args = argv[1:]
    report = None
    if "--report" in args:
        at = args.index("--report")
        if at + 1 >= len(args):
            sys.stderr.write(__doc__)
            return 64
        report = args[at + 1]
        del args[at:at + 2]
    if len(args) != 2:
        sys.stderr.write(__doc__)
        return 64
    try:
        recovered, unread = rewrite(args[0], args[1])
    except (zipfile.BadZipFile, ET.ParseError, KeyError) as error:
        print(f"picture-text: {args[0]}: {error}", file=sys.stderr)
        return 1
    if report:
        with open(report, "w", encoding="utf-8") as out:
            out.write(f"recovered {recovered}\nunread {unread}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
