# Preferred Vendors

Tier is a soft ranking bias — a tiebreaker among comparable candidates, never a filter: the best product from any vendor still appears in the report, with its tier noted. Tiers: **preferred** (buy from these when possible) · **decent** (fine, no edge) · **last-resort** (only when nothing better exists). Unlisted vendors are unrated and judged on their own merits. Cached facts are dated snapshots — re-verify when stale or load-bearing.

When no stocked part fits, custom fabrication is in scope as an option (e.g. CNC machining in China often beats Misumi on price and lead time) — surface it via the manufacturer-RFQ technique; specific fab services aren't tiered here.

| Vendor | Categories | Tier | Why | Trust | Platform (2026-07-31) | Cached facts |
|---|---|---|---|---|---|---|
| Digi-Key | electronics | preferred | fast, reliable stock data | listings reliable | custom | MCP for stock/price/parametrics — MCP credentials expired, all calls 401 (2026-07-30); Cloudflare bot-wall; no free shipping: $4.99 USPS Ground Advantage / $8.49 FedEx-UPS Ground / $13.99 Priority or 2-day / $26.99 overnight PM (2026-07) |
| McMaster-Carr | mechanical/industrial | preferred | same-day ship, authoritative specs + CAD | listings authoritative | custom | MCP available; no bot-wall; shows shipping before ordering — per-shipment weight pricing, typically ~$10 for small items (2026-07) |
| Bolt Depot | fasteners | preferred | cheap hardware | listings reliable | custom | Cloudflare bot-wall; Economy $8.40 was the lowest live SF delivery rate; no published flat rate or free threshold (2026-07-31) |
| Amazon | consumer goods, generic parts | preferred | free 1–2 day shipping, low prices | verify specs elsewhere — listings unreliable, commingled inventory | custom | no technical bot-wall — Amazon serves full `/dp/` pages with live prices even to declared bot user agents — but the read tools are shut out by policy: robots.txt disallows essentially every declared AI agent by name, including `ClaudeBot`, `Claude-User`, `GPTBot`, `OAI-SearchBot` and `ChatGPT-User`, so search holds titles without body text and a plain `WebFetch` gets nothing usable. A GPT leaf's fetch, which does not consult robots.txt, does reach `/dp/` pages, but returns only what its extractor keeps: the title always, a real product-photo URL usually, the description body only sometimes, and a buy-box price on some listings and never on others (stable per listing across repeats, so worth one try). **Images are fully solvable without a browser** — take the `/images/I/<hash>` URL that fetch surfaces and request any size by swapping the suffix (`._SL1500_`, `._SX679_`, `._SS75_` all resolve); the image CDN serves plain fetches even though `/dp/` does not. Stock and seller need a browser or an API. Amazon's own PA-API was retired 2026-05 and its Creators API successor gates on 10 qualifying affiliate sales per rolling 30 days — not a buyer-side path. For structured data prefer a scraper API whose recurring free tier covers our volume (ScraperAPI ~200 lookups/mo, Apify, Bright Data), or Keepa plus the `BWB03/keepa-adapter` MCP (~€19/mo, near-real-time not live) (2026-07). Free shipping ≥$35 non-Prime, Prime free (2026-07) |
| Automation Direct | industrial automation, pneumatics, sensors | preferred | very good pricing | listings reliable | custom | no bot-wall; free 2-day shipping over $49, $10 flat under (2026-07) |
| eBay | used/surplus, cheap goods | preferred | another cheap-stuff channel alongside Amazon/AliExpress | verify everything | custom | partial bot-check — homepage/help challenged, search fine; shipping seller-set (2026-07) |
| DERNORD | tri-clamp/sanitary fittings | preferred | preferred tri-clamp brand; sold via Amazon | Amazon listing caveats apply | Shopify | flat "FeDex" rate was $55 on a $10.59 fitting, so Amazon stays the right channel (live quote 2026-07-30) |
| Glacier Tanks | tri-clamp/sanitary fittings | decent | tri-clamp fittings vendor | listings reliable | Magento (guest API open) | Cloudflare bot-wall; USPS Priority Mail $10.86 was the lowest of eight live SF rates (2026-07-31); free ground ≥$500 per secondary sources (2026-07) |
| Mouser | electronics | decent | only when cheaper than Digi-Key or Digi-Key is out of stock | listings reliable | custom | no MCP; Akamai+DataDome bot-wall; carrier pass-through rates, free threshold $50–100 (sources conflict) (2026-07) |
| Master Electronics | electronics (long-tail stock) | decent | hard-to-find and long-tail parts | listings reliable | custom | no MCP; Akamai bot-wall; $8.99 UPS Ground flat under 15 lb (2026-07) |
| Arrow | electronics | decent | price check like Mouser; occasional free shipping, sometimes best price on ICs | listings reliable | custom | no MCP; Akamai bot-wall; loads in fingerprint-patched headless Chromium or Firefox (verified 2026-07-30); free FedEx Ground ≥$100 (2026-07) |
| SparkFun | hobbyist modules | decent | documented modules at premium prices | listings authoritative | Magento (guest API open) | no bot-wall; FedEx Ground Economy $19.31 / FedEx Ground $30.32 / UPS Ground $34.28 on a $22.50 board to SF (live quote 2026-07-30); free ≥$100 logged-in under 10 lb; $2 handling fee on all orders (2026-07) |
| Pololu | motors, drivers, robotics electronics | decent | excellent first-party docs and test data; premium prices | listings authoritative | custom | no bot-wall; free ≥$100 Pololu-brand ($75 add-on-eligible); ~$6.95 USPS Ground Advantage for 1 lb (live quote 2026-07) |
| Mettle Air | pneumatics | decent | cheaper than McMaster when you can afford to wait; more reputable than Amazon | verify key specs | Shopify | no bot-wall; mettleair.com redirects to mettleairstore.com; $27.78 Standard / $31.75 Expedited / $39.17 UPS Express Saver on a $144 manifold to SF (live quote 2026-07-30); import/handling surcharge broken out at cart (2026-07) |
| Omega | sensors, instrumentation | decent | authoritative specs, premium pricing | listings authoritative | custom | Akamai bot-wall; flat rates: $10 UPS Ground ($8 for ≤$25 orders), 2-day $22 (2026-07) |
| AliExpress | prototype-grade imports (mostly electronics, screws) | decent | cheap; some items only exist from no-name Chinese factories | verify everything | custom | official Affiliate Product API requires an approved app key and none is configured; no bot-wall on aliexpress.us; ~10–12 day shipping (2026-07-31) |
| Alibaba | bulk/custom from manufacturers | decent | real RFQ + purchase channel for volume/custom parts | verify everything — listed MOQs and prices unreliable | custom | real minimum order ~a couple hundred dollars; search/product pages CAPTCHA to headless browsers, homepage fine (2026-07) |
| Zoro / Grainger | MRO/industrial | decent | Zoro is largely Grainger stock at lower prices with frequent coupons — always check Zoro pricing before recommending a Grainger part | listings reliable | custom | Zoro runs Akamai+DataDome, Grainger DataDome-only — both block every headless engine (2026-07-30); Zoro free ≥$50 signed-in, $5 flat under; Grainger threshold unclear (2026-07) |
| GoBilda / ServoCity | robotics mechanicals | decent | robotics-mechanical ecosystem, premium vs raw imports; same parent company | listings reliable | BigCommerce | no bot-wall; no free tier; ~$8 USPS Ground Advantage, $11.99 flat rate (live quotes 2026-07) |
| StepperOnline (OMC) | steppers, servos | decent | cheap-but-documented motors | verify key specs | OpenCart | Cloudflare bot-wall; no free threshold; US warehouse 4–7 day, China orders express-only with duties pre-included (2026-07) |
| Lowes / Home Depot | hardware-store goods | decent | on the commute — bulky items that would be expensive to ship; also online orders | listings reliable | custom | Lowes fully bot-walled (Akamai), Home Depot homepage-only partial; both free ≥$45 ($5.99 / $8.99 under) (2026-07) |
| Target | consumer goods | decent | nearby big-box, easy pickup | listings reliable | custom | no bot-wall; free 2-day ≥$35, $5.99 under (2026-07) |
| JLCMC | mechanical parts | decent | cheap parts but expensive shipping | listings reliable | custom | no bot-wall; no free tier; ~$11 slow line (8–13 day) for 1 lb, express $26+ (2026-07) |
| LCSC | electronics | last-resort | slower and more expensive shipping than AliExpress | listings reliable | custom | Akamai bot-wall; free shipping only as monthly promos (~$499); dynamic checkout rates (2026-07) |
| Adafruit | hobbyist modules | last-resort | pricing and shipping cost; good docs remain the draw | listings authoritative | Zen Cart | no bot-wall; no domestic free threshold; ~$8–9 USPS Ground Advantage for 1 lb (2026-07) |
| Misumi | configurable precision mechanical | last-resort | long lead times and pricing; custom precision parts often better CNC-machined in China | listings authoritative | custom | Akamai bot-wall; per-order freight quotes, can be disproportionate on small orders (2026-07) |

