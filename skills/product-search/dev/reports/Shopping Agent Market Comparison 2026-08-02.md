# Shopping Agent Market Comparison — 2026-08-02

How the storefront tool (plan: `dev/plans/platform-refactor.md`) compares to AI-agent shopping assistants on the market that could be used with Claude Code. Research fan-out: GPT Sol (Pi) + Opus web research, 2026-08-01/02.

## TLDR

Nobody on the market combines the three things this tool does: **cross-platform search of arbitrary independent stores, canonical variant resolution via the store's own API, and pre-checkout shipping quotes via guest carts** — all keyless and free. Competitors split into five categories: catalog search (Shopify Catalog MCP, Channel3, SerpApi), marketplace resellers (Zinc, Rye), checkout orchestration (Rye, Crossmint, Firmly), payment protocols (ACP, AP2, UCP, Visa/Mastercard), and browser automation (Playwright MCP, Browserbase). Sol's verdict: the defensible part of the design is the platform-aware resolution and guest-cart shipping layer.

Checkout is on this tool's roadmap, which reframes the checkout-capable services from competitors into candidate backends: our guest-cart quote flow is literally the first half of every platform's native checkout flow, and the marketplaces where we can't checkout natively (Amazon, Walmart, Target) are exactly where Zinc ($1/order) and Rye already operate. The flip side today: on the big marketplaces we are strictly worse than Zinc for data, and for pure Shopify discovery the free Global Catalog MCP already exists — our value there is federating it with everything else and adding the shipping layer it lacks.

## The market, by category

### Cross-merchant catalog search

| Tool | Coverage | Shipping quotes | Access | Cost |
|---|---|---|---|---|
| **Shopify Global Catalog MCP** | Eligible Shopify merchants (5.6M stores default-on since Mar 2026) | No | Keyless; requires `meta.ucp-agent.profile` URL per request | Free |
| **Channel3** (trychannel3.com) | 100M+ products, 25k+ brands, incl. non-Shopify | No (cart/checkout "Coming Soon") | MCP at `mcp.trychannel3.com`, no API key on free tier | 1k free searches, then ~$7/1k reported |
| **SerpApi** | Google Shopping, Amazon, Walmart, eBay engines | No | API key, instant | 250 free, then ~$25/1k |
| **Logimu / Forage / BigGo / BuyWhere** (shopping MCPs) | Big marketplaces / proprietary hosted catalogs | No | Mostly free tiers | Varies |

None of these resolve variants against the merchant's own API or produce shipping quotes. The open-source shopping MCP ecosystem is thin wrappers around proprietary hosted catalogs — nothing self-contained, nothing with shipping. **Channel3 is the notable new entrant**: the closest keyless competitor to Shopify's Global Catalog, with different (broader-than-Shopify) coverage, and 7–7.7% commission on trackable links as a possible revenue path.

### Marketplace resellers (data + ordering via managed accounts)

| Tool | Retailers | Search | Shipping | Checkout | Cost |
|---|---|---|---|---|---|
| **Zinc** | Amazon, Walmart, Target, Best Buy, eBay, Home Depot, Lowe's, Wayfair, +6 | Yes (per-retailer + cross-retailer beta) | As part of order resolution | Yes ($1/order) | $0.01/API call, $15 min deposit, self-serve |
| **Rye** | Amazon + any product URL (browser automation) | No — URL-in only | Yes (checkout intent resolves shipping + totals) | Yes | $149/mo + $0.02/fetch + $0.05/order |

Zinc is the surprise: self-serve, cheap, has search, and exposes an accountless HTTP-402 "MPP" path (`/agent/product-search`, `/agent/product-details`, …, $0.01/call) with a Claude Code skill (`npx skills add zincio/skills`). **For Amazon/Walmart/Target/Best Buy data, Zinc is a credible alternative to SerpApi** and the only self-serve search+purchase provider. Rye's real reliability (own whitepaper): Amazon 99%, Shopify 96%, generic AI flows 65% with ~5-min latency — below its "90%+" marketing.

### Checkout orchestration & agent payments

Crossmint (URL + spending cap → completed purchase), Firmly.ai (best-documented shipping-quote lifecycle but no self-serve signup, unpublished pricing), Skyfire, Nevermined, x402 — all purchase infrastructure, irrelevant to a quote-only tool except as the adjacent market. Nate imploded (DOJ fraud indictment — the "AI" was a Philippine call center).

