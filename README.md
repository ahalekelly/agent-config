# agent-config

Versioned configuration for Claude Code, Codex, and Pi. The repo lives at `~/.agents`. Agent runtime directories under `$HOME` stay real; `sync.py` links individual config files into them.

## Layout

- `AGENTS.md` — shared instructions for every agent.
- `claude/`, `codex/`, `pi/` — tool configuration. Codex has a shared base plus one OS overlay.
- `shell/` — shell startup files and the global git ignore.
- `linux/`, `macos/` — OS-specific service and application files.
- `hooks/`, `bin/`, `skills/` — shared hooks, command guards, and skills.
- `sync.py` — cross-platform config installer.
- `pi-for-claude/`, `claude-patching/`, `browser-swarm/` — submodules.

Runtime state, credentials, caches, and `~/.codex/config.toml.rendered` remain outside the repo.

## Syncing

Edit the source under `claude/`, `codex/`, or `pi/`, then run:

```sh
uv run ~/.agents/sync.py
```

Commit and push the repo changes. On another machine, pull and run the same command. Restart open shells after shell config changes.

Claude and Pi config files are links. If a tool replaces one with a regular file, sync prints its diff and stops. Move the changes into the named repo file, remove the generated file, and rerun sync.

Codex needs a rendered file, so sync deep-merges `codex/config.toml` with `codex/config.<os>.toml`. It compares the live config with `~/.codex/config.toml.rendered`; Codex-added or changed keys move into the shared base and appear in `git status`. Move platform-specific imports into the relevant overlay before committing. Project trust entries, marketplace refresh timestamps, and the machine-local model reasoning preference are not imported.

## Setup

Requires git and [uv](https://docs.astral.sh/uv/). Windows also requires Developer Mode for symlinks.

```sh
git clone --recurse-submodules https://github.com/ahalekelly/agent-config.git ~/.agents
uv run ~/.agents/sync.py
(cd ~/.agents/pi-for-claude && npm install && npm link)
pi-for-claude setup
```

Create `~/.agents/secrets.env` for keys agents may use and `~/.secrets.env` for keys agents must not see. The shell wrappers scrub the latter from agent processes.

On Linux, run the system setup after sync:

```sh
bash ~/.agents/linux/setup.sh
```

It installs the sandbox and trash dependencies, configures AppArmor when needed, enables the Claude Remote Control and claude-patching autoport user units, enables linger, and sources `shell/bashrc.agents` from `~/.bashrc`. Install claude-patching's dependency with `(cd ~/.agents/claude-patching && npm ci)`. Run `claude` once in `~/Git` to accept trust, then `claude remote-control` once to enable remote control.

On macOS, sync also links `.zshrc`, `.zprofile`, and the iTerm2 dynamic profile. On Windows, rerun sync after enabling Developer Mode if symlink creation fails. Windows paths and native Codex settings live in `codex/config.windows.toml`.

The `claudew` shell function uses `~/.claude-work` for a second account while sharing config and runtime data with the personal profile. See `claude/second-profile-setup.md`.

## History

The repo's history is continuous through the bare-repo-to-normal-repo conversion (2026-07-11, `b8c99d9a`); commits before it use the old dotfile layout (`.claude/…`, `.codex/…`, `.agents/pi-run/…`), so `git log --follow` doesn't track files across the conversion. The exception is `pi-for-claude/`, which was split into its own repository at the conversion: the submodule's history starts there, and its earlier history is the `.agents/pi-run/` commits here.

The bare repo `~/Git/agent-config.git.before-normal-repo-20260711-233133` (local only, never pushed) archives the history-rewrite work from the day of the conversion: refs `bak1`/`bak2` are intermediate rewrite stages, plus reflogs and a dangling pre-rewrite tip. `bak1` holds the only copy of `.agents/advisor-protocol.md`, the advisor-tool protocol extracted verbatim from the Claude Code binary.
