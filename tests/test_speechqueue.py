"""speechqueue.py: the speech widget's state, read from fixture files, and the files it writes.

The golden samples under tests/golden/speech/<case>/ are what render() writes for each
case. After a change to the layout that is meant, write them again with
    SPEECH_GOLDEN=write python3 -m unittest tests.test_speechqueue
and read the diff before committing it.
"""
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import support

speechqueue = support.load_speechqueue()
import sessions  # noqa: E402

GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'golden', 'speech')
OUTPUTS = ('widget.txt', 'draw.txt', 'regions.json', 'sessions.txt')
ME = '11111111-aaaa'
OTHER = '22222222-bbbb'
QUIET = '33333333-cccc'


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='speechqueue-test-')
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.f = support.SpeechFixture(self.root)
        cache = os.path.join(self.root, 'cache')
        for name, path in (('OUT', 'widget.txt'), ('DRAW', 'draw.txt'),
                           ('REGIONS', 'regions.json'), ('SESSIONS', 'sessions.txt')):
            p = mock.patch.object(speechqueue, name, os.path.join(cache, path))
            p.start()
            self.addCleanup(p.stop)
        for name, value in (('COLLAPSE', os.path.join(self.root, 'collapse-idle')),
                            ('SPLIT', os.path.join(self.root, 'split')),
                            ('SCROLLBACK', os.path.join(self.root, 'scrollback.json')), ('_scrollback', None), ('_message_lines', {}),
                            ('LEDGERS', self.f.ledgers),
                            ('SCALE', 1), ('clock', speechqueue.Clock())):
            p = mock.patch.object(speechqueue, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch('time.monotonic', return_value=1000.0)
        p.start()
        self.addCleanup(p.stop)
        try:
            os.remove(speechqueue.SIZE)
        except FileNotFoundError:
            pass
        self.cache = cache

    def state(self):
        return speechqueue.read_state(self.f.speak, self.f.sessions, self.f.proc)

    def three(self):
        """This session with speech on, another on Alerts with a line queued, a third Off."""
        self.f.session(300, ME, 'Claude Voice Widget', status='busy')
        self.f.session(100, OTHER, 'Release 1.2')
        self.f.session(200, QUIET, 'Docs pass')
        self.f.file(ME + '.replies')
        self.f.file(QUIET + '.muted')
        self.f.queue(OTHER, 'The build is green.')


class ReadState(Fixture):
    def test_sessions_sort_speech_on_first_then_by_pid(self):
        self.three()
        s = self.state()['sessions']
        self.assertEqual([x['id'] for x in s], [ME, OTHER, QUIET])
        self.assertEqual([x['speech'] for x in s], ['on', 'alerts', 'off'])
        self.assertEqual([x['queued'] for x in s], [0, 1, 0])
        self.assertTrue(s[0]['busy'])

    def test_a_background_session_is_listed_and_a_spare_one_is_not(self):
        self.three()
        self.f.session(400, '99999999-jobs', 'Bridge Update', kind='bg')
        self.f.session(500, '88888888-jobs', '88888888', kind='bg', spare=True)
        got = self.state()['sessions']
        self.assertEqual([x['id'] for x in got], [ME, OTHER, QUIET, '99999999-jobs'])
        self.assertEqual([x['spare'] for x in got], [False] * 4)

    def test_a_spare_session_that_speaks_keeps_its_name_in_the_terminal(self):
        self.f.session(400, ME, 'A job', kind='bg', spare=True)
        self.f.now(ME, 'A job', 'A job says: done.', hook_pid=9001)
        state = self.state()
        self.assertEqual((state['sessions'], state['name']), ([], 'A job'))

    def test_a_queued_question_is_a_tag_not_a_line(self):
        self.f.session(100, ME, 'One')
        self.f.queue(ME, 'Question: Open the pull request? Options: yes or no.')
        s = self.state()['sessions'][0]
        self.assertEqual((s['queued'], s['question']), (1, True))
        self.assertIn('question', speechqueue.session_line(s).split('\t')[4].split(','))

    def test_waiting_on_ci_or_a_merge_by_the_sessions_ledger(self):
        self.three()
        flags = lambda sid: next(speechqueue.session_line(x) for x in self.state()['sessions']
                                 if x['id'] == sid).split('\t')[4].split(',')
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
        flags = lambda sid: next(speechqueue.session_line(x) for x in self.state()['sessions']
                                 if x['id'] == sid).split('\t')[4]
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
        flags = lambda sid: next(speechqueue.session_line(x) for x in self.state()['sessions']
                                 if x['id'] == sid).split('\t')[4]
        self.f.sweep(OTHER, 'done', 'done')
        self.assertEqual(flags(OTHER), 'idle')
        self.f.ledger(OTHER, ('pr:111', 'open'))
        self.f.sweep(OTHER, 'done', 'in_progress', 'waiting')
        self.assertEqual(flags(OTHER), 'waiting: tests')          # over waiting on a merge

    def test_waiting_on_a_systemd_unit_a_shell_polls(self):
        self.three()
        flags = lambda sid: next(speechqueue.session_line(x) for x in self.state()['sessions']
                                 if x['id'] == sid).split('\t')[4]
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
                ['bash', 'speechctl_test.sh'], ['./speechctl_test.sh'], ['npm', 'test'],
                ['npm', 'run', 'test'], ['go', 'test', './...'], ['cargo', 'test'],
                ['node', 'node_modules/.bin/playwright', 'test'])
        others = ([], ['grep', 'unittest'], ['bash', '-c', 'pytest'], ['python3', 'speechqueue.py'],
                  ['python3', '-m'], ['npm', 'install'], ['go', 'build'], ['playwright', 'show-report'])
        for argv in runs:
            self.assertTrue(speechqueue.is_test_run(argv), argv)
        for argv in others:
            self.assertFalse(speechqueue.is_test_run(argv), argv)

    def test_one_tag_a_question_first(self):
        self.three()
        flags = lambda sid: next(speechqueue.session_line(x) for x in self.state()['sessions']
                                 if x['id'] == sid).split('\t')[4]
        self.assertEqual((flags(ME), flags(OTHER), flags(QUIET)), ('busy', 'idle', 'idle'))
        self.f.queue(ME, 'Question: Merge it? Options: yes or no.')
        self.f.ledger(ME, ('pr:111', 'open'))
        self.assertEqual(flags(ME), 'question')                   # over busy and waiting
        self.f.queue(QUIET, 'Question: Which one?')
        self.assertEqual(flags(QUIET), 'question')                # over idle

    def test_the_hooks_speaker_is_dropped_only_at_the_start(self):
        self.assertEqual(speechqueue.without_speaker('Claude Voice Widget session says: PR 110 merged.'), 'PR 110 merged.')
        self.assertEqual(speechqueue.without_speaker('It says: nothing here, mid-line it stays.'),
                         'It says: nothing here, mid-line it stays.')              # not the hook's
        self.assertEqual(speechqueue.without_speaker('The log says nothing.'), 'The log says nothing.')
        self.assertEqual(speechqueue.without_speaker('Overmind session says: '), 'Overmind session says: ')

    def test_both_markers_read_as_on(self):
        self.f.session(100, ME, 'One')
        self.f.file(ME + '.replies')
        self.f.file(ME + '.muted')
        self.assertEqual(self.state()['sessions'][0]['speech'], 'on')

    def test_stale_and_socketless_sessions_are_left_out(self):
        self.f.session(100, ME, 'Live')
        self.f.session(200, OTHER, 'Gone', stale=True)
        self.f.session(300, QUIET, 'No socket', socket=False)
        self.f.session(400, 'dddd', 'Other kind', kind='sdk')
        self.assertEqual([x['name'] for x in self.state()['sessions']], ['Live'])

    def test_duplicate_names_are_numbered_in_pid_order(self):
        self.f.session(300, QUIET, 'Widget')
        self.f.session(100, ME, 'Widget')
        self.f.session(200, OTHER, 'widget')
        names = {s['id']: s['name'] for s in sessions.list_sessions(self.f.sessions, self.f.proc)}
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

    def test_now_json_of_an_exited_hook_is_ignored(self):
        self.three()
        self.f.now(ME, 'Claude Voice Widget', 'Hello.', hook_pid=9001)
        shutil.rmtree(os.path.join(self.f.proc, '9001'))
        state = self.state()
        self.assertIsNone(state['now'])
        self.assertFalse(any(s['speaking'] for s in state['sessions']))
        self.assertTrue(os.path.exists(os.path.join(self.f.speak, 'now.json')))   # only reads

    def test_zombie_hook_is_not_alive(self):
        self.f.now(ME, 'One', 'Hello.', hook_pid=9001)
        self.f.alive(9001, state='Z')
        self.assertIsNone(self.state()['now'])

    def test_duration_from_the_wav_once_it_plays(self):
        self.f.now(ME, 'One', 'Hello.', hook_pid=9001)
        self.f.wav(9001, 2.5)
        self.assertAlmostEqual(self.state()['duration'], 2.5, places=3)
        self.f.now(ME, 'One', 'Hello.', hook_pid=9001, player_pid=None)
        self.assertIsNone(self.state()['duration'])                      # still rendering
        self.f.now(ME, 'One', 'Hello.', hook_pid=9001, engine='spd-say')
        self.assertIsNone(self.state()['duration'])

    def test_settings_voice_and_volume(self):
        self.assertEqual(self.state()['voice'], 'en_US-amy-medium')
        self.assertEqual(self.state()['volume'], 1.2)
        self.f.file('settings.json', json.dumps({'voice': 'en_GB-alan-low', 'volume': 0.75}))
        state = self.state()
        self.assertEqual((state['voice'], state['volume']), ('en_GB-alan-low', 0.8))


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
        self.assertEqual(speechqueue.repo_name(os.path.join(wt, 'src')), 'Gnome-Widgets')

    def test_repo_name_follows_a_relative_gitdir(self):
        top = self.repo('Overmind')
        os.makedirs(os.path.join(top, '.git', 'worktrees', 'wt'))
        with open(os.path.join(top, '.git', 'worktrees', 'wt', 'commondir'), 'w') as f:
            f.write('../..\n')
        wt = os.path.join(top, 'wt')
        os.makedirs(wt)
        with open(os.path.join(wt, '.git'), 'w') as f:
            f.write('gitdir: ../.git/worktrees/wt\n')
        self.assertEqual(speechqueue.repo_name(wt), 'Overmind')

    def test_repo_name_without_a_remote_is_the_folder(self):
        self.assertEqual(speechqueue.repo_name(self.repo('LaundryBot')), 'LaundryBot')

    def test_the_session_line_carries_the_whole_repository_name(self):
        top = self.repo('x', 'git@github.com:someone/fagerteam-health-coach.git')
        self.assertEqual(speechqueue.session_repo(top), 'fagerteam-health-coach')
        self.f.session(100, ME, 'One')
        s = dict(self.state()['sessions'][0], repo='fagerteam-health-coach')
        self.assertEqual(speechqueue.session_line(s).split('\t')[6], 'fagerteam-health-coach')


