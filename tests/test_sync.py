import json
import importlib.util
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLATFORM = {"darwin": "macos", "win32": "windows"}.get(sys.platform, "linux")
linux_only = pytest.mark.skipif(PLATFORM != "linux", reason="systemd units are Linux-only")


@pytest.fixture
def fake_home(tmp_path):
    home = tmp_path / "home"
    repo = home / ".agents"
    repo.mkdir(parents=True)
    shutil.copy2(ROOT / "sync.py", repo / "sync.py")
    for name in ("claude", "codex", "pi", "shell", "linux", "macos"):
        shutil.copytree(ROOT / name, repo / name, symlinks=True)
    for name in ("skills", "hooks", "claude-patching"):
        (repo / name).mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    systemctl = bin_dir / "systemctl"
    systemctl.write_text("#!/bin/sh\nexit 0\n")
    systemctl.chmod(0o755)
    environment = os.environ | {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
    }
    return home, repo, environment


def run_sync(repo: Path, environment: dict[str, str], check: bool = True):
    result = subprocess.run(
        ["uv", "run", str(repo / "sync.py")],
        env=environment,
        capture_output=True,
        text=True,
    )
    if check:
        assert result.returncode == 0, result.stderr
    return result


def load_toml(path: Path):
    return tomllib.loads(path.read_text())


def read_link(path: Path) -> str:
    return os.readlink(path).removeprefix("\\\\?\\")


def test_installs_profile_links(fake_home):
    home, repo, environment = fake_home

    result = run_sync(repo, environment)

    assert read_link(home / ".claude" / "settings.json") == str(repo / "claude" / "settings.json")
    work_skills = home / ".claude-work" / "skills"
    assert read_link(work_skills) == "../.claude/skills"
    assert work_skills.resolve() == (repo / "skills").resolve()
    assert "linked" in result.stdout
    assert run_sync(repo, environment).stdout == ""


@linux_only
def test_installs_systemd_units(fake_home):
    home, repo, environment = fake_home

    run_sync(repo, environment)

    assert read_link(home / ".config" / "systemd" / "user" / "agent-config-pull.timer") == str(
        repo / "linux" / "agent-config-pull.timer"
    )


def test_process_wrapper_lives_in_local_settings(fake_home):
    home, repo, environment = fake_home
    local = home / ".claude" / "settings.local.json"
    local.parent.mkdir()
    local.write_text('{"permissions": {"allow": ["WebSearch"]}}\n')

    run_sync(repo, environment)

    assert "processWrapper" not in json.loads((repo / "claude" / "settings.json").read_text())
    settings = json.loads(local.read_text())
    assert settings["permissions"] == {"allow": ["WebSearch"]}
    if PLATFORM == "windows":
        assert "processWrapper" not in settings
    else:
        assert settings["processWrapper"] == str(repo / "claude-patching" / "process-wrapper.sh")


