#!/usr/bin/env python3
"""Mouse handling and placement for a conky widget: conky-mouse.py <widget>.

<widget> is the folder under src/ whose mouse.py names the widget (its config and cache
folders, launcher and window class) and does what its own controls do. The Spotify widget's
are the heart, play/pause, previous and next buttons, the seek bar, the volume slider and
the album art.

Conky's own Lua mouse hook never receives button presses under GNOME/XWayland, so this
helper subscribes to clicks on conky's window itself:
  - the widget's controls: pressed by a click or a tap (its mouse.py)
  - minimize and close: hide this widget, and only this one, until the tray menu or the
    launcher shows it again. The tray menu's Quit is what stops the widgets.
  - an edge or corner: resize the widget. A side edge changes its width, the top or bottom
    edge the height of the lyrics, and a corner both; the text keeps its size. An outline
    shows the new size while the button is held; on release it is saved (widget_size.py)
  - anywhere else: drag the widget; the position is saved on release
  - the mouse wheel: whatever the widget's mouse.py does with it there. For Spotify, over
    the volume slider it turns Spotify's volume down or up a step; over static lyrics (plain
    ones, which have no timing to follow, or synced ones under the tray menu's Static) it
    scrolls them a line at a time; and it does nothing anywhere else.

A touchscreen does the same with one finger, through XInput 2 touch events selected on the
window, which X then sends instead of the pointer events it would make up from the touch:
a tap on a control does what a click does, once the finger lifts on that control; a drag
seeks, sets the volume, resizes or moves like the mouse; and a vertical swipe over static
lyrics scrolls them a line for each line's height the finger moves. A second finger is ignored.

Hit areas come from nowplaying.py (regions.json, logical px, from the card's top left), since
the controls move when titles wrap. Conky's window is the widget's rounded card plus a margin
on every side (widget_size.SHADOW) that draw.lua paints the card's shadow in. Everything here
works on the card: the edges that resize, the position saved, the room left on a monitor.
The window's input shape is the card alone, so a click on the shadow goes to whatever is
under it.

The pointer over the card is the cursor theme's own arrow, set on the window like the resize
cursors are, never the X server's root cursor: under XWayland with native scaling that one is
loaded at the unscaled cursor size, and shows at half the size or less (Xcursor.size, which
X font cursors load at, carries the scale).

The position lives in ~/.config/<name>/position, not in conky.conf:
rewriting conky.conf makes conky reload and flash. Instead this helper keeps the window
at the saved spot, moving it back whenever conky places it elsewhere (startup, reloads).
The file holds 'x y monitor dx dy width scale': the root-window x y conky.conf starts the
window at, and the monitor the window was left on, its offset from that monitor's top left
corner, that monitor's width and the display scale, all as they were when saved. Adding or
removing a monitor moves the others in root coordinates, and can change XWayland's scale
and with it every coordinate, so the window is put back at its offset on its monitor,
scaled as that monitor's width has (the width is read with the origin, so the two always
agree), while that monitor is connected, and kept on the nearest one while it is not.

A change of Xft.dpi (the display scale, or the text scaling it also carries) needs
nowplaying.py and conky started again, since both read it once at start; this helper
saves the position and exits with RESCALED, and the launcher restarts the three of them.
It compares against CSN_DPI, the Xft.dpi the launcher read as it started nowplaying.py.

A resize only writes the size settings, once, on release: nowplaying.py lays the widget out
again and conky's window takes the new size, without a reload or a restart. Conky's window
shows a blank frame when it resizes, so a copy of the widget's pixels covers it until conky
has drawn at the new size.

Always on top is the window manager's state for conky's regular window, set and cleared
here as ~/.config/<name>/on-top (the tray menu's toggle) changes, so conky
never restarts for it.

Hidden is a flag file (~/.cache/<name>/hidden), one per widget, that the tray menu's
Show ticks and the launcher's show/hide commands also write; while it exists this helper
keeps conky's window unmapped and keeps running, so showing it again is instant.
"""
import ctypes, importlib.util, json, math, os, re, subprocess, sys, time

import widget_size

HERE = os.path.dirname(os.path.abspath(__file__))
# What a widget's name sets, in configure(): the folders and files below, and `hooks`, the
# widget's own mouse.py.
hooks = None
CONF = POSITION = SIZE = CACHE = REGIONS = LOG = HIDDEN = ON_TOP = None
WM_CLASS, OUTLINE, BUTTONS, HEIGHT_REGION = None, None, (), None
BUTTON_PRESS, MOTION_NOTIFY, BUTTON1_MASK = 4, 6, 1 << 8
WHEEL_UP, WHEEL_DOWN = 4, 5                       # X reports the wheel as button presses
BUTTON_PRESS_MASK, BUTTON_RELEASE_MASK, POINTER_MOTION_MASK = 1 << 2, 1 << 3, 1 << 6
CLIENT_MESSAGE, SUBSTRUCTURE_NOTIFY_MASK, SUBSTRUCTURE_REDIRECT_MASK = 33, 1 << 19, 1 << 20
CW_BACK_PIXMAP, CW_BACK_PIXEL, CW_BORDER_PIXEL = 1 << 0, 1 << 1, 1 << 3
CW_OVERRIDE_REDIRECT, CW_COLORMAP = 1 << 9, 1 << 13
US_POSITION, P_POSITION = 1 << 0, 1 << 2          # XSizeHints flags
COVER_HOLD = 0.1                                  # s: conky draws every 0.05 s
OUTLINE_WIDTH = 2                                 # logical px
CLICK_SLOP = 4                                    # logical px a press moves before it is a drag
TAP_SLOP = 8                                      # the same for a finger, which rolls as it lifts
EDGE = 6                                          # logical px along the border that resize
CORNER = 24                                       # how far from a corner both of its edges resize
RESCALED = 75                                     # exit status: Xft.dpi changed (the launcher's too)
HIDES = ('minimize', 'close')                     # the controls that hide the widget
# X cursor font shapes (X11/cursorfont.h), by the edges a press there resizes.
# '' is the arrow anywhere else on the card (left_ptr).
CURSORS = {'': 68, 'l': 70, 'r': 96, 't': 138, 'b': 16, 'lt': 134, 'rt': 136, 'lb': 12, 'rb': 14,
           'divider': 108}                      # a widget's divider: the left-right arrow with a bar
