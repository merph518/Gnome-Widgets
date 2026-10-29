"""What the tray menu reads and writes, apart from GTK: whether each widget shows, its always
on top and text size settings, and whether the orchestrator widget collapses when idle.

Each widget is shown or hidden by its own flag file, hidden in its cache folder, which the
tray's Show ticks, the widget's own – and × buttons (conky-mouse.py) and the launcher's
show/hide all write. A Show tick is ticked while that widget runs and has no flag, so the
ticks follow the flags whichever of the three changed them.
"""
import os, subprocess

# Each widget's name in its Show item, its config and cache folders as the launcher keeps
# them, and its autostart entry.
WIDGETS = {
    'spotify': dict(show='Spotify', conf='~/.config/conky-spotify-nowplaying',
                    cache='~/.cache/conky-spotify-nowplaying', autostart='conky-spotify-nowplaying.desktop'),
    'orchestrator': dict(show='Claude Code Orchestrator', conf='~/.config/conky-widgets/orchestrator',
                         cache='~/.cache/conky-widgets/orchestrator', autostart='conky-widgets-orchestrator.desktop'),
}
LAUNCHER = os.environ.get('CSN_LAUNCHER') or 'conky-widgets'
UP = os.path.expanduser('~/.cache/conky-widgets/up')     # a file per widget the supervisor runs
AUTOSTART_DIR = os.path.expanduser('~/.config/autostart')
SCALES = (0.7, 0.85, 1.0, 1.25, 1.5, 1.75, 2.0)          # the Text scaling menu's presets


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


def collapse_file():
    return os.path.join(conf_dir('orchestrator'), 'collapse-idle')   # 'on': one line while idle


def collapse_idle():
    try:
        with open(collapse_file()) as f:
            return f.read().strip() == 'on'
    except OSError:
        return False


def set_collapse_idle(on):
    path = collapse_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('on\n' if on else 'off\n')


def starts_at_login():
    return any(os.path.exists(autostart_file(w)) for w in WIDGETS)
