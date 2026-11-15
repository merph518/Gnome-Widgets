#!/usr/bin/env python3
"""Reports a converted file whose top-level list numbers differ from its source.

A rule written from a converted document cites the document's list numbers,
so a list that restarts or drifts in the Markdown puts a wrong anchor into
every rule written from it. LibreOffice lays numbering out the way Word draws
it, so its text export of the source is the reference: each numbered item at
the left margin of the Markdown is found in that export by its opening words,
and its number is compared with the label the export gives it.

The export is taken from the source as the conversion reads it: a legacy
`.doc` or `.dot` file goes through LibreOffice's `docx` first, then
`hidden-text.py` takes out what Word does not print, hidden text and
paragraphs deleted with their changes tracked, and takes the blank paragraph
LibreOffice gives a deleted item's list out of that list. LibreOffice would
otherwise number a paragraph Word leaves out of the count, and report every
number after it as wrong.

An item the export does not hold, such as one whose opening words the
conversion changed, is counted and left alone, since there is nothing to
compare it with. A sub-item left at the margin is compared with its own label
read as a number, `ii` as 2, so it is reported only when that number differs.

Usage:
  check-list-numbers.py MARKDOWN SOURCE

SOURCE is the Word file the Markdown came from, or a text export of it
(`.txt`). Exits 0 when every item found agrees, 2 when one differs, 1 when the
source cannot be read, and 64 on a wrong call.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import tempfile
import zipfile
from importlib import util
from xml.etree import ElementTree

HERE = pathlib.Path(__file__).resolve().parent
_SPEC = util.spec_from_file_location("hidden_text", HERE / "hidden-text.py")
HIDDEN = util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(HIDDEN)

# The Word formats LibreOffice rewrites as `docx` before the source is read.
LEGACY = {".doc", ".dot"}

# A numbered item at the left margin. A number the source typed as text rather
# than drew arrives escaped, as `18\.`.
MD_ITEM = re.compile(r"^(\d{1,4})\\?[.)]\s+(\S.*)$")

# A labelled item in the export: any indent, then a number, a roman numeral or
# a letter, and the delimiter Word drew; or a level number such as `1.3`, which
# the Markdown can only draw as its last part.
EXPORT_ITEM = re.compile(
    r"^\s*\(?(?:(\d{1,4}(?:\.\d{1,4})+)\.?|(\d{1,4}|[a-z]{1,7})[.)])\s+(\S.*)$",
    re.IGNORECASE,
)

# How many characters of an item's opening text have to agree. Long enough that
# items opening alike ("The window will display") rarely collide, and short
# enough to fit in the first line the Markdown wraps at.
PREFIX = 48

# An item whose opening text is shorter than this, such as `1. Yes`, says too
# little to be found by its words.
SHORTEST = 8

ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}

PUNCTUATION = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-", "\u00a0": " ",
})


def normalize(text: str) -> str:
    text = text.translate(PUNCTUATION).replace("&nbsp;", " ")
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_`~\\]", "", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def roman(label: str) -> int | None:
    total = largest = 0
    for char in reversed(label):
        value = ROMAN.get(char)
        if value is None:
            return None
        total += -value if value < largest else value
        largest = max(largest, value)
    return total


def label_values(label: str) -> set[int]:
    """Every number a label can stand for: `c` is the third letter or 100, and
    `1.3` is 3."""
    label = label.lower().rsplit(".", 1)[-1]
    if label.isdigit():
        return {int(label)}
    values = set()
    if label == label[0] * len(label):
        # Word's letter lists run a to z, then aa to zz.
        values.add(ord(label[0]) - ord("a") + 1 + 26 * (len(label) - 1))
    if roman(label):
        values.add(roman(label))
    return values


def markdown_items(markdown: str):
    fenced = False
    for line_number, line in enumerate(markdown.splitlines(), 1):
        if line.startswith("```"):
            fenced = not fenced
            continue
        match = None if fenced else MD_ITEM.match(line)
        if match:
            yield line_number, int(match.group(1)), normalize(match.group(2))


def export_items(export: str):
    for line in export.splitlines():
        match = EXPORT_ITEM.match(line)
        if match:
            yield match.group(1) or match.group(2), normalize(match.group(3))


def libreoffice(source: pathlib.Path, target: str, extension: str,
                work: pathlib.Path) -> pathlib.Path:
    """The file LibreOffice writes from SOURCE in the TARGET filter, under WORK.

    LibreOffice hands a conversion to an instance already running on the same
    profile, which can be closing down and drop it, so the call runs on a
    profile of its own."""
    outdir = work / extension
    subprocess.run(
        ["soffice", f"-env:UserInstallation={(work / 'profile').as_uri()}", "--headless",
         "--convert-to", target, "--outdir", str(outdir), str(source)],
        capture_output=True, timeout=600, check=False,
    )
    written = outdir / f"{source.stem}.{extension}"
    if not written.is_file():
        raise OSError(f"LibreOffice wrote no {extension} copy of {source}")
    return written


def drop_deleted_text(path: pathlib.Path) -> None:
    """Removes the text deleted with its changes tracked, which Pandoc leaves out
    and LibreOffice's text export prints."""
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        parts = {info.filename: archive.read(info) for info in infos}
    deleted = (HIDDEN.W + "del", HIDDEN.W + "moveFrom")
    for name in HIDDEN.PARTS:
        if name not in parts:
            continue
        HIDDEN.keep_prefixes(parts[name])
        root = ElementTree.fromstring(parts[name])
        for parent in root.iter():
            # In run properties the same tags mark a deleted paragraph mark, not text.
            if parent.tag == HIDDEN.W + "rPr":
                continue
            for child in [child for child in parent if child.tag in deleted]:
                parent.remove(child)
        parts[name] = ElementTree.tostring(root, encoding="UTF-8", xml_declaration=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as out:
        for info in infos:
            out.writestr(info, parts[info.filename])


def as_printed(source: pathlib.Path, work: pathlib.Path) -> pathlib.Path:
    """SOURCE as the conversion reads it: modern format, nothing Word leaves unprinted.

    A file `hidden-text.py` cannot read goes on as it is, as it does in the conversion."""
    if source.suffix.lower() in LEGACY:
        source = libreoffice(source, "docx", "docx", work)
    visible = work / "visible" / source.name
    visible.parent.mkdir()
    try:
        HIDDEN.rewrite(source, visible)
        drop_deleted_text(visible)
    except (zipfile.BadZipFile, ElementTree.ParseError, KeyError):
        return source
    return visible


def text_export(source: pathlib.Path) -> str:
    # LibreOffice opens its UTF-8 export with a byte-order mark, which utf-8-sig drops.
    if source.suffix.lower() == ".txt":
        return source.read_text(encoding="utf-8-sig", errors="replace")
    with tempfile.TemporaryDirectory() as directory:
        work = pathlib.Path(directory)
        exported = libreoffice(as_printed(source, work), "txt:Text (encoded):UTF8", "txt", work)
        return exported.read_text(encoding="utf-8-sig", errors="replace")


def compare(markdown: str, export: str):
    """Returns the items that disagree, as (line, number, label, text), and the
    counts of items found and not found in the export."""
    entries = [(line_number, number, text[:PREFIX], text)
               for line_number, number, text in markdown_items(markdown)
               if len(text[:PREFIX]) >= SHORTEST]
    items = [(label, text[:PREFIX]) for label, text in export_items(export)]
    # Both sides hold the items in the source's order. An export item is a copy
    # of a Markdown item when it opens with the item's first line (cut to
    # PREFIX). The copies are the pairing, kept in that order, that pairs the
    # most items; among pairings of the same size, the one whose labels agree
    # most wins. An item whose opening repeats is so placed by the items around it.
    starts = {key[:SHORTEST] for _, _, key, _ in entries}
    pool = [item for item in items if item[1][:SHORTEST] in starts]
    rows, cols = len(entries), len(pool)
    pair = rows + 1  # one more pair outweighs any count of agreeing labels
    best = [[0] * (cols + 1) for _ in range(rows + 1)]

    def gain(i, j):
        return pair + (entries[i][1] in label_values(pool[j][0]))

    for i in range(rows - 1, -1, -1):
        row, below = best[i], best[i + 1]
        for j in range(cols - 1, -1, -1):
            score = max(below[j], row[j + 1])
            if pool[j][1].startswith(entries[i][2]):
                score = max(score, below[j + 1] + gain(i, j))
            row[j] = score
    differ = []
    unpaired = []
    found = i = j = 0
    while i < rows:
        line_number, number, key, text = entries[i]
        if (j < cols and pool[j][1].startswith(key)
                and best[i][j] == best[i + 1][j + 1] + gain(i, j)):
            found += 1
            if number not in label_values(pool[j][0]):
                differ.append((line_number, number, pool[j][0], text))
            i += 1
            j += 1
        elif j == cols or best[i][j] == best[i + 1][j]:
            unpaired.append(entries[i])
            i += 1
        else:
            j += 1
    # An item left out of the pairing, such as one the Markdown moved, counts as
    # found when some item opening alike carries its number. Otherwise its own
    # copy is not in the export as a labelled item (a table cell, for one).
    missing = 0
    for _, number, key, _ in unpaired:
        if any(item[1].startswith(key) and number in label_values(item[0]) for item in items):
            found += 1
        else:
            missing += 1
    return differ, found, missing


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        sys.stderr.write(__doc__)
        return 64
    markdown_path, source = pathlib.Path(argv[1]), pathlib.Path(argv[2])
    try:
        export = text_export(source)
        markdown = markdown_path.read_text(encoding="utf-8")
    except (OSError, subprocess.SubprocessError) as error:
        print(f"list numbers: {error}", file=sys.stderr)
        return 1
    differ, found, missing = compare(markdown, export)
    for line_number, number, label, text in differ:
        print(f"{markdown_path}:{line_number}: numbered {number}, "
              f"the source numbers it {label}: {text[:60]}")
    print(f"list numbers: {markdown_path.name}: {found} found, {len(differ)} differ, "
          f"{missing} not in the source")
    return 2 if differ else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
