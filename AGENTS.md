Hi I'm Adrian Kelly, welcome to my computer

## Writing Style

Cut Unnecessary Words: Don't add any words that are not essential to the meaning.
Use Active Voice: Favor the active voice over the passive voice.
Use Simple Language: Opt for everyday English over jargon, or scientific terms.

## Code Style

Do not preserve backward compatibility. Remove obsolete paths instead of adding compatibility layers, fallbacks, or migrations.
Choose the simplest implementation that fully meets the current requirements. Avoid speculative abstractions, configuration, and indirection.
Grow the system in layers. Start from the smallest version that works end to end, and add each new capability on top of a product that already works.
Keep components modular and concerns clearly separated.
Prefer established, well-maintained libraries when they reduce overall complexity or improve reliability. Do not reimplement common functionality without a clear reason.
Lean on the dependencies already in the project before writing your own implementation or adding packages. Do not assume a library lacks a capability without checking its documentation and types.
Make architectural decisions for the long term. Do not accept a stopgap that only works for now and is meant to be replaced later.

Write extremely easy to consume code, it should be "skimmable" and easy to understand. Optimize for how easy the code is to read.
Prefer fewer states, fewer arguments, and required values over optional ones.
Minimize possible states by reducing number of arguments, remove or narrow any state.
Use discriminated unions to reduce number of states the code can be in.
Exhaustively handle any objects with multiple different types, fail on unknown type.
Don't write defensive code, assume the values are always what types tell you they are.
Verify data that gets loaded or passed into a function and don't be afraid to raise errors if it's incorrect. Always be highly opinionated about the parameters you pass around. Don't let things be optional if not strictly required.
Remove any changes that are not strictly required.
Bias for fewer lines of code.
Don't break out into too many functions, that's hard to read.
Use "if: raise" instead of try catches or default values when you do expect something to exist.
Never pass overrides except strictly necessary, keep argument count low.
Don't make arguments optional if they are actually required.

When you refactor or remove some functionality, also remove any dead code created by that change. Code and docs should reflect the intended end state, not the historical path that produced the current implementation. Optimize for the code that should exist, not the smallest diff from the old shape. Delete dead compatibility paths instead of making them better. Do not invent a generic framework for one feature. Prefer names that describe product intent over implementation history.

Don't make workarounds for code in the same project, if you're adding new functionality and it would reduce complexity and total LOC to refactor to do it properly then do it.

If things aren't working they should fail loudly and provide clear error messages to the user. Fallback paths are almost always unecessary extra code, they make functionality harder to reason about and hide when there are errors that need to be fixed.

Documentation and code comments should be timeless, imagine you're writing them for someone reading a year from now. No breadcrumbs, the docs and code comments shouldn't mention, refer to, or imply previous versions of the code. Do not mention in comments or docs how the code is different now from how it was before, except in a specific high level project changelog. Code comments can still include warnings about specific mistakes to avoid.

Timeless also means independent of the conversation that produced the edit: answer my question in your reply, and write the doc from the document's own point of view, stating facts positively rather than as responses ("the scope of X is ..." not "there is no separate definition of X"). Test: would the text make sense if it had always been in the doc?

Reports are different, they're an explanation for the user to read immediately after creation, and a point-in-time snapshot, they don't have to be timeless. Put the datetime in a report's title — it marks the content as frozen at that date, so any future reader knows current docs win on conflict. If a report needs updating, it has become a living doc — drop the date from the title and record `created:` and `verified:` (last fact-checked) as frontmatter properties instead. Git preserves history, so delete or consolidate superseded reports rather than curating them. Keep reports in a `reports/` subfolder beside the project's living docs, so a project folder shows only maintained docs.

When creating Markdown files in greenfield projects, don't use newlines to hard-wrap, the markdown viewer's soft line wrapping is preferred.

My requests are approximate. I am not the one coding; you are. My directions are pointers toward what I actually want -- the simplest, cleanest, most elegant design -- and they may be slightly off. That goal ALWAYS outranks my literal words.

