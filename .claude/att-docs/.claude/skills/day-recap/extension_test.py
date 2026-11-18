#!/usr/bin/env python3
"""Checks the day-recap extension's repository list.

`repos` must name Overmind and every repository in .github/consumers.json, as
`owner/name`, so one recap run covers all of them.

usage: python3 .claude/skills/day-recap/extension_test.py
"""
import json
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
OWNER = "merph518"
OVERMIND = f"{OWNER}/Overmind-Mod"


def read_json(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return json.load(f)


class Extension(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = read_json(".claude", "skills", "day-recap", "extension.json")
        cls.consumers = read_json(".github", "consumers.json")["consumers"]

    def test_config_is_an_object_with_a_non_empty_repos_list(self):
        self.assertIsInstance(self.config, dict)
        repos = self.config.get("repos")
        self.assertIsInstance(repos, list)
        self.assertTrue(repos)

    def test_repos_are_unique_owner_slash_name_strings(self):
        repos = self.config["repos"]
        for repo in repos:
            self.assertIsInstance(repo, str)
            self.assertTrue(re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", repo),
                            f"{repo} is not owner/name")
        self.assertEqual(len(repos), len(set(repos)))

    def test_overmind_is_listed(self):
        self.assertIn(OVERMIND, self.config["repos"])

    def test_every_consumer_is_listed(self):
        repos = self.config["repos"]
        for name in self.consumers:
            self.assertIn(f"{OWNER}/{name}", repos,
                          f"extension.json repos lacks {OWNER}/{name}")


if __name__ == "__main__":
    unittest.main()
