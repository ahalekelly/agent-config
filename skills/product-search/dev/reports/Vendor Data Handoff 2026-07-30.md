# Vendor Data Access — Handoff, 2026-07-30

Session covered headless engines, Amazon access, and platform storefront APIs. Living docs are already updated; this is the state-of-play and what to pick up next.

## The headline

**Platform storefront APIs solved the problem the browser research was chasing.** Shopify's Storefront GraphQL API grants **tokenless cart read/write** — `cartCreate` with the destination in `buyerIdentity`, then `deliveryGroups(withCarrierRates: true)` inside `@defer` — returning the vendor's real shipping rates in ~1s with no credentials. Verified live on a dozen stores by a subagent and independently replicated (Standard $9.99 / Two Day $18.99 / Overnight $32.99 on `redbullshopus.com`). WooCommerce's Store API is equivalent via a `Cart-Token` header.

The same tokenless tier also answers per-store keyword search and returns SKU, **barcode** (a cross-vendor matching key), price, `availableForSale`, **weight** (feeds carrier estimates), images and shop policies — plus server-side filtering and sorting, which search cannot do at all. Stock is boolean; `quantityAvailable` needs a scope tokenless access doesn't grant.

So the browser is now the residue path, not the main one.

## Also established

- **DataDome blocks every headless engine tried** (seven configurations, live vendors). **Akamai does not** — plain Firefox clears it, as does a fingerprint-patched Chromium, which unlike Firefox can serve a CDP daemon.
- **Detection was wrong**: `403` is not the signal. AWS WAF challenges with **202**, CAPTCHAs **405**, Kasada opens **429**, Fastly blocks **406**, Radware and Queue-it redirect without leaving 2xx, Imperva sometimes serves blocks under **200**.

## Where things live

| Doc | Holds |
|---|---|
| `product-search/SKILL.md` | source ladder, platform storefront API technique, pricing pass |
| `product-search/vendors.md` | per-vendor cached facts incl. Amazon's access situation |
| `product-search/dev/reports/Vendor Data Access.md` | benchmark data, agentic-commerce landscape, leads |

## Next steps, in order

1. **Run the tokenless quote against the vendors in `vendors.md`.** Verified only on a consumer store so far. What fraction of our 29 tracked vendors run Shopify or WooCommerce decides whether this is workflow-changing or niche. Cheap scripted pass; everything else sequences off it.
2. **Write the platform-detection recipe.** The pricing pass says "check the platform first" without saying how. Prerequisite for the whole path.
3. **Renew Digi-Key MCP credentials** (401 since 2026-07-30 — a working source lost to expiry) and **get a free Mouser API key** (Mouser is Akamai+DataDome and unreachable by any engine tested). Both sign-up-and-paste.
4. **Test Magento / Adobe Commerce** guest-cart shipping estimation — biggest untested platform, skews to the industrial distributors we actually buy from.
5. Lower: register for **Shopify Web Bot Auth** before scaling (we're an unsigned bot on the strictest limits); swap the shared daemon binary to **fingerprint-chromium** so the residue browser path clears Akamai; measure real WooCommerce Store API coverage (sample was n=3).

Drop the ACP/UCP thread unless wanted for its own sake — neither protocol is a data source, and the platform APIs deliver the quote it might have provided.

## Blockers and loose ends

- **Org monthly spend limit reached** — killed the ACP agent; further delegation fails until it resets. Items 1–3 above are shell work that doesn't need agents.
- **Eight unpushed commits** on `~/.agents` main, five from this session. Uncommitted changes to `settings.json`, `statusline.sh` and the `pi-for-claude` submodule are not from this session.
- Unverified leads carried in `dev/reports/Vendor Data Access.md`: Magento, storefront search providers shipping public Algolia/Searchspring keys, the free-API-key list.
