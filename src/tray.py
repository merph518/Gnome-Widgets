#!/usr/bin/env python3
"""The one top-bar (AppIndicator) icon for every widget, started by the launcher's
supervisor while any widget runs. Its menu shows the current track and what speech is
saying; shows or hides each widget on its own; holds a submenu of settings for each
(Spotify: text scaling, size, lyrics, always on top; Speech: pause, skip, clear, voice,
volume, pace, text scaling, size, collapse when idle, always on top); turns start-at-login on or
off; and quits every widget. What it reads and writes is in tray_model.py."""
import ctypes, os, signal, subprocess, sys, threading

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
try:
    gi.require_version('AyatanaAppIndicator3', '0.1')
    from gi.repository import AyatanaAppIndicator3 as AppIndicator
except (ValueError, ImportError):
    print('tray: AyatanaAppIndicator3 not available (install gir1.2-ayatanaappindicator3-0.1)',
          file=sys.stderr)
    sys.exit(78)   # tells the supervisor not to keep restarting us
from gi.repository import Gdk, GLib, Gtk

# The shared modules sit in common/ next to this file, installed or in a checkout, and the
# Spotify widget's settings in spotify/.
HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(HERE, 'common'))
sys.path.insert(0, os.path.join(HERE, 'spotify'))

import lyrics_settings
import tray_model
import widget_size

NAME = 'conky-spotify-nowplaying'                         # the icon, and the indicator's id
SCALES = (0.7, 0.85, 1.0, 1.25, 1.5, 1.75, 2.0)          # the Text scaling menu's presets
VOICES_EVERY = 10                                         # refreshes between asking for the voices


def installed(widget):
    return os.path.isfile(os.path.join(HERE, widget, 'conky.conf'))


def now_playing():
    out = subprocess.run(['playerctl', '-p', 'spotify', 'metadata', '--format', '{{artist}} – {{title}}'],
                         capture_output=True, text=True).stdout.strip()
    return out or 'Spotify not playing'


def same(a, b):
    return a == b or (isinstance(a, float) and isinstance(b, float) and abs(a - b) < 1e-6)


class Check:
    """A check item that shows current() and calls toggle(on) when clicked. sync() reads
    current() again, for a change made outside the menu."""

    def __init__(self, label, current, toggle):
        self.item = Gtk.CheckMenuItem(label=label)
        self.current, self.syncing = current, False
        self.item.connect('toggled', lambda item: self.syncing or toggle(item.get_active()))
        self.sync()

    def sync(self):
        on = self.current()
        if self.item.get_active() != on:
            self.syncing = True                 # set_active emits the same signal a click does
            self.item.set_active(on)
            self.syncing = False


class Radio:
    """A submenu of choices, (value, label) each, with the one current() returns checked;
    a click calls pick(value)."""

    def __init__(self, label, choices, current, pick):
        self.item = Gtk.MenuItem(label=label)
        self.menu = Gtk.Menu()
        self.item.set_submenu(self.menu)
        self.current, self.pick, self.items, self.syncing = current, pick, {}, False
        self.set_choices(choices)

    def set_choices(self, choices):
        for child in self.menu.get_children():
            self.menu.remove(child)
        self.items = {}
        for value, label in choices:
            item = Gtk.CheckMenuItem(label=label)
            item.set_draw_as_radio(True)
            item.connect('activate', lambda _, value=value: self.activate(value))
            self.items[value] = item
            self.menu.append(item)
        self.menu.show_all()
        self.item.set_sensitive(bool(choices))
        self.sync()

    def activate(self, value):
        if not self.syncing:
            self.pick(value)
            self.sync()                         # a click on the checked one unchecked it

    def sync(self):
        self.syncing = True                     # set_active emits activate, as a click does
        current = self.current()
        for value, item in self.items.items():
            item.set_active(same(value, current))
        self.syncing = False


def pace_label(pace):
    """A pace preset's menu label: its length scale, and what the ends and the default are."""
    note = {tray_model.PACES[0]: ' (fastest)', tray_model.PACES[-1]: ' (slowest)',
            tray_model.DEFAULT_PACE: ' (default)'}.get(pace, '')
    return f'{pace:g}{note}'


def item(label, activate):
    menu_item = Gtk.MenuItem(label=label)
    menu_item.connect('activate', lambda _: activate())
    return menu_item


