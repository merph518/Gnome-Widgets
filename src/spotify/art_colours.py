"""Background colours picked by clicking the album art, kept per artwork in
~/.config/conky-spotify-nowplaying/art-colours.json as {art URL: [r, g, b]}, channels 0-1.

conky-mouse.py calls pick() when the art is clicked; nowplaying.py asks chosen() before it
works a colour out of the art itself, so a cover picked once keeps its colour on every track
that shows it, a whole album for one. Spotify's art URLs name the image
(i.scdn.co/image/<id>), so the URL is the artwork's key.
"""
import json, math, os, threading, time

CONF = os.path.expanduser('~/.config/conky-spotify-nowplaying')
COLOURS = os.path.join(CONF, 'art-colours.json')
CACHE = os.path.expanduser('~/.cache/conky-spotify-nowplaying')
COVER = os.path.join(CACHE, 'cover.jpg')
COVER_URL = os.path.join(CACHE, 'cover.url')       # the URL cover.jpg came from (nowplaying.py)
BG = os.path.join(CACHE, 'bg.txt')                 # what draw.lua fades to
# Shown for a track without art. Every such track shares it, so it never keeps a pick.
NO_ART_URL = 'file://' + os.path.join(os.path.dirname(os.path.abspath(__file__)), 'no-art.png')
BOOT_ID = '/proc/sys/kernel/random/boot_id'
NO_BG = 0.094                                      # what theme.lua shows without a bg.txt: #181818
SPOT = 0.02                                        # the square around a click, as a fraction of the cover


def _write(path, text):
    # nowplaying.py's threads and conky-mouse.py can write bg.txt at once, so each writer
    # has its own temporary file.
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f'{path}.{os.getpid()}.{threading.get_ident()}.tmp'
    with open(tmp, 'w') as f:
        f.write(text)
    os.replace(tmp, path)


def boot_id():
    """This boot's id, which bg.txt carries beside its start time: CLOCK_BOOTTIME restarts at
    each boot, so a start from another boot is long finished."""
    try:
        with open(BOOT_ID) as f:
            return f.readline().strip()
    except OSError:
        return ''


def _numbers(words, n):
    try:
        return [float(w) for w in words[:n]] if len(words) >= n else None
    except ValueError:
        return None


def shown_bg(now):
    """The colour the widgets show at now (CLOCK_BOOTTIME seconds): where bg.txt's fade has got
    to, as theme.lua's fade works it out; Spotify's #181818 while there is no bg.txt."""
    try:
        with open(BG) as f:
            words = f.readline().split()
    except OSError:
        words = []
    v = _numbers(words, 7)
    if v and len(words) >= 8:
        if words[7] != boot_id():
            return tuple(v[:3])
        k = 1 - math.exp(-max(now - v[6], 0) * 3)
        return tuple(v[3 + i] + (v[i] - v[3 + i]) * k for i in range(3))
    return tuple(_numbers(words, 3) or (NO_BG,) * 3)


def write_bg(rgb):
    # The target, the colour shown now, now and this boot: both widgets fade from the colour
    # shown to the target over the same wall-clock second, counted from the time written here.
    now = time.clock_gettime(time.CLOCK_BOOTTIME)
    _write(BG, '{:.3f} {:.3f} {:.3f} {:.3f} {:.3f} {:.3f} {:.3f} {}\n'.format(
        *rgb, *shown_bg(now), now, boot_id()))


def _shown_url():
    try:
        with open(COVER_URL) as f:
            return f.read().strip()
    except OSError:
        return ''


def load():
    try:
        with open(COLOURS) as f:
            colours = json.load(f)
        return colours if isinstance(colours, dict) else {}
    except (OSError, ValueError):
        return {}


def chosen(url):
    """The colour picked for the art at url, or None when none was."""
    rgb = load().get(url) if url else None
    try:
        r, g, b = (min(max(float(c), 0.0), 1.0) for c in rgb)
        return r, g, b
    except (TypeError, ValueError):
        return None


def colour_at(path, fx, fy):
    """The cover's colour at (fx, fy), fractions of its width and height: of the pixels in a
    square SPOT wide around it, the one nearest their mean. A plain mean of a spot on a thin
    line or an edge is a blend no pixel has; one pixel alone can be JPEG noise."""
    import gi
    gi.require_version('GdkPixbuf', '2.0')
    from gi.repository import GdkPixbuf
    pb = GdkPixbuf.Pixbuf.new_from_file(path)
    w, h, n, stride, px = (pb.get_width(), pb.get_height(), pb.get_n_channels(),
                           pb.get_rowstride(), pb.get_pixels())
    cx = min(max(int(fx * w), 0), w - 1)
    cy = min(max(int(fy * h), 0), h - 1)
    r = max(int(SPOT * w / 2), 0)
    spot = []
    for yy in range(max(cy - r, 0), min(cy + r, h - 1) + 1):
        for xx in range(max(cx - r, 0), min(cx + r, w - 1) + 1):
            i = yy * stride + xx * n
            spot.append((px[i] / 255, px[i + 1] / 255, px[i + 2] / 255))
    mean = [sum(c) / len(spot) for c in zip(*spot)]
    return min(spot, key=lambda p: sum((a - b) ** 2 for a, b in zip(p, mean)))


def pick(fx, fy):
    """Make the shown cover's colour at (fx, fy) the background, now and whenever that art
    shows again. Returns the colour, or None when no cover, or the placeholder, is shown, or
    the cover changed while it was read: then the pixels could be the new cover's."""
    url = _shown_url()
    if not url or url == NO_ART_URL:
        return None
    r, g, b = colour_at(COVER, fx, fy)
    if _shown_url() != url:
        return None
    colours = load()
    colours[url] = [round(r, 4), round(g, 4), round(b, 4)]
    _write(COLOURS, json.dumps(colours, indent=0) + '\n')
    write_bg((r, g, b))
    return r, g, b
