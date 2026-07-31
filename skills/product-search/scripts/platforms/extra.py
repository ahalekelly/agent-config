from __future__ import annotations

import html
import json
import re
import uuid
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote as url_quote, urljoin, urlsplit, urlunsplit

from platform_api_core import Detection, Http, ToolError, api_error, classify_http, item_ref, money, option, origin, parse_ref, quote_result


WIX_ECOM_APP = "1380b703-ce81-ff05-f115-39571d94dfcd"
SQUARESPACE_ADDRESS = {
    "line1": "747 Howard St",
    "line2": "Pacific Prototyping LLC",
    "city": "San Francisco",
    "region": "CA",
    "postalCode": "94103",
    "country": "US",
}


class Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str | None]] = []
        self.navigation_links: list[str] = []
        self.current: str | None = None
        self.in_navigation = False
        self.form_action: str | None = None
        self.form_has_query = False
        self.search_forms: list[str] = []
        self.product_depth = 0
        self.product: dict[str, str | None] | None = None
        self.products: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "nav" and values.get("data-content-field") == "navigation":
            self.in_navigation = True
        if tag == "a" and values.get("href"):
            self.current = values["href"]
            self.links.append((values["href"], None))
            if self.in_navigation:
                self.navigation_links.append(values["href"])
        if tag == "form":
            self.form_action = values.get("action")
            self.form_has_query = False
        input_name = values.get("name")
        if tag == "input" and self.form_action and isinstance(input_name, str) and input_name.casefold() == "q":
            self.form_has_query = True
        if tag == "div" and self.product:
            self.product_depth += 1
        elif tag == "div" and values.get("data-pid"):
            self.product = {"pid": values["data-pid"], "href": None, "title": None}
            self.products.append(self.product)
            self.product_depth = 1
        if tag == "a" and self.product and values.get("href") and self.product["href"] is None:
            self.product["href"] = values["href"]
        if tag == "img" and self.product and values.get("alt") and self.product["title"] is None:
            self.product["title"] = values["alt"].strip()

    def handle_data(self, data: str) -> None:
        if self.current and data.strip():
            self.links[-1] = (self.links[-1][0], data.strip())

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self.current = None
        if tag == "nav":
            self.in_navigation = False
        if tag == "form":
            if self.form_action and self.form_has_query:
                self.search_forms.append(self.form_action)
            self.form_action = None
            self.form_has_query = False
        if tag == "div" and self.product:
            self.product_depth -= 1
            if self.product_depth == 0:
                self.product = None


def products(http: Http, detection: Detection, query: str) -> dict[str, Any]:
    if detection.platform == "squarespace":
        return squarespace_products(http, detection, query)
    if detection.platform == "wix":
        return wix_products(http, detection, query)
    if detection.platform == "ecwid":
        return ecwid_products(http, detection, query)
    if detection.platform == "sfcc":
        return sfcc_products(http, detection, query)
    raise AssertionError(detection.platform)


def quote(http: Http, detection: Detection, reference: str) -> dict[str, Any]:
    if detection.platform == "squarespace":
        return squarespace_quote(http, detection, reference)
    if detection.platform in {"wix", "ecwid", "sfcc"}:
        return quote_result(
            "unsupported",
            detection.platform,
            reason="a generic destination-specific public quote workflow was not proven",
            stage="quote",
        )
    raise AssertionError(detection.platform)


