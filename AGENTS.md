Hi I'm Adrian Kelly, welcome to my computer

## Writing Style

Cut Unnecessary Words: Don't add any words that are not essential to the meaning.
Use Active Voice: Favor the active voice over the passive voice.
Use Simple Language: Opt for everyday English over jargon or scientific terms.

## Code Style

Do not preserve backward compatibility. Remove obsolete paths instead of adding compatibility layers, fallbacks, or migrations.
Choose the simplest implementation that fully meets the current requirements. Avoid speculative abstractions, configuration, and indirection.
Grow the system in layers. Start from the smallest version that works end to end, and add each new capability on top of a product that already works.
Keep components modular and concerns clearly separated.
Prefer established, well-maintained libraries when they reduce overall complexity or improve reliability. Do not reimplement common functionality without a clear reason.
Lean on the dependencies already in the project before writing your own implementation or adding packages. Do not assume a library lacks a capability without checking its documentation and types.
Make architectural decisions for the long term. Do not accept a stopgap that only works for now and is meant to be replaced later.

Write skimmable code — optimize for how easy it is to read.
Minimize possible states: fewer arguments, narrower state, required values instead of optional ones. Don't add optional arguments or overrides unless strictly necessary.
Don't write defensive code, assume values are what their types say. Verify data where it's loaded or passed in and raise errors if it's incorrect — use "if: raise" instead of try/catch or default values when you expect something to exist.
Don't break code into too many functions, that's hard to read.
In our projects, bias for fewer total lines of code instead of minimizing the size of the diff. When you refactor or remove some functionality, also remove any dead code created by that change. Code and docs should reflect the intended end state, not the historical path that produced the current implementation. Optimize for the code that should exist, not the smallest diff from the old shape. Do not invent a generic framework for one feature. Prefer names that describe product intent over implementation history.
Don't create workarounds for code that's in a project we own. If adding the new functionality properly via a refactor would reduce complexity and total LOC across our projects, do the refactor.

When writing code to contribute to other people's open source projects, keep the diff size small. Ask me for each project whether we're contributing upstream or not and note that in your memory.

If things aren't working they should fail loudly with clear error messages. Fallback paths are almost always unnecessary extra code: they make functionality harder to reason about and hide errors that need to be fixed.

Documentation and code comments should be timeless, imagine you're writing them for someone reading a year from now. No breadcrumbs: docs shouldn't mention, refer to, or imply previous versions of the code, except in a specific high-level project changelog. Code comments should only mention code changes if they are warning about specific mistakes to avoid.

Timeless also means independent of the conversation that produced the edit: answer my question in your reply, and write the doc from the document's own point of view, stating facts positively rather than as responses ("the scope of X is ..." not "there is no separate definition of X"). Test: would the text make sense if it had always been in the doc?

Reports are different: they're an explanation for the user to read immediately after creation, a point-in-time snapshot, and don't have to be timeless. Put the datetime in a report's title — it marks the content as frozen at that date, so any future reader knows current docs win on conflict. If a report needs updating, it has become a living doc — drop the date from the title and record `created:` and `verified:` (last fact-checked) as frontmatter properties instead. Git preserves history, so delete or consolidate superseded reports rather than curating them. Keep reports in a `reports/` subfolder beside the project's living docs, so a project folder shows only maintained docs.

When creating Markdown files in greenfield projects, don't hard-wrap with newlines; the markdown viewer's soft wrapping is preferred.

My requests are approximate. I am not the one coding; you are. My directions are pointers toward what I actually want -- the simplest, cleanest, most elegant design -- and they may be slightly off. That goal ALWAYS outranks my literal words.

So when you hit a wall -- a case that doesn't fit, a spec that breaks, an assumption that fails -- the wall is information: the design is wrong somewhere. STOP. Re-derive the design from first principles until the wall does not exist. If the result diverges from my spec, diverging is your duty: present it to me.

What you must never do is patch around the wall to comply with my words: a flag, a special case, a conversion shim, a second channel, a parallel path, a test rewritten to dodge a broken rule. The patch IS the failure. Every duct-tape betrays my intent while pretending to honor it, and it will be rejected -- 100% of the time, regardless of cost already sunk. A blocker honestly reported is a good outcome; a "working" deliverable built on gambiarra is the worst possible one, and is treated as sabotage.

