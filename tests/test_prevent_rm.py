# /// script
# requires-python = ">=3.11"
# dependencies = ["pytest"]
# ///

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("command", ["rm file", "/bin/rm file", "command rm file", "echo ready && rm file"])
def test_direct_deletion_is_denied(command):
    result = subprocess.run(
        [sys.executable, str(ROOT / "hooks" / "prevent-rm.py")],
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}),
        text=True,
        capture_output=True,
        check=True,
    )
    output = json.loads(result.stdout)["hookSpecificOutput"]
    assert output["permissionDecision"] == "deny"
    assert "trash" in output["permissionDecisionReason"]


def test_dependency_build_is_allowed():
    result = subprocess.run(
        [sys.executable, str(ROOT / "hooks" / "prevent-rm.py")],
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "pod install"}}),
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout == ""


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell PATH")
def test_child_shell_does_not_inherit_agent_deletion_guard():
    result = subprocess.run(
        ["/bin/sh", "-c", "rm"],
        env={**os.environ, "PATH": f"{ROOT / 'bin'}:/usr/bin:/bin"},
        text=True,
        capture_output=True,
    )
    # No operands: exercise command resolution without deleting anything.
    assert result.returncode != 0
    assert "Blocked: do not delete files" not in result.stderr
    assert "usage:" in result.stderr.lower() or "missing operand" in result.stderr.lower()