SHAPE_INPUT, SHAPE_SET, UNSORTED = 2, 0, 0         # X Shape extension
SHADOW = widget_size.SHADOW                        # logical px of shadow around the card
GENERIC_EVENT = 35                                 # an extension's event, XInput 2's among them
XI_TOUCH_BEGIN, XI_TOUCH_UPDATE, XI_TOUCH_END = 18, 19, 20
XI_ALL_MASTER_DEVICES = 1
TOUCH_TIMEOUT = 30                                 # s without a touch event before a finger counts as lifted

def configure(widget):
    """Sets this helper up for the widget in src/<widget>/, whose mouse.py says its name
    (the config and cache folders, the launcher, the window class), its controls and what
    they do. Run before anything else here."""
    global hooks, CONF, POSITION, SIZE, CACHE, REGIONS, LOG, HIDDEN, ON_TOP
    global WM_CLASS, OUTLINE, BUTTONS, HEIGHT_REGION
    folder = os.path.join(HERE, '..', widget)
    sys.path.insert(0, folder)
    spec = importlib.util.spec_from_file_location(f'{widget}_mouse', os.path.join(folder, 'mouse.py'))
    hooks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hooks)
    hooks.core = sys.modules[__name__]
    CONF = os.path.expanduser(f'~/.config/{hooks.NAME}')
    POSITION = os.path.join(CONF, 'position')
    SIZE = os.path.join(CONF, 'size')             # widget_size.py's settings
    CACHE = os.path.expanduser(f'~/.cache/{hooks.NAME}')
    REGIONS = os.path.join(CACHE, 'regions.json')
    LOG = os.path.join(CACHE, 'mouse.log')
    HIDDEN = os.path.join(CACHE, 'hidden')
    ON_TOP = os.path.join(CONF, 'on-top')         # 'off': not always on top
    WM_CLASS, OUTLINE, HEIGHT_REGION = hooks.WM_CLASS, hooks.OUTLINE, hooks.HEIGHT_REGION
    BUTTONS = hooks.BUTTONS + HIDES               # the controls a click or tap presses


x11 = ctypes.CDLL('libX11.so.6')
x11.XOpenDisplay.restype = ctypes.c_void_p
x11.XDefaultRootWindow.restype = ctypes.c_ulong
x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
x11.XSelectInput.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_long]
x11.XMoveWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int]
x11.XMapWindow.argtypes = x11.XUnmapWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
x11.XFlush.argtypes = [ctypes.c_void_p]
x11.XPending.argtypes = [ctypes.c_void_p]
x11.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
x11.XQueryPointer.argtypes = [ctypes.c_void_p, ctypes.c_ulong] + [ctypes.c_void_p] * 7
x11.XGetGeometry.argtypes = [ctypes.c_void_p, ctypes.c_ulong] + [ctypes.c_void_p] * 7
x11.XCreateFontCursor.restype = ctypes.c_ulong
x11.XCreateFontCursor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
x11.XDefineCursor.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong]
x11.XGetWindowAttributes.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p]
x11.XCreatePixmap.restype = ctypes.c_ulong
x11.XCreatePixmap.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
x11.XFreePixmap.argtypes = x11.XDestroyWindow.argtypes = x11.XMapRaised.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
x11.XCreateGC.restype = ctypes.c_void_p
x11.XCreateGC.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
x11.XFreeGC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
x11.XCopyArea.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p] + [ctypes.c_int] * 2 + \
    [ctypes.c_uint] * 2 + [ctypes.c_int] * 2
x11.XCreateWindow.restype = ctypes.c_ulong
x11.XMoveResizeWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_uint, ctypes.c_uint]
x11.XCreateWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_uint,
                              ctypes.c_uint, ctypes.c_uint, ctypes.c_int, ctypes.c_uint, ctypes.c_void_p,
                              ctypes.c_ulong, ctypes.c_void_p]
x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
x11.XInternAtom.restype = ctypes.c_ulong
x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
x11.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_long, ctypes.c_void_p]
x11.XGetWMNormalHints.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p]
x11.XSetWMNormalHints.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p]
# Windows vanish when conky restarts; don't let the resulting X errors kill the helper.
ERROR_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)(lambda d, e: 0)
x11.XSetErrorHandler(ERROR_HANDLER)
x11.XQueryExtension.argtypes = [ctypes.c_void_p, ctypes.c_char_p] + [ctypes.c_void_p] * 3
x11.XGetEventData.argtypes = x11.XFreeEventData.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
xext = ctypes.CDLL('libXext.so.6')
xext.XShapeCombineRectangles.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
                                         ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                         ctypes.c_int]
try:
    xi = ctypes.CDLL('libXi.so.6')
    xi.XIQueryVersion.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    xi.XISelectEvents.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_int]
except OSError:                                    # no touch, the mouse still works
    xi = None


class XButtonEvent(ctypes.Structure):
    _fields_ = [('type', ctypes.c_int), ('serial', ctypes.c_ulong), ('send_event', ctypes.c_int),
                ('display', ctypes.c_void_p), ('window', ctypes.c_ulong), ('root', ctypes.c_ulong),
                ('subwindow', ctypes.c_ulong), ('time', ctypes.c_ulong),
                ('x', ctypes.c_int), ('y', ctypes.c_int), ('x_root', ctypes.c_int), ('y_root', ctypes.c_int),
                ('state', ctypes.c_uint), ('button', ctypes.c_uint), ('same_screen', ctypes.c_int)]


