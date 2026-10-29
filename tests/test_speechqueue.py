"""speechqueue.py: the speech widget's state, read from fixture files, and the files it writes.

The golden samples under tests/golden/speech/<case>/ are what render() writes for each
case. After a change to the layout that is meant, write them again with
    SPEECH_GOLDEN=write python3 -m unittest tests.test_speechqueue
and read the diff before committing it.
"""
import json
import math
import os
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
                            ('LAST', os.path.join(self.root, 'last-lines.json')), ('_last', None),
                            ('HEARD', os.path.join(self.root, 'last-heard.json')), ('_heard', None),
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
        self.f.session(200, QUIET, 'Docs pass', kind='bg')
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
        self.assertTrue(s[2]['background'])

    def test_a_queued_question_is_a_tag_not_a_line(self):
        self.f.session(100, ME, 'One')
        self.f.queue(ME, 'Question: Open the pull request? Options: yes or no.')
        s = self.state()['sessions'][0]
        self.assertEqual((s['queued'], s['question']), (1, True))
        self.assertIn('question', speechqueue.session_line(s).split('\t')[4].split(','))

    def test_an_on_session_keeps_its_last_line_and_others_have_none(self):
        self.three()
        line = lambda sid: next(speechqueue.session_line(x) for x in self.state()['sessions']
                                if x['id'] == sid).split('\t')[7]
        self.assertEqual(line(ME), speechqueue.NOTHING_SAID)
        self.assertEqual(line(OTHER), '')
        self.f.now(ME, 'Claude Voice Widget', 'Pass 1 is pushed.')
        self.assertEqual(line(ME), 'Pass 1 is pushed.')
        self.f.now(ME, 'Claude Voice Widget', 'Question: Open it? Options: yes or no.')
        self.assertEqual(line(ME), 'Pass 1 is pushed.')
        os.remove(os.path.join(self.f.speak, 'now.json'))
        self.assertEqual(line(ME), 'Pass 1 is pushed.')
        speechqueue._last = None                       # a restart reads it back from LAST
        self.assertEqual(line(ME), 'Pass 1 is pushed.')

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
        self.assertEqual(flags(QUIET), ['waiting: merge'])        # one tag: waiting over bg

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
        self.assertEqual(flags(QUIET), 'waiting: tests')          # over bg
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
        self.assertEqual((flags(ME), flags(OTHER), flags(QUIET)), ('busy', 'idle', 'bg'))
        self.f.queue(ME, 'Question: Merge it? Options: yes or no.')
        self.f.ledger(ME, ('pr:111', 'open'))
        self.assertEqual(flags(ME), 'question')                   # over busy and waiting
        self.f.queue(QUIET, 'Question: Which one?')
        self.assertEqual(flags(QUIET), 'question')                # over bg

    def test_the_second_row_drops_the_hooks_speaker(self):
        self.three()
        line = lambda: next(speechqueue.session_line(x) for x in self.state()['sessions']
                            if x['id'] == ME).split('\t')[7]
        self.f.now(ME, 'Claude Voice Widget', 'Claude Voice Widget session says: PR 110 merged.')
        self.assertEqual(line(), 'PR 110 merged.')
        self.assertEqual(speechqueue.last_lines(None, {ME})[ME],
                         'Claude Voice Widget session says: PR 110 merged.')   # kept whole
        self.f.now(ME, 'Claude Voice Widget', 'It says: nothing here, mid-line it stays.')
        self.assertEqual(line(), 'It says: nothing here, mid-line it stays.')     # not the hook's
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
        self.assertEqual(speechqueue.voice_label(state['voice']), 'alan')
        self.assertEqual(speechqueue.voice_label('my-voice'), 'my-voice')


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

    def test_the_pill_names_the_ready_pull_requests(self):
        pr = 'https://github.com/o/r/pull/'
        self.assertEqual(speechqueue.link_pill([pr + '151']), 'PR #151')
        self.assertEqual(speechqueue.link_pill([pr + '151', pr + '152']), '2 PRs')
        self.assertEqual(speechqueue.link_pill([]), '')

    def test_the_ledgers_open_pull_requests_are_the_ready_ones(self):
        self.f.session(100, ME, 'One')
        self.pr_ledger(ME, (150, 'done'), (151, 'open'), (152, 'open'))
        s = self.state()['sessions'][0]
        self.assertEqual(s['prs'], ['https://github.com/someone/Gnome-Widgets/pull/151',
                                    'https://github.com/someone/Gnome-Widgets/pull/152'])
        self.assertEqual(speechqueue.session_line(s).split('\t')[8:], ['2 PRs', '', '1'])

    def test_the_pill_shows_for_a_ledger_another_repository_keeps(self):
        # ledger.tsv and catchup.tsv, with a branch column after the label
        self.f.session(100, ME, 'One')
        self.f.session(200, OTHER, 'Two')
        self.f.branch_ledger(ME, 'ledger.tsv', ('pr:151', 'done'), ('pr:152', 'open'))
        self.f.branch_ledger(OTHER, 'catchup.tsv', ('pr:7', 'open'), ('pr:8', 'open'))
        one, two = self.state()['sessions']
        self.assertEqual(one['prs'], ['https://github.com/o/r/pull/152'])
        self.assertEqual(speechqueue.session_line(one).split('\t')[8], 'PR #152')
        self.assertEqual(speechqueue.session_line(two).split('\t')[8], '2 PRs')
        self.assertEqual(one['waiting'], 'merge')
        self.f.branch_ledger(ME, 'ledger.tsv', ('pr:152', 'done'))
        self.assertEqual(self.state()['sessions'][0]['prs'], [])

    def test_one_pill_counts_the_open_rows_of_both_layouts(self):
        self.f.session(100, ME, 'One')
        self.pr_ledger(ME, (151, 'open'))
        self.f.branch_ledger(ME, 'ledger.tsv', ('pr:152', 'open'), ('pr:153', 'done'))
        self.assertEqual(self.state()['sessions'][0]['prs'],
                         ['https://github.com/someone/Gnome-Widgets/pull/151', 'https://github.com/o/r/pull/152'])

    def test_each_issue_opens_its_issue_the_pill_the_pull_requests_and_the_name_closes_the_session(self):
        self.f.session(100, ME, 'One')
        self.f.session(200, OTHER, 'Two')
        self.pr_ledger(ME, (151, 'open'))
        with mock.patch.object(speechqueue, 'session_branch',
                               side_effect=lambda cwd: ('feat/issue-127-repo-box-links', 'someone/Gnome-Widgets')):
            state = self.state()
        state['sessions'][1]['issue'] = 'https://github.com/someone/Gnome-Widgets/issues/131'
        for s in state['sessions']:
            s['repo'] = 'Gnome-Widgets'
        speechqueue.repo_issues(state['sessions'])
        speechqueue.render(state)
        with open(speechqueue.REGIONS) as f:
            one, two = json.load(f)['rows']
        links = ['https://github.com/someone/Gnome-Widgets/issues/127',
                 'https://github.com/someone/Gnome-Widgets/issues/131']
        for row in (one, two):                                      # the repository's issues, on each
            self.assertEqual([chip[4] for chip in row['issues']], links)
            self.assertLess(row['issues'][0][2], row['issues'][1][0])   # side by side, a gap between
        self.assertEqual(one['issues'][0][0], speechqueue.MARGIN + speechqueue.BLOCK_RULE + speechqueue.BLOCK_PAD)
        with open(speechqueue.SESSIONS) as f:
            lines = [line.split('\t') for line in f.read().splitlines()]
        self.assertEqual([l[6] for l in lines], ['Gnome-Widgets', 'Gnome-Widgets'])
        self.assertEqual([l[8] for l in lines], ['PR #151', ''])
        self.assertEqual([[t.split(':')[3] for t in l[9].split()] for l in lines], [['#127', '#131']] * 2)
        self.assertEqual(one['prs'], ['https://github.com/someone/Gnome-Widgets/pull/151'])
        self.assertLess(one['issues'][1][2], one['name'][0])       # the block, then the name
        self.assertEqual(one['name'][1], one['link'][0])           # then the pill
        self.assertLess(one['link'][1], one['gear'][0])            # clear of the gear
        self.assertFalse({'link', 'prs'} & set(two))
        self.assertEqual([(r['pid'], r['title'], r['busy']) for r in (one, two)],
                         [(100, 'One', False), (200, 'Two', False)])
        self.assertLess(two['name'][0], two['name'][1])            # every name is there to click
        self.assertLess(two['name'][1], two['gear'][0])


    def test_a_session_without_issues_has_no_chips_and_one_row(self):
        self.f.session(100, ME, 'One')
        state = self.state()
        state['sessions'][0]['repo'] = 'Gnome-Widgets'
        speechqueue.render(state)
        with open(speechqueue.REGIONS) as f:
            row = json.load(f)['rows'][0]
        with open(speechqueue.SESSIONS) as f:
            line = f.read().splitlines()[0].split('\t')
        self.assertNotIn('issues', row)
        self.assertEqual(line[9:], ['', '1'])

    def test_a_repository_lists_the_issues_of_the_sessions_in_it_in_number_order(self):
        issue = lambda repo, n: f'https://github.com/{repo}/issues/{n}'
        listed = [dict(github='o/a', issue=issue('o/a', 31)), dict(github='o/a', issue=issue('o/a', 7)),
                  dict(github='o/a', issue=issue('o/a', 31)), dict(github='o/a', issue=''),
                  dict(github='o/b', issue=issue('o/b', 2)), dict(github='', issue='')]
        speechqueue.repo_issues(listed)
        self.assertEqual([[n for n, _ in s['issues']] for s in listed],
                         [['#7', '#31']] * 4 + [['#2'], []])
        self.assertEqual(listed[0]['issues'][0][1], issue('o/a', 7))

    def test_the_block_is_as_wide_as_the_longest_name_and_never_below_its_least(self):
        width = lambda *names: speechqueue.block_width([dict(repo=n) for n in names])
        chrome = speechqueue.BLOCK_RULE + speechqueue.BLOCK_PAD
        with mock.patch.object(speechqueue, 'text_width', side_effect=lambda t, f: 5 * len(t)):
            self.assertEqual(width('ab', 'cd'), chrome + speechqueue.BLOCK_MIN)
            self.assertEqual(width('a' * 30, 'b'), chrome + math.ceil(150 * speechqueue.BLOCK_SLACK))
            self.assertEqual(width('a' * 100), chrome + math.ceil(500 * speechqueue.BLOCK_SLACK))
            self.assertEqual(width(), chrome + speechqueue.BLOCK_MIN)

    def test_the_issue_numbers_wrap_onto_the_next_line_when_they_pass_the_width(self):
        with mock.patch.object(speechqueue, 'text_width', side_effect=lambda t, f: 10 * len(t)):
            issues = [(f'#{n}', f'link{n}') for n in (127, 131, 133, 5)]
            chips, lines = speechqueue.block_chips(issues, 110)
        pad, gap = speechqueue.CHIP_PAD, speechqueue.CHIP_GAP
        w = 40 + pad
        self.assertEqual([(c[0], c[1]) for c in chips],
                         [(0, 0), (1, 0), (2, 0), (2, w + gap)] if w * 2 + gap > 110 else
                         [(0, 0), (0, w + gap), (1, 0), (1, w + gap)])
        self.assertEqual(lines, chips[-1][0] + 1)
        self.assertEqual(speechqueue.block_chips([], 110), ([], 0))

    def test_a_session_takes_the_rows_its_block_needs_or_the_two_speech_on_takes(self):
        self.f.session(100, ME, 'One')
        self.f.session(200, OTHER, 'Two')
        self.f.file(ME + '.replies')
        state = self.state()
        for s in state['sessions']:
            s['repo'] = 'Gnome-Widgets'
        speechqueue.render(state)
        with open(speechqueue.SESSIONS) as f:
            spans = [int(line.split('\t')[10]) for line in f.read().splitlines()]
        self.assertEqual(spans, [2, 1])                             # no issues: speech on takes two
        for s in state['sessions']:
            s['issues'] = [(f'#{n}', f'link{n}') for n in range(1, 40)]    # far more than a line holds
        speechqueue.render(state)
        with open(speechqueue.SESSIONS) as f:
            lines = [line.split('\t') for line in f.read().splitlines()]
        with open(speechqueue.REGIONS) as f:
            rows = json.load(f)['rows']
        spans = [int(l[10]) for l in lines]
        self.assertGreater(min(spans), 2)
        self.assertEqual([r['bottom'] - r['top'] for r in rows], [sp * 24 for sp in spans])
        last_line = max(int(t.split(':')[0]) for t in lines[0][9].split())
        self.assertGreaterEqual(last_line, 1)                       # it wrapped
        self.assertGreaterEqual(spans[0] * 24, rows[0]['issues'][-1][3])    # the last chip is inside the row

    def test_the_close_prompt_is_a_panel_over_the_list_with_cancel_before_ok(self):
        self.f.session(100, ME, 'One')
        speechqueue.render(self.state())
        with open(speechqueue.REGIONS) as f:
            regions = json.load(f)
        prompt, (x0, top, x1, bottom) = regions['confirm'], regions['list']
        box = prompt['box']
        self.assertTrue(x0 <= box[0] < box[2] <= x1 and box[3] - box[1] > 0)
        for key in ('cancel', 'ok'):
            self.assertTrue(box[0] <= prompt[key][0] < prompt[key][2] <= box[2], key)
            self.assertTrue(box[1] <= prompt[key][1] < prompt[key][3] <= box[3], key)
        self.assertLess(prompt['cancel'][2], prompt['ok'][0])
        with open(speechqueue.DRAW) as f:
            line = next(l for l in f.read().splitlines() if l.startswith('confirm '))
        self.assertEqual([float(v) for v in line.split()[1:5]], box)



