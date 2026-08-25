#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["tomlkit>=0.13"]
# ///
"""Install the repository's agent configuration into real home directories."""

from __future__ import annotations

import copy
import difflib
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


def has_tail(path: Path, *tails: tuple[str, ...]) -> bool:
    return any(tuple(path.parts[-len(tail) :]) == tail for tail in tails)


def migrate_old_directory(live: Path, *tails: tuple[str, ...]) -> bool:
    if not live.is_symlink():
        return False
    source = live.resolve(strict=False)
    if not has_tail(source, *tails):
        raise SyncError(f"{live} is an unexpected symlink to {source}")

    live.unlink()
    if source.is_dir():
        source.rename(live)
        print(f"migrated {live} from {source}")
    else:
        live.mkdir(parents=True)
        print(f"replaced dangling legacy symlink {live}")
    return True


def ensure_directory(path: Path) -> None:
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise SyncError(f"{path} must be a real directory")
    if not path.exists():
        path.mkdir(parents=True)
        print(f"created {path}")


def same_link(target: Path, source: Path, relative_source: str | None) -> bool:
    expected = relative_source or str(source)
    return target.is_symlink() and os.readlink(target) == expected


def print_diff(target: Path, source: Path) -> None:
    if not target.is_file() or not source.is_file():
        return
    old = target.read_text(errors="replace").splitlines(keepends=True)
    new = source.read_text(errors="replace").splitlines(keepends=True)
    print(
        "".join(difflib.unified_diff(old, new, fromfile=str(target), tofile=str(source))),
        end="",
        flush=True,
    )


def link(
    target: Path,
    source: Path,
    *,
    relative_source: str | None = None,
    legacy_root: Path | None = None,
    directory: bool | None = None,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if same_link(target, source, relative_source):
        return
    if target.is_symlink():
        target.unlink()
    elif target.exists():
        if legacy_root is None or not target.is_relative_to(legacy_root):
            print_diff(target, source)
            raise SyncError(f"move these changes into {source}, then re-run")
        if target.is_dir():
            raise SyncError(f"move the legacy directory {target} aside, then re-run")
        target.unlink()
        print(f"removed legacy config {target}")

    try:
        os.symlink(
            relative_source or source,
            target,
            target_is_directory=source.is_dir() if directory is None else directory,
        )
    except OSError as error:
        if sys.platform == "win32":
            raise SyncError(
                f"could not create {target}; enable Developer Mode, then re-run"
            ) from error
        raise
    print(f"linked {target} -> {relative_source or source}")


def cleanup_macos_codex_home() -> None:
    environment = subprocess.run(
        ["launchctl", "getenv", "CODEX_HOME"], capture_output=True, text=True
    )
    subprocess.run(
        ["launchctl", "unsetenv", "CODEX_HOME"],
        capture_output=True,
        text=True,
        check=True,
    )
    if environment.returncode == 0 and environment.stdout.strip():
        print("unset launchctl CODEX_HOME")

    service = f"gui/{os.getuid()}/com.akelly.codex-home"
    unloaded = subprocess.run(
        ["launchctl", "bootout", service], capture_output=True, text=True
    )
    if unloaded.returncode == 0:
        print("unloaded com.akelly.codex-home")

    plist = HOME / "Library" / "LaunchAgents" / "com.akelly.codex-home.plist"
    if plist.exists() or plist.is_symlink():
        subprocess.run(["trash", str(plist)], capture_output=True, text=True, check=True)
        print(f"trashed {plist}")


def install_links(platform: str, migrated: set[Path]) -> None:
    claude = HOME / ".claude"
    work = HOME / ".claude-work"
    codex = HOME / ".codex"
    pi = HOME / ".pi" / "agent"
    git = HOME / ".config" / "git"

    static = {
        claude / "CLAUDE.md": REPO / "claude" / "CLAUDE.md",
        claude / "settings.json": REPO / "claude" / "settings.json",
        claude / "statusline.py": REPO / "claude" / "statusline.py",
        claude / "tab-title.py": REPO / "claude" / "tab-title.py",
        claude / "skills": REPO / "skills",
        claude / "output-styles": REPO / "claude" / "output-styles",
        work / "CLAUDE.md": REPO / "claude" / "CLAUDE.md",
        work / "settings.json": REPO / "claude" / "settings.json",
        work / "statusline.py": REPO / "claude" / "statusline.py",
        work / "tab-title.py": REPO / "claude" / "tab-title.py",
        codex / "AGENTS.md": REPO / "AGENTS.md",
        pi / "AGENTS.md": REPO / "AGENTS.md",
        pi / "settings.json": REPO / "pi" / "settings.json",
        pi / "extensions" / "prevent-rm.ts": REPO / "hooks" / "prevent-rm-pi.ts",
        git / "ignore": REPO / "shell" / "gitignore-global",
    }
    if platform == "linux":
        units = HOME / ".config" / "systemd" / "user"
        static |= {
            units / "claude-remote-control.service": REPO
            / "linux"
            / "claude-remote-control.service",
            units / "claude-patching-autoport.path": REPO
            / "claude-patching"
            / "claude-patching-autoport.path",
            units / "claude-patching-autoport.service": REPO
            / "claude-patching"
            / "claude-patching-autoport.service",
        }
    elif platform == "macos":
        static |= {
            HOME / ".zshrc": REPO / "shell" / "zshrc",
            HOME / ".zprofile": REPO / "shell" / "zprofile",
            HOME
            / "Library"
            / "Application Support"
            / "iTerm2"
            / "DynamicProfiles"
            / "herdr.json": REPO
            / "macos"
            / "Library"
            / "Application Support"
            / "iTerm2"
            / "DynamicProfiles"
            / "herdr.json",
        }

    for target, source in static.items():
        legacy_root = next((root for root in migrated if target.is_relative_to(root)), None)
        link(target, source, legacy_root=legacy_root)

    for name in WORK_PROFILE_ENTRIES:
        source = claude / name
        link(
            work / name,
            source,
            relative_source=f"../.claude/{name}",
            legacy_root=work if work in migrated else None,
            directory=name not in {"history.jsonl", "settings.local.json"},
        )


def deep_merge(base: MutableMapping, overlay: Mapping) -> None:
    for key, value in overlay.items():
        if key in base and isinstance(base[key], MutableMapping) and isinstance(value, Mapping):
            deep_merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)


