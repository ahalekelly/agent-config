alias axbrew='arch -x86_64 /usr/local/homebrew/bin/brew'

export STM32CubeMX_PATH=/Applications/STMicroelectronics/STM32CubeMX.app/Contents/Resources
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"  # This loads nvm
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion
export PATH="$HOME/.local/bin:$PATH"

# Secrets in ~/.secrets.env must not reach AI agents; the terminal env has
# them (via ~/.zprofile), so agent launchers scrub every var named there.
# For Claude this also keeps ANTHROPIC_API_KEY from overriding claude.ai login.
_scrub_secrets() {
  local scrub=() name
  for name in $(grep -oE '^export [A-Z_]+' ~/.secrets.env | cut -d' ' -f2); do
    scrub+=(-u "$name")
  done
  env "${scrub[@]}" AGENT_LAUNCH=1 "$@"
}

codex() { _scrub_secrets codex "$@"; }

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

# Claude Code on GPT via CLIProxyAPI (brew service, 127.0.0.1:8317).
# CLIPROXYAPI_KEY comes from ~/.agents/secrets.env; the config lives at
# /opt/homebrew/etc/cliproxyapi.conf and the Codex OAuth token in ~/.cli-proxy-api/.
claudex() {
  ANTHROPIC_BASE_URL=http://127.0.0.1:8317 \
  ANTHROPIC_AUTH_TOKEN="$CLIPROXYAPI_KEY" \
  CLAUDE_CODE_SUBAGENT_MODEL=gpt-5.6-sol \
  CLAUDE_CODE_ALWAYS_ENABLE_EFFORT=1 \
  CLAUDE_CODE_MAX_TOOL_USE_CONCURRENCY=3 \
  ENABLE_TOOL_SEARCH=false \
  ENABLE_CLAUDEAI_MCP_SERVERS=false \
  claude --model gpt-5.6-sol "$@"
}

# Fable main loop with gpt-5.6-sol subagents, both routed through CLIProxyAPI
# (requires both a Claude and a Codex OAuth credential in ~/.cli-proxy-api/).
# claude.ai connectors can't work in proxied sessions, so they're switched off
# explicitly to silence the startup warning.
claudef() {
  ANTHROPIC_BASE_URL=http://127.0.0.1:8317 \
  ANTHROPIC_AUTH_TOKEN="$CLIPROXYAPI_KEY" \
  CLAUDE_CODE_SUBAGENT_MODEL=gpt-5.6-sol \
  ENABLE_CLAUDEAI_MCP_SERVERS=false \
  claude --model claude-fable-5 "$@"
}

# PlatformIO CLI
export PATH="$HOME/.platformio/penv/bin:$PATH"

alias git-agent-cfg='git -C "$HOME/.agents"'