Protocols: OpenAI/Stripe **ACP** (beta, ChatGPT Instant Checkout is consumer-only), Google **AP2** (spec + partners, no callable service), **UCP** (the one with real endpoints — Shopify's catalog MCPs implement it; Amazon joined the UCP Tech Council 2026-04-24 as governance only), Visa Intelligent Commerce (free sandbox), Mastercard Agent Pay (enterprise). None substitute for buyer-side search or shipping quotes today.

### First-party marketplace APIs

- **Amazon**: no sanctioned individual-developer shopping API. Creators API is affiliate-gated with a hard eligibility floor (10 qualifying sales/trailing 30 days, revoked after 30 quiet days), max 100 results/query, and **zero shipping data**. Sleeper: **Amazon Business API** has product search *with delivery estimates*, cart-level shipping/tax costs, and ordering — but access is email-approval-gated (ab-api-access-approvals@amazon.com), timeline/cost unpublished. Nova Act ($4.75/agent-hour) is a browser agent, not a commerce API.
- **eBay Browse API**: better than planned — `shippingOptions` come back **inline in search results**, not just item detail, when `X-EBAY-C-ENDUSERCTX` (contextualLocation) + `X-EBAY-C-MARKETPLACE-ID` are supplied; silently absent otherwise. Free, 5k calls/day self-serve (growth check → 100k/day). eBay ships an official read-only MCP ([eBay/npm-public-api-mcp](https://github.com/eBay/npm-public-api-mcp)).
- **AliExpress**: gateway moved to `api-sg.aliexpress.com/sync` with SHA-256 signing (old TOP MD5 gateway deprecated — our existing client may need updating). Affiliate API has no SKU/variant matrix (product-level only; variants need the harder-approval Dropshipping API), and freight calculation requires OAuth user authorization beyond the app key.

### Browser automation (the universal fallback)

Playwright MCP (free, local), Browserbase/Stagehand (free tier: 1 browser-hour; $20/mo: ~100 hrs). Can reach any store's shipping stage but slow, brittle, bot-walled — and now legally fraught: eBay's User Agreement (eff. 2026-02-20) bans "buy-for-me agents, LLM-driven bots" placing orders without human review (**search and quoting explicitly unaffected — exactly our scope**), and the Amazon v. Perplexity CFAA appeal is submitted at the Ninth Circuit with no ruling. We already have browser-swarm for this; the storefront tool's whole point is to make API paths cover enough that the browser is rarely needed.

## Head-to-head: storefront vs. the field

**What only we do:**
- Shipping quotes on arbitrary long-tail stores, pre-checkout, via each platform's own guest-cart API (Shopify Cart API, Woo Store API, Magento guest-carts, BigCommerce consignments). Rye is the only competitor that resolves shipping, at $149/mo, via browser automation, inside a checkout flow.
- Merchant-native variant resolution (SERP APIs and catalog aggregators return variant-ambiguous leads).
- Batch, token-lean CLI output designed for agent context budgets — every hosted MCP returns whatever it returns.
- Free and keyless for the platform adapters; optional keys only for marketplace pseudo-platforms.

**What the market does that we don't yet:**
- Checkout/purchase (Zinc, Rye, Crossmint, ACP) — on our roadmap; see the checkout section below.
- Amazon-native data depth (Zinc/Canopy/Rainforest have offers, reviews, price history; our SerpApi leads are shallower).
- Hosted 100M-product single-index search (Channel3, Shopify Catalog) — we federate instead of index.

## Checkout roadmap: the quote layer is half the work

Every platform adapter's quote flow (cart → items → destination → rates) is the front half of that platform's native checkout; the back half is payment + confirm:

- **Shopify**: furthest along in the industry — UCP cart/checkout capabilities on the same MCP endpoints, or classic Cart API → checkout URL handoff. Native agent checkout is realistic here first.
- **WooCommerce**: Store API has a genuine `/checkout` endpoint; guest orders work for gateways with hosted/tokenized payment.
- **Magento**: the same guest-cart REST path we use for quotes continues to `payment-information` order placement.
- **BigCommerce**: consignment checkout exists but payment needs store-scoped API credentials — likely browser or handoff territory.
- **Marketplaces**: no native path. **Zinc** ($1/order, managed accounts, self-serve, Claude Code skill) is the obvious Amazon/Walmart/Target/Best Buy checkout backend; **Rye** ($149/mo) for arbitrary-URL checkout; **Crossmint** if we want them to hold the payment method. These are integrations to buy, not systems to beat.
- **Payment credentials**: once we hold any, ACP/AP2/Visa Intelligent Commerce/Mastercard Agent Pay become relevant as the tokenization layer — or Crossmint abstracts it.
- **Legal shape**: eBay's ToS bans agent order placement *without human review* — so the checkout command should be built around an explicit human confirmation step anyway, which also keeps us clean everywhere else.

Design consequences worth honoring in v1 (cheap now, painful to retrofit): keep the cart/session identifiers from quote flows in the run cache so a future `checkout <handle>` can resume the same cart instead of rebuilding it, and reserve the failure taxonomy (`gated`, `browser_required`) to describe checkout capability per platform.

## Implications for the plan (not yet applied — plan §s reference platform-refactor.md)

1. **§9 Shopify Global Catalog is stale**: endpoint is now `POST https://catalog.shopify.com/api/ucp/mcp`, tools renamed to UCP-style (`search_catalog`, `lookup_catalog`, `get_product`), auth is a `meta.ucp-agent.profile` URL rather than the client-credentials JWT the plan describes. Per-store Storefront MCP likewise at `{shop}.myshopify.com/api/ucp/mcp`. Verify live before coding.
2. **§8 eBay**: request `shippingOptions` in *search* via the ENDUSERCTX header (the plan only uses it for detail); same silent-absence trap class as elsewhere.
3. **§8 AliExpress**: confirm our existing client targets `api-sg.aliexpress.com` with SHA-256, not the deprecated TOP gateway; note variant and freight limitations.
4. **Consider Channel3** as a keyless second global-catalog source alongside Shopify's, and **Zinc MPP** as the Amazon/Walmart/Target/Best Buy data source instead of (or beside) SerpApi — cheaper ($0.01/call), structured, self-serve.
5. **Amazon Associates legal trap for the affiliate roadmap**: the Operating Agreement bars affiliate Content/Special Links in "any client-side software application… executable or installable by an end user." A locally-installed CLI/MCP is squarely that. If Amazon affiliate links are ever added, they likely must be served from a hosted component, or Amazon routed through Zinc/SerpApi with no Associates credential in the tool. (eBay's parallel restriction doesn't bite: search/quoting explicitly allowed.)

## Sources

Key links surfaced by the research agents:

- Shopify Global Catalog MCP: https://shopify.dev/docs/agents/catalog/global-catalog · UCP changelog: https://shopify.dev/changelog/storefront-catalog-mcp-now-implements-ucp · Cart API for shipping: https://shopify.dev/docs/storefronts/headless/building-with-the-storefront-api/cart/manage
- Channel3: https://docs.trychannel3.com/
- Zinc: https://www.zinc.com/pricing · docs: https://www.zinc.com/docs/quickstart
- Rye: https://rye.com/docs/api-v2/introduction · https://rye.com/pricing · checkout whitepaper: https://rye.com/blog/whitepaper-universal-checkout-api-agentic-commerce
- ACP: https://github.com/agentic-commerce-protocol/agentic-commerce-protocol · https://openai.com/index/buy-it-in-chatgpt/
- AP2: https://cloud.google.com/blog/products/ai-machine-learning/announcing-agents-to-payments-ap2-protocol
- Amazon Creators API: https://affiliate-program.amazon.com/creatorsapi/docs/en-us/introduction · Associates participation rules: https://affiliate-program.amazon.com/help/operating/participation/ · Amazon Business API: https://docs.business.amazon.com/docs
- eBay Browse requirements: https://developer.ebay.com/api-docs/buy/buy-requirements.html · official MCP: https://github.com/eBay/npm-public-api-mcp
- Crossmint: https://docs.crossmint.com/agents/agent-checkouts-quickstart · Firmly: https://developers.firmly.ai
- Playwright MCP: https://playwright.dev/docs/getting-started-mcp · Browserbase: https://www.browserbase.com/pricing
- Shopping MCPs: https://github.com/BuyWhere/buywhere-mcp · https://github.com/Funmula-Corp/BigGo-MCP-Server · Logimu (Claude connectors directory, Jul 2026)
