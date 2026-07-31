# product-search dev memory — bot-walls & shipping quotes

Working notes on reaching vendor data — **shipping quotes and product detail** — without fighting bot walls. Artifacts in this folder: `benchmark_results.json` (reference engine benchmark), `benchmark_results-2026-07-30-headless-local.json` (local rerun, six headless configurations), `benchmark-plots-2026-07-30.html` (scatter plots + live-finding annotations).

The headline shift: **the platform storefront APIs solved the problem the browser work was trying to solve.** Shopify, WooCommerce, open-guest-API Magento, BigCommerce Stencil, and Squarespace hand real shipping quotes and structured product data to anonymous callers, so the engine-versus-wall research below now matters only for the residue — unsupported storefront runtimes, challenged endpoints, and vendors like Amazon whose data is reachable no other way.

## Bottom line (read this first)

1. **No headless browser beats production DataDome.** Seven configurations — plain Playwright Firefox, camoufox, tf-playwright-stealth (both engines), cloakbrowser, cloakbrowser+patchright, and fingerprint-chromium+patchright, all headless — were 403'd identically on live DataDome sites, several of them despite passing DataDome in the benchmark. The benchmark's DataDome targets (the vendor's own marketing site, a fashion retailer) are far softer than a distributor guarding pricing. Don't chase a headless DataDome bypass.
2. **Akamai-only vendors are cheap:** plain Playwright **Firefox headless** loads them fine (no stealth patch needed), invisibly and for free. A **fingerprint-patched Chromium** also clears Akamai and, being Chromium, can serve a shared CDP daemon that Firefox cannot. Both confirmed live on Master Electronics.
3. **Amazon needs a browser, and the engine choice matters.** There is no browser-free path: across three listings, `WebFetch` on `/dp/` URLs returned HTTP 500 or a body-less shell every time, and web search returned only the listing title — no price, stock, seller, or Prime status from either, with the only prices on offer being stale aggregator figures. Product pages do load for patchright, tf-playwright-stealth, and fingerprint-chromium+patchright, and fail only for cloakbrowser, so pick the engine accordingly.
4. **DataDome vendors (alone or stacked) need one of:** headed patchright/cloakbrowser driven invisibly via **background computer-use (cua-driver / Codex Computer Use)**, or a **non-quote data source** (published policy, carrier estimate, platform cart API). This is the main unproven step — see Open questions.
5. **Prefer avoiding the browser entirely** where possible: platform cart APIs and carrier-rate estimates are the general cold-paths that sidestep bot-walls, because they don't drive the walled HTML.

## Strategy

Get one **representative shipping quote per store**, cache it in `vendors.md`, reuse for any order that isn't heavy/oversized (live per-order quotes only for heavy/oversized). The methods below are mechanisms for getting that representative quote.

**Open-world long tail.** The workflow runs across many searches against an open-ended vendor set — most stores seen once, **not** limited to `vendors.md`. Design for an arbitrary unknown store with zero prior setup. This splits the methods:

- **General cold-path methods** (zero per-vendor setup, generalize to unknown stores — these carry the tail):
  - **Platform cart APIs — validated, and they replace the browser for most of the tail.** Shopify's Storefront GraphQL API grants **tokenless** cart read/write: `cartCreate` with the destination in `buyerIdentity`, then `deliveryGroups(withCarrierRates: true)` inside `@defer`. Verified live across a dozen stores plus an independent replication — real rates, ~1s per quote, no credentials, and it captures vendor economics a carrier API cannot (free-shipping thresholds that reshape the whole rate table at higher quantities, ShipperHQ/ShipBob apps, a $510 freight estimate on an LTL item, destination refusals). Works on headless storefronts where `/cart.js` 404s. WooCommerce's Store API is likewise unauthenticated via the `Cart-Token` header, and unlike Shopify returns populated `taxes`. Shopify is pre-tax only — `totalTaxAmount` is deprecated and null. Magento's guest-cart REST flow works where a store leaves the guest API open. BigCommerce Stencil also has a generic browserless workflow: create `/api/storefront/carts`, then create a checkout consignment with the returned `SHOP_SESSION_TOKEN` and `SF-CSRF-TOKEN`; this quoted 11/11 stores in the 2026-07-31 corpus. The older `/cart.php` plus `/remote/v1/shipping-quote` path also works when its XSRF cookie is echoed, but is not the primary path. Carrier APIs answer the wrong question entirely. Trap on all platforms: an empty rate list means no quote, never free.
  - **Carrier-rate estimate** — item weight (usually on the product page) + **the carrier/service the vendor uses** → a carrier rate API (EasyPost / Shippo). The carrier list is the hard input, more than warehouse origin: the vendor's charge tracks its carrier + service choice, so without it you can't pick the right rate to quote (origin only needs a rough region). Works only when the site states its carriers.
  - **Headed background computer-use** (cua-driver / Codex Computer Use) — universal fallback; drives a real headed browser cold on any store's GUI, invisibly. Slow and token-heavy → reserve for walled, high-stakes finalists.
- **Per-vendor learned optimizations** (only pay off on the recurring head — optimizations, not the strategy): representative-quote cache; record-once/replay-cheap (capture the checkout XHR from a successful browser run, cache the endpoint, replay as one HTTP request). Auto-populate into `vendors.md`.

`vendors.md` shifts from a hand-curated list to **curated head + auto-growing learned cache** keyed by domain (platform, working endpoint, origin, carrier, representative quote, bot-wall status). Unknown vendor → run the general cold-path → write back what was learned.

`scripts/platform_api.py` is the production cold-path helper. It implements product search for Shopify, WooCommerce, Magento, BigCommerce, Squarespace, Wix, Ecwid, and SFCC; the first five also implement destination quotes, while the last three return explicit browser-required quote boundaries. It emits sanitized JSON and runs resumable bounded corpora. Its opaque item references are platform-specific and must be passed through exactly as returned.

**Escalate by stakes:** most one-off tail vendors need only a rough estimate to tell whether shipping flips the ranking. Spend a precise cart quote only on serious contenders.

## Cold-path decision by wall type (the actionable recommendation)

| Detected wall | Recommended path | Basis |
|---|---|---|
| None / light | Platform cart API or plain fetch; carrier estimate | — |
| **Akamai only** | **Plain Playwright Firefox headless** (invisible, free); else platform cart API / carrier estimate | live-confirmed |
| **DataDome** (alone or + Akamai) | Headed patchright/cloakbrowser via **cua-driver background computer-use**; or non-quote source (published policy / carrier estimate / cart API) | live-confirmed no headless works |
| **PerimeterX** | Treat like DataDome (headless plain-FF blocked live); headed/computer-use or non-quote source | 1 live data point |
| **Cloudflare** (CDN vs challenge) | Often just CDN; try the standard API because challenge behavior can differ by endpoint, then escalate only the blocked operation | live-confirmed on BigCommerce and tracked bot-wall stores |

## Evidence — local headless rerun (2026-07-30)

`benchmark_results-2026-07-30-headless-local.json`, run from this machine's own IP with proxies disabled, six headless configurations against the same ten targets. Rates: patchright 4/10, tf-stealth-chromium 5/10, tf-stealth-firefox 6/10, cloakbrowser 7/10, cloakbrowser+patchright 6/10, **fingerprint-chromium+patchright 7/10**. Cloudflare, PerimeterX and Reddit passed for everything; Google Search and one DataDome target failed for everything; the discriminating targets were the second DataDome site, Amazon, Ticketmaster, Akamai, and Kasada.

Two conclusions. **Akamai now has a Chromium answer** — both patched builds clear it where every stock engine fails. And **cloakbrowser is an unattributed fork of [fingerprint-chromium](https://github.com/adryfish/fingerprint-chromium)**, which is BSD-3, free, tracks a newer Chromium, and scores the same; prefer the upstream, accepting that its WebGL spoofing is Linux-only so on macOS it leaks the real GPU. Rates agreed closely with the reference run despite different hardware, a two-month gap, and no proxy, which suggests these measure engine capability rather than IP reputation. Still n=1 per target — don't over-read single-target differences, especially on DataDome, which tightens on repeat visits.

## Evidence — benchmark

Source: `benchmark_results.json`, from [techinz/browsers-benchmark](https://github.com/techinz/browsers-benchmark) example run dated 2026-05-26. **Single run, n=1 per target** — a snapshot, not a constant. 23 engine configs × 10 bot-wall targets. Plots: `benchmark-plots-2026-07-30.html`.

- **Headed dominates.** patchright (headed) bypasses 10/10 (1.00); the top scorers are generally headed. patchright_headless only 0.40.
- **Akamai (`akamai_protected`) is the benchmark's hardest wall** — only 3 of 23 pass: patchright (headed), cloakbrowser (headed), and **playwright-firefox_headless** (the only headless passer). No Chromium stealth clears it headless.
- **DataDome / PerimeterX** — softer in the benchmark: `camoufox_headless` passes both DataDome targets + PerimeterX; plain `playwright-firefox_headless` fails all three. This predicted a wall-specific split (Akamai→Firefox, DataDome→camoufox) that **did not survive live** (below).
- Headless engines passing ≥1 DataDome target: camoufox_headless, cloakbrowser_headless (both), tf-playwright-stealth-firefox_headless, adspower_headless. Everything else headless fails both.

## Evidence — live tests (2026-07-30)

**Akamai-only** (Master Electronics): plain Firefox headless **passes** — HTTP 200, real rendered homepage (screenshot-confirmed). camoufox headless also passes (adds nothing).

**DataDome — four headless engines, all blocked** (403 `captcha-delivery`, or Akamai sensor on stacked sites):

| Engine (headless) | Grainger (DD-only) | SeatGeek (DD-only) | Mouser (Akamai+DD) |
|---|---|---|---|
| plain Playwright Firefox | 403 | 403 (home+deep) | 403 |
| camoufox | 403 | 403 | 403 |
| tf-playwright-stealth-firefox | 403 | 403 | — |
| cloakbrowser | 403 | 403 | 403 |

`cloakbrowser_headless` is the decisive negative: open-source, free-tier (`pip install cloakbrowser`, source-level-patched Chromium 145), and the benchmark's *strongest* headless DataDome scorer — still 403'd everywhere. **DataDome is adaptive**: SeatGeek served a first-hit 200 to a bare probe, then 403 on focused repeat visits, so a lone 200 is not a bypass. Only `adspower_headless` (commercial) remains untested among benchmark DataDome-passers; expectation near zero given the above.

Incidental: The RealReal (PerimeterX-only) also 403'd plain Firefox headless (matches benchmark Firefox-fails-PerimeterX; camoufox untested there).

## Live wall map (probed 2026-07-30, plain Firefox headless; status = FF-headless result)

| Vendor | Detected protection | FF headless |
|---|---|---|
| Mouser | **Akamai + DataDome** | 403 blocked |
| Zoro | **Akamai + DataDome** | 403 blocked |
| Grainger | **DataDome only** | 403 blocked |
| Master Electronics | Akamai (+ Cloudflare CDN) | 200, real content ✓ |
| Omega | Akamai (+ Cloudflare CDN) | 200 |
| Lowes | Akamai | 200 |
| Misumi | Akamai (+ Cloudflare CDN) | 200 |
| Arrow | Akamai | 200 (loaded fine despite `vendors.md` "TLS reset" note) |
| LCSC | none detected on homepage | 200 |
| FootLocker | Akamai only | 200 (incidental, non-`vendors.md`) |

**Akamai+DataDome sites = Mouser and Zoro.** Resolves the `vendors.md` "Zoro / Grainger … (DataDome / Akamai)" ambiguity: **not** a per-vendor split — **Zoro runs both, Grainger runs DataDome only.** Every live 403 lines up exactly with DataDome presence; Akamai-only sites all returned 200. Caveat: only Master Electronics was content-verified; other 200s weren't hard-blocked but bodies weren't confirmed real (soft 200 challenge not ruled out).

The Zoro/Grainger split, Arrow reachability, and the platform census below are reflected in `vendors.md` (2026-07-30).

## Evidence — platform census and corpus validation (2026-07-30–31)

All ~29 `vendors.md` domains probed for platform (Shopify GraphQL, WooCommerce Store API, Magento guest-carts, homepage markers). Two traps the probe hit: **apex domains 301 to `www.` and the API endpoints don't follow** — probe the resolved host, or every result is a false negative; and **the storefront can live on a different domain** (mettleair.com → mettleairstore.com), so resolve the homepage redirect first.

Results: **Shopify** = DERNORD (dernord.com) and Mettle Air (mettleairstore.com), both verified end-to-end with tokenless cart quotes (Mettle Air returned four live UPS-tier rates; DERNORD one flat $55 "FeDex" rate on a $10 item — vendor economics no carrier API would predict). **Magento** = SparkFun, with the guest API **open**: unauthenticated `guest-carts` → `items` → `estimate-shipping-methods` returned live ShipperHQ rates. **BigCommerce** = GoBilda + ServoCity, both verified through the anonymous Stencil session/CSRF quote flow. Bolt Depot is custom, Glacier Tanks is Magento with an open guest cart behind Cloudflare, and StepperOnline is OpenCart with a Cloudflare-gated cart write. WooCommerce: zero among tracked vendors.

So the answer to "workflow-changing or niche for the tracked head?" is: **five tracked storefronts quote through plain HTTP** — DERNORD, Mettle Air, SparkFun, GoBilda, and ServoCity — while Glacier Tanks exposes the same Magento guest-cart flow after BrowserSwarm establishes Cloudflare state. The platform path is still most valuable for the open-world tail. Magento catalog REST is normally gated, but public catalog GraphQL worked on 7/10 open stores in the 2026-07-31 corpus; use GraphQL first, then sitemap/product-page data.

## Driving tooling — how to actually run these

- **Playwright MCP (`@playwright/mcp` v0.0.78 in `~/.agents/browser-swarm`)** supports `--browser firefox|chrome|webkit|msedge` + `--headless`. **Firefox works, but only in launched mode.** BrowserSwarm attaches isolated contexts to one shared headless fingerprint-Chromium daemon over CDP (`shared-browser.sh` + `--cdp-endpoint`), and **CDP is Chromium-only**. The separately installed `browser-swarm-firefox` agent launches its own headless Firefox where that engine is needed.
- **camoufox / cloakbrowser are not `@playwright/mcp`-native.** `--browser` doesn't accept them. `--executable-path` to the camoufox binary gets the patched binary but not camoufox's fingerprint-injection launcher (its actual stealth) → hobbled. Use their own launchers or a dedicated MCP server.
- **Relevant stealth MCP servers** (if driving via MCP rather than raw scripts): `stealth-browser-mcp` (vibheksoni — nodriver + CDP, ~97 tools, standalone page-driver); AdsPower LocalAPI MCP (official — profile manager that returns a CDP endpoint you attach Playwright to, not a page-driver); `patchright-mcp-lite` (drop-in patched Playwright).
- **Background computer-use (the DataDome route):** Codex Computer Use on macOS (April 2026) and the open-source **`cua-driver` (trycua/cua)** drive a real headed app *behind* the current window with no focus steal / no cursor move / no Space switch — via SkyLight `SLEventPostToPid` + focus-without-raise. This is the macOS equivalent of "headed but invisible" (no native Xvfb on macOS). Costs: GUI/vision-level driving (slower, token-heavy, less deterministic than DOM/CDP), needs Accessibility + Screen Recording permissions, must run **unsandboxed** (desktop access, not the Claude/Codex sandbox).

## Reproduction & environment

- **Plain Playwright Firefox:** install through the pinned Playwright package in `~/.agents/browser-swarm`, then use the generated launched-mode `browser-swarm-firefox` agent. Firefox cannot attach to the shared CDP daemon.
- **camoufox:** `uv run --with camoufox python -m camoufox fetch` (binary in `~/Library/Caches/camoufox`), then `from camoufox.sync_api import Camoufox; Camoufox(headless=True)`.
- **tf-playwright-stealth:** `uv run --with tf-playwright-stealth --with playwright …`; `from playwright_stealth import stealth_sync; stealth_sync(page)` per page (older API; package also exposes `Stealth`).
- **cloakbrowser:** `pip install cloakbrowser` (or `uv run --with cloakbrowser`), runs **free tier, no license**; binary auto-downloads to `~/.cloakbrowser` (Chromium 145). API: `cloakbrowser.launch(headless=True)` → Playwright Browser.
- **Bot-wall detection** (how the wall map was built): load homepage, inspect cookies + body. Markers — Akamai Bot Manager: cookies `_abck`/`bm_sz`/`ak_bmsc`/`bm_sv`/`bm_lso`, body `bazadebezolkohpepadr` or `/akam/` script. DataDome: cookie `datadome`, body `captcha-delivery` / `dd={`. Cloudflare: `__cf_bm`/`cf_clearance`/`cf-ray` (often just CDN). PerimeterX: `_px*`/`pxcts`. **Probe more than once** — DataDome may pass the first hit then block on repeat.
- All browser launches were **unsandboxed** (network + browser exec). Test scripts + screenshots were in this session's ephemeral scratchpad (`/private/tmp/.../scratchpad/`, cleaned with the job) — not preserved here. The detection technique and results above are self-sufficient to re-run; ask to preserve the scripts if wanted.

## Agentic commerce standards

Two protocols exist and **Amazon participates in neither**. OpenAI and Stripe's **ACP** launched September 2025 (Etsy first, then Walmart, Target, Instacart); its consumer-facing Instant Checkout was withdrawn around March 2026, but the protocol outlived the product and gained Meta as a lead maintainer alongside PayPal, Affirm, Adyen and Wix. Google's **UCP** followed in January 2026, co-developed with Shopify and endorsed by Etsy, Wayfair, Target, Walmart and 20-odd payments partners. The word "Amazon" appears nowhere in OpenAI's commerce documentation, and every Amazon–OpenAI agreement is compute and capital only.

Neither is usable as a data source: ACP governs checkout, while product discovery runs on merchant feeds submitted to the platform. The feed spec is also thinner than it looks — `availability` is an enum with **no inventory count**, matching the boolean-stock ceiling the platform storefront APIs impose. Whether either protocol's buyer side is callable by an independent developer is unresolved.

## Leads worth chasing

- **Shopware** is the next major untested platform. Squarespace now has a reusable anonymous cart/address flow; Salesforce Commerce Cloud's SFRA convention can quote but is merchant-customizable; Wix and Ecwid have explicit storefront-runtime boundaries.
- **Storefront search providers** — Algolia, Searchspring, Klevu, Constructor.io — ship a public search-only key in the page bundle by design. Where a store uses one, that is faceted catalog search on sites that are not Shopify at all, potentially a wider net than any single platform API.
- **Free vendor API keys** would convert known blockers into structured sources. Mouser is the prize: it is Akamai+DataDome walled and unreachable by every headless engine tested, and offers a free search API. Digi-Key's MCP credentials have expired and merely need renewing. Nexar/Octopart and Element14/Farnell also have free tiers.
- **Shopify Web Bot Auth**: the request signer now emits the fixed Ed25519 profile and passes local verification. Shopify documents a higher signed tier, but bounded signed/unsigned trials did not expose a crossover or explicit tier signal. The public key directory still needs a deployed self-signature and post-deployment verification before the identity path is operationally complete.

## Open questions / next steps

1. **Primary unproven step: does headed patchright/cloakbrowser via cua-driver actually clear live DataDome?** Spike headed cloakbrowser or patchright against Grainger through cua-driver background computer-use. This is the recommended DataDome route and needs confirmation before the skill relies on it.
2. **Content-verify the Akamai-only 200s** (Omega, Lowes, Misumi, Arrow) — confirm they're real pages, not soft 200 challenges (only Master Electronics was screenshot-verified).
3. `adspower_headless` is the last untested benchmark DataDome-passer (commercial) — low priority given cloakbrowser failed.
4. Doc-state nit: the plot's "live-tested" rings cover only 2 of the 4 engines later tested (Firefox, camoufox); tf-stealth and cloakbrowser were tested afterward and not ring-annotated.

## Shared pieces live in the `browser-swarm` submodule

The engine-vs-wall decision table, the launched-mode Firefox config, the wall-detection markers, and the MCP driving constraints are general browser-tooling knowledge and live in [bot-detection.md](~/.agents/browser-swarm/docs/bot-detection.md); `browser-swarm` is a public repo, so anything vendor-specific or private stays out of it. This folder keeps the vendor-specific wall map, the shipping-quote strategy, and the raw benchmark data. Update both when a finding changes which one it belongs to.

Still unpromoted: a reusable **wall-detection helper script** (the markers are documented, the script was never written).
