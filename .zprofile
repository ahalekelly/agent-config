
# API keys that aren't costly to leak go in the agents secrets file so AI agents can access them: 
eval "$(/opt/homebrew/bin/brew shellenv)"
. "$HOME/.agents/secrets.env"

# API keys that are costly to leak go here, AI agents shouldn't have access.
# Agent harnesses snapshot or source this profile into their shell
# environments, so only real user terminals get these: agent launches carry a
# marker (AGENT_LAUNCH from the ~/.zshrc wrappers, or the harness's own), and
# desktop-app shells have no TERM_PROGRAM. Note: ssh sessions also lack
# TERM_PROGRAM; source ~/.secrets.env manually there if needed.
if [ -n "$TERM_PROGRAM" ] && [ -z "$AGENT_LAUNCH$CLAUDECODE$AI_AGENT$CODEX_SANDBOX$PI_CODING_AGENT" ]; then
  . "$HOME/.secrets.env"
fi

# Added by Obsidian
export PATH="$PATH:/Applications/Obsidian.app/Contents/MacOS"
export PATH="$PATH:$HOME/Git/codex-plugin-cc/bin"
export PATH="$PATH:$HOME/.agents/pi-run/bin"
