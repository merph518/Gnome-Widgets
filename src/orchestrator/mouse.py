"""The orchestrator widget's part of the mouse helper, loaded by conky-mouse.py when it is started
as `conky-mouse.py orchestrator`: its name, window class and what a click, tap, drag or wheel step
does.

  - an issue or pull request number in a message's header in the terminal: a click or tap
    opens it in a new Chrome tab
  - a session's name: a click or tap asks "Are you sure?" over the list, and OK ends the
    session (SIGTERM to its process). While the prompt is open this helper holds the pointer
    and the keyboard, so a click anywhere but on OK, Cancel and Escape close it without
    ending anything
  - the divider between the columns: a drag moves it
  - the wheel: over the terminal pane it scrolls the pane, and over the list it scrolls the
    list a row at a time; a finger swiped over the list scrolls it too

conky-mouse.py gives this module itself as `core`, for the window handling it shares.
"""
import ctypes, json, os, signal, subprocess, threading, time

NAME = 'conky-widgets/orchestrator'            # the config and cache folders under ~/.config, ~/.cache
# conky.conf's own_window_class, with the suffix a copy beside the user's adds
WM_CLASS = 'ConkyOrchestrator' + os.environ.get('CSN_CLASS_SUFFIX', '')
OUTLINE = 0x5e9cf0                             # the outline a resize shows
BUTTONS = ()                                   # the controls a click or tap presses: this widget has none of its own
REGIONS_ORDER = ('minimize', 'close', 'divider')   # the regions a press looks through, in order
HEIGHT_REGION = 'list'                         # the region the second size setting is the height of
BROWSER = 'google-chrome'                      # what a session's box and name open their links in
OPEN_AGAIN = 3.0                               # s before a session's box or name opens again
CACHE = os.path.expanduser(f'~/.cache/{NAME}')
LIST_SCROLL = os.path.join(CACHE, 'list-scroll')   # how many rows the list is scrolled, for draw.lua
TERMINAL_SCROLL = os.path.join(CACHE, 'terminal-scroll')   # wheel steps over the terminal pane, in all, for draw.lua
SPLIT = os.path.expanduser(f'~/.config/{NAME}/split')   # the sessions column's share of the width, which orchestrator.py lays the columns out by
DIVIDER_DRAG = os.path.join(CACHE, 'divider-drag')   # exists while the divider is held, so draw.lua brightens it
MENU_TIMEOUT = 20.0                            # s an open popup waits before it closes itself
CLOSE_CONFIRM = os.path.join(CACHE, 'close-confirm')   # "<button under the pointer> <busy>" and the session's name, while the prompt is open
CONFIRM_ARMED = 0.5                            # s after the prompt opens before a press answers it, so the second click of a double click on a name cannot
SESSIONS_DIR = os.path.expanduser('~/.claude/sessions')   # one <pid>.json a running Claude session
KEY_PRESS, ESCAPE = 2, 0xff1b                  # X's key press event, and the Escape keysym
GRAB_SUCCESS, GRAB_ASYNC = 0, 1
core = None                                    # conky-mouse.py's module, set when it loads this one


def start():
    """Clears the open prompt and the held divider a previous run left behind if it was killed
    mid-popup or mid-drag."""
    for path in (CLOSE_CONFIRM, DIVIDER_DRAG):
        try:
            os.remove(path)
        except OSError:
            pass


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
    """The session row under card-relative (x, y), or None off the list."""
    area, scroll = regions.get('list'), regions.get('list_scroll')
    if not (inside(area, s, x, y) and scroll):
        return None
    at = y / s - area[1] + offset(regions) * scroll[1]       # px down the whole list
    return next((row for row in regions.get('rows', ()) if row['top'] <= at < row['bottom']), None)


TERMINAL_LINKS = os.path.join(CACHE, 'terminal-links')   # "<line> <number> x0 y0 x1 y1" for each issue or pull request number draw.lua drew in the terminal


def terminal_link_at(regions, s, x, y):
    """(a row with the 'issue' to open, 'issue') when an issue or pull request number in a
    message's header in the terminal is under card-relative (x, y), else None. draw.lua writes
    where it drew each; regions.json's `terminal_links` says what each opens."""
    if not inside(regions.get('terminal'), s, x, y):
        return None
    try:
        with open(TERMINAL_LINKS) as f:
            rows = [line.split() for line in f.read().splitlines()]
    except OSError:
        return None
    for fields in rows:
        try:
            line, number, x0, y0, x1, y1 = int(fields[0]), int(fields[1]), *(float(v) for v in fields[2:6])
            info = regions['terminal_links'][str(line)][number - 1]
        except (IndexError, KeyError, ValueError):
            continue
        if x0 * s <= x <= x1 * s and y0 * s <= y <= y1 * s:
            return dict(info), 'issue'
    return None