def squarespace_products(http: Http, detection: Detection, query: str) -> dict[str, Any]:
    http.client.cookies.clear()
    homepage = http.request("GET", detection.origin + "/", follow_redirects=True)
    if homepage.status_code != 200:
        return classify_http("squarespace", "homepage", homepage)
    links = Links()
    links.feed(homepage.text)
    collections: list[str] = []
    canonical = urlsplit(detection.origin)
    for href in links.navigation_links:
        url = urljoin(str(homepage.url), html.unescape(href))
        parts = urlsplit(url)
        if parts.scheme == "https" and parts.netloc.casefold() == canonical.netloc.casefold() and parts.path not in {"", "/"}:
            collection = urlunsplit((canonical.scheme, canonical.netloc, parts.path.rstrip("/"), "", ""))
            if collection not in collections:
                collections.append(collection)
    collections.sort(key=lambda value: not any(word in value.lower() for word in ("shop", "store", "product")))
    if not collections:
        return api_error("squarespace", "products", "no same-origin navigation collection links")
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for collection in collections:
        response = http.request("GET", collection, params={"format": "json"})
        if response.status_code != 200 or "json" not in response.headers.get("content-type", ""):
            continue
        payload = http.json_object(response, "Squarespace collection")
        website = payload.get("website")
        valid_collection = (
            isinstance(website, dict)
            and isinstance(website.get("id"), str)
            and bool(website["id"])
            and isinstance(payload.get("items"), list)
        )
        if not valid_collection:
            continue
        for product in payload["items"]:
            if not isinstance(product, dict) or not isinstance(product.get("variants"), list):
                continue
            product_id, title = product.get("id"), product.get("title")
            if not isinstance(product_id, str) or not isinstance(title, str):
                raise ToolError("Squarespace product identity changed")
            for variant in product["variants"]:
                if not isinstance(variant, dict) or not isinstance(variant.get("sku"), str):
                    raise ToolError("Squarespace variant identity changed")
                searchable = f"{title} {variant['sku']} {json.dumps(variant.get('attributes', {}))}".casefold()
                if query.casefold() not in searchable:
                    continue
                raw_price = variant.get("salePriceMoney") if variant.get("onSale") is True else variant.get("priceMoney")
                if not isinstance(raw_price, dict):
                    raise ToolError("Squarespace variant price changed")
                key = (product_id, variant["sku"])
                found[key] = {
                    "item_ref": item_ref("squarespace", {"collection": collection, "item_id": product_id, "sku": variant["sku"]}),
                    "title": title,
                    "variant": variant.get("attributes") or None,
                    "sku": variant["sku"],
                    "available": variant.get("unlimited") is True or int(variant.get("qtyInStock", 0)) > 0,
                    "price": money(raw_price.get("value"), raw_price.get("currency")),
                    "url": urljoin(detection.origin + "/", str(product.get("fullUrl", ""))),
                }
    return {
        "platform": "squarespace",
        "query": query,
        "collection_candidates_scanned": len(collections),
        "items": list(found.values()),
    }


def squarespace_quote(http: Http, detection: Detection, reference: str) -> dict[str, Any]:
    value = parse_ref("squarespace", reference)
    collection, item_id, sku = (value.get(name) for name in ("collection", "item_id", "sku"))
    if not all(isinstance(item, str) and item for item in (collection, item_id, sku)) or origin(collection) != detection.origin:
        raise ToolError("Squarespace item_ref has invalid product identity")
    http.client.cookies.clear()
    page = http.request("GET", collection, params={"format": "json"})
    if page.status_code != 200:
        return classify_http("squarespace", "collection", page)
    crumbs = {cookie.value for cookie in http.client.cookies.jar if cookie.name == "crumb"}
    if len(crumbs) != 1:
        return quote_result("gated", "squarespace", reason="collection did not issue one crumb", stage="cart")
    headers = {"X-CSRF-Token": crumbs.pop(), "Add-To-Cart-Id": str(uuid.uuid4())}
    added = http.request(
        "POST",
        detection.origin + "/api/commerce/shopping-cart/entries",
        headers=headers,
        json={"itemId": item_id, "sku": sku, "quantity": 1, "additionalFields": None},
    )
    if added.status_code != 200:
        return classify_http("squarespace", "cart", added)
    cart_payload = http.json_object(added, "Squarespace cart")
    if cart_payload.get("error") or cart_payload.get("crumbFail") is True:
        return api_error("squarespace", "cart", "cart rejected CSRF or product input")
    cart = cart_payload.get("shoppingCart")
    if not isinstance(cart, dict) or not isinstance(cart.get("cartToken"), str):
        return api_error("squarespace", "cart", "cartToken missing")
    quoted = http.request(
        "PUT",
        detection.origin + f"/api/3/commerce/cart/{url_quote(cart['cartToken'], safe='')}/shipping/location",
        headers=headers,
        json=SQUARESPACE_ADDRESS,
    )
    if quoted.status_code != 200:
        return classify_http("squarespace", "shipping", quoted)
    payload = http.json_object(quoted, "Squarespace shipping")
    status = payload.get("shippingOptionsStatus")
    if status == "SHIPPING_NOT_REQUIRED":
        return quote_result("no_quote", "squarespace", reason="shipping_not_required")
    if status == "POSTAL_CODE_NOT_APPLICABLE":
        return quote_result("no_quote", "squarespace", reason="postal_code_not_applicable")
    if status != "APPLICABLE_SHIPPING_OPTIONS":
        return api_error("squarespace", "shipping", f"unknown shippingOptionsStatus {status!r}")
    raw_options = payload.get("fulfillmentOptions")
    if not isinstance(raw_options, list):
        return api_error("squarespace", "shipping", "fulfillmentOptions missing")
    unique: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for raw in raw_options:
        if not isinstance(raw, dict) or not isinstance(raw.get("price"), dict):
            return api_error("squarespace", "shipping", "fulfillment option shape changed")
        price = money(raw["price"].get("decimalValue"), raw["price"].get("currencyCode"))
        disposition = "pickup" if raw.get("isPickup") is True else "delivery"
        item = option(str(raw.get("key")), raw.get("name"), disposition, price, selected=raw.get("key") == payload.get("selectedFulfillmentOptionKey"))
        unique[(item["id"], item["title"], price["amount"], disposition)] = item
    options = list(unique.values())
    subtotal = payload.get("subtotal")
    normalized_subtotal = money(subtotal["decimalValue"], subtotal.get("currencyCode")) if isinstance(subtotal, dict) else None
    outcome = "quoted" if any(item["disposition"] == "delivery" for item in options) else "no_quote"
    reason = None if outcome == "quoted" else "no_comparable_delivery_rate" if options else "empty_rate_list"
    return quote_result(outcome, "squarespace", options, subtotal=normalized_subtotal, reason=reason)


