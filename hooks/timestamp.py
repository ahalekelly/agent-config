#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# ///
"""Codex UserPromptSubmit hook: print the local time as model context.

Codex feeds the hook event JSON on stdin and injects stdout as developer
context. Time only — Codex usage would need the ChatGPT token dance that
hooks/usage-context.sh does for Claude, and Pi's runs already track it.
"""
import sys
import time

sys.stdin.read()
print(time.strftime("Time: %A %Y-%m-%d %H:%M:%S %Z"))
