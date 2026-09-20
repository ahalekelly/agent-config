# tweaks

Adrian's Claude Code mod: one function-hooks plugin carrying the prompt-side fixes that used to need a patched binary or a shell hook.

## Features

- **pinned-tools** — the tools `pinnedTools` names ship their whole schema in the prompt instead of waiting behind ToolSearch (`tool.describe`, `isDeferred: false`). Default: WebFetch, WebSearch.

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

`types/` is generated and gitignored: never hand-edit it, regenerate it.

## Loading

The plugin loads from this checkout through `--plugin-dir`, in `claude-launch` and in `process-wrapper.sh` (T3 and daemon launches execute the binary directly, so a launcher flag alone would miss them).

A local-path marketplace is the other way to load it, and is not used: `claude plugin install` copies the folder into `<config>/plugins/cache/<marketplace>/<plugin>/<version>/` and serves the copy, so edits to the checkout do nothing until the version changes — `claude plugin update` at the same version re-copies nothing. One loading path only: loading the same plugin twice registers every hook twice.
