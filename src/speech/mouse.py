"""The speech widget's part of the mouse helper, loaded by conky-mouse.py when it is started
as `conky-mouse.py speech`: its name, window class and controls, every one of which runs
speechctl (tray_model.py's, from PATH or the path ~/.config/conky-widgets/speech/speechctl
holds).

  - skip, next, pause/resume, voice ◀ ▶: a click or tap runs `speechctl skip`, `next`,
    `toggle` and `voice prev|next`
  - the volume slider: a click, tap or drag along it runs `speechctl volume <level>` where it
    is let go, a tenth at a time from 0 to 2.0
  - a session's On / Alerts / Off: a click or tap runs `speechctl speech <id> on|alerts|off`
  - the wheel: over the volume slider or its speaker it turns it down or up, over the voice it steps through the
    voices, over a session's setting it moves it a segment along, and over the rest of the
    list it scrolls the list a row at a time; a finger swiped over the list scrolls it too

conky-mouse.py gives this module itself as `core`, for the window handling it shares.
"""
import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import tray_model  # noqa: E402

NAME = 'conky-widgets/speech'                  # the config and cache folders under ~/.config, ~/.cache
WM_CLASS = 'ConkySpeechQueue'                  # conky.conf's own_window_class
OUTLINE = 0x5e9cf0                             # the outline a resize shows
# The buttons speechqueue.py writes the regions of, and what each runs.
COMMANDS = {'skip': ('skip',), 'next': ('next',), 'pause': ('toggle',),
            'voice_prev': ('voice', 'prev'), 'voice_next': ('voice', 'next')}
BUTTONS = tuple(COMMANDS)                      # the controls a click or tap presses
REGIONS_ORDER = BUTTONS + ('minimize', 'close', 'volume')   # the regions a press looks through, in order
VOLUME_TOP = 2.0                               # speechctl's loudest volume, the slider's right end
HEIGHT_REGION = 'list'                         # the region the second size setting is the height of
SETTINGS = ('on', 'alerts', 'off')             # a session's segments, left to right
CACHE = os.path.expanduser(f'~/.cache/{NAME}')
LIST_SCROLL = os.path.join(CACHE, 'list-scroll')   # how many rows the list is scrolled, for draw.lua
VOLUME_PREVIEW = os.path.join(CACHE, 'volume-preview')   # the level under the pointer, for draw.lua
core = None                                    # conky-mouse.py's module, set when it loads this one


def start():
    """Clears the preview a previous run left behind if it was killed mid-drag."""
    try:
        os.remove(VOLUME_PREVIEW)
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


def pull_control(d, root, win, s, regions, hit, track, at, touch):
    """A press on the volume slider sets the volume along it. A press on a session's segment:
    a click or tap sets the setting; a drag from it moves the widget, or with a finger scrolls
    the list. Returns whether the press was on either."""
    x, y, start = at
    if hit == 'volume' and regions.get('volume_bar'):
        set_volume(d, win, regions, s, track)
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
