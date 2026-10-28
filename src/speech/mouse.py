"""The speech widget's part of the mouse helper, loaded by conky-mouse.py when it is started
as `conky-mouse.py speech`: its name, window class and controls.

conky-mouse.py gives this module itself as `core`, for the window handling it shares.
"""

NAME = 'conky-widgets/speech'                  # the config and cache folders under ~/.config, ~/.cache
WM_CLASS = 'ConkySpeechQueue'                  # conky.conf's own_window_class
OUTLINE = 0x5e9cf0                             # the outline a resize shows
BUTTONS = ()                                   # the controls a click or tap presses
REGIONS_ORDER = ('minimize', 'close')          # the regions a press looks through, in order
core = None                                    # conky-mouse.py's module, set when it loads this one


def start():
    pass


def press(d, win, hit):
    pass


def pull_control(d, root, win, s, regions, hit, track, at, touch):
    return False


def without_idle_edges(edges, regions):
    return edges


def scroll_lyrics(regions, s, x, y, down):
    return None


def scrollable(regions, s, x, y):
    return False


def swipe(regions, s, x, y, y0, track):
    pass
