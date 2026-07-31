# Storefront platform APIs

Use these workflows after search identifies a store and live product data or a destination shipping quote is needed. Start with plain HTTP. Escalate to BrowserSwarm only at an explicit browser boundary.

## Safety and interpretation

All shipping probes use this dummy destination:

```text
Jordan Smith
Pacific Prototyping LLC
747 Howard St
San Francisco, CA 94103
US
415-555-0132
```

Create only anonymous carts needed to calculate rates. Never submit an order, create an account, enter payment details, or repeatedly mutate a challenged cart endpoint.

Use these outcomes consistently:

| Outcome | Meaning |
| --- | --- |
| `quote` | One or more destination-specific delivery methods returned. A named zero-dollar delivery method may be real free shipping. |
| `empty` | The rate list is empty. This is no quote, never free shipping. |
| `fallback` | A provider-specific marker says a merchant fallback replaced a failed live carrier calculation. Keep it distinct from a live quote. |
| `gated` | A known storefront API refused the operation because merchant or customer authorization is required. |
| `bot_wall` | The response contains positive challenge evidence. A generic 401/403 is not enough to name a wall or platform. |
| `unsupported_operation` | The platform is detected, but the CLI intentionally has no generic product or quote adapter for that operation. |
| `unsupported_product_configuration` | An exact product needs options or other configuration the CLI will not guess. |
| `tool_error` | Transport, parser, schema, or invariant failure. Fail loudly rather than inventing a result. |

Exclude pickup, local collection, deferred freight, `PAID LATER`, and similarly unpriced methods from delivered-shipping comparisons. Preserve them as warnings when useful. Rates and prices below are observations from 2026-07-31, not invariants.

## Production helper

Use the helper through its PEP 723 environment:

```sh
PLATFORM_API=/Users/akelly/.agents/skills/product-search/scripts/platform_api.py

uv run "$PLATFORM_API" detect STORE
uv run "$PLATFORM_API" search STORE QUERY
uv run "$PLATFORM_API" quote STORE ITEM_REF
uv run "$PLATFORM_API" probe STORE QUERY
uv run "$PLATFORM_API" corpus INPUT.json OUTPUT.jsonl
```

`detect` resolves the storefront origin and identifies the platform. `search` returns exact product candidates. Pass the selected candidate's `item_ref` verbatim to `quote`; its opaque representation is platform-specific and must not be guessed. `probe` selects the first available candidate that does not require configuration and performs the complete flow.

Product-search adapters cover Shopify, WooCommerce, Magento, BigCommerce, Squarespace, Wix, Ecwid, and Salesforce Commerce Cloud. Destination-quote adapters cover the first five. Wix, Ecwid, and Salesforce Commerce Cloud return `unsupported_operation` with `browser_required:true` for quote because their generic public search paths do not establish portable cart state.

Successful operation commands print one compact JSON record with `schema_version`, `observed_at`, `input`, resolved `origin`, `detection`, normalized `result`, and sanitized `evidence`. Result kinds are `search`, `quote`, `empty`, `fallback`, `gated`, `bot_wall`, `unsupported_operation`, and `unsupported_product_configuration`. `detect` and any command that cannot positively detect a platform omit `result`; the discriminated `detection` is the outcome. Contract, transport, parser, and schema errors print a terse message to stderr and exit nonzero.

Corpus input is a JSON array of 1–100 objects, each containing exactly two nonempty strings:

```json
[
  {"store": "https://example-store.test", "query": "bearing"},
  {"store": "https://another-store.test", "query": "gasket"}
]
```

The corpus command appends one JSONL record per store/query, resumes by skipping identities already present in the output, records per-store failures as `tool_error`, flushes after every record, and exits nonzero if any current or prior record is an error.

Magento quote currency comes from guest-cart `totals.quote_currency_code`; rate amounts and subtotal use that currency, while base amounts use `base_currency_code`. Missing currencies are schema errors. BigCommerce search hydrates at most three exact-ranked product pages and encodes the verified product ID plus canonical same-origin URL in its opaque `item_ref`; `quote` reloads that page, requires the same ID, and refuses required product configuration instead of guessing options.

## Detection and dispatch

