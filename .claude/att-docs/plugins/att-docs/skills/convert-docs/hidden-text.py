#!/usr/bin/env python3
"""Removes what Word does not print from a Word file, so Pandoc never reads it.

Word's hidden text is a run whose run properties set `w:vanish`. Word does not
print it, and Pandoc's docx reader writes it as ordinary text. Help files keep
jump and bookmark names that way, glued to the visible label after them, and
templates leave a hidden paragraph such as `Exi` between tables.

A run is hidden when its own properties set `w:vanish` on, and shown when
they set it off. When they say nothing about it, the styles decide. Three
styles can speak for a run: the style of the table it sits in, its paragraph's
style, and its character style, each read through the styles it is based on. A
paragraph that names no style, or one the file does not hold, takes the
paragraph style marked as the default, and a table takes the default table style
the same way. A text box inside a table cell does not take the table's style.
The document defaults give the starting value, and since `w:vanish` is a toggle
property, each style that sets it the other way flips it: with the defaults off,
an odd number of styles turning it on hides the run, and with the defaults on,
an even number of styles turning it off does. The formatting a table style gives
its header row or banded rows is not read. `w:val` of `0`, `false` or `off`
turns it off. `w:specVanish` and `w:webHidden` are left alone.

A run that holds a field character or a field instruction stays even when
hidden, since Word still reads a field whose code is hidden.

A paragraph whose mark is a tracked deletion (`w:del` or `w:moveFrom` in the
mark's run properties) is not a paragraph of its own in the document Word
prints with its changes accepted, the view Pandoc's reader writes: what is left
of it joins the paragraph after it, which keeps its own properties. Pandoc
drops the deleted runs but keeps the paragraph, so a numbered one reaches the
Markdown as an empty list item and takes a number Word gives the next item. A
deleted mark with no paragraph straight after it, as at the end of a table
cell or before a table, is left alone.

LibreOffice's `docx` copy of a legacy `.doc` file gives the paragraph after a
deleted mark a copy of the deleted paragraph's properties, its list included,
and sets `w:widowControl` and `w:bidi w:val="0"` on it. Word draws the joined
paragraph with that paragraph's own properties, which the copy has replaced.
Left with nothing Word prints, the paragraph is a blank line between the
items, which Word draws with no number, while the copy makes it an empty item
that takes a number and pushes every item after it one up. So in a file
LibreOffice wrote, a paragraph carrying that copy and left empty is taken out
of the list (`w:numId` 0). One that keeps text keeps the copy here, since the
file no longer says what its own properties were; `doc-lists.py`, which reads
the `.doc` file itself, takes that one out of the list ahead of this step.
`pages.py` lays pages out from a copy with only that change made, so a page
that opens on a list item finds the number the Markdown gives it.

The body, the footnotes and the endnotes are rewritten. A paragraph left with
no visible text has nothing for Pandoc to write.

Usage:
  hidden-text.py IN OUT

Writes OUT and exits 0. Exits 1 when IN is not a zip archive or a part of it
is not well-formed XML.
"""
from __future__ import annotations

import copy
import io
import sys
import xml.etree.ElementTree as ET
import zipfile

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

PARTS = ("word/document.xml", "word/footnotes.xml", "word/endnotes.xml")
OFF = ("0", "false", "off")

# What Word prints in a paragraph besides its text.
SHOWN = {W + name for name in ("drawing", "pict", "object", "sym")}
# What a paragraph holds that Word does not print with its changes accepted.
UNSHOWN = {W + name for name in ("pPr", "del", "moveFrom")}


def keep_prefixes(raw: bytes) -> None:
    # ElementTree writes ns0:, ns1: for every prefix it was not told about.
    for _, (prefix, uri) in ET.iterparse(io.BytesIO(raw), events=("start-ns",)):
        try:
            ET.register_namespace(prefix, uri)
        except ValueError:
            pass


def vanish(rpr) -> bool | None:
    """On, off, or None when the properties do not say."""
    flag = None if rpr is None else rpr.find(W + "vanish")
    if flag is None:
        return None
    return (flag.get(W + "val") or "true").lower() not in OFF


def style_type(style) -> str:
    """The type a style is for; one that names none is a paragraph style."""
    return style.get(W + "type") or "paragraph"


