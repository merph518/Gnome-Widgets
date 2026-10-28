#!/usr/bin/env python3
"""Builds the speech widget's contents: what is being read aloud and what waits behind it.

Four times a second this reads, and only reads:
  - the open Claude sessions, from ~/.claude/sessions/<pid>.json (sessions.py)
  - the speaking hook's state in $XDG_RUNTIME_DIR/speak-attention/: now.json while a clip
    plays, <session>.queue (a line per block still to read), <session>.name, <session>.replies
    (speech on) and <session>.muted (speech off), the paused flag and settings.json (voice,
    volume). The .key files beside the session files are never opened.

and writes, under ~/.cache/conky-widgets/speech/, the files the Spotify widget's
nowplaying.py writes for its own card:
  - widget.txt   conky's markup: the header ("<name> says:"), the Sessions label and spacer
                 lines that give conky's window its size, which stays the same while lines play
  - draw.txt     geometry for draw.lua (logical px, from the card's top left): the buttons,
                 the progress of the current line, the sessions list and the footer
  - regions.json click areas for conky-mouse.py, in the same coordinates
  - sessions.txt the sessions list, a line per session, rewritten only when it changes

Each session has a speech setting, read from its files the way speechctl reads it: On while
<id>.replies exists (its replies are read aloud), Off while <id>.muted exists (nothing
plays), Alerts only with neither (only its announcements play). Sessions with speech on sort
first, then by process id, so the ones being read aloud are at the top.
"""
import fcntl, hashlib, json, os, re, subprocess, sys, time, unicodedata, wave
import gi
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Pango, PangoCairo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'common'))
import sessions as sessions_mod  # noqa: E402
import widget_size as size_file  # noqa: E402

NAME = 'conky-widgets/speech'
CONF = os.path.expanduser(f'~/.config/{NAME}')
CACHE = os.path.expanduser(f'~/.cache/{NAME}')
OUT = os.path.join(CACHE, 'widget.txt')
DRAW = os.path.join(CACHE, 'draw.txt')
REGIONS = os.path.join(CACHE, 'regions.json')
SESSIONS = os.path.join(CACHE, 'sessions.txt')
LAST = os.path.join(CACHE, 'last-lines.json')     # {session id: the last line read aloud for it}
LOG = os.path.join(CACHE, 'speechqueue.log')
INSTANCE_LOCK = os.path.join(CACHE, 'speechqueue.lock')
SIZE = size_file.SPEECH_PATH
COLLAPSE = os.path.join(CONF, 'collapse-idle')    # 'on': a single line while nothing is said
LABELS = os.path.join(CONF, 'labels.json')        # {repository name: label}, before each session
SPEAK = os.path.join(os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}', 'speak-attention')
DEFAULT_VOICE = 'en_US-amy-medium'                # speechctl's, with no setting
DEFAULT_VOLUME = 1.2

SHADOW = size_file.SHADOW
MARGIN = 16                                   # around the contents
ICON_W = 24                                   # the speaker icon left of the header text
HEADER_GAP = 6                                # header to the progress bar's row
LINE_GAP = 14                                 # the progress bar's row to Sessions
PROGRESS_H = 14                               # the progress bar's row
LIST_GAP = 0                                  # the Sessions label to the list
FOOTER_GAP = 8                                # list to the footer
FOOTER_H = 30                                 # the footer row: pause, volume and voice
ROW_SPACING = 6                               # extra space in a session's row
BUTTON_SIZE = 16                              # skip and next, right of the header
BUTTON_PITCH = 26
WINDOW_BUTTON_SIZE = 10                       # minimize / close, as the Spotify widget's
WINDOW_BUTTON_PITCH = 22
PAUSE_SIZE = 28                               # the footer's pause/resume circle
SMALL_PITCH = 22                              # − + and ◀ ▶, centre to centre, and their hit width
SEGMENTS = (('on', 'On'), ('alerts', 'Alerts'), ('off', 'Off'))
SEGMENT_PAD = 7                               # either side of a segment's label
LABEL_LEN = 4                                 # a repository's label, in letters
NOTHING_SAID = 'Nothing read aloud yet'       # an On session's second row before its first line
# labels.json's first contents, written when it is missing; keys match without case
DEFAULT_LABELS = {
    'Gnome-Widgets': 'GWID', 'conky-widgets': 'GWID', 'Overmind': 'OVMD',
    'fagerteam-health-coach': 'FTHC', 'LaundryBot': 'LBOT', 'Playwright-Testing': 'PWRT',
    'TheRPGClub-api': 'RPGA', 'TheRPGClub-bot': 'RPGB', 'CalendarBot': 'CALB',
    'ATT-Test-Pack-Gen': 'ATPG', 'eve-lectures': 'EVEL',
}

