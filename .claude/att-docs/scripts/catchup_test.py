#!/usr/bin/env python3
"""Checks catchup.py: add and its retries, add-checks, the test-all tally, pull request
and issue rows, and the wait arguments, against a stub gh that fails the way the real one
does.

usage: python3 scripts/catchup_test.py

The stub sits first on PATH, so catchup.gh runs it as a real process and add sees
gh's own stderr wording. Elsewhere gh is replaced in process. Pauses are skipped, so the
checks run in about a second.
"""
import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import catchup  # noqa: E402

STUB = """#!/usr/bin/env python3
import json, os, sys
state = os.environ['STUB_GH_STATE']
calls = int(open(state).read() or 0) + 1 if os.path.exists(state) else 1
open(state, 'w').write(str(calls))
if calls <= int(os.environ['STUB_GH_FAILS']):
    sys.stderr.write(os.environ['STUB_GH_ERROR'] + '\\n')
    sys.exit(1)
if sys.argv[-1].endswith('/jobs'):
    print(json.dumps({'jobs': [{'html_url': 'https://example.test/job/7'}]}))
else:
    print(json.dumps({'head_branch': 'fix/stub', 'html_url': 'https://example.test/run/42',
                      'display_title': os.environ.get('STUB_GH_TITLE', ''),
                      'path': os.environ.get('STUB_GH_PATH', '')}))
"""

NOT_FOUND = 'gh: Not Found (HTTP 404)'


class StubGh(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        gh = os.path.join(self.dir, 'gh')
        with open(gh, 'w') as f:
            f.write(STUB)
        os.chmod(gh, os.stat(gh).st_mode | stat.S_IEXEC)
        self.ledger = os.path.join(self.dir, 'ledger.tsv')
        self.state = os.path.join(self.dir, 'calls')
        path = self.dir + os.pathsep + os.environ.get('PATH', '')
        self.env = mock.patch.dict(os.environ, {'PATH': path, 'STUB_GH_STATE': self.state})
        self.env.start()
        self.sleep = mock.patch.object(catchup.time, 'sleep')
        self.sleep.start()

    def tearDown(self):
        self.sleep.stop()
        self.env.stop()

    def run_add(self, fails, error=NOT_FOUND):
        os.environ['STUB_GH_FAILS'] = str(fails)
        os.environ['STUB_GH_ERROR'] = error
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = catchup.main(['catchup.py', 'add', self.ledger, '42', 'stub label'])
        return code, out.getvalue()

    def calls(self):
        with open(self.state) as f:
            return int(f.read())


class AddRetry(StubGh):
    def test_two_404s_then_success_records_one_row(self):
        code, out = self.run_add(fails=2)
        rows = catchup.read_ledger(self.ledger)
        self.assertEqual(code, 0, out)
        self.assertEqual([r['run'] for r in rows], ['42'])
        self.assertEqual(rows[0]['job'], 'https://example.test/job/7')
        self.assertEqual(out.count('trying again'), 2, out)
        self.assertNotIn('Traceback', out)

    def test_adding_again_keeps_one_row(self):
        self.run_add(fails=0)
        os.remove(self.state)
        code, out = self.run_add(fails=2)
        self.assertEqual(code, 0, out)
        self.assertEqual(len(catchup.read_ledger(self.ledger)), 1)

    def test_three_404s_record_nothing_and_exit_nonzero(self):
        code, out = self.run_add(fails=3)
        self.assertEqual(code, 1, out)
        self.assertEqual(catchup.read_ledger(self.ledger), [])
        self.assertIn('add: run 42 not recorded: gh: Not Found (HTTP 404)', out)
        self.assertEqual(self.calls(), 3)
        self.assertNotIn('Traceback', out)

    def test_a_refusal_is_not_retried(self):
        code, out = self.run_add(fails=1, error='gh: Bad credentials (HTTP 401)')
        self.assertEqual(code, 1, out)
        self.assertEqual(self.calls(), 1)
        self.assertNotIn('trying again', out)

    def test_the_row_carries_the_display_title_with_its_spacing_folded(self):
        os.environ['STUB_GH_TITLE'] = 'Pin   consumers '
        code, out = self.run_add(fails=0)
        self.assertEqual(code, 0, out)
        self.assertEqual(catchup.read_ledger(self.ledger)[0]['title'], 'Pin consumers')

    def test_a_ci_run_links_the_run_without_reading_its_jobs(self):
        os.environ['STUB_GH_PATH'] = catchup.CI_WORKFLOW
        code, out = self.run_add(fails=0)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.calls(), 1)
        self.assertEqual(catchup.read_ledger(self.ledger)[0]['job'],
                         'https://example.test/run/42')

    def test_a_ledger_without_the_title_column_still_reads(self):
        with open(self.ledger, 'w') as f:
            f.write('earlier\tfix/stub\t41\tjob\tdone\tsuccess CI\n')
        code, out = self.run_add(fails=0)
        self.assertEqual(code, 0, out)
        rows = catchup.read_ledger(self.ledger)
        self.assertEqual([(r['run'], r['title']) for r in rows], [('41', ''), ('42', '')])


def stamped(*lines):
    """Lines as the jobs API returns a job log: a timestamp in front of every line."""
    return ''.join(f'2026-11-18T06:40:00.0000000Z {line}\n' for line in lines)


# A test-all run in the CI job, as scripts/test-all.sh prints it: one file passes, one
# fails with its log indented under it, and the static checks pass.
TEST_ALL_LOG = stamped(
    '##[group]Run bash scripts/test-all.sh',
    'bash scripts/test-all.sh',
    '##[endgroup]',
    '== Tests',
    'PASS  scripts/consumers_test.py',
    'FAIL  scripts/x.test.mjs (exit 1)',
    '      not ok 3 - reads the pin',
    '      ok 4 - writes the pin',
    '      # Subtest: thPASS  scripts/y.test.mjs',
    '      not ok 3 - reads the pin',
    '      not ok 5 - drops the pin',
    'PASS  scripts/z_test.py',
    'SKIP  hooks module tests',
    '',
    'Tests: 2 passed, 1 failed',
    '',
    '== Static checks',
    'shellcheck not installed; skipped (advisory)',
    '0 problem(s) found',
    'Static checks: passed',
    '',
    'FAILED:',
    '  scripts/x.test.mjs',
    '##[error]Process completed with exit code 1.',
)
# Static checks that found a problem after every test passed.
STATIC_FAILED_LOG = stamped(
    '== Tests',
    'PASS  scripts/consumers_test.py',
    '',
    'Tests: 1 passed, 0 failed',
    '',
    '== Static checks',
    'ERROR  docs/a.md: line 3: link b.md does not resolve',
    '1 problem(s) found',
    'Static checks: failed',
    '',
    'FAILED:',
    '  static checks',
    '##[error]Process completed with exit code 1.',
)
GREEN_LOG = stamped(
    '== Tests',
    'PASS  scripts/consumers_test.py',
    '',
    'Tests: 1 passed, 0 failed',
    '',
    '== Static checks',
    '0 problem(s) found',
    'Static checks: passed',
    '',
    'All passed',
)


