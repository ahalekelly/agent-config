#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# ///
# Claude Code status line (cross-platform port of ../../home/.claude/statusline.sh):
# directory | branch(*dirty) +added/-removed | tokens - last-request time | $cost | 5h usage % (reset time) | model

import json
import os
import subprocess
import sys
from datetime import datetime

data = json.load(sys.stdin)


def git(args: list[str], cwd: str) -> str:
    result = subprocess.run(
        ["git", "-C", cwd, "--no-optional-locks", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return result.stdout.strip() if result.returncode == 0 else ""


model = data.get("model", {}).get("display_name", "")
model = model.split(" (")[0]  # drop a "(1M context)"-style suffix

cwd = data.get("workspace", {}).get("current_dir") or data.get("cwd", "")
base = os.path.basename(cwd.rstrip("/\\"))

git_part = ""
branch = git(["rev-parse", "--abbrev-ref", "HEAD"], cwd) if cwd else ""
if branch:
    dirty = "*" if git(["status", "--porcelain"], cwd) else ""
    # uncommitted line counts: tracked diff plus all lines in untracked (unignored) files
    added = removed = 0
    for line in git(["diff", "HEAD", "--numstat"], cwd).splitlines():
        a, r, _ = line.split("\t", 2)
        added += int(a) if a.isdigit() else 0
        removed += int(r) if r.isdigit() else 0
    for name in git(["ls-files", "--others", "--exclude-standard"], cwd).splitlines():
        try:
            with open(os.path.join(cwd, name), "rb") as f:
                added += f.read().count(b"\n")
        except OSError:
            pass
    changes = f" +{added}/-{removed}" if added + removed > 0 else ""
    git_part = f"{branch}{dirty}{changes}"

tokens_part = ""
tokens = data.get("context_window", {}).get("total_input_tokens")
if tokens is not None:
    count = f"{round(tokens / 1000)}k" if tokens >= 1000 else str(tokens)
    # The 1h prompt-cache TTL refreshes when each API request is *created*, so the
    # anchor is the last user/tool-result entry (sent just before the final request),
    # not the transcript mtime — mtime lags by the final response's streaming time.
    turn_time = ""
    transcript = data.get("transcript_path", "")
    if transcript and os.path.isfile(transcript):
        timestamps = []
        with open(transcript, encoding="utf-8", errors="replace") as f:
            for line in f.readlines()[-500:]:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") == "user" and entry.get("timestamp"):
                    timestamps.append(entry["timestamp"])
        if timestamps:
            ts = max(timestamps)
            local = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
            turn_time = f" - {local:%H:%M}"
    tokens_part = f"{count} tokens{turn_time}"

cost = data.get("cost", {}).get("total_cost_usd")
cost_part = f"${cost:.2f}" if cost is not None else ""

usage_part = ""
five_hour = data.get("rate_limits", {}).get("five_hour", {})
usage = five_hour.get("used_percentage")
if usage is not None:
    reset = ""
    resets_at = five_hour.get("resets_at")
    if resets_at:
        reset = f" {datetime.fromtimestamp(int(resets_at)).astimezone():%H:%M}"
    usage_part = f"5h: {round(usage)}%{reset}"

print(" | ".join(p for p in [base, git_part, tokens_part, cost_part, usage_part, model] if p))