def test_codex_round_trip_keeps_local_state_and_routes_drift(fake_home):
    home, repo, environment = fake_home
    codex = home / ".codex"
    codex.mkdir()
    live = codex / "config.toml"
    rendered = codex / "config.toml.rendered"
    live.write_text(
        'model_reasoning_effort = "high"\n'
        '\n[projects."/x"]\ntrust_level = "trusted"\n'
        '\n[hooks.state]\n"/x:pre_tool_use:0:0" = "trusted"\n'
        '\n[marketplaces.test]\nlast_updated = "2026-01-01T00:00:00Z"\n'
    )

    run_sync(repo, environment)

    local = load_toml(live)
    assert local["model_reasoning_effort"] == "high"
    assert local["projects"]["/x"]["trust_level"] == "trusted"
    assert local["hooks"]["state"]["/x:pre_tool_use:0:0"] == "trusted"
    assert local["marketplaces"]["test"]["last_updated"] == "2026-01-01T00:00:00Z"
    shared = load_toml(rendered)
    assert "model_reasoning_effort" not in shared
    assert "projects" not in shared
    assert "state" not in shared["hooks"]
    assert "test" not in shared.get("marketplaces", {})
    assert rendered.read_text().endswith("\n")
    assert '"/x"' not in (repo / "codex" / "config.toml").read_text()

    live.write_text('test_shared = "live"\n' + live.read_text())
    run_sync(repo, environment)
    overlay_path = repo / "codex" / f"config.{PLATFORM}.toml"
    assert load_toml(overlay_path)["test_shared"] == "live"
    assert "test_shared" not in load_toml(repo / "codex" / "config.toml")

    live.write_text(live.read_text().replace('"." = "read"', '"." = "write"'))
    run_sync(repo, environment)
    roots = lambda document: document["permissions"]["workspace_sandbox"]["filesystem"][":workspace_roots"]
    assert roots(load_toml(overlay_path))["."] == "write"
    assert roots(load_toml(repo / "codex" / "config.toml"))["."] == "read"
    assert roots(load_toml(live))["."] == "write"
    assert load_toml(live)["projects"]["/x"]["trust_level"] == "trusted"


def test_codex_first_sync_keeps_existing_config(fake_home):
    home, repo, environment = fake_home
    codex = home / ".codex"
    codex.mkdir()
    live = codex / "config.toml"
    live.write_text('model = "existing-model"\n\n[projects."/x"]\ntrust_level = "trusted"\n')

    run_sync(repo, environment)

    assert load_toml(repo / "codex" / f"config.{PLATFORM}.toml")["model"] == "existing-model"
    assert load_toml(live)["model"] == "existing-model"
    assert load_toml(live)["projects"]["/x"]["trust_level"] == "trusted"


def test_codex_removed_key_leaves_overlay(fake_home):
    home, repo, environment = fake_home
    codex = home / ".codex"
    codex.mkdir()
    live = codex / "config.toml"
    overlay_path = repo / "codex" / f"config.{PLATFORM}.toml"
    overlay_path.write_text(overlay_path.read_text() + '\n[plugins."browser@test"]\nenabled = true\n')
    run_sync(repo, environment)
    assert load_toml(live)["plugins"]["browser@test"]["enabled"] is True

    text = live.read_text()
    live.write_text(text.replace('[plugins."browser@test"]\nenabled = true\n', ""))
    result = run_sync(repo, environment)

    assert "removed Codex key" in result.stdout
    assert "browser@test" not in load_toml(overlay_path).get("plugins", {})
    assert "browser@test" not in load_toml(live).get("plugins", {})


def test_codex_keeps_literal_strings(fake_home):
    home, repo, environment = fake_home
    codex = home / ".codex"
    codex.mkdir()
    live = codex / "config.toml"
    live.write_text("[projects.'C:\\Users\\x']\ntrust_level = \"trusted\"\n")
    run_sync(repo, environment)
    assert "'C:\\Users\\x'" in live.read_text()

    live.write_text("test_path = 'C:\\tools\\test.exe'\n" + live.read_text())
    run_sync(repo, environment)
    assert "'C:\\tools\\test.exe'" in (repo / "codex" / f"config.{PLATFORM}.toml").read_text()
    assert "'C:\\tools\\test.exe'" in live.read_text()

    before = live.read_text()
    run_sync(repo, environment)
    assert live.read_text() == before


def test_regular_config_file_prints_diff_and_stops(fake_home):
    home, repo, environment = fake_home
    run_sync(repo, environment)
    settings = home / ".claude" / "settings.json"
    settings.unlink()
    settings.write_text('{"changed": true}\n')

    result = run_sync(repo, environment, check=False)

    assert result.returncode == 1
    assert f"--- {settings}" in result.stdout
    assert f"+++ {repo / 'claude' / 'settings.json'}" in result.stdout
    assert "move these changes into" in result.stderr


