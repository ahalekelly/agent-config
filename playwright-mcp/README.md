# Shared Browser Daemon

One long-lived headless Chromium serves every Playwright MCP instance over CDP on fixed port 9377. Each MCP instance attaches with `--cdp-endpoint http://localhost:9377 --isolated` and gets its own private browser context (own cookies, storage, tabs); `--isolated` is mandatory — without it every instance lands in the browser's default context and they hijack each other's tabs.

The port is 9377 rather than CDP's default 9222 so neither side collides with other tooling: the daemon never contends with a legitimate 9222 user (IDE debuggers, a Chrome launched with `--remote-debugging-port`), and a leaf spawning while the daemon is down finds the port closed instead of silently attaching to whatever debug browser happens to be listening — the attaching MCP client does no ownership check. Accepted risk: the CDP port is unauthenticated, so any local process can drive the shared browser; fine on a single-user machine.

```sh
~/.agents/playwright-mcp/shared-browser.sh start   # idempotent — exit 0 if our daemon is already up; safe to fire blind
~/.agents/playwright-mcp/shared-browser.sh status  # pid + watchdog + context count + open pages
~/.agents/playwright-mcp/shared-browser.sh stop    # idempotent — refuses to kill a browser it didn't start; rarely needed, the watchdog stops idle daemons
```

The script must run outside the sandbox (Chrome can't write its crashpad/profile files inside it, and sandboxed Bash has no network anyway). It resolves the newest Chrome for Testing build under `~/Library/Caches/ms-playwright` and logs to `shared-browser.log` beside itself. The daemon launches under `taskpolicy -c utility`, so every Chrome process is QoS-clamped below the user's foreground apps.

Resource rules for anything that attaches: at most 2 tabs open per context, closed as soon as their content is extracted (each open tab holds a renderer process and hundreds of MB — a 14-tab session once reached ~6 GB RSS and froze the machine). The Claude leaf defs carry the tab rule; a codex exec leaf gets it only if the launch prompt includes it.

Idle auto-stop: `start` also spawns a watchdog (an internal `watchdog` verb, one per browser pid) that counts established connections to the CDP port every 30s (via `lsof`, excluding the browser itself) and kills the browser after 5 minutes at zero. A leaf holds its CDP connection for exactly the lifetime of its MCP process, so zero clients means no leaf from any session is attached; connections are the signal rather than contexts or pages because a leaf between tabs has neither (and a pageless context created by another CDP connection is invisible to playwright's `contexts()`). Orchestrators should not run `stop` after a fan-out: the daemon is machine-wide, another session's leaves may still be attached, and shutdown is the watchdog's job. Known gap: a wedged leaf whose MCP process never exits keeps its connection and defers auto-stop indefinitely; `status` shows the attached-client count and open pages.

Ownership is derived from the port, not a pidfile: the listener on 9377 whose command line names the script's profile dir is ours. That makes `start` safe under concurrent invocation (the race loser's Chrome dies on the profile lock and the loser reports the winner's daemon), lets `stop` find orphaned daemons, and makes any *foreign* process on 9377 — e.g. a headed Chrome launched with `--remote-debugging-port` — a hard error on every verb: `start` refuses to share it (leaves must never attach to a visible browser) and `stop` refuses to kill it.

Who attaches: the five `browser-leaf*` Claude agent defs (`~/.claude/agents/browser-leaf*.md`) and the codex exec vendor-leaf recipe ([Codex Playwright Cold-Start Fix 2026-07-28](<Codex Playwright Cold-Start Fix 2026-07-28.md>)) point at the daemon unconditionally. Start it before any browser fan-out; attached calls fail immediately with `ECONNREFUSED :9377` when it's down. Pi's native `agent_browser` is separate and unaffected.

No auto-restart by design: if the browser crashes, every attached MCP call fails loudly (clean `### Error` result within milliseconds, no hangs) and the operator starts it again. Contexts are cleaned up automatically — Chrome disposes a CDP-created context when its owning connection drops, so killed leaves leave nothing behind; `status` showing `contexts: 1` (the untouched default `chrome://new-tab-page`) means no leaks.

The daemon is Chromium and CDP is Chromium-only, so anything needing a different engine — notably headless Firefox, which is the cheap way past Akamai — launches its own browser instead of attaching. [Bot Walls and Browser Engines](<Bot Walls and Browser Engines.md>) covers which engine clears which wall, the launched-mode Firefox leaf config, and how to identify the wall a site is running.

Verified behavior and resource numbers: [Shared CDP Browser Phase 0 Result 2026-07-29](<Shared CDP Browser Phase 0 Result 2026-07-29.md>).
