---
name: product-search
description: Source purchasable products — find parts/products meeting hard specs, check stock and price across vendors, run market surveys ("does a compliant X even exist?"), or compare consumer purchase options. Use when the user wants to find, source, or buy a physical part or product, or asks who sells or stocks something.
---

# Product Search

Everything here is a default shape, not law — deviate with judgment and note the deviation in the report. Applies to anything purchasable, from certified industrial components to consumer goods; pick techniques from the list below to fit the product and the stakes.

## 1. Intake

One quick AskUserQuestion round before searching: which constraints are hard vs soft, budget, quantity, timeline, and what the product is *for* — the underlying need matters later if nothing complies. Skip questions the request already answers.

A key intake question: **one-off or production?** One-off opens cheap channels — used, surplus, eBay/AliExpress, no-name Chinese parts with thin documentation. Production prefers a reputable supplier, real documentation, and a stable supply chain (multi-sourcing, lifecycle status, lead-time history), and those factors join the viability ranking.

Also read `vendors.md` beside this file — the preferred-vendors table: tiers, trust levels for listing claims, and cached vendor facts (shipping policies, bot-walls, MCP availability).

## 2. Fan out

Launch both engines in parallel, in the background — they use different search indexes and reliably find different things:

- **GPT Sol** via pi-for-claude (`run` with a plan file, in a persistent Monitor). Answer its consult questions promptly via the answer file.
- **A Claude Opus subagent** (`model: "opus"`, background) with WebSearch/WebFetch.

Give each: the criteria in priority order with hard/soft markings, the relevant rows from `vendors.md`, the source channels you've chosen from the techniques list, and the deliverable shape (viability-sorted table + most promising links + frank assessment). Their instructions should also say: specifically check every plausible preferred and decent vendor from the `vendors.md` rows; double check that each candidate actually matches all the criteria; near-misses are worth listing with the deviation noted; "this category is empty" is a valid, valuable answer; and if there's a source you're blocked from accessing that seems more promising than the sources you can access, always mention it.

The orchestrator does no searching itself — no WebSearch, no distributor MCPs — that pollutes its context with result dumps. Subagents carry the searches; the orchestrator launches, steers, adjudicates, and writes.

## 3. Verify

First, **cross-examine the two reports against each other**: where they overlap, agreement is cheap confirmation; where one engine found something promising the other didn't, send that finding to the other agent to check — its different search index and perspective is exactly what tests a single-source lead.

Agent output is **leads, not facts**. Key specs need to be checked against the primary source before the report asserts it. Delegate this too: once the finders report, the orchestrator should check the specific claims against the primary-source URLs. The orchestrator adjudicates verdicts and disagreements; it reads a document itself only when it's genuinely decisive and small.

When agents disagree, the primary document wins (a certificate has refuted a confident agent claim about an Ex rating before). Unverifiable claims still belong in the table, flagged "unverified" and generally ranked below verified rows.

## Techniques

Escalate by cost, not by habit: if web search can get the info, that's preferable over browser use, and a structured API or MCP is better still. Drive a browser only for what the cheaper sources genuinely cannot answer — a live cart quote, a stock figure that exists nowhere but the page, a form that has to be filled. A browser leaf costs far more tokens and wall-clock than a search, and it is the only path that bot walls can block.

Choose per task; none are mandatory:

- **Live product/retailer pages** — the primary source for stock and price claims, and capability claims on anything without a datasheet culture.
- **Datasheets and certificates as primary sources** — for spec and certification claims, the manufacturer's PDF outranks every listing page
- **Distributor MCPs** (Digi-Key, McMaster) via a subagent — structured stock/price/parametric data for engineering parts; the same subagent can chase datasheet URLs the API returns.
- **Part-number scheme decoding** — decode the manufacturer's suffix/option system early (configurator PDFs, ordering-code tables); it reveals the whole family including unlisted variants, and what each stocked SKU actually is.
- **Supply-chain breadth** — for production sourcing, the number of distributors stocking a part, its lifecycle status (active/NRND/EOL), and price-break structure are ranking inputs, not trivia.
- **Manufacturer RFQ leads** — when a spec combination isn't stocked anywhere, hunt for the manufacturer who could build it (configurators, option codes, "available on request" lines) and report it as an RFQ path with lead-time caveats.
- **Localized search terms** — industrial niches often surface on non-English queries (e.g. German "ATEX Axiallüfter") or region-specific distributors; tell the finders when the category smells European or Asian.
- **Market-gap analysis** — when nothing complies, dig for *why* (a structural incompatibility, a certification economics problem); the reason predicts whether waiting, RFQing, or redesigning is the fix.
- **Quote-only price estimation** — if a promising product is quote-only, search for approximate pricing in public grant documents or forums.
- **Reviews and first-hand accounts** — search for blogs, forums, and social media reports as sources whenever appropriate, such as for first-hand accounts of real-world reliability or limitations. Blogs means written by hobbyists or professionals in the field — exclude SEO slop and AI-generated websites. Weigh by independence and credibility, not source count.
- **Methodology comparisons** — make sure specifications were measured with similar methodology, flag it if methodologies are significantly different

## Vendor pricing pass

Only when asked to compare pricing across vendors — typically a second pass after the initial search. If shipping looks like it'll exceed ~20% of the total order cost, compare on **delivered price**, not list price:

1. The search subagent first does a comprehensive search for vendors.
2. The search subagent spawns a **Terra or Sonnet** subagent per vendor. The vendor subagent first checks the vendor's site for a free or flat-rate shipping policy and whether this order qualifies.
3. Where that fails, the vendor subagent uses a browser tool to get an actual shipping quote — also recording the sales tax, tariffs, and any other taxes and fees the checkout shows, so delivered price is complete. The browser tool must be invisible to the user of the computer: headless only, never the user's browser (Vivaldi), no window focus changes. Cap concurrent browser leaves (~4) so the machine stays responsive.
   - Harness choice (benchmarked across every vendors.md vendor 2026-07-29 — "Vendor Bot-Wall and Shipping Benchmark 2026-07-29.md" in the vault):
     - **codex exec Terra — the default.** Fastest (~80 s/vendor), mid token cost. Launch with the pinned recipe from "Codex Playwright Cold-Start Fix 2026-07-28.md": Playwright MCP from `~/.agents/playwright-mcp` (never cold-`npx @latest` in parallel), `BROWSER_USE_AVAILABLE_BACKENDS=""` on node_repl so the leaf can't reach the desktop browsers. (Setting it to `"iab"` does not work: the in-app-browser backend is gated to ChatGPT-app-hosted sessions and reports "not available" from `codex exec` even with the component installed; tested 2026-07-29.) Two hard rules, because codex otherwise fabricates browsing: (1) the prompt must state that only `playwright` MCP tools count as browsing, the bundled Browser skill's node_repl-only rule does not apply, and web search / server-side URL fetches / shell-installed browsers are forbidden substitutes — without this, most runs "browse" via OpenAI's server-side fetcher (which tests OpenAI's egress, not this machine) or npm-install a rogue Chromium, then report confident verdicts anyway; (2) verify each run by counting `browser_*` calls in its log — zero calls invalidates its browsing claims. Codex's cloud fetch is still a fine source for *published* policy text; it can never produce a cart quote (it does no form interaction).
     - **pi-for-claude Terra** — equal accuracy, cheapest fresh tokens, slowest on deep checkouts. Only works launched *outside* the Claude sandbox (`nohup pi-for-claude run … &`) — the sandboxed-Monitor launch breaks its socket dir and DNS. It may raise consult questions mid-run even when told not to: watch the session's `.question.md` files and answer promptly or the run stalls up to 10 min.
     - **Sonnet browser-leaf** — most thorough, best at driving carts and shipping calculators for live quotes, ~2× codex tokens. Leaves attach as isolated contexts to the shared headless browser daemon: start it before the fan-out (`~/.agents/playwright-mcp/shared-browser.sh start`); leaves fail immediately with `ECONNREFUSED :9377` when it's down. Still one leaf per numbered type (`browser-leaf` … `browser-leaf-5`) — Claude Code multiplexes concurrent same-type subagents onto one MCP session, which would put them in one shared context (tested 2026-07-28); context isolation through the shared browser verified at 4 concurrent (2026-07-29). Never route leaves at the session-level Playwright plugin (one shared *headed* Chrome).
     - Sandboxed Bash has no network — the shared browser daemon and any other headless browser must launch unsandboxed. Leaves with cwd in a repo drop `.playwright-mcp/` artifacts there — gitignore or trash them. Batch drivers on macOS: bash 3.2 has no `wait -n`; throttle with `sleep` polling or the loop busy-spins.
   - Bot walls: per-vendor status is cached in `vendors.md`. Which wall a vendor runs decides whether a leaf can reach it at all — **DataDome blocks every headless engine tried**, while **Akamai is beatable headless** by Firefox or a fingerprint-patched Chromium. `~/.agents/playwright-mcp/Bot Walls and Browser Engines.md` has the engine-per-wall table and the leaf configs. For DataDome vendors use API/MCP data or published-policy text. Report a bot-wall as "blocked", not as a failed vendor.
   - Dummy ship-to for estimates: Jordan Smith, Pacific Prototyping LLC, 747 Howard St, San Francisco, CA 94103, (415) 555-0132. Rate estimation only: never place an order, create an account, or enter payment details.
4. Neither the orchestrator nor the search subagent uses the browser themselves — it's very token-heavy; it belongs in the per-vendor leaf agents.

## 4. Report

A datetime-titled `.md` report (e.g. `ATEX Fan Search 2026-07-28.md`) in the invoking project or vault, auto-opened (Obsidian if in a vault, else Vivaldi), unless the user pointed output somewhere else.

Shape:

- **Headline verdict first** — including "this doesn't exist in stock anywhere" when that's the truth.
- **Requirements as understood** — the hard/soft constraint list from intake, plus assumptions made.
- **Table sorted by viability**: how likely the row solves the actual need. Verified beats unverified, and **in-stock carries heavy weight over RFQ** — buyable-today with a verified quantity usually outranks a paper-perfect part behind a quote cycle, and an in-stock near-miss on a soft constraint beats an RFQ exact match. Only a hard requirement met exclusively by unstocked options justifies an RFQ row on top, flagged as such. Vendor tier from `vendors.md` breaks ties among otherwise comparable rows — never a reason to omit a row. Link part numbers to product pages/datasheets. Date-stamp stock and prices; they're snapshots. For foreign currencies, always give the value in USD as well; no need to cite a source for the exchange rate. When a row's best source is foreign, note shipping, lead time, and import/tariff friction as a caveat. Provide prices, links, and a picture for each product whenever possible. Obsidian and Vivaldi render web-hosted images.
- **Caveats** — integration conditions, certificate limitations, anything that applies across rows.
- **If the hard constraints can't all be met**: state the gap, explain *why* it exists if discoverable, and propose different approaches to the underlying need — this is what intake's "what's it for" was for.
- **Recommended next actions.**

After the report: if the run surfaced a changed bot-wall status or shipping policy for a vendor already in `vendors.md`, update that row's cached facts and re-date it. Only those facts — don't add vendor rows, change tiers, or rewrite the other columns.