@pytest.fixture
def sync_module():
    spec = importlib.util.spec_from_file_location("agent_sync", ROOT / "sync.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def repositories(tmp_path, sync_module):
    git = sync_module.git
    origin = tmp_path / "origin.git"
    first = tmp_path / "first"
    second = tmp_path / "second"
    git(tmp_path, "init", "--bare", "--initial-branch=main", str(origin))
    git(tmp_path, "clone", str(origin), str(first))
    git(first, "config", "user.name", "Sync test")
    git(first, "config", "user.email", "sync@example.test")
    (first / "config.txt").write_text("initial\n")
    git(first, "add", ".")
    git(first, "commit", "-m", "Initial configuration")
    git(first, "push", "-u", "origin", "main")
    git(first, "remote", "set-head", "origin", "-a")
    git(tmp_path, "clone", str(origin), str(second))
    git(second, "config", "user.name", "Sync test")
    git(second, "config", "user.email", "sync@example.test")
    return first, second


def test_auto_sync_commits_new_files_and_merges_both_machines(repositories, sync_module):
    first, second = repositories
    (first / ".gitignore").write_text("secret.txt\n")
    (first / "secret.txt").write_text("private\n")
    (first / "linux.txt").write_text("linux\n")
    (second / "mac.txt").write_text("mac\n")
    sync_module.sync_repository(first)
    sync_module.sync_repository(second)
    sync_module.sync_repository(first)
    assert (first / "mac.txt").read_text() == "mac\n"
    assert (second / "linux.txt").read_text() == "linux\n"
    assert not (second / "secret.txt").exists()
    assert sync_module.git(first, "rev-parse", "HEAD") == sync_module.git(second, "rev-parse", "HEAD")
    before = sync_module.git(first, "rev-parse", "HEAD")
    sync_module.sync_repository(first)
    assert sync_module.git(first, "rev-parse", "HEAD") == before


def test_auto_sync_stops_on_conflict_and_preserves_work(repositories, sync_module):
    first, second = repositories
    (first / "config.txt").write_text("linux\n")
    (second / "config.txt").write_text("mac\n")
    sync_module.sync_repository(first)
    with pytest.raises(sync_module.SyncError, match="CONFLICT"):
        sync_module.sync_repository(second)
    with pytest.raises(sync_module.SyncError, match="finish or abort"):
        sync_module.sync_repository(second)
    assert sync_module.git(second, "show", "HEAD:config.txt") == "mac"
    assert sync_module.git(first, "show", "HEAD:config.txt") == "linux"


def test_auto_sync_leaves_feature_branches_untouched(repositories, sync_module):
    first, _ = repositories
    sync_module.git(first, "switch", "-c", "feature", "--track", "origin/main")
    (first / "config.txt").write_text("unfinished\n")
    with pytest.raises(sync_module.SyncError, match="default branch"):
        sync_module.sync_repository(first)
    assert sync_module.git(first, "diff", "--name-only") == "config.txt"


def test_sync_initializes_submodules_and_publishes_edits(repositories, sync_module, tmp_path, monkeypatch):
    first, second = repositories
    parent = tmp_path / "parent"
    parent.mkdir()
    git = sync_module.git
    git(parent, "init", "--initial-branch=main")
    (parent / ".gitmodules").write_text(f'[submodule "child"]\npath = child\nurl = {tmp_path / "origin.git"}\n')
    git(parent, "add", ".gitmodules")
    git(parent, "update-index", "--add", "--cacheinfo", "160000", git(first, "rev-parse", "HEAD"), "child")
    monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "file")
    monkeypatch.setattr(sync_module, "REPO", parent)
    sync_module.sync_submodules()
    child = parent / "child"
    git(child, "config", "user.name", "Sync test")
    git(child, "config", "user.email", "sync@example.test")
    (child / "new.txt").write_text("shared\n")
    sync_module.sync_submodules()
    sync_module.sync_repository(second)
    assert (second / "new.txt").read_text() == "shared\n"