SPACER_FONT = 'Ubuntu Sans 1'
SPACER_HEIGHT = 2                             # what conky adds for that spacer line (measured)
PLAIN_FONT = 'Ubuntu Sans 13'                 # between runs of text; see plain()
LABEL_FONT = 'Ubuntu Sans Bold 11'            # "<name> says:", "Speech idle"
HEADING_FONT = 'Ubuntu Sans Bold 9'           # "Sessions"
ROW_FONT = 'Ubuntu Sans 11'                   # a session's row, as draw.lua draws it
SEGMENT_FONT = 'Ubuntu Sans Bold 9'           # On | Alerts | Off, as draw.lua draws it
FOOTER_FONT = 'Ubuntu Sans 11'                # Vol 1.2, Voice amy, as draw.lua draws it
TEXT_FONTS = {PLAIN_FONT, LABEL_FONT, HEADING_FONT, ROW_FONT, SEGMENT_FONT, FOOTER_FONT}

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


def repo_name(cwd):
    """The GitHub name of the repository cwd is in: the last part of its origin remote's URL,
    or the checkout's folder name without one. A worktree's .git is a file pointing into
    the main checkout's .git, which holds the config. '' outside a repository."""
    d = os.path.abspath(cwd) if cwd else ''
    while d and d != os.path.dirname(d):
        git = os.path.join(d, '.git')
        if os.path.exists(git):
            break
        d = os.path.dirname(d)
    else:
        return ''
    top, config = d, os.path.join(git, 'config')
    if os.path.isfile(git):
        m = re.match(r'gitdir:\s*(.+)', _read(git) or '')
        if m:
            base = os.path.join(d, m.group(1).strip())     # relative to the worktree, when it is
            common = (_read(os.path.join(base, 'commondir')) or '').strip()
            main = os.path.normpath(os.path.join(base, common)) if common else base
            config, top = os.path.join(main, 'config'), os.path.dirname(main)
    m = re.search(r'\[remote "origin"\][^\[]*?url\s*=\s*(\S+)', _read(config) or '')
    url = m.group(1).rstrip('/') if m else ''
    name = re.sub(r'\.git$', '', url.rsplit('/', 1)[-1].rsplit(':', 1)[-1]) if url else ''
    return name or os.path.basename(top)


def short_label(name):
    """A repository name as LABEL_LEN capitals: each word's first letter, filled out with the
    last word's following letters (LaundryBot -> LBOT, Overmind -> OVER)."""
    words = re.findall(r'[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+', name)
    if not words:
        return ''
    label = ''.join(w[0] for w in words)[:LABEL_LEN]
    label += words[-1][1:LABEL_LEN - len(label) + 1]
    return label[:LABEL_LEN].upper()


_repos = {}


def session_label(cwd, labels):
    """The label before a session's name: labels.json's for its repository, else short_label."""
    if cwd not in _repos:
        _repos[cwd] = repo_name(cwd)
    name = _repos[cwd]
    custom = {str(k).lower(): str(v) for k, v in labels.items()}.get(name.lower())
    return display_text(custom if custom is not None else short_label(name))[:LABEL_LEN]


def read_labels(path=None):
    labels = _json(path or LABELS)
    return labels if isinstance(labels, dict) else {}


def seed_labels():
    """labels.json with DEFAULT_LABELS when it is missing; the widget runs without it."""
    if not os.path.exists(LABELS):
        try:
            write_atomic(LABELS, json.dumps(DEFAULT_LABELS, indent=2) + '\n')
        except OSError as e:
            log(f'labels.json not written: {e}')


def voice_label(voice):
    """A Piper model's speaker: 'en_US-amy-medium' -> 'amy'; another name as it is."""
    m = re.fullmatch(r'[a-z]{2,3}_[A-Za-z]{2,3}-(.+)-(x_low|low|medium|high)', voice)
    return m.group(1) if m else voice


_last = None


def last_lines(n, live):
    """{session id: the last line read aloud for it}, kept in LAST across restarts: the line
    now.json plays is recorded once it starts, a question excepted (it shows as a tag while it
    waits, and its text is not listed). Sessions no longer open are dropped."""
    global _last
    if _last is None:
        saved = _json(LAST)
        _last = {str(k): str(v) for k, v in saved.items()} if isinstance(saved, dict) else {}
    last = {k: v for k, v in _last.items() if k in live}
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


