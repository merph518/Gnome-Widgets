"""What the tray menu reads and writes, apart from GTK: whether each widget shows, the
speech line, the speech settings and voices, and the speechctl that carries out the
Speech submenu's items.

Each widget is shown or hidden by its own flag file, hidden in its cache folder, which the
tray's Show ticks, the widget's own – and × buttons (conky-mouse.py) and the launcher's
show/hide all write. A Show tick is ticked while that widget runs and has no flag, so the
ticks follow the flags whichever of the three changed them.

Speech is read from the files the speaking hook keeps in $XDG_RUNTIME_DIR/speak-attention/:
now.json while a clip plays, paused while paused, settings.json for the voice and volume.
The commands go through speechctl, from ~/.config/conky-widgets/speech/speechctl when that
file names one, otherwise from PATH.
"""
import json, os, shutil, subprocess

# Each widget's name in its Show item, its config and cache folders as the launcher keeps
# them, and its autostart entry.
WIDGETS = {
    'spotify': dict(show='Spotify', conf='~/.config/conky-spotify-nowplaying',
                    cache='~/.cache/conky-spotify-nowplaying', autostart='conky-spotify-nowplaying.desktop'),
    'speech': dict(show='speech', conf='~/.config/conky-widgets/speech',
                   cache='~/.cache/conky-widgets/speech', autostart='conky-widgets-speech.desktop'),
}
LAUNCHER = os.environ.get('CSN_LAUNCHER') or 'conky-widgets'
UP = os.path.expanduser('~/.cache/conky-widgets/up')     # a file per widget the supervisor runs
AUTOSTART_DIR = os.path.expanduser('~/.config/autostart')
SPEAK = os.path.join(os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}', 'speak-attention')
SPEECHCTL = os.path.expanduser('~/.config/conky-widgets/speech/speechctl')   # a path to speechctl
SPEECH_LINE = 60                                          # characters of the spoken line the menu shows
VOLUMES = (0.25, 0.5, 0.75, 1.0, 1.2, 1.5, 2.0)          # the Volume menu's presets
DEFAULT_VOLUME = 1.2                                      # what speech plays at with no setting


def conf_dir(widget):
    return os.path.expanduser(WIDGETS[widget]['conf'])


def hidden_file(widget):
    return os.path.join(os.path.expanduser(WIDGETS[widget]['cache']), 'hidden')


def size_file(widget):
    return os.path.join(conf_dir(widget), 'size')


def on_top_file(widget):
    return os.path.join(conf_dir(widget), 'on-top')        # 'off': not always on top


def autostart_file(widget):
    return os.path.join(AUTOSTART_DIR, WIDGETS[widget]['autostart'])


def running(widget):
    return os.path.exists(os.path.join(UP, widget))


def shown(widget):
    """What the widget's Show tick says: it runs, and is not hidden."""
    return running(widget) and not os.path.exists(hidden_file(widget))


def set_hidden(widget, hidden):
    path = hidden_file(widget)
    if hidden:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, 'w').close()
    else:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


def launcher(*args):
    subprocess.Popen([LAUNCHER, *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def show(widget, on):
    """What the widget's Show tick does: shows or hides it, starting it when it is not
    running."""
    set_hidden(widget, not on)
    if on and not running(widget):
        launcher(widget, 'start')


def on_top(widget):
    try:
        with open(on_top_file(widget)) as f:
            return f.read().strip() != 'off'
    except OSError:
        return True


def set_on_top(widget, on):
    path = on_top_file(widget)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('on\n' if on else 'off\n')


def starts_at_login():
    return any(os.path.exists(autostart_file(w)) for w in WIDGETS)


def _json(path):
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def speech_line():
    """The menu's speech line: who is speaking and what, or Speech paused or Speech idle."""
    if os.path.exists(os.path.join(SPEAK, 'paused')):
        return 'Speech paused'
    now = _json(os.path.join(SPEAK, 'now.json'))
    text = ' '.join(str(now.get('text') or '').split())
    if not text:
        return 'Speech idle'
    if len(text) > SPEECH_LINE:
        text = text[:SPEECH_LINE - 1].rstrip() + '…'
    name = str(now.get('name') or '').strip()
    return f'{name}: “{text}”' if name else f'“{text}”'


def paused():
    return os.path.exists(os.path.join(SPEAK, 'paused'))


def speech_settings():
    """(voice, volume) from settings.json; '' and DEFAULT_VOLUME when it has none."""
    settings = _json(os.path.join(SPEAK, 'settings.json'))
    try:
        volume = float(settings.get('volume', DEFAULT_VOLUME))
    except (TypeError, ValueError):
        volume = DEFAULT_VOLUME
    return str(settings.get('voice') or ''), volume


def speechctl():
    """The speechctl to run: the one SPEECHCTL names when it is there, else PATH's; None
    when there is none."""
    try:
        with open(SPEECHCTL) as f:
            path = os.path.expanduser(f.read().strip())
        if path and os.access(path, os.X_OK):
            return path
    except OSError:
        pass
    return shutil.which('speechctl')


def voices():
    """The voices `speechctl voices` lists, one a line, its first word the name."""
    ctl = speechctl()
    if not ctl:
        return []
    try:
        out = subprocess.run([ctl, 'voices'], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [line.split()[0] for line in out.splitlines() if line.strip()]


def run_speechctl(*args):
    """Runs speechctl with `args`, without waiting; False when there is no speechctl."""
    ctl = speechctl()
    if not ctl:
        return False
    subprocess.Popen([ctl, *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True
