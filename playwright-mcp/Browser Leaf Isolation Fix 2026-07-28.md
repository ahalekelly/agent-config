# Browser Leaf Isolation Fix 2026-07-28

**TL;DR:** The 5-leaf browser sharing was caused by Claude Code, not Playwright: Claude Code (v2.1.220) deduplicates inline agent-frontmatter MCP servers by **config content** — all concurrent subagents whose frontmatter declares a byte-identical server share ONE stdio server process and ONE MCP session, hence one browser context and one contested tab list. Fix: sibling agent types `browser-leaf` … `browser-leaf-5`, each with a unique `--output-dir` arg to defeat the dedup. Verified at 5× concurrency: 15/15 tab listings clean, five separate server + browser processes.

## Root cause

Claude Code shares one inline-frontmatter MCP server across concurrent subagents when their server configs are identical. The docs (sub-agents.md, "Scope MCP servers to a subagent") say inline servers are "connected when the subagent starts and disconnected when it finishes" — under concurrency this is false. The sharing is keyed on config content, **not** agent type: four *different* agent types with byte-identical playwright configs still shared one server.

Why that produces the observed tab-stealing: `@playwright/mcp` (v0.0.78) with `--isolated` launches one browser per server process and creates one browser context per *MCP client session* (`packages/playwright-core/src/tools/mcp/program.ts`: `useSharedBrowser = config.sharedBrowserContext || config.browser.isolated`, then per-client `browser.newContext()`). A stdio server has exactly one client session. When Claude Code multiplexes N leaves over that one session, they all operate on the same context — same tab list, same "current tab" that every `browser_navigate` retargets. `--isolated` cannot help; the isolation boundary (the client session) is what Claude Code collapsed. Cross-process browser sharing is impossible in this mode (`createIsolatedBrowser` does a fresh `browserType.launch()` per server), which pins the sharing on Claude Code's connection layer.

### Evidence

**Baseline repro (4 concurrent `browser-leaf` leaves, fresh `claude -p` child session, 2026-07-28 22:42).** All four leaves shared literally one tab; each `browser_navigate` clobbered the previous leaf's page. Leaf 1 (assigned example.com), verbatim:

> **CHECK1** (immediately after navigating to example.com):
> `- 0: (current) [Wikipedia](https://www.wikipedia.org/)`
> **CHECK2**: `- 0: (current) [Internet Archive …](https://archive.org/)`

Leaf 3 (assigned rust-lang.org): "the navigate tool's own response confirmed … rust-lang.org, but the very next `browser_tabs` list call showed … archive.org". Process table during the run (2–5 s sampling): at no point was more than one fresh `npm exec @playwright/mcp@latest` process alive for the four leaves.

