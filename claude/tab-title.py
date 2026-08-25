#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""Drive the terminal tab title glyph from Claude Code session state."""

import json
import os
import subprocess
import sys

ESC = "\x1b"
BEL = "\x07"


def emit(sequence: str) -> None:
    print(json.dumps({"terminalSequence": sequence}, separators=(",", ":")))


def title(glyph: str) -> None:
    emit(f"{ESC}]0;{glyph} Claude Code{BEL}")


def frontmost_iterm_session() -> str:
    front = subprocess.run(
        ["lsappinfo", "front"], capture_output=True, text=True
    ).stdout.strip()
    app = subprocess.run(
        ["lsappinfo", "info", "-only", "name", front],
        capture_output=True,
        text=True,
    ).stdout
    if "iTerm" not in app:
        return ""
    return subprocess.run(
        [
            "osascript",
            "-e",
            "tell application \"iTerm2\" to tell current window to tell current session to get id",
        ],
        capture_output=True,
        text=True,
    ).stdout.strip()


data = json.load(sys.stdin)
event = data["hook_event_name"]

if event == "SessionStart":
    title("✳")
elif event in {"UserPromptSubmit", "PreToolUse"}:
    title("•")
elif event == "Notification" and data.get("notification_type") in {
    "permission_prompt",
    "elicitation_dialog",
}:
    title("?")
elif event == "Stop":
    session = os.environ.get("ITERM_SESSION_ID", "").split(":")[-1]
    if sys.platform == "darwin" and session and session == frontmost_iterm_session():
        title("✳")
    else:
        emit(f"{BEL}{ESC}]0;◆ Claude Code{BEL}")
elif event == "SessionEnd":
    emit(f"{ESC}]0;{BEL}")
