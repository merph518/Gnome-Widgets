#!/usr/bin/env python3
"""Writes the text of a PowerPoint deck as Markdown, read straight from its slide XML.

Usage: slides.py DECK OUT

A slide holds its text in shapes: title and body placeholders, and free-standing
text boxes and rectangles that belong to no placeholder at all. LibreOffice's HTML
export of a deck loses much of the text in the free shapes, so this reader takes
every shape with text itself, in the order the slide stacks them, groups and
tables included.

Each slide shown in the deck opens with a heading: its title, or `Slide N` when
it has none, so a slide with only a picture still has a place in the Markdown.
Hidden slides are left out, as they are left out of the deck's PDF, so heading N
is slide N of what the audience sees. The page step reads the same headings from
the deck to mark where each slide starts.

Paragraph levels become list nesting. A paragraph takes its bullet or number from
its own properties first, then from the shape's list style, then, for a
placeholder, from the matching placeholder on the slide layout and from the slide
master's text styles, which is where the bullets of an ordinary body placeholder
come from. A digit list is written with digits; a lettered or roman list is
written as bullets that open with the label the slide draws, so a rule can cite
"step b" and find it.

Speaker notes, charts, and SmartArt are not read.

Standard library only, like stamp.py beside it.
"""

from __future__ import annotations

import posixpath
import re
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


# A deck saved as Strict Open XML names the same elements under these namespaces.
STRICT = {
    "http://purl.oclc.org/ooxml/presentationml/main": P,
    "http://purl.oclc.org/ooxml/drawingml/main": A,
    "http://purl.oclc.org/ooxml/officeDocument/relationships": R,
    "http://purl.oclc.org/ooxml/officeDocument/math":
        "http://schemas.openxmlformats.org/officeDocument/2006/math",
}

# What reading a deck that is not a readable deck raises.
READ_ERRORS = (OSError, KeyError, ValueError, zipfile.BadZipFile, ET.ParseError)


def q(prefix: str, name: str) -> str:
    return "{%s}%s" % ({"p": P, "a": A, "r": R, "mc": MC, "pkg": PKG}[prefix], name)


# Placeholders that repeat on every slide and say nothing about it.
FURNITURE = {"dt", "ftr", "sldNum", "hdr"}
TITLES = {"title", "ctrTitle"}

# The scheme names of a:buAutoNum: what counts, and what follows the count.
SCHEME = re.compile(r"^(alphaLc|alphaUc|arabic|romanLc|romanUc)(.*)$")
SUFFIX = {"Period": "{}.", "ParenR": "{})", "ParenBoth": "({})", "Plain": "{}"}

