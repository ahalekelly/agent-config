Shared instructions for all coding agents live in ~/.codex/AGENTS.md — edit them there, this file only adds Claude-specific sections.

@~/.codex/AGENTS.md

## Model Routing

Fable usage credits are limited, Fable should mainly do planning, bug finding, auditing for correctness and edge cases, UI, copy, non-coding reasoning, and other tasks that require a lot of intelligence or taste. Fable should delegate well-defined tasks to another model. But if it's only a few lines of changes and less work to do it yourself than create a subagent, it could be faster to just do it yourself.

Codex is the default code implementation model, delegate to Codex via the following agents: `codex-implementation` for implementing coding plans, doing data analysis, schlep work, and other general purpose tasks, `codex-review` for code reviews, and `codex-computer-use` for browser/GUI verification. If Codex does a poor job, you can also use Opus for implementation.
