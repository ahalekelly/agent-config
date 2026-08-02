# Storefront tool: standalone package, batch commands, marketplace discovery, token-lean output

Baseline: branch `codex/product-search-platform-apis` (PR #3), which superseded PR #2. Work on that branch (or main after it merges). All work is in `skills/product-search/` unless stated. Do NOT touch `web-bot-auth/` (PR #1 owns it) or anything outside product-search.

## Current state of the codebase

`scripts/platform_api.py` (~370 lines) is the agent-facing CLI: `detect`, `search`, `probe`, `quote`, `corpus` — all single-store, scalar args, base64 `item-v1.` refs, fixed San Francisco dummy destination (copied into five adapter files). `scripts/platform_api_core.py` (~1,800 lines, ~88 defs) is the single shared module: result envelopes, schema enforcement, money, bot-wall, refs. Adapters in `scripts/platforms/`: shopify (signed GraphQL via `scripts/web_bot_auth.py`, which hardcodes `/Users/akelly/.agents/web-bot-auth/private.pem`), woocommerce (Store API), magento (GraphQL catalog with HTML-scrape fallback recorded as `search_source`, REST guest carts — keep all three faces, they're Magento's real surface), bigcommerce (Stencil scrape + Storefront REST carts), squarespace, extra.py (wix/ecwid catalog bootstrap; quote is `unsupported_operation(..., browser_required=True)` — preserve these boundaries; SFCC/OpenCart documented as boundaries only). `scripts/aliexpress_affiliate.py` (TOP HMAC-MD5 signing) and `scripts/serpapi_google_shopping.py` (engine `google_shopping`) are standalone strict clients whose results are unverified leads. `scripts/read_only_http.py` + `scripts/platform_search_acceptance.py` + `scripts/platform_search_corpus_contract.py` are a sealed-capability/provenance acceptance stack. Tests in `scripts/tests/` (per-platform, mock transports, fixtures under `tests/fixtures/`) — 232 pass. Docs: `SKILL.md`, `platform-apis.md`, `vendors.md` (includes a learned cache of ~87 normalized domain→platform facts), committed evidence reports under `dev/reports/`.

End goal: a separately published tool. This session restructures it as a self-contained installable package (working name `storefront`; final name TBD by the user) still living inside `skills/product-search/` so it can later be copied into its own repo unchanged. Nothing in the package may reference `~/.agents` or any user-specific path; all user-specific values move to config (§4) or env.

The primary consumer is an AI agent whose context window is the scarce resource: output design is token-lean by default (§10), with debug detail opt-in.

CLI argument philosophy: positional scalars and flags for simple values; JSON only for inherently structured values. Never a single all-of-argv JSON blob.

## CLI surface

Five commands; `detect`, `corpus`, and `probe` are removed (probe's "first available hit" selection is an arbitrary product choice we don't want ergonomic; its semantics are just search + quote). search/product/quote are batch commands sharing one execution model (§5).

- `search <entries-json> [--limit N=20, max 50] [--description-chars N=300] [--redetect] [--debug]` — entries: `[{"store": <url>, "query": <str>}]`, 1–100
- `product <items-json> [--description-chars N=2000] [--redetect] [--debug]` — items: array of 1–100 entries, each a product-page URL (string), a handle (string, §6), or a ref (object)
- `quote <quotes-json> [--destination <json>] [--redetect] [--debug]` — quotes: `[{"store": <url>, "lines": [{"item": <url|handle|ref>, "quantity": <int ≥ 1>}]}]`, 1–20 stores, 1–20 lines each
- `images <item-handle> [<range>]` — download an item's images to files, print the paths (§6)
- `config set-destination <json>` / `config show`

Item inputs discriminate by JSON type and shape: object = ref; string starting with `http` = product-page URL; string matching the handle grammar (§6) = handle; anything else is a ToolError naming the three accepted forms.

Refs are readable, self-contained JSON objects — the current `item-v1.` base64 tokens and `item_ref()`/`parse_item_ref()` are removed entirely. A ref is `{"platform": <str>, "store": <canonical origin>, <platform-specific identity keys>}`, e.g. `{"platform": "shopify", "store": "https://example.com", "variant_id": "gid://shopify/ProductVariant/123"}`. Refs are emitted only by `product` (per variant); they are the durable way to name an exact variant across sessions. Validate refs strictly and exhaustively per platform (required identity keys present, no unknown keys, known platform) with loud, specific errors; hand-written refs are acceptable input by design since every ref is re-verified against the live store at use time. Ref equality uses canonical serialization (sorted keys, compact separators).

Every store-touching command auto-detects (registry-first, §4) and accepts `--redetect` to force a live re-probe. Exit code 1 if any entry in the invocation ended in api_error, else 0.

A `search` entry's store may also be a marketplace pseudo-store — same command and output shape, but the query hits a cross-merchant index instead of one storefront, and pseudo-stores mix freely with regular storefronts in one batch:

| pseudo-store origin | backend | quote support |
| --- | --- | --- |
| `https://shop.app` | Shopify Global Catalog MCP (§9) | error → quote the merchant store |
| `https://www.aliexpress.com` | AliExpress Affiliate API (§8) | error: not available via affiliate API |
| `https://shopping.google.com` | SerpApi `google_shopping` engine (§8) | error → leads; quote the merchant store |
| `https://www.amazon.com` | SerpApi `amazon` engine (§8) | error: no anonymous Amazon cart API exists |
| `https://www.ebay.com` | eBay Browse API (§8) | error → shipping shown in `product` detail instead |

Commit granularly: each numbered section below is at least one commit. Follow the code style in `~/.agents/AGENTS.md` (skimmable, few states, no defensive code, no optional args unless truly optional, fail loudly).

## 1. Delete the acceptance/provenance stack

Delete `read_only_http.py`, `platform_search_acceptance.py`, `platform_search_corpus_contract.py`, their tests (`test_read_only_http.py`, `test_platform_search_acceptance.py`, `test_platform_model_v2.py`), and the committed evidence artifacts under `dev/reports/` (input JSON / JSONL / regenerated report — git history preserves them). This stack is audit-evidence machinery (sealed per-operation capabilities, per-hop provenance, SHA-256-bound reproducible reports), not product functionality, and it runs against the project's code-style rules. Adapters that currently make requests through sealed capability objects (e.g. magento's `http.magento_html_search`) are rewired onto the plain session convention in §2. Validation going forward = the mock-transport test suite plus occasional live smoke runs; delete `corpus` with it (§5's batch search replaces the sweep role).

## 2. Slim the core, one adapter convention

`platform_api_core.py` (~1,800 lines) carries heavy schema-enforcement ceremony around every envelope shape. Collapse it around the redesigned output (§10): ONE result-envelope builder, one money/price helper, one bot-wall classifier, one error constructor — one definition per rule, and drop enforcement layers that only re-validate what the types already guarantee. Target: the core shrinks by several hundred lines while every §12 test still passes.

All adapters share ONE calling convention: each receives a per-store session object bundling request execution (Web Bot Auth signing wired in for Shopify when configured, §3), cookie/cart isolation, and evidence capture in one place. §5's parallelism requires one independent session per store worker anyway. Keep magento's `search_source` mechanism (graphql vs html) — that's real platform surface, not ceremony.

`detect()` becomes table-driven: a declarative marker/probe table the loop walks, so adding a platform is mostly a data change. Preserve the current detection semantics, including bot-wall-beats-weak-markers ordering and the wix/ecwid/SFCC/OpenCart boundary classifications.

The core must be a library with the CLI as a thin argparse shell over it — a future MCP server entry point (explicitly out of scope this session) will call the same library functions.

## 3. Restructure as a self-contained publishable package

Replace `scripts/` with a package directory under `skills/product-search/` containing `pyproject.toml` (uv-compatible, console entry point for the CLI), the package source, tests, and a succinct README (what it does, install/run via `uv run`/`uvx`, the commands, config locations, Web Bot Auth stance). Keep dependencies minimal (httpx, cryptography for signing, platformdirs). The skill's docs invoke it via `uv run` against this directory.

User-specific values become configuration:
- Data directory (registry, settings, run cache, downloaded images): default via platformdirs' user-data location, overridable with env `STOREFRONT_DATA_DIR`. No file in the package tree is written at runtime.
- Web Bot Auth signing: settings entry `web_bot_auth: {"private_key_path": ..., "key_directory_url": ...}` replacing `web_bot_auth.py`'s hardcoded `PRIVATE_KEY_PATH` and directory URL. When unset, Shopify requests are sent WITHOUT signatures (unsigned is the norm for a public tool; signing is an opt-in identity feature). When set but the key file is missing/unreadable, that is a structured api_error naming the path — not a silent unsigned fallback and not a traceback. Keep the branch's signing behaviors (thumbprint validation, fresh replay material, same-authority redirect rule).
- AliExpress affiliate and SerpApi credentials stay env-based; eBay and Shopify Global Catalog credentials live in settings (§8, §9). Document every env var and settings key in the README.

After the restructure, `uv run <package-dir>/…` and the console entry point must both work; tests run via pytest with `uv run`.

## 4. Vendor registry and settings files

Two JSON files in the data directory (§3):

- `vendors.json` — persistent vendor→platform registry. Map keyed by canonical store origin, values like `{"platform": "shopify", "api_origin": "https://x.myshopify.com", "detected_at": "<ISO date>", "evidence": [...], "name": "<optional human name>"}`. Every successful detection (any command) upserts its entry; writes are atomic (temp file + rename) and guarded by a lock shared with §5's worker threads. All commands consult the registry before probing: a registry hit skips live detection entirely. `--redetect` forces a live probe and refreshes the entry; a live probe that contradicts the registry overwrites it. Failed/unknown/bot_wall detections are NOT recorded — the registry holds only confirmed platforms, and only real storefronts: marketplace pseudo-platforms are built into the dispatch table, never registry entries. Entries may be hand-curated. Marketplace search results NEVER upsert the registry directly (they're unverified leads); only a real detection against the merchant store does — except Shopify Global Catalog results, which are first-party platform facts (§9).
- `settings.json` — user settings: the default shipping destination (managed via `config set-destination` / `config show`), the optional `web_bot_auth` block (§3), and optional `shopify_global` / `ebay` credential blocks. Missing file or key → built-in defaults (SF constant for destination, unsigned for Shopify, structured setup-instruction error for credentialed marketplaces).

