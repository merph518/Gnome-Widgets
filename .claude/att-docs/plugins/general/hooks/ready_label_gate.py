#!/usr/bin/env python3
"""Stop hook that blocks a ready report on a pull request missing its review label.

usage: python3 ready_label_gate.py --config <extension.json> < hook-input.json

On Stop, when the session's final reply says a pull request is ready for review and this
turn opened or pushed to one, the hook reads that pull request's labels. Without the
review label it blocks the stop, naming the pull request and the commands that add the
label and read it back. With the label, or with no pull request, it does nothing.

The settings are the `readyLabelGate` section of the extension file:

  label         the label a ready pull request carries; defaults to Manual Review Needed
  readyPattern  a regular expression, matched without case, that marks the final reply
                as a ready report; defaults to DEFAULT_READY below
  maxBlocks     how many times one pull request may block a stop in one session before
                the hook only reports it; defaults to 2, so a stop never loops forever

The turn is everything after the last prompt the person typed. It opened or pushed to a
pull request when one of its Bash commands is `gh pr create` (the URL it printed on a line
of its own), `gh pr ready [<n>]`, or `git push`. A push, or `gh pr ready` alone, is looked
up with `gh pr list --head <branch>` for the branch checked out where the push ran: the
session's folder, moved by an earlier `cd` in the same command and by `git -C <dir>`. When
the reply names some of the pull requests by number, only those are checked.

A `gh` call that fails lets the stop through with a note saying the label was not checked.
A subagent's stop is not checked.
"""
import json
import os
import re
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pr_testing_gate import command_words, expand, segments  # noqa: E402

EXIT_USAGE = 64
TIMEOUT = 10
DEFAULT_LABEL = 'Manual Review Needed'
DEFAULT_READY = r'\b(ready for (manual )?review|marked (it )?ready|review-ready)\b'
DEFAULT_MAX_BLOCKS = 2
# Words just before a ready phrase that turn it into its opposite or into a plan: "not
# quite yet ready", "will mark it ready", "it'll be ready".
NEGATION = re.compile(r"(\bnot|n't|\bnever|\bwill|'ll)\s+(\w+\s+){0,2}$", re.I)
# gh options that take a value, so the value is not read as a subcommand or a number.
GH_VALUE_FLAGS = ('-R', '--repo', '--hostname')
PR_URL = re.compile(r'^\s*(https://github\.com/([^/\s]+/[^/\s]+)/pull/(\d+))\s*$', re.M)
ANY_PR_URL = re.compile(r'https://github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)')
MENTION = re.compile(r'(?:#|/pull/)(\d+)\b')
SESSION = re.compile(r'^[A-Za-z0-9_-]+$')


