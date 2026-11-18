#!/usr/bin/env python3
"""Tests for scripts/select_tests.py, which picks the test files a change can affect.

usage: python3 scripts/select_tests_test.py
"""
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import select_tests  # noqa: E402

BTP = 'plugins/att-docs/skills/build-test-pack'
TESTS = [
    f'{BTP}/local/build-pack.test.mjs',
    f'{BTP}/local/check.test.mjs',
    '.github/scripts/pack-compare.test.mjs',
    'plugins/att-docs/shared/doc-names.test.mjs',
    'plugins/att-docs/skills/living-wiki/wiki.test.mjs',
    'plugins/att-docs/skills/convert-docs/slides_test.py',
    'plugins/att-docs/skills/doc-impact/docimpact_test.py',
    'plugins/att-docs/skills/doc-watch/docwatch_test.py',
    'plugins/att-docs/skills/repo-writing/payload-guard_test.sh',
    'plugins/general/hooks/implement_loop_test.py',
    'plugins/general/skills/day-recap/day_recap_test.py',
    'plugins/general/skills/oversee-development/oversee_test.sh',
    'plugins/general',
    'plugins/cache-clock',
    '.claude/skills/implement/merge_pin_pr_test.py',
    'scripts/consumers_test.py',
    'scripts/guard-main-checkout_test.sh',
    'scripts/lib/hook-tool_test.sh',
    'scripts/pin/overmind-pin_test.sh',
    'scripts/consumer/overmind-consumer_test.sh',
]


def run(changed):
    picked, skipped, every = select_tests.select(changed, TESTS)
    return picked, skipped, every


def picked(changed):
    return set(run(changed)[0])


class Units(unittest.TestCase):
    def test_unit_of_each_kind_of_path(self):
        cases = {
            f'{BTP}/local/build-pack.mjs': BTP,
            f'{BTP}/SKILL.md': BTP,
            'plugins/att-docs/shared/alm-text.mjs': 'plugins/att-docs/shared',
            'plugins/general/hooks/run.sh': 'plugins/general',
            'plugins/general/types.ts': 'plugins/general',
            'plugins/general': 'plugins/general',
            '.claude/skills/implement/SKILL.md': '.claude/skills/implement',
            '.github/scripts/pack-compare.mjs': '.github/scripts',
            'scripts/pin/pin_notes.py': 'scripts/pin',
            'scripts/catchup.py': 'scripts',
            'README.md': None,
            'docs/adr/0001.md': None,
            'odd/place.txt': None,
        }
        for path, unit in cases.items():
            self.assertEqual(select_tests.unit_of(path), unit, path)


class Select(unittest.TestCase):
    def test_a_change_outside_build_test_pack_runs_none_of_its_files(self):
        got = picked(['plugins/general/skills/day-recap/day_recap.py'])
        self.assertEqual(got, {'plugins/general/skills/day-recap/day_recap_test.py'})

    def test_skipped_files_name_why(self):
        _, skipped, every = run(['plugins/att-docs/skills/convert-docs/slides.py'])
        self.assertIsNone(every)
        self.assertIn(f'{BTP}/local/build-pack.test.mjs', skipped)
        self.assertIn(BTP, skipped[f'{BTP}/local/build-pack.test.mjs'])

    def test_a_build_test_pack_change_runs_its_files_and_pack_compare(self):
        got = picked([f'{BTP}/local/check.mjs'])
        self.assertEqual(got, {f'{BTP}/local/build-pack.test.mjs',
                               f'{BTP}/local/check.test.mjs',
                               '.github/scripts/pack-compare.test.mjs'})

    def test_markdown_inside_a_unit_runs_that_unit(self):
        self.assertIn(f'{BTP}/local/build-pack.test.mjs', picked([f'{BTP}/SKILL.md']))

    def test_markdown_outside_every_unit_runs_no_tests(self):
        for path in ['README.md', 'GLOSSARY.md', 'docs/agents/issue-tracker.md',
                     'docs/runners/RunnerRegistration.md', 'docs/adr/0001-x.md', 'LICENSE']:
            picked_, _, every = run([path])
            self.assertIsNone(every, path)
            self.assertEqual(picked_, [], path)

    def test_an_empty_change_runs_no_tests(self):
        self.assertEqual(run([]), ([], {t: 'no file changed' for t in TESTS}, None))

    def test_paths_that_run_everything(self):
        for path in ['scripts/test-all.sh', 'scripts/select_tests.py',
                     '.github/workflows/ci.yml', 'package.json', 'package-lock.json',
                     '.claude-plugin/marketplace.json']:
            picked_, skipped, every = run([path])
            self.assertEqual(picked_, TESTS, path)
            self.assertEqual(skipped, {}, path)
            self.assertIn(path, every)

    def test_an_unknown_path_runs_everything(self):
        for path in ['odd/place.txt', 'docs/diagram.png', '.gitignore', 'docs/x/data.json']:
            picked_, _, every = run([path])
            self.assertEqual(picked_, TESTS, path)
            self.assertIn(path, every)

    def test_a_plugin_level_file_runs_every_test_in_that_plugin(self):
        got = picked(['plugins/general/types.ts'])
        self.assertEqual(got, {'plugins/general/hooks/implement_loop_test.py',
                               'plugins/general/skills/day-recap/day_recap_test.py',
                               'plugins/general/skills/oversee-development/oversee_test.sh',
                               'plugins/general'})

    def test_a_hook_change_runs_its_plugin_mod_test(self):
        self.assertIn('plugins/cache-clock', picked(['plugins/cache-clock/hooks/clock.ts']))

    def test_edges_between_units(self):
        cases = {
            'plugins/att-docs/skills/convert-docs/pages.py':
                {'plugins/att-docs/skills/convert-docs/slides_test.py',
                 'plugins/att-docs/skills/doc-impact/docimpact_test.py',
                 'plugins/att-docs/skills/doc-watch/docwatch_test.py'},
            'plugins/att-docs/shared/doc-names.mjs':
                {'plugins/att-docs/shared/doc-names.test.mjs',
                 'plugins/att-docs/skills/living-wiki/wiki.test.mjs'},
            'scripts/lib/heredoc.py':
                {'scripts/lib/hook-tool_test.sh', 'scripts/consumers_test.py',
                 'scripts/guard-main-checkout_test.sh',
                 'plugins/att-docs/skills/repo-writing/payload-guard_test.sh'},
            'scripts/consumer/overmind-sync.sh':
                {'scripts/consumer/overmind-consumer_test.sh',
                 'scripts/pin/overmind-pin_test.sh'},
            'plugins/general/skills/oversee-development/loop.py':
                {'plugins/general/skills/oversee-development/oversee_test.sh',
                 'plugins/general/hooks/implement_loop_test.py', 'plugins/general'},
            '.claude/settings.json':
                {'scripts/consumers_test.py', 'scripts/guard-main-checkout_test.sh'},
            '.github/consumers.json':
                {'scripts/consumers_test.py', 'scripts/guard-main-checkout_test.sh'},
            'CLAUDE.md':
                {'scripts/consumers_test.py', 'scripts/guard-main-checkout_test.sh'},
        }
        for path, want in cases.items():
            self.assertEqual(picked([path]), want, path)

    def test_a_rename_selects_both_sides(self):
        got = picked(['scripts/pin/x.sh', 'scripts/consumer/x.sh'])
        self.assertIn('scripts/pin/overmind-pin_test.sh', got)
        self.assertIn('scripts/consumer/overmind-consumer_test.sh', got)

    def test_order_follows_the_test_list(self):
        got, _, _ = run(['scripts/catchup.py', f'{BTP}/x.mjs'])
        self.assertEqual(got, [t for t in TESTS if t in set(got)])


