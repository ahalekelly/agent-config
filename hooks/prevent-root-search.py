#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# ///
"""Deny Bash commands that search from /, /home, ~, /mnt, or a drive mounted under /mnt.

A whole-filesystem find or grep crawls every mounted drive and can run for an
hour at high CPU. Commands that stay on one filesystem (find -xdev or -mount,
du -x in any short-flag cluster such as -xsh, --one-file-system) are allowed, as
are searches inside a subdirectory of a drive.
"""

import json
import os
import re
import shlex
import sys

HOME = os.path.expanduser("~")
FORBIDDEN_ROOTS = {"/", "/home", HOME, "/mnt"}
SEPARATORS = {";", "&", "&&", "|", "||", "(", ")", "`"}
WRAPPERS = {"sudo", "command", "env", "nice", "ionice", "timeout", "time", "nohup", "exec"}
ONE_FILESYSTEM_FLAGS = {
    "find": {"-xdev", "-mount"},
    "bfs": {"-xdev", "-mount"},
    "du": {"--one-file-system"},
    "tree": set(),
    "rg": {"--one-file-system"},
    "fd": {"--one-file-system"},
    "fdfind": {"--one-file-system"},
}
# du and tree spell one-file-system as -x, which bundles into clusters like -xsh.
# rg -x is --line-regexp and fd -x is --exec, so the cluster rule stays off them.
X_CLUSTER_COMMANDS = {"du", "tree"}
BLOCK_REASON = (
    "Blocked: searching from /, /home, ~, or /mnt crawls every mounted drive and runs for "
    "an hour at high CPU. Search a specific directory instead, or stay on one filesystem "
    "with find -xdev, du -x, or rg --one-file-system."
)


def command_from_hook(payload: object) -> tuple[str, str]:
    if not isinstance(payload, dict):
        return "", ""
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else ""
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict) and isinstance(tool_input.get("command"), str):
        return tool_input["command"], cwd
    return "", cwd


def shell_segments(command: str) -> list[list[str]]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    segments: list[list[str]] = [[]]
    for token in lexer:
        if token in SEPARATORS:
            segments.append([])
        else:
            segments[-1].append(token)
    return [s for s in segments if s]


def strip_wrappers(tokens: list[str]) -> list[str]:
    while tokens:
        head = tokens[0]
        if "=" in head and not head.startswith("="):
            tokens = tokens[1:]
        elif os.path.basename(head) in WRAPPERS:
            tokens = tokens[1:]
            while tokens and (tokens[0].startswith("-") or tokens[0].isdigit()):
                tokens = tokens[1:]
        else:
            break
    return tokens


def is_forbidden(path: str, cwd: str) -> bool:
    expanded = os.path.expandvars(os.path.expanduser(path)).rstrip("*")
    normalized = os.path.normpath(os.path.join(cwd, expanded))
    return normalized in FORBIDDEN_ROOTS or re.fullmatch(r"/mnt/[^/]+", normalized) is not None


def find_roots(args: list[str]) -> list[str]:
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in {"-S", "-j", "-O"} else 1
    roots = []
    while i < len(args) and not args[i].startswith("-") and args[i] not in {"(", "!", ","}:
        roots.append(args[i])
        i += 1
    return roots


def positional_args(args: list[str]) -> list[str]:
    return [a for a in args if not a.startswith("-")]


def has_flag(args: list[str], pattern: str) -> bool:
    return any(re.match(pattern, a) for a in args)


def stays_on_one_filesystem(name: str, args: list[str]) -> bool:
    if any(a in ONE_FILESYSTEM_FLAGS.get(name, ()) for a in args):
        return True
    return name in X_CLUSTER_COMMANDS and has_flag(args, r"^-[a-zA-Z]*x[a-zA-Z]*$")


def segment_searches_forbidden_root(tokens: list[str], cwd: str) -> bool:
    tokens = strip_wrappers(tokens)
    if not tokens:
        return False
    name = os.path.basename(tokens[0])
    args = tokens[1:]
    if stays_on_one_filesystem(name, args):
        return False

    if name in {"find", "bfs"}:
        roots = find_roots(args) or [cwd]
    elif name in {"tree", "du"}:
        roots = positional_args(args) or [cwd]
    elif name in {"rg", "fd", "fdfind"}:
        roots = positional_args(args)
    elif name in {"grep", "egrep", "fgrep"} and has_flag(args, r"^(-[a-zA-Z]*[rR]|--(dereference-)?recursive)"):
        roots = positional_args(args)
    elif name == "ls" and has_flag(args, r"^(-[a-zA-Z]*R|--recursive)"):
        roots = positional_args(args) or [cwd]
    else:
        return False
    return any(is_forbidden(r, cwd) for r in roots if r)


def searches_forbidden_root(command: str, cwd: str) -> bool:
    try:
        segments = shell_segments(command)
    except ValueError:
        return bool(re.search(r"\b(find|bfs|rg|grep|du|tree)\b[^;&|]*\s(/|~|\$HOME|/home|/mnt)(/\S*)?(\s|$)", command))
    return any(segment_searches_forbidden_root(s, cwd) for s in segments)


def main() -> int:
    raw = sys.stdin.read()
    payload = json.loads(raw) if raw.strip() else {}
    command, cwd = command_from_hook(payload)
    if command and searches_forbidden_root(command, cwd):
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": BLOCK_REASON,
            }
        }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
