# Static checks

Shared by every skill, by [ready-signal.md](ready-signal.md) and
[self-review.md](self-review.md), and by any commit a session makes outside a
skill. Ported in idea from PlaywrightTesting's `static-checks.md`; the commands
are this repository's own. This file is the only place the list is written out.
A skill that needs it points here rather than restating it.

This repository has no CI, so the checks run locally, on the branch head,
before every push to a pull request, again before the self review starts, and
before `/release` builds.

## The list

```bash
python3 -m py_compile src/*.py src/*/*.py bin/conky-widgets scripts/*.py
python3 scripts/catchup_test.py
python3 -m unittest discover -s tests
luac5.3 -p src/common/theme.lua src/spotify/draw.lua src/spotify/conky.conf \
  src/speech/draw.lua src/speech/conky.conf
sh -n build-deb.sh release-ppa.sh debian/postinst
desktop-file-validate packaging/*.desktop
test "$(git write-tree --prefix=.claude/att-docs/)" = "$(sed -n 's/^tree=//p' .claude/att-docs.lock)" \
  && git diff --quiet -- .claude/att-docs \
  && test -z "$(git ls-files --others --exclude-standard -- .claude/att-docs)"
```

Every command must exit 0 and print nothing, apart from the test summaries
`catchup_test.py` and `unittest` print.

- The last command fails when the vendored Overmind copy differs from the tree
  `.claude/att-docs.lock` pins, so a hand edit to it shows offline. Moving the
  pin is `scripts/overmind-sync.sh <tag>`, followed by
  `claude plugin update voice@att-docs`. The tree is read from the index, which
  `overmind-sync.sh` fills, so the check passes before the sync is committed;
  an edit, a deletion or a file added under the copy fails it. Run it from the
  repository root.
- `desktop-file-validate` hints count as failures to fix. It once caught a
  duplicate main category that every other check passed.
- `luac5.3 -p` only parses; it catches syntax errors, not a bad call or a
  misspelt name. `src/spotify/conky.conf` is Lua too (conky reads its config with its
  embedded interpreter), and conky links Lua 5.3, so `luac5.3` reads both
  files with the grammar conky uses. After a conky upgrade,
  `ldd "$(command -v conky)" | grep liblua` shows the version it links; when
  that changes, the checker here changes with it. `luac5.3` comes from the
  `lua5.3` package, installed with apt in the user's terminal
  (`sudo apt install lua5.3`). While it is missing, the check has not run: say
  so in the test plan, and let the run below read the Lua errors out of the
  log instead.

## A build, when packaging could break

A change that touches `debian/`, `packaging/` or `build-deb.sh`, or adds,
removes or renames a file under `src/` or `bin/`, also builds the package,
since only a build shows a file `debian/install` names that is not there, or a
build script that parses but does not run:

```bash
./build-deb.sh
dpkg-deb --contents "dist/conky-widgets_$(dpkg-parsechangelog -S Version)_all.deb"
```

`dist/` is ignored by git and keeps every version built in it, so the listing
names the version rather than globbing. `build-deb.sh` needs `debhelper` and
`devscripts`, and cleans up after itself with `dh_clean`. It writes through the
parent directory, which sibling worktrees share, so it holds a lock on that
directory, and a second session's build waits for the first.

## Then a run

The checks cannot see a Lua runtime error or a path that only exists under
`/usr`. A change that touches `src/`, `bin/`, `packaging/` or `debian/` has not
been checked until it has run: as an isolated copy of the widgets that belongs to
the session, as in `/implement` Section 6, or installed, as in `/release` step 4.
The isolated copy is the standard way to run from a working session, and its
`--installed` option runs the installed launcher in the same isolation:

```bash
scripts/isolated-widgets.py start                  # a copy of its own, beside the user's
RUN=$(scripts/isolated-widgets.py path)/home/.cache
grep -iE 'error|critical|traceback|lua' "$RUN/conky-widgets/run.log"
grep 'api:' "$RUN/conky-spotify-nowplaying/nowplaying.log"    # must print nothing
scripts/isolated-widgets.py stop
```

The copy has its own home, fixture speech sessions and no sound, no tray icon, no
Spotify login and window class and position of its own. A session never stops,
replaces, restarts or captures a copy it did not start: the user's, installed or
from a checkout, or another session's. `critical` is there for GLib's
`Gtk-CRITICAL` lines, which name no error. The log should hold nothing beyond
conky's startup chatter; a run in the user's own copy (the installed smoke test of
`/release` step 4, which the user does) also shows the
`libayatana-appindicator is deprecated` warning from the tray.

The pull request's test plan says which run was done. A change to
documentation, skills or `scripts/` alone owes no run.

## No pre-commit hook

The list is not wired into a git hook. Hooks live in `.git/hooks`, which every
worktree shares and git does not version, so one installed there would run on
every session's commits at once, including the temporary WIP commits
`/new-branch` recommends over a stash. The skills run the list at the points
named above instead.
