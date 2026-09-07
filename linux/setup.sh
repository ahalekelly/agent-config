#!/usr/bin/env bash
# One-time Linux system setup. Run sync.py first.
set -euo pipefail

repo="$HOME/.agents"
[ -d "$repo/.git" ] || { echo "Repo not found at $repo - clone it there first" >&2; exit 1; }

line='[ -f "$HOME/.agents/shell/bashrc.agents" ] && . "$HOME/.agents/shell/bashrc.agents"'
grep -qF '.agents/shell/bashrc.agents' "$HOME/.bashrc" || printf '\n# Agent config (~/.agents)\n%s\n' "$line" >> "$HOME/.bashrc"

command -v trash >/dev/null || npm install -g trash-cli
if ! command -v bwrap >/dev/null || ! command -v socat >/dev/null || ! command -v trash-empty >/dev/null; then
  sudo apt-get install -y bubblewrap socat trash-cli
fi

if [ "$(sysctl -n kernel.apparmor_restrict_unprivileged_userns 2>/dev/null)" = 1 ]; then
  sudo cp "$repo/linux/apparmor.d/bwrap" /etc/apparmor.d/bwrap
  chromium_profile=$(<"$repo/linux/apparmor.d/agent-chromium")
  printf '%s\n' "${chromium_profile//@@HOME@@/"$HOME"}" | sudo tee /etc/apparmor.d/agent-chromium > /dev/null
  sudo chmod 644 /etc/apparmor.d/agent-chromium
  sudo mkdir -p /etc/apparmor.d/disable
  sudo ln -sf /etc/apparmor.d/bwrap-userns-restrict /etc/apparmor.d/disable/bwrap-userns-restrict
  sudo apparmor_parser -R /etc/apparmor.d/bwrap-userns-restrict 2>/dev/null || true
  sudo systemctl reload apparmor
fi

mkdir -p "$HOME/Git"
systemctl --user daemon-reload
systemctl --user enable --now \
  claude-remote-control.service \
  claude-patching-autoport.path \
  claude-patching-autoport.service
sudo loginctl enable-linger "$USER"

echo 'Restart your shell, then run `claude` once in ~/Git and `claude remote-control` once.'
