#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["tomlkit>=0.13"]
# ///
"""Install this repository's agent configuration and synchronize it on request."""

from __future__ import annotations

import copy
import difflib
import json
import os
import subprocess
import sys
from collections.abc import Mapping, MutableMapping
from pathlib import Path

import tomlkit

REPO = Path(__file__).resolve().parent
HOME = Path.home().resolve()
WORK_PROFILE_ENTRIES = (
    "agents",
    "backups",
    "cache",
    "debug",
    "downloads",
    "file-history",
    "history.jsonl",
    "ide",
    "output-styles",
    "paste-cache",
    "plans",
    "plugins",
    "projects",
    "scripts",
    "session-env",
    "settings.local.json",
    "shell-snapshots",
    "skills",
    "statsig",
    "tasks",
    "telemetry",
    "todos",
)


class SyncError(Exception):
    pass


def platform_name() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "win32":
        return "windows"
    raise SyncError(f"unsupported platform: {sys.platform}")


def ensure_directory(path: Path) -> None:
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise SyncError(f"{path} must be a real directory")
    if not path.exists():
        path.mkdir(parents=True)
        print(f"created {path}")


def read_link(target: Path) -> str:
    """Link text as written; Windows reports absolute targets with a \\\\?\\ prefix."""
    return os.readlink(target).removeprefix("\\\\?\\")


def same_link(target: Path, link_text: str) -> bool:
    return target.is_symlink() and read_link(target) == link_text


def print_diff(target: Path, source: Path) -> None:
    old = target.read_text(errors="replace").splitlines(keepends=True)
    new = source.read_text(errors="replace").splitlines(keepends=True)
    print(
        "".join(difflib.unified_diff(old, new, fromfile=str(target), tofile=str(source))),
        end="",
        flush=True,
    )


def link(target: Path, link_text: str, is_directory: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if same_link(target, link_text):
        return
    if target.is_symlink():
        target.unlink()
    elif target.exists():
        if target.is_dir():
            raise SyncError(f"{target} is a directory; move it aside, then re-run")
        source = Path(link_text)
        if not source.is_absolute():
            source = target.parent / source
        print_diff(target, source)
        raise SyncError(f"move these changes into {source}, then re-run")

    try:
        os.symlink(link_text, target, target_is_directory=is_directory)
    except OSError as error:
        if sys.platform == "win32":
            raise SyncError(
                f"could not create {target}; enable Developer Mode, then re-run"
            ) from error
        raise
    print(f"linked {target} -> {link_text}")


def install_links(platform: str) -> None:
    claude = HOME / ".claude"
    work = HOME / ".claude-work"
    codex = HOME / ".codex"
    pi = HOME / ".pi" / "agent"
    git = HOME / ".config" / "git"

    for profile in (claude, work):
        for name in ("CLAUDE.md", "settings.json", "statusline.py", "tab-title.py"):
            source = REPO / "claude" / name
            link(profile / name, str(source), source.is_dir())

    static = {
        claude / "skills": REPO / "skills",
        claude / "output-styles": REPO / "claude" / "output-styles",
        codex / "AGENTS.md": REPO / "AGENTS.md",
        pi / "AGENTS.md": REPO / "AGENTS.md",
        pi / "settings.json": REPO / "pi" / "settings.json",
        pi / "extensions" / "prevent-rm.ts": REPO / "hooks" / "prevent-rm-pi.ts",
        pi / "extensions" / "timestamp.ts": REPO / "hooks" / "timestamp-pi.ts",
        git / "ignore": REPO / "shell" / "gitignore-global",
    }
    if platform == "linux":
        units = HOME / ".config" / "systemd" / "user"
        static |= {
            units / "agent-config-pull.service": REPO / "linux" / "agent-config-pull.service",
            units / "agent-config-pull.timer": REPO / "linux" / "agent-config-pull.timer",
            units / "t3-trace-archive.service": REPO / "linux" / "t3-trace-archive.service",
            units / "t3-trace-archive.timer": REPO / "linux" / "t3-trace-archive.timer",
            units / "claude-remote-control.service": REPO / "linux" / "claude-remote-control.service",
            units / "claude-patching-autoport.path": REPO / "claude-patching" / "claude-patching-autoport.path",
            units / "claude-patching-autoport.service": REPO / "claude-patching" / "claude-patching-autoport.service",
        }
    elif platform == "macos":
        static |= {
            HOME / ".zshrc": REPO / "shell" / "zshrc",
            HOME / ".zprofile": REPO / "shell" / "zprofile",
            HOME / "Library" / "Application Support" / "iTerm2" / "DynamicProfiles" / "herdr.json": REPO / "macos" / "Library" / "Application Support" / "iTerm2" / "DynamicProfiles" / "herdr.json",
        }

    for target, source in static.items():
        link(target, str(source), source.is_dir())

    for source in sorted((REPO / "codex" / "skills").iterdir()):
        link(codex / "skills" / source.name, str(source), True)

    for name in WORK_PROFILE_ENTRIES:
        link(
            work / name,
            f"../.claude/{name}",
            name not in {"history.jsonl", "settings.local.json"},
        )


def deep_merge(base: MutableMapping, overlay: Mapping) -> None:
    for key, value in overlay.items():
        if key in base and isinstance(base[key], MutableMapping) and isinstance(value, Mapping):
            deep_merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)