class XClientMessageEvent(ctypes.Structure):
    _fields_ = [('type', ctypes.c_int), ('serial', ctypes.c_ulong), ('send_event', ctypes.c_int),
                ('display', ctypes.c_void_p), ('window', ctypes.c_ulong), ('message_type', ctypes.c_ulong),
                ('format', ctypes.c_int), ('data', ctypes.c_long * 5)]


class XWindowAttributes(ctypes.Structure):
    _fields_ = [('x', ctypes.c_int), ('y', ctypes.c_int), ('width', ctypes.c_int), ('height', ctypes.c_int),
                ('border_width', ctypes.c_int), ('depth', ctypes.c_int), ('visual', ctypes.c_void_p),
                ('root', ctypes.c_ulong), ('class_', ctypes.c_int), ('bit_gravity', ctypes.c_int),
                ('win_gravity', ctypes.c_int), ('backing_store', ctypes.c_int),
                ('backing_planes', ctypes.c_ulong), ('backing_pixel', ctypes.c_ulong),
                ('save_under', ctypes.c_int), ('colormap', ctypes.c_ulong), ('map_installed', ctypes.c_int),
                ('map_state', ctypes.c_int), ('all_event_masks', ctypes.c_long),
                ('your_event_mask', ctypes.c_long), ('do_not_propagate_mask', ctypes.c_long),
                ('override_redirect', ctypes.c_int), ('screen', ctypes.c_void_p)]


class XSetWindowAttributes(ctypes.Structure):
    _fields_ = [('background_pixmap', ctypes.c_ulong), ('background_pixel', ctypes.c_ulong),
                ('border_pixmap', ctypes.c_ulong), ('border_pixel', ctypes.c_ulong),
                ('bit_gravity', ctypes.c_int), ('win_gravity', ctypes.c_int),
                ('backing_store', ctypes.c_int), ('backing_planes', ctypes.c_ulong),
                ('backing_pixel', ctypes.c_ulong), ('save_under', ctypes.c_int),
                ('event_mask', ctypes.c_long), ('do_not_propagate_mask', ctypes.c_long),
                ('override_redirect', ctypes.c_int), ('colormap', ctypes.c_ulong),
                ('cursor', ctypes.c_ulong)]


class XSizeHints(ctypes.Structure):
    _fields_ = [('flags', ctypes.c_long)] + [(n, ctypes.c_int) for n in (
        'x', 'y', 'width', 'height', 'min_width', 'min_height', 'max_width', 'max_height',
        'width_inc', 'height_inc', 'min_aspect_x', 'min_aspect_y', 'max_aspect_x', 'max_aspect_y',
        'base_width', 'base_height', 'win_gravity')]


class XRectangle(ctypes.Structure):
    _fields_ = [('x', ctypes.c_short), ('y', ctypes.c_short),
                ('width', ctypes.c_ushort), ('height', ctypes.c_ushort)]


class XGenericEventCookie(ctypes.Structure):
    _fields_ = [('type', ctypes.c_int), ('serial', ctypes.c_ulong), ('send_event', ctypes.c_int),
                ('display', ctypes.c_void_p), ('extension', ctypes.c_int), ('evtype', ctypes.c_int),
                ('cookie', ctypes.c_uint), ('data', ctypes.c_void_p)]


class XIDeviceEvent(ctypes.Structure):
    # Up to the coordinates and flags; the button, valuator and modifier state after them
    # are not read.
    _fields_ = [('type', ctypes.c_int), ('serial', ctypes.c_ulong), ('send_event', ctypes.c_int),
                ('display', ctypes.c_void_p), ('extension', ctypes.c_int), ('evtype', ctypes.c_int),
                ('time', ctypes.c_ulong), ('deviceid', ctypes.c_int), ('sourceid', ctypes.c_int),
                ('detail', ctypes.c_int), ('root', ctypes.c_ulong), ('event', ctypes.c_ulong),
                ('child', ctypes.c_ulong), ('root_x', ctypes.c_double), ('root_y', ctypes.c_double),
                ('event_x', ctypes.c_double), ('event_y', ctypes.c_double), ('flags', ctypes.c_int)]


class XIEventMask(ctypes.Structure):
    _fields_ = [('deviceid', ctypes.c_int), ('mask_len', ctypes.c_int), ('mask', ctypes.c_void_p)]


class XEvent(ctypes.Union):
    # A motion event has the same layout as a button event up to its x and y.
    _fields_ = [('type', ctypes.c_int), ('xbutton', XButtonEvent), ('xcookie', XGenericEventCookie),
                ('pad', ctypes.c_long * 24)]


def log(msg):
    # Dated like nowplaying.log's lines, so the two logs line up across days.
    with open(LOG, 'a') as f:
        f.write(time.strftime('%F %T ') + msg + '\n')


def conky_window():
    tree = subprocess.run(['xwininfo', '-root', '-tree'], capture_output=True, text=True).stdout
    for line in tree.splitlines():
        if f'"{WM_CLASS}")' in line:
            return int(line.split()[0], 16)
    return None


def monitors():
    """[(x, y, w, h, primary, name)] in root-window coordinates."""
    out = subprocess.run(['xrandr', '--listmonitors'], capture_output=True, text=True).stdout
    mons = []
    for m in re.finditer(r'^\s*\d+: \+(\*?)(\S+) (\d+)/\d+x(\d+)/\d+\+(-?\d+)\+(-?\d+)', out, re.M):
        mons.append((int(m[5]), int(m[6]), int(m[3]), int(m[4]), m[1] == '*', m[2]))
    return mons


def nearest_monitor(x, y, w, h, mons=None):
    """The monitors() entry containing the window's center (or the nearest one), or None
    when xrandr lists none."""
    mons = monitors() if mons is None else mons
    if not mons:
        return None
    cx, cy = x + w // 2, y + h // 2
    def dist(m):
        mx, my, mw, mh = m[:4]
        dx = max(mx - cx, 0, cx - (mx + mw))
        dy = max(my - cy, 0, cy - (my + mh))
        return dx * dx + dy * dy
    return min(mons, key=dist)


