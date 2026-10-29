"""speechqueue.py: the speech widget's state, read from fixture files, and the files it writes.

The golden samples under tests/golden/speech/<case>/ are what render() writes for each
case. After a change to the layout that is meant, write them again with
    SPEECH_GOLDEN=write python3 -m unittest tests.test_speechqueue
and read the diff before committing it.
"""
import json
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

    def test_each_issue_number_opens_its_issue_and_the_name_the_pull_requests_each_only_with_one(self):
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
        self.assertLess(one['issues'][1][2], one['link'][0])        # the block, then the name
        self.assertLess(one['link'][1], one['on'][0])               # clear of the setting
        self.assertFalse({'link', 'prs'} & set(two))

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

    def test_the_block_is_as_wide_as_the_longest_name_within_its_limits(self):
        width = lambda *names: speechqueue.block_width([dict(repo=n) for n in names])
        chrome = speechqueue.BLOCK_RULE + speechqueue.BLOCK_PAD
        with mock.patch.object(speechqueue, 'text_width', side_effect=lambda t, f: 5 * len(t)):
            self.assertEqual(width('ab', 'cd'), chrome + speechqueue.BLOCK_MIN)
            self.assertEqual(width('a' * 30, 'b'), chrome + 150)
            self.assertEqual(width('a' * 100), chrome + speechqueue.BLOCK_MAX)
            self.assertEqual(width(), chrome + speechqueue.BLOCK_MIN)

    def test_the_issue_chips_wrap_onto_the_next_line_when_they_pass_the_width(self):
        with mock.patch.object(speechqueue, 'text_width', side_effect=lambda t, f: 10 * len(t)):
            issues = [(f'#{n}', f'link{n}') for n in (127, 131, 133, 5)]
            chips, lines = speechqueue.block_chips(issues, 110)
        pad, gap = speechqueue.CHIP_PAD, speechqueue.CHIP_GAP
        w = 40 + 2 * pad
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


class VoiceDropDown(Fixture):
    def render(self, voices, voice='en_GB-jenny_dioco-medium'):
        self.three()
        self.f.file('settings.json', json.dumps({'voice': voice}))
        speechqueue.render(dict(self.state(), voices=voices), now=1000.0)
        with open(speechqueue.DRAW) as f:
            draw = f.read().splitlines()
        with open(speechqueue.REGIONS) as f:
            return draw, json.load(f)

    def test_the_drop_down_names_the_voice_and_the_list_has_every_voice_with_the_current_marked(self):
        draw, regions = self.render(VOICES)
        self.assertTrue(next(l for l in draw if l.startswith('voice ')).endswith(' Voice: jenny_dioco'))
        self.assertEqual([l for l in draw if l.startswith('item ')],
                         ['item 0 alan', 'item 1 jenny_dioco', 'item 0 amy', 'item 0 hfc_female',
                          'item 0 joe', 'item 0 lessac', 'item 0 libritts', 'item 0 ryan'])
        self.assertEqual((regions['menu']['names'], regions['menu']['current']), (VOICES, 1))

    def test_the_arrows_are_gone(self):
        _, regions = self.render(VOICES)
        self.assertFalse({'voice_prev', 'voice_next'} & set(regions))

    def test_the_list_opens_upward_from_the_drop_downs_right_edge(self):
        _, regions = self.render(VOICES)
        drop, (x0, top, x1, bottom) = regions['voice'], regions['menu']['box']
        self.assertEqual(x1, drop[2])
        self.assertLess(bottom, drop[1])                      # clear of the drop down, above it
        self.assertLess(x0, drop[2])
        self.assertGreater(top, 0)
        self.assertEqual(round(bottom - top - 2 * regions['menu']['pad'], 2),
                         round(regions['menu']['rows'] * regions['menu']['item_h'], 2))

    def test_a_list_longer_than_fits_shows_the_rows_that_fit(self):
        many = [f'en_US-voice{i:02d}-medium' for i in range(40)]
        draw, regions = self.render(many, voice=many[20])
        menu = regions['menu']
        self.assertTrue(speechqueue.MENU_MIN_ROWS <= menu['rows'] < len(many))
        self.assertEqual(len([l for l in draw if l.startswith('item ')]), len(many))
        self.assertGreater(menu['box'][1], 0)                          # inside the card
        self.assertEqual(menu['current'], 20)
        narrow = self.render(VOICES)[1]['menu']['box']
        self.assertGreater(menu['box'][2] - menu['box'][0], 0)
        self.assertEqual(menu['box'][2], narrow[2])

    def test_a_short_list_shows_only_its_voices(self):
        _, regions = self.render(VOICES[:2])
        self.assertEqual(regions['menu']['rows'], 2)

    def test_without_voices_there_is_no_list_but_the_drop_down_stays(self):
        draw, regions = self.render([])
        self.assertNotIn('menu', regions)
        self.assertFalse([l for l in draw if l.startswith(('menu ', 'item '))])
        self.assertIn('voice', regions)

    def test_the_drop_down_and_the_footer_grow_with_the_text(self):
        heights = {}
        for scale in (1.0, 2.0):
            with mock.patch.object(speechqueue.size_file, 'load', return_value=(660, 128, scale)):
                _, regions = self.render(VOICES)
            drop = regions['voice']
            heights[scale] = (drop[3] - drop[1], regions['pause'][1])
            line = speechqueue.line_height(speechqueue.FOOTER_FONT)
            self.assertGreaterEqual(drop[3] - drop[1], line)         # the label fits its pill
        self.assertEqual(heights[1.0][0], speechqueue.DROPDOWN_H)    # as before at scale 1
        self.assertGreater(heights[2.0][0], heights[1.0][0])

    def test_a_voice_that_is_not_installed_marks_none(self):
        _, regions = self.render(VOICES, voice='de_DE-thorsten-medium')
        self.assertEqual(regions['menu']['current'], -1)

    def test_a_long_name_is_cut_to_the_room_left_of_the_volume(self):
        draw, regions = self.render(VOICES, voice='en_US-' + 'x' * 120 + '-medium')
        self.assertIn('…', next(l for l in draw if l.startswith('voice ')))
        self.assertGreater(regions['voice'][0], regions['volume'][2])


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

    def test_the_voice_drop_down_and_its_open_list(self):
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
