#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pytest"]
# ///
"""Tests for the prevent-root-search PreToolUse hook."""

import importlib.util
import os
import pathlib
import sys

import pytest

spec = importlib.util.spec_from_file_location(
    "prevent_root_search", pathlib.Path(__file__).parent / "prevent-root-search.py"
)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)

HOME = os.path.expanduser("~")
REPO = f"{HOME}/.agents"


@pytest.mark.parametrize("command", [
    "sudo du -xh --max-depth=1 /",
    "sudo du -xsh /var /usr /opt",
    'cd "$H" && du -xsh -- * .[!.]*',
    "find / -xdev -name x",
    "du -sh /mnt/960PRO/backups",
    "rg --one-file-system foo /",
])
def test_allowed(command):
    assert not hook.searches_forbidden_root(command, REPO)


@pytest.mark.parametrize("command", [
    "du -sh /",
    "find / -name x",
    "rg foo ~",
    "grep -r foo /home",
    "du -sh /mnt/960PRO",
    "rg -x foo /",
])
def test_blocked(command):
    assert hook.searches_forbidden_root(command, REPO)


def test_relative_root_resolves_against_cwd():
    assert hook.searches_forbidden_root("du -sh .", HOME)
    assert not hook.searches_forbidden_root("du -sh .", REPO)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
