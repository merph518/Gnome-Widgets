#!/usr/bin/env python3
"""Static checks for the repository. Standard library only.

Checks: plugin and marketplace JSON, that every plugin has its marketplace.json and
release-please-config.json entries, SKILL.md frontmatter, relative Markdown links,
and syntax of every .py, .mjs/.js and .sh file. shellcheck runs on .sh files when it
is installed; its output is advisory and never fails the run.
"""
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {"node_modules", ".git", "__pycache__"}
errors = []


def error(path, message):
    errors.append(f"{os.path.relpath(path, ROOT)}: {message}")


def walk():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        rel = os.path.relpath(dirpath, ROOT)
        # Other worktrees live under .claude/worktrees and are checked on their own.
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIRS
            and not (rel == ".claude" and d == "worktrees")
        ]
        for name in filenames:
            yield os.path.join(dirpath, name)


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        error(path, f"not valid JSON ({e})")
        return None


def check_json(files):
    for path in files:
        base = os.path.basename(path)
        parent = os.path.basename(os.path.dirname(path))
        if base == "plugin.json" and parent == ".claude-plugin":
            load_json(path)
        elif base == "marketplace.json" and parent == ".claude-plugin":
            data = load_json(path)
            if not isinstance(data, dict):
                continue
            plugins = data.get("plugins", [])
            if not isinstance(plugins, list):
                error(path, '"plugins" is not a list')
                continue
            for plugin in plugins:
                source = plugin.get("source") if isinstance(plugin, dict) else None
                if not isinstance(source, str):
                    error(path, f"plugin {plugin!r} has no string source")
                    continue
                if not os.path.exists(os.path.join(ROOT, source)):
                    error(path, f"source {source} does not exist")


def check_skills(files):
    prefixes = ("plugins" + os.sep, os.path.join(".claude", "skills") + os.sep)
    for path in files:
        if os.path.basename(path) != "SKILL.md":
            continue
        if not os.path.relpath(path, ROOT).startswith(prefixes):
            continue
        with open(path, encoding="utf-8") as f:
            text = f.read()
        m = re.match(r"---\r?\n(.*?)\r?\n---\s*(\r?\n|$)", text, re.S)
        if not m:
            error(path, "no frontmatter")
            continue
        fields = {}
        current = None
        for line in m.group(1).splitlines():
            km = re.match(r"([A-Za-z_-]+):\s*(.*)$", line)
            if km:
                current = km.group(1)
                fields[current] = km.group(2).strip()
            elif current and line.strip():
                fields[current] += " " + line.strip()
        for key in ("name", "description"):
            value = fields.get(key, "").strip().strip("|>-").strip()
            if not value:
                error(path, f"frontmatter {key} is missing or empty")


MARKETPLACE = os.path.join(".claude-plugin", "marketplace.json")
RELEASE_CONFIG = "release-please-config.json"