def monitor_for(x, y, w, h, mons=None):
    """(x, y, w, h) of the monitor containing the window's center (or the nearest one), or
    None when xrandr lists none."""
    mon = nearest_monitor(x, y, w, h, mons)
    return mon[:4] if mon else None


def clamp_to_monitor(x, y, w, h, mons=None):
    """Keep the window fully on the monitor containing its center (or the nearest one)."""
    mon = monitor_for(x, y, w, h, mons)
    if not mon:
        return x, y
    mx, my, mw, mh = mon
    return min(max(x, mx), mx + mw - w), min(max(y, my), my + mh - h)


def geometry(d, win):
    root, x, y = ctypes.c_ulong(), ctypes.c_int(), ctypes.c_int()
    w, h, b, depth = ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint()
    x11.XGetGeometry(d, win, ctypes.byref(root), ctypes.byref(x), ctypes.byref(y),
                     ctypes.byref(w), ctypes.byref(h), ctypes.byref(b), ctypes.byref(depth))
    return x.value, y.value, w.value, h.value


def card_of(rect, s):
    """The card's (x, y, w, h) in a window at `rect`: the window less the shadow margin on
    every side, at display scale s."""
    x, y, w, h = rect
    m = SHADOW * s
    return x + m, y + m, w - 2 * m, h - 2 * m


def window_of(rect, s):
    """The window's (x, y, w, h) around a card at `rect`; card_of() turned round."""
    x, y, w, h = rect
    m = SHADOW * s
    return x - m, y - m, w + 2 * m, h + 2 * m


def on_card(x, y, w, h):
    """Whether card-relative (x, y) is on a w x h card."""
    return 0 <= x < w and 0 <= y < h


def set_input_shape(d, win, w, h, s):
    """Takes clicks on the card only, out of the window's w x h, so the shadow passes them to
    whatever is under it."""
    m = SHADOW * s
    rect = XRectangle(m, m, max(w - 2 * m, 1), max(h - 2 * m, 1))
    xext.XShapeCombineRectangles(d, win, SHAPE_INPUT, 0, 0, ctypes.byref(rect), 1, SHAPE_SET, UNSORTED)
    x11.XFlush(d)


def pointer(d, root):
    r, c = ctypes.c_ulong(), ctypes.c_ulong()
    rx, ry, wx, wy, mask = ctypes.c_int(), ctypes.c_int(), ctypes.c_int(), ctypes.c_int(), ctypes.c_uint()
    x11.XQueryPointer(d, root, ctypes.byref(r), ctypes.byref(c), ctypes.byref(rx), ctypes.byref(ry),
                      ctypes.byref(wx), ctypes.byref(wy), ctypes.byref(mask))
    return rx.value, ry.value, mask.value


def dpi():
    """Xft.dpi, 96 times the display scale, or None when xrdb has none. XWayland's scale
    follows the monitors connected, so adding or removing one can change it."""
    out = subprocess.run(['xrdb', '-query'], capture_output=True, text=True).stdout
    m = re.search(r'Xft\.dpi:\s*(\d+)', out)
    return int(m.group(1)) if m else None


def scale_of(at):
    """The display scale at Xft.dpi `at`, as conky.conf and nowplaying.py work it out."""
    return round((at or 96) / 96)


def scale():
    return scale_of(dpi())


def load_position():
    """(x, y, anchor), anchor being (monitor, dx, dy, width, scale) or None for a file
    without one, or None when no position is saved."""
    try:
        with open(POSITION) as f:
            fields = f.read().split()
        x, y = int(fields[0]), int(fields[1])
    except (OSError, ValueError, IndexError):
        return None
    try:
        anchor = (fields[2], *map(int, fields[3:7])) if len(fields) >= 7 else None
    except ValueError:
        anchor = None
    if anchor and min(anchor[3:]) <= 0:                 # resolve() divides by the width and scale
        anchor = None
    return x, y, anchor


def save_position(x, y, anchor):
    os.makedirs(CONF, exist_ok=True)
    with open(POSITION + '.tmp', 'w') as f:            # conky.conf reads it at start
        f.write(' '.join(map(str, (x, y, *(anchor or ())))) + '\n')
    os.replace(POSITION + '.tmp', POSITION)


def anchor_for(x, y, w, h, mons, s):
    """The anchor for a window at (x, y, w, h) at display scale s: the monitor it is on,
    its offset there, that monitor's width and s. None when xrandr lists no monitors."""
    mon = nearest_monitor(x, y, w, h, mons)
    return (mon[5], x - mon[0], y - mon[1], mon[2], s) if mon else None


def resolve(saved, mons, s):
    """The saved position for the monitors `mons` at display scale s: (x, y, anchor). With
    the anchor's monitor connected, at its offset there, scaled as the monitor's width has;
    without it, where it was saved, scaled as the display scale has. Not yet kept on a
    monitor."""
    x, y, anchor = saved
    if not anchor:
        return saved
    name, dx, dy, width, saved_s = anchor
    mon = next((m for m in mons if m[5] == name), None)
    if mon:
        if mon[2] != width:
            dx, dy = (round(v * mon[2] / width) for v in (dx, dy))
        return mon[0] + dx, mon[1] + dy, (name, dx, dy, mon[2], s)
    if saved_s != s:
        x, y, dx, dy, width = (round(v * s / saved_s) for v in (x, y, dx, dy, width))
    return x, y, (name, dx, dy, width, s)


def remember(x, y, w, h):
    """Save (x, y) as the position of a w x h window, anchored to the monitor it is on."""
    save_position(x, y, anchor_for(x, y, w, h, monitors(), scale()))


