# agent-config

Versioned configuration for the coding agents on this machine: Claude Code, Codex, and Pi. The repo lives at `~/.agents`, and the agent dotfiles in `$HOME` are symlinks into it.

## Layout

- `AGENTS.md` — shared instructions for all agents. Claude loads it via `@` from its CLAUDE.md; Codex and Pi read it through symlinks (`home/.codex/AGENTS.md`, `home/.pi/agent/AGENTS.md`).
- `home/` — the real dotfiles, symlinked from `$HOME`: `.claude`, `.claude-work`, `.codex`, `.pi`, `.zprofile`, `.zshrc`. Only the config worth versioning is tracked; runtime state (sessions, caches, credentials) stays untracked.
- `hooks/` — rm guards: `prevent-rm.py` (Claude and Codex PreToolUse hook) and `prevent-rm-pi.ts` (Pi extension) block `rm` and point agents at `trash`.
- `bin/` — shims prepended to agents' PATH; `bin/rm` refuses to run as a last line of defense.
- `skills/` — Claude skills, local-only (untracked); `home/.claude/skills` symlinks here.
- `pi-for-claude/` — submodule: the Pi delegation wrapper.
- `secrets.env` — API keys agents may use, sourced by `.zprofile`. Never committed.
- `migrate-agent-config-repo.sh` — the one-shot script that converted the original bare-repo setup into this layout.

## How tracking works

`.gitignore` is deny-all (`*`): nothing is tracked unless explicitly added with `git add -f`. This makes leaking runtime state or credentials into the repo an opt-in mistake rather than a default one. The flip side: `git add` on new files silently no-ops without `-f`, and already-tracked files need `git add -u`.

`home/.codex/config.toml` runs through a clean filter (`clean-codex-config.py`, wired in `.gitattributes`) that strips the machine-generated `[projects]` trust entries and marketplace timestamps Codex appends — activity history that must not be committed. The filter driver is per-clone git config; without it the file stages verbatim, so run the setup line below after cloning.

## Setup on a new machine

```sh
git clone --recurse-submodules https://github.com/ahalekelly/agent-config.git ~/.agents
git -C ~/.agents config filter.codex-config.clean 'uv run "$HOME/.agents/clean-codex-config.py"'
for f in .claude .claude-work .codex .pi .zprofile .zshrc; do ln -s ~/.agents/home/$f ~/$f; done
```

Then create `~/.agents/secrets.env` (agent-safe keys) and `~/.secrets.env` (keys agents must not see — the `claude`/`codex`/`pi` wrappers in `.zshrc` scrub these from the environment, and `.zprofile` only sources them in real user terminals).

## Two Claude profiles

`home/.claude-work` is a second Claude Code profile (work account) that symlinks everything except login state back into `home/.claude`. See `home/.claude/second-profile-setup.md`.
