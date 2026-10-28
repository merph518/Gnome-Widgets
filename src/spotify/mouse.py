"""The Spotify widget's part of the mouse helper, loaded by conky-mouse.py when it is
started as `conky-mouse.py spotify`: what its controls do, the seek bar, the album art's
colour pick and the wheel and swipes over static lyrics.

conky-mouse.py gives this module itself as `core`, for the window handling it shares:
logging, following the pointer, dragging and the card's geometry.
"""
import os, subprocess, sys, time

import art_colours

NAME = 'conky-spotify-nowplaying'              # the config and cache folders, the launcher
WM_CLASS = 'ConkySpotifyNowPlaying'            # conky.conf's own_window_class
OUTLINE = 0x1db954                             # Spotify green: the outline a resize shows
BUTTONS = ('heart', 'play', 'prev', 'next')    # the controls this widget's click or tap presses
# The regions nowplaying.py writes, in the order a press looks through them.
REGIONS_ORDER = ('heart', 'play', 'prev', 'next', 'minimize', 'close', 'seek', 'art')
CONF = os.path.expanduser(f'~/.config/{NAME}')
CACHE = os.path.expanduser(f'~/.cache/{NAME}')
SEEK_PREVIEW = os.path.join(CACHE, 'seek-preview')
LYRICS_SCROLL = os.path.join(CACHE, 'lyrics-scroll')   # '<lyrics version> <line offset>', for draw.lua
HERE = os.path.dirname(os.path.abspath(__file__))
core = None                                    # conky-mouse.py's module, set when it loads this one


def start():
    """Clears what a previous run left behind if it was killed mid-seek."""
    try:
        os.remove(SEEK_PREVIEW)
    except OSError:
        pass


def press(d, win, hit):
    """Does what a click or tap on the control `hit` (one of BUTTONS) does."""
    if hit == 'heart':
        logged_in = os.path.exists(os.path.join(CONF, 'spotify-token.json'))
        action = 'toggle' if logged_in else 'login'
        subprocess.Popen([sys.executable, os.path.join(HERE, 'spotify_api.py'), action],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        core.log(f'heart: {action}')
    elif hit == 'play':
        subprocess.Popen(['playerctl', '-p', 'spotify', 'play-pause'])
        core.log('play-pause')
    elif hit == 'prev':
        subprocess.Popen(['playerctl', '-p', 'spotify', 'previous'])
        core.log('previous')
    elif hit == 'next':
        subprocess.Popen(['playerctl', '-p', 'spotify', 'next'])
        core.log('next')


def pull_control(d, root, win, s, regions, hit, track, at, touch):
    """What a press on the seek bar or the album art does, following `track` from
    card-relative (x, y) and root (x, y) `at` until release: seek along the bar; pick the
    art's colour on a click or tap, or move the widget from the press on a drag. Returns
    whether the press was one of those."""
    x, y, start = at
    if hit == 'seek' and regions.get('duration'):
        seek(d, root, win, regions, s, track)
    elif hit == 'art':
        if core.clicked(start, s, track, core.TAP_SLOP if touch else core.CLICK_SLOP):
            pick_colour(regions['art'], x / s, y / s)
        else:
            core.remember(*core.drag(d, root, win, s, track, start))
    else:
        return False
    return True


def without_idle_edges(edges, regions):
    """With no lyrics shown the height has nothing to change: the top and bottom edges move
    the widget like anywhere else, and a corner only changes the width."""
    return edges if regions.get('lyrics') else edges.replace('t', '').replace('b', '')


def scroll_lyrics(regions, s, x, y, down):
    """Moves static lyrics under window-relative (x, y) a line down or up, between their
    first line at the top and their last at the bottom. Returns the new offset, or None
    when (x, y) is not over lyrics the wheel scrolls."""
    area, static = regions.get('lyrics'), regions.get('lyrics_scroll')
    if not (area and static and area[0] * s <= x <= area[2] * s and area[1] * s <= y <= area[3] * s):
        return None
    version, last = static[:2]
    try:
        with open(LYRICS_SCROLL) as f:
            shown, offset = f.read().split()
        offset = int(offset) if shown == version else 0     # other lyrics: from the top
    except (OSError, ValueError):
        offset = 0
    offset = min(max(min(offset, last) + (1 if down else -1), 0), last)   # last shrinks when the area grows
    with open(LYRICS_SCROLL + '.tmp', 'w') as f:
        f.write(f'{version} {offset}')
    os.replace(LYRICS_SCROLL + '.tmp', LYRICS_SCROLL)
    return offset


def pick_colour(art, x, y):
    """Make the art's colour at card (x, y), logical px, the background."""
    fx, fy = (x - art[0]) / (art[2] - art[0]), (y - art[1]) / (art[3] - art[1])
    try:
        rgb = art_colours.pick(fx, fy)
    except Exception as e:
        core.log(f'art colour: failed at {fx:.2f},{fy:.2f}: {type(e).__name__}: {e}')
        return
    if rgb:
        core.log(f'art colour: {fx:.2f},{fy:.2f} -> ' + ' '.join(f'{c:.3f}' for c in rgb))


def swipe_lines(dy, row):
    """How many lines a finger moved `dy` px down has scrolled lyrics `row` px a line:
    up shows later lines (positive), down earlier ones, a line for each whole row."""
    return int(-dy / row) if row > 0 else 0


def swipe(regions, s, x, y, y0, track):
    """Scroll the static lyrics under window-relative (x, y) with the finger `track`
    follows, which touched down at root y0, until it lifts."""
    row = regions['lyrics_scroll'][2] * s
    done, held = 0, True
    while held:
        _, fy, held = track()
        lines = swipe_lines(fy - y0, row)
        while done != lines:
            down = lines > done
            if scroll_lyrics(regions, s, x, y, down) is None:
                held = False                     # the lyrics went from under it
                break
            done += 1 if down else -1
        time.sleep(0.01)
    core.log(f'swipe: {done} lines')


def scrollable(regions, s, x, y):
    """Whether window-relative (x, y) is over static lyrics a swipe scrolls."""
    area, static = regions.get('lyrics'), regions.get('lyrics_scroll')
    return bool(area and static and len(static) > 2 and
                area[0] * s <= x <= area[2] * s and area[1] * s <= y <= area[3] * s)


def seek(d, root, win, regions, s, track):
    """Follow `track` (follow_pointer() or a Touch) along the bar (draw.lua shows the
    preview), seek on release."""
    bx0, bx1 = regions['bar']
    duration = regions['duration']
    wx, _, _, _ = core.card_of(core.geometry(d, win), s)
    fraction, held = 0.0, True
    while held:
        px, _, held = track()
        fraction = min(max((px - wx - bx0 * s) / ((bx1 - bx0) * s), 0.0), 1.0)
        with open(SEEK_PREVIEW + '.tmp', 'w') as f:
            f.write(f'{fraction:.4f}')
        os.replace(SEEK_PREVIEW + '.tmp', SEEK_PREVIEW)
        time.sleep(0.02)
    subprocess.run(['playerctl', '-p', 'spotify', 'position', f'{fraction * duration:.2f}'])
    core.log(f'seek: {fraction:.3f} of {duration:.0f}s')
    time.sleep(0.4)  # keep the preview until nowplaying.py reports the new position
    try:
        os.remove(SEEK_PREVIEW)
    except OSError:
        pass