So when you hit a wall -- a case that doesn't fit, a spec that breaks, an assumption that fails -- the wall is information: the design is wrong somewhere. STOP. Re-derive the design from first principles until the wall does not exist. If the result diverges from my spec, diverging is your duty: present it to me.

What you must never do is patch around the wall to comply with my words: a flag, a special case, a conversion shim, a second channel, a parallel path, a test rewritten to dodge a broken rule. The patch IS the failure. Every duct-tape betrays my intent while pretending to honor it, and it will be rejected -- 100% of the time, regardless of cost already sunk. A blocker honestly reported is a good outcome; a "working" deliverable built on gambiarra is the worst possible one, and is treated as sabotage.

## Secrets

API keys live in `~/.agents/secrets.env`, one `export NAME=value` per line, readable from inside both the Claude and Codex sandboxes and normally already present in the command environment. If one is missing (e.g. in a desktop-launched session), source the file in the command that needs it: `. ~/.agents/secrets.env && <command>`. Never commit this file or print its contents.

## Config Layout

`~/.agents` is a git repo holding shared configuration for all coding agents; `~/.claude`, `~/.claude-work`, and `~/.codex` are symlinks into `~/.agents/home/`. `~/.agents/AGENTS.md` (this file) holds the shared instructions; `~/.agents/home/.claude/CLAUDE.md` adds Claude-specific sections on top. Skills are shared across projects via the `~/.claude/skills` symlink (real path `~/.agents/skills`). When editing any of these files, use the real `~/.agents/` paths — some tools refuse to write through the symlinks.


## Workflow

Never use `rm` to delete files or directories, use the `trash` command instead so deleted items can be recovered.

Python, Typescript, and Rust are the preferred languages when starting a greenfield project.

When creating Python scripts, always use `uv run` and put PEP 723 headers at the top. Never use pip.

macOS ships bash 3.2, which lacks `wait -n` — a `while jobs ≥ N; do wait -n; done` concurrency throttle busy-spins at 100% CPU. Poll with `sleep` in shell concurrency loops instead.

To interact with web pages, spawn `browser-swarm-1...10` subagents — up to 10 in parallel, one per type, up to 2 tabs each. They come pre-wired to a shared headless browser daemon (Playwright MCP over CDP port 9377).

Never attach a whole-browser CDP client (e.g. Playwright `connect_over_cdp`) to my real Vivaldi — it attaches a debugger to every target, which force-loads my 100+ lazily-suspended tabs and can wedge the browser. To inspect my real browser, list targets passively via `/json/list` and open a websocket directly to just the page targets you need.

There are often multiple agents working on different tasks in the same project, don't interfere with the other agent's work. Sometimes I will also edit files while you're working.

If I ask a question mid task, always answer my question first, before resuming what you were working on. If I give you additional instructions mid task, still complete the original task unless I said otherwise.

Sometimes I miss an earlier message of yours, especially one buried in a long run of tool calls. Don't assume I read everything: repeat anything still relevant — open questions, warnings, key findings — in your latest reply.

If you find a bug in one place in the code, look for other places where that same class of bug could have occured. More generally, whenever you learn something surprising, like finding a bug, think about what that tells you about the state of the codebase and where it indicates there are areas for improvement, if they're small changes just do them, if they're big changes suggest them to me.

Don't be afraid to use web search to look things up.

Split distinct logical changes into separate commits. After making changes, you should typically commit before returning to the user. 

Typically commit at file granularity, don't stage part of a file. If one file ends up containing multiple different changes you made, just commit them together. If the work is unfinished or tests are failing, flag these and don't commit. If a file you're working on also has edits that you didn't make, flag this and don't commit until the user explicitly asks you to.

On repos I (ahalekelly) own, don't open pull requests for changes I asked for, just commit to main without pushing. If you are running in /goal or a similar mode without me in the loop and come up with ideas for improvements to my repos, try them and submit them as PRs if they work and seem good.

