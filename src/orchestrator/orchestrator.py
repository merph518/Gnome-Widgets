#!/usr/bin/env python3
"""Builds the Claude Code Orchestrator widget's contents: the managed Claude sessions, and what they have replied.

Four times a second this reads, and only reads:
  - the open Claude sessions, from ~/.claude/sessions/<pid>.json (sessions.py), the
    processes under each in /proc (a test run, or a wait on a systemd unit) and its
    catchup.py ledgers
  - the hooks' folder, $XDG_RUNTIME_DIR/speak-attention/: <session>.managed marks a
    managed session (sessions.py lists only those) and <session>.feed holds its replies, one
    JSON object a line (session, name, text, markdown, at), written by the hooks.
    The .key files beside the session files are never opened.

and writes, under ~/.cache/conky-widgets/orchestrator/, the files the Spotify widget's
nowplaying.py writes for its own card:
  - widget.txt   conky's markup: the spacer lines that give conky's window its size
  - draw.txt     geometry for draw.lua (logical px, from the card's top left): the title, the
                 sessions list and the terminal pane with the replies
  - regions.json click areas for conky-mouse.py, in the same coordinates
  - sessions.txt the sessions list, a line per session, rewritten only when it changes

Each session's row ends with the age of its last reply, and carries that reply's line under
it while the reply is newer than LAST_LINE_WITHIN. The terminal pane prints the replies of
the listed sessions, oldest first.
"""
import datetime, fcntl, glob, hashlib, json, math, os, re, subprocess, sys, tempfile, time, unicodedata
import gi
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Pango, PangoCairo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'common'))
import sessions as sessions_mod  # noqa: E402
import widget_size as size_file  # noqa: E402

NAME = 'conky-widgets/orchestrator'
CONF = os.path.expanduser(f'~/.config/{NAME}')
CACHE = os.path.expanduser(f'~/.cache/{NAME}')
OUT = os.path.join(CACHE, 'widget.txt')
DRAW = os.path.join(CACHE, 'draw.txt')
REGIONS = os.path.join(CACHE, 'regions.json')
SESSIONS = os.path.join(CACHE, 'sessions.txt')
LOG = os.path.join(CACHE, 'orchestrator.log')
INSTANCE_LOCK = os.path.join(CACHE, 'orchestrator.lock')
SIZE = size_file.ORCHESTRATOR_PATH
SPLIT = os.path.join(CONF, 'split')               # the sessions column's share of the width, 0 to 1; dragged by the divider
COLLAPSE = os.path.join(CONF, 'collapse-idle')    # 'on': a single line while nothing is said
# Claude's per-session temp folders, where a session's scripts/catchup.py ledger is
# <project>/<session id>/scratchpad/<a LEDGER_FILES name>: a row a line, tab apart, as
# ledger_fields reads it
LEDGERS = os.path.join(tempfile.gettempdir(), f'claude-{os.getuid()}')
LEDGER_FILES = ('ledger', 'ledger.tsv', 'catchup.tsv')   # a session's ledger in its scratchpad
WAITS = (('run:', 'tests'), ('lp:', 'ci'), ('pr:', 'merge'))   # an open row's key, and the wait
# A shell polling a systemd user unit until it stops, and the tag of the units it shows
UNIT_WAIT = re.compile(r'systemctl --user is-active (?:-q |--quiet )?([\w@.-]+)')
UNITS = {'build-pack-now': 'local ai'}          # build-test-pack's local model pipeline
TEST_FILE = re.compile(r'(test_[\w.-]*|[\w.-]*_test)\.(py|sh)$')   # test_x.py, x_test.sh
HOOK_DIR = os.path.join(os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}', 'speak-attention')

SHADOW = size_file.SHADOW
MARGIN = 16                                   # around the contents
TERM_PAD = 10                                 # the terminal pane's border to its text, on every side
TERM_TITLE = 'Combined Session Output'        # on the pane's border, whichever session is read
SCROLLBACK_KEEP = 40                          # the replies the pane keeps to scroll back through
SCROLLBACK_CHARS = 60000                      # and the most text they hold between them
LAST_LINE_WITHIN = 600                        # s: a session's last reply is a line under its row while it is newer than this
BULLET_MARK = '\x02'                          # opens a draw.txt line that is the first of a message, which draw.lua draws a bullet by
PROMPT_MARK = '\x04'                          # opens a draw.txt line that is a speaker's name, which draw.lua draws as the CLI's prompt: on a grey band behind a chevron
META_MARK = '\x06'                            # in a prompt line, before the speaker's name's end and before each piece of its issue and pull request list: a style letter (n plain, k a number that is a link), then the text, which draw.lua right-aligns
BAND_MARK = '\x07'                            # opens a draw.txt line of a fenced code block (after BULLET_MARK when it is a message's first), which draw.lua sets on a lighter band across the pane
DONE_MARK = '\x05'                            # opens a message's closing line, which draw.lua draws dim behind the CLI's spinner glyph
TERM_BANNER_LINES = 3                         # the pane's welcome banner: the creature's rows, beside its title and a dim line
TERM_INDENT = '  '                            # every line's room at the left, where the first line's bullet is drawn
TITLE = 'Claude Code Orchestrator'            # the widget's name, drawn in capitals along the top
TITLE_TRACK = 0.09                            # the title's letter spacing, in ems
TITLE_GAP = 8                                 # the title's end to the minimize button
HEADER_GAP = 6                                # the title to the card's end when collapsed
COLUMN_GAP = 24                               # the sessions column to the terminal pane, the divider centred in it
SPLIT_DEFAULT = 0.5                           # the sessions column's share of the width inside the gap, with no setting
LIST_MIN = 260                                # the sessions column's least width, so a row keeps its name
TERM_MIN = 200                                # the terminal pane's least width
LINE_GAP = 14                                 # the title's row to the list
ROW_SPACING = 4                               # extra space in a session's row
WINDOW_BUTTON_SIZE = 10                       # minimize / close, as the Spotify widget's
WINDOW_BUTTON_PITCH = 22
CONFIRM_W = 320                               # the close prompt's width, at most
CONFIRM_PAD = 14                              # round its contents
CONFIRM_GAP = 8                               # between its lines, and its two buttons
CONFIRM_BUTTON_PAD = 14                       # either side of a button's label
GROUP_PAD = 10                                # the list's edge to a repository's name
SESSION_INDENT = 32                           # a repository's name's left to the names of the sessions under it, after their bullets, which are not indented
BLOCK_SLACK = 1.04                            # draw.lua's cairo text runs wider than Pango's, which kerns
SPACER_FONT = 'Ubuntu Sans 1'
SPACER_HEIGHT = 2                             # what conky adds for that spacer line (measured)
PLAIN_FONT = 'Ubuntu Sans 13'                 # between runs of text; see plain()
LABEL_FONT = 'Ubuntu Sans Bold 11'            # the title, and the close prompt's title and buttons
ROW_FONT = 'Ubuntu Sans 11'                   # a session's row, as draw.lua draws it
SEGMENT_FONT = 'Ubuntu Sans Bold 9'           # a repository's name, as draw.lua draws it
LIST_FONT = 'Ubuntu Mono 12'                  # the sessions column's text, as the terminal's, as draw.lua draws it: a session's name
LIST_TAG_FONT = 'Ubuntu Mono 11'              # its repository and the age of its last reply
LIST_HEAD_FONT = 'Ubuntu Mono Bold 12'        # a repository's name
TAG_FONT = 'Ubuntu Sans 9'                    # the close prompt's lines, as draw.lua draws them
TERM_FONT = 'Ubuntu Mono 12'                  # the terminal pane's text, as draw.lua draws it
TERM_BOLD_FONT = 'Ubuntu Mono Bold 12'
TERM_ITALIC_FONT = 'Ubuntu Mono Italic 12'
TERM_BOLD_ITALIC_FONT = 'Ubuntu Mono Bold Italic 12'
STYLE_FONTS = {'': TERM_FONT, 'b': TERM_BOLD_FONT, 'i': TERM_ITALIC_FONT, 'x': TERM_BOLD_ITALIC_FONT, 'c': TERM_FONT, 'd': TERM_FONT}
TEXT_FONTS = {PLAIN_FONT, LABEL_FONT, ROW_FONT, SEGMENT_FONT, TAG_FONT, LIST_FONT, LIST_TAG_FONT, LIST_HEAD_FONT,
              TERM_FONT, TERM_BOLD_FONT, TERM_ITALIC_FONT, TERM_BOLD_ITALIC_FONT}