def run_command(args, cwd=None):
    """Runs a command. Returns (exit code, stdout, stderr); raises OSError if it cannot start."""
    try:
        done = subprocess.run(args, cwd=cwd or None, capture_output=True, text=True,
                              timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return 124, '', f'timed out after {TIMEOUT}s'
    return done.returncode, done.stdout, done.stderr


def load_entries(path):
    """The transcript's entries, or [] when it cannot be read. Bad lines are skipped."""
    entries = []
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if isinstance(entry, dict):
                    entries.append(entry)
    except (OSError, TypeError):
        pass
    return entries


def content_blocks(entry):
    content = (entry.get('message') or {}).get('content')
    if isinstance(content, str):
        return [{'type': 'text', 'text': content}]
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def is_prompt(entry):
    """True for a user entry the person typed, as opposed to a tool result, a background
    task's notification, a message from another session, or a note."""
    if entry.get('type') != 'user' or entry.get('isMeta') or entry.get('isCompactSummary'):
        return False
    origin = entry.get('origin')
    if isinstance(origin, dict) and origin.get('kind') not in (None, 'human'):
        return False
    content = (entry.get('message') or {}).get('content')
    if isinstance(content, str) and content.lstrip().startswith('<task-notification>'):
        return False
    return not any(b.get('type') == 'tool_result' for b in content_blocks(entry))


def this_turn(entries):
    """The entries after the last prompt the person typed."""
    for i in range(len(entries) - 1, -1, -1):
        if is_prompt(entries[i]):
            return entries[i + 1:]
    return entries


def final_reply(payload, entries):
    text = payload.get('last_assistant_message')
    if isinstance(text, str) and text.strip():
        return text
    for entry in reversed(this_turn(entries)):
        if entry.get('type') == 'assistant':
            texts = [b.get('text', '') for b in content_blocks(entry) if b.get('type') == 'text']
            if any(t.strip() for t in texts):
                return '\n'.join(texts)
    return ''


def is_ready(text, pattern):
    """True when the pattern (a string or a compiled expression) matches without a
    negation just before it."""
    if isinstance(pattern, str):
        pattern = re.compile(pattern, re.I)
    for match in pattern.finditer(text):
        if not NEGATION.search(text[max(0, match.start() - 40):match.start()]):
            return True
    return False


def result_text(block):
    content = block.get('content')
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return '\n'.join(c.get('text', '') for c in content
                         if isinstance(c, dict) and c.get('type') == 'text')
    return ''


def turn_commands(entries):
    """[(command, output)] for each Bash call this turn, in order."""
    calls, outputs = [], {}
    for entry in this_turn(entries):
        for b in content_blocks(entry):
            if b.get('type') == 'tool_use' and b.get('name') == 'Bash':
                command = (b.get('input') or {}).get('command')
                if isinstance(command, str):
                    calls.append((b.get('id'), command))
            elif b.get('type') == 'tool_result':
                outputs[b.get('tool_use_id')] = result_text(b)
    return [(command, outputs.get(tool_id, '')) for tool_id, command in calls]


def in_folder(folder, target):
    """Where `cd <target>` or `git -C <target>` lands from folder; None when unknown, as
    for a target naming a variable this process does not have."""
    target = expand(target, {})
    if '$' in target:
        return None
    if os.path.isabs(target):
        return os.path.normpath(target)
    return os.path.normpath(os.path.join(folder, target)) if folder else None


def simple_commands(command, base):
    """(words, folder) for each simple command, where folder is the folder it runs in:
    base, moved by any earlier `cd` in the command, or None when that is unknown. A
    command shlex cannot read whole, such as a heredoc with an apostrophe in its body, is
    read line by line, skipping the lines it cannot read."""
    try:
        segs = list(segments(command))
    except ValueError:
        segs = []
        for line in command.split('\n'):
            try:
                segs.extend(segments(line))
            except ValueError:
                continue
    folder = base
    for seg, _ in segs:
        words = command_words(seg, {})
        if words[:1] == ['cd']:
            args = [w for w in words[1:] if w == '-' or not w.startswith('-')]
            folder = in_folder(folder, args[0] if args else '~') if len(args) <= 1 else None
            if args == ['-']:
                folder = None
        elif words:
            yield words, folder


def gh_words(words):
    """(positional words after `gh`, the --repo value or None), with options dropped."""
    positional, repo, i = [], None, 1
    while i < len(words):
        word = words[i]
        if word in GH_VALUE_FLAGS:
            if word in ('-R', '--repo') and i + 1 < len(words):
                repo = words[i + 1]
            i += 2
            continue
        if word.startswith('--repo='):
            repo = word[len('--repo='):]
        elif not word.startswith('-'):
            positional.append(word)
        i += 1
    return positional, repo


def git_push_folder(words, folder):
    """For a `git push`, the folder it ran in (folder, moved by any `-C`); False for any
    other git command."""
    i = 1
    while i < len(words) and words[i].startswith('-'):
        if words[i] == '-C' and i + 1 < len(words):
            folder = in_folder(folder, words[i + 1])
        i += 2 if words[i] in ('-C', '-c') else 1
    return folder if i < len(words) and words[i] == 'push' else False


def touched_prs(commands, base=None):
    """(refs, lookups): pull request refs this turn named, and (folder, repo) pairs whose
    current branch's pull request has to be looked up (a push, or `gh pr ready` with no
    number). base is the session's folder; repo is a `gh -R` value or None."""
    refs, folders = [], []
    for command, output in commands:
        for words, folder in simple_commands(command, base):
            if words[0] == 'gh':
                positional, repo = gh_words(words)
                if positional[:2] == ['pr', 'create']:
                    refs.extend(m.group(1) for m in PR_URL.finditer(output))
                elif positional[:2] == ['pr', 'ready']:
                    if len(positional) < 3:
                        folders.append((folder, repo))
                    elif repo and positional[2].isdigit():
                        refs.append(f'https://github.com/{repo}/pull/{positional[2]}')
                    else:
                        refs.append(positional[2])
            elif words[0] == 'git':
                pushed = git_push_folder(words, folder)
                if pushed is not False:
                    folders.append((pushed, None))
    return refs, list(dict.fromkeys(folders))


def number_of(ref):
    match = re.search(r'(\d+)$', ref)
    return int(match.group(1)) if match else None


def branch_prs(run, cwd, repo=None):
    """URLs of the open pull requests on the branch checked out in cwd, in repo when given.
    Raises LookupError on failure."""
    code, out, err = run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], cwd)
    branch = out.strip()
    if code != 0 or not branch or branch == 'HEAD':
        raise LookupError(err.strip() or 'no current branch')
    code, out, err = run(['gh', 'pr', 'list', '--head', branch, '--state', 'open',
                          '--json', 'number,url'] + (['--repo', repo] if repo else []), cwd)
    if code != 0:
        raise LookupError(err.strip() or f'gh exited {code}')
    try:
        return [pr['url'] for pr in json.loads(out) if isinstance(pr, dict) and pr.get('url')]
    except (ValueError, TypeError) as err:
        raise LookupError(f'unreadable gh output: {err}') from err