def check_plugin_registration(root):
    """Return the problems with how the plugins under root/plugins are registered.

    A plugin is a plugins/<name>/ folder holding .claude-plugin/plugin.json. Each one
    needs a marketplace.json entry named <name> with source ./plugins/<name>, and a
    release-please extra-files entry for its plugin.json with type json and jsonpath
    $.version, or release-please leaves its version behind. Every extra-files path must
    exist, because release-please skips a missing file without saying so.
    """
    problems = []

    def load(rel):
        try:
            with open(os.path.join(root, rel), encoding="utf-8") as f:
                return json.load(f)
        except OSError as e:
            problems.append(f"{rel}: cannot be read ({e.strerror})")
        except ValueError as e:
            problems.append(f"{rel}: not valid JSON ({e})")
        return None

    plugins_dir = os.path.join(root, "plugins")
    names = sorted(
        name for name in (os.listdir(plugins_dir) if os.path.isdir(plugins_dir) else [])
        if os.path.isfile(os.path.join(plugins_dir, name, ".claude-plugin", "plugin.json"))
    )

    market = load(MARKETPLACE)
    if market is not None and not isinstance(market, dict):
        problems.append(f"{MARKETPLACE}: the top level is not an object")
    # A plugins value that is not a list, and an entry with no string source, are
    # reported by check_json.
    if isinstance(market, dict) and isinstance(market.get("plugins", []), list):
        sources = {}
        for entry in market.get("plugins", []):
            if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                continue
            name = entry["name"]
            if name in sources:
                problems.append(f"{MARKETPLACE}: plugin {name} is listed more than once")
            sources[name] = entry.get("source")
        for name in names:
            want = f"./plugins/{name}"
            if name not in sources:
                problems.append(f"{MARKETPLACE}: no entry for plugin {name} (source {want})")
            elif isinstance(sources[name], str) and (
                    os.path.normpath(sources[name]) != os.path.normpath(want)):
                problems.append(
                    f"{MARKETPLACE}: plugin {name} has source {sources[name]!r}, not {want}")

    config = load(RELEASE_CONFIG)
    if config is not None and not isinstance(config, dict):
        problems.append(f"{RELEASE_CONFIG}: the top level is not an object")
    if isinstance(config, dict):
        packages = config.get("packages")
        if not isinstance(packages, dict):
            problems.append(f'{RELEASE_CONFIG}: "packages" is missing or not an object')
            packages = {}
        entries = {}
        for package_dir, package in packages.items():
            if not isinstance(package, dict):
                problems.append(f"{RELEASE_CONFIG}: package {package_dir} is not an object")
                continue
            # release-please reads extra-files paths relative to their package's folder.
            extra_files = package.get("extra-files", [])
            if not isinstance(extra_files, list):
                problems.append(
                    f'{RELEASE_CONFIG}: "extra-files" in package {package_dir} is not a list')
                continue
            for entry in extra_files:
                path = entry if isinstance(entry, str) else (
                    entry.get("path") if isinstance(entry, dict) else None)
                if not isinstance(path, str) or not path:
                    problems.append(f"{RELEASE_CONFIG}: extra-files entry {entry!r} has no path")
                    continue
                path = os.path.normpath(os.path.join(package_dir, path)).replace(os.sep, "/")
                if os.path.isabs(path) or path == ".." or path.startswith("../"):
                    problems.append(
                        f"{RELEASE_CONFIG}: extra-files path {path} is outside the repository")
                    continue
                if path in entries:
                    problems.append(f"{RELEASE_CONFIG}: extra-files lists {path} more than once")
                entries[path] = entry
                if not os.path.exists(os.path.join(root, path)):
                    problems.append(f"{RELEASE_CONFIG}: extra-files path {path} does not exist")
        for name in names:
            path = f"plugins/{name}/.claude-plugin/plugin.json"
            entry = entries.get(path)
            if entry is None:
                problems.append(
                    f"{RELEASE_CONFIG}: plugin {name} has no extra-files entry for {path}")
            elif not isinstance(entry, dict) or entry.get("type") != "json" or (
                    entry.get("jsonpath") != "$.version"):
                problems.append(f"{RELEASE_CONFIG}: the extra-files entry for {path} needs "
                                f'"type": "json" and "jsonpath": "$.version"')

    return problems


LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")


def check_links(files):
    for path in files:
        if not path.endswith(".md"):
            continue
        in_fence = None
        with open(path, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                fm = re.match(r"\s*(```+|~~~+)", line)
                if fm:
                    marker = fm.group(1)[0]
                    if in_fence is None:
                        in_fence = marker
                    elif in_fence == marker:
                        in_fence = None
                    continue
                if in_fence:
                    continue
                line = re.sub(r"`[^`]*`", "", line)
                for m in LINK.finditer(line):
                    target = m.group(1)
                    if re.match(r"([a-zA-Z][a-zA-Z0-9+.-]*:|#)", target):
                        continue
                    target = target.split("#", 1)[0]
                    if not target:
                        continue
                    resolved = os.path.normpath(os.path.join(os.path.dirname(path), target))
                    if not os.path.exists(resolved):
                        error(path, f"line {n}: link {target} does not resolve")


def run(cmd, path):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        error(path, f"{' '.join(cmd[:2])} failed: {(r.stderr or r.stdout).strip()}")


def check_syntax(files):
    for path in files:
        if path.endswith(".py"):
            with open(path, "rb") as f:
                try:
                    compile(f.read(), path, "exec")
                except (SyntaxError, ValueError) as e:
                    error(path, f"py_compile failed: {e}")
        elif path.endswith((".mjs", ".js")):
            run(["node", "--check", path], path)
        elif path.endswith(".sh"):
            run(["bash", "-n", path], path)


def shellcheck(files):
    exe = shutil.which("shellcheck")
    scripts = [p for p in files if p.endswith(".sh")]
    if not exe:
        print("shellcheck not installed; skipped (advisory)")
        return
    r = subprocess.run([exe, "-x", *scripts], capture_output=True, text=True)
    out = (r.stdout + r.stderr).strip()
    print("shellcheck (advisory, never fails the run):")
    print(out if out else "  no findings")


def main():
    files = list(walk())
    check_json(files)
    # check_json has already reported a marketplace.json that does not parse.
    errors.extend(p for p in check_plugin_registration(ROOT) if p not in errors)
    check_skills(files)
    check_links(files)
    check_syntax(files)
    shellcheck(files)
    for e in errors:
        print(f"ERROR  {e}")
    print(f"{len(errors)} problem(s) found")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
