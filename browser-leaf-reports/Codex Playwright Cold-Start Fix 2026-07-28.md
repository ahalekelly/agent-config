# Codex Playwright Cold-Start Fix 2026-07-28

Investigation of the 2/5 failures in the 2026-07-28 shipping-cost benchmark's parallel `codex exec` + Playwright MCP launches. Written 2026-07-28 ~23:30.

## TL;DR

It was never a cold-start race, and the Playwright MCP server was never the thing that failed. The OpenSSL error came from codex's **node_repl** MCP server (the ChatGPT.app-bundled `cua_node`), whose kernel crashes **100% deterministically** under codex's seatbelt sandbox on this machine: the bundled Node reads `/System/Library/OpenSSL/openssl.cnf` at startup, the sandbox denies that specific directory (EPERM), and Node treats a non-ENOENT config error as fatal. The 3/5-vs-2/5 split was pure agent tool-choice variance: the bundled Browser skill tells agents that *only* node_repl may control the browser and that "Playwright" means its in-skill `tab.playwright` API, so two of the five agents obeyed the skill, hit the dead kernel, and gave up — the other three used the `playwright` MCP tools directly and succeeded. Serial retries "fixed" it only because those agents happened to pick the playwright MCP.

The fix is a one-flag seatbelt grant plus a pinned, pre-installed Playwright MCP (a concurrent-`npx` race is real as a separate latent issue — reproduced below). The fixed recipe passed **15/15** fresh simultaneous launches.

## Root cause, with evidence

**1. The error text, located.** The two failed benchmark sessions (`~/.codex/sessions/2026/07/28/rollout-2026-07-28T21-54-41-*71f1*` and `*73a0*`) contain zero playwright MCP tool calls. Each failure is a `node_repl` `js` call returning:

```
node_repl kernel exited unexpectedly
kernel_stderr_tail: /Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node:
OpenSSL configuration error: 80DDB5F201000000:error:80000001:system library:BIO_new_file:
Operation not permitted:...bss_file.c:67:calling fopen(/System/Library/OpenSSL//openssl.cnf, rb)
```

The three successful sessions show normal `playwright` server calls (`browser_navigate`, `browser_snapshot`, …). So the failing process was the ChatGPT-app-bundled Node kernel that codex's `mcp_servers.node_repl` spawns — not `npx`, not `@playwright/mcp`, not Chromium.

**2. Why the agents went there.** The prompts said "using your `playwright` MCP tools only", but the bundled Browser skill (from the `chrome@openai-bundled` plugin) that got pulled into the failed sessions says:

> "Only the Node REPL `js` tool (`mcp__node_repl__js`) can be used to control the selected browser. Do not use external MCP browser-control tools, separate browser automation servers, or other browser skills for this surface. References to Playwright mean the in-skill `tab.playwright` API after browser-client setup."

Two agents followed the skill; three ignored it. That's the entire "probabilistic" behavior.

**3. The crash is deterministic, not a race.**

- The identical kernel crash appears in **Codex Desktop sessions on 2026-07-27** — the day before, serial, no parallelism (`rollout-2026-07-27T18-54-26-*`, `18-56-44-*`, `19-08-51-*`, `19-10-53-*`).
- No model, no concurrency needed: `codex sandbox -- /Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node -e 'console.log(1)'` reproduces the exact error every time.
- A single serial `codex exec` run (gpt-5.6-terra, prompt "use node_repl js to evaluate 6\*7") reproduced the exact benchmark error on the first try.

**4. Why EPERM.** The file is world-readable outside the sandbox, and codex's seatbelt allows `/System/Library` reads generally (`/System/Library/CoreServices/SystemVersion.plist` reads fine) — but denies `/System/Library/OpenSSL` specifically (`cat` under `codex sandbox` → "Operation not permitted"). This looks like a codex built-in sensitive-path deny (the directory contains a `private/` key dir). Homebrew Node is unaffected (its OpenSSL config lives under `/opt/homebrew`, which the user's `workspace_sandbox` profile grants). `cua_node` (Node v24, custom build) has `/System/Library/OpenSSL/` baked in as OPENSSLDIR; seatbelt turns the probe's ENOENT-tolerated `fopen` into a fatal EPERM.

**5. The npx race is real — but it's a different, latent bug.** Five concurrent `npx -y @playwright/mcp@latest --version` cold starts against one fresh npm cache: round 1 (pinned `@0.0.41`) 5/5 ok; round 2 (`@latest`) **4/5**, the loser crashing with `Cannot find module './utilsBundle'` from a partially-extracted `_npx` tree. It didn't cause the benchmark failures (the cache was warm from the 21:37 smoke test, and the failed runs never touched playwright), but it will eventually bite any truly-cold parallel launch, so the fixed recipe eliminates npx entirely.

## Fixed launch recipe (verified)

One-time setup (already done, pinned to current latest 0.0.78):

```sh
mkdir -p ~/.agents/playwright-mcp && cd ~/.agents/playwright-mcp
npm install --no-fund --no-audit @playwright/mcp@0.0.78
```

Per-run command (replaces the old recipe):

