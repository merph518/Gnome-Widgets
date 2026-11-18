#!/usr/bin/env python3
"""Gives LibreOffice's docx copy of a Word 97-2003 file the lists Word counts.

A Word 97-2003 file numbers a paragraph through a list override, and each
override names the list it draws from. Word keeps one count per list, so two
overrides of one list continue each other: the paragraphs of the second carry
on from the last number the first drew. LibreOffice's docx copy can give an
override, or part of one override's paragraphs, an abstract numbering
definition of its own, which list-numbers.py and Pandoc then count from its
start.

This step reads the list tables and each paragraph's override from the Word
97-2003 file, pairs its paragraphs with the docx copy's by their words, and
learns which override each docx numbering instance stands for. Instances whose
overrides name one list are put back on one abstract definition. A level the
instance draws differently from that definition keeps its own drawing as a
level override, and the definition starts each level where the list does.

An override's restart applies at the first paragraph Word numbers with it, and
only at that paragraph's level: when the first paragraph of an override sits at
the second level, the next first-level paragraph of the override continues the
list's first-level count. The step writes that restart as a start override on
the one level of the instance holding that paragraph, however many instances
the copy split the override into.

LibreOffice's copy also gives the paragraph after a deleted paragraph mark that
paragraph's properties, its list included, in place of its own. Word joins the
two and draws them with the properties of the second, so where the Word
97-2003 file puts that second paragraph in no list, the step takes it out of
the list in the copy, and the joined paragraph takes no number. The deleted
paragraphs that join it leave their lists with it, so a layout of the copy,
which still draws them apart, numbers the items after them as the Markdown
does.

Usage:
  doc-lists.py SOURCE IN OUT

SOURCE is the Word 97-2003 file and IN its docx copy. Writes OUT and exits 0.
When SOURCE is not a Word 97-2003 file this step can read, or it finds nothing
to change, OUT is a copy of IN. Exits 1 when IN is not a zip archive or a part
of it is not well-formed XML.
"""
from __future__ import annotations

import copy
import difflib
import io
import pathlib
import re
import shutil
import struct
import sys
import xml.etree.ElementTree as ET
import zipfile
from importlib import util

HERE = pathlib.Path(__file__).resolve().parent
_SPEC = util.spec_from_file_location("hidden_text", HERE / "hidden-text.py")
HIDDEN = util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(HIDDEN)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

LEVELS = 9

FREE = 0xFFFFFFFF
END_OF_CHAIN = 0xFFFFFFFE

# Byte offsets in the file information block that opens the WordDocument stream.
FIB_VERSION = 0x02
FIB_FLAGS = 0x0A
FIB_BASE = 32
WHICH_TABLE = 0x0200
ENCRYPTED = 0x0100
# Word 97 is version 193. Word 6 and Word 95 files lay the tables out otherwise.
WORD97 = 0xC1

# Entries of the FibRgFcLcb97 array, each a position and a length in the table stream.
STSHF, CLX, BTE_PAPX, PLF_LST, PLF_LFO = 1, 33, 13, 73, 74

SPRM_ILVL = 0x260A
SPRM_ILFO = 0x460B
SPRM_CHANGE_TABS = 0xC615
SPRM_TABLE_DEFINITION = 0xD608


class NotReadable(Exception):
    """The source is not a Word 97-2003 file this step reads."""


def u16(data, offset):
    return struct.unpack_from("<H", data, offset)[0]


