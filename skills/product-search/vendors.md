# Preferred Vendors

Tier is a soft ranking bias — a tiebreaker among comparable candidates, never a filter: the best product from any vendor still appears in the report, with its tier noted. Tiers: **preferred** (buy from these when possible) · **decent** (fine, no edge) · **last-resort** (only when nothing better exists) · **blacklisted** (never buy; the exception to "tiers never exclude" — a blacklisted vendor may still appear in a report as a spec/existence data point, marked not purchasable). Unlisted vendors are unrated and judged on their own merits. Vendor notes are maintained guidance; re-verify current prices, stock, platform behavior, and shipping when load-bearing.

When no stocked part fits, custom fabrication is in scope as an option (e.g. CNC machining in China often beats Misumi on price and lead time) — surface it via the manufacturer-RFQ technique; specific fab services aren't tiered here.

Platform labels are a scan aid. The cross-shop tool's `vendors.json` registry holds operational domain-to-platform facts.

| Vendor | Categories | Tier | Why | Trust | Platform (2026-07-31) | Cached facts |
|---|---|---|---|---|---|---|
| Digi-Key | electronics | preferred | fast, reliable stock data | listings reliable | custom | MCP for stock, price, and parametrics; credentials are expired and all calls return 401 |
| McMaster-Carr | mechanical/industrial | preferred | same-day ship, authoritative specs + CAD | listings authoritative | custom | MCP available |
| Bolt Depot | fasteners | preferred | cheap hardware | listings reliable | custom | — |
| Amazon | consumer goods, generic parts | preferred | free 1–2 day shipping, low prices | verify specs elsewhere — listings unreliable, commingled inventory | custom | For a known ASIN, `cross-shop` `product` returns the current title, image, rating, and offer-panel prices, sellers, shippers, and anonymous-default delivery promises. It is not keyword search or a destination quote. A GPT leaf remains useful for listing descriptions. PA-API retired in May 2026; Creators API is affiliate-gated, while the Business Product Search API requires business onboarding and authorization. |
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
| Zoro / Grainger | MRO/industrial | decent | Zoro is largely Grainger stock at lower prices with frequent coupons — always check Zoro pricing before recommending a Grainger part | listings reliable | custom | Both DataDome-walled to all automated fetch/browser routes (2026-08-07, challenge canvas renders height=0, unsolvable; one attempt drew an IP-level block) — price checks need a human or the user |
| GoBilda / ServoCity | robotics mechanicals | decent | robotics-mechanical ecosystem, premium vs raw imports; same parent company | listings reliable | BigCommerce | — |
| StepperOnline (OMC) | steppers, servos | decent | cheap-but-documented motors | verify key specs | OpenCart | — |
| Lowes / Home Depot | hardware-store goods | decent | on the commute — bulky items that would be expensive to ship; also online orders | listings reliable | custom | Home Depot product (`/p/`) and search (`/s/`) pages return Akamai 403 to all automated fetch and headless-Chromium routes (2026-08-30, homepage renders fine) — price checks need a human or a Firefox retry |
| Target | consumer goods | decent | nearby big-box, easy pickup | listings reliable | custom | — |
| JLCMC | mechanical parts | decent | cheap parts but expensive shipping | listings reliable | custom | — |
| LCSC | electronics | last-resort | slower and more expensive shipping than AliExpress | listings reliable | custom | — |
| Adafruit | hobbyist modules | last-resort | pricing and shipping cost; good docs remain the draw | listings authoritative | Zen Cart | — |
| Misumi | configurable precision mechanical | last-resort | long lead times and pricing; custom precision parts often better CNC-machined in China | listings authoritative | custom | — |
| Nash Fuel | propane/LP-gas equipment | blacklisted | Adrian-directed blacklist (2026-08-07); do not buy | — | custom | — |