class Cli(unittest.TestCase):
    def cli(self, changed, tests):
        with tempfile.NamedTemporaryFile('wb', delete=False) as f:
            f.write(b'\0'.join(p.encode() for p in changed) + (b'\0' if changed else b''))
        try:
            return subprocess.run(
                [sys.executable, '-I', os.path.join(HERE, 'select_tests.py'), f.name],
                input='\n'.join(tests) + '\n', capture_output=True, text=True, check=True,
            ).stdout.splitlines()
        finally:
            os.unlink(f.name)

    def test_prints_a_line_per_test(self):
        out = self.cli(['scripts/pin/a b.sh'], ['scripts/pin/overmind-pin_test.sh',
                                                'scripts/catchup_test.py'])
        self.assertEqual(out, [
            'RUN\tscripts/pin/overmind-pin_test.sh',
            'SKIP\tscripts/catchup_test.py\tno changed file in scripts',
        ])

    def test_prints_why_it_runs_everything(self):
        out = self.cli(['package.json'], ['scripts/catchup_test.py'])
        self.assertEqual(out, ['ALL\tpackage.json changed', 'RUN\tscripts/catchup_test.py'])


def tracked(*patterns):
    out = subprocess.run(['git', 'ls-files', *patterns], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout.splitlines()
    for path in out:
        unit = select_tests.unit_of(path)
        if unit is not None:
            with open(os.path.join(ROOT, path), encoding='utf-8', errors='replace') as f:
                yield path, unit, f.read()


class Audit(unittest.TestCase):
    """A file that reaches into another unit has to be listed as an edge, or a change to
    the file it reaches would skip its tests."""

    IMPORT = re.compile(r"""(?:from\s+|import\s*\(\s*|require\s*\(\s*)['"](\.\.?/[^'"]+)['"]""")

    def test_every_cross_unit_import_is_an_edge(self):
        missing = []
        for path, unit, text in tracked('*.mjs', '*.js', '*.ts', '*.tsx'):
            for target in self.IMPORT.findall(text):
                joined = os.path.normpath(os.path.join(os.path.dirname(path), target))
                other = select_tests.unit_of(joined)
                if other and other != unit and unit not in select_tests.Reach([joined]):
                    missing.append(f'{path} imports {joined}')
        self.assertEqual(missing, [])

    def test_every_reference_to_another_skill_folder_is_an_edge(self):
        # Python puts a sibling skill folder on sys.path, and shell runs its scripts, by
        # naming the folder: "convert-docs", ../convert-docs, /convert-docs/.
        skills = {u for _, u, _ in tracked('*') if '/skills/' in u}
        mapping = {os.path.join(HERE, 'select_tests.py'), os.path.abspath(__file__)}
        missing = []
        for path, unit, text in tracked('*.py', '*.sh', '*.mjs', '*.js', '*.ts', '*.tsx'):
            if os.path.join(ROOT, path) in mapping:
                continue
            for other in skills:
                name = other.rsplit('/', 1)[1]
                if other == unit or unit.endswith('/' + name):
                    continue
                # `.claude/skills/<name>` is a repository's own extension folder, which
                # shares the skill's name but is not the plugin's skill folder.
                own = text.replace(f'.claude/skills/{name}', '')
                named = re.search(r"""(?:['"/]|\.\./)""" + re.escape(name) + r"""['"/]""", own)
                if named and unit not in select_tests.Reach([other + '/x']):
                    missing.append(f'{path} names {other}')
        self.assertEqual(missing, [])


if __name__ == '__main__':
    unittest.main()