## Using platform APIs

Follow the homepage redirect and keep one cookie jar on the resolved origin. Use a current browser User-Agent. A challenge, intercepted 403, or TLS failure means unresolved access, not platform absence. For rate tests use Jordan Smith, Pacific Prototyping LLC, 747 Howard St, San Francisco, CA 94103, US, +1 415-555-0132. Stop after the quote: never create an account, enter payment, or place an order. Exact payloads and tested failure modes are in `platform-apis.md`.

- **Shopify:** Positive probe: signed `POST /api/2026-07/graphql.json` with `{shop{name}}` returns `data.shop`; sign through `scripts/web_bot_auth.py`. Search with Storefront GraphQL `products(query:)`, create a cart containing the chosen variant and `buyerIdentity.deliveryAddressPreferences`, then query `deliveryGroups(first:10,withCarrierRates:true)` inside `... @defer { ... }`. Parse every `multipart/mixed` part; rates normally arrive in an incremental part. If a headless/custom origin does not proxy the API, discover its single `*.myshopify.com` backend from source and retry there.
- **WooCommerce:** Positive probe: `GET /wp-json/wc/store/v1/cart` returns JSON containing `totals`; retain its `Cart-Token` header. Search `/wp-json/wc/store/v1/products?search=...&per_page=20`, add an in-stock purchasable simple item through `/cart/add-item`, then send the address to `/cart/update-customer`. Read `shipping_rates`, taxes, currency, and `currency_minor_unit`; empty-cart shipping totals may be null, and a `rate_id` ending `_fallback` is a merchant fallback.
- **Magento / Adobe Commerce:** Require a Magento page fingerprint, then `POST /rest/V1/guest-carts` with `{}`. A quoted token proves the guest cart is open; a Magento-shaped 401/403/404/405 plus page evidence proves gated or disabled. Obtain a concrete simple SKU from the sitemap, storefront search, or product-page JSON-LD because anonymous `/rest/V1/products` is normally gated. Add it at `/rest/V1/guest-carts/<token>/items`, then call `/estimate-shipping-methods` with the address. Preserve carrier/method codes and distinguish delivery from pickup.
- **BigCommerce Stencil:** Positive fingerprints include `cdn11.bigcommerce.com/s-<hash>`, Stencil assets, and `x-bc-store-id`. Discover products through `/search.php`, `/xmlsitemap.php`, product-page `BCData`, or a page-exposed Storefront GraphQL token. Create the guest cart with `POST /api/storefront/carts`; retain its `SHOP_SESSION_TOKEN`, `SF-CSRF-TOKEN`, cart ID, and physical item ID. Post the address and item to `/api/storefront/checkouts/<cart-id>/consignments?include=consignments.availableShippingOptions` with the session cookie and `X-SF-CSRF-TOKEN` header. Tokenless GraphQL is gated; the generic cart and quote are not.
- **Squarespace:** Require Squarespace headers/context and a store collection whose `?format=json` response contains `items`. Keep its `crumb` cookie, then `POST /api/commerce/shopping-cart/entries` with `X-CSRF-Token: <crumb>`, a unique `Add-To-Cart-Id`, and the exact `itemId`/`sku`. Read `shoppingCart.cartToken`; `PUT /api/3/commerce/cart/<token>/shipping/location` with the address and read `shippingOptionsStatus` plus `fulfillmentOptions`.
- **Ecwid:** Detect `app.ecwid.com/script.js?<storeId>`, read its storefront `apiBaseUrl`, and obtain the page-issued `ecwid-storefront` token through `initial-data`. Use that token with `app.ecwid.com/api/v3/<storeId>/products` for public search. Guest checkout can expose a pre-address fallback rate, but destination address mutation crosses the storefront-runtime boundary; use browser-swarm and do not replay internal `/checkout/update`.
- **Wix:** Require Pepyaka/Wix markers, obtain the visitor/app tokens from `/_api/v1/access-tokens`, and use the e-commerce app token with the catalog reader for public products. Generic cart catalog references do not resolve reliably, so cart and quote are browser-swarm/site-SDK cases; page-issued tokens are not merchant credentials and must not be persisted.
- **Salesforce Commerce Cloud / Demandware:** Detect Demandware static/store routes, headers, and site identifiers. Use live storefront search and product pages. Where standard SFRA forms exist, add a concrete variant, open `Checkout-Begin`, then submit the guest-email and shipping forms with their exact actions, field names, shipment UUIDs, method ID, and CSRF token. Customized sites remain browser-swarm/controller cases.
- **OpenCart:** Detect `/catalog/view/` assets and `index.php?route=checkout/cart/add`. Product and required-option discovery are page-specific; post the concrete `product_id`, quantity, and required `option[...]` values to the cart route. If the write is challenged after readable GETs, classify it as an endpoint-specific bot wall and move the quote to browser-swarm.

