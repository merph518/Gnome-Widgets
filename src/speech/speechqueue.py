#!/usr/bin/env python3
"""Builds the speech widget's contents: what is being read aloud and what waits behind it.

Four times a second this reads, and only reads:
  - the open Claude sessions, from ~/.claude/sessions/<pid>.json (sessions.py), the
    processes under each in /proc (a test run, or a wait on a systemd unit) and its
    catchup.py ledgers
  - the speaking hook's state in $XDG_RUNTIME_DIR/speak-attention/: now.json while a clip
    plays, <session>.queue (a line per block still to read), <session>.name, <session>.replies
    (speech on) and <session>.muted (speech off), the paused flag and settings.json (voice,
    volume). The .key files beside the session files are never opened.

and writes, under ~/.cache/conky-widgets/speech/, the files the Spotify widget's
nowplaying.py writes for its own card:
  - widget.txt   conky's markup: the sessions' column headers and spacer
                 lines that give conky's window its size, which stays the same while lines play
  - draw.txt     geometry for draw.lua (logical px, from the card's top left): the title, the
                 buttons, the sessions list, the speaker's avatar and the bubble with the line
                 being read, the progress of the current line and the footer
  - regions.json click areas for conky-mouse.py, in the same coordinates
  - sessions.txt the sessions list, a line per session, rewritten only when it changes

Each session has a speech setting, read from its files the way speechctl reads it: On while
<id>.replies exists (its replies are read aloud), Off while <id>.muted exists (nothing
plays), Alerts only with neither (only its announcements play). Sessions with speech on sort
first, then by process id, so the ones being read aloud are at the top.
"""
import fcntl, glob, hashlib, json, math, os, re, subprocess, sys, tempfile, threading, time, unicodedata, wave
import gi
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Pango, PangoCairo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'common'))
import sessions as sessions_mod  # noqa: E402
import widget_size as size_file  # noqa: E402
sys.path.insert(0, os.path.join(HERE, '..'))
import tray_model  # noqa: E402

NAME = 'conky-widgets/speech'
CONF = os.path.expanduser(f'~/.config/{NAME}')
CACHE = os.path.expanduser(f'~/.cache/{NAME}')
OUT = os.path.join(CACHE, 'widget.txt')
DRAW = os.path.join(CACHE, 'draw.txt')
REGIONS = os.path.join(CACHE, 'regions.json')
SESSIONS = os.path.join(CACHE, 'sessions.txt')
LAST = os.path.join(CACHE, 'last-lines.json')     # {session id: the last line read aloud for it}
HEARD = os.path.join(CACHE, 'last-heard.json')    # the last clip's speaker and length, kept on
                                                  # the header and progress bar once it ends
LOG = os.path.join(CACHE, 'speechqueue.log')
INSTANCE_LOCK = os.path.join(CACHE, 'speechqueue.lock')
SIZE = size_file.SPEECH_PATH
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
SPEAK = os.path.join(os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}', 'speak-attention')
DEFAULT_VOICE = 'en_US-amy-medium'                # speechctl's, with no setting
DEFAULT_VOLUME = 1.2