Always follow the homepage redirect and probe the resolved storefront origin. An apex domain may only return 301, and a brand domain may redirect to a different commerce host.

| Platform | Positive evidence | Product path | Destination quote path |
| --- | --- | --- | --- |
| Shopify | `POST /api/2026-07/graphql.json` returns `data.shop`; a discovered `.myshopify.com` backend may be the API origin | tokenless Storefront GraphQL | tokenless Storefront GraphQL cart with deferred carrier rates |
| WooCommerce | `GET /wp-json/wc/store/v1/cart` returns a cart object with `totals` | Store API `/products` | `Cart-Token`, add item, update customer |
| Magento / Adobe Commerce | Magento markers plus a Magento-shaped guest-cart response; a quoted masked ID means open | public `/graphql`, sitemap, or product page | guest-cart REST when open |
| BigCommerce Stencil | `cdn*.bigcommerce.com/s-<hash>`, Stencil assets, or `x-bc-store-id` | sitemap/search/product form; conditional page token GraphQL | Storefront REST cart plus checkout consignment |
| Squarespace | Squarespace server/static assets and commerce collection JSON | `?format=json` collection data | anonymous cart entry plus shipping-location update |
| Wix | Wix/Pepyaka headers or Wix static assets | anonymous e-commerce app token plus Catalog Reader | Wix storefront SDK/runtime |
| Ecwid | `app.ecwid.com/script.js?<store-id>` or storefront API bootstrap | public storefront token plus V3 products | supported Ecwid cart runtime |
| Salesforce Commerce Cloud | `/on/demandware.` assets or Demandware response headers | site-specific search/product forms | standard SFRA guest checkout forms when unmodified |
| OpenCart | `/catalog/view/` assets and `index.php?route=checkout/cart/add` | page/search routes | site-specific form; options and walls vary |

Marker evidence is enough to classify a readable page, but not enough to claim that a public cart operation works. A challenge before positive platform evidence means the platform remains unknown.

## Evidence and redaction

Record only normalized evidence: resolved origin, platform signal, method, redacted endpoint, status, content type, elapsed time, response size/hash, normalized product fields, normalized rate fields, and the dated outcome.

Never persist these values in repository docs, fixtures, logs, or learned cache rows:

- request or response `Cookie`/`Set-Cookie`, WooCommerce `Cart-Token`, authorization headers, Web Bot Auth signature headers, or raw request headers;
- Shopify cart IDs/keys and checkout URLs;
- Magento guest-cart masked IDs;
- BigCommerce Storefront JWTs, `SHOP_SESSION_TOKEN`, `SF-CSRF-TOKEN`, cart IDs, checkout IDs, or raw success bodies;
- Squarespace crumbs, cart tokens, and add-to-cart identifiers;
- Wix and Ecwid storefront bearer tokens, checkout JWTs, or bootstrap blobs;
- Salesforce Commerce Cloud CSRF tokens and session cookies;
- private keys, API secrets, or any derived private key material.

Public page-emitted tokens are still bearer material. Keep live wire captures in an isolated temporary directory only when diagnosis requires them, then preserve a sanitized summary and hashes rather than credentials.

## Shopify

### Product search

Shopify's tokenless Storefront GraphQL endpoint is:

```sh
curl 'https://STORE/api/2026-07/graphql.json' \
  -H 'Content-Type: application/json' \
  --data-binary '{"query":"query($q:String!){products(first:20,query:$q){nodes{title handle variants(first:50){nodes{id title sku barcode availableForSale price{amount currencyCode} compareAtPrice{amount currencyCode} weight weightUnit}}}}}","variables":{"q":"bearing"}}'
```

Search exact identifiers as well as keywords. `availableForSale` is boolean stock only; tokenless access does not expose inventory depth. The barcode is often the best cross-store match key. Headless/custom storefronts may proxy the endpoint on their brand domain; otherwise discover the single `.myshopify.com` backend from source or `/admin` and probe it directly.

### Cart and rates

Create a cart with one exact variant and the dummy destination in `buyerIdentity.deliveryAddressPreferences`:

```graphql
mutation CartCreate($input: CartInput!) {
  cartCreate(input: $input) {
    cart { id cost { subtotalAmount { amount currencyCode } } }
    userErrors { field code message }
  }
}
```

