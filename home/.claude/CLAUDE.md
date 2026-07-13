Shared instructions for all coding agents live in ~/.agents/AGENTS.md (Codex and Pi read it directly) — edit them there, this file only adds Claude-specific sections.

@~/.agents/AGENTS.md

## Claude Code Specifics

Don't run bash commands that have long outputs, they put the entire output in the chat with me. Default to the `Read` tool instead of `cat` for reading files.

Text written between tool calls is not displayed to me (Claude Code bug, anthropics/claude-code#75900). Treat the final message of each turn as the only text I will ever see: it must contain the complete answer or result, self-contained, even if you already said it mid-turn. Never end a turn on an aside or a message that assumes I read earlier text.

## Model Routing

Any tasks that require taste or complicated thinking should be done by Fable, including feature planning, bug finding, auditing for correctness and edge cases, UI, copy, obscure knowledge, or non-code reasoning. If you are not Fable and I tell you to do any of these things, flag this to me. Fable should delegate simple, well-defined tasks that are more than a couple lines of code to another model. This includes implementing coding plans, doing data analysis, and any work you don't feel like doing.

## Pi Implementation Delegation

@~/.agents/pi-for-claude/prompts/pi-for-claude-instructions.md

Fable should be careful about reading very large files, tokens in are usually the majority of inference cost. Fable should set the length limit in the read tool to a reasonable number of lines, a few hundred max. Use `rg`, the Explore tool, or a Sonnet or Opus subagent to help you find where the relevant info is.

When spawning a subagent, always set the model explicitly (eg `model: "sonnet"`). Omitting the model parameter makes the subagent silently inherit the caller's model, which is costly. Default to running subagents in the background.

Never use Haiku.

## Codex Implementation Delegation

@~/Git/codex-plugin-cc/bin/codex-task.md
