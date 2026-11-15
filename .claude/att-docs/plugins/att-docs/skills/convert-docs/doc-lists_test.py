#!/usr/bin/env python3
"""Cases for doc-lists.py: list overrides of one list keep counting it after the rewrite."""
from __future__ import annotations

import importlib.util
import os
import pathlib
import shutil
import struct
import subprocess
import tempfile
import unittest
import zipfile

HERE = pathlib.Path(__file__).resolve().parent


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DOC = load("doc_lists", "doc-lists.py")
LIST = load("list_numbers", "list-numbers.py")
CASES = load("list_numbers_test", "list-numbers_test.py")

SECTOR = 512
MINI = 64
CUTOFF = 4096
FREE, END, FAT_SECTOR = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD


def compound(streams):
    """A compound file holding each named stream, a short one in the mini
    stream as a writer puts it."""
    mini_data, mini_fat, named = b"", [], []
    chunks, chains = [], []

    def place(data):
        first = sum(len(c) // SECTOR for c in chunks)
        chunks.append(data.ljust(max(1, -(-len(data) // SECTOR)) * SECTOR, b"\0"))
        chains.append((first, len(chunks[-1]) // SECTOR))
        return first

    for name, data in streams.items():
        if len(data) < CUTOFF:
            first = len(mini_fat)
            count = max(1, -(-len(data) // MINI))
            mini_fat += list(range(first + 1, first + count)) + [END]
            mini_data += data.ljust(count * MINI, b"\0")
            named.append((name, first, len(data)))
        else:
            named.append((name, place(data), len(data)))
    mini_at = place(mini_data) if mini_data else END
    mini_fat_at = place(b"".join(struct.pack("<I", n) for n in mini_fat))

    def entry(name, kind, start, size, child=FREE, right=FREE):
        raw = name.encode("utf-16-le") + b"\0\0"
        return (raw.ljust(64, b"\0") + struct.pack("<HBB", len(raw), kind, 1)
                + struct.pack("<III", FREE, right, child) + b"\0" * 36
                + struct.pack("<II", start, size) + b"\0" * 4)

    directory = entry("Root Entry", 5, mini_at, len(mini_data), child=1)
    for index, (name, start, size) in enumerate(named, 1):
        directory += entry(name, 2, start, size,
                           right=index + 1 if index < len(named) else FREE)
    directory_at = place(directory)
    used = sum(len(c) // SECTOR for c in chunks)
    fat_sectors = -(-(used + 1) // (SECTOR // 4))
    fat = [FREE] * (used + fat_sectors)
    for start, count in chains:
        for n in range(start, start + count):
            fat[n] = n + 1 if n + 1 < start + count else END
    for n in range(used, used + fat_sectors):
        fat[n] = FAT_SECTOR
    fat_bytes = b"".join(struct.pack("<I", n) for n in fat).ljust(fat_sectors * SECTOR, b"\xff")
    difat = list(range(used, used + fat_sectors)) + [FREE] * (109 - fat_sectors)
    header = (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 16
              + struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6) + b"\0" * 6
              + struct.pack("<IIIIIIIII", 0, fat_sectors, directory_at, 0, CUTOFF,
                            mini_fat_at, -(-len(mini_fat) * 4 // SECTOR), END, 0)
              + b"".join(struct.pack("<I", n) for n in difat))
    return header.ljust(SECTOR, b"\0") + b"".join(chunks) + fat_bytes


def lvl(start):
    """A list level with no properties of its own and a one-character label."""
    return (struct.pack("<iBB", start, 0, 0) + b"\0" * 18 + bytes([0, 0, 0, 0])
            + struct.pack("<H", 2) + "\0.".encode("utf-16-le"))


def grpprl(ilfo, ilvl):
    out = b""
    if ilfo is not None:
        out += struct.pack("<Hh", DOC.SPRM_ILFO, ilfo)
    if ilvl is not None:
        out += struct.pack("<HB", DOC.SPRM_ILVL, ilvl)
    return out


def style_sheet(styles):
    """Paragraph styles, each (name, ilfo, ilvl), the first one the default."""
    stdf = 10
    out = struct.pack("<H", 18) + struct.pack("<HH", len(styles), stdf) + b"\0" * 14
    for index, (name, ilfo, ilvl) in enumerate(styles):
        upx = struct.pack("<H", index) + grpprl(ilfo, ilvl)
        body = (struct.pack("<HHHHH", index, 1 | (0xFFF << 4), 1 | (index << 4), 0, 0)
                + struct.pack("<H", len(name)) + name.encode("utf-16-le") + b"\0\0"
                + struct.pack("<H", len(upx)) + upx + (b"\0" if len(upx) % 2 else b""))
        out += struct.pack("<H", len(body)) + body
    return out


def word_file(paragraphs, lists, overrides, styles=(("Normal", None, None),)):
    """A Word 97-2003 file. paragraphs: (text, ilfo, ilvl) or (text, ilfo, ilvl,
    style); lists: {lsid: [start of each level]}; overrides: [(lsid, {level:
    restart})], numbered from 1 as ilfo."""
    text_at = 1024
    text = "".join(p[0] + "\r" for p in paragraphs)
    encoded = text.encode("utf-16-le")
    page_at = -(-(text_at + len(encoded)) // SECTOR) * SECTOR
    limits, position = [], text_at
    for p in paragraphs:
        limits.append(position)
        position += 2 * (len(p[0]) + 1)
    limits.append(position)
    page = bytearray(SECTOR)
    struct.pack_into("<%dI" % len(limits), page, 0, *limits)
    free = SECTOR - 1
    for index, p in enumerate(paragraphs):
        style = p[3] if len(p) > 3 else 0
        data = struct.pack("<H", style) + grpprl(p[1], p[2])
        if len(data) % 2:
            papx = bytes([(len(data) + 1) // 2]) + data
        else:
            papx = bytes([0, len(data) // 2]) + data
        free = (free - len(papx)) & ~1
        page[free:free + len(papx)] = papx
        page[len(limits) * 4 + index * 13] = free // 2
    page[511] = len(paragraphs)
    table = bytearray()

    def add(data):
        at = len(table)
        table.extend(data)
        return at, len(data)

    clx = add(b"\x02" + struct.pack("<I", 16) + struct.pack("<II", 0, len(text))
              + struct.pack("<HIH", 0, text_at, 0))
    bte = add(struct.pack("<III", limits[0], limits[-1], page_at // SECTOR))
    lst = struct.pack("<h", len(lists))
    levels = b""
    for lsid, starts in lists.items():
        lst += struct.pack("<iI", lsid, 0) + b"\xff\x0f" * 9 + bytes([0, 0])
        levels += b"".join(lvl(s) for s in starts)
    plf_lst = add(lst + levels)
    lfo = struct.pack("<i", len(overrides))
    data = b""
    for lsid, restarts in overrides:
        lfo += struct.pack("<iIIBBBB", lsid, 0, 0, len(restarts), 0, 0, 0)
        data += struct.pack("<I", FREE)
        for level, start in restarts.items():
            data += struct.pack("<iI", start, level | 0x10)
    plf_lfo = add(lfo + data)
    stsh = add(style_sheet(styles))
    fib = bytearray(1024)
    struct.pack_into("<HH", fib, 0, 0xA5EC, DOC.WORD97)
    struct.pack_into("<H", fib, DOC.FIB_FLAGS, DOC.WHICH_TABLE)
    struct.pack_into("<H", fib, 32, 14)
    struct.pack_into("<H", fib, 62, 22)
    struct.pack_into("<I", fib, 64 + 12, len(text))
    struct.pack_into("<H", fib, 152, 93)
    for index, (fc, lcb) in ((DOC.CLX, clx), (DOC.BTE_PAPX, bte), (DOC.PLF_LST, plf_lst),
                             (DOC.PLF_LFO, plf_lfo), (DOC.STSHF, stsh)):
        struct.pack_into("<II", fib, 154 + 8 * index, fc, lcb)
    word = bytes(fib) + encoded
    # Long enough to sit outside the mini stream, as a real document does.
    word = (word.ljust(page_at, b"\0") + bytes(page)).ljust(CUTOFF, b"\0")
    return compound({"WordDocument": word, "1Table": bytes(table)})


# Two levels: numbers, then roman numerals under them.
LEVELS = [CASES.level(0, left=720), CASES.level(1, fmt="lowerRoman", text="%2)", left=1350)]


class Rewriting(unittest.TestCase):
    def setUp(self):
        self.work = pathlib.Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.work)

    def numbers(self, paragraphs, lists, overrides, definitions, body, styles=None):
        """What Pandoc draws on each numbered paragraph once doc-lists.py and
        list-numbers.py have run over a docx copy of the Word 97-2003 file."""
        source = self.work / "in.doc"
        extra = {} if styles is None else {"styles": styles}
        source.write_bytes(word_file(paragraphs, lists, overrides, **extra))
        copied, shared, numbered = (self.work / n for n in ("in.docx", "s.docx", "n.docx"))
        CASES.docx(copied, body, definitions)
        self.assertEqual(DOC.main(["doc-lists.py", str(source), str(copied), str(shared)]), 0)
        self.assertEqual(LIST.main(["list-numbers.py", str(shared), str(numbered)]), 0)
        return [(t, n) for t, _, n in CASES.drawn(numbered) if n is not None]


class SharedListTest(Rewriting):
    # The Workload Mockups & Design shape: Word restarted the roman sub-list of
    # rule 2 by giving it a second override of the main list, and the rules
    # after it keep that override. LibreOffice's copy gives each override its
    # own definition, numbers 2 and 53.
    PARAGRAPHS = [("first rule", 1, 0), ("second rule", 1, 0), ("a dropdown", 2, 1),
                  ("the search button", 2, 1), ("third rule", 2, 0), ("fourth rule", 2, 0),
                  ("fifth rule", 1, 0), ("sixth rule", 2, 0)]
    LISTS = {0x697593: [1] * 9}
    OVERRIDES = [(0x697593, {}), (0x697593, {level: 1 for level in range(9)})]
    DEFINITIONS = [CASES.abstract(2, *LEVELS), CASES.abstract(53, *LEVELS),
                   CASES.num(2, 2), CASES.num(53, 53)]

    def body(self, paragraphs):
        ids = {1: 2, 2: 53}
        return [CASES.para(text, ids[ilfo], ilvl) for text, ilfo, ilvl in paragraphs]

    def test_the_shared_definition_draws_every_level_the_copy_defines(self):
        # Person Detail Mockups & Design: LibreOffice gives the first rule a
        # definition of the first level alone and the rest of the override a
        # full one, so the shared definition is the full one.
        paragraphs = [("rule", 1, 0), ("next rule", 1, 0), ("sub", 1, 1)]
        definitions = [CASES.abstract(2, LEVELS[0]), CASES.abstract(53, *LEVELS),
                       CASES.num(2, 2), CASES.num(53, 53)]
        body = [CASES.para("rule", 2, 0), CASES.para("next rule", 53, 0),
                CASES.para("sub", 53, 1)]
        source, copied, shared = (self.work / n for n in ("in.doc", "in.docx", "s.docx"))
        source.write_bytes(word_file(paragraphs, self.LISTS, self.OVERRIDES[:1]))
        CASES.docx(copied, body, definitions)
        self.assertEqual(DOC.main(["doc-lists.py", str(source), str(copied), str(shared)]), 0)
        with zipfile.ZipFile(shared) as archive:
            numbering = DOC.ET.fromstring(archive.read("word/numbering.xml"))
        W = DOC.W
        nums = {n.get(W + "numId"): n for n in numbering.iter(W + "num")}
        abstract_id = nums["2"].find(W + "abstractNumId").get(W + "val")
        self.assertEqual(nums["53"].find(W + "abstractNumId").get(W + "val"), abstract_id)
        abstract = next(a for a in numbering.iter(W + "abstractNum")
                        if a.get(W + "abstractNumId") == abstract_id)
        formats = [lvl.find(W + "numFmt").get(W + "val") for lvl in abstract.iter(W + "lvl")]
        self.assertEqual(formats, ["decimal", "lowerRoman"])
        self.assertEqual(list(numbering.iter(W + "lvlOverride")), [])

    def test_a_second_override_continues_the_list_it_overrides(self):
        self.assertEqual(
            self.numbers(self.PARAGRAPHS, self.LISTS, self.OVERRIDES, self.DEFINITIONS,
                         self.body(self.PARAGRAPHS)),
            [("first rule", 1), ("second rule", 2), ("a dropdown", 1),
             ("the search button", 2), ("third rule", 3), ("fourth rule", 4),
             ("fifth rule", 5), ("sixth rule", 6)])

    def test_the_copy_alone_restarts_the_second_override(self):
        copied, numbered = self.work / "in.docx", self.work / "n.docx"
        CASES.docx(copied, self.body(self.PARAGRAPHS), self.DEFINITIONS)
        self.assertEqual(LIST.main(["list-numbers.py", str(copied), str(numbered)]), 0)
        drawn = [n for _, _, n in CASES.drawn(numbered) if n is not None]
        self.assertEqual(drawn, [1, 2, 1, 2, 2, 3, 3, 4])

    def test_an_override_restarts_at_the_level_of_its_first_paragraph(self):
        paragraphs = [("one", 1, 0), ("two", 1, 0), ("again one", 2, 0), ("again two", 2, 0)]
        overrides = [(0x697593, {}), (0x697593, {0: 1})]
        self.assertEqual(
            self.numbers(paragraphs, self.LISTS, overrides, self.DEFINITIONS,
                         self.body(paragraphs)),
            [("one", 1), ("two", 2), ("again one", 1), ("again two", 2)])

    def test_a_restart_applies_once_when_the_copy_splits_an_override(self):
        # The copy can give one override's paragraphs two instances; Word still
        # restarts the override once, at its first paragraph.
        paragraphs = [("one", 2, 0), ("two", 2, 0), ("three", 2, 0)]
        overrides = [(0x697593, {}), (0x697593, {0: 1})]
        body = [CASES.para("one", 2, 0), CASES.para("two", 53, 0), CASES.para("three", 53, 0)]
        self.assertEqual(
            self.numbers(paragraphs, self.LISTS, overrides, self.DEFINITIONS, body),
            [("one", 1), ("two", 2), ("three", 3)])

    def test_the_list_start_wins_over_the_copy(self):
        definitions = [CASES.abstract(2, CASES.level(0, start=4)),
                       CASES.abstract(53, CASES.level(0, start=9)),
                       CASES.num(2, 2), CASES.num(53, 53)]
        paragraphs = [("one", 1, 0), ("two", 2, 0)]
        lists = {0x697593: [4] * 9}
        overrides = [(0x697593, {}), (0x697593, {1: 1})]
        self.assertEqual(
            self.numbers(paragraphs, lists, overrides, definitions, self.body(paragraphs)),
            [("one", 4), ("two", 5)])

    def test_style_numbering_counts_as_the_override(self):
        styles = (("Normal", None, None), ("Rule", 2, 0))
        paragraphs = [("first rule", 1, 0), ("styled rule", None, None, 1)]
        overrides = [(0x697593, {}), (0x697593, {1: 1})]
        body = [CASES.para("first rule", 2, 0), CASES.para("styled rule", 53, 0)]
        self.assertEqual(
            self.numbers(paragraphs, self.LISTS, overrides, self.DEFINITIONS, body, styles),
            [("first rule", 1), ("styled rule", 2)])

    def test_separate_lists_keep_their_own_counts(self):
        paragraphs = [("one", 1, 0), ("two", 1, 0), ("other one", 2, 0)]
        lists = {1: [1] * 9, 2: [1] * 9}
        overrides = [(1, {}), (2, {})]
        self.assertEqual(
            self.numbers(paragraphs, lists, overrides, self.DEFINITIONS, self.body(paragraphs)),
            [("one", 1), ("two", 2), ("other one", 1)])

    def test_a_source_it_cannot_read_leaves_the_copy_as_it_is(self):
        source, copied, out = (self.work / n for n in ("in.doc", "in.docx", "out.docx"))
        source.write_bytes(b"{\\rtf1 not a Word 97-2003 file}")
        CASES.docx(copied, self.body(self.PARAGRAPHS), self.DEFINITIONS)
        self.assertEqual(DOC.main(["doc-lists.py", str(source), str(copied), str(out)]), 0)
        self.assertEqual(copied.read_bytes(), out.read_bytes())

    def test_a_copy_that_is_not_a_zip_fails(self):
        source, copied = self.work / "in.doc", self.work / "in.docx"
        source.write_bytes(word_file(self.PARAGRAPHS, self.LISTS, self.OVERRIDES))
        copied.write_text("not a zip")
        self.assertEqual(
            DOC.main(["doc-lists.py", str(source), str(copied), str(self.work / "o")]), 1)


class ConvertRouteTest(Rewriting):
    """convert.sh's route for a Word 97-2003 file, with LibreOffice and Pandoc
    stood in for: the stand-ins write the file Pandoc was given."""

    def route(self, step):
        script = (HERE / "convert.sh").read_text()
        start = script.index("\nto_markdown() {")
        function = script[start:script.index("\n}\n", start) + 3]
        tools = self.work / "tools"
        tools.mkdir()
        (tools / "doc-lists.py").write_text(step)
        (self.work / "work" / "doc").mkdir(parents=True)
        source = self.work / "Events.doc"
        source.write_bytes(b"Word 97-2003")
        stand_ins = (
            'run_soffice() { printf copy > "$3/$(basename "${2%.*}").docx"; }\n'
            'run_pandoc() { printf \'%s\\n\' "$2" > "$3"; }\n')
        call = 'to_markdown "$1" "$2" && printf \'%s\\n\' "$NUMBERED"\n'
        runner = self.work / "route.sh"
        runner.write_text("set -uo pipefail\n" + stand_ins + function + call)
        result = subprocess.run(
            ["bash", str(runner), str(source), str(self.work / "body.md")],
            capture_output=True, text=True,
            env={"PATH": os.environ["PATH"], "HERE": str(tools), "WORK": str(self.work / "work")})
        self.assertEqual(result.returncode, 0, result.stderr)
        read = (self.work / "body.md").read_text().strip()
        return read, result.stdout.strip(), source

    def test_pandoc_reads_the_rebuilt_copy(self):
        read, numbered, _ = self.route(
            "import shutil, sys\nshutil.copyfile(sys.argv[2], sys.argv[3])\n")
        self.assertEqual(read, str(self.work / "work" / "doc-lists.docx"))
        self.assertEqual(numbered, read)

    def test_a_failed_step_leaves_pandoc_libreoffice_copy(self):
        read, numbered, source = self.route("import sys\nsys.exit(1)\n")
        self.assertEqual(read, str(self.work / "work" / "doc" / "Events.docx"))
        self.assertEqual(numbered, str(source))


if __name__ == "__main__":
    unittest.main()