```json
{
  "input": {
    "lines": [{"merchandiseId": "gid://shopify/ProductVariant/…", "quantity": 1}],
    "buyerIdentity": {
      "countryCode": "US",
      "deliveryAddressPreferences": [{"deliveryAddress": {
        "firstName": "Jordan", "lastName": "Smith", "company": "Pacific Prototyping LLC",
        "address1": "747 Howard St", "city": "San Francisco", "province": "CA",
        "country": "US", "zip": "94103", "phone": "+14155550132"
      }}]
    }
  }
}
```

The mailing address uses `country` and `province`; `countryCode` and `provinceCode` are not fields of `MailingAddressInput`. Then query rates with `@defer` on an inline fragment:

```graphql
query CartRates($id: ID!) {
  cart(id: $id) {
    ... @defer {
      deliveryGroups(first: 10, withCarrierRates: true) {
        nodes { groupType deliveryOptions { handle title code description deliveryMethodType estimatedCost { amount currencyCode } } }
      }
    }
  }
}
```

Send:

```text
Accept: multipart/mixed; deferSpec=20220824, application/json
```

The response is normally MIME multipart even for static rates. Parse the boundary, require JSON parts, apply incremental patches by path, and require a terminal `hasNext:false`. Do not concatenate bodies or assume the first part contains the rates. An empty `deliveryOptions` array is `empty`.

Shopify's cart total is pre-tax in this public path; `totalTaxAmount` is deprecated and null. Updating selected delivery options can fold shipping into `totalAmount`, but does not make the result tax-inclusive.

### Web Bot Auth

All Shopify requests should use `scripts/web_bot_auth.py` and the configured identity:

```python
from web_bot_auth import send_signed

request = client.build_request("POST", target_url, json=payload)
response = send_signed(client, request)
```

`send_signed` is the only public signing surface. It loads `/Users/akelly/.agents/web-bot-auth/private.pem`, verifies that the Ed25519 public JWK thumbprint equals `PtFPEn59EWaohh4V82GazSOYlIBm3LqPOhoLUu--1So`, signs the prepared HTTPS authority with a fresh 64-byte nonce and 60-second lifetime, and immediately sends with redirects disabled. It rejects credentials, non-HTTPS targets, preexisting signature headers, and replay of the mutated request. Build a fresh request and obtain a fresh signature for any validated HTTPS redirect target. Never log generated signature headers.

Shopify documents a better rate tier for authenticated bots. Bounded signed/unsigned trials at 3, 25, 50, and 100 requests all returned HTTP 200 on both paths and exposed no crossover or tier header, so the better tier is provider-documented but not empirically observable in this corpus.

On 2026-07-31 the public directory served the expected key but its response lacked the directory profile's required `Signature` and `Signature-Input`. Verify a signed directory response after deploying the directory Worker change before claiming that the identity path is operational end to end.

### Corpus result

Twelve of twelve stores completed product discovery, cart creation, and a rate request. Eight returned rates and four returned empty lists. All rate responses exercised multipart parsing.

| Store | Storefront shape | Result |
| --- | --- | --- |
| DERNORD | tracked, Liquid/custom domain | FedEx $55.00 |
| Mettle Air | tracked, redirected custom domain | four options, $27.78–$56.06 |
| Garage Cabinets Online | Liquid/custom domain | Standard $12.99 |
| Air Compressor Services | Liquid/custom domain | LTL $448.41 or $535.84 |
| VHS Hydraulics | UK Liquid | empty |
| Parker Hydraulics & Pneumatics | UK Liquid | empty |
| Carex | Liquid/custom domain | Standard $9.99 |
| SAS Locksmiths | Australia Liquid | empty |
| Sika Marketplace | Liquid/custom domain | empty |
| Manors Golf | Hydrogen/Oxygen | international economy £7.43 |
| Nour Hammour | Hydrogen/Oxygen | named `FREE`, €0.00 |
| ATTITUDE Living | Hydrogen/Oxygen, `.myshopify.com` API | Standard $12.99 |

## WooCommerce

### Product and cart

Probe the Store API and capture the response `Cart-Token`:

```sh
curl -i 'https://STORE/wp-json/wc/store/v1/cart'
curl --get 'https://STORE/wp-json/wc/store/v1/products' --data-urlencode 'search=bearing' --data 'per_page=20'
```

Use the token on every mutation:

```sh
curl -X POST 'https://STORE/wp-json/wc/store/v1/cart/add-item' \
  -H 'Cart-Token: …' -H 'Content-Type: application/json' \
  --data-binary '{"id":123,"quantity":1}'

curl -X POST 'https://STORE/wp-json/wc/store/v1/cart/update-customer' \
  -H 'Cart-Token: …' -H 'Content-Type: application/json' \
  --data-binary '{"shipping_address":{"first_name":"Jordan","last_name":"Smith","company":"Pacific Prototyping LLC","address_1":"747 Howard St","address_2":"","city":"San Francisco","state":"CA","postcode":"94103","country":"US","phone":"4155550132"}}'
```

Read `shipping_rates[].shipping_rates[]`. Prices and taxes are integer strings in `currency_minor_unit`; convert with decimal arithmetic. Preserve cart `totals.total_tax` and per-rate taxes when present. A `rate_id` ending `_fallback` is `fallback`, not a verified carrier rate. Cleanup with `DELETE /cart/items/<key>` is useful but separate from quote success; one tested store returned 403 on cleanup after a successful quote.

### Corpus result

All 12 stores completed the cart/address flow. Seven returned rates, five were empty, and one of the seven was explicitly `_fallback`.

| Store | SF result |
| --- | --- |
| Actisense | empty |
| GPS Pilot Supplies | empty |
| Pureseal Services | empty |
| F-O-A Shocks | empty; cleanup 403 |
| Resin Pro UK | two methods, £24.85–£29.85 |
| Rope Source | UPS or FedEx £80.00 |
| ProtoSupplies | three methods, $6.95–$16.95 |
| Maker Store USA | seven methods, $6.01–$35.35 |
| Rotary Solutions | named Free shipping $0.00 |
| Tech7000 | UPS Flat Rate $19.95, `_fallback` |
| NRG Wave | empty |
| MYOLYN | named USPS Flat Rate Envelope: FREE $0.00 |

## Magento / Adobe Commerce

### Detection and product search

An open guest cart returns a quoted masked ID:

```sh
curl -X POST 'https://STORE/rest/V1/guest-carts' -H 'Content-Type: application/json' --data-binary '{}'
```

Magento authorization JSON, an edge HTML block, and a generic 401 are distinct. Markers such as `x-magento-init`, `Magento_*` assets, `form_key`, `mage-cache-*`, and `x-magento-*` headers can establish the platform even when catalog or cart access is gated.

Use a narrow public GraphQL search before scraping a SKU:

```sh
curl 'https://STORE/graphql' -H 'Content-Type: application/json' \
  --data-binary '{"query":"query($search:String!){products(search:$search,pageSize:10){total_count items{__typename name sku stock_status url_key}}}","variables":{"search":"bearing"}}'
```

Query one exact parent SKU next for `storeConfig`, price range, and configurable children. Preserve usable partial `data` while recording GraphQL errors. If GraphQL is unavailable, validate same-origin `/catalogsearch/result/?q=…` links and extract exact simple SKUs from product JSON-LD or Magento page configuration. Add an in-stock simple SKU, never a configurable or bundle parent.

### Guest cart and rates

```sh
curl -X POST 'https://STORE/rest/V1/guest-carts/MASKED_ID/items' \
  -H 'Content-Type: application/json' \
  --data-binary '{"cartItem":{"quote_id":"MASKED_ID","sku":"SKU","qty":1}}'

curl -X POST 'https://STORE/rest/V1/guest-carts/MASKED_ID/estimate-shipping-methods' \
  -H 'Content-Type: application/json' \
  --data-binary '{"address":{"firstname":"Jordan","lastname":"Smith","company":"Pacific Prototyping LLC","street":["747 Howard St"],"city":"San Francisco","region":"California","region_code":"CA","region_id":12,"postcode":"94103","country_id":"US","telephone":"4155550132"}}'
```

Read carrier/method codes, titles, availability, `amount`, `price_excl_tax`, and `price_incl_tax`. Exclude pickup. Treat account-priced zero, “freight”, and similar ambiguous methods as unusable until verified; a named `freeshipping/freeshipping` zero is a real candidate.

