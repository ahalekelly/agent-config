#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# ///

import json
import os
import re
import shlex
import sys

BLOCK_REASON = "Blocked: do not delete files with rm. Use the trash command instead, e.g. `trash path/to/file`."


def command_from_hook(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""

    for key in ("tool_input", "input"):
        value = payload.get(key)
        if isinstance(value, dict) and isinstance(value.get("command"), str):
            return value["command"]

    if isinstance(payload.get("command"), str):
        return payload["command"]

    return ""


def token_is_rm(token: str) -> bool:
    return os.path.basename(token) == "rm"


def shell_tokens(command: str) -> list[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def contains_rm(command: str) -> bool:
    try:
        tokens = shell_tokens(command)
    except ValueError:
        return bool(re.search(r"(^|[;&|()`])\s*(?:command\s+|sudo\s+|env\s+)?(?:/[^\s;&|()`]+/)?rm\b", command))

    command_start = True
    previous = ""
    wrappers = {"command", "sudo", "env", "time", "xargs", "-exec", "-execdir", "-c"}
    separators = {";", "&", "&&", "|", "||", "(", ")", "`"}

    for token in tokens:
        base = os.path.basename(token)
        if token in separators:
            command_start = True
        elif token_is_rm(token) and (command_start or previous in wrappers):
            return True
        elif previous == "-c" and re.match(r"\s*(?:/[^\s;&|()`]+/)?rm\b", token):
            return True
        elif command_start and "=" in token and not token.startswith("="):
            command_start = True
        else:
            command_start = base in wrappers
        previous = base

    return False


def deny() -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": BLOCK_REASON,
        }
    }))


def main() -> int:
    raw = sys.stdin.read()
    payload = json.loads(raw) if raw.strip() else {}
    command = command_from_hook(payload)

    if command and contains_rm(command):
        deny()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
