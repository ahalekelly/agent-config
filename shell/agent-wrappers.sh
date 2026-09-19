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

_patched_claude() {
  # The patcher returns the best available binary while reconciling updates in
  # the background. Pause after a visible error before the TUI clears it.
  local target bin=claude
  if ! target="$("$HOME/.agents/claude-patching/check-and-apply.sh")" && [[ -t 0 && -t 1 ]]; then
    printf 'Press Enter to launch Claude Code... '
    read -r
  fi
  [[ -n "$target" ]] && bin="$target"
  _scrub_secrets "$bin" "$@"
}

# One launcher, two accounts: each function exports the token and profile from
# its env file (see README.md) and runs bin/claude-launch.
claude()  { (set -a; source "$HOME/.agents/claude-token.env";  set +a; exec "$HOME/.agents/bin/claude-launch" "$@"); }
claudew() { (set -a; source "$HOME/.agents/claudew-token.env"; set +a; exec "$HOME/.agents/bin/claude-launch" "$@"); }
ca() { claude agents "$@"; }
caw() { claudew agents "$@"; }
