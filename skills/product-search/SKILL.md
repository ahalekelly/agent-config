---
name: product-search
description: Source purchasable products — find parts/products meeting hard specs, check stock and price across vendors, run market surveys ("does a compliant X even exist?"), or compare consumer purchase options. Use when the user wants to find, source, or buy a physical part or product, or asks who sells or stocks something.
---

# Product Search

Everything here is a default shape, not law — deviate with judgment and note the deviation in the report. Applies to anything purchasable, from certified industrial components to consumer goods; pick techniques from the list below to fit the product and the stakes.

## 1. Intake

One quick AskUserQuestion round before searching: which constraints are hard vs soft, budget, quantity, timeline, and what the product is *for* — the underlying need matters later if nothing complies. Skip questions the request already answers.

A key intake question: **one-off or production?** One-off opens cheap channels — used, surplus, eBay/AliExpress, no-name Chinese parts with thin documentation. Production prefers a reputable supplier, real documentation, and a stable supply chain (multi-sourcing, lifecycle status, lead-time history), and those factors join the viability ranking.

Read `vendors.md` beside this file before searching. It contains the preferred-vendor tiers, trust levels, dated platform classifications, concise platform-API dispatch recipes, and the learned domain cache. Read `platform-apis.md` when the task needs exact requests, failure diagnosis, test findings, or a destination shipping quote.

## 2. Fan out

Launch both engines in parallel, in the background — they use different search indexes and reliably find different things:

- **GPT Sol** via pi-for-claude (`run` with a plan file, in a persistent Monitor). Answer its consult questions promptly via the answer file.
- **A Claude Opus subagent** (`model: "opus"`, background) with WebSearch/WebFetch.

Give each: the criteria in priority order with hard/soft markings, the relevant rows from `vendors.md`, the source channels chosen from the techniques list, and the deliverable shape (viability-sorted table + most promising links + frank assessment). Their instructions should also say: specifically check every plausible preferred and decent vendor from `vendors.md`; double-check that each candidate matches all criteria; list useful near-misses with the deviation; accept that an empty category is a valuable result; and mention a promising source even when access is blocked.

The orchestrator does no searching itself — no WebSearch, no distributor MCPs. Subagents carry the searches; the orchestrator launches, steers, adjudicates, and writes.

## 3. Verify

First, **cross-examine the two reports against each other**: where they overlap, agreement is cheap confirmation; where one engine found something promising the other did not, send that finding to the other agent to check.

Agent output is **leads, not facts**. Check key specs against the primary source before asserting them. Delegate this too: once the finders report, the orchestrator should have specific claims checked against the primary-source URLs. The orchestrator adjudicates verdicts and disagreements; it reads a document itself only when it is genuinely decisive and small.

When agents disagree, the primary document wins. Unverifiable claims still belong in the table, flagged `unverified` and generally ranked below verified rows.

## Techniques

Sources are roughly in order of cost. Treat this as a default to depart from, not a sequence to march through.

