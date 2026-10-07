#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pytest", "tomlkit>=0.13", "filelock>=3.16", "websockets>=14"]
# ///
"""Run the test suite with the tested scripts' dependencies; arguments pass through to pytest."""

import sys
from pathlib import Path

import pytest

raise SystemExit(pytest.main([str(Path(__file__).parent), *sys.argv[1:]]))