class Styles:
    def __init__(self, root):
        self.by_id = {}
        # The style each type uses when none is named; the last one marked wins.
        self.defaults = {}
        for style in [] if root is None else root.findall(W + "style"):
            style_id = style.get(W + "styleId")
            if style_id is None:
                continue
            self.by_id[style_id] = style
            if (style.get(W + "default") or "").lower() not in ("",) + OFF:
                self.defaults[style_type(style)] = style_id
        defaults = None if root is None else root.find(f"{W}docDefaults/{W}rPrDefault/{W}rPr")
        self.default = bool(vanish(defaults))

    def applied(self, kind, style_id):
        """The style a paragraph or table of type KIND uses when it names STYLE_ID."""
        style = self.by_id.get(style_id)
        if style is not None and style_type(style) == kind:
            return style_id
        return self.defaults.get(kind)

    def run_hidden(self, char_style, para_style, table_style=None) -> bool:
        """What the styles and the defaults say for a run that says nothing itself."""
        hidden = self.default
        # A toggle property: each style level that sets it the other way flips it.
        for style in (table_style, para_style, char_style):
            found = self.hidden(style)
            if found is not None and found != self.default:
                hidden = not hidden
        return hidden

    def hidden(self, style_id) -> bool | None:
        seen = set()
        while style_id in self.by_id and style_id not in seen:
            seen.add(style_id)
            style = self.by_id[style_id]
            found = vanish(style.find(W + "rPr"))
            if found is not None:
                return found
            based = style.find(W + "basedOn")
            style_id = None if based is None else based.get(W + "val")
        return None


def style_of(properties, tag):
    element = None if properties is None else properties.find(W + tag)
    return None if element is None else element.get(W + "val")


def enclosing_table(paragraph, parents):
    """The table PARAGRAPH sits in, or None outside one or inside a text box."""
    element = parents.get(paragraph)
    while element is not None and element.tag not in (W + "tbl", W + "txbxContent"):
        element = parents.get(element)
    return element if element is not None and element.tag == W + "tbl" else None


def drop_hidden(root, styles: Styles) -> int:
    """Removes every hidden run under root and returns how many went."""
    parents = {child: parent for parent in root.iter() for child in parent}
    dropped = 0
    for run in list(root.iter(W + "r")):
        if run.find(W + "fldChar") is not None or run.find(W + "instrText") is not None:
            continue
        rpr = run.find(W + "rPr")
        hidden = vanish(rpr)
        if hidden is None:
            # The paragraph the run sits in, the nearest one when a text box
            # puts a paragraph inside another.
            paragraph = parents.get(run)
            while paragraph is not None and paragraph.tag != W + "p":
                paragraph = parents.get(paragraph)
            para_style = table_style = None
            if paragraph is not None:
                para_style = styles.applied("paragraph", style_of(
                    paragraph.find(W + "pPr"), "pStyle"))
                table = enclosing_table(paragraph, parents)
                if table is not None:
                    table_style = styles.applied("table", style_of(
                        table.find(W + "tblPr"), "tblStyle"))
            hidden = styles.run_hidden(style_of(rpr, "rStyle"), para_style, table_style)
        if hidden:
            parents[run].remove(run)
            dropped += 1
    return dropped


def mark_deleted(paragraph) -> bool:
    rpr = paragraph.find(f"{W}pPr/{W}rPr")
    return rpr is not None and (
        rpr.find(W + "del") is not None or rpr.find(W + "moveFrom") is not None)


def numbering(paragraph):
    """The list a paragraph's own properties put it in, as (numId, ilvl), or None."""
    num_pr = paragraph.find(f"{W}pPr/{W}numPr")
    if num_pr is None or style_of(num_pr, "numId") in (None, "0"):
        return None
    return style_of(num_pr, "numId"), style_of(num_pr, "ilvl")


def copied_list(deleted, following) -> bool:
    """Whether LibreOffice gave FOLLOWING the list of the DELETED paragraph before it."""
    ppr = following.find(W + "pPr")
    bidi = None if ppr is None else ppr.find(W + "bidi")
    return (bidi is not None and (bidi.get(W + "val") or "").lower() in OFF
            and ppr.find(W + "widowControl") is not None
            and numbering(following) is not None
            and numbering(following) == numbering(deleted))


def prints(element) -> bool:
    """Whether Word prints anything held under ELEMENT with its changes accepted."""
    for child in element:
        if child.tag in UNSHOWN:
            continue
        if child.tag in SHOWN or (child.tag == W + "t" and (child.text or "").strip()):
            return True
        if prints(child):
            return True
    return False