If you find a bug in one place in the code, look for other places where that same class of bug could have occurred. More generally, whenever you learn something surprising, like finding a bug, think about what that tells you about the state of the codebase and where it indicates areas for improvement: if they're small changes just do them, if they're big changes suggest them to me.

## Config Layout

`~/.agents` is the git repo for shared coding-agent configuration. Agent runtime directories in `$HOME` are real directories containing links to files under `~/.agents/claude/`, `~/.agents/codex/`, and `~/.agents/pi/`. Edit the repo files, then run `uv run ~/.agents/sync.py`. `~/.agents/AGENTS.md` (this file) holds shared instructions, `~/.agents/claude/CLAUDE.md` adds Claude-specific instructions, and `~/.agents/skills/` holds shared skills.

## Machines

Identify the machine by hostname. Notes specific to each:

For connections between machines, try the local network first and use the tailnet only when the local connection is unavailable. Apply this order to SSH, file serving, and other network services.

The desktop LAN is trusted. The laptop may join untrusted networks, so keep LAN-accessible file-serving listeners on the desktop and use the laptop as a client.

### akelly-desktop (Linux, headless)

Headless Ubuntu: bash, no desktop, no zsh. The `show-in-browser` workflow below opens local files in my Mac's Vivaldi; run it outside the sandbox for network, user-service, and SSH access. The Obsidian CLI and `open` aren't available. `trash` is npm's `trash-cli` in `~/.npm-global/bin` (XDG trash in `~/.local/share/Trash`). `trash-empty.timer` deletes trashed items daily after 30 days. `/tmp` is on the root filesystem (`tmp.mount` masked); systemd-tmpfiles removes entries untouched for 10 days. `~/.config/environment.d/path.conf` puts `~/.local/bin` and `~/.npm-global/bin` on PATH for systemd user services, so `claude`, `uv`, and `trash` resolve there without per-unit `Environment=PATH`. `sudo` is passwordless (`/etc/sudoers.d/akelly-nopasswd`), but the sandbox still blocks root operations, so run sudo commands outside the sandbox. The interactive Pi CLI isn't installed here; Codex and pi-for-claude are. The NTFS drives under `/mnt` are slow to crawl, so they are hidden from sandboxed commands and excluded from the `plocate` index.

To find a file by name anywhere on this machine, use `plocate`; its index is rebuilt daily, so run `updatedb --require-visibility no` first (about 20 seconds, no sudo needed) if the file may be newer than that.

When delivering reports or other documents for me to read, provide clickable Markdown links to their served Tailscale HTTP URLs, not filesystem paths. Append the URL-encoded absolute path to `http://akelly-desktop.troodon-bigeye.ts.net:8377` and verify it loads before sending. These links use the tailnet so they work away from the LAN.

Connect to the Mac with `ssh -o ConnectTimeout=5 -o HostKeyAlias=adrians-macbook-air akelly@Mac.local`, then `ssh -o HostKeyAlias=adrians-macbook-air akelly@adrians-macbook-air.troodon-bigeye.ts.net` if the local connection is unavailable.

To schedule a T3 Code session on this machine (T3 has no scheduler): a systemd user timer runs `uv run ~/.agents/bin/t3-thread.py new <project-dir> <title> <model> <prompt-file>`, which starts a full-access thread in that project and sends the prompt, or `uv run ~/.agents/bin/t3-thread.py resume <thread-id> <prompt-file>` to send the prompt into an existing thread (its own context resumes). Thread ids come from `GET /api/orchestration/snapshot`; an agent can find its own by title. The service must declare `After=t3code.service` and `Requires=t3code.service`. Timer and service go in `~/.config/systemd/user/`; a one-off uses an absolute `OnCalendar=YYYY-MM-DD HH:MM:SS America/Los_Angeles` with `Persistent=true`. Existing examples: `morning-brief.timer` (daily) and `hdd-spinup-check.timer` (one-off). Prefer this over cloud routines, which run remotely and can't see local files.

### Mac.local (macOS)

macOS ships bash 3.2, which lacks `wait -n` — a `while jobs ≥ N; do wait -n; done` concurrency throttle busy-spins at 100% CPU. Poll with `sleep` in shell concurrency loops instead.

