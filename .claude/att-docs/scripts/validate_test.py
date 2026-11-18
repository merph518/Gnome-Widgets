#!/usr/bin/env python3
"""Tests for the plugin registration check in scripts/validate.py: every plugin folder
needs a marketplace.json entry and a release-please extra-files entry, and every
extra-files path exists.

usage: python3 scripts/validate_test.py
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# scripts/ is not a package and validate.py runs under -I, so it is loaded by path.
_spec = importlib.util.spec_from_file_location("validate", os.path.join(HERE, "validate.py"))
validate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validate)

PLUGINS = ["alpha", "beta"]


def marketplace(names=PLUGINS):
    return {"name": "x", "plugins": [
        {"name": n, "source": f"./plugins/{n}", "description": n} for n in names]}


def extra_file(name):
    return {"type": "json", "path": f"plugins/{name}/.claude-plugin/plugin.json",
            "jsonpath": "$.version"}


def release_config(entries=None):
    if entries is None:
        entries = [extra_file(n) for n in PLUGINS]
    return {"packages": {".": {"changelog-path": "CHANGELOG.md", "extra-files": entries}}}


class Registration(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        for name in PLUGINS:
            self.write(f"plugins/{name}/.claude-plugin/plugin.json", {"name": name})
        self.write(".claude-plugin/marketplace.json", marketplace())
        self.write("release-please-config.json", release_config())

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel, data):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(data if isinstance(data, str) else json.dumps(data))

    def check(self):
        return validate.check_plugin_registration(self.root)

    def assertOneError(self, *fragments):
        errors = self.check()
        self.assertEqual(len(errors), 1, errors)
        for fragment in fragments:
            self.assertIn(fragment, errors[0])

    def test_a_complete_tree_passes(self):
        self.assertEqual(self.check(), [])

    def test_plugin_missing_from_marketplace(self):
        self.write(".claude-plugin/marketplace.json", marketplace(["alpha"]))
        self.assertOneError("marketplace.json", "beta", "no entry")

    def test_marketplace_entry_with_the_wrong_source(self):
        data = marketplace()
        data["plugins"][1]["source"] = "./plugins/alpha"
        self.write(".claude-plugin/marketplace.json", data)
        self.assertOneError("marketplace.json", "beta", "./plugins/beta")

    def test_equivalent_source_spellings_pass(self):
        data = marketplace()
        data["plugins"][0]["source"] = "plugins/alpha/"
        self.write(".claude-plugin/marketplace.json", data)
        self.assertEqual(self.check(), [])

    def test_duplicate_marketplace_name(self):
        data = marketplace()
        data["plugins"].append(dict(data["plugins"][0]))
        self.write(".claude-plugin/marketplace.json", data)
        self.assertOneError("marketplace.json", "alpha", "more than once")

    def test_plugin_missing_from_extra_files(self):
        self.write("release-please-config.json", release_config([extra_file("alpha")]))
        self.assertOneError("release-please-config.json", "beta", "no extra-files entry")

    def test_extra_files_entry_with_the_wrong_jsonpath(self):
        entry = extra_file("beta")
        entry["jsonpath"] = "$.ver"
        self.write("release-please-config.json", release_config([extra_file("alpha"), entry]))
        self.assertOneError("release-please-config.json", "beta", "$.version")

    def test_extra_files_entry_with_the_wrong_type(self):
        entry = extra_file("beta")
        entry["type"] = "toml"
        self.write("release-please-config.json", release_config([extra_file("alpha"), entry]))
        self.assertOneError("release-please-config.json", "beta", "json")

    def test_extra_files_path_that_does_not_exist(self):
        entries = [extra_file(n) for n in PLUGINS] + [extra_file("ghost")]
        self.write("release-please-config.json", release_config(entries))
        self.assertOneError("release-please-config.json",
                            "plugins/ghost/.claude-plugin/plugin.json", "does not exist")

    def test_string_extra_files_path_that_does_not_exist(self):
        entries = [extra_file(n) for n in PLUGINS] + ["VERSION.txt"]
        self.write("release-please-config.json", release_config(entries))
        self.assertOneError("release-please-config.json", "VERSION.txt", "does not exist")

    def test_extra_files_entry_with_no_path(self):
        entries = [extra_file(n) for n in PLUGINS] + [{"type": "json"}]
        self.write("release-please-config.json", release_config(entries))
        self.assertOneError("release-please-config.json", "no path")

    def test_duplicate_extra_files_path(self):
        entries = [extra_file(n) for n in PLUGINS] + [extra_file("alpha")]
        self.write("release-please-config.json", release_config(entries))
        self.assertOneError("release-please-config.json", "alpha", "more than once")

    def test_extra_files_from_every_package_count(self):
        data = release_config([extra_file("alpha")])
        data["packages"]["plugins/beta"] = {"extra-files": [
            {"type": "json", "path": ".claude-plugin/plugin.json", "jsonpath": "$.version"}]}
        self.write("release-please-config.json", data)
        self.assertEqual(self.check(), [])

    def test_package_paths_are_relative_to_the_package(self):
        data = release_config([extra_file("alpha")])
        data["packages"]["plugins/beta"] = {"extra-files": [extra_file("beta")]}
        self.write("release-please-config.json", data)
        errors = self.check()
        self.assertIn("plugins/beta/plugins/beta/.claude-plugin/plugin.json does not exist",
                      "\n".join(errors))
        self.assertIn("plugin beta has no extra-files entry", "\n".join(errors))

    def test_extra_files_that_is_not_a_list(self):
        for value in (None, "plugins/alpha/.claude-plugin/plugin.json", {"path": "x"}):
            with self.subTest(value=value):
                data = release_config()
                data["packages"]["."]["extra-files"] = value
                self.write("release-please-config.json", data)
                errors = self.check()
                self.assertIn('"extra-files" in package . is not a list', errors[0])
                # Then each plugin is reported as missing, and nothing else.
                self.assertEqual(len(errors), 1 + len(PLUGINS), errors)

    def test_packages_missing(self):
        self.write("release-please-config.json", {})
        errors = self.check()
        self.assertIn('"packages" is missing or not an object', errors[0])
        self.assertEqual(len(errors), 1 + len(PLUGINS), errors)

    def test_top_level_that_is_not_an_object(self):
        for rel in (".claude-plugin/marketplace.json", "release-please-config.json"):
            with self.subTest(rel=rel):
                self.write(".claude-plugin/marketplace.json", marketplace())
                self.write("release-please-config.json", release_config())
                self.write(rel, [])
                self.assertOneError(rel, "top level is not an object")

    def test_extra_files_path_outside_the_repository(self):
        for path in ("/etc/hostname", "../outside.json"):
            with self.subTest(path=path):
                entries = [extra_file(n) for n in PLUGINS] + [path]
                self.write("release-please-config.json", release_config(entries))
                self.assertOneError("release-please-config.json", "outside the repository")

    def test_marketplace_plugins_that_is_not_a_list_is_left_to_check_json(self):
        self.write(".claude-plugin/marketplace.json", {"plugins": None})
        self.assertEqual(self.check(), [])

    def test_non_string_source_is_left_to_check_json(self):
        data = marketplace()
        data["plugins"][0]["source"] = {"source": "github"}
        self.write(".claude-plugin/marketplace.json", data)
        self.assertEqual(self.check(), [])

    def test_folder_without_plugin_json_is_ignored(self):
        os.makedirs(os.path.join(self.root, "plugins", "shared"))
        self.write("plugins/README.md", "notes")
        self.assertEqual(self.check(), [])

    def test_no_plugins_folder_passes(self):
        shutil.rmtree(os.path.join(self.root, "plugins"))
        self.write(".claude-plugin/marketplace.json", marketplace([]))
        self.write("release-please-config.json", release_config([]))
        self.assertEqual(self.check(), [])

    def test_malformed_marketplace(self):
        self.write(".claude-plugin/marketplace.json", "{not json")
        self.assertOneError("marketplace.json", "not valid JSON")

    def test_malformed_release_config(self):
        self.write("release-please-config.json", "{not json")
        self.assertOneError("release-please-config.json", "not valid JSON")

    def test_missing_release_config(self):
        os.remove(os.path.join(self.root, "release-please-config.json"))
        self.assertOneError("release-please-config.json", "cannot be read")

    def run_cli_on_a_copy(self, rel, edit):
        """Copy this checkout, rewrite one file with edit(text), run validate.py on the copy."""
        # The CLI checks the tree it sits in, so it runs from a copy of this checkout.
        with tempfile.TemporaryDirectory() as tmp:
            copy = os.path.join(tmp, "repo")
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(
                ".git", "node_modules", "worktrees", "__pycache__"))
            path = os.path.join(copy, rel)
            with open(path, encoding="utf-8") as f:
                text = f.read()
            with open(path, "w", encoding="utf-8") as f:
                f.write(edit(text))
            return subprocess.run(
                [sys.executable, "-I", os.path.join(copy, "scripts", "validate.py")],
                capture_output=True, text=True)

    def test_cli_reports_the_problem_and_exits_1(self):
        def add_ghost(text):
            data = json.loads(text)
            data["packages"]["."]["extra-files"].append(extra_file("ghost"))
            return json.dumps(data)
        r = self.run_cli_on_a_copy("release-please-config.json", add_ghost)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("plugins/ghost/.claude-plugin/plugin.json does not exist", r.stdout)

    def test_cli_reports_a_malformed_marketplace_once(self):
        r = self.run_cli_on_a_copy(".claude-plugin/marketplace.json", lambda _: "{not json")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(r.stdout.count("marketplace.json: not valid JSON"), 1, r.stdout)

    def test_cli_reports_marketplace_plugins_null_without_crashing(self):
        def null_plugins(text):
            data = json.loads(text)
            data["plugins"] = None
            return json.dumps(data)
        r = self.run_cli_on_a_copy(".claude-plugin/marketplace.json", null_plugins)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn('"plugins" is not a list', r.stdout)


class ThisRepository(unittest.TestCase):
    def test_every_plugin_is_registered(self):
        self.assertEqual(validate.check_plugin_registration(ROOT), [])


if __name__ == "__main__":
    unittest.main()