def split_local(document: Mapping) -> tuple[Mapping, dict]:
    """Separate shared Codex config from machine-local state."""
    shared = copy.deepcopy(document)
    local = {}
    for key in ("projects", "model_reasoning_effort"):
        if key in shared:
            local[key] = shared.pop(key)

    if "state" in shared.get("hooks", {}):
        local["hooks"] = {"state": shared["hooks"].pop("state")}
        if not shared["hooks"]:
            shared.pop("hooks")

    marketplaces = shared.get("marketplaces", {})
    for name in list(marketplaces):
        marketplace = marketplaces[name]
        if "last_updated" in marketplace:
            local.setdefault("marketplaces", {}).setdefault(name, {})["last_updated"] = marketplace.pop("last_updated")
        if not marketplace:
            marketplaces.pop(name)
    if "marketplaces" in shared and not marketplaces:
        shared.pop("marketplaces")
    return shared, local


def plain(value):
    """The Python value behind a tomlkit item; tomlkit already returns bools bare."""
    return value.unwrap() if isinstance(value, tomlkit.items.Item) else value


def changed_values(live: Mapping, previous: Mapping, path: tuple[str, ...] = ()):
    """Keys the live config adds or changes, as tomlkit items so string styles survive."""
    for key, value in live.items():
        current_path = (*path, key)
        if key not in previous:
            yield current_path, value
        elif isinstance(value, Mapping) and isinstance(previous[key], Mapping):
            yield from changed_values(value, previous[key], current_path)
        elif plain(value) != plain(previous[key]):
            yield current_path, value


def removed_paths(live: Mapping, previous: Mapping, path: tuple[str, ...] = ()):
    for key, value in previous.items():
        current_path = (*path, key)
        if key not in live:
            yield current_path
        elif isinstance(value, Mapping) and isinstance(live[key], Mapping):
            yield from removed_paths(live[key], value, current_path)


def set_path(document: MutableMapping, path: tuple[str, ...], value) -> None:
    table = document
    for key in path[:-1]:
        if key not in table or not isinstance(table[key], MutableMapping):
            table[key] = tomlkit.table()
        table = table[key]
    table[path[-1]] = copy.deepcopy(value)


def delete_path(document: MutableMapping, path: tuple[str, ...]) -> bool:
    table = document
    for key in path[:-1]:
        table = table.get(key)
        if not isinstance(table, MutableMapping):
            return False
    return table.pop(path[-1], None) is not None


def merged(base: Mapping, overlay: Mapping) -> tomlkit.TOMLDocument:
    document = copy.deepcopy(base)
    deep_merge(document, overlay)
    return document


def write_if_changed(path: Path, content: str, action: str) -> None:
    if path.exists() and path.read_text() == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    print(f"{action} {path}")


