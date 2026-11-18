#!/usr/bin/env python3
"""Tally every run, pull request and issue a session is waiting on, with as few API calls
as possible.

A session records each run it waits on in a ledger, one line per run, and reads them all
back through this script instead of watching each one.

usage:
  scripts/catchup.py add   <ledger> <run-id> <label>   record a workflow run
  scripts/catchup.py check <ledger>                    tally what has finished, once
  scripts/catchup.py wait  <ledger> [--interval 180] [--all]
                                                       check until a row finishes
                                                       (--all: until every row has)
  scripts/catchup.py add-pr <ledger> <pr> [label]      wait for a pull request to merge
  scripts/catchup.py add-checks <ledger> <pr> [label]  wait for its CI run
  scripts/catchup.py add-issue <ledger> <issue> [label]
                                                       wait for a blocking issue to close

`add-pr` reads a pull request row once, to record it and to settle it at once if
it has already merged or closed. After that, the forwarder's pull_request close
notice settles it, with no API call. When a forwarder connects, every waiter
reads each open pull request once, for a close sent while nobody was listening,
and a read that fails there is tried once more thirty seconds later. Every timer
check also reads each open pull request, push or no push: a merge during an
outage is caught within one timer interval, and a merge conflict sends no
notice at all, since it comes from the base branch moving rather than from the
pull request.

Each read takes the pull request's mergeable state. A read that finds it
CONFLICTING marks the row and prints `pr: <number> conflicting`, and `wait`
then hands back, so the session merges the base branch, resolves the conflicts
and pushes. The mark keeps the same conflict from being reported twice, and a
read that finds the pull request MERGEABLE again clears it.

`add-checks` records the CI run (.github/workflows/ci.yml) on a pull request's head
commit as an ordinary run row titled `CI on pull request <n>`, and drops the row an
earlier push left under that title on the same branch, done or not, since the push
cancels that run. The head commit is read from the branch's ref, since the pull
request's own record lags a push by a few seconds; a fork's pull request uses the
record's. The commit's runs are read again for up to two minutes until the run
appears. It exits 3 when none does, naming a conflict with the base when the pull
request has one, since no run starts then; otherwise the run is slow to queue or the
push did not reach GitHub. Given a completed run whose done row tallied the same
attempt, it prints that row's tally and saved log rather than reopening it. A rerun
keeps the run id, so its tally ends in `(attempt <n>)`, and `wait` tells a done row
apart by run and tally. The row links the run rather than its job, so its log is
every job's.

A run is tallied from the summary scripts/test-all.sh prints: its `Tests: <n> passed,
<m> failed` line and its `Static checks: passed|failed` line, as
`<conclusion> test-all: <n> passed, <m> failed; static checks <result>`. Below the
tally come each `FAIL  <file> (exit N)` line with the `not ok` and `FAIL` lines of that
file's output, and each `ERROR` line the static checks printed. A log with no `Tests:`
line, such as a run that failed before the tests started, is tallied as
`<conclusion> <workflow>` followed by each error line and the step output above it.

An issue row is the issue a blocked session waits on, the one that holds the work
it deferred. `add-issue` reads it once, and settles it at once if it is already
closed. After that, the forwarder's issues close notice settles it, and the rows
are read wherever pull request rows are read. Every timer check also reads each
open issue, push or no push: the waiter holding the forwarder may be an older copy
of this script that does not forward issues events, and a blocked session can
wait for days, so a fifteen minute read is the backstop.

`check` costs one run list per branch in the ledger, plus one log fetch per run
that finished since the last check. Runs already tallied cost nothing. A finished
run whose log comes back empty or cannot be read is fetched again on the next
check, unless it was cancelled or skipped: such a run may have ended before its
job started and written nothing, so its row is marked done with that conclusion. `wait` is
the single watcher a session may run, and it never checks more often than every
three minutes on a timer. It exits as soon as any row finishes, so the session
can act on that result while the rest are still out, and the session then runs
it again on the rows still open. `--all` waits for every row instead. Its flags
may come before or after the ledger. `wait` and `check` exit 2 when no ledger
exists at the path given, since only the `add` commands create one, and an
empty ledger would read as nothing left to wait on. `add` and `check` take a
lock beside the ledger to rewrite it, so a run recorded while `wait` is checking
keeps its row. `add` tries a read that fails with a 404, a server error or no
answer up to three times inside two minutes, since a run is
read the moment it starts. A run it still cannot read is reported on one
line with a nonzero exit, and adding it again later replaces its row rather
than duplicating it.

Pull request and issue rows never count as runs.

`wait` also listens for GitHub's workflow_run event through `gh webhook forward`
(the cli/gh-webhook extension), so a run is tallied within seconds of finishing.
A waiter on a machine without the extension says so, names the command that
installs it, and checks on its timer; it never installs the extension itself.
GitHub accepts one forwarder hook per repository, so the waiters on a machine
share one. The waiter holding a lock under ~/.cache/catchup runs the forwarder,
reads its output on a thread, and writes each event to a shared events file as
one short line. Every waiter reads that file. A run that the events say
finished is read by id before its log is fetched, so a burst of finished runs
costs one run read and one log fetch per run, however long the branch's run
history is. Past a megabyte the events file is renamed to events.jsonl.old, and
readers follow the rename.

gh runs the extension as a child process, and a child that outlives its waiter
keeps the hook and blocks the next forwarder. The lock proves no live waiter
owns such a process, so the holder stops any it finds before starting a
forwarder. It also deletes the last hook a forwarder on this machine made, if
GitHub has not dropped it already. A forwarder hook GitHub has marked inactive
has no forwarder behind it, wherever it was made, so the holder deletes it
before starting. An active hook made on another machine is left alone: the
forwarder here is refused, retries after a delay that doubles up to
ten minutes, and `wait` checks on the timer meanwhile. Every five minutes the
holder confirms its hook is still on the repository and restarts the forwarder
when it is gone.

A gh call that fails on the wait path never ends `wait`. A run read, a run list
or a log fetch that fails leaves its rows as they were, and the next check tries
again. When the waiter cannot reach GitHub to name the repository, push is off
and `wait` checks on the timer, setting push up again after each check. A pull
request row keeps such a waiter going, since push can still come up for it.

While the push is live the timer check runs every fifteen minutes and only
catches a lost event. When the extension is not installed, or while the
forwarder is down, `wait` checks every three minutes. When a forwarder connects, every waiter runs
one full check once the three minute floor allows, which covers runs that
finished while no forwarder was listening.

The repository is the one the current directory's checkout belongs to: gh reads it
from there, and the forwarder is started for the repository gh names.

The ledger is tab separated: label, branch, run id, job url, state, tally, title. A
pull request row holds pr:<number> as its run id and the pull request's url as its
job url, and an issue row holds issue:<number> and the issue's url, with no branch.
The title is the run's display title, or the title add-checks gives its row. The log
of each finished run is saved beside the ledger as <ledger>.logs/<run-id>.log so it
can be grepped again without another fetch, and the lines printed below its tally as
<ledger>.logs/<run-id>.errors.
"""
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from urllib.parse import quote

