from __future__ import annotations

import json
import re
from decimal import Decimal
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote as url_quote
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from platform_api_core import (
    Detection,
    Http,
    ToolError,
    bot_wall,
    canonical_url,
    gated,
    item_ref,
    json_list,
    json_object,
    money,
    parse_item_ref,
    quote_outcome,
    search_result,
    shipping_option,
    url_origin,
    wall_system,
)

SEARCH_QUERY = """\
query ProductSearch($search: String!) {
  products(search: $search, pageSize: 10) {
    total_count
    items { __typename name sku stock_status url_key }
  }
}
"""

DETAIL_QUERY = """\
query ProductDetail($sku: String!) {
  storeConfig { base_url product_url_suffix base_currency_code }
  products(filter: {sku: {eq: $sku}}, pageSize: 1) {
    items {
      __typename name sku stock_status url_key
      price_range {
        minimum_price {
          final_price { value currency }
          regular_price { value currency }
        }
      }
      ... on ConfigurableProduct {
        variants {
          attributes { code label value_index }
          product {
            __typename name sku stock_status
            price_range {
              minimum_price {
                final_price { value currency }
                regular_price { value currency }
              }
            }
          }
        }
      }
    }
  }
}
"""

DUMMY_SF = {
    "firstname": "Jordan",
    "lastname": "Smith",
    "company": "Pacific Prototyping LLC",
    "street": ["747 Howard St"],
    "city": "San Francisco",
    "region": "California",
    "region_code": "CA",
    "region_id": 12,
    "postcode": "94103",
    "country_id": "US",
    "telephone": "4155550132",
}

MAX_SEARCH_RESULTS = 10

DETECT_QUERY = "query PlatformProbe { storeConfig { base_url } }"


class ProductLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        values = dict(attrs)
        classes = (values.get("class") or "").split()
        href = values.get("href")
        if href and ({"product-item-link", "product-item-photo"} & set(classes)):
            self.links.append(href)


