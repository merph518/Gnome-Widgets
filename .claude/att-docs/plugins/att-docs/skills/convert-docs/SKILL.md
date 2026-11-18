---
name: convert-docs
description: Convert a batch of source documents (Word, PDF, presentations, spreadsheets, HTML, text) into wiki-quality Markdown, one file per document, with a provenance block on every file recording where its revision date and version came from. Use when asked to convert, import, or re-convert specification documents, or whenever a new batch of source documents arrives.
---

# Convert Docs

Turns the documents in `<todo-root>` into Markdown under `<apps-root>`, one file
per document, each carrying a block that says where it came from and how its
dates were established.

The consuming repository's extension supplies the values below. Where it names
none, ask the user rather than guessing.

| Placeholder | Meaning |
| --- | --- |
| `<todo-root>` | Where a batch of source documents is dropped for conversion |
| `<apps-root>` | Where the converted Markdown lands |
| `<docs-root>` | The documentation tree both of them sit in |
| `<group>` | One folder per suite or application, under both roots |
| `<future-folder>` | The folder in a group that holds revisions not carried yet |
| `<library-file>` | The table of each source's place in the SharePoint library |
| `<sharepoint-host>` | The SharePoint host the library lives on |
| `<collisions-file>` | Sources downloaded under a longer name than the library's |
| `<config>` | The extension's `extension.json`, which every script here takes as `--config` |
| `<converter-script>` | The command that runs a batch: `convert.sh --config <config>` |
| `<stamp-script>` | The script that writes the cleanup, provenance block, and markers |
| `<pages-script>` | The script that finds where each page of the original starts |
| `<drop-images-filter>` | The Pandoc Lua filter for nodes Markdown cannot carry |
| `<flatten-tables-filter>` | The Pandoc Lua filter that keeps tables out of raw HTML |
| `<shift-check>` | The check for text in a font the conversion could not map |
| `<words-file>` | The word list the shift check reads |
| `<words-builder>` | The script that rebuilds the word list |
| `<stub-names>` | The file names a failed download leaves behind |

The scripts and the filters ship in this folder: `convert.sh`, `stamp.py`,
`pages.py`, `slides.py`, `doc_paths.py`, `hidden-text.py`, `doc-lists.py`, `list-numbers.py`,
`check-list-numbers.py`, `check-shifted-text.py`, `build-words.py`,
`check-doc-credentials.py`, `drop-images.lua`, `flatten-tables.lua`,
`list-markers.lua`, and the
config reader `convert_config.py`. A script that needs a root, a host, or a data
file reads it from `<config>`, given as `--config <file>`, and stops with exit 64
without one. A path in the file is relative to the git toplevel of the file's
folder. Its fields: `todoRoot` (`<todo-root>`), `appsRoot` (`<apps-root>`),
`futureFolder` (`<future-folder>`), `words` (`<words-file>`), `collisions`
(`<collisions-file>`), and `sharePointHost` (`<sharepoint-host>`). The data
files stay in the consuming repository. `stamp.py` takes the host as a
parameter too, `sharepoint_url(path, host)` and `sharepoint_line(name, path,
host)`, for a caller that writes the link line itself.

```bash
<converter-script>
```

That is the whole run for a normal batch. The rest of this file is what to do
when it is not normal.

`<converter-script>` walks the batch and routes each document by format. It
calls `<stamp-script>` for the cleanup, the provenance block, and the page
markers, which `<stamp-script>` gets from `<pages-script>`. Pandoc runs with
three Lua filters: `<drop-images-filter>` for the nodes Markdown cannot carry,
the placeholder each picture leaves, and the space a bookmark leaves at the
front of a paragraph,
`<flatten-tables-filter>` for the ones that would force a table into raw HTML,
and `list-markers.lua` for list labels Markdown cannot draw.

## What the batch looks like

`<todo-root>/<group>/` mirrors `<apps-root>/<group>/`, so a file in
`<todo-root>/<group>/` lands in `<apps-root>/<group>/`. The group folder is the
only thing that decides the destination; nothing is inferred from the file name.