@unittest.skipUnless(shutil.which('lua5.3'), 'lua5.3 is not installed')
class SharedColours(unittest.TestCase):
    """Both widgets' draw.lua, loaded side by side, with the Spotify widget's bg.txt driven
    through a light colour, a dark one and away again: each frame they give conky the same
    title and text colours, white on Spotify's #181818 while there is no bg.txt."""

    HARNESS = """
package.preload['cairo'] = function() return true end
cairo_text_extents_t = {create = function() return {} end}
cairo_font_extents_t = cairo_text_extents_t
conky_info = {update_interval = 0.05}
local function load(path)
    dofile(path)
    return conky_widget, conky_fg
end
local spotify_widget, spotify_fg = load(SPOTIFY)
local speech_widget, speech_fg = load(SPEECH)
local theme, T = package.loaded.theme, 1000
theme.now = function() return T end
theme.BOOT = 'boot-1'
local function put(path, text)
    if text then local f = assert(io.open(path, 'w')); f:write(text); f:close()
    else os.remove(path) end
end
for _, step in ipairs(STEPS) do
    put(step.path, step.text)
    if step.late then speech_widget, speech_fg = load(SPEECH) end
    for _ = 1, step.frames do
        spotify_widget(); speech_widget()
        T = T + 0.05
        print(table.concat({spotify_fg('title'), spotify_fg('text'),
                            speech_fg('title'), speech_fg('text')}, '\\t'))
    end
end
"""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix='speech-colours-')
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.spotify = os.path.join(self.home, '.cache', 'conky-spotify-nowplaying')
        self.setting = os.path.join(self.home, '.config', 'conky-widgets', 'speech', 'background')
        os.makedirs(self.spotify)
        os.makedirs(os.path.dirname(self.setting))
        self.bg = os.path.join(self.spotify, 'bg.txt')

    def frames(self, steps):
        """Each frame's colours, as (Spotify's title, its text, speech's title, its text)."""
        lua = ', '.join('{path = %s, text = %s, frames = %d, late = %s}' % (
            json.dumps(path), json.dumps(text) if text is not None else 'nil', n,
            'true' if late else 'false')
            for path, text, n, *late in steps)
        script = (self.HARNESS
                  .replace('SPOTIFY', json.dumps(os.path.join(support.SRC, 'spotify', 'draw.lua')))
                  .replace('SPEECH', json.dumps(os.path.join(support.SRC, 'speech', 'draw.lua')))
                  .replace('STEPS', '{' + lua + '}'))
        out = subprocess.run(['lua5.3', '-'], input=script, capture_output=True, text=True,
                             check=True, env=dict(os.environ, HOME=self.home)).stdout
        return [tuple(line.split('\t')) for line in out.splitlines()]

    def test_both_widgets_pick_the_same_colours(self):
        frames = self.frames([(self.bg, None, 20),               # no bg.txt yet
                              (self.bg, '0.950 0.900 0.800', 40),  # a light cover
                              (self.bg, '0.157 0.275 0.549', 40),  # a dark one
                              (self.bg, None, 40)])              # gone again
        self.assertEqual(len(frames), 140)
        for i, f in enumerate(frames):
            self.assertEqual(f[:2], f[2:], f'frame {i}')
        self.assertEqual(frames[0][0], '${color ffffff}')       # white on #181818
        self.assertEqual(frames[59][0], '${color 121212}')      # near-black on the light cover
        self.assertEqual(frames[99][0], '${color ffffff}')
        self.assertEqual(frames[-1][0], '${color ffffff}')      # back to the fallback
        with open(self.bg, 'w') as f:
            f.write('0.188 0.424 0.463')
        self.frames([(self.bg, '0.188 0.424 0.463', 5)])
        with open(self.bg) as f:
            self.assertEqual(f.read(), '0.188 0.424 0.463')     # read, never written

    def test_a_widget_started_part_way_shows_the_same_colour(self):
        # bg.txt as art_colours.py writes it: black to white from 1000 s, the harness's first
        # frame. The speech widget, loaded again half a second in with its own #181818, takes
        # the near-black text the light grey there needs from its first frame, as the Spotify
        # widget does, rather than fading from #181818 under white.
        fade = '1.000 1.000 1.000 0.000 0.000 0.000 1000.000 boot-1'
        frames = self.frames([(self.bg, fade, 10), (self.bg, fade, 30, True)])
        for i, f in enumerate(frames):
            self.assertEqual(f[:2], f[2:], f'frame {i}')
        self.assertEqual(frames[0][0], '${color ffffff}')
        self.assertEqual(frames[10][2], '${color 121212}')

    def test_the_fade_takes_wall_clock_time(self):
        # 20 frames of 0.05 s: one second in, the fade is 95% of the way, so near-black text
        fade = '0.950 0.900 0.800 0.094 0.094 0.094 1000.000 boot-1'
        frames = self.frames([(self.bg, fade, 21)])
        self.assertEqual(frames[0][0], '${color ffffff}')
        self.assertEqual(frames[20][0], '${color 121212}')

    def test_a_fade_from_another_boot_is_finished(self):
        # written before a reboot at 999.5 s: the new boot's clock reads 1000 s, half a second
        # on, but the fade is long done, so the light colour's near-black text from the start
        fade = '0.950 0.900 0.800 0.094 0.094 0.094 999.500 boot-0'
        self.assertEqual(self.frames([(self.bg, fade, 1)])[0][0], '${color 121212}')

    def test_falling_back_to_an_earlier_colour_fades_again(self):
        # #181818 without bg.txt, a timed fade to a light colour, then bg.txt gone: back to
        # #181818 over a second, not at once
        fade = '0.950 0.900 0.800 0.094 0.094 0.094 1000.000 boot-1'
        frames = self.frames([(self.bg, None, 2), (self.bg, fade, 40), (self.bg, None, 25)])
        self.assertEqual(frames[41][0], '${color 121212}')
        self.assertEqual(frames[43][0], '${color 121212}')     # still light just after
        self.assertEqual(frames[-1][0], '${color ffffff}')

    def test_the_setting_names_another_file(self):
        other = os.path.join(self.home, 'other.txt')
        frames = self.frames([(self.setting, '~/other.txt\n', 0),
                              (other, '0.950 0.900 0.800', 40)])
        self.assertEqual(frames[-1][0], '${color ffffff}')      # Spotify's still on #181818
        self.assertEqual(frames[-1][2], '${color 121212}')      # speech follows other.txt


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


