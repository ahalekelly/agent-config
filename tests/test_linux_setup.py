# /// script
# requires-python = ">=3.11"
# dependencies = ["pytest"]
# ///
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux system setup")


@pytest.mark.parametrize("home_name", ["new-user", "user & space"])
@pytest.mark.parametrize("missing_command", [None, "bwrap", "socat", "trash-empty"])
def test_setup_renders_home_and_installs_sandbox_dependencies(tmp_path, home_name, missing_command):
    home = tmp_path / home_name
    repo = home / ".agents"
    repo.mkdir(parents=True)
    (repo / ".git").mkdir()
    shutil.copytree(ROOT / "linux", repo / "linux")
    (home / ".bashrc").touch()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("grep", "mkdir"):
        (bin_dir / name).symlink_to(shutil.which(name))
    commands = {
        "trash": "exit 0",
        "socat": "exit 0",
        "bwrap": "exit 0",
        "trash-empty": "exit 0",
        "sysctl": "printf '1\\n'",
        "systemctl": "exit 0",
        "sudo": 'printf "%s\\n" "$*" >> "$SETUP_COMMANDS"\nif [ "$1" = tee ]; then /usr/bin/tee "$SETUP_PROFILE"; fi',
    }
    if missing_command:
        del commands[missing_command]
    for name, body in commands.items():
        executable = bin_dir / name
        executable.write_text(f"#!/bin/bash\n{body}\n")
        executable.chmod(0o755)
    profile = tmp_path / "profile"
    log = tmp_path / "commands"
    environment = os.environ | {
        "HOME": str(home),
        "USER": "setup-test",
        "PATH": str(bin_dir),
        "SETUP_PROFILE": str(profile),
        "SETUP_COMMANDS": str(log),
    }

    for _ in range(2):
        subprocess.run(["/bin/bash", str(repo / "linux/setup.sh")], env=environment, check=True, capture_output=True, text=True)

    rendered = profile.read_text()
    for cache in (".agent-browser/browsers", ".cache/ms-playwright", ".cache/puppeteer/chrome"):
        assert f'"{home}/{cache}/' in rendered
    assert "@@HOME@@" not in rendered
    assert "/home/akelly" not in rendered
    assert ("apt-get install -y bubblewrap socat trash-cli" in log.read_text()) == (missing_command is not None)
    assert (home / "Git").is_dir()
    subprocess.run(["apparmor_parser", "--skip-kernel-load", "--skip-cache", str(profile)], check=True, capture_output=True, text=True)