A group folder's `<future-folder>` folder is a batch of its own:
`<todo-root>/<group>/<future-folder>/` lands in
`<apps-root>/<group>/<future-folder>/`. It holds a revision the system the
documents specify does not carry yet, which converts beside the version that
system follows rather than over it, per the `doc-watch` rule for a revision not
carried yet.

When `<todo-root>` is not ignored by git, a batch dropped there, and the `_done`
folder it moves into, shows up in `git status` as untracked. Stage the converted
Markdown by path and leave the sources out of the commit unless the batch is
meant to be tracked.

Before a run, look for an earlier conversion of the same document under
`<apps-root>`. A document that already lives in another group folder goes into
that folder's `<todo-root>/<group>/`, so the new conversion replaces the
existing file and the paths that cite it stay valid.

### Page names

No name under `<docs-root>` holds a space. A converted page takes its source's
name with the extension swapped for `.md` and each run of spaces, with any
hyphens touching it, written as one hyphen, so `Example 4.0 - Home Page.docx`
becomes `Example-4.0-Home-Page.md`. The page's H1 title keeps the library
name's spaces. `doc-watch` downloads each source under that hyphenated name and
records the library name in `<library-file>`, and the Source line names both:
`` `Example-4.0-Home-Page.docx`, named here without spaces, by way of
`Example 4.0 - Home Page.docx` ``.

A document whose conversion succeeded moves to `<todo-root>/_done/<group>/`,
which makes a second run pick up only what is left. Pass `--keep-sources` when
the sources are tracked and moving them would show up as a rename of every
file in the batch.

## One document, several files

A document held in more than one format is one document. `Spec.docx` and
`Spec.pdf` are the same specification, so they convert once, and the
provenance block names both.

The richest format carries the body. That order is measured rather than
assumed: a PDF can drop a whole column of a data dictionary table that the Word
copy carries, and give back almost nothing in return. Word first, then
presentations, then spreadsheets, then PDF, then plain text.

Every other format is still read, as a check on the one that won. When a
secondary format holds more than 5 per cent of its vocabulary that the body
does not, the two disagree by more than layout, and the group is held back:
both conversions go to `<todo-root>/_needs_merge/<group>/` and nothing is
written to `<apps-root>`. Read both, write the merged document by hand, and
delete the staged pair.

## The provenance block

Every file opens with its title as the only H1, then this:

```markdown
**Document provenance**

- Source: `Example - 5.0 - Home Page.doc`
- SharePoint: [Example - 5.0 - Home Page.doc](<sharepoint-host>/sites/...?web=1)
- Revised: 2017-07-11, from the revision history table
- Version: not stated
- Screen: 5.0, from the file name
- Pages: 9, as LibreOffice lays the document out
- Converted: 2026-08-20 14:05Z
```

`Converted` is the run date and time to the minute, in Zulu time (a trailing `Z`), and is the only
value here that is originated rather than found. A file converted before the
time was stamped holds the date alone. Everything else is quoted from somewhere, and says where.

### The SharePoint line

Each source with a known place in the SharePoint library gets a `SharePoint`
line under the `Source` lines, linking to that document on `<sharepoint-host>`.
The place comes from `<library-file>`, which the `doc-watch` placement step
writes as it moves each download into `<todo-root>`: the group, the file name,
and the server-relative library path. A source with no row, such as one dropped
into `<todo-root>` by hand, gets no line; add its row first when the link
matters. A file renamed off a shared library name (see `<collisions-file>`) is
looked up under either name.

A Word, Excel, or PowerPoint link ends in `?web=1`, which opens the document in
the browser rather than downloading it. A PDF opens in the browser anyway.

A converted file with no row gets its line from the `doc-watch` links scan,
which reads where every converted document sits in the library and writes the
line into each one.

A source held as an attachment in another system, rather than in the library,
gets no `SharePoint` line. Its `Source` line names the attachment instead, in
the `by way of` form: the system, the attachment and the record it is attached
to, then `` by way of `<file>` ``.

### The Pages line and the page markers

Every document with pages gets a `Pages` line, and a marker line in the body
where each page of the original starts:

```markdown
<a id="page-7"></a>*Page 7*
```