ROMAN = [(1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
         (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]

# Text that would read as Markdown syntax at the start of a line.
# A line of only `=` or `-` under a line of text makes it a heading, and a line of
# dashes alone draws a rule.
LEADING_SYNTAX = re.compile(r"^(\s*)([#>+]|=+|-+|\d+[.)])(?=\s|$)")
INLINE_SYNTAX = re.compile(r"([\\`*\[\]<{~])")
LOOSE_UNDERSCORE = re.compile(r"(?<![A-Za-z0-9])_|_(?![A-Za-z0-9])")


@dataclass
class Bullet:
    """How a paragraph is drawn: plain, a bullet, or a number in a scheme."""

    kind: str  # "plain", "bullet", or "number"
    scheme: str = "arabicPeriod"
    start: int = 1


@dataclass
class Slide:
    heading: str
    blocks: list[str] = field(default_factory=list)


def roman(number: int) -> str:
    out = ""
    for value, letters in ROMAN:
        while number >= value:
            out += letters
            number -= value
    return out


def letters(number: int) -> str:
    out = ""
    while number > 0:
        number, rest = divmod(number - 1, 26)
        out = chr(ord("a") + rest) + out
    return out


def label(scheme: str, number: int) -> str:
    """The label a slide draws for item NUMBER of SCHEME, such as `b)` or `IV.`."""
    match = SCHEME.match(scheme)
    kind, suffix = (match.group(1), match.group(2)) if match else ("arabic", "Period")
    if kind == "arabic":
        text = str(number)
    elif kind.startswith("alpha"):
        text = letters(number)
    else:
        text = roman(number)
    if kind.endswith("Uc"):
        text = text.upper()
    return SUFFIX.get(suffix, "{}.").format(text)


def escape(text: str, leading: bool = True) -> str:
    """Slide text written so that Markdown reads it as text. LEADING escapes what
    would open a heading or a list, which a heading's own text cannot do."""
    text = INLINE_SYNTAX.sub(r"\\\1", text)
    text = LOOSE_UNDERSCORE.sub(r"\\_", text)
    match = LEADING_SYNTAX.match(text) if leading else None
    if match:
        mark = match.group(2)
        cut = match.start(2) + (len(mark) - 1 if mark[0].isdigit() else 0)
        text = text[:cut] + "\\" + text[cut:]
    return text


def branch(content: ET.Element) -> ET.Element | None:
    """The branch of an mc:AlternateContent to read: the fallback, unless only the
    first choice holds text, as an equation or a newer kind of shape can."""
    fallback = content.find(q("mc", "Fallback"))
    choice = content.find(q("mc", "Choice"))
    if fallback is not None and (choice is None or has_text(fallback)
                                 or not has_text(choice)):
        return fallback
    return choice


# An equation keeps its text in Office Math, under this element.
EQUATION = "{http://schemas.microsoft.com/office/drawing/2010/main}m"
MATH = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
MATH_TEXT = f"{MATH}t"


def has_text(element: ET.Element) -> bool:
    return any((t.text or "").strip() for t in element.iter()
               if t.tag in (q("a", "t"), MATH_TEXT))


def runs(parent: ET.Element) -> list[str]:
    pieces: list[str] = []
    for child in parent:
        if child.tag in (q("a", "r"), q("a", "fld")):
            pieces.append("".join(t.text or "" for t in child.iter(q("a", "t"))))
        elif child.tag == q("a", "br"):
            pieces.append("\n")
        elif child.tag == EQUATION:
            # Each m:oMath is one line of the equation.
            lines = list(child.iter(f"{MATH}oMath")) or [child]
            pieces.append(" ".join("".join(t.text or "" for t in line.iter(MATH_TEXT))
                                   for line in lines))
        elif child.tag == q("mc", "AlternateContent"):
            chosen = branch(child)
            if chosen is not None:
                pieces.extend(runs(chosen))
    return pieces


def paragraph_text(paragraph: ET.Element) -> list[str]:
    """The lines of one a:p, split where it breaks the line."""
    text = "".join(runs(paragraph)).replace("\x0b", "\n").replace("\t", " ")
    lines = [re.sub(r"[  ]+", " ", line).strip() for line in text.split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    while lines and not lines[0]:
        lines.pop(0)
    return lines


def bullet_in(props: ET.Element | None) -> Bullet | None:
    """The bullet a paragraph properties element sets, or None when it sets none."""
    if props is None:
        return None
    for child in props:
        if child.tag == q("a", "buNone"):
            return Bullet("plain")
        if child.tag in (q("a", "buChar"), q("a", "buBlip")):
            return Bullet("bullet")
        if child.tag == q("a", "buAutoNum"):
            return Bullet("number", child.get("type", "arabicPeriod"),
                          int(child.get("startAt", "1")))
    return None


def level_props(styles: ET.Element | None, level: int) -> ET.Element | None:
    if styles is None:
        return None
    return styles.find(q("a", f"lvl{level + 1}pPr"))


def placeholder(shape: ET.Element) -> ET.Element | None:
    return shape.find(f"{q('p', 'nvSpPr')}/{q('p', 'nvPr')}/{q('p', 'ph')}")


class Deck:
    def __init__(self, path: Path) -> None:
        with zipfile.ZipFile(path) as archive:
            self.files = {name: archive.read(name) for name in archive.namelist()
                          if name.endswith((".xml", ".rels"))}
        self.parts: dict[str, ET.Element] = {}

    def xml(self, name: str) -> ET.Element:
        if name not in self.parts:
            data = self.files[name]
            for strict, transitional in STRICT.items():
                data = data.replace(strict.encode(), transitional.encode())
            self.parts[name] = ET.fromstring(data)
        return self.parts[name]

    def related(self, part: str, kind: str | None = None) -> dict[str, str]:
        """The parts PART points at, by relationship id, or the ones of type KIND."""
        folder, name = posixpath.split(part)
        rels = posixpath.join(folder, "_rels", name + ".rels")
        if rels not in self.files:
            return {}
        out = {}
        for rel in self.xml(rels).iter(q("pkg", "Relationship")):
            if rel.get("TargetMode") == "External":
                continue
            if kind and not rel.get("Type", "").endswith("/" + kind):
                continue
            target = rel.get("Target", "")
            path = (target.lstrip("/") if target.startswith("/")
                    else posixpath.normpath(posixpath.join(folder, target)))
            out[rel.get("Id", "")] = path
        return out

    def slide_parts(self) -> list[str]:
        """The slides in the order the deck shows them, hidden ones left out."""
        presentation = "ppt/presentation.xml"
        targets = self.related(presentation)
        shown = []
        for slide_id in self.xml(presentation).iter(q("p", "sldId")):
            part = targets.get(slide_id.get(q("r", "id"), ""))
            if part and self.xml(part).get("show") not in ("0", "false"):
                shown.append(part)
        return shown

    def layout_of(self, slide: str) -> str | None:
        return next(iter(self.related(slide, "slideLayout").values()), None)

    def master_of(self, layout: str | None) -> str | None:
        if not layout:
            return None
        return next(iter(self.related(layout, "slideMaster").values()), None)


class Inherited:
    """Where a placeholder paragraph's bullet comes from when it sets none itself."""

    def __init__(self, deck: Deck, slide: str) -> None:
        self.layout = deck.layout_of(slide)
        self.master = deck.master_of(self.layout)
        self.deck = deck

    def _layout_styles(self, ph: ET.Element) -> ET.Element | None:
        if not self.layout:
            return None
        kind, idx = ph.get("type", "obj"), ph.get("idx")
        by_index = by_type = None
        for shape in self.deck.xml(self.layout).iter(q("p", "sp")):
            other = placeholder(shape)
            if other is None:
                continue
            styles = shape.find(f"{q('p', 'txBody')}/{q('a', 'lstStyle')}")
            if idx is not None and other.get("idx") == idx and by_index is None:
                by_index = styles
            if other.get("type", "obj") == kind and by_type is None:
                by_type = styles
        # PowerPoint matches a placeholder to the layout by index, then by type.
        return by_index if by_index is not None else by_type

    def bullet(self, ph: ET.Element, level: int) -> Bullet:
        found = bullet_in(level_props(self._layout_styles(ph), level))
        if found:
            return found
        if self.master:
            style = "titleStyle" if ph.get("type") in TITLES else "bodyStyle"
            styles = self.deck.xml(self.master).find(
                f"{q('p', 'txStyles')}/{q('p', style)}")
            found = bullet_in(level_props(styles, level))
            if found:
                return found
        return Bullet("plain")


def shapes_in(tree: ET.Element):
    """The shapes of a shape tree in stacking order, groups opened in place."""
    for child in tree:
        if child.tag == q("p", "grpSp"):
            yield from shapes_in(child)
        elif child.tag == q("mc", "AlternateContent"):
            chosen = branch(child)
            if chosen is not None:
                yield from shapes_in(chosen)
        elif child.tag in (q("p", "sp"), q("p", "graphicFrame")):
            yield child


def table_markdown(table: ET.Element) -> str:
    rows = []
    for row in table.findall(q("a", "tr")):
        cells = []
        for cell in row.findall(q("a", "tc")):
            if cell.get("hMerge") in ("1", "true") or cell.get("vMerge") in ("1", "true"):
                cells.append("")
                continue
            texts = [" ".join(paragraph_text(p)) for p in cell.iter(q("a", "p"))]
            text = "; ".join(t for t in texts if t)
            cells.append(escape(text, leading=False).replace("|", "\\|"))
        rows.append(cells)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    lines = [f"| {' | '.join(rows[0])} |", f"| {' | '.join(['----'] * width)} |"]
    lines += [f"| {' | '.join(row)} |" for row in rows[1:]]
    return "\n".join(lines)


def text_blocks(shape: ET.Element, inherited: Inherited) -> list[str]:
    """The Markdown blocks of one shape's text: paragraphs, and lists kept together."""
    body = shape.find(q("p", "txBody"))
    if body is None:
        return []
    ph = placeholder(shape)
    own = body.find(q("a", "lstStyle"))
    blocks: list[str] = []
    items: list[str] = []
    # The open list items, outermost first: (level, column their text starts at).
    open_items: list[tuple[int, int]] = []
    counters: dict[int, tuple[str, int]] = {}

    def close_list() -> None:
        if items:
            blocks.append("\n".join(items))
            items.clear()
        open_items.clear()

    for paragraph in body.findall(q("a", "p")):
        lines = paragraph_text(paragraph)
        if not lines:
            continue
        props = paragraph.find(q("a", "pPr"))
        level = int(props.get("lvl", "0")) if props is not None else 0
        bullet = (bullet_in(props) or bullet_in(level_props(own, level))
                  or (inherited.bullet(ph, level) if ph is not None else Bullet("plain")))
        for deeper in [lvl for lvl in counters if lvl > level]:
            del counters[deeper]

        if bullet.kind == "plain":
            counters.pop(level, None)
            close_list()
            blocks.append("\\\n".join(escape(line) for line in lines))
            continue

        if bullet.kind == "number":
            previous = counters.get(level)
            number = (previous[1] + 1 if previous and previous[0] == bullet.scheme
                      else bullet.start)
            counters[level] = (bullet.scheme, number)
            if bullet.scheme.startswith("arabic") and bullet.scheme.endswith("Period"):
                marker, lead = f"{number}.", ""
            else:
                marker, lead = "-", label(bullet.scheme, number) + " "
        else:
            counters.pop(level, None)
            marker, lead = "-", ""

        while open_items and open_items[-1][0] >= level:
            open_items.pop()
        indent = open_items[-1][1] if open_items else 0
        # An ordered list opening past 1 cannot interrupt the text of the item
        # above it, so a blank line sets it apart.
        if (indent and marker != "-" and number != 1
                and items and not items[-1].startswith(" " * indent)):
            items.append("")
        column = indent + len(marker) + 1
        open_items.append((level, column))
        lines = [lead + lines[0], *lines[1:]]
        text = ("\\\n" + " " * column).join(escape(line) for line in lines)
        items.append(f"{' ' * indent}{marker} {text}")
    close_list()
    return blocks


def heading_text(shape: ET.Element) -> str:
    body = shape.find(q("p", "txBody"))
    if body is None:
        return ""
    words = [" ".join(paragraph_text(p)) for p in body.findall(q("a", "p"))]
    return " ".join(word for word in words if word).strip()


def has_words(text: str) -> bool:
    return bool(re.search(r"[^\W_]", text))


def read(path: Path) -> list[Slide]:
    """Every slide the deck shows, with its heading and its Markdown blocks."""
    deck = Deck(path)
    slides = []
    for number, part in enumerate(deck.slide_parts(), start=1):
        root = deck.xml(part)
        tree = root.find(f"{q('p', 'cSld')}/{q('p', 'spTree')}")
        inherited = Inherited(deck, part)
        title = ""
        blocks: list[str] = []
        for shape in shapes_in(tree if tree is not None else root):
            if shape.tag == q("p", "graphicFrame"):
                table = shape.find(f".//{q('a', 'tbl')}")
                if table is not None:
                    rendered = table_markdown(table)
                    if rendered:
                        blocks.append(rendered)
                continue
            ph = placeholder(shape)
            kind = ph.get("type", "obj") if ph is not None else None
            if kind in FURNITURE:
                continue
            if kind in TITLES and not title:
                title = heading_text(shape)
                if has_words(title):
                    continue
                # A title with nothing a heading can be found by stays as text.
                title = ""
            blocks.extend(text_blocks(shape, inherited))
        heading = title or f"Slide {number}"
        slides.append(Slide(heading, blocks))
    return slides


def headings(path: Path) -> list[str]:
    """The heading of each slide the deck shows, in order."""
    return [slide.heading for slide in read(path)]


def heading_line(text: str) -> str:
    line = escape(text, leading=False)
    # A run of `#` closing a heading line is read as the heading's closing marks.
    return "# " + re.sub(r"(#+)$", lambda m: "\\" + m.group(1), line)


def render(found: list[Slide]) -> str:
    parts = ["\n\n".join([heading_line(slide.heading), *slide.blocks]) for slide in found]
    return "\n\n".join(parts) + "\n"


def markdown(path: Path) -> str:
    return render(read(path))


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: slides.py DECK OUT", file=sys.stderr)
        return 2
    try:
        found = read(Path(argv[1]))
    except READ_ERRORS as error:
        print(f"slides.py: {argv[1]}: {error}", file=sys.stderr)
        return 1
    if not found:
        print(f"slides.py: {argv[1]}: the deck shows no slides", file=sys.stderr)
        return 1
    text = render(found)
    Path(argv[2]).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
