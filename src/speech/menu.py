"""The speech widget's settings menu, laid out as the CLI's settings list: a title, then a row
for each setting with its value at the right, one of them selected. Enter, Space or a click
changes the selected row (a setting with a few values turns to the next, a row with a › opens
a page of its own) and Left, Backspace or a click on the title goes back a page.

The pages: the widget's own settings (the default voice, pace, text scaling, collapse when idle,
always on top, reset size), the voices, the sessions, and for a session its speech setting and
its voice. This module holds what they show and do; mouse.py draws nothing and runs it, and
draw.lua draws what it writes.
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', 'common'))
import tray_model  # noqa: E402
import widget_size  # noqa: E402

SPEECH_CYCLE = ('on', 'alerts', 'off')                  # a session's speech setting, in the order Enter turns it
SPEECH_LABELS = {'on': 'On', 'alerts': 'Alerts', 'off': 'Off'}
CHEVRON = '›'
SCALES = tray_model.SCALES


def voice_label(voice):
    """A Piper model's speaker: 'en_US-amy-medium' -> 'amy'; another name as it is."""
    m = re.fullmatch(r'[a-z]{2,3}_[A-Za-z]{2,3}-(.+)-(x_low|low|medium|high)', voice)
    return m.group(1) if m else voice


class Settings:
    """What the menu reads and changes of the widget and the speech, the tray's own settings: the
    one place the menu touches the machine, so a test can put its own in."""

    def __init__(self, run=None, set_session_voice=None, set_session_speech=None):
        self.size_path = tray_model.size_file('speech')
        self.run = run or tray_model.run_speechctl
        self.set_session_voice = set_session_voice
        self.set_session_speech = set_session_speech

    def voice(self):
        return tray_model.speech_settings()[0]

    def set_voice(self, name):
        self.run('voice', name)

    def pace(self):
        return tray_model.speech_pace()

    def set_pace(self, pace):
        tray_model.set_speech_pace(pace)

    def scale(self):
        return widget_size.load(self.size_path)[2]

    def set_scale(self, scale):
        width, height, _ = widget_size.load(self.size_path)
        widget_size.save((width, height, scale), self.size_path)

    def collapse(self):
        return tray_model.collapse_idle()

    def set_collapse(self, on):
        tray_model.set_collapse_idle(on)

    def on_top(self):
        return tray_model.on_top('speech')

    def set_on_top(self, on):
        tray_model.set_on_top('speech', on)

    def reset_size(self):
        widget_size.save(widget_size.defaults_for(self.size_path)[:2] + widget_size.load(self.size_path)[2:],
                         self.size_path)


def next_of(values, current, step=1):
    """The value `step` after `current` in `values` (before it for -1), wrapping; the first
    when it is not there (a value the presets do not hold, a hand-edited pace)."""
    for i, v in enumerate(values):
        if abs(v - current) < 1e-6 if isinstance(v, float) else v == current:
            return values[(i + step) % len(values)]
    return values[0]