### Corpus result

Ten of 12 stores exposed open guest carts and all 10 returned at least one method. Bulk Reef Supply was independently Magento-positive but its guest endpoint returned a merchant-branded CDN 403. Aheadworks was independently Magento-positive while the homepage was Cloudflare-challenged and the guest endpoint returned generic 401.

| Store | Result |
| --- | --- |
| SparkFun | 9 rates; USPS Ground Advantage $9.69 |
| DecksDirect | 3 rates; FedEx Ground $9.99 |
| Barr Display | 5 rates; FedEx Ground $17.97; pickup excluded |
| Scout Shop | 3 rates; USPS Ground $3.95 |
| Blanks.ca | 5 cross-border rates; FedEx Ground C$29.54 |
| Signet Australia | ambiguous $0 account/freight rate |
| ATX Fitness USA | explicit Free Shipping $0 |
| The CPAP Shop | 7 rates; merchant standard $8.99 |
| Dillon Precision | Standard Ground $11.95; hazardous handling unproven |
| TileBar | Economy Shipping $1.00 |
| Bulk Reef Supply | Magento positive; edge 403; no quote |
| Aheadworks | Magento positive; Cloudflare/generic 401; no quote |

Glacier Tanks is a browser-wall hybrid. Fingerprint Chromium establishes Cloudflare state, its page's Algolia integration supplies product discovery, and same-origin Magento guest REST then accepts the full dummy address. The exact 94103 run returned eight methods, with USPS Priority Mail lowest at $10.86.

## BigCommerce Stencil

### Product discovery

Use `/search.php?search_query=…` and product-page `BCData` or add-to-cart form fields. The helper canonicalizes search links, ranks exact matches, hydrates at most three product pages, and returns an opaque reference containing the verified product ID and canonical URL. Quote reloads the page and requires the same identity. It returns `unsupported_product_configuration` when required options remain unresolved; it never guesses them. A page-emitted, origin-constrained `storefrontApiToken` can enable conditional structured search at `POST /graphql`; never persist it. Tokenless GraphQL returned 401 on 11/11 stores.

### Storefront REST cart and consignment

Clear pre-cart cookies, then create a cart without prefetching a session:

```sh
curl -i -X POST 'https://STORE/api/storefront/carts' \
  -H 'Content-Type: application/json' \
  --data-binary '{"lineItems":[{"quantity":1,"productId":123,"optionSelections":[]}]}'
```

Require a cart ID, physical item ID, `SHOP_SESSION_TOKEN`, and `SF-CSRF-TOKEN`. Then create the exact-address consignment:

```sh
curl -X POST 'https://STORE/api/storefront/checkouts/CART_ID/consignments?include=consignments.availableShippingOptions' \
  -H 'Cookie: SHOP_SESSION_TOKEN=…' \
  -H 'X-SF-CSRF-TOKEN: …' \
  -H 'Content-Type: application/json' \
  --data-binary '[{"shippingAddress":{"firstName":"Jordan","lastName":"Smith","company":"Pacific Prototyping LLC","address1":"747 Howard St","address2":"","city":"San Francisco","stateOrProvince":"California","stateOrProvinceCode":"CA","countryCode":"US","postalCode":"94103","phone":"4155550132","email":"jordan.smith@example.invalid"},"lineItems":[{"itemId":"PHYSICAL_ITEM_ID","quantity":1}]}]'
```

The minimum tested request needs only the session cookie, content type, and CSRF header. Missing CSRF returned 403 HTML; missing session returned 401 `Checkout not found`. Read `consignments[].availableShippingOptions[]` and interpret zero methods by label. Do not silently fall back to another endpoint.

The older product-form `/cart.php` plus `/remote/v1/shipping-quote` estimator is a separately labeled diagnostic. It succeeded on 10/11 stores but Valin challenged `/cart.php`; that does not justify a browser because Valin's primary REST path worked. Use BrowserSwarm only when the primary REST request itself is blocked or customized beyond the standard contract.

### Corpus result

Storefront REST cart creation and exact-address consignment quoting returned nonempty rates on 11/11 stores, 43 methods total. A unified source scan found page tokens on 8/11 and structured product search succeeded 8/8.

