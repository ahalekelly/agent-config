# Preferred Vendors

Tier is a soft ranking bias — a tiebreaker among comparable candidates, never a filter: the best product from any vendor still appears in the report, with its tier noted. Tiers: **preferred** (buy from these when possible) · **decent** (fine, no edge) · **last-resort** (only when nothing better exists). Unlisted vendors are unrated and judged on their own merits. Cached facts are dated snapshots — re-verify when stale or load-bearing.

When no stocked part fits, custom fabrication is in scope as an option (e.g. CNC machining in China often beats Misumi on price and lead time) — surface it via the manufacturer-RFQ technique; specific fab services aren't tiered here.

Platform labels are a scan aid; operational platform, wall, shipping, and verification facts live only in the learned cache below.

| Vendor | Categories | Tier | Why | Trust | Platform (2026-07-31) | Cached facts |
|---|---|---|---|---|---|---|
| Digi-Key | electronics | preferred | fast, reliable stock data | listings reliable | custom | MCP for stock, price, and parametrics; credentials are expired and all calls return 401 |
| McMaster-Carr | mechanical/industrial | preferred | same-day ship, authoritative specs + CAD | listings authoritative | custom | MCP available |
| Bolt Depot | fasteners | preferred | cheap hardware | listings reliable | custom | — |
| Amazon | consumer goods, generic parts | preferred | free 1–2 day shipping, low prices | verify specs elsewhere — listings unreliable, commingled inventory | custom | A GPT leaf fetch returns the title, usually a product-photo URL, sometimes the description, and listing-dependent buy-box prices. Image CDN URLs can be resized by replacing their suffix (`._SL1500_`, `._SX679_`, and `._SS75_` resolve). Stock and seller need a browser or API. PA-API retired in May 2026; the Creators API requires 10 qualifying affiliate sales per rolling 30 days. Structured alternatives include ScraperAPI (about 200 free lookups monthly), Apify, Bright Data, or Keepa with the `BWB03/keepa-adapter` MCP (about €19 monthly; near-real-time, not live). |
| Automation Direct | industrial automation, pneumatics, sensors | preferred | very good pricing | listings reliable | custom | — |
| eBay | used/surplus, cheap goods | preferred | another cheap-stuff channel alongside Amazon/AliExpress | verify everything | custom | — |
| DERNORD | tri-clamp/sanitary fittings | preferred | preferred tri-clamp brand; sold via Amazon | Amazon listing caveats apply | Shopify | Amazon remains the practical channel for small fittings |
| Glacier Tanks | tri-clamp/sanitary fittings | decent | tri-clamp fittings vendor | listings reliable | Magento (guest API open) | — |
| Mouser | electronics | decent | only when cheaper than Digi-Key or Digi-Key is out of stock | listings reliable | custom | no MCP |
| Master Electronics | electronics (long-tail stock) | decent | hard-to-find and long-tail parts | listings reliable | custom | no MCP |
| Arrow | electronics | decent | price check like Mouser; occasional free shipping, sometimes best price on ICs | listings reliable | custom | no MCP |
| SparkFun | hobbyist modules | decent | documented modules at premium prices | listings authoritative | Magento (guest API open) | — |
| Pololu | motors, drivers, robotics electronics | decent | excellent first-party docs and test data; premium prices | listings authoritative | custom | — |
| Mettle Air | pneumatics | decent | cheaper than McMaster when you can afford to wait; more reputable than Amazon | verify key specs | Shopify | — |
| Omega | sensors, instrumentation | decent | authoritative specs, premium pricing | listings authoritative | custom | — |
| AliExpress | prototype-grade imports (mostly electronics, screws) | decent | cheap; some items only exist from no-name Chinese factories | verify everything | custom | official Affiliate Product API requires an approved app key; none is configured |
| Alibaba | bulk/custom from manufacturers | decent | real RFQ + purchase channel for volume/custom parts | verify everything — listed MOQs and prices unreliable | custom | practical minimum orders are typically a few hundred dollars |
| Zoro / Grainger | MRO/industrial | decent | Zoro is largely Grainger stock at lower prices with frequent coupons — always check Zoro pricing before recommending a Grainger part | listings reliable | custom | — |
| GoBilda / ServoCity | robotics mechanicals | decent | robotics-mechanical ecosystem, premium vs raw imports; same parent company | listings reliable | BigCommerce | — |
| StepperOnline (OMC) | steppers, servos | decent | cheap-but-documented motors | verify key specs | OpenCart | — |
| Lowes / Home Depot | hardware-store goods | decent | on the commute — bulky items that would be expensive to ship; also online orders | listings reliable | custom | — |
| Target | consumer goods | decent | nearby big-box, easy pickup | listings reliable | custom | — |
| JLCMC | mechanical parts | decent | cheap parts but expensive shipping | listings reliable | custom | — |
| LCSC | electronics | last-resort | slower and more expensive shipping than AliExpress | listings reliable | custom | — |
| Adafruit | hobbyist modules | last-resort | pricing and shipping cost; good docs remain the draw | listings authoritative | Zen Cart | — |
| Misumi | configurable precision mechanical | last-resort | long lead times and pricing; custom precision parts often better CNC-machined in China | listings authoritative | custom | — |