class TestAllTally(unittest.TestCase):
    """A CI run is tallied from the summary scripts/test-all.sh prints."""

    def test_a_failing_file_is_named_with_its_failure_lines(self):
        summary, lines = catchup.test_all_tally(TEST_ALL_LOG)
        self.assertEqual(summary, 'test-all: 2 passed, 1 failed; static checks passed')
        self.assertEqual(lines, ['  FAIL  scripts/x.test.mjs (exit 1)',
                                 '    not ok 3 - reads the pin',
                                 '    not ok 5 - drops the pin'])

    def test_a_python_failure_line_is_kept(self):
        log = TEST_ALL_LOG.replace('not ok 5 - drops the pin', 'FAIL: test_x (x_test.Pin)')
        self.assertIn('    FAIL: test_x (x_test.Pin)', catchup.test_all_tally(log)[1])

    def test_a_static_check_problem_is_named(self):
        summary, lines = catchup.test_all_tally(STATIC_FAILED_LOG)
        self.assertEqual(summary, 'test-all: 1 passed, 0 failed; static checks failed')
        self.assertEqual(lines, ['  ERROR  docs/a.md: line 3: link b.md does not resolve'])

    def test_a_green_run_prints_no_lines(self):
        self.assertEqual(catchup.test_all_tally(GREEN_LOG),
                         ('test-all: 1 passed, 0 failed; static checks passed', []))

    def test_a_run_stopped_before_the_static_checks_says_so(self):
        log = GREEN_LOG.split('== Static checks')[0]
        self.assertEqual(catchup.test_all_tally(log)[0],
                         'test-all: 1 passed, 0 failed; static checks did not finish')

    def test_a_log_without_the_tests_line_has_no_tally(self):
        self.assertIsNone(catchup.test_all_tally(stamped('npm ERR! code E404')))

    def test_lines_past_the_cap_are_counted(self):
        files = [f'FAIL  scripts/f{i}_test.py (exit 1)'
                 for i in range(catchup.CHECKS_ERROR_LINES + 5)]
        log = stamped(*files, 'Tests: 0 passed, 45 failed')
        lines = catchup.test_all_tally(log)[1]
        self.assertEqual(len(lines), catchup.CHECKS_ERROR_LINES + 1)
        self.assertEqual(lines[-1], '  ... 5 more lines in the saved log')

    def test_color_codes_are_taken_off(self):
        log = TEST_ALL_LOG.replace('Tests: 2', '\x1b[1mTests: 2').replace('failed\n',
                                                                          'failed\x1b[0m\n', 1)
        self.assertEqual(catchup.test_all_tally(log)[0],
                         'test-all: 2 passed, 1 failed; static checks passed')


JOB_LINK = 'https://github.com/o/r/actions/runs/42/job/108'


