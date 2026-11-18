#!/usr/bin/env python3
"""Picks the test files a change can affect, for scripts/test-all.sh --changed-since.

usage: python3 -I scripts/select_tests.py <changed-paths-file>

The changed-paths file holds repository paths separated by NUL bytes, as
`git diff -z --name-only` writes them. The test entries come on stdin, one per line:
a test file's path, or `plugins/<name>` for a plugin whose hooks tests run with
`claude plugin test`. One line goes to stdout per entry, in the order given:

    RUN<TAB><entry>
    SKIP<TAB><entry><TAB><reason>

When the change has to run every test, the first line is `ALL<TAB><reason>` and every
entry is RUN.

A path belongs to a unit, the folder its tests sit in:

    plugins/<p>/skills/<s>/...   plugins/<p>/skills/<s>
    plugins/<p>/shared/...       plugins/<p>/shared
    plugins/<p>/...              plugins/<p> (hooks, types, scripts, plugin.json)
    .claude/skills/<s>/...       .claude/skills/<s>
    .github/scripts/...          .github/scripts
    scripts/<sub>/...            scripts/<sub>
    scripts/<file>               scripts

A test runs when a changed path is in its unit, or in a unit that EDGES says the test's
unit depends on. A changed path in `plugins/<p>` itself runs every test under that
plugin. Markdown at the root or under docs/, and LICENSE, run nothing, unless EDGES
names the file. A path in RUN_ALL runs everything, and so does any other path outside
every unit, so a file nobody mapped never skips a test it feeds.
"""
import sys

# Changing one of these can change any test's result.
RUN_ALL = (
    'scripts/test-all.sh',
    'scripts/select_tests.py',
    '.github/workflows/',
    'package.json',
    'package-lock.json',
    '.claude-plugin/',
)

# Files outside every unit that no test reads: Markdown at the root or under docs/, and
# the license.
NO_TESTS_FILES = ('LICENSE',)

# A unit or a single file, and the units whose tests read it from outside their own unit.
EDGES = {
    # wiki.mjs imports doc-names.mjs.
    'plugins/att-docs/shared': ('plugins/att-docs/skills/living-wiki',),
    # docimpact.py and docwatch.py import convert-docs modules, and docwatch runs its
    # scripts.
    'plugins/att-docs/skills/convert-docs': ('plugins/att-docs/skills/doc-impact',
                                             'plugins/att-docs/skills/doc-watch'),
    # doc_paths_test.py reads the generated-page marker from wiki.mjs.
    'plugins/att-docs/skills/living-wiki': ('plugins/att-docs/skills/convert-docs',),
    # pack-compare.mjs imports build-pack.mjs.
    'plugins/att-docs/skills/build-test-pack': ('.github/scripts',),
    # The hooks run oversee.sh and loop.py.
    'plugins/general/skills/oversee-development': ('plugins/general',),
    # guard-main-checkout.sh sources these, and payload-guard_test.sh copies them.
    'scripts/lib': ('scripts', 'plugins/att-docs/skills/repo-writing'),
    # overmind-pin_test.sh copies the consumer scripts.
    'scripts/consumer': ('scripts/pin',),
    # guard-main-checkout_test.sh reads the hook entry.
    '.claude/settings.json': ('scripts',),
    # consumers_test.py reads both; the day-recap extension test checks its repository
    # list against consumers.json.
    '.github/consumers.json': ('scripts', '.claude/skills/day-recap'),
    'CLAUDE.md': ('scripts',),
    # The path in scripts/ runs the worktree-sweeper plugin's copy, and its test runs it.
    'scripts/worktree-cleanup.sh': ('plugins/worktree-sweeper',),
}


def unit_of(path):
    """The unit a path belongs to, or None for a path outside every unit."""
    parts = path.split('/')
    if parts[0] == 'plugins' and len(parts) >= 2:
        if len(parts) >= 4 and parts[2] == 'skills':
            return '/'.join(parts[:4])
        if len(parts) >= 3 and parts[2] == 'shared':
            return '/'.join(parts[:3])
        return '/'.join(parts[:2])
    if parts[:2] == ['.claude', 'skills'] and len(parts) >= 4:
        return '/'.join(parts[:3])
    if parts[:2] == ['.github', 'scripts'] and len(parts) >= 3:
        return '.github/scripts'
    if parts[0] == 'scripts' and len(parts) >= 2:
        return 'scripts' if len(parts) == 2 else '/'.join(parts[:2])
    return None


def runs_all(path):
    return any(path == p or (p.endswith('/') and path.startswith(p)) for p in RUN_ALL)


def no_tests(path):
    if path in NO_TESTS_FILES:
        return True
    in_docs = '/' not in path or path.startswith('docs/')
    return in_docs and path.endswith('.md') and path not in EDGES


class Reach:
    """The units a set of changed paths reaches, edges included. A change to a
    plugin-level file (`plugins/<p>/...` outside its skills and shared folders) reaches
    every unit under that plugin."""

    def __init__(self, changed):
        self.units, self.plugins = set(), set()
        for path in changed:
            unit = unit_of(path)
            if unit is not None:
                self.units.add(unit)
                if unit.count('/') == 1 and unit.startswith('plugins/'):
                    self.plugins.add(unit)
            self.units.update(EDGES.get(path, ()))
            self.units.update(EDGES.get(unit, ()))

    def __contains__(self, unit):
        """Whether the tests of `unit` can be affected."""
        return unit in self.units or '/'.join(unit.split('/')[:2]) in self.plugins


def select(changed, tests):
    """(tests to run, {skipped test: reason}, reason every test runs or None)."""
    for path in changed:
        if runs_all(path):
            return list(tests), {}, f'{path} changed'
        if unit_of(path) is None and not no_tests(path) and path not in EDGES:
            return list(tests), {}, f'{path} is outside every test folder'
    if not changed:
        return [], {t: 'no file changed' for t in tests}, None
    reach = Reach(changed)
    picked, skipped = [], {}
    for test in tests:
        unit = unit_of(test)
        # A test outside every unit has no unit to match, so it always runs.
        if unit is None or unit in reach:
            picked.append(test)
        else:
            skipped[test] = f'no changed file in {unit}'
    return picked, skipped, None


def main(argv):
    if len(argv) != 2:
        print(__doc__.split('\n\n')[1], file=sys.stderr)
        return 2
    with open(argv[1], 'rb') as f:
        changed = [p.decode() for p in f.read().split(b'\0') if p]
    tests = [line for line in sys.stdin.read().splitlines() if line]
    picked, skipped, every = select(changed, tests)
    if every:
        print(f'ALL\t{every}')
    for test in tests:
        if test in skipped:
            print(f'SKIP\t{test}\t{skipped[test]}')
        else:
            print(f'RUN\t{test}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