MIN_INTERVAL = 180
PUSH_FALLBACK_INTERVAL = 900
# How often a waiter reads the local events file; no API call is made.
EVENT_POLL = 5
# A notified run the API does not report completed yet is read again this often,
# this many times in all, and then left to the timer.
EVENT_RECHECK = 30
EVENT_RECHECKS = 4
# An events line is about 250 bytes, so the file holds about 4,000 events.
EVENTS_ROTATE = 1_000_000
# Runs a waiter remembers from the events files, about what the two files hold.
SEEN_LIMIT = 10_000
RANK = {'requested': 0, 'in_progress': 1, 'completed': 2}
FORWARDER_RESTART = 60
FORWARDER_RESTART_MAX = 600
HOOK_CHECK = 300
EXTENSION = 'cli/gh-webhook'
INSTALL_TIMEOUT = 120
PUSH_DIR = os.path.expanduser('~/.cache/catchup')
# Color codes arrive either as escape bytes or as their printed ^[[ form.
ANSI = re.compile(r'(?:\x1b|\^\[)\[[0-9;]*m')
FIELDS = ('label', 'branch', 'run', 'job', 'state', 'tally', 'title')
# The event behind a pull request's own check runs, and the workflow add-checks records.
# Its row links the run, so its log is every job's.
PR_EVENT = 'pull_request'
CI_WORKFLOW = '.github/workflows/ci.yml'
# The row title names the check by this, the workflow's name.
CI_NAME = 'CI'
CHECKS_ERROR = '##[error]'
# The most lines a finished run prints below its tally.
CHECKS_ERROR_LINES = 40
# add-checks exits with this when no CI run turns up on the head commit.
NO_CHECK_RUNS = 3
# What scripts/test-all.sh prints: a line per test file, the tests' summary, the static
# checks' result, and each problem the static checks found. A failing file's output
# follows its FAIL line, every line indented by six spaces.
TEST_FILE = re.compile(r'^(PASS|FAIL|SKIP)  (.*?)(?: \(exit (\d+)\))?$')
TESTS_LINE = re.compile(r'^Tests: (\d+) passed, (\d+) failed$')
STATIC_LINE = re.compile(r'^Static checks: (passed|failed)$')
STATIC_START = '== Static checks'
STATIC_ERROR = 'ERROR  '
FILE_OUTPUT = ' ' * 6
# In a failing file's output, the lines that name a failure: node --test prints `not ok`,
# and python's unittest prints `FAIL:`.
FAIL_DETAIL = re.compile(r'^(not ok|FAIL)\b')
# A pull request row's key in the run column, and in the events file.
PR_PREFIX = 'pr:'
# What a pull request row's title holds while the pull request conflicts with its base.
CONFLICT_MARK = 'conflicting since '
# An issue row's key, for the issue a blocked session waits on.
ISSUE_PREFIX = 'issue:'
FORWARDED_EVENTS = 'workflow_run,pull_request,issues'
# add reads a run the moment it starts, when the API can still answer 404 for it,
# or answer nothing at all. Each read is tried this many times, pausing this many seconds
# times the try number, and add gives up once this many seconds have passed since it began.
ADD_READ_TRIES = 3
ADD_READ_BACKOFF = 5
ADD_READ_TIMEOUT = 30
ADD_BUDGET = 120
ADD_JOBS_PAUSE = 10
# gh's wording for a failure worth another try: not found yet, a server error, or no answer.
TRANSIENT = re.compile(r'HTTP (404|5\d\d)|no answer in|error connecting|connection reset'
                       r'|i/o timeout|TLS handshake timeout|unexpected EOF', re.I)
# Conclusions a run can reach before its job writes a log, as when it is cancelled
# while still queued. A run with one of these and no log is settled rather than read again.
NO_LOG_CONCLUSIONS = ('cancelled', 'skipped')
# The job id at the end of a job link: .../actions/runs/<run>/job/<job>.
JOB_ID = re.compile(r'/job/(\d+)')


def gh(*args, timeout=None):
    try:
        r = subprocess.run(['gh', *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f'no answer in {timeout}s') from None
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:300])
    return r.stdout


def job_log(job_id):
    """One job's log from the jobs API. A gh that refuses a response carrying terminal
    escape sequences, which a log with color codes does, is told to print it anyway; a
    gh too old to know the flag does not refuse, so it reads the log without it."""
    path = f'repos/{{owner}}/{{repo}}/actions/jobs/{job_id}/logs'
    try:
        return gh('api', '--allow-escape-sequences', path)
    except RuntimeError as e:
        if 'unknown flag' not in str(e):
            raise
    return gh('api', path)


def job_logs(run_id, job_link=''):
    """A run's logs, one per job, read from the jobs API, which answers on every gh
    release. A job link names its job id, so that job is read alone; otherwise every job
    the run lists is read, in order, passing over a job that never started a step, such
    as a skipped one or one no runner took, whose log cannot be read. A job that never
    started a step is read the same way when linked, and one that failed so gives a line
    saying it failed before its first step. A job that succeeded ran its steps, so a
    failed read of its log is raised whatever its step list shows."""
    found = JOB_ID.search(job_link)
    if found:
        jobs = [{'id': found.group(1)}]
    else:
        listed = gh('api', f'repos/{{owner}}/{{repo}}/actions/runs/{run_id}/jobs')
        jobs = json.loads(listed)['jobs']
    logs = []
    for job in jobs:
        try:
            logs.append(job_log(job['id']))
        except RuntimeError:
            if found:
                job = json.loads(gh('api', f'repos/{{owner}}/{{repo}}/actions/jobs/{job["id"]}'))
            steps = job.get('steps')
            if (steps is None or any(step.get('started_at') for step in steps)
                    or job.get('conclusion') == 'success'):
                raise
            # A job that failed before its first step still says why the run is red.
            if job.get('conclusion') == 'failure':
                logs.append(f'{CHECKS_ERROR}{job.get("name", "A job")} failed before its '
                            'first step\n')
    return logs


