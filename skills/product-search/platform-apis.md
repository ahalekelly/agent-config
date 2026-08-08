---
created: 2026-07-31
verified: 2026-08-02
---

# Storefront platform APIs

Use `cross-shop` after discovery identifies vendors that need live product data or destination shipping. Start with the package's plain HTTP adapters and escalate to BrowserSwarm only at an explicit runtime or wall boundary.

## CLI

From the product-search directory:

```sh
uv run --project cross-shop cross-shop search '[{"store":"https://example.com","query":"bearing"}]'
uv run --project cross-shop cross-shop product '["r1.1.1"]'
uv run --project cross-shop cross-shop quote '[{"store":"https://example.com","lines":[{"item":"r1.1.1.2","quantity":2}]}]'
uv run --project cross-shop cross-shop images r1.1.1 1:3
```

`search`, `product`, and `quote` are batch commands. They group work by canonical store, run up to five stores concurrently, keep one session per store, consult the vendor registry before detection, and preserve input order. `--redetect` refreshes registry facts. `--debug` adds detection and request evidence omitted from token-lean default output.

Search emits product-level handles, never variant refs. Product detail emits strict readable refs per variant. Handles are seven-day conveniences tied to a monotonic run ID; refs are durable exact identities and are reverified against the live store. Product URLs containing queries or fragments are rejected rather than dropping possible identity components; use a durable ref instead.

The destination defaults to 747 Howard St, San Francisco, CA 94103, US. Override it persistently with `config set-destination` or per quote with `--destination`. Create only anonymous carts needed for rates. Never submit an order, create an account, enter payment, or repeatedly mutate a challenged endpoint. Empty rates mean no quote, never free shipping. Exclude pickup, deferred freight, paid-later, and quote-later methods from delivered-price comparisons.

## Amazon ASIN hydration

Amazon's undocumented All Offers Display endpoint provides useful primary-source data for a known US ASIN without an API credential. It does not search Amazon. Discover the product first, then pass its exact ASIN or US `/dp/` URL to the bounded helper:

```sh
AMAZON_PRODUCT=scripts/amazon_product.py

uv run "$AMAZON_PRODUCT" B0CZP3CDSZ
uv run "$AMAZON_PRODUCT" 'https://www.amazon.com/dp/B0CZP3CDSZ'
```

The helper creates one anonymous session with `GET /`, then performs one read-only request to `GET /gp/product/ajax/aodAjaxMain/ref=auto_load_aod?asin=ASIN&pc=dp`. A successful result contains the title, product image, rating state, and an explicit offer state. Available offers contain condition, USD price, seller, shipper, and structured delivery promises. The `reported_other_offer_count` can exceed the offers embedded in the response; `other_offers_complete` makes that truncation explicit.

`delivery_scope:anonymous_default_location` means Amazon selected the location. Those promises are neither an SF quote nor evidence for the user's destination. An offer is current offer-panel evidence, not an inventory count. A response without reviews is `unrated`; no buyable offer is `no_offers`; no featured offer alongside marketplace offers is an available offer set with `featured.status:unavailable`.

HTTP 404 is `aod_unavailable` because some valid products use a different offers interface. It is not evidence that the ASIN does not exist. Other non-200 responses and unexpected HTML are terminal errors: do not retry, rotate proxies, or add a challenge bypass. The helper discards cookies, add-to-cart values, CSRF tokens, and offer tokens and never mutates a cart.

This is unstable storefront plumbing, not a supported contract. Amazon's robots policy disallows its named AI crawler user agents, so use the helper only when Amazon is explicitly within the task's scope and keep each lookup bounded. For a supported production integration, prefer the official Amazon Business Product Search API when the required business onboarding, catalog role, customer identity, and access token are available.

## Detection and dispatch

Homepage redirects establish the canonical storefront origin. The registry records only confirmed real storefronts; marketplace pseudo-stores are built in.

| Platform | Positive evidence | Product path | Quote path |
| --- | --- | --- | --- |
| Shopify | tokenless Storefront GraphQL returns `data.shop`; source may identify one `.myshopify.com` API origin | product-by-handle Ajax JSON / exact variant GraphQL | one `cartCreate`, deferred delivery groups |
| WooCommerce | bounded Store API products request returns an array | products by search, slug, or ID; variations endpoint for variable products | one cart token, repeated add-item, one customer update, cleanup every line |
| Magento | GraphQL capability response; Magento page markers select HTML search when GraphQL is unavailable | stable detection-selected GraphQL or HTML strategy | one REST guest cart, repeated items, one estimate call |
| BigCommerce | BigCommerce CDN/Stencil signals | search page plus product-page `BCData` | one Storefront REST cart and checkout consignment |
| Squarespace | Squarespace server/assets and commerce JSON | product URL with `?format=json` | repeated cart entries and one shipping-location update |
| Wix / Ecwid | public runtime/catalog bootstrap | public catalog APIs | browser/runtime boundary |
| Salesforce Commerce Cloud | Demandware routes, headers, or site ID | site-local search convention | customized SFRA flows are a browser boundary |
| OpenCart | `/catalog/view/` assets and cart route | page-specific products/options | browser/site-specific boundary |

