import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def fake_home(tmp_path):
    home = tmp_path / "home"
    repo = home / ".agents"
    shutil.copytree(
        ROOT,
        repo,
        symlinks=True,
        ignore=shutil.ignore_patterns(".*", "__pycache__"),
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    systemctl = bin_dir / "systemctl"
    systemctl.write_text("#!/bin/sh\nexit 0\n")
    systemctl.chmod(0o755)
    environment = os.environ | {
        "HOME": str(home),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
    }
    return home, repo, environment


def run_sync(repo: Path, environment: dict[str, str], check: bool = True):
    return subprocess.run(
        ["uv", "run", str(repo / "sync.py")],
        env=environment,
        capture_output=True,
        text=True,
        check=check,
    )


def load_toml(path: Path):
    return tomllib.loads(path.read_text())


def test_installs_profile_links(fake_home):
    home, repo, environment = fake_home

    run_sync(repo, environment)

    assert os.readlink(home / ".claude" / "settings.json") == str(
        repo / "claude" / "settings.json"
    )
    work_skills = home / ".claude-work" / "skills"
    assert os.readlink(work_skills) == "../.claude/skills"
    assert work_skills.resolve() == (repo / "skills").resolve()
    assert os.readlink(
        home / ".config" / "systemd" / "user" / "agent-config-pull.timer"
    ) == str(repo / "linux" / "agent-config-pull.timer")


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
    assert load_toml(repo / "codex" / "config.toml")["test_shared"] == "live"

    live.write_text(live.read_text().replace('":tmpdir" = "write"', '":tmpdir" = "read"'))
    run_sync(repo, environment)
    overlay = load_toml(repo / "codex" / "config.linux.toml")
    assert overlay["permissions"]["workspace_sandbox"]["filesystem"][":tmpdir"] == "read"
    base = load_toml(repo / "codex" / "config.toml")
    assert ":tmpdir" not in base["permissions"]["workspace_sandbox"]["filesystem"]
    assert load_toml(live)["projects"]["/x"]["trust_level"] == "trusted"


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