So `Example-5.0-Home-Page.md#page-7` lands on the text that opens page 7 of the
original. The pages come from the best layout available, and the `Pages` line
names which:

1. **one per slide shown in the deck**: a presentation's pages are its slides. Each slide opens on a heading in the Markdown, so every slide gets a marker, one with only a picture included, and the deck decides the pages even when the group also holds a PDF.
2. **from the PDF**: the group holds a PDF of the document, whose pages are the
   pages. When the library path of that PDF is known, each marker also links to
   that page of it, as `*[Page 7](https://...pdf#page=7)*`.
3. **as Word last laid the document out**: a `.docx` that Word saved carries a
   `w:lastRenderedPageBreak` wherever a page ended when Word last laid it out.
   Word leaves some pages unmarked, so this layout is used only when the page
   count Word stored in the file agrees with the marks. When they differ, the
   document goes to the next layout, and the `Pages` line says what Word marked
   and what its stored count says, as in `(Word's last layout marked 6, its stored
   count says 10)`.
4. **as LibreOffice lays the document out**: everything else LibreOffice can
   open, rendered to a PDF. A legacy `.doc` lands here, since the modern copy
   LibreOffice writes carries no Word layout. LibreOffice breaks lines a little
   differently from Word, so a page can start a line or two off. A blank
   paragraph LibreOffice gave a deleted list item's list is taken out of that
   list in the copy it lays out, as it is in the conversion, so a page that
   opens on a later item of the list carries the number the Markdown gives it.
   When LibreOffice cannot lay out a document whose Word marks and stored count
   differ, Word's layout is used and the `Pages` line names the difference.

A Word marker carries no link, because SharePoint opens those files in the browser, which takes no page number in the address. Neither does a deck's marker, unless the group holds a PDF of the deck with as many pages as the deck shows slides, and its library path is known: then each marker links to that page of the PDF.

A spreadsheet, an HTML page, and a text file have no pages and get neither the
line nor the markers.

`<pages-script>` finds the text each page opens with, after taking off the
running header, the footer, and the page number, and searches the converted
body for it, in order. A page whose full opening is not there is tried on
shorter pieces of its opening lines, between the pages found on either side,
and goes to the block holding the most of them, since a short piece can be a
table header the document repeats. Two blocks holding as many leave the page
unmarked.
A marker never splits a block: when a page opens partway through a paragraph, a
list, a table, or a code block, the marker goes in front of the whole block, and
in front of the list item an indented block belongs to. A page whose opening
text is not in the body at all, such as a page holding only a screenshot, gets
no marker, and the `Pages` line names it.

A deck's slides are found by their headings instead: each slide's marker goes in front of the next heading line, in order, whose text is that slide's heading, so slides sharing a title and untitled slides are marked too.

### The ladder

`Revised` is answered by the first of these that holds a date, and the label
names the rung so a reader can weigh it:

1. **The revision history table.** Its last dated row. A table whose rows the
   author never filled in is a fact about the document and is left visible in
   the output.
2. **A stated update line.** A line the document devotes to saying when it was
   last changed, wherever it sits, including in a Word header or footer.
   Pandoc discards those parts entirely, so this rung reads them out of the
   container directly.
3. **The file or folder name.** For `Version` only, and only on an explicit
   marker: `v1.2`, `Rev 3`, `Draft 2`.
4. **The file's embedded document properties.** `dcterms:modified`, or
   `ModDate` for a PDF.
5. **`not stated`.**

A file that only transports something written elsewhere is stamped with
`--origin`, and the block then names that origin ahead of the file:

```markdown
- Source: <system>, the record's title, description, and comment thread, by way of `<file>`
- Revised: 2026-08-18, from the last dated comment in the thread
```

A pasted comment thread from a record is the case this exists for. The comment
lines it carries, a name, a logon in angle brackets, a date, and the text, are
dated statements about the record, so with `--origin` given the ladder reads the
last of them for `Revised` ahead of the rungs below the revision table. The
rung is off without `--origin`, because a comment in a document that is its own
document dates the comment rather than the document.

Nothing else answers. In particular:

- **A number leading a file name is a screen, not a version.** In
  `<prefix> 4.1` or `<prefix> - 5.0`, the number identifies the screen the
  document specifies. It goes on its own `Screen` line, and `Version` stays
  honest.
- **`cp:revision` is not a version.** It counts how many times the file has
  been saved.
- **A Word date field is not a statement.** A footer built from `SAVEDATE`
  regenerates every time the file is opened and saved, so it says no more than
  the file system does. Dated headers built from a field are ignored; the
  literal ones are read.
- **A column name is not an update line.** A data dictionary can carry a column
  named for a last update date. A stated update line has to own its line, so a
  table row never answers.
- **The embedded title is not the title.** `dc:title` can be left over from
  whatever the file was saved from. Titles come from the file name.

## What the output may contain

Markdown, and nothing else. No images are extracted and no `_assets` folder is
written, so a link to a file that does not exist cannot be produced. Each
picture leaves a plain-text placeholder where it was: `[picture]` inside a line
of text, such as an icon quoted between quote marks, and `[Picture]` on a line
of its own, such as a screen print. The picture's alt text follows a colon when
the document gives one, apart from the description Word writes for itself.
The Markdown escapes the brackets, `\[picture\]`, so the placeholder reads as
text and never as a link. A picture with a caption keeps the caption under its
placeholder.

Every file that lands has to satisfy all of this:

- exactly one H1, which is the title
- a provenance block
- no `![`, no `<img`, no `<table`, no `<span`, no `<div`, no `_assets`
- no control characters and no byte order mark
- no em dash, neither the character nor the `---` that Pandoc writes for one
- no text in a font the conversion could not map, which is the one invariant
  the file itself cannot be read for

Check the HTML tags by name rather than by scanning for an angle bracket. These
documents write their own placeholders as `<First Name>` and quote XML payloads
verbatim, and both have to survive. The conversion writes three pieces of HTML
itself: the empty `<a id="page-N"></a>` anchor on each page marker line, the
`<br>` between the rows of a table nested inside a table cell, and the empty
comment `<!-- -->` between two digit lists a reader would otherwise count as
one.

Tables are pipe tables, because that is the only table syntax that renders
outside Pandoc. A grid table shows up in an ordinary Markdown viewer as one
run-together paragraph of pluses and pipes, and a writer that does not support
grid tables replaces the table with the text `[TABLE]`, losing the contents.

Four things in a Word table have no pipe equivalent, and all four are ordinary
in specification control tables: a cell holding a list, a cell holding a second
paragraph, a line break inside a cell, and a cell spanning rows or columns.
Any one of them makes the writer fall back to a raw `<table>`, so
`<flatten-tables-filter>` removes them first. Block content in a cell becomes
one line, with list items kept apart by a semicolon so the boundaries survive,
and a spanned cell is expanded into the individual cells it covered.

A table nested inside a cell is a fifth. It becomes lines of the outer cell
separated by `<br>`: whatever precedes it in the cell, such as the table's
title, then one line per inner row with its cells joined by `; ` in Word's
order, then whatever follows it. A cell Word merges down several rows is given
once, in the first row it spans, and an empty inner cell is left out.

## Routes

Pandoc cannot read the legacy Word format, any presentation format, or any
spreadsheet, so those go through LibreOffice first, or, for a presentation,
through the slide reader beside this skill.

| Input | Route |
|---|---|
| `docx` `docm` `odt` `rtf` | pandoc |
| `doc` `dot` | soffice to `docx`, then pandoc |
| `htm` `html` | pandoc, with divs and spans dropped at the reader |
| `pptx` `pptm` | the slide reader |
| `ppt` `odp` | soffice to `pptx`, then the slide reader |
| `xls` `xlsx` `xlsm` `ods` | soffice to one `csv` per sheet, then pandoc |
| `pdf` | `pdftotext -layout`, then a heading heuristic |
| `txt` `md` | copied |

A workbook exports one csv per sheet, named for the sheet, which is where the
sheet names in the output come from. An empty sheet is reported rather than
rendered as an empty table, and the padding around a sheet's used range is
trimmed before conversion.

