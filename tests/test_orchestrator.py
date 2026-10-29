"""orchestrator.py: the orchestrator widget's state, read from fixture files, and the files it writes.

The golden samples under tests/golden/orchestrator/<case>/ are what render() writes for each
case. After a change to the layout that is meant, write them again with
    ORCHESTRATOR_GOLDEN=write python3 -m unittest tests.test_orchestrator
and read the diff before committing it.
"""
import datetime
import json
import math
import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

import support

orchestrator = support.load_orchestrator()
import sessions  # noqa: E402

GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'golden', 'orchestrator')
OUTPUTS = ('widget.txt', 'draw.txt', 'regions.json', 'sessions.txt')
ME = '11111111-aaaa'
OTHER = '22222222-bbbb'
QUIET = '33333333-cccc'
NOW = 1000.0


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='orchestrator-test-')
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.f = support.OrchestratorFixture(self.root)
        cache = os.path.join(self.root, 'cache')
        for name, path in (('OUT', 'widget.txt'), ('DRAW', 'draw.txt'),
                           ('REGIONS', 'regions.json'), ('SESSIONS', 'sessions.txt')):
            p = mock.patch.object(orchestrator, name, os.path.join(cache, path))
            p.start()
            self.addCleanup(p.stop)
        for name, value in (('COLLAPSE', os.path.join(self.root, 'collapse-idle')),
                            ('SPLIT', os.path.join(self.root, 'split')),
                            ('_feeds', {}), ('_message_lines', {}),
                            ('LEDGERS', self.f.ledgers),
                            ('SCALE', 1)):
            p = mock.patch.object(orchestrator, name, value)
            p.start()
            self.addCleanup(p.stop)
        try:
            os.remove(orchestrator.SIZE)
        except FileNotFoundError:
            pass
        self.cache = cache

    def state(self, now=NOW):
        return orchestrator.read_state(self.f.hook_dir, self.f.sessions, self.f.proc, now=now)

    def three(self):
        """This session working, another and a third idle."""
        self.f.session(300, ME, 'Feed widget', status='busy')
        self.f.session(100, OTHER, 'Release 1.2')
        self.f.session(200, QUIET, 'Docs pass')

    def idle(self):
        """Three sessions, none of them working."""
        self.f.session(300, ME, 'Feed widget')
        self.f.session(100, OTHER, 'Release 1.2')
        self.f.session(200, QUIET, 'Docs pass')


class ReadState(Fixture):
    def test_sessions_are_listed_in_pid_order(self):
        self.three()
        s = self.state()['sessions']
        self.assertEqual([x['id'] for x in s], [OTHER, QUIET, ME])
        self.assertTrue(s[2]['busy'])

    def test_a_background_session_is_listed_and_a_spare_one_is_not(self):
        self.three()
        self.f.session(400, '99999999-jobs', 'Bridge Update', kind='bg')
        self.f.session(500, '88888888-jobs', '88888888', kind='bg', spare=True)
        got = self.state()['sessions']
        self.assertEqual([x['id'] for x in got], [OTHER, QUIET, ME, '99999999-jobs'])
        self.assertEqual([x['spare'] for x in got], [False] * 4)

    def test_a_spare_sessions_replies_are_not_in_the_feed(self):
        self.f.session(400, ME, 'A job', kind='bg', spare=True)
        self.f.feed(ME, 900.0, 'Done.')
        state = self.state()
        self.assertEqual((state['sessions'], state['feed']), ([], []))

    def test_a_session_waiting_for_input_in_the_cli_is_under_needs_input(self):
        self.three()
        self.f.session(400, '99999999-jobs', 'Relay Authority', kind='bg', status='waiting', waiting_for='input needed')
        by_id = {x['id']: x for x in self.state()['sessions']}
        self.assertTrue(by_id['99999999-jobs']['question'])
        self.assertEqual(orchestrator.status_group(by_id['99999999-jobs']), 'Needs input')
        self.assertFalse(by_id[ME]['question'])

    def test_waiting_on_ci_or_a_merge_by_the_sessions_ledger(self):
        self.three()
        flags = lambda sid: next(orchestrator.session_line(x) for x in self.state()['sessions']
                                 if x['id'] == sid).split('\t')[2].split(',')
        self.assertEqual(flags(OTHER), ['idle'])
        self.f.ledger(OTHER, ('pr:107', 'done'), ('pr:111', 'open'))
        self.assertEqual(flags(OTHER), ['waiting: merge'])
        self.f.ledger(OTHER, ('pr:111', 'open'), ('lp:2.1.0', 'open'))
        self.assertEqual(flags(OTHER), ['waiting: ci'])
        self.f.ledger(OTHER, ('pr:111', 'done'), ('issue:12', 'open'))
        self.assertEqual(flags(OTHER), ['idle'])                  # nothing it shows
        self.f.ledger(ME, ('pr:111', 'open'))
        self.assertEqual(flags(ME), ['busy'])                     # working, not waiting
        self.f.ledger(QUIET, ('pr:5', 'open'))
        self.assertEqual(flags(QUIET), ['waiting: merge'])        # one tag: waiting over idle

    def test_waiting_on_tests_while_a_test_run_is_under_the_session(self):
        self.three()
        flags = lambda sid: next(orchestrator.session_line(x) for x in self.state()['sessions']
                                 if x['id'] == sid).split('\t')[2]
        self.f.process(110, 100, 'bash', '-c', 'python3 -m unittest discover -s tests')
        self.assertEqual(flags(OTHER), 'idle')                    # the shell's -c is not one
        self.f.process(111, 110, '/usr/bin/python3', '-m', 'unittest', 'discover', '-s', 'tests')
        self.f.ledger(OTHER, ('pr:111', 'open'))
        self.assertEqual(flags(OTHER), 'waiting: tests')          # over waiting on a merge
        self.f.process(210, 200, 'python3', 'scripts/catchup_test.py')
        self.assertEqual(flags(QUIET), 'waiting: tests')          # over idle
        self.f.process(310, 300, 'npx', 'playwright', 'test')
        self.assertEqual(flags(ME), 'busy')                       # its own turn runs them

    def test_waiting_on_tests_while_a_ci_run_is_open_in_a_skills_ledger(self):
        self.three()
        flags = lambda sid: next(orchestrator.session_line(x) for x in self.state()['sessions']
                                 if x['id'] == sid).split('\t')[2]
        self.f.sweep(OTHER, 'done', 'done')
        self.assertEqual(flags(OTHER), 'idle')
        self.f.ledger(OTHER, ('pr:111', 'open'))
        self.f.sweep(OTHER, 'done', 'in_progress', 'waiting')
        self.assertEqual(flags(OTHER), 'waiting: tests')          # over waiting on a merge

    def test_waiting_on_a_systemd_unit_a_shell_polls(self):
        self.three()
        flags = lambda sid: next(orchestrator.session_line(x) for x in self.state()['sessions']
                                 if x['id'] == sid).split('\t')[2]
        loop = 'while systemctl --user is-active -q {} ; do sleep 60; done'
        self.f.process(110, 100, '/bin/bash', '-c', loop.format('build-pack-now'))
        self.assertEqual(flags(OTHER), 'waiting: local ai')
        self.f.process(210, 200, '/bin/bash', '-c', loop.format('nightly.service'))
        self.assertEqual(flags(QUIET), 'waiting: nightly.service')   # a unit with no tag
        self.f.process(211, 200, 'pytest')
        self.assertEqual(flags(QUIET), 'waiting: tests')          # a test run over a unit
        self.f.sweep(OTHER, 'in_progress')
        self.assertEqual(flags(OTHER), 'waiting: tests')          # a CI run over a unit too

    def test_what_counts_as_a_test_run(self):
        runs = (['pytest', '-q'], ['python3', '-I', '-m', 'pytest'], ['python3', 'tests/test_x.py'],
                ['python3', '-W', 'ignore', 'test_x.py'],
                ['bash', 'run_test.sh'], ['./run_test.sh'], ['npm', 'test'],
                ['npm', 'run', 'test'], ['go', 'test', './...'], ['cargo', 'test'],
                ['node', 'node_modules/.bin/playwright', 'test'])
        others = ([], ['grep', 'unittest'], ['bash', '-c', 'pytest'], ['python3', 'orchestrator.py'],
                  ['python3', '-m'], ['npm', 'install'], ['go', 'build'], ['playwright', 'show-report'])
        for argv in runs:
            self.assertTrue(orchestrator.is_test_run(argv), argv)
        for argv in others:
            self.assertFalse(orchestrator.is_test_run(argv), argv)

    def test_one_tag_a_question_first(self):
        self.three()
        flags = lambda sid: next(orchestrator.session_line(x) for x in self.state()['sessions']
                                 if x['id'] == sid).split('\t')[2]
        self.assertEqual((flags(ME), flags(OTHER), flags(QUIET)), ('busy', 'idle', 'idle'))
        self.f.session(300, ME, 'Feed widget', status='waiting')
        self.f.ledger(ME, ('pr:111', 'open'))
        self.assertEqual(flags(ME), 'question')                   # over busy and waiting
        self.f.session(200, QUIET, 'Docs pass', status='waiting')
        self.assertEqual(flags(QUIET), 'question')                # over idle

    def test_stale_and_socketless_sessions_are_left_out(self):
        self.f.session(100, ME, 'Live')
        self.f.session(200, OTHER, 'Gone', stale=True)
        self.f.session(300, QUIET, 'No socket', socket=False)
        self.f.session(400, 'dddd', 'Other kind', kind='sdk')
        self.assertEqual([x['name'] for x in self.state()['sessions']], ['Live'])

    def test_only_managed_sessions_are_listed(self):
        self.f.session(100, ME, 'Managed')
        self.f.session(200, OTHER, 'Plain', managed=False)
        self.f.session(300, QUIET, 'Marker gone')
        os.remove(os.path.join(self.f.hook_dir, QUIET + '.managed'))
        self.assertEqual([x['name'] for x in self.state()['sessions']], ['Managed'])
        self.assertEqual([x['id'] for x in sessions.list_sessions(self.f.sessions, self.f.proc, self.f.hook_dir)], [ME])

    def test_a_session_becomes_managed_when_its_marker_appears(self):
        self.f.session(100, ME, 'Plain', managed=False)
        self.assertEqual(self.state()['sessions'], [])
        self.f.file(ME + '.managed')
        self.assertEqual([x['name'] for x in self.state()['sessions']], ['Plain'])

    def test_duplicate_names_are_numbered_in_pid_order(self):
        self.f.session(300, QUIET, 'Widget')
        self.f.session(100, ME, 'Widget')
        self.f.session(200, OTHER, 'widget')
        names = {s['id']: s['name'] for s in sessions.list_sessions(self.f.sessions, self.f.proc, self.f.hook_dir)}
        self.assertEqual(names, {ME: 'Widget', OTHER: 'widget 2', QUIET: 'Widget 3'})

    def test_key_files_are_never_opened(self):
        self.f.session(100, ME, 'One')
        key = os.path.join(self.f.sessions, '100.key')
        with open(key, 'w') as fh:
            fh.write('secret')
        real = open

        def guarded(path, *a, **k):
            self.assertFalse(str(path).endswith('.key'), path)
            return real(path, *a, **k)

        with mock.patch('builtins.open', guarded):
            self.assertEqual(len(self.state()['sessions']), 1)


