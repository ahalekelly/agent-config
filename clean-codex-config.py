#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# ///
# git clean filter for .codex/config.toml (see info/attributes).
# Codex appends a [projects."<path>"] trust entry for every directory it runs
# in, and bumps last_updated timestamps under [marketplaces.*] on refresh —
# machine-generated activity history that must not be committed. Strips both
# and normalizes the trailing newline so the staged blob stays byte-identical
# to the committed one.
import re
import sys

data = sys.stdin.buffer.read()
data = re.sub(rb'\[projects\."[^"]*"\]\ntrust_level = "[a-z]+"\n\n?', b"", data)
data = re.sub(rb'(?m)^last_updated = "[^"]*"\n', b"", data)
data = re.sub(rb"\n+\Z", b"\n", data)
sys.stdout.buffer.write(data)
