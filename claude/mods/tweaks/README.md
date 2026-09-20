# tweaks

Adrian's Claude Code mod: one function-hooks plugin carrying the prompt-side fixes that used to need a patched binary or a shell hook.

## Features

- **pinned-tools** — the tools `pinnedTools` names ship their whole schema in the prompt instead of waiting behind ToolSearch (`tool.describe`, `isDeferred: false`).
- **prompt-trim** — drops the standing context nothing reads: the `userEmail` and `currentDate` context blocks, the `date` attachment, the model-family table from the `# Environment` section, and the environment attachment's `Platform:` and `Shell:` lines.
- **sandbox-notice** — the sandbox notice's filesystem policy drops Claude Code's own state under `~/.claude` and the `/dev/` handles, which makes room to name what the engine truncated away.
- **task-reminder** — the periodic nag to use the task tools reaches the model only while the session has tasks.
- **context-envelope** — context a hook attached reads as `additional context:` on its own line, without the hook's name.
- **cron-label** — a scheduled task's prompt carries a line saying the scheduler fired it.
- **todo-capture** — a prompt typed as `todo: <item>` is appended to `todo.md` in the session's root and runs no turn.
- **usage-context** — every prompt the person sends carries the local time, what the Claude and Codex weekly budgets have left, and what the machine is short of.
- **task-provenance** — every task-notification says what started the run it reports: the agent's launch, a `SendMessage` this session's model sent, or something this session cannot account for.
- **spawn-guard** — a subagent spawned without a model is refused, since an omitted model silently inherits the caller's. A fork inherits by design and passes.
- **read-guard** — a Fable or Opus loop reading a file over its token budget has the call paged down to what fits, or refused with the way to read less.

## Options

Set in settings under `pluginConfigs.tweaks.options`, or from `/config`:

| Option | Kind | Default |
| --- | --- | --- |
| `pinnedTools` | list of tool names | `["WebFetch", "WebSearch"]` |
| `readGuardTokensFable` | number | 4000 |
| `readGuardTokensOpus` | number | 15000 |

A list is declared in `plugin.json` as `"type": "string"` with `"multiple": true`; the manifest's other types are `number`, `boolean`, `file` and `directory`.

## Developing

Function hooks load only where `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1` is set, so every command below carries it.

```bash
CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude --plugin-dir ~/.agents/claude/mods/tweaks   # run it; the folder is watched and reloads on save
CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude -p "/plugin-types ~/.agents/claude/mods/tweaks/types"   # regenerate types/ after a Claude Code update
CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude plugin validate ~/.agents/claude/mods/tweaks
CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude plugin test ~/.agents/claude/mods/tweaks
tsc -p ~/.agents/claude/mods/tweaks    # against the generated types
```

`types/` is generated and gitignored: never hand-edit it, regenerate it. `plugin test` is hidden from `claude plugin --help`.

The mod needs Claude Code 2.1.278 or newer: `prompt.attachment` and `session.root` are not events in 2.1.274, and a release without them refuses the whole module at load.

The tests pin the engine's own wording — the trimmed lines, the task reminder, the usage endpoints' fields. A release that rewords one fails its test, which is the signal to read the release and follow it.

## Loading

The plugin loads from this checkout through `--plugin-dir`, passed by `bin/claude-process-wrapper`. `claude-launch` runs that wrapper for terminal and T3 sessions, and Claude Code runs it as its `processWrapper` for background sessions, which spawn the binary directly and would miss a launcher flag.

A local-path marketplace is the other way to load it, and is not used: `claude plugin install` copies the folder into `<config>/plugins/cache/<marketplace>/<plugin>/<version>/` and serves the copy, so edits to the checkout do nothing until the version changes — `claude plugin update` at the same version re-copies nothing. One loading path only: loading the same plugin twice registers every hook twice.

## What the engine does

What a discovery run settled, on Claude Code 2.1.278. Each answer is pinned by a test.

- A scheduled task's prompt arrives at `prompt.submit` with `origin.kind` `scheduled-trigger`; a background agent's notification arrives there too, with `task-notification`. `session.receive` fires for neither.
- A notification's text is a `<task-notification>` element whose `<task-id>` is the agent's id and whose `<tool-use-id>` names the call that started the run that just stopped: the `Agent` call for the launch, the `SendMessage` call for a resume. Some notifications carry no `<tool-use-id>` at all, so its absence is reported as an unattributable run rather than guessed at.
- A subagent's loop raises no `prompt.submit` of its own, so a hook on that event is the main conversation's alone. Its attachments and tool calls carry `agentId`.
- `agent.spawn`'s result carries the new agent's `agentId` beside the model it resolved.
- The first user message's context blocks are `claudeMd`, `currentDate`, `gitStatus` and — with an account logged in — `userEmail`. The engine's own injected messages arrive at `prompt.attachment` as `date`, `environment`, `model`, `deferred_tools_delta`, `agent_listing_delta`, `skill_listing`, `total_tokens_reminder`, `queued_command`, `sandbox_instructions` and `task_reminder`.
- The system prompt's `# Environment` section is `prompt.section` `env_info_simple` and carries the model-family table. The `Platform:`, `Shell:` and `OS Version:` lines are not in it: they belong to the `environment` attachment.
- A `task_reminder` attachment carries the session's task list under `Here are the existing tasks:` while the list holds anything, and the nag alone while it does not — so an attachment-local decision tells the two apart.
- `$.session.root()` is where the session started, which is what `CLAUDE_PROJECT_DIR` gives a settings hook.

Four limits shaped the code:

- A `prompt.submit` hook's rewritten `text` does not reach the model on the scheduled-trigger path, though `next` resolves with it; `context` does reach the model. Hence cron-label rides as context. On the task-notification path both land, so the `<trigger>` element is prepended to the notification itself. Whether the fired prompt is drawn in the transcript is not a plugin's to decide — the engine queues it as a meta message and no event exposes that — so it stays invisible, and the label is what tells the model.
- `$` may not be passed across an import: a function that takes it lives in the file that hooks with it. That is why the machine probes sit in usage-context.ts.
- `$.http.fetch` takes neither a timeout nor an abort signal, so a refresh cannot be time-bounded; a hung fetch is held until the module reloads, and a single-flight guard keeps the timer from starting another.
- A hook that fails takes its plugin's other hooks on that event with it, not just itself. A feature that gathers several inputs therefore catches each one of them.
- `$.http.fetch` is refused outright where `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` is set, and the usage lines then read as unavailable, naming that refusal.

A hook's context reaches the model as a `hook_additional_context` attachment inside a `<system-reminder>`, led by `${hookName} hook additional context: ` — a plugin's chain event, a settings hook's event name. The lead-in sits inside the attachment's `text`, so a `prompt.attachment` hook rewrites it. Nothing carries a `hook success:` envelope, which is what the shell hooks needed stripping for.