class Feed(Fixture):
    """The replies read from <session>.feed, and what the rows take from them."""

    def test_the_feed_is_the_listed_sessions_replies_oldest_first_under_the_names_the_list_gives(self):
        self.three()
        self.f.feed(ME, 990.0, 'Third.', name='old name')
        self.f.feed(OTHER, 900.0, 'First.')
        self.f.feed(QUIET, 950.0, 'Second.')
        self.f.session(400, '44444444-dddd', 'Plain', managed=False)
        self.f.feed('44444444-dddd', 980.0, 'Not listed.')
        feed = self.state()['feed']
        self.assertEqual([(e['text'], e['name'], e['session'], e['at']) for e in feed],
                         [('First.', 'Release 1.2', OTHER, 900.0), ('Second.', 'Docs pass', QUIET, 950.0),
                          ('Third.', 'Feed widget', ME, 990.0)])

    def test_an_entry_has_the_markdown_and_the_text_on_one_line(self):
        self.f.session(100, ME, 'One')
        self.f.feed(ME, 900.0, 'Two\n  lines​ here.', markdown='Two\r\n**lines** here.  ')
        entry = self.state()['feed'][0]
        self.assertEqual((entry['text'], entry['markdown']), ('Two lines here.', 'Two\n**lines** here.'))
        self.assertEqual(len(entry['key']), 40)

    def test_a_session_without_a_feed_has_no_replies(self):
        self.three()
        state = self.state()
        self.assertEqual(state['feed'], [])
        self.assertEqual([(s['age'], s['last']) for s in state['sessions']], [('', '')] * 3)

    def test_lines_that_are_not_replies_are_skipped(self):
        self.f.session(100, ME, 'One')
        self.f.file(ME + '.feed', '\n'.join((
            '{"at": 900, "text": "First."}',
            'not json at all',
            '[1, 2]',
            '"a string"',
            '{"text": "No time."}',
            '{"at": "soon", "text": "Not a time."}',
            '{"at": null, "text": "Null time."}',
            '{"at": 910, "text": "", "markdown": ""}',
            '{"at": 920, "text": 5, "markdown": ["x"]}',
            '{"at": 930, "text": "Cut off',
            '{"at": 940, "text": "Last.", "markdown": null}',
        )) + '\n')
        self.assertEqual([e['text'] for e in self.state()['feed']], ['First.', '5', 'Last.'])

    def test_a_last_line_still_being_written_is_skipped_until_it_is_whole(self):
        self.f.session(100, ME, 'One')
        self.f.feed(ME, 900.0, 'First.')
        with open(os.path.join(self.f.hook_dir, ME + '.feed'), 'a') as f:
            f.write('{"at": 950, "text": "Sec')
        self.assertEqual([e['text'] for e in self.state()['feed']], ['First.'])
        with open(os.path.join(self.f.hook_dir, ME + '.feed'), 'a') as f:
            f.write('ond."}\n')
        self.assertEqual([e['text'] for e in self.state()['feed']], ['First.', 'Second.'])

    def test_a_reply_with_only_markdown_is_kept_and_its_line_is_the_markdown(self):
        self.f.session(100, ME, 'One')
        self.f.feed(ME, 990.0, '', markdown='```bash\ngh run list\n```')
        s = self.state()['sessions'][0]
        self.assertEqual(s['last'], '```bash gh run list ```')

    def test_the_feed_is_read_again_when_the_file_changes_and_is_gone_with_it(self):
        self.f.session(100, ME, 'One')
        self.assertEqual(self.state()['feed'], [])
        self.f.feed(ME, 900.0, 'First.')
        self.assertEqual(len(self.state()['feed']), 1)
        self.f.feed(ME, 910.0, 'Second.')
        self.assertEqual([e['text'] for e in self.state()['feed']], ['First.', 'Second.'])
        os.remove(os.path.join(self.f.hook_dir, ME + '.feed'))
        self.assertEqual(self.state()['feed'], [])

    def test_the_feed_keeps_the_newest_replies_within_the_text_it_holds(self):
        self.f.session(100, ME, 'One')
        for i in range(orchestrator.SCROLLBACK_KEEP + 7):
            self.f.feed(ME, 100.0 + i, f'Reply {i}.')
        feed = self.state()['feed']
        self.assertEqual((len(feed), feed[0]['text'], feed[-1]['text']),
                         (orchestrator.SCROLLBACK_KEEP, 'Reply 7.', f'Reply {orchestrator.SCROLLBACK_KEEP + 6}.'))
        with mock.patch.object(orchestrator, 'SCROLLBACK_CHARS', 40):
            feed = self.state()['feed']
        self.assertTrue(1 < len(feed) < orchestrator.SCROLLBACK_KEEP)
        self.assertEqual(feed[-1]['text'], f'Reply {orchestrator.SCROLLBACK_KEEP + 6}.')

    def test_a_reply_says_how_long_ago_it_was(self):
        for seconds, want in ((-5, 'now'), (0, 'now'), (59, 'now'), (60, '1m'), (119, '1m'), (1500, '25m'),
                              (3599, '59m'), (3600, '1h'), (7300, '2h'), (86399, '23h'), (86400, '1d'),
                              (3 * 86400 + 5, '3d')):
            self.assertEqual(orchestrator.age_text(seconds), want, seconds)

    def test_a_row_ends_with_the_age_of_its_sessions_last_reply(self):
        self.three()
        self.f.feed(ME, NOW - 4000, 'Older.')
        self.f.feed(ME, NOW - 60, 'Newer.')
        self.f.feed(OTHER, NOW - 1500, 'Earlier.')
        state = self.state()
        ages = {s['id']: s['age'] for s in state['sessions']}
        self.assertEqual(ages, {ME: '1m', OTHER: '25m', QUIET: ''})
        by_id = {s['id']: s for s in state['sessions']}
        self.assertEqual(orchestrator.session_line(by_id[ME]).split('\t')[1], '1m')
        self.assertEqual(orchestrator.session_line(by_id[QUIET]).split('\t')[1], '')
        later = {s['id']: s['age'] for s in self.state(now=NOW + 3600)['sessions']}
        self.assertEqual(later, {ME: '1h', OTHER: '1h', QUIET: ''})                       # it follows the clock

    def test_a_quiet_session_keeps_its_age_when_a_busier_one_fills_the_pane(self):
        self.three()
        self.f.feed(QUIET, NOW - 1500, 'Long ago.')
        for i in range(orchestrator.SCROLLBACK_KEEP + 1):
            self.f.feed(ME, NOW - 100 + i, f'Reply {i}.')
        state = self.state()
        self.assertNotIn(QUIET, {e['session'] for e in state['feed']})
        self.assertEqual({s['id']: s['age'] for s in state['sessions']}[QUIET], '25m')

    def test_the_last_line_shows_while_the_reply_is_under_ten_minutes_old(self):
        self.three()
        self.f.feed(ME, NOW - 599, 'Newest reply.')
        self.f.feed(OTHER, NOW - 600, 'Ten minutes old.')
        self.f.feed(QUIET, NOW - 1500, 'Long ago.')
        by_id = {s['id']: s for s in self.state()['sessions']}
        self.assertEqual((by_id[ME]['last'], by_id[ME]['age']), ('Newest reply.', '9m'))
        self.assertEqual((by_id[OTHER]['last'], by_id[OTHER]['age']), ('', '10m'))
        self.assertEqual((by_id[QUIET]['last'], by_id[QUIET]['age']), ('', '25m'))
        self.assertEqual(orchestrator.LAST_LINE_WITHIN, 600)
        self.assertEqual(orchestrator.session_line(by_id[ME]).split('\t')[8], 'Newest reply.')
        self.assertEqual(orchestrator.session_line(by_id[OTHER]).split('\t')[8], '')

    def test_the_last_line_is_the_newest_reply_on_one_line(self):
        self.f.session(100, ME, 'One')
        self.f.feed(ME, NOW - 30, 'Two\nlines   here.')
        self.f.feed(ME, NOW - 90, 'Older.')
        self.f.feed(ME, NOW - 60, 'Not the newest.')
        self.assertEqual(self.state()['sessions'][0]['last'], 'Two lines here.')


