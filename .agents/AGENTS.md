User Instructions:

## Code Style

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
When you refactor or remove some functionality, also remove any dead code created by that change.
Make the code skimmable, avoid cleverness.

Do not implement fallback paths without explicit approval, if things aren't working they should fail loudly and provide clear error messages to the user.

Documentation and code comments should be timeless, imagine you're writing them for someone reading a year from now. No breadcrumbs, the docs and code comments shouldn't mention, refer to, or imply previous versions of the code, or mention how the code is different now from how it was before. Warnings about pitfalls, confusing things, mistakes to avoid, can still be good though.

Reports are different, they're an explanation for the user to read immediately after creation, and a point-in-time snapshot, they don't have to be timeless. Reports should have the datetime in the title.

When creating Markdown files in greenfield projects, don't use newlines to hard-wrap, the markdown viewer's soft line wrapping is preferred.

## Secrets

API keys live in `~/.agents/secrets.env`, one `export NAME=value` per line, readable from inside both the Claude and Codex sandboxes and normally already present in the command environment. If one is missing (e.g. in a desktop-launched session), source the file in the command that needs it: `. ~/.agents/secrets.env && <command>`. Never commit this file or print its contents.

## Workflow

Never use `rm` to delete files or directories. Use the `trash` command instead so deleted items can be recovered.

When creating Python scripts, always use `uv run` and put PEP 723 headers at the top. Never use pip.

There are often multiple of you running on different tasks in the same project, don't interfere with the other one's work, don't try to infer what they're doing and finish it for them. Sometimes I will also edit files while you're working.

If I give you steering instructions mid task, you should still complete the original task unless I said otherwise.

If you find a bug in one place in the code, look for other places where that same class of bug could have occured. More generally, whenever you learn something surprising, like finding a bug, think about what that tells you about the state of the codebase and where it indicates there are areas for improvement, if they're small changes just do them, if they're big changes suggest them to me.

Don't be afraid to use web search to look things up.

Split distinct logical changes into separate commits. After making changes, you should typically commit before returning to the user. 

Typically commit at file granularity, don't stage part of a file. If one file ends up containing multiple different changes you made, just commit them together. If the work is unfinished or tests are failing, flag these and don't commit. If a file you're working on also has edits that you didn't make, flag this and don't commit until the user explicitly asks you to.

Make sure to keep docs up to date whenever something changes, but please keep user-facing docs succinct. If you notice a doc doesn't match the comitted code, update it, even if you're not the one who made it out of date. But if the doc doesn't match uncomitted changes done by another agent, no need to update the doc, they'll update the doc before they commit the code.

If I ask you a question and it's ambiguous whether it's rhetorical, treat it as an actual question where I'm looking for an answer, not a rhetorical question that's asking you to make a change.

If I ask for something that would add a lot more complexity than you think I would expect, or would create potential problems or edge cases, flag this to me.

If you're doing an in-depth report or want to include images or other visualizations in an explanation, put it in a .md or .html file. 

To show me an .html file, use `~/Git/show-in-browser/show-in-browser.sh <absolute-path> [focus] [last]` (outside the sandbox): it opens the file (deduping tabs), `focus` brings it forward, `last` moves its tab to the end to highlight it to me. Default to `last` but not `focus`, but if I tell you to do otherwise, make that the new default for the rest of that conversation. The extension live-reloads the visible page in place with zero flicker whenever you edit the file — no need to re-run the script to refresh. Pages with `<script>`s get a full (flashing) reload instead of the flicker-free swap.

To show me a Markdown file, if it is not in an Obsidian vault, open it with Vivaldi. If it is, use the `obsidian://` URI scheme with a URL-encoded absolute path:

```bash
open "obsidian://open?path=~/Git/Repo/Note.md"
```

Obsidian and Vivaldi both auto-reload .md files. In Vivaldi this is done with the [markdown-viewer extension](https://github.com/simov/markdown-viewer). If we run into issues, let me know and we can try installing [md-reader](https://github.com/md-reader/md-reader) instead.

This must run outside the sandbox (`open` needs LaunchServices access, which the sandbox blocks).

The Obsidian CLI is also installed for richer vault operations — read/create/append, search, properties, tasks, backlinks (`obsidian help` for the full list). File names resolve like wikilinks: `obsidian open file="Note Name" vault="Repo"`. It talks to the running Obsidian app and must also run outside the sandbox.

Let me know if you run into workflow issues with anything in this doc, or think something in this doc should be changed or explained better.

