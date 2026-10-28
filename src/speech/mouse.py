"""The speech widget's part of the mouse helper, loaded by conky-mouse.py when it is started
as `conky-mouse.py speech`: its name, window class and controls, every one of which runs
speechctl (tray_model.py's, from PATH or the path ~/.config/conky-widgets/speech/speechctl
holds).

  - skip, next, pause/resume: a click or tap runs `speechctl skip`, `next` and `toggle`
  - the voice drop down: a click or tap opens the list of voices over the card; picking one
    runs `speechctl voice <name>`. While it is open this helper holds the pointer and the
    keyboard, so a click anywhere else and Escape close it, and the wheel or a swipe scrolls it
  - the volume slider: a click, tap or drag along it runs `speechctl volume <level>` where it
    is let go, a tenth at a time from 0 to 2.0
  - a session's On / Alerts / Off: a click or tap runs `speechctl speech <id> on|alerts|off`
  - the wheel: over the volume slider or its speaker it turns it down or up, over the closed
    drop down it steps through the voices, over a session's setting it moves it a segment along, and over the rest of the
    list it scrolls the list a row at a time; a finger swiped over the list scrolls it too

conky-mouse.py gives this module itself as `core`, for the window handling it shares.
"""
import ctypes, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import tray_model  # noqa: E402

NAME = 'conky-widgets/speech'                  # the config and cache folders under ~/.config, ~/.cache
WM_CLASS = 'ConkySpeechQueue'                  # conky.conf's own_window_class
OUTLINE = 0x5e9cf0                             # the outline a resize shows
# The buttons speechqueue.py writes the regions of, and what each runs.
COMMANDS = {'skip': ('skip',), 'next': ('next',), 'pause': ('toggle',)}
BUTTONS = tuple(COMMANDS)                      # the controls a click or tap presses
REGIONS_ORDER = BUTTONS + ('minimize', 'close', 'volume', 'voice')   # the regions a press looks through, in order
VOLUME_TOP = 2.0                               # speechctl's loudest volume, the slider's right end
HEIGHT_REGION = 'list'                         # the region the second size setting is the height of
SETTINGS = ('on', 'alerts', 'off')             # a session's segments, left to right
CACHE = os.path.expanduser(f'~/.cache/{NAME}')
LIST_SCROLL = os.path.join(CACHE, 'list-scroll')   # how many rows the list is scrolled, for draw.lua
VOLUME_PREVIEW = os.path.join(CACHE, 'volume-preview')   # the level under the pointer, for draw.lua
VOICE_MENU = os.path.join(CACHE, 'voice-menu')   # "<first voice shown> <voice under the pointer>" while the list is open
MENU_TIMEOUT = 20.0                            # s an open list waits before it closes itself
KEY_PRESS, ESCAPE = 2, 0xff1b                  # X's key press event, and the Escape keysym
GRAB_SUCCESS, GRAB_ASYNC = 0, 1
core = None                                    # conky-mouse.py's module, set when it loads this one


def start():
    """Clears the preview and the open list a previous run left behind if it was killed
    mid-drag or mid-list."""
    for path in (VOLUME_PREVIEW, VOICE_MENU):
        try:
            os.remove(path)
        except OSError:
            pass


def speechctl(*args):
    """Runs speechctl with `args`, and logs it."""
    ran = tray_model.run_speechctl(*args)
    core.log('speechctl ' + ' '.join(args) + ('' if ran else ': no speechctl'))


def press(d, win, hit):
    """Does what a click or tap on the control `hit` (one of BUTTONS) does."""
    speechctl(*COMMANDS[hit])


def inside(r, s, x, y):
    return bool(r) and r[0] * s <= x <= r[2] * s and r[1] * s <= y <= r[3] * s


