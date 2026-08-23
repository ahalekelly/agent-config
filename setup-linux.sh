#!/usr/bin/env bash
# One-time Linux setup: point the $HOME agent dotfiles at this repo (see README.md).
# Run with the repo already at ~/.agents. Idempotent: safe to re-run.
#   bash ~/.agents/setup-linux.sh
set -euo pipefail
repo="$HOME/.agents"
[ -d "$repo/.git" ] || { echo "Repo not found at $repo - clone it there first" >&2; exit 1; }

# Per-clone git config the .gitattributes clean filter depends on (see README).
git -C "$repo" config filter.codex-config.clean 'uv run "$HOME/.agents/clean-codex-config.py"'
git -C "$repo" config filter.codex-config.required true

# Swap ~/.claude to a symlink into home-linux/. Existing runtime state moves
# into the repo (it stays untracked: .gitignore is deny-all); where a file
# already exists in the repo, the repo copy wins and the machine's old copy is
# kept alongside as *.pre-agents-repo. Renames within one filesystem keep
# inodes, so a running daemon/session keeps its open files.
swap() {
  local live="$HOME/$1" target="$repo/home-linux/$1"
  if [ -L "$live" ]; then echo "$live already a symlink"; return; fi
  mkdir -p "$target"
  if [ -d "$live" ]; then
    for child in "$live"/.[!.]* "$live"/*; do
      [ -e "$child" ] || [ -L "$child" ] || continue
      name="$(basename "$child")"
      if [ -e "$target/$name" ] || [ -L "$target/$name" ]; then
        mv "$child" "$target/$name.pre-agents-repo"
      else
        mv "$child" "$target/$name"
      fi
    done
    rmdir "$live"
  fi
  ln -s "$target" "$live"
  echo "$live -> $target"
}
swap .claude

# Global git ignore (shared with macOS).
mkdir -p "$HOME/.config/git"
if [ ! -L "$HOME/.config/git/ignore" ]; then
  [ -e "$HOME/.config/git/ignore" ] && mv "$HOME/.config/git/ignore" "$HOME/.config/git/ignore.pre-agents-repo"
  ln -s "$repo/home/.config/git/ignore" "$HOME/.config/git/ignore"
  echo "~/.config/git/ignore -> $repo/home/.config/git/ignore"
fi

# Bash wrappers (bash port of home/.zshrc's agent functions).
line='[ -f "$HOME/.agents/home-linux/.bashrc.agents" ] && . "$HOME/.agents/home-linux/.bashrc.agents"'
grep -qF '.bashrc.agents' "$HOME/.bashrc" || printf '\n# Agent config (~/.agents)\n%s\n' "$line" >> "$HOME/.bashrc"

# trash-cli: `trash` is what agents are told to use instead of rm.
command -v trash >/dev/null || npm install -g trash-cli

# Claude Remote Control as a user service (home-linux/.config/systemd/user/).
# Linger keeps user services running at boot and after logout.
mkdir -p "$HOME/.config/systemd/user"
[ -L "$HOME/.config/systemd/user/claude-remote-control.service" ] || ln -s "$repo/home-linux/.config/systemd/user/claude-remote-control.service" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
sudo loginctl enable-linger "$USER"

# Sandboxed Bash in remote sessions needs socat, and on Ubuntu an AppArmor
# profile that lets bwrap create nested user namespaces (home-linux/apparmor.d/).
command -v socat >/dev/null || sudo apt-get install -y socat
if [ "$(sysctl -n kernel.apparmor_restrict_unprivileged_userns 2>/dev/null)" = 1 ]; then
  sudo cp "$repo/home-linux/apparmor.d/bwrap" /etc/apparmor.d/bwrap
  sudo mkdir -p /etc/apparmor.d/disable
  sudo ln -sf /etc/apparmor.d/bwrap-userns-restrict /etc/apparmor.d/disable/bwrap-userns-restrict
  sudo apparmor_parser -R /etc/apparmor.d/bwrap-userns-restrict 2>/dev/null || true
  sudo systemctl reload apparmor
fi

echo 'Done. Then: (cd ~/.agents/pi-for-claude && npm install && npm link) && pi-for-claude setup'
echo 'Then run `claude` once in ~/Git, then `claude remote-control` once to accept its prompt, then: systemctl --user enable --now claude-remote-control'