MARKDOWN_MAX = 6000                           # the most of a line's markdown the terminal pane reads
STYLE_MARK = '\x1f'                           # in a draw.txt line, before each run: its style letter, then its text

_pango = PangoCairo.FontMap.get_default().create_context()
PangoCairo.context_set_resolution(_pango, 96)

widget_width, list_height, text_scale = size_file.ORCHESTRATOR_DEFAULTS


def log(msg):
    os.makedirs(CACHE, exist_ok=True)
    with open(LOG, 'a') as f:
        f.write(time.strftime('%H:%M:%S ') + msg + '\n')


# Text, measured with Pango in the fonts conky and draw.lua draw with -----------------------

def sized(font):
    """The font at the text scale, if it is text: 'Ubuntu Sans 13' at 1.5 -> 'Ubuntu Sans 19.5'."""
    if font not in TEXT_FONTS:
        return font
    *name, pt = font.split()
    return f"{' '.join(name)} {float(pt) * text_scale:g}"


def font_description(font):
    return Pango.FontDescription.from_string(sized(font))


def layout(text, font):
    lay = Pango.Layout.new(_pango)
    lay.set_font_description(font_description(font))
    lay.set_text(text, -1)
    return lay


def display_text(text):
    """text on one line as the widget shows it: format characters (Unicode Cf), which conky
    and Cairo draw as boxes, dropped, and runs of white space, newlines and tabs among them,
    as one space."""
    text = ''.join(c for c in str(text) if unicodedata.category(c) != 'Cf')
    return ' '.join(text.split())


def ledger_fields(f):
    """A ledger line's fields as [label, key, link, state, tally, ...]. This repository's
    catchup.py writes those columns; the one the other repositories keep has the branch after
    the label (label, branch, key, link, state, tally, title), told apart by the link in the
    fourth field."""
    return [f[0]] + f[2:] if len(f) > 4 and f[3].startswith('http') else f


def ledger_rows(sid, ledgers=None):
    """The open rows of session `sid`'s catchup.py ledgers (scratchpad/ledger, ledger.tsv or
    catchup.tsv as another repository names it, and a skill's own such as
    scratchpad/sweep/ledger.tsv), each a list of its fields as ledger_fields has them."""
    folder = os.path.join(glob.escape(ledgers or LEDGERS), '*', glob.escape(sid), 'scratchpad')
    paths = [p for name in LEDGER_FILES for p in glob.glob(os.path.join(folder, name))]
    paths += glob.glob(os.path.join(folder, '*', 'ledger.tsv'))
    rows = []
    for path in paths:
        for line in (_read(path) or '').splitlines():
            f = ledger_fields(line.split('\t'))
            if len(f) >= 4 and f[3] != 'done':
                rows.append(f)
    return rows


def waiting_on(rows):
    """What a session waits on by its open ledger rows: 'tests' with a GitHub Actions run open,
    else 'ci' with a Launchpad build open, else 'merge' with a pull request open, else ''."""
    # a row with a run link is a test run in CI, whatever its key
    keys = {'run:' if any('/actions/runs/' in x for x in f) else f[1] for f in rows}
    return next((wait for prefix, wait in WAITS if any(k.startswith(prefix) for k in keys)), '')


def ledger_prs(rows):
    """The links of the pull requests a session's open ledger rows wait on to merge, which
    /implement records once it has sent the ready signal."""
    return list(dict.fromkeys(f[2] for f in rows if f[1].startswith('pr:') and '/pull/' in f[2]))


def first_wait(process, ledger):
    """The one wait a row shows: tests (a run under the session or in CI), then a unit the
    session polls, then what its ledger waits on."""
    return 'tests' if 'tests' in (process, ledger) else process or ledger


def is_test_run(argv):
    """Whether a process's arguments are a test run: unittest or pytest, a test_*.py or
    *_test.sh/py script, `npm|pnpm|yarn test`, `go|cargo test` or `playwright test`. A shell's
    -c wrapper around one is not, so the run counts once, by its own process."""
    if not argv:
        return False
    prog, args = os.path.basename(argv[0]), argv[1:]
    words = [os.path.basename(a) for a in argv]
    if prog in ('pytest', 'py.test') or TEST_FILE.match(prog):
        return True
    if prog.startswith('python'):
        if '-m' in args[:-1] and args[args.index('-m') + 1] in ('unittest', 'pytest'):
            return True
        # the first argument that is neither an option nor the value -W or -X takes
        script = next((a for i, a in enumerate(args) if not a.startswith('-') and
                       (i == 0 or args[i - 1] not in ('-W', '-X'))), '')
        return bool(TEST_FILE.match(os.path.basename(script)))
    if prog in ('bash', 'sh', 'dash'):
        return bool(args) and args[0] != '-c' and bool(TEST_FILE.match(os.path.basename(args[0])))
    if prog in ('npm', 'pnpm', 'yarn'):
        return 'test' in args[:2]
    if prog in ('go', 'cargo'):
        return args[:1] == ['test']
    return any(w == 'playwright' and words[i + 1:i + 2] == ['test'] for i, w in enumerate(words))


def children(pid, proc_dir='/proc'):
    """The pids of `pid`'s child processes, from each of its threads' children file."""
    kids = []
    for path in glob.glob(os.path.join(proc_dir, str(pid), 'task', '*', 'children')):
        kids += [int(k) for k in (_read(path) or '').split()]
    return kids


