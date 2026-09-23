# agent-config

Versioned configuration for Claude Code, Codex, and Pi. The repo lives at `~/.agents`. Agent runtime directories under `$HOME` stay real; `sync.py` links individual config files into them.

## Layout

- `AGENTS.md` — shared instructions for every agent.
- `claude/`, `codex/`, `pi/` — tool configuration. Codex has a shared base plus one OS overlay.
- `uv/`, `pnpm/` — package manager configuration.
- `shell/` — shell startup files and the global git ignore.
- `linux/`, `macos/` — OS-specific service and application files.
- `hooks/`, `bin/`, `skills/` — shared hooks, command guards, and skills. `bin/t3-thread.py` sends prompts to the local T3 service.
- `sync.py` — cross-platform config installer.
- `pi-for-claude/`, `browser-swarm/` — submodules.

Runtime state, credentials, caches, and `~/.codex/config.toml.rendered` remain outside the repo.

## Syncing

Edit the source under `claude/`, `codex/`, or `pi/`, then run:

```sh
uv run ~/.agents/sync.py
```

Sync installs a job that runs every 10 minutes: a systemd user timer on Linux, a launchd agent on macOS, or a Windows scheduled task while logged in. It commits edits and new files, merges upstream changes, pushes, and installs the config. Git-ignored files stay local. Submodule repositories sync first, then their revisions enter the config repo. Auto-sync runs on each repository's default branch and stops on conflicts or unfinished Git operations; resolve those before the next run. A pulled change to `sync.py` itself takes effect on the following run. Restart open shells after shell config changes.

Sync also quarantines fresh package releases: uv, npm, and pnpm refuse versions published in the last 3 days, configured through `uv/uv.toml`, `pnpm/config.yaml`, and `~/.npmrc`. Tools updated on purpose, such as Codex and Claude Code, are exempt by name; their dependencies are not. npm 11.15 or newer is required.

Claude and Pi config files are links. If a tool replaces one with a regular file, sync prints its diff and stops. Move the changes into the named repo file, remove the generated file, and rerun sync.

Matt Pocock's skills update from `mattpocock/skills` on every sync. The upstream checkout lives in `skills/.mattpocock/`, outside version control; links in `skills/` expose its skills to all agents; to leave one out, add its name to `SKIPPED_UPSTREAM_SKILLS` in `sync.py`. Keep upstream files unmodified so updates can fast-forward.

Codex needs a rendered file, so sync deep-merges `codex/config.toml` with `codex/config.<os>.toml`. It compares the shared part of the live config with `~/.codex/config.toml.rendered`, or with the fresh render on a machine that has none, so an existing Codex config survives the first sync. Changed keys enter the OS overlay and keys Codex removed leave it; the shared base changes only by hand. Project trust, hook trust hashes, marketplace timestamps, and reasoning effort stay only in the live file and are never imported. Linux and macOS Codex commands use `/tmp/uv-cache-akelly` for uv caching so workspace sandboxes can write to it; temporary-file cleanup may evict cached packages.

