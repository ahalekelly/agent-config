# Product-search storefront HTTP evidence — 2026-08-01

This read-only acceptance rerun used one literal query (`a`) per store with no alternate-query retries. It called the production detection and platform search adapters over plain HTTP. Magento capability negotiation used one bounded product-search GraphQL query. The run created no cart, product line, customer address, consignment, or shipping-rate request.

Opaque product references were hashed in memory and discarded. The JSONL contains only public detection evidence, whitelisted product fields, sanitized HTTP request metadata, and learned-cache domain joins.

Every row carries source-tree SHA-256 `71fdb9ada5e47129baf9a9beb9be9d612adc7aa3027f9336078f5d8349f5666a`, computed from the platform API, adapters, read-only HTTP policy, acceptance runner, and signing helper. The exact per-domain disposition SHA-256 is `d19ffd2b33185417116488bd32abb5e8d1caa8dba802255740f4717deef8c496`. The observation window was 2026-08-02 03:28:43–03:32:52 UTC (2026-08-01 local time).

## Summary

| Expected group | Total | Positive candidates | Empty | Tool errors | Terminal/not run | Detection mismatches |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Shopify | 12 | 12 | 0 | 0 | 0 | 0 |
| WooCommerce | 12 | 12 | 0 | 0 | 0 | 0 |
| Magento | 12 | 8 | 4 | 0 | 0 | 0 |
| BigCommerce | 11 | 9 | 2 | 0 | 0 | 0 |
| Squarespace | 3 | 3 | 0 | 0 | 0 | 0 |
| Wix | 3 | 2 | 1 | 0 | 0 | 0 |
| Ecwid | 3 | 0 | 2 | 0 | 1 | 1 |
| Salesforce Commerce Cloud | 3 | 3 | 0 | 0 | 0 | 0 |

## Per-store outcomes

