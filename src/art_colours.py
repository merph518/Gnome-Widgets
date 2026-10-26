"""Background colours picked by clicking the album art, kept per artwork in
~/.config/conky-spotify-nowplaying/art-colours.json as {art URL: [r, g, b]}, channels 0-1.

conky-mouse.py calls pick() when the art is clicked; nowplaying.py asks chosen() before it
works a colour out of the art itself, so a cover picked once keeps its colour on every track
that shows it, a whole album for one. Spotify's art URLs name the image
(i.scdn.co/image/<id>), so the URL is the artwork's key.
"""
import json, os

CONF = os.path.expanduser('~/.config/conky-spotify-nowplaying')
COLOURS = os.path.join(CONF, 'art-colours.json')
CACHE = os.path.expanduser('~/.cache/conky-spotify-nowplaying')
COVER = os.path.join(CACHE, 'cover.jpg')
COVER_URL = os.path.join(CACHE, 'cover.url')       # the URL cover.jpg came from (nowplaying.py)
BG = os.path.join(CACHE, 'bg.txt')                 # what draw.lua fades to
SPOT = 0.02                                        # the square around a click, as a fraction of the cover


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f'{path}.{os.getpid()}.tmp'
    with open(tmp, 'w') as f:
        f.write(text)
    os.replace(tmp, path)


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
    shows again. Returns the colour, or None when no cover is shown."""
    try:
        with open(COVER_URL) as f:
            url = f.read().strip()
    except OSError:
        return None
    if not url:
        return None
    r, g, b = colour_at(COVER, fx, fy)
    colours = load()
    colours[url] = [round(r, 4), round(g, 4), round(b, 4)]
    _write(COLOURS, json.dumps(colours, indent=0) + '\n')
    _write(BG, f'{r:.3f} {g:.3f} {b:.3f}\n')
    return r, g, b