class Repos(Fixture):
    def repo(self, name, url=None):
        top = os.path.join(self.root, 'code', name)
        os.makedirs(os.path.join(top, '.git'))
        with open(os.path.join(top, '.git', 'config'), 'w') as f:
            f.write('[core]\n\tbare = false\n')
            if url:
                f.write(f'[remote "origin"]\n\turl = {url}\n\tfetch = +refs/heads/*\n')
        return top

    def test_repo_name_is_the_origin_remote_from_a_worktree_subfolder(self):
        top = self.repo('old-folder', 'https://github.com/someone/Gnome-Widgets.git')
        gitdir = os.path.join(top, '.git', 'worktrees', 'wt')
        os.makedirs(gitdir)
        with open(os.path.join(gitdir, 'commondir'), 'w') as f:
            f.write('../..\n')
        wt = os.path.join(top, '.claude', 'worktrees', 'wt')
        os.makedirs(os.path.join(wt, 'src'))
        with open(os.path.join(wt, '.git'), 'w') as f:
            f.write(f'gitdir: {gitdir}\n')
        self.assertEqual(orchestrator.repo_name(os.path.join(wt, 'src')), 'Gnome-Widgets')

    def test_repo_name_follows_a_relative_gitdir(self):
        top = self.repo('Overmind')
        os.makedirs(os.path.join(top, '.git', 'worktrees', 'wt'))
        with open(os.path.join(top, '.git', 'worktrees', 'wt', 'commondir'), 'w') as f:
            f.write('../..\n')
        wt = os.path.join(top, 'wt')
        os.makedirs(wt)
        with open(os.path.join(wt, '.git'), 'w') as f:
            f.write('gitdir: ../.git/worktrees/wt\n')
        self.assertEqual(orchestrator.repo_name(wt), 'Overmind')

    def test_repo_name_without_a_remote_is_the_folder(self):
        self.assertEqual(orchestrator.repo_name(self.repo('LaundryBot')), 'LaundryBot')

    def test_the_session_line_carries_the_whole_repository_name(self):
        top = self.repo('x', 'git@github.com:someone/fagerteam-health-coach.git')
        self.assertEqual(orchestrator.session_repo(top), 'fagerteam-health-coach')
        self.f.session(100, ME, 'One')
        s = dict(self.state()['sessions'][0], repo='fagerteam-health-coach')
        self.assertEqual(orchestrator.session_line(s).split('\t')[4], 'fagerteam-health-coach')