def process_waits(pids, proc_dir='/proc'):
    """{session pid: 'tests' or a unit's tag} for the pids among `pids` (the sessions') with a
    test run among their descendants, or a shell waiting on a systemd unit (UNIT_WAIT). A test
    run comes before a unit."""
    found = {}
    for session in pids:
        todo, seen = children(session, proc_dir), set()
        while todo and found.get(session) != 'tests':
            pid = todo.pop()
            if pid in seen:
                continue
            seen.add(pid)
            try:
                with open(os.path.join(proc_dir, str(pid), 'cmdline'), 'rb') as f:
                    argv = [a.decode(errors='replace') for a in f.read().split(b'\0') if a]
            except OSError:
                continue
            if is_test_run(argv):
                found[session] = 'tests'
            elif len(argv) > 2 and argv[1] == '-c' and (unit := UNIT_WAIT.search(argv[2])):
                found.setdefault(session, UNITS.get(unit[1], unit[1]))
            todo += children(pid, proc_dir)
    return found


def text_width(text, font):
    return layout(text, font).get_pixel_size()[0]


def fit(text, font, width):
    """text, cut a character at a time with an ellipsis until it fits in width."""
    if text_width(text, font) <= width:
        return text
    while text:
        text = text[:-1]
        if text_width(text.rstrip() + '…', font) <= width:
            return text.rstrip() + '…'
    return '…'


def _height(description):
    m = _pango.get_metrics(description, None)
    return (m.get_ascent() + m.get_descent()) / Pango.SCALE


def line_height(*fonts):
    """Conky's height for a line: the tallest font's ascent + descent."""
    return max(_height(font_description(font)) for font in fonts)


def esc(text):
    """text as conky draws it literally: '$' starts a variable and '#' a comment."""
    return text.replace('$', '$$').replace('#', '\\#')


def conky_font(pango_font, family=None):
    """'Ubuntu Sans Bold 11' -> 'Ubuntu Sans:bold:size=11', at the text scale."""
    *name, pt = sized(pango_font).split()
    bold = 'Bold' in name
    name = family or ' '.join(n for n in name if n != 'Bold')
    return f"{name}{':bold' if bold else ''}:size={pt}"


def plain():
    """Ends a run of text in a font of its own rather than conky.conf's tiny default, which
    conky would count into the line's height (nowplaying.py's plain)."""
    return f"${{font {conky_font(PLAIN_FONT)}}}"


class Markup:
    """conky.text, a line at a time, and the running top of the next line (logical px from
    the card's top). Vertical gaps are tiny lines of their own ending in a ${voffset}; a line
    starts in the font the one before it ended in, which conky counts into its height, so
    this keeps track of whether that was text (plain()) or the spacer font."""

    def __init__(self, top):
        # The first line makes conky's window the widget's width (a goto only counts on a
        # line with another after it) and starts the next one at `top`.
        self.lines, self.y, self.after_text = [], 0, False
        self.gap(SHADOW + top, f"${{goto {2 * (SHADOW + MARGIN) + widget_width}}}")
        self.y = top

    def gap(self, space, end=''):
        starts = line_height(PLAIN_FONT) if self.after_text else SPACER_HEIGHT
        self.lines.append(f"${{font {conky_font(SPACER_FONT)}}} {end}${{voffset {round(space - starts)}}}")
        self.y += space
        self.after_text = False

    def text(self, markup, height):
        self.lines.append(markup)
        self.y += height
        self.after_text = True

    def end(self, bottom):
        """The last line, ending the window at the shadow margin below `bottom`."""
        self.gap(bottom + SHADOW - self.y)
        return '\n'.join(self.lines)   # no trailing newline: it would add an empty line


# The files it reads ---------------------------------------------------------------------

def _read(path):
    try:
        with open(path, encoding='utf-8') as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


_feeds = {}


def feed_entries(path):
    """The replies in a session's <id>.feed, oldest first, as {key, session, name, markdown, text,
    at}: one JSON object a line, as the hook appends them. A line that is not an object with a
    time, or that holds nothing to print, is skipped, as is a last line still being written. Kept
    until the file changes, since the sessions' feeds are read four times a second."""
    try:
        st = os.stat(path)
    except OSError:
        _feeds.pop(path, None)
        return []
    stamp = (st.st_mtime_ns, st.st_size)
    if _feeds.get(path, (None,))[0] != stamp:
        entries = []
        for line in (_read(path) or '').splitlines():
            try:
                e = json.loads(line)
                at = float(e['at'])
            except (ValueError, KeyError, TypeError):
                continue
            if not math.isfinite(at):
                continue
            text, markdown = display_text(e.get('text') or ''), clean_markdown(e.get('markdown'))
            if text or markdown:
                entries.append({'key': hashlib.sha1(line.encode()).hexdigest(), 'session': str(e.get('session') or ''),
                                'name': display_text(e.get('name') or ''), 'markdown': markdown, 'text': text,
                                'at': at})
        _feeds[path] = (stamp, entries)
    return _feeds[path][1]


def feed(hook_dir, listed):
    """The replies the terminal pane prints: those of the listed sessions, each under the name the
    list gives it, the newest SCROLLBACK_KEEP of them within SCROLLBACK_CHARS of text, oldest
    first."""
    entries = []
    for s in listed:
        entries += [dict(e, session=s['id'], name=s['name']) for e in feed_entries(os.path.join(hook_dir, s['id'] + '.feed'))]
    entries.sort(key=lambda e: e['at'])
    entries = entries[-SCROLLBACK_KEEP:]
    while len(entries) > 1 and sum(len(e['markdown']) + len(e['text']) for e in entries) > SCROLLBACK_CHARS:
        del entries[0]
    return entries


def age_text(seconds):
    """How long ago a reply was, as the row's right end says it: now, 1m, 25m, 3h, 2d."""
    seconds = max(seconds, 0)
    for span, unit in ((86400, 'd'), (3600, 'h'), (60, 'm')):
        if seconds >= span:
            return f'{int(seconds // span)}{unit}'
    return 'now'


def last_replies(hook_dir, listed, now):
    """Gives each session the age of its last reply ('' with none) and, while that reply is newer
    than LAST_LINE_WITHIN, its line for the row to carry under it. Read from the session's own
    feed, not the pane's, which a busier session can push a quiet one's replies out of."""
    for s in listed:
        own = feed_entries(os.path.join(hook_dir, s['id'] + '.feed'))
        e = max(own, key=lambda r: r['at'], default=None)
        s['age'], s['last'] = '', ''
        if e:
            s['age'] = age_text(now - e['at'])
            if now - e['at'] < LAST_LINE_WITHIN:
                s['last'] = display_text(e['text'] or e['markdown'])


