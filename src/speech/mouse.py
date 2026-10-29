"""The speech widget's part of the mouse helper, loaded by conky-mouse.py when it is started
as `conky-mouse.py speech`: its name, window class and controls, every one of which runs
speechctl (tray_model.py's, from PATH or the path ~/.config/conky-widgets/speech/speechctl
holds).

  - skip, next, pause/resume: a click or tap runs `speechctl skip`, `next` and `toggle`
  - a session's gear: a click or tap opens that session's settings over the list, in the
    close prompt's panel: its speech On, Alerts or Off (`speechctl speech <id> on|alerts|off`)
    and the voice it is read in, which is kept in <id>.voice beside the session's other speech
    files (a voice's name, absent for the global one). Each choice applies at once and the popup
    stays open; Done, a click outside it and Escape close it. While it is open this helper holds
    the pointer and the keyboard
  - the volume slider: a click, tap or drag along it runs `speechctl volume <level>` where it
    is let go, a tenth at a time from 0 to 2.0; a click or tap on its speaker mutes it (volume
    0) and the next restores the level from before
  - an issue number under a session's repository name: a click or tap opens that issue in a
    new Chrome tab
  - the pill after a session's name: a click or tap opens, in new Chrome tabs, its pull
    requests still open with the ready label
  - a session's name: a click or tap asks "Are you sure?" over the list, and OK ends the
    session (SIGTERM to its process). While the prompt is open this helper holds the pointer
    and the keyboard, so a click anywhere but on OK, Cancel and Escape close it without
    ending anything
  - the wheel: over the volume slider or its speaker it turns it down or up, and over the
    list it scrolls the list a row at a time; a finger swiped over the list scrolls it too

conky-mouse.py gives this module itself as `core`, for the window handling it shares.
"""
import ctypes, json, os, signal, subprocess, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import tray_model  # noqa: E402

NAME = 'conky-widgets/speech'                  # the config and cache folders under ~/.config, ~/.cache
# conky.conf's own_window_class, with the suffix a copy beside the user's adds
WM_CLASS = 'ConkySpeechQueue' + os.environ.get('CSN_CLASS_SUFFIX', '')
OUTLINE = 0x5e9cf0                             # the outline a resize shows
# The buttons speechqueue.py writes the regions of, and what each runs.
COMMANDS = {'skip': ('skip',), 'next': ('next',), 'pause': ('toggle',)}
BUTTONS = tuple(COMMANDS) + ('volume_icon',)  # the controls a click or tap presses
REGIONS_ORDER = BUTTONS + ('minimize', 'close', 'volume', 'divider')   # the regions a press looks through, in order
VOLUME_TOP = 2.0                               # speechctl's loudest volume, the slider's right end
VOLUME_MUTED = 0.05                            # below this volume the speaker draws its cross (a tenth is the least set)
HEIGHT_REGION = 'list'                         # the region the second size setting is the height of
READY_LABEL = 'Manual Review Needed'           # the ready signal's label on a pull request
BROWSER = 'google-chrome'                      # what a session's box and name open their links in
OPEN_AGAIN = 3.0                               # s before a session's box or name opens again
CACHE = os.path.expanduser(f'~/.cache/{NAME}')
LIST_SCROLL = os.path.join(CACHE, 'list-scroll')   # how many rows the list is scrolled, for draw.lua
TERMINAL_SCROLL = os.path.join(CACHE, 'terminal-scroll')   # wheel steps over the terminal pane, in all, for draw.lua
SPLIT = os.path.expanduser(f'~/.config/{NAME}/split')   # the sessions column's share of the width, which speechqueue.py lays the columns out by
DIVIDER_DRAG = os.path.join(CACHE, 'divider-drag')   # exists while the divider is held, so draw.lua brightens it
VOLUME_PREVIEW = os.path.join(CACHE, 'volume-preview')   # the level under the pointer, for draw.lua
VOLUME_BEFORE_MUTE = os.path.join(CACHE, 'volume-before-mute')   # the level the speaker restores
SESSION_MENU = os.path.join(CACHE, 'session-menu')   # "<under the pointer> <speech> <voice>" and the session's name, while its settings are open
SPEAK = os.path.join(os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}', 'speak-attention')   # the speaking hook's state
MENU_TIMEOUT = 20.0                            # s an open popup waits before it closes itself
CLOSE_CONFIRM = os.path.join(CACHE, 'close-confirm')   # "<button under the pointer> <busy>" and the session's name, while the prompt is open
CONFIRM_ARMED = 0.5                            # s after the prompt opens before a press answers it, so the second click of a double click on a name cannot
SESSIONS_DIR = os.path.expanduser('~/.claude/sessions')   # one <pid>.json a running Claude session
KEY_PRESS, ESCAPE = 2, 0xff1b                  # X's key press event, and the Escape keysym
GRAB_SUCCESS, GRAB_ASYNC = 0, 1
core = None                                    # conky-mouse.py's module, set when it loads this one