A presentation is read straight from its slide XML by the slide reader, `slides.py`. Every shape with text is read, in the order the slide stacks them: title and body placeholders, free-standing text boxes and rectangles, shapes inside a group, and tables, which become pipe tables with a cell's paragraphs joined by `; `. Each slide opens with a heading, its title or `Slide N` when it has none, so a slide with only a picture still has its place. A title with no letter or digit stays on the slide as text under `Slide N`. An equation is read as its text. A deck saved as Strict Open XML is read the same way, and a deck that shows no slides fails. Hidden slides are left out, as they are from a PDF of the deck. A paragraph's level is its list depth, and its bullet or number comes from the paragraph, then from the shape, then from the slide layout and master, which is where a body placeholder's bullets come from. A lettered or roman list is written as bullets that open with the label the slide draws. Date, footer, and slide number placeholders, speaker notes, charts, and SmartArt are not read.

A PDF carries no heading structure, so the only signal left is layout: a short
line standing alone that does not read as a sentence becomes a heading, and
anything less certain stays a paragraph. Running headers and footers are
dropped by finding the lines that repeat on more than half the pages.

## List numbers

A rule written from a converted document cites the document's list numbers, so
a converted list has to count the way Word draws it. Pandoc's docx reader does
not always: it keeps one count per numbering instance where Word keeps one per
definition, it starts an item at 1 where Word counts the unused levels above it
as already used, and it nests by level where Word nests by indentation. Left
alone, a list restarts at 1 partway through and a sub-list lands at the margin.

Word never prints its hidden text, runs whose properties set `w:vanish`
directly, through their character or paragraph style, or through the document
defaults, and Pandoc writes it as any other text. `hidden-text.py` removes
those runs from every route that reads a `docx`, `doc` and `dot` included,
before `list-numbers.py` sees the file. A character style and a paragraph
style that both hide a run cancel each other, as Word treats the setting as a
toggle. A run holding a field code stays, since Word still reads a field whose
code is hidden. A paragraph whose mark is a tracked deletion joins the
paragraph after it, as it does in the document Word prints with its changes
accepted, so a deleted list item takes no number from the item after it.
LibreOffice's `docx` copy of a `.doc` file gives the paragraph after a deleted
mark the deleted paragraph's properties, list included, in place of its own.
When that paragraph is left with nothing Word prints, it is a blank line Word
draws with no number, so it comes out of the list rather than reaching the
Markdown as an empty item that pushes every number after it one up. A file it
cannot read goes on unchanged.

A `doc` or `dot` file numbers a list through overrides of it, and Word keeps one
count for the list however many overrides it has. The LibreOffice copy gives
each override a definition of its own, so a second override restarts the
count. `doc-lists.py` reads the list and override tables of the Word file and
points the copy's instances of one list at one shared definition, keeping an
override's restart only at its first paragraph and that paragraph's level, as
Word applies it. Where the copy gave a paragraph the list of the deleted
paragraph before it and the Word file puts that paragraph in no list, the step
takes it out of the list, so the paragraph Word joins from the two takes no
number even when it keeps text. A file it cannot read goes on unchanged, and
when the step fails Pandoc reads the LibreOffice copy as it stands. The page
markers are laid out from the rebuilt copy, so a page that opens on a
renumbered item still finds its opening line in the Markdown.

`list-numbers.py` sits in front of Pandoc on every route that reads a `docx`,
`doc` and `dot` included, and rewrites the numbering into a form Pandoc draws
the way Word does. Lists inside tables and numbered headings are left as they
are, with one exception: a heading whose own numbering, not its style's, puts
it in a list beside an ordinary item at the same level is drawn as one more
item, unless that list also numbers a heading standing alone or through its
style, and so numbers the document's sections. A level whose definition names
no start counts from 0, as Word counts it. A paragraph with no number stays in
the item above it when it starts at or past that item's text, and a hanging
indent starts it at its first line unless it opens with a tab, with spaces
typed ahead of its first words counted at about their width. The blank
paragraphs between the item and that paragraph stay in the item too, since a
blank paragraph left outside the list would end it and put the paragraph at
the margin. A paragraph that starts short of the item's text ends the item,
and numbering that names no list, as `w:numId` 0 does, comes off it there,
since Pandoc would read it as one more paragraph of the item. A file it cannot
read goes to Pandoc unchanged.