SHADOW = size_file.SHADOW
MARGIN = 16                                   # around the contents
AVATAR_D = 36                                 # the speaker's avatar, left of the bubble
# The avatar's image, the first of these that is there: one the user puts in the widget's own folder,
# else the one shipped beside this file. Without either, draw.lua draws a spark.
AVATAR_IMAGES = (os.path.join(CONF, 'avatar.png'), os.path.join(HERE, 'avatar.png'))
AVATAR_GAP = 12                               # the avatar to the bubble, which its tail points across
BUBBLE_PAD = 10                               # the bubble's edge to its text, on every side
BUBBLE_NAME_GAP = 2                           # the speaker's name to the text under it
BUBBLE_LINES = 6                              # most lines of the text read aloud the bubble shows at once
TITLE = 'Claude Code Session Management'      # the widget's name, drawn in capitals along the top
TITLE_TRACK = 0.09                            # the title's letter spacing, in ems
HEADER_GAP = 6                                # the title to the avatar when collapsed, the bubble to the progress bar's row
LINE_GAP = 14                                 # the title's row to the column headers
PROGRESS_H = 14                               # the progress bar's row
LIST_GAP = 0                                  # the column headers to the list
FOOTER_GAP = 8                                # list to the bubble, and the progress bar's row to the controls
FOOTER_H = 30                                 # the footer row: pause, volume and voice
ROW_SPACING = 6                               # extra space in a session's row
WINDOW_BUTTON_SIZE = 10                       # minimize / close, as the Spotify widget's
WINDOW_BUTTON_PITCH = 22
PAUSE_SIZE = 28                               # the footer's pause/resume circle, and skip and next after it
FOOTER_BUTTON_GAP = 8                         # between the footer's round buttons
DROPDOWN_H = 24                               # the voice drop down's height, at least
DROPDOWN_PAD = 10                             # either side of its label
DROPDOWN_ARROW = 10                           # the arrow's width, after the label
DROPDOWN_GAP = 6                              # label to arrow
MENU_PAD = 4                                  # round the open list's items
CONFIRM_W = 320                               # the close prompt's width, at most
CONFIRM_PAD = 14                              # round its contents
CONFIRM_GAP = 8                               # between its lines, and its two buttons
CONFIRM_BUTTON_PAD = 14                       # either side of a button's label
MENU_GAP = 4                                  # the open list to the footer
MENU_MIN_ROWS = 3                             # rows the open list shows however short the card is
VOICES_EVERY = 10.0                           # s between asking speechctl for the voices
VOLUME_WIDTH = 80                             # the volume slider's track, right of its speaker
VOLUME_ICON = 16                              # the speaker and its waves, left of the track
VOLUME_GAP = 8                                # speaker to track
VOLUME_MIN = 32                               # its shortest track, as the Spotify widget's: the voice drop down keeps its label first
VOLUME_TOP = 2.0                              # speechctl's loudest volume, the track's right end
SEGMENTS = (('on', 'On'), ('alerts', 'Alerts'), ('off', 'Off'))
SEGMENT_PAD = 7                               # either side of a segment's label
PILL_PAD = 6                                  # either side of the pill after a session's name
PILL_GAP = 8                                  # a session's name to its pill
BLOCK_RULE = 2                                # the rule left of a repository's name and issue numbers
BLOCK_PAD = 7                                 # that rule to the text
BLOCK_MIN = 90                                # the text's least width, however short the names are
BLOCK_SLACK = 1.04                            # draw.lua's cairo text runs wider than Pango's, which kerns
CHIP_PAD = 5                                  # left of an issue number, which has nothing right of it
CHIP_GAP = 3                                  # between chips, and between their lines
NOTHING_SAID = 'Nothing read aloud yet'       # an On session's second row before its first line
SPEAKER = re.compile(r'^[^:]{1,120}? session says:\s*')   # the hook's "<name> session says:"
SPACER_FONT = 'Ubuntu Sans 1'
SPACER_HEIGHT = 2                             # what conky adds for that spacer line (measured)
PLAIN_FONT = 'Ubuntu Sans 13'                 # between runs of text; see plain()
LABEL_FONT = 'Ubuntu Sans Bold 11'            # "<name> says:", "Speech idle"
HEADING_FONT = 'Ubuntu Sans Bold 9'           # the column headers over the sessions
ROW_FONT = 'Ubuntu Sans 11'                   # a session's row, as draw.lua draws it
SEGMENT_FONT = 'Ubuntu Sans Bold 9'           # On | Alerts | Off, and a repository's name, as draw.lua draws them
TAG_FONT = 'Ubuntu Sans 9'                    # a row's tag, pill, queued count and issue numbers, as draw.lua draws them
FOOTER_FONT = 'Ubuntu Sans 11'                # Voice: amy, and the open list, as draw.lua draws them
TEXT_FONTS = {PLAIN_FONT, LABEL_FONT, HEADING_FONT, ROW_FONT, SEGMENT_FONT, TAG_FONT, FOOTER_FONT}

_pango = PangoCairo.FontMap.get_default().create_context()
PangoCairo.context_set_resolution(_pango, 96)

widget_width, list_height, text_scale = size_file.SPEECH_DEFAULTS


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


def without_speaker(text):
    """text without the "<name> session says:" the voice hook opens a clip with, for a row that already
    sits under the session's name."""
    return SPEAKER.sub('', text, count=1) or text


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


def link_pill(prs):
    """The pill after a session's name, naming the ready pull requests a click on it opens; ''
    without any, when there is no pill."""
    if not prs:
        return ''
    return f"PR #{prs[0].rsplit('/', 1)[-1]}" if len(prs) == 1 else f'{len(prs)} PRs'


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


# The speaking hook's state ---------------------------------------------------------------