def read_pr(run, cwd, ref):
    """(url, number, repo, labels) of one pull request. Raises LookupError on failure."""
    code, out, err = run(['gh', 'pr', 'view', ref, '--json', 'number,url,labels'], cwd)
    if code != 0:
        raise LookupError(err.strip() or f'gh exited {code}')
    try:
        data = json.loads(out)
        url = data['url']
        labels = [label['name'] for label in data.get('labels') or []]
        match = ANY_PR_URL.search(url)
        return url, int(data['number']), match.group(1) if match else None, labels
    except (ValueError, TypeError, KeyError) as err:
        raise LookupError(f'unreadable gh output: {err}') from err


def label_commands(number, repo, label):
    path = f'repos/{repo or "{owner}/{repo}"}/issues/{number}/labels'
    repo_flag = f' --repo {repo}' if repo else ''
    return (f'  gh api {path} -f "labels[]={label}"\n'
            f"  gh pr view {number}{repo_flag} --json labels --jq '[.labels[].name]'")


class FileState:
    """Block counts per pull request for one session, kept in the temp folder."""

    def __init__(self, session):
        self.path = None
        if isinstance(session, str) and SESSION.match(session):
            self.path = os.path.join(tempfile.gettempdir(), 'ready-label-gate', session + '.json')

    def load(self):
        try:
            with open(self.path, encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, TypeError, ValueError):
            return {}

    def save(self, data):
        if self.path is None:
            return
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump(data, f)
        except OSError:
            pass


def settings(config):
    """(label, compiled pattern, max blocks, notes) from the section, with defaults."""
    notes = []
    label = config.get('label')
    label = label if isinstance(label, str) and label else DEFAULT_LABEL
    pattern = config.get('readyPattern', DEFAULT_READY)
    try:
        compiled = re.compile(pattern if isinstance(pattern, str) else DEFAULT_READY, re.I)
    except re.error as err:
        notes.append(f'ready_label_gate: readyPattern is not a valid expression ({err}); '
                     'using the default.')
        compiled = re.compile(DEFAULT_READY, re.I)
    cap = config.get('maxBlocks')
    cap = cap if isinstance(cap, int) and not isinstance(cap, bool) and cap >= 0 \
        else DEFAULT_MAX_BLOCKS
    return label, compiled, cap, notes