A paragraph with no number inside a list continues an item, and Pandoc joins it
to the last item it read. After a sub-list, that item is the sub-list's last
one, while Word may draw the paragraph back under the item the sub-list hangs
from. `list-numbers.py` reads where the paragraph starts, first-line indent
included, and gives it to the deepest item, from that one down to the
sub-list's last item, whose text starts at least as near as the text of the
item above it. Tab stops a paragraph sets itself count on both sides: a tab
ahead of the paragraph's first words carries them to the next stop, and an
item's text starts at a stop set between its number and its hanging indent. A
paragraph that leaves the sub-list this way reaches Pandoc as a one-item list
starting at 32768, past any start Word takes, and `list-markers.lua` writes
such a list as the paragraphs it holds, under the item and after the sub-list.

The column a list or a paragraph is drawn in also takes it out of the item
before it. A list of another definition is an item's sub-list when its number
is drawn at or past the text of the item's first line, a tab stop set between
the item's number and its hanging indent included. A deeper level of the
item's own list is its sub-list unless Word draws that level's number beside
the item or beside an item it is under, in the column of that item's number
and with the same kind of number: such a level is a run of items beside that
item, and it is written at that item's depth. A deeper level of bullets stays
a sub-list. A paragraph with no number that a blank paragraph sets off from
the last item read, and that starts at that item's text, is left out of the
item when it starts where the last paragraph ahead of the list did, no
heading, and no table outside every item, lies between the two, and no
paragraph after it, up to the next heading, is more of an open item's list:
numbered by its definition, or drawn beside it. Past a table only an item
of the definition and level of an open item inside another counts, since only
such an item takes the list up again. That paragraph
is the text of the body going on after a list whose numbers hang left of it. A table in an
item, and a note or table at the margin that the list takes back in when it
goes on, are part of the list, not of the body. After a sub-list of the item,
the paragraph goes to the item it starts nearest, as above.

Pandoc ends every list at a table, and at a paragraph that holds only a picture
or an empty run, so the items after one would land at the margin. A table is
inside the item above it when its indent sets it at or past that item's text
and the item's text is set in from the page margin; a table set in the middle
or at the right sits in the deepest such item. When the list goes on after the
table, with a paragraph or an item still inside an item left open,
`list-numbers.py` puts a run of empty items after the table, one at each level
of the items the table sits in, in a list starting at 65536. Pandoc nests what
follows the table in those, and `list-markers.lua` moves the table and what
they hold back into the items of the list before the table, so the table is
written inside its item and the items after it keep their depth and their
count. A paragraph with no text between two items of a list that goes on stays
in the item above it. A table followed by nothing of the list it is drawn in is
written after the list.

An item that counts on from the last item at its depth, under the same item
above, stays in that list when a paragraph or a table at the margin came
between the two, as a note set at the margin between two lettered items does.
What was read between them is written one level inside the item they are
under, between the two parts of the list. A list that starts its count again,
and any item after a heading, is placed by where it is drawn alone.

Markdown numbers an ordered list with digits only, so Pandoc writes a list Word
letters `a.`, `b.` or numbers `i.`, `ii.` as `1.`, `2.`, and a rule citing
item 2.a finds no such item. `list-markers.lua` runs last on every route and
turns each item of a letter or roman list outside a table into a bullet whose
text opens with Word's label, such as `- a\.` or `- (ii)`. What else the item
holds stays nested under that bullet, two letter or roman lists side by side
make one bullet list, and a list Word numbers with digits is left as a list.
A Markdown reader counts two digit lists in a row as one list, whatever digits
the second is written with, so a digit list that does not count on from the
digit list right before it has an empty comment, `<!-- -->`, on a line of its
own in front of it.

After a Word document is stamped, `check-list-numbers.py` compares each
numbered item at the margin of the Markdown with the label LibreOffice's text
export gives the same item in the source, or in the `doc-lists.py` copy for a
`doc` or `dot` file. A document whose numbers differ is
still written, and the run lists the items and counts the document under
`with list numbers off the source`. Correct those numbers in the Markdown
before rules are written from it. The check runs on its own too, against a
Word file or a text export of one:

```bash
python3 check-list-numbers.py <apps-root>/<group>/<page>.md SOURCE.doc
```

It exits 0 when every item agrees, 2 when one differs, and 1 when the source
cannot be read.

The check reads the source as the conversion does: a `.doc` or `.dot` file
through a `docx` copy, and without its hidden text or the paragraphs deleted
with their changes tracked, and with the blank paragraph LibreOffice gives a
deleted item's list taken out of it, so neither paragraph takes a number on
either side.

## Text in a font the conversion could not map

A PDF whose body text is set in a non-embedded font with a `Custom` encoding
and no ToUnicode map carries nothing that maps a glyph back to a character.
`pdftotext` emits the glyph codes themselves, which sit a fixed distance below
the characters they draw, and they read as text to every other check: the word
count is healthy, the provenance block is there, and there is no banned tag and
no em dash to catch. `KDVGHYHORSHG` is `has developed`.

`<shift-check>` is what notices. The codes for the letters land between `$`
and `]`, so shifted text holds no lowercase letter however long the run, and
the space encodes to a control character that is dropped, which leaves a whole
phrase as one unbroken token. A token in that range whose decoding segments
into English words is shifted text.

A document that trips it is held: the sources stay where they are, nothing is
written under `<apps-root>`, and the run counts it. Decoding it automatically
would be guesswork, because the distance between a code and the character it
draws belongs to the font rather than being a constant, and the spaces and the
punctuation are gone whichever way the file is read. Whoever supplied the batch
is the one to ask for a copy that carries its font.

`pdffonts` does not narrow a batch on its own: form field annotations use such
a font whether or not any body text does.

| Option | Effect |
|---|---|
| `--shift N` | the distance between a code and the character, 29 by default |
| `--all` | also show the short runs held back as too weak to report on |
| `--label NAME` | what to call the file in the report |

A short run is held back because four and five letter accidents are ordinary:
`FREE` decodes to `cobb` and `5817` to `RUNT`, and neither is a defect. A file
is reported for a run long enough to be certain about, and the short ones are
then listed with it.

The words the check reads are in `<words-file>`, which is the vocabulary of the
documents already converted kept to the words a system dictionary also knows.
`<words-builder>` rebuilds it from `<apps-root>` and needs a system dictionary
to do so; the committed list is what a run reads, so a rebuild is a commit.

## Files that are not documents

A download that failed leaves a stub behind explaining the failure. Converting
one produces a Markdown file that reads like a document and holds an error
message. These are recognized by name (`<stub-names>`) and by content, and are
counted as quarantined rather than converted.

When a run reports any, tell whoever supplied the batch which documents are
missing. The stub names them.

## Options

| Option | Effect |
|---|---|
| `--suite NAME` | one group folder rather than all of them; `<group>/<future-folder>` names a future folder alone |
| `--limit N` | stop after N documents |
| `--dry-run` | report the grouping and the routes, write nothing |
| `--keep-sources` | leave the sources in place instead of moving them to `_done` |
| `--origin TEXT` | `<stamp-script>` only: name where a transported document was written |
| `--converted STAMP` | override the run date and time in the block, `YYYY-MM-DD HH:MMZ` or a date alone |
| `--in DIR` `--out DIR` | move either end of the batch from `<todo-root>` and `<apps-root>` |

`--dry-run` first is worth the second it takes: it prints how the files grouped
and which format won each group, which is where a surprise shows up.

## After the merge

A converted batch changes the rules its test plans were written from. Once the
change carrying it merges, run the `doc-impact` review the extension names
over it.

## Before committing

Run the conversion, then sweep what already landed:

```bash
<shift-check> <apps-root>
```

The conversion runs the same check over each document as it produces it, so a
clean run of the batch and a clean sweep of the tree say the same thing; the
sweep is what finds a document converted before the check existed.

Then run the consuming repository's own text, acronym, wiki, and secret checks
over the output. The extension names them.