def _read(path):
    try:
        with open(path, encoding='utf-8') as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def _json(path):
    try:
        data = json.loads(_read(path) or '')
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def pid_alive(pid, proc_dir='/proc'):
    """A stopped process is alive, an exited (zombie) one is not."""
    try:
        with open(os.path.join(proc_dir, str(int(pid)), 'stat')) as f:
            return f.read().rsplit(') ', 1)[1].split()[0] != 'Z'
    except (OSError, IndexError, TypeError, ValueError):
        return False


def now_playing(speak, proc_dir='/proc'):
    """now.json while the hook that wrote it is still there, with its mtime as `published`;
    None when nothing plays. A file a killed hook left behind is not removed here: this only
    reads."""
    path = os.path.join(speak, 'now.json')
    n = _json(path)
    if not n or not pid_alive(n.get('hook_pid'), proc_dir):
        return None
    try:
        n['published'] = os.stat(path).st_mtime
    except OSError:
        return None
    return n


def clip_duration(speak, n):
    """The clip's length in seconds, from the WAV Piper rendered for it (<hook pid>.wav),
    once it plays; None when that is not known (Speech Dispatcher, or still rendering)."""
    if n.get('engine') != 'piper' or n.get('player_pid') is None:
        return None
    try:
        with wave.open(os.path.join(speak, f"{int(n['hook_pid'])}.wav"), 'rb') as w:
            rate = w.getframerate()
            return w.getnframes() / rate if rate else None
    except (OSError, EOFError, wave.Error, TypeError, ValueError):
        return None


def queue_lines(path):
    text = _read(path) or ''
    return [line for line in text.split('\n') if line.strip()]


def speech_setting(speak, sid):
    # a session with both markers is read aloud, so it reports on (as speechctl does)
    if os.path.exists(os.path.join(speak, sid + '.replies')):
        return 'on'
    return 'off' if os.path.exists(os.path.join(speak, sid + '.muted')) else 'alerts'


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


def voice_label(voice):
    """A Piper model's speaker: 'en_US-amy-medium' -> 'amy'; another name as it is."""
    m = re.fullmatch(r'[a-z]{2,3}_[A-Za-z]{2,3}-(.+)-(x_low|low|medium|high)', voice)
    return m.group(1) if m else voice


_voices = {'names': [], 'asked': None, 'busy': False}


def installed_voices(now=None):
    """The voices `speechctl voices` lists, asked for in a thread of its own at most every
    VOICES_EVERY seconds, since speechctl can be slow; what the last answer was until the next
    one lands. A failed ask leaves the list as it was."""
    now = time.monotonic() if now is None else now
    asked = _voices['asked']
    if not _voices['busy'] and (asked is None or now - asked >= VOICES_EVERY):
        _voices['busy'], _voices['asked'] = True, now

        def ask():
            try:
                names = tray_model.voices()
                if names:
                    _voices['names'] = names
            finally:
                _voices['busy'] = False
        threading.Thread(target=ask, daemon=True).start()
    return _voices['names']


_last = None


def last_lines(n, live):
    """{session id: the last line read aloud for it}, kept in LAST across restarts: the line
    now.json plays is recorded once it starts, a question excepted (it shows as a tag while it
    waits, and its text is not listed). Sessions no longer open are dropped, unless none is
    listed at all, which is a sessions folder that could not be read as often as it is none."""
    global _last
    if _last is None:
        saved = _json(LAST)
        _last = {str(k): str(v) for k, v in saved.items()} if isinstance(saved, dict) else {}
    last = {k: v for k, v in _last.items() if k in live} if live else dict(_last)
    text = display_text((n or {}).get('text') or '')
    sid = str((n or {}).get('session') or '')
    if sid in live and text and not text.lower().startswith('question:'):
        last[sid] = text
    if last != _last:
        _last = last
        try:
            write_atomic(LAST, json.dumps(last))
        except OSError:
            pass
    return last


_heard = None


def last_heard(n, name, duration):
    """{'name', 'duration'} of the last clip played, kept in HEARD across restarts, so the
    progress bar stays as the last line left it while nothing plays."""
    global _heard
    if _heard is None:
        saved = _json(HEARD)
        _heard = saved if isinstance(saved, dict) else {}
    if n:
        heard = {'name': name or 'A session', 'duration': duration or 0}
        if heard != _heard:
            _heard = heard
            try:
                write_atomic(HEARD, json.dumps(heard))
            except OSError:
                pass
    return _heard