## Using platform APIs

Run `scripts/platform_api.py detect`, then `search` and `quote` with the returned opaque `item_ref`; `probe` performs the complete flow. Follow redirects, keep one cookie jar per origin, and treat a challenge as unresolved access rather than platform absence. Use BrowserSwarm only at the explicit boundaries below. See `platform-apis.md` for copyable requests, exact schemas, redaction rules, and failure modes.

| Platform | Positive probe | Product and quote path |
| --- | --- | --- |
| Shopify | signed tokenless Storefront GraphQL returns `data.shop` | helper; discover one `.myshopify.com` backend from source when a custom origin does not proxy |
| WooCommerce | Store API cart returns `totals` and `Cart-Token` | helper; product search → add simple item → update customer → `shipping_rates` |
| Magento | page fingerprint plus guest-cart response | helper; use an exact simple SKU; open guest cart → item → estimate methods; otherwise record gated |
| BigCommerce | BigCommerce CDN/Stencil marker | helper; `/search.php`/`BCData` → Storefront REST cart → checkout consignment |
| Squarespace | commerce collection `?format=json` returns items and a crumb | helper; exact item/SKU → cart entry → shipping location |
| Wix / Ecwid | platform bootstrap and public catalog token | public search only; destination quote requires the supported storefront runtime in BrowserSwarm |
| Salesforce Commerce Cloud | Demandware routes/headers/site ID | follow exact SFRA forms when standard; customized controllers require BrowserSwarm |
| OpenCart | `/catalog/view/` assets and cart route | page-specific product/options; challenged writes require BrowserSwarm |

Quote only to Jordan Smith, Pacific Prototyping LLC, 747 Howard St, San Francisco, CA 94103, US, +1 415-555-0132. Never create an account, enter payment, or place an order. Empty rates mean **no quote**. Zero is free only when a named delivery method says so; exclude pickup, paid-later, and quote-later methods. Record fallback labels, walls/gates, the tested product, taxes, and date.

## Learned storefront cache

This untiered cache is operational memory, not a vendor ranking. It is keyed by normalized domain: update a matching row when reverified and append a row for a new domain. The 2026-07-31 seed includes all 62 distinct entry domains in the acceptance corpus, plus resolved aliases and other preferred-vendor facts. Shipping is a snapshot for the tested item and SF destination, not a policy promise. `none` means no wall appeared in the tested workflow; an API gate or browser boundary is stated separately.