| Store | Expected | Detection | Search outcome | Candidates | Selection | Selected product | SKU |
| --- | --- | --- | --- | ---: | --- | --- | --- |
| DERNORD (`dernord.com`) | Shopify | shopify | search / storefront_graphql | 71 | selected | 1.5" Tri Clamp \| to Hose Barbed Adapter \| Sanitary Hose Barb Pipe Fitting | DER003 |
| Mettle Air (`mettleair.com`) | Shopify | shopify | search / storefront_graphql | 20 | selected | Composite Compact PTC Run Tee 5/32" OD - 1/8" BSPT Male | MTD5/32-01C |
| Garage Cabinets Online (`garagecabinetsonline.com`) | Shopify | shopify | search / storefront_graphql | 20 | selected | Gladiator GAWUXXSCRH Scoop Hook | GAWUXXSCRH |
| Air Compressor Services (`aircompressorservices.com`) | Shopify | shopify | search / storefront_graphql | 20 | selected | Champion Cooler Replacement - EFC89754889 | EFC89754889 |
| VHS Hydraulics (`hydraulic-components.net`) | Shopify | shopify | search / storefront_graphql | 20 | selected | Dana Brevini Cetop 3 (NG6) Auto-Reciprocating  Valve 20-140 Bar | BRVAD3RI211Z2003 |
| Parker Hydraulics & Pneumatics (`parkerhydraulics-shop.co.uk`) | Shopify | shopify | search / storefront_graphql | 226 | selected | IMO-Miniature Circuit Breaker 1 Pole Type C | I1B10C1002 |
| Carex (`carex.com`) | Shopify | shopify | search / storefront_graphql | 32 | selected | AccuRelief&trade; Universal Supply Kit | ACRL-0021 |
| SAS Locksmiths (`saslocksmiths.com`) | Shopify | shopify | search / storefront_graphql | 21 | selected | Dorma Slide Arm & Channel G-n Suit Ts92 & Ts93 Silver 64010001 | DO93GN |
| Sika Marketplace (`sikahealth.com`) | Shopify | shopify | search / storefront_graphql | 27 | selected | Soothing Hydration Cream | 415035 |
| Manors Golf (`manorsgolf.com`) | Shopify | shopify | search / storefront_graphql | 320 | selected | Tech Cap | A-24SS-FRONTIER-CAP-DOLV |
| Nour Hammour (`nour-hammour.com`) | Shopify | shopify | search / storefront_graphql | 85 | selected | Hatti | HattiBlackXL |
| ATTITUDE Living (`attitudeliving.com`) | Shopify | shopify | search / storefront_graphql | 78 | selected | Pet Wipes | 81160 |
| Actisense (`actisense.com`) | WooCommerce | woocommerce | search / wc_store_api | 20 | selected | NMEA 2000 to Wi-Fi Gateway | A-W2K-2 |
| GPS Pilot Supplies (`gps.co.uk`) | WooCommerce | woocommerce | search / wc_store_api | 20 | selected | Insta360 X3 Mic Adapter | CINSBAQ/A |
| Pureseal Services (`puresealservices.co.uk`) | WooCommerce | woocommerce | search / wc_store_api | 20 | selected | GutterRepair Pro | GUTREP.05 |
| F-O-A Shocks (`f-o-a.com`) | WooCommerce | woocommerce | search / wc_store_api | 20 | selected | Shock Seal Insertion Tool (Steel) | — |
| Resin Pro UK (`resin-pro.co.uk`) | WooCommerce | woocommerce | search / wc_store_api | 20 | selected | Wooden Resin Coaster Starter Kit – Create Beautiful Handmade Coasters at Home | WOODCOASTERKIT |
| Rope Source (`rope-source.co.uk`) | WooCommerce | woocommerce | search / wc_store_api | 20 | selected | SAMPLES | — |
| ProtoSupplies (`protosupplies.com`) | WooCommerce | woocommerce | search / wc_store_api | 20 | selected | Dupont 2.54mm Connector Housing 14-Pin (10-Pack) | CON-35 |
| Maker Store USA (`makerstore.cc`) | WooCommerce | woocommerce | search / wc_store_api | 20 | selected | FORTIS E5X MCS T4.1 &#8211; Ethernet 5-Axis Motion Control System | ELEC-FORTIS-E5X |
| Rotary Solutions (`rotarysolutions.com`) | WooCommerce | woocommerce | search / wc_store_api | 20 | selected | Pro Jack 4000 | RJ40BBK |
| Tech7000 (`tech7000.com`) | WooCommerce | woocommerce | search / wc_store_api | 9 | selected | Tech7000 25HA3 SSTK 3″ x 3 1/2″ Wrenches | 25HA325 |
| NRG Wave (`store.nrgwave.com`) | WooCommerce | woocommerce | search / wc_store_api | 4 | selected | PHYTO PRO MAXX | — |
| MYOLYN (`myolyn.com`) | WooCommerce | woocommerce | search / wc_store_api | 17 | selected | MyoCycle V1 Stimulation Cable | AS-0017 |
| SparkFun (`sparkfun.com`) | Magento | magento | search / magento_graphql | 10 | selected | USB OTG Cable - Female A to Micro-A - 4&quot; | CAB-11604 |
| DecksDirect (`decksdirect.com`) | Magento | magento | search / magento_graphql | 251 | selected | SMART-BIT® Depth Setter Tool by Starborn | BDA565A |
| Barr Display (`barrdisplay.com`) | Magento | magento | search / magento_graphql | 10 | selected | 90"H White Wall Showcase-- Modern Collection | 2066A |
| Scout Shop (`scoutshop.org`) | Magento | magento | search / magento_graphql | 44 | selected | Veteran Unit Bar Emblem | 105 |
| Blanks.ca (`blanks.ca`) | Magento | magento | search / magento_html | 0 | empty | — | — |
| Signet Australia (`signet.net.au`) | Magento | magento | search / magento_graphql | 10 | selected | 3M P2 Dust/Mist Respirator Without Valve | SIG_10276 |
| ATX Fitness USA (`atxfitness.com`) | Magento | magento | search / magento_html | 0 | empty | — | — |
| The CPAP Shop (`thecpapshop.com`) | Magento | magento | search / magento_html | 0 | empty | — | — |
| Dillon Precision (`dillonprecision.com`) | Magento | magento | search / magento_html | 0 | empty | — | — |
| TileBar (`tilebar.com`) | Magento | magento | search / magento_html | 61 | selected | Zelora | TLSEGBLNBG4X4 |
| Bulk Reef Supply (`bulkreefsupply.com`) | Magento | magento | search / magento_html | 17 | selected | Low Range pH/Conductivity/TDS Combo Pen HI98129 - Hanna | 211107 |
| Aheadworks (`aheadworks.com`) | Magento | magento | search / magento_graphql | 20 | selected | Follow Up Email | ext.fue-community-0 |
| ServoCity (`servocity.com`) | BigCommerce | bigcommerce | search / html_search_and_product_pages | 3 | selected | 15" x 15" ABS Sheet (0.250" Thickness) | ABS250-15-15 |
| Hi-Line (`hi-line.com`) | BigCommerce | bigcommerce | search / html_search_and_product_pages | 3 | selected | Aerosol Topper | ACR13 |
| Hydraulic Hose To Go (`hydraulichosetogo.com`) | BigCommerce | bigcommerce | search / html_search_and_product_pages | 3 | selected | Off-Road Hydraulic Orbital Steering Valve Mount | AM-AV0I-O60Q |
| goBILDA (`gobilda.com`) | BigCommerce | bigcommerce | search / html_search_and_product_pages | 3 | selected | 1111 Series Angle Pattern Bracket (1-1) | 1111-0001-0001 |
| International Air Tool (`intlairtool.com`) | BigCommerce | bigcommerce | search / html_search_and_product_pages | 3 | selected | Aircat Pneumatic Tools 1994 Super Duty Straight Impact Wrench With 8" Extended Anvil \| 2300 (ft-lbs) Max Torque \| 4500 RPM \| 1"x8" Square Drive | 1994 |
| SPW Industrial (`spwindustrial.com`) | BigCommerce | bigcommerce | search / html_search_and_product_pages | 3 | selected | Leybold Inficon 904-432-G1 - Residual Gas Analyzer | ADA-287055844445 |
| Fabric Warehouse (`fabricwarehouse.com`) | BigCommerce | bigcommerce | search / html_search_and_product_pages | 3 | no_eligible_candidate | — | — |
| Buckleguy (`buckleguy.com`) | BigCommerce | bigcommerce | search / html_search_and_product_pages | 0 | empty | — | — |
| DeBrovys (`debrovys.com`) | BigCommerce | bigcommerce | search / html_search_and_product_pages | 3 | selected | Aluminum Cabinet Cab Rack | 40-310 |
| TackleDirect (`tackledirect.com`) | BigCommerce | bigcommerce | search / html_search_and_product_pages | 0 | empty | — | — |
| Valin (`valinonline.com`) | BigCommerce | bigcommerce | search / html_search_and_product_pages | 3 | no_eligible_candidate | — | — |
| Frankly Good Coffee (`franklygoodcoffee.com`) | Squarespace | squarespace | search / squarespace_storefront_search | 12 | selected | Cold Brew Blend | Flagship-003-WB |
| Archive07 (`archive07.com`) | Squarespace | squarespace | search / squarespace_storefront_search | 25 | selected | Spacebot V03 - Enamel Pin | SQ3537556 |
| Marie Burgos Collection (`marieburgoscollection.com`) | Squarespace | squarespace | search / squarespace_storefront_search | 1046 | selected | Aimi Bar & Counter Stool | SQ5653938 |
| Izzy Wheels (`izzywheels.com`) | Wix | wix | search / catalog_reader | 10 | selected | Amalfi Lemons | — |
| Bestie Hugs (`bestiehugs.com`) | Wix | wix | search / catalog_reader | 0 | empty | — | — |
| Holzbuchstaben (`holzbuchstaben.ch`) | Wix | wix | search / catalog_reader | 2 | selected | Modern \| Apricot Orange | — |
| Northbound Coffee (`northboundcoffee.com`) | Ecwid | ecwid | search / storefront_api_v3 | 0 | empty | — | — |
| CakeSafe (`cakesafe.com`) | Ecwid | ecwid | search / storefront_api_v3 | 0 | empty | — | — |
| Wylie Beckert (`wyliebeckert.com`) | Ecwid | unknown | not_run / — | — | — | — | — |
| Dunlop Sports US (`us.dunlopsports.com`) | Salesforce Commerce Cloud | sfcc | search / search_show | 12 | selected | XXIO - XXIO 14+ Irons | — |
| Alcott (`www.alcott.eu`) | Salesforce Commerce Cloud | sfcc | search / search_show | 20 | selected | Borsa a spalla a mezzaluna | — |
| HUGO BOSS (`hugoboss.com`) | Salesforce Commerce Cloud | sfcc | search / search_show | 11 | selected | — | — |

## Detection mismatches

- `wyliebeckert.com`: expected `ecwid`, observed kind `unknown` / platform `None`; search `not_run`.

The JSONL is the authoritative per-request evidence. Empty results mean only that the fixed query returned zero candidates at observation time. Tool errors and terminal outcomes were not retried with another query.
