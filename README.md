# conky-widgets

A bundle of desktop widgets for Linux (GNOME on Wayland), built on Conky. Each widget is a
card of its own that you can drag, resize and minimize, on any monitor.

There are two: a Spotify "now playing" widget, and a speech widget that shows and controls
what Claude Code sessions read aloud. One package, `conky-widgets`, ships both, and one
top-bar icon serves them.

## Spotify now playing

- Album art, title and artist, with long titles wrapped to the widget's width
- Titles, artists and lyrics in other scripts, Cyrillic, Japanese, Chinese and Korean among
  them, drawn in a font that has them (Noto Sans CJK, which the package recommends, for CJK).
  Invisible characters Spotify sometimes puts in a title, like a word joiner, are left out
  rather than drawn as a box
- Spotify-style controls: previous / play-pause / next, and a seek bar you can click or drag
- A volume slider left of the heart that sets Spotify's own volume, not the system's: click or
  drag along it, or turn the mouse wheel over it or its speaker, a step of 5% a notch. Click or
  tap the speaker to mute, and again to bring back the volume from before (kept in
  `~/.cache/conky-spotify-nowplaying/volume-before-mute`, so a restart while muted still
  restores it; half volume if none was kept). It
  follows changes made in Spotify too, and its speaker shows a cross when muted, one wave
  below half volume and two from half up. On a narrow widget with large text, it shortens,
  and is left out when it no longer fits beside NOW PLAYING