| Domain | Platform | Bot wall | Shipping facts | Verified |
|---|---|---|---|---|
| `digikey.com` | custom | Cloudflare | no free shipping; $4.99 USPS Ground Advantage / $8.49 FedEx-UPS Ground / $13.99 Priority or 2-day / $26.99 overnight PM | platform 2026-07-31; shipping 2026-07 |
| `mcmaster.com` | custom | none | rates shown before ordering; per-shipment weight pricing; typically about $10 for small items | platform 2026-07-31; shipping 2026-07 |
| `boltdepot.com` | custom | Cloudflare; fingerprint Chromium works | SF: Economy $8.40 lowest of six delivery rates; pickup excluded; no published flat rate or free threshold | 2026-07-31 |
| `amazon.com` | custom | robots.txt disallows declared AI agents including ClaudeBot, Claude-User, GPTBot, OAI-SearchBot, and ChatGPT-User; `/dp/` has no technical wall and serves declared bot user agents; search exposes titles without body text, plain WebFetch is unusable, and a GPT leaf fetch can reach listings | free shipping at $35 for non-Prime; Prime free | platform 2026-07-31; wall/shipping 2026-07 |
| `automationdirect.com` | custom | none | free 2-day shipping over $49; $10 flat under | platform 2026-07-31; shipping 2026-07 |
| `ebay.com` | custom | partial bot-check; homepage/help challenged, search works | seller-set shipping | platform 2026-07-31; shipping 2026-07 |
| `dernord.com` | Shopify | none | SF: flat "FeDex" rate $55 on a $10.59 fitting | 2026-07-31 |
| `glaciertanks.com` | Magento (guest API open) | Cloudflare; fingerprint Chromium works | SF: USPS Priority Mail $10.86 lowest of eight delivery rates; maximum $31.31; reported free ground at $500 from secondary sources | platform/quote 2026-07-31; threshold 2026-07 |
| `mouser.com` | custom | Akamai + DataDome | carrier pass-through; reported free threshold conflicts between $50 and $100 | platform 2026-07-31; shipping 2026-07 |
| `masterelectronics.com` | custom | Akamai | $8.99 UPS Ground flat under 15 lb | platform 2026-07-31; shipping 2026-07 |
| `arrow.com` | custom | Akamai; patched headless Chromium/Firefox renders | free FedEx Ground at $100 | platform 2026-07-31; wall 2026-07-30; shipping 2026-07 |
| `sparkfun.com` | Magento (guest API open) | none | SF: $9.32–$58.96 across nine delivery rates in the corpus probe; on a $22.50 board, FedEx Ground Economy $19.31 / FedEx Ground $30.32 / UPS Ground $34.28; free at $100 for logged-in orders under 10 lb; $2 handling fee on all orders; pickup/non-delivery excluded | corpus probe 2026-07-31; board quote/policy 2026-07-30 |
| `pololu.com` | custom | none | free at $100 of Pololu-brand goods ($75 add-on eligible); about $6.95 USPS Ground Advantage for 1 lb | platform 2026-07-31; shipping 2026-07 |
| `mettleair.com` | Shopify | none | redirects to `mettleairstore.com`; $27.78 Standard / $31.75 Expedited / $39.17 UPS Express Saver on a $144 manifold to SF; import/handling surcharge is separate | platform 2026-07-31; shipping 2026-07-30 |
| `mettleairstore.com` | Shopify | none | SF: 27.78–56.06 USD across 4 rate(s) | 2026-07-31 |
| `omega.com` | custom | Akamai | $10 UPS Ground ($8 for orders at or below $25); 2-day $22 | platform 2026-07-31; shipping 2026-07 |
| `aliexpress.us` | custom | none | typically 10–12 day shipping | platform 2026-07-31; shipping 2026-07 |
| `alibaba.com` | custom | CAPTCHA on search/product pages; homepage works | shipping is supplier/quote-specific | platform 2026-07-31; shipping 2026-07 |
| `zoro.com` | custom | Akamai + DataDome; blocks all tested headless engines | free at $50 signed-in; $5 flat under | platform 2026-07-31; wall 2026-07-30; shipping 2026-07 |
| `grainger.com` | custom | DataDome; blocks all tested headless engines | free threshold unclear | platform 2026-07-31; wall 2026-07-30; shipping 2026-07 |
| `gobilda.com` | BigCommerce | none | no free tier; SF: $7.86–$210.48 across four rates, including USPS Ground Advantage near $8 and an $11.99 flat-rate option | corpus probe 2026-07-31; policy 2026-07 |
| `servocity.com` | BigCommerce | none | no free tier; SF: $8.36–$129.22 across four rates, including USPS Ground Advantage near $8 and an $11.99 flat-rate option | corpus probe 2026-07-31; policy 2026-07 |
| `omc-stepperonline.com` | OpenCart | Cloudflare; cart write challenged | SF quote blocked before cart; no free threshold; US warehouse delivery 4–7 days; China orders are express-only with duties included; rates vary by item, warehouse, and destination | platform/probe 2026-07-31; policy 2026-07 |
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
| `manorsgolf.com` | Shopify | none | SF: International Economy 10.00 USD | 2026-07-31 |
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
| `rotarysolutions.com` | WooCommerce | none | SF: named Free shipping, 0 USD | 2026-07-31 |
| `tech7000.com` | WooCommerce | none | SF: 19.95 USD across 1 rate(s); merchant fallback rate present | 2026-07-31 |
| `store.nrgwave.com` | WooCommerce | none | SF: no quote (empty rates) | 2026-07-31 |
| `myolyn.com` | WooCommerce | none | SF: named USPS Flat Rate Envelope: FREE, 0 USD | 2026-07-31 |
| `dillonprecision.com` | Magento (guest API open) | none | SF: 11.95–44.45 USD across 3 rate(s); exclude pickup/non-delivery methods | 2026-07-31 |
| `killerinktattoo.co.uk` | Magento (guest API open) | none | SF: 4.12–29.97 GBP across 2 rate(s); exclude pickup/non-delivery methods | 2026-07-31 |
| `tilebar.com` | Magento (guest API open) | none | SF: 1 USD across 1 rate(s); exclude pickup/non-delivery methods | 2026-07-31 |
| `decksdirect.com` | Magento (guest API open) | none | SF: 9.99–126.85 USD across 3 rate(s); exclude pickup/non-delivery methods | 2026-07-31 |
| `barrdisplay.com` | Magento (guest API open) | none | SF: 17.97–100.20 USD across 4 delivery rates; pickup excluded | 2026-07-31 |
| `scoutshop.org` | Magento (guest API open) | none | SF: 3.95–30.72 USD across 3 rate(s); exclude pickup/non-delivery methods | 2026-07-31 |
| `blanks.ca` | Magento (guest API open) | none | SF: FedEx Ground 29.54 CAD lowest of 5 cross-border delivery rates | 2026-07-31 |
| `signet.net.au` | Magento (guest API open) | none | SF: only Freight 0 AUD on an account-priced item; non-actionable, not free shipping | 2026-07-31 |
| `atxfitness.com` | Magento (guest API open) | none | SF: named Free Shipping, 0 USD on a 2,999 USD machine | 2026-07-31 |
| `thecpapshop.com` | Magento (guest API open) | none | SF: 4.5–203.33 USD across 8 rate(s); exclude pickup/non-delivery methods | 2026-07-31 |
| `bulkreefsupply.com` | Magento (guest API gated) | none | quote not reached; guest cart gated | 2026-07-31 |
| `aheadworks.com` | Magento (guest API gated) | Cloudflare | quote not reached; Magento footprint with plain 401 guest endpoint | 2026-07-31 |
| `hi-line.com` | BigCommerce | none | SF: 9.95 USD across 1 rate(s) | 2026-07-31 |
| `hydraulichosetogo.com` | BigCommerce | none | SF: 17.99 USD across 1 rate(s) | 2026-07-31 |
| `intlairtool.com` | BigCommerce | none | SF: 23.5–36.22 USD across 2 rate(s) | 2026-07-31 |
| `spwindustrial.com` | BigCommerce | none | SF: named Free Shipping, 0 USD; FedEx 27.05–54.26 USD | 2026-07-31 |
| `fabricwarehouse.com` | BigCommerce | none | SF: 3.70–17.00 USD across 6 delivery rates; $0 PAID LATER excluded | 2026-07-31 |
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
| `malcowallshop.com` | Wix | none | redirects to `holzbuchstaben.ch`; SF quote not reached; storefront runtime/controller required | 2026-07-31 |
| `northboundcoffee.com` | Ecwid | none | USD 5.00 Flat Rate pre-address fallback; SF quote not verified | 2026-07-31 |
| `cakesafe.com` | Ecwid | none | SF quote not reached; storefront runtime/controller required | 2026-07-31 |
| `wyliebeckert.com` | Ecwid | none | SF quote not reached; storefront runtime/controller required | 2026-07-31 |
| `us.dunlopsports.com` | Salesforce Commerce Cloud | none | SF: Ground USD 6.99; 2 Day USD 14.99; tax USD 3.19; Ground total USD 40.17 | 2026-07-31 |
| `alcott.eu` | Salesforce Commerce Cloud | none | SF quote not reached; storefront runtime/controller required | 2026-07-31 |
| `hugoboss.com` | Salesforce Commerce Cloud | none | SF quote not reached; storefront runtime/controller required | 2026-07-31 |
