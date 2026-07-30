# Shared CDP Browser Phase 0 Result 2026-07-29

Phase 0 gating experiment for the shared-CDP browser plan (`~/.agents/.agents/plans/shared-cdp-browser.md`): **PASS with one flag change, no patch needed.** `@playwright/mcp` 0.0.78 on `--cdp-endpoint` *alone* gives attached instances no isolation at all (the original fail result below), but adding `--isolated` composes correctly: each instance gets its own browser context over CDP, with clean crash and shutdown behavior. Phase 2 wiring must therefore **keep `--isolated` and add `--cdp-endpoint`**, not replace one with the other as the plan text originally said.

## Experiment

One Chrome for Testing 151 (the `chromium-1234` build under `~/Library/Caches/ms-playwright`) launched with `--headless --remote-debugging-port=9222 --user-data-dir=<scratch>`. Two MCP instances from the pinned install at `~/.agents/playwright-mcp`, both started with `--cdp-endpoint http://localhost:9222`, driven concurrently over stdio JSON-RPC. Test pages served from a local HTTP server on `127.0.0.1:8801` instead of example.com/example.org — same-origin pages make the cookie check stricter and avoid external network. Driver script: `$TMPDIR/cdp-exp/experiment.js` (scratch, not committed).

## Result without `--isolated`: shared context *and* shared tab

Worse than the anticipated fail mode (shared tab list / shared storage):

- **Tab hijack by design.** Instance A navigated its page to `/page-a`; instance B's subsequent `browser_navigate` drove the *same tab* to `/page-b`. A's own tab list then showed `/page-b` as its current page. The browser held exactly one page target for both instances.
- **Storage fully shared.** Cookie and localStorage set through A were immediately readable through B.

This exactly recreates the browser-leaf tab-hijacking bug, as the plan's fail criterion anticipated.

## Root cause (source-confirmed)

In `playwright-core/lib/coreBundle.js` (which backs the 0.0.78 MCP), the context factory is:

```js
isolated ? await browser.newContext(config.browser.contextOptions) : browser.contexts()[0]
```

and `isolated` defaults to false whenever a CDP endpoint is configured (a `!browser.cdpEndpoint` term in the default computation). So a CDP-attached instance without `--isolated` takes `browser.contexts()[0]` — the browser's default context — and reuses its current page. But that forced-false computation is only the *default fill-in*: the stdio CLI passes `--isolated` through verbatim, and `createBrowserWithInfo` checks `cdpEndpoint` before `isolated`, so with both flags the instance connects over CDP **and** calls `newContext()` per instance. No source patch required.

## Follow-up: `--cdp-endpoint --isolated` tested — full pass

Same two-instance setup rerun with `--cdp-endpoint http://localhost:9222 --isolated`:

- **Isolation.** Separate tabs per instance; same-origin cookie and localStorage set through A invisible to B; A's state intact after B's activity.
- **Crash cleanup.** SIGKILL of one MCP process removed its browser context and tab from the shared browser within ~3 s (Chrome disposes CDP-created contexts when the owning connection drops). The other instance kept working.
- **Graceful shutdown.** After both clients exited, no leftover contexts; the shared browser survived (Playwright's `close()` on a connected browser only disconnects). The default context's `chrome://newtab` tab is never touched.

This covers Phase 3 items 3–4 at small scale.

## Phase 1–3 rollout (same day)

Daemon: `~/.agents/playwright-mcp/shared-browser.sh` (`start`/`stop`/`status`), usage in [Shared Browser Daemon](README.md). Validation at 4 concurrent MCP instances through the daemon:

- **Isolation under load: PASS.** Four instances on four distinct local origins — each saw exactly its own single tab, and on a common host each saw exactly its own cookie (shared contexts would all show the last-written value). Contexts back to just the default after all four disconnected.
- **Resources.** Browser process trees, macOS RSS (shared pages double-counted the same way in both modes): shared daemon with 4 contexts = 2122 MB / 20 processes; four per-instance Chromiums = 2693 MB / 28 processes. Saving ≈ 570 MB (~21%, ~143 MB/leaf) — more modest than the plan's estimate because per-page renderer processes dominate and exist in both modes. Startup was not improved (4 instances navigated in 4.2 s shared vs 2.9 s per-instance; CDP attach serializes on one browser).
- **Crash behavior: PASS.** SIGKILL of the daemon mid-session → every attached instance's next call returned a clean `### Error` tool result within ~2 ms; none hung. Attaching with no daemon running fails equally fast: `connect ECONNREFUSED ::1:9222`.
- **Leak check: PASS.** Contexts are disposed when their owning connection drops; no cleanup logic needed in the daemon script.

Wiring (option (a) — daemon unconditional, fails loudly when forgotten): the five `browser-leaf*` defs now attach via the pinned install (`/opt/homebrew/bin/node …/cli.js --cdp-endpoint http://localhost:9222 --isolated`, npx eliminated per the cold-start-race finding), and the codex recipe in [Codex Playwright Cold-Start Fix 2026-07-28](<Codex Playwright Cold-Start Fix 2026-07-28.md>) got the same args change. Caveat: Claude Code loads agent defs at session start, so leaves launched from an already-open session still run the old per-instance config (observed: a leaf launched minutes after the edit browsed successfully but never appeared in the daemon's context list). End-to-end confirmed from a fresh session (child `claude -p`): its browser-leaf attached to the daemon as a second context, browsed correctly, and its context was gone after the run.
