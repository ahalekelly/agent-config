Shared instructions for all coding agents live in ~/.agents/AGENTS.md (Codex and Pi read it directly) — edit them there, this file only adds Claude-specific sections.

@~/.agents/AGENTS.md

## Claude Code Specifics

The `!` prefix I use to run a command myself still executes in the session's non-interactive shell, not a real TTY. When a command needs sudo or another interactive terminal prompt, tell me to run it in a separate real Terminal window instead of suggesting `!`.

WebFetch's text extraction often fails on PDFs ("corrupted/unreadable" or empty answers), but it still saves the raw file to a local path noted in the result. Don't retry WebFetch or hunt for another copy — Read the saved file, the Read tool renders PDF pages natively. For a URL you already know is a PDF, fetch and Read in one step. Reading a PDF costs vision tokens, so if a task requires reading multiple PDFs, delegate it to an Opus subagent or GPT via pi-for-claude instead of reading them yourself.

Whenever posting on Github, put the "🤖 Generated with Claude Code" line at the top instead of the bottom so it's more clear to the reader.

Never stop the shared browser daemon (`shared-browser.sh stop`) after browser-swarm fan-outs: it is machine-wide, another session's agents may still be attached, and it stops itself after 5 minutes with no attached agents.

## Model Routing

Any tasks that require taste or complicated thinking should be done by Fable, including feature planning, bug finding, auditing for correctness and edge cases, UI, copy, obscure knowledge, or non-code reasoning. If you are not Fable and I tell you to do any of these things, flag this to me. Fable should delegate well-defined tasks that take more than a minute or two to another model. This includes implementing coding plans, research, any mechanical work, and any work you don't feel like doing.

GPT models come in 3 classes, Sol (Opus class), Terra (Sonnet class), and Luna (Haiku class). GPT is smarter, cheaper, and faster than Opus/Sonnet/Haiku, so use GPT with pi-for-claude when you would use otherwise Opus/Sonnet/Haiku. If GPT or pi-for-claude doesn't work for some reason, fall back to Opus/Sonnet and let me know so we can fix it. Never use Haiku. All production code should be written by Sol, Opus, or Fable. Never have Sonnet, Terra, or Luna write production code.

GPT uses a different search engine from Claude, so for thorough web research tasks, delegate to both Sol and Opus, and have them surface the most promising links for you to review, quoting the relevant sections of their sources exactly in their response.

You can consult GPT Sol for a second opinion whenever you want. Do this liberally, especially on tricky tasks like debugging or code review.

Fable should be careful about reading very large files, tokens in are usually the majority of inference cost. Fable should set the length limit in the read tool to a reasonable number of lines, a few hundred max. Instead of reading large files, use `rg`, the Explore tool, or a Sonnet or Opus subagent to help you find where the relevant info is.

When spawning a subagent, always set the model explicitly (eg `model: "opus"`). Omitting the model parameter makes the subagent silently inherit the caller's model, which is costly. Run subagents in the background.

## Pi Implementation Delegation

@~/.agents/pi-for-claude/prompts/pi-for-claude-instructions.md