def read_state(speak=None, sessions_dir=None, proc_dir=None, ledgers=None):
    """Everything the widget shows, from the files alone."""
    speak = speak or SPEAK
    proc = proc_dir or '/proc'
    n = now_playing(speak, proc)
    settings = _json(os.path.join(speak, 'settings.json')) or {}
    voice = str(settings.get('voice') or '')
    if not voice:
        model = os.environ.get('SPEAK_PIPER_MODEL', '')
        voice = os.path.basename(model)[:-len('.onnx')] if model.endswith('.onnx') else DEFAULT_VOICE
    try:
        volume = float(settings.get('volume', DEFAULT_VOLUME))
    except (TypeError, ValueError):
        volume = DEFAULT_VOLUME
    listed = []
    open_sessions = sessions_mod.list_sessions(sessions_dir, proc_dir)
    waits = process_waits({s['pid'] for s in open_sessions}, proc)
    said = last_lines(n, {s['id'] for s in open_sessions})
    for s in open_sessions:
        lines = queue_lines(os.path.join(speak, s['id'] + '.queue'))
        # A question waiting to be read out shows as a "question" tag on the row
        question = bool(lines) and display_text(lines[0]).lower().startswith('question:')
        ledger = ledger_rows(s['id'], ledgers)
        git = session_branch(s['cwd'])
        listed.append(dict(s, speech=speech_setting(speak, s['id']), queued=len(lines),
                           question=question,
                           waiting=first_wait(waits.get(s['pid']), waiting_on(ledger)),
                           issue=session_issue(*git), branch=git[0], prs=ledger_prs(ledger),
                           repo=session_repo(s['cwd']), github=git[1],
                           last=said.get(s['id'], ''),
                           speaking=bool(n and n.get('session') == s['id'])))
    listed.sort(key=lambda s: (s['speech'] != 'on', s['pid']))
    repo_issues(listed)
    name = ''
    if n:
        name = display_text(n.get('name') or '') or next(
            (s['name'] for s in listed if s['id'] == n.get('session')), '')
    return {
        'now': n, 'name': name, 'text': display_text((n or {}).get('text') or ''),
        'duration': clip_duration(speak, n) if n else None,
        'paused': os.path.exists(os.path.join(speak, 'paused')),
        'voice': voice, 'volume': round(volume, 1), 'sessions': listed,
    }


class Clock:
    """How far into the current clip playback is: from when the hook published the player's
    pid (now.json's mtime), less the time spent paused, which speechqueue sees four times a
    second."""

    def __init__(self):
        self.clip, self.paused_for, self.last = None, 0.0, None

    def elapsed(self, n, paused, now):
        if not n or n.get('player_pid') is None:
            self.clip, self.paused_for, self.last = None, 0.0, None
            return 0.0
        key = (n.get('clip'), n.get('published'))
        if key != self.clip:
            self.clip, self.paused_for, self.last = key, 0.0, None
        if paused and self.last is not None:
            self.paused_for += now - self.last
        self.last = now
        return max(now - n['published'] - self.paused_for, 0.0)


clock = Clock()


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


def session_line(s, chips=(), span=1):
    """sessions.txt's line for a session: id, speech, speaking, queued, flags, name, its
    repository's name, for a session with speech on its last line read aloud (NOTHING_SAID
    before one), the pill after its name, its issue chips as line:x:width:text (block_chips'),
    and how many rows it takes."""
    return '\t'.join((s['id'], s['speech'], str(int(s['speaking'])), str(s['queued']), row_flags(s),
                      display_text(s['name']), s.get('repo', ''),
                      without_speaker(s.get('last') or NOTHING_SAID) if s['speech'] == 'on' else '',
                      link_pill(s.get('prs')),
                      ' '.join(f'{line}:{x:g}:{w:g}:{text}' for line, x, w, text, _ in chips), str(span)))


