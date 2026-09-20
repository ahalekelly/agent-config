# 2026-09-20 10:55 PDT: what the model sees, before and after the mods cutover

Captured from real API requests on this machine (a local capture proxy on `ANTHROPIC_BASE_URL`, stock Claude Code 2.1.278). "Before" is the patched 2.1.270 setup: `usage-context.sh` as a `UserPromptSubmit` hook with the `hook-envelope-strip` patch, and browser-swarm agents with an inline Playwright MCP server.

## Usage block

**Before.** The hook's stdout reached the model as its own text block in the user turn, right after the prompt, with no wrapper:

```
[user turn]
<system-reminder> Codebase and user instructions ... </system-reminder>
Reply with exactly: ok
Time: Sunday 2026-09-20 10:53:48 PDT
Opus/Sonnet weekly: 24% used, 48% of week elapsed
Fable weekly: 38% used, 48% of week elapsed
Codex weekly: 8% used, 9% of week elapsed
```

**Now.** The mod attaches the same lines as `prompt.submit` context. The engine renders plugin context as a `hook_additional_context` attachment, prefixed with the hook's name, and 2.1.278 delivers every attachment in a system-channel message that follows the user turn (the sandbox notice, the date, listings and reminders all live there now). The model reads:

```
[user turn]
<system-reminder> Codebase and user instructions ... </system-reminder>
Reply with exactly: ok

[system message after the user turn]
## Bash command sandbox
By default, Bash commands run inside an OS-level sandbox ...
... Fall back to a dedicated tool only when Bash genuinely cannot do the job.

prompt.submit hook additional context: Time: Sunday 2026-09-20 10:53:48 PDT
Opus/Sonnet weekly: 24% used, 48% of week elapsed
Fable weekly: 38% used, 48% of week elapsed
Codex weekly: 8% used, 9% of week elapsed
```

**After the fix.** A probe confirmed the prefix is inside the attachment's text, which a `prompt.attachment` hook may rewrite: the attachment arrives as `{ type: "hook_additional_context", origin: { kind: "plugin", event: "prompt.submit" }, text: "prompt.submit hook additional context: Time: ..." }`. One hook on that type, dropping the leading `<name> hook additional context: `, gives:

```
[system message after the user turn]
... Fall back to a dedicated tool only when Bash genuinely cannot do the job.

Time: Sunday 2026-09-20 10:53:48 PDT
Opus/Sonnet weekly: 24% used, 48% of week elapsed
Fable weekly: 38% used, 48% of week elapsed
Codex weekly: 8% used, 9% of week elapsed
```

The same hook covers settings hooks' output (`origin.kind: "hook"`), which is the whole of what `hook-envelope-strip` did. The move from the user turn to the system channel is the engine's, applies to every attachment, and is not the plugin's to change.

## browser-swarm: MCP server vs `swarm` CLI

**Before.** The agent definition declared an inline stdio MCP server, so each browser-swarm subagent's request carried 22 `mcp__playwright__*` tool definitions, 15,655 characters of JSON (about 3,900 tokens), either in the `tools` array or, with tool-search deferral on, listed by name and loaded through a `ToolSearch` call at startup. One of them:

```json
{
  "name": "mcp__playwright__browser_navigate",
  "description": "Navigate to a URL",
  "input_schema": {
    "type": "object",
    "properties": { "url": { "type": "string", "description": "The URL to navigate to" } },
    "required": ["url"],
    "additionalProperties": false
  }
}
```

A browser action was a native tool call:

```json
{ "type": "tool_use", "name": "mcp__playwright__browser_navigate", "input": { "url": "https://example.com" } }
```

The agent prompt was 3.5 KB and opened with: "Use your Playwright MCP tools (browser_navigate, browser_snapshot, ...). They carry an MCP server prefix ... loading them with one ToolSearch is normal startup, not a failure."

**Now.** No browser tools exist in the request; the tool set is the standard one minus `Agent`. The prompt is 4.5 KB and opens with: "You drive a shared headless browser from Bash with the `swarm` CLI. No browser tools appear in your tool list; there is nothing to load with ToolSearch." It gives the four commands (`open`, `tools`, `help <tool>`, `<tool> '<json>'`, `close`) and the exit-status contract.

A browser action is a Bash call:

```json
{ "type": "tool_use", "name": "Bash", "input": { "command": "/home/akelly/.agents/browser-swarm/swarm \"$id\" navigate '{\"url\":\"https://example.com\"}'" } }
```

and its result is the same text Playwright MCP produced, now on stdout:

````
### Ran Playwright code
```js
await page.goto('https://example.com');
```
### Page
- Page URL: https://example.com/
- Page Title: Example Domain
### Snapshot
- [Snapshot](./page-2026-09-20T18-01-06-866Z.yml)
````

**What changed for the model.**

- About 3,900 tokens of tool schemas left every subagent's context; a schema is fetched on demand with `swarm "$id" help <tool>` when the model wants one.
- Two extra Bash calls per agent: `open` at the start and `close` at the end.
- Arguments are JSON inside a shell string instead of a validated `tool_use` input, so a malformed call fails at Playwright MCP (exit 1 with its message on stdout) rather than at the harness. `-` reads the JSON from stdin when quoting gets awkward. Gate A's agent hit exactly this with `tabs '{}'` and recovered from the error text.
- A lost context is exit status 4 with one line of explanation, instead of an MCP tool error the harness might retry.