def link_at(regions, s, x, y):
    """(session row, 'close') when the session's name is under card-relative (x, y), else
    None; or an issue or pull request number in the terminal, terminal_link_at's."""
    row = row_at(regions, s, x, y)
    if not row:
        return terminal_link_at(regions, s, x, y)
    at = y / s - regions['list'][1] + offset(regions) * regions['list_scroll'][1]
    line = row['top'] + row.get('head', 0)                   # the name's line: not the section's title above it
    if row.get('name') and line <= at < line + regions['list_scroll'][1] and row['name'][0] * s <= x <= row['name'][1] * s:
        return row, 'close'
    return None


def open_links(row, kind, run=subprocess.run, popen=subprocess.Popen):
    """Opens, in a new browser tab, the issue or pull request (`row['issue']`, the URL) a click
    on its number in a message's header in the terminal asked for. Chrome takes it; without
    it, xdg-open does."""
    try:
        links = [row['issue']]
        core.log('open: ' + ' '.join(links))
        quiet = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            launched = [popen([BROWSER, *links], **quiet)]
        except OSError:
            launched = [popen(['xdg-open', link], **quiet) for link in links]
        for p in launched:
            # reaped on a thread of its own: a launcher that starts Chrome is Chrome, until it quits
            threading.Thread(target=p.wait, daemon=True).start()
    except OSError as e:
        core.log(f'open: {e}')
    finally:
        opening.discard(click_key(row, kind))


opening = set()                                # click_key()s a click is still opening
opened = {}                                    # click_key(): when a click last opened it


def click_key(row, kind):
    """What a click opens, for telling a double click from a click on another: a session's close
    prompt, or an issue or pull request, each number its own."""
    return (row['id'], row.get('issue') if kind == 'issue' else kind)


def open_once(row, kind, now=time.monotonic):
    """Opens a session's issue or pull requests on a thread, as gh reads each pull request,
    which takes a moment. A second click on the same one while it is still opening, or within
    OPEN_AGAIN s of the last (a double click), does nothing."""
    key = click_key(row, kind)
    if key in opening or now() - opened.get(key, -OPEN_AGAIN) < OPEN_AGAIN:
        return
    opening.add(key)
    opened[key] = now()
    threading.Thread(target=open_links, args=(row, kind), daemon=True).start()


def move_divider(d, win, regions, s, track):
    """Follow `track` (follow_pointer() or a Touch) while the divider is held, writing the
    share of the width the sessions column takes with the pointer at the middle of the gap,
    within the limits orchestrator.py gave in regions.json's `divider_drag`; it lays the columns
    out again within a tenth of a second."""
    left, avail, gap, low, high = regions['divider_drag']
    wx, _, _, _ = core.card_of(core.geometry(d, win), s)
    os.makedirs(os.path.dirname(SPLIT), exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)
    open(DIVIDER_DRAG, 'w').close()
    held, last = True, None
    try:
        while held:
            px, _, held = track()
            share = round(min(max(((px - wx) / s - left - gap / 2) / avail, low), high), 4)
            if share != last:
                last = share
                with open(SPLIT + '.tmp', 'w') as f:
                    f.write(f'{share:.4f}\n')
                os.replace(SPLIT + '.tmp', SPLIT)
            time.sleep(0.02)
    finally:
        try:
            os.remove(DIVIDER_DRAG)
        except OSError:
            pass


def declare(x11):
    """The argument types of the X calls the open prompt makes, which conky-mouse.py has no use for."""
    x11.XGrabPointer.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_uint,
                                 ctypes.c_int, ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    x11.XGrabKeyboard.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_ulong]
    x11.XUngrabPointer.argtypes = x11.XUngrabKeyboard.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x11.XKeysymToKeycode.restype = ctypes.c_ubyte


class XWMHints(ctypes.Structure):
    _fields_ = [('flags', ctypes.c_long), ('input', ctypes.c_int), ('initial_state', ctypes.c_int),
                ('icon_pixmap', ctypes.c_ulong), ('icon_window', ctypes.c_ulong), ('icon_x', ctypes.c_int),
                ('icon_y', ctypes.c_int), ('icon_mask', ctypes.c_ulong), ('window_group', ctypes.c_ulong)]


INPUT_HINT, REVERT_TO_PARENT = 1, 2


def set_accepts_input(d, win, accepts):
    """Sets whether the window accepts keyboard focus (WM_HINTS' input), which conky leaves
    False, so the window manager never gives the widget a key. Returns the value it had, or
    None when the window has no hints to change."""
    x11 = core.x11
    x11.XGetWMHints.restype = ctypes.POINTER(XWMHints)
    x11.XGetWMHints.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x11.XSetWMHints.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(XWMHints)]
    x11.XFree.argtypes = [ctypes.c_void_p]
    hints = x11.XGetWMHints(d, win)
    if not hints:
        return None
    try:
        before = bool(hints.contents.flags & INPUT_HINT and hints.contents.input)
        hints.contents.flags |= INPUT_HINT
        hints.contents.input = int(accepts)
        x11.XSetWMHints(d, win, hints)
    finally:
        x11.XFree(hints)
    x11.XFlush(d)
    return before