def decide(payload, config, run=run_command, entries=None, state=None):
    """The hook's output for one Stop payload, or None to let the stop through."""
    if payload.get('hook_event_name') != 'Stop' or payload.get('agent_id'):
        return None
    session = payload.get('session_id')
    if state is None:
        state = FileState(session)
        # With no session to count blocks against, a stop already continued by a hook
        # goes through, so the block cannot repeat.
        if state.path is None and payload.get('stop_hook_active'):
            return None
    if entries is None:
        entries = load_entries(payload.get('transcript_path'))
    label, pattern, cap, notes = settings(config)
    reply = final_reply(payload, entries)
    if not reply or not is_ready(reply, pattern):
        return None
    cwd = payload.get('cwd')
    refs, lookups = touched_prs(turn_commands(entries), cwd)
    for folder, repo in lookups:
        try:
            refs.extend(branch_prs(run, folder, repo))
        except (LookupError, OSError) as err:
            notes.append(f'ready_label_gate: could not find the pull request for the '
                         f'branch in {folder or "this folder"} ({err}); its label was not '
                         'checked.')
    refs = list(dict.fromkeys(refs))
    named = {int(n) for n in MENTION.findall(reply)}
    if named & {number_of(r) for r in refs}:
        refs = [r for r in refs if number_of(r) in named]
    missing = []
    viewed = set()
    for ref in refs:
        try:
            url, number, repo, labels = read_pr(run, cwd, ref)
        except (LookupError, OSError) as err:
            shown = f'#{number_of(ref)}' if number_of(ref) is not None else ref
            notes.append(f'ready_label_gate: could not read the labels of pull request '
                         f'{shown} ({err}); not checked.')
            continue
        if url in viewed:
            continue
        viewed.add(url)
        if label not in labels:
            missing.append((url, number, repo))
    counts = state.load() if missing else {}
    to_block = []
    for url, number, repo in missing:
        if counts.get(url, 0) >= cap:
            notes.append(f'ready_label_gate: pull request #{number} is reported ready '
                         f'without the {label} label; not blocking again this session.')
        else:
            counts[url] = counts.get(url, 0) + 1
            to_block.append((number, repo))
    if missing:
        state.save(counts)
    out = {}
    if to_block:
        lines = [f'The final reply reports a pull request ready for review, but it does not '
                 f'carry the {label} label, so it is not ready yet.']
        for number, repo in to_block:
            lines.append(f'Pull request #{number}{f" in {repo}" if repo else ""}: add the label '
                         f'and read it back with\n{label_commands(number, repo, label)}')
        lines.append('Add it once every check on the pull request has passed, or do not '
                     'report it ready.')
        out = {'decision': 'block', 'reason': '\n'.join(lines)}
    if notes:
        out['systemMessage'] = '\n'.join(notes)
    return out or None


def read_config(argv):
    """The readyLabelGate section of the file named by `--config <file>`, or exit 64."""
    if len(argv) < 3 or argv[1] != '--config':
        print('ready_label_gate.py: --config <extension.json> is required', file=sys.stderr)
        sys.exit(EXIT_USAGE)
    try:
        with open(argv[2], encoding='utf-8') as f:
            section = json.load(f).get('readyLabelGate')
    except (OSError, ValueError, AttributeError) as err:
        print(f'ready_label_gate.py: cannot read {argv[2]}: {err}', file=sys.stderr)
        sys.exit(EXIT_USAGE)
    return section if isinstance(section, dict) else {}


def main(argv):
    config = read_config(argv)
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    result = decide(payload, config) if isinstance(payload, dict) else None
    if result:
        print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