```sh
/opt/homebrew/bin/codex exec --skip-git-repo-check -C <scratchdir> \
  -m gpt-5.6-terra -c model_reasoning_effort="medium" \
  -c permissions.workspace_sandbox.filesystem./System/Library/OpenSSL=read \
  -c 'mcp_servers.playwright.command="/opt/homebrew/bin/node"' \
  -c 'mcp_servers.playwright.args=["/Users/akelly/.agents/playwright-mcp/node_modules/@playwright/mcp/cli.js","--cdp-endpoint","http://localhost:9377","--isolated"]' \
  -c 'mcp_servers.node_repl.env.BROWSER_USE_AVAILABLE_BACKENDS=""' \
  -o last.txt - < prompt.md > run.log 2>&1
```

What each change does:

- **OpenSSL seatbelt grant** — fixes the node_repl kernel crash at its root; node_repl works again for compute (verified: returns `42`). Note the flag must be written **unquoted** exactly as above: codex's `-c` dotted-path parser does not strip quotes from key segments, so the natural `-c 'permissions...."/System/Library/OpenSSL"="read"'` form is rejected with "path must be absolute".
- **Pinned playwright MCP via node** — no npm/npx work at launch, so parallel cold starts have nothing to race on, and `@latest` version drift can't change behavior mid-benchmark.
- **Shared browser over CDP** — the MCP attaches to the shared headless browser daemon as its own isolated context instead of launching a browser per instance (`--isolated` is required: without it every instance lands in the browser's default context and they hijack each other's tabs). Start the daemon before launching runs: `~/.agents/playwright-mcp/shared-browser.sh start`; runs fail immediately with `ECONNREFUSED :9377` when it's down. Details in [Shared Browser Daemon](README.md).
- **`BROWSER_USE_AVAILABLE_BACKENDS=""` on the node_repl server** — with the kernel fixed, an agent that follows the Browser skill could otherwise reach the `chrome`/`iab` backends (the user's visible Chrome / the desktop in-app browser). Emptying the backend list on the server keeps headless runs headless and pushes agents back to the playwright MCP. The old recipe's `shell_environment_policy.set.BROWSER_USE_AVAILABLE_BACKENDS="iab"` never affected node_repl at all — that policy applies to shell commands, while `[mcp_servers.node_repl.env]` in config.toml sets its own value (`"chrome,iab"`).

**Update, same evening:** on the user's request the grant is now permanent in `~/.codex/config.toml` — this line was added to `[permissions.workspace_sandbox.filesystem]` and verified against the live config:

```toml
"/System/Library/OpenSSL" = "read"
```

With that in place the per-run `-c permissions...` flag is redundant on this machine (keep it for portability to machines without the config line).

## Verification

All runs gpt-5.6-terra, medium effort, scratch dirs under `/tmp/claude/shipbench-handoff/codex-race/` (artifacts left in place: `a1`, `b1`, `c1`–`c3`, `npxcold`, `probe`).

| Test | Recipe | Result |
|---|---|---|
| `codex sandbox` + cua_node direct | original | fails, exact benchmark error, every time |
| 1× `codex exec`, node_repl 6\*7 prompt | original | kernel crash, exact benchmark error |
| 1× `codex exec`, node_repl 6\*7 prompt | + OpenSSL grant | `42` |
| 5× concurrent npx cold start, pinned `@0.0.41` | shared fresh cache | 5/5 ok |
| 5× concurrent npx cold start, `@latest` | shared fresh cache | **4/5** — module-not-found crash |
| 3 rounds × 5 simultaneous `codex exec`, example.com via playwright MCP | fixed recipe | **15/15** "Example Domain" |

Given the original ~40% per-run failure mode was a deterministic crash gated on agent tool choice, the combination of (a) root-cause elimination verified directly and (b) 15/15 end-to-end passes is far stronger evidence than any number of stochastic re-rolls of the original recipe.

## Recommended doc updates (for the skill/memory maintainer)

- **Correct the benchmark note.** "Shipping Cost Benchmark 2026-07-28.md" §"codex parallel cold-start race" attributes the failures to launching five npx servers simultaneously and advises staggering launches. Both are wrong: staggering does nothing (the crash is deterministic and also occurred in serial Desktop sessions on 07-27). Replace with a pointer to this report's recipe.
- **Skill/recipe for codex browser runs:** use the fixed command above verbatim — pinned MCP path, OpenSSL grant flag, empty `BROWSER_USE_AVAILABLE_BACKENDS` for the node_repl server; drop the ineffective `shell_environment_policy.set.BROWSER_USE_AVAILABLE_BACKENDS="iab"` flag. Worth noting the `-c` quoting gotcha for path-keyed permissions.
- **Maintenance note for the pin:** update with `cd ~/.agents/playwright-mcp && npm install @playwright/mcp@<new-version>`; if a new version bumps its bundled playwright-core to a browser build not yet in `~/Library/Caches/ms-playwright`, run its browser install once before parallel use.
- **Memory-worthy facts:** (1) codex's seatbelt denies `/System/Library/OpenSSL` specifically, which kills the ChatGPT-bundled `cua_node` (node_repl kernel) on any sandboxed run until the grant is added — this affects *all* node_repl use, not just browser work; (2) the bundled Browser skill hijacks the word "Playwright" and forbids external MCP browser tools, so prompts saying "use playwright MCP" do not reliably steer codex agents while `chrome@openai-bundled` is enabled; (3) concurrent cold `npx -y <pkg>@latest` starts against a shared npm cache can crash with partially-extracted module trees — pre-install anything launched in parallel.