def start():
    """Clears the preview, the open settings and the open prompt a previous run left behind if
    it was killed mid-drag or mid-popup."""
    for path in (VOLUME_PREVIEW, SESSION_MENU, CLOSE_CONFIRM, DIVIDER_DRAG):
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
    if hit == 'volume_icon':
        toggle_mute()
    else:
        speechctl(*COMMANDS[hit])


def remembered_volume():
    """The level before the last mute, or None when none was kept."""
    try:
        with open(VOLUME_BEFORE_MUTE) as f:
            level = float(f.read())
    except (OSError, ValueError):
        return None
    return level if level >= VOLUME_MUTED else None


def toggle_mute():
    """Mutes the speech, keeping its volume in VOLUME_BEFORE_MUTE so a restart while muted still
    restores it, or restores that volume when it is already muted. The kept level stays when the
    volume is already zero, and the default volume comes back where none was kept (a slider
    dragged to its left end)."""
    level = tray_model.speech_settings()[1]
    if level >= VOLUME_MUTED:
        os.makedirs(CACHE, exist_ok=True)
        with open(VOLUME_BEFORE_MUTE + '.tmp', 'w') as f:
            f.write(f'{level:.1f}')
        os.replace(VOLUME_BEFORE_MUTE + '.tmp', VOLUME_BEFORE_MUTE)
        speechctl('volume', '0')
        return
    back = remembered_volume() or tray_model.DEFAULT_VOLUME
    speechctl('volume', f'{back:.1f}')
    try:
        os.remove(VOLUME_BEFORE_MUTE)
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
    """The session row under card-relative (x, y), and whether (x, y) is on its gear (the row's
    name line, at its right); (None, False) off the list."""
    area, scroll = regions.get('list'), regions.get('list_scroll')
    if not (inside(area, s, x, y) and scroll):
        return None, False
    at = y / s - area[1] + offset(regions) * scroll[1]       # px down the whole list
    for row in regions.get('rows', ()):
        if row['top'] <= at < row['bottom']:
            line = row['top'] + row.get('head', 0)               # its name line, under the repository's name
            on_control = (line <= at < line + scroll[1] and
                          row['gear'][0] * s <= x <= row['gear'][1] * s)
            return row, on_control
    return None, False


def link_at(regions, s, x, y):
    """(session row, 'issue') when an issue number of its repository is under card-relative
    (x, y), with the row's 'issue' set to that issue's link, (row, 'prs') when its pill is,
    (row, 'close') when its name is, else None. An issue number and the pill are there only
    with something to open."""
    row, _ = row_at(regions, s, x, y)
    if not row:
        return None
    at = y / s - regions['list'][1] + offset(regions) * regions['list_scroll'][1]
    for x0, y0, x1, y1, link in row.get('issues', ()):        # on any line of the row's block
        if x0 * s <= x <= x1 * s and (row['top'] + y0) <= at <= (row['top'] + y1):
            return dict(row, issue=link), 'issue'
    line, height = row['top'] + row.get('head', 0), regions['list_scroll'][1]
    # the name closes the session from its name line, the pill opens its pull requests from the
    # line under that, and the repository's name above and the lines below are neither
    for key, kind, first in (('link', 'prs', line + height), ('name', 'close', line)):
        if row.get(key) and first <= at < first + height and row[key][0] * s <= x <= row[key][1] * s:
            return row, kind
    return None