def read_file(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except FileNotFoundError:
        return ''


def write_file(path, text):
    """Replace a file whole, so a reader never sees it half written."""
    tmp = f'{path}.{os.getpid()}.tmp'
    with open(tmp, 'w') as f:
        f.write(text)
    os.replace(tmp, path)


def locked(path):
    """The ledger's lock, held while a ledger is read and rewritten."""
    lock = open(path + '.lock', 'a')
    fcntl.flock(lock, fcntl.LOCK_EX)
    return lock


def read_ledger(path):
    rows = []
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    parts = line.rstrip('\n').split('\t') + [''] * len(FIELDS)
                    rows.append(dict(zip(FIELDS, parts)))
    return rows


def write_ledger(path, rows):
    write_file(path, ''.join('\t'.join(r[k] for k in FIELDS) + '\n' for r in rows))


def open_runs(path):
    return {r['run'] for r in read_ledger(path) if r['state'] != 'done'}


def done_rows(path):
    """Each done row by run and tally, since a rerun settles the same run with a new tally."""
    return {(r['run'], r['tally']) for r in read_ledger(path) if r['state'] == 'done'}


def handed_back(path, before, every, conflicts=frozenset()):
    """Whether wait stops now: a row finished, or a pull request came to conflict with its
    base, since it started, unless it waits for all."""
    if every:
        return False
    finished = report_finished(path, before)
    return report_conflicts(path, conflicts) or finished


def report_finished(path, before):
    """Print the rows finished since wait started. False if none."""
    finished = done_rows(path) - before
    if not finished:
        return False
    left = len(open_runs(path))
    print(f'wait: {len(finished)} finished; {left} still open'
          + ('; act on the result, then run wait again' if left else ''))
    return True


def is_pr(key):
    return key.startswith(PR_PREFIX)


def is_issue(key):
    return key.startswith(ISSUE_PREFIX)


def is_run(key):
    """Whether a ledger key is a workflow run, rather than a pull request or an issue."""
    return not is_pr(key) and not is_issue(key)


def pr_tally(state, sha, merged_at, closed_at):
    if state == 'merged':
        return f'merged {(sha or "")[:9]} at {merged_at}'
    return f'closed without merging at {closed_at}'


def issue_tally(reason, closed_at):
    """What a closed issue row reads: completed, not planned, or duplicate, and when."""
    reason = (reason or 'closed').lower().replace('_', ' ')
    return f'closed as {reason} at {closed_at}'


def notice_tally(event):
    """The tally for a pull request or issue row, from its close notice."""
    if event.get('event') == 'issue':
        return issue_tally(event.get('reason'), event.get('closed_at'))
    return pr_tally(event['state'], event.get('sha'), event.get('merged_at'),
                    event.get('closed_at'))


def settle_row(path, key, state, tally_text):
    """Mark an open pull request or issue row done. False when no open row has that key."""
    with locked(path):
        rows = read_ledger(path)
        hit = [r for r in rows if r['run'] == key and r['state'] != 'done']
        for r in hit:
            r['state'], r['tally'] = 'done', tally_text
        write_ledger(path, rows)
    kind, number = key.split(':', 1)
    for r in hit:
        print_done(r)
        print(f'{kind}: {number} {state}')
    return bool(hit)


def read_pr(number):
    """One read of a pull request: its url, head branch, mergeable state, and (state, tally)
    once it is shut."""
    pr = json.loads(gh('pr', 'view', str(number), '--json',
                       'url,headRefName,state,mergedAt,closedAt,mergeCommit,mergeable'))
    state = pr['state'].lower()
    shut = None
    if state in ('merged', 'closed'):
        sha = (pr.get('mergeCommit') or {}).get('oid')
        shut = (state, pr_tally(state, sha, pr.get('mergedAt'), pr.get('closedAt')))
    return pr, shut


def note_conflict(path, key, mergeable):
    """Mark an open pull request row that conflicts with its base, once per conflict.

    The mark sits in the row's title, which pull request rows leave empty otherwise. A
    MERGEABLE read clears it, so a later conflict is reported again. UNKNOWN, which GitHub
    answers while it recomputes after the base moved, leaves the row as it was. Returns
    True when this read found a conflict the row was not already marked with.
    """
    with locked(path):
        rows = read_ledger(path)
        hit = [r for r in rows if r['run'] == key and r['state'] != 'done']
        fresh = False
        for r in hit:
            marked = r['title'].startswith(CONFLICT_MARK)
            if mergeable == 'CONFLICTING' and not marked:
                r['title'], fresh = f'{CONFLICT_MARK}{utc()}', True
            elif mergeable == 'MERGEABLE' and marked:
                r['title'] = ''
        write_ledger(path, rows)
    if fresh:
        print(f'conflict: {hit[0]["label"]} - {hit[0]["job"]}\n'
              f'pr: {key.split(":", 1)[1]} conflicting')
    return fresh


def conflicted_rows(path):
    """The open pull request rows marked as conflicting with their base branch, as
    (key, mark) pairs. The mark carries its time, so a conflict that clears and comes back
    differs from the one wait started with."""
    return {(r['run'], r['title']) for r in read_ledger(path)
            if r['state'] != 'done' and is_pr(r['run']) and r['title'].startswith(CONFLICT_MARK)}


def report_conflicts(path, before):
    """Print the pull requests that came to conflict since wait started. False if none."""
    fresh = conflicted_rows(path) - before
    if not fresh:
        return False
    numbers = ', '.join(sorted({key.split(':', 1)[1] for key, _ in fresh}))
    print(f'wait: pull request {numbers} conflicts with its base branch; merge the base '
          'branch, resolve the conflicts, run the tests, push, record the new CI run with '
          'add-checks, then run wait again')
    return True


def add_pr(path, number, label):
    pr, shut = read_pr(number)
    key = f'{PR_PREFIX}{number}'
    with locked(path):
        rows = [r for r in read_ledger(path) if r['run'] != key]
        # An open row keeps the time it was recorded, so an older close notice for the same
        # pull request, from before a reopen, is not taken for this one.
        rows.append({'label': label, 'branch': pr['headRefName'], 'run': key, 'job': pr['url'],
                     'state': 'open', 'tally': f'added {utc()}', 'title': ''})
        write_ledger(path, rows)
    print(f'waiting for merge: {label} - {pr["url"]}')
    if shut:
        settle_row(path, key, *shut)
    else:
        note_conflict(path, key, pr.get('mergeable'))


def read_issue(number):
    """One read of an issue: its url, and (state, tally) once it is closed."""
    issue = json.loads(gh('api', f'repos/{{owner}}/{{repo}}/issues/{number}'))
    issue['url'] = issue['html_url']
    shut = None
    if issue['state'].lower() == 'closed':
        shut = ('closed', issue_tally(issue.get('state_reason'), issue.get('closed_at')))
    return issue, shut


def add_issue(path, number, label):
    issue, shut = read_issue(number)
    key = f'{ISSUE_PREFIX}{number}'
    with locked(path):
        rows = [r for r in read_ledger(path) if r['run'] != key]
        # As with a pull request row, the time it was recorded screens out an older close
        # notice from before a reopen.
        rows.append({'label': label, 'branch': '', 'run': key, 'job': issue['url'],
                     'state': 'open', 'tally': f'added {utc()}', 'title': ''})
        write_ledger(path, rows)
    print(f'waiting for close: {label} - {issue["url"]}')
    if shut:
        settle_row(path, key, *shut)


def reconcile_rows(path, keys=None):
    """Read each open pull request and issue row once, for a notice nobody heard.

    Given keys, reads only those rows. Returns the keys whose read failed.
    """
    failed = set()
    for r in read_ledger(path):
        key = r['run']
        if r['state'] == 'done' or is_run(key):
            continue
        if keys is not None and key not in keys:
            continue
        kind, number = key.split(':', 1)
        try:
            item, shut = read_issue(number) if is_issue(key) else read_pr(number)
        except (RuntimeError, ValueError, KeyError) as e:
            print(f'{r["label"]}: {"issue" if kind == "issue" else "pull request"} '
                  f'read failed: {e}')
            failed.add(key)
            continue
        if shut:
            settle_row(path, key, *shut)
        elif is_pr(key):
            note_conflict(path, key, item.get('mergeable'))
    return failed


def add_read(endpoint, deadline):
    """One API read for add, tried again on a transient failure while the deadline allows."""
    for attempt in range(1, ADD_READ_TRIES + 1):
        try:
            return json.loads(gh('api', endpoint, timeout=ADD_READ_TIMEOUT))
        except RuntimeError as e:
            pause = ADD_READ_BACKOFF * attempt
            if (attempt == ADD_READ_TRIES or not TRANSIENT.search(str(e))
                    or time.monotonic() + pause > deadline):
                raise
            print(f'{endpoint}: read failed, trying again in {pause}s: {e}')
            time.sleep(pause)


def add(path, run_id, label, run=None, title=None):
    """Record a run. Given the run's record, as add-checks has it, the run is not read again.
    Given a title, as add-checks gives one per pull request, the row carries it in place of
    the run's own, and any earlier run row on the same branch with that title is dropped,
    done or not, since a push cancels the run the push before it started."""
    deadline = time.monotonic() + ADD_BUDGET
    run = run or add_read(f'repos/{{owner}}/{{repo}}/actions/runs/{run_id}', deadline)
    jobs = []
    # The job list is empty for a few seconds after a run starts, before the job exists.
    # A pull request check row links the run, so its log is every job's.
    for _ in range(0 if run.get('path') == CI_WORKFLOW else 6):
        jobs = add_read(f'repos/{{owner}}/{{repo}}/actions/runs/{run_id}/jobs',
                        deadline)['jobs']
        if jobs or time.monotonic() + ADD_JOBS_PAUSE > deadline:
            break
        time.sleep(ADD_JOBS_PAUSE)
    job = jobs[0]['html_url'] if jobs else run['html_url']
    with locked(path):
        rows = [r for r in read_ledger(path) if r['run'] != str(run_id)]
        if title:
            rows = without_check(path, rows, run['head_branch'], title)
        rows.append({'label': label, 'branch': run['head_branch'], 'run': str(run_id),
                     'job': job, 'state': 'waiting', 'tally': '',
                     'title': title or ' '.join(run.get('display_title', '').split())})
        write_ledger(path, rows)
    print(f'waiting: {label} - {job}')


def ci_run(number, sha, branch, deadline):
    """The newest CI run the pull request event started for the pull request on the commit
    from the branch, and the pull request's mergeable state at that commit. The run appears
    a few seconds after the push, so the list is read again until it does, the pull
    request reads as conflicting at that commit twice in a row, since no run starts then,
    or the deadline passes. The mergeable state reads null until it is worked out, and the
    pull request's own head lags a push, so it reads None until the head is the commit.
    The run is None when none turns up."""
    workflow, conflicts = os.path.basename(CI_WORKFLOW), 0
    while True:
        listed = add_read(f'repos/{{owner}}/{{repo}}/actions/workflows/{workflow}/runs'
                          f'?head_sha={sha}&event={PR_EVENT}&per_page=100', deadline)
        # A fork's run lists no pull request, so a run listing none is taken only when no
        # run lists this one.
        runs = [r for r in listed['workflow_runs'] if r['head_branch'] == branch]
        runs = ([r for r in runs if any(p['number'] == int(number)
                                        for p in r.get('pull_requests') or [])]
                or [r for r in runs if not r.get('pull_requests')])
        if runs:
            return max(runs, key=lambda r: r['id']), True
        pr = add_read(f'repos/{{owner}}/{{repo}}/pulls/{number}', deadline)
        mergeable = pr.get('mergeable') if pr['head']['sha'] == sha else None
        # A merge that resolves a conflict can still read False once at the new head, so a
        # conflict counts on the second read in a row.
        conflicts = conflicts + 1 if mergeable is False else 0
        if conflicts == 2 or time.monotonic() + ADD_JOBS_PAUSE > deadline:
            return None, mergeable
        time.sleep(ADD_JOBS_PAUSE)


def saved_log(path, run_id, kind='log'):
    """Where finish saves a run's log, or with kind `errors`, the lines below its tally."""
    return os.path.join(path + '.logs', f'{run_id}.{kind}')


def forget_logs(path, rows):
    """Remove the saved log and error lines of rows leaving the ledger."""
    for r in rows:
        for kind in ('log', 'errors'):
            if os.path.exists(saved_log(path, r['run'], kind)):
                os.remove(saved_log(path, r['run'], kind))


def same_check(row, branch, title):
    """Whether the row is a run row for the check with this title on the branch, which a
    later push's run replaces."""
    return is_run(row['run']) and (row['branch'], row['title']) == (branch, title)


def print_done(row, path=None):
    """A done row's block, naming its saved log when the ledger path is given and the
    log was saved."""
    print(f'done: {row["label"]} - {row["job"]}\n  {row["tally"]}')
    if path and os.path.exists(saved_log(path, row['run'])):
        print(f'  log: {saved_log(path, row["run"])}')


def drop_open_check(path, branch, title):
    """Drop the open row an earlier push left for the check when no run on the pushed
    commit turned up to replace it, so the row checks a commit that is not the head."""
    if not os.path.exists(path):
        return
    with locked(path):
        write_ledger(path, without_check(path, read_ledger(path), branch, title, True))


def without_check(path, rows, branch, title, open_only=False):
    """The rows less those for the check on the branch, open ones only when asked, whose
    saved log and error lines are removed."""
    dropped = [r for r in rows if same_check(r, branch, title)
               and not (open_only and r['state'] == 'done')]
    forget_logs(path, dropped)
    return [r for r in rows if r not in dropped]


def add_checks(path, number, label):
    """Record the CI run on the pull request's head commit, replacing the row an earlier
    push left. Returns the exit code."""
    deadline = time.monotonic() + ADD_BUDGET
    pr = add_read(f'repos/{{owner}}/{{repo}}/pulls/{number}', deadline)
    branch, sha = pr['head']['ref'], pr['head']['sha']
    title = f'{CI_NAME} on pull request {number}'
    if pr['state'] != 'open':
        drop_open_check(path, branch, title)
        print(f'add-checks: pull request {number} is {pr["state"]}, so nothing was recorded')
        return 1
    # A push reaches the pull request's own record a few seconds late, so the branch's ref
    # is read for the pushed commit. A fork's branch is not in this repo, so it is not.
    if (pr['head'].get('repo') or {}).get('full_name') == pr['base']['repo']['full_name']:
        ref = add_read(f'repos/{{owner}}/{{repo}}/git/ref/heads/{quote(branch)}', deadline)
        sha = ref['object']['sha']
    run, mergeable = ci_run(number, sha, branch, deadline)
    if run is None:
        drop_open_check(path, branch, title)
    if mergeable is False:
        print(f'add-checks: pull request {number} conflicts with its base, so no CI run '
              'starts until the conflict is resolved; merge the base in, push, then run '
              'add-checks again')
        return NO_CHECK_RUNS
    if run is None and mergeable is None:
        print(f'add-checks: no CI run on pull request {number} at {sha[:9]}, and whether '
              'it conflicts with its base is not yet worked out; run add-checks again '
              'before taking any other step')
        return NO_CHECK_RUNS
    if run is None:
        print(f'add-checks: no CI run on pull request {number} at {sha[:9]}; CI runs on '
              'every pull request, so check that the push reached GitHub, then run '
              'add-checks once more, since a queue can be slow, and if it still finds none, '
              'ask the user')
        return NO_CHECK_RUNS
    done = {r['run']: r for r in read_ledger(path) if r['state'] == 'done'}
    row = done.get(str(run['id']))
    # A rerun keeps the run id, so a done row answers only for the attempt it tallied.
    if row and run.get('status') == 'completed' and row['tally'].endswith(attempt_note(run)):
        print_done(row, path)
        if os.path.exists(saved_log(path, row['run'], 'errors')):
            with open(saved_log(path, row['run'], 'errors')) as f:
                print(f.read(), end='')
        return 0
    add(path, run['id'], label or title, run, title=title)
    return 0


def log_lines(log):
    """The log's lines with color codes and the runner's timestamp column taken off."""
    for raw in ANSI.sub('', log).splitlines():
        yield raw.split('Z ', 1)[1] if 'Z ' in raw else raw


def more_lines(left_out):
    """The note that ends a cut list of log lines, or nothing when none were cut."""
    return [f'  ... {left_out} more lines in the saved log'] if left_out > 0 else []


def check_errors(logs):
    """The error lines in a run's job logs, each with the step output above it, since a
    lint or scan step prints its findings as plain output before the step's error line.
    Each step opens with a `Run` group holding its setup lines, which are left out along
    with the output of earlier steps; a group the step's own output opens is kept. An
    error line straight after the same one in the same step, with nothing between, is
    shown once. Up to CHECKS_ERROR_LINES error lines are kept, the output above them
    shares the room left in CHECKS_ERROR_LINES, nearest lines first, and a count of the
    lines left out follows."""
    blocks = []
    for log in logs:
        above, in_setup, same_step = [], False, False
        for line in log_lines(log):
            text = line.strip()
            if CHECKS_ERROR in text:
                if above or not same_step or blocks[-1][1] != '  ' + text:
                    blocks.append((above, '  ' + text))
                above, same_step = [], True
            elif text.startswith('##[group]Run '):
                above, in_setup, same_step = [], True, False
            elif text.startswith('##[endgroup]'):
                in_setup = False
            elif text and not in_setup and not text.startswith('##['):
                above.append('  ' + text)
    shown = blocks[:CHECKS_ERROR_LINES]
    room, kept = CHECKS_ERROR_LINES - len(shown), {}
    # The shortest output takes its fair share first, and what it leaves goes to the rest.
    for left, i in enumerate(sorted(range(len(shown)), key=lambda i: len(shown[i][0]))):
        kept[i] = min(len(shown[i][0]), room // (len(shown) - left))
        room -= kept[i]
    out = [line for i, (above, error) in enumerate(shown)
           for line in above[len(above) - kept[i]:] + [error]]
    left_out = sum(len(above) + 1 for above, _ in blocks) - len(out)
    return out + more_lines(left_out)


def test_all_tally(log):
    """The scripts/test-all.sh result in a run's log as (summary, lines), or None when the
    log has no `Tests:` line. The summary reads `test-all: <n> passed, <m> failed; static
    checks <passed|failed>`, with `did not finish` for a run that stopped before the static
    checks printed their result. The lines are each `FAIL  <file> (exit N)` line, followed
    by the `not ok` and `FAIL` lines of that file's output, each once, and then each
    `ERROR` line the static checks printed. Up to CHECKS_ERROR_LINES of them are kept, and
    a count of the lines left out follows."""
    tests = static = None
    lines, failing, seen, in_static = [], False, set(), False
    for line in log_lines(log):
        text = line.strip()
        if line.startswith(FILE_OUTPUT):
            if failing and FAIL_DETAIL.match(text) and text not in seen:
                seen.add(text)
                lines.append('    ' + text)
            continue
        found = TEST_FILE.match(text)
        failing = bool(found) and found[1] == 'FAIL'
        if failing:
            seen = set()
            lines.append('  ' + text)
        elif TESTS_LINE.match(text):
            tests = TESTS_LINE.match(text)
        elif text.startswith(STATIC_START):
            in_static = True
        elif STATIC_LINE.match(text):
            static = STATIC_LINE.match(text)[1]
        elif in_static and text.startswith(STATIC_ERROR):
            lines.append('  ' + text)
    if tests is None:
        return None
    left_out = len(lines) - CHECKS_ERROR_LINES
    summary = (f'test-all: {tests[1]} passed, {tests[2]} failed; '
               f'static checks {static or "did not finish"}')
    return summary, lines[:CHECKS_ERROR_LINES] + more_lines(left_out)


def branch_runs(branch, wanted):
    """The branch's runs by id, read newest first until every wanted run has been seen."""
    runs, page = {}, 1
    while True:
        listed = json.loads(gh('api', f'repos/{{owner}}/{{repo}}/actions/runs'
                               f'?branch={branch}&per_page=100&page={page}'))
        runs.update({str(r['id']): r for r in listed['workflow_runs']})
        if wanted <= runs.keys() or len(listed['workflow_runs']) < 100:
            return runs
        page += 1


def read_runs(rows, by_id):
    """The run record for each row the API answered for."""
    runs = {}
    if by_id:
        for r in rows:
            try:
                runs[r['run']] = json.loads(
                    gh('api', f'repos/{{owner}}/{{repo}}/actions/runs/{r["run"]}'))
            except (RuntimeError, ValueError) as e:
                print(f'{r["label"]}: run read failed, nothing changed: {e}')
        return runs
    for branch in sorted({r['branch'] for r in rows}):
        wanted = {r['run'] for r in rows if r['branch'] == branch}
        try:
            listed = branch_runs(branch, wanted)
        except (RuntimeError, ValueError, KeyError) as e:
            print(f'{branch}: run list failed, nothing changed: {e}')
            continue
        for run_id in wanted:
            runs[run_id] = listed.get(run_id, {'status': 'not listed'})
    return runs


def no_log_tally(conclusion, missing):
    """The tally of a run settled with no log."""
    return f'{conclusion}, no log ({missing})'


def attempt_note(run):
    """The tally's ending for a rerun, which keeps the run id; empty for a first attempt."""
    attempt = run.get('run_attempt', 1)
    return f' (attempt {attempt})' if attempt > 1 else ''


def summarize(run, logs):
    """A finished run's summary and the lines printed below it: the test-all result when
    the log has one, and otherwise the workflow's name and the run's error lines."""
    found = test_all_tally(''.join(logs))
    if found:
        return found
    name = run.get('name') or 'run'
    if run.get('path') == CI_WORKFLOW:
        name += ', no test-all summary'
    return name, check_errors(logs)


def finish(path, row, run):
    """Save a completed run's log and tally it. False when the log fetch failed or came
    back empty, which a log read straight after the run finishes can do for a while. A
    cancelled or skipped run with no log is done, since it may never have started a job,
    and so is a run none of whose jobs started a step, as when no runner took them."""
    try:
        logs, missing = job_logs(row['run'], row['job']), 'log came back empty'
    except RuntimeError as e:
        logs, missing = None, f'log fetch failed: {e}'
    if logs == []:
        missing = 'no job ran'
    log = ''.join(logs or [])
    if not log.strip():
        if run.get('conclusion') in NO_LOG_CONCLUSIONS or logs == []:
            # An earlier attempt's log and error lines do not belong to this one.
            forget_logs(path, [row])
            row['state'] = 'done'
            row['tally'] = no_log_tally(run['conclusion'], missing) + attempt_note(run)
            print_done(row)
            return True
        print(f'{row["label"]}: {missing}, will retry next check')
        return False
    os.makedirs(path + '.logs', exist_ok=True)
    with open(saved_log(path, row['run']), 'w') as f:
        f.write(log)
    summary, lines = summarize(run, logs)
    # add-checks prints these again when asked about a run already done.
    with open(saved_log(path, row['run'], 'errors'), 'w') as f:
        f.writelines(line + '\n' for line in lines)
    row['state'], row['tally'] = 'done', f'{run["conclusion"]} {summary}{attempt_note(run)}'
    print_done(row, path)
    for line in lines:
        print(line)
    # A run's block reaches a redirected stdout whole, before the next run's log is read.
    sys.stdout.flush()
    return True


def check(path, notified=None):
    """Tally what has finished. Given notified run ids, reads only those runs, each by id."""
    # Pull request and issue rows settle through their own reads, so check skips them.
    rows = [r for r in read_ledger(path) if r['state'] != 'done' and is_run(r['run'])
            and (notified is None or r['run'] in notified)]
    runs = read_runs(rows, notified is not None)
    updates = {}
    for r in rows:
        run = runs.get(r['run'])
        if run is None:
            continue
        if run['status'] != 'completed':
            updates[r['run']] = (run['status'], '')
        elif finish(path, r, run):
            updates[r['run']] = ('done', r['tally'])
    # add can record a run while the calls above are out, so the ledger is read again here.
    with locked(path):
        rows = read_ledger(path)
        for r in rows:
            if r['run'] in updates and r['state'] != 'done':
                r['state'], r['tally'] = updates[r['run']]
        write_ledger(path, rows)
    waiting = [r for r in rows if r['state'] != 'done']
    counts = {}
    for r in waiting:
        counts[r['state']] = counts.get(r['state'], 0) + 1
    summary = ', '.join(f'{n} {s}' for s, n in sorted(counts.items())) or 'none'
    print(f'{len(rows) - len(waiting)} of {len(rows)} done; still waiting: {summary}')
    return len(waiting)


def utc(seconds=None):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(seconds))


def installed():
    """Whether gh has the forwarder extension. A missing extension is reported, never
    installed here, and the waiter checks on its timer instead."""
    os.makedirs(PUSH_DIR, exist_ok=True)
    with open(os.path.join(PUSH_DIR, 'extension.lock'), 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if EXTENSION in gh('extension', 'list', timeout=INSTALL_TIMEOUT):
                return True
        except RuntimeError as e:
            print(f'push: {EXTENSION} is not available: {e}')
            return False
    print(f'push: the {EXTENSION} extension is not installed, so this waiter checks on '
          f'its timer; ask the user to run `gh extension install {EXTENSION}`')
    return False


class Push:
    """This waiter's share of the workflow_run event stream on this machine."""

    def __init__(self):
        self.proc = self.hook = self.handle = None
        self.holder, self.marked, self.error, self.threads = False, '', '', []
        self.started = self.retry_at = self.checked = 0.0
        self.backoff = FORWARDER_RESTART
        # The latest event for each run, by run id.
        self.seen = {}
        # Set when GitHub gave no answer, so wait tries again on its next timer check.
        self.retryable = False
        self.usable = installed()
        if not self.usable:
            return
        try:
            self.repo = gh('repo', 'view', '--json', 'nameWithOwner',
                           '-q', '.nameWithOwner').strip()
        except RuntimeError as e:
            print(f'push: could not reach GitHub, push is off for now: {e}')
            self.usable, self.retryable = False, True
            return
        base = os.path.join(PUSH_DIR, self.repo.replace('/', '__'))
        os.makedirs(base, exist_ok=True)
        self.events = os.path.join(base, 'events.jsonl')
        self.state = os.path.join(base, 'forwarder.state')
        self.hook_file = os.path.join(base, 'forwarder.hook')
        self.lock = open(os.path.join(base, 'forwarder.lock'), 'a')
        # A run can be recorded after its completed event landed, so the files are read whole.
        try:
            with open(self.events + '.old', 'rb') as f:
                for line in f:
                    self.fold(line)
        except FileNotFoundError:
            pass
        self.read()

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def tend(self):
        """Hold the lock and keep a forwarder running under it. True while events arrive."""
        if not self.usable:
            return False
        if not self.holder:
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return read_file(self.state) == 'live'
            self.holder = True
            print(f'push: this waiter holds the forwarder for {self.repo}')
        now = time.time()
        if self.running() and now - self.checked >= HOOK_CHECK:
            self.checked = now
            if self.hook is None or self.hook_exists(self.hook) is False:
                print('push: the forwarder has no hook on the repository')
                self.halt()
        if self.running():
            self.mark('live' if self.hook else 'starting')
            return self.hook is not None
        if self.proc:
            lived = now - self.started
            print(f'push: forwarder stopped after {lived:.0f}s with {self.proc.returncode}: '
                  f'{self.error or "no error message"}')
            self.halt()
            self.proc = None
            # A forwarder refused at once, as when another machine holds the hook, waits
            # twice as long after each refusal.
            if lived >= FORWARDER_RESTART:
                self.backoff = FORWARDER_RESTART
            self.retry_at = now + self.backoff
            self.backoff = min(self.backoff * 2, FORWARDER_RESTART_MAX)
        if now < self.retry_at:
            self.mark('down')
            return False
        self.start()
        return False

    def mark(self, state):
        if state != self.marked:
            write_file(self.state, state)
            self.marked = state

    def start(self):
        orphan = f'extensions/gh-webhook/gh-webhook forward --repo {self.repo} '
        if subprocess.run(['pkill', '-f', orphan]).returncode == 0:
            print('push: stopped a forwarder that outlived its waiter')
        made_here = read_file(self.hook_file)
        if made_here:
            self.retire(made_here)
        self.clear_inactive()
        # gh runs the extension as a child process, so halt() signals the whole group. The
        # extension takes the repository only through its own --repo flag.
        self.proc = subprocess.Popen(
            ['gh', 'webhook', 'forward', '--repo', self.repo, '--events', FORWARDED_EVENTS],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True)
        self.hook, self.error = None, ''
        self.started = self.checked = time.time()
        self.threads = [threading.Thread(target=self.pump, args=(self.proc.stdout,)),
                        threading.Thread(target=self.keep_error, args=(self.proc.stderr,))]
        for t in self.threads:
            t.daemon = True
            t.start()
        self.mark('starting')
        print(f'push: forwarder started at {utc()}')

    def retire(self, hook):
        """Wait for GitHub to drop a hook made here, and delete it if it stays."""
        for _ in range(5):
            exists = self.hook_exists(hook)
            if exists is not True:
                break
            time.sleep(2)
        if exists:
            try:
                gh('api', '-X', 'DELETE', f'repos/{self.repo}/hooks/{hook}')
                print(f'push: deleted hook {hook}, which a forwarder here left behind')
                exists = False
            except RuntimeError as e:
                print(f'push: could not delete hook {hook}: {e}')
        if exists is False and os.path.exists(self.hook_file):
            os.remove(self.hook_file)

    def clear_inactive(self):
        """Delete forwarder hooks GitHub has marked inactive, which no forwarder is using."""
        try:
            hooks = json.loads(gh('api', f'repos/{self.repo}/hooks'))
        except (RuntimeError, ValueError) as e:
            print(f'push: could not list hooks: {e}')
            return
        for hook in hooks:
            # A forwarder's hook is named cli and stays active while one is connected.
            if hook.get('name') != 'cli' or hook.get('active'):
                continue
            last = hook.get('last_response') or {}
            try:
                gh('api', '-X', 'DELETE', f'repos/{self.repo}/hooks/{hook["id"]}')
                print(f'push: deleted inactive hook {hook["id"]}, made '
                      f'{hook.get("created_at")}, last delivery {last.get("code")} '
                      f'{last.get("status")}')
            except RuntimeError as e:
                print(f'push: could not delete inactive hook {hook["id"]}: {e}')

    def hook_exists(self, hook):
        """Whether the repository has the hook, or None when the API gave no answer."""
        try:
            gh('api', '--silent', f'repos/{self.repo}/hooks/{hook}')
            return True
        except RuntimeError as e:
            return False if 'HTTP 404' in str(e) else None

    def pump(self, pipe):
        """Write each event the forwarder prints to the events file as one short line."""
        for raw in pipe:
            try:
                event = json.loads(raw)
                run = event.get('workflow_run')
                if run:
                    line = {'event': 'run', 'run': str(run['id']),
                            'attempt': run.get('run_attempt'), 'action': event.get('action'),
                            'conclusion': run.get('conclusion'),
                            'updated': run.get('updated_at'),
                            'branch': run.get('head_branch'), 'at': utc()}
                elif event.get('pull_request'):
                    pr = event['pull_request']
                    # Only a close settles a row; opens, pushes and reviews are not written.
                    if event.get('action') != 'closed':
                        continue
                    line = {'event': 'pr', 'run': f'{PR_PREFIX}{pr["number"]}',
                            'action': 'closed',
                            'state': 'merged' if pr.get('merged') else 'closed',
                            'sha': pr.get('merge_commit_sha'),
                            'merged_at': pr.get('merged_at'),
                            'closed_at': pr.get('closed_at'),
                            'branch': (pr.get('head') or {}).get('ref'), 'at': utc()}
                elif event.get('issue'):
                    issue = event['issue']
                    # Only a close settles an issue row; edits, labels and reopens do not.
                    if event.get('action') != 'closed':
                        continue
                    line = {'event': 'issue', 'run': f'{ISSUE_PREFIX}{issue["number"]}',
                            'action': 'closed', 'state': 'closed',
                            'reason': issue.get('state_reason'),
                            'closed_at': issue.get('closed_at'), 'at': utc()}
                elif 'hook_id' in event:
                    self.hook = event['hook_id']
                    write_file(self.hook_file, str(self.hook))
                    line = {'event': 'hook', 'hook': self.hook, 'at': utc()}
                else:
                    continue
                if os.path.exists(self.events) and os.path.getsize(self.events) > EVENTS_ROTATE:
                    os.replace(self.events, self.events + '.old')
                with open(self.events, 'a') as f:
                    f.write(json.dumps(line) + '\n')
            # A bad line is skipped: a stopped thread leaves the forwarder blocked on a full pipe.
            except Exception as e:
                print(f'push: skipped a forwarder line: {e!r}'[:200])

    def keep_error(self, pipe):
        """Keep the forwarder's error message; its other lines are usage text and event logs."""
        detail = False
        for raw in pipe:
            text = raw.decode(errors='replace').strip()
            if text.startswith('Error'):
                self.error, detail = text, True
            elif detail and text:
                self.error, detail = f'{self.error} {text}', False

    def halt(self):
        """Stop the forwarder's process group and let the threads write what it printed."""
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(self.proc.pid, sig)
            except ProcessLookupError:
                pass
            for t in self.threads:
                t.join(timeout=10)
            if not any(t.is_alive() for t in self.threads):
                break
        self.proc.wait()

    def stop(self):
        if not self.holder:
            return
        if self.proc:
            self.halt()
            self.proc = None
        self.mark('down')
        fcntl.flock(self.lock, fcntl.LOCK_UN)
        self.holder = False

    def read(self):
        """Fold the events added since the last read into seen. True if a forwarder connected."""
        connected = False
        for line in self.new_lines():
            connected = self.fold(line) or connected
        return connected

    def new_lines(self):
        """Complete lines added to the events file since the last read, across a rename.

        A reader that misses two renames between reads loses the file between them, and
        the timer check covers those runs.
        """
        try:
            inode = os.stat(self.events).st_ino
        except FileNotFoundError:
            return []
        lines = []
        if self.handle and os.fstat(self.handle.fileno()).st_ino != inode:
            lines = self.drain()
            self.handle.close()
            self.handle = None
        if not self.handle:
            self.handle, self.partial = open(self.events, 'rb'), b''
        return lines + self.drain()

    def drain(self):
        *lines, self.partial = (self.partial + self.handle.read()).split(b'\n')
        return lines

    def fold(self, raw):
        """Record one events line. True when the line says a forwarder connected."""
        try:
            line = json.loads(raw)
        except ValueError:
            return False
        if not isinstance(line, dict):
            return False
        if line.get('event') == 'hook':
            return True
        run_id = line.get('run')
        if line.get('event') in ('pr', 'issue'):
            # The latest close wins: either can be closed, reopened and closed again.
            if run_id and not is_run(run_id):
                self.remember(run_id, line)
            return False
        if line.get('event') != 'run' or not run_id or line.get('action') not in RANK:
            return False
        # Deliveries can land out of order, so a later attempt or a later action wins.
        old = self.seen.pop(run_id, None)
        if old and ((old.get('attempt') or 1, RANK[old['action']])
                    >= (line.get('attempt') or 1, RANK[line['action']])):
            line = old
        self.remember(run_id, line)
        return False

    def remember(self, key, line):
        self.seen.pop(key, None)
        self.seen[key] = line
        if len(self.seen) > SEEN_LIMIT:
            del self.seen[next(iter(self.seen))]


def wait(path, interval, every=False):
    push = Push()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.signal(signal.SIGHUP, lambda *_: sys.exit(0))
    before, conflicts = done_rows(path), conflicted_rows(path)
    try:
        if not push.usable:
            print('push: off, checking on the timer only')
        # A push that failed to reach GitHub is set up again after each timer check, and
        # the waiter moves on to the push loop below once it comes up.
        while not push.usable:
            # With no forwarder, the timer is the only way a pull request or issue row settles.
            reconcile_rows(path)
            left = check(path)
            if handed_back(path, before, every, conflicts):
                return
            if not left:
                report_finished(path, before)
                return
            sys.stdout.flush()
            time.sleep(interval)
            if push.retryable:
                push = Push()
                if push.usable:
                    print('push: reached GitHub, push is on')
        push.tend()
        remaining, last = check(path), time.time()
        # By run id: the completed event last acted on, and for each notified run still
        # open, when it is read next and how many reads it has left.
        acted, pending, gap = {}, {}, False
        # Pull request and issue reads that failed on connect, and when they are read again.
        pr_retry, pr_retry_at = set(), 0.0
        while remaining and not handed_back(path, before, every, conflicts):
            sys.stdout.flush()
            time.sleep(EVENT_POLL)
            live = push.tend()
            # A forwarder that just connected missed the runs that finished before it.
            connected = push.read()
            gap = connected or gap
            now = time.time()
            if connected:
                pr_retry, pr_retry_at = reconcile_rows(path), now + EVENT_RECHECK
                remaining = len(open_runs(path))
            elif pr_retry and now >= pr_retry_at:
                # One retry; a read that fails again waits for the next connect.
                for key in reconcile_rows(path, pr_retry):
                    print(f'{key} read failed twice; waiting for its push notice '
                          'or the next forwarder connect')
                pr_retry = set()
                remaining = len(open_runs(path))
            for row in read_ledger(path):
                run_id = row['run']
                if row['state'] == 'done':
                    continue
                event = push.seen.get(run_id)
                if not is_run(run_id):
                    added = row['tally'].removeprefix('added ')
                    if event and event.get('at', '') >= added and acted.get(run_id) != event:
                        acted[run_id] = event
                        print(f'push: notice for {run_id} arrived {event.get("at")}')
                        settle_row(path, run_id, event['state'], notice_tally(event))
                        remaining = len(open_runs(path))
                    continue
                if event and event['action'] == 'completed' and acted.get(run_id) != event:
                    acted[run_id] = event
                    print(f'push: notice for {run_id} arrived {event.get("at")}; '
                          f'run updated_at {event.get("updated")}')
                    pending[run_id] = (now, EVENT_RECHECKS)
            due = {r for r, (at, _) in pending.items() if at <= now}
            timer = interval if gap or not live else max(interval, PUSH_FALLBACK_INTERVAL)
            if now - last >= timer:
                # A close sent while the forwarder is down never arrives, and a reconnect
                # can be minutes away, so the timer reads the rows itself. Issue rows are
                # read even while it is live, since an older holder does not forward them,
                # and so are pull request rows, since a merge conflict sends no notice.
                reconcile_rows(path)
                remaining, last, gap, due = check(path), now, False, set(pending)
            elif due:
                remaining = check(path, due)
            else:
                continue
            still_open = open_runs(path)
            for run_id in due:
                reads = pending.pop(run_id)[1] - 1
                if run_id in still_open and reads:
                    pending[run_id] = (now + EVENT_RECHECK, reads)
        # The loop test skips handed_back once nothing is open, so the last row's
        # result is reported here.
        if not remaining:
            report_finished(path, before)
    finally:
        push.stop()


def wait_args(args):
    """The ledger, interval and --all that `wait` was given, its flags in any order."""
    ledger, interval, every = None, MIN_INTERVAL, False
    rest = iter(args)
    for arg in rest:
        if arg == '--all':
            every = True
        elif arg == '--interval':
            value = next(rest, None)
            if value is None or not value.isdigit():
                raise ValueError(f'--interval takes a number of seconds, not {value!r}')
            interval = max(MIN_INTERVAL, int(value))
        elif arg.startswith('-'):
            raise ValueError(f'unknown option {arg}')
        elif ledger is None:
            ledger = arg
        else:
            raise ValueError(f'one ledger, not both {ledger} and {arg}')
    if ledger is None:
        raise ValueError('no ledger given')
    return ledger, interval, every


def ledger_missing(command, path):
    """True, with a line saying so, when there is no ledger at path to read."""
    if os.path.isfile(path):
        return False
    print(f'{command}: no ledger at {path}; add, add-pr, add-checks and '
          'add-issue create one')
    return True


def main(argv):
    if len(argv) >= 4 and argv[1] == 'add':
        try:
            add(argv[2], argv[3], ' '.join(argv[4:]) or argv[3])
        except (RuntimeError, ValueError, KeyError) as e:
            print(f'add: run {argv[3]} not recorded: {e}')
            return 1
    elif len(argv) == 3 and argv[1] == 'check':
        if ledger_missing('check', argv[2]):
            return 2
        check(argv[2])
    elif len(argv) >= 3 and argv[1] == 'wait':
        try:
            ledger, interval, every = wait_args(argv[2:])
        except ValueError as e:
            print(f'wait: {e}')
            return 2
        if ledger_missing('wait', ledger):
            return 2
        return wait(ledger, interval, every) or 0
    elif len(argv) >= 4 and argv[1] == 'add-pr':
        add_pr(argv[2], argv[3], ' '.join(argv[4:]) or f'pull request {argv[3]}')
    elif len(argv) >= 4 and argv[1] == 'add-checks':
        number = argv[3].lstrip('#')
        try:
            return add_checks(argv[2], number, ' '.join(argv[4:]))
        except (RuntimeError, ValueError, KeyError) as e:
            print(f'add-checks: pull request {number} failed: {e}; nothing was recorded')
            return 1
    elif len(argv) >= 4 and argv[1] == 'add-issue':
        number = argv[3].lstrip('#')
        try:
            add_issue(argv[2], number, ' '.join(argv[4:]) or f'issue {number}')
        except (RuntimeError, ValueError, KeyError) as e:
            print(f'add-issue: issue {number} not recorded: {e}')
            return 1
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