def git_paths(cwd):
    """(top, git folder, config) of the repository cwd is in, or None outside one. A worktree's
    .git is a file pointing at its own folder in the main checkout's .git, which holds its
    HEAD, while the config is the main checkout's."""
    d = os.path.abspath(cwd) if cwd else ''
    while d and d != os.path.dirname(d):
        git = os.path.join(d, '.git')
        if os.path.exists(git):
            break
        d = os.path.dirname(d)
    else:
        return None
    top, config = d, os.path.join(git, 'config')
    if os.path.isfile(git):
        m = re.match(r'gitdir:\s*(.+)', _read(git) or '')
        if m:
            git = os.path.join(d, m.group(1).strip())      # relative to the worktree, when it is
            common = (_read(os.path.join(git, 'commondir')) or '').strip()
            main = os.path.normpath(os.path.join(git, common)) if common else git
            config, top = os.path.join(main, 'config'), os.path.dirname(main)
    return top, git, config


def origin_url(config):
    m = re.search(r'\[remote "origin"\][^\[]*?^\s*url\s*=\s*(\S+)', _read(config) or '', re.M)
    return m.group(1).rstrip('/') if m else ''


def repo_name(cwd):
    """The GitHub name of the repository cwd is in: the last part of its origin remote's URL,
    or the checkout's folder name without one. '' outside a repository."""
    paths = git_paths(cwd)
    if not paths:
        return ''
    url = origin_url(paths[2])
    name = re.sub(r'\.git$', '', url.rsplit('/', 1)[-1].rsplit(':', 1)[-1]) if url else ''
    return name or os.path.basename(paths[0])


_git = {}


def session_branch(cwd):
    """(branch, GitHub owner/repo) of the session in cwd, each '' when it has none. Where its
    repository is, and its origin, are found once; HEAD is read each time, as it switches."""
    if cwd not in _git:
        paths = git_paths(cwd)
        repo = paths and re.search(r'github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?$', origin_url(paths[2]))
        _git[cwd] = (paths[1] if paths else '', repo.group(1) if repo else '')
    gitdir, repo = _git[cwd]
    m = re.match(r'ref:\s*refs/heads/(\S+)', _read(os.path.join(gitdir, 'HEAD')) or '') if gitdir else None
    return (m.group(1) if m else ''), repo


def session_issue(branch, repo):
    """The link of the issue a session on `branch` of GitHub's `repo` works: the N of the
    branch's issue-<N>, as /implement names branches; '' without one."""
    m = re.search(r'\bissue-(\d+)\b', branch)
    return f'https://github.com/{repo}/issues/{m.group(1)}' if m and repo else ''


_repos = {}


def session_repo(cwd):
    """The repository name shown at the left of a session's row: its origin remote's, or its
    checkout's folder."""
    if cwd not in _repos:
        _repos[cwd] = display_text(repo_name(cwd))
    return _repos[cwd]


def repo_issues(listed):
    """Gives each session the issues of its GitHub repository that the listed sessions work, as
    [(number text, link)] in number order: the issue a branch names is one, and a repository
    with two sessions on it lists both, on each."""
    found = {}
    for s in listed:
        m = re.search(r'/issues/(\d+)$', s.get('issue') or '')
        if m:
            found.setdefault(s['github'], set()).add(int(m.group(1)))
    for s in listed:
        s['issues'] = [(f'#{n}', f"https://github.com/{s['github']}/issues/{n}")
                       for n in sorted(found.get(s['github'], ()))]


def read_state(hook_dir=None, sessions_dir=None, proc_dir=None, ledgers=None, now=None):
    """Everything the widget shows, from the files alone."""
    hook_dir = hook_dir or HOOK_DIR
    proc = proc_dir or '/proc'
    now = time.time() if now is None else now
    listed = []
    open_sessions = sessions_mod.list_sessions(sessions_dir, proc_dir, hook_dir)
    waits = process_waits({s['pid'] for s in open_sessions}, proc)
    for s in open_sessions:
        if s['spare']:
            continue                                            # a background job kept ready, with no work yet, is not listed
        ledger = ledger_rows(s['id'], ledgers)
        branch = session_branch(s['cwd'])
        listed.append(dict(s, question=s['needs_input'],        # a session blocked on input in the CLI is under Needs input
                           waiting=first_wait(waits.get(s['pid']), waiting_on(ledger)),
                           issue=session_issue(*branch), branch=branch[0], prs=ledger_prs(ledger),
                           repo=session_repo(s['cwd']), github=branch[1]))
    repo_issues(listed)
    replies = feed(hook_dir, listed)
    last_replies(hook_dir, listed, now)
    return {'sessions': listed, 'feed': replies}


# Layout ----------------------------------------------------------------------------------

def scale():
    out = subprocess.run(['xrdb', '-query'], capture_output=True, text=True).stdout
    m = re.search(r'Xft\.dpi:\s*(\d+)', out)
    return round(int(m.group(1)) / 96) if m else 1


SCALE = scale()


