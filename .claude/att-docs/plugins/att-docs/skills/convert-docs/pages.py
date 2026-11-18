#!/usr/bin/env python3
"""Finds where each page of a source document starts, and marks it in the Markdown.

A converted document loses its pagination, so a citation into it can name a heading
but not the page a reader would turn to in the original. This module recovers the
page boundaries from whichever layout is the most faithful one available, finds the
text that opens each page in the converted Markdown, and puts a marker line with an
HTML anchor in front of the block that holds it, so `Doc.md#page-7` lands on page 7.

The layouts, best first:

1. A PDF of the document. Its pages are the pages, so nothing is guessed.
2. Word's own last layout. Word writes a `w:lastRenderedPageBreak` element wherever a
   page ended the last time it laid the document out, and saves it with the file. Word
   leaves some pages unmarked, so the layout is used only when the page count Word
   stored in `docProps/app.xml` agrees with the marks. When the two differ, neither is
   trusted and the document goes to the LibreOffice layout, whose provenance line says
   what Word marked and what its stored count says.
3. LibreOffice's layout, from a PDF it renders. Its line breaking is close to Word's
   but not identical, so a page can start a line or two away from where Word starts
   it, and the provenance block says this was the layout used.

A deck is the exception: each slide shown is a page, and its Markdown opens every
slide with a heading, so the pages are read from the deck itself and each one is
found by its heading rather than by its opening text.

Standard library only, like stamp.py beside it.
"""

from __future__ import annotations

import html
import re
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from importlib import util
from pathlib import Path
from typing import Callable
from xml.etree import ElementTree as ET

# The Word file reader that knows which paragraphs the conversion numbers.
_SPEC = util.spec_from_file_location(
    "hidden_text", Path(__file__).resolve().parent / "hidden-text.py")
HIDDEN = util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(HIDDEN)

# The deck reader, whose slide headings are the page openings of a deck.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import slides as SLIDES  # noqa: E402

# Formats LibreOffice can lay out as pages. A spreadsheet has no pages a reader
# turns, and the HTML, text, and Markdown sources have none at all.
RENDERABLE = {".doc", ".dot", ".docx", ".docm", ".odt", ".rtf",
              ".ppt", ".pptx", ".pptm", ".odp"}
WORD = {".docx", ".docm"}
DECKS = {".pptx", ".pptm"}

# The marker line, which also serves as the pattern doc-impact reads to tell a
# marker from the document's own text.
MARKER = re.compile(r'^<a id="page-(\d+)"></a>\*.*\*$')

# How much of a page's opening text is matched, in normalized characters. Long
# enough that a phrase a document repeats (a field label, a running heading) does
# not match too early, short enough to fit inside the first paragraph of the page.
SNIPPET_CHARS = 48
SHORT_SNIPPET_CHARS = 24
# The shortest piece worth matching at all.
MIN_PIECE_CHARS = 12

# How many of a page's opening lines are tried, one at a time, when its first line
# is text the conversion did not keep, such as a label inside a screenshot.
OPENING_LINES = 8

# A page number standing alone, as a footer writes it: `3`, `Page 3`, `Page 3 of 12`,
# `- 3 -`.
PAGE_NUMBER = re.compile(r"^[-\s]*(page\s*)?\d+(\s*of\s*\d+)?[-\s]*$", re.IGNORECASE)

WORD_TOKEN = re.compile(
    r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>"
    r"|<w:lastRenderedPageBreak\s*/>"
    r"|<w:br\s[^>]*w:type=\"page\"[^>]*/>"
    r"|<w:tab\s*/>"
    r"|</w:p>"
)

