# Storefront Platform APIs

Use these workflows after ordinary search identifies a store and product search or delivered price needs live structured data. Start with plain HTTP. Use browser-swarm only where this guide marks a browser boundary.

## Rules shared by every platform

Follow the homepage redirect and build every endpoint from the resolved storefront origin. Let the adapter own session boundaries: reuse cookies within one stateful cart or quote flow, but keep detection, catalog discovery, and commerce mutations isolated when the platform recipe calls for fresh sessions. Send a current browser User-Agent. Validate response content and shape, not status alone: unrelated HTML can arrive with HTTP 200, and generic 401/403 responses do not prove a platform.

Use this destination for rate estimates:

```text
Jordan Smith
Pacific Prototyping LLC
747 Howard St
San Francisco, CA 94103
United States
+1 415-555-0132
```

Stop after obtaining rates. Never create an account, enter payment details, or place an order.

Classify the result precisely:

- `quoted`: one or more destination delivery methods were returned. A named free-shipping method may cost zero.
- `no_quote`: the destination was accepted but no delivery method was returned. This is never free shipping.
- `fallback`: the store returned only explicitly fallback-labelled rates or values calculated before the destination was applied.
- `gated`: the platform is independently established and its public workflow refuses guest access or requires a visitor/member identity.
- `bot_wall`: a challenge prevented the operation. This is not platform absence.
- `unsupported`: the platform is unknown, or the known platform or selected product has no scripted public workflow for the operation.
- `api_error`: the workflow failed outside a normal quote outcome, such as a transport failure, malformed response, schema change, or structured operational error.

Preserve every shipping option and label its disposition as `delivery`, `pickup`, `paid_later`, `unavailable`, or `fallback`. Only `delivery` options are comparable destination rates. Do not silently promote fallback evidence to `quoted`.

Exclude pickup, freight-paid-later, quote-later, unavailable, and error-bearing options from delivered-price comparisons. Fail loudly on malformed response shapes, contradictory detections, schema drift, and unexpected multipart data.

## Preferred commands

Use the single platform workflow entry point:

```sh
uv run ~/.agents/skills/product-search/scripts/platform_api.py detect https://store.example
uv run ~/.agents/skills/product-search/scripts/platform_api.py products https://store.example 'bearing'
uv run ~/.agents/skills/product-search/scripts/platform_api.py quote https://store.example 'ITEM_REF'
uv run ~/.agents/skills/product-search/scripts/platform_api.py probe https://store.example 'bearing'
uv run ~/.agents/skills/product-search/scripts/platform_api.py corpus stores.json results.jsonl
```

`detect` records exactly one state: `detected`, `unknown`, or `bot_wall`; only `detected` names a platform and API origin. `products` returns opaque `item_ref` values; pass one unchanged to `quote`. `probe` selects the first available returned product and quotes it. Product search supports Shopify, WooCommerce, Magento, BigCommerce, Squarespace, Wix, Ecwid, and Salesforce Commerce Cloud. Generic public quotes support Shopify, WooCommerce, Magento, BigCommerce, and Squarespace; Wix, Ecwid, and Salesforce Commerce Cloud return `unsupported` at the quote boundary.

Every single-store command writes one JSON value to stdout. Quote results carry exactly one `status`: `quoted`, `no_quote`, `fallback`, `gated`, `bot_wall`, `unsupported`, or `api_error`. `shipping_options` preserves every returned option with disposition `delivery`, `pickup`, `paid_later`, `unavailable`, or `fallback`; `delivery_rates` contains only comparable home-delivery options. With valid syntax, a single-store command exits nonzero only when `result.status` is `api_error`; `corpus` exits nonzero if any new row has that status. The workflow never changes platform or invokes a browser silently.

`corpus` reads a JSON array of 1–100 objects containing exactly nonempty `store` and `query` strings:

```json
[
  {"store": "https://store.example", "query": "bearing"}
]
```

It appends one result per line to the output JSONL and resumes by skipping completed `(store, query)` pairs. All quote paths use the fixed 94103 destination and stop before checkout. The remaining sections document exact request schemas, interpretation, and failure diagnosis.

## Shopify

Shopify's tokenless Storefront GraphQL API provides product search, carts, and delivery options. Every Shopify request must pass through `send_signed(client, request)` in `scripts/web_bot_auth.py`. The helper reads the fixed Ed25519 key in place, validates its JWK thumbprint, signs one prepared HTTPS request, and sends it immediately without following redirects:

```python
from scripts.web_bot_auth import send_signed

url = "https://store.example/api/2026-07/graphql.json"
request = client.build_request(
    "POST",
    url,
    headers={"Accept": "application/json", "Content-Type": "application/json"},
    json={"query": query, "variables": variables},
)
response = send_signed(client, request)
```

Resolve the storefront authority before building the request. Never redirect or reuse a signed request, print generated signature headers, or copy the private key.

### Detection and API origin

Send this signed request to the resolved host:

```http
POST /api/2026-07/graphql.json
Content-Type: application/json

{"query":"{ shop { name } }"}
```

HTTP 200 with `data.shop.name` is positive detection. A headless/custom storefront may not proxy `/api`; discover exactly one canonical `*.myshopify.com` host from the already-fetched page source and retry there. ATTITUDE Living exercised this path. A challenge or custom-domain 404 is not a negative Shopify verdict.

### Product search

```graphql
query ProductSearch($query: String!) {
  products(first: 20, query: $query) {
    nodes {
      id
      title
      handle
      vendor
      productType
      featuredImage { url altText }
      variants(first: 100) {
        nodes {
          id
          title
          sku
          barcode
          availableForSale
          price { amount currencyCode }
          compareAtPrice { amount currencyCode }
          weight
          weightUnit
          image { url altText }
        }
      }
    }
  }
}
```