def wix_products(http: Http, detection: Detection, query: str) -> dict[str, Any]:
    homepage = http.request("GET", detection.origin + "/", follow_redirects=True)
    if homepage.status_code != 200:
        return classify_http("wix", "homepage", homepage)
    match = re.search(r'"accessTokensUrl"\s*:\s*("(?:\\.|[^"\\])*")', homepage.text)
    if match is None:
        return api_error("wix", "products", "access-tokens URL missing")
    token_url = json.loads(match.group(1))
    if not isinstance(token_url, str):
        raise ToolError("Wix accessTokensUrl must be a string")
    canonical = urlsplit(detection.origin)
    parts = urlsplit(token_url)
    valid_token_url = (
        parts.scheme == "https"
        and parts.netloc.casefold() == canonical.netloc.casefold()
        and parts.path == "/_api/v1/access-tokens"
        and not parts.query
        and not parts.fragment
    )
    if not valid_token_url:
        return api_error("wix", "products", "access-tokens URL invalid")
    tokens = http.request("GET", token_url)
    if tokens.status_code != 200:
        return classify_http("wix", "access-tokens", tokens)
    payload = http.json_object(tokens, "Wix access tokens")
    apps = payload.get("apps")
    app = apps.get(WIX_ECOM_APP) if isinstance(apps, dict) else None
    token = app.get("accessToken") if isinstance(app, dict) else None
    if not isinstance(token, str):
        return api_error("wix", "access-tokens", "e-commerce app token missing")
    response = http.request(
        "POST",
        detection.origin + "/_api/catalog-reader-server/api/v1/products/query",
        headers={"Authorization": token},
        json={"query": {"filter": json.dumps({"name": {"$contains": query}}), "paging": {"limit": 20, "offset": 0}}, "includeVariants": True},
    )
    if response.status_code != 200:
        return classify_http("wix", "products", response)
    data = http.json_object(response, "Wix products")
    raw_products = data.get("products")
    if not isinstance(raw_products, list):
        return api_error("wix", "products", "products array missing")
    items = []
    for product in raw_products:
        if not isinstance(product, dict) or not isinstance(product.get("id"), str):
            return api_error("wix", "products", "product identity changed")
        price = product.get("priceData")
        stock = product.get("stock")
        items.append({
            "item_ref": item_ref("wix", {"product_id": product["id"]}),
            "title": product.get("name"),
            "sku": product.get("sku"),
            "available": isinstance(stock, dict) and stock.get("inStock") is True,
            "price": money(price.get("discountedPrice", price.get("price")), price.get("currency")) if isinstance(price, dict) else None,
            "url": urljoin(detection.origin + "/product-page/", str(product.get("slug", ""))),
        })
    return {"platform": "wix", "query": query, "items": items}


