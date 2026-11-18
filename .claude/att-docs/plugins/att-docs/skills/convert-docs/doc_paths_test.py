#!/usr/bin/env python3
"""Cases for doc_paths.py: hyphenated file names and Markdown discovery.

Run: python3 plugins/att-docs/skills/convert-docs/doc_paths_test.py
"""
from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True
import doc_paths  # noqa: E402


class HyphenatedTest(unittest.TestCase):
    def test_spaced_dash_collapses(self):
        self.assertEqual(
            doc_paths.hyphenated("ACT 4.0 - Activity Entry.docx"),
            "ACT-4.0-Activity-Entry.docx")

    def test_name_without_space_is_unchanged(self):
        self.assertEqual(doc_paths.hyphenated("a-b_c.docx"), "a-b_c.docx")

    def test_hyphen_before_extension_dropped(self):
        self.assertEqual(doc_paths.hyphenated("Plan -.docx"), "Plan.docx")

    def test_space_run_becomes_one_hyphen(self):
        self.assertEqual(doc_paths.hyphenated("A   B.md"), "A-B.md")


class MarkdownUnderTest(unittest.TestCase):
    def test_walks_directories_and_takes_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "sub").mkdir()
            (root / "a.md").write_text("a")
            (root / "sub" / "b.md").write_text("b")
            (root / "sub" / "c.txt").write_text("c")
            lone = root / "sub" / "c.txt"
            got = doc_paths.markdown_under([str(root), str(lone)])
            self.assertEqual(got, [root / "a.md", root / "sub" / "b.md", lone])

    def test_missing_path_exits_with_message(self):
        with self.assertRaises(SystemExit) as ctx:
            doc_paths.markdown_under(["/nonexistent-dir-xyz"])
        self.assertIn("no such file or directory", str(ctx.exception.code))


class IsGeneratedPageTest(unittest.TestCase):
    HEADER = doc_paths.GENERATED_PREFIX + "docs/. Edits here are overwritten. -->\n"
    OTHER_DOCS_HEADER = doc_paths.GENERATED_PREFIX + "wiki/. Edits here are overwritten. -->\n"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name: str, text: str) -> pathlib.Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_page_beside_the_future_folder_is_generated_without_a_header(self):
        page = self.write("Future.md", "# Future\n")
        (self.root / "Future").mkdir()
        self.assertTrue(doc_paths.is_generated_page(page, "Future"))

    def test_future_named_page_without_a_folder_or_header_is_a_document(self):
        page = self.write("Future.md", "# Future\n")
        self.assertFalse(doc_paths.is_generated_page(page, "Future"))

    def test_configured_future_name_is_used(self):
        page = self.write("Later.md", "# Later\n")
        (self.root / "Later").mkdir()
        self.assertTrue(doc_paths.is_generated_page(page, "Later"))
        self.assertFalse(doc_paths.is_generated_page(page, "Future"))

    def test_only_the_future_name_is_matched_by_the_sibling_rule(self):
        page = self.write("Notes.md", "# Notes\n")
        (self.root / "Notes").mkdir()
        self.assertFalse(doc_paths.is_generated_page(page, "Future"))

    def test_header_on_the_first_line_marks_any_markdown_file(self):
        page = self.write("Notes.md", self.HEADER + "# Notes\n")
        self.assertTrue(doc_paths.is_generated_page(page, "Future"))

    def test_header_names_any_docs_folder(self):
        page = self.write("Notes.md", self.OTHER_DOCS_HEADER + "# Notes\n")
        self.assertTrue(doc_paths.is_generated_page(page, "Future"))

    def test_header_after_the_first_line_does_not_count(self):
        page = self.write("Notes.md", "# Notes\n" + self.HEADER)
        self.assertFalse(doc_paths.is_generated_page(page, "Future"))

    def test_header_in_a_non_markdown_file_does_not_count(self):
        page = self.write("Notes.txt", self.HEADER)
        self.assertFalse(doc_paths.is_generated_page(page, "Future"))

    def test_missing_file_is_not_generated(self):
        self.assertFalse(doc_paths.is_generated_page(self.root / "gone.md", "Future"))

    def test_prefix_is_the_start_of_the_wiki_marker_and_the_shell_copy(self):
        wiki = (HERE.parent / "living-wiki" / "wiki.mjs").read_text(encoding="utf-8")
        shell = (HERE / "convert.sh").read_text(encoding="utf-8")
        self.assertIn("const MARKER = `" + doc_paths.GENERATED_PREFIX + "${DOCS_NAME}/.", wiki)
        self.assertIn("'^" + doc_paths.GENERATED_PREFIX + "'", shell)


if __name__ == "__main__":
    unittest.main()