def sanitized(document):
    clean = copy.deepcopy(document)
    clean.pop("projects", None)
    clean.pop("model_reasoning_effort", None)
    for marketplace in clean.get("marketplaces", {}).values():
        if isinstance(marketplace, MutableMapping):
            marketplace.pop("last_updated", None)
    return clean


def plain(value):
    return value.unwrap() if hasattr(value, "unwrap") else value


def changed_values(live: Mapping, previous: Mapping, path: tuple[str, ...] = ()):
    for key, value in live.items():
        current_path = (*path, key)
        if key not in previous:
            yield current_path, value
        elif isinstance(value, Mapping) and isinstance(previous[key], Mapping):
            yield from changed_values(value, previous[key], current_path)
        elif plain(value) != plain(previous[key]):
            yield current_path, value


def set_path(document: MutableMapping, path: tuple[str, ...], value) -> None:
    table = document
    for key in path[:-1]:
        if key not in table or not isinstance(table[key], MutableMapping):
            table[key] = tomlkit.table()
        table = table[key]
    table[path[-1]] = copy.deepcopy(value)


def remove_path(document: MutableMapping, path: tuple[str, ...]) -> None:
    tables = [document]
    table = document
    for key in path[:-1]:
        if key not in table or not isinstance(table[key], MutableMapping):
            return
        table = table[key]
        tables.append(table)
    table.pop(path[-1], None)
    for index in range(len(path) - 1, 0, -1):
        if tables[index]:
            break
        tables[index - 1].pop(path[index - 1], None)


def write_if_changed(path: Path, content: str, action: str) -> None:
    if path.exists() and path.read_text() == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    print(f"{action} {path}")


def render_codex(platform: str) -> None:
    base_path = REPO / "codex" / "config.toml"
    overlay_path = REPO / "codex" / f"config.{platform}.toml"
    live_path = HOME / ".codex" / "config.toml"
    rendered_path = HOME / ".codex" / "config.toml.rendered"

    base = tomlkit.parse(base_path.read_text())
    overlay = tomlkit.parse(overlay_path.read_text())
    if live_path.exists() and rendered_path.exists():
        live = sanitized(tomlkit.parse(live_path.read_text()))
        previous = sanitized(tomlkit.parse(rendered_path.read_text()))
        drift = list(changed_values(live, previous))
        for path, value in drift:
            set_path(base, path, value)
            remove_path(overlay, path)
            print(f"imported Codex drift: {'.'.join(path)} = {plain(value)!r}")
        if drift:
            base_path.write_text(tomlkit.dumps(base))
            overlay_path.write_text(tomlkit.dumps(overlay))

    rendered = copy.deepcopy(base)
    deep_merge(rendered, overlay)
    content = tomlkit.dumps(rendered)
    if not content.endswith("\n"):
        content += "\n"
    write_if_changed(live_path, content, "rendered")
    write_if_changed(rendered_path, content, "recorded")


GIT_HOOK = """#!/bin/sh
# Installed by sync.py: keep the live agent config in step with the repo.
exec uv run --quiet sync.py
"""


def install_git_hooks() -> None:
    hooks = Path(
        subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "--git-path", "hooks"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )
    if not hooks.is_absolute():
        hooks = REPO / hooks
    for name in ("post-merge", "post-checkout", "post-commit", "post-rewrite"):
        hook = hooks / name
        if hook.exists() and hook.read_text() == GIT_HOOK:
            continue
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(GIT_HOOK)
        hook.chmod(0o755)
        print(f"installed git hook {hook}")


def main() -> None:
    if REPO != HOME / ".agents":
        raise SyncError(f"sync only runs from {HOME / '.agents'}, not a worktree or other clone ({REPO})")
    platform = platform_name()
    install_git_hooks()
    migrated = set()
    migrations = (
        (HOME / ".claude", (("home", ".claude"), ("home-linux", ".claude"), ("home-windows", ".claude"))),
        (HOME / ".claude-work", (("home", ".claude-work"),)),
        (HOME / ".codex", (("home", ".codex"), ("home-linux", ".codex"), ("home-windows", ".codex"))),
        (HOME / ".pi", (("home", ".pi"),)),
        (HOME / ".pi" / "agent", (("home", ".pi", "agent"),)),
        (HOME / ".config" / "git", (("home", ".config", "git"),)),
    )
    for live, tails in migrations:
        if migrate_old_directory(live, *tails):
            migrated.add(live)

    for directory in (
        HOME / ".claude",
        HOME / ".claude-work",
        HOME / ".codex",
        HOME / ".pi" / "agent",
        HOME / ".config" / "git",
    ):
        ensure_directory(directory)

    if platform == "macos":
        cleanup_macos_codex_home()
    install_links(platform, migrated)
    render_codex(platform)


if __name__ == "__main__":
    try:
        main()
    except SyncError as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
