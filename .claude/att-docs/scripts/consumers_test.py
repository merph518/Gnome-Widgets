#!/usr/bin/env python3
"""Checks .github/consumers.json, the list of repositories that pin Overmind, and that
every name in it has a pointer line under "Other Repos" in CLAUDE.md.

The names are repositories owned by merph518, written without the owner, in plain
(case-sensitive) sort order.

usage: python3 scripts/consumers_test.py
"""
import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, ".github", "consumers.json")
CLAUDE_MD = os.path.join(ROOT, "CLAUDE.md")


class Consumers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(PATH, encoding="utf-8") as f:
            cls.data = json.load(f)

    def test_the_only_key_is_consumers(self):
        self.assertIsInstance(self.data, dict)
        self.assertEqual(list(self.data), ["consumers"])

    def test_consumers_is_a_non_empty_list_of_strings(self):
        names = self.data["consumers"]
        self.assertIsInstance(names, list)
        self.assertTrue(names)
        for name in names:
            self.assertIsInstance(name, str)
            self.assertTrue(name.strip(), "a name is empty")

    def test_names_are_unique(self):
        names = self.data["consumers"]
        self.assertEqual(len(names), len(set(names)))

    def test_names_are_sorted(self):
        names = self.data["consumers"]
        self.assertEqual(names, sorted(names))

    def test_names_are_repository_names_without_an_owner(self):
        for name in self.data["consumers"]:
            self.assertTrue(re.fullmatch(r"[A-Za-z0-9._-]+", name),
                            f"{name} is not a bare repository name")

    def test_every_consumer_has_a_pointer_in_claude_md(self):
        names = pointer_names_in_other_repos(read_claude_md())
        for name in self.data["consumers"]:
            self.assertIn(name, names,
                          f"CLAUDE.md, Other Repos, has no pointer line for {name}")


def read_claude_md():
    with open(CLAUDE_MD, encoding="utf-8") as f:
        return f.read()


def pointer_names_in_other_repos(text):
    """Return the repository names that have a pointer line under "## Other Repos".

    A pointer line has the shape
    - `<name>` (<what it is>): `<local path>`. Clone from <remote> if missing.
    """
    match = re.search(r"^## Other Repos\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not match:
        return set()
    return set(re.findall(
        r"^- `([^`]+)` \(.+?\): `[^`]+`\. Clone from \S+ if missing\.",
        match.group(1), re.M))


class OtherReposPointers(unittest.TestCase):
    def test_reads_names_from_the_section_only(self):
        text = ("## Other Repos\n\n"
                "- `A` (a thing): `~/Code/a`. Clone from https://x/a if missing.\n"
                "- `B` (b thing): `~/Code/b`. Clone from https://x/b if missing. Read it.\n"
                "\n## Later\n\n"
                "- `C` (c thing): `~/Code/c`. Clone from https://x/c if missing.\n")
        self.assertEqual(pointer_names_in_other_repos(text), {"A", "B"})

    def test_a_line_without_path_or_remote_is_not_a_pointer(self):
        text = "## Other Repos\n\n- `A` (a thing): somewhere.\n"
        self.assertEqual(pointer_names_in_other_repos(text), set())

    def test_no_section_means_no_pointers(self):
        self.assertEqual(pointer_names_in_other_repos("# Title\n"), set())


if __name__ == "__main__":
    unittest.main()