def ready_prs(links, branch, run=subprocess.run):
    """The pull requests of `links` still open, carrying READY_LABEL and from `branch`, read
    from GitHub: a session's ledger also waits on other sessions' pull requests that block it.
    One gh cannot read (not installed, logged out, offline) is not opened, and is logged."""
    ready = []
    for link in links:
        try:
            out = run(['gh', 'pr', 'view', link, '--json', 'state,labels,headRefName'], capture_output=True,
                      text=True, timeout=15)
            pr = json.loads(out.stdout) if out.returncode == 0 else None
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pr = None
        if pr is None:
            core.log(f'{link}: gh could not read it, so it is not opened')
        elif (pr.get('state') == 'OPEN' and READY_LABEL in [l.get('name') for l in pr.get('labels', ())]
              and branch and pr.get('headRefName') == branch):
            ready.append(link)
        else:
            core.log(f'{link}: not ready ({pr.get("state")}, from {pr.get("headRefName")})')
    return ready


def open_links(row, kind, run=subprocess.run, popen=subprocess.Popen):
    """Opens, each in a new browser tab, a session's issue (`kind` 'issue', a click on an issue
    number) or its ready pull requests ('prs', a click on its pill). Chrome takes them all at once;
    without it, xdg-open takes each."""
    try:
        if kind == 'issue':
            links = [row['issue']]
        else:
            links = ready_prs(row.get('prs') or [], row.get('branch') or '', run)
        if not links:
            core.log(f'session {row["id"]}: no ready pull request to open')
            return
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
    """What a click opens, for telling a double click from a click on another: a session's pull
    requests or its close prompt, or one of its issues, each issue number its own."""
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


def gear_at(regions, s, x, y):
    """The session row whose gear is under card-relative (x, y), or None."""
    row, on_gear = row_at(regions, s, x, y)
    return row if on_gear else None


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


def move_divider(d, win, regions, s, track):
    """Follow `track` (follow_pointer() or a Touch) while the divider is held, writing the
    share of the width the sessions column takes with the pointer at the middle of the gap,
    within the limits speechqueue.py gave in regions.json's `divider_drag`; it lays the columns
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


def settings_at(popup, x, y):
    """What card-relative logical (x, y) is on in the settings popup `popup` (regions.json's):
    ('speech', key) for a speech button, ('voice', index) for a voice's button, ('done',),
    ('panel',) for the rest of the panel, or None outside it."""
    if not inside(popup['box'], 1, x, y):
        return None
    for key, box in popup['speech'].items():
        if inside(box, 1, x, y):
            return 'speech', key
    if inside(popup['done'], 1, x, y):
        return ('done',)
    for i, box in enumerate(popup['voices']):
        if inside(box, 1, x, y):
            return 'voice', i
    return ('panel',)


def write_settings(row, hover, speech, voice):
    """What draw.lua draws the popup from: what is under the pointer ('none', 'speech:<key>',
    'item:<index>' or 'done'), the session's speech setting and its voice (an index into the
    voices), then its name."""
    os.makedirs(CACHE, exist_ok=True)
    with open(SESSION_MENU + '.tmp', 'w') as f:
        f.write(f"{hover} {speech} {voice}\n{row.get('title', '')}")
    os.replace(SESSION_MENU + '.tmp', SESSION_MENU)


def hover_token(hit):
    return 'none' if hit is None or hit[0] == 'panel' else hit[0] if hit[0] == 'done' else \
        f'{"item" if hit[0] == "voice" else "speech"}:{hit[1]}'


def run_settings(popup, row, events, act, now=time.monotonic, sleep=time.sleep):
    """Shows the settings popup for session `row` until it is closed. `events()` gives the
    card-relative logical-px events that arrived since it was last called: ('move', x, y),
    ('press', x, y) and ('escape',). A press on a speech
    button or a voice calls act('speech', key) or act('voice', name) at once and the popup stays
    open; Done, a press outside it, Escape and MENU_TIMEOUT without an event close it. Presses
    in the first CONFIRM_ARMED seconds are ignored, so the second click of a double click on the
    gear is not an answer. draw.lua draws it from SESSION_MENU for as long as this runs."""
    names = popup['names']
    speech = row.get('speech', '')
    voice = names.index(row.get('voice') or '') if (row.get('voice') or '') in names else -1
    opened = now()
    deadline = opened + MENU_TIMEOUT
    pointer, shown = None, None
    try:
        while now() < deadline:
            for kind, *args in events():
                deadline = now() + MENU_TIMEOUT
                if kind == 'move':
                    pointer = args
                elif kind == 'press' and now() - opened >= CONFIRM_ARMED:
                    hit = settings_at(popup, *args)
                    if hit is None or hit[0] == 'done':
                        return
                    if hit[0] == 'speech':
                        speech = hit[1]
                        act('speech', speech)
                    elif hit[0] == 'voice':
                        voice = hit[1]
                        act('voice', names[voice])
                elif kind == 'escape':
                    return
            hover = hover_token(settings_at(popup, *pointer) if pointer else None)
            if (hover, speech, voice) != shown:
                shown = hover, speech, voice
                write_settings(row, *shown)
            sleep(0.02)
    finally:
        try:
            os.remove(SESSION_MENU)
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


def x_events(d, win, s, opcode):
    """run_settings's and run_confirm's events() reading X's queue. A finger that touches down
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


