# Shared agent launchers for bash and zsh.

_scrub_secrets() {
  local scrub=() name
  if [ -f "$HOME/.secrets.env" ]; then
    for name in $(grep -oE '^export [A-Z_]+' "$HOME/.secrets.env" | cut -d' ' -f2); do
      scrub+=(-u "$name")
    done
  fi
  env "${scrub[@]}" AGENT_LAUNCH=1 "$@"
}

codex() { _scrub_secrets codex "$@"; }
# Keep the interactive Pi CLI at the version used by pi-for-claude.
pi() { _scrub_secrets "$HOME/.agents/pi-for-claude/node_modules/.bin/pi" "$@"; }

_claude_with_profile() {
  # The patcher returns the best available binary while reconciling updates in
  # the background. Pause after a visible error before the TUI clears it.
  local target bin=claude
  if ! target="$("$HOME/.agents/claude-patching/check-and-apply.sh")" && [[ -t 0 && -t 1 ]]; then
    printf 'Press Enter to launch Claude Code... '
    read -r
  fi
  [[ -n "$target" ]] && bin="$target"
  CLAUDE_CONFIG_DIR="$1" _scrub_secrets "$bin" "${@:2}"
}

claude() { _claude_with_profile "$HOME/.claude" "$@"; }
# Both profiles share one version store, so only the personal profile updates it.
claudew() { DISABLE_AUTOUPDATER=1 _claude_with_profile "$HOME/.claude-work" "$@"; }
ca() { claude agents "$@"; }
caw() { claudew agents "$@"; }
