#!/usr/bin/env python3
"""Cases for convert.sh and the living-wiki page beside a suite's Future folder.

The page the wiki writes there is not a source document, so a batch leaves it in the
todo root and converts the documents around it. Plain Markdown sources take the copy
route, so the external converters are stubbed and the cases run anywhere.

Run: python3 plugins/att-docs/skills/convert-docs/convert_wiki_page_test.py
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True
import doc_paths  # noqa: E402
HEADER = doc_paths.GENERATED_PREFIX + "docs/. Edits here are overwritten. -->\n"
TOOLS = ("pandoc", "soffice", "pdftotext", "pdfinfo")


class WikiPageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.repo = root / "repo"
        self.suite = self.repo / "todo" / "OCS"
        (self.suite / "Future").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        (self.repo / "words.txt").write_text("plain\ntext\nrevision\n", encoding="utf-8")
        (self.repo / "extension.json").write_text(json.dumps({
            "todoRoot": "todo", "appsRoot": "apps", "futureFolder": "Future",
            "words": "words.txt", "collisions": "collisions.tsv",
            "sharePointHost": "https://example.invalid",
        }), encoding="utf-8")
        stubs = root / "stubs"
        stubs.mkdir()
        for tool in TOOLS:
            stub = stubs / tool
            stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            stub.chmod(0o755)
        self.env = {**os.environ, "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}"}
        (self.suite / "Future.md").write_text(HEADER + "# Future\n", encoding="utf-8")
        (self.suite / "Doc.md").write_text("Plain text.\n", encoding="utf-8")
        (self.suite / "Future" / "Rev.md").write_text("Revision text.\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def convert(self, *extra: str) -> subprocess.CompletedProcess:
        run = subprocess.run(
            ["bash", str(HERE / "convert.sh"), "--config", str(self.repo / "extension.json"),
             "--converted", "2024-01-02 03:04Z", *extra],
            capture_output=True, text=True, check=False, timeout=600, env=self.env)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        return run

    def test_the_page_stays_in_the_todo_root_and_is_not_converted(self) -> None:
        run = self.convert("--keep-sources")
        apps = self.repo / "apps" / "OCS"
        self.assertFalse((apps / "Future.md").exists(), run.stdout)
        self.assertTrue((self.suite / "Future.md").is_file())
        self.assertTrue((apps / "Doc.md").is_file(), run.stdout)
        self.assertTrue((apps / "Future" / "Rev.md").is_file(), run.stdout)

    def test_the_page_stays_when_sources_are_moved_to_done(self) -> None:
        self.convert()
        self.assertTrue((self.suite / "Future.md").is_file())
        self.assertFalse((self.repo / "todo" / "_done" / "OCS" / "Future.md").exists())
        self.assertTrue((self.repo / "todo" / "_done" / "OCS" / "Doc.md").is_file())

    def test_a_suite_run_leaves_the_page_too(self) -> None:
        self.convert("--keep-sources", "--suite", "OCS")
        self.assertFalse((self.repo / "apps" / "OCS" / "Future.md").exists())
        self.assertTrue((self.suite / "Future.md").is_file())

    def test_a_real_document_of_the_same_stem_does_not_take_the_page_as_a_source(self) -> None:
        (self.suite / "Future.txt").write_text("Plain text.\n", encoding="utf-8")
        self.convert()
        self.assertTrue((self.suite / "Future.md").is_file())
        self.assertFalse((self.repo / "todo" / "_done" / "OCS" / "Future.md").exists())
        self.assertTrue((self.repo / "todo" / "_done" / "OCS" / "Future.txt").is_file())
        converted = (self.repo / "apps" / "OCS" / "Future.md").read_text(encoding="utf-8")
        self.assertNotIn("Generated from the folder layout", converted)

    def test_a_future_named_document_with_no_folder_or_header_converts(self) -> None:
        (self.suite / "Future").joinpath("Rev.md").unlink()
        (self.suite / "Future").rmdir()
        (self.suite / "Future.md").write_text("Hand written text.\n", encoding="utf-8")
        self.convert("--keep-sources")
        self.assertTrue((self.repo / "apps" / "OCS" / "Future.md").is_file())

    def test_a_headed_page_with_no_future_folder_is_left_alone(self) -> None:
        (self.suite / "Future" / "Rev.md").unlink()
        (self.suite / "Future").rmdir()
        self.convert()
        self.assertTrue((self.suite / "Future.md").is_file())
        self.assertFalse((self.repo / "apps" / "OCS" / "Future.md").exists())
        self.assertTrue((self.repo / "apps" / "OCS" / "Doc.md").is_file())
        self.assertFalse((self.repo / "todo" / "_done" / "OCS" / "Future.md").exists())

    def test_any_headed_markdown_file_is_left_alone(self) -> None:
        (self.suite / "Notes.md").write_text(HEADER + "# Notes\n", encoding="utf-8")
        self.convert("--keep-sources")
        self.assertFalse((self.repo / "apps" / "OCS" / "Notes.md").exists())
        self.assertTrue((self.suite / "Notes.md").is_file())

    def test_a_header_below_the_first_line_is_a_document(self) -> None:
        (self.suite / "Notes.md").write_text("Plain text.\n" + HEADER, encoding="utf-8")
        self.convert("--keep-sources")
        self.assertTrue((self.repo / "apps" / "OCS" / "Notes.md").is_file())

    def test_the_suite_folder_stays_while_it_holds_the_page(self) -> None:
        self.convert()
        self.assertEqual([p.name for p in self.suite.iterdir()], ["Future.md"])

    def test_the_configured_future_folder_name_is_used(self) -> None:
        config = self.repo / "extension.json"
        config.write_text(config.read_text(encoding="utf-8").replace("Future", "Later"),
                          encoding="utf-8")
        (self.suite / "Future").rename(self.suite / "Later")
        (self.suite / "Future.md").unlink()
        (self.suite / "Later.md").write_text("# Later\n", encoding="utf-8")
        self.convert("--keep-sources")
        apps = self.repo / "apps" / "OCS"
        self.assertFalse((apps / "Later.md").exists())
        self.assertTrue((self.suite / "Later.md").is_file())
        self.assertTrue((apps / "Later" / "Rev.md").is_file())

    def test_a_page_with_no_header_beside_the_future_folder_is_left_alone(self) -> None:
        (self.suite / "Future.md").write_text("# Future\n", encoding="utf-8")
        self.convert("--keep-sources")
        self.assertFalse((self.repo / "apps" / "OCS" / "Future.md").exists())
        self.assertTrue((self.suite / "Future.md").is_file())


if __name__ == "__main__":
    unittest.main()
