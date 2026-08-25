# Agent environment configuration

This repository is the source of truth for Adrian's Claude Code, Codex, Pi, shell, skill, and Git configuration across macOS, Linux, and Windows. Credentials, sessions, caches, and other runtime state stay in real directories under `$HOME`, outside the repo.

## Installation model

`sync.py` links static files from `claude/`, `pi/`, `skills/`, `hooks/`, and `shell/` into each tool's runtime directory. It also recreates the work Claude profile's links to shared personal-profile state. `AGENTS.md` supplies common instructions; `claude/CLAUDE.md` adds Claude-specific guidance.

Codex config cannot be linked because Codex edits it. Sync deep-merges `codex/config.toml` with the current OS overlay into `~/.codex/config.toml`, recording the result at `~/.codex/config.toml.rendered`. On later runs, changed or added live keys move into the shared base before rendering. Project trust records and marketplace timestamps remain machine state.

## Security boundaries

- `~/.agents/secrets.env` contains keys agents may use.
- `~/.secrets.env` contains keys shell launchers remove before starting agents.
- `hooks/` and `bin/rm` reject direct `rm` use in favor of recoverable deletion through `trash`.
- `shell/gitignore-global` excludes common agent runtime directories inside projects.

## Components

- Claude uses sandbox permissions, an `rm` hook, shared skills, a Python status line, and terminal tab-state hooks.
- The `claude` and `claudew` launchers select separate account identities while sharing configuration and project state.
- Codex uses a workspace-write sandbox, local MCP servers, plugins, desktop settings where available, and the shared `rm` hook.
- Pi stores project sessions under `.agents/sessions` and loads `hooks/prevent-rm-pi.ts` as an extension.
- `pi-for-claude` manages delegated Pi sessions and worktrees.

See [README.md](README.md) for setup and syncing commands.
