# agent-config

Versioned configuration for the coding agents on this machine: Claude Code, Codex, and Pi. The repo lives at `~/.agents`, and the agent dotfiles in `$HOME` are symlinks into it.

## Layout

- `AGENTS.md` — shared instructions for all agents. Claude loads it via `@` from its CLAUDE.md; Codex and Pi read it through symlinks (`home/.codex/AGENTS.md`, `home/.pi/agent/AGENTS.md`).
- `home/` — the real dotfiles (macOS), symlinked from `$HOME`: `.claude`, `.claude-work`, `.codex`, `.pi`, `.zprofile`, `.zshrc`. Only the config worth versioning is tracked; runtime state (sessions, caches, credentials) stays untracked.
- `home-windows/` — the Windows equivalent of `home/`: `.claude` and `.codex`, junction-linked from `$HOME`. The statusline is `statusline.py` there (the shell version needs jq).
- `home-linux/` — the Linux equivalent: `.claude` (a Linux `settings.json` and `CLAUDE.md`; skills, statusline, and output styles symlink back into `home/`) plus `.bashrc.agents`, the bash port of the `.zshrc` agent wrappers, sourced from `~/.bashrc`.
- `hooks/` — rm guards: `prevent-rm.py` (Claude and Codex PreToolUse hook) and `prevent-rm-pi.ts` (Pi extension) block `rm` and point agents at `trash`; `allow-mcp.py` auto-allows MCP tools from Claude's PreToolUse.
- `bin/` — shims prepended to agents' PATH; `bin/rm` refuses to run as a last line of defense.
- `skills/` — Claude skills, all tracked (third-party ones are vendored, with source and hash pinned in `.skill-lock.json`); `home/.claude/skills` symlinks here.
- `pi-for-claude/` — submodule: the Pi delegation wrapper.
- `secrets.env` — API keys agents may use, sourced by `.zprofile`. Never committed.
- `migrate-agent-config-repo.sh` — the one-shot script that converted the original bare-repo setup into this layout.

## How tracking works

The root `.gitignore` is a normal deny-list: everything is tracked by default except dependencies, logs, and agent runtime state. The exception is `home/`, `home-windows/`, and `home-linux/` — the live runtime dirs (`~/.claude` etc.) symlink or junction into them, so each carries its own deny-all (`*`) `.gitignore`, making leaking runtime state or credentials an opt-in mistake rather than a default one. Inside those folders, new curated config files must be added with `git add -f`, and `git add` on an already-tracked file exits nonzero with an ignore warning (while still staging) — use `git add -u` for tracked changes there. Everywhere else, git behaves normally.

`home/.codex/config.toml` runs through a clean filter (`clean-codex-config.py`, wired in `.gitattributes`) that strips the machine-generated `[projects]` trust entries and marketplace timestamps Codex appends — activity history that must not be committed. The filter driver is per-clone git config; the setup lines below configure it and mark it required, so a clone missing the filter fails loudly instead of staging the file verbatim.

## History

The repo's history is continuous through the bare-repo-to-normal-repo conversion (2026-07-11, `b8c99d9a`); commits before it use the old dotfile layout (`.claude/…`, `.codex/…`, `.agents/pi-run/…`), so `git log --follow` doesn't track files across the conversion. The exception is `pi-for-claude/`, which was split into its own repository at the conversion: the submodule's history starts there, and its earlier history is the `.agents/pi-run/` commits here.

The bare repo `~/Git/agent-config.git.before-normal-repo-20260711-233133` (local only, never pushed) archives the history-rewrite work from the day of the conversion: refs `bak1`/`bak2` are intermediate rewrite stages, plus reflogs and a dangling pre-rewrite tip. `bak1` holds the only copy of `.agents/advisor-protocol.md`, the advisor-tool protocol extracted verbatim from the Claude Code binary.

## Setup on a new machine

```sh
git clone --recurse-submodules https://github.com/ahalekelly/agent-config.git ~/.agents
git -C ~/.agents config filter.codex-config.clean 'uv run "$HOME/.agents/clean-codex-config.py"'
git -C ~/.agents config filter.codex-config.required true
for f in .claude .claude-work .codex .pi .zprofile .zshrc; do ln -s ~/.agents/home/$f ~/$f; done
(cd ~/.agents/pi-for-claude && npm install && npm link)   # builds dist/ and puts pi-for-claude on PATH
pi-for-claude setup
```

Then create `~/.agents/secrets.env` (agent-safe keys) and `~/.secrets.env` (keys agents must not see — the `claude`/`codex`/`pi` wrappers in `.zshrc` scrub these from the environment, and `.zprofile` only sources them in real user terminals).

## Setup on a new Windows machine

Requires Developer Mode (for native symlinks), git, uv, and node. In PowerShell, with Claude Code and Codex not running:

```powershell
git clone -c core.symlinks=true https://github.com/ahalekelly/agent-config.git "$env:USERPROFILE\.agents"
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.agents\setup-windows.ps1"
npm install -g trash-cli
```

`setup-windows.ps1` configures the clean filter, then swaps `~\.claude` and `~\.codex` to junctions into `home-windows\`, moving any existing runtime state into the repo (kept untracked by `home-windows/`'s deny-all `.gitignore`; pre-existing config files are preserved as `*.pre-agents-repo`). Pi, the second Claude profile, and the zsh secrets-scrubbing wrappers are macOS-only and not set up on Windows. Syncing is manual: `git -C $env:USERPROFILE\.agents` add/commit/pull/push as needed.

## Setup on a new Linux machine

Requires git, uv, node, and jq (`trash-cli` is installed from npm by the script). With Claude Code not running:

```sh
git clone --recurse-submodules https://github.com/ahalekelly/agent-config.git ~/.agents
bash ~/.agents/setup-linux.sh
(cd ~/.agents/pi-for-claude && npm install && npm link) && pi-for-claude setup
```

`setup-linux.sh` configures the clean filter, swaps `~/.claude` to a symlink into `home-linux/.claude` (moving existing runtime state into the repo, pre-existing config files kept as `*.pre-agents-repo`), links the global git ignore, and adds a line to `~/.bashrc` that sources `home-linux/.bashrc.agents`. Codex, the second Claude profile, and claude-patching are not set up on Linux.

It also installs Claude Remote Control as a systemd user service (`home-linux/.config/systemd/user/claude-remote-control.service`, serving `~/Git`, stdout discarded and stderr in the journal), enables linger so it runs at boot, and sets up sandboxing for remote sessions: `socat`, plus on Ubuntu the `home-linux/apparmor.d/bwrap` AppArmor profile, which replaces the stock `bwrap-userns-restrict` so bwrap can create the nested user namespaces Claude's sandbox needs. The service starts only after two interactive one-offs: `claude` in `~/Git` to accept the trust dialog, and `claude remote-control` to accept its enable prompt (with stdin at `/dev/null` it otherwise exits silently in a restart loop). Manage with `systemctl --user {status,restart} claude-remote-control`; to see the TUI output during debugging, set `StandardOutput=journal` temporarily.

## Two Claude profiles

`home/.claude-work` is a second Claude Code profile (work account) that symlinks everything except login state back into `home/.claude`. See `home/.claude/second-profile-setup.md`.