class SettingsPopup(Fixture):
    def render(self, voices, voice='en_GB-jenny_dioco-medium'):
        self.three()
        self.f.file('settings.json', json.dumps({'voice': voice}))
        speechqueue.render(dict(self.state(), voices=voices), now=1000.0)
        with open(speechqueue.DRAW) as f:
            draw = f.read().splitlines()
        with open(speechqueue.REGIONS) as f:
            return draw, json.load(f)

    def test_the_popup_offers_the_global_voice_first_and_then_every_installed_one(self):
        draw, regions = self.render(VOICES)
        self.assertEqual([l for l in draw if l.startswith('item ')],
                         ['item 0 Default (jenny_dioco)', 'item 0 alan', 'item 0 jenny_dioco', 'item 0 amy',
                          'item 0 hfc_female', 'item 0 joe', 'item 0 lessac', 'item 0 libritts', 'item 0 ryan'])
        self.assertEqual(regions['settings']['names'], [''] + VOICES)

    def test_the_footer_has_no_voice_drop_down_or_list(self):
        draw, regions = self.render(VOICES)
        self.assertFalse({'voice', 'menu'} & set(regions))
        self.assertFalse([l for l in draw if l.startswith(('voice ', 'menu '))])

    def test_the_popup_is_a_panel_over_the_list_holding_its_buttons_voices_and_done(self):
        draw, regions = self.render(VOICES)
        popup, (x0, top, x1, bottom) = regions['settings'], regions['list']
        box = popup['box']
        self.assertTrue(x0 <= box[0] < box[2] <= x1 and box[3] - box[1] > 0)
        buttons = [popup['speech'][key] for key in ('on', 'alerts', 'off')]
        self.assertEqual(list(popup['speech']), ['on', 'alerts', 'off'])
        for b in buttons + [popup['list'], popup['done']]:
            self.assertTrue(box[0] <= b[0] < b[2] <= box[2] and box[1] <= b[1] < b[3] <= box[3], b)
        self.assertTrue(buttons[0][2] < buttons[1][0] and buttons[1][2] < buttons[2][0])    # side by side
        self.assertLess(buttons[0][3], popup['list'][1])                  # buttons, then the voices
        self.assertLess(popup['list'][3], popup['done'][1])               # then Done, at the right
        self.assertEqual(popup['done'][2], buttons[2][2])
        line = next(l for l in draw if l.startswith('settings '))
        self.assertEqual([float(v) for v in line.split()[1:5]], box)

    def test_a_long_list_shows_four_rows_and_a_short_one_only_its_voices(self):
        many = [f'en_US-voice{i:02d}-medium' for i in range(40)]
        draw, regions = self.render(many, voice=many[20])
        popup = regions['settings']
        self.assertEqual((popup['rows'], len(popup['names'])), (speechqueue.SETTINGS_ROWS, 41))
        self.assertEqual(len([l for l in draw if l.startswith('item ')]), 41)
        self.assertEqual(round(popup['list'][3] - popup['list'][1] - 2 * popup['pad'], 2),
                         round(popup['rows'] * popup['item_h'], 2))
        self.assertEqual(self.render(VOICES[:2])[1]['settings']['rows'], 3)      # the global one and two

    def test_without_installed_voices_the_global_one_is_the_only_row(self):
        draw, regions = self.render([])
        self.assertEqual((regions['settings']['names'], regions['settings']['rows']), ([''], 1))
        self.assertEqual([l for l in draw if l.startswith('item ')], ['item 0 Default (jenny_dioco)'])

    def test_the_popup_grows_with_the_text(self):
        heights = {}
        for scale in (1.0, 2.0):
            with mock.patch.object(speechqueue.size_file, 'load', return_value=(660, 128, scale)):
                _, regions = self.render(VOICES)
            box, popup = regions['settings']['box'], regions['settings']
            heights[scale] = (box[3] - box[1], popup['speech']['on'][3] - popup['speech']['on'][1])
            self.assertGreaterEqual(popup['item_h'], speechqueue.line_height(speechqueue.FOOTER_FONT))
        self.assertGreater(heights[2.0][0], heights[1.0][0])
        self.assertGreater(heights[2.0][1], heights[1.0][1])

    def test_each_row_has_a_gear_at_its_right_and_carries_its_own_voice(self):
        self.f.file(ME + '.voice', 'en_US-joe-medium\n')
        _, regions = self.render(VOICES)
        rows = {r['id']: r for r in regions['rows']}
        self.assertEqual([rows[i]['voice'] for i in (ME, OTHER, QUIET)], ['en_US-joe-medium', '', ''])
        for row in rows.values():
            self.assertEqual(row['gear'][1], regions['list'][2])           # at the list's right edge
            self.assertLess(row['name'][1], row['gear'][0])
            self.assertFalse({'on', 'alerts', 'off'} & set(row))
        with open(speechqueue.DRAW) as f:
            control = next(l for l in f.read().splitlines() if l.startswith('control ')).split()[1:]
        self.assertEqual([float(v) for v in control[:2]], rows[ME]['gear'])


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

    def test_after_a_line_the_header_and_full_bar_stay(self):
        self.three()
        self.f.now(ME, 'Claude Voice Widget', 'Done.', hook_pid=9001)
        os.utime(os.path.join(self.f.speak, 'now.json'), (998.0, 998.0))
        self.f.wav(9001, 6.0)
        speechqueue.render(self.state(), now=1000.0)
        os.remove(os.path.join(self.f.speak, 'now.json'))
        self.f.file(OTHER + '.queue', '')
        text = speechqueue.render(self.state(), now=1010.0)
        self.assertIn('Claude Voice Widget says:', text)
        self.assertNotIn('Speech idle', text)
        with open(speechqueue.DRAW) as f:
            progress = next(l for l in f if l.startswith('progress ')).split()
        self.assertEqual(progress[5:], ['6.000', '6.000', '0'])

    def test_paused(self):
        self.three()
        self.f.now(ME, 'Claude Voice Widget', 'Paused part way.', hook_pid=9001)
        os.utime(os.path.join(self.f.speak, 'now.json'), (998.0, 998.0))
        self.f.wav(9001, 4.0)
        self.f.file('paused')
        self.check('paused', self.state())

    def test_repository_names_and_issue_numbers_wrap_inside_the_block(self):
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

    def test_the_settings_popup_and_its_voices(self):
        self.three()
        self.f.file('settings.json', json.dumps({'voice': 'en_GB-jenny_dioco-medium'}))
        self.check('voices', dict(self.state(), voices=VOICES))

    def test_collapse_when_idle(self):
        self.three()
        self.f.file(OTHER + '.queue', '')
        with open(speechqueue.COLLAPSE, 'w') as fh:
            fh.write('on\n')
        self.check('collapse', self.state())


if __name__ == '__main__':
    unittest.main()