def resize_edges(x, y, w, h, s):
    """The edges a press at window-relative (x, y) drags: '' for none (a move), else 'l' or
    'r' and/or 't' or 'b', as in 'rb' for the bottom right corner."""
    edge, corner = EDGE * s, CORNER * s
    horiz = 'l' if x < edge else 'r' if x >= w - edge else ''
    vert = 't' if y < edge else 'b' if y >= h - edge else ''
    if horiz and not vert:                     # along an edge but close to a corner: both
        vert = 't' if y < corner else 'b' if y >= h - corner else ''
    elif vert and not horiz:
        horiz = 'l' if x < corner else 'r' if x >= w - corner else ''
    return horiz + vert


def dragged(settings, edges, dx, dy, room_x, room_y, s):
    """The size settings once the pointer has dragged `edges` by (dx, dy) window px: the side
    edges change the width, the top and bottom the lyrics' height, a corner both. The window
    grows by at most (room_x, room_y), what its monitor has left; s is the display scale."""
    width, height, text = settings
    limits = widget_size.LIMITS
    if 'l' in edges or 'r' in edges:
        out = min(dx if 'r' in edges else -dx, room_x)     # how far the edge moved outwards
        width = widget_size.clamp(width + math.floor(out / s), *limits[0])
    if 't' in edges or 'b' in edges:
        out = min(dy if 'b' in edges else -dy, room_y)
        height = widget_size.clamp(height + math.floor(out / s), *limits[1])
    return width, height, text


def set_cursor(d, win, edges, cache={}):
    """The resize cursor for `edges`, or the arrow for ''. Both come from the cursor theme
    at Xcursor.size, through libX11's font cursors."""
    if edges not in cache:
        cache[edges] = x11.XCreateFontCursor(d, CURSORS[edges])
    x11.XDefineCursor(d, win, cache[edges])
    x11.XFlush(d)


def cover(d, root, win, rect, src):
    """An unmanaged window at `rect` (root x, y, w, h) showing `win`'s pixels from `src`
    (window x, y), transparency and all: it hides the blank frame conky's window shows while
    it resizes. Taken down with uncover()."""
    x, y, w, h = rect
    attrs = XWindowAttributes()
    x11.XGetWindowAttributes(d, win, ctypes.byref(attrs))
    pixmap = x11.XCreatePixmap(d, win, w, h, attrs.depth)
    gc = x11.XCreateGC(d, pixmap, 0, None)
    x11.XCopyArea(d, win, pixmap, gc, src[0], src[1], w, h, 0, 0)
    x11.XFreeGC(d, gc)
    # A 32-bit visual needs its own colormap and a border pixel, or the window is refused.
    new = XSetWindowAttributes(background_pixmap=pixmap, border_pixel=0, override_redirect=1,
                               colormap=attrs.colormap)
    shade = x11.XCreateWindow(d, root, x, y, w, h, 0, attrs.depth, 1, attrs.visual,
                              CW_BACK_PIXMAP | CW_BORDER_PIXEL | CW_OVERRIDE_REDIRECT | CW_COLORMAP,
                              ctypes.byref(new))
    x11.XFreePixmap(d, pixmap)                  # the window keeps its own reference
    x11.XMapRaised(d, shade)
    x11.XSync(d, False)
    return shade


def uncover(d, shade):
    if shade:
        x11.XDestroyWindow(d, shade)
        x11.XFlush(d)


def outline(d, root):
    """Four thin unmanaged windows, not mapped yet, that frame a rectangle between them."""
    attrs = XSetWindowAttributes(background_pixel=OUTLINE, override_redirect=1)
    return [x11.XCreateWindow(d, root, 0, 0, 1, 1, 0, 0, 1, None,
                              CW_BACK_PIXEL | CW_OVERRIDE_REDIRECT, ctypes.byref(attrs))
            for _ in range(4)]


def place_outline(d, frame, x, y, w, h, t):
    for part, (px, py, pw, ph) in zip(frame, ((x, y, w, t), (x, y + h - t, w, t),
                                              (x, y, t, h), (x + w - t, y, t, h))):
        x11.XMoveResizeWindow(d, part, px, py, max(pw, 1), max(ph, 1))
        x11.XMapRaised(d, part)
    x11.XFlush(d)


def resized(start, edges, old, new, s, tall):
    """The window's geometry at size settings `new`, from `start` (x, y, w, h) at `old`:
    the edges across from the dragged ones stay put. Without the region whose height the
    second size setting is (HEIGHT_REGION) the height stays."""
    x, y, w, h = start
    nw = w + round((new[0] - old[0]) * s)
    nh = h + (round((new[1] - old[1]) * s) if tall else 0)
    return x + (w - nw if 'l' in edges else 0), y + (h - nh if 't' in edges else 0), nw, nh


def near(a, b):
    return abs(a[0] - b[0]) <= 8 and abs(a[1] - b[1]) <= 8   # conky rounds, and adds its border


def follow_pointer(d, root):
    """A tracker for the mouse: each call gives the pointer's root (x, y) and whether
    button 1 is still held."""
    def track():
        x, y, mask = pointer(d, root)
        return x, y, bool(mask & BUTTON1_MASK)
    return track


