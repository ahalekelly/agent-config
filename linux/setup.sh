#!/usr/bin/env bash
# One-time Linux system setup. Run sync.py first.
set -euo pipefail

repo="$HOME/.agents"
[ -d "$repo/.git" ] || { echo "Repo not found at $repo - clone it there first" >&2; exit 1; }

line='[ -f "$HOME/.agents/shell/bashrc.agents" ] && . "$HOME/.agents/shell/bashrc.agents"'
grep -qF '.agents/shell/bashrc.agents' "$HOME/.bashrc" || printf '\n# Agent config (~/.agents)\n%s\n' "$line" >> "$HOME/.bashrc"

command -v trash >/dev/null || npm install -g trash-cli
command -v socat >/dev/null || sudo apt-get install -y socat

if [ "$(sysctl -n kernel.apparmor_restrict_unprivileged_userns 2>/dev/null)" = 1 ]; then
  sudo cp "$repo/linux/apparmor.d/bwrap" /etc/apparmor.d/bwrap
  sudo mkdir -p /etc/apparmor.d/disable
  sudo ln -sf /etc/apparmor.d/bwrap-userns-restrict /etc/apparmor.d/disable/bwrap-userns-restrict
  sudo apparmor_parser -R /etc/apparmor.d/bwrap-userns-restrict 2>/dev/null || true
  sudo systemctl reload apparmor
fi

systemctl --user daemon-reload
systemctl --user enable --now \
  claude-remote-control.service \
  claude-patching-autoport.path \
  claude-patching-autoport.service
sudo loginctl enable-linger "$USER"

echo 'Restart your shell, then run `claude` once in ~/Git and `claude remote-control` once.'