def offset(regions):
    """How many rows the list is scrolled, within what it can scroll."""
    last = (regions.get('list_scroll') or [0])[0]
    try:
        with open(LIST_SCROLL) as f:
            at = int(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        at = 0
    return min(max(at, 0), last)


def row_at(regions, s, x, y):
    """The session row under card-relative (x, y), and whether (x, y) is on its setting's
    segments (the row's first line, from On's left to Off's right); (None, False) off the list."""
    area, scroll = regions.get('list'), regions.get('list_scroll')
    if not (inside(area, s, x, y) and scroll):
        return None, False
    at = y / s - area[1] + offset(regions) * scroll[1]       # px down the whole list
    for row in regions.get('rows', ()):
        if row['top'] <= at < row['bottom']:
            on_control = (at < row['top'] + scroll[1] and
                          row['on'][0] * s <= x <= row['off'][1] * s)
            return row, on_control
    return None, False


def segment_at(regions, s, x, y):
    """(session id, setting) of the segment under card-relative (x, y), or None."""
    row, on_control = row_at(regions, s, x, y)
    if not on_control:
        return None
    for key in SETTINGS:
        if row[key][0] * s <= x <= row[key][1] * s:
            return row['id'], key
    return None


def set_volume(d, win, regions, s, track):
    """Follow `track` (follow_pointer() or a Touch) along the volume slider, showing the level
    under it (draw.lua draws the preview until speechqueue.py reports the level), and set the
    speech volume where it is let go. speechctl runs unwaited, so it runs once, at the end,
    where runs along the way could land out of order."""
    bx0, bx1 = regions['volume_bar']
    wx, _, _, _ = core.card_of(core.geometry(d, win), s)
    os.makedirs(CACHE, exist_ok=True)
    level, held = 0.0, True
    try:
        while held:
            px, _, held = track()
            fraction = min(max((px - wx - bx0 * s) / ((bx1 - bx0) * s), 0.0), 1.0)
            level = round(fraction * VOLUME_TOP, 1)
            with open(VOLUME_PREVIEW + '.tmp', 'w') as f:
                f.write(f'{level / VOLUME_TOP:.4f}')
            os.replace(VOLUME_PREVIEW + '.tmp', VOLUME_PREVIEW)
            time.sleep(0.02)
        speechctl('volume', f'{level:.1f}')
        time.sleep(0.6)  # keep the preview until speechqueue.py reports the new level
    finally:
        # a preview left behind would hold the slider at it, so it goes however the drag ends
        try:
            os.remove(VOLUME_PREVIEW)
        except OSError:
            pass


def menu_at(menu, x, y, scroll):
    """The index of the voice under card-relative (x, y) logical px in the open list `menu`
    (regions.json's), scrolled `scroll` voices down; None off its rows."""
    x0, top, x1, bottom = menu['box']
    top += menu['pad']
    rows = min(menu['rows'], len(menu['names']) - scroll)
    if not (x0 <= x <= x1 and top <= y < top + rows * menu['item_h']):
        return None
    return scroll + int((y - top) // menu['item_h'])


def menu_scroll(menu, scroll, rows):
    """`scroll` moved `rows` voices down (up when negative), within the list."""
    return min(max(scroll + rows, 0), max(len(menu['names']) - menu['rows'], 0))


def write_menu(scroll, hover):
    os.makedirs(CACHE, exist_ok=True)
    with open(VOICE_MENU + '.tmp', 'w') as f:
        f.write(f'{scroll} {hover}')
    os.replace(VOICE_MENU + '.tmp', VOICE_MENU)


def run_menu(menu, events, now=time.monotonic, sleep=time.sleep):
    """Shows the open voice list until it is closed, and returns the name picked, or None.
    `events()` gives the card-relative logical-px events that arrived since it was last
    called: ('move', x, y), ('press', x, y), ('wheel', down), ('scroll', rows) and ('escape',).
    A press on a voice picks it and one anywhere else closes the list; it closes by itself
    after MENU_TIMEOUT without an event. draw.lua draws it from VOICE_MENU for as long as this
    runs."""
    current = menu.get('current', -1)
    scroll = menu_scroll(menu, 0, current - menu['rows'] // 2 if current >= menu['rows'] else 0)
    pointer, hover, shown = None, -1, None
    deadline = now() + MENU_TIMEOUT
    try:
        while now() < deadline:
            for kind, *args in events():
                deadline = now() + MENU_TIMEOUT
                if kind == 'move':
                    pointer = args
                elif kind == 'wheel':
                    scroll = menu_scroll(menu, scroll, 1 if args[0] else -1)
                elif kind == 'scroll':
                    scroll = menu_scroll(menu, scroll, args[0])
                elif kind == 'press':
                    i = menu_at(menu, *args, scroll)
                    return None if i is None else menu['names'][i]
                elif kind == 'escape':
                    return None
                # the voice under the pointer, which a scroll moves from under it too
                i = menu_at(menu, *pointer, scroll) if pointer else None
                hover = -1 if i is None else i
            if (scroll, hover) != shown:
                shown = scroll, hover
                write_menu(scroll, hover)
            sleep(0.02)
        return None
    finally:
        try:
            os.remove(VOICE_MENU)
        except OSError:
            pass


def declare(x11):
    """The argument types of the X calls the open list makes, which conky-mouse.py has no use for."""
    x11.XGrabPointer.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_uint,
                                 ctypes.c_int, ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    x11.XGrabKeyboard.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_ulong]
    x11.XUngrabPointer.argtypes = x11.XUngrabKeyboard.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x11.XKeysymToKeycode.restype = ctypes.c_ubyte


def grab(d, win):
    """Holds the pointer and the keyboard on `win` for the open list, so every click and key
    reaches it and none goes to the window under the pointer. Returns whether each was
    granted; a grab the X server refuses leaves the list open to the widget's own clicks
    only."""
    x11 = core.x11
    events = core.BUTTON_PRESS_MASK | core.BUTTON_RELEASE_MASK | core.POINTER_MOTION_MASK
    pointer = x11.XGrabPointer(d, win, 0, events, GRAB_ASYNC, GRAB_ASYNC, 0, 0, 0) == GRAB_SUCCESS
    keyboard = x11.XGrabKeyboard(d, win, 0, GRAB_ASYNC, GRAB_ASYNC, 0) == GRAB_SUCCESS
    return pointer, keyboard


def ungrab(d):
    core.x11.XUngrabPointer(d, 0)
    core.x11.XUngrabKeyboard(d, 0)
    core.x11.XFlush(d)


def x_events(d, win, s, opcode, menu):
    """run_menu's events() reading X's queue. A finger that touches down is followed from one
    call to the next: where it lifts after a tap is a press, and a swipe scrolls the list a
    voice for each voice's height it moves."""
    x11, ev = core.x11, core.XEvent()
    escape = x11.XKeysymToKeycode(d, ESCAPE)
    step = menu['item_h'] * s
    touch = {}                                   # the finger being followed: it, where it began, rows scrolled

    def card(x, y):
        return (x - core.SHADOW * s) / s, (y - core.SHADOW * s) / s

    def follow():
        out = []
        fx, fy, down = touch['finger']()
        sx, sy = touch['start']
        if not touch['swiped'] and max(abs(fx - sx), abs(fy - sy)) > core.TAP_SLOP * s:
            touch['swiped'] = True
        if touch['swiped']:
            rows = int(-(fy - sy) / step)
            if rows != touch['rows']:
                out.append(('scroll', rows - touch['rows']))
                touch['rows'] = rows
        if not down:
            if not touch['swiped']:
                out.append(('press', *touch['at']))
            touch.clear()
        return out

    def events():
        out = follow() if touch else []
        while x11.XPending(d):
            x11.XNextEvent(d, ctypes.byref(ev))
            b = ev.xbutton
            if ev.type == core.MOTION_NOTIFY:
                out.append(('move', *card(b.x, b.y)))
            elif ev.type == core.BUTTON_PRESS and b.button in (core.WHEEL_UP, core.WHEEL_DOWN):
                out.append(('wheel', b.button == core.WHEEL_DOWN))
            elif ev.type == core.BUTTON_PRESS and b.button == 1:
                out.append(('press', *card(b.x, b.y)))
            elif ev.type == KEY_PRESS and b.button == escape:   # an XKeyEvent's keycode sits where a button's does
                out.append(('escape',))
            elif opcode and ev.type == core.GENERIC_EVENT and not touch:
                t = core.touch_event(d, ev, opcode)
                if t and t[0] == core.XI_TOUCH_BEGIN and t[2] == win:
                    start = round(t[3]), round(t[4])
                    touch.update(finger=core.Touch(d, opcode, t[1], *start), start=start,
                                 at=card(t[5], t[6]), swiped=False, rows=0)
        return out
    return events


def open_menu(d, win, s, regions):
    """The voice drop down was pressed: open the list, and set the voice picked from it."""
    menu = regions.get('menu')
    if not menu:
        return
    declare(core.x11)
    pointer, keyboard = grab(d, win)
    core.log(f'voice list: {len(menu["names"])} voices, pointer {"held" if pointer else "not held"}, '
             f'keyboard {"held" if keyboard else "not held"}')
    try:
        name = run_menu(menu, x_events(d, win, s, core.touch_opcode(d), menu))
    finally:
        ungrab(d)
    core.log('voice list closed' + (f': {name}' if name else ''))
    if name is not None and menu['names'].index(name) != menu['current']:
        speechctl('voice', name)


def pull_control(d, root, win, s, regions, hit, track, at, touch):
    """A press on the volume slider sets the volume along it. A press on the voice drop down:
    a click or tap opens the list of voices, a drag from it moves the widget. A press on a
    session's segment: a click or tap sets the setting; a drag from it moves the widget, or
    with a finger scrolls the list. Returns whether the press was on any of them."""
    x, y, start = at
    if hit == 'volume' and regions.get('volume_bar'):
        set_volume(d, win, regions, s, track)
        return True
    if hit == 'voice':
        if core.clicked(start, s, track, core.TAP_SLOP if touch else core.CLICK_SLOP):
            open_menu(d, win, s, regions)
        else:
            core.remember(*core.drag(d, root, win, s, track, start))
        return True
    segment = segment_at(regions, s, x, y)
    if not segment:
        return False
    if core.clicked(start, s, track, core.TAP_SLOP if touch else core.CLICK_SLOP):
        speechctl('speech', *segment)
    elif touch:
        swipe(regions, s, x, y, start[1], track)
    else:
        core.remember(*core.drag(d, root, win, s, track, start))
    return True


def without_idle_edges(edges, regions):
    return edges


def scroll_list(regions, down):
    """Moves the list a row down or up, between its top and its last row; returns the offset."""
    last = (regions.get('list_scroll') or [0])[0]
    at = min(max(offset(regions) + (1 if down else -1), 0), last)
    os.makedirs(CACHE, exist_ok=True)
    with open(LIST_SCROLL + '.tmp', 'w') as f:
        f.write(f'{at}')
    os.replace(LIST_SCROLL + '.tmp', LIST_SCROLL)
    return at


def wheel(regions, s, x, y, down):
    """What a wheel step down (or up) over card-relative (x, y) does: turns the volume down
    over the slider or its speaker, the next voice, the setting a segment right, or the list a row down. Returns what it did,
    or None where the wheel does nothing."""
    if inside(regions.get('volume_wheel'), s, x, y):
        speechctl('volume', 'down' if down else 'up')
        return 'volume'
    if inside(regions.get('voice'), s, x, y):
        speechctl('voice', 'next' if down else 'prev')
        return 'voice'
    row, on_control = row_at(regions, s, x, y)
    if on_control and row.get('speech') in SETTINGS:
        i = SETTINGS.index(row['speech']) + (1 if down else -1)
        if 0 <= i < len(SETTINGS):
            speechctl('speech', row['id'], SETTINGS[i])
        return 'setting'
    if inside(regions.get('list'), s, x, y) and regions.get('list_scroll'):
        scroll_list(regions, down)
        return 'list'
    return None


def scrollable(regions, s, x, y):
    """Whether card-relative (x, y) is over the list, with more sessions than it shows."""
    scroll = regions.get('list_scroll')
    return bool(scroll and scroll[0] > 0 and inside(regions.get('list'), s, x, y))


def swipe(regions, s, x, y, y0, track):
    """Scroll the list with the finger `track` follows, which touched down at root y0, a row
    for each row's height it moves, until it lifts."""
    row = regions['list_scroll'][1] * s
    done, held = 0, True
    while held:
        _, fy, held = track()
        rows = int(-(fy - y0) / row) if row > 0 else 0
        while done != rows:
            down = rows > done
            before = offset(regions)
            if scroll_list(regions, down) == before:
                y0 = fy + done * row             # at the top or the last row: count from here
                break
            done += 1 if down else -1
        time.sleep(0.01)
    core.log(f'swipe: {done} rows')