def resize(d, root, win, edges, s, regions, track):
    """Outline the new size while `track` (follow_pointer() or a Touch) drags `edges`; on
    release, save it and hold a copy of the widget over conky's window while it takes the
    new size. Returns the window's new position and size, or None if nothing changed."""
    old = new = widget_size.load(SIZE)
    window = geometry(d, win)
    start = wx, wy, w, h = card_of(window, s)
    mon = monitor_for(wx, wy, w, h)
    if mon:                                     # the room on the dragged side, to the monitor's edge
        mx, my, mw, mh = mon
        room_x = max(wx - mx if 'l' in edges else mx + mw - wx - w, 0)
        room_y = max(wy - my if 't' in edges else my + mh - wy - h, 0)
    else:
        room_x = room_y = math.inf
    px, py, held = track()
    log(f'resize start: {edges} at {old}, card {wx},{wy} {w}x{h}')
    frame = outline(d, root)
    g = start
    try:
        while held:
            nx, ny, held = track()
            new = dragged(old, edges, nx - px, ny - py, room_x, room_y, s)
            g = resized(start, edges, old, new, s, regions.get(HEIGHT_REGION))
            if (nx, ny) != (px, py):
                place_outline(d, frame, *g, round(OUTLINE_WIDTH * s))
            time.sleep(0.01)
    finally:
        for part in frame:
            x11.XDestroyWindow(d, part)
        x11.XFlush(d)
    if new == old:
        log('resize end: unchanged')
        return None
    shade = cover(d, root, win, window, (0, 0))
    goal = window_of(g, s)
    try:
        widget_size.save(new, SIZE)
        # nowplaying.py lays the widget out again and conky resizes its window, from its top
        # left corner; move it into place, then keep the copy up while conky draws there.
        deadline, shown = time.monotonic() + 1, None
        while time.monotonic() < deadline and (shown is None or time.monotonic() < shown):
            x, y, cw, ch = geometry(d, win)
            if near((cw, ch), goal[2:]):
                if (x, y) != goal[:2]:
                    x11.XMoveWindow(d, win, *goal[:2])
                    x11.XFlush(d)
                elif shown is None:
                    shown = time.monotonic() + COVER_HOLD
            time.sleep(0.01)
    finally:
        uncover(d, shade)
    set_input_shape(d, win, *goal[2:], s)
    x, y = clamp_to_monitor(*g)
    log(f'resize end: {new}, card {g[2]}x{g[3]} -> saved {x},{y}')
    return x, y, *g[2:]


def clicked(start, s, track, slop=CLICK_SLOP):
    """Whether the press at root (x, y) `start` that `track` (follow_pointer() or a Touch)
    follows lets go before it moves `slop` logical px from there: a click or tap, not the
    start of a drag."""
    held = True
    while held:
        nx, ny, held = track()
        if max(abs(nx - start[0]), abs(ny - start[1])) > slop * s:
            return False
        time.sleep(0.01)
    return True


def drag(d, root, win, s, track, start=None):
    """Move the window with `track` (follow_pointer() or a Touch) while it is held, from
    root (x, y) `start` if given, else from where it is first read; returns the card's
    position, kept on its monitor, and size."""
    wx, wy, w, h = geometry(d, win)
    px, py, held = track()
    if start:
        px, py = start
    log(f'drag start: window {wx},{wy} pointer {px},{py}')
    last_logged = 0.0
    while held:
        nx, ny, held = track()
        x11.XMoveWindow(d, win, wx + nx - px, wy + ny - py)
        x11.XFlush(d)
        if time.monotonic() - last_logged > 0.25:
            last_logged = time.monotonic()
            log(f'  pointer {nx},{ny} held {held}')
        time.sleep(0.01)
    x, y, cw, ch = card_of(geometry(d, win), s)
    cx, cy = clamp_to_monitor(x, y, cw, ch)
    log(f'drag end: card {x},{y} -> saved {cx},{cy}')
    return cx, cy, cw, ch


def load_on_top():
    try:
        with open(ON_TOP) as f:
            return f.read().strip() != 'off'
    except OSError:
        return True


def hint_position(d, win, x, y):
    """Mark (x, y) as the window's own position in WM_NORMAL_HINTS, keeping any size hints
    already there. Unmapping withdraws the window, and on the next map the window manager
    places it anew (mutter: the middle of some monitor) unless the hints carry a
    position; without them the widget would show there until moved back."""
    hints, supplied = XSizeHints(), ctypes.c_long()
    if not x11.XGetWMNormalHints(d, win, ctypes.byref(hints), ctypes.byref(supplied)):
        hints = XSizeHints()
    hints.flags |= US_POSITION | P_POSITION
    hints.x, hints.y = x, y
    x11.XSetWMNormalHints(d, win, ctypes.byref(hints))


def has_above(win):
    """Whether the window manager has the window above others now (_NET_WM_STATE)."""
    out = subprocess.run(['xprop', '-id', hex(win), '_NET_WM_STATE'], capture_output=True, text=True).stdout
    return '_NET_WM_STATE_ABOVE' in out


def set_above(d, root, win, above):
    """Ask the window manager to keep the window above others, or not (EWMH _NET_WM_STATE)."""
    ev = XClientMessageEvent(type=CLIENT_MESSAGE, window=win, format=32,
                             message_type=x11.XInternAtom(d, b'_NET_WM_STATE', False))
    ev.data[:] = [1 if above else 0, x11.XInternAtom(d, b'_NET_WM_STATE_ABOVE', False), 0, 1, 0]
    x11.XSendEvent(d, root, False, SUBSTRUCTURE_REDIRECT_MASK | SUBSTRUCTURE_NOTIFY_MASK, ctypes.byref(ev))
    x11.XFlush(d)


def load_regions(cache={}):
    """regions.json, read again only when nowplaying.py has rewritten it: pointer motion
    along the border asks for it many times a second."""
    try:
        mtime = os.stat(REGIONS).st_mtime_ns
        if cache.get('mtime') != mtime:
            with open(REGIONS) as f:
                cache.update(mtime=mtime, regions=json.load(f))
        return cache['regions']
    except (OSError, ValueError):
        return {}


def region_at(regions, s, x, y):
    """The control under window-relative (x, y), if any."""
    for name in hooks.REGIONS_ORDER:
        r = regions.get(name)
        if r and r[0] * s <= x <= r[2] * s and r[1] * s <= y <= r[3] * s:
            return name
    return None


def tap(regions, s, x, y, start, hit, track):
    """Whether a finger that touched down on the control `hit` at window-relative (x, y),
    root `start`, lifts on that control. Waits for it to lift."""
    while True:
        fx, fy, down = track()
        if not down:
            break
        time.sleep(0.01)
    return region_at(regions, s, x + fx - start[0], y + fy - start[1]) == hit