def copied_blanks(root) -> list:
    """The paragraphs LibreOffice gave a deleted paragraph's list that print nothing.

    Each follows a run of paragraphs whose marks are deleted, carries the copy
    of the last one's list, and neither it nor that run prints anything."""
    found = []
    for parent in root.iter():
        run = []
        for child in parent:
            if child.tag != W + "p":
                run = []
            elif mark_deleted(child):
                run.append(child)
            else:
                if (run and copied_list(run[-1], child)
                        and not any(prints(paragraph) for paragraph in run + [child])):
                    found.append(child)
                run = []
    return found


def take_out_of_list(paragraph) -> None:
    num_pr = paragraph.find(f"{W}pPr/{W}numPr")
    for child in list(num_pr):
        num_pr.remove(child)
    ET.SubElement(num_pr, W + "numId").set(W + "val", "0")


def join_deleted_marks(root) -> int:
    """Joins each paragraph whose mark is deleted to the one after it; returns how many."""
    joined = 0
    for parent in list(root.iter()):
        children = list(parent)
        for paragraph, following in zip(children, children[1:]):
            if paragraph.tag != W + "p" or following.tag != W + "p":
                continue
            if not mark_deleted(paragraph):
                continue
            content = [child for child in paragraph if child.tag != W + "pPr"]
            at = 1 if following.find(W + "pPr") is not None else 0
            for offset, child in enumerate(content):
                following.insert(at + offset, child)
            parent.remove(paragraph)
            joined += 1
    return joined


def written_by_libreoffice(parts) -> bool:
    """Whether the file's extended properties name LibreOffice as the application."""
    if "docProps/app.xml" not in parts:
        return False
    try:
        properties = ET.fromstring(parts["docProps/app.xml"])
    except ET.ParseError:
        return False
    application = next((element.text or "" for element in properties.iter()
                        if element.tag.rsplit("}", 1)[-1] == "Application"), "")
    return application.startswith("LibreOffice")


def read_parts(source):
    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        parts = {info.filename: archive.read(info) for info in infos}
    for name in PARTS + ("word/styles.xml",):
        if name in parts:
            keep_prefixes(parts[name])
    styles = Styles(ET.fromstring(parts["word/styles.xml"]) if "word/styles.xml" in parts else None)
    return infos, parts, styles


def write_parts(target, infos, parts) -> None:
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as out:
        for info in infos:
            out.writestr(info, parts[info.filename])


def rewrite(source, target) -> int:
    infos, parts, styles = read_parts(source)
    copies = written_by_libreoffice(parts)
    dropped = 0
    for name in PARTS:
        if name not in parts:
            continue
        root = ET.fromstring(parts[name])
        count = drop_hidden(root, styles)
        blanks = copied_blanks(root) if copies else []
        for paragraph in blanks:
            take_out_of_list(paragraph)
        count += len(blanks) + join_deleted_marks(root)
        if count:
            dropped += count
            parts[name] = ET.tostring(root, encoding="UTF-8", xml_declaration=True)
    write_parts(target, infos, parts)
    return dropped


def unlist_copied_blanks(source, target) -> int:
    """Writes SOURCE to TARGET with only the copied blanks taken out of their lists.

    Everything else stays, hidden text and deleted paragraphs included, so a
    layout of TARGET breaks its pages where one of SOURCE does while its list
    numbers are the ones the rewrite gives. Returns how many paragraphs left a
    list; TARGET is written either way."""
    infos, parts, styles = read_parts(source)
    taken = 0
    for name in PARTS if written_by_libreoffice(parts) else ():
        if name not in parts:
            continue
        root = ET.fromstring(parts[name])
        # Decided on a copy without its hidden runs, as the rewrite decides.
        visible = copy.deepcopy(root)
        original = dict(zip(visible.iter(), root.iter()))
        drop_hidden(visible, styles)
        blanks = [original[paragraph] for paragraph in copied_blanks(visible)]
        for paragraph in blanks:
            take_out_of_list(paragraph)
        if blanks:
            taken += len(blanks)
            parts[name] = ET.tostring(root, encoding="UTF-8", xml_declaration=True)
    write_parts(target, infos, parts)
    return taken


def main(argv):
    if len(argv) != 3:
        sys.stderr.write(__doc__)
        return 64
    try:
        rewrite(argv[1], argv[2])
    except (zipfile.BadZipFile, ET.ParseError, KeyError) as error:
        print(f"hidden-text: {argv[1]}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
