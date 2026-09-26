# AliExpress private APIs for search and product info — 2026-09-25

Sources: my own curl probes, a headless-browser test, and two independent web-research passes (Opus and GPT Sol). All from this Mac's IP on 2026-09-25.

## Summary

| Need | Endpoint | Works without a browser? |
|---|---|---|
| Keyword search | Search page HTML (`/w/wholesale-<slug>.html`), parse embedded `_init_data_` JSON | Yes, at low rate. Blocked by captcha after a few requests, recovers later |
| Product detail (SKUs, per-SKU price, stock, shipping, seller, rating) | mtop `mtop.aliexpress.pdp.pc.query` | Protocol yes, anti-bot no. Signed plain-HTTP calls get `RGV587_ERROR` captcha, often on the first call |
| Reviews | `feedback.aliexpress.com/pc/searchEvaluation.do` | Yes (per Scrapfly and fetchaller code; untested here) |
| Mobile app API | `x-sign` / `wua` headers | No: needs Alibaba's native SecurityGuard library |
| Legacy (`glosearch/api/product`, `aeglodetailweb/api`, old freight routes) | — | No evidence they work after 2020 |

robots.txt (`User-agent: *`) does not disallow `/w/` or `/item/`.

## 1. Search: search page HTML

```
GET https://www.aliexpress.com/w/wholesale-<slug>.html?SearchText=<q>&page=N&SortType=price_asc
Cookie: aep_usuc_f=site=glo&c_tp=USD&region=US&b_locale=en_US
```

- The `aep_usuc_f` cookie sets currency and ship-to country. The `.us` host also works; a cookieless first request redirects through `login.aliexpress.com/sync_cookie_read.htm`, so keep a cookie jar.
- Parse `window._dida_config_._init_data_= { data: {...} }`. Items are at `data.root.fields.mods.itemList.content` (60 per page), and the total is at `pageInfo.totalResults`.
- Each item has `productId`, `title.displayTitle`, `prices.salePrice.{cent,currencyCode}`, `prices.originalPrice`, `image.imgUrl`, `evaluation.starRating`, `trade.tradeDesc` ("100K+ sold"), and a delivery-ETA tag in `sellingPoints`.
- Other sort values: `total_tranpro_desc`, `price_desc`, `create_desc`. Price-range filter: `pr=min-max`; other filters go in `selectedSwitches` (e.g. `filterCode:freeshipping`).
- **Blocking:** when blocked, the response is HTTP 200 with a `_____tmd_____/punish?x5secdata=…` slider page. The status code doesn't show the block; check for missing `_init_data_`.
  - My first request worked. After one `/fn/search-pc/index` POST, every page request from this IP was blocked, including the headless browser's first load. It was working again roughly 5 minutes later (Pi's test).
- The JSON endpoint `POST /fn/search-pc/index` (needs the `pageVersion` scraped from the page) is not needed, since `page=N` on the GET paginates. It is the fastest way to get the IP blocked.

## 2. Product detail: mtop H5 gateway

```
GET https://acs.aliexpress.com/h5/mtop.aliexpress.pdp.pc.query/1.0/
  ?jsv=2.5.1&appKey=12574478&t=<ms>&sign=<md5>&api=mtop.aliexpress.pdp.pc.query
  &v=1.0&type=originaljson&dataType=json&timeout=5000
  &data={"productId":"…","_lang":"en_US","_currency":"USD","country":"US","clientType":"pc"}
```

- **Token:** an unsigned call answers `FAIL_SYS_TOKEN_EMPTY` and sets the `_m_h5_tk` and `_m_h5_tk_enc` cookies. The token is the part of `_m_h5_tk` before the first `_`.
- **Signing:** `sign = md5(token&t&12574478&data)`.
- **Response modules:**
  - `PRODUCT_TITLE`
  - `PRICE.skuIdStrPriceInfoMap` (per-SKU prices)
  - `SKU.skuProperties`
  - `QUANTITY_PC.totalAvailableInventory`
  - `SHIPPING.originalLayoutResultList[*].bizData` (fee, delivery days, ETA; country-level, not a ZIP-level quote)
  - `SHOP_CARD_PC`, `HEADER_IMAGE_PC`, `PC_RATING`, `PRODUCT_PROP_PC`
- **Fallback APIs:** `mtop.aliexpress.itemdetail.pc.asyncPCDetail` and `mtop.aliexpress.itemdetail.msite`.
- **Status:** blocked for plain HTTP since about 2026-08-08.
  - Pi reproduced it: a correctly signed call returned `FAIL_SYS_USER_VALIDATE / RGV587_ERROR` with a captcha URL.
  - In our headless browser, the product page itself loaded, but its own `pdp.pc.query` call was also captcha'd because this IP was flagged.
  - SMCodesP/aliexpress-mcp says "Product detail is gated on executed JavaScript rather than TLS fingerprint". Its fix is a Playwright page load of `/item/<id>.html` that captures the `pdp.pc.query` response.
  - [wafer-py](https://pypi.org/project/wafer-py/) solves the captcha in a browser, then reuses the resulting `x5sec` cookie over plain HTTP.

## What triggers blocks

- **Traffic volume matters most.** youseiushida/aliexpress tested and ruled out user agent, header order, TLS fingerprint and HTTP version. It says "Pacing is therefore the whole game, and probing the block makes it worse."
- **Blocks cover the whole IP**, and heavy probing can extend them to hours.
- **Pacing other clients use:**
  - Warm up once with a search-page GET, then reuse the cookie jar.
  - Wait at least 1 s between searches and at least 3 s between detail calls.
  - Stop immediately on a punish response.

## Official alternatives

- **Affiliate API** (`aliexpress.affiliate.product.query`, `productdetail.get`): app key and secret, approval takes about 2 days. It covers search and summary detail, but not shipping. cross-shop's current AliExpress adapter uses it.
- **Dropshipping API** (`aliexpress.ds.product.get`, `aliexpress.ds.freight.query`): needs dropshipper approval and OAuth. It has full per-SKU data plus per-country shipping cost and ETA. It is the only stable route to shipping quotes.

## Reference implementations (2026)

- [SMCodesP/aliexpress-mcp](https://github.com/SMCodesP/aliexpress-mcp): Python, search page plus mtop detail with a Playwright fallback, and a module parser.
- [youseiushida/aliexpress](https://github.com/youseiushida/aliexpress): Deno; detailed notes on what triggers blocks.
- [navotvolkgroundup/alibadge](https://github.com/navotvolkgroundup/alibadge): browser extension; image search via `/fn/search-pc/index`.
- [Averyy/fetchaller-mcp](https://github.com/Averyy/fetchaller-mcp): uses wafer-py.
- [scrapfly-scrapers aliexpress](https://github.com/scrapfly/scrapfly-scrapers/tree/main/aliexpress-scraper): search, product and reviews.

## Fit for cross-shop

1. **Search:** replacing the Affiliate API with search-page parsing drops the key requirement and returns the same lead-grade fields. It will fail loudly on captcha pages, which fits cross-shop's error model.
2. **Product detail:** the cleanest option is a browser-swarm page load that captures `pdp.pc.query`. Otherwise apply for the Dropshipping API.
