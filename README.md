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

Sync installs a job that runs every 10 minutes: a systemd user timer on Linux, a launchd agent on macOS, or a Windows scheduled task while logged in. It commits edits and new files, merges upstream changes, pushes, and installs the config. Git-ignored files stay local. Submodule repositories sync first, then their revisions enter the config repo. Auto-sync runs on each repository's default branch and stops on conflicts or unfinished Git operations; resolve those before the next run. Restart open shells after shell config changes.

Claude and Pi config files are links. If a tool replaces one with a regular file, sync prints its diff and stops. Move the changes into the named repo file, remove the generated file, and rerun sync.

Matt Pocock's skills update from `mattpocock/skills` on every sync. The upstream checkout lives in `skills/.mattpocock/`, outside version control; links in `skills/` expose its skills to all agents. Keep upstream files unmodified so updates can fast-forward.

Codex needs a rendered file, so sync deep-merges `codex/config.toml` with `codex/config.<os>.toml`. It compares the shared part of the live config with `~/.codex/config.toml.rendered`, or with the fresh render on a machine that has none, so an existing Codex config survives the first sync. Changed keys enter the OS overlay and keys Codex removed leave it; the shared base changes only by hand. Project trust, hook trust hashes, marketplace timestamps, and reasoning effort stay only in the live file and are never imported.

`claude/settings.json` holds only portable settings. Machine-specific ones go in `~/.claude/settings.local.json`, which Claude Code layers on top: sync writes `processWrapper` there on Linux and macOS, and hooks for tools installed on one machine (Herdr's session-start hook on akelly-desktop) belong there too.

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

On macOS, sync also links `.zshrc`, `.zprofile`, and the iTerm2 dynamic profile. On Windows, rerun sync after enabling Developer Mode if symlink creation fails, and install `jq` (`winget install jqlang.jq`) for the prompt hooks. Windows paths and native Codex settings live in `codex/config.windows.toml`.

The `claudew` launcher (`bin/claudew`) uses `~/.claude-work` for a second account while sharing config and runtime data with the personal profile. See `claude/second-profile-setup.md`.

## History

The repo's history is continuous through the bare-repo-to-normal-repo conversion (2026-07-11, `b8c99d9a`); commits before it use the old dotfile layout (`.claude/…`, `.codex/…`, `.agents/pi-run/…`), so `git log --follow` doesn't track files across the conversion. The exception is `pi-for-claude/`, which was split into its own repository at the conversion: the submodule's history starts there, and its earlier history is the `.agents/pi-run/` commits here.

The bare repo `~/Git/agent-config.git.before-normal-repo-20260711-233133` (local only, never pushed) archives the history-rewrite work from the day of the conversion: refs `bak1`/`bak2` are intermediate rewrite stages, plus reflogs and a dangling pre-rewrite tip. `bak1` holds the only copy of `.agents/advisor-protocol.md`, the advisor-tool protocol extracted verbatim from the Claude Code binary.