Use Shopify's query grammar for fields such as `title`, `product_type`, `tag`, `vendor`, `variants.price`, and `available_for_sale`. `availableForSale` is boolean stock only; tokenless callers do not receive inventory depth.

### Cart creation

```graphql
mutation CartCreate($input: CartInput!) {
  cartCreate(input: $input) {
    cart { id }
    userErrors { field message }
  }
}
```

```json
{
  "input": {
    "lines": [{"merchandiseId": "gid://shopify/ProductVariant/…", "quantity": 1}],
    "buyerIdentity": {
      "countryCode": "US",
      "deliveryAddressPreferences": [{
        "deliveryAddress": {
          "firstName": "Jordan",
          "lastName": "Smith",
          "company": "Pacific Prototyping LLC",
          "address1": "747 Howard St",
          "city": "San Francisco",
          "province": "CA",
          "country": "US",
          "zip": "94103",
          "phone": "+14155550132"
        }
      }]
    }
  }
}
```

`MailingAddressInput` uses `country` and `province`. `countryCode` and `provinceCode` are invalid inside that object; `buyerIdentity.countryCode` is a separate field.

### Delivery rates and multipart parsing

```graphql
query CartRates($id: ID!) {
  cart(id: $id) {
    id
    ... @defer {
      deliveryGroups(first: 10, withCarrierRates: true) {
        nodes {
          groupType
          deliveryOptions {
            handle
            title
            code
            description
            deliveryMethodType
            estimatedCost { amount currencyCode }
          }
        }
      }
    }
  }
}
```

Send `Accept: multipart/mixed; deferSpec=20220824, application/json`. The inline fragment and `@defer` are mandatory when `withCarrierRates: true` is used. Live responses normally put the cart shell in the first MIME JSON part and `deliveryGroups` in a later `incremental` part. Parse the boundary with a MIME parser, JSON-decode every `application/json` part, merge each patch at its typed `path`, combine GraphQL errors, and require terminal `hasNext: false`. A JSON-only parser silently loses the rates.

Treat missing delivery groups, empty groups, and GraphQL errors as distinct no-quote failures. Storefront cart totals are pre-tax in this workflow; do not claim a tax-inclusive delivered total.

### Web Bot Auth status

The fixed identity is:

```text
Signature-Agent: "https://lancelotlabs.org"
kid: PtFPEn59EWaohh4V82GazSOYlIBm3LqPOhoLUu--1So
```