def row_flags(s):
    """A session's one tag, the first that holds: a question waiting, then busy, waiting (on
    tests, a unit, ci or a merge), bg, else idle."""
    wait = s.get('waiting')
    return next(f for f, on in (('question', s.get('question')), ('busy', s['busy']),
                                (f'waiting: {wait}', wait), ('bg', s['background']),
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


def block_width(listed):
    """The width of a repository's name and issue numbers, one for every row so the names after
    it line up, as draw.lua draws it: the rule, then text as wide as the longest repository
    name listed, and at least BLOCK_MIN, so no name is cut. BLOCK_SLACK widens the longest name
    to what draw.lua measures, so it is not cut either."""
    names = [math.ceil(text_width(s['repo'], SEGMENT_FONT) * BLOCK_SLACK) for s in listed if s.get('repo')]
    return BLOCK_RULE + BLOCK_PAD + max(max(names, default=0), BLOCK_MIN)


def block_chips(issues, width):
    """[(line, x, width, text, link)] for a session's issue numbers laid left to right, each on
    the next line when it would pass `width`, and how many lines they take."""
    chips, x, line = [], 0, 0
    for text, link in issues:
        w = text_width(text, TAG_FONT) + CHIP_PAD
        if x and x + w > width:
            line, x = line + 1, 0
        chips.append((line, x, w, text, link))
        x += w + CHIP_GAP
    return chips, line + 1 if chips else 0


def block_rows(row):
    """(chips_top, pitch, chip_h) of a repository's block in a session's rows, `row` high: its
    name is centred on the first line, as the session's name is, and the chips follow it."""
    name_h = line_height(SEGMENT_FONT)
    chip_h = line_height(TAG_FONT) + 2
    return row / 2 + name_h / 2 + 1, chip_h + CHIP_GAP, chip_h


def name_left(box_w):
    """Where a session's name begins along its row, after its block, `box_w` wide."""
    return MARGIN + box_w + 8


def name_spans(s, right, box_w):
    """Where a session's name and its pill sit along its row, as draw.lua lays them out between
    its block, `box_w` wide, and `right` (the queued count's right edge): ([left, right] of the name,
    [left, right] of the pill, or None without one). The name's span ends where the pill's
    begins."""
    pill = link_pill(s.get('prs'))
    if s['queued'] > 0:
        right -= text_width(f"{s['queued']} queued", TAG_FONT) + 10
    name_x = name_left(box_w)
    pill_w = text_width(pill, TAG_FONT) + 2 * PILL_PAD + PILL_GAP if pill else 0
    flags_w = text_width(row_flags(s), TAG_FONT) + 8
    name = fit(display_text(s['name']), ROW_FONT, right - name_x - flags_w - pill_w)
    after = name_x + text_width(name, ROW_FONT)
    if not pill:
        return [round(name_x - 4, 2), round(after + 4, 2)], None
    return ([round(name_x - 4, 2), round(after + PILL_GAP / 2, 2)],
            [round(after + PILL_GAP / 2, 2), round(after + pill_w + 4, 2)])


def write_sessions(listed, layout):
    """sessions.txt, rewritten only when it changes; its version is what draw.txt names.
    `layout` is a (chips, span) for each session."""
    text = ''.join(session_line(s, *l) + '\n' for s, l in zip(listed, layout))
    version = hashlib.sha1(text.encode()).hexdigest()[:10]
    if _read(SESSIONS) != text:
        write_atomic(SESSIONS, text)
    return version


def collapse_idle():
    return (_read(COLLAPSE) or '').strip() == 'on'


def render(state, now=None):
    """widget.txt's markup for `state` (read_state's); writes draw.txt, regions.json and
    sessions.txt beside it."""
    global widget_width, list_height, text_scale
    widget_width, list_height, text_scale = size_file.load(SIZE)
    now = time.time() if now is None else now
    n, paused, listed = state['now'], state['paused'], state['sessions']
    right = MARGIN + widget_width
    idle = not n and not any(s['queued'] for s in listed)

    # The top row: the widget's title, then minimize and close at the top right. The title is
    # drawn by draw.lua, which spaces its letters; the row is a gap here.
    close_cx = right - WINDOW_BUTTON_SIZE / 2
    min_cx = close_cx - WINDOW_BUTTON_PITCH
    header_h = line_height(LABEL_FONT, PLAIN_FONT)
    cy = MARGIN + header_h / 2
    text_right = min_cx - WINDOW_BUTTON_PITCH / 2 - 8
    em = font_description(LABEL_FONT).get_size() / Pango.SCALE * 96 / 72      # px
    title = TITLE.upper()
    title = fit(title, LABEL_FONT, (text_right - MARGIN - TITLE_TRACK * em * len(title)) / BLOCK_SLACK)
    heard = last_heard(n, state['name'], state['duration'])
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

    avatar = next((path for path in AVATAR_IMAGES if os.path.isfile(path)), '')

    def avatar_at(top):
        """The speaker's avatar, at the card's left from `top`, drawn by draw.lua from its image."""
        draw.append(f'avatar {MARGIN + AVATAR_D / 2} {top + AVATAR_D / 2} {AVATAR_D} {avatar}'.rstrip())

    if idle and collapse_idle():
        out.gap(HEADER_GAP)
        avatar_at(out.y)
        out.gap(AVATAR_D)
        write_atomic(DRAW, '\n'.join(draw) + '\n')
        write_atomic(REGIONS, json.dumps(regions))
        write_sessions(listed, [((), 1)] * len(listed))
        return out.end(out.y + MARGIN - 4)

    # Sessions: a row each, drawn by draw.lua from sessions.txt, scrolled by the wheel when
    # they run longer than the list's height. A session with speech on always takes two rows,
    # the second its last line read aloud, so the list's layout doesn't change as lines play.
    # Three column headers sit over them, each at the left edge of the column it names: the
    # repository and issue numbers, the name, tag and last line, and the speech setting.
    box_w = block_width(listed)
    text_w = box_w - BLOCK_RULE - BLOCK_PAD
    # The setting's three segments at the right of each row, as wide as their labels
    xs = [right]
    for _, label in reversed(SEGMENTS):
        xs.insert(0, xs[0] - text_width(label, SEGMENT_FONT) - 2 * SEGMENT_PAD * text_scale)
    name_x = name_left(box_w)
    out.gap(LINE_GAP)
    heading_h = line_height(HEADING_FONT, PLAIN_FONT)
    columns = ((MARGIN + BLOCK_RULE + BLOCK_PAD, text_w, 'Identifiers'),
               (name_x, xs[0] - 8 - name_x, 'Session Information'),
               (xs[0], right - xs[0], 'Speech Setting')) if listed else ()
    # a column with no room for even an ellipsis (a narrow card at a large text scale) has no header
    room = text_width('…', HEADING_FONT)
    heads = ''.join(f"${{goto {round(SHADOW + x)}}}{esc(fit(label, HEADING_FONT, width))}"
                    for x, width, label in columns if width >= room)
    out.text(f"${{lua_parse fg text}}${{font {conky_font(HEADING_FONT)}}}{heads}{plain()}", heading_h)
    out.gap(LIST_GAP)
    list_top = out.y
    row = line_height(ROW_FONT) + ROW_SPACING * text_scale
    rows_fit = list_height / row
    count = len(listed)
    chips_top, pitch, chip_h = block_rows(row)
    layout, spans = [], []
    for s in listed:
        chips, lines = block_chips(s.get('issues', ()), text_w)
        # the block's lines may need more rows than the speech setting does
        span = max(2 if s['speech'] == 'on' else 1, math.ceil(round((chips_top + lines * pitch) / row, 6)) if lines else 1)
        layout.append((chips, span))
        spans.append(span)
    last = max(0, round(sum(spans) - rows_fit + 0.4999))
    version = write_sessions(listed, layout)
    seg_h = line_height(SEGMENT_FONT) + 4 * text_scale
    queued_right = xs[0] - 10
    draw.append(f'list {MARGIN} {right} {list_top} {row:.2f} {list_height} {version} {count} '
                f'{last}')
    draw.append('control ' + ' '.join(f'{x:.2f}' for x in xs) + f' {seg_h:.2f} {queued_right:.2f}')
    draw.append(f'block {BLOCK_RULE} {BLOCK_PAD} {text_w:g} {chips_top:.2f} {pitch:.2f} {chip_h:.2f}')
    rows, top = [], 0.0
    for s, (chips, span) in zip(listed, layout):
        entry = {'id': s['id'], 'speech': s['speech'], 'top': round(top, 2),
                 'bottom': round(top + row * span, 2)}
        for i, (key, _) in enumerate(SEGMENTS):
            entry[key] = [round(xs[i], 2), round(xs[i + 1], 2)]
        # Each issue number opens its issue and the pill the ready pull requests, each only
        # with one to open; the name closes the session, once confirmed. An issue's box is
        # [left, top, right, bottom], its top from the row's
        name_span, pill_span = name_spans(s, queued_right, box_w)
        entry.update(name=name_span, title=display_text(s['name']), pid=s['pid'], busy=bool(s['busy']))
        if chips:
            x0 = MARGIN + BLOCK_RULE + BLOCK_PAD
            entry['issues'] = [[round(x0 + x, 2), round(chips_top + line * pitch + (pitch - chip_h) / 2, 2),
                                round(x0 + x + w, 2),
                                round(chips_top + line * pitch + (pitch + chip_h) / 2, 2), link]
                               for line, x, w, _, link in chips]
        if s.get('prs'):
            entry.update(link=pill_span, branch=s.get('branch') or '', prs=s['prs'])
        rows.append(entry)
        top += row * span
    regions['list'] = [MARGIN, list_top, right, list_top + list_height]
    regions['rows'] = rows
    regions['list_scroll'] = [last, round(row, 2)]
    prompt_line, regions['confirm'] = close_prompt(right, list_top, list_height)
    draw.append(prompt_line)
    out.gap(list_height)

    # The footer: the says line, the progress bar, then the controls: pause or resume, skip and
    # next, the volume slider, the voice drop down. Skip and next are drawn dimmed, and are not
    # click areas, while no clip plays. The open list is drawn above the controls, over the
    # progress bar and the sessions, when conky-mouse.py has it open.
    out.gap(FOOTER_GAP)
    # The speaker's avatar, level with the bottom of a bubble whose tail points at it. While a
    # clip plays the bubble holds the speaker's name, then the whole line being read aloud: one
    # line high for a short one, growing upward with it to BUBBLE_LINES lines, after which
    # draw.lua scrolls it; while nothing plays there is the avatar alone. The row is always as
    # tall as the tallest bubble, so the card's size does not change as lines play. draw.lua
    # draws it from these lines.
    name_h, line_h = line_height(SEGMENT_FONT), line_height(ROW_FONT)
    full_h = 2 * BUBBLE_PAD + name_h + BUBBLE_NAME_GAP + BUBBLE_LINES * line_h
    bubble_x0 = MARGIN + AVATAR_D + AVATAR_GAP
    inner = (right - bubble_x0 - 2 * BUBBLE_PAD) / BLOCK_SLACK    # draw.lua's text runs wider
    bottom = out.y + full_h
    avatar_at(bottom - AVATAR_D)                              # level with the bubble's bottom
    if n:
        speaker = re.sub(r' session$', '', state['name'], flags=re.I) or 'A session'   # the hook's "<name> session"
        said = wrap_lines(without_speaker(state.get('text') or ''), ROW_FONT, inner)
        shown = min(max(len(said), 1), BUBBLE_LINES)
        top = bottom - (2 * BUBBLE_PAD + name_h + BUBBLE_NAME_GAP + shown * line_h)
        name = fit(speaker, SEGMENT_FONT, inner)
        wide = max([text_width(name, SEGMENT_FONT)] + [text_width(l, ROW_FONT) for l in said]) * BLOCK_SLACK
        bubble_right = min(bubble_x0 + 2 * BUBBLE_PAD + math.ceil(wide), right)   # as wide as its text needs
        draw.append(f'bubble {bubble_x0} {top} {bubble_right} {bottom} {BUBBLE_PAD} '
                    f'{top + BUBBLE_PAD + name_h / 2:.2f} '
                    f'{top + BUBBLE_PAD + name_h + BUBBLE_NAME_GAP + line_h / 2:.2f} {line_h:.2f} '
                    f'{bottom - AVATAR_D / 2:.2f} {shown}')
        draw.append(f'speaker {name}')
        draw.extend(f'line {line}' for line in said)
        regions['bubble'] = [bubble_x0, top, bubble_right, bottom]
        regions['bubble_scroll'] = max(len(said) - shown, 0)            # lines past what it shows
    out.gap(max(full_h, AVATAR_D))
    out.gap(HEADER_GAP)
    # The progress bar, always there: the current line's while its length is known (0:00 while
    # Piper still renders it), else the last line's, left full where it finished.
    duration, running = state['duration'] or 0, False
    if n:
        elapsed = clock.elapsed(n, paused, now)
        running = bool(duration) and not paused
        elapsed = min(elapsed, duration)
    else:
        duration = elapsed = float(heard.get('duration') or 0)
    draw.append(f'progress {MARGIN} {right} {out.y + PROGRESS_H / 2} {time.monotonic():.3f} '
                f'{elapsed:.3f} {duration:.3f} {int(running)}')
    out.gap(PROGRESS_H)
    footer_top = out.y
    out.gap(FOOTER_GAP)
    drop_h = max(DROPDOWN_H, line_height(FOOTER_FONT) + 6)   # taller with the text scale
    footer_h = max(FOOTER_H, drop_h + 6)
    fy = out.y + footer_h / 2
    pause_cx = MARGIN + PAUSE_SIZE / 2
    skip_cx = pause_cx + PAUSE_SIZE + FOOTER_BUTTON_GAP
    next_cx = skip_cx + PAUSE_SIZE + FOOTER_BUTTON_GAP
    vol_icon = next_cx + PAUSE_SIZE / 2 + 16
    vol_x0 = vol_icon + VOLUME_ICON + VOLUME_GAP
    level = min(max(state['volume'] / VOLUME_TOP, 0.0), 1.0)
    chrome = 2 * DROPDOWN_PAD + DROPDOWN_GAP + DROPDOWN_ARROW
    voice = f"Voice: {voice_label(state['voice'])}"
    # The track gives up room, down to VOLUME_MIN, before the voice's label is cut
    vol_x1 = vol_x0 + min(VOLUME_WIDTH, max(VOLUME_MIN, right - (text_width(voice, FOOTER_FONT) + chrome) - 22 - vol_x0))
    voice = fit(voice, FOOTER_FONT, right - (vol_x1 + 6 + 16) - chrome)
    drop_x0 = right - (text_width(voice, FOOTER_FONT) + chrome)
    drop = [drop_x0, fy - drop_h / 2, right, fy + drop_h / 2]
    draw.append(f'footer {pause_cx} {fy} {PAUSE_SIZE} {int(paused)}')
    draw.append(f'buttons {skip_cx} {next_cx} {fy} {PAUSE_SIZE} {int(bool(n))}')
    draw.append(f'volume {vol_x0} {vol_x1} {fy} {level:.4f} {vol_icon} {VOLUME_ICON}')
    draw.append(f'voice {drop_x0} {right} {fy} {drop_h:g} {DROPDOWN_PAD} {DROPDOWN_ARROW} {voice}')
    half = PAUSE_SIZE / 2 + 4
    regions.update({
        'pause': box(pause_cx, fy, half, half),
        'volume_icon': [vol_icon - 4, fy - 10, vol_x0 - 6, fy + 10],   # a click mutes; the wheel reaches it too
        'volume': [vol_x0 - 6, fy - 10, vol_x1 + 6, fy + 10],
        'volume_wheel': [vol_icon - 4, fy - 10, vol_x1 + 6, fy + 10],
        'volume_bar': [vol_x0, vol_x1],
        'voice': drop,
    })
    if n:
        regions['skip'] = box(skip_cx, fy, half, half)
        regions['next'] = box(next_cx, fy, half, half)
    names = state.get('voices') or []
    if names:
        menu_lines, menu = voice_menu(names, state['voice'], right, footer_top - MENU_GAP + FOOTER_GAP,
                                      list_top)
        draw.extend(menu_lines)
        regions['menu'] = menu
    out.gap(footer_h)
    write_atomic(DRAW, '\n'.join(draw) + '\n')
    write_atomic(REGIONS, json.dumps(regions))
    return out.end(out.y + MARGIN - 4)


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


def voice_menu(names, current, right, bottom, top_limit):
    """(draw.txt's lines, regions.json's entry) for the open voice list: one row a voice, its
    right edge on the drop down's, its bottom at `bottom` and as many rows as fit between there
    and `top_limit` (at least MENU_MIN_ROWS), the rest scrolled. draw.lua draws it only while
    conky-mouse.py has it open; the entry carries the names conky-mouse.py sets one from."""
    item_h = line_height(FOOTER_FONT) + 8 * text_scale
    rows = max(MENU_MIN_ROWS, int((bottom - top_limit - 2 * MENU_PAD) // item_h))
    rows = min(rows, len(names))
    labels = [voice_label(n) for n in names]
    scrolls = len(names) > rows
    width = max(text_width(label, FOOTER_FONT) for label in labels) + 2 * DROPDOWN_PAD + (8 if scrolls else 0)
    x0, top = right - width, bottom - rows * item_h - 2 * MENU_PAD
    lines = [f'menu {x0:.2f} {right} {top:.2f} {bottom} {item_h:.2f} {rows} {MENU_PAD} {len(names)}']
    lines += [f'item {int(n == current)} {label}' for n, label in zip(names, labels)]
    entry = {'box': [round(x0, 2), round(top, 2), right, bottom], 'item_h': round(item_h, 2),
             'rows': rows, 'pad': MENU_PAD, 'names': names,
             'current': names.index(current) if current in names else -1}
    return lines, entry


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
            state = read_state()
            state['voices'] = installed_voices()
            text = render(state)
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
        # Every 0.25 s, or at once when the size settings change.
        settings = size_file.load(SIZE)
        for _ in range(5):
            time.sleep(0.05)
            if size_file.load(SIZE) != settings:
                break


if __name__ == '__main__':
    main()