A readable marker can classify a platform but cannot prove its cart API works. A challenge before positive platform evidence is a wall, not evidence of a platform.

## Shopify

Catalog and cart traffic uses `POST /api/2026-07/graphql.json`. Search requests product descriptions, images, variants, selected options, exact IDs, availability, and money. Product URLs resolve through `/products/<handle>.js`; exact variant refs resolve through GraphQL. A failed exact live lookup is an error rather than a cached or search-derived product response.

Quote sends every selected variant in one `cartCreate(input.lines)` call and places the destination in `buyerIdentity.deliveryAddressPreferences`. Carrier-calculated rates use `deliveryGroups(first:10,withCarrierRates:true)` under `@defer`. The response can be MIME multipart: parse every JSON part, apply incremental patches, and require terminal `hasNext:false`. `PICK_UP`, `PICKUP_POINT`, and `RETAIL` are pickup; `NONE` is unavailable; priced `LOCAL`/`SHIPPING` options are delivery.

Shopify is unsigned unless `settings.web_bot_auth` is configured. Signing validates the Ed25519 key's JWK thumbprint, creates fresh replay material, and follows only one same-authority redirect to the Storefront API path. Signature headers and private material never enter logs.

Dated behavior: on 2026-07-31, 12/12 stores completed discovery, cart creation, and a rate request; eight returned rates and four returned empty arrays. Tested rates ranged from named free delivery to large LTL charges. Treat those observations as evidence of protocol coverage, not current prices.

## WooCommerce

Detection and search use `/wp-json/wc/store/v1/products`. URL detail resolves by `slug`; exact refs resolve by product ID. Variable products require exact variations rather than guessing options.

Quote first gets `/cart` and its `Cart-Token`, repeats `/cart/add-item` for every line, verifies the returned cart contains each selected product/variation, rejects quantities below each product minimum, updates the customer once, reads nested `shipping_rates`, then deletes every added cart item. Cleanup runs after any successful add, including later add or parse failures, and every delete must succeed before a quote is emitted. Store API amounts are integer strings scaled by `currency_minor_unit`. A rate ID ending in `_fallback` is not a verified carrier rate.

Dated behavior: on 2026-07-31, 12/12 stores completed the cart/address flow; seven returned rates, five were empty, and one rate was explicitly fallback.

## Magento / Adobe Commerce

Detection sends one GraphQL capability query. Usable `storeConfig` and `products.total_count` select `search_source:graphql`. Independent Magento markers plus unavailable GraphQL select `search_source:html`. Redirects, 429/5xx, transient transport failures, and contradictory proven-Magento shapes fail loudly. Search never changes strategy mid-operation.

GraphQL search hydrates candidate SKUs through bounded detail queries, preserves partial data with errors, expands configurable children into exact simple SKUs, and uses `product_url_suffix`. HTML search stays on the canonical origin and extracts exact simple SKUs from JSON-LD or Magento page state.

Quote creates one `/rest/V1/guest-carts` cart, adds all SKUs to its masked ID, reads `/totals`, and calls `/estimate-shipping-methods` once. Quote currency comes from `quote_currency_code`; base amounts use `base_currency_code`. Exclude unavailable, pickup, and ambiguous zero-dollar freight/account methods.

Dated behavior: on 2026-07-31, ten open guest-cart stores all returned methods; two independently detected controls gated guest carts. Glacier Tanks required a fingerprint browser only to establish Cloudflare state before same-origin guest REST worked.

## BigCommerce Stencil

Search uses `/search.php?search_query=…`, ranks canonical same-origin product links, and hydrates product pages. `BCData.product_attributes` provides product ID, SKU, price, stock, purchasability, and required configuration. Required choices are never guessed.

Quote clears pre-cart cookies, sends all `lineItems` to `/api/storefront/carts`, requires physical item IDs plus `SHOP_SESSION_TOKEN` and `SF-CSRF-TOKEN`, then creates one checkout consignment containing all lines and the mapped destination. Read `availableShippingOptions`; pickup and paid-later labels remain non-comparable.

Dated behavior: on 2026-07-31, 11/11 stores returned nonempty primary Storefront REST rates, 43 methods total. The older product-form remote shipping estimator is diagnostic only and is not a fallback for a failed primary path.

## Squarespace

Product and collection data comes from `?format=json`. Variant `onSale` and `unlimited` default false when absent; `qtyInStock` defaults to zero. Exact item ID and SKU form the ref.