The [live public key directory](https://lancelotlabs.org/.well-known/http-message-signatures-directory) was deployed and independently verified on 2026-07-31. Its HTTP 200 response carried the expected public JWK, `Signature`, `Signature-Input`, `Cache-Control: no-store`, the directory signature tag, and a ten-second lifetime. Independent Ed25519 verification succeeded using only the returned public JWK, and its RFC 7638 thumbprint matched the configured `kid`.

Shopify's [Storefront API limits](https://shopify.dev/docs/api/usage/limits#storefront-api-rate-limits) and [May 7, 2026 changelog](https://shopify.dev/changelog/bots-and-agents-should-identify-themselves-via-web-bot-auth) document the policy: unsigned anonymous bots receive the strictest limits and correctly signed Web Bot Auth traffic qualifies for higher limits. They do not document a validator endpoint, recognition header, entitlement response, or tier API for a particular identity; the [Storefront API reference](https://shopify.dev/docs/api/storefront/2026-04) exposes no such signal.

The 2026-07-31 identity experiment sent exactly 100 identical product-only requests in two reversed-order rounds: 50 signed and 50 unsigned. Every request returned HTTP 200 with valid, stable product data. Neither mode produced throttling, `Retry-After`, or a rate-, limit-, throttle-, retry-, or tier-named response header. Because neither mode crossed an observable limit, recognition of this identity is strictly inconclusive; the experiment neither empirically confirms nor contradicts Shopify's documented higher-limit policy.

A separate bounded differential sent exactly three sequential product queries: one unsigned, one validly signed through `send_signed`, and one with the signature deliberately corrupted. All three returned identical valid HTTP 200 product data, body digest, response size, relevant response-header classification, and `server-timing: anonymous`. This establishes that the request exposed no client-visible signature-validation or identity-recognition signal. It does not show that Shopify accepted the corrupted signature internally; an invalid or unrecognized signature may be handled as anonymous traffic.

One signed request to [Cloudflare's crawl-test endpoint](https://crawltest.com/cdn-cgi/web-bot-auth) returned HTTP 401. That endpoint tests Cloudflare recognition under [Cloudflare's Web Bot Auth profile](https://developers.cloudflare.com/bots/reference/bot-verification/web-bot-auth/), not Shopify recognition. Shopify explicitly states that Cloudflare enrollment is unnecessary, so this result is not Shopify evidence.

### Corpus result, 2026-07-31

Twelve of twelve stores completed detection, structured product data, cart creation, and a rate request. Eight returned rates and four returned empty delivery-option lists. All twelve rate responses exercised multipart parsing. The corpus included two tracked vendors, twelve custom-domain storefronts, and three Hydrogen/Oxygen storefronts within that set. Observed results ranged from explicit free shipping to $448.41 LTL freight; the four empty lists carried no explanatory GraphQL error.

| Store | Selected product / SKU | API path | SF outcome |
|---|---|---|---|
| DERNORD | Tri-clamp hose-barb adapter / `DER003` | custom-domain GraphQL | FeDex $55 |
| Mettle Air | 316L 8-port manifold / `SM20-250-8` | redirect to `mettleairstore.com` GraphQL | four rates, $27.78–$56.06 |
| Garage Cabinets Online | Gladiator scoop hook / `GAWUXXSCRH` | custom-domain GraphQL | Standard $12.99 |
| Air Compressor Services | Champion cooler / `EFC89754889` | custom-domain GraphQL | LTL $448.41 / $535.84 |
| VHS Hydraulics | Dana Brevini valve / `BRVAD3RI211Z2003` | custom-domain GraphQL | no quote: empty options |
| Parker Hydraulics & Pneumatics | IMO circuit breaker / `I1B10C1002` | custom-domain GraphQL | no quote: empty options |
| Carex | AccuRelief supply kit / `ACRL-0021` | custom-domain GraphQL | Standard $9.99 |
| SAS Locksmiths | Dorma slide arm / `DO93GN` | custom-domain GraphQL | no quote: empty options |
| Sika Marketplace | Soothing Hydration Cream / `415035` | custom-domain GraphQL | no quote: empty options |
| Manors Golf | Tech Cap / `A-24SS-FRONTIER-CAP-DOLV` | Hydrogen custom-domain proxy | International Economy £7.43 |
| Nour Hammour | Hatti / `HattiBlackL` | Hydrogen custom-domain proxy | explicit FREE €0 |
| ATTITUDE Living | Pet Wipes / `81160` | Hydrogen; `.myshopify.com` API fallback | Standard $12.99 |

## WooCommerce

WooCommerce's Store API exposes a guest cart, public catalog, customer-address update, taxes, and rates.

### Detection and token

```sh
curl -i 'https://STORE/wp-json/wc/store/v1/cart'
```

Require HTTP 200 and a JSON object containing `totals`; capture the response's `Cart-Token` header without logging it. A WordPress marker alone is not sufficient. Probe the Store API even when the homepage is challenged: API endpoints can remain open behind a challenged landing page.

### Search, cart, and quote

```sh
curl --get 'https://STORE/wp-json/wc/store/v1/products' \
  --data-urlencode 'search=bearing' \
  --data-urlencode 'per_page=100'

curl -X POST 'https://STORE/wp-json/wc/store/v1/cart/add-item' \
  -H "Cart-Token: $CART_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"id":123,"quantity":1}'

curl -X POST 'https://STORE/wp-json/wc/store/v1/cart/update-customer' \
  -H "Cart-Token: $CART_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"shipping_address":{"first_name":"Jordan","last_name":"Smith","company":"Pacific Prototyping LLC","address_1":"747 Howard St","address_2":"","city":"San Francisco","state":"CA","postcode":"94103","country":"US","phone":"4155550132"}}'
```

Choose a `simple` or concrete `variation` product whose response says both `is_purchasable` and `is_in_stock`. Use `add_to_cart.minimum` for quantity. Rates are nested in the updated cart's shipping packages; preserve the full package and rate metadata.

All product prices, cart totals, rate prices, and rate taxes are integer strings scaled by `currency_minor_unit`. Do not assume two decimal places or convert through binary float. A `rate_id` ending `_fallback` is a merchant fallback, not a live carrier result. Preserve `selected`; the selected rate need not be the cheapest. Taxes can be nonzero even when the rate list is empty.

Delete the temporary item when possible:

```sh
curl -X DELETE "https://STORE/wp-json/wc/store/v1/cart/items/$ITEM_KEY" \
  -H "Cart-Token: $CART_TOKEN"
```

Record cleanup status separately. A store may allow cart GET/POST while filtering DELETE.

### Corpus result, 2026-07-31

All twelve stores were detected, returned public product data, accepted a purchasable item, and accepted the SF address. Seven returned rates; five returned empty lists. Tech7000 returned one `_fallback` flat rate. Two carts returned nonzero tax. F-O-A Shocks blocked only the cleanup DELETE with an HTML 403; the quote workflow itself had succeeded through the address stage.

A later 2026-07-31 integrated Tech7000 run still passed cart detection and collection product search, but its exact `/products/240` validation request hit an HTML WAF 403 before cart creation. The CLI reported `gated` at `selected_product`; this is an endpoint-specific wall, not evidence that the guest cart API closed, and it does not erase the earlier dated fallback quote.

| Store | Selected product | Cart/address | SF outcome |
|---|---|---|---|
| Actisense | Mid Bulk Cable Reel | accepted | no quote: empty rates |
| GPS Pilot Supplies | RG142 Coaxial Cable | accepted | no quote: empty rates |
| Pureseal Services | GutterRepair Pro | accepted; £30 cart tax | no quote: empty rates |
| F-O-A Shocks | Shock Seal Insertion Tool | accepted; $2.93 cart tax; cleanup DELETE 403 | no quote: empty rates |
| Resin Pro UK | Wooden Resin Coaster Starter Kit | accepted | £24.85 Standard / £29.85 selected Priority |
| Rope Source | Polyhemp Rope | accepted | UPS or FedEx £80 |
| ProtoSupplies | Soil Moisture Sensor Module | accepted | three rates, $6.95–$16.95 |
| Maker Store USA | KFL10 Pillow Block Bearing | accepted | seven rates, $6.01–$35.35 |
| Rotary Solutions | Pro6MR | accepted | explicit Free shipping $0 |
| Tech7000 | 25HA3 SSTK Wrenches | accepted | `_fallback` UPS Flat Rate $19.95 |
| NRG Wave | PHYTO PRO MAXX | accepted | no quote: empty rates |
| MYOLYN | MyoCycle V1 Stimulation Cable | accepted | explicit USPS Flat Rate Envelope FREE $0 |

## Magento / Adobe Commerce

Magento often leaves guest carts open while gating REST catalog access. Treat catalog and cart access as separate capabilities.

### Detection and catalog

Strong page evidence includes versioned `/static/.../frontend/` paths, `Magento_*` modules, `x-magento-init`, `mage-cache-*`, `private_content_version`, and `X-Magento-*` headers.

```sh
curl -X POST 'https://STORE/rest/V1/guest-carts' \
  -H 'Content-Type: application/json' \
  -d '{}'
```

A 2xx response containing a bare quoted 20–80 character token proves `Magento (guest API open)`. A Magento-shaped error plus page evidence proves gated/disabled access. Generic HTML 401/403/404/405 without independent Magento evidence proves neither.

Do not use REST catalog search as the default. `GET /rest/V1/products` returned `Magento_Catalog::products` authorization errors even on every tested open-cart store in the first corpus. Try public Magento GraphQL instead:

```graphql
query ProductProbe($search: String!) {
  products(search: $search, pageSize: 10) {
    total_count
    items {
      __typename
      name
      sku
      stock_status
      url_key
    }
  }
}
```

Post it as JSON to `/graphql`. It returned usable results on seven of ten open stores in the expanded corpus. Query configurable `variants` only after narrowing to one parent; broad variant queries can be huge or hit broken resolvers. If GraphQL is absent or broken, use the product sitemap, storefront search/category page, and product JSON-LD or Magento data layer. Add a concrete in-stock simple SKU, not a configurable or bundle parent.

### Cart and quote

```sh
cart_id=$(curl -sS -X POST 'https://STORE/rest/V1/guest-carts' \
  -H 'Content-Type: application/json' -d '{}' | jq -r .)

curl -X POST "https://STORE/rest/V1/guest-carts/$cart_id/items" \
  -H 'Content-Type: application/json' \
  -d "{\"cartItem\":{\"sku\":\"SIMPLE-SKU\",\"qty\":1,\"quote_id\":\"$cart_id\"}}"

curl -X POST "https://STORE/rest/V1/guest-carts/$cart_id/estimate-shipping-methods" \
  -H 'Content-Type: application/json' \
  -d '{"address":{"firstname":"Jordan","lastname":"Smith","company":"Pacific Prototyping LLC","street":["747 Howard St"],"city":"San Francisco","region":"California","region_code":"CA","region_id":12,"postcode":"94103","country_id":"US","telephone":"4155550132"}}'
```

Require the add response to confirm the expected SKU and name. Preserve `carrier_code`, `method_code`, `amount`, `price_excl_tax`, `price_incl_tax`, `available`, and `error_message`. `shq*` codes are ShipperHQ; `amstrates*` are merchant/Amasty rules.

An empty array is no quote. A zero-dollar `instore` or pickup method is not delivery. An explicit `freeshipping` method can be free. An account-priced zero item combined with a generic freight method is not an actionable delivered price. Cross-border pickup-network methods can also survive an implausible address; choose an actual destination delivery method.

HTTP 400 on add normally means the SKU is invalid, unavailable, configurable, or a bundle parent. Return to product discovery; do not patch around it with guessed options.

### Corpus result, 2026-07-31

Ten of twelve mixed stores exposed open guest carts; all ten accepted a real SKU and returned at least one method. Bulk Reef Supply was independently Magento-positive but its guest endpoint returned a merchant-branded CDN 403. Aheadworks was Cloudflare-challenged and its guest endpoint returned plain `401 Not authorized`; without the independent footprint, the HTTP result alone would remain unknown. The corpus included explicit free shipping, pickup mixed with delivery, account-priced zero/freight ambiguity, ShipperHQ and Amasty methods, and no empty arrays.

| Store | SKU source and selected SKU | Cart stage | SF outcome |
|---|---|---|---|
| SparkFun | public GraphQL / `CAB-11604` | added | USPS Ground Advantage $9.69 lowest of nine |
| DecksDirect | public GraphQL / `BDA565A` | added | FedEx Ground $9.99 lowest of three |
| Barr Display | public GraphQL / `68Mallet` | added | FedEx Ground $17.97; $0 pickup excluded |
| Scout Shop | public GraphQL / `10701` | added | USPS Ground $3.95 lowest of three |
| Blanks.ca | public GraphQL / `705A.B005.14` | added | FedEx Ground C$29.54 lowest of five |
| Signet Australia | public GraphQL / `SIG_10402` | added, account-priced A$0 item | generic A$0 freight method; non-actionable |
| ATX Fitness USA | public GraphQL / `ATX-BPR-790` | added | explicit Free Shipping $0 |
| The CPAP Shop | product page / `635871164` | added | merchant Standard $8.99 lowest of seven |
| Dillon Precision | product page / `12472` | added | Standard Ground $11.95; special-handling inclusion unproven |
| TileBar | product page / `SMP-TLFXINBLJD16X16SAMPLE` | added | Economy Shipping $1 |
| Bulk Reef Supply | public Magento product page | not attempted | guest-cart endpoint returned merchant CDN 403 |
| Aheadworks | independent Magento footprint | not attempted | homepage Cloudflare 403; guest endpoint plain 401 |

An earlier validated run also added Killer Ink Tattoo SKU `ALLEI60-BLAK`. The page offer was £12.59 while the cart item was £10.49 after VAT removal; UPS Express Saver £29.97 was the usable home-delivery method and the DPD pickup-network method was excluded.

Glacier Tanks is a browser-wall hybrid: direct HTTP is Cloudflare-challenged, but fingerprint Chromium establishes the session; same-origin Magento guest-cart calls then work. Its REST catalog is gated, while its page's Algolia integration supplies product discovery.

## BigCommerce Stencil

BigCommerce has a generic tokenless Storefront REST cart and CSRF-protected consignment quote. It does not require Storefront GraphQL, a merchant credential, or a browser.

### Detection and product discovery

Strong evidence includes `cdn11.bigcommerce.com/s-<store-hash>`, Stencil assets or the Stencil platform meta tag, and `x-bc-store-id` on Storefront responses.

Detection, product discovery, and quoting use deliberately isolated anonymous sessions. Product discovery parses the complete search response rather than an evidence-sized prefix; quoting starts another fresh session so stale detection or catalog cookies cannot poison cart creation.

Public product paths are:

- `/xmlsitemap.php` and `/xmlsitemap.php?type=products&page=1`
- `/search.php?search_query=<term>`
- product-page hidden `product_id` fields and `BCData.product_attributes`, including SKU, price, stock, weight, and required option IDs/values

Search and product pages can expose candidate option vectors. Resolve a nonempty vector through the public product-selection endpoint:

```http
POST /remote/v1/product-attributes/<product-id>
Content-Type: application/x-www-form-urlencoded

action=add&product_id=<product-id>&attribute[<option-id>]=<option-value>
```

Accept the vector only when the response echoes the exact `selected_attributes` and returns a concrete SKU. Otherwise mark the selection unresolved; do not guess a required option. The opaque `item_ref` preserves the public option definitions, concrete vector, and authoritative SKU for the quote.

A conditional structured catalog path is Storefront GraphQL. Scan anonymous source for a short-lived, origin-constrained `storefrontApiToken`, then send it as a bearer token to `POST /graphql`. Tokenless GraphQL returned 401 on every tested store; six of eleven page-source tokens returned structured products. Never persist the raw token.

### Tokenless guest cart

Start with a fresh anonymous quote session. The cart creation and consignment requests share only this new session.

```http
POST /api/storefront/carts
Content-Type: application/json

{"lineItems":[{"quantity":1,"productId":1957}]}
```

For public required radio/select options:

```json
{
  "lineItems": [{
    "quantity": 1,
    "productId": 4169,
    "optionSelections": [{"optionId": 6074, "optionValue": 4070}]
  }]
}
```

Require HTTP 200 JSON, a cart ID, one physical item, and response cookies `SHOP_SESSION_TOKEN` and `SF-CSRF-TOKEN`. Read the physical item ID, variant ID, price, and shipping-required flag from the cart, and require its SKU to equal the concrete SKU carried by the `item_ref`; a mismatch is `api_error`. Do not invent a value for a required free-text customization.

### Consignment and rates

```http
POST /api/storefront/checkouts/<cart-id>/consignments?include=consignments.availableShippingOptions
Cookie: SHOP_SESSION_TOKEN=<cart response value>
Content-Type: application/json
X-SF-CSRF-TOKEN: <cart response value>

[{"address":{"firstName":"Jordan","lastName":"Smith","company":"Pacific Prototyping LLC","address1":"747 Howard St","address2":"","city":"San Francisco","stateOrProvince":"California","stateOrProvinceCode":"CA","countryCode":"US","postalCode":"94103","phone":"4155550132","customFields":[],"shouldSaveAddress":false},"lineItems":[{"itemId":"<physical-item-id>","quantity":1}]}]
```

The body must be an array. Rates are at `consignments[].availableShippingOptions[]`; preserve `description`, `cost`, and `costAfterDiscount`.

The minimum tested request needs only the `SHOP_SESSION_TOKEN` cookie, `Content-Type`, and `X-SF-CSRF-TOKEN`. Omitting the CSRF header returned 403 HTML `Forbidden`; using the cart ID without its session cookie returned 401 JSON `Checkout not found`. These are CSRF/session failures, not an authentication boundary.

`/remote/v1/product-attributes/<product-id>` resolves a product selection only. It is unrelated to the legacy `/remote/v1/shipping-quote` estimator. The workflow never calls that shipping estimator or mutates `/cart.php`; every quote uses the Storefront cart and checkout-consignment APIs above.

### Corpus result, 2026-07-31

All eleven stores completed detection, product data, anonymous cart creation, and the SF consignment quote over plain HTTP. The responses contained 43 nonempty methods. GoBilda and ServoCity were included. Valin's custom theme also completed the flow; its nine rates were real, but its anonymous product price was $0/quote-priced, so delivered product price remained incomplete. SPW returned explicit free shipping. Fabric Warehouse returned a `$0 PAID LATER` placeholder alongside usable paid methods.

| Store | Selected product / SKU | Product path | SF outcome |
|---|---|---|---|
| ServoCity | Washer six-pack / `632145` | sitemap/search/`BCData` | four rates, $8.36–$129.22 |
| Hi-Line | O-ring / `2254611` | sitemap/search/`BCData` | Flat Rate $9.95; cart price public despite login-pricing theme |
| Hydraulic Hose To Go | Fitting / `BW230826DLF` | sitemap/search/`BCData` | Flat Rate $17.99 |
| GoBilda | Aluminum tube / `4100-1214-0200` | sitemap/search/`BCData` | four rates, $7.86–$210.48 |
| International Air Tool | Sander / `59014` | page-source GraphQL token + HTML | two ground rates, $23.50–$36.22 |
| SPW Industrial | 250 ft cord / `BZ01177825` | sitemap/search/`BCData` | explicit Free Shipping $0 plus FedEx |
| Fabric Warehouse | Fabric swatch / `PHXUPH-1320-02` | page-source GraphQL token + public option | paid delivery $3.70–$17; `$0 PAID LATER` excluded |
| Buckleguy | Swivel snap / `521-0K-BOCR2-LL` | page-source GraphQL token + public option | six rates, $8.99–$50.80 |
| DeBrovys | 273 lb rack / `40-320390` | page-source GraphQL token + HTML | freight $3,460.48 / $3,685.48 with liftgate |
| TackleDirect | Lure / `SEB-0242-3` | page-source GraphQL token + HTML | four rates, $4.99–$161.01 |
| Valin | Parker valve / `4A-B6XS2-V-SS-61ACX-2` | custom theme + page-source GraphQL token | nine rates, $33.91–$142.37; product remained quote-priced $0 |

## Squarespace

Squarespace exposes a stable anonymous product/cart/address workflow.

### Detection, product, and cart

Prefer `Server: Squarespace`; `Static.SQUARESPACE_CONTEXT` and `static1.squarespace.com` are secondary evidence. Start product discovery from a fresh canonical-origin session. Collect the finite links inside the homepage's Squarespace navigation, normalize each same-origin candidate to scheme, host, and path, discard query strings and fragments, and scan every deduplicated candidate. There is no universal collection slug.

```sh
curl -c cookies.txt 'https://STORE/COLLECTION?format=json'
```

Require `website.id` and product `items[]`, deduplicate variants by `(itemId, sku)`, then choose an exact variant. The product result preserves its canonical collection URL.

Start quoting with another fresh session at that canonical collection URL. Read the new public `crumb` cookie and keep this quote session through the cart add and address update:

```http
POST /api/commerce/shopping-cart/entries
Content-Type: application/json
X-CSRF-Token: <crumb cookie>
Add-To-Cart-Id: <fresh unique value>

{"itemId":"…","sku":"…","quantity":1,"additionalFields":null}
```

Require `shoppingCart.cartToken`. HTTP 200 with `error` and `crumbFail: true` is failure, not a cart.

### Address and quote

```http
PUT /api/3/commerce/cart/<cartToken>/shipping/location
Content-Type: application/json
X-CSRF-Token: <crumb cookie>

{"line1":"747 Howard St","line2":"Pacific Prototyping LLC","city":"San Francisco","region":"CA","postalCode":"94103","country":"US"}
```

Read `shippingOptionsStatus` and `fulfillmentOptions`. `POSTAL_CODE_NOT_APPLICABLE` is a no-quote result; `SHIPPING_NOT_REQUIRED` means the chosen item needs no shipment, not free parcel shipping.

### Corpus result, 2026-07-31

All three stores completed product and cart operations. The exact-product 94103 reruns returned Standard $161.13 and Oversized/Heavy $562.13 for a Marie Burgos Collection chair, `SHIPPING_NOT_REQUIRED` for a Frankly Good Coffee subscription, and `POSTAL_CODE_NOT_APPLICABLE` for an Archive07 shirt.

## Wix

Wix provides stable public product search after its anonymous visitor bootstrap, but no generic arbitrary-store cart contract was validated.

### Detection and product search

Evidence includes `Server: Pepyaka`, `x-wix-request-id`, Wix static assets, and the essential viewer model. Extract the JSON string named `accessTokensUrl` and JSON-decode it so escaped slashes are handled. Require an HTTPS, same-origin URL whose exact path is `/_api/v1/access-tokens` and which has no query or fragment. Fetch it in the same cookie jar and select the e-commerce app token under app ID `1380b703-ce81-ff05-f115-39571d94dfcd`.

```http
POST /_api/catalog-reader-server/api/v1/products/query
Authorization: <page-issued e-commerce app token>
Content-Type: application/json

{"query":{"filter":"{\"name\":{\"$contains\":\"wheel\"}}","paging":{"limit":10,"offset":0}},"includeVariants":true}
```

The token and response are storefront-scoped; do not persist or reuse them across stores.

### Cart boundary and corpus result, 2026-07-31

The v2 current-cart endpoint accepted only the expected snake-case envelope, then rejected the representative Wix Stores catalog reference with `ITEM_NOT_FOUND_IN_CATALOG`. The older endpoint returned HTTP 200 with an empty cart. Product options and catalog-reference resolution are mediated by storefront SDK logic.

Treat cart, address, and shipping as a browser-swarm or site-specific SDK case. Do not replay renderer internals or treat bootstrap values as reusable merchant credentials. All three stores were detected and exposed public product data; none produced a generic destination quote.

## Ecwid

Ecwid provides stable public product search and anonymous checkout creation, but destination address mutation remains a storefront-runtime boundary.

### Detection and products

Detect `app.ecwid.com/script.js?<storeId>`. The script supplies the store's `apiBaseUrl`.

```http
POST <apiBaseUrl>/<storeId>/initial-data
Content-Type: application/json

{"lang":"en"}
```

Read the public `ecwid-storefront` token from the opened store profile, then search:

```http
GET https://app.ecwid.com/api/v3/<storeId>/products?token=<publicToken>&keyword=<query>&limit=10
```

The owner REST API is credentialed; only the page-issued public token makes this a storefront product path. Take currency from the store profile. Ignore disabled search records, which may contain only partial identity data; enabled records must contain an integer ID, name, and boolean stock state before they become products.

### Checkout and quote boundary

The store-specific storefront API accepts an anonymous checkout:

```http
POST <apiBaseUrl>/<storeId>/checkout/create
Content-Type: application/json

{"lang":"en","checkout":{"cartItems":[{"identifier":{"productId":2913395,"selectedOptions":{},"recurringSubscription":"ONE_TIME_PURCHASE"},"quantity":1,"isPreorder":false}]},"shouldOverwriteEmailWithCustomerEmail":false}
```

Supply required options exactly as the product describes them. The response returns an anonymous checkout session. A shipping amount present at creation time is pre-address/default/fallback only. The tested internal address-update request returned HTTP 400 and its state/update contract did not generalize.

Use the supported storefront runtime in browser-swarm for destination rates, set the customer's address through Ecwid's cart interface, then read the recalculated cart. Do not document or replay the internal `/checkout/update` call as a public API.

### Corpus result, 2026-07-31

All three stores were detected and exposed public V3 product search. Northbound Coffee created an anonymous checkout and returned a $5 fallback before address; the SF address update was rejected. Cakesafe and Wylie Beckert remained product-only after that boundary was established.

## Salesforce Commerce Cloud / Demandware

SFCC has stable detection and public storefront search. Standard SFRA forms can support a complete guest-address quote, but cart controllers and shipping behavior remain merchant-specific. There is no universal anonymous OCAPI/SCAPI contract for arbitrary stores.

### Detection and search

Strong markers include `/on/demandware.static/Sites-<site>-Site/`, `/on/demandware.store/`, `dwvar_` parameters, `x-dw-request-base-id`, `CQuotient.siteId`, Demandware cookies, and `dw/image/v2/` media.

Parse the homepage and require exactly one same-origin search form whose fields include `q`. Send the query to that form's action; never synthesize `Search-Show` without page evidence. Associate each concrete `data-pid` with the title and URL inside its enclosing product tile, then deduplicate by product ID.

### Standard SFRA guest quote and corpus result, 2026-07-31

When the live storefront exposes the standard forms:

1. Post a concrete orderable variant and quantity to its `Cart-AddProduct` action.
2. GET its `Checkout-Begin` action in the same cookie jar.
3. Parse the guest-customer action, shipping action, CSRF token, `originalShipmentUUID`, `shipmentUUID`, and offered shipping method IDs from the returned page.
4. POST a syntactically valid guest email with the exact page field names and CSRF token. Do not create an account.
5. POST the page's shipping form with the exact address field names, shipment UUIDs, selected method, and CSRF token. If the form has no company field, put `Pacific Prototyping LLC` in address line 2.
6. Require the JSON response to echo the submitted SF address, then read `order.shipping[].applicableShippingMethods` and `order.totals`.

The Dunlop request used this form shape; derive the actions, token, UUIDs, and method ID from the live checkout page:

```text
originalShipmentUUID=<page value>
shipmentUUID=<page value>
dwfrm_shipping_shippingAddress_addressFields_firstName=Jordan
dwfrm_shipping_shippingAddress_addressFields_lastName=Smith
dwfrm_shipping_shippingAddress_addressFields_companyName=Pacific Prototyping LLC  # only when the form exposes it
dwfrm_shipping_shippingAddress_addressFields_address1=747 Howard St
dwfrm_shipping_shippingAddress_addressFields_address2=Pacific Prototyping LLC
dwfrm_shipping_shippingAddress_addressFields_country=US
dwfrm_shipping_shippingAddress_addressFields_states_stateCode=CA
dwfrm_shipping_shippingAddress_addressFields_city=San Francisco
dwfrm_shipping_shippingAddress_addressFields_postalCode=94103
dwfrm_shipping_shippingAddress_addressFields_phone=4155550132
dwfrm_shipping_shippingAddress_shippingMethodID=<page value>
csrf_token=<page value>
```

Dunlop completed this flow for variant `12133488`: Ground $6.99, 2 Day $14.99, $3.19 tax, and $40.17 total with Ground. Alcott returned HTTP 500 for its master PID. HUGO BOSS redirected to storefront HTML rather than returning cart JSON.

Treat customized sites as a browser-swarm/controller case unless their live forms establish and validate a complete contract. Preserve CSRF and exact field names from the page, never invent a variant, and label any rate returned before the address as fallback.

## Custom storefront: Bolt Depot

Bolt Depot is a custom storefront behind a Cloudflare managed challenge. Plain HTTP returns 403; a browser-swarm fingerprint-Chromium session can load the site. Its first-party routes are bespoke Razor-style handlers rather than a commodity platform API:

```text
POST /Quick-Add?handler=ItemDescription
productId=<numeric product ID>

POST /Quick-Add?handler=AddItemsToCart
QuickAddResponses[0].ProductId=<numeric product ID>
QuickAddResponses[0].Quantity=1
__RequestVerificationToken=<page token>

POST /ShoppingCart?handler=EstimateShipping
ShipToCountry=US
ShipToZipcode=94103
__RequestVerificationToken=<page token>
```

Keep the Cloudflare clearance, shopper session, and page antiforgery token inside one isolated browser context. The estimator accepts country and ZIP only and returns an HTML fragment. On 2026-07-31 product `9019` produced six delivery methods from Economy $8.40 to UPS Saturday Next Day $86.91; exclude the $0 Customer Pickup row. There is no stable public API to replay outside the browser session.

## OpenCart

OpenCart is detectable through `/catalog/view/` assets and `index.php?route=checkout/cart/add`. Product and option contracts are page-specific.

StepperOnline's fingerprint-Chromium session exposed product ID `110`, SKU `17HS19-2004S1`, the anonymous cart route, and required warehouse option `option[13184]=23933`. Posting without the option returned structured validation; posting the complete selection returned a Cloudflare managed challenge and left the cart empty. Classify this as an endpoint-specific cart-write wall and use browser-swarm only if an interactive challenge can be completed. Do not repeat writes or claim a quote.

## Product and price aggregation

Aggregation APIs provide leads, not primary-source verification or merchant cart economics.

### Google Merchant API

Do not use it for sourcing. It manages an authenticated merchant's own Merchant Center catalog and cannot search the public Google Shopping index.

### SerpApi Google Shopping

This is the best first evaluation for occasional buyer-side searches: one synchronous request can return product, seller, extracted price, rating, delivery text, and product-detail tokens.

```sh
curl --get 'https://serpapi.com/search.json' \
  --data-urlencode 'engine=google_shopping' \
  --data-urlencode 'q=Knipex 87 01 250' \
  --data-urlencode 'location=San Francisco, California, United States' \
  --data-urlencode 'gl=us' \
  --data-urlencode 'hl=en' \
  --data-urlencode "api_key=$SERPAPI_API_KEY"
```

No key was configured on 2026-07-31, so the endpoint was only confirmed credential-gated. Do not make it a routine dependency until a real-key acceptance corpus checks direct seller links and primary-source price agreement.

Pricing observed on 2026-07-31: free 250 searches/month and 50/hour throughput; Starter $25 for 1,000/month; Developer $75 for 5,000/month; Production $150 for 15,000/month. An exact cached result retained for one hour is free, while product-detail follow-ups are separate searches. Recheck [SerpApi's Google Shopping API](https://serpapi.com/google-shopping-api) and [current pricing](https://serpapi.com/pricing) before relying on these limits.

### DataForSEO

Use only for bulk/scheduled work after explicit credential and spend approval. Its Google Shopping Products task is asynchronous; a Sellers task supplies comparable offers and delivery data. It requires Basic-auth credentials even in the sandbox and a minimum top-up. No credential was configured on 2026-07-31.

Pricing observed on 2026-07-31 was $0.001/item standard or $0.002/item priority, with $1 trial credit and a $50 minimum top-up. Tasks allow high batch throughput but require submit-and-poll orchestration. See the [Google Shopping overview](https://docs.dataforseo.com/v3/merchant-google-overview/) and [current pricing](https://dataforseo.com/google-shopping-api).

### Gemini Google Search grounding

Treat it as another search agent, not a product/price feed. It produces synthesized text and citations rather than stable Shopping offer records. The credential configured on 2026-07-31 was rejected by the Gemini Developer API, so it is not a current fallback.

### AliExpress Affiliate Product API

Use the official Affiliate Product Query API for buyer-side discovery, not seller catalog-management APIs. It covers affiliate-promotable products rather than the entire catalog and does not provide variant stock or a destination cart quote.

The included client implements the required sorted-parameter uppercase HMAC-MD5 signature and fails loudly on provider errors:

```sh
export ALIEXPRESS_APP_KEY='…'
export ALIEXPRESS_APP_SECRET='…'
uv run ~/.agents/skills/product-search/scripts/aliexpress_affiliate.py 'Knipex Cobra pliers' --sort SALE_PRICE_ASC
```

It defaults to the working overseas TOP gateway, US ship-to, USD, and English. No Affiliate credentials were configured on 2026-07-31; transport, encoding, response parsing, and invalid-key failure were tested, but a real product response and signature acceptance remain unproven. Adopt the client only after an approved Affiliate app returns products and selected results survive live variant/cart verification.

The API searches affiliate-promotable products and supports category/keyword, price bounds, sale-price or recent-volume sorting, target language/currency, ship-to country, and delivery-day filters. Method references label it free, but quotas are app- and method-specific in the app console. Older Affiliate onboarding pages are deprecated even though the live [Product Query method](https://developer.alibaba.com/docs/api.htm?apiId=45803) and [TOP signing protocol](https://developer.alibaba.com/docs/doc.htm?articleId=101617&docType=1&treeId=1) remain available; treat new-app approval as a lifecycle risk.

## 2026-07-31 corpus summary

| Platform | Stores | Product path | Cart/address outcome | SF shipping outcome |
|---|---:|---|---|---|
| Shopify | 12 | 12/12 | 12/12 cart + address | 8 quoted, 4 empty |
| WooCommerce | 12 | 12/12 | 12/12 cart + address | 7 quoted, 5 empty; 1 fallback |
| Magento | 12 | 10 open; 2 wall/gate controls | 10/10 open carts added | 10 quoted; 2 not reached |
| BigCommerce | 11 | 11/11 | 11/11 tokenless carts + consignments | 11 quoted, 43 methods |
| Squarespace | 3 | 3/3 | 3/3 | 1 quoted, 1 not applicable, 1 shipping not required |
| Wix | 3 | 3/3 | generic cart boundary | browser/SDK case |
| Ecwid | 3 | 3/3 | 1 checkout; address update boundary | 1 pre-address fallback, no SF quote |
| Salesforce Commerce Cloud | 3 | 3/3 | 1 full SFRA guest flow, 1 server error, 1 redirect | 1 SF quote, 2 not reached |

### Extra-platform store findings

| Platform / store | Product evidence | Cart stage | Shipping result |
|---|---|---|---|
| Squarespace / Frankly Good Coffee | Flagship Subscription / `SQ6853991` | added | `SHIPPING_NOT_REQUIRED`; not a parcel quote |
| Squarespace / Archive07 | Deviation shirt / `SQ0817768` | added | `POSTAL_CODE_NOT_APPLICABLE` |
| Squarespace / Marie Burgos Collection | KITSUI Lounge Chair / `SQ3115437` | added | SF Standard $161.13 / Oversized or Heavy $562.13 |
| Wix / Izzy Wheels | Jurassic World Dino Parade, €169, in stock | generic v2 catalog reference rejected | browser/site-SDK boundary |
| Wix / Bestie Hugs | Galaxy Purple page data | not attempted after boundary | browser/site-SDK boundary |
| Wix / Holzbuchstaben | public product page data | not attempted after boundary | browser/site-SDK boundary |
| Ecwid / Northbound Coffee | Organic Spoonbender / `spb12` | anonymous checkout created | $5 pre-address fallback; SF address update HTTP 400 |
| Ecwid / Cakesafe | Floating Cake Bases, public V3 search | not attempted after boundary | browser storefront-runtime boundary |
| Ecwid / Wylie Beckert | Wicked Kingdom sheet / `WK-UNCUT-FLAW` | not attempted after boundary | browser storefront-runtime boundary |
| SFCC / Dunlop Sports | Summer Major Towel / `12133488` | full standard SFRA guest flow | SF Ground $6.99 / 2 Day $14.99; Ground total $40.17 |
| SFCC / Alcott | Sneakers / `SC0071DOAY15` | `Cart-AddProduct` HTTP 500 | quote not reached |
| SFCC / HUGO BOSS | watch / `hbna58034135_999` | `Cart-AddProduct` redirected to HTML | quote not reached |

The domain-keyed observations, bot-wall status, and per-store shipping facts live in the learned cache in `vendors.md`.