| Store | Result |
| --- | --- |
| ServoCity | USPS $8.36; flat $11.99; FedEx $71.85/$129.22 |
| Hi-Line | flat $9.95 |
| Hydraulic Hose To Go | flat $17.99 |
| goBILDA | USPS $7.86; flat $11.99; FedEx $130.85/$210.48 |
| International Air Tool | ground $23.50; FedEx Ground $36.22 |
| SPW Industrial | named Free Shipping $0; FedEx $27.05/$54.26 |
| Fabric Warehouse | `PAID LATER` $0 excluded; valid shipping from $3.70 |
| Buckleguy | flat $8.99; carriers $18.85–$50.80 |
| DeBrovys | freight $3,460.48; liftgate $3,685.48 |
| TackleDirect | economy $4.99 through expedited $161.01 |
| Valin | 9 carrier rates, $33.91–$142.37; product price itself quote-only |

## Squarespace

Read collection JSON from a commerce collection URL with `?format=json`. Resolve an exact item ID and SKU, then load the product page in one cookie jar to obtain the crumb. Add the item with a unique request ID:

```sh
curl -X POST 'https://STORE/api/commerce/shopping-cart/entries' \
  -H 'X-CSRF-Token: CRUMB' -H 'Add-To-Cart-Id: UUID' -H 'Content-Type: application/json' \
  --data-binary '{"itemId":"ITEM_ID","sku":"SKU","quantity":1,"additionalFields":null}'
```

HTTP 200 with `error` or `crumbFail:true` is failure. Require `shoppingCart.cartToken`, then update location:

```sh
curl -X PUT 'https://STORE/api/3/commerce/cart/CART_TOKEN/shipping/location' \
  -H 'X-CSRF-Token: CRUMB' -H 'Content-Type: application/json' \
  --data-binary '{"line1":"747 Howard St","line2":"Pacific Prototyping LLC","city":"San Francisco","region":"CA","postalCode":"94103","country":"US"}'
```

Interpret both `shippingOptionsStatus` and `fulfillmentOptions`. Three exact-address cases produced: Marie Burgos KITSUI chair, Standard $161.13 and Oversized/Heavy $562.13; Frankly Good Coffee subscription, `SHIPPING_NOT_REQUIRED`; Archive07 shirt, `POSTAL_CODE_NOT_APPLICABLE`.

## Wix

Wix detection and public product data generalize, but destination cart quoting does not. Obtain an anonymous e-commerce app token from `/_api/v1/access-tokens`, then query `/_api/catalog-reader-server/api/v1/products/query`. Keep the token in memory only.

Cart creation requires Wix's supported storefront SDK/runtime because catalog-reference and renderer state are site-specific. Treat cart/address/shipping as a BrowserSwarm or merchant integration case. Three tested stores exposed public product data; none produced a generic destination quote.

## Ecwid

Discover the numeric store ID and `apiBaseUrl` from the storefront bootstrap. Obtain the public `ecwid-storefront` bearer token from `initial-data`, then query V3 products. Anonymous checkout creation can return a shipping amount before address, but that is fallback only.

The attempted internal checkout address update did not generalize. Use the supported Ecwid storefront runtime in BrowserSwarm, set the address through the cart interface, and read the recalculated cart. Do not replay internal `/checkout/update` calls as a public API.

## Salesforce Commerce Cloud

Salesforce Commerce Cloud exposes conventions, not one universal anonymous API. Resolve a concrete variant, establish a session and CSRF token, then follow the storefront's exact SFRA forms. A standard flow is:

```text
POST /on/demandware.store/Sites-<site>-Site/<locale>/Cart-AddProduct
GET  /on/demandware.store/Sites-<site>-Site/<locale>/Checkout-Begin?stage=customer
POST /on/demandware.store/Sites-<site>-Site/<locale>/CheckoutServices-SubmitCustomer
POST /on/demandware.store/Sites-<site>-Site/<locale>/CheckoutShippingServices-SubmitShipping
```

