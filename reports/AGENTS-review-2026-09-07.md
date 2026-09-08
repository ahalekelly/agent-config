# AGENTS.md review — 2026-09-07 17:48 PDT

Seven actionable findings. `AGENTS.md` and project files were left unchanged. Checks covered the document, local configuration and source files, and selected commands on `akelly-desktop`. Windows-specific claims were not verified on a Windows machine.

## 1. Automatic sync conflicts with commit ownership rules

[AGENTS.md:98](/Users/akelly/.agents/AGENTS.md:98) says not to commit files containing another person's edits without approval, or unfinished work. However, the installed Mac job runs `sync.py pull` every 600 seconds. [sync.py:351](/Users/akelly/.agents/sync.py:351) stages **all** changes, commits, and pushes without those checks. During this conversation, it committed the instruction edit and an unrelated Codex setting together.

**Suggested resolution:** Decide whether this configuration repo is exempt from the commit rules or whether automatic publication should change. Merely telling agents to leave files uncommitted does not protect them from this job.

## 2. The file-search command is Linux-specific but required globally

[AGENTS.md:84](/Users/akelly/.agents/AGENTS.md:84) requires `plocate` and `updatedb` “anywhere on the machine.” Neither command resolves on this Mac; both resolve on `akelly-desktop`.

**Suggested correction:** Move those commands into the Linux section and provide a Mac-specific search instruction.

## 3. The T3 resume example cannot run directly as shown

[AGENTS.md:60](/Users/akelly/.agents/AGENTS.md:60) uses `uv run ~/.agents/bin/t3-thread.py new ...` but switches to bare `t3-thread.py resume ...`. The script is in `~/.agents/bin`, and its first line is a PEP 723 metadata comment, not an executable shebang. This was verified in both the local and Linux copies.

**Suggested correction:** Use `uv run ~/.agents/bin/t3-thread.py resume <thread-id> <prompt-file>`.

## 4. The shared bug workflow requires an unavailable model

[AGENTS.md:120](/Users/akelly/.agents/AGENTS.md:120) requires a Fable subagent; line 122 refers to “the model routing rules.” This Codex session has no Fable model option, and the routing rules are in [claude/CLAUDE.md:33](/Users/akelly/.agents/claude/CLAUDE.md:33), rather than the shared instructions.

**Suggested correction:** Describe the investigation responsibility in shared instructions and keep the Fable model assignment in Claude-specific instructions.

## 5. Shared instructions name a Claude-specific sandbox parameter

[AGENTS.md:56](/Users/akelly/.agents/AGENTS.md:56) twice prescribes `dangerouslyDisableSandbox`. This session's execution tool instead accepts `sandbox_permissions: "require_escalated"`; it has no `dangerouslyDisableSandbox` parameter.

**Suggested correction:** Say to request execution outside the sandbox using the runtime's supported mechanism. Put exact tool parameters in runtime-specific instructions.

## 6. The Mac section heading disagrees with the hostname rule

[AGENTS.md:52](/Users/akelly/.agents/AGENTS.md:52) says to identify the machine by hostname, but the Mac section is headed `adrians-macbook-air`. Running `hostname` returns `Mac.local`, which line 58 also identifies as the Mac's local hostname.

**Suggested correction:** Rename the heading to `Mac.local (macOS)`.

## 7. The documentation-update rule contradicts itself

[AGENTS.md:102](/Users/akelly/.agents/AGENTS.md:102) requires updating docs for “committed or untracked changes,” then says updates are unnecessary for “uncommitted changes.” Untracked files are also uncommitted, so both instructions apply to the same case.

**Suggested correction:** If the distinction is intentional, change the second phrase to “uncommitted changes to tracked files.” Otherwise, choose one rule for all uncommitted work.
