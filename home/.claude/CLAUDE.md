Shared instructions for all coding agents live in ~/.agents/AGENTS.md (Codex and Pi read it directly) — edit them there, this file only adds Claude-specific sections.

@~/.agents/AGENTS.md

## Claude Code Specifics

Don't run bash commands that have long outputs, they put the entire output in the chat with me. Try not to use `cat` to read a file — use the `Read` tool instead, even when it means splitting a compound shell command apart (e.g. `ls dir; cat file` becomes a Bash call for `ls dir` plus a separate Read call for `file`, not one bundled command).

Text written between tool calls is not displayed to me (Claude Code bug, anthropics/claude-code#75900). Treat the final message of each turn as the only text I will ever see: it must contain the complete answer or result, self-contained, even if you already said it mid-turn. Never end a turn on an aside or a message that assumes I read earlier text.

The `!` prefix I use to run a command myself still executes in the session's non-interactive shell, not a real TTY. When a command needs sudo or another interactive terminal prompt, tell me to run it in a separate real Terminal window instead of suggesting `!`.

## Model Routing

Any tasks that require taste or complicated thinking should be done by Fable, including feature planning, bug finding, auditing for correctness and edge cases, UI, copy, obscure knowledge, or non-code reasoning. If you are not Fable and I tell you to do any of these things, flag this to me. Fable should delegate well-defined tasks that take more than a minute or two to another model. This includes implementing coding plans, research, any mechanical work, and any work you don't feel like doing.

You can get a second opinion from the latest GPT agent whenever you want using pi-for-claude. Do this especially on tricky tasks like debugging or code review.

Fable should be careful about reading very large files, tokens in are usually the majority of inference cost. Fable should set the length limit in the read tool to a reasonable number of lines, a few hundred max. Instead of reading large files, use `rg`, the Explore tool, or a Sonnet or Opus subagent to help you find where the relevant info is.

When spawning a subagent, always set the model explicitly (eg `model: "sonnet"`). Omitting the model parameter makes the subagent silently inherit the caller's model, which is costly. Run subagents in the background.

Never use Haiku.

## Pi Implementation Delegation

@~/.agents/pi-for-claude/prompts/pi-for-claude-instructions.md