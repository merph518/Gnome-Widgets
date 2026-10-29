#!/usr/bin/env python3
"""Render a widget as it would look with one option applied, and save it as a PNG.

usage: scripts/render-option.py <out.png> [spotify|speech] [--patch FILE]

The widget is drawn by the real code, not imitated: a temporary worktree of origin/main
gets the option's patch (a `git diff` of its change to src/, none for the look as it is
today), an isolated copy of the widget runs from it with fixture content, the copy's window
is captured with scripts/isolated-widgets.py, and the copy and the worktree are removed.
Nothing of the user's own copy or another session's is read, stopped or captured.

One call renders one option in one state; the states the content has (a session with and
without an issue, say) are the fixture rows the copy shows. The PNGs of the options are
what the user compares, per .claude/skills/_shared/ui-options.md.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.dirname(HERE)
SHOW_WITHIN = 20          # seconds the copy has to put its window up


def run(*cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def render(out, widget, patch):
    work = tempfile.mkdtemp(prefix='render-option-')
    tree = os.path.join(work, 'checkout')
    name = f'render-option-{os.getpid()}'
    run('git', '-C', REPO, 'fetch', '-q', 'origin', 'main')
    run('git', '-C', REPO, 'worktree', 'add', '-q', '--detach', tree, 'origin/main')
    isolated = [sys.executable, os.path.join(tree, 'scripts', 'isolated-widgets.py'), '--name', name]
    try:
        if patch:
            run('git', '-C', tree, 'apply', os.path.abspath(patch))
        run(*isolated, 'start', widget)
        deadline = time.monotonic() + SHOW_WITHIN
        while subprocess.run([*isolated, 'capture', out, widget], capture_output=True).returncode:
            if time.monotonic() > deadline:
                sys.exit(f'the {widget} window never showed in {SHOW_WITHIN}s; see the copy\'s run.log')
            time.sleep(1)
        print(f'saved {out}')
    finally:
        subprocess.run([*isolated, 'stop'], capture_output=True)
        subprocess.run(['git', '-C', REPO, 'worktree', 'remove', '--force', tree], capture_output=True)
        shutil.rmtree(work, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('out')
    parser.add_argument('widget', nargs='?', choices=('spotify', 'speech'), default='speech')
    parser.add_argument('--patch')
    args = parser.parse_args()
    render(args.out, args.widget, args.patch)


if __name__ == '__main__':
    main()