Preserve the page's session cookie, CSRF token, shipment UUIDs, exact form field names, and shipping method IDs. Dunlop completed the full plain-HTTP flow for exact 94103 and returned Ground $6.99, 2 Day $14.99, $3.19 tax, and $40.17 Ground total. Alcott returned 500 and HUGO BOSS redirected to HTML. Treat customized controllers as a BrowserSwarm/site-specific case rather than inventing fields.

## OpenCart and custom storefronts

OpenCart product options are page-specific. StepperOnline/OMC is OpenCart with Journal3 behind Cloudflare. A known product add without the warehouse option returned structured validation; the complete US warehouse selection returned a managed challenge and left the cart empty. No quote was reached. Report the endpoint-specific cart-write wall and stop repeated writes.

Bolt Depot is custom behind Cloudflare. A fingerprint-Chromium session can use its bespoke handlers:

```text
POST /Quick-Add?handler=ItemDescription
POST /Quick-Add?handler=AddItemsToCart
POST /ShoppingCart?handler=EstimateShipping
```

Keep clearance, shopper session, and page antiforgery token in one isolated context. The estimator accepts only country and ZIP, not the full street/identity. For US/94103 it returned six delivery methods, Economy lowest at $8.40; exclude Customer Pickup $0.

## BrowserSwarm boundary

Before browser work, read `~/.agents/browser-swarm/README.md`. Attach to the shared fingerprint-Chromium daemon through the documented MCP agent configuration. Use isolated contexts, respect the two-tab cap across the whole swarm, and stop existing fan-outs before starting more. Do not stop the shared daemon explicitly. Keep browser work headless/invisible and never use the user's interactive browser.

Production DataDome blocked every tested headless engine. Do not burn repeated probes trying to bypass it. Akamai-only storefronts were readable in headless Firefox or fingerprint Chromium. Browser evidence begins only after plain HTTP has positively identified a wall or an operation requires a supported runtime.

## Product and price aggregation

Aggregation APIs produce leads, not primary-source verification or merchant cart economics.

### Google-derived options

- Google Merchant API manages an authenticated merchant's own Merchant Center catalog; it cannot search public Google Shopping.
- SerpApi Google Shopping is the best occasional-search candidate because a synchronous response can include seller, extracted price, rating, delivery text, and detail tokens. Use the included client:

```sh
. /Users/akelly/.agents/secrets.env
uv run /Users/akelly/.agents/skills/product-search/scripts/serpapi_google_shopping.py 'Knipex Cobra pliers'
```

It requires `SERPAPI_API_KEY`, fixes the search to Google Shopping in San Francisco/US/English with direct retailer links requested, and returns normalized `lead` records plus an explicit primary-source verification requirement. It redacts the API key from provider and HTTP errors and fails on malformed or ambiguous result layouts. No key was configured for a real catalog response or acceptance corpus.
- DataForSEO is a bulk asynchronous option with submit-and-poll tasks and seller follow-ups. It needs Basic-auth credentials and explicit spend approval; no credentials were configured.
- Gemini search grounding produces synthesized text and citations rather than stable offer records. The configured credential was rejected during this evaluation.

Do not adopt an aggregator until a credentialed acceptance corpus checks direct seller links and agrees with live primary-source prices.

### AliExpress Affiliate Product API

The included client uses the official buyer-side Affiliate Product Query method:

```sh
. /Users/akelly/.agents/secrets.env
uv run /Users/akelly/.agents/skills/product-search/scripts/aliexpress_affiliate.py 'Knipex Cobra pliers'
```

It requires `ALIEXPRESS_APP_KEY` and `ALIEXPRESS_APP_SECRET`, sorts parameter names, concatenates each name and value, signs with HMAC-MD5, and sends the uppercase hex digest. It fixes the query to page 1 with at most 50 results and defaults to US ship-to, USD, and English. The output normalizes Affiliate records as `lead` evidence and requires live verification of the exact variant, price, stock, specifications, seller, and delivered cost. The Affiliate method does not require seller OAuth, but it covers only affiliate-promotable products and does not prove variant stock or destination cart rates.

No approved Affiliate credentials were available, so transport, encoding, response parsing, and invalid-key failure were tested but a real product response and signature acceptance remain unproven. Older onboarding pages are deprecated while the live method remains documented; treat new-app approval as a lifecycle risk. Verify selected products at the live variant/cart before reporting them.

