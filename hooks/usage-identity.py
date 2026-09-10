#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Record the active Claude account for a session without retaining prompt text."""
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
    profile = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))
    settings = json.loads(config.read_text())
    sources = [s for s in settings["sources"] if s["provider"] == "claude"
               and Path(s["path"]).expanduser().parent.resolve() == profile.resolve()]
    if len(sources) != 1:
        raise ValueError("Active Claude profile needs exactly one usage-trends identity mapping")
    source = sources[0]
    account = json.loads(Path(source["identity_file"]).expanduser().read_text())["oauthAccount"]
    if key("claude", account["accountUuid"], account["organizationUuid"]) != source["identity"]:
        raise ValueError("Claude account changed; update usage-trends mapping")
    binding = dict(session=key(event["session_id"]), timestamp=time.time(),
                   identity=key("claude", account["accountUuid"], account["organizationUuid"]))
    state = Path(settings["state_dir"]).expanduser()
    state.mkdir(parents=True, exist_ok=True)
    fd = os.open(state / "session-bindings.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write((json.dumps(binding) + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())


if __name__ == "__main__":
    main()
