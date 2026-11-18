# Overmind

These rules are for the `merph518/Overmind-Mod` repository itself. In a vendored copy under
`.claude/att-docs/`, ignore this file.

## Every pull request follows the implement procedure

The procedure in `.claude/skills/implement/SKILL.md` is the standard for every pull request
in this repository, whether or not it starts from an issue and whether or not a session
was asked to implement one. At the start of any change, before editing anything, read that
file and the general skill it builds on, `plugins/general/skills/implement/SKILL.md`, and
follow them. The section "Applies to every pull request" in the first file says which
steps to skip when there is no issue.

Two parts are easy to miss:

- The self review loop runs on every pull request, with a review of every change,
  including the last fix. Section 7 sets the pass limit.
- When the loop ends, add the `Manual Review Needed` label and read it back. A pull request
  reported ready without the label is not ready.

## Agent skills

### Issue tracker

Issues live in GitHub Issues for `merph518/Overmind-Mod`, worked with the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five default triage labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Other Repos

Pointers to the other repositories on this machine, so a session started here can open
or clone one without searching the disk. Read a repository's own `CLAUDE.md`, when it has one, before
changing it, and do work there from a session started in that repository. Every name in
`.github/consumers.json` has a pointer; `scripts/consumers_test.py` fails when one is
missing.

- `ATT-Test-Pack-Gen` (builds test pack workbooks with a model on the local workstation; pins Overmind): `~/Code/ATT-Test-Pack-Gen`. Clone from https://github.com/merph518/ATT-Test-Pack-Gen if missing.
- `Gnome-Widgets` (Spotify now-playing Conky widget for GNOME on Wayland; pins Overmind): `~/Code/conky-spotify-nowplaying`. Clone from https://github.com/merph518/Gnome-Widgets if missing. The folder name differs from the repository name.
- `Laundry-Bot` (Discord bot that runs the family laundry schedule; pins Overmind): `~/Code/LaundryBot`. Clone from https://github.com/merph518/Laundry-Bot if missing. The local clone's remote may still name `mfagerstrom/LaundryBot`, which GitHub redirects.
- `Playwright-Testing` (the Automated Testing Team's Playwright test suites; pins Overmind): `~/Code/Playwright-Testing`. Clone from https://github.com/merph518/Playwright-Testing if missing. The local clone may be behind, so `git pull` first.
- `personal` (personal tasks; pins Overmind): `~/Code/personal`. Clone from https://github.com/merph518/personal if missing. The local clone may sit on an old branch whose upstream is gone, so check out `main` and `git pull` first.
- `AI-Health-Coach` (family weight loss coach; pins Overmind with a lock not yet migrated, so it is not in `consumers.json`): `~/Code/fagerteam-health-coach`. Clone from https://github.com/merph518/AI-Health-Coach if missing. The local clone's remote may still name `mfagerstrom/fagerteam-health-coach`, which GitHub redirects, and may be behind, so `git pull` first.
- `TheRPGClub-bot` (GameDB Discord bot for the RPG Club community, owned by the `TheRPGClub` organization; pins Overmind but is not in `consumers.json`): `~/Code/bot`. Clone from https://github.com/TheRPGClub/TheRPGClub-bot if missing.