def pull(d, root, win, s, regions, hit, edges, track, at, touch=False):
    """What a press off the plain buttons does, following `track` from card-relative (x, y)
    and root (x, y) `at` until release: whatever the widget does with its controls (its
    mouse.py: seek, set the volume, pick a colour from the art); resize from an edge; scroll
    static lyrics with a finger; or else move the widget."""
    x, y, start = at
    if hooks.pull_control(d, root, win, s, regions, hit, track, at, touch):
        pass
    elif edges:
        placed = resize(d, root, win, edges, s, regions, track)
        if placed:
            remember(*placed)
    elif touch and hooks.scrollable(regions, s, x, y):
        hooks.swipe(regions, s, x, y, start[1], track)
    else:
        remember(*drag(d, root, win, s, track))


def press(d, win, hit):
    """Does what a click or tap on the control `hit` (one of BUTTONS) does."""
    if hit in HIDES:
        os.makedirs(CACHE, exist_ok=True)
        open(HIDDEN, 'w').close()
        x11.XUnmapWindow(d, win)
        x11.XFlush(d)
        log(hit)
    else:
        hooks.press(d, win, hit)


def touch_opcode(d):
    """XInput's major opcode, which its touch events carry, or None when the server has no
    XInput 2.2 (touch) or libXi is missing."""
    if not xi:
        return None
    opcode, first_event, first_error = ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
    if not x11.XQueryExtension(d, b'XInputExtension', ctypes.byref(opcode),
                               ctypes.byref(first_event), ctypes.byref(first_error)):
        return None
    major, minor = ctypes.c_int(2), ctypes.c_int(2)
    if xi.XIQueryVersion(d, ctypes.byref(major), ctypes.byref(minor)) != 0:
        return None
    return opcode.value if (major.value, minor.value) >= (2, 2) else None


