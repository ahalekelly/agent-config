# Two Claude Code profiles

The `claude` shell function runs `~/.agents/bin/claude-token` with the default `~/.claude`; `claudew` (`~/.agents/bin/claudew`) sets `CLAUDE_CONFIG_DIR=~/.claude-work`. Both are executables so tools like T3 Code can spawn them. `claude-token` must leave `CLAUDE_CONFIG_DIR` unset: Claude Code keys its macOS Keychain entry on whether the variable is set, so setting it even to the default splits state from tools that launch `claude` bare. Both profiles share configuration and runtime data while keeping account identity separate.

Each launcher authenticates with a one-year token. Run `command claude setup-token`, log in with the account for that profile, and store the result as `CLAUDE_CODE_OAUTH_TOKEN=<token>` in `~/.agents/claude-token.env` (personal) or `~/.agents/claudew-token.env` (work), owner-readable only. The launcher refuses to start until its file exists. Token sessions can't use claude.ai connectors or Remote Control.

`uv run ~/.agents/sync.py` creates `~/.claude-work` as a real directory. It links shared configuration directly to this repo and shared runtime entries to the matching entry under `~/.claude`. Files that Claude creates only in `~/.claude-work`, including `.claude.json`, remain specific to the work account.

On macOS and Linux, syncing links `claudew` into `~/.local/bin` for normal terminal use. Both launchers disable the auto-updater because the profiles share one Claude installation and two updaters race. In T3 Code, the default Claude provider's binary path is `~/.agents/bin/claude-token`; the second one uses `~/.agents/bin/claudew` (absolute paths) with home path `~/.claude-work`.