def focus_window(d, win, sleep=time.sleep):
    """Asks for keyboard focus on `win` for the open menu: lets it accept input, asks the window
    manager to activate it (_NET_ACTIVE_WINDOW, as a pager does) and sets the focus itself.
    Returns (whether the window has the focus now, what accepted input before) so the caller
    can put the hint back."""
    x11 = core.x11
    before = set_accepts_input(d, win, True)
    root = x11.XDefaultRootWindow(d)
    ev = core.XClientMessageEvent(type=core.CLIENT_MESSAGE, window=win, format=32,
                                  message_type=x11.XInternAtom(d, b'_NET_ACTIVE_WINDOW', False))
    ev.data[:] = [2, 0, 0, 0, 0]
    x11.XSendEvent(d, root, False, core.SUBSTRUCTURE_REDIRECT_MASK | core.SUBSTRUCTURE_NOTIFY_MASK, ctypes.byref(ev))
    x11.XSetInputFocus.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    x11.XSetInputFocus(d, win, REVERT_TO_PARENT, 0)
    x11.XFlush(d)
    sleep(0.1)
    x11.XGetInputFocus.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int)]
    focus, revert = ctypes.c_ulong(), ctypes.c_int()
    x11.XGetInputFocus(d, ctypes.byref(focus), ctypes.byref(revert))
    return focus.value == win, before


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


def x_events(d, win, s, opcode):
    """run_confirm's events() reading X's queue. A finger that touches down
    is followed from one call to the next: where it lifts after a tap is a press, and a swipe
    is not one."""
    x11, ev = core.x11, core.XEvent()
    escape = x11.XKeysymToKeycode(d, ESCAPE)
    touch = {}                                   # the finger being followed: it, where it began, where it tapped

    def card(x, y):
        return (x - core.SHADOW * s) / s, (y - core.SHADOW * s) / s

    def follow():
        out = []
        fx, fy, down = touch['finger']()
        sx, sy = touch['start']
        if not touch['swiped'] and max(abs(fx - sx), abs(fy - sy)) > core.TAP_SLOP * s:
            touch['swiped'] = True
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
            elif ev.type == core.BUTTON_PRESS and b.button == 1:
                out.append(('press', *card(b.x, b.y)))
            elif ev.type == KEY_PRESS and b.button == escape:   # an XKeyEvent's keycode sits where a button's does
                out.append(('escape',))
            elif opcode and ev.type == core.GENERIC_EVENT and not touch:
                t = core.touch_event(d, ev, opcode)
                if t and t[0] == core.XI_TOUCH_BEGIN and t[2] == win:
                    start = round(t[3]), round(t[4])
                    touch.update(finger=core.Touch(d, opcode, t[1], *start), start=start,
                                 at=card(t[5], t[6]), swiped=False)
        return out
    return events


def prompt_at(prompt, x, y):
    """'ok' or 'cancel' for the button of the close prompt `prompt` (regions.json's) under
    card-relative logical (x, y), else None."""
    return next((key for key in ('ok', 'cancel') if inside(prompt[key], 1, x, y)), None)


def write_confirm(row, hover):
    """What draw.lua draws the close prompt from: the button under the pointer (0 none, 1 OK,
    2 Cancel), whether the session is busy, and its name."""
    os.makedirs(CACHE, exist_ok=True)
    with open(CLOSE_CONFIRM + '.tmp', 'w') as f:
        f.write(f"{(None, 'ok', 'cancel').index(hover)} {int(bool(row.get('busy')))}\n{row.get('title', '')}")
    os.replace(CLOSE_CONFIRM + '.tmp', CLOSE_CONFIRM)


def run_confirm(prompt, row, events, now=time.monotonic, sleep=time.sleep):
    """Shows the close prompt for session `row` until it is answered, and returns whether OK was
    pressed. `events()` gives the card-relative logical-px events since it was last called:
    ('move', x, y), ('press', x, y) and ('escape',). A press on OK answers yes; one anywhere else, Escape and
    MENU_TIMEOUT without an event answer no. Presses in the first CONFIRM_ARMED seconds are
    ignored, so the second click of a double click on the name is not an answer. draw.lua draws
    the prompt from CLOSE_CONFIRM for as long as this runs."""
    opened = now()
    deadline = opened + MENU_TIMEOUT
    pointer, hover = None, None
    try:
        write_confirm(row, hover)
        while now() < deadline:
            for kind, *args in events():
                deadline = now() + MENU_TIMEOUT
                if kind == 'move':
                    pointer = args
                elif kind == 'press' and now() - opened >= CONFIRM_ARMED:
                    return prompt_at(prompt, *args) == 'ok'
                elif kind == 'escape':
                    return False
            under = prompt_at(prompt, *pointer) if pointer else None
            if under != hover:
                hover = under
                write_confirm(row, hover)
            sleep(0.02)
        return False
    finally:
        try:
            os.remove(CLOSE_CONFIRM)
        except OSError:
            pass


