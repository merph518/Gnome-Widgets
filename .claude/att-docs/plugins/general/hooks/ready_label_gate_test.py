#!/usr/bin/env python3
"""Checks ready_label_gate.py: when a stop that reports a pull request ready is blocked.

usage: python3 ready_label_gate_test.py

`gh` and `git` are stand-ins, so no network or repository is needed.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ready_label_gate as gate  # noqa: E402

URL = 'https://github.com/o/r/pull/7'
READY = f'Pull request #7 is ready for review: {URL}'


def user(text):
    return {'type': 'user', 'message': {'role': 'user', 'content': text}}


def bash(tool_id, command):
    return {'type': 'assistant', 'message': {'role': 'assistant', 'content': [
        {'type': 'tool_use', 'id': tool_id, 'name': 'Bash', 'input': {'command': command}}]}}


def result(tool_id, text):
    return {'type': 'user', 'message': {'role': 'user', 'content': [
        {'type': 'tool_result', 'tool_use_id': tool_id, 'content': text}]}}


def say(text):
    return {'type': 'assistant', 'message': {'role': 'assistant', 'content': [
        {'type': 'text', 'text': text}]}}


def opened(url=URL):
    return [user('implement 89'), bash('t1', 'gh pr create --body-file b.md'),
            result('t1', f'Creating pull request\n{url}\n')]


class Memory:
    def __init__(self):
        self.data = {}

    def load(self):
        return dict(self.data)

    def save(self, data):
        self.data = dict(data)


class Runner:
    """Answers `gh` and `git` calls from a table keyed by the words after the tool."""

    def __init__(self, labels=None, branch_prs=None, fail=None):
        self.labels = labels if labels is not None else {}
        self.branch_prs = branch_prs or []
        self.fail = fail
        self.calls = []

    def __call__(self, args, cwd=None):
        self.calls.append(args)
        if self.fail == 'missing':
            raise OSError('gh: not found')
        if args[:3] == ['git', 'rev-parse', '--abbrev-ref']:
            return 0, 'feat/x\n', ''
        if args[:3] == ['gh', 'pr', 'list']:
            return 0, json.dumps(self.branch_prs), ''
        if args[:3] == ['gh', 'pr', 'view']:
            if self.fail == 'exit':
                return 1, '', 'HTTP 502'
            ref = args[3]
            number = int(ref.rsplit('/', 1)[-1].lstrip('#'))
            url = ref if ref.startswith('https://') else f'https://github.com/o/r/pull/{number}'
            names = self.labels.get(number, [])
            return 0, json.dumps({'number': number, 'url': url,
                                  'labels': [{'name': n} for n in names]}), ''
        return 1, '', 'unexpected call'


def decide(entries, reply=READY, runner=None, config=None, state=None, **extra):
    payload = {'hook_event_name': 'Stop', 'session_id': 's1', 'cwd': '/repo',
               'stop_hook_active': False, **extra}
    if reply is not None:
        payload['last_assistant_message'] = reply
    return gate.decide(payload, config if config is not None else {},
                       run=runner or Runner(), entries=entries,
                       state=state if state is not None else Memory())


class Acceptance(unittest.TestCase):
    def test_labeled_pr_passes(self):
        runner = Runner(labels={7: ['Manual Review Needed']})
        self.assertIsNone(decide(opened(), runner=runner))
        self.assertIn(['gh', 'pr', 'view', URL, '--json', 'number,url,labels'], runner.calls)

    def test_unlabeled_pr_blocks(self):
        out = decide(opened(), runner=Runner(labels={7: ['enhancement']}))
        self.assertEqual(out['decision'], 'block')
        reason = out['reason']
        self.assertIn('#7', reason)
        self.assertIn('gh api repos/o/r/issues/7/labels -f "labels[]=Manual Review Needed"', reason)
        self.assertIn("gh pr view 7 --repo o/r --json labels --jq '[.labels[].name]'", reason)

    def test_no_pr_passes(self):
        runner = Runner()
        entries = [user('what is 2+2'), bash('t1', 'ls'), result('t1', 'a\n')]
        self.assertIsNone(decide(entries, runner=runner))
        self.assertEqual(runner.calls, [])

    def test_push_without_open_pr_passes(self):
        entries = [user('push it'), bash('t1', 'git push -u origin HEAD'), result('t1', '')]
        runner = Runner(branch_prs=[])
        self.assertIsNone(decide(entries, runner=runner))
        self.assertIn(['gh', 'pr', 'list', '--head', 'feat/x', '--state', 'open',
                       '--json', 'number,url'], runner.calls)

    def test_push_with_open_pr_checks_it(self):
        entries = [user('fix it'), bash('t1', 'cd /w && git -C /w push'), result('t1', '')]
        runner = Runner(branch_prs=[{'number': 7, 'url': URL}])
        self.assertEqual(decide(entries, runner=runner)['decision'], 'block')

    def test_gh_failure_fails_open(self):
        for mode in ('exit', 'missing'):
            with self.subTest(mode=mode):
                out = decide(opened(), runner=Runner(fail=mode))
                self.assertNotIn('decision', out)
                self.assertIn('#7', out['systemMessage'])
                self.assertIn('not checked', out['systemMessage'])


class Ready(unittest.TestCase):
    def test_no_ready_report_skips_gh(self):
        runner = Runner()
        self.assertIsNone(decide(opened(), reply='Opened #7; CI is still running.', runner=runner))
        self.assertEqual(runner.calls, [])

    def test_negated_ready_does_not_count(self):
        for text in ('#7 is not ready for review yet.', "It isn't ready for review.",
                     'It is not quite yet ready for review.',
                     'Once CI passes I will mark it ready for review.',
                     "It'll be ready for review after CI."):
            with self.subTest(text=text):
                self.assertFalse(gate.is_ready(text, gate.DEFAULT_READY))

    def test_ready_phrases(self):
        for text in ('PR #7 is ready for review.', 'Marked it ready.', 'Ready for manual review: #7',
                     'After fixes it is ready for review.', "I'll say PR is ready for review.",
                     'Once more, it is ready for review.',
                     'The pull request is review-ready.'):
            with self.subTest(text=text):
                self.assertTrue(gate.is_ready(text, gate.DEFAULT_READY))

    def test_custom_pattern_and_malformed_pattern(self):
        runner = Runner(labels={7: []})
        out = decide(opened(), reply='Handing #7 over.', runner=runner,
                     config={'readyPattern': 'handing .* over'})
        self.assertEqual(out['decision'], 'block')
        out = decide(opened(), reply=READY, runner=Runner(labels={7: []}),
                     config={'readyPattern': '('})
        self.assertEqual(out['decision'], 'block')
        self.assertIn('readyPattern', out['systemMessage'])

    def test_reply_from_transcript_when_payload_has_none(self):
        entries = opened() + [say(READY)]
        out = decide(entries, reply=None, runner=Runner(labels={7: []}))
        self.assertEqual(out['decision'], 'block')

    def test_no_reply_at_all_passes(self):
        self.assertIsNone(decide([], reply=None))


class Turn(unittest.TestCase):
    def test_only_this_turn_counts(self):
        entries = opened() + [say('done'), user('thanks, anything else?')]
        runner = Runner()
        self.assertIsNone(decide(entries, runner=runner))
        self.assertEqual(runner.calls, [])

    def test_a_tool_result_is_not_a_new_turn(self):
        entries = opened() + [bash('t2', 'gh pr checks 7'), result('t2', 'pass')]
        self.assertEqual(decide(entries, runner=Runner(labels={7: []}))['decision'], 'block')

    def test_a_mention_is_not_a_create(self):
        entries = [user('look'), bash('t1', 'grep -rn "gh pr create" .'),
                   result('t1', f'notes.md:{URL}\n{URL}\n')]
        runner = Runner()
        self.assertIsNone(decide(entries, runner=runner))
        self.assertEqual(runner.calls, [])

    def test_gh_pr_ready_names_the_pr(self):
        entries = [user('go'), bash('t1', 'gh pr ready 12'), result('t1', '')]
        runner = Runner(labels={12: []})
        out = decide(entries, reply='#12 is ready for review.', runner=runner)
        self.assertIn('#12', out['reason'])

    def test_reply_narrows_several_prs(self):
        other = 'https://github.com/o/r/pull/8'
        entries = [user('go'), bash('t1', 'gh pr create -F a.md'), result('t1', URL + '\n'),
                   bash('t2', 'gh pr create -F b.md'), result('t2', other + '\n')]
        runner = Runner(labels={7: [], 8: []})
        out = decide(entries, reply='#8 is ready for review.', runner=runner)
        self.assertIn('#8', out['reason'])
        self.assertNotIn('#7', out['reason'])

    def test_notifications_and_peer_messages_are_not_a_new_turn(self):
        note = {'type': 'user', 'origin': {'kind': 'task-notification'},
                'message': {'role': 'user', 'content': '<task-notification>done</task-notification>'}}
        peer = {'type': 'user', 'origin': {'kind': 'peer'},
                'message': {'role': 'user', 'content': 'Another session sent a message'}}
        old = {'type': 'user', 'message': {'role': 'user', 'content': '<task-notification>x'}}
        for entry in (note, peer, old):
            with self.subTest(entry=entry):
                out = decide(opened() + [entry], runner=Runner(labels={7: []}))
                self.assertEqual(out['decision'], 'block')

    def test_a_typed_prompt_with_an_origin_is_a_new_turn(self):
        typed = {'type': 'user', 'origin': {'kind': 'human'},
                 'message': {'role': 'user', 'content': 'thanks'}}
        runner = Runner()
        self.assertIsNone(decide(opened() + [typed], runner=runner))
        self.assertEqual(runner.calls, [])

    def test_a_heredoc_does_not_hide_the_command(self):
        for command in ("gh pr create --title t --body-file - <<'EOF'\nIt's done\nEOF",
                        "git commit -F - <<'EOF'\ndon't\nEOF\ngit push"):
            with self.subTest(command=command):
                entries = [user('go'), bash('t1', command), result('t1', URL + '\n')]
                runner = Runner(labels={7: []}, branch_prs=[{'number': 7, 'url': URL}])
                self.assertEqual(decide(entries, runner=runner)['decision'], 'block')

    def test_gh_global_repo_flag(self):
        entries = [user('go'), bash('t1', 'gh -R o/r pr create --fill'), result('t1', URL + '\n')]
        self.assertEqual(decide(entries, runner=Runner(labels={7: []}))['decision'], 'block')

    def test_gh_pr_ready_with_repo_flag(self):
        entries = [user('go'), bash('t1', 'gh pr ready --repo o/r 12'), result('t1', '')]
        runner = Runner(labels={12: []})
        out = decide(entries, reply='#12 is ready for review.', runner=runner)
        self.assertIn('#12', out['reason'])
        self.assertIn(['gh', 'pr', 'view', 'https://github.com/o/r/pull/12', '--json',
                       'number,url,labels'], runner.calls)

    def test_gh_pr_ready_with_repo_and_no_number_looks_up_that_repo(self):
        entries = [user('go'), bash('t1', 'gh pr ready -R o/r'), result('t1', '')]
        runner = Runner(branch_prs=[])
        decide(entries, runner=runner)
        self.assertIn(['gh', 'pr', 'list', '--head', 'feat/x', '--state', 'open',
                       '--json', 'number,url', '--repo', 'o/r'], runner.calls)

    def test_push_from_another_folder_looks_up_that_folder(self):
        for command, folder in (('git -C /w push', '/w'), ('cd /w && git push', '/w'),
                                ('git -C sub push', '/repo/sub'),
                                ('cd /a; cd b; git push', '/a/b'),
                                ('cd /a && git -C b push', '/a/b'),
                                ('git push', '/repo'),
                                ('cd -P /a && git push', '/a'),
                                ('cd "$HOME/w" && git push', os.path.expanduser('~/w')),
                                ('cd "$NO_SUCH_VAR_89" && git push', None)):
            with self.subTest(command=command):
                runner = Runner(branch_prs=[])
                seen = []
                def spy(args, cwd=None):
                    seen.append(cwd)
                    return runner(args, cwd)
                entries = [user('go'), bash('t1', command), result('t1', '')]
                decide(entries, runner=spy)
                self.assertEqual(seen[0], folder)

    def test_meta_user_entry_is_not_a_new_turn(self):
        meta = {'type': 'user', 'isMeta': True, 'message': {'role': 'user', 'content': 'caveat'}}
        entries = opened() + [meta]
        self.assertEqual(decide(entries, runner=Runner(labels={7: []}))['decision'], 'block')


class Skips(unittest.TestCase):
    def test_subagent_stop_skipped(self):
        runner = Runner(labels={7: []})
        self.assertIsNone(decide(opened(), runner=runner, agent_id='a1'))
        self.assertEqual(runner.calls, [])

    def test_other_events_skipped(self):
        out = gate.decide({'hook_event_name': 'SessionStart'}, {}, run=Runner(),
                          entries=opened(), state=Memory())
        self.assertIsNone(out)

    def test_stop_hook_active_still_checked(self):
        out = decide(opened(), runner=Runner(labels={7: []}), stop_hook_active=True)
        self.assertEqual(out['decision'], 'block')

    def test_block_cap_downgrades_to_message(self):
        state = Memory()
        for _ in range(2):
            self.assertEqual(decide(opened(), runner=Runner(labels={7: []}), state=state)['decision'],
                             'block')
        out = decide(opened(), runner=Runner(labels={7: []}), state=state)
        self.assertNotIn('decision', out)
        self.assertIn('Manual Review Needed', out['systemMessage'])

    def test_custom_label_and_cap(self):
        state = Memory()
        config = {'label': 'Ready', 'maxBlocks': 1}
        out = decide(opened(), runner=Runner(labels={7: ['Manual Review Needed']}),
                     config=config, state=state)
        self.assertIn('labels[]=Ready', out['reason'])
        out = decide(opened(), runner=Runner(labels={7: []}), config=config, state=state)
        self.assertNotIn('decision', out)


class Process(unittest.TestCase):
    SCRIPT = os.path.join(HERE, 'ready_label_gate.py')

    def test_main_requires_config(self):
        done = subprocess.run([sys.executable, self.SCRIPT], input='{}', capture_output=True,
                              text=True)
        self.assertEqual(done.returncode, 64)

    def test_main_passes_a_turn_with_no_pr(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = os.path.join(tmp, 'extension.json')
            with open(config, 'w', encoding='utf-8') as f:
                json.dump({'readyLabelGate': {}}, f)
            transcript = os.path.join(tmp, 't.jsonl')
            with open(transcript, 'w', encoding='utf-8') as f:
                for entry in (user('hi'), say(READY)):
                    f.write(json.dumps(entry) + '\n')
            payload = {'hook_event_name': 'Stop', 'session_id': 's1', 'cwd': tmp,
                       'transcript_path': transcript}
            done = subprocess.run([sys.executable, self.SCRIPT, '--config', config],
                                  input=json.dumps(payload), capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stdout, '')


if __name__ == '__main__':
    unittest.main()