# The text the conversion leaves where a picture was, as Pandoc writes it with its
# brackets escaped: `\[picture\]` in a line of text, `\[Picture\]` on a line of its
# own, either with alt text after a colon. Escaped characters in the alt text are
# part of it, and a long one can wrap over two lines but never across a blank one.
# The alt text ends at the first escaped bracket, since Pandoc writes a bracket in it
# the same way. It is at most ALT_TEXT_CHARS long, so an opener that never closes costs
# a bounded look ahead rather than a scan to the next blank line.
ALT_TEXT_CHARS = 1000
PLACEHOLDER = re.compile(
    r"\\\[[Pp]icture(?::(?:\\[^\]\n]|[^\]\\\n]|\n(?!\n)){0,%d}?)?\\\]" % ALT_TEXT_CHARS)

FENCE = re.compile(r"^\s*(```|~~~)")
HEADING = re.compile(r"^#{1,6}\s+(.*)$")


@dataclass
class Layout:
    """The pages of one document: how many, and the text each one after the first opens with."""

    pages: int
    starts: list[str]
    label: str
    from_pdf: Path | None = None
    # Each page after the first opens on a heading whose text is its start, so it
    # is found by the whole heading line rather than by a piece of its text.
    headings: bool = False
    # Set when Word's marks and the page count it stored disagree: the pages the marks
    # give, and the count in `docProps/app.xml`.
    marked: int | None = None
    stored: int | None = None


@dataclass
class Placed:
    """What marking a Markdown body produced."""

    markdown: str
    missed: list[int] = field(default_factory=list)


def normalize(text: str) -> str:
    """Lowercase letters and digits only, so wrapping, table pipes, and emphasis drop out."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def pdf_pages(path: Path) -> list[str]:
    """The text of each page of a PDF, in reading order, or none when pdftotext fails.

    Page markers are an extra, so a pdftotext that is missing or hangs costs the
    document its markers and nothing else.
    """
    try:
        out = subprocess.run(
            ["pdftotext", str(path), "-"],
            capture_output=True, text=True, timeout=300, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    pages = out.split("\f")
    # pdftotext ends the last page with a form feed too.
    if pages and not pages[-1].strip():
        pages.pop()
    return pages


def opening_lines(pages: list[str]) -> list[list[str]]:
    """Each page's lines with its running header, footer, and page number taken off.

    A line repeating on more than half the pages is furniture rather than text, which
    for a two-page document means a line on both. The PDF route in convert.sh leaves a
    two-page document's text alone, since it deletes what it calls furniture, but here
    the rule only decides which lines a page's opening is matched on.
    """
    split = [[line.strip() for line in page.split("\n") if line.strip()] for page in pages]
    furniture: set[str] = set()
    if len(pages) > 1:
        counts = Counter(line for lines in split for line in set(lines) if len(line) > 3)
        furniture = {line for line, count in counts.items() if count > len(pages) / 2}
    # A line with no letter or digit, such as a bullet glyph pdftotext puts on a line
    # of its own, has nothing to match on.
    return [
        [
            line for line in lines
            if line not in furniture and not PAGE_NUMBER.match(line) and normalize(line)
        ]
        for lines in split
    ]


def from_pdf(path: Path, label: str) -> Layout | None:
    pages = pdf_pages(path)
    if not pages:
        return None
    lines = opening_lines(pages)
    starts = ["\n".join(page_lines[:OPENING_LINES]) for page_lines in lines[1:]]
    return Layout(len(pages), starts, label, path)


def stored_pages(path: Path) -> int | None:
    """The page count Word wrote in `docProps/app.xml`, or None when it did not write one.

    Another application's count is that application's layout, not Word's, so only a
    file naming Word as its application has one.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            properties = ET.fromstring(archive.read("docProps/app.xml"))
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError):
        return None
    found = {element.tag.rsplit("}", 1)[-1]: (element.text or "").strip()
             for element in properties.iter()}
    if not found.get("Application", "").startswith("Microsoft Office Word"):
        return None
    count = found.get("Pages", "")
    return int(count) if count.isdigit() and int(count) >= 1 else None