class Links(Repos):
    """What a click on a session's name opens: its issue, from its branch, or its ready pull
    requests, from its ledger."""

    def setUp(self):
        super().setUp()
        p = mock.patch.object(orchestrator, '_git', {})
        p.start()
        self.addCleanup(p.stop)

    def worktree(self, head, url='git@github.com:someone/Gnome-Widgets.git'):
        top = self.repo('Gnome-Widgets', url)
        gitdir = os.path.join(top, '.git', 'worktrees', 'wt')
        os.makedirs(gitdir)
        for name, text in (('commondir', '../..\n'), ('HEAD', head + '\n')):
            with open(os.path.join(gitdir, name), 'w') as f:
                f.write(text)
        wt = os.path.join(top, '.claude', 'worktrees', 'wt')
        os.makedirs(wt)
        with open(os.path.join(wt, '.git'), 'w') as f:
            f.write(f'gitdir: {gitdir}\n')
        return wt

    def pr_ledger(self, sid, *rows):
        folder = os.path.join(self.f.ledgers, '-home-user-project', sid, 'scratchpad')
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, 'ledger'), 'w') as f:
            f.writelines(f'pr {n}\tpr:{n}\thttps://github.com/someone/Gnome-Widgets/pull/{n}\t{state}\t\n'
                         for n, state in rows)

    def test_the_issue_is_the_branchs_issue_number_on_the_origin_repository(self):
        wt = self.worktree('ref: refs/heads/feat/issue-123-session-row-links')
        self.assertEqual(orchestrator.session_issue(*orchestrator.session_branch(wt)),
                         'https://github.com/someone/Gnome-Widgets/issues/123')
        top =self.repo('plain', 'https://github.com/someone/Overmind.git')
        with open(os.path.join(top, '.git', 'HEAD'), 'w') as f:
            f.write('ref: refs/heads/fix/issue-7-x\n')
        self.assertEqual(orchestrator.session_issue(*orchestrator.session_branch(top)),
                         'https://github.com/someone/Overmind/issues/7')

    def test_no_issue_without_one_in_the_branch_a_branch_or_github(self):
        for head, url in (('ref: refs/heads/main', None), ('0123abcd' * 5, None),
                          ('ref: refs/heads/feat/issue-5-x', 'https://gitlab.com/someone/x.git'),
                          ('ref: refs/heads/feat/tissue-5', None)):
            with self.subTest(head=head):
                shutil.rmtree(os.path.join(self.root, 'code'), ignore_errors=True)
                orchestrator._git.clear()
                wt = self.worktree(head, url or 'git@github.com:someone/Gnome-Widgets.git')
                self.assertEqual(orchestrator.session_issue(*orchestrator.session_branch(wt)), '')
        nowhere = orchestrator.session_branch(os.path.join(self.root, 'nowhere'))
        self.assertEqual((nowhere, orchestrator.session_issue(*nowhere)), (('', ''), ''))

    def test_the_origin_is_the_url_and_not_a_pushurl_before_it(self):
        top = self.repo('fork')
        with open(os.path.join(top, '.git', 'config'), 'a') as f:
            f.write('[remote "origin"]\n\tpushurl = git@github.com:me/fork.git\n'
                    '\turl = https://github.com/org/repo.git\n')
        with open(os.path.join(top, '.git', 'HEAD'), 'w') as f:
            f.write('ref: refs/heads/feat/issue-9-x\n')
        self.assertEqual(orchestrator.session_issue(*orchestrator.session_branch(top)),
                         'https://github.com/org/repo/issues/9')
        self.assertEqual(orchestrator.session_branch(top), ('feat/issue-9-x', 'org/repo'))

    def test_the_ledgers_open_pull_requests_are_the_ready_ones(self):
        self.f.session(100, ME, 'One')
        self.pr_ledger(ME, (150, 'done'), (151, 'open'), (152, 'open'))
        s = self.state()['sessions'][0]
        self.assertEqual(s['prs'], ['https://github.com/someone/Gnome-Widgets/pull/151',
                                    'https://github.com/someone/Gnome-Widgets/pull/152'])

    def test_the_pill_shows_for_a_ledger_another_repository_keeps(self):
        # ledger.tsv and catchup.tsv, with a branch column after the label
        self.f.session(100, ME, 'One')
        self.f.session(200, OTHER, 'Two')
        self.f.branch_ledger(ME, 'ledger.tsv', ('pr:151', 'done'), ('pr:152', 'open'))
        self.f.branch_ledger(OTHER, 'catchup.tsv', ('pr:7', 'open'), ('pr:8', 'open'))
        one, two = self.state()['sessions']
        self.assertEqual(one['prs'], ['https://github.com/o/r/pull/152'])
        self.assertEqual(two['prs'], ['https://github.com/o/r/pull/7', 'https://github.com/o/r/pull/8'])
        self.assertEqual(one['waiting'], 'merge')
        self.f.branch_ledger(ME, 'ledger.tsv', ('pr:152', 'done'))
        self.assertEqual(self.state()['sessions'][0]['prs'], [])

    def test_one_pill_counts_the_open_rows_of_both_layouts(self):
        self.f.session(100, ME, 'One')
        self.pr_ledger(ME, (151, 'open'))
        self.f.branch_ledger(ME, 'ledger.tsv', ('pr:152', 'open'), ('pr:153', 'done'))
        self.assertEqual(self.state()['sessions'][0]['prs'],
                         ['https://github.com/someone/Gnome-Widgets/pull/151', 'https://github.com/o/r/pull/152'])

    def test_a_repository_lists_the_issues_of_the_sessions_in_it_in_number_order(self):
        issue = lambda repo, n: f'https://github.com/{repo}/issues/{n}'
        listed = [dict(github='o/a', issue=issue('o/a', 31)), dict(github='o/a', issue=issue('o/a', 7)),
                  dict(github='o/a', issue=issue('o/a', 31)), dict(github='o/a', issue=''),
                  dict(github='o/b', issue=issue('o/b', 2)), dict(github='', issue='')]
        orchestrator.repo_issues(listed)
        self.assertEqual([[n for n, _ in s['issues']] for s in listed],
                         [['#7', '#31']] * 4 + [['#2'], []])
        self.assertEqual(listed[0]['issues'][0][1], issue('o/a', 7))

    def test_the_sessions_are_listed_in_the_sections_the_cli_names_for_their_state(self):
        listed = [dict(id='a', busy=False), dict(id='b', busy=True), dict(id='c', busy=False, question=True),
                  dict(id='e', busy=False, waiting='merge')]
        self.assertEqual([(orchestrator.status_group(x), x['id']) for x in orchestrator.grouped(listed)],
                         [('Needs input', 'c'), ('Working', 'b'), ('Working', 'e'), ('Completed', 'a')])

    def test_an_idle_session_with_a_pull_request_open_is_in_review_under_needs_input(self):
        self.f.session(100, ME, 'One')
        self.f.session(200, OTHER, 'Two', status='busy')
        self.f.session(300, QUIET, 'Three')
        self.pr_ledger(ME, (151, 'open'), (152, 'open'), (150, 'done'))
        self.pr_ledger(OTHER, (160, 'open'))
        by_id = {x['id']: x for x in self.state()['sessions']}
        for s in by_id.values():
            s['repo'] = 'Gnome-Widgets'
        one, two, three = by_id[ME], by_id[OTHER], by_id[QUIET]
        self.assertEqual(orchestrator.review_label(one), 'In review \u00b7 Gnome-Widgets #151, #152')
        self.assertEqual(orchestrator.status_group(one), 'Needs input')
        self.assertEqual(orchestrator.session_line(one).split('\t')[7], orchestrator.review_label(one))
        self.assertEqual((orchestrator.status_group(two), orchestrator.review_label(two)), ('Working', ''))   # busy: still working
        self.assertEqual((orchestrator.status_group(three), orchestrator.review_label(three)), ('Completed', ''))

    def test_a_session_is_one_row_and_a_section_adds_its_title_and_a_blank_row_after_the_first(self):
        self.f.session(100, ME, 'One')
        self.f.session(200, OTHER, 'Two')
        state = self.state()
        state['sessions'][0].update(busy=True)
        orchestrator.render(state)
        with open(orchestrator.SESSIONS) as f:
            lines = [line.split('\t') for line in f.read().splitlines()]
        with open(orchestrator.REGIONS) as f:
            regions = json.load(f)
        self.assertEqual([(l[5], l[6]) for l in lines], [('2', 'Working'), ('3', 'Completed')])
        row = regions['list_scroll'][1]
        one, two = regions['rows']
        self.assertEqual((one['head'], two['head']), (row, 2 * row))     # the title; a blank row and the title
        self.assertEqual((one['bottom'] - one['top'], two['bottom'] - two['top']), (2 * row, 3 * row))
        self.assertLess(two['name'][0], two['name'][1])                  # every name is there to click
        self.assertLess(two['name'][1], regions['list'][2])
        self.assertEqual([(r['pid'], r['title']) for r in (one, two)], [(100, 'One'), (200, 'Two')])

    def test_the_numbers_of_a_sessions_issues_and_pull_requests_head_its_messages(self):
        sess = dict(id='aaaa', issues=[('#123', 'https://o/r/issues/123'), ('#125', 'https://o/r/issues/125')],
                    prs=['https://o/r/pull/124', 'https://o/r/pull/126'])
        segments = orchestrator.meta_segments(sess)
        self.assertEqual(''.join(t for t, _ in segments), '[ Issue #123, #125 | PR #124, #126 ]')
        self.assertEqual([info['issue'] for _, info in segments if info],
                         ['https://o/r/issues/123', 'https://o/r/issues/125', 'https://o/r/pull/124',
                          'https://o/r/pull/126'])
        self.assertEqual(''.join(t for t, _ in orchestrator.meta_segments(dict(sess, issues=[]))), '[ PR #124, #126 ]')
        self.assertEqual(orchestrator.meta_segments(dict(id='aaaa')), [])
        self.assertEqual(orchestrator.meta_segments(None), [])

    def test_the_close_prompt_is_a_panel_over_the_list_with_cancel_before_ok(self):
        self.f.session(100, ME, 'One')
        orchestrator.render(self.state())
        with open(orchestrator.REGIONS) as f:
            regions = json.load(f)
        prompt, (_, top, _, bottom) = regions['confirm'], regions['list']
        x0, x1 = orchestrator.MARGIN, orchestrator.MARGIN + orchestrator.widget_width        # over both columns
        box = prompt['box']
        self.assertTrue(x0 <= box[0] < box[2] <= x1 and box[3] - box[1] > 0)
        for key in ('cancel', 'ok'):
            self.assertTrue(box[0] <= prompt[key][0] < prompt[key][2] <= box[2], key)
            self.assertTrue(box[1] <= prompt[key][1] < prompt[key][3] <= box[3], key)
        self.assertLess(prompt['cancel'][2], prompt['ok'][0])
        with open(orchestrator.DRAW) as f:
            line = next(l for l in f.read().splitlines() if l.startswith('confirm '))
        self.assertEqual([float(v) for v in line.split()[1:5]], box)