Seeding: convert the learned-domain cache currently embedded in `vendors.md` (~87 normalized domain→platform facts, including redirect aliases like `malcowallshop.com`) into `vendors.seed.json` shipped beside the package docs in this repo (NOT inside the package); on first run, or via `config import-vendors <path>`, merge it into `vendors.json`. `vendors.md` keeps human-facing vendor notes only — the machine facts live in the registry.

## 5. Batch execution model and search

Shared execution model for search, product, and quote: group the invocation's work by canonical store origin; run stores concurrently with a worker pool of 5 (queue, not fail-fast); within one store, operations run sequentially on that store's own session; one registry-first detection per store per invocation; a store failing (bot_wall, api_error) must not affect other stores — its results carry the error envelope. Registry upserts from workers go through the §4 lock. Output arrays preserve input order regardless of completion order.

`search <entries-json>` replaces the single-store `search` command; `corpus` is deleted in §1.

- `<entries-json>`: JSON array of `{"store": <url>, "query": <string>}`, 1–100 entries. One store may appear in multiple entries (multiple queries). Validate strictly, fail loudly.
- Search results are PRODUCT-level, one item per product — never one item per variant. Each item: item index `i` (§6), title, price (single value, or `[min, max]` range across variants), availability, product URL, truncated description, `variants` = array of variant display names (option labels joined, e.g. `"Small / Blue"`) when the product has more than one, `images` = image count (§6). No refs in search output; no image URLs. Adapters still fetch variant ids/prices where the API returns them (needed for the run cache and price range) but output stays product-level.
- Multiple queries against the same store: merge and dedup by product identity, keeping first occurrence; record which queries matched each item (`"queries": [...]` on the item, only when the store block has more than one query).
- Output: one JSON object with top-level metadata (§10) and a `stores` array in input order, each with its store index `"s"` (§6), detection summary, currency, per-store status, and items.
- Marketplace pseudo-stores return the same item shape; their items are leads (their `product`/`quote` support varies per the §"CLI surface" table).