def proc_start(pid, proc_dir='/proc'):
    """The start time of process `pid` in clock ticks since boot, field 22 of its stat, which
    Claude Code writes to a session's file as procStart."""
    with open(os.path.join(proc_dir, str(int(pid)), 'stat'), encoding='utf-8') as f:
        return f.read().rsplit(')', 1)[1].split()[19]      # after the name, which can hold spaces and ')'


def end_session(row, sessions_dir=SESSIONS_DIR, proc_dir='/proc', kill=os.kill):
    """Ends the Claude session `row` by sending its process SIGTERM, which is what closing it
    from outside comes to. Claude Code's file for the pid is read first and has to still name
    this session, and the process has to have started when the file says it did, so a file
    that outlived its session while its pid went to another process signals nothing. Returns
    whether the signal was sent."""
    pid, sid = row.get('pid'), row.get('id')
    try:
        with open(os.path.join(sessions_dir, f'{int(pid)}.json'), encoding='utf-8') as f:
            entry = json.load(f)
        named = isinstance(entry, dict) and int(entry.get('pid')) == int(pid) and str(entry.get('sessionId')) == sid
        same = named and str(entry.get('procStart')) == proc_start(pid, proc_dir)
    except (OSError, ValueError, TypeError, IndexError):
        same = False
    if not (same and sid):
        core.log(f'close: session {sid} is no longer running as pid {pid}')
        return False
    try:
        kill(int(pid), signal.SIGTERM)
    except OSError as e:
        core.log(f'close: session {sid} pid {pid}: {e}')
        return False
    core.log(f'close: SIGTERM to session {sid} ({row.get("title", "")}) pid {pid}')
    return True


def close_session(d, win, s, regions, row):
    """A session's name was pressed: show the prompt, and end the session when OK is pressed."""
    prompt = regions.get('confirm')
    if not prompt:
        return
    declare(core.x11)
    pointer, keyboard = grab(d, win)
    focused, accepted = focus_window(d, win)
    core.log(f'close prompt for {row["id"]}: pointer {"held" if pointer else "not held"}, '
             f'keyboard {"held" if keyboard else "not held"}, focus {"taken" if focused else "not taken"}')
    try:
        ok = run_confirm(prompt, row, x_events(d, win, s, core.touch_opcode(d)))
    finally:
        ungrab(d)
        set_accepts_input(d, win, bool(accepted))
    core.log('close prompt: ' + ('OK' if ok else 'not confirmed'))
    if ok:
        end_session(row)


def pull_control(d, root, win, s, regions, hit, track, at, touch):
    """A press on the divider moves it. A press on a session's name or an issue or pull request
    number in the terminal: a click or tap opens the prompt that closes the session, or the issue
    or pull request; a drag moves the widget, or with a finger scrolls the list when it can
    scroll. Returns whether the press was on any of them."""
    x, y, start = at
    if hit == 'divider' and regions.get('divider_drag'):
        move_divider(d, win, regions, s, track)
        return True
    link = link_at(regions, s, x, y)
    if not link:
        return False
    if core.clicked(start, s, track, core.TAP_SLOP if touch else core.CLICK_SLOP):
        if link[1] == 'close':
            close_session(d, win, s, regions, link[0])
        else:
            open_once(*link)
    elif touch and scrollable(regions, s, x, y):
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


def scroll_terminal(down):
    """Counts a wheel step over the terminal pane, down or up, for draw.lua to turn into lines."""
    try:
        with open(TERMINAL_SCROLL) as f:
            steps = int(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        steps = 0
    os.makedirs(CACHE, exist_ok=True)
    with open(TERMINAL_SCROLL + '.tmp', 'w') as f:
        f.write(f'{steps + (1 if down else -1)}')
    os.replace(TERMINAL_SCROLL + '.tmp', TERMINAL_SCROLL)


def wheel(regions, s, x, y, down):
    """What a wheel step down (or up) over card-relative (x, y) does: scrolls the terminal pane's
    text a line down while the pointer is over it, or the list a row down. Returns what it did,
    or None where the wheel does nothing."""
    if inside(regions.get('terminal'), s, x, y):
        if regions.get('terminal_scroll'):
            scroll_terminal(down)
        return 'terminal'
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