## Reproducible verification

Run deterministic unit tests from the repository root:

```sh
uv run --with 'beautifulsoup4>=4.13,<5' --with 'cryptography>=45,<47' --with 'httpx>=0.28,<0.29' \
  python -m unittest discover -s skills/product-search/scripts/tests -p 'test_*.py'
```

The deterministic suite passed 91/91 on 2026-07-31. It covers the core contract, CLI, all storefront adapters, Shopify signer, SerpApi client, and AliExpress client. Aggregation tests use mocked provider responses; neither client produced a credentialed live catalog result.

The final live acceptance used the production helper end to end: signed Shopify discovery/search/cart/multipart quote on ATTITUDE returned Standard $12.99; WooCommerce on ProtoSupplies returned $6.95–$16.95; Magento on SparkFun returned nine rates at $9.32–$58.96; BigCommerce on goBILDA hydrated three pages and returned four rates at $7.86–$210.48; direct-product Squarespace on Marie Burgos returned $161.13 and $562.13. These are dated evidence, not price assertions for future tests.

For a safe live smoke, run the commands separately so the chosen `item_ref` is inspected before cart creation:

```sh
uv run skills/product-search/scripts/platform_api.py detect https://dernord.com
uv run skills/product-search/scripts/platform_api.py search https://dernord.com DER003
uv run skills/product-search/scripts/platform_api.py quote https://dernord.com 'ITEM_REF_FROM_SEARCH'
```

Live network probes are deliberate, not part of unit tests. Corpus inputs must remain bounded, and any raw diagnostic wire evidence belongs in a temporary directory rather than the repository.

The dated long-tail corpus comprised 12 Shopify, 12 WooCommerce, 12 Magento controls/open stores, and 11 BigCommerce stores, plus three each for Squarespace, Wix, Ecwid, and Salesforce Commerce Cloud and the three tracked bot-wall unknowns. The core outcomes were:

| Platform | Product result | Cart/address result | SF shipping result |
| --- | --- | --- | --- |
| Shopify | 12/12 | 12/12 | 8 quote, 4 empty |
| WooCommerce | 12/12 | 12/12 | 7 quote, 5 empty; 1 fallback |
| Magento | 10 open, 2 controls | 10/10 open | 10 quote; 2 not reached |
| BigCommerce | 11/11; GraphQL token 8/11 | 11/11 primary REST | 11 quote, 43 methods |
| Squarespace | 3/3 | 3/3 | 1 quote, 1 not applicable, 1 shipping not required |
| Wix | 3/3 | generic runtime boundary | no generic quote |
| Ecwid | 3/3 | one anonymous checkout; address boundary | pre-address fallback only |
| Salesforce Commerce Cloud | 3 detected | one full standard SFRA flow | one exact-address quote |

Tests should assert schemas and semantics, not live prices: multipart termination and patch paths, exact address field names, minor-unit conversion, empty-versus-zero, fallback markers, pickup/deferred filtering, platform-bound item references, redaction, positive wall evidence, and explicit gated/unsupported outcomes.

## Reference links

- [Shopify carrier rates through `@defer`](https://shopify.dev/changelog/fetching-carrier-calculated-rates-through-defer-directive-in-storefront-graphql-api)
- [Shopify Storefront API rate limits](https://shopify.dev/docs/api/usage/limits#storefront-api-rate-limits)
- [Shopify Web Bot Auth announcement](https://shopify.dev/changelog/bots-and-agents-should-identify-themselves-via-web-bot-auth)
- [Cloudflare Web Bot Auth directory profile](https://developers.cloudflare.com/bots/reference/bot-verification/web-bot-auth/)
- [Google Merchant API products overview](https://developers.google.com/merchant/api/guides/products/overview)
- [SerpApi Google Shopping API](https://serpapi.com/google-shopping-api)
- [DataForSEO Google Shopping overview](https://docs.dataforseo.com/v3/merchant-google-overview/)
- [AliExpress Affiliate Product Query](https://developer.alibaba.com/docs/api.htm?apiId=45803)
- [Alibaba TOP request signing](https://developer.alibaba.com/docs/doc.htm?articleId=101617&docType=1&treeId=1)