class Links(Repos):
    """What a click on a session's name opens: its issue, from its branch, or its ready pull
    requests, from its ledger."""

    def setUp(self):
        super().setUp()
        p = mock.patch.object(speechqueue, '_git', {})
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
        self.assertEqual(speechqueue.session_issue(*speechqueue.session_branch(wt)),
                         'https://github.com/someone/Gnome-Widgets/issues/123')
        top =self.repo('plain', 'https://github.com/someone/Overmind.git')
        with open(os.path.join(top, '.git', 'HEAD'), 'w') as f:
            f.write('ref: refs/heads/fix/issue-7-x\n')
        self.assertEqual(speechqueue.session_issue(*speechqueue.session_branch(top)),
                         'https://github.com/someone/Overmind/issues/7')

    def test_no_issue_without_one_in_the_branch_a_branch_or_github(self):
        for head, url in (('ref: refs/heads/main', None), ('0123abcd' * 5, None),
                          ('ref: refs/heads/feat/issue-5-x', 'https://gitlab.com/someone/x.git'),
                          ('ref: refs/heads/feat/tissue-5', None)):
            with self.subTest(head=head):
                shutil.rmtree(os.path.join(self.root, 'code'), ignore_errors=True)
                speechqueue._git.clear()
                wt = self.worktree(head, url or 'git@github.com:someone/Gnome-Widgets.git')
                self.assertEqual(speechqueue.session_issue(*speechqueue.session_branch(wt)), '')
        nowhere = speechqueue.session_branch(os.path.join(self.root, 'nowhere'))
        self.assertEqual((nowhere, speechqueue.session_issue(*nowhere)), (('', ''), ''))

    def test_the_origin_is_the_url_and_not_a_pushurl_before_it(self):
        top = self.repo('fork')
        with open(os.path.join(top, '.git', 'config'), 'a') as f:
            f.write('[remote "origin"]\n\tpushurl = git@github.com:me/fork.git\n'
                    '\turl = https://github.com/org/repo.git\n')
        with open(os.path.join(top, '.git', 'HEAD'), 'w') as f:
            f.write('ref: refs/heads/feat/issue-9-x\n')
        self.assertEqual(speechqueue.session_issue(*speechqueue.session_branch(top)),
                         'https://github.com/org/repo/issues/9')
        self.assertEqual(speechqueue.session_branch(top), ('feat/issue-9-x', 'org/repo'))

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
        speechqueue.repo_issues(listed)
        self.assertEqual([[n for n, _ in s['issues']] for s in listed],
                         [['#7', '#31']] * 4 + [['#2'], []])
        self.assertEqual(listed[0]['issues'][0][1], issue('o/a', 7))

    def test_the_sessions_are_listed_in_the_sections_the_cli_names_for_their_state(self):
        listed = [dict(id='a', busy=False), dict(id='b', busy=True), dict(id='c', busy=False, question=True),
                  dict(id='e', busy=False, waiting='merge')]
        self.assertEqual([(speechqueue.status_group(x), x['id']) for x in speechqueue.grouped(listed)],
                         [('Needs input', 'c'), ('Working', 'b'), ('Working', 'e'), ('Completed', 'a')])

    def test_a_session_is_one_row_and_a_section_adds_its_title_and_a_blank_row_after_the_first(self):
        self.f.session(100, ME, 'One')
        self.f.session(200, OTHER, 'Two')
        state = self.state()
        state['sessions'][0].update(busy=True)
        speechqueue.render(state)
        with open(speechqueue.SESSIONS) as f:
            lines = [line.split('\t') for line in f.read().splitlines()]
        with open(speechqueue.REGIONS) as f:
            regions = json.load(f)
        self.assertEqual([(l[7], l[8]) for l in lines], [('2', 'Working'), ('3', 'Completed')])
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
        segments = speechqueue.meta_segments(sess)
        self.assertEqual(''.join(t for t, _ in segments), '[ Issue #123, #125 | PR #124, #126 ]')
        self.assertEqual([info['issue'] for _, info in segments if info],
                         ['https://o/r/issues/123', 'https://o/r/issues/125', 'https://o/r/pull/124',
                          'https://o/r/pull/126'])
        self.assertEqual(''.join(t for t, _ in speechqueue.meta_segments(dict(sess, issues=[]))), '[ PR #124, #126 ]')
        self.assertEqual(speechqueue.meta_segments(dict(id='aaaa')), [])
        self.assertEqual(speechqueue.meta_segments(None), [])

    def test_the_close_prompt_is_a_panel_over_the_list_with_cancel_before_ok(self):
        self.f.session(100, ME, 'One')
        speechqueue.render(self.state())
        with open(speechqueue.REGIONS) as f:
            regions = json.load(f)
        prompt, (_, top, _, bottom) = regions['confirm'], regions['list']
        x0, x1 = speechqueue.MARGIN, speechqueue.MARGIN + speechqueue.widget_width        # over both columns
        box = prompt['box']
        self.assertTrue(x0 <= box[0] < box[2] <= x1 and box[3] - box[1] > 0)
        for key in ('cancel', 'ok'):
            self.assertTrue(box[0] <= prompt[key][0] < prompt[key][2] <= box[2], key)
            self.assertTrue(box[1] <= prompt[key][1] < prompt[key][3] <= box[3], key)
        self.assertLess(prompt['cancel'][2], prompt['ok'][0])
        with open(speechqueue.DRAW) as f:
            line = next(l for l in f.read().splitlines() if l.startswith('confirm '))
        self.assertEqual([float(v) for v in line.split()[1:5]], box)



