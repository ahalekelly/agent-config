# /// script
# requires-python = ">=3.11"
# dependencies = ["pytest"]
# ///
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "bin/t3-thread.py"


@pytest.mark.parametrize("mode", ["new", "resume"])
def test_missing_runtime_explains_server_readiness(tmp_path, mode):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Hello")
    args = ["new", str(tmp_path), "Test", "model"] if mode == "new" else ["resume", "thread-id"]
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args, str(prompt)],
        env=os.environ | {"T3CODE_HOME": str(tmp_path)},
        capture_output=True, text=True,
    )

    assert result.returncode == 1
    assert str(tmp_path / "userdata/server-runtime.json") in result.stderr
    assert "running and ready" in result.stderr
    assert "T3CODE_HOME" in result.stderr
    assert "Traceback" not in result.stderr
