#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.9"
# ///
# Claude Code PreToolUse hook (matcher mcp__.*): auto-allow all MCP tools.
# A script rather than an inline echo so the settings.json command needs no
# shell quoting and behaves the same under cmd, PowerShell, and bash.
import json

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "permissionDecisionReason": "All MCP tools are allowed",
    }
}))
