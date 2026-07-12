Shared instructions for all coding agents live in ~/.agents/AGENTS.md (Codex and Pi read it directly) — edit them there, this file only adds Claude-specific sections.

@~/.agents/AGENTS.md

## Claude Code Specifics

Don't run bash commands like `cat` that have long outputs, they put the entire output in the chat with me.

## Model Routing

Any tasks that require taste or complicated thinking should be done by Fable, including feature planning, bug finding, auditing for correctness and edge cases, UI, copy, obscure knowledge, or non-code reasoning. If you are not Fable and I tell you to do any of these things, flag this to me. Fable should delegate simple, well-defined tasks that are more than a couple lines of code to another model. This includes implementing coding plans, doing data analysis, and any work you don't feel like doing.

Subagents should consult their Fable orchestrator at these points: before substantive work — orientation (finding files, reading sources) is fine to do first, but consult before writing, editing, or committing to an interpretation; when stuck (recurring errors, non-converging approach) or considering a change of approach. On short reactive tasks, one consult before the approach crystallizes is enough. Weight Fable's advice heavily — adapt only on empirical failure or primary-source evidence contradicting a specific claim, and if your evidence points one way and Fable another, surface the conflict ("I found X, you suggest Y") rather than silently switching. Fable should include these consultation instructions when prompting subagents if relevant.

Fable should be careful about reading very large files, tokens in are usually the majority of inference cost. Fable should set the length limit in the read tool to a reasonable number of lines, a few hundred max. Use `rg`, the Explore tool, or a Sonnet or Opus subagent to help you find where the relevant info is.

When spawning a subagent, always set the model explicitly (eg `model: "sonnet"`). Omitting the model parameter makes the subagent silently inherit the caller's model, which can be very costly.

Never use Haiku.

## Codex Implementation Delegation

@~/Git/codex-plugin-cc/bin/codex-task.md