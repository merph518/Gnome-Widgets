"""The Spotify widget's part of the mouse helper, loaded by conky-mouse.py when it is
started as `conky-mouse.py spotify`: what its controls do, the seek bar, the volume slider,
the speaker that mutes it, the album art's colour pick, and the wheel over the volume and the
wheel and swipes over static lyrics.

conky-mouse.py gives this module itself as `core`, for the window handling it shares:
logging, following the pointer, dragging and the card's geometry.
"""
import os, subprocess, sys, time

import art_colours

NAME = 'conky-spotify-nowplaying'              # the config and cache folders, the launcher
WM_CLASS = 'ConkySpotifyNowPlaying'            # conky.conf's own_window_class
OUTLINE = 0x1db954                             # Spotify green: the outline a resize shows
BUTTONS = ('heart', 'play', 'prev', 'next', 'volume_icon')   # the controls this widget's click or tap presses
# The regions nowplaying.py writes, in the order a press looks through them.
HEIGHT_REGION = 'lyrics'                       # the region the second size setting is the height of
REGIONS_ORDER = ('heart', 'play', 'prev', 'next', 'minimize', 'close', 'volume_icon', 'volume', 'seek', 'art')
CONF = os.path.expanduser(f'~/.config/{NAME}')
CACHE = os.path.expanduser(f'~/.cache/{NAME}')
SEEK_PREVIEW = os.path.join(CACHE, 'seek-preview')
VOLUME_PREVIEW = os.path.join(CACHE, 'volume-preview')   # the level under the pointer, for draw.lua
VOLUME_STEP = 0.05                             # a wheel step's change of Spotify's volume
VOLUME_MUTED = 0.005                           # below this volume the speaker draws its cross (theme.lua)
VOLUME_UNMUTED = 0.5                           # what the speaker restores when no level was remembered
VOLUME_BEFORE_MUTE = os.path.join(CACHE, 'volume-before-mute')   # the level the speaker restores
LYRICS_SCROLL = os.path.join(CACHE, 'lyrics-scroll')   # '<lyrics version> <line offset>', for draw.lua
HERE = os.path.dirname(os.path.abspath(__file__))
core = None                                    # conky-mouse.py's module, set when it loads this one


def start():
    """Clears what a previous run left behind if it was killed mid-seek or mid-drag."""
    for preview in (SEEK_PREVIEW, VOLUME_PREVIEW):
        try:
            os.remove(preview)
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
    elif hit == 'volume_icon':
        toggle_mute()


def spotify_volume():
    """Spotify's volume through MPRIS, or None when it cannot be read (Spotify is not running)."""
    try:
        out = subprocess.run(['playerctl', '-p', 'spotify', 'volume'], capture_output=True, text=True,
                             timeout=5)
        return float(out.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def remembered_volume():
    """The level before the last mute, or None when none was kept."""
    try:
        with open(VOLUME_BEFORE_MUTE) as f:
            level = float(f.read())
    except (OSError, ValueError):
        return None
    return level if level >= VOLUME_MUTED else None


def toggle_mute():
    """Mutes Spotify, keeping its volume in VOLUME_BEFORE_MUTE so a restart while muted still
    restores it, or restores that volume when it is already muted. The kept level stays when
    the volume is already zero, and VOLUME_UNMUTED comes back where none was kept (a slider
    dragged to its left end)."""
    level = spotify_volume()
    if level is None:
        core.log('volume: mute: Spotify volume unreadable')
        return
    if level >= VOLUME_MUTED:
        os.makedirs(CACHE, exist_ok=True)
        with open(VOLUME_BEFORE_MUTE + '.tmp', 'w') as f:
            f.write(f'{level:.4f}')
        os.replace(VOLUME_BEFORE_MUTE + '.tmp', VOLUME_BEFORE_MUTE)
        subprocess.run(['playerctl', '-p', 'spotify', 'volume', '0'])
        core.log(f'volume: mute (was {level:.2f})')
        return
    back = remembered_volume() or VOLUME_UNMUTED
    subprocess.run(['playerctl', '-p', 'spotify', 'volume', f'{back:.2f}'])
    try:
        os.remove(VOLUME_BEFORE_MUTE)
    except OSError:
        pass
    core.log(f'volume: unmute ({back:.2f})')


def pull_control(d, root, win, s, regions, hit, track, at, touch):
    """What a press on the seek bar, the volume slider or the album art does, following
    `track` from card-relative (x, y) and root (x, y) `at` until release: seek along the
    bar; set the volume along the slider; pick the art's colour on a click or tap, or move
    the widget from the press on a drag. Returns whether the press was one of those."""
    x, y, start = at
    if hit == 'seek' and regions.get('duration'):
        seek(d, root, win, regions, s, track)
    elif hit == 'volume' and regions.get('volume_bar'):
        set_volume(d, win, regions, s, track)
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


def wheel(regions, s, x, y, down):
    """What a wheel step down (or up) over card-relative (x, y) does: turns Spotify's volume
    down or up a step over the volume slider, else scrolls static lyrics there. Returns
    'volume', the lyrics' new offset, or None where the wheel does nothing."""
    area = regions.get('volume_wheel')
    if area and area[0] * s <= x <= area[2] * s and area[1] * s <= y <= area[3] * s:
        # relative, so steps faster than nowplaying.py reports the level all count
        subprocess.run(['playerctl', '-p', 'spotify', 'volume', f'{VOLUME_STEP}{"-" if down else "+"}'])
        core.log(f'volume: wheel {"down" if down else "up"}')
        return 'volume'
    return scroll_lyrics(regions, s, x, y, down)


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



def set_volume(d, win, regions, s, track):
    """Follow `track` (follow_pointer() or a Touch) along the volume slider, setting
    Spotify's volume as it moves (draw.lua shows the preview until nowplaying.py reports
    the level), and once more where it is let go."""
    bx0, bx1 = regions['volume_bar']
    wx, _, _, _ = core.card_of(core.geometry(d, win), s)
    fraction, sent, held = 0.0, None, True
    while held:
        px, _, held = track()
        fraction = round(min(max((px - wx - bx0 * s) / ((bx1 - bx0) * s), 0.0), 1.0), 2)
        with open(VOLUME_PREVIEW + '.tmp', 'w') as f:
            f.write(f'{fraction:.2f}')
        os.replace(VOLUME_PREVIEW + '.tmp', VOLUME_PREVIEW)
        if fraction != sent:
            subprocess.run(['playerctl', '-p', 'spotify', 'volume', f'{fraction:.2f}'])
            sent = fraction
        time.sleep(0.02)
    core.log(f'volume: {fraction:.2f}')
    time.sleep(0.4)  # keep the preview until nowplaying.py reports the new level
    try:
        os.remove(VOLUME_PREVIEW)
    except OSError:
        pass