- Like button (♥) showing whether the track is in your Liked Songs, click to toggle
- Minimize (–) and close (×) buttons next to the heart, both of which hide the widget
- Smoothly scrolling synced lyrics from [LRCLIB](https://lrclib.net), as many lines as the widget
  is tall, fading out at the top and bottom once five or more show
- Plain lyrics for a track LRCLIB has no synced lyrics for: a static block from the first line,
  every line alike, that you scroll with the mouse wheel over it, or a finger swiped up or
  down on a touchscreen. When they run longer than
  the lyrics area, a slim scrollbar on its right shows how far down you are
- A placeholder cover while Spotify's DJ talks between songs (or any track without artwork)
- Background colour taken from the album art as it is, fading between tracks; the text and
  controls turn dark on a light background. On a mostly dark cover, a bright colour such as
  a band of light gives way to a deeper shade of it that the cover also has. When neither
  white nor dark text would be easy to read on the cover's main colour, the next colour on
  the cover is used instead, never a lightened or darkened one. A vivid, bright colour that
  would carry white text, like a saturated red or orange, gives way to the cover's next
  colour, and to a black or gray from the cover only when none of its colours will do. A
  cover with no such colour gets Spotify's dark gray (#181818)
- Click the album art to make the colour under the pointer the background instead. The
  choice is remembered for that artwork, so every song with the same cover, a whole album
  for one, shows it from then on. A drag that starts on the art still moves the widget
- A rounded card with a soft drop shadow, so it stands out from any wallpaper. Clicks on the
  shadow go through to whatever is under it
- Drag the widget anywhere, on any monitor; its position is remembered. Plugging in or
  unplugging a monitor keeps it where it was on its own monitor, at the same size, or moves
  it onto the nearest one while its own is unplugged
- Drag an edge or corner to resize it: the sides set its width, the top and bottom how many
  lines of lyrics it shows. An outline shows the new size until you let go; the text keeps
  its size, and the size is remembered
- Works by touch too: a tap does what a click does, once the finger lifts on the same
  control, and dragging a finger seeks, moves or resizes the widget like the mouse
- One top-bar icon for both widgets with the current track and what speech is saying, a Show
  toggle for each widget, a Spotify submenu (Text scaling from 70% to 200%, where the widget
  keeps its size unless larger text wraps a title onto another line; Reset widget size; a
  Lyrics toggle; Lyrics scrolling, Autoscroll or Static; Always on top), a Speech submenu
  (pause, skip, clear, Voice, Volume, Pace, and the widget's own settings),
  a Start at login toggle and Quit

## Speech widget

The speech widget shows what the Claude Code sessions on this machine are reading aloud
through the voice hooks of [Overmind](https://github.com/merph518/Overmind)'s `voice` plugin
(`/implement-with-speech`), and controls it. It reads the hooks' state and never speaks
itself.

- A title along the top, **CLAUDE CODE SESSION MANAGEMENT**, with minimize and close at its right
- **Sessions**: every open Claude session, the ones with speech on first, under three
  column headers: **Identifiers** (the repository's label and its issue numbers),
  **Session Information** (the name, one tag, how many lines it has queued and the last
  line read) and **Speech Setting** (On | Alerts | Off).
  The tag is the first of these that holds: **question** (one waits to be read), **busy**,
  **waiting: tests** (a test run, such as `unittest`, `pytest`, a `test_*.py` or `*_test.sh`
  script, `npm test` or `playwright test`, runs under it, or its ledger has a GitHub Actions
  run open), **waiting: local ai** (it polls `systemctl --user is-active build-pack-now`, the
  local model pipeline; another unit it polls shows by name), **waiting: ci** or
  **waiting: merge** (its `scripts/catchup.py` ledger has a Launchpad build or a pull request
  open; a skill's own ledger such as `scratchpad/sweep/ledger.tsv` counts too), **bg** (it
  runs in the background), else **idle**
- A footer with, from the top: the speaker's avatar (the image
  `~/.config/conky-widgets/speech/avatar.png` when it is there, else the Claude icon the
  package ships, else a spark drawn on an orange circle) at the bottom left, and, while a clip plays,
  a speech bubble pointing at it that holds the speaker's name and up to three lines of the
  line being read aloud (the row is as tall without the bubble, so the card does not change size
  as lines play); a progress bar with the line's elapsed time and length; then pause / resume,
  skip and next, the volume and a drop down for the voice

Each session in the speech widget's list starts with its repository's whole name, named after
its GitHub origin remote (or its folder, without one), in bold with a rule at its left. Under it are the issue numbers of that repository,
each in a chip: the issue a session's branch names, on a branch named `<type>/issue-<N>-...` as
`/implement` names them, and the same for any other open session in that repository, in number
order. They wrap onto more lines when they do not fit, and the session's row grows to hold them.
While the session is speaking, the rule is thicker and the chips are tinted and lit. Every block is as wide
as the longest name in the list (at least 90 px), so no name is cut and the names after it still line up. A
click or tap on a chip opens that issue in a new Google Chrome tab, and the chip is tinted under
the pointer (a chip is otherwise plain text on the card); a repository with no issue shows its name alone.

Once a session has pull requests waiting on the user (open rows in its `scripts/catchup.py`
ledger, which `/implement` adds after the ready signal; a `ledger`, `ledger.tsv` or `catchup.tsv`
in its scratchpad, as this repository's and the sibling repositories' scripts keep it), a white pill after its name reads
**PR #M** or **2 PRs**. A click or tap on the pill opens, in new Chrome tabs, each of those
pull requests still open with the **Manual Review Needed** label and from the session's own
branch, read from GitHub with `gh` at the click; when none is, it opens nothing and notes
that in `mouse.log`. The pill grows a little under the pointer.

A click or tap on a session's name closes the session, but only after it asks. The name is
underlined under the pointer, and a click dims the list and opens a prompt over it,
**Close <name>?**, with **Cancel** and a red **OK**; a busy session's prompt adds that
closing it stops the turn it is in. Only a click or tap on **OK** closes the session: Cancel,
a click anywhere else and Escape close the prompt and leave the session running, as does
leaving it for twenty seconds. A press in the half second after the prompt opens is ignored,
so the second click of a double click cannot answer it. While the prompt is open the widget
holds the pointer and the keyboard, as it does for the voice list. Closing sends the session's
process SIGTERM, after checking that its file in `~/.claude/sessions` still names that
session, so it also ends a session the Claude app does not show. It is written to `mouse.log`.

A session with speech on always has a second row under its name: the last line read aloud
for it, without the hook's opening "<name> session says:" and cut to one line, or *Nothing
read aloud yet* before its first. A question waiting to
be read shows as a **question** tag after the name instead of its text.
The header and progress bar stay put between lines: once a line ends, the header keeps
"<name> says:" and the bar stays full at that line's length until the next one starts.

The speech widget takes the Spotify widget's background: it reads that widget's
`~/.cache/conky-spotify-nowplaying/bg.txt` and fades with it, in step: both cards show the
same colour in every frame of the one-second fade, and their text and controls turn dark on a
light cover at the same moment. It stays on #181818 with white text while there is no
`bg.txt`. To follow another colour file, put its path on the first line of
`~/.config/conky-widgets/speech/background`; a file holding just `r g b` (0 to 1) starts a
fade of the same length each time its colour changes.

### Controls

The controls run `speechctl`, the same one the tray menu uses. In the footer, at the lower
left, three round buttons in a row: the first pauses or resumes, ⏭ after it skips the line
playing, and ⏩ skips it and the rest of that session's queue. ⏭ and ⏩ are dimmed, and do
nothing, while no line plays, and grow a little under the pointer, as the pause button does. The
**Voice:** drop down picks the voice, a session's **On**, **Alerts** and **Off** set how it
is read, an issue number under a session's repository opens that issue, its pill its ready pull
requests, and its name asks to close it. The
volume slider, drawn and sized like the Spotify widget's (it shortens, down to 32 px, before the
voice drop down's label is cut), sets the speech volume where you click, tap
or let go of a drag, from 0 at its left to 2.0 at its right, a tenth at a time; its speaker
shows a cross when muted, one wave below 1.0 and two from 1.0 up, and it follows changes made
from the tray or the keyboard. A click or tap on the speaker mutes, and the next one brings back
the volume from before (kept in `~/.cache/conky-widgets/speech/volume-before-mute`, so a restart
while muted still restores it; 1.2 if none was kept). The mouse wheel turns the volume a tenth a notch over the
slider or its speaker, steps through the voices over the closed drop down, moves a session's
setting a segment along over its segments, and scrolls the list anywhere else on it; a finger
swiped up or down on the list scrolls it too.

A click or tap on the **Voice:** drop down opens a list of the installed voices above it, over
the session list, with the current one marked; picking one sets it. While the list is open it
holds the pointer and the keyboard like a menu does, so a click anywhere else or Escape closes
it, and it closes by itself after 20 seconds. A
list longer than the card has room for scrolls with the wheel or a swipe. A touch outside the
widget is not seen, so it closes on the timeout instead. The list follows voices installed
meanwhile within ten seconds.
Taps, dragging, resizing, − and × work as they do on the Spotify widget.

### Speech setting

Each session's **On**, **Alerts** and **Off** say what is read from it:

- **On**: its replies are read aloud from then on, and it gets a second row with its last line
- **Alerts** (a new session's default): only its announcements
- **Off**: nothing; a clip of it that is playing stops

The voice plugin's phone feed carries on whatever the setting, and `/implement-with-speech`
and `/implement` change it too.

### speechctl

Every control, the tray menu's speech items and the keyboard shortcuts below run `speechctl`,
which ships with the Overmind `voice` plugin, not with this package. The widget uses the one
on `PATH`, or the one whose path is the first line of
`~/.config/conky-widgets/speech/speechctl`. With the plugin installed from its marketplace
that is:

```sh
echo ~/.claude/plugins/marketplaces/att-docs/plugins/voice/skills/voice-bridge-hooks/speechctl \
  > ~/.config/conky-widgets/speech/speechctl
```

Without `speechctl` the widget still shows what is said, but its controls do nothing (each
press is logged in `~/.cache/conky-widgets/speech/mouse.log`).

### Voices and pace

The Speech submenu's **Voice** and the widget's **Voice:** drop down list the Piper voices in
`~/.local/share/piper/` (or `SPEAK_PIPER_DIR`), a voice being its `.onnx` model and its
`.onnx.json` file. `conky-widgets-voices` lists the voices Piper publishes and fetches the ones
you pick from its [voice repository](https://huggingface.co/rhasspy/piper-voices); it downloads
nothing unless you run `add`:

```sh
conky-widgets-voices list              # English voices, with their quality, speakers and size; * is installed
conky-widgets-voices list de_          # any other language, or part of a name
conky-widgets-voices add en_GB-alan-medium en_US-ryan-medium
```

A medium voice is about 63 MB and a high one 110 to 135 MB; each download is checked against
the sizes and checksums of Piper's catalog and kept only when they match.
The widget's drop down lists a new voice within ten seconds, and the tray's Voice menu shows it within half a minute.
A model with several speakers (`arctic`, `libritts`, `vctk`) speaks as its first one for now.

**Pace** in the same submenu is how fast a voice speaks, from 0.6 (fastest) to 1.4 (slowest),
0.85 by default. It is Piper's length scale, kept in the voice settings (`pace` in
`settings.json`), and the next line spoken uses it.

### Keyboard shortcuts

GNOME can run `speechctl` from the keyboard. In **Settings → Keyboard → View and Customize
Shortcuts → Custom Shortcuts**, add one shortcut per row, with `speechctl`'s full path in
place of `speechctl`:

| Shortcut | Command | Does |
| --- | --- | --- |
| Super+Alt+S | `speechctl skip` | Skips the line playing |
| Super+Alt+N | `speechctl next` | Skips it and the rest of that session's queue |
| Super+Alt+P | `speechctl toggle` | Pauses or resumes |
| Super+Alt+↑ | `speechctl volume up` | Volume up a tenth |
| Super+Alt+↓ | `speechctl volume down` | Volume down a tenth |
| Super+Alt+V | `speechctl voice next` | The next installed voice |

## Install

Install from the PPA, which also pulls in the dependencies (Conky, playerctl, Python GObject
bindings, fonts) and brings new versions with your other updates:

```sh
sudo add-apt-repository ppa:mfagerstrom/conky-spotify-nowplaying
sudo apt install conky-widgets
```

The package used to be called `conky-spotify-nowplaying`. If you installed it under that name
from the PPA, `sudo apt upgrade` moves you over: `conky-spotify-nowplaying` becomes an empty
transitional package that pulls in `conky-widgets`, and you can `sudo apt remove
conky-spotify-nowplaying` afterwards. Your settings and autostart entry carry over, and a
running widget restarts from the new files.

The PPA builds for Ubuntu 26.04 (`resolute`) only, and that is the only release the widget is
tested on. On another release you can try the latest `.deb` from the
[Releases page](https://github.com/merph518/Gnome-Widgets/releases) instead; apt
reports any dependency that release lacks, and a `.deb` installed this way does not update itself.
It replaces a `conky-spotify-nowplaying` installed the same way:

```sh
sudo apt install ./conky-widgets_2.0.0_all.deb
```

Then open **Spotify Now Playing** from the app grid. Opening it again hides the widget, or
shows it if it is hidden.

The – and × buttons at a widget's top right both hide that widget, and only that one. While
any widget runs there's one icon in the top bar for all of them. Click it to see the current
track and what speech is saying (or **Speech idle** / **Speech paused**), tick **Show Spotify
widget** or **Show speech widget** to show or hide each one (ticking one that isn't running
starts it), toggle **Start at login** for both, or **Quit**, which stops both. A hidden widget
keeps running, so it comes back at once and where it was, and hidden speech keeps talking.
Hidden or shown is remembered: a widget hidden when you quit or log out starts hidden, and
the icon stays while both are hidden.

The **Spotify** submenu holds that widget's Text scaling, Reset widget size, Lyrics, Lyrics
scrolling and Always on top. The **Speech** submenu holds **Pause** / **Resume**, **Skip**,
**Clear queue**, **Voice**, **Volume**, and the speech widget's own Text scaling, Reset widget
size, **Collapse when idle** (off by default: on, the widget shrinks to its title and the avatar
while nothing is said or queued) and Always on top. Its speech controls run `speechctl` (see
[Speech widget](#speech-widget)); without one they're greyed out.

Two of the Spotify settings are about lyrics, and both are remembered:

- **Lyrics** (on by default): untick it and the widget shows only the track, with no lyrics
  area and no lyrics looked up. Tick it again and the lyrics area comes back at the height you
  gave it, with the playing track's lyrics.
- **Lyrics scrolling**: **Autoscroll** (the default) scrolls synced lyrics along with the song,
  the current line bold in the middle. **Static** shows them like plain lyrics instead: every
  line alike from the first one, scrolled with the mouse wheel, back at the top on the next
  track. Plain lyrics are always static, having no timing to follow. The choice is greyed out
  while Lyrics is off.

Right-click the app icon for more:

- **Start at login** / **Don't start at login**
- **Log in to Spotify (like button)**

The same things work from a terminal:

```sh
conky-widgets spotify                   # start and show, or hide if showing
conky-widgets spotify start|stop|restart|status   # a hidden widget starts hidden
conky-widgets spotify show|hide         # show a hidden widget, or hide it
conky-widgets spotify autostart on|off
conky-widgets spotify login
conky-widgets show|hide                 # every running widget
conky-widgets stop|restart|status       # every widget
```

`speech` takes the place of `spotify` for the speech widget, which has an app-grid entry and an
autostart toggle of its own. One supervisor runs every widget that is started, and `run.log` is
in `~/.cache/conky-widgets/`. `conky-spotify-nowplaying <command>` still works: it is
`conky-widgets spotify <command>`.

To uninstall: `sudo apt remove conky-widgets` (and `conky-spotify-nowplaying`, if the
transitional package is still there). Your settings stay in
`~/.config/conky-spotify-nowplaying` (delete that folder too for a clean slate), and the
autostart entry, if you turned it on, is `~/.config/autostart/conky-spotify-nowplaying.desktop`.

### Like button (optional)

Playback control, lyrics and album art work without any account setup.

The heart reads whether a song is liked from the Spotify desktop app's own copy of your Liked
Songs, which it keeps in `~/.cache/spotify/Users/<name>-user/primary.ldb`. The widget only reads
those files, while the app runs or not, and sends Spotify nothing to do it, so the heart follows
a like or unlike made in the app within about five seconds, needs no login and works while
Spotify rate-limits the widget. It looks for the app's cache where the Spotify apt package,
snap and flatpak keep it. Without those files (Spotify used only on another device, say), or
when they cannot be read, the heart asks the Spotify Web API instead, every two minutes, which needs the login below.

Clicking the heart likes or unlikes the song through the Web API, which needs the login:

1. Create an app at <https://developer.spotify.com/dashboard> with redirect URI
   `http://127.0.0.1:8888/callback` and the **Web API** enabled.
2. Save its Client ID:
   `mkdir -p ~/.config/conky-spotify-nowplaying && echo YOUR_CLIENT_ID > ~/.config/conky-spotify-nowplaying/spotify-client-id`
3. Click the heart on the widget (or run `conky-spotify-nowplaying login`) and approve access in
   the browser.

No client secret is needed (PKCE). The refresh token is stored in
`~/.config/conky-spotify-nowplaying/spotify-token.json` with mode 600.

The heart shows a song as liked when any release of it is saved (single, album version, ...),
matching the Spotify app; unliking from the widget removes every saved release. Like the app,
it does not count a copy saved from a duplicate listing of the same album (Spotify sometimes
lists one album twice, under the same barcode).
To know which songs you have saved under another release, the widget keeps an index of your
Liked Songs in `~/.cache/conky-spotify-nowplaying/library.json`, and counts a release in it
only while the app still has it saved. Finding those other releases uses the Web API, so it
needs the login and pauses while Spotify rate-limits the widget; the heart then shows whether
the app has this exact release saved. After you log in the widget reads
the whole library slowly in the background, one page of 50 songs every 15 seconds (about 25
minutes for 5,000 songs), and does the same again once a day. In between it fetches your
newest likes every five minutes, or, while it can read the app's Liked Songs, only when the
app has a song the index lacks. Until the index is complete,
a song liked only as a different release may show as not liked. The index saves its place
after every page, so quitting the widget or hitting a rate limit resumes the read rather
than restarting it.

Spotify's limits for new developer apps are low, and a request sent while rate-limited can
extend the block, so the widget keeps its traffic small. With the app's files readable, steady
play costs about one request per song the app has not saved (to look for other releases of it,
remembered across restarts in `lookups.json`), plus the daily library read. Every request is
logged with its status to `~/.cache/conky-spotify-nowplaying/nowplaying.log` as an `api:` line.
Only one copy of the widget runs against that cache: a second one waits until the first exits.
If Spotify rate-limits the app, anywhere, the widget stops calling Spotify until the block lifts. The heart keeps showing what the Spotify app has
saved, and a click on it only says when likes can be changed again. Without the app's files
to read, the heart is hidden meanwhile, since it can neither read nor change likes;
everything else keeps working, and minimize and close stay where they are. It comes back,
with the track's like state checked again, once the block lifts.

## Development

Run straight from a checkout without installing the package. Its dependencies still have to be
there: install the ones listed under `Depends:` in `debian/control` with apt.

```sh
bin/conky-widgets spotify start
```

Run the unit tests (standard library `unittest`, same dependencies as above; they use
temporary directories and never touch `~/.cache`, `~/.config` or the network):

```sh
python3 -m unittest discover -s tests
```

Build the package into `dist/` (needs `sudo apt install debhelper devscripts`):

```sh
./build-deb.sh
```

Packaging lives in `debian/`; the version comes from `debian/changelog`.

### Releasing

Releases are cut with the `/release` skill in Claude Code, and its steps in
[`.claude/skills/release/SKILL.md`](.claude/skills/release/SKILL.md) are the one written-down
process. In short: a `debian/changelog` entry (the only place the version lives), the
[static checks](.claude/skills/_shared/static-checks.md), `./build-deb.sh` and a smoke test of
the installed package, a commit and tag, a GitHub release with the `.deb` attached, and
`./release-ppa.sh` to upload the signed source package to the PPA (needs `dput` and a GPG key
registered on Launchpad), followed until Launchpad publishes it.

## How it works

| File | Role |
| --- | --- |
| `bin/conky-widgets` | Launcher: `conky-widgets <spotify\|speech> start/stop, show/hide, autostart, login`; one supervisor for every widget that runs, which restarts their processes if they exit |
| `bin/conky-widgets-voices` | Lists Piper's published voices and downloads the ones you name into the folder `speechctl voices` reads |
| `bin/conky-spotify-nowplaying` | The Spotify widget's old launcher, kept as `conky-widgets spotify …` for the app-grid and autostart entries of older versions |
| `src/spotify/conky.conf` | Conky window setup; renders the text generated by `nowplaying.py`, and sizes the window to it |
| `src/spotify/nowplaying.py` | Reads Spotify via `playerctl` (MPRIS), fetches art/lyrics/like state, lays the widget out at its size settings, and writes the widget text plus geometry for `draw.lua` and click areas for `conky-mouse.py` |
| `src/spotify/draw.lua` | Cairo drawing: background, buttons, seek bar and times, lyrics (20 fps) |
| `src/common/conky-mouse.py` | Started as `conky-mouse.py spotify` or `conky-mouse.py speech`; handles clicks and taps, the mouse wheel and swipes over static lyrics, dragging and resizing (Conky's own mouse hook gets no button presses under XWayland), keeps the window at its saved position and always on top when set, and unmaps it while hidden |
| `src/speech/conky.conf` | The speech widget's conky window; renders the text generated by `speechqueue.py` |
| `src/speech/speechqueue.py` | Reads the open Claude sessions and the speaking hook's state (read only), lays the speech widget out, and writes its text, geometry for its `draw.lua`, click areas and the sessions list |
| `src/speech/sessions.py` | Lists the open Claude sessions from `~/.claude/sessions`, as `speechctl` finds them |
| `src/speech/draw.lua`, `src/speech/mouse.py` | The speech widget's Cairo drawing, and what its controls, the volume's mute speaker, the close prompt, the wheel and swipes over its list do for `conky-mouse.py`, through `speechctl` |
| `src/common/theme.lua` | Drawing and colour helpers every widget's `draw.lua` shares: the card and its shadow, the volume slider, and the foreground that follows a fading background |
| `src/common/widget_size.py` | Reads and writes a widget's size settings: width, lyrics (Spotify) or sessions list (speech) height, text scale |
| `src/spotify/mouse.py` | What the Spotify widget's controls do for `conky-mouse.py`: the buttons, the seek bar, the volume slider and its mute speaker (Spotify's own volume, through MPRIS), the album art's colour pick, and the wheel over the volume and the wheel and swipes over static lyrics |
| `src/spotify/lyrics_settings.py` | Reads and writes the lyrics settings: on or off, autoscroll or static |
| `src/spotify/art_colours.py` | Takes the background colour from the spot clicked on the album art, and keeps it per artwork |
| `src/spotify/spotify_api.py` | Minimal Spotify Web API client (PKCE login, like/unlike, Liked Songs index, rate-limit backoff) |
| `src/spotify/spotify_local.py` | Reads the Spotify desktop app's Liked Songs from its LevelDB on disk, read-only, for the heart |
| `src/tray.py` | The one top-bar (AppIndicator) icon for every widget: current track and speech line, Show per widget, Spotify and Speech submenus, start at login, Quit |
| `src/tray_model.py` | What the tray reads and writes: each widget's hidden flag and settings files, the speech state, and `speechctl` |
| `debian/`, `packaging/` | Debian packaging (also used for the PPA), desktop entry, icons |

Settings of the Spotify widget live in `~/.config/conky-spotify-nowplaying/` (`position`, `size`, `on-top`, `lyrics`,
`lyrics-scrolling`, `art-colours.json`, `spotify-client-id`, `spotify-token.json`) and runtime
files/logs in `~/.cache/conky-spotify-nowplaying/`.

## Notes

- Tested on Ubuntu 26.04, GNOME/Wayland, with 2x display scaling across three monitors.
- The widget is an undecorated window on every workspace. Always on top, it stays above
  other windows; with that unticked, it is raised when clicked and covered like any other.
- Lyrics coverage depends on LRCLIB. Synced lyrics are always preferred, and scroll along
  with the song, the current line bold in the middle. A track with only plain (untimed)
  lyrics shows them from the top without following the song: scroll them with the mouse
  wheel over the lyrics, a line per step, between the first and the last line, with a
  scrollbar on the right when they don't all fit. They start at the top again on the next
  track. Lyrics scrolling set to Static shows synced lyrics
  the same way. Each track's lyrics are
  cached in `~/.cache/conky-spotify-nowplaying/lyrics/` (up to 2000 tracks, the least
  recently played dropped first), so a track played again, or after a restart, shows them
  without asking LRCLIB. A track LRCLIB has no lyrics for is asked about again after
  a week; a failed lookup is never cached. Delete that folder to fetch everything afresh.

## License

[MIT](LICENSE)