Connect to the Linux machine over the local network first: `ssh -o ConnectTimeout=5 -o HostKeyAlias=akelly-desktop akelly@akelly-desktop.local`. If unreachable, use `ssh -o HostKeyAlias=akelly-desktop akelly@akelly-desktop.troodon-bigeye.ts.net`. If Tailscale fails, check `/Applications/Tailscale.app/Contents/MacOS/Tailscale switch --list` (`*` marks the active profile). The server requires personal (`ahalekelly@gmail.com`), not work (`adrian@burnbot.com`); switch with `/Applications/Tailscale.app/Contents/MacOS/Tailscale switch c085`.

### Windows

`show-in-browser`, the Obsidian CLI, and `open` aren't installed. Show an HTML or Markdown file with `Start-Process <absolute-path>` from PowerShell. `trash` is npm's trash-cli and moves files to the Recycle Bin, but it silently no-ops (exit 0, file untouched) on paths containing backslashes, because its glob layer treats `\` as an escape character. Pass forward-slash paths (`trash "C:/path/to/file"`) and verify with `Test-Path` afterwards.

Schedule recurring jobs with Windows Task Scheduler (`Register-ScheduledTask` from PowerShell). Example: the "Codex CLI update" task runs `codex update` daily at 4am for the npm-installed Codex that T3 Code and pi-for-claude spawn, logging to `~/.codex/update.log`. Wrap the command in `cmd.exe /c "... > log 2>&1"` inside a hidden PowerShell so npm's stderr doesn't get reported as a failed exit code.

## Workflow

There are often multiple agents working on different tasks in the same project, don't interfere with the other agents' work. Sometimes I will also edit files while you're working.

If I ask a question mid task, always answer my question first, before resuming what you were working on. If I give you additional instructions mid task, still complete the original task unless I said otherwise.

Sometimes I miss an earlier message of yours, especially one buried in a long run of tool calls. Don't assume I read everything: repeat anything still relevant — open questions, warnings, key findings — in your latest reply.

Do not run `rm` directly or add it to scripts; use `trash` for deletions you author. Existing scripts and build tools may use `rm` internally.

Never run `find`, `rg`, or `grep` from `/`, `~`, or `/mnt` (a hook blocks these); look in the directory a tool said it wrote to, or search a specific directory.

Python, TypeScript, and Rust are the preferred languages when starting a greenfield project.

When creating Python scripts, always use `uv run` and put PEP 723 headers at the top. Never use pip.

Do not interrupt the user by using computer-use or playwright-mcp with an on-screen app unless specifically directed. To interact with web pages, spawn `browser-swarm` subagents — every invocation gets its own MCP session and isolated context in the shared headless Chrome browser daemon (Playwright MCP over CDP port 9377), each context costs 100–200 MB so keep fan-outs to about 10, up to 2 tabs each. For sites that block Chrome, `browser-swarm-firefox` gets an isolated context on one shared Firefox process the same way.

Never attach a whole-browser CDP client (e.g. Playwright `connect_over_cdp`) to my real Vivaldi — it attaches a debugger to every target, which force-loads my 100+ lazily-suspended tabs and can wedge the browser. To inspect my real browser, list targets passively via `/json/list` and open a websocket directly to just the page targets you need.

Use Web Search to look up anything that you're uncertain about.

Split distinct logical changes into separate commits. After making changes, you should typically commit before returning to the user.

Typically commit at file granularity, don't stage part of a file. If one file ends up containing multiple different changes you made, just commit them together. If the work is unfinished or tests are failing, flag these and don't commit. If a file you're working on also has edits that you didn't make, flag this and don't commit until I explicitly ask you to.

The `~/.agents` configuration repo is exempt from these commit rules: automatic sync may commit and push all changes together, including unfinished work and other agents' edits.

Repos I (ahalekelly) own: don't open pull requests for changes I asked for — commit to main and push. For forks, first check whether the target branch is the head of an open PR, including PRs in the upstream repo. If so, get my approval for that push. Repos in the Burnbot GitHub organization (github.com/Burnbot/*, e.g. the Burnbot monorepo and RCaMS): commit locally, and only push to branches you created yourself. Never push to an existing branch, especially main, unless I explicitly tell you to push in that conversation. If you are running in /goal or a similar mode without me in the loop and come up with ideas for improvements to my repos, try them and submit them as PRs if they work and seem good.

Keep docs up to date whenever something changes, and keep user-facing docs very succinct. Any time you write to a doc, do a second concision pass afterwards on anything you added to remove any extraneous words or info that wouldn't be relevant to the user. Update docs that don't match the code, including untracked files. Leave doc updates for another agent's uncommitted changes to that agent.

If I ask a question with a question mark, it is an actual question where I'm looking for an answer, NOT a rhetorical question asking you to make a change. Answering the question is the entire deliverable. Investigation to find the answer is fine (reading, searching, throwaway tests in scratch dirs), but do not modify project files or anything else based on what you find. If the answer implies an obvious fix, state the fix and stop — I'll ask for it if I want it. This applies even when the fix is small, even when you're confident, and even to mid-task questions (answer first, then resume the original task).

If I ask for something that would add a lot more complexity than you think I would expect, or would create potential problems or edge cases, flag this to me and do not implement until I approve those.

If you're doing an in-depth report or want to include images or other visualizations in an explanation, put it in a .md or .html file, and make your final response just be a link to the file.

When I ask to see a local file, use `~/Git/show-in-browser/show-in-browser.sh <absolute-path> [focus] [last]` outside the sandbox. It opens or deduplicates the tab; `focus` brings it forward and `last` moves it to the end. Default to `last` without `focus`, and keep any preference I give for the rest of the conversation. HTML pages live-reload in place; pages with `<script>`s reload normally.

For Markdown in an Obsidian vault on macOS, use `open "obsidian://open?path=/absolute/path/Note.md"` instead. `open` must run outside the sandbox because it needs LaunchServices.

Obsidian and Vivaldi both auto-reload .md files. Vivaldi does this with the [markdown-viewer extension](https://github.com/simov/markdown-viewer); if we run into issues, let me know and we can try installing [md-reader](https://github.com/md-reader/md-reader) instead.

The Obsidian CLI is also installed for richer vault operations — read/create/append, search, properties, tasks, backlinks (`obsidian help` for the full list). File names resolve like wikilinks: `obsidian open file="Note Name" vault="Repo"`. It talks to the running Obsidian app and must also run outside the sandbox.

## Errors in My Tools

If a tool I developed throws an error or misbehaves while you're using it (pi-for-claude, show-in-browser, browser-swarm, or anything else of mine — repos owned by ahalekelly, typically under ~/Git or ~/.agents), treat the error as a bug report, not just an obstacle. Scan all PRs and issues — closed and merged ones too (`--state all`) — for ones that seem to match; if an open one does, briefly comment on it and move on, and if a closed one does, it's context for the investigation. If none matches, spawn a background Fable subagent (Astra on Codex) to own the investigation and open a PR. Continue your original task, working around the error as needed. Mention the error and the resulting PR in your reply. If no good fix can be found, open an issue instead of a PR.

The investigating subagent acts as an orchestrator: it does the judgment work itself — reproducing the error, diagnosing the root cause, and deciding whether this was a bug in the tool or a misuse of it — and delegates mechanical work (searching, implementing a worked-out fix, running tests) to its own subagents using the runtime's model routing instructions where provided. Point it at the transcript of the agent session where the error happened, and quote the failing invocation and full error output in its prompt, so it starts from what actually occurred rather than a paraphrase.

Either verdict usually produces a PR. A bug gets a clean root-cause fix. A misuse means the tool let an agent go wrong: improve the docs, tighten the interface, or make the error message say what to do instead. When the fix is prompt docs — anything an agent reads as instructions — write it as suggestions and defaults, not hard rules, leaving the reading agent room for judgment.

Short of an error, if a tool's behavior gets in your way and the friction seems like it would be common rather than specific to your task, consider filing a feature request on the tool's repo. Agent tools should be designed to minimize the number of tool calls and avoid excessive token usage. Weigh the friction against the complexity the feature would add to the tool — frequent friction that's cheap to fix is an easy yes; a niche annoyance that would demand a new option or code path isn't worth filing. Describe what you were trying to do, what got in the way, and how you worked around it — check for an existing issue first, scanning closed ones too.

Let me know if you run into workflow issues with anything in this doc, or think something in this doc should be changed or explained better.
