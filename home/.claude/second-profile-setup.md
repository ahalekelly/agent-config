# Two Claude Code profiles via `CLAUDE_CONFIG_DIR`, sharing everything except the account

Run two Claude Code profiles — personal (`~/.claude`) and work (`~/.claude-work`) — switched by shell functions that set `CLAUDE_CONFIG_DIR`:

```zsh
_claude_with_profile() {
  CLAUDE_CONFIG_DIR="$1" _scrub_secrets claude "${@:2}"
}

# Personal profile (default)
claude() {
  _claude_with_profile "$HOME/.claude" "$@"
}

# Work profile. Auto-update stays off here: both profiles share one version
# store, so the personal profile keeps it updated and a second updater only
# adds a failure-prone race.
claudew() {
  DISABLE_AUTOUPDATER=1 _claude_with_profile "$HOME/.claude-work" "$@"
}
```

(`_scrub_secrets` is a separate wrapper that strips API keys from the environment before launching — if you don't have it, use `command claude` in its place.)

The trick is that `~/.claude-work` is not a full second config — almost everything inside it is a symlink back to the same file/directory in `~/.claude`, so both profiles share settings, skills, agents, plugins, history, and project state. The only things that stay real (per-profile) files are the ones holding account identity and login state — most importantly `.claude.json`, which is where OAuth credentials and MCP auth live. So `claudew` logs into the work Anthropic account while everything else behaves identically.

## Setup

In this repo the profile directory lives at `~/.agents/home/.claude-work` (with `~/.claude-work` symlinked to it) and the symlink structure is tracked in git — only the per-profile files (`.claude.json`, `sessions/`, caches) stay untracked. To recreate it from scratch:

```zsh
mkdir -p ~/.claude-work
cd ~/.claude-work
for f in agents backups cache CLAUDE.md debug downloads file-history \
         history.jsonl ide output-styles paste-cache plans plugins \
         projects scripts session-env settings.json settings.local.json \
         shell-snapshots skills statsig tasks telemetry todos; do
  ln -s ~/.claude/$f $f
done
```

Then add the shell functions to `.bashrc` / `.zshrc`, run `claudew`, and log in with the work account. Claude Code creates the remaining per-profile files (`.claude.json`, `sessions/`, caches) on first run.
