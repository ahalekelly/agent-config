Shared instructions for all coding agents live in ~/.agents/AGENTS.md (Codex and Pi read it directly) — edit them there, this file only adds Claude-specific sections.

@~/.agents/AGENTS.md


## Claude Code Specifics

Don't use `cat` to read files, that puts the entire file contents in the chat with me.

## Model Routing

Any tasks that require taste or complicated thinking should be done by Fable, including feature planning, bug finding, auditing for correctness and edge cases, UI, copy, obscure knowledge, or non-code reasoning. If you are not Fable and I tell you to do any of these things, flag this to me. Fable should delegate simple, well-defined tasks that are more than a couple lines of code to another model. This includes implementing coding plans, doing data analysis, and any work you don't feel like doing.

Be careful about reading very large files, tokens in are usually the majority of inference cost. Fable should set the length limit in the read tool to a reasonable number of lines, a few hundred max. Use `rg` or use another model or the Explore tool to help you figure out what to read.

Codex is the default code implementation model, delegate to Codex via the following agents: `codex-implementation` for , and other general purpose tasks, `codex-review` for a second opinion code review, and `codex-computer-use` for browser/GUI verification.

Load the `codex-prompting` skill before writing a Codex plan file or review focus text.