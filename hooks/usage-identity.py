#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Record the session's Claude account for usage-trends without retaining prompt text."""
import hashlib
import json
import os
import sys
import time
from pathlib import Path


def key(*values):
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def main():
    config = Path.home() / ".config/usage-trends/config.json"
    if not config.exists():
        return
    event = json.load(sys.stdin)
    settings = json.loads(config.read_text())
    profile = os.environ.get("CLAUDE_PROFILE")
    if not profile:
        raise ValueError("CLAUDE_PROFILE must name the account this Claude session signed in as")
    account = f"claude-{profile}"
    identity = next((h for h, name in settings["claude_accounts"].items() if name == account), None)
    if identity is None:
        raise ValueError(f"usage-trends claude_accounts has no identity for {account}")
    binding = dict(session=key(event["session_id"]), timestamp=time.time(), identity=identity)
    state = Path(settings["state_dir"]).expanduser()
    state.mkdir(parents=True, exist_ok=True)
    fd = os.open(state / "session-bindings.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write((json.dumps(binding) + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())


if __name__ == "__main__":
    main()