def read_state(speak=None, sessions_dir=None, proc_dir=None, labels=None):
    """Everything the widget shows, from the files alone."""
    speak = speak or SPEAK
    labels = read_labels(labels)
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
    said = last_lines(n, {s['id'] for s in open_sessions})
    for s in open_sessions:
        lines = queue_lines(os.path.join(speak, s['id'] + '.queue'))
        # A question waiting to be read out shows as a "question" tag on the row
        question = bool(lines) and display_text(lines[0]).lower().startswith('question:')
        listed.append(dict(s, speech=speech_setting(speak, s['id']), queued=len(lines),
                           question=question,
                           label=session_label(s['cwd'], labels),
                           last=said.get(s['id'], ''),
                           speaking=bool(n and n.get('session') == s['id'])))
    listed.sort(key=lambda s: (s['speech'] != 'on', s['pid']))
    name = ''
    if n:
        name = display_text(n.get('name') or '') or next(
            (s['name'] for s in listed if s['id'] == n.get('session')), '')
    return {
        'now': n, 'name': name, 'duration': clip_duration(speak, n) if n else None,
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


def session_line(s):
    """sessions.txt's line for a session: id, speech, speaking, queued, flags, name, label,
    and for a session with speech on, its last line read aloud (NOTHING_SAID before one)."""
    flags = ','.join(f for f, on in (('busy', s['busy']), ('bg', s['background']),
                                        ('question', s.get('question'))) if on) or '-'
    return '\t'.join((s['id'], s['speech'], str(int(s['speaking'])), str(s['queued']), flags,
                      display_text(s['name']), s.get('label', ''),
                      (s.get('last') or NOTHING_SAID) if s['speech'] == 'on' else ''))


def write_sessions(listed):
    """sessions.txt, rewritten only when it changes; its version is what draw.txt names."""
    text = ''.join(session_line(s) + '\n' for s in listed)
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

    # The top row: the speaker and "<name> says:" or the idle or paused line, skip and next
    # while there is a clip, then minimize and close at the top right.
    close_cx = right - WINDOW_BUTTON_SIZE / 2
    min_cx = close_cx - WINDOW_BUTTON_PITCH
    header_h = line_height(LABEL_FONT, PLAIN_FONT)
    cy = MARGIN + header_h / 2
    next_cx = min_cx - WINDOW_BUTTON_PITCH / 2 - 8 - BUTTON_SIZE / 2
    skip_cx = next_cx - BUTTON_PITCH
    text_right = (skip_cx - BUTTON_SIZE / 2 if n else min_cx - WINDOW_BUTTON_PITCH / 2) - 8
    if n:
        who = state['name'] or 'A session'
        label = fit(f'{who} says:', LABEL_FONT, text_right - MARGIN - ICON_W)
    else:
        label = 'Speech paused' if paused else 'Speech idle'
    half = WINDOW_BUTTON_PITCH / 2
    regions = {
        'minimize': box(min_cx, cy, half, half),
        'close': [close_cx - half, cy - half, close_cx + half + 12, cy + half],
    }
    draw = [f'scale {SCALE} {text_scale:g}', f'shadow {SHADOW}',
            f'window {min_cx} {close_cx} {cy} {WINDOW_BUTTON_SIZE}',
            f"state {'paused' if paused else 'playing' if n else 'idle'}",
            f'header {MARGIN + ICON_W / 2 - 4} {cy}']
    g = f'${{goto {SHADOW + MARGIN + ICON_W}}}'
    out = Markup(MARGIN)
    out.text(f"{g}${{lua_parse fg {'title' if n else 'text'}}}${{font {conky_font(LABEL_FONT)}}}{esc(label)}{plain()}",
             header_h)
    if n:
        draw.append(f'buttons {skip_cx} {next_cx} {cy} {BUTTON_SIZE}')
        regions['skip'] = box(skip_cx, cy, BUTTON_PITCH / 2, BUTTON_PITCH / 2)
        regions['next'] = box(next_cx, cy, BUTTON_PITCH / 2, BUTTON_PITCH / 2)

    if idle and collapse_idle():
        write_atomic(DRAW, '\n'.join(draw) + '\n')
        write_atomic(REGIONS, json.dumps(regions))
        write_sessions(listed)
        return out.end(out.y + MARGIN - 4)

    # The current line's progress when the clip's length is known. Its row is kept while
    # nothing plays, so the card keeps one height from line to line.
    out.gap(HEADER_GAP)
    if n and state['duration']:
        elapsed = min(clock.elapsed(n, paused, now), state['duration'])
        draw.append(f'progress {MARGIN} {right} {out.y + PROGRESS_H / 2} {time.monotonic():.3f} '
                    f'{elapsed:.3f} {state["duration"]:.3f} {int(not paused)}')
    elif n:
        clock.elapsed(n, paused, now)
    out.gap(PROGRESS_H)

    # Sessions: a row each, drawn by draw.lua from sessions.txt, scrolled by the wheel when
    # they run longer than the list's height. A session with speech on always takes two rows,
    # the second its last line read aloud, so the list's layout doesn't change as lines play.
    out.gap(LINE_GAP)
    heading_h = line_height(HEADING_FONT, PLAIN_FONT)
    out.text(f"${{goto {SHADOW + MARGIN}}}${{lua_parse fg text}}${{font {conky_font(HEADING_FONT)}}}Sessions{plain()}",
             heading_h)
    out.gap(LIST_GAP)
    list_top = out.y
    row = line_height(ROW_FONT) + ROW_SPACING * text_scale
    rows_fit = list_height / row
    count = len(listed)
    spans = [2 if s['speech'] == 'on' else 1 for s in listed]
    last = max(0, round(sum(spans) - rows_fit + 0.4999))
    version = write_sessions(listed)
    # The setting's three segments at the right of each row, as wide as their labels
    seg_h = line_height(SEGMENT_FONT) + 4 * text_scale
    xs = [right]
    for _, label in reversed(SEGMENTS):
        xs.insert(0, xs[0] - text_width(label, SEGMENT_FONT) - 2 * SEGMENT_PAD * text_scale)
    queued_right = xs[0] - 10
    draw.append(f'list {MARGIN} {right} {list_top} {row:.2f} {list_height} {version} {count} '
                f'{last}')
    draw.append('control ' + ' '.join(f'{x:.2f}' for x in xs) + f' {seg_h:.2f} {queued_right:.2f}')
    rows, top = [], 0.0
    for s, span in zip(listed, spans):
        entry = {'id': s['id'], 'top': round(top, 2), 'bottom': round(top + row * span, 2)}
        for i, (key, _) in enumerate(SEGMENTS):
            entry[key] = [round(xs[i], 2), round(xs[i + 1], 2)]
        rows.append(entry)
        top += row * span
    regions['list'] = [MARGIN, list_top, right, list_top + list_height]
    regions['rows'] = rows
    regions['list_scroll'] = [last, round(row, 2)]
    out.gap(list_height)

    # The footer: pause or resume, the volume with − and +, the voice with ◀ and ▶
    out.gap(FOOTER_GAP)
    fy = out.y + FOOTER_H / 2
    pause_cx = MARGIN + PAUSE_SIZE / 2
    vol_x = pause_cx + PAUSE_SIZE / 2 + 16
    vol_text = f"Vol {state['volume']:.1f}"
    minus_cx = vol_x + text_width(vol_text, FOOTER_FONT) + 4 + SMALL_PITCH / 2
    plus_cx = minus_cx + SMALL_PITCH
    voice_next_cx = right - SMALL_PITCH / 2
    voice_prev_cx = voice_next_cx - SMALL_PITCH
    voice_right = voice_prev_cx - SMALL_PITCH / 2 - 4
    voice = fit(f"Voice {voice_label(state['voice'])}", FOOTER_FONT,
                voice_right - (plus_cx + SMALL_PITCH / 2 + 16))
    draw.append(f'footer {pause_cx} {fy} {PAUSE_SIZE} {int(paused)}')
    draw.append(f'volume {vol_x} {minus_cx} {plus_cx} {fy} {SMALL_PITCH} {vol_text}')
    draw.append(f'voice {voice_right} {voice_prev_cx} {voice_next_cx} {fy} {SMALL_PITCH} {voice}')
    small = SMALL_PITCH / 2
    regions.update({
        'pause': box(pause_cx, fy, PAUSE_SIZE / 2 + 4, PAUSE_SIZE / 2 + 4),
        'vol_down': box(minus_cx, fy, small, small),
        'vol_up': box(plus_cx, fy, small, small),
        'voice_prev': box(voice_prev_cx, fy, small, small),
        'voice_next': box(voice_next_cx, fy, small, small),
        'volume': [vol_x, fy - small, plus_cx + small, fy + small],
        'voice': [voice_right - text_width(voice, FOOTER_FONT), fy - small, voice_next_cx + small, fy + small],
    })
    out.gap(FOOTER_H)
    write_atomic(DRAW, '\n'.join(draw) + '\n')
    write_atomic(REGIONS, json.dumps(regions))
    return out.end(out.y + MARGIN - 4)


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
    seed_labels()
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
        # Every 0.25 s, or at once when the size settings change.
        settings = size_file.load(SIZE)
        for _ in range(5):
            time.sleep(0.05)
            if size_file.load(SIZE) != settings:
                break


if __name__ == '__main__':
    main()