def set_session_voice(sid, name, speak=None):
    """Keeps `name` as the voice session `sid` is read in, in <sid>.voice beside its other speech
    files; '' (the global voice) removes the file."""
    if not sid or os.path.basename(sid) != sid:
        return
    path = os.path.join(speak or SPEAK, sid + '.voice')
    try:
        if name:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path + '.tmp', 'w') as f:
                f.write(name)
            os.replace(path + '.tmp', path)
        else:
            os.remove(path)
    except OSError as e:
        if not (isinstance(e, FileNotFoundError) and not name):
            core.log(f'voice for {sid}: {e}')


def apply_setting(row, kind, value):
    """A choice made in a session's settings popup: its speech setting, or its voice."""
    if kind == 'speech':
        speechctl('speech', row['id'], value)
    else:
        set_session_voice(row['id'], value)
        core.log(f'voice for {row["id"]}: {value or "global"}')


def open_settings(d, win, s, regions, row):
    """A session's gear was pressed: open its settings, and apply what is chosen in them."""
    popup = regions.get('settings')
    if not popup:
        return
    declare(core.x11)
    pointer, keyboard = grab(d, win)
    core.log(f'settings for {row["id"]}: pointer {"held" if pointer else "not held"}, '
             f'keyboard {"held" if keyboard else "not held"}')
    try:
        run_settings(popup, row, x_events(d, win, s, core.touch_opcode(d)),
                     lambda kind, value: apply_setting(row, kind, value))
    finally:
        ungrab(d)
    core.log('settings closed')


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
    pressed. `events()` is run_menu's. A press on OK answers yes; one anywhere else, Escape and
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
    core.log(f'close prompt for {row["id"]}: pointer {"held" if pointer else "not held"}, '
             f'keyboard {"held" if keyboard else "not held"}')
    try:
        ok = run_confirm(prompt, row, x_events(d, win, s, core.touch_opcode(d)))
    finally:
        ungrab(d)
    core.log('close prompt: ' + ('OK' if ok else 'not confirmed'))
    if ok:
        end_session(row)


def pull_control(d, root, win, s, regions, hit, track, at, touch):
    """A press on the volume slider sets the volume along it. A press on a session's gear: a click
    or tap opens its settings; a drag from it moves the widget, or with a finger scrolls the
    list. A press on a session's issue number, pill or name: a click or tap opens its issue, its
    pull requests, or the prompt that closes it; a drag moves the widget, or with a finger
    scrolls the list when it can scroll.
    Returns whether the press was on any of them."""
    x, y, start = at
    if hit == 'volume' and regions.get('volume_bar'):
        set_volume(d, win, regions, s, track)
        return True
    if hit == 'divider' and regions.get('divider_drag'):
        move_divider(d, win, regions, s, track)
        return True
    gear = gear_at(regions, s, x, y)
    link = None if gear else link_at(regions, s, x, y)
    if not (gear or link):
        return False
    if core.clicked(start, s, track, core.TAP_SLOP if touch else core.CLICK_SLOP):
        if gear:
            open_settings(d, win, s, regions, gear)
        elif link[1] == 'close':
            close_session(d, win, s, regions, link[0])
        else:
            open_once(*link)
    elif touch and (gear or scrollable(regions, s, x, y)):
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
    """What a wheel step down (or up) over card-relative (x, y) does: turns the volume down
    over the slider or its speaker, the terminal pane's text a line down while the pointer is
    over it, or the list a row down. Returns what it did, or None where the wheel does nothing."""
    if inside(regions.get('volume_wheel'), s, x, y):
        speechctl('volume', 'down' if down else 'up')
        return 'volume'
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
