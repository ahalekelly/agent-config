# Bot Walls and Browser Engines

Which engine to reach for when a site blocks the shared headless Chromium daemon, and what the leaf tooling can actually drive. Findings here were measured on live commercial sites in July 2026; bot-wall vendors tune continuously, so treat the ratings as a starting point and re-probe when a site that used to work stops working.

## Which engine clears which wall

| Detected wall | Path | Confidence |
|---|---|---|
| None / light | Shared Chromium daemon (the default leaf) | — |
| Cloudflare | Usually just CDN, not a challenge. Try the default leaf first, escalate only on a real interstitial | untested in depth |
| **Akamai** | **Launched-mode Firefox leaf** (recipe below), or **cloakbrowser headless** if you need Chromium | live-confirmed, both |
| **DataDome**, alone or stacked | No headless engine works. Headed patchright/cloakbrowser driven via background computer-use, or avoid the browser entirely | live-confirmed negative |
| **PerimeterX** | Behaves like DataDome; headless Firefox is blocked | one live data point |

**No headless browser beats production DataDome.** Five configurations — plain Playwright Firefox, camoufox, tf-playwright-stealth-firefox, cloakbrowser, and cloakbrowser driven by patchright — were 403'd identically on live DataDome sites despite several of them passing DataDome in the [browsers-benchmark](https://github.com/techinz/browsers-benchmark) suite. The benchmark's DataDome targets are the vendor's own marketing site and a fashion retailer, which are far softer than a distributor protecting pricing and inventory. `cloakbrowser` is the decisive case: it scores well headless in the benchmark and still returns a `captcha-delivery` challenge on every real vendor. Don't spend time hunting a headless DataDome bypass.

**Akamai is the opposite case — several engines clear it headless.** Plain Firefox is the cheapest and needs no stealth patch. Where the leaf has to be Chromium, a fingerprint-patched Chromium (cloakbrowser or its upstream, below) clears both the benchmark's Akamai target and a live Akamai-only vendor with a real rendered page. All are free and invisible.

