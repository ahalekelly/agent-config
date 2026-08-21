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

echo 'Done. Then: (cd ~/.agents/pi-for-claude && npm install && npm link) && pi-for-claude setup'