def ecwid_products(http: Http, detection: Detection, query: str) -> dict[str, Any]:
    homepage = http.request("GET", detection.origin + "/", follow_redirects=True)
    match = re.search(r"app\.ecwid\.com(?::443)?/script\.js\?(\d+)", homepage.text)
    if match is None:
        return api_error("ecwid", "products", "store ID missing")
    store_id = match.group(1)
    script = http.request("GET", f"https://app.ecwid.com/script.js?{store_id}")
    api_match = re.search(r'"apiBaseUrl":"([^"]+)"', script.text)
    if api_match is None:
        return api_error("ecwid", "products", "apiBaseUrl missing")
    initial = http.request("POST", f"{api_match.group(1)}/{store_id}/initial-data", json={"lang": "en"})
    if initial.status_code != 200:
        return classify_http("ecwid", "initial-data", initial)
    data = http.json_object(initial, "Ecwid initial-data")
    try:
        token = data["storeProfile"]["value"]["integrations"]["apps"]["publicTokens"]["ecwid-storefront"]
        currency = data["storeProfile"]["value"]["formats"]["currencyFormat"]["currencyCode"]
    except (KeyError, TypeError):
        return api_error("ecwid", "initial-data", "storefront token or currency missing")
    if not isinstance(token, str) or not token or not isinstance(currency, str) or not currency:
        return api_error("ecwid", "initial-data", "storefront token or currency invalid")
    response = http.request(
        "GET",
        f"https://app.ecwid.com/api/v3/{store_id}/products",
        params={"token": token, "keyword": query, "limit": 20},
    )
    if response.status_code != 200:
        return classify_http("ecwid", "products", response)
    payload = http.json_object(response, "Ecwid products")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return api_error("ecwid", "products", "items array missing")
    items = []
    for product in raw_items:
        if not isinstance(product, dict):
            return api_error("ecwid", "products", "product shape changed")
        if product.get("enabled") is not True:
            continue
        if not isinstance(product.get("id"), int) or not isinstance(product.get("name"), str):
            return api_error("ecwid", "products", "product identity changed")
        if not isinstance(product.get("inStock"), bool):
            return api_error("ecwid", "products", "product stock changed")
        items.append({
            "item_ref": item_ref("ecwid", {"store_id": store_id, "product_id": product["id"]}),
            "title": product.get("name"),
            "sku": product.get("sku"),
            "available": product["inStock"],
            "price": money(product.get("price"), currency),
            "url": product.get("url"),
        })
    return {"platform": "ecwid", "query": query, "items": items}


def sfcc_products(http: Http, detection: Detection, query: str) -> dict[str, Any]:
    homepage = http.request("GET", detection.origin + "/", follow_redirects=True)
    if homepage.status_code != 200:
        return classify_http("sfcc", "homepage", homepage)
    parser = Links()
    parser.feed(homepage.text)
    canonical = urlsplit(detection.origin)
    routes = []
    for action in parser.search_forms:
        parts = urlsplit(urljoin(str(homepage.url), html.unescape(action)))
        if parts.scheme == "https" and parts.netloc.casefold() == canonical.netloc.casefold():
            route = urlunsplit((canonical.scheme, canonical.netloc, parts.path or "/", "", ""))
            if route not in routes:
                routes.append(route)
    if len(routes) != 1:
        return api_error("sfcc", "products", "one same-origin search form is required")
    response = http.request("GET", routes[0], params={"q": query}, follow_redirects=True)
    if response.status_code != 200:
        return classify_http("sfcc", "products", response)
    if "/on/demandware." not in response.text and "data-pid=" not in response.text:
        return api_error("sfcc", "products", "search route did not return SFRA product markup")
    parser = Links()
    parser.feed(response.text)
    items = []
    seen: set[str] = set()
    for product in parser.products:
        pid = product["pid"]
        if not pid:
            raise ToolError("SFCC product identity changed")
        if pid in seen:
            continue
        seen.add(pid)
        items.append({
            "item_ref": item_ref("sfcc", {"pid": pid}),
            "title": product["title"],
            "sku": pid,
            "available": True,
            "price": None,
            "url": urljoin(str(response.url), product["href"]) if product["href"] else None,
        })
        if len(items) == 20:
            break
    return {"platform": "sfcc", "query": query, "items": items}
