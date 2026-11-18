#!/usr/bin/env python3
"""Cases for flatten-tables.lua: a Word table nested inside a table cell."""
from __future__ import annotations

import importlib.util
import pathlib
import shutil
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
FILTERS = [HERE / "drop-images.lua", HERE / "flatten-tables.lua", HERE / "list-markers.lua"]

# The Word file builders the list-numbers cases already use.
SPEC = importlib.util.spec_from_file_location("list_numbers_test", HERE / "list-numbers_test.py")
WORD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORD)


def cell(*paragraphs, merge=None):
    """A table cell; merge is "restart" or "continue" for a cell Word merges down rows."""
    props = "" if merge is None else f'<w:tcPr><w:vMerge w:val="{merge}"/></w:tcPr>'
    return f'<w:tc>{props}{"".join(paragraphs)}</w:tc>'


def merged():
    """The cell under a merge, which Word stores empty."""
    return cell(WORD.para(""), merge="continue")


def table(*rows):
    """A table; Pandoc takes its column count from the grid."""
    grid = '<w:gridCol w:w="2000"/>' * len(rows[0])
    body = "".join(f'<w:tr>{"".join(cells)}</w:tr>' for cells in rows)
    return f"<w:tbl><w:tblGrid>{grid}</w:tblGrid>{body}</w:tbl>"


def texts(*values):
    return [cell(WORD.para(value)) for value in values]


# The shape of the approver tables in the save approval documents: a one-column
# outer table whose cell holds the table's title and then the table itself.
APPROVERS = table(
    texts("If the submitter is:", "Approver 1 will be:", "Approver 2 will be:"),
    [cell(WORD.para("Caseworker"), merge="restart"), *texts("Unit Approver", "Case Manager")],
    [merged(), *texts("Approver selected in Staff Search", "N/A")],
    texts("Case Manager", "Unit Approver of Case Manager", "N/A"),
)


def convert(source: pathlib.Path) -> list[str]:
    """The lines convert.sh's Pandoc call writes, blank lines dropped."""
    command = ["pandoc", "-f", "docx", "-t", "gfm-raw_html-raw_attribute",
               "--columns=100", "--wrap=auto"]
    command += [f"--lua-filter={path}" for path in FILTERS] + [str(source)]
    out = subprocess.run(command, capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line.strip()]


@unittest.skipUnless(shutil.which("pandoc"), "pandoc is not installed")
class NestedTableTest(unittest.TestCase):
    def setUp(self):
        self.work = pathlib.Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.work)

    def word(self, *body) -> list[str]:
        source = self.work / "in.docx"
        WORD.docx(source, body, [])
        return convert(source)

    def test_each_row_of_a_nested_table_is_a_line_of_the_cell(self):
        outer = table([cell(WORD.para("TABLE 1: Approvers"), APPROVERS)])
        self.assertEqual(self.word(outer), [
            "| TABLE 1: Approvers<br>"
            "If the submitter is:; Approver 1 will be:; Approver 2 will be:<br>"
            "Caseworker; Unit Approver; Case Manager<br>"
            "Approver selected in Staff Search; N/A<br>"
            "Case Manager; Unit Approver of Case Manager; N/A |",
            "|----|",
        ])

    def test_a_cell_merged_down_rows_is_given_once_in_its_first_row(self):
        lines = self.word(table([cell(APPROVERS)]))
        rows = lines[0].removeprefix("| ").removesuffix(" |").split("<br>")
        self.assertEqual(rows[1:3], [
            "Caseworker; Unit Approver; Case Manager",
            "Approver selected in Staff Search; N/A",
        ])
        self.assertEqual(sum(row.count("Caseworker") for row in rows), 1)

    def test_text_after_a_nested_table_starts_a_line_of_its_own(self):
        inner = table(texts("Code", "Meaning"), texts("PROC", "Processed"))
        outer = table([cell(WORD.para("Statuses:"), inner, WORD.para("See rule 3."))])
        self.assertEqual(self.word(outer)[0],
                         "| Statuses:<br>Code; Meaning<br>PROC; Processed<br>See rule 3. |")

    def test_the_other_cells_of_the_outer_table_stay_as_they_were(self):
        outer = table(texts("Name", "Rule"),
                      [cell(WORD.para("Approvers")), cell(WORD.para("one"), WORD.para("two"))])
        self.assertEqual(self.word(outer), [
            "| Name      | Rule     |", "|-----------|----------|", "| Approvers | one; two |",
        ])


if __name__ == "__main__":
    unittest.main()