`claude/settings.json` holds only portable settings. Machine-specific ones go in `~/.claude/settings.local.json`, which Claude Code layers on top: sync writes `processWrapper` there on Linux and macOS so background sessions load the tweaks mod through `bin/claude-process-wrapper`, and hooks for tools installed on one machine (Herdr's session-start hook on akelly-desktop) belong there too. Sandbox filesystem rules are the exception: Claude Code ignores `sandbox` in the local file, so machine-specific entries such as akelly-desktop's NTFS mounts in `denyRead` live in `claude/settings.json`; the sandbox skips paths that don't exist on a machine.

`codex/model-instructions.md` replaces Codex's base prompt for all models. It uses the GPT-6-Astra template with file-link formatting delegated to the user's machine-specific instructions. Maintain this prompt manually; model catalog updates do not refresh it. Start a new session after editing it.

## Setup

Requires git and [uv](https://docs.astral.sh/uv/). Windows also requires Developer Mode for symlinks.

```sh
git clone --recurse-submodules https://github.com/ahalekelly/agent-config.git ~/.agents
uv run ~/.agents/sync.py
(cd ~/.agents/pi-for-claude && npm install && npm link)
pi-for-claude setup
```

Create `~/.agents/secrets.env` for keys agents may use and `~/.secrets.env` for keys agents must not see. The shell wrappers scrub the latter from agent processes.

On Debian/Ubuntu with systemd, run the system setup after sync:

```sh
bash ~/.agents/linux/setup.sh
```

It installs the sandbox and trash dependencies, configures AppArmor for Bubblewrap and cached Chromium, enables the Claude Remote Control user unit, enables linger, and sources `shell/bashrc.agents` from `~/.bashrc`. Run `claude` once in `~/Git` to accept trust, then `claude remote-control` once to enable remote control.

The browser AppArmor rule covers the current user's standard agent-browser, Playwright, and Puppeteer caches. Custom browser locations need a matching rule. On Linux ARM64, install Chromium through the system package manager.

On macOS, sync also links `.zshrc`, `.zprofile`, and the iTerm2 dynamic profile. The `com.akelly.t3-keepalive` launch agent reopens T3 Code after it quits and hides its startup window; existing windows stay untouched. It requires Xcode command-line tools. Logs are in `~/Library/Logs/t3-keepalive.log`. Stop it with `launchctl bootout gui/$(id -u)/com.akelly.t3-keepalive`; running sync installs it again.

On Windows, rerun sync after enabling Developer Mode if symlink creation fails, and install `jq` (`winget install jqlang.jq`) for the prompt hooks. Windows paths and native Codex settings live in `codex/config.windows.toml`. The `T3 keepalive` scheduled task reopens T3 Code after it quits and minimizes its startup window; existing windows stay untouched. Logs are in `%LOCALAPPDATA%\t3-keepalive\t3-keepalive.log`. Stop it with `schtasks /Delete /TN "T3 keepalive" /F`, then end the watcher, which outlives the task: `Get-CimInstance Win32_Process -Filter "CommandLine LIKE '%t3-keepalive.py%'" | Invoke-CimMethod -MethodName Terminate`. Running sync installs it again.

Every Claude Code launch, terminal or T3 Code, goes through `bin/claude-launch`, which takes its account from `CLAUDE_CODE_OAUTH_TOKEN` and `CLAUDE_PROFILE` in the environment. The `claude` and `claudew` shell functions export them from the gitignored `~/.agents/claude-token.env` and `~/.agents/claudew-token.env`, each owner-readable only and holding a one-year `CLAUDE_CODE_OAUTH_TOKEN` from `command claude setup-token` plus `CLAUDE_PROFILE=personal` or `work`, so no session depends on a refreshable login. A T3 Code provider points at the absolute `~/.agents/bin/claude-launch` with an empty home path and sets both variables under Environment variables, the token marked sensitive. Every session shares `~/.claude`, so `CLAUDE_CONFIG_DIR` is never set. Token sessions can't use claude.ai connectors or Remote Control, and the weekly usage lines in prompt context come from the login stored in `~/.claude`, so they appear only in personal sessions.

Autodesk Fusion's local MCP endpoint is configured in the Codex macOS overlay. Enable it in Fusion under Preferences > General > API and keep Fusion running. Register it globally in Claude Code with `claude mcp add --transport http --scope user fusion http://127.0.0.1:27182/mcp`.

Gmail comes from Google's Gmail MCP server (search, read, label, create drafts; no send or draft editing). It needs a Google Cloud project with the Gmail API and Gmail MCP API enabled, an OAuth consent screen with the `gmail.readonly` and `gmail.compose` scopes, and a Web application OAuth client whose redirect URI is `http://localhost:8080/callback`. Register it per machine, then authorize with `/mcp` in an interactive session:

```bash
claude mcp add-json --scope user gmail '{"type":"http","url":"https://gmailmcp.googleapis.com/mcp/v1","oauth":{"clientId":"<client id>","callbackPort":8080}}' --client-secret
```

## History

The repo's history is continuous through the bare-repo-to-normal-repo conversion (2026-07-11, `b8c99d9a`); commits before it use the old dotfile layout (`.claude/…`, `.codex/…`, `.agents/pi-run/…`), so `git log --follow` doesn't track files across the conversion. The exception is `pi-for-claude/`, which was split into its own repository at the conversion: the submodule's history starts there, and its earlier history is the `.agents/pi-run/` commits here.

The bare repo `~/Git/agent-config.git.before-normal-repo-20260711-233133` (local only, never pushed) archives the history-rewrite work from the day of the conversion: refs `bak1`/`bak2` are intermediate rewrite stages, plus reflogs and a dangling pre-rewrite tip. `bak1` holds the only copy of `.agents/advisor-protocol.md`, the advisor-tool protocol extracted verbatim from the Claude Code binary.