class Terminal(Fixture):
    """The widget's title along the top, the sessions' rows, and the terminal pane with the replies."""
    LONG = ('Pull request 148 now has the new title and footer layout, and the pane is nudged 3 px toward '
            'the text. The widget at the top of the card is titled in capitals with letter spacing, with '
            'minimize and close at the right. The pane runs as tall as the list beside it.')

    def draw(self, size=None, text=None, markdown='', setup=None):
        (setup or self.three)()
        self.f.file(ME + '.feed')
        if text:
            self.f.feed(ME, NOW - 2, text, markdown=markdown, name='Feed widget')
        with mock.patch.object(orchestrator.size_file, 'load', return_value=size or (660, 128, 1.0)):
            widget = orchestrator.render(self.state())
        with open(orchestrator.DRAW) as f:
            raw = f.read().splitlines()
        lines = {l.split()[0]: l.split(None, 1)[1] for l in raw if len(l.split()) > 1 and not l.startswith('line ')}
        lines['line'] = [l[5:] for l in raw if l.startswith('line ')]
        lines['text'] = [l.lstrip(orchestrator.BULLET_MARK) for l in lines['line']
                         if l and not l.startswith((orchestrator.PROMPT_MARK, orchestrator.DONE_MARK))]
        with open(orchestrator.REGIONS) as f:
            return lines, json.load(f), widget

    def test_the_title_is_along_the_top_level_with_minimize_and_close(self):
        lines, regions, _ = self.draw()
        x, cy, track, text = lines['title'].split(None, 3)
        self.assertEqual(text, 'CLAUDE CODE ORCHESTRATOR')
        self.assertEqual((float(x), float(track)), (orchestrator.MARGIN, orchestrator.TITLE_TRACK))
        self.assertEqual(float(cy), (regions['minimize'][1] + regions['minimize'][3]) / 2)
        self.assertLess(float(cy), regions['list'][1])                # above the list

    def test_the_terminal_pane_is_a_column_right_of_the_list_and_as_tall_as_it(self):
        lines, regions, _ = self.draw(text=self.LONG)
        x0, y0, x1, y1, pad = (float(v) for v in lines['terminal'].split()[:5])
        list_x0, list_y0, list_x1, list_y1 = regions['list']
        self.assertEqual((y0, y1), (list_y0, list_y1))                    # the sessions column, no controls under it
        self.assertLess(list_x1, x0)                                      # right of the sessions
        self.assertEqual(x0 - list_x1, orchestrator.COLUMN_GAP)
        self.assertEqual(x1, orchestrator.MARGIN + orchestrator.widget_width)
        self.assertEqual(pad, orchestrator.TERM_PAD)
        self.assertEqual(regions['terminal'], [x0, y0, x1, y1])

    def test_the_card_ends_a_margin_under_the_list_and_the_divider_ends_with_it(self):
        lines, regions, _ = self.draw()
        x, y0, y1 = (float(v) for v in lines['divider'].split())
        self.assertEqual(y1, regions['list'][3] + orchestrator.MARGIN - 4)
        self.assertEqual(regions['divider'][3], y1)

    def test_the_divider_is_a_line_in_the_gap_between_the_columns_with_a_grab_area_over_it(self):
        lines, regions, _ = self.draw()
        x, y0, y1 = (float(v) for v in lines['divider'].split())
        gap0, gap1 = regions['list'][2], float(lines['terminal'].split()[0])
        self.assertEqual(x, (gap0 + gap1) / 2)
        self.assertLess(y0, regions['list'][1])                           # the divider runs from the header's rule
        self.assertGreater(y1, regions['list'][3])                        # to the card's bottom
        self.assertEqual(float(lines['rules']), y0)                       # the header's rule is the only one
        grab = regions['divider']
        self.assertTrue(gap0 <= grab[0] < x < grab[2] <= gap1)
        self.assertEqual((grab[1], grab[3]), (y0, y1))
        left, avail, gap, low, high = regions['divider_drag']
        self.assertEqual((left, gap), (orchestrator.MARGIN, orchestrator.COLUMN_GAP))
        self.assertEqual(left + avail + gap, orchestrator.MARGIN + orchestrator.widget_width)
        self.assertEqual(orchestrator.COLUMN_GAP, 24)
        self.assertTrue(0 < low <= 0.5 <= high < 1)

    def test_the_divider_file_sets_the_sessions_share_within_the_least_each_column_keeps(self):
        with open(orchestrator.SPLIT, 'w') as f:
            f.write('0.6\n')
        lines, regions, _ = self.draw()
        left, avail, gap, low, high = regions['divider_drag']
        self.assertEqual(regions['list'][2], left + round(avail * 0.6))
        for share, want in (('0.0', low), ('1.0', high), ('junk', orchestrator.SPLIT_DEFAULT)):
            with open(orchestrator.SPLIT, 'w') as f:
                f.write(share)
            _, regions, _ = self.draw()
            self.assertEqual(regions['list'][2], left + round(avail * want), share)
        self.assertGreaterEqual(regions['list'][2] - left, orchestrator.LIST_MIN)

    def test_nothing_of_playback_is_drawn_or_a_click_area(self):
        lines, regions, _ = self.draw(text=self.LONG)
        for key in ('clock', 'footer', 'buttons', 'volume', 'gear', 'menu', 'status', 'progress'):
            self.assertNotIn(key, lines)
        for key in ('pause', 'skip', 'next', 'volume', 'volume_icon', 'volume_wheel', 'volume_bar', 'gear', 'menu'):
            self.assertNotIn(key, regions)
        self.assertEqual(len(lines['terminal'].split()), 10)               # the box, its lines and the sessions it counts
        self.assertEqual(lines['control'].count(' '), 1)

    def test_the_pane_counts_the_managed_sessions_it_lists(self):
        lines, _, _ = self.draw()
        self.assertEqual(lines['terminal'].split()[9], '3')
        lines, _, _ = self.draw(setup=lambda: (self.three(), self.f.session(400, '44444444-dddd', 'Plain', managed=False)))
        self.assertEqual(lines['terminal'].split()[9], '3')                  # an unmanaged session is not counted

    def test_the_rows_hold_only_what_a_click_needs(self):
        _, regions, _ = self.draw()
        for row in regions['rows']:
            self.assertEqual(sorted(row), ['bottom', 'busy', 'head', 'id', 'name', 'pid', 'title', 'top'])
            self.assertLess(row['name'][0], row['name'][1])

    def test_the_pane_prints_the_whole_text_behind_a_left_margin_for_the_bullet_and_names_the_speaker(self):
        lines, _, _ = self.draw(text=self.LONG)
        x0, y0, x1, y1, pad = (float(v) for v in lines['terminal'].split()[:5])
        self.assertEqual(lines['speaker'], orchestrator.TERM_TITLE)                  # static, whoever replies
        step = float(lines['terminal'].split()[7])
        shown = int(lines['terminal'].split()[8])                                  # lines shown at once
        self.assertEqual(shown, max(int((y1 - y0 - 2 * pad - (orchestrator.TERM_BANNER_LINES + 1) * step) // step), 1))
        self.assertEqual(lines['line'][0], orchestrator.PROMPT_MARK + 'Feed widget')   # who replied, as the prompt
        self.assertEqual(lines['line'][1], '')
        self.assertTrue(lines['line'][2].startswith(orchestrator.BULLET_MARK))             # then the text behind its bullet
        when = datetime.datetime.fromtimestamp(NOW - 2).strftime('%A %-I:%M %p')
        self.assertEqual(lines['line'][-1], orchestrator.DONE_MARK + 'Replied · ' + when)
        self.assertEqual(' '.join(l.strip() for l in lines['text']), self.LONG)   # every word, none cut
        self.assertTrue(all(l.startswith(orchestrator.TERM_INDENT) for l in lines['text']))
        for line in lines['text']:
            self.assertLess(orchestrator.text_width(line, orchestrator.TERM_FONT) * orchestrator.BLOCK_SLACK,
                            x1 - x0 - 2 * pad)

    def test_a_word_wider_than_the_pane_is_broken_across_lines_and_none_is_lost(self):
        word = 'x' * 300
        lines, _, _ = self.draw(text=f'See {word} now')
        x0, _, x1, _, pad = (float(v) for v in lines['terminal'].split()[:5])
        self.assertEqual(''.join(lines['text']).replace(' ', ''), 'See' + word + 'now')
        for line in lines['text']:
            self.assertLess(orchestrator.text_width(line, orchestrator.TERM_FONT) * orchestrator.BLOCK_SLACK,
                            x1 - x0 - 2 * pad)

    def test_the_pane_is_a_wheel_area_and_counts_the_lines_past_what_it_shows(self):
        lines, regions, _ = self.draw(text=self.LONG * 3)
        x0, y0, x1, y1 = (float(v) for v in lines['terminal'].split()[:4])
        self.assertEqual(regions['terminal'], [x0, y0, x1, y1])
        self.assertEqual(regions['terminal_scroll'], len(lines['line']) - int(lines['terminal'].split()[8]))
        self.assertGreater(regions['terminal_scroll'], 0)
        lines, regions, _ = self.draw()
        self.assertEqual(regions['terminal_scroll'], 0)
        self.assertIn('terminal', regions)                               # the pane stays with nothing to print

    MARKDOWN = ('## What changed\n\nBoth changes are **pushed** (`cfd3cda`), and your *orchestrator* widget restarted.\n\n'
                '- Spacing: **12 px**\n- Avatar: trimmed\n\n```\nsudo apt install lua5.3\n```')

    def test_the_pane_draws_the_markdown_the_feed_holds_with_each_runs_style(self):
        self.three()
        self.f.feed(ME, NOW - 2, 'flat', markdown=self.MARKDOWN, name='Feed widget')
        with mock.patch.object(orchestrator.size_file, 'load', return_value=(1400, 128, 1.0)):
            orchestrator.render(self.state())
        with open(orchestrator.DRAW) as f:
            lines = [l[5:] for l in f.read().split('\n') if l.startswith('line ')]
        self.assertEqual(lines[:2], [orchestrator.PROMPT_MARK + 'Feed widget', ''])
        lines = lines[2:]
        lines[0] = lines[0].lstrip(orchestrator.BULLET_MARK)
        mark = orchestrator.STYLE_MARK
        self.assertEqual(lines[0], f'{mark}n  {mark}bWhat changed')              # a heading is bold, behind the margin
        self.assertEqual(lines[1].strip(), '')                                   # and a paragraph follows a blank line
        self.assertIn(mark + 'bpushed', lines[2])
        self.assertIn(mark + 'ccfd3cda', lines[2])
        self.assertIn(mark + 'iorchestrator', lines[2])
        self.assertNotIn('*', ''.join(lines))
        self.assertNotIn('`', ''.join(lines))
        self.assertTrue(any(l.startswith(mark + 'n  • Spacing: ') and mark + 'b12 px' in l for l in lines))
        self.assertIn(orchestrator.BAND_MARK + mark + 'n    ' + mark + 'csudo apt install lua5.3', lines)  # a code line, in the code style

    def test_without_markdown_the_pane_keeps_the_plain_line(self):
        lines, _, _ = self.draw(text='Done and dusted.')
        prompt, blank, bullet, blank2, done = lines['line']
        self.assertEqual((prompt, blank, bullet, blank2), (orchestrator.PROMPT_MARK + 'Feed widget', '',
                                                           orchestrator.BULLET_MARK + '  Done and dusted.', ''))
        self.assertTrue(done.startswith(orchestrator.DONE_MARK + 'Replied · '))
        self.assertNotIn(orchestrator.STYLE_MARK, ''.join(lines['line']))

    def test_markdown_is_blocks_of_paragraphs_headings_list_items_quotes_rules_and_code(self):
        blocks = orchestrator.markdown_blocks('# Title\nfirst line\nsecond line\n\n- a **b**\n2. c\n> quoted\n---\n```\nx  y\n```')
        self.assertEqual([(k, m) for k, m, _ in blocks],
                         [('h', ''), ('p', ''), ('li', '\u2022'), ('li', '2.'), ('q', ''), ('hr', ''), ('code', '')])
        self.assertEqual(blocks[1][2], [('first line second line', '')])           # a paragraph's lines join
        self.assertEqual(blocks[2][2], [('a ', ''), ('b', 'b')])
        self.assertEqual(blocks[4][2], [('quoted', '')])
        self.assertEqual(blocks[6][2], [('x  y', 'c')])                            # a code line is kept as written

    def test_a_table_is_its_rows_without_the_separator_and_a_fence_tag_is_a_dim_run(self):
        blocks = orchestrator.markdown_blocks('| A | B |\n|:--|--:|\n| 1 | **2** |\n\n```python\nx\n```')
        self.assertEqual(blocks[0], ('tbl', '', [['A', 'B'], ['1', '**2**']]))
        self.assertEqual(blocks[1:], [('tag', '', [('python', 'd')]), ('code', '', [('x', 'c')])])

    def test_nested_list_levels_are_indented_two_spaces_each_with_a_small_bullet_below_the_first(self):
        blocks = orchestrator.markdown_blocks('- a\n  - b\n    - c\n1. d\n   1. e')
        self.assertEqual([m for _, m, _ in blocks], ['\u2022', '  \u2219', '    \u2219', '1.', '  1.'])

    def plain(self, markdown, width=600):
        """The visual lines of `markdown` with the style marks taken out."""
        return [re.sub(orchestrator.STYLE_MARK + '[a-z]', '', text) for text, _ in orchestrator.markdown_lines(markdown, width)]

    def test_a_table_is_drawn_in_box_characters_with_its_header_bold_and_its_rules_dim(self):
        lines = orchestrator.markdown_lines('| Part | N |\n|---|---|\n| Feed | 12 |\n| Pane | 3 |', 600)
        mark = orchestrator.STYLE_MARK
        self.assertEqual(self.plain('| Part | N |\n|---|---|\n| Feed | 12 |\n| Pane | 3 |'), [
            '  \u250c\u2500\u2500\u2500\u2500\u2500\u2500\u252c\u2500\u2500\u2500\u2500\u2510',
            '  \u2502 Part \u2502 N  \u2502',
            '  \u251c\u2500\u2500\u2500\u2500\u2500\u2500\u253c\u2500\u2500\u2500\u2500\u2524',
            '  \u2502 Feed \u2502 12 \u2502',
            '  \u2502 Pane \u2502 3  \u2502',
            '  \u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2534\u2500\u2500\u2500\u2500\u2518'])
        self.assertIn(mark + 'b Part', lines[1][0])                                  # the header row is bold
        self.assertIn(mark + 'd\u2502', lines[1][0])                                # and the rules dim

    def test_a_table_wider_than_the_pane_cuts_its_widest_cells_with_an_ellipsis(self):
        table = '| Name | Note |\n|---|---|\n| a | ' + 'long ' * 30 + '|'
        lines = orchestrator.markdown_lines(table, 300)
        self.assertEqual(len(lines), 5)                                             # none wraps into another row
        for line, width in lines:
            self.assertLessEqual(width, 300)
        self.assertIn('\u2026', lines[3][0])
        self.assertIn('Name', lines[1][0])                                          # the narrow column keeps its text

    def test_nested_list_lines_hang_under_their_first_word(self):
        lines = self.plain('- a\n  - b ' + 'word ' * 20, 200)
        self.assertEqual(lines[0], '  \u2022 a')
        self.assertTrue(lines[1].startswith('    \u2219 b word') and lines[2].startswith('      word'))

    def test_a_block_quote_is_behind_a_dim_bar_on_every_line(self):
        lines = orchestrator.markdown_lines('> ' + 'word ' * 30, 200)
        self.assertGreater(len(lines), 1)
        for line, width in lines:
            self.assertIn(orchestrator.STYLE_MARK + 'd\u2502 ', line)
            self.assertLessEqual(width, 200)

    def test_a_horizontal_rule_is_a_dim_line_across_the_pane(self):
        text, width = orchestrator.markdown_lines('a\n\n---\n\nb', 400)[2]
        self.assertRegex(text, '^' + orchestrator.STYLE_MARK + 'n  ' + orchestrator.STYLE_MARK + 'd\u2500+$')
        self.assertGreater(width, 300)
        self.assertLessEqual(width, 400)

    def test_a_code_block_is_banded_with_its_language_tag_dim_above_and_long_lines_cut(self):
        band, mark = orchestrator.BAND_MARK, orchestrator.STYLE_MARK
        lines = [t for t, _ in orchestrator.markdown_lines('```python\nx = 1\n\n' + 'y' * 200 + '\n```', 300)]
        self.assertEqual(lines[0], f'{band}{mark}n    {mark}dpython')
        self.assertEqual(lines[1], f'{band}{mark}n    {mark}cx = 1')
        self.assertEqual(lines[2], band + '    ')                              # a blank code line keeps the band
        self.assertTrue(lines[3].startswith(band) and lines[3].endswith('\u2026'))
        self.assertTrue(all(l.startswith(band) for l in lines))
        untagged = [t for t, _ in orchestrator.markdown_lines('```\nx\n```', 300)]
        self.assertEqual(untagged, [f'{band}{mark}n    {mark}cx'])

    def test_a_code_block_that_opens_a_reply_has_the_bullet_and_the_band_both(self):
        self.three()
        self.f.feed(ME, NOW - 2, 'flat', markdown='```\nx\n```', name='Feed widget')
        with mock.patch.object(orchestrator.size_file, 'load', return_value=(1400, 128, 1.0)):
            orchestrator.render(self.state())
        with open(orchestrator.DRAW) as f:
            lines = [l[5:] for l in f.read().split('\n') if l.startswith('line ')]
        self.assertTrue(lines[2].startswith(orchestrator.BULLET_MARK + orchestrator.BAND_MARK))

    def test_inline_marks_nest_and_a_link_is_its_label(self):
        self.assertEqual(orchestrator.inline_runs('a **b *c* d** [e](http://f) `g*h*`'),
                         [('a ', ''), ('b ', 'b'), ('c', 'x'), (' d', 'b'), (' ', ''), ('e', ''), (' ', ''),
                          ('g*h*', 'c')])
        self.assertEqual(orchestrator.inline_runs('snake_case_name and 2 * 3 * 4'),
                         [('snake_case_name and 2 * 3 * 4', '')])

    def test_a_list_items_second_line_hangs_under_its_first_word(self):
        wide = orchestrator.markdown_lines('- ' + 'word ' * 30, 200)
        self.assertGreater(len(wide), 2)
        first, second = wide[0][0], wide[1][0]
        self.assertTrue(first.startswith('  \u2022 ') and second.startswith('    '))
        for line, width in wide:
            self.assertLessEqual(width, 200)

    def test_the_markdown_a_line_publishes_is_cleaned_and_capped(self):
        self.assertEqual(orchestrator.clean_markdown('a\u200b\r\nb  '), 'a\nb')
        self.assertEqual(orchestrator.clean_markdown(None), '')
        self.assertEqual(orchestrator.clean_markdown(5), '')
        self.assertEqual(len(orchestrator.clean_markdown('x' * 99999)), orchestrator.MARKDOWN_MAX)

    def test_the_title_on_the_pane_is_static_whichever_session_replies(self):
        self.three()
        self.f.feed(ME, NOW - 2, 'Checks pass.', name='Table Headers session')
        orchestrator.render(self.state())
        with open(orchestrator.DRAW) as f:
            self.assertIn('speaker Combined Session Output', f.read().splitlines())

    def test_the_pane_names_a_session_as_the_list_does_not_as_the_feed_did(self):
        self.three()
        self.f.feed(ME, NOW - 2, 'Hello.', name='A name it had before')
        orchestrator.render(self.state())
        with open(orchestrator.DRAW) as f:
            self.assertIn('line ' + orchestrator.PROMPT_MARK + 'Feed widget', f.read().splitlines())

    def test_the_card_is_as_big_with_replies_as_without(self):
        with_lines, with_regions, with_replies = self.draw(text=self.LONG)
        lines, regions, without = self.draw()
        self.assertEqual(lines['terminal'].split()[:4], with_lines['terminal'].split()[:4])   # the same box
        self.assertEqual(without, with_replies)                                               # conky's window does not resize

    def test_the_replies_are_printed_oldest_first_each_once_under_a_header_for_each_change_of_speaker(self):
        self.three()
        for sid, ago, text in ((ME, 90, 'First.'), (ME, 80, 'Second.'), (OTHER, 70, 'Third.'), (ME, 60, 'Fourth.')):
            self.f.feed(sid, NOW - ago, text)
        for _ in range(2):                                              # rendered again: not printed twice
            orchestrator.render(self.state())
        with open(orchestrator.DRAW) as f:
            lines = [l[5:] for l in f.read().splitlines() if l.startswith('line ')]
        bullets = [l[1:].strip() for l in lines if l.startswith(orchestrator.BULLET_MARK)]
        self.assertEqual(bullets, ['First.', 'Second.', 'Third.', 'Fourth.'])
        names = [l[1:] for l in lines if l.startswith(orchestrator.PROMPT_MARK)]
        self.assertEqual(names, ['Feed widget', 'Release 1.2', 'Feed widget'])

    def test_the_speakers_header_is_printed_only_when_the_speaker_changes(self):
        entries = [{'key': k, 'session': sid, 'name': name, 'text': text, 'at': 1.0}
                   for k, sid, name, text in (('a', 's1', 'One', 'First.'), ('b', 's1', 'One', 'Second.'),
                                              ('c', 's2', 'Two', 'Third.'), ('d', 's1', 'One', 'Fourth.'))]
        said, previous = [], None
        for entry in entries:
            said.extend(orchestrator.message_lines(entry, 600, (), entry['session'] != previous))
            previous = entry['session']
        names = [l[1:] for l in said if l.startswith(orchestrator.PROMPT_MARK)]
        self.assertEqual(names, ['One', 'Two', 'One'])
        self.assertEqual(sum(l.startswith(orchestrator.DONE_MARK) for l in said), 4)

    def test_the_same_words_replied_again_are_a_second_message(self):
        self.three()
        self.f.feed(ME, NOW - 100, 'Finished.')
        self.f.feed(ME, NOW - 98, 'Finished.')
        orchestrator.render(self.state())
        with open(orchestrator.DRAW) as f:
            lines = f.read().splitlines()
        self.assertEqual(lines.count('line ' + orchestrator.BULLET_MARK + '  Finished.'), 2)

    def test_every_message_keeps_its_closing_line(self):
        self.three()
        self.f.feed(ME, NOW - 100, 'First.')
        self.f.feed(ME, NOW - 50, 'Second one.')
        orchestrator.render(self.state())
        with open(orchestrator.DRAW) as f:
            lines = [l[5:] for l in f.read().splitlines() if l.startswith('line ')]
        done = [l for l in lines if l.startswith(orchestrator.DONE_MARK)]
        prompts = sum(l.startswith(orchestrator.PROMPT_MARK) for l in lines)
        self.assertEqual((len(done), prompts), (2, 1))
        self.assertEqual(lines[-1], done[-1])                            # the last line of the pane

    def test_a_message_is_laid_out_again_under_another_name(self):
        entry = {'key': 'k', 'session': 's1', 'name': 'One', 'text': 'Hi.', 'markdown': '', 'at': 1.0}
        self.assertEqual(orchestrator.message_lines(entry, 600)[0], orchestrator.PROMPT_MARK + 'One')
        self.assertEqual(orchestrator.message_lines(dict(entry, name='Two'), 600)[0], orchestrator.PROMPT_MARK + 'Two')

    def test_only_the_newest_replies_are_printed(self):
        self.three()
        for i in range(orchestrator.SCROLLBACK_KEEP + 5):
            self.f.feed(ME, 100.0 + i, f'Reply {i}.')
        orchestrator.render(self.state())
        with open(orchestrator.DRAW) as f:
            lines = [l[5:] for l in f.read().splitlines() if l.startswith('line ')]
        self.assertEqual(sum(l.startswith(orchestrator.DONE_MARK) for l in lines), orchestrator.SCROLLBACK_KEEP)
        self.assertIn(orchestrator.BULLET_MARK + f'  Reply {orchestrator.SCROLLBACK_KEEP + 4}.', lines)
        self.assertNotIn(orchestrator.BULLET_MARK + '  Reply 4.', lines)

    def test_a_row_with_a_last_line_takes_a_second_row_under_its_name_and_the_age_is_on_the_first(self):
        self.three()
        self.f.feed(ME, NOW - 60, 'Working on the feed.')
        self.f.feed(OTHER, NOW - 1500, 'Done an hour ago.')
        with mock.patch.object(orchestrator.size_file, 'load', return_value=(660, 290, 1.0)):
            orchestrator.render(self.state())
        with open(orchestrator.SESSIONS) as f:
            lines = [l.split('\t') for l in f.read().splitlines()]
        with open(orchestrator.REGIONS) as f:
            regions = json.load(f)
        by_id = {l[0]: l for l in lines}
        self.assertEqual((by_id[ME][1], by_id[ME][8]), ('1m', 'Working on the feed.'))
        self.assertEqual((by_id[OTHER][1], by_id[OTHER][8]), ('25m', ''))
        self.assertEqual((by_id[QUIET][1], by_id[QUIET][8]), ('', ''))
        row = regions['list_scroll'][1]
        rows = {r['id']: r for r in regions['rows']}
        # working: its section's title, its name and its last line; the others one row each under theirs
        self.assertEqual(rows[ME]['bottom'] - rows[ME]['top'], 3 * row)
        self.assertEqual(rows[ME]['head'], row)
        self.assertEqual(rows[OTHER]['bottom'] - rows[OTHER]['top'], 3 * row)        # a blank row, the title, the name
        self.assertEqual(rows[QUIET]['bottom'] - rows[QUIET]['top'], row)
        self.assertEqual(by_id[ME][5], '3')

    def test_a_collapsed_card_is_the_title_alone_while_no_session_works(self):
        with open(orchestrator.COLLAPSE, 'w') as f:
            f.write('on')
        lines, _, _ = self.draw(setup=self.idle)
        self.assertEqual(sorted(k for k in lines if k in ('title', 'terminal', 'speaker', 'list')), ['title'])
        lines, _, _ = self.draw()                                       # one is working
        self.assertEqual(sorted(k for k in lines if k in ('title', 'terminal', 'speaker', 'list')),
                         ['list', 'speaker', 'terminal', 'title'])

    def test_a_session_waiting_on_input_keeps_a_collapsed_card_open(self):
        with open(orchestrator.COLLAPSE, 'w') as f:
            f.write('on')
        lines, _, _ = self.draw(setup=lambda: self.f.session(100, ME, 'One', status='waiting'))
        self.assertIn('terminal', lines)

    def test_a_narrow_card_at_a_large_scale_cuts_the_title_to_what_clears_minimize(self):
        lines, regions, _ = self.draw((400, 128, 2.0))
        text = lines['title'].split(None, 3)[3]
        self.assertTrue(text.endswith('…') and len(text) < len('CLAUDE CODE ORCHESTRATOR'))
        spaced = orchestrator.text_width(text, orchestrator.LABEL_FONT) + len(text) * orchestrator.TITLE_TRACK * 2.0 * 11 * 96 / 72
        self.assertLess(orchestrator.MARGIN + spaced, regions['minimize'][0])


class Golden(Fixture):
    def check(self, case, state):
        text = orchestrator.render(state)
        orchestrator.write_atomic(orchestrator.OUT, text)
        folder = os.path.join(GOLDEN, case)
        if os.environ.get('ORCHESTRATOR_GOLDEN') == 'write':
            os.makedirs(folder, exist_ok=True)
            for name in OUTPUTS:
                shutil.copy(os.path.join(self.cache, name), os.path.join(folder, name))
        for name in OUTPUTS:
            with open(os.path.join(folder, name)) as want, open(os.path.join(self.cache, name)) as got:
                self.assertEqual(got.read(), want.read(), f'{case}/{name}')

    def test_idle(self):
        self.three()
        self.check('idle', self.state())

    def test_replies(self):
        self.three()
        self.f.feed(OTHER, NOW - 1500, 'The build is green.', name='Release 1.2')
        self.f.feed(ME, NOW - 2400, 'Opened the pull request.', name='Feed widget')
        self.f.feed(ME, NOW - 60, 'The data layer is in: orchestrator.py writes the '
                    'widget, draw and regions files four times a second.', name='Feed widget')
        self.check('replies', self.state())

    def test_issue_numbers_head_the_message_of_their_session(self):
        self.three()
        self.f.feed(ME, NOW - 60, 'Three issues, then one, then too many for a line.', name='Feed widget')
        state = self.state()
        other, quiet, mine = state['sessions']
        issues = lambda *numbers: [(f'#{n}', f'https://github.com/o/r/issues/{n}') for n in numbers]
        mine.update(repo='Gnome-Widgets', issues=issues(127, 131, 133))
        other.update(repo='fagerteam-health-coach', issues=issues(214))
        quiet.update(repo='TheRPGClub-bot', issues=issues(31, 48, 52, 53, 60, 61, 64, 70, 71))
        self.check('issues', state)

    def test_many_sessions_scroll(self):
        for i in range(8):
            self.f.session(100 + i, f'{i:08d}-eeee', f'Session {i}')
        self.check('scroll', self.state())

    def test_collapse_when_idle(self):
        self.idle()
        with open(orchestrator.COLLAPSE, 'w') as fh:
            fh.write('on\n')
        self.check('collapse', self.state())


if __name__ == '__main__':
    unittest.main()