def size_items(widget):
    """Text scaling: preset sizes for the widget's text, the current one checked; the widget
    keeps its size. Reset widget size puts the width and height back, keeping the text."""
    path = tray_model.size_file(widget)

    def pick_scale(scale):
        width, height, _ = widget_size.load(path)
        widget_size.save((width, height, scale), path)

    scaling = Radio('Text scaling', [(scale, f'{scale:.0%}') for scale in SCALES],
                    lambda: widget_size.load(path)[2], pick_scale)
    reset = item('Reset widget size',
                 lambda: widget_size.save(widget_size.defaults_for(path)[:2] + widget_size.load(path)[2:], path))
    return scaling, reset


def on_top_check(widget):
    return Check('Always on top', lambda: tray_model.on_top(widget),
                 lambda on: tray_model.set_on_top(widget, on))


def set_autostart(on):
    for widget in tray_model.WIDGETS:
        if installed(widget) or not on:
            tray_model.launcher(widget, 'autostart', 'on' if on else 'off')


class Indicator(AppIndicator.Indicator):
    """The library's indicator, minus its GtkStatusIcon fallback off X11 (see no_fallback)."""


def no_fallback():
    """When the panel's StatusNotifierWatcher is missing or slow at start, the library falls
    back to a GtkStatusIcon until it answers. Off X11 that icon has no tray to live in: it
    shows nothing and GTK logs a gtk_widget_get_scale_factor critical for it. Clear the
    class's fallback hook, which the library skips when unset; the item still registers
    once the watcher answers. The hook is AppIndicatorClass's 26th pointer: GObjectClass
    is 17 pointer-sized fields, then eight signal slots come before it, and seven more
    slots follow. A class of any other size is left alone rather than written blind."""
    class TypeQuery(ctypes.Structure):
        _fields_ = [('type', ctypes.c_size_t), ('type_name', ctypes.c_char_p),
                    ('class_size', ctypes.c_uint), ('instance_size', ctypes.c_uint)]

    gobject = ctypes.CDLL('libgobject-2.0.so.0')
    gobject.g_type_from_name.restype = ctypes.c_size_t
    gobject.g_type_from_name.argtypes = [ctypes.c_char_p]
    gobject.g_type_query.argtypes = [ctypes.c_size_t, ctypes.POINTER(TypeQuery)]
    gobject.g_type_class_ref.restype = ctypes.c_void_p
    gobject.g_type_class_ref.argtypes = [ctypes.c_size_t]
    gtype = gobject.g_type_from_name(Indicator.__gtype__.name.encode())
    query = TypeQuery()
    gobject.g_type_query(gtype, ctypes.byref(query))
    pointer = ctypes.sizeof(ctypes.c_void_p)
    if query.class_size != 33 * pointer:
        print(f'tray: unexpected AppIndicator class size {query.class_size}; keeping its fallback',
              file=sys.stderr)
        return
    klass = gobject.g_type_class_ref(gtype)
    ctypes.c_void_p.from_address(klass + 25 * pointer).value = None