def touch_mask(*evtypes):
    """An XI event mask with the bits for `evtypes` set, as XISetMask() sets them."""
    mask = bytearray(max(evtypes) // 8 + 1)
    for t in evtypes:
        mask[t // 8] |= 1 << (t % 8)
    return bytes(mask)


def select_touch(d, win):
    """Ask for the window's touch events. X only takes the three together."""
    mask = ctypes.create_string_buffer(touch_mask(XI_TOUCH_BEGIN, XI_TOUCH_UPDATE, XI_TOUCH_END))
    em = XIEventMask(XI_ALL_MASTER_DEVICES, len(mask.raw), ctypes.cast(mask, ctypes.c_void_p))
    xi.XISelectEvents(d, win, ctypes.byref(em), 1)


def touch_event(d, ev, opcode):
    """(evtype, touch id, window, root x, root y, event x, event y) for an XInput touch
    event, or None for any other event. Frees the event's data."""
    cookie = ev.xcookie
    if ev.type != GENERIC_EVENT or cookie.extension != opcode:
        return None
    if not x11.XGetEventData(d, ctypes.byref(cookie)):
        return None
    try:
        if cookie.evtype not in (XI_TOUCH_BEGIN, XI_TOUCH_UPDATE, XI_TOUCH_END):
            return None
        e = ctypes.cast(cookie.data, ctypes.POINTER(XIDeviceEvent)).contents
        return cookie.evtype, e.detail, e.event, e.root_x, e.root_y, e.event_x, e.event_y
    finally:
        x11.XFreeEventData(d, ctypes.byref(cookie))


class Touch:
    """A tracker for one finger, as follow_pointer() is for the mouse: each call reads the
    pending events and gives the finger's root (x, y) and whether it is still down. Other
    events that arrive meanwhile, another finger's among them, are dropped, as the mouse's
    loops leave them unread."""

    def __init__(self, d, opcode, touch_id, x, y):
        self.d, self.opcode, self.id = d, opcode, touch_id
        self.x, self.y, self.down = x, y, True
        self.last = time.monotonic()
        self.ev = XEvent()

    def __call__(self):
        while self.down and x11.XPending(self.d):
            x11.XNextEvent(self.d, ctypes.byref(self.ev))
            t = touch_event(self.d, self.ev, self.opcode)
            if t and t[1] == self.id and t[0] != XI_TOUCH_BEGIN:
                self.x, self.y, self.last = t[3], t[4], time.monotonic()
                self.down = t[0] != XI_TOUCH_END
        if self.down and time.monotonic() - self.last > TOUCH_TIMEOUT:
            self.down = False                    # an end that never came: let go
        return round(self.x), round(self.y), self.down


def main(widget):
    configure(widget)
    hooks.start()
    d = ctypes.c_void_p(x11.XOpenDisplay(None))
    root = x11.XDefaultRootWindow(d)
    win, last_check, hidden = None, 0.0, None   # None: not known, e.g. after a restart
    cursor = None                                # the edges whose cursor win shows; None: not set
    shaped, last_shape = None, 0.0               # (win, w, h, s) the input shape was set for
    above, last_on_top = None, 0.0               # the always-on-top state win has; None: not set
    logged_on_top = None
    opcode = touch_opcode(d)
    log('touch: XInput 2.2 present' if opcode else 'touch: no XInput 2.2, mouse only')
    s = scale()                                  # refreshed on each click; motion uses the last
    start_dpi = int(os.environ.get('CSN_DPI') or 0) or dpi()   # what nowplaying.py started at
    ev = XEvent()
    while True:
        now = time.monotonic()
        # Conky rebuilds its window on reloads, often under the same id, which silently drops
        # our selection, its position and its always-on-top state -- so re-select, re-place and
        # re-apply every second.
        if now - last_check > 1:
            last_check = now
            mons, at, saved = monitors(), dpi(), load_position()
            resolved = saved and resolve(saved, mons, scale_of(at))
            if at and start_dpi and at != start_dpi:
                if saved:
                    save_position(*resolved)            # what conky.conf starts the window at
                log(f'display scale changed: {start_dpi} -> {at} dpi, restarting')
                sys.exit(RESCALED)
            current = conky_window()
            if current:
                if current != win:
                    log(f'attached to 0x{current:x}')
                win = current
                above = has_above(win)                 # sent below only if it differs: mutter restacks
                                                       # the window on every request, even a no-op
                x11.XSelectInput(d, win, BUTTON_PRESS_MASK | BUTTON_RELEASE_MASK | POINTER_MOTION_MASK)
                if opcode:
                    select_touch(d, win)
                # A rebuilt window has neither the cursor nor the input shape: set both again.
                cursor = cursor or ''                  # the arrow until the pointer says otherwise
                set_cursor(d, win, cursor)
                shaped = None
                ws = scale_of(at)
                x, y, w, h = card_of(geometry(d, win), ws)
                target = clamp_to_monitor(*resolved[:2], w, h, mons) if saved else (x, y)
                window_target = window_of((*target, w, h), ws)[:2]
                if (x, y) != target:
                    x11.XMoveWindow(d, win, *window_target)
                if saved:                              # a file from before anchors gets one here
                    anchor = resolved[2] or anchor_for(*target, w, h, mons, scale_of(at))
                    if (*target, anchor) != saved:     # x y for conky.conf; the anchor stays
                        save_position(*target, anchor)
                # Unmapped again every second while hidden, since a conky reload maps it.
                hide = os.path.exists(HIDDEN)
                if hide:
                    x11.XUnmapWindow(d, win)
                elif hidden is not False:              # a no-op when already mapped
                    hint_position(d, win, *window_target)
                    x11.XMapWindow(d, win)
                    above = None                       # the window manager forgets it when unmapped
                    if hidden:
                        log('shown')
                hidden = hide
                x11.XFlush(d)
        # The input shape follows the window's size, which changes with a title's wrapping,
        # within a tenth of a second; conky's reloads are covered by the reset above.
        if win and now - last_shape > 0.1:
            last_shape = now
            _, _, w, h = geometry(d, win)
            if (win, w, h, s) != shaped:
                set_input_shape(d, win, w, h, s)
                shaped = (win, w, h, s)
        # The tray's toggle takes effect within a tenth of a second.
        if win and not hidden and now - last_on_top > 0.1:
            last_on_top = now
            want = load_on_top()
            if want != above:
                set_above(d, root, win, want)
                above = want
                if want != logged_on_top:
                    log(f'always on top: {want}')
                    logged_on_top = want
        while x11.XPending(d):
            x11.XNextEvent(d, ctypes.byref(ev))
            b = ev.xbutton
            if ev.type == MOTION_NOTIFY and b.window == win:
                _, _, w, h = card_of(geometry(d, win), s)
                x, y = b.x - SHADOW * s, b.y - SHADOW * s    # card-relative
                edges = resize_edges(x, y, w, h, s) if on_card(x, y, w, h) else ''
                if edges:
                    regions = load_regions()
                    if region_at(regions, s, x, y):
                        edges = ''               # a control reaching the border wins
                    else:
                        edges = hooks.without_idle_edges(edges, regions)
                elif on_card(x, y, w, h) and region_at(load_regions(), s, x, y) == 'divider':
                    edges = 'divider'            # the resize cursor over the divider between columns
                if edges != cursor:
                    set_cursor(d, win, edges)
                    cursor = edges
            elif ev.type == BUTTON_PRESS and b.button in (WHEEL_UP, WHEEL_DOWN) and b.window == win:
                hooks.wheel(load_regions(), s, b.x - SHADOW * s, b.y - SHADOW * s, b.button == WHEEL_DOWN)
            elif ev.type == BUTTON_PRESS and b.button == 1 and b.window == win:
                s = scale()
                _, _, w, h = card_of(geometry(d, win), s)
                x, y = b.x - SHADOW * s, b.y - SHADOW * s    # card-relative
                if not on_card(x, y, w, h):
                    continue                     # the shadow, while the input shape is not set
                regions = load_regions()
                hit = region_at(regions, s, x, y)
                edges = resize_edges(x, y, w, h, s)
                edges = hooks.without_idle_edges(edges, regions)
                if hit in BUTTONS:
                    press(d, win, hit)
                    if hit in HIDES:
                        hidden = True
                else:
                    pull(d, root, win, s, regions, hit, edges, follow_pointer(d, root),
                         (x, y, (b.x_root, b.y_root)))
            elif ev.type == GENERIC_EVENT and opcode:
                t = touch_event(d, ev, opcode)
                if not (t and t[0] == XI_TOUCH_BEGIN and t[2] == win):
                    continue
                s = scale()
                _, _, w, h = card_of(geometry(d, win), s)
                x, y = t[5] - SHADOW * s, t[6] - SHADOW * s    # card-relative
                if not on_card(x, y, w, h):
                    continue
                regions = load_regions()
                hit = region_at(regions, s, x, y)
                edges = hooks.without_idle_edges(resize_edges(x, y, w, h, s), regions)
                start = round(t[3]), round(t[4])
                finger = Touch(d, opcode, t[1], *start)
                what = hit or edges or ('lyrics' if hooks.scrollable(regions, s, x, y) else 'card')
                log(f'touch at {round(x)},{round(y)}: {what}')
                if hit in BUTTONS:               # pressed once it lifts, if still on the control
                    if tap(regions, s, x, y, start, hit, finger):
                        press(d, win, hit)
                        if hit in HIDES:
                            hidden = True
                    else:
                        log(f'touch: lifted off {hit}')
                else:
                    pull(d, root, win, s, regions, hit, edges, finger, (x, y, start), touch=True)
        time.sleep(0.02)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit('usage: conky-mouse.py <widget>')
    main(sys.argv[1])