class ProductPage(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.json_ld: list[str] = []
        self.form_sku: str | None = None
        self.itemprop_sku: str | None = None
        self.price: str | None = None
        self.currency: str | None = None
        self.available: bool | None = None
        self.required_fields: list[str] = []
        self.title: str | None = None
        self._json: list[str] | None = None
        self._in_product_form = False
        self._sku_tag: str | None = None
        self._sku_text: list[str] | None = None
        self._title: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if (
            tag == "script"
            and (values.get("type") or "").lower() == "application/ld+json"
        ):
            self._json = []
        if tag == "title":
            self._title = []
        if tag == "form" and values.get("id") == "product_addtocart_form":
            self._in_product_form = True
            self.form_sku = values.get("data-product-sku")
        if self._in_product_form and tag in {"input", "select", "textarea"}:
            name = values.get("name") or ""
            input_type = (values.get("type") or "text").lower()
            required = "required" in values or name.startswith(
                ("super_attribute[", "options[")
            )
            if name and input_type != "hidden" and required:
                self.required_fields.append(name)
        itemprop = (values.get("itemprop") or "").lower()
        content = values.get("content")
        if itemprop == "sku" and content:
            self.itemprop_sku = content
        if itemprop == "sku" and content is None:
            self._sku_tag = tag
            self._sku_text = []
        if itemprop == "price" and content:
            self.price = content
        if itemprop == "pricecurrency" and content:
            self.currency = content
        availability = (values.get("property") or "").lower()
        if availability == "product:availability" and content:
            self.available = "in stock" in content.lower() or content.lower().endswith(
                "instock"
            )
        classes = set((values.get("class") or "").lower().split())
        if "stock" in classes and "available" in classes:
            self.available = True
        if "stock" in classes and "unavailable" in classes:
            self.available = False

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._json is not None:
            self.json_ld.append("".join(self._json))
            self._json = None
        if tag == "title" and self._title is not None:
            self.title = " ".join("".join(self._title).split()) or None
            self._title = None
        if tag == self._sku_tag and self._sku_text is not None:
            self.itemprop_sku = " ".join("".join(self._sku_text).split()) or None
            self._sku_tag = None
            self._sku_text = None
        if tag == "form" and self._in_product_form:
            self._in_product_form = False

    def handle_data(self, data: str) -> None:
        if self._json is not None:
            self._json.append(data)
        if self._title is not None:
            self._title.append(data)
        if self._sku_text is not None:
            self._sku_text.append(data)


def detect(
    http: Http,
    origin: str,
    entry_url: str,
    homepage: httpx.Response,
) -> Detection | None:
    markers = _homepage_markers(homepage)
    guest = http.request(
        "POST",
        origin + "/rest/V1/guest-carts",
        headers={"Content-Type": "application/json"},
        content=b"{}",
    )
    try:
        guest_value = guest.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        guest_value = None
    if (
        guest.is_success
        and isinstance(guest_value, str)
        and 16 <= len(guest_value) <= 128
    ):
        return Detection(
            "detected",
            origin,
            entry_url,
            "magento",
            origin,
            ("magento_guest_cart_token",),
        )
    if (
        isinstance(guest_value, dict)
        and isinstance(guest_value.get("message"), str)
        and ("parameters" in guest_value or "trace" in guest_value)
    ):
        return Detection(
            "detected",
            origin,
            entry_url,
            "magento",
            origin,
            ("magento_guest_cart_error",),
        )

    graphql = http.request(
        "POST",
        origin + "/graphql",
        headers={"Content-Type": "application/json"},
        json={"query": DETECT_QUERY, "variables": {}},
    )
    try:
        graphql_value = graphql.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        graphql_value = None
    if graphql.status_code == 200 and isinstance(graphql_value, dict):
        data = graphql_value.get("data")
        config = data.get("storeConfig") if isinstance(data, dict) else None
        if isinstance(config, dict) and isinstance(config.get("base_url"), str):
            return Detection(
                "detected",
                origin,
                entry_url,
                "magento",
                origin,
                ("magento_graphql_store_config",),
            )
    if markers:
        return Detection(
            "detected",
            origin,
            entry_url,
            "magento",
            origin,
            tuple(markers),
        )
    return None


def _homepage_markers(homepage: httpx.Response) -> list[str]:
    source = homepage.text[:2_000_000].lower()
    markers = []
    if re.search(r"/static/(?:version\d+/)?frontend/", source):
        markers.append("magento_static_asset")
    if "x-magento-init" in source:
        markers.append("magento_x_magento_init")
    if "mage-cache-" in source:
        markers.append("magento_mage_cache")
    if "private_content_version" in source:
        markers.append("magento_private_content_version")
    if any(name.lower().startswith("x-magento-") for name in homepage.headers):
        markers.append("magento_response_header")
    return markers


def search(http: Http, detection: Detection, query: str) -> dict[str, object]:
    origin = _magento_origin(detection)
    response = http.request(
        "POST",
        origin + "/graphql",
        headers={"Content-Type": "application/json"},
        json={"query": SEARCH_QUERY, "variables": {"search": query}},
    )
    if response.status_code in {401, 403, 404}:
        return _html_search(
            http,
            detection,
            query,
            [{"stage": "search", "status": response.status_code}],
        )
    if response.status_code != 200:
        raise ToolError(f"Magento GraphQL search returned HTTP {response.status_code}")

    envelope = json_object(response, "Magento GraphQL search")
    errors = _graphql_errors(envelope, "search")
    products = _products(envelope)
    if products is None:
        if errors:
            return _html_search(http, detection, query, errors)
        raise ToolError("Magento GraphQL search has no products data")
    candidates = products.get("items")
    if not isinstance(candidates, list):
        raise ToolError("Magento GraphQL search items must be an array")
    if not candidates:
        return search_result("magento", query, [], source="graphql", api_errors=errors)

    items: list[dict[str, Any]] = []
    omitted = 0
    for candidate in candidates[:MAX_SEARCH_RESULTS]:
        if not isinstance(candidate, dict) or not isinstance(candidate.get("sku"), str):
            raise ToolError("Magento GraphQL search candidate has no SKU")
        detail, detail_errors = _graphql_detail(http, origin, candidate["sku"])
        errors.extend(detail_errors)
        if detail is None:
            continue
        concrete, unsupported = _detail_items(detail, origin, candidate["sku"])
        items.extend(concrete)
        omitted += unsupported
    if not items and errors:
        return _html_search(http, detection, query, errors)
    return search_result(
        "magento",
        query,
        _unique_skus(items),
        source="graphql",
        api_errors=errors,
        configurable_products_omitted=omitted,
    )


def quote(http: Http, detection: Detection, reference: str) -> dict[str, object]:
    origin = _magento_origin(detection)
    selected = parse_item_ref(reference, "magento")
    if (
        set(selected) != {"sku"}
        or not isinstance(selected["sku"], str)
        or not selected["sku"]
    ):
        raise ToolError("Magento item_ref must contain exactly one nonempty simple SKU")
    sku = selected["sku"]
    if any(character in sku for character in "\r\n"):
        raise ToolError("Magento item_ref SKU cannot contain a newline")

    create = http.request(
        "POST",
        origin + "/rest/V1/guest-carts",
        headers={"Content-Type": "application/json"},
        content=b"{}",
    )
    denied = _denied("quote", "/rest/V1/guest-carts", create, "guest cart API refused")
    if denied:
        return denied
    if create.status_code not in {200, 201}:
        raise ToolError(f"Magento guest cart returned HTTP {create.status_code}")
    try:
        token = create.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ToolError("Magento guest cart did not return JSON") from error
    if not isinstance(token, str) or not 16 <= len(token) <= 128:
        raise ToolError("Magento guest cart did not return a masked-ID string")
    cart_path = "/rest/V1/guest-carts/" + quote_path(token)

    add = http.request(
        "POST",
        origin + cart_path + "/items",
        headers={"Content-Type": "application/json"},
        json={"cartItem": {"sku": sku, "qty": 1, "quote_id": token}},
    )
    denied = _denied(
        "quote",
        "/rest/V1/guest-carts/[redacted]/items",
        add,
        "guest cart item API refused",
    )
    if denied:
        return denied
    if add.status_code not in {200, 201}:
        raise ToolError(
            f"Magento rejected selected simple SKU with HTTP {add.status_code}"
        )
    added = json_object(add, "Magento add item")
    if added.get("sku") != sku:
        raise ToolError("Magento add item did not return the selected SKU")

    totals_response = http.request("GET", origin + cart_path + "/totals")
    denied = _denied(
        "quote",
        "/rest/V1/guest-carts/[redacted]/totals",
        totals_response,
        "guest cart totals API refused",
    )
    if denied:
        return denied
    if totals_response.status_code != 200:
        raise ToolError(
            f"Magento guest cart totals returned HTTP {totals_response.status_code}"
        )
    totals = json_object(totals_response, "Magento guest cart totals")
    quote_currency = totals.get("quote_currency_code")
    base_currency = totals.get("base_currency_code")
    subtotal_value = totals.get("subtotal")
    base_subtotal_value = totals.get("base_subtotal")
    if (
        not isinstance(quote_currency, str)
        or not quote_currency
        or not isinstance(base_currency, str)
        or not base_currency
        or subtotal_value is None
    ):
        raise ToolError("Magento guest cart totals has no subtotal and currency codes")
    subtotal = money(subtotal_value, quote_currency)

    rates_response = http.request(
        "POST",
        origin + cart_path + "/estimate-shipping-methods",
        headers={"Content-Type": "application/json"},
        json={"address": DUMMY_SF},
    )
    denied = _denied(
        "quote",
        "/rest/V1/guest-carts/[redacted]/estimate-shipping-methods",
        rates_response,
        "shipping estimate API refused",
    )
    if denied:
        return denied
    if rates_response.status_code != 200:
        raise ToolError(
            f"Magento shipping estimate returned HTTP {rates_response.status_code}"
        )
    raw_rates = json_list(rates_response, "Magento shipping estimate")
    options = [_rate_option(rate, quote_currency, base_currency) for rate in raw_rates]
    return quote_outcome(
        "magento",
        options,
        subtotal,
        no_quote_reason="empty_rate_list"
        if not raw_rates
        else "no_comparable_delivery_rate",
        item={"sku": sku, "title": added.get("name"), "quantity": added.get("qty", 1)},
        base_subtotal=money(base_subtotal_value, base_currency)
        if base_subtotal_value is not None
        else None,
        subtotal_incl_tax=(
            money(totals["subtotal_incl_tax"], quote_currency)
            if totals.get("subtotal_incl_tax") is not None
            else None
        ),
    )


def quote_path(value: str) -> str:
    return url_quote(value, safe="")


def _magento_origin(detection: Detection) -> str:
    if (
        detection.kind != "detected"
        or detection.platform != "magento"
        or detection.api_origin is None
    ):
        raise ToolError("Magento adapter requires a positive Magento detection")
    return detection.api_origin


def _graphql_detail(
    http: Http,
    origin: str,
    sku: str,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    response = http.request(
        "POST",
        origin + "/graphql",
        headers={"Content-Type": "application/json"},
        json={"query": DETAIL_QUERY, "variables": {"sku": sku}},
    )
    if response.status_code in {401, 403, 404}:
        return None, [{"stage": "detail", "sku": sku, "status": response.status_code}]
    if response.status_code != 200:
        raise ToolError(f"Magento GraphQL detail returned HTTP {response.status_code}")
    envelope = json_object(response, "Magento GraphQL detail")
    errors = _graphql_errors(envelope, "detail", sku)
    if _products(envelope) is None:
        if errors:
            return None, errors
        raise ToolError("Magento GraphQL detail has no products data")
    return envelope, errors


def _graphql_errors(
    envelope: dict[str, Any], stage: str, sku: str | None = None
) -> list[dict[str, Any]]:
    errors = envelope.get("errors", [])
    if not isinstance(errors, list):
        raise ToolError("Magento GraphQL errors must be an array")
    normalized = []
    for error in errors[:20]:
        if not isinstance(error, dict):
            raise ToolError("Magento GraphQL error must be an object")
        normalized.append(
            {
                "stage": stage,
                "message": str(error.get("message", "GraphQL error"))[:240],
                "path": error.get("path"),
                **({"sku": sku} if sku else {}),
            }
        )
    return normalized


def _products(envelope: dict[str, Any]) -> dict[str, Any] | None:
    data = envelope.get("data")
    if not isinstance(data, dict):
        return None
    products = data.get("products")
    return products if isinstance(products, dict) else None


def _detail_items(
    envelope: dict[str, Any],
    origin: str,
    selected_sku: str,
) -> tuple[list[dict[str, Any]], int]:
    products = _products(envelope)
    rows = products.get("items") if products else None
    if not isinstance(rows, list):
        raise ToolError("Magento GraphQL detail items must be an array")
    matches = [
        row for row in rows if isinstance(row, dict) and row.get("sku") == selected_sku
    ]
    if len(matches) != 1:
        raise ToolError("Magento exact parent SKU did not resolve exactly once")
    parent = matches[0]
    data = envelope.get("data")
    config = (
        data.get("storeConfig")
        if isinstance(data, dict) and isinstance(data.get("storeConfig"), dict)
        else {}
    )
    base_url = (
        config.get("base_url")
        if isinstance(config.get("base_url"), str)
        else origin + "/"
    )
    suffix = (
        config.get("product_url_suffix")
        if isinstance(config.get("product_url_suffix"), str)
        else ""
    )
    product_url = canonical_url(
        urljoin(base_url, str(parent.get("url_key") or "") + suffix)
    )
    if parent.get("__typename") == "SimpleProduct":
        return [_graphql_item(parent, parent, product_url, [])], 0
    variants = parent.get("variants")
    if parent.get("__typename") != "ConfigurableProduct" or not isinstance(
        variants, list
    ):
        return [], 1
    items = []
    for variant in variants:
        if not isinstance(variant, dict) or not isinstance(
            variant.get("product"), dict
        ):
            raise ToolError("Magento configurable variant has an unexpected shape")
        child = variant["product"]
        if child.get("__typename") != "SimpleProduct":
            continue
        attributes = (
            variant.get("attributes")
            if isinstance(variant.get("attributes"), list)
            else []
        )
        items.append(_graphql_item(child, parent, product_url, attributes))
    return items, int(not items)


def _graphql_item(
    product: dict[str, Any],
    parent: dict[str, Any],
    product_url: str,
    attributes: list[Any],
) -> dict[str, Any]:
    sku = product.get("sku")
    if not isinstance(sku, str) or not sku:
        raise ToolError("Magento product has no simple SKU")
    final, regular = _prices(product)
    labels = [
        str(value.get("label"))
        for value in attributes
        if isinstance(value, dict) and value.get("label")
    ]
    return {
        "item_ref": item_ref("magento", {"sku": sku}),
        "title": parent.get("name") or product.get("name"),
        "variant": ", ".join(labels)
        or (product.get("name") if product is not parent else None),
        "sku": sku,
        "barcode": None,
        "available": product.get("stock_status") == "IN_STOCK",
        "price": final,
        "compare_at_price": regular if regular != final else None,
        "weight": None,
        "url": product_url,
        "options": [
            {
                "code": value.get("code"),
                "label": value.get("label"),
                "value": value.get("value_index"),
            }
            for value in attributes
            if isinstance(value, dict)
        ],
    }


def _prices(
    product: dict[str, Any],
) -> tuple[dict[str, str] | None, dict[str, str] | None]:
    price_range = product.get("price_range")
    minimum = (
        price_range.get("minimum_price") if isinstance(price_range, dict) else None
    )
    final = minimum.get("final_price") if isinstance(minimum, dict) else None
    regular = minimum.get("regular_price") if isinstance(minimum, dict) else None
    return _price(final), _price(regular)


def _price(value: Any) -> dict[str, str] | None:
    if (
        not isinstance(value, dict)
        or value.get("value") is None
        or value.get("currency") is None
    ):
        return None
    return money(value["value"], value["currency"])


def _html_search(
    http: Http,
    detection: Detection,
    query: str,
    graphql_errors: list[dict[str, Any]],
) -> dict[str, object]:
    search_url = urljoin(detection.entry_url, "catalogsearch/result/")
    response = http.request("GET", search_url, params={"q": query})
    denied = _denied(
        "search",
        "/catalogsearch/result/",
        response,
        "public Magento HTML search refused",
    )
    if denied:
        return denied
    if response.status_code != 200:
        raise ToolError(f"Magento HTML search returned HTTP {response.status_code}")
    parser = ProductLinks()
    parser.feed(response.text)
    links = []
    for href in parser.links:
        candidate = _canonical_product_url(urljoin(str(response.url), href))
        if candidate is None:
            continue
        if url_origin(candidate) == detection.origin and candidate not in links:
            links.append(candidate)
        if len(links) == MAX_SEARCH_RESULTS:
            break

    items: list[dict[str, Any]] = []
    omitted = 0
    for product_url in links:
        product = http.request("GET", product_url)
        if product.status_code == 404:
            continue
        denied = _denied(
            "search", product_url, product, "public Magento product page refused"
        )
        if denied:
            return denied
        if product.status_code != 200:
            raise ToolError(f"Magento product page returned HTTP {product.status_code}")
        page = ProductPage()
        page.feed(product.text)
        page_items, configured = _page_items(page, product_url)
        items.extend(page_items)
        omitted += int(configured and not page_items)
    return search_result(
        "magento",
        query,
        _unique_skus(items),
        source="html",
        api_errors=graphql_errors,
        configurable_products_omitted=omitted,
    )


def _page_items(
    page: ProductPage, product_url: str
) -> tuple[list[dict[str, Any]], bool]:
    items: list[dict[str, Any]] = []
    parent_skus: set[str] = set()
    for raw in page.json_ld:
        try:
            document = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for node in _walk_json(document):
            if not isinstance(node, dict):
                continue
            schema_type = _schema_type(node.get("@type"))
            if schema_type == "productgroup" and isinstance(
                node.get("hasVariant"), list
            ):
                parent = node.get("name")
                parent_sku = node.get("productGroupID")
                if isinstance(parent_sku, str):
                    parent_skus.add(parent_sku)
                for child in node["hasVariant"]:
                    if isinstance(child, dict):
                        normalized = _json_ld_item(child, parent, product_url)
                        if normalized:
                            items.append(normalized)
            if schema_type == "product":
                normalized = _json_ld_item(node, None, product_url)
                if normalized:
                    items.append(normalized)
    configured = bool(page.required_fields)
    items = [
        item
        for item in _unique_skus(items)
        if not (configured and item["sku"] in parent_skus)
    ]
    if items:
        return items, configured
    if page.form_sku and page.itemprop_sku and page.form_sku != page.itemprop_sku:
        raise ToolError("Magento product page form and visible SKU disagree")
    sku = page.form_sku or page.itemprop_sku
    if not sku or configured:
        return [], configured
    price = (
        money(page.price, page.currency)
        if page.price is not None and page.currency is not None
        else None
    )
    return [
        {
            "item_ref": item_ref("magento", {"sku": sku}),
            "title": page.title,
            "variant": None,
            "sku": sku,
            "barcode": None,
            "available": page.available,
            "price": price,
            "compare_at_price": None,
            "weight": None,
            "url": product_url,
            "options": [],
        }
    ], False


def _json_ld_item(
    product: dict[str, Any], parent_name: Any, product_url: str
) -> dict[str, Any] | None:
    sku = product.get("sku")
    if not isinstance(sku, str) or not sku:
        return None
    offers = product.get("offers")
    offer = (
        offers
        if isinstance(offers, dict)
        else offers[0]
        if isinstance(offers, list) and len(offers) == 1
        else {}
    )
    price = None
    if (
        isinstance(offer, dict)
        and offer.get("price") is not None
        and offer.get("priceCurrency") is not None
    ):
        price = money(offer["price"], offer["priceCurrency"])
    availability = offer.get("availability") if isinstance(offer, dict) else None
    available = (
        str(availability).lower().rstrip("/").endswith("instock")
        if availability is not None
        else None
    )
    barcode = next(
        (
            product[name]
            for name in ("gtin14", "gtin13", "gtin12", "gtin", "mpn")
            if product.get(name)
        ),
        None,
    )
    return {
        "item_ref": item_ref("magento", {"sku": sku}),
        "title": parent_name or product.get("name"),
        "variant": product.get("name") if parent_name else None,
        "sku": sku,
        "barcode": barcode,
        "available": available,
        "price": price,
        "compare_at_price": None,
        "weight": None,
        "url": product_url,
        "options": [],
    }


def _schema_type(value: Any) -> str:
    candidate = value[0] if isinstance(value, list) and value else value
    return str(candidate).lower().rstrip("/").rsplit("/", 1)[-1]


def _walk_json(value: Any):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _unique_skus(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique = {}
    for product in items:
        sku = product.get("sku")
        if not isinstance(sku, str):
            raise ToolError("Magento normalized product has no SKU")
        unique.setdefault(sku, product)
    return list(unique.values())


def _canonical_product_url(value: str) -> str | None:
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname:
        return None
    return canonical_url(
        urlunsplit((parts.scheme, parts.netloc, parts.path or "/", "", ""))
    )


def _denied(
    operation: str,
    endpoint: str,
    response: Any,
    reason: str,
) -> dict[str, Any] | None:
    if response.status_code not in {401, 403, 404, 405}:
        return None
    system = wall_system(response)
    if system:
        return bot_wall(operation, "magento", response, system)
    return gated(operation, "magento", endpoint, response, reason)


def _rate_option(rate: Any, quote_currency: str, base_currency: str) -> dict[str, Any]:
    if not isinstance(rate, dict):
        raise ToolError("Magento shipping rate must be an object")
    carrier = rate.get("carrier_code")
    method = rate.get("method_code")
    if (
        not isinstance(carrier, str)
        or not carrier
        or not isinstance(method, str)
        or not method
    ):
        raise ToolError("Magento shipping rate has no carrier and method codes")
    option_id = f"{carrier}/{method}"
    title = (
        " — ".join(
            str(value)
            for value in (rate.get("carrier_title"), rate.get("method_title"))
            if value
        )
        or option_id
    )
    label = f"{option_id} {title}".lower()
    error = str(rate["error_message"]) if rate.get("error_message") else None
    available = rate.get("available") is not False
    amount_value = (
        rate.get("price_incl_tax")
        if rate.get("price_incl_tax") is not None
        else rate.get("amount")
    )
    amount = money(amount_value, quote_currency) if amount_value is not None else None
    zero_amount = amount is not None and Decimal(amount["amount"]) == 0
    if not available or error:
        disposition = "unavailable"
    elif any(
        marker in label
        for marker in (
            "pickup",
            "pick up",
            "click and collect",
            "collect in store",
            "instore",
        )
    ):
        disposition = "pickup"
    elif (
        "paid later" in label
        or "quote later" in label
        or ("freight" in label and zero_amount)
    ):
        disposition = "paid_later"
    elif "fallback" in label:
        disposition = "fallback"
    else:
        disposition = "delivery"
    return shipping_option(
        option_id,
        title,
        disposition,
        amount,
        carrier_code=carrier,
        method_code=method,
        available=available,
        error=error,
        base_amount=money(rate["base_amount"], base_currency)
        if rate.get("base_amount") is not None
        else None,
        price_excl_tax=money(rate["price_excl_tax"], quote_currency)
        if rate.get("price_excl_tax") is not None
        else None,
        price_incl_tax=money(rate["price_incl_tax"], quote_currency)
        if rate.get("price_incl_tax") is not None
        else None,
    )
