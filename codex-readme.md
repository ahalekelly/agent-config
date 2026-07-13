# Agent environment configuration

This repository is the versioned source of truth for a personal AI-agent environment on macOS. It keeps selected Claude Code, Codex, Pi, shell, skill, and Git configuration together under `~/.agents`, while leaving credentials, conversations, caches, databases, and other runtime state untracked.

It is a machine-specific configuration repository rather than a portable dotfiles package. Several settings contain absolute paths, local MCP server locations, installed application paths, model choices, and plugin state for this machine.

## How the layout works

The `home/` directory contains files intended to back their corresponding paths in the real home directory:

```text
~/.agents/
├── AGENTS.md                 shared instructions for coding agents
├── home/
│   ├── .claude/              Claude Code configuration and UI hooks
│   ├── .claude-work/         second Claude account sharing the main profile
│   ├── .codex/               Codex configuration
│   ├── .pi/                  Pi configuration
│   ├── .config/git/ignore    global Git exclusions for agent runtime files
│   ├── .zprofile             environment and secret loading
│   └── .zshrc                agent launchers and shell aliases
├── hooks/                    command guards shared by agent harnesses
├── bin/rm                    PATH-level guard against destructive deletion
├── clean-codex-config.py     Git clean filter for generated Codex settings
├── skills/                   installed skills, ignored by Git
├── .skill-lock.json          tracked skill provenance and versions
└── pi-for-claude/            Git submodule for Claude-to-Pi delegation
```

The main Claude, Codex, and Pi instruction files converge on `AGENTS.md`, so the agents receive the same code style, secret-handling, and workflow policy. Claude also has tool-specific instructions in `home/.claude/CLAUDE.md`.

## What is versioned

The root `.gitignore` ignores everything except the ignore file itself. Files become part of the repository only when deliberately added with `git add -f`. This makes the tracked set an explicit allowlist and prevents newly generated agent state from appearing as ordinary untracked files.

The important tracked areas are:

- `AGENTS.md`: shared operating policy for agents.
- `home/.claude/settings.json`: Claude permissions, sandbox access, hooks, plugins, status line, and model settings.
- `home/.codex/config.toml`: Codex models, permissions, sandbox rules, MCP servers, plugins, desktop behavior, and hooks.
- `home/.pi/agent/settings.json`: Pi models, packages, session location, and extensions.
- `home/.zprofile` and `home/.zshrc`: environment setup, agent launchers, profile selection, and secret scrubbing.
- `hooks/` and `bin/rm`: overlapping guards that reject `rm` and direct agents to use recoverable deletion through `trash`.
- `.skill-lock.json`: the source and content identity of installed third-party skills. The installed `skills/` tree remains ignored.
- `pi-for-claude`: a pinned submodule that lets Claude delegate implementation, review, and related work to Pi in isolated worktrees or in place.

Everything else under the managed application directories should be assumed to be runtime state unless it has been explicitly force-added.

## Secrets and generated state

Secrets are intentionally outside Git:

- `~/.agents/secrets.env` contains keys that agent processes may use.
- `~/.secrets.env` contains sensitive keys that must not reach agents.

The shell launchers remove variables named in `~/.secrets.env` before starting Claude or Codex. Agent contexts load `~/.agents/secrets.env`; normal interactive terminals may additionally load `~/.secrets.env`.

Authentication files, session transcripts, project history, caches, downloads, SQLite databases, plugin caches, and similar application-created data live beside the tracked configuration but remain ignored. The global Git ignore file also excludes `.agents/sessions/`, `.agents/plans/`, and `.agents/worktrees/` when agent tools create them inside project repositories.

## Agent-specific behavior

### Claude Code

Claude uses a sandbox with selected network and filesystem access. A pre-tool hook blocks shell commands that invoke `rm`, while terminal hooks maintain a compact status line and tab-state indicator.

The `claude` launcher selects the personal profile. `claudew` selects `home/.claude-work`, whose tracked entries are symlinks back to the main Claude profile. This shares settings, skills, plugins, history, and project state while leaving account identity and login state separate and untracked.

The `claudex` and `claudef` launchers route selected Claude sessions through a locally running CLIProxyAPI service.

### Codex

Codex is configured for a workspace-write sandbox with explicit host reads and writable workspace roots. Its configuration also registers local MCP servers, bundled artifact and browser plugins, desktop preferences, and the shared `rm` guard.

Codex writes project trust records and marketplace refresh timestamps into `config.toml`. The `codex-config` Git clean filter removes those generated fields from staged content. Every clone must configure the filter before committing Codex configuration:

```sh
git -C ~/.agents config filter.codex-config.clean 'uv run "$HOME/.agents/clean-codex-config.py"'
git -C ~/.agents config filter.codex-config.required true
```

### Pi and `pi-for-claude`

Pi stores project sessions under `.agents/sessions` and loads the shared deletion guard as an extension. The `pi-for-claude` submodule adds a command layer for starting, resuming, reviewing, inspecting, merging, and discarding delegated Pi sessions. It records session metadata and creates worktrees beneath each project's `.agents/` directory.

The submodule is a Node.js and TypeScript project. After cloning or updating it, install and verify it from its directory:

```sh
git -C ~/.agents submodule update --init
cd ~/.agents/pi-for-claude
npm ci
npm run typecheck
npm test
npm run build
```

## Routine maintenance

Inspect changes through the repository rather than from the managed home paths:

```sh
git -C ~/.agents status
git -C ~/.agents diff
```

Because the repository ignores new files by default, add a new configuration file deliberately:

```sh
git -C ~/.agents add -f path/to/file
```

Tracked files can be staged normally after their first commit. Update the submodule independently, then commit the new submodule pointer in this repository. Treat changes to shell secret handling, sandbox permissions, authentication paths, and deletion guards as security-sensitive.

`migrate-agent-config-repo.sh` is a one-time migration utility for converting an older bare `~/Git/agent-config.git` setup into this normal repository layout. It validates that exact source layout and moves live configuration, so it is not a general installation or update command.