**Dedup is by config, not agent type (siblings test, 23:06).** Created `browser-leaf-2/3/4` as byte-identical copies (different `name:` only) and ran one leaf on each of the four types concurrently. Still one shared context — all four leaves reported the same 3-tab list (`about:blank` / example.com / a contested tab that rust-lang.org, archive.org, and wikipedia.org overwrote in turn). Monitor showed exactly **one** `--headless --isolated` server process (plus the session's unrelated plugin playwright server) for all four leaves; it spawned when the first leaf started (23:06:29) and exited when the last finished (23:07:29). Leaf 1 also confirmed its tools were `mcp__playwright__*` — the frontmatter server, not the plugin.

**Why the earlier 2-leaf test looked fine.** The "multiple headless Chrome processes" observed then were Pi `agent_browser` Chromes (`--user-data-dir=…/T/agent-browser-chrome-<uuid>`), not playwright-mcp browsers — a misattribution. Two leaves whose tool calls don't interleave can also miss the contention window.

**Related upstream reports.** microsoft/playwright-mcp#893 describes exactly this symptom (parallel Claude Code agents "fighting over the same tab … despite `--isolated`") with no root cause identified; anthropics/claude-code#28126 reports the opposite (per-subagent duplicate servers) on Windows. Neither documents the config-content dedup shown here. Worth filing against anthropics/claude-code with this evidence if you want it fixed upstream.

**Bonus finding (not the cause, but real):** every Claude Code session spawns a playwright **plugin** MCP server (`npm exec @playwright/mcp@latest`, no flags) at startup and these leak — ~18 were alive dating back to Jul 20, parented to live `claude` / `claude bg-spare` daemon processes. Each idle one is just a node process (browser not launched), but it's why the machine's process table is full of playwright-mcp entries.

## The fix

Defeat the dedup by making each concurrent leaf's server config unique. Five sibling agent types now exist, identical except `name:` and a per-type `--output-dir` (which also moves `.playwright-mcp` artifact droppings out of the cwd into `/tmp/claude/`).

Diff to `~/.claude/agents/browser-leaf.md`:

```diff
-description: … Owns a private Playwright MCP browser instance per invocation — safe to run several in parallel.
+description: … Owns a private Playwright MCP browser instance, but only one concurrent invocation per leaf type — Claude Code shares identical inline MCP server configs across concurrent subagents, so run parallel leaves on distinct types (browser-leaf, browser-leaf-2 … browser-leaf-5, one type per concurrent leaf).
...
-      args: ["-y", "@playwright/mcp@latest", "--headless", "--isolated"]
+      args: ["-y", "@playwright/mcp@latest", "--headless", "--isolated", "--output-dir", "/tmp/claude/pwmcp-leaf-1"]
```

New files `~/.claude/agents/browser-leaf-{2,3,4,5}.md`: same content with `name: browser-leaf-N` and `--output-dir /tmp/claude/pwmcp-leaf-N`. The system-prompt body is unchanged in all five.

This is a workaround for a Claude Code bug, presented as such. Complexity flag: five near-identical files that must stay in sync (and their configs must stay *different* — "cleaning up" the output-dirs to match would silently reintroduce the shared browser), and the orchestrator must assign types round-robin.

## Verification (5 leaves fully concurrent, fresh child session, 23:12)

One leaf per type, five distinctive sites (example.com, wikipedia.org, rust-lang.org, archive.org, python.org), each leaf listing its full tab set three times at 15 s intervals. Whole child session: 93 s (23:12:09→23:13:42); all five leaves' checks interleaved (artifact mtimes 23:12:29–23:13:07 across all five output dirs).

- **Tab evidence:** all 15 listings (5 leaves × 3 checks) showed exactly one tab — the leaf's own site. E.g. leaf 5: `- 0: (current) [Welcome to Python.org](https://www.python.org/)` on every check. Orchestrator summary: "no leaf ever saw another leaf's tab in any of the 15 tab listings." The identical 4-leaf test a few minutes earlier was also 12/12 clean.
- **Process evidence (mid-run):** five `playwright-mcp --headless --isolated --output-dir /tmp/claude/pwmcp-leaf-{1..5}` node processes, and five headless `Google Chrome` roots, each parented to a distinct server (ppid mapping 1:1) with a distinct throwaway profile (`--user-data-dir=…/T/playwright_chromiumdev_profile-<rand>`); monitor showed the count ramp 0→5 servers as leaves connected and back to 0 at teardown. Headless throughout — no window, no Dock icon.

Test prompts, transcripts, and `ps` monitor logs: `/tmp/claude/shipbench-handoff/browser-iso/{baseline,siblings,uniqueargs,final5,logs}/`.

## Caveats

- **Concurrency cap = 5** (one per sibling type). Two concurrent invocations of the *same* type still share a browser — orchestrator discipline required. More siblings can be added mechanically (`browser-leaf-6.md`, `--output-dir …-6`).
- Verified on Claude Code 2.1.220 + `@playwright/mcp` 0.0.78. The `@latest` tag is unpinned; a future version could change behavior (and anthropics/claude-code#34891 reports npm-registry races under concurrent `npx @latest` spawns — pinning a version would harden both).
- If Anthropic later fixes per-instance connections to match the docs, the unique configs stay harmless.
- The browser is headless Google Chrome (user's `/Applications` binary, throwaway temp profile) — separate from and invisible to the user's own Chrome/Vivaldi.

## Recommended doc updates (for the skill/memory maintainer)

- **product-search SKILL.md:** parallel browser leaves must use distinct agent types (`browser-leaf`, `browser-leaf-2` … `browser-leaf-5`), one concurrent leaf per type, max 5 concurrent; never spawn two concurrent leaves on the same type.
- **Memory:** (1) Claude Code inline agent-frontmatter `mcpServers` are deduplicated by config content across concurrent subagents — per-instance isolation requires per-type unique configs (the sub-agents.md claim of per-instance connections is wrong under concurrency, as of 2.1.220). (2) The earlier "2-leaf isolation confirmed" observation was a misread — the extra headless Chromes belonged to Pi `agent_browser`. (3) Every session leaks one idle `npm exec @playwright/mcp@latest` plugin server process.