Quote reads a collection to establish the `crumb`, posts every line to `/api/commerce/shopping-cart/entries` in one session, and verifies each response contains the requested item ID and SKU. All adds must preserve one cart token. It then sends one `PUT /api/3/commerce/cart/<token>/shipping/location`. Interpret both `shippingOptionsStatus` and `fulfillmentOptions`; `SHIPPING_NOT_REQUIRED` and `POSTAL_CODE_NOT_APPLICABLE` are not parcel quotes.

Dated behavior: three exact-address tests produced one priced delivery result, one shipping-not-required result, and one postal-code-not-applicable result.

## Wix, Ecwid, SFCC, and OpenCart boundaries

Wix public discovery uses the site-local anonymous e-commerce token and Catalog Reader endpoint. Ecwid discovery obtains store ID, API base, and the public storefront token from bootstrap data before querying products. Neither generic bootstrap establishes portable destination cart state, so quote returns an explicit browser-required error.

SFCC exposes conventions rather than one anonymous API. Public search stays under the detected locale entry URL. Standard SFRA checkout can work, but modified controllers, exact form fields, CSRF, and shipment state are merchant-specific. On 2026-07-31, Dunlop completed a standard guest flow; Alcott returned 500 and HUGO BOSS redirected to HTML.

OpenCart options are page-specific. StepperOnline accepted a known product only after a warehouse option, then challenged the cart write. Report that wall rather than repeating writes.

## Marketplace pseudo-stores

| Origin | Contract | Interpretation |
| --- | --- | --- |
| `https://shop.app` | Shopify `https://catalog.shopify.com/api/ucp/mcp`, JSON-RPC `tools/call` using `search_catalog` and `get_product`; every call carries the configured UCP agent profile in `arguments.meta.ucp-agent.profile` | first-party Shopify catalog facts; quote a concrete merchant offer |
| `https://www.aliexpress.com` | Affiliate Product Query with TOP HMAC-MD5 signing | affiliate-promotable leads; no exact cart quote |
| `https://shopping.google.com` | SerpApi `google_shopping` | unverified cross-merchant leads |
| `https://www.amazon.com` | SerpApi `amazon` organic results | listings only; no anonymous Amazon cart API |
| `https://www.ebay.com` | Browse `item_summary/search`, `getItem`, and `getItemByLegacyId`; lazy OAuth client credentials; encoded contextual-location header | shipping appears in detail; checkout is restricted-tier |

Shopify Global Catalog models each merchant offer under that offer's seller storefront and API domains, preserves variant and checkout handoff links, and supports mixed merchant currencies without forcing product-level USD. It is the only marketplace source allowed to seed merchant origins into `vendors.json`, because its merchant identity is first-party platform data. AliExpress and SerpApi results never seed the registry.

## Data hygiene and failures

Default output contains no request evidence, cookies, bearer material, cart IDs, masked IDs, signature headers, image URLs, or search refs. `--debug` restores sanitized detection and request summaries for search, product, and quote, never secrets. `config show` reports credential presence without returning credential values or private-key paths.

Errors are compact: `status`, `platform`, `stage`, `reason`, and `http_status` when known. Missing marketplace setup is an error only for the requested pseudo-store. Transport/schema/invariant failures are loud; there are no fallback APIs or guessed buyer choices.

Never persist cookies, Woo cart tokens, Shopify cart IDs, Magento masked IDs, BigCommerce session/CSRF/cart IDs, Squarespace crumbs/cart tokens, Wix/Ecwid tokens, SFCC CSRF/session state, OAuth tokens, private keys, API secrets, or HTTP Message Signatures.

## Verification

The package test suite uses mock transports and fixtures only:

```sh
uv run --project cross-shop pytest
```

Live smoke tests are deliberate and separate. Inspect product detail and select an exact variant ref before any cart request. Dated acceptance results in this document describe observed protocol behavior, not prices or availability that tests should pin.

## References

- [Shopify Storefront carrier rates with `@defer`](https://shopify.dev/changelog/fetching-carrier-calculated-rates-through-defer-directive-in-storefront-graphql-api)
- [Shopify Global Catalog](https://shopify.dev/docs/agents/catalog/global-catalog)
- [eBay Browse API](https://developer.ebay.com/api-docs/buy/browse/overview.html)
- [SerpApi Google Shopping](https://serpapi.com/google-shopping-api)
- [SerpApi Amazon](https://serpapi.com/amazon-search-api)
- [AliExpress Affiliate Product Query](https://developer.alibaba.com/docs/api.htm?apiId=45803)
- [Amazon Business Product Search API overview](https://docs.business.amazon.com/docs/product-search-api-overview)
- [Amazon Business Product Search request requirements](https://docs.business.amazon.com/docs/initiating-a-search)
- [Amazon robots policy](https://www.amazon.com/robots.txt)