def u32(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def compound_streams(raw):
    """The named streams of a compound file, read whole."""
    if raw[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise NotReadable("not a compound file")
    sector = 1 << u16(raw, 0x1E)
    mini = 1 << u16(raw, 0x20)
    cutoff = u32(raw, 0x38)

    def at(number):
        return raw[(number + 1) * sector:(number + 2) * sector]

    fat_sectors = [u32(raw, 0x4C + 4 * i) for i in range(109)]
    difat, count = u32(raw, 0x44), u32(raw, 0x48)
    for _ in range(count):
        if difat in (FREE, END_OF_CHAIN):
            break
        block = at(difat)
        fat_sectors += [u32(block, 4 * i) for i in range(sector // 4 - 1)]
        difat = u32(block, sector - 4)
    fat = []
    for number in fat_sectors:
        if number in (FREE, END_OF_CHAIN):
            continue
        block = at(number)
        fat += [u32(block, 4 * i) for i in range(sector // 4)]

    def chain(start, table):
        seen = set()
        while start < len(table) and start not in seen:
            seen.add(start)
            yield start
            start = table[start]

    def regular(start):
        return b"".join(at(n) for n in chain(start, fat))

    directory = regular(u32(raw, 0x30))
    entries = []
    for offset in range(0, len(directory) - 127, 128):
        length = u16(directory, offset + 0x40)
        name = directory[offset:offset + max(length - 2, 0)].decode("utf-16-le", "replace")
        entries.append((name, directory[offset + 0x42], u32(directory, offset + 0x74),
                        u32(directory, offset + 0x78)))
    if not entries:
        raise NotReadable("no directory")
    root = entries[0]
    mini_stream = regular(root[2])
    mini_fat_raw = regular(u32(raw, 0x3C)) if u32(raw, 0x40) else b""
    mini_fat = [u32(mini_fat_raw, 4 * i) for i in range(len(mini_fat_raw) // 4)]
    streams = {}
    for name, kind, start, size in entries[1:]:
        if kind != 2:
            continue
        if size < cutoff:
            data = b"".join(mini_stream[n * mini:(n + 1) * mini] for n in chain(start, mini_fat))
        else:
            data = regular(start)
        streams[name] = data[:size]
    return streams


def sprms(grpprl):
    """Each property modifier of a list as (code, operand)."""
    out, j = [], 0
    while j + 2 <= len(grpprl):
        code = u16(grpprl, j)
        j += 2
        kind = code >> 13
        if kind in (0, 1):
            size = 1
        elif kind in (2, 4, 5):
            size = 2
        elif kind == 3:
            size = 4
        elif kind == 7:
            size = 3
        elif code == SPRM_TABLE_DEFINITION and j + 2 <= len(grpprl):
            size = 2 + u16(grpprl, j) - 1
        elif code == SPRM_CHANGE_TABS and j < len(grpprl) and grpprl[j] == 255:
            deleted = grpprl[j + 1] if j + 1 < len(grpprl) else 0
            added_at = j + 2 + deleted * 4
            added = grpprl[added_at] if added_at < len(grpprl) else 0
            size = 1 + 1 + deleted * 4 + 1 + added * 3
        elif j < len(grpprl):
            size = 1 + grpprl[j]
        else:
            break
        out.append((code, grpprl[j:j + size]))
        j += size
    return out


def numbering_of(grpprl):
    """The (override, level) a run of property modifiers sets, None where unset."""
    ilfo = ilvl = None
    for code, operand in sprms(grpprl):
        if code == SPRM_ILFO and len(operand) == 2:
            ilfo = struct.unpack("<h", operand)[0]
        elif code == SPRM_ILVL and len(operand) == 1:
            ilvl = operand[0]
    return ilfo, ilvl


class Level:
    """A list level as the Word 97-2003 file holds it: its start and how far it
    reaches in the table stream."""

    SIZE = 28

    @staticmethod
    def read(table, offset):
        start = struct.unpack_from("<i", table, offset)[0]
        chpx, papx = table[offset + 24], table[offset + 25]
        offset += Level.SIZE + papx + chpx
        offset += 2 + 2 * u16(table, offset)
        return start, offset


class WordFile:
    """The lists of a Word 97-2003 file and the paragraphs that use them."""

    def __init__(self, raw):
        streams = compound_streams(raw)
        word = streams.get("WordDocument")
        if word is None or len(word) < 0x200:
            raise NotReadable("no WordDocument stream")
        flags = u16(word, FIB_FLAGS)
        if u16(word, FIB_VERSION) < WORD97 or flags & ENCRYPTED:
            raise NotReadable("an older or encrypted Word file")
        table = streams.get("1Table" if flags & WHICH_TABLE else "0Table")
        if table is None:
            raise NotReadable("no table stream")
        self.word, self.table = word, table
        offset = FIB_BASE
        offset += 2 + 2 * u16(word, offset)
        self.text_length = u32(word, offset + 2 + 12)
        offset += 2 + 4 * u16(word, offset)
        self.fc_lcb = offset + 2
        if u16(word, offset) <= PLF_LFO:
            raise NotReadable("no list tables")
        self.lists = self.read_lists()
        self.overrides = self.read_overrides()
        self.styles = self.read_styles()
        self.paragraphs = self.read_paragraphs()

    def pair(self, index):
        return struct.unpack_from("<II", self.word, self.fc_lcb + 8 * index)

    def read_lists(self):
        """Each list's id and the start of each of its levels."""
        fc, lcb = self.pair(PLF_LST)
        if not lcb:
            return {}
        table = self.table
        count = struct.unpack_from("<h", table, fc)[0]
        heads = []
        for index in range(count):
            at = fc + 2 + index * 28
            heads.append((struct.unpack_from("<i", table, at)[0], table[at + 26] & 1))
        offset = fc + 2 + count * 28
        lists = {}
        for lsid, simple in heads:
            starts = []
            for _ in range(1 if simple else LEVELS):
                start, offset = Level.read(table, offset)
                starts.append(start)
            lists[lsid] = starts
        return lists

    def read_overrides(self):
        """Each override's list id and the levels it restarts, by its 1-based index."""
        fc, lcb = self.pair(PLF_LFO)
        if not lcb:
            return {}
        table = self.table
        count = struct.unpack_from("<i", table, fc)[0]
        heads = []
        for index in range(count):
            at = fc + 4 + index * 16
            heads.append((struct.unpack_from("<i", table, at)[0], table[at + 12]))
        offset = fc + 4 + count * 16
        overrides = {}
        for index, (lsid, levels) in enumerate(heads, 1):
            offset += 4
            restarts = {}
            for _ in range(levels):
                start, bits = struct.unpack_from("<iI", table, offset)
                offset += 8
                if bits & 0x10:
                    restarts[bits & 0xF] = start
                if bits & 0x20:
                    _, offset = Level.read(table, offset)
            overrides[index] = (lsid, restarts)
        return overrides

    def read_styles(self):
        """The (override, level) each paragraph style numbers with, by style index."""
        fc, lcb = self.pair(STSHF)
        if not lcb:
            return {}
        table = self.table
        header = u16(table, fc)
        count, base_size = u16(table, fc + 2), u16(table, fc + 4)
        offset = fc + 2 + header
        own, bases = {}, {}
        for istd in range(count):
            size = u16(table, offset)
            at, offset = offset + 2, offset + 2 + size
            if not size:
                continue
            kind, base = u16(table, at + 2) & 0xF, u16(table, at + 2) >> 4
            bases[istd] = base
            if kind != 1:
                continue
            name_at = at + base_size
            upx = name_at + 2 + 2 * u16(table, name_at) + 2
            upx_size = u16(table, upx)
            own[istd] = numbering_of(table[upx + 4:upx + 2 + upx_size])
        resolved = {}
        for istd in own:
            ilfo = ilvl = None
            seen, current = set(), istd
            while current in own and current not in seen:
                seen.add(current)
                ilfo = own[current][0] if ilfo is None else ilfo
                ilvl = own[current][1] if ilvl is None else ilvl
                current = bases.get(current)
            resolved[istd] = (ilfo, ilvl)
        return resolved

    def characters(self):
        """The main document's characters, each with where it sits in the stream."""
        fc, lcb = self.pair(CLX)
        table, word = self.table, self.word
        at = fc
        while at < fc + lcb and table[at] == 1:
            at += 3 + u16(table, at + 1)
        if at >= fc + lcb or table[at] != 2:
            raise NotReadable("no piece table")
        size = u32(table, at + 1)
        plc = at + 5
        pieces = (size - 4) // 12
        cps = struct.unpack_from("<%dI" % (pieces + 1), table, plc)
        for index in range(pieces):
            if cps[index] >= self.text_length:
                break
            where = u32(table, plc + (pieces + 1) * 4 + index * 8 + 2)
            compressed = bool(where & 0x40000000)
            where &= ~0x40000000
            length = min(cps[index + 1], self.text_length) - cps[index]
            for k in range(length):
                if compressed:
                    position = where // 2 + k
                    yield bytes(word[position:position + 1]).decode("cp1252", "replace"), position
                else:
                    position = where + 2 * k
                    yield word[position:position + 2].decode("utf-16-le", "replace"), position

    def property_runs(self):
        """(first, limit, style, grpprl) for each run of paragraph properties."""
        fc, lcb = self.pair(BTE_PAPX)
        count = (lcb - 4) // 8
        pages = struct.unpack_from("<%dI" % count, self.table, fc + (count + 1) * 4)
        runs = []
        for number in pages:
            page = self.word[number * 512:(number + 1) * 512]
            if len(page) < 512:
                continue
            crun = page[511]
            limits = struct.unpack_from("<%dI" % (crun + 1), page, 0)
            for index in range(crun):
                offset = page[(crun + 1) * 4 + index * 13] * 2
                style, grpprl = 0, b""
                if offset:
                    size = page[offset]
                    if size:
                        body, length = offset + 1, 2 * size - 1
                    else:
                        body, length = offset + 2, 2 * page[offset + 1]
                    style = u16(page, body)
                    grpprl = page[body + 2:body + length]
                runs.append((limits[index], limits[index + 1], style, grpprl))
        runs.sort()
        return runs

    def read_paragraphs(self):
        """Each main-document paragraph as (words, override, level)."""
        runs = self.property_runs()
        firsts = [run[0] for run in runs]
        paragraphs, text, fields = [], [], []
        for char, position in self.characters():
            if char == "\x13":
                fields.append(True)
            elif char == "\x14":
                if fields:
                    fields[-1] = False
            elif char == "\x15":
                if fields:
                    fields.pop()
            elif char in "\r\x07":
                index = bisect_right(firsts, position) - 1
                ilfo = ilvl = None
                if 0 <= index and position < runs[index][1]:
                    _, _, style, grpprl = runs[index]
                    ilfo, ilvl = numbering_of(grpprl)
                    from_style = self.styles.get(style, (None, None))
                    ilfo = from_style[0] if ilfo is None else ilfo
                    ilvl = from_style[1] if ilvl is None else ilvl
                if ilfo is not None and ilfo not in self.overrides:
                    ilfo = None
                paragraphs.append((key("".join(text)), ilfo, min(ilvl or 0, LEVELS - 1)))
                text = []
            elif not any(fields):
                text.append(char)
        return paragraphs


def bisect_right(values, value):
    low, high = 0, len(values)
    while low < high:
        middle = (low + high) // 2
        if value < values[middle]:
            high = middle
        else:
            low = middle + 1
    return low


def key(text):
    return " ".join(re.findall(r"\w+", text.lower()))


def keep_prefixes(raw: bytes) -> None:
    for _, (prefix, uri) in ET.iterparse(io.BytesIO(raw), events=("start-ns",)):
        try:
            ET.register_namespace(prefix, uri)
        except ValueError:
            pass


def val(element, name="val"):
    return None if element is None else element.get(W + name)


def body_paragraphs(parent):
    """Body paragraphs in order, tables included, without descending into a
    paragraph, where a text box's paragraphs sit."""
    for child in parent:
        if child.tag == W + "p":
            yield child
        elif child.tag != W + "sectPr":
            yield from body_paragraphs(child)


class Copy:
    """The docx copy: its paragraphs, numbering instances and definitions."""

    def __init__(self, document, numbering, styles):
        self.numbering = numbering
        self.abstracts = {val(a, "abstractNumId"): a for a in numbering.findall(W + "abstractNum")}
        self.nums = {val(n, "numId"): n for n in numbering.findall(W + "num")}
        style_numbers = {}
        for style in [] if styles is None else styles.findall(W + "style"):
            num_pr = style.find(W + "pPr/" + W + "numPr")
            if num_pr is not None:
                style_numbers[val(style, "styleId")] = (
                    val(num_pr.find(W + "numId")), val(num_pr.find(W + "ilvl")))
        body = document.find(W + "body")
        self.paragraphs = []
        self.elements = []
        for paragraph in [] if body is None else body_paragraphs(body):
            ppr = paragraph.find(W + "pPr")
            style = val(ppr.find(W + "pStyle")) if ppr is not None else None
            num_pr = ppr.find(W + "numPr") if ppr is not None else None
            num_id = val(num_pr.find(W + "numId")) if num_pr is not None else None
            if num_id is None and style in style_numbers:
                num_id = style_numbers[style][0]
            words = key("".join(t.text or "" for t in paragraph.iter(W + "t")))
            self.paragraphs.append((words, num_id if num_id in self.nums else None))
            self.elements.append(paragraph)
        # The paragraph straight above each one under the same parent.
        self.above = {}
        for parent in [] if body is None else body.iter():
            children = list(parent)
            for upper, lower in zip(children, children[1:]):
                if upper.tag == W + "p" and lower.tag == W + "p":
                    self.above[lower] = upper

    def abstract_of(self, num_id):
        return val(self.nums[num_id].find(W + "abstractNumId"))

    def level(self, abstract_id, ilvl):
        for lvl in self.abstracts[abstract_id].findall(W + "lvl"):
            if int(val(lvl, "ilvl") or 0) == ilvl:
                return lvl
        return None


def paired(source, target):
    """(Word file index, copy index) of each paragraph the two hold alike."""
    matcher = difflib.SequenceMatcher(
        None, [p[0] for p in source.paragraphs], [p[0] for p in target.paragraphs],
        autojunk=False)
    pairs = []
    for tag, i1, i2, j1, _ in matcher.get_opcodes():
        if tag == "equal":
            pairs += [(i1 + offset, j1 + offset) for offset in range(i2 - i1)]
    return pairs


def overrides_by_instance(source, target, pairs):
    """The override each docx instance stands for, where every paired paragraph
    agrees, and for each override the level and the instance of the first
    paragraph it numbers."""
    votes, first = {}, {}
    for i, j in pairs:
        _, ilfo, ilvl = source.paragraphs[i]
        num_id = target.paragraphs[j][1]
        if num_id is None or ilfo is None:
            continue
        votes.setdefault(num_id, set()).add(ilfo)
        first.setdefault(ilfo, (ilvl, num_id))
    found = {}
    for num_id, ilfos in votes.items():
        if len(ilfos) == 1:
            found[num_id] = ilfos.pop()
    return found, first


def drawing(lvl):
    """A level's definition with its start left out, for comparing two."""
    if lvl is None:
        return None
    lvl = copy.deepcopy(lvl)
    for start in lvl.findall(W + "start"):
        lvl.remove(start)
    return ET.tostring(lvl)


def set_start(lvl, start):
    element = lvl.find(W + "start")
    if element is None:
        element = ET.Element(W + "start")
        lvl.insert(0, element)
    element.set(W + "val", str(start))


def unlist_copies(source, target, pairs):
    """Takes out of its list each paragraph the copy gave the list of the
    deleted paragraph above it, where the Word file puts it in no list, and
    with it the run of deleted paragraphs that join it. Returns how many
    paragraphs left a list."""
    taken = 0
    for i, j in pairs:
        paragraph = target.elements[j]
        deleted = target.above.get(paragraph)
        if (source.paragraphs[i][1] is not None or deleted is None
                or not HIDDEN.mark_deleted(deleted)
                or not HIDDEN.copied_list(deleted, paragraph)):
            continue
        HIDDEN.take_out_of_list(paragraph)
        taken += 1
        while deleted is not None and HIDDEN.mark_deleted(deleted):
            if HIDDEN.numbering(deleted) is not None:
                HIDDEN.take_out_of_list(deleted)
                taken += 1
            deleted = target.above.get(deleted)
    return taken


def share_lists(source, target, pairs):
    """Points instances whose overrides name one list at one definition.
    Returns how many instances moved.

    The shared definition is a copy of the instance definition that defines
    the most levels, the first used among equals: LibreOffice can give part of
    an override's paragraphs a definition holding the first level alone, and a
    level override drawing the rest is one LibreOffice does not lay out."""
    found, first = overrides_by_instance(source, target, pairs)
    groups = {}
    for num_id, ilfo in found.items():
        groups.setdefault(source.overrides[ilfo][0], []).append(num_id)
    order = {}
    for index, (_, num_id) in enumerate(target.paragraphs):
        order.setdefault(num_id, index)
    moved = 0
    next_id = 1 + max([int(k) for k in target.abstracts if (k or "").isdigit()] or [0])
    for lsid, num_ids in groups.items():
        if len({target.abstract_of(n) for n in num_ids}) < 2 or lsid not in source.lists:
            continue
        num_ids.sort(key=lambda n: order.get(n, len(order)))
        starts = source.lists[lsid]
        fullest = max(num_ids, key=lambda n: len(
            target.abstracts[target.abstract_of(n)].findall(W + "lvl")))
        shared = copy.deepcopy(target.abstracts[target.abstract_of(fullest)])
        shared.set(W + "abstractNumId", str(next_id))
        for lvl in shared.findall(W + "lvl"):
            ilvl = int(val(lvl, "ilvl") or 0)
            if ilvl < len(starts):
                set_start(lvl, starts[ilvl])
        existing = target.numbering.findall(W + "abstractNum")
        target.numbering.insert(list(target.numbering).index(existing[-1]) + 1, shared)
        target.abstracts[str(next_id)] = shared
        for num_id in num_ids:
            own = target.abstract_of(num_id)
            ilfo = found[num_id]
            restarts = source.overrides[ilfo][1]
            num = target.nums[num_id]
            num.find(W + "abstractNumId").set(W + "val", str(next_id))
            overridden = {int(val(o, "ilvl") or 0) for o in num.findall(W + "lvlOverride")}
            ilvl_first, num_first = first.get(ilfo, (None, None))
            for ilvl in range(LEVELS):
                if ilvl in overridden:
                    continue
                lvl = target.level(own, ilvl)
                differs = lvl is not None and (
                    drawing(lvl) != drawing(target.level(str(next_id), ilvl)))
                restart = num_id == num_first and ilvl == ilvl_first and ilvl in restarts
                if not differs and not restart:
                    continue
                override = ET.SubElement(num, W + "lvlOverride")
                override.set(W + "ilvl", str(ilvl))
                if restart:
                    ET.SubElement(override, W + "startOverride").set(
                        W + "val", str(restarts[ilvl]))
                if differs:
                    lvl = copy.deepcopy(lvl)
                    if ilvl < len(starts):
                        set_start(lvl, starts[ilvl])
                    override.append(lvl)
            moved += 1
        next_id += 1
    return moved


def rewrite(source_path, target_path, out_path):
    with zipfile.ZipFile(target_path) as archive:
        infos = archive.infolist()
        parts = {info.filename: archive.read(info) for info in infos}
    try:
        with open(source_path, "rb") as handle:
            source = WordFile(handle.read())
    except (NotReadable, struct.error, IndexError, UnicodeDecodeError):
        shutil.copyfile(target_path, out_path)
        return
    if "word/document.xml" not in parts or "word/numbering.xml" not in parts:
        shutil.copyfile(target_path, out_path)
        return
    for name in ("word/document.xml", "word/numbering.xml", "word/styles.xml"):
        if name in parts:
            keep_prefixes(parts[name])
    document = ET.fromstring(parts["word/document.xml"])
    numbering = ET.fromstring(parts["word/numbering.xml"])
    styles = ET.fromstring(parts["word/styles.xml"]) if "word/styles.xml" in parts else None
    target = Copy(document, numbering, styles)
    pairs = paired(source, target)
    moved = share_lists(source, target, pairs)
    taken = unlist_copies(source, target, pairs)
    if not moved and not taken:
        shutil.copyfile(target_path, out_path)
        return
    if moved:
        parts["word/numbering.xml"] = ET.tostring(
            numbering, encoding="UTF-8", xml_declaration=True)
    if taken:
        parts["word/document.xml"] = ET.tostring(
            document, encoding="UTF-8", xml_declaration=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as out:
        for info in infos:
            out.writestr(info, parts[info.filename])


def main(argv):
    if len(argv) != 4:
        sys.stderr.write(__doc__)
        return 64
    try:
        rewrite(argv[1], argv[2], argv[3])
    except (zipfile.BadZipFile, ET.ParseError) as error:
        print(f"doc-lists: {argv[2]}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