## 6. Run cache, handles, and the `images` command

Every `search` and `product` invocation persists its full results — including everything elided from output: per-variant ids/refs, image URLs, full descriptions — as a run file in the data directory. Run ids are monotonic: `r1`, `r2`, `r3`, … allocated from a persistent counter file in the data directory (lock-protected, safe under concurrent invocations from parallel agent sessions, and NEVER reset or reused — the counter outlives garbage collection, so a dangling handle can never silently resolve against a newer run). The output's top-level metadata includes `"run": "<id>"`. Runs are garbage-collected after 7 days; a handle referencing a GC'd or unknown run is a ToolError telling the caller to re-run search.

Handle grammar — all segments 1-based and monotonic in output order: `<run>.<s>.<i>` names item `i` of store `s` of that run; `<run>.<s>.<i>.<v>` names variant `v` (in the order of the item's `variants` array). `s` is the store's index within the run (order of first appearance in the invocation's input), so two handles sharing the `<run>.<s>` prefix are from the same vendor — agents can group products by vendor from ids alone. In search output, store blocks carry an explicit `"s"` field and items carry `"i"`; in product output, each element carries its full composed `"handle"` (its entries aren't grouped by store). Agents must never have to count positions. Handles are accepted anywhere an item input is accepted:

- `product r7.2.5` → detail for that item (resolved from the cached identity, fetched live).
- `quote` line `{"item": "r7.2.5.3", "quantity": 3}` → that variant. A bare item handle for a multi-variant product is an api_error naming the `variants` and the `<run>.<s>.<i>.<v>` form. Handle store must agree with the quote entry's store (ToolError otherwise).
- `images r7.2.5 [<range>]` → downloads that item's images (URLs from the run cache; no product re-fetch) to files under the data directory's images area, printing a JSON array of absolute file paths for the agent to view. `<range>` is 1-based: `2`, `1:3`, or omitted for all; count capped at 10 per call.

Handles are session-ephemeral conveniences; refs (from `product`) remain the durable cross-session names. Staleness is acceptable by design: everything a handle resolves to is re-verified live at use time (except `images`, which intentionally serves cached URLs).

## 7. `product` and `quote`

`product <items-json> [--description-chars N=2000]`: array of 1–100 entries (URL / handle / ref). Entries group by store origin and run under §5; exact duplicates are fetched once. Output: top-level metadata (§10) plus a `products` array in input order — each element is the product detail (full composed `"handle"`, title, full description, price, stock/availability, `images` count, product URL, and per-variant: display name, option labels, price if it differs, availability, and the durable ref) or that entry's error envelope.

URL→product resolution per platform (build on each adapter's existing product-page machinery):
- Shopify: product handle from the URL path, then GraphQL product-by-handle — same signing path as search.
- WooCommerce: slug from URL, `/wp-json/wc/store/v1/products?slug=<slug>`; variable products emit one ref per variation (fetch variations).
- Magento: url_key via GraphQL when `search_source` is graphql; via the existing product-page HTML parser otherwise.
- BigCommerce: fetch the product page directly — the page parser already exists; expose it for a caller-supplied URL.
- Squarespace: `<product-url>?format=json`.
- Wix/Ecwid: resolve by slug via the catalog APIs the adapters already use; if a platform genuinely cannot resolve a URL, return a structured api_error saying so — no silent fallback.
- eBay: item URL → Browse API `getItem` (§8), including shipping options for the configured destination.

A ref or handle input skips URL resolution and fetches detail directly.

`quote <quotes-json> [--destination <json>]`:

- `<quotes-json>`: JSON array of `{"store": <url>, "lines": [{"item": <url|handle|ref>, "quantity": <int ≥ 1>}]}` — 1–20 store entries, 1–20 lines each, stores quoted concurrently under §5, output as a `stores` array in input order. A line whose resolved store origin disagrees with its entry's store is a ToolError. URLs resolve via the table above (a URL resolving to a multi-variant product without a determinable single variant is an api_error telling the caller to use `product` or a variant handle).
- One cart per store entry containing ALL its lines at their quantities, then one shipping-rates fetch: Shopify `cartCreate` lines array; WooCommerce repeated `add-item` against one cart token (a quantity below the product's minimum is an api_error, not a silent bump) with cleanup removing every added line; Magento guest cart multiple items; BigCommerce `line_items` array; Squarespace repeated adds. Wix/Ecwid keep their `unsupported_operation` / browser-boundary behavior. There is no single-item quote path: one line at quantity 1 is just the smallest lines array.
- Result per store entry: line items as quoted (title, unit price, quantity, line total), subtotal, and the shipping-options envelope.
- Destination precedence: `--destination` flag > settings destination > built-in SF constant. The dummy SF address is currently copy-pasted in five adapter files; replace with ONE canonical constant plus per-platform mapping functions. Shape: `{"country": "US", "region": "CA", "city": "San Francisco", "address1": "747 Howard St", "postal_code": "94103"}`; country (ISO-3166 alpha-2) and postal_code required, rest optional with sensible platform mapping.

Descriptions (search and product): shared core helper, HTML → plain text (strip tags, unescape entities, collapse whitespace), truncate to the char limit, append `…` when cut. Adapters fetch descriptions natively from payloads they already retrieve (add `description` to the Shopify GraphQL — `description(truncateAt:)` where it helps; Woo store API `short_description`/`description`; Magento `short_description { html }` fallback `description { html }`; BigCommerce/Squarespace/Wix/Ecwid from pages/JSON already fetched). Image URLs come only from payloads already fetched — no extra requests just for image URLs.

## 8. Marketplace pseudo-platforms: AliExpress, SerpApi (Google Shopping + Amazon), eBay

All follow the §2 adapter convention, are built into the dispatch table under the origins in the §"CLI surface" table, are never live-probed for detection, and emit the standard §5 item shape with results marked as leads where applicable.

- AliExpress: fold the existing `aliexpress_affiliate.py` client behind `search` (and `product` if the affiliate API supports detail); env-based credentials unchanged; `quote` → structured api_error. Re-plumbing, not a rewrite; preserve its tests.
- SerpApi: fold the existing `serpapi_google_shopping.py` client behind `search` as `https://shopping.google.com`, and add the `amazon` engine behind `https://www.amazon.com` (same client, second engine — read SerpApi's docs for the amazon engine's request/response shape and encode it in mock fixtures). Env-based API key. Results are unverified cross-platform leads (Google Shopping) and Amazon listings; `product`/`quote` → structured api_errors pointing at the merchant link (Google Shopping) or stating no anonymous Amazon API exists. Keep the strict-validation character of the existing client.
- eBay: NEW adapter for the eBay Browse API. Credentials (client id/secret) in settings `ebay: {...}`; mint the OAuth client-credentials token lazily per invocation, in memory only; missing credentials → structured setup-instruction api_error. `search` → `item_summary/search`; `product` → `getItem` by item URL/ref, including shipping options for the configured destination via the `X-EBAY-C-ENDUSERCTX` contextual location header; `quote` → structured api_error explaining shipping appears in `product` detail (checkout APIs are restricted-tier). Read eBay's Browse API docs for exact shapes; encode them in mock fixtures. Note the production-keyset prerequisite (marketplace account-deletion notification compliance) in the README.

## 9. Shopify Global Catalog: cross-merchant discovery

Shopify's Global Catalog MCP server (https://shopify.dev/docs/agents/catalog/global-catalog) searches products across all Shopify merchants. Integrate it as the `https://shop.app` pseudo-platform using the current UCP contract.

- Transport: send plain httpx JSON-RPC `tools/call` requests to `/api/ucp/mcp`; do not add an MCP SDK dependency. Use `search_catalog` for discovery and `get_product` for detail, with all tool arguments wrapped in `catalog`.
- Identity: every request includes `meta.ucp-agent.profile`, configured as `shopify_global: {"profile_url": ...}` in settings. Missing configuration produces a structured setup-instruction api_error. The current UCP contract does not use the retired Global Catalog client-credentials JWT flow.
- `search` with store `https://shop.app`: map query + `--limit` to `search_catalog`; pass destination fields through `filters.ships_to`. Results follow the §5 item shape and the run cache stores the universal product ID.
- Every result's merchant storefront origin is upserted into `vendors.json` as `{"platform": "shopify", ...}` with evidence `global_catalog_result` — first-party platform facts, the one exception to the leads-don't-upsert rule (§4).
- `product` on a shop.app item maps its universal product ID to `get_product`. `quote` against shop.app returns a structured api_error directing the caller to quote a specific merchant store from the result.

## 10. Token-lean output rules

The default output of every command follows these rules; `--debug` relaxes them:

- Top-level metadata exactly once per invocation: `schema_version`, `observed_at`, `run` (when a run is written). Never repeated per store or per item.
- No `evidence` anywhere by default; detection appears as a summary (`platform`, plus `state` only when not `detected`). `--debug` restores full evidence arrays and detection detail.
- Hoist store-level constants out of items: `currency` once per store block; item prices are bare numbers (or `[min, max]`).
- Omit empty/null/default fields entirely: no `"available": null`, no `"variants"` for single-variant products, no `"queries"` for single-query stores, no zero counters, no empty arrays. Presence means signal.
- No image URLs in search/product output — `images` counts plus the §6 command. No refs in search output — handles cover the in-session flow, `product` provides durable refs.
- Compact JSON to stdout (no pretty-printing).
- Errors are structured and terse: status, platform, stage, reason, http_status when known.

The `input` echo block stays for now (each store block identifies its store origin and query/lines).

## 11. Docs

- The package README (§3) is the tool's own documentation: commands, config/env reference, credential setup per marketplace (Shopify Global Catalog Dev Dashboard, eBay Developers Program + compliance step, SerpApi key, AliExpress affiliate), Web Bot Auth stance, data files.
- `platform-apis.md`: update for the new CLI surface and remove/replace everything describing the old commands, base64 refs, and acceptance stack; keep the per-platform protocol reference and dated failure modes (they move with the tool at extraction time, so keep them free of `~/.agents` specifics).
- `SKILL.md`: update all tool invocations for the new CLI; verify the vendor pricing-pass orchestration rules (per-vendor subagents, shipping-policy-first, browser discipline, concurrency cap) survive in SKILL.md or vendors.md after PR #3's doc reorganization — if any were lost, restore them from git history.
- `vendors.md`: human-facing vendor notes only after the §4 registry migration.

## 12. Tests and housekeeping

- Rework the existing per-platform mock-transport suites to the new surface and keep their fixtures. Cover: the shared batch model (multi-store parallel, input-order output, one store's bot_wall not affecting others, registry hit skips detection, `--redetect` refreshes, contradiction overwrites, registry write locking) across search, product, and quote; search multi-query dedup and product-level collapse (multi-variant product → one item, variant names, price range); run cache write + handle resolution (`product`/`quote` via handles, variant handles, GC'd-run ToolError, `images` range download from cached URLs, monotonic counter surviving GC and concurrent allocation, same-store items sharing the `<run>.<s>` prefix); mixed URL/handle/ref inputs; ref round-trip (search → product → quote) and line-vs-store origin mismatch rejection; multi-line quote per platform incl. quantity mapping and Woo multi-line cleanup; URL resolution per platform incl. a Woo variable product; description strip+truncate helper; token-lean output rules (§10, incl. `--debug` restoring detail); destination precedence (flag > settings > constant); unsigned-Shopify-when-unconfigured vs api_error-when-key-missing; each marketplace adapter (mocked: search mapping, detail where supported, token minting, missing-credential errors, Global Catalog merchant upsert, eBay shipping-in-detail).
- Registry seed: test `vendors.seed.json` import/merge.
- Full test suite green via `uv run`. No live network calls in tests.

## Out of scope

MCP server entry point (planned follow-up; §2's library/CLI split is its enabler — do not build the server now). Retry/backoff politeness. `web-bot-auth/` worker changes (PR #1). PyPI publication mechanics and the new repo extraction. Amazon first-party API (Creators API requires an active affiliate business — Amazon coverage is SerpApi leads only). Do not add flags or features beyond this plan.