def main():
    if not Gdk.Display.get_default().__gtype__.name.startswith('GdkX11'):
        no_fallback()
    indicator = Indicator(id=NAME, icon_name=f'{NAME}-symbolic', category='ApplicationStatus')
    # Running from a checkout the icon isn't installed; point at the repo's copy.
    repo_icons = os.path.join(HERE, '..', 'packaging', 'icons')
    if os.path.isdir(repo_icons):
        indicator.set_icon_theme_path(os.path.realpath(repo_icons))
    indicator.set_title('Conky widgets')
    indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)

    menu = Gtk.Menu()
    track = Gtk.MenuItem(label=now_playing())
    track.set_sensitive(False)
    menu.append(track)
    speaking = Gtk.MenuItem(label=tray_model.speech_line())
    speaking.set_sensitive(False)
    menu.append(speaking)
    menu.append(Gtk.SeparatorMenuItem())

    checks = []                                 # every Check, read again on each refresh
    radios = []                                 # and every Radio
    for widget, info in tray_model.WIDGETS.items():
        show = Check(f"Show {info['show']} widget", lambda widget=widget: tray_model.shown(widget),
                     lambda on, widget=widget: tray_model.show(widget, on))
        show.item.set_sensitive(installed(widget))
        checks.append(show)
        menu.append(show.item)
    menu.append(Gtk.SeparatorMenuItem())

    # Spotify: its size, lyrics on or off and how they scroll (greyed out while lyrics are
    # off), and always on top.
    spotify_menu = Gtk.Menu()
    scaling, reset = size_items('spotify')
    def set_lyrics(on):
        lyrics_settings.set_shown(on)
        scrolling.item.set_sensitive(on)

    lyrics = Check('Lyrics', lyrics_settings.shown, set_lyrics)
    scrolling = Radio('Lyrics scrolling',
                      [(lyrics_settings.AUTOSCROLL, 'Autoscroll'), (lyrics_settings.STATIC, 'Static')],
                      lyrics_settings.scrolling, lyrics_settings.set_scrolling)
    spotify_on_top = on_top_check('spotify')
    for entry in (scaling.item, reset, lyrics.item, scrolling.item, spotify_on_top.item):
        spotify_menu.append(entry)
    checks += [lyrics, spotify_on_top]
    radios += [scaling, scrolling]
    spotify = Gtk.MenuItem(label='Spotify')
    spotify.set_submenu(spotify_menu)
    menu.append(spotify)

    # Speech: what speechctl does, greyed out without one, then the widget's own settings.
    speech_menu = Gtk.Menu()
    pause = item('Pause', lambda: tray_model.run_speechctl('toggle'))
    skip = item('Skip', lambda: tray_model.run_speechctl('skip'))
    clear = item('Clear queue', lambda: tray_model.run_speechctl('clear'))
    voice = Radio('Voice', [], lambda: tray_model.speech_settings()[0],
                  lambda name: tray_model.run_speechctl('voice', name))
    volume = Radio('Volume', [(v, f'{v:.0%}') for v in tray_model.VOLUMES],
                   lambda: tray_model.speech_settings()[1],
                   lambda v: tray_model.run_speechctl('volume', f'{v:g}'))
    pace = Radio('Pace', [(v, pace_label(v)) for v in tray_model.PACES], tray_model.speech_pace,
                 tray_model.set_speech_pace)
    controls = (pause, skip, clear, volume.item, pace.item)   # the voices are greyed out by having none
    scaling, reset = size_items('speech')
    speech_on_top = on_top_check('speech')
    collapse = Check('Collapse when idle', tray_model.collapse_idle, tray_model.set_collapse_idle)
    for entry in (pause, skip, clear, voice.item, volume.item, pace.item, scaling.item, reset, collapse.item,
                  speech_on_top.item):
        speech_menu.append(entry)
    checks += [collapse, speech_on_top]
    radios += [voice, volume, pace, scaling]
    speech = Gtk.MenuItem(label='Speech')
    speech.set_submenu(speech_menu)
    menu.append(speech)
    menu.append(Gtk.SeparatorMenuItem())

    autostart = Check('Start at login', tray_model.starts_at_login, set_autostart)
    checks.append(autostart)
    menu.append(autostart.item)
    menu.append(item('Quit', lambda: tray_model.launcher('stop')))     # every widget, and with them this icon
    menu.show_all()
    indicator.set_menu(menu)

    refreshes = 0

    def show_voices(names):
        if list(voice.items) != names:
            voice.set_choices([(name, name) for name in names])

    def ask_voices():                           # off the main loop: speechctl can be slow
        names = tray_model.voices()
        GLib.idle_add(show_voices, names)

    def refresh():
        nonlocal refreshes
        track.set_label(now_playing())
        speaking.set_label(tray_model.speech_line())
        pause.set_label('Resume' if tray_model.paused() else 'Pause')
        has_speechctl = bool(tray_model.speechctl())
        for control in controls:
            control.set_sensitive(has_speechctl)
        if refreshes % VOICES_EVERY == 0:       # a voice installed meanwhile
            threading.Thread(target=ask_voices, daemon=True).start()
        refreshes += 1
        for check in checks:                    # changed outside the menu: a button, the launcher,
            check.sync()                        # a drag, the app menu or a terminal
        for radio in radios:
            radio.sync()
        scrolling.item.set_sensitive(lyrics_settings.shown())
        return True

    refresh()
    GLib.timeout_add_seconds(3, refresh)
    try:                                        # newer PyGObject moved this into GLibUnix
        gi.require_version('GLibUnix', '2.0')
        from gi.repository import GLibUnix
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, Gtk.main_quit)
    except (ValueError, ImportError):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, Gtk.main_quit)
    Gtk.main()


if __name__ == '__main__':
    main()