Make sure to keep docs up to date whenever something changes, but please keep user-facing docs succinct. If you notice a doc doesn't match the comitted code, update it, even if you're not the one who made it out of date. But if the doc doesn't match uncomitted changes done by another agent, no need to update the doc, they'll update the doc before they commit the code.

If I ask a question with a question mark, it is an actual question where I'm looking for an answer, NOT a rhetorical question asking you to make a change. Answering the question is the entire deliverable. Investigation to find the answer is fine (reading, searching, throwaway tests in scratch dirs), but do not modify project files or anything else based on what you find. If the answer implies an obvious fix, state the fix and stop — I'll ask for it if I want it. This applies even when the fix is small, even when you're confident, and even to mid-task questions (answer first, then resume the original task).

If I ask for something that would add a lot more complexity than you think I would expect, or would create potential problems or edge cases, flag this to me.

If you're doing an in-depth report or want to include images or other visualizations in an explanation, put it in a .md or .html file. 

To show me an .html file, use `~/Git/show-in-browser/show-in-browser.sh <absolute-path> [focus] [last]` (outside the sandbox): it opens the file (deduping tabs), `focus` brings it forward, `last` moves its tab to the end to highlight it to me. Default to `last` but not `focus`, but if I tell you to do otherwise, make that the new default for the rest of that conversation. The extension live-reloads the visible page in place with zero flicker whenever you edit the file — no need to re-run the script to refresh. Pages with `<script>`s get a full (flashing) reload instead of the flicker-free swap.

To show me a Markdown file, if it is not in an Obsidian vault, open it with Vivaldi. If it is, use `open "obsidian://open?path=~/Git/Repo/Note.md"`

Obsidian and Vivaldi both auto-reload .md files. In Vivaldi this is done with the [markdown-viewer extension](https://github.com/simov/markdown-viewer). If we run into issues, let me know and we can try installing [md-reader](https://github.com/md-reader/md-reader) instead.

This must run outside the sandbox (`open` needs LaunchServices access, which the sandbox blocks).

The Obsidian CLI is also installed for richer vault operations — read/create/append, search, properties, tasks, backlinks (`obsidian help` for the full list). File names resolve like wikilinks: `obsidian open file="Note Name" vault="Repo"`. It talks to the running Obsidian app and must also run outside the sandbox.

## Errors in My Tools

If a tool I developed throws an error or misbehaves while you're using it (pi-for-claude, show-in-browser, browser-swarm, or anything else of mine — repos owned by ahalekelly, typically under ~/Git or ~/.agents), treat the error as a bug report, not just an obstacle. Scan all PRs and issues — closed and merged ones too, not just open (`--state all`) — for one that seems to match; if an open one does, briefly comment on it and move on, and if a closed one does, it's context for the investigation. If none matches, spawn a background Fable subagent to own the investigation and open a PR. Continue your original task, working around the error as needed. Mention the error and the resulting PR in your reply.

The Fable subagent acts as an orchestrator: it does the judgment work itself — reproducing the error, diagnosing the root cause, and deciding whether this was a bug in the tool or a misuse of it — and delegates mechanical work (searching, implementing a worked-out fix, running tests) to its own subagents per the model routing rules. Point it at the transcript of the agent session where the error happened, and quote the failing invocation and full error output in its prompt, so it starts from what actually occurred rather than a paraphrase.

Either verdict usually produces a PR. A bug gets a clean root-cause fix. A misuse means the tool let an agent go wrong: improve the docs, tighten the interface, or make the error message say what to do instead. When the fix is prompt docs — anything an agent reads as instructions — write it as suggestions and defaults, not hard rules, leaving the reading agent room for judgment.

Short of an error, if a tool's behavior gets in your way and the friction seems like it would be common rather than specific to your task, consider filing a feature request on the tool's repo. Weigh the friction against the complexity the feature would add to the tool — frequent friction that's cheap to fix is an easy yes; a niche annoyance that would demand a new option or code path isn't worth filing. Describe what you were trying to do, what got in the way, and how you worked around it — check for an existing issue first, scanning closed ones too.

Let me know if you run into workflow issues with anything in this doc, or think something in this doc should be changed or explained better.

