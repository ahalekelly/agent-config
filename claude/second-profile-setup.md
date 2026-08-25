# Two Claude Code profiles

The `claude` and `claudew` shell functions select `~/.claude` and `~/.claude-work` through `CLAUDE_CONFIG_DIR`. Both profiles share configuration and runtime data while keeping account identity separate.

`uv run ~/.agents/sync.py` creates `~/.claude-work` as a real directory. It links shared configuration directly to this repo and shared runtime entries to the matching entry under `~/.claude`. Files that Claude creates only in `~/.claude-work`, including `.claude.json`, remain specific to the work account.

Run `claudew` and log in with the work account after syncing. The shell wrapper disables its auto-updater because both profiles use one Claude installation.