def from_word(path: Path) -> Layout | None:
    """Word's last layout, read from the page breaks it saved in document.xml.

    None when the file carries no `w:lastRenderedPageBreak` at all, which is what a
    file saved by anything other than Word looks like. An explicit page break alone
    does not count: it says where the author forced a page, not where the others fell.
    The layout records the stored page count when it differs from the marks' count.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml").decode("utf-8", "replace")
    except (OSError, KeyError, zipfile.BadZipFile):
        return None
    if "lastRenderedPageBreak" not in xml:
        return None
    text: list[str] = []
    breaks: list[int] = []
    length = 0
    # Whether any letter or digit has come since the last break.
    worded = False
    first_word: int | None = None
    last_word = 0
    for match in WORD_TOKEN.finditer(xml):
        token = match.group(0)
        if match.group(1) is not None:
            piece = html.unescape(match.group(1))
        elif token.startswith("<w:tab"):
            piece = " "
        elif token == "</w:p>":
            piece = "\n"
        else:
            # Word writes a rendered break beside an explicit one, and both can fall
            # before any text of the new page, so breaks with only whitespace between
            # them are one page boundary.
            if not breaks or worded:
                breaks.append(length)
                worded = False
            continue
        if normalize(piece):
            worded = True
            if first_word is None:
                first_word = length
            last_word = length + len(piece)
        text.append(piece)
        length += len(piece)
    if first_word is None:
        return None
    body = "".join(text)
    # A break before the first word or after the last one opens no page.
    breaks = [at for at in breaks if first_word < at < last_word]
    starts = [body[at:at + 400].lstrip() for at in breaks]
    layout = Layout(len(starts) + 1, starts, "as Word last laid the document out")
    stored = stored_pages(path)
    if stored is not None and stored != layout.pages:
        layout.marked, layout.stored = layout.pages, stored
    return layout


def from_slides(path: Path) -> Layout | None:
    """One page per slide the deck shows, each opening on the slide's heading."""
    try:
        found = SLIDES.headings(path)
    except SLIDES.READ_ERRORS:
        return None
    if not found:
        return None
    return Layout(len(found), found[1:], "one per slide shown in the deck", headings=True)