def render_codex(platform: str) -> None:
    """Render the live Codex config and import the app's edits into the OS overlay.

    Drift is the difference between the live config's shared part and the last
    render, or, before any render exists, the fresh render itself, so a machine
    with an existing Codex config keeps its settings. Keys Codex removed leave the
    overlay; a removed key that only the shared base holds returns on render,
    because the base changes only by hand.
    """
    base_path = REPO / "codex" / "config.toml"
    overlay_path = REPO / "codex" / f"config.{platform}.toml"
    live_path = HOME / ".codex" / "config.toml"
    rendered_path = HOME / ".codex" / "config.toml.rendered"

    base = tomlkit.parse(base_path.read_text())
    overlay = tomlkit.parse(overlay_path.read_text())
    rendered = merged(base, overlay)
    local = {}
    if live_path.exists():
        shared, local = split_local(tomlkit.parse(live_path.read_text()))
        changed = False
        if rendered_path.exists():
            previous = tomlkit.parse(rendered_path.read_text())
            for path in removed_paths(shared, previous):
                key = ".".join(path)
                if delete_path(overlay, path):
                    changed = True
                    print(f"removed Codex key from {overlay_path.name}: {key}")
                else:
                    print(f"Codex removed {key}, which only {base_path.name} holds; delete it there by hand")
        else:
            previous = rendered
        for path, value in changed_values(shared, previous):
            set_path(overlay, path, value)
            changed = True
            print(f"imported Codex drift into {overlay_path.name}: {'.'.join(path)} = {plain(value)!r}")
        if changed:
            overlay_path.write_text(tomlkit.dumps(overlay))
            rendered = merged(base, overlay)

    live = copy.deepcopy(rendered)
    deep_merge(live, local)
    write_if_changed(live_path, tomlkit.dumps(live), "rendered")
    write_if_changed(rendered_path, tomlkit.dumps(rendered), "recorded")


def install_process_wrapper(platform: str) -> None:
    """Point background Claude sessions at claude-patching's wrapper where it can run.

    The wrapper is a bash script, so it stays out of the shared settings.json and
    lands in settings.local.json, which Claude Code layers on top and Windows skips.
    """
    if platform == "windows":
        return
    wrapper = str(REPO / "claude-patching" / "process-wrapper.sh")
    path = HOME / ".claude" / "settings.local.json"
    settings = json.loads(path.read_text()) if path.exists() else {}
    if settings.get("processWrapper") == wrapper:
        return
    settings["processWrapper"] = wrapper
    path.write_text(json.dumps(settings, indent=2) + "\n")
    print(f"set processWrapper in {path}")


def git(*args: str) -> str:
    result = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise SyncError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def pull() -> None:
    """Fast-forward from origin, then push unpushed commits."""
    git("pull", "--quiet", "--ff-only", "--autostash")
    if git("rev-list", "--count", "@{upstream}..HEAD") != "0":
        git("push", "--quiet")
        print("pushed local commits")


def install_pull_schedule(platform: str) -> None:
    if platform == "linux":
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(
            ["systemctl", "--user", "enable", "--quiet", "--now", "agent-config-pull.timer"],
            check=True,
        )
    elif platform == "macos":
        name = "com.akelly.agent-config-pull.plist"
        plist = HOME / "Library" / "LaunchAgents" / name
        source = REPO / "macos" / "Library" / "LaunchAgents" / name
        if plist.exists() and plist.read_text() == source.read_text():
            return
        # launchd refuses symlinked plists, so install a copy and (re)load it.
        subprocess.run(
            ["launchctl", "bootout", f"gui/{os.getuid()}/com.akelly.agent-config-pull"],
            capture_output=True,
        )
        plist.write_text(source.read_text())
        subprocess.run(
            ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)], check=True
        )
        print(f"installed launchd agent {plist}")


def main() -> None:
    if REPO != HOME / ".agents":
        raise SyncError(
            f"sync only runs from {HOME / '.agents'}, not a worktree or other clone ({REPO})"
        )
    args = sys.argv[1:]
    if args == ["pull"]:
        pull()
    elif args:
        raise SyncError("usage: sync.py [pull]")

    platform = platform_name()
    for directory in (
        HOME / ".claude",
        HOME / ".claude-work",
        HOME / ".codex",
        HOME / ".pi" / "agent",
        HOME / ".config" / "git",
    ):
        ensure_directory(directory)
    install_links(platform)
    install_process_wrapper(platform)
    render_codex(platform)
    install_pull_schedule(platform)


if __name__ == "__main__":
    try:
        main()
    except SyncError as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