For every platform, an empty rate list is **no quote**, never free shipping. A zero value is free only when an explicit delivery method says so; pickup, paid-later freight, and quote-later placeholders are not free. Record fallback-labelled rates, wall/gate status, the tested product, destination, taxes exposed by the cart, and the date.

## Learned storefront cache

This untiered cache is operational memory, not a vendor ranking. It is keyed by normalized domain: update a matching row when reverified and append a row for a new domain. Shipping is a snapshot for the tested item and SF destination, not a policy promise. `none` means no wall appeared in the tested workflow; an API gate or browser boundary is stated separately.

| Domain | Platform | Bot wall | Shipping facts | Verified |
|---|---|---|---|---|
| `digikey.com` | custom | Cloudflare | no free shipping; $4.99 USPS Ground Advantage / $8.49 FedEx-UPS Ground / $13.99 Priority or 2-day / $26.99 overnight PM | platform 2026-07-31; shipping 2026-07 |
| `mcmaster.com` | custom | none | per-shipment weight pricing; typically about $10 for small items | platform 2026-07-31; shipping 2026-07 |
| `boltdepot.com` | custom | Cloudflare; fingerprint Chromium works | SF: Economy $8.40 lowest of six delivery rates; pickup excluded | 2026-07-31 |
| `amazon.com` | custom | robots policy blocks declared AI agents; no technical wall on /dp/ | free shipping at $35 for non-Prime; Prime free | platform 2026-07-31; shipping 2026-07 |
| `automationdirect.com` | custom | none | free 2-day shipping over $49; $10 flat under | platform 2026-07-31; shipping 2026-07 |
| `ebay.com` | custom | partial bot-check; search works | seller-set shipping | platform 2026-07-31; shipping 2026-07 |
| `dernord.com` | Shopify | none | SF: 55 USD across 1 rate(s) | 2026-07-31 |
| `glaciertanks.com` | Magento (guest API open) | Cloudflare; fingerprint Chromium works | SF: $10.86–$31.31 across eight delivery rates | 2026-07-31 |
| `mouser.com` | custom | Akamai + DataDome | carrier pass-through; reported free threshold conflicts between $50 and $100 | platform 2026-07-31; shipping 2026-07 |
| `masterelectronics.com` | custom | Akamai | $8.99 UPS Ground flat under 15 lb | platform 2026-07-31; shipping 2026-07 |
| `arrow.com` | custom | Akamai; patched headless Chromium/Firefox renders | free FedEx Ground at $100 | platform 2026-07-31; shipping 2026-07 |
| `sparkfun.com` | Magento (guest API open) | none | SF: 9.32–58.96 USD across 9 rate(s); exclude pickup/non-delivery methods | 2026-07-31 |
| `pololu.com` | custom | none | free at $100 of Pololu-brand goods ($75 add-on eligible); about $6.95 USPS Ground Advantage for 1 lb | platform 2026-07-31; shipping 2026-07 |
| `mettleair.com` | Shopify | none | $27.78 Standard / $31.75 Expedited / $39.17 UPS Express Saver on a $144 manifold to SF; import/handling surcharge is separate | platform 2026-07-31; shipping 2026-07-30 |
| `mettleairstore.com` | Shopify | none | SF: 27.78–56.06 USD across 4 rate(s) | 2026-07-31 |
| `omega.com` | custom | Akamai | $10 UPS Ground ($8 for orders at or below $25); 2-day $22 | platform 2026-07-31; shipping 2026-07 |
| `aliexpress.us` | custom | none | typically 10–12 day shipping | platform 2026-07-31; shipping 2026-07 |
| `alibaba.com` | custom | CAPTCHA on search/product pages; homepage works | shipping is supplier/quote-specific | platform 2026-07-31; shipping 2026-07 |
| `zoro.com` | custom | Akamai + DataDome | free at $50 signed-in; $5 flat under | platform 2026-07-31; shipping 2026-07 |
| `grainger.com` | custom | DataDome | free threshold unclear | platform 2026-07-31; shipping 2026-07 |
| `gobilda.com` | BigCommerce | none | SF: 7.86–210.48 USD across 4 rate(s) | 2026-07-31 |
| `servocity.com` | BigCommerce | none | SF: 8.36–129.22 USD across 4 rate(s) | 2026-07-31 |
| `omc-stepperonline.com` | OpenCart | Cloudflare; cart write challenged | SF quote blocked before cart; rates vary by item, warehouse, and destination | 2026-07-31 |
| `lowes.com` | custom | Akamai | free at $45; $5.99 under | platform 2026-07-31; shipping 2026-07 |
| `homedepot.com` | custom | partial wall; homepage-only in prior benchmark | free at $45; $8.99 under | platform 2026-07-31; shipping 2026-07 |
| `target.com` | custom | none | free 2-day at $35; $5.99 under | platform 2026-07-31; shipping 2026-07 |
| `jlcmc.com` | custom | none | no free tier; about $11 slow line (8–13 day) for 1 lb; express $26+ | platform 2026-07-31; shipping 2026-07 |
| `lcsc.com` | custom | Akamai | free shipping only as monthly promos (about $499); dynamic checkout rates | platform 2026-07-31; shipping 2026-07 |
| `adafruit.com` | Zen Cart | none | no domestic free threshold; about $8–9 USPS Ground Advantage for 1 lb | platform 2026-07-31; shipping 2026-07 |
| `us.misumi-ec.com` | custom | Akamai | per-order freight quotes; can be disproportionate on small orders | platform 2026-07-31; shipping 2026-07 |
| `garagecabinetsonline.com` | Shopify | none | SF: 12.99 USD across 1 rate(s) | 2026-07-31 |
| `aircompressorservices.com` | Shopify | none | SF: 448.41–535.84 USD across 2 rate(s) | 2026-07-31 |
| `hydraulic-components.net` | Shopify | none | SF: no quote (empty rates) | 2026-07-31 |
| `parkerhydraulics-shop.co.uk` | Shopify | none | SF: no quote (empty rates) | 2026-07-31 |
| `carex.com` | Shopify | none | SF: 9.99 USD across 1 rate(s) | 2026-07-31 |
| `saslocksmiths.com` | Shopify | none | SF: no quote (empty rates) | 2026-07-31 |
| `sikahealth.com` | Shopify | none | SF: no quote (empty rates) | 2026-07-31 |
| `manorsgolf.com` | Shopify | none | SF: 10 USD across 1 rate(s) | 2026-07-31 |
| `nour-hammour.com` | Shopify | none | SF: explicit FREE rate, 0 USD | 2026-07-31 |
| `attitudeliving.com` | Shopify | none | SF: 12.99 USD across 1 rate(s) | 2026-07-31 |
| `actisense.com` | WooCommerce | none | SF: no quote (empty rates) | 2026-07-31 |
| `gps.co.uk` | WooCommerce | none | SF: no quote (empty rates) | 2026-07-31 |
| `puresealservices.co.uk` | WooCommerce | none | SF: no quote (empty rates); cart tax 30 GBP | 2026-07-31 |
| `f-o-a.com` | WooCommerce | none | SF: no quote (empty rates); cart tax 2.93 USD | 2026-07-31 |
| `resin-pro.co.uk` | WooCommerce | none | SF: 24.85–29.85 GBP across 2 rate(s) | 2026-07-31 |
| `rope-source.co.uk` | WooCommerce | none | SF: 80 GBP across 1 rate(s) | 2026-07-31 |
| `protosupplies.com` | WooCommerce | none | SF: 6.95–16.95 USD across 3 rate(s) | 2026-07-31 |
| `makerstore.cc` | WooCommerce | none | SF: 6.01–35.35 USD across 7 rate(s) | 2026-07-31 |
| `rotarysolutions.com` | WooCommerce | none | SF: 0 USD across 1 rate(s) | 2026-07-31 |
| `tech7000.com` | WooCommerce | none | SF: 19.95 USD across 1 rate(s); merchant fallback rate present | 2026-07-31 |
| `store.nrgwave.com` | WooCommerce | none | SF: no quote (empty rates) | 2026-07-31 |
| `myolyn.com` | WooCommerce | none | SF: 0 USD across 1 rate(s) | 2026-07-31 |
| `dillonprecision.com` | Magento (guest API open) | none | SF: 11.95–44.45 USD across 3 rate(s); exclude pickup/non-delivery methods | 2026-07-31 |
| `killerinktattoo.co.uk` | Magento (guest API open) | none | SF: 4.12–29.97 GBP across 2 rate(s); exclude pickup/non-delivery methods | 2026-07-31 |
| `tilebar.com` | Magento (guest API open) | none | SF: 1 USD across 1 rate(s); exclude pickup/non-delivery methods | 2026-07-31 |
| `decksdirect.com` | Magento (guest API open) | none | SF: 9.99–126.85 USD across 3 rate(s); exclude pickup/non-delivery methods | 2026-07-31 |
| `barrdisplay.com` | Magento (guest API open) | none | SF: 0–100.2 USD across 5 rate(s); exclude pickup/non-delivery methods | 2026-07-31 |
| `scoutshop.org` | Magento (guest API open) | none | SF: 3.95–30.72 USD across 3 rate(s); exclude pickup/non-delivery methods | 2026-07-31 |
| `thecpapshop.com` | Magento (guest API open) | none | SF: 4.5–203.33 USD across 8 rate(s); exclude pickup/non-delivery methods | 2026-07-31 |
| `bulkreefsupply.com` | Magento (guest API gated) | none | quote not reached; guest cart gated | 2026-07-31 |
| `hi-line.com` | BigCommerce | none | SF: 9.95 USD across 1 rate(s) | 2026-07-31 |
| `hydraulichosetogo.com` | BigCommerce | none | SF: 17.99 USD across 1 rate(s) | 2026-07-31 |
| `intlairtool.com` | BigCommerce | none | SF: 23.5–36.22 USD across 2 rate(s) | 2026-07-31 |
| `spwindustrial.com` | BigCommerce | none | SF: 0–54.26 USD across 3 rate(s) | 2026-07-31 |
| `fabricwarehouse.com` | BigCommerce | none | SF: 0–17 USD across 7 rate(s); a $0 paid-later method is not free | 2026-07-31 |
| `buckleguy.com` | BigCommerce | none | SF: 8.99–50.8 USD across 6 rate(s) | 2026-07-31 |
| `debrovys.com` | BigCommerce | none | SF: 3460.48–3685.48 USD across 2 rate(s) | 2026-07-31 |
| `tackledirect.com` | BigCommerce | none | SF: 4.99–161.01 USD across 4 rate(s) | 2026-07-31 |
| `valinonline.com` | BigCommerce | none | SF: 33.91–142.37 USD across 9 rate(s) | 2026-07-31 |
| `franklygoodcoffee.com` | Squarespace | none | selected item did not require shipping; not a parcel quote | 2026-07-31 |
| `archive07.com` | Squarespace | none | SF: no quote (no applicable rate) | 2026-07-31 |
| `marieburgoscollection.com` | Squarespace | none | SF: Standard USD 161.13; Oversized / Heavy Shipping USD 562.13 | 2026-07-31 |
| `izzywheels.com` | Wix | none | SF quote not reached; storefront runtime/controller required | 2026-07-31 |
| `bestiehugs.com` | Wix | none | SF quote not reached; storefront runtime/controller required | 2026-07-31 |
| `holzbuchstaben.ch` | Wix | none | SF quote not reached; storefront runtime/controller required | 2026-07-31 |
| `northboundcoffee.com` | Ecwid | none | USD 5.00 Flat Rate pre-address fallback; SF quote not verified | 2026-07-31 |
| `cakesafe.com` | Ecwid | none | SF quote not reached; storefront runtime/controller required | 2026-07-31 |
| `wyliebeckert.com` | Ecwid | none | SF quote not reached; storefront runtime/controller required | 2026-07-31 |
| `us.dunlopsports.com` | Salesforce Commerce Cloud | none | SF: Ground USD 6.99; 2 Day USD 14.99; tax USD 3.19; Ground total USD 40.17 | 2026-07-31 |
| `alcott.eu` | Salesforce Commerce Cloud | none | SF quote not reached; storefront runtime/controller required | 2026-07-31 |
| `hugoboss.com` | Salesforce Commerce Cloud | none | SF quote not reached; storefront runtime/controller required | 2026-07-31 |