def render(path: Path, workdir: Path) -> Path | None:
    """A PDF of the document as LibreOffice lays it out, or None when soffice fails."""
    try:
        subprocess.run(
            ["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(workdir),
             str(path)],
            capture_output=True, timeout=600, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    pdf = workdir / f"{path.stem}.pdf"
    return pdf if pdf.is_file() else None


def as_listed(path: Path, workdir: Path) -> Path:
    """The file LibreOffice lays out in place of PATH, numbered as the Markdown is.

    In a `docx` copy LibreOffice wrote, a blank paragraph can carry a deleted list
    item's list, which LibreOffice numbers and the conversion does not, so every
    page opening on a later item of that list would carry a number the Markdown
    lacks. The copy takes those paragraphs out of their lists and changes nothing
    else. PATH itself is laid out when there are none, or when it cannot be read.
    """
    if path.suffix.lower() not in WORD:
        return path
    listed = workdir / "listed" / path.name
    listed.parent.mkdir(parents=True, exist_ok=True)
    try:
        taken = HIDDEN.unlist_copied_blanks(path, listed)
    except (zipfile.BadZipFile, ET.ParseError, KeyError, OSError):
        return path
    return listed if taken else path


def layout_of(path: Path, renderable: Path | None = None) -> Layout | None:
    """The best layout available for a document, or None when it has no pages.

    `path` is the file pages are counted from. `renderable` is a file LibreOffice can
    open in its place, such as the modern copy a legacy Word file was converted to,
    which is what Word's layout is looked for in too. A Word layout whose marks
    disagree with the page count Word stored gives way to LibreOffice's, and stands
    in only when that cannot be had.
    """
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return from_pdf(path, "from the PDF")
    candidate = renderable or path
    if candidate.suffix.lower() in DECKS:
        slides = from_slides(candidate)
        if slides:
            return slides
    word = from_word(candidate) if candidate.suffix.lower() in WORD else None
    if word and word.stored is None:
        return word
    if suffix not in RENDERABLE:
        return word
    with tempfile.TemporaryDirectory() as workdir:
        pdf = render(as_listed(candidate, Path(workdir)), Path(workdir))
        found = from_pdf(pdf, "as LibreOffice lays the document out") if pdf else None
    if not found:
        # Word's pages are likelier right than none, and the line says they are doubtful.
        return word
    found.from_pdf = None
    if word:
        found.marked, found.stored = word.marked, word.stored
    return found


def fence_state(lines: list[str]) -> list[int | None]:
    """For each line, the index of the fence that opened the code block it sits in."""
    state: list[int | None] = []
    opened: int | None = None
    for index, line in enumerate(lines):
        if FENCE.match(line):
            if opened is None:
                opened = index
                state.append(index)
                continue
            state.append(opened)
            opened = None
            continue
        state.append(opened)
    return state


def without_placeholders(lines: list[str], fences: list[int | None]) -> list[str]:
    """The lines with each picture placeholder taken out, so the text matches the source's.

    The source's page text has nothing where a picture sat, so a placeholder would stop
    a page from being found when it falls inside the opening. The result has as many
    lines as the input, each placeholder leaving behind the line breaks it held, so a
    position in it still names the line it came from. A placeholder in a code block
    is the block's own text and stays.
    """
    text = "\n".join(lines)
    out: list[str] = []
    # `copied` is how far the text has been copied to `out`, `counted` how far its
    # line breaks have been counted, and `line` the line `counted` is on.
    copied = counted = line = 0
    for hit in PLACEHOLDER.finditer(text):
        line += text.count("\n", counted, hit.start())
        counted = hit.start()
        if fences[line] is not None:
            continue
        out.append(text[copied:hit.start()])
        out.append("\n" * hit.group(0).count("\n"))
        copied = hit.end()
    out.append(text[copied:])
    return "".join(out).split("\n")


def block_start(lines: list[str], index: int, fences: list[int | None]) -> int:
    """The first line of the block holding `index`, so a marker never splits one.

    A marker inside a table row, a list, a paragraph, or a code block would cut it in
    two, so the marker goes in front of the whole block instead. An indented block
    belongs to the list item above it, and a line at the margin between the two ends
    the list, so the marker goes in front of that item.
    """
    while True:
        if fences[index] is not None:
            index = fences[index]
        while index > 0 and lines[index - 1].strip() and fences[index - 1] is None:
            index -= 1
        if index == 0 or not lines[index][:1].isspace():
            return index
        index -= 1
        while index > 0 and not lines[index].strip():
            index -= 1


def marker(page: int, link: str | None) -> str:
    label = f"[Page {page}]({link}#page={page})" if link else f"Page {page}"
    return f'<a id="page-{page}"></a>*{label}*'


def place(markdown: str, layout: Layout, link: str | None = None) -> Placed:
    """Insert one marker per page into a Markdown body.

    Each page's full opening is searched for after the place the previous page's was
    found, so pages land in order. A page whose full opening is not there is tried
    on shorter pieces, between the pages found on either side of it, and goes to the
    block holding the most of them. A page with no piece there, or with two blocks
    holding as many, is left unmarked and reported, rather than guessed at. The text
    searched leaves out the placeholders that stand for pictures, since the page text
    of the source has none.
    """
    lines = markdown.split("\n")
    if layout.headings:
        return place_on_headings(lines, layout, link)
    fences = fence_state(lines)
    flat: list[str] = []
    origin: list[int] = []
    for number, line in enumerate(without_placeholders(lines, fences)):
        for ch in normalize(line):
            flat.append(ch)
            origin.append(number)
    haystack = "".join(flat)

    found: dict[int, int] = {}
    cursor = 0
    for page, start in enumerate(layout.starts, start=2):
        piece = normalize(start)[:SNIPPET_CHARS]
        at = haystack.find(piece, cursor) if len(piece) >= MIN_PIECE_CHARS else -1
        if at >= 0:
            found[page] = at
            cursor = at + 1
    for page, start in enumerate(layout.starts, start=2):
        if page in found:
            continue
        low = max((at + 1 for p, at in found.items() if p < page), default=0)
        high = min((at for p, at in found.items() if p > page), default=len(haystack))
        at = locate(
            haystack[low:high], start,
            lambda offset, low=low: block_start(lines, origin[low + offset], fences),
        )
        if at is not None:
            found[page] = low + at

    before: dict[int, list[int]] = {}
    for page, at in sorted(found.items()):
        before.setdefault(block_start(lines, origin[at], fences), []).append(page)
    missed = [page for page in range(2, layout.pages + 1) if page not in found]

    first = next((i for i, line in enumerate(lines) if line.strip()), 0)
    before.setdefault(first, []).insert(0, 1)
    return Placed(write_markers(lines, before, link), missed)


def place_on_headings(lines: list[str], layout: Layout, link: str | None) -> Placed:
    """Marks each page at the next heading line whose text is the page's start.

    Slides can share a title, and an untitled slide's heading can be as short as
    `Slide 7`, so neither a piece of text nor a minimum length would find them.
    Taking the headings in order, and only whole heading lines, does: the body of a
    slide never holds a heading of its own.
    """
    fences = fence_state(lines)
    first = next((i for i, line in enumerate(lines) if line.strip()), 0)
    before: dict[int, list[int]] = {first: [1]}
    missed: list[int] = []
    cursor = first + 1
    for page, start in enumerate(layout.starts, start=2):
        target = normalize(start)
        for index in range(cursor, len(lines)):
            match = HEADING.match(lines[index])
            if match and fences[index] is None and normalize(match.group(1)) == target:
                before.setdefault(index, []).append(page)
                cursor = index + 1
                break
        else:
            missed.append(page)
    return Placed(write_markers(lines, before, link), missed)


def write_markers(lines: list[str], before: dict[int, list[int]], link: str | None) -> str:
    """The lines with each page's marker in front of the line it opens on."""
    out: list[str] = []
    for index, line in enumerate(lines):
        for page in before.get(index, []):
            if out and out[-1].strip():
                out.append("")
            out.append(marker(page, link))
            out.append("")
        out.append(line)
    return "\n".join(out)


def locate(window: str, start: str, block_at: Callable[[int], int]) -> int | None:
    """Where a page's opening sits in a stretch of the normalized body, on a short piece.

    A page that opens on text the conversion reshaped, a table whose columns came out
    in another order, say, often still matches on a shorter piece, and failing that
    on the openings of its next lines. A short piece can be text the document repeats,
    such as a table's header row, so each block the pieces land in is scored by how
    many of them it holds, and the block holding the most wins. A tie for the most
    names no block. `block_at` gives the block an offset in the stretch is in.
    """
    text = normalize(start)
    attempts = [text[:SHORT_SNIPPET_CHARS]]
    later = [normalize(line) for line in start.split("\n")[1:OPENING_LINES]]
    attempts += [line[:SNIPPET_CHARS] for line in later]
    first: dict[int, int] = {}
    score: Counter[int] = Counter()
    for attempt in set(attempts):
        if len(attempt) < MIN_PIECE_CHARS:
            continue
        blocks: set[int] = set()
        at = window.find(attempt)
        while at >= 0:
            block = block_at(at)
            blocks.add(block)
            first[block] = min(first.get(block, at), at)
            at = window.find(attempt, at + 1)
        score.update(blocks)
    ranked = score.most_common(2)
    if not ranked or (len(ranked) > 1 and ranked[0][1] == ranked[1][1]):
        return None
    return first[ranked[0][0]]