def write_atomic(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f'{path}.{os.getpid()}.tmp'
    with open(tmp, 'w') as f:
        f.write(text)
    os.replace(tmp, path)


def box(cx, cy, half_w, half_h):
    return [cx - half_w, cy - half_h, cx + half_w, cy + half_h]


def session_line(s, span=1, header=''):
    """sessions.txt's line for a session: id, the age of its last reply, flags, name, its
    repository's name, how many rows it takes, its section's title when this session is the
    first listed under it, which draw.lua prints on a row above it, the "In review" label
    of a session with a pull request open, which draw.lua prints in place of the repository,
    and the line of its last reply, which draw.lua prints on a row under its name."""
    return '\t'.join((s['id'], s.get('age', ''), row_flags(s), display_text(s['name']), s.get('repo', ''),
                      str(span), header, review_label(s), s.get('last', '')))


def row_flags(s):
    """A session's one tag, the first that holds: a question waiting, then busy, waiting (on
    tests, a unit, ci or a merge), else idle."""
    wait = s.get('waiting')
    return next(f for f, on in (('question', s.get('question')), ('busy', s['busy']),
                                (f'waiting: {wait}', wait),
                                ('idle', True)) if on)


_wrapped = {}


def wrap_lines(text, font, width):
    """`text` broken at spaces into lines of `font` that fit `width`, every word kept; a word
    wider than `width` is broken across lines."""
    key = (text, font, width, text_scale)
    if key not in _wrapped:
        if len(_wrapped) > 32:
            _wrapped.clear()
        out, line = [], ''
        for word in text.split():
            trial = f'{line} {word}'.strip()
            if text_width(trial, font) <= width:
                line = trial
                continue
            if line:
                out.append(line)
            while text_width(word, font) > width and len(word) > 1:
                cut = len(word) - 1
                while cut > 1 and text_width(word[:cut], font) > width:
                    cut -= 1
                out.append(word[:cut])
                word = word[cut:]
            line = word
        if line:
            out.append(line)
        _wrapped[key] = out
    return _wrapped[key]


def clean_markdown(text):
    """A line's markdown source as the hook publishes it in now.json, or '' without one: format
    characters dropped as display_text does, newlines kept, cut at MARKDOWN_MAX."""
    if not isinstance(text, str):
        return ''
    text = ''.join(c for c in text if c in '\n\t' or unicodedata.category(c) != 'Cf')
    return text.replace('\r', '')[:MARKDOWN_MAX].strip()


INLINE = re.compile(r'(?P<code>`+)(?P<c>.+?)(?P=code)|\*\*(?P<b>.+?)\*\*|__(?P<b2>.+?)__'
                    r'|\*(?P<i>[^\s*][^*]*?)\*|(?<![\w])_(?P<i2>[^\s_][^_]*?)_(?![\w])|\[(?P<l>[^\]]+)\]\([^)]*\)', re.S)


def inline_runs(text, style=''):
    """[(text, style)] for markdown's inline marks: `code` ('c'), **bold** ('b'), *italic* ('i'), both
    ('x'), and a [link](url) as its label; anything else is kept as written."""
    runs, at = [], 0
    for m in INLINE.finditer(text):
        if m.start() > at:
            runs.append((text[at:m.start()], style))
        at = m.end()
        if m.group('c') is not None:
            runs.append((m.group('c'), 'c'))
        elif m.group('b') is not None or m.group('b2') is not None:
            runs += inline_runs(m.group('b') or m.group('b2'), 'x' if style in ('i', 'x') else 'b')
        elif m.group('i') is not None or m.group('i2') is not None:
            runs += inline_runs(m.group('i') or m.group('i2'), 'x' if style in ('b', 'x') else 'i')
        else:
            runs += inline_runs(m.group('l'), style)
    if at < len(text):
        runs.append((text[at:], style))
    return runs


BULLET = re.compile(r'^(\s*)([-*+]|\d+[.)])\s+(.*)$')


def markdown_blocks(markdown):
    """[(kind, marker, runs)] for the blocks of `markdown`: 'p' a paragraph, 'h' a heading (its
    runs bold), 'li' a list item (its bullet or number the marker, led by two spaces a level), 'q'
    a line of a block quote, 'tbl' a table (its runs the rows of cell texts, the separator row
    left out), 'hr' a horizontal rule, 'tag' a fence's language tag (one dim run) and 'code' a line
    of a fenced block (one run, kept as written). Consecutive lines of a paragraph join."""
    blocks, para, fenced, table, quote = [], [], False, [], []

    def flush():
        if table:                                     # a paragraph that is still open came after the table
            rows = [[c.strip() for c in r.strip().strip('|').split('|')] for r in table
                    if not re.fullmatch(r'\s*\|?[\s:|-]+\|[\s:|-]*', r)]
            blocks.append(('tbl', '', rows))
            table.clear()
        if para:
            blocks.append(('p', '', inline_runs(' '.join(para))))
            para.clear()
        if quote:
            blocks.append(('q', '', inline_runs(' '.join(quote))))
            quote.clear()
    for line in markdown.split('\n'):
        if line.strip().startswith('```'):
            flush()
            fenced = not fenced
            if fenced and line.strip()[3:].strip():
                blocks.append(('tag', '', [(line.strip()[3:].strip(), 'd')]))
        elif fenced:
            blocks.append(('code', '', [(line.rstrip(), 'c')]))
        elif line.strip().startswith('|') and line.count('|') >= 2:
            if para or quote:
                flush()
            table.append(line)
        elif not line.strip():
            flush()
        elif re.fullmatch(r'\s*([-*_]\s*){3,}', line):
            flush()
            blocks.append(('hr', '', []))
        elif re.match(r'\s*#{1,6}\s', line):
            flush()
            blocks.append(('h', '', [(t, 'x' if st in ('i', 'x') else 'b') for t, st in
                                    inline_runs(re.sub(r'^\s*#{1,6}\s+|\s+#+\s*$', '', line))]))
        elif m := BULLET.match(line):
            flush()
            level = len(m.group(1).expandtabs(2)) // 2
            bullet = ('\u2022' if level == 0 else '\u2219') if m.group(2) in '-*+' else m.group(2)
            blocks.append(('li', '  ' * level + bullet, inline_runs(m.group(3))))
        elif re.match(r'\s*>', line):
            text = re.sub(r'^\s*>\s?', '', line).strip()
            if text:
                if para or table:
                    flush()
                quote.append(text)
            else:
                flush()                               # a lone ">" ends the quote's paragraph
        else:
            if quote:
                flush()
            para.append(line.strip())
    flush()
    return blocks


def wrap_runs(runs, width, first='', rest=''):
    """`runs` ([(text, style)]) broken at spaces into lines that fit `width` in the style's own
    font, as lists of runs, each line after the first opening with the spaces of `rest` and the
    first with `first`; a word wider than `width` is broken across lines."""
    sp = text_width('a a', TERM_FONT) - text_width('aa', TERM_FONT)
    tokens, gap = [], False                              # (text, style, a space before it)
    for text, style in runs:
        for part in re.findall(r'\s+|\S+', text):
            if part.isspace():
                gap = True
            else:
                tokens.append((part, style, gap))
                gap = False
    lines, cur, w = [], [], 0.0
    lead = first

    def width_of(text, style):
        return text_width(text, STYLE_FONTS[style])
    for text, style, spaced in tokens:
        tw = width_of(text, style)
        lead_w = width_of(lead, '') if not cur and lead else 0
        add = (sp if spaced and cur else 0) + tw
        if cur and w + add > width:
            lines.append(cur)
            cur, w, lead = [], 0.0, rest
            lead_w = width_of(lead, '') if lead else 0
            add = tw
        if not cur:
            w = lead_w
            if lead:
                cur.append((lead, ''))
        elif spaced:
            cur.append((' ', ''))
        while w + add > width and len(text) > 1:        # a word wider than the line is broken
            cut = len(text) - 1
            while cut > 1 and w + width_of(text[:cut], style) > width:
                cut -= 1
            cur.append((text[:cut], style))
            lines.append(cur)
            text, cur, lead = text[cut:], [], rest
            w = width_of(lead, '') if lead else 0
            if lead:
                cur.append((lead, ''))
            add = width_of(text, style)
        cur.append((text, style))
        w += add
    if cur:
        lines.append(cur)
    return lines


def markdown_lines(markdown, width, indent=TERM_INDENT):
    """[(draw.txt text, pixel width)] for the visual lines of `markdown` wrapped to `width`, each
    opening with `indent`: a list item's lines hang under its first word, a quote's lines follow
    a dim bar, a table is drawn in box characters with its widest columns cut with an ellipsis
    when it is wider than the pane, a rule is a dim line across the pane, a code line wraps like text, each
    of its lines opening with BAND_MARK, and a blank line sits between blocks. A line with only
    plain text is its text; one with styled runs has STYLE_MARK, a style letter and the text
    before each run."""
    out, prev = [], None
    cw = text_width(' ', TERM_FONT)
    chars = int((width - text_width(indent, TERM_FONT)) / cw)

    def cut(text, n):
        return text if len(text) <= n else text[:max(n - 1, 0)] + '\u2026'
    for kind, marker, runs in markdown_blocks(markdown):
        if prev and (kind != 'li' or prev != 'li') and not (kind in ('code', 'tag') and prev in ('code', 'tag')):
            out.append([(indent, '')] if indent else [])
        prev = kind
        if kind == 'tbl':
            cols = max(len(r) for r in runs)
            rows = [[''.join(t for t, _ in inline_runs(c)) for c in r] + [''] * (cols - len(r)) for r in runs]
            ws = [max(len(r[i]) for r in rows) for i in range(cols)]
            while sum(ws) + 3 * cols + 1 > chars and max(ws) > 2:      # too wide: the widest column is cut
                ws[ws.index(max(ws))] -= 1

            def rule(l, m, r):
                return [(indent, ''), (l + m.join('\u2500' * (w + 2) for w in ws) + r, 'd')]

            def row(cells, style):
                line = [(indent, ''), ('\u2502', 'd')]
                for c, w in zip(cells, ws):
                    c = cut(c, w)
                    line += [(' ' + c + ' ' * (w - len(c) + 1), style), ('\u2502', 'd')]
                return line
            out.append(rule('\u250c', '\u252c', '\u2510'))
            out.append(row(rows[0], 'b'))
            if len(rows) > 1:
                out.append(rule('\u251c', '\u253c', '\u2524'))
            out += [row(r, '') for r in rows[1:]]
            out.append(rule('\u2514', '\u2534', '\u2518'))
        elif kind == 'hr':
            out.append([(indent, ''), ('\u2500' * int((width * BLOCK_SLACK - text_width(indent, TERM_FONT)) / cw), 'd')])
        elif kind == 'tag':
            out.append([(BAND_MARK, ''), (indent + '  ', ''), runs[0]])
        elif kind == 'q':
            for line in wrap_runs(runs, width - text_width(indent + '\u2502 ', TERM_FONT)):
                out.append([(indent, ''), ('\u2502 ', 'd')] + line)
        elif kind == 'code':
            first = indent + '  '
            if runs[0][0].strip():
                out += [[(BAND_MARK, '')] + line for line in wrap_runs(runs, width, first, first)]
            else:
                out.append([(BAND_MARK, ''), (first, '')])
        else:
            first = indent + (marker + ' ' if kind == 'li' else '')
            rest = ' ' * max(round(text_width(first, TERM_FONT) / max(text_width(' ', TERM_FONT), 1)), 0)
            out += wrap_runs(runs, width, first, rest)
    res = []
    for r in out:
        band = bool(r) and r[0] == (BAND_MARK, '')
        r = r[1:] if band else r
        res.append(((BAND_MARK if band else '') + encode_runs(r), sum(text_width(t, STYLE_FONTS[st]) for t, st in tidy_runs(r))))
    return res


def tidy_runs(runs):
    """`runs` with a lone space between two runs of one style taking that style, so a bold phrase
    or a code span is one run, and neighbours of one style joined."""
    runs = [(t, st) for t, st in runs if t]
    for i in range(1, len(runs) - 1):
        if runs[i] == (' ', '') and runs[i - 1][1] == runs[i + 1][1]:
            runs[i] = (' ', runs[i - 1][1])
    out = []
    for text, style in runs:
        if out and out[-1][1] == style:
            out[-1] = (out[-1][0] + text, style)
        else:
            out.append((text, style))
    return out


def encode_runs(runs):
    """One draw.txt line's text for `runs`."""
    runs = tidy_runs(runs)
    if all(not style for _, style in runs):
        return ''.join(text for text, _ in runs)
    return ''.join(STYLE_MARK + (style or 'n') + text for text, style in runs)


STATUS_GROUPS = ('Needs input', 'Working', 'Completed')   # the sessions column's sections, in order, as the CLI names its session states


def in_review(s):
    """Whether a session that is not working has a pull request open, which waits on the user."""
    return bool(s.get('prs')) and row_flags(s) not in ('question', 'busy')


def review_label(s):
    """"In review · Repo #151, #152" for a session in review, else ''."""
    if not in_review(s):
        return ''
    numbers = ', '.join('#' + url.rstrip('/').rsplit('/', 1)[-1] for url in s['prs'])
    return f"In review \u00b7 {s['repo']} {numbers}" if s.get('repo') else f'In review {numbers}'


def status_group(s):
    """The section a session is listed under: Needs input while a question waits to be read or
    the CLI waits on input, or a pull request is open for the user to review; Completed while it
    is idle with none; else Working, which holds busy and waiting ones."""
    tag = row_flags(s)
    if tag == 'question' or in_review(s):
        return 'Needs input'
    return 'Completed' if tag == 'idle' else 'Working'


def grouped(listed):
    """`listed` with the sessions of one section together, in STATUS_GROUPS' order, and each
    section's sessions in their order."""
    return sorted(listed, key=lambda sess: STATUS_GROUPS.index(status_group(sess)))


def name_left():
    """Where a session's name begins along its row, indented under its repository's name."""
    return MARGIN + GROUP_PAD + SESSION_INDENT


def name_span(s, right):
    """Where a session's name sits on its name line, as draw.lua lays it out, ending at `right`,
    the gear's left edge: [left, right], the area a click on it asks to close the session."""
    name_x = name_left()
    name = fit(display_text(s['name']), LIST_FONT, (right - name_x) / BLOCK_SLACK)
    return [round(name_x - 4, 2), round(name_x + text_width(name, LIST_FONT) * BLOCK_SLACK + 4, 2)]


def write_sessions(listed, layout):
    """sessions.txt, rewritten only when it changes; its version is what draw.txt names.
    `layout` is a (span, header) for each session."""
    text = ''.join(session_line(s, *l) + '\n' for s, l in zip(listed, layout))
    version = hashlib.sha1(text.encode()).hexdigest()[:10]
    if _read(SESSIONS) != text:
        write_atomic(SESSIONS, text)
    return version


def collapse_idle():
    return (_read(COLLAPSE) or '').strip() == 'on'


def load_split():
    """The sessions column's share of the width inside the gap, 0 to 1, from the SPLIT file the
    divider's drag writes; SPLIT_DEFAULT when it is missing or bad."""
    try:
        with open(SPLIT) as f:
            v = float(f.read().split()[0])
    except (OSError, IndexError, ValueError):
        return SPLIT_DEFAULT
    return min(max(v, 0.0), 1.0) if v == v else SPLIT_DEFAULT


def split_limits(avail):
    """(least, most) share of `avail`, the width inside the gap, the sessions column may take:
    each column keeps its minimum, or half the width where both cannot."""
    low = min(LIST_MIN / avail, 0.5)
    return low, max(1 - TERM_MIN / avail, 0.5)


_message_lines = {}


def meta_segments(sess):
    """[(text, what a click on it opens or None)] for the "[ Issue #1, #2 | PR #3 ]" a session's
    messages carry after the speaker's name: its repository's issue numbers and its pull
    requests' numbers, each number a link ({'id', 'issue': the URL}). No issue and no pull
    request, or a session no longer open, gives none."""
    if not sess:
        return []
    groups = []
    issues = [(text, {'id': sess['id'], 'issue': link}) for text, link in sess.get('issues', ())]
    prs = [('#' + url.rstrip('/').rsplit('/', 1)[-1], {'id': sess['id'], 'issue': url}) for url in sess.get('prs') or ()]
    for label, numbers in (('Issue', issues), ('PR', prs)):
        if numbers:
            groups.append((label, numbers))
    if not groups:
        return []
    out = [('[ ', None)]
    for g, (label, numbers) in enumerate(groups):
        out.append((('' if g == 0 else ' | ') + label + ' ', None))
        for n, number in enumerate(numbers):
            out += ([(', ', None)] if n else []) + [number]
    return out + [(' ]', None)]


def message_lines(entry, width, segments=(), header=True):
    """draw.txt's lines for one printed message, wrapped to `width`, as the CLI prints a turn: the
    speaker's name as the prompt with the session's issue and pull request numbers
    (`segments`, meta_segments') right-aligned on it, a blank line, the text behind a bullet (its
    markdown formatted when the hook published it), a blank line, and a closing line with when
    it was replied. The prompt line and the blank after it are left out when `header`
    is false, for a message from the session the one before it was from. Kept until the width, the text scale or the message changes,
    since a scrollback of them is laid out four times a second."""
    key = (entry['key'], entry['name'], width, text_scale, header, tuple((t, bool(i)) for t, i in segments))
    if key not in _message_lines:
        if len(_message_lines) > 4 * SCROLLBACK_KEEP:
            _message_lines.clear()
        if entry.get('markdown'):
            body = [line for line, _ in markdown_lines(entry['markdown'], width)]
        else:
            body = [TERM_INDENT + l for l in wrap_lines(entry.get('text') or '', TERM_FONT,
                                                         width - text_width(TERM_INDENT, TERM_FONT))]
        if body:
            body[0] = BULLET_MARK + body[0]
        done = 'Replied'
        if entry.get('at'):
            done += ' \u00b7 ' + datetime.datetime.fromtimestamp(entry['at']).strftime('%A %-I:%M %p')
        cw = text_width(' ', TERM_FONT)
        meta_w = sum(text_width(t, TERM_FONT) for t, _ in segments) + (2 * cw if segments else 0)
        name = fit(entry['name'], TERM_FONT, width - 2 * cw - meta_w)
        prompt = PROMPT_MARK + name + ''.join(META_MARK + ('k' if info else 'n') + t for t, info in segments)
        _message_lines[key] = (([prompt, ''] if header else []) + body
                               + ['', DONE_MARK + fit(done, TERM_FONT, width - 2 * cw)])
    return _message_lines[key]


def render(state):
    """widget.txt's markup for `state` (read_state's); writes draw.txt, regions.json and
    sessions.txt beside it."""
    global widget_width, list_height, text_scale
    widget_width, list_height, text_scale = size_file.load(SIZE)
    listed = state['sessions']
    right = MARGIN + widget_width
    idle = not any(s['busy'] or s['question'] for s in listed)

    # The top row: the widget's title, then minimize and close at the top right. The title is
    # drawn by draw.lua, which spaces its letters; the row is a gap here.
    close_cx = right - WINDOW_BUTTON_SIZE / 2
    min_cx = close_cx - WINDOW_BUTTON_PITCH
    header_h = line_height(LABEL_FONT, PLAIN_FONT)
    cy = MARGIN + header_h / 2
    text_right = min_cx - WINDOW_BUTTON_PITCH / 2 - TITLE_GAP
    em = font_description(LABEL_FONT).get_size() / Pango.SCALE * 96 / 72      # px
    title = TITLE.upper()
    title = fit(title, LABEL_FONT, (text_right - MARGIN - TITLE_TRACK * em * len(title)) / BLOCK_SLACK)
    half = WINDOW_BUTTON_PITCH / 2
    regions = {
        'minimize': box(min_cx, cy, half, half),
        'close': [close_cx - half, cy - half, close_cx + half + 12, cy + half],
    }
    draw = [f'scale {SCALE} {text_scale:g}', f'shadow {SHADOW}',
            f'window {min_cx} {close_cx} {cy} {WINDOW_BUTTON_SIZE}',
            f'title {MARGIN} {cy} {TITLE_TRACK} {title}']
    out = Markup(MARGIN)
    out.gap(header_h)

    if idle and collapse_idle():
        out.gap(HEADER_GAP)
        write_atomic(DRAW, '\n'.join(draw) + '\n')
        write_atomic(REGIONS, json.dumps(regions))
        write_sessions(listed, [(1, "")] * len(listed))
        return out.end(out.y + MARGIN - 4)

    # Sessions: drawn by draw.lua from sessions.txt, scrolled by the wheel when they run longer
    # than the list's height.
    # Two columns of the same height: the sessions at the left, the terminal pane at the right,
    # the divider between them in the gap, where the drag moves it.
    avail = right - MARGIN - COLUMN_GAP
    low, high = split_limits(avail)
    list_right = MARGIN + round(avail * min(max(load_split(), low), high))
    term_left = list_right + COLUMN_GAP
    # One column, set as the CLI sets its session list: a section for each state it names (needs
    # input, working, completed) with its sessions under it, one line each.
    listed = grouped(listed)
    row_right = list_right - GROUP_PAD                         # where a row ends, with the age of its last reply
    out.gap(LINE_GAP)
    list_top = out.y
    row = line_height(LIST_FONT) + ROW_SPACING * text_scale
    rows_fit = list_height / row
    count = len(listed)
    layout, spans, heads, section = [], [], [], None
    for s in listed:
        header = status_group(s) if status_group(s) != section else ''
        # a section's title takes a row, and a blank row above it except for the first section
        head_rows = (1 if section is None else 2) if header else 0
        section = status_group(s)
        span = 1 + head_rows + bool(s['last'])                  # the session's line, one row, the title above and its last reply under
        layout.append((span, header))
        spans.append(span)
        heads.append(head_rows * row)
    last = max(0, round(sum(spans) - rows_fit + 0.4999))
    version = write_sessions(listed, layout)
    draw.append(f'list {MARGIN} {list_right} {list_top} {row:.2f} {list_height} {version} {count} '
                f'{last}')
    draw.append(f'control {list_right} {row_right:.2f}')
    draw.append(f'block {GROUP_PAD} {SESSION_INDENT}')
    rows, top = [], 0.0
    for s, (span, _), head in zip(listed, layout, heads):
        entry = {'id': s['id'], 'top': round(top, 2), 'bottom': round(top + row * span, 2), 'head': round(head, 2)}
        # The name closes the session, once confirmed
        entry.update(name=name_span(s, row_right), title=display_text(s['name']), pid=s['pid'], busy=bool(s['busy']))
        rows.append(entry)
        top += row * span
    regions['list'] = [MARGIN, list_top, list_right, list_top + list_height]
    # The divider's grab area is over the gap, the card's whole height; `divider_drag` is what the drag
    # needs to turn the pointer's x into the share: [left of the columns, their width inside the
    # gap, the gap, least share, most share]
    divider_x = list_right + COLUMN_GAP / 2
    regions['divider_drag'] = [MARGIN, avail, COLUMN_GAP, round(low, 4), round(high, 4)]
    regions['rows'] = rows
    regions['list_scroll'] = [last, round(row, 2)]
    prompt_line, regions['confirm'] = close_prompt(right, list_top, list_height)
    draw.append(prompt_line)
    # The terminal pane, as Claude's CLI prints a reply: a bordered box with a static title on its
    # border, the replies of the listed sessions inside it, each behind a bullet (its markdown
    # formatted, in monospace; as many lines show as the column holds and draw.lua scrolls the
    # rest). It is as tall as the sessions column. draw.lua draws it from these lines.
    line_h = line_height(TERM_FONT)
    box_top = list_top
    bottom = list_top + list_height
    banner_h = (TERM_BANNER_LINES + 1) * line_h                    # the welcome banner and a blank line
    term_lines = max(int((bottom - box_top - 2 * TERM_PAD - banner_h) // line_h), 1)
    inner = (right - term_left - 2 * TERM_PAD) / BLOCK_SLACK    # draw.lua's text runs wider
    said, links = [], {}
    open_by_id = {x['id']: x for x in listed}
    previous = None
    for entry in state['feed']:
        if said:
            said.append('')                                    # a blank line between messages
        header = entry.get('session') != previous              # the speaker's name only when the speaker changes
        previous = entry.get('session')
        segments = meta_segments(open_by_id.get(entry.get('session')))
        if header and segments:                                # what each number in this prompt line opens
            links[str(len(said))] = [info for _, info in segments if info]
        said.extend(message_lines(entry, inner, segments, header))
    regions['terminal_links'] = links
    draw.append(f'terminal {term_left} {box_top:.2f} {right} {bottom:.2f} {TERM_PAD} '
                f'{box_top + TERM_PAD + line_h / 2:.2f} {box_top + TERM_PAD + banner_h + line_h / 2:.2f} {line_h:.2f} '
                f'{term_lines} {count}')
    draw.append(f'speaker {fit(TERM_TITLE, LABEL_FONT, right - term_left - 40)}')
    draw.extend(f'line {line}' for line in said)
    regions['terminal'] = [term_left, round(box_top, 2), right, round(bottom, 2)]
    regions['terminal_scroll'] = max(len(said) - term_lines, 0)       # lines past what it shows
    out.gap(list_height)
    card_h = out.y + MARGIN - 4
    # The application's chrome: the header runs the card's width with a rule under it, and the
    # divider runs from that rule to the card's bottom.
    rule_top = list_top - LINE_GAP / 2
    draw.append(f'divider {divider_x:.2f} {rule_top:.2f} {card_h:.2f}')
    draw.append(f'rules {rule_top:.2f}')
    regions['divider'] = [list_right + 2, round(rule_top, 2), term_left - 2, round(card_h, 2)]
    write_atomic(DRAW, '\n'.join(draw) + '\n')
    write_atomic(REGIONS, json.dumps(regions))
    return out.end(card_h)


def close_prompt(right, list_top, list_height):
    """(draw.txt's line, regions.json's entry) for the "Are you sure?" prompt a click on a
    session's name opens: a panel centred over the list, `right` being the list's right edge,
    with its title and one line of explanation above Cancel and OK at its right. The names in
    it come from conky-mouse.py's close-confirm file; draw.lua draws it only while that exists."""
    title_h, msg_h = line_height(LABEL_FONT), line_height(TAG_FONT)
    button_h = title_h + 8 * text_scale
    height = 2 * CONFIRM_PAD + title_h + msg_h + CONFIRM_GAP + button_h + CONFIRM_GAP
    width = min(right - MARGIN, CONFIRM_W)
    x0 = (MARGIN + right - width) / 2
    x1 = x0 + width
    top = max(MARGIN, list_top + list_height / 2 - height / 2)
    title_cy = top + CONFIRM_PAD + title_h / 2
    msg_cy = top + CONFIRM_PAD + title_h + msg_h / 2
    button_cy = top + height - CONFIRM_PAD - button_h / 2
    ok_x0 = x1 - CONFIRM_PAD - text_width('OK', LABEL_FONT) - 2 * CONFIRM_BUTTON_PAD
    cancel_x1 = ok_x0 - CONFIRM_GAP
    cancel_x0 = cancel_x1 - text_width('Cancel', LABEL_FONT) - 2 * CONFIRM_BUTTON_PAD
    ok, cancel = [ok_x0, x1 - CONFIRM_PAD], [cancel_x0, cancel_x1]
    line = (f'confirm {x0:.2f} {top:.2f} {x1:.2f} {top + height:.2f} {title_cy:.2f} {msg_cy:.2f} '
            f'{button_cy:.2f} {button_h:.2f} {cancel_x0:.2f} {cancel_x1:.2f} {ok[0]:.2f} {ok[1]:.2f} '
            f'{MARGIN} {list_top} {right} {list_top + list_height}')
    half = button_h / 2
    entry = {'box': [round(x0, 2), round(top, 2), round(x1, 2), round(top + height, 2)],
             'ok': [round(ok[0], 2), round(button_cy - half, 2), round(ok[1], 2), round(button_cy + half, 2)],
             'cancel': [round(cancel[0], 2), round(button_cy - half, 2), round(cancel[1], 2),
                        round(button_cy + half, 2)]}
    return line, entry


def message(text):
    """A line of text in place of the widget, for when render() itself fails."""
    write_atomic(DRAW, f'scale {SCALE} {text_scale:g}\nshadow {SHADOW}\n')
    write_atomic(REGIONS, '{}')
    out = Markup(MARGIN)
    out.text(f"${{goto {SHADOW + MARGIN}}}${{lua_parse fg text}}${{font {conky_font(ROW_FONT)}}}{esc(text)}{plain()}",
             line_height(ROW_FONT, PLAIN_FONT))
    return out.end(out.y + MARGIN)


def hold_instance_lock():
    """One copy reads the state and writes the cache; a second one waits for the first."""
    os.makedirs(CACHE, exist_ok=True)
    lock = open(INSTANCE_LOCK, 'a+')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log(f'another copy is running; pid {os.getpid()} waits for it to exit')
        fcntl.flock(lock, fcntl.LOCK_EX)
    lock.truncate(0)
    lock.write(str(os.getpid()))
    lock.flush()
    return lock


def main():
    lock = hold_instance_lock()  # noqa: F841  (held until the process exits)
    last_error = None
    while True:
        try:
            text = render(read_state())
            last_error = None
        except Exception as e:
            if str(e) != last_error:
                log(f'render failed: {type(e).__name__}: {e}')
                last_error = str(e)
            try:
                text = message(f'widget error: {str(e)[:60]}')
            except Exception:
                text = f"${{lua_parse fg text}}${{font Ubuntu Sans:size=11}}widget error: {esc(str(e))[:60]}\n"
        write_atomic(OUT, text)
        # Every 0.25 s, or at once when the size settings or the divider change.
        settings = size_file.load(SIZE), load_split()
        for _ in range(5):
            time.sleep(0.05)
            if (size_file.load(SIZE), load_split()) != settings:
                break


if __name__ == '__main__':
    main()