class ClockTest(unittest.TestCase):
    def test_paused_time_is_not_counted(self):
        c = speechqueue.Clock()
        n = {'clip': '1', 'published': 100.0, 'player_pid': 5}
        self.assertEqual(c.elapsed(n, False, 101.0), 1.0)
        self.assertEqual(c.elapsed(n, True, 102.0), 1.0)       # paused since the last tick
        self.assertEqual(c.elapsed(n, True, 104.0), 1.0)
        self.assertEqual(c.elapsed(n, False, 105.0), 2.0)
        self.assertEqual(c.elapsed(dict(n, clip='2', published=105.0), False, 106.0), 1.0)


VOICES = ['en_GB-alan-medium', 'en_GB-jenny_dioco-medium', 'en_US-amy-medium',
          'en_US-hfc_female-medium', 'en_US-joe-medium', 'en_US-lessac-medium',
          'en_US-libritts-high', 'en_US-ryan-high']


class TitleAndFooter(Fixture):
    """The widget's title and volume along the top, and the terminal pane above the controls."""
    LONG = ('Pull request 148 now has the new title and footer layout, and the pane is nudged 3 px toward '
            'the text. The widget at the top of the card is titled in capitals with letter spacing, with '
            'minimize and close at the right. The status line and the controls now sit under the pane.')

    def draw(self, size=None, text=None, quiet=False):
        self.three()
        if quiet:
            self.f.file(OTHER + '.queue', '')                       # nothing queued: idle
        if text:
            self.f.now(ME, 'Claude Voice Widget', 'Claude Voice Widget session says: ' + text, hook_pid=9001)
            os.utime(os.path.join(self.f.speak, 'now.json'), (998.0, 998.0))
            self.f.wav(9001, 6.0)
        with mock.patch.object(speechqueue.size_file, 'load', return_value=size or (660, 128, 1.0)):
            widget = speechqueue.render(self.state(), now=1000.0)
        with open(speechqueue.DRAW) as f:
            raw = f.read().splitlines()
        lines = {l.split()[0]: l.split(None, 1)[1] for l in raw if len(l.split()) > 1 and not l.startswith('line ')}
        lines['line'] = [l[5:] for l in raw if l.startswith('line ')]
        lines['text'] = [l.lstrip(speechqueue.BULLET_MARK) for l in lines['line']
                         if l and not l.startswith((speechqueue.PROMPT_MARK, speechqueue.DONE_MARK))]
        with open(speechqueue.REGIONS) as f:
            return lines, json.load(f), widget

    def test_the_title_is_along_the_top_level_with_minimize_and_close(self):
        lines, regions, _ = self.draw()
        x, cy, track, text = lines['title'].split(None, 3)
        self.assertEqual(text, 'CLAUDE CODE SESSION MANAGEMENT')
        self.assertEqual((float(x), float(track)), (speechqueue.MARGIN, speechqueue.TITLE_TRACK))
        self.assertEqual(float(cy), (regions['minimize'][1] + regions['minimize'][3]) / 2)
        self.assertLess(float(cy), regions['list'][1])                # above the list

    def test_the_terminal_pane_is_a_column_right_of_the_list_as_tall_as_it_and_the_controls_under_it(self):
        lines, regions, _ = self.draw(text=self.LONG)
        x0, y0, x1, y1, pad = (float(v) for v in lines['terminal'].split()[:5])
        controls_y = float(lines['footer'].split()[1])
        list_x0, list_y0, list_x1, list_y1 = regions['list']
        self.assertEqual(y0, list_y0)
        self.assertEqual(y1, list_y1 + speechqueue.FOOTER_GAP + speechqueue.FOOTER_H)   # the sessions column, controls too
        self.assertLess(list_x1, x0)                                      # right of the sessions
        self.assertEqual(x0 - list_x1, speechqueue.COLUMN_GAP)
        self.assertEqual(x1, speechqueue.MARGIN + speechqueue.widget_width)
        self.assertGreater(controls_y, list_y1)                           # the controls sit in the column's foot, left of the pane
        self.assertLess(controls_y, y1)
        self.assertEqual(pad, speechqueue.TERM_PAD)
        self.assertEqual(regions['terminal'], [x0, y0, x1, y1])

    def test_the_divider_is_a_line_in_the_gap_between_the_columns_with_a_grab_area_over_it(self):
        lines, regions, _ = self.draw()
        x, y0, y1 = (float(v) for v in lines['divider'].split())
        gap0, gap1 = regions['list'][2], float(lines['terminal'].split()[0])
        self.assertEqual(x, (gap0 + gap1) / 2)
        self.assertLess(y0, regions['list'][1])                           # the divider runs between the header's rule
        self.assertGreater(y1, regions['list'][3])                        # to the card's bottom, past the controls
        rule_top, rule_controls = (float(v) for v in lines['rules'].split())
        self.assertEqual(rule_top, y0)
        self.assertGreater(rule_controls, regions['list'][3])             # the controls' rule, under the list
        self.assertLess(rule_controls, float(lines['footer'].split()[1]))
        grab = regions['divider']
        self.assertTrue(gap0 <= grab[0] < x < grab[2] <= gap1)
        self.assertEqual((grab[1], grab[3]), (y0, y1))
        left, avail, gap, low, high = regions['divider_drag']
        self.assertEqual((left, gap), (speechqueue.MARGIN, speechqueue.COLUMN_GAP))
        self.assertEqual(left + avail + gap, speechqueue.MARGIN + speechqueue.widget_width)
        self.assertEqual(speechqueue.COLUMN_GAP, 24)
        self.assertTrue(0 < low <= 0.5 <= high < 1)

    def test_the_divider_file_sets_the_sessions_share_within_the_least_each_column_keeps(self):
        with open(speechqueue.SPLIT, 'w') as f:
            f.write('0.6\n')
        lines, regions, _ = self.draw()
        left, avail, gap, low, high = regions['divider_drag']
        self.assertEqual(regions['list'][2], left + round(avail * 0.6))
        for share, want in (('0.0', low), ('1.0', high), ('junk', speechqueue.SPLIT_DEFAULT)):
            with open(speechqueue.SPLIT, 'w') as f:
                f.write(share)
            _, regions, _ = self.draw()
            self.assertEqual(regions['list'][2], left + round(avail * want), share)
        self.assertGreaterEqual(regions['list'][2] - left, speechqueue.LIST_MIN)

    def test_there_is_no_progress_bar_only_the_clocks_numbers_for_the_status_line(self):
        lines, regions, _ = self.draw(text=self.LONG)
        self.assertNotIn('progress', lines)
        stamp, elapsed, duration, running = lines['clock'].split()
        self.assertEqual((elapsed, duration, running), ('2.000', '6.000', '1'))
        self.assertEqual(float(lines['footer'].split()[1]), float(lines['buttons'].split()[2]))   # one row of buttons

    def test_the_volume_sits_in_the_footer_after_the_buttons_and_the_gear_at_its_right(self):
        lines, regions, _ = self.draw()
        track0, track1, y, _, icon, size = (float(v) for v in lines['volume'].split())
        self.assertEqual(y, float(lines['footer'].split()[1]))         # level with the buttons
        self.assertGreater(icon, float(lines['buttons'].split()[1]))    # after the last of them
        self.assertLess(icon + size, track0)                           # the speaker, then its track
        self.assertEqual(regions['volume_bar'], [track0, track1])
        for key in ('volume', 'volume_icon', 'volume_wheel'):
            self.assertLess(regions[key][1], y)
            self.assertGreater(regions[key][3], y)
        gear_x, gear_y, gear_size = (float(v) for v in lines['gear'].split())
        self.assertGreater(regions['gear'][0], track1)                 # the gear stands apart, at the right
        self.assertLess(regions['gear'][0], gear_x - gear_size / 2)
        self.assertEqual(gear_y, y)
        self.assertFalse(regions['volume'][0] < regions['minimize'][2] and regions['volume'][1] < regions['minimize'][3])   # none in the header

    def test_the_pane_prints_the_whole_text_behind_a_left_margin_for_the_bullet_and_names_the_speaker(self):
        lines, _, _ = self.draw(text=self.LONG)
        x0, y0, x1, y1, pad = (float(v) for v in lines['terminal'].split()[:5])
        self.assertEqual(lines['speaker'], speechqueue.TERM_TITLE)                  # static, whoever speaks
        step = float(lines['terminal'].split()[7])
        shown = int(lines['terminal'].split()[8])                                  # lines shown at once
        self.assertEqual(shown, max(int((y1 - y0 - 2 * pad - (speechqueue.TERM_BANNER_LINES + 1) * step
                                         - speechqueue.TERM_STATUS_GAP - step) // step), 1))
        self.assertEqual(lines['line'][0], speechqueue.PROMPT_MARK + 'Claude Voice Widget')   # who spoke, as the prompt
        self.assertEqual(lines['line'][1], '')
        self.assertTrue(lines['line'][2].startswith(speechqueue.BULLET_MARK))             # then the text behind its bullet
        self.assertTrue(lines['line'][-1].startswith(speechqueue.DONE_MARK + 'Read aloud for 6s \u00b7 done '))
        self.assertEqual(' '.join(l.strip() for l in lines['text']), self.LONG)   # every word, none cut
        self.assertTrue(all(l.startswith(speechqueue.TERM_INDENT) for l in lines['text']))
        for line in lines['text']:
            self.assertLess(speechqueue.text_width(line, speechqueue.TERM_FONT) * speechqueue.BLOCK_SLACK,
                            x1 - x0 - 2 * pad)

    def test_a_word_wider_than_the_pane_is_broken_across_lines_and_none_is_lost(self):
        word = 'x' * 300
        lines, _, _ = self.draw(text=f'See {word} now')
        x0, _, x1, _, pad = (float(v) for v in lines['terminal'].split()[:5])
        self.assertEqual(''.join(lines['text']).replace(' ', ''), 'See' + word + 'now')
        for line in lines['text']:
            self.assertLess(speechqueue.text_width(line, speechqueue.TERM_FONT) * speechqueue.BLOCK_SLACK,
                            x1 - x0 - 2 * pad)

    def test_the_pane_is_a_wheel_area_and_counts_the_lines_past_what_it_shows(self):
        lines, regions, _ = self.draw(text=self.LONG * 3)
        x0, y0, x1, y1 = (float(v) for v in lines['terminal'].split()[:4])
        self.assertEqual(regions['terminal'], [x0, y0, x1, y1])
        self.assertEqual(regions['terminal_scroll'], len(lines['line']) - int(lines['terminal'].split()[8]))
        self.assertGreater(regions['terminal_scroll'], 0)
        os.remove(os.path.join(self.f.speak, 'now.json'))
        lines, regions, _ = self.draw(quiet=True)
        self.assertEqual(regions['terminal_scroll'], len(lines['line']) - int(lines['terminal'].split()[8]))
        self.assertIn('terminal', regions)                               # the pane stays while nothing plays

    MARKDOWN = ('## What changed\n\nBoth changes are **pushed** (`cfd3cda`), and your *speech* widget restarted.\n\n'
                '- Spacing: **12 px**\n- Avatar: trimmed\n\n```\nsudo apt install lua5.3\n```')

    def test_the_pane_draws_the_markdown_the_hook_published_with_each_runs_style(self):
        self.three()
        self.f.now(ME, 'Claude Voice Widget', 'Claude Voice Widget session says: flat', hook_pid=9001,
                   markdown=self.MARKDOWN)
        os.utime(os.path.join(self.f.speak, 'now.json'), (998.0, 998.0))
        self.f.wav(9001, 6.0)
        with mock.patch.object(speechqueue.size_file, 'load', return_value=(1400, 128, 1.0)):
            speechqueue.render(self.state(), now=1000.0)
        with open(speechqueue.DRAW) as f:
            lines = [l[5:] for l in f.read().split('\n') if l.startswith('line ')]
        self.assertEqual(lines[:2], [speechqueue.PROMPT_MARK + 'Claude Voice Widget', ''])
        lines = lines[2:]
        lines[0] = lines[0].lstrip(speechqueue.BULLET_MARK)
        mark = speechqueue.STYLE_MARK
        self.assertEqual(lines[0], f'{mark}n  {mark}bWhat changed')              # a heading is bold, behind the margin
        self.assertEqual(lines[1].strip(), '')                                   # and a paragraph follows a blank line
        self.assertIn(mark + 'bpushed', lines[2])
        self.assertIn(mark + 'ccfd3cda', lines[2])
        self.assertIn(mark + 'ispeech', lines[2])
        self.assertNotIn('*', ''.join(lines))
        self.assertNotIn('`', ''.join(lines))
        self.assertTrue(any(l.startswith(mark + 'n  \u2022 Spacing: ') and mark + 'b12 px' in l for l in lines))
        self.assertIn(mark + 'n    ' + mark + 'csudo apt install lua5.3', lines)  # a code line, in the code style

    def test_without_markdown_the_pane_keeps_the_plain_line(self):
        lines, _, _ = self.draw(text='Done and dusted.')
        prompt, blank, bullet, blank2, done = lines['line']
        self.assertEqual((prompt, blank, bullet, blank2), (speechqueue.PROMPT_MARK + 'Claude Voice Widget', '',
                                                           speechqueue.BULLET_MARK + '  Done and dusted.', ''))
        self.assertTrue(done.startswith(speechqueue.DONE_MARK + 'Read aloud for 6s'))
        self.assertNotIn(speechqueue.STYLE_MARK, ''.join(lines['line']))

    def test_markdown_is_blocks_of_paragraphs_headings_list_items_and_code(self):
        blocks = speechqueue.markdown_blocks('# Title\nfirst line\nsecond line\n\n- a **b**\n2. c\n> quoted\n---\n```\nx  y\n```')
        self.assertEqual([(k, m) for k, m, _ in blocks],
                         [('h', ''), ('p', ''), ('li', '\u2022'), ('li', '2.'), ('p', ''), ('code', '')])
        self.assertEqual(blocks[1][2], [('first line second line', '')])           # a paragraph's lines join
        self.assertEqual(blocks[2][2], [('a ', ''), ('b', 'b')])
        self.assertEqual(blocks[4][2], [('quoted', '')])
        self.assertEqual(blocks[5][2], [('x  y', 'c')])                            # a code line is kept as written

    def test_inline_marks_nest_and_a_link_is_its_label(self):
        self.assertEqual(speechqueue.inline_runs('a **b *c* d** [e](http://f) `g*h*`'),
                         [('a ', ''), ('b ', 'b'), ('c', 'x'), (' d', 'b'), (' ', ''), ('e', ''), (' ', ''),
                          ('g*h*', 'c')])
        self.assertEqual(speechqueue.inline_runs('snake_case_name and 2 * 3 * 4'),
                         [('snake_case_name and 2 * 3 * 4', '')])

    def test_a_list_items_second_line_hangs_under_its_first_word(self):
        wide = speechqueue.markdown_lines('- ' + 'word ' * 30, 200)
        self.assertGreater(len(wide), 2)
        first, second = wide[0][0], wide[1][0]
        self.assertTrue(first.startswith('  \u2022 ') and second.startswith('    '))
        for line, width in wide:
            self.assertLessEqual(width, 200)

    def test_the_markdown_a_line_publishes_is_cleaned_and_capped(self):
        self.assertEqual(speechqueue.clean_markdown('a\u200b\r\nb  '), 'a\nb')
        self.assertEqual(speechqueue.clean_markdown(None), '')
        self.assertEqual(speechqueue.clean_markdown(5), '')
        self.assertEqual(len(speechqueue.clean_markdown('x' * 99999)), speechqueue.MARKDOWN_MAX)

    def test_the_title_on_the_pane_is_static_whichever_session_speaks(self):
        self.three()
        self.f.now(ME, 'Table Headers session', 'Checks pass.', hook_pid=9001)
        os.utime(os.path.join(self.f.speak, 'now.json'), (998.0, 998.0))
        self.f.wav(9001, 6.0)
        speechqueue.render(self.state(), now=1000.0)
        with open(speechqueue.DRAW) as f:
            self.assertIn('speaker Combined Session Output', f.read().splitlines())

    def test_the_pane_is_as_tall_while_nothing_plays_and_the_card_keeps_its_size(self):
        playing_lines, playing_regions, playing = self.draw(text=self.LONG)
        os.remove(os.path.join(self.f.speak, 'now.json'))             # the clip ends
        lines, regions, idle = self.draw()
        self.assertEqual(lines['terminal'].split()[:4], playing_lines['terminal'].split()[:4])   # the same box
        self.assertEqual(lines['terminal'].split()[10], '0')            # but not playing
        self.assertEqual(lines['line'], playing_lines['line'])          # what was printed stays
        self.assertEqual(idle, playing)                                 # conky's window does not resize

    def test_a_message_is_printed_once_when_it_starts_to_play_and_stays_below_the_older_ones(self):
        lines, _, _ = self.draw(quiet=False)                           # queued lines, none playing
        self.assertEqual(lines['line'], [])                            # received is not printed
        lines, _, _ = self.draw(text='First.')
        lines, _, _ = self.draw(text='First.')                         # rendered again: not printed twice
        self.assertEqual(lines['text'], ['  First.'])
        os.remove(os.path.join(self.f.speak, 'now.json'))
        lines, _, _ = self.draw(text='Second one.')
        os.utime(os.path.join(self.f.speak, 'now.json'), (999.0, 999.0))
        lines, _, _ = self.draw(text='Second one.')
        self.assertEqual(sum(l.startswith(speechqueue.PROMPT_MARK) for l in lines['line']), 1)   # the same session: no second header
        self.assertIn('  First.', lines['text'])
        self.assertEqual(lines['text'][-1], '  Second one.')            # the newest at the end

    def test_the_speakers_header_is_printed_only_when_the_speaker_changes(self):
        entries = [{'key': k, 'session': sid, 'name': name, 'text': text, 'at': 1.0}
                   for k, sid, name, text in (('a', 's1', 'One', 'First.'), ('b', 's1', 'One', 'Second.'),
                                              ('c', 's2', 'Two', 'Third.'), ('d', 's1', 'One', 'Fourth.'))]
        said, previous = [], None
        for entry in entries:
            said.extend(speechqueue.message_lines(entry, 600, (), entry['session'] != previous))
            previous = entry['session']
        names = [l[1:] for l in said if l.startswith(speechqueue.PROMPT_MARK)]
        self.assertEqual(names, ['One', 'Two', 'One'])
        self.assertEqual(sum(l.startswith(speechqueue.DONE_MARK) for l in said), 4)

    def test_a_clip_published_again_or_the_same_words_said_again_at_once_print_once(self):
        self.draw(text='Finished.')
        path = os.path.join(self.f.speak, 'now.json')
        os.utime(path, (1001.0, 1001.0))                                # the hook wrote now.json again: a new mtime, the same clip
        lines, _, _ = self.draw(text='Finished.')
        self.assertEqual(lines['text'], ['  Finished.'])
        n = {'session': 's1', 'clip': 'a', 'published': 5000.0, 'text': 'Same words'}
        speechqueue.spoken_log(n, 'Name')
        speechqueue.spoken_log(dict(n, clip='b', published=5002.0), 'Name')    # another clip, the same words, 2 s on
        speechqueue.spoken_log(dict(n, clip='c', published=5100.0), 'Name')    # and again a minute on: said again
        self.assertEqual([e['text'] for e in speechqueue._scrollback].count('Same words'), 2)

    def test_every_message_keeps_its_closing_line(self):
        self.draw(text='First.')
        os.remove(os.path.join(self.f.speak, 'now.json'))
        lines, _, _ = self.draw(text='Second one.')
        os.utime(os.path.join(self.f.speak, 'now.json'), (999.0, 999.0))
        lines, _, _ = self.draw(text='Second one.')
        done = [l for l in lines['line'] if l.startswith(speechqueue.DONE_MARK)]
        prompts = sum(l.startswith(speechqueue.PROMPT_MARK) for l in lines['line'])
        self.assertEqual((len(done), prompts), (2, 1))
        self.assertEqual(lines['line'][-1], done[-1])                    # the last line of the pane

    def test_the_printed_messages_are_kept_across_a_restart_and_capped(self):
        self.draw(text='Kept across.')
        speechqueue._scrollback = None                                 # a new process reads the file
        lines, _, _ = self.draw(quiet=True)
        self.assertEqual(lines['text'], ['  Kept across.'])
        for i in range(speechqueue.SCROLLBACK_KEEP + 5):
            speechqueue.spoken_log({'published': i, 'session': 's', 'text': f'line {i}'}, 'Name')
        self.assertEqual(len(speechqueue._scrollback), speechqueue.SCROLLBACK_KEEP)
        self.assertEqual(speechqueue._scrollback[-1]['text'], f'line {speechqueue.SCROLLBACK_KEEP + 4}')

    def test_a_collapsed_card_is_the_title_alone(self):
        with open(speechqueue.COLLAPSE, 'w') as f:
            f.write('on')
        lines, _, _ = self.draw(quiet=True)
        self.assertEqual(sorted(k for k in lines if k in ('title', 'terminal', 'speaker', 'clock', 'list')),
                         ['title'])

    def test_a_narrow_card_at_a_large_scale_cuts_the_title_to_what_clears_minimize(self):
        lines, regions, _ = self.draw((400, 128, 2.0))
        text = lines['title'].split(None, 3)[3]
        self.assertTrue(text.endswith('\u2026') and len(text) < len('CLAUDE CODE SESSION MANAGEMENT'))
        spaced = speechqueue.text_width(text, speechqueue.LABEL_FONT) + len(text) * speechqueue.TITLE_TRACK * 2.0 * 11 * 96 / 72
        self.assertLess(speechqueue.MARGIN + spaced, regions['minimize'][0])


class SettingsMenu(Fixture):
    def render(self, voices, size=None):
        self.three()
        with mock.patch.object(speechqueue.size_file, 'load', return_value=size or (660, 128, 1.0)):
            speechqueue.render(dict(self.state(), voices=voices), now=1000.0)
        with open(speechqueue.DRAW) as f:
            draw = f.read().splitlines()
        with open(speechqueue.REGIONS) as f:
            return draw, json.load(f)

    def test_the_menu_covers_the_card_under_its_header_and_lists_the_installed_voices(self):
        draw, regions = self.render(VOICES)
        menu = regions['menu']
        self.assertEqual(menu['voices'], VOICES)
        line = next(l for l in draw if l.startswith('menu ')).split()[1:]
        x0, y0, x1, y1, title_cy, first, row, visible, hint_cy, value_x, pad = (float(v) for v in line)
        self.assertEqual(menu['box'], [x0, y0, x1, y1])
        self.assertLess(y0, title_cy)
        self.assertLess(title_cy, first)
        self.assertLess(first + visible * row, hint_cy + row / 2)         # the rows end above the hint line
        self.assertEqual((menu['first'], menu['row'], menu['visible']), (first, row, int(visible)))
        self.assertGreaterEqual(menu['visible'], 3)
        self.assertEqual(menu['title'], [round(title_cy - row / 2, 2), round(title_cy + row / 2, 2)])
        self.assertGreater(value_x, x0)
        self.assertLess(value_x, x1)

    def test_the_header_holds_no_volume_and_no_session_has_a_gear(self):
        draw, regions = self.render(VOICES)
        for row in regions['rows']:
            self.assertNotIn('gear', row)
        self.assertEqual(next(l for l in draw if l.startswith('control ')).count(' '), 2)

    def test_each_row_carries_its_own_voice_for_the_menu(self):
        self.f.file(ME + '.voice', 'en_US-joe-medium\n')
        _, regions = self.render(VOICES)
        rows = {r['id']: r for r in regions['rows']}
        self.assertEqual([rows[i]['voice'] for i in (ME, OTHER, QUIET)], ['en_US-joe-medium', '', ''])
        for row in rows.values():
            self.assertLess(row['name'][0], row['name'][1])
            self.assertFalse({'on', 'alerts', 'off'} & set(row))

    def test_the_menu_grows_with_the_card(self):
        small = self.render(VOICES)[1]['menu']['visible']
        tall = self.render(VOICES, (660, 400, 1.0))[1]['menu']['visible']
        self.assertGreater(tall, small)


class InstalledVoices(unittest.TestCase):
    def setUp(self):
        for name, value in (('names', []), ('asked', None), ('busy', False)):
            speechqueue._voices[name] = value
        p = mock.patch.object(speechqueue.threading, 'Thread', side_effect=lambda target, daemon: mock.Mock(
            start=target))
        p.start()
        self.addCleanup(p.stop)

    def test_it_asks_speechctl_at_most_every_so_often_and_keeps_the_last_answer(self):
        with mock.patch.object(speechqueue.tray_model, 'voices', side_effect=[['a'], ['a', 'b'], []]) as voices:
            self.assertEqual(speechqueue.installed_voices(100.0), ['a'])
            self.assertEqual(speechqueue.installed_voices(105.0), ['a'])
            self.assertEqual(voices.call_count, 1)
            self.assertEqual(speechqueue.installed_voices(100.0 + speechqueue.VOICES_EVERY), ['a', 'b'])
            self.assertEqual(speechqueue.installed_voices(100.0 + 2 * speechqueue.VOICES_EVERY),
                             ['a', 'b'])                  # an empty answer is speechctl failing

    def test_a_slow_ask_is_not_asked_again_while_it_runs(self):
        speechqueue._voices['busy'] = True
        with mock.patch.object(speechqueue.tray_model, 'voices') as voices:
            speechqueue.installed_voices(100.0)
        voices.assert_not_called()


class Golden(Fixture):
    def check(self, case, state, now=1000.0):
        text = speechqueue.render(state, now=now)
        speechqueue.write_atomic(speechqueue.OUT, text)
        folder = os.path.join(GOLDEN, case)
        if os.environ.get('SPEECH_GOLDEN') == 'write':
            os.makedirs(folder, exist_ok=True)
            for name in OUTPUTS:
                shutil.copy(os.path.join(self.cache, name), os.path.join(folder, name))
        for name in OUTPUTS:
            with open(os.path.join(folder, name)) as want, open(os.path.join(self.cache, name)) as got:
                self.assertEqual(got.read(), want.read(), f'{case}/{name}')

    def test_idle(self):
        self.three()
        self.f.file(OTHER + '.queue', '')
        self.check('idle', self.state())

    def test_playing(self):
        self.three()
        self.f.now(ME, 'Claude Voice Widget', 'The data layer is in: speechqueue.py writes the '
                   'widget, draw and regions files four times a second.', hook_pid=9001)
        os.utime(os.path.join(self.f.speak, 'now.json'), (998.0, 998.0))
        self.f.wav(9001, 6.0)
        self.check('playing', self.state())

    def footer(self):
        """(draw.txt's lines by key, regions.json) as render() just wrote them."""
        with open(speechqueue.DRAW) as f:
            lines = {l.split()[0]: l.split()[1:] for l in f.read().splitlines()}
        with open(speechqueue.REGIONS) as f:
            return lines, json.load(f)

    def test_skip_and_next_are_round_buttons_in_the_footer_after_pause(self):
        self.three()
        self.f.now(ME, 'Claude Voice Widget', 'The data layer is in.', hook_pid=9001)
        os.utime(os.path.join(self.f.speak, 'now.json'), (998.0, 998.0))
        self.f.wav(9001, 6.0)
        speechqueue.render(self.state(), now=1000.0)
        lines, regions = self.footer()
        pause_cx, footer_y, size = (float(v) for v in lines['footer'][:3])
        skip_cx, next_cx, y, button, active = (float(v) for v in lines['buttons'])
        gap = speechqueue.FOOTER_BUTTON_GAP
        self.assertEqual((skip_cx, next_cx, y, button, active),
                         (pause_cx + size + gap, pause_cx + 2 * (size + gap), footer_y, size, 1))
        for key, cx in (('pause', pause_cx), ('skip', skip_cx), ('next', next_cx)):
            self.assertEqual(((regions[key][0] + regions[key][2]) / 2, (regions[key][1] + regions[key][3]) / 2),
                             (cx, footer_y), key)
        self.assertLessEqual(regions['pause'][2], regions['skip'][0])        # side by side, not overlapping
        self.assertLessEqual(regions['skip'][2], regions['next'][0])
        self.assertLess(regions['next'][2], regions['volume'][0])            # clear of the volume slider
        self.assertGreater(regions['skip'][1], regions['close'][3])          # and not in the header

    def test_the_slider_shortens_as_the_card_narrows(self):
        self.three()
        widths = {}
        for size in ((660, 128, 1.0), (200, 128, 1.0)):
            with mock.patch.object(speechqueue.size_file, 'load', return_value=size):
                speechqueue.render(self.state(), now=1000.0)
            lines, regions = self.footer()
            x0, x1 = (float(v) for v in lines['volume'][:2])
            widths[size] = x1 - x0
            self.assertEqual(regions['volume_bar'], [x0, x1])
            icon = float(lines['volume'][4])
            self.assertEqual(regions['volume_icon'][0], icon - 4)       # the speaker takes a click too
            self.assertEqual(regions['volume_icon'][2], regions['volume'][0])
        self.assertEqual(widths[(660, 128, 1.0)], speechqueue.VOLUME_WIDTH)
        self.assertLess(widths[(200, 128, 1.0)], speechqueue.VOLUME_WIDTH)
        self.assertGreaterEqual(widths[(200, 128, 1.0)], speechqueue.VOLUME_MIN)

    def test_without_a_clip_the_buttons_are_drawn_dimmed_and_are_not_click_areas(self):
        self.three()
        speechqueue.render(self.state(), now=1000.0)
        lines, regions = self.footer()
        self.assertEqual(lines['buttons'][4], '0')
        self.assertFalse({'skip', 'next'} & set(regions))
        self.assertIn('pause', regions)

    def test_after_a_line_the_pane_keeps_what_was_printed(self):
        self.three()
        self.f.now(ME, 'Claude Voice Widget', 'Done.', hook_pid=9001)
        os.utime(os.path.join(self.f.speak, 'now.json'), (998.0, 998.0))
        self.f.wav(9001, 6.0)
        speechqueue.render(self.state(), now=1000.0)
        os.remove(os.path.join(self.f.speak, 'now.json'))
        self.f.file(OTHER + '.queue', '')
        speechqueue.render(self.state(), now=1010.0)
        with open(speechqueue.DRAW) as f:
            lines = f.read().splitlines()
        self.assertIn('line ' + speechqueue.BULLET_MARK + '  Done.', lines)  # the message stays printed
        self.assertIn('speaker Combined Session Output', lines)          # titled the same after the line
        self.assertEqual(next(l for l in lines if l.startswith('clock ')).split()[2:], ['0.000', '0.000', '0'])

    def test_paused(self):
        self.three()
        self.f.now(ME, 'Claude Voice Widget', 'Paused part way.', hook_pid=9001)
        os.utime(os.path.join(self.f.speak, 'now.json'), (998.0, 998.0))
        self.f.wav(9001, 4.0)
        self.f.file('paused')
        self.check('paused', self.state())

    def test_issue_numbers_head_the_message_of_their_session(self):
        self.three()
        self.f.now(ME, 'Claude Voice Widget', 'Three issues, then one, then too many for a line.', hook_pid=9001)
        os.utime(os.path.join(self.f.speak, 'now.json'), (998.0, 998.0))
        self.f.wav(9001, 6.0)
        state = self.state()
        mine, other, quiet = state['sessions']
        issues = lambda *numbers: [(f'#{n}', f'https://github.com/o/r/issues/{n}') for n in numbers]
        mine.update(repo='Gnome-Widgets', issues=issues(127, 131, 133))
        other.update(repo='fagerteam-health-coach', issues=issues(214))
        quiet.update(repo='TheRPGClub-bot', issues=issues(31, 48, 52, 53, 60, 61, 64, 70, 71))
        self.check('issues', state)

    def test_many_sessions_scroll(self):
        for i in range(8):
            self.f.session(100 + i, f'{i:08d}-eeee', f'Session {i}')
            self.f.queue(f'{i:08d}-eeee', f'Line {i}')
        self.check('scroll', self.state())

    def test_the_settings_menu_and_its_voices(self):
        self.three()
        self.f.file('settings.json', json.dumps({'voice': 'en_GB-jenny_dioco-medium'}))
        self.check('menu', dict(self.state(), voices=VOICES))

    def test_collapse_when_idle(self):
        self.three()
        self.f.file(OTHER + '.queue', '')
        with open(speechqueue.COLLAPSE, 'w') as fh:
            fh.write('on\n')
        self.check('collapse', self.state())


if __name__ == '__main__':
    unittest.main()