**Prefer fingerprint-chromium to cloakbrowser.** cloakbrowser is a fork of [fingerprint-chromium](https://github.com/adryfish/fingerprint-chromium), which is BSD-3 licensed, tracks a newer Chromium, ships a macOS arm64 build, and removes the `HeadlessChrome` product name in C++ unconditionally. It also disables `Runtime.enable` in the binary, which is more durable than a driver-side patch since no client upgrade can undo it. Measured headless on the same targets the two score the same overall, differing on which they clear; the upstream is slightly lighter. Its one real deficit is that WebGL vendor/renderer spoofing is Linux-only, so on macOS it reports the true GPU while cloakbrowser reports a fabricated one.

DataDome is also **adaptive** — a site served a first-hit 200 to a bare probe, then 403'd focused repeat visits. A single 200 is not proof of a bypass; probe more than once.

Where a browser isn't strictly required, the reliable escape is not to drive the walled HTML at all: sites' own JSON APIs (platform cart and rate endpoints, search APIs) stay open because blocking them breaks the site itself.

## What the leaf tooling can drive

The leaves run `@playwright/mcp` (pinned in this directory) and today all attach to the shared Chromium daemon over CDP. That shapes what is reachable:

- **CDP is Chromium-only.** Firefox cannot be driven over CDP, so a Firefox leaf must launch its own browser instead of attaching to the daemon. Functionally fine — leaves are isolated from each other anyway — but it costs a browser process per leaf, so the 2-tab rule matters more, not less.
- **`--browser` accepts only `chrome`, `firefox`, `webkit`, `msedge`,** but **`--config` exposes the full Playwright `launchOptions`** — `executablePath`, `args`, `ignoreDefaultArgs`, `env`, plus `contextOptions`. Any engine whose stealth is a patched binary driven by launch flags is therefore reachable from the MCP alone, with no second driver process.
- **`--endpoint <ws url>`** connects to an existing **Playwright server** (`browserType.connect()`), not a CDP endpoint. Unlike `--cdp-endpoint` this is browser-agnostic, so it is the hook for any engine that can expose a Playwright server.
- **`--init-script <path>`** adds a JavaScript file evaluated in every page before the page's own scripts, and **`--init-page <path>`** evaluates TypeScript against the Playwright page object (`export default async ({ page }) => …`), which is the escape hatch for anything the page context can't do, such as `setExtraHTTPHeaders`.
- **`--user-agent`** sets the real context UA, on the wire and in JS, because it routes through `Network.setUserAgentOverride` with matching metadata. Chromium's **own** `--user-agent` command-line flag is a trap by comparison: it changes the string while leaving the low-entropy client hints reporting real values and blanking every high-entropy hint, a combination no genuine Chrome produces. Use the MCP flag, never the browser flag. An evasion bundle that spoofs the UA only in JS has the same problem in reverse.

**One fingerprint per browser process.** Isolated contexts do not get isolated fingerprints — the seed is process-level, so every context on a daemon returns identical canvas hashes, WebGL strings, and screen metrics. All leaves sharing a daemon therefore look like one device, which correlates them if they hit the same target. Run separate daemons where that matters.

For driving via MCP rather than raw scripts, the alternatives are `stealth-browser-mcp` (nodriver + CDP, standalone page driver) and AdsPower's LocalAPI MCP (a profile manager that hands back a CDP endpoint, not a page driver). `patchright-mcp-lite` is not worth using — an unpublished GitHub-only repo abandoned after a single day of work, launching plain `chromium.launch()` in violation of patchright's own guidance. Upstream `@playwright/mcp` has no stealth support and the maintainers closed the PR that proposed it.

## Playwright itself is a tell

Every stock Playwright page — launched or attached — gets `Runtime.enable`, `Log.enable`, `Page.createIsolatedWorld`, and `Page.addScriptToEvaluateOnNewDocument` during frame-session init. Anti-bot vendors probe these directly; the `rebrowser-bot-detector` suite names two of them `runtimeEnableLeak` and `pwInitScripts`. This is a floor on how stealthy any Playwright-driven browser can be, ours included.

**Patchright lifts that floor, and it composes with the MCP as a package swap.** It is a fork of playwright-core that rewrites `Frame._context()` to derive the execution context from a `Runtime.evaluate` object handle instead of subscribing to context-created events, which removes `Runtime.enable` from the Chromium page path entirely; the utility world is then created lazily and named plainly rather than `__playwright_utility_world_page@<hash>`. Because those patches live in `Frame._context()` and `FrameSession._initialize()`, which the attach path funnels through identically, **they apply over `connectOverCDP` as well as on launch** — measured on a stock Chromium daemon, `Runtime.enable` calls drop from 5 to 0 with no browser-side change.

The swap is mechanical: `@playwright/mcp` is a shim around `playwright-core`'s bundle, and patchright-core exports the same surface including the MCP entry points, so aliasing `playwright-core` to `patchright-core` yields a patchright-driven MCP that keeps every flag. Three costs, all real. You inherit the MCP version bundled in patchright's core rather than the pinned one. `Console.enable` is disabled by design, so console tooling degrades. And main-world globals become unreadable from `evaluate`, which breaks the common "read a value the page set" pattern.

**Stacking patchright with cloakbrowser works, and closes both layers at once.** Launch cloakbrowser's patched binary as a bare process carrying its own stealth flags plus `--remote-debugging-port` and `--disable-blink-features=AutomationControlled`, then attach patchright over CDP. Measured together, that browser sends zero `Runtime.enable` calls, reports `Chrome/145` rather than `HeadlessChrome`, leaves `navigator.webdriver` false, and exposes a real GPU renderer instead of SwiftShader. Launch the binary directly rather than through cloakbrowser's own Playwright wrapper: a stock Playwright client on the same browser auto-attaches to every new page and re-emits exactly the commands patchright suppresses.

Measured against bot walls, though, the stack scores no better than cloakbrowser alone, and both fail the same live vendors. Patchright's contribution is a lower detection floor, not a wall bypass — these walls appear to key on browser-layer signals that patchright by design does not touch.

What patchright does **not** do is hide headless. It patches the client layer only; the browser still reports `HeadlessChrome` in its user agent, and the maintainers state plainly that headless Chromium cannot be made undetectable without patching Chromium itself. That is why patchright clears every benchmark wall headed and few of them headless. Its value here is a lower detection floor for all leaves, not a wall bypass — and it stacks with a browser-layer engine, since the two patch disjoint layers.

It also rules out a whole engine family. **CDP-minimal drivers — zendriver, nodriver, selenium-driverless — get their stealth from *not sending* those commands, so attaching Playwright to one destroys the property it exists to provide.** Worse, it is not containable: `connectOverCDP` issues `Target.setAutoAttach` with no target-type filter, so Playwright initializes every existing and future page in that browser, including tabs the native driver is using. Driving these engines means replacing the MCP, not configuring it.

## Per-engine integration routes

- **cloakbrowser** — the cheapest fork to adopt. Its stealth is entirely the patched binary plus launch flags (`--fingerprint=<random seed>`, `--fingerprint-platform`), with `ignoreDefaultArgs: ["--enable-automation", "--enable-unsafe-swiftshader"]` — dropping `--enable-automation` is mandatory, since Playwright adds it by default and it exposes `navigator.webdriver`. No init scripts, no CDP work, no Python at runtime: an MCP `--config` reproduces it exactly. Set the viewport explicitly, because Playwright's emulated default produces `outerWidth < innerWidth`, a physically impossible window. Its `humanize` cursor layer is Python-only and doesn't come along.
- **camoufox** — the fingerprint is delivered as chunked `CAMOU_CONFIG_*` environment variables and Firefox prefs on the browser process at launch, so it is process-global and **is** inherited by a remote `browserType.connect()` client. Server mode is `launch_server(headless=True, port=…, ws_path=…)` from Python; the `camoufox server` CLI takes no options and defaults to headed, so it isn't usable as a configured daemon. Three costs: a Python daemon in an otherwise node-only setup, a Playwright client/server minor-version match (camoufox pins `playwright<1.61`), and an explicit viewport — Playwright's default deadlocks Juggler when the window is spoofed to a different size. Per-context fingerprint rotation is applied by the Python client and does not reach a remote one, so a server serves one fixed identity.
- **patchright** — alias `playwright-core` to `patchright-core`; the leaf keeps `--cdp-endpoint --isolated` unchanged. Add `--disable-blink-features=AutomationControlled` to the daemon's own argv, since that part of patchright is a launch flag and doesn't reach an attached client. See the section above for what it buys and costs.
- **tf-playwright-stealth** — the evasions genuinely are one concatenated init script (`utils.js` must come first), so `--init-script` covers all of it but one call: `set_extra_http_headers`, which sets the UA and `sec-ch-ua*` headers at the HTTP layer. Close that with `--user-agent` matching the value baked into the script, or with `--init-page`. Note it is the weakest of these engines — the older puppeteer-extra evasion set.

**The DataDome route is headed, not headless.** macOS has no Xvfb equivalent and no way to render a headed Chromium invisibly: Chrome for macOS has no Ozone/X11 backend, offscreen window positions are clamped back on screen, and hiding or minimizing the window makes screenshot capture time out. The only genuine invisible-headed route is a second user account left logged in via fast user switching, which costs a full GUI session's memory. Short of that, Codex Computer Use and the open-source `cua-driver` (trycua/cua) drive a real headed app *behind* the current window — no focus steal, no cursor move, no Space switch — via SkyLight `SLEventPostToPid` and focus-without-raise. That is the macOS equivalent of "headed but invisible". It costs GUI/vision-level driving (slow, token-heavy, less deterministic than DOM/CDP), needs Accessibility and Screen Recording permissions, and must run unsandboxed. Reserve it for walled, high-stakes targets. Whether it actually clears live DataDome is unproven.

## Launched-mode Firefox leaf

For Akamai-only sites. Same MCP, no daemon: drop `--cdp-endpoint` and let the MCP launch its own headless Firefox.

```yaml
mcpServers:
  - playwright:
      type: stdio
      command: /opt/homebrew/bin/node
      args: ["/Users/akelly/.agents/playwright-mcp/node_modules/@playwright/mcp/cli.js",
             "--browser", "firefox", "--headless", "--isolated",
             "--output-dir", "/tmp/claude/pwmcp-ff-1"]
```

A leaf using this config needs a system prompt that differs from the shared-daemon leaves in one respect: those are told never to launch a browser and to report `ECONNREFUSED :9377` as a daemon-down failure, neither of which applies here. Every other rule — headless only, 2-tab cap, temp-dir-only writes, read-only by default — carries over unchanged.

Firefox builds are already installed under `~/Library/Caches/ms-playwright`. Verified end to end through the MCP: an Akamai-only vendor returned a real rendered page, a DataDome vendor returned HTTP 403.

## Detecting the wall

Load the homepage and inspect cookies and body. The MCP reports HTTP status in its navigate result, so a 403 is visible to a leaf without extra work.

| Wall | Markers |
|---|---|
| Akamai Bot Manager | cookies `_abck`, `bm_sz`, `ak_bmsc`, `bm_sv`, `bm_lso`; body contains `bazadebezolkohpepadr` or an `/akam/` script |
| DataDome | cookie `datadome`; body contains `captcha-delivery` or `dd={` |
| Cloudflare | cookies `__cf_bm`, `cf_clearance`, header `cf-ray` — often only CDN |
| PerimeterX | cookies `_px*`, `pxcts` |

A soft 200 challenge is possible, so a 200 alone doesn't prove the page is real — check the body or a screenshot when it matters.

## Running the engines directly

For raw scripts outside the MCP:

- **Playwright Firefox** — `node_modules/.bin/playwright install firefox` (node) or `python -m playwright install firefox`; `firefox.launch({headless: true})`.
- **camoufox** — `uv run --with camoufox python -m camoufox fetch`, then `from camoufox.sync_api import Camoufox; Camoufox(headless=True)`. Binary in `~/Library/Caches/camoufox`.
- **tf-playwright-stealth** — `uv run --with tf-playwright-stealth --with playwright …`; `from playwright_stealth import stealth_sync; stealth_sync(page)` per page.
- **cloakbrowser** — `pip install cloakbrowser`, free tier, no license; binary auto-downloads to `~/.cloakbrowser` (Chromium 145). `cloakbrowser.launch(headless=True)` returns a Playwright Browser.

All browser launches must be unsandboxed — the sandbox has no network and Chrome can't write its profile files inside it.

## Basis

Engine-vs-wall scores come from a single [browsers-benchmark](https://github.com/techinz/browsers-benchmark) run (23 engine configs × 10 targets, n=1 per target — a snapshot, not a constant). Its headline result is that **headed dominates**: patchright headed clears 10/10, and headless Chromium stealth clears no Akamai target at all. Its DataDome results do not survive contact with real sites, which is why the table above leads with live evidence.

The live probes, the per-vendor wall map, and the benchmark data live in `~/.agents/skills/product-search/dev/` alongside the shipping-quote strategy they were gathered for.