1. **A distributor MCP** — structured stock, price, and parametric data straight from the vendor.
2. **An API** — either a working vendor API recorded in `vendors.md`, or a public storefront API. The generic platform workflows cover Shopify, WooCommerce, Magento guest carts, BigCommerce Stencil, and Squarespace; Wix, Ecwid, Salesforce Commerce Cloud, and OpenCart have explicit browser or merchant-customization boundaries. A known Amazon ASIN can be hydrated through `scripts/amazon_product.py`. Use `vendors.md` for dispatch and `platform-apis.md` for the exact contracts.
3. **Web search** — useful for discovery, but unstructured and possibly stale. Check that a price came from the vendor before trusting it.
4. **A fetch through a GPT leaf** (Pi's `fetch_content`) — useful for descriptions, specifications, and published policies when plain WebFetch fails. It does not interact, often misses dynamic offers, and crosses a policy boundary when a site excludes crawlers. Try plain WebFetch first.
5. **BrowserSwarm** — last. Use it when the task needs interaction, rendered-only price or stock, a site-specific SDK, or a bot-wall session. Before attaching, read `~/.agents/browser-swarm/README.md`. The daemon uses fingerprint Chromium and gives each browser agent an isolated context with a two-open-tab cap. Close tabs after extracting the needed data and end browser agents when their work is finished; the shared daemon auto-stops when no clients remain.

Choose per task; none are mandatory:

- **Live product/retailer pages** — primary source for current stock and price claims, and capability claims where no datasheet culture exists.
- **Datasheets and certificates** — primary sources for specifications and certifications.
- **Distributor MCPs** (Digi-Key, McMaster) via a subagent — structured engineering-part data; the same subagent can follow returned datasheet URLs.
- **Platform storefront APIs** — detect the platform, obtain exact product data, and request the merchant's destination rates before opening a browser. Empty rate lists are no quote, never free shipping. See `vendors.md` and `platform-apis.md`.
- **Amazon ASIN hydration** — after discovery yields an exact ASIN, use `scripts/amazon_product.py` for the current title, image, rating, offer prices, sellers, shippers, and anonymous-default delivery promises. The undocumented read-only endpoint is not keyword search or an SF shipping quote. Treat `aod_unavailable` as endpoint unavailability, not proof that the product does not exist, and stop on blocks instead of retrying.
- **Part-number scheme decoding** — decode manufacturer suffixes and option tables early.
- **Supply-chain breadth** — production ranking includes distributor count, lifecycle status, lead-time history, and price breaks.
- **Manufacturer RFQ leads** — when nothing stocked complies, identify manufacturers that can build it and report the lead-time caveat.
- **Localized search terms** — use region-appropriate language for industrial niches.
- **Market-gap analysis** — explain why a category is empty and whether waiting, RFQing, or redesigning addresses the cause.
- **Quote-only price estimation** — look for approximate pricing in credible public grants, procurement records, or practitioner forums.
- **Reviews and first-hand accounts** — use independent, credible practitioner sources; exclude SEO slop and AI-generated sites.
- **Methodology comparisons** — compare like measurement methods and flag material differences.

## Vendor pricing pass

Use this pass only when comparing vendors. If shipping may exceed roughly 20% of the order, rank by delivered price rather than list price.

1. Search comprehensively for vendors, then give each plausible vendor to a separate Terra or Sonnet subagent.
2. Check published free- or flat-shipping rules first.
3. Detect the storefront and use the concise recipe in `vendors.md`; open `platform-apis.md` for exact requests, failure modes, safe evidence, and test findings. Prefer `scripts/platform_api.py` where its platform adapter applies, or `scripts/amazon_product.py` for a known Amazon ASIN.
4. Use BrowserSwarm only for the residue explicitly marked as a browser boundary. Keep it invisible, follow its README resource rules, and never place an order, create an account, or enter payment details. Use the dummy ship-to recorded in `vendors.md`.
5. Cache the dated platform, bot-wall, and shipping facts learned for an unknown domain in the untiered table in `vendors.md`. Do not turn learned domains into preferred vendors or change tiers.

Neither the orchestrator nor the search subagent drives the browser itself; browser work belongs in per-vendor subagents.

## 4. Report

Create a datetime-titled Markdown report in the invoking project or vault, auto-opened in Obsidian when it is in a vault and otherwise in Vivaldi, unless the user points output elsewhere.

- **Headline verdict first** — including “this does not exist in stock anywhere” when true.
- **Requirements as understood** — hard and soft constraints plus assumptions.
- **Table sorted by viability** — verified beats unverified and in-stock carries heavy weight over RFQ. Vendor tier breaks ties but never excludes a result. Link product pages and datasheets, date-stamp stock and prices, convert foreign prices to USD, note shipping/import friction, and include a picture where possible.
- **Caveats** — integration conditions, certificate limits, and cross-row qualifications.
- **If hard constraints cannot all be met** — state the gap, explain why it exists where discoverable, and propose alternatives to the underlying need.
- **Recommended next actions.**

After the report, update only changed dated facts for existing preferred vendors and append newly learned domains to the untiered cache. Do not add preferred-vendor rows or change tiers without direction.