class Menu:
    """The pages and the cursor. `sessions` are regions.json's rows ({'id', 'title', 'speech',
    'voice'}), `voices` the installed voices' names, and `settings` a Settings."""

    def __init__(self, sessions, voices, settings):
        self.sessions = [dict(s) for s in sessions]
        self.voices = list(voices)
        self.settings = settings
        self.path = [('root', None)]
        self.selected = 0
        self.top = 0
        self.came_from = []
        self._rows = None

    # What a page shows
    @property
    def page(self):
        return self.path[-1]

    def title(self):
        kind, i = self.page
        parts = ['Settings']
        if kind == 'voice':
            parts.append('Default voice')
        if kind in ('sessions', 'session', 'svoice'):
            parts.append('Sessions')
        if kind in ('session', 'svoice'):
            parts.append(self.sessions[i]['title'])
        if kind == 'svoice':
            parts.append('Voice')
        return ' › '.join(parts)

    def rows(self):
        """The page's rows, built once and again after a change: mouse.py asks fifty times a second
        and each build reads the settings' files."""
        if self._rows is None:
            self._rows = self._build()
        return self._rows

    def _build(self):
        """[(label, value, flag)] of the page: the flag is 'current' on the voice in use and ''
        otherwise, and a value ending in › opens a page."""
        kind, i = self.page
        s = self.settings
        if kind == 'root':
            return [('Default voice', voice_label(s.voice()) + ' ' + CHEVRON, ''),
                    ('Pace', f'{s.pace():g}', ''),
                    ('Text scaling', f'{s.scale():.0%}', ''),
                    ('Collapse when idle', str(s.collapse()).lower(), ''),
                    ('Always on top', str(s.on_top()).lower(), ''),
                    ('Reset widget size', CHEVRON, ''),
                    ('Sessions', f'{len(self.sessions)} {CHEVRON}', '')]
        if kind == 'voice':
            current = s.voice()
            return [(voice_label(n), 'current' if n == current else '', 'current' if n == current else '')
                    for n in self.voices]
        if kind == 'sessions':
            return [(x['title'], SPEECH_LABELS.get(x['speech'], x['speech']) + ' ' + CHEVRON, '')
                    for x in self.sessions] or [('No Claude sessions open', '', '')]
        if kind == 'session':
            x = self.sessions[i]
            return [('Speech', SPEECH_LABELS.get(x['speech'], x['speech']), ''),
                    ('Voice', (voice_label(x['voice']) if x['voice'] else 'Default') + ' ' + CHEVRON, '')]
        if kind == 'svoice':
            x = self.sessions[i]
            return [('Default', 'current' if not x['voice'] else '', 'current' if not x['voice'] else '')] + \
                   [(voice_label(n), 'current' if n == x['voice'] else '', 'current' if n == x['voice'] else '')
                    for n in self.voices]

    # What the cursor does
    def move(self, delta, visible):
        count = len(self.rows())
        self.selected = min(max(self.selected + delta, 0), max(count - 1, 0))
        self.follow(visible)

    def follow(self, visible):
        """Scrolls so the selected row shows among `visible` rows."""
        count = len(self.rows())
        if self.selected < self.top:
            self.top = self.selected
        elif self.selected >= self.top + visible:
            self.top = self.selected - visible + 1
        self.top = min(max(self.top, 0), max(count - visible, 0))

    def select(self, index):
        if 0 <= index < len(self.rows()):
            self.selected = index

    def go(self, page, selected=0):
        """Opens `page` with row `selected` under the cursor, remembering where the cursor was."""
        self._rows = None
        self.came_from.append(self.selected)
        self.path.append(page)
        self.selected, self.top = selected, 0

    def back(self):
        """Goes back a page, the cursor on the row that opened it; False at the first page,
        which closing the menu answers."""
        if len(self.path) == 1:
            return False
        self._rows = None
        self.path.pop()
        self.selected, self.top = self.came_from.pop(), 0
        return True

    def nudge(self, step):
        """Right (+1) and Left (-1) on the selected row: a setting that has values turns to the
        next or the one before; Right on a row that opens a page opens it; Left on one, on a page
        of choices or on a row with nothing to turn goes back a page, and does nothing on the first
        page. Never closes the menu."""
        kind, i = self.page
        row = self.selected
        turns = (kind == 'root' and row in (1, 2, 3, 4)) or (kind == 'session' and row == 0)
        if turns:
            self.activate(step=step)
        elif step > 0:
            self.activate()
        else:
            self.back()

    def activate(self, index=None, step=1):
        """Changes the selected row (or `index`'s); `step` -1 turns a setting that has values
        backwards."""
        if index is not None:
            self.select(index)
        self._rows = None                                         # what is chosen shows in the page's values
        kind, i = self.page
        s, row = self.settings, self.selected
        if kind == 'root':
            if row == 0:
                self.go(('voice', None))
            elif row == 1:
                s.set_pace(next_of(tray_model.PACES, s.pace(), step))
            elif row == 2:
                s.set_scale(next_of(tuple(SCALES), s.scale(), step))
            elif row == 3:
                s.set_collapse(not s.collapse())
            elif row == 4:
                s.set_on_top(not s.on_top())
            elif row == 5:
                s.reset_size()
            elif row == 6:
                self.go(('sessions', None))
        elif kind == 'voice':
            if row < len(self.voices):
                s.set_voice(self.voices[row])
            self.back()
        elif kind == 'sessions':
            if row < len(self.sessions):
                self.go(('session', row))
        elif kind == 'session':
            x = self.sessions[i]
            if row == 0:
                x['speech'] = next_of(SPEECH_CYCLE, x['speech'], step)
                s.set_session_speech(x['id'], x['speech'])
            else:
                names = [''] + self.voices
                self.go(('svoice', i), names.index(x['voice']) if x['voice'] in names else 0)
        elif kind == 'svoice':
            x = self.sessions[i]
            names = [''] + self.voices
            if row < len(names):
                x['voice'] = names[row]
                s.set_session_voice(x['id'], names[row])
            self.back()