class FinishLog(unittest.TestCase):
    """finish reads a finished run's log from the jobs API and tallies it."""

    def run_finish(self, job_link, jobs=({'id': 108},), log=TEST_ALL_LOG,
                   conclusion='success'):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ledger = os.path.join(tmp.name, 'ledger.tsv')
        row = {'label': 'stub', 'run': '42', 'job': job_link}
        calls = []

        def fake_gh(*gh_args, timeout=None):
            calls.append(gh_args)
            if gh_args[-1].endswith('/runs/42/jobs'):
                return json.dumps({'jobs': list(jobs)})
            if gh_args[-1].endswith('/actions/jobs/108'):
                return json.dumps(jobs[0])
            if gh_args[-1].endswith('/logs'):
                if isinstance(log, Exception):
                    raise log
                return log
            raise AssertionError(f'unexpected gh call {gh_args}')

        out = io.StringIO()
        with mock.patch.object(catchup, 'gh', side_effect=fake_gh), \
                contextlib.redirect_stdout(out):
            done = catchup.finish(ledger, row, {'conclusion': conclusion,
                                                'path': catchup.CI_WORKFLOW, 'name': 'CI'})
        saved = None
        if os.path.exists(ledger + '.logs/42.log'):
            with open(ledger + '.logs/42.log') as f:
                saved = f.read()
        return done, row, out.getvalue(), calls, saved

    def test_a_succeeded_job_with_no_steps_is_read_again(self):
        succeeded = {'id': 108, 'steps': [], 'conclusion': 'success'}
        done, row, _, _, _ = self.run_finish(JOB_LINK, jobs=(succeeded,),
                                             log=RuntimeError(NOT_FOUND))
        self.assertFalse(done)
        self.assertNotIn('state', row)

    def test_a_job_that_failed_before_its_first_step_says_so(self):
        failed = {'id': 108, 'name': 'test-all', 'steps': [], 'conclusion': 'failure'}
        done, row, out, _, saved = self.run_finish(JOB_LINK, jobs=(failed,),
                                                   log=RuntimeError(NOT_FOUND),
                                                   conclusion='failure')
        self.assertTrue(done)
        self.assertIn('test-all failed before its first step', saved)
        self.assertEqual(row['tally'], 'failure CI, no test-all summary')
        self.assertIn('  ##[error]test-all failed before its first step', out)

    def test_a_linked_job_that_never_started_is_done(self):
        done, row, _, _, _ = self.run_finish(JOB_LINK, jobs=({'id': 108, 'steps': []},),
                                             log=RuntimeError(NOT_FOUND), conclusion='failure')
        self.assertTrue(done)
        self.assertEqual(row['tally'], 'failure, no log (no job ran)')

    def test_a_job_link_reads_that_job_log_alone(self):
        done, row, out, calls, saved = self.run_finish(JOB_LINK, conclusion='failure')
        self.assertTrue(done)
        self.assertEqual(calls, [('api', '--allow-escape-sequences',
                                  'repos/{owner}/{repo}/actions/jobs/108/logs')])
        self.assertEqual(saved, TEST_ALL_LOG)
        self.assertEqual(row['tally'],
                         'failure test-all: 2 passed, 1 failed; static checks passed')
        self.assertIn('  FAIL  scripts/x.test.mjs (exit 1)\n    not ok 3 - reads the pin',
                      out)
        self.assertIn('  log: ', out)

    def test_a_gh_without_the_escape_flag_reads_the_log_without_it(self):
        calls = []

        def fake_gh(*gh_args, timeout=None):
            calls.append(gh_args)
            if '--allow-escape-sequences' in gh_args:
                raise RuntimeError('unknown flag: --allow-escape-sequences')
            return GREEN_LOG

        with mock.patch.object(catchup, 'gh', side_effect=fake_gh):
            self.assertEqual(catchup.job_log(108), GREEN_LOG)
        self.assertEqual(calls[-1], ('api', 'repos/{owner}/{repo}/actions/jobs/108/logs'))

    def test_an_empty_log_leaves_the_row_open_for_the_next_check(self):
        done, row, out, _, saved = self.run_finish(JOB_LINK, log='')
        self.assertFalse(done)
        self.assertNotIn('state', row)
        self.assertIsNone(saved)
        self.assertIn('log came back empty, will retry next check', out)

    def test_a_run_link_reads_every_job_the_run_lists(self):
        _, _, _, calls, saved = self.run_finish('https://github.com/o/r/actions/runs/42',
                                                jobs=({'id': 108}, {'id': 109}))
        self.assertEqual([c[-1].rsplit('/', 2)[-2] for c in calls[1:]], ['108', '109'])
        self.assertEqual(saved, TEST_ALL_LOG * 2)

    def test_a_failed_log_fetch_leaves_a_green_run_open(self):
        done, row, out, _, _ = self.run_finish(JOB_LINK, log=RuntimeError(NOT_FOUND))
        self.assertFalse(done)
        self.assertNotIn('state', row)
        self.assertIn(f'log fetch failed: {NOT_FOUND}, will retry next check', out)

    def test_a_run_cancelled_before_its_job_started_is_done(self):
        # A run cancelled while queued lists no job, so there is no log to read.
        done, row, out, calls, saved = self.run_finish(
            'https://github.com/o/r/actions/runs/42', jobs=(), log='', conclusion='cancelled')
        self.assertTrue(done)
        self.assertEqual(len(calls), 1)
        self.assertEqual(row['state'], 'done')
        self.assertEqual(row['tally'], 'cancelled, no log (no job ran)')
        self.assertIsNone(saved)
        self.assertIn('done: stub - ', out)
        self.assertNotIn('retry', out)

    def test_a_cancelled_run_whose_log_is_not_found_is_done(self):
        done, row, _, _, _ = self.run_finish(JOB_LINK, log=RuntimeError(NOT_FOUND),
                                             conclusion='cancelled')
        self.assertTrue(done)
        self.assertEqual(row['tally'], f'cancelled, no log (log fetch failed: {NOT_FOUND})')

    def test_a_skipped_run_with_no_log_is_done(self):
        done, row, _, _, _ = self.run_finish(JOB_LINK, log='', conclusion='skipped')
        self.assertTrue(done)
        self.assertTrue(row['tally'].startswith('skipped, no log'))

    def test_a_cancelled_run_with_a_log_is_tallied_from_it(self):
        done, row, _, _, saved = self.run_finish(JOB_LINK, conclusion='cancelled')
        self.assertTrue(done)
        self.assertEqual(saved, TEST_ALL_LOG)
        self.assertTrue(row['tally'].startswith('cancelled test-all: 2 passed'))

    def test_a_rerun_tally_names_its_attempt(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        row = {'label': 'stub', 'run': '42', 'job': JOB_LINK}
        with mock.patch.object(catchup, 'gh', return_value=GREEN_LOG), \
                contextlib.redirect_stdout(io.StringIO()):
            catchup.finish(os.path.join(tmp.name, 'ledger.tsv'), row,
                           {'conclusion': 'success', 'run_attempt': 2})
        self.assertEqual(row['tally'], 'success test-all: 1 passed, 0 failed; '
                                       'static checks passed (attempt 2)')

    def test_another_workflow_without_a_summary_is_named(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        row = {'label': 'stub', 'run': '42', 'job': JOB_LINK}
        with mock.patch.object(catchup, 'gh', return_value=stamped('packed')), \
                contextlib.redirect_stdout(io.StringIO()):
            catchup.finish(os.path.join(tmp.name, 'ledger.tsv'), row,
                           {'conclusion': 'success', 'name': 'Pack compare'})
        self.assertEqual(row['tally'], 'success Pack compare')


CHECKS_RUN_URL = 'https://github.com/o/r/actions/runs/77'
# A step that fails before test-all runs prints its findings as plain output and ends
# on the step's error line.
CHECKS_LOG = ('2026-10-22T18:00:00.0000000Z ##[group]Run npm ci\n'
              '2026-10-22T18:00:00.0000000Z shell: /usr/bin/bash -e {0}\n'
              '2026-10-22T18:00:00.0000000Z ##[endgroup]\n'
              '2026-10-22T18:00:01.0000000Z npm install started\n'
              '2026-10-22T18:00:02.0000000Z npm ERR! code E404\n'
              '2026-10-22T18:00:03.0000000Z npm ERR! 404 Not Found - left-pad\n'
              '2026-10-22T18:00:04.0000000Z ##[error]Process completed with exit code 1.\n'
              '2026-10-22T18:00:05.0000000Z ##[error]Process completed with exit code 1.\n')
TITLE = 'CI on pull request 5'


def pr_run(run_id, status='completed'):
    return {'id': run_id, 'path': catchup.CI_WORKFLOW, 'name': 'CI',
            'event': 'pull_request', 'html_url': f'https://github.com/o/r/actions/runs/{run_id}',
            'head_branch': 'fix/stub', 'display_title': 'Fix the stub', 'status': status}


def check_row(run, state='waiting', tally='', branch='fix/stub'):
    return {'label': TITLE, 'branch': branch, 'run': run,
            'job': f'https://github.com/o/r/actions/runs/{run}', 'state': state,
            'tally': tally, 'title': TITLE}


class AddChecks(unittest.TestCase):
    """add-checks records the CI run on a pull request's head commit."""

    def run_add_checks(self, listed, rows=(), local='abc123def456', head_repo='o/r',
                       mergeable=True, state='open'):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ledger = os.path.join(tmp.name, 'ledger.tsv')
        if rows:
            catchup.write_ledger(ledger, list(rows))
        calls = []

        def fake_gh(*gh_args, timeout=None):
            calls.append(gh_args[-1])
            if gh_args[-1].endswith('/pulls/5'):
                return json.dumps({'mergeable': mergeable, 'state': state,
                                   'base': {'repo': {'full_name': 'o/r'}},
                                   'head': {'sha': 'abc123def456', 'ref': 'fix/stub',
                                            'repo': {'full_name': head_repo}}})
            if gh_args[-1].endswith('/git/ref/heads/fix/stub'):
                return json.dumps({'object': {'sha': local}})
            if '/workflows/ci.yml/runs?head_sha=' in gh_args[-1]:
                return json.dumps({'workflow_runs': listed})
            raise AssertionError(f'unexpected gh call {gh_args}')

        out, clock = io.StringIO(), [0]

        def fake_sleep(seconds):
            clock[0] += seconds

        with mock.patch.object(catchup, 'gh', side_effect=fake_gh), \
                mock.patch.object(catchup.time, 'monotonic', side_effect=lambda: clock[0]), \
                mock.patch.object(catchup.time, 'sleep', side_effect=fake_sleep), \
                contextlib.redirect_stdout(out):
            code = catchup.main(['catchup.py', 'add-checks', ledger, '#5'])
        return code, catchup.read_ledger(ledger), out.getvalue(), calls

    def test_the_newest_run_is_recorded_linking_the_run(self):
        code, rows, out, calls = self.run_add_checks([pr_run(70), pr_run(77)])
        self.assertEqual(code, 0, out)
        self.assertEqual([(r['run'], r['job'], r['label'], r['title']) for r in rows], [
            ('77', 'https://github.com/o/r/actions/runs/77', TITLE, TITLE)])
        self.assertTrue(all('event=pull_request' in c and 'head_sha=abc123def456' in c
                            for c in calls if 'head_sha' in c), calls)
        self.assertFalse(any(c.endswith('/jobs') or c.endswith('/runs/77') for c in calls),
                         calls)

    def test_a_label_given_names_the_row(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ledger = os.path.join(tmp.name, 'ledger.tsv')
        with mock.patch.object(catchup, 'add_read', side_effect=[
                {'state': 'open', 'mergeable': True, 'base': {'repo': {'full_name': 'o/r'}},
                 'head': {'sha': 'abc', 'ref': 'fix/stub', 'repo': {'full_name': 'x/r'}}},
                {'workflow_runs': [pr_run(77)]}]), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(catchup.add_checks(ledger, '5', 'my checks'), 0)
        row = catchup.read_ledger(ledger)[0]
        self.assertEqual((row['label'], row['title']), ('my checks', TITLE))

    def test_an_earlier_push_row_is_replaced(self):
        earlier = check_row('60', state='in_progress')
        # The push cancels the earlier run, which can settle before add-checks records.
        done = check_row('50', state='done', tally='cancelled test-all: 1 passed, 0 failed')
        other = check_row('61', branch='fix/other')
        _, rows, _, _ = self.run_add_checks([pr_run(77)], rows=[done, earlier, other])
        self.assertEqual([r['run'] for r in rows], ['61', '77'])

    def test_a_run_already_done_is_reported_not_reopened(self):
        done = dict(check_row('77', state='done', tally='failure CI, no test-all summary'),
                    title='Fix the stub')
        code, rows, out, _ = self.run_add_checks([pr_run(77)], rows=[done])
        self.assertEqual(code, 0, out)
        self.assertEqual(rows, [done])
        self.assertIn('failure CI, no test-all summary', out)
        # A rerun keeps the run id and is recorded again, running or finished.
        for rerun in (pr_run(77, 'in_progress'), dict(pr_run(77), run_attempt=2)):
            _, rows, _, _ = self.run_add_checks([rerun], rows=[done])
            self.assertEqual([r['state'] for r in rows], ['waiting'])
        attempt_2 = dict(done, tally='success test-all: 1 passed, 0 failed (attempt 2)')
        _, rows, _, _ = self.run_add_checks([dict(pr_run(77), run_attempt=2)], rows=[attempt_2])
        self.assertEqual(rows, [attempt_2])

    def test_a_rerun_finishing_is_handed_back(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ledger = os.path.join(tmp.name, 'ledger.tsv')
        row = check_row('77', state='done', tally='failure test-all: 1 passed, 1 failed')
        catchup.write_ledger(ledger, [row])
        before = catchup.done_rows(ledger)
        catchup.write_ledger(ledger, [dict(row, tally='success test-all (attempt 2)')])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(catchup.report_finished(ledger, before))

    def test_the_merge_watch_row_and_other_runs_are_kept(self):
        watch = dict(check_row('pr:5', state='open'), job='')
        tests = dict(check_row('76'), title='Fix the stub')
        _, rows, _, _ = self.run_add_checks([pr_run(77)], rows=[watch, tests])
        self.assertEqual([r['run'] for r in rows], ['pr:5', '76', '77'])

    def test_the_pushed_head_is_read_from_origin(self):
        _, _, _, calls = self.run_add_checks([pr_run(77)], local='fff999')
        self.assertTrue(any('head_sha=fff999' in c for c in calls), calls)

    def test_a_fork_reads_the_pull_request_head(self):
        _, _, _, calls = self.run_add_checks([pr_run(77)], local='fff999', head_repo='x/r')
        self.assertTrue(any('head_sha=abc123def456' in c for c in calls), calls)

    def test_another_branch_run_on_the_commit_is_passed_over(self):
        other = dict(pr_run(78), head_branch='fix/other')
        _, rows, _, _ = self.run_add_checks([pr_run(77), other])
        self.assertEqual([r['run'] for r in rows], ['77'])

    def test_a_conflict_is_named_when_no_run_starts(self):
        code, _, out, _ = self.run_add_checks([], mergeable=False)
        self.assertEqual(code, catchup.NO_CHECK_RUNS)
        self.assertIn('conflicts with its base, so no CI run starts', out)

    def test_no_run_records_nothing_and_exits_3(self):
        code, rows, out, _ = self.run_add_checks([])
        self.assertEqual(code, catchup.NO_CHECK_RUNS, out)
        self.assertEqual(rows, [])
        self.assertIn('add-checks: no CI run on pull request 5 at abc123def', out)
        self.assertIn('CI runs on every pull request', out)
        self.assertNotIn('paths-ignore', out)

    def finish_checks(self, jobs_logs, skipped=()):
        row = {'label': 'checks', 'run': '77', 'job': CHECKS_RUN_URL}
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)

        def fake_gh(*gh_args, timeout=None):
            if gh_args[-1].endswith('/runs/77/jobs'):
                return json.dumps({'jobs': [
                    {'id': i, 'conclusion': 'skipped' if i in skipped else 'failure',
                     'steps': [] if i in skipped else [{'started_at': '2026-10-22T18:00Z'}]}
                    for i in range(len(jobs_logs))]})
            log = jobs_logs[int(gh_args[-1].rsplit('/', 2)[-2])]
            if isinstance(log, Exception):
                raise log
            return log

        out = io.StringIO()
        with mock.patch.object(catchup, 'gh', side_effect=fake_gh), \
                contextlib.redirect_stdout(out):
            done = catchup.finish(os.path.join(tmp.name, 'ledger.tsv'), row,
                                  dict(pr_run(77), conclusion='failure'))
        return done, row, out.getvalue()

    def test_a_run_without_a_summary_is_tallied_with_the_lines_above_its_errors(self):
        done, row, out = self.finish_checks([CHECKS_LOG])
        self.assertTrue(done)
        self.assertEqual(row['tally'], 'failure CI, no test-all summary')
        self.assertIn('  npm ERR! code E404', out)
        self.assertIn('  npm install started', out)
        self.assertEqual(out.count('Process completed with exit code 1.'), 1, out)
        self.assertNotIn('##[group]', out)
        self.assertNotIn('shell:', out)

    def test_a_run_with_a_summary_ignores_the_error_lines_of_other_steps(self):
        log = CHECKS_LOG + GREEN_LOG
        done, row, out = self.finish_checks([log])
        self.assertEqual(row['tally'], 'failure test-all: 1 passed, 0 failed; '
                                       'static checks passed')
        self.assertNotIn('npm ERR!', out)

    def test_error_lines_past_the_cap_are_counted(self):
        log = ''.join(f'2026-10-22T18:00:00.0000000Z ##[error]finding {i}\n'
                      for i in range(catchup.CHECKS_ERROR_LINES + 5))
        lines = catchup.check_errors([log])
        self.assertEqual(len(lines), catchup.CHECKS_ERROR_LINES + 1)
        self.assertEqual(lines[-1], '  ... 5 more lines in the saved log')

    def test_every_error_line_is_kept_past_long_output(self):
        job = ''.join(f'2026-10-22T18:00:00.0000000Z out {i}\n' for i in range(60))
        job += '2026-10-22T18:00:01.0000000Z ##[error]Process completed with exit code 1.\n'
        lines = catchup.check_errors([job, job.replace('out', 'scan')])
        self.assertEqual(len(lines), catchup.CHECKS_ERROR_LINES + 1)
        self.assertEqual(lines.count('  ##[error]Process completed with exit code 1.'), 2)
        self.assertEqual(lines[0], '  out 41')
        self.assertEqual(lines[-1], '  ... 82 more lines in the saved log')

    def test_a_step_group_and_a_second_failing_step_are_shown(self):
        stamp = '2026-10-22T18:00:00.0000000Z '
        job = ''.join(stamp + line + '\n' for line in (
            '##[group]Run npm ci', 'shell: /usr/bin/bash -e {0}', '##[endgroup]',
            'npm ERR! code E404', '##[group]Resolution', 'npm ERR! 404 left-pad',
            '##[endgroup]', '##[error]npm ci failed with exit 1',
            '##[group]Run git sparse-checkout disable', '##[endgroup]', 'fatal: not a repo',
            '##[error]Process completed with exit code 128.'))
        self.assertEqual(catchup.check_errors([job]), [
            '  npm ERR! code E404', '  npm ERR! 404 left-pad',
            '  ##[error]npm ci failed with exit 1', '  fatal: not a repo',
            '  ##[error]Process completed with exit code 128.'])

    def test_a_silent_failing_step_is_its_own_error(self):
        stamp = '2026-10-22T18:00:00.0000000Z '
        error = '##[error]Process completed with exit code 1.'
        job = ''.join(stamp + line + '\n' for line in (
            '##[group]Run scan', '##[endgroup]', 'docs/a.md: bad link', error, error,
            '##[group]Run credential scan', '##[endgroup]', error))
        self.assertEqual(catchup.check_errors([job]),
                         ['  docs/a.md: bad link', '  ' + error, '  ' + error])

    def test_a_conflict_on_an_older_head_is_not_taken(self):
        # The pull request's record still shows the head before the push that resolved it.
        code, rows, out, _ = self.run_add_checks([], local='fff999', mergeable=False)
        self.assertEqual(code, catchup.NO_CHECK_RUNS)
        self.assertIn('not yet worked out', out)
        _, rows, _, _ = self.run_add_checks([pr_run(77)], mergeable=False)
        self.assertEqual([r['run'] for r in rows], ['77'])

    def test_unused_room_goes_to_the_longer_output(self):
        stamp = '2026-10-22T18:00:00.0000000Z '
        job = ''.join(f'{stamp}finding {i}\n' for i in range(30))
        job += f'{stamp}##[error]Lint failed\n{stamp}##[group]Run next\n{stamp}##[endgroup]\n'
        job += f'{stamp}##[error]Process completed with exit code 1.\n'
        lines = catchup.check_errors([job])
        self.assertEqual(len(lines), 32)
        self.assertEqual(lines[0], '  finding 0')

    def test_a_cancelled_job_that_ran_is_read_again(self):
        def fake_gh(*gh_args, timeout=None):
            if gh_args[-1].endswith('/jobs'):
                return json.dumps({'jobs': [{'id': 1, 'conclusion': 'cancelled',
                                             'steps': [{'started_at': '2026-10-22T18:00Z'}]}]})
            raise RuntimeError(NOT_FOUND)

        with mock.patch.object(catchup, 'gh', side_effect=fake_gh):
            self.assertRaises(RuntimeError, catchup.job_logs, '77')

    def test_a_skipped_job_is_passed_over(self):
        done, _, out = self.finish_checks([RuntimeError(NOT_FOUND), CHECKS_LOG], skipped={0})
        self.assertTrue(done)
        self.assertIn('npm ERR! code E404', out)

    def test_the_error_lines_are_saved_for_add_checks(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ledger = os.path.join(tmp.name, 'ledger.tsv')
        row = check_row('77', state='done', tally='failure test-all: 1 passed, 1 failed')
        catchup.write_ledger(ledger, [row])
        os.makedirs(ledger + '.logs')
        with open(catchup.saved_log(ledger, '77', 'errors'), 'w') as f:
            f.write('  FAIL  scripts/x.test.mjs (exit 1)\n')
        with mock.patch.object(catchup, 'add_read', side_effect=[
                {'state': 'open', 'mergeable': True, 'base': {'repo': {'full_name': 'o/r'}},
                 'head': {'sha': 'abc', 'ref': 'fix/stub', 'repo': {'full_name': 'x/r'}}},
                {'workflow_runs': [pr_run(77)]}]), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(catchup.add_checks(ledger, '5', ''), 0)
        self.assertIn('  FAIL  scripts/x.test.mjs (exit 1)', out.getvalue())

    def test_finish_saves_the_lines_it_prints(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ledger = os.path.join(tmp.name, 'ledger.tsv')
        row = {'label': 'checks', 'run': '77', 'job': CHECKS_RUN_URL + '/job/9'}
        with mock.patch.object(catchup, 'gh', return_value=TEST_ALL_LOG), \
                contextlib.redirect_stdout(io.StringIO()):
            catchup.finish(ledger, row, dict(pr_run(77), conclusion='failure'))
        with open(catchup.saved_log(ledger, '77', 'errors')) as f:
            self.assertEqual(f.read().splitlines()[0], '  FAIL  scripts/x.test.mjs (exit 1)')

    def test_a_conflict_drops_the_earlier_push_row(self):
        code, rows, _, _ = self.run_add_checks([], rows=[check_row('60')], mergeable=False)
        self.assertEqual(code, catchup.NO_CHECK_RUNS)
        self.assertEqual(rows, [])

    def test_no_run_drops_the_earlier_push_row(self):
        code, rows, out, _ = self.run_add_checks([], rows=[check_row('60')])
        self.assertEqual(code, catchup.NO_CHECK_RUNS)
        self.assertEqual(rows, [])
        self.assertIn('run add-checks once more', out)

    def test_a_closed_pull_request_drops_the_earlier_push_row(self):
        code, rows, _, _ = self.run_add_checks([], rows=[check_row('60')], state='closed')
        self.assertEqual(code, 1)
        self.assertEqual(rows, [])

    def test_a_run_listing_this_and_another_pull_request_is_taken(self):
        run = pr_run(77)
        run['pull_requests'] = [{'number': 9}, {'number': 5}]
        _, rows, _, _ = self.run_add_checks([run])
        self.assertEqual([r['run'] for r in rows], ['77'])

    def test_another_pull_requests_run_on_the_branch_is_passed_over(self):
        other, own = pr_run(78), pr_run(77)
        other['pull_requests'], own['pull_requests'] = [{'number': 9}], [{'number': 5}]
        _, rows, _, _ = self.run_add_checks([other, own])
        self.assertEqual([r['run'] for r in rows], ['77'])

    def test_a_run_whose_jobs_never_started_is_done(self):
        done, row, out = self.finish_checks([RuntimeError(NOT_FOUND)], skipped={0})
        self.assertTrue(done)
        self.assertEqual(row['tally'], 'failure, no log (no job ran)')

    def test_a_job_log_not_ready_leaves_the_row_open(self):
        done, row, out = self.finish_checks([RuntimeError(NOT_FOUND), CHECKS_LOG])
        self.assertFalse(done)
        self.assertNotIn('state', row)
        self.assertIn('will retry next check', out)


class Check(unittest.TestCase):
    """check settles what finished and reads a notified run by id."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ledger = os.path.join(tmp.name, 'ledger.tsv')
        catchup.write_ledger(self.ledger, [{
            'label': 'ci run', 'branch': 'fix/stub', 'run': '42',
            'job': 'https://github.com/o/r/actions/runs/42', 'state': 'waiting', 'tally': '',
            'title': ''}])

    def run_check(self, fake_gh, notified=None):
        out = io.StringIO()
        with mock.patch.object(catchup, 'gh', side_effect=fake_gh), \
                contextlib.redirect_stdout(out):
            left = catchup.check(self.ledger, notified)
        return left, out.getvalue()

    def test_a_run_cancelled_before_its_job_started_is_done_after_one_check(self):
        run = {'id': 42, 'status': 'completed', 'conclusion': 'cancelled'}

        def fake_gh(*gh_args, timeout=None):
            if '/actions/runs?branch=fix/stub' in gh_args[-1]:
                return json.dumps({'workflow_runs': [run]})
            if gh_args[-1].endswith('/runs/42/jobs'):
                return json.dumps({'jobs': []})
            raise AssertionError(f'unexpected gh call {gh_args}')

        left, out = self.run_check(fake_gh)
        self.assertEqual(left, 0, out)
        self.assertEqual(catchup.read_ledger(self.ledger)[0]['state'], 'done')
        self.assertIn('1 of 1 done; still waiting: none', out)

    def test_a_notified_run_is_read_by_id_and_tallied(self):
        run = {'id': 42, 'status': 'completed', 'conclusion': 'success',
               'path': catchup.CI_WORKFLOW, 'name': 'CI'}
        calls = []

        def fake_gh(*gh_args, timeout=None):
            calls.append(gh_args[-1])
            if gh_args[-1].endswith('/actions/runs/42'):
                return json.dumps(run)
            if gh_args[-1].endswith('/runs/42/jobs'):
                return json.dumps({'jobs': [{'id': 5}]})
            if gh_args[-1].endswith('/jobs/5/logs'):
                return GREEN_LOG
            raise AssertionError(f'unexpected gh call {gh_args}')

        left, out = self.run_check(fake_gh, {'42'})
        self.assertEqual(left, 0, out)
        self.assertFalse(any('?branch=' in c for c in calls), calls)
        row = catchup.read_ledger(self.ledger)[0]
        self.assertEqual(row['tally'], 'success test-all: 1 passed, 0 failed; '
                                       'static checks passed')

    def test_a_running_run_takes_its_status(self):
        def fake_gh(*gh_args, timeout=None):
            return json.dumps({'workflow_runs': [{'id': 42, 'status': 'in_progress'}]})

        left, out = self.run_check(fake_gh)
        self.assertEqual(left, 1)
        self.assertEqual(catchup.read_ledger(self.ledger)[0]['state'], 'in_progress')
        self.assertIn('0 of 1 done; still waiting: 1 in_progress', out)

    def test_a_failed_run_list_changes_nothing(self):
        left, out = self.run_check(mock.Mock(side_effect=RuntimeError('HTTP 502')))
        self.assertEqual(left, 1)
        self.assertIn('fix/stub: run list failed, nothing changed', out)
        self.assertEqual(catchup.read_ledger(self.ledger)[0]['state'], 'waiting')


OPEN_ISSUE = {'html_url': 'https://example.test/issues/9', 'state': 'open',
              'state_reason': None, 'closed_at': None}
CLOSED_ISSUE = {'html_url': 'https://example.test/issues/9', 'state': 'closed',
                'state_reason': 'completed', 'closed_at': '2026-09-23T18:00:00Z'}


class IssueRow(unittest.TestCase):
    """An issue row waits for a blocking issue to close and never counts as a run."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.ledger = os.path.join(self.dir, 'ledger.tsv')

    def run_main(self, *args, answer=OPEN_ISSUE):
        out = io.StringIO()
        with mock.patch.object(catchup, 'gh', return_value=json.dumps(answer)) as gh, \
                contextlib.redirect_stdout(out):
            code = catchup.main(['catchup.py', *args])
        return code, out.getvalue(), gh

    def test_an_open_issue_records_one_open_row(self):
        code, out, gh = self.run_main('add-issue', self.ledger, '#9', 'blocker')
        self.assertEqual(code, 0, out)
        self.assertIn('waiting for close: blocker - https://example.test/issues/9', out)
        self.assertEqual(gh.call_args.args, ('api', 'repos/{owner}/{repo}/issues/9'))
        rows = catchup.read_ledger(self.ledger)
        self.assertEqual([(r['run'], r['state']) for r in rows], [('issue:9', 'open')])

    def test_a_closed_issue_settles_at_once(self):
        code, out, _ = self.run_main('add-issue', self.ledger, '9', answer=CLOSED_ISSUE)
        self.assertEqual(code, 0, out)
        self.assertIn('issue: 9 closed', out)
        row = catchup.read_ledger(self.ledger)[0]
        self.assertEqual(row['state'], 'done')
        self.assertEqual(row['tally'], 'closed as completed at 2026-09-23T18:00:00Z')

    def test_a_failed_read_records_nothing_and_exits_nonzero(self):
        out = io.StringIO()
        with mock.patch.object(catchup, 'gh', side_effect=RuntimeError('HTTP 404')), \
                contextlib.redirect_stdout(out):
            code = catchup.main(['catchup.py', 'add-issue', self.ledger, '9'])
        self.assertEqual(code, 1)
        self.assertIn('add-issue: issue 9 not recorded', out.getvalue())
        self.assertEqual(catchup.read_ledger(self.ledger), [])

    def test_check_neither_reads_nor_counts_an_issue_row(self):
        self.run_main('add-issue', self.ledger, '9')
        code, out, gh = self.run_main('check', self.ledger)
        self.assertEqual(code, 0, out)
        gh.assert_not_called()

    def test_a_closed_issue_is_reported(self):
        self.run_main('add-issue', self.ledger, '9')
        before = catchup.done_rows(self.ledger)
        out = io.StringIO()
        with mock.patch.object(catchup, 'gh', return_value=json.dumps(CLOSED_ISSUE)), \
                contextlib.redirect_stdout(out):
            self.assertEqual(catchup.reconcile_rows(self.ledger), set())
            self.assertTrue(catchup.report_finished(self.ledger, before))
        self.assertIn('issue: 9 closed', out.getvalue())

    def test_the_forwarder_writes_an_issue_close_and_the_reader_keeps_it(self):
        push = object.__new__(catchup.Push)
        push.events = os.path.join(self.dir, 'events.jsonl')
        push.hook_file = os.path.join(self.dir, 'hook')
        push.seen = {}
        closed = {'action': 'closed', 'issue': {'number': 9, 'state_reason': 'completed',
                                                'closed_at': '2026-09-23T18:00:00Z'}}
        labeled = {'action': 'labeled', 'issue': {'number': 9}}
        with contextlib.redirect_stdout(io.StringIO()):
            push.pump([json.dumps(labeled).encode(), json.dumps(closed).encode()])
        with open(push.events, 'rb') as f:
            lines = f.read().splitlines()
        self.assertEqual(len(lines), 1)
        push.fold(lines[0])
        event = push.seen['issue:9']
        self.assertEqual(catchup.notice_tally(event),
                         'closed as completed at 2026-09-23T18:00:00Z')


class PushEvents(unittest.TestCase):
    """The forwarder's events reach every waiter through the shared events file."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.push = object.__new__(catchup.Push)
        self.push.events = os.path.join(tmp.name, 'events.jsonl')
        self.push.hook_file = os.path.join(tmp.name, 'hook')
        self.push.seen, self.push.handle = {}, None
        self.addCleanup(lambda: self.push.handle and self.push.handle.close())

    def pump(self, *events):
        with contextlib.redirect_stdout(io.StringIO()):
            self.push.pump([json.dumps(e).encode() for e in events])

    def test_a_merge_notice_settles_as_merged(self):
        self.pump({'action': 'synchronize', 'pull_request': {'number': 5}},
                  {'action': 'closed', 'pull_request': {
                      'number': 5, 'merged': True, 'merge_commit_sha': 'abcdef1234567',
                      'merged_at': '2026-11-18T06:00:00Z', 'head': {'ref': 'fix/stub'}}})
        self.push.read()
        self.assertEqual(catchup.notice_tally(self.push.seen['pr:5']),
                         'merged abcdef123 at 2026-11-18T06:00:00Z')

    def test_a_later_action_wins_over_an_earlier_one_delivered_late(self):
        run = {'id': 42, 'run_attempt': 1}
        self.pump({'action': 'completed', 'workflow_run': run},
                  {'action': 'in_progress', 'workflow_run': run})
        self.push.read()
        self.assertEqual(self.push.seen['42']['action'], 'completed')
        self.pump({'action': 'requested', 'workflow_run': dict(run, run_attempt=2)})
        self.push.read()
        self.assertEqual(self.push.seen['42']['action'], 'requested')

    def test_a_hook_line_says_a_forwarder_connected(self):
        self.pump({'hook_id': 7})
        self.assertTrue(self.push.read())
        self.assertEqual(self.push.hook, 7)
        self.assertFalse(self.push.read())

    def test_a_reader_follows_the_file_across_a_rename(self):
        self.pump({'action': 'completed', 'workflow_run': {'id': 1}})
        self.push.read()
        with mock.patch.object(catchup, 'EVENTS_ROTATE', 0):
            self.pump({'action': 'completed', 'workflow_run': {'id': 2}})
        self.pump({'action': 'completed', 'workflow_run': {'id': 3}})
        self.push.read()
        self.assertEqual(sorted(self.push.seen), ['1', '2', '3'])


def open_pr(mergeable):
    return {'url': 'https://example.test/pull/5', 'headRefName': 'fix/stub', 'state': 'OPEN',
            'mergedAt': None, 'closedAt': None, 'mergeCommit': None, 'mergeable': mergeable}


class PrConflict(unittest.TestCase):
    """A pull request row reports a conflict with its base once, and wait hands back on it."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ledger = os.path.join(tmp.name, 'ledger.tsv')

    def read(self, mergeable, *args):
        out = io.StringIO()
        with mock.patch.object(catchup, 'gh', return_value=json.dumps(open_pr(mergeable))), \
                contextlib.redirect_stdout(out):
            if args:
                catchup.main(['catchup.py', *args])
            else:
                catchup.reconcile_rows(self.ledger)
        return out.getvalue()

    def title(self):
        return catchup.read_ledger(self.ledger)[0]['title']

    def test_add_pr_records_an_open_row_read_from_the_checkout(self):
        out = io.StringIO()
        with mock.patch.object(catchup, 'gh',
                               return_value=json.dumps(open_pr('MERGEABLE'))) as gh, \
                contextlib.redirect_stdout(out):
            catchup.main(['catchup.py', 'add-pr', self.ledger, '5'])
        self.assertEqual(gh.call_args.args[:3], ('pr', 'view', '5'))
        self.assertNotIn('--repo', gh.call_args.args)
        self.assertNotIn('-R', gh.call_args.args)
        row = catchup.read_ledger(self.ledger)[0]
        self.assertEqual((row['run'], row['label'], row['state']),
                         ('pr:5', 'pull request 5', 'open'))
        self.assertIn('waiting for merge: pull request 5 - https://example.test/pull/5',
                      out.getvalue())

    def test_add_pr_settles_a_merged_pull_request_at_once(self):
        merged = dict(open_pr('UNKNOWN'), state='MERGED', mergedAt='2026-11-18T06:00:00Z',
                      mergeCommit={'oid': 'abcdef1234567'})
        out = io.StringIO()
        with mock.patch.object(catchup, 'gh', return_value=json.dumps(merged)), \
                contextlib.redirect_stdout(out):
            catchup.main(['catchup.py', 'add-pr', self.ledger, '5'])
        row = catchup.read_ledger(self.ledger)[0]
        self.assertEqual((row['state'], row['tally']),
                         ('done', 'merged abcdef123 at 2026-11-18T06:00:00Z'))
        self.assertIn('pr: 5 merged', out.getvalue())

    def test_add_pr_marks_a_conflict_it_finds(self):
        out = self.read('CONFLICTING', 'add-pr', self.ledger, '5', 'stub')
        self.assertIn('pr: 5 conflicting', out)
        self.assertTrue(self.title().startswith(catchup.CONFLICT_MARK))
        self.assertEqual(catchup.read_ledger(self.ledger)[0]['state'], 'open')

    def test_a_conflict_is_reported_once(self):
        self.read('MERGEABLE', 'add-pr', self.ledger, '5', 'stub')
        self.assertIn('pr: 5 conflicting', self.read('CONFLICTING'))
        self.assertNotIn('conflicting', self.read('CONFLICTING'))

    def test_unknown_leaves_the_mark_and_mergeable_clears_it(self):
        self.read('CONFLICTING', 'add-pr', self.ledger, '5', 'stub')
        self.read('UNKNOWN')
        self.assertTrue(self.title().startswith(catchup.CONFLICT_MARK))
        self.read('MERGEABLE')
        self.assertEqual(self.title(), '')
        self.assertIn('pr: 5 conflicting', self.read('CONFLICTING'))

    def test_wait_hands_back_on_a_new_conflict_only(self):
        self.read('MERGEABLE', 'add-pr', self.ledger, '5', 'stub')
        before, conflicts = catchup.done_rows(self.ledger), catchup.conflicted_rows(self.ledger)
        self.read('CONFLICTING')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertTrue(catchup.handed_back(self.ledger, before, False, conflicts))
            self.assertFalse(catchup.handed_back(
                self.ledger, before, False, catchup.conflicted_rows(self.ledger)))
            self.assertFalse(catchup.handed_back(self.ledger, before, True, conflicts))
        self.assertIn('wait: pull request 5 conflicts with its base branch', out.getvalue())

    def test_wait_hands_back_when_a_marked_conflict_clears_and_returns(self):
        self.read('CONFLICTING', 'add-pr', self.ledger, '5', 'stub')
        before, conflicts = catchup.done_rows(self.ledger), catchup.conflicted_rows(self.ledger)
        self.read('MERGEABLE')
        with mock.patch.object(catchup, 'utc', return_value='2099-01-01T00:00:00Z'):
            self.read('CONFLICTING')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(catchup.handed_back(self.ledger, before, False, conflicts))


class WaitArguments(unittest.TestCase):
    """`wait` reads its flags wherever they sit, and no ledger is never an empty one."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.ledger = os.path.join(self.dir, 'ledger.tsv')

    def run_main(self, *args):
        out = io.StringIO()
        with mock.patch.object(catchup, 'wait', return_value=0) as wait, \
                mock.patch.object(catchup, 'check') as check, \
                contextlib.redirect_stdout(out):
            code = catchup.main(['catchup.py', *args])
        return code, out.getvalue(), wait, check

    def write_ledger(self):
        with open(self.ledger, 'w') as f:
            f.write('')

    def test_flags_before_the_ledger_reach_wait(self):
        self.write_ledger()
        code, _, wait, _ = self.run_main('wait', '--all', '--interval', '600', self.ledger)
        self.assertEqual(code, 0)
        wait.assert_called_once_with(self.ledger, 600, True)

    def test_flags_after_the_ledger_reach_wait(self):
        self.write_ledger()
        code, _, wait, _ = self.run_main('wait', self.ledger, '--all')
        self.assertEqual(code, 0)
        wait.assert_called_once_with(self.ledger, catchup.MIN_INTERVAL, True)

    def test_an_interval_under_the_floor_is_raised_to_it(self):
        self.write_ledger()
        self.run_main('wait', self.ledger, '--interval', '5')[2].assert_called_once_with(
            self.ledger, catchup.MIN_INTERVAL, False)

    def test_flags_alone_exit_2_and_create_nothing(self):
        cwd = os.getcwd()
        os.chdir(self.dir)
        self.addCleanup(os.chdir, cwd)
        code, out, wait, _ = self.run_main('wait', '--all')
        self.assertEqual(code, 2)
        self.assertIn('no ledger given', out)
        wait.assert_not_called()
        self.assertEqual(os.listdir(self.dir), [])

    def test_a_bad_interval_or_option_exits_2(self):
        self.write_ledger()
        for args in (('--interval',), ('--interval', 'soon'), ('--every',), ('second.tsv',)):
            code, out, wait, _ = self.run_main('wait', self.ledger, *args)
            self.assertEqual(code, 2, args)
            self.assertTrue(out.startswith('wait: '), out)
            wait.assert_not_called()

    def test_a_missing_ledger_exits_2_for_wait_and_check(self):
        for command in ('wait', 'check'):
            code, out, wait, check = self.run_main(command, self.ledger)
            self.assertEqual(code, 2, command)
            self.assertIn(f'{command}: no ledger at {self.ledger}', out)
            wait.assert_not_called()
            check.assert_not_called()
        self.assertFalse(os.path.exists(self.ledger + '.lock'))

    def test_an_unknown_command_prints_the_usage_and_exits_2(self):
        for args in (('nope',), ('add', self.ledger), ('check',)):
            code, out, _, _ = self.run_main(*args)
            self.assertEqual(code, 2, args)
            self.assertIn('usage:', out)


if __name__ == '__main__':
    unittest.main()
