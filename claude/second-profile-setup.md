# Two Claude Code profiles

The `claude` shell function uses the default `~/.claude`; `claudew` (`~/.agents/bin/claudew`, an executable so tools like T3 Code can spawn it) sets `CLAUDE_CONFIG_DIR=~/.claude-work`. `claude` must leave `CLAUDE_CONFIG_DIR` unset: Claude Code keys its macOS Keychain entry on whether the variable is set, so setting it even to the default splits credentials from tools that launch `claude` bare. Both profiles share configuration and runtime data while keeping account identity separate.

`uv run ~/.agents/sync.py` creates `~/.claude-work` as a real directory. It links shared configuration directly to this repo and shared runtime entries to the matching entry under `~/.claude`. Files that Claude creates only in `~/.claude-work`, including `.claude.json`, remain specific to the work account.

Run `claudew` and log in with the work account after syncing. It disables its auto-updater because both profiles use one Claude installation and two updaters race. In T3 Code, add a second Claude provider with binary path `~/.agents/bin/claudew` (absolute path) and home path `~/.claude-work`.
