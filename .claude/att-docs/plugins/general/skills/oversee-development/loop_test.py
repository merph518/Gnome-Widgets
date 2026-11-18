#!/usr/bin/env python3
"""Cases for loop.py's board command, which the status row's pane reads.

Each case builds a throwaway git repository with its own .claude/oversee folder, so
nothing real is touched.
usage: python3 loop_test.py
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

LOOP = Path(__file__).resolve().parent / 'loop.py'


def ledger_row(issue, status, branch='-', pr='-', note='-', ts='2026-01-01T00:00:00Z'):
    return f'{ts}\t{issue}\t{status}\t{branch}\t{pr}\t{note}\n'


def queue_row(issue, title, area='-', blockers='-', waits='-', pick='-'):
    return f'{issue}\t{area}\t{title}\t\t1\t{blockers}\t{waits}\t{pick}\n'


class Board(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / 'repo'
        self.repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        self.state = self.repo / '.claude' / 'oversee'
        (self.state / 'loops').mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def loop(self, *args, session='A'):
        env = {k: v for k, v in os.environ.items() if k != 'CLAUDE_CODE_SESSION_ID'}
        ran = subprocess.run([sys.executable, str(LOOP), '--session', session, *args],
                             cwd=self.repo, capture_output=True, text=True, env=env)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        return ran.stdout

    def board(self, session='A'):
        return json.loads(self.loop('board', session=session))

    def write(self, name, text):
        (self.state / name).write_text(text)

    def test_empty_state_gives_empty_lists(self):
        board = self.board()
        self.assertIsNone(board['current'])
        self.assertEqual(board['queued'], [])
        self.assertEqual(board['finished'], [])
        self.assertEqual(board['more'], 0)

    def test_queue_with_no_ledger_is_all_queued_in_file_order(self):
        self.write('queue.tsv', queue_row(16, 'Third') + queue_row(14, 'First') +
                   queue_row(15, 'Second', blockers='#14'))
        board = self.board()
        self.assertEqual([q['issue'] for q in board['queued']], [16, 14, 15])
        self.assertEqual(board['queued'][2]['blockers'], '#14')
        self.assertEqual(board['queued'][0]['title'], 'Third')

    def test_live_loop_reads_its_own_queue(self):
        self.write('queue.tsv', queue_row(1, 'Shared'))
        self.loop('start', 'alpha')
        self.write('loops/A.queue.tsv', queue_row(2, 'Mine') + queue_row(3, 'Mine too'))
        self.assertEqual([q['issue'] for q in self.board()['queued']], [2, 3])
        self.loop('pause', 'a reason')
        self.assertEqual([q['issue'] for q in self.board()['queued']], [2, 3])
        self.loop('stop', 'done')
        self.assertEqual([q['issue'] for q in self.board()['queued']], [1])

    def test_ledger_folds_into_current_queued_and_finished(self):
        self.write('queue.tsv', ''.join(queue_row(n, f'Issue {n}') for n in (5, 6, 7, 8, 9, 10)))
        self.write('ledger.tsv',
                   ledger_row(5, 'start', 'feat/issue-5', note='session A pid 1') +
                   ledger_row(5, 'done', 'feat/issue-5', '20', 'ready') +
                   ledger_row(6, 'start', 'feat/issue-6', note='session A pid 1; pick: oldest') +
                   ledger_row(7, 'skipped', note='picked up Blocked') +
                   ledger_row(8, 'start', 'feat/issue-8', note='session AB pid 2') +
                   ledger_row(9, 'start', 'feat/issue-9', note='session A pid 1') +
                   ledger_row(9, 'withdrawn', 'feat/issue-9', note='session A pid 1') +
                   ledger_row(4, 'stalled', 'feat/issue-4', '#19', 'checks red'))
        board = self.board()
        self.assertEqual(board['current'], {
            'issue': 6, 'title': 'Issue 6', 'phase': 'working',
            'branch': 'feat/issue-6', 'since': '2026-01-01T00:00:00Z'})
        # 8 belongs to session AB, so it is neither this loop's current issue nor queued.
        self.assertEqual([q['issue'] for q in board['queued']], [9, 10])
        self.assertEqual([(f['issue'], f['status'], f['pr']) for f in board['finished']],
                         [(4, 'stalled', 19), (7, 'skipped', None), (5, 'done', 20)])
        self.assertIsNone(board['finished'][0]['title'])
        self.assertEqual(board['finished'][2]['title'], 'Issue 5')
        self.assertEqual(board['finished'][1]['note'], 'picked up Blocked')

    def test_runs_row_is_current_waiting_on_runs(self):
        self.write('ledger.tsv', ledger_row(3, 'start', 'feat/issue-3', note='session A pid 1') +
                   ledger_row(3, 'runs', 'feat/issue-3', note='session A pid 1'))
        board = self.board()
        self.assertEqual(board['current']['phase'], 'waiting on runs')
        self.assertNotIn('passes', board['current'])
        self.assertIsNone(self.board(session='B')['current'])

    def test_reopened_issue_is_current_not_finished(self):
        self.write('ledger.tsv', ledger_row(5, 'done', pr='20', note='ready') +
                   ledger_row(5, 'start', 'feat/issue-5', note='session A pid 1 resumed'))
        board = self.board()
        self.assertEqual(board['current']['issue'], 5)
        self.assertEqual(board['finished'], [])

    def test_partial_last_line_and_short_rows_are_skipped(self):
        self.write('ledger.tsv', ledger_row(5, 'done', pr='20') + 'garbage\n' +
                   '2026-01-01T00:00:00Z\t6\tdo')
        board = self.board()
        self.assertEqual([f['issue'] for f in board['finished']], [5])

    def test_finished_is_capped_and_counts_the_rest(self):
        self.write('ledger.tsv', ''.join(ledger_row(n, 'done', pr=str(n)) for n in range(1, 26)))
        board = self.board()
        self.assertEqual(len(board['finished']), 20)
        self.assertEqual(board['finished'][0]['issue'], 25)
        self.assertEqual(board['more'], 5)
        limited = json.loads(self.loop('board', '--limit', '3'))
        self.assertEqual(len(limited['finished']), 3)
        self.assertEqual(limited['more'], 22)

    def test_a_duplicate_queue_row_is_listed_once(self):
        self.write('queue.tsv', queue_row(1, 'Once') + queue_row(2, 'Two') + queue_row(1, 'Once'))
        self.assertEqual([q['issue'] for q in self.board()['queued']], [1, 2])

    def test_control_characters_are_stripped(self):
        self.write('queue.tsv', queue_row(1, 'Bad \x1b[31mred\x07 title'))
        self.assertEqual(self.board()['queued'][0]['title'], 'Bad [31mred title')

    def git(self, *args, check=True):
        subprocess.run(['git', '-C', str(self.repo), *args], capture_output=True, check=check)

    def test_repo_url_from_origin(self):
        self.assertIsNone(self.board()['repo'])
        for remote in ('git@github.com:o/r.git', 'https://github.com/o/r',
                       'https://github.com/o/r.git', 'ssh://git@github.com/o/r.git'):
            self.git('remote', 'remove', 'origin', check=False)
            self.git('remote', 'add', 'origin', remote)
            self.assertEqual(self.board()['repo'], 'https://github.com/o/r', remote)
        self.git('remote', 'set-url', 'origin', 'https://gitlab.com/o/r')
        self.assertIsNone(self.board()['repo'])

    def test_board_creates_no_files(self):
        bare = Path(self.tmp.name) / 'bare'
        bare.mkdir()
        subprocess.run(['git', 'init', '-q', str(bare)], check=True)

        def listing(root):
            return sorted(str(path.relative_to(root)) for path in root.rglob('*')
                          if '.git' not in path.parts)

        for root in (self.repo, bare):
            before = listing(root)
            ran = subprocess.run([sys.executable, str(LOOP), '--session', 'A', 'board'], cwd=root,
                                 capture_output=True, text=True)
            self.assertEqual(ran.returncode, 0, ran.stderr)
            self.assertEqual(listing(root), before)
        self.assertIsNone(json.loads(ran.stdout)['current'])


if __name__ == '__main__':
    unittest.main()
