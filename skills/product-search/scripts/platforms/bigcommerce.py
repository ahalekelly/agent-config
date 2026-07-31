from __future__ import annotations

import json
from html import unescape
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit

from .catalog_common import api_error, denied, money, option_disposition, quote_result


Request = Callable[..., dict[str, Any]]

DUMMY_SF = {
    "firstName": "Jordan",
    "lastName": "Smith",
    "company": "Pacific Prototyping LLC",
    "address1": "747 Howard St",
    "address2": "",
    "city": "San Francisco",
    "stateOrProvince": "California",
    "stateOrProvinceCode": "CA",
    "countryCode": "US",
    "postalCode": "94103",
    "phone": "4155550132",
    "customFields": [],
    "shouldSaveAddress": False,
}


def products(request: Request, origin: str, query: str, detection_evidence: list[str]) -> dict[str, Any]:
    response = request("GET", origin + "/search.php", params={"search_query": query})
    if response["status"] in {401, 403}:
        return denied("bigcommerce", "products", "/search.php", response, detection_evidence)
    if response["status"] != 200:
        return api_error(
            "bigcommerce",
            "products",
            "search page request failed",
            [{"type": "http_status", "endpoint": "/search.php", "status": response["status"]}],
        )

    parser = SearchParser()
    parser.feed(response.get("text", ""))
    urls = _product_urls(origin, parser.links)
    items = []
    evidence = []
    for url in urls[:10]:
        page = request("GET", url)
        if page["status"] in {401, 403}:
            evidence.append(denied("bigcommerce", "product", url, page, detection_evidence))
            continue
        if page["status"] != 200:
            evidence.append({"type": "api_error", "endpoint": url, "http_status": page["status"]})
            continue
        try:
            product = _product(page.get("text", ""), url, parser.option_selections)
            _resolve_selection(request, origin, product)
            items.append(product)
        except ValueError as error:
            evidence.append({"type": "api_error", "endpoint": url, "message": str(error)})
    if not items and evidence:
        return api_error("bigcommerce", "products", "no product page produced public product data", evidence)
    return {
        "operation": "products",
        "platform": "bigcommerce",
        "query": query,
        "products": items,
        "evidence": evidence,
    }


def quote(request: Request, origin: str, selection: dict[str, Any], detection_evidence: list[str]) -> dict[str, Any]:
    product_id = selection.get("product_id")
    option_selections = selection.get("option_selections")
    expected_sku = selection.get("sku")
    if not isinstance(product_id, int) or not isinstance(option_selections, list):
        return api_error("bigcommerce", "quote", "quote requires product_id and option_selections", [])
    if selection.get("selection_required") is True:
        return {
            "status": "unsupported",
            "platform": "bigcommerce",
            "operation": "quote",
            "reason": selection.get("selection_reason") or "product requires a concrete public option selection",
        }
    if not isinstance(expected_sku, str) or not expected_sku:
        return api_error("bigcommerce", "quote", "quote requires the concrete SKU returned by products", [])
    unsupported = _validate_options(selection.get("options"), option_selections)
    if unsupported:
        return {
            "status": "unsupported",
            "platform": "bigcommerce",
            "operation": "quote",
            "reason": unsupported,
        }

    create = request(
        "POST",
        origin + "/api/storefront/carts",
        json={
            "lineItems": [
                {
                    "quantity": 1,
                    "productId": product_id,
                    "optionSelections": option_selections,
                }
            ]
        },
    )
    if create["status"] in {401, 403}:
        return denied("bigcommerce", "quote", "/api/storefront/carts", create, detection_evidence)
    cart = create.get("json")
    if create["status"] not in {200, 201} or not isinstance(cart, dict):
        return api_error(
            "bigcommerce",
            "quote",
            "Storefront cart creation failed",
            [{"type": "http_status", "endpoint": "/api/storefront/carts", "status": create["status"]}],
        )
    cookies = create.get("cookies", {})
    shop_session = cookies.get("SHOP_SESSION_TOKEN")
    csrf = cookies.get("SF-CSRF-TOKEN")
    cart_id = cart.get("id")
    item = _cart_item(cart, product_id)
    if not all(isinstance(value, str) and value for value in (shop_session, csrf, cart_id)) or item is None:
        return api_error(
            "bigcommerce",
            "quote",
            "Storefront cart omitted its session, CSRF token, cart ID, or selected physical item",
            [{"type": "response_shape", "endpoint": "/api/storefront/carts"}],
        )
    if item.get("sku") != expected_sku:
        return api_error(
            "bigcommerce",
            "quote",
            "Storefront cart resolved a different SKU than products",
            [{
                "type": "sku_mismatch",
                "endpoint": "/api/storefront/carts",
                "expected": expected_sku,
                "actual": item.get("sku"),
            }],
        )
    if item.get("isShippingRequired") is not True:
        return {
            "status": "unsupported",
            "platform": "bigcommerce",
            "operation": "quote",
            "reason": "selected item is not a physical shippable product",
        }

    consignment = request(
        "POST",
        origin + f"/api/storefront/checkouts/{cart_id}/consignments",
        params={"include": "consignments.availableShippingOptions"},
        headers={"Cookie": f"SHOP_SESSION_TOKEN={shop_session}", "X-SF-CSRF-TOKEN": csrf},
        json=[
            {
                "address": DUMMY_SF,
                "lineItems": [{"itemId": item["id"], "quantity": item.get("quantity", 1)}],
            }
        ],
    )
    if consignment["status"] in {401, 403}:
        return api_error(
            "bigcommerce",
            "quote",
            "checkout consignment rejected the anonymous cart session",
            [{
                "type": "session_failure",
                "endpoint": "/api/storefront/checkouts/[redacted]/consignments",
                "status": consignment["status"],
            }],
        )
    checkout = consignment.get("json")
    if consignment["status"] != 200 or not isinstance(checkout, dict):
        return api_error(
            "bigcommerce",
            "quote",
            "checkout consignment failed",
            [{"type": "http_status", "endpoint": "/api/storefront/checkouts/[redacted]/consignments", "status": consignment["status"]}],
        )
    raw_consignments = checkout.get("consignments")
    if not isinstance(raw_consignments, list):
        return api_error(
            "bigcommerce",
            "quote",
            "checkout omitted consignments",
            [{"type": "response_shape", "endpoint": "/api/storefront/checkouts/[redacted]/consignments"}],
        )

    currency = cart.get("currency", {}).get("code") if isinstance(cart.get("currency"), dict) else None
    options = []
    for raw_consignment in raw_consignments:
        raw_options = raw_consignment.get("availableShippingOptions") if isinstance(raw_consignment, dict) else None
        if not isinstance(raw_options, list):
            return api_error(
                "bigcommerce",
                "quote",
                "consignment omitted availableShippingOptions",
                [{"type": "response_shape", "endpoint": "/api/storefront/checkouts/[redacted]/consignments"}],
            )
        options.extend(_shipping_option(option, currency) for option in raw_options if isinstance(option, dict))
    normalized_item = {
        "product_id": item.get("productId"),
        "variant_id": item.get("variantId"),
        "sku": item.get("sku"),
        "title": item.get("name"),
        "quantity": item.get("quantity"),
        "price": money(item.get("salePrice"), currency),
        "physical": True,
    }
    return quote_result(
        "bigcommerce",
        options,
        item=normalized_item,
        subtotal=money(cart.get("baseAmount"), currency),
    )


class SearchParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.option_selections: dict[int, list[list[dict[str, int]]]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        values = dict(attrs)
        href = values.get("href")
        if href:
            concrete = _cart_selection(href)
            if concrete:
                product_id, selections = concrete
                self.option_selections.setdefault(product_id, []).append(selections)
        marker = " ".join(str(values.get(name, "")) for name in ("class", "data-card-type", "data-product-id"))
        if href and ("product" in marker.lower() or "card" in marker.lower() or "searchid=" in href.lower()):
            self.links.append(href)


class ProductParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.product_ids: list[int] = []
        self.title_parts: list[str] = []
        self.in_title = False
        self.cart_form = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "title":
            self.in_title = True
        if tag == "form":
            action = values.get("action", "") or ""
            self.cart_form = "data-cart-item-add" in values or "/cart.php" in action
        if tag == "input" and self.cart_form and values.get("name") == "product_id":
            try:
                self.product_ids.append(int(values.get("value", "")))
            except ValueError:
                pass

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        if tag == "form":
            self.cart_form = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)


def _product_urls(origin: str, links: list[str]) -> list[str]:
    urls = []
    host = urlsplit(origin).netloc
    for href in links:
        candidate = urljoin(origin + "/", unescape(href))
        parts = urlsplit(candidate)
        if parts.scheme != "https" or parts.netloc != host or parts.path.lower() in {"/", "/cart.php", "/search.php"}:
            continue
        clean = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
        if clean not in urls:
            urls.append(clean)
    return urls


def _product(
    text: str,
    url: str,
    search_selections: dict[int, list[list[dict[str, int]]]],
) -> dict[str, Any]:
    parser = ProductParser()
    parser.feed(text)
    product_ids = sorted(set(parser.product_ids))
    if len(product_ids) != 1:
        raise ValueError("product page did not contain exactly one cart product ID")
    context = _assigned_json(text, "var BCData =")
    attributes = context.get("product_attributes") if isinstance(context, dict) else None
    if not isinstance(attributes, dict):
        raise ValueError("product page has no BCData.product_attributes")
    product_id = product_ids[0]
    raw_options = _assigned_json(text, f"window.__bidsys_product_options__[{product_id}] =", required=False)
    options = [_option(option) for option in raw_options] if isinstance(raw_options, list) else []
    candidates = list(search_selections.get(product_id, []))
    selected_attributes = attributes.get("selected_attributes")
    if isinstance(selected_attributes, dict) and selected_attributes:
        candidates.append([
            {"optionId": int(option_id), "optionValue": value}
            for option_id, value in selected_attributes.items()
        ])
    concrete_selections = _concrete_selections(options, candidates)
    selection_required = any(option["required"] for option in options) and concrete_selections is None
    raw_price = attributes.get("price")
    raw_price = raw_price.get("with_tax") or raw_price.get("without_tax") if isinstance(raw_price, dict) else None
    weight = attributes.get("weight")
    return {
        "product_id": product_id,
        "url": url,
        "title": " ".join("".join(parser.title_parts).split()) or None,
        "sku": attributes.get("sku"),
        "barcode": attributes.get("gtin") or attributes.get("upc"),
        "mpn": attributes.get("mpn"),
        "available": attributes.get("instock") is True and attributes.get("purchasable") is True,
        "stock": attributes.get("available_to_sell", attributes.get("stock")),
        "price": money(raw_price.get("value"), raw_price.get("currency")) if isinstance(raw_price, dict) else None,
        "weight": {"value": str(weight.get("value")), "formatted": weight.get("formatted")} if isinstance(weight, dict) else None,
        "options": options,
        "option_selections": concrete_selections or [],
        "selection_required": selection_required,
        "selection_reason": "required options have no unique public concrete mapping" if selection_required else None,
    }


def _option(raw: dict[str, Any]) -> dict[str, Any]:
    values = raw.get("values") if isinstance(raw.get("values"), list) else []
    return {
        "option_id": raw.get("id"),
        "label": raw.get("display_name"),
        "type": raw.get("type"),
        "required": raw.get("required") is True,
        "values": [
            {
                "value": value.get("id"),
                "label": value.get("label"),
                "available": value.get("instock") is not False,
            }
            for value in values
            if isinstance(value, dict)
        ],
    }


def _resolve_selection(request: Request, origin: str, product: dict[str, Any]) -> None:
    selections = product["option_selections"]
    if not selections:
        return
    response = request(
        "POST",
        origin + f"/remote/v1/product-attributes/{product['product_id']}",
        data={
            "action": "add",
            "product_id": str(product["product_id"]),
            **{f"attribute[{item['optionId']}]": str(item["optionValue"]) for item in selections},
        },
    )
    envelope = response.get("json")
    attributes = envelope.get("data") if isinstance(envelope, dict) else None
    expected_attributes = {str(item["optionId"]): item["optionValue"] for item in selections}
    if (
        response["status"] != 200
        or not isinstance(attributes, dict)
        or attributes.get("selected_attributes") != expected_attributes
        or not isinstance(attributes.get("sku"), str)
        or not attributes["sku"]
    ):
        product["option_selections"] = []
        product["selection_required"] = True
        product["selection_reason"] = "public option mapping did not resolve to a concrete SKU"
        return

    raw_price = attributes.get("price")
    raw_price = (raw_price.get("with_tax") or raw_price.get("without_tax")) if isinstance(raw_price, dict) else None
    weight = attributes.get("weight")
    product.update(
        sku=attributes["sku"],
        barcode=attributes.get("gtin") or attributes.get("upc"),
        mpn=attributes.get("mpn"),
        available=attributes.get("instock") is True and attributes.get("purchasable") is True,
        stock=attributes.get("available_to_sell", attributes.get("stock")),
        price=money(raw_price.get("value"), raw_price.get("currency")) if isinstance(raw_price, dict) else None,
        weight={"value": str(weight.get("value")), "formatted": weight.get("formatted")} if isinstance(weight, dict) else None,
        selection_required=False,
        selection_reason=None,
    )


def _assigned_json(text: str, marker: str, *, required: bool = True) -> Any:
    start = text.find(marker)
    if start == -1:
        if required:
            raise ValueError(f"product page has no {marker.strip()}")
        return None
    start += len(marker)
    try:
        return json.JSONDecoder().raw_decode(text, start + len(text[start:]) - len(text[start:].lstrip()))[0]
    except json.JSONDecodeError as error:
        raise ValueError(f"{marker.strip()} is not JSON") from error


def _validate_options(options: Any, selections: list[Any]) -> str | None:
    if not isinstance(options, list):
        return "quote selection must preserve the product options returned by products"
    normalized_options = {
        option.get("option_id"): option
        for option in options
        if isinstance(option, dict) and isinstance(option.get("option_id"), int)
    }
    if len(normalized_options) != len(options):
        return "every product option requires an integer option ID"
    selected: dict[int, Any] = {}
    for selection in selections:
        if not isinstance(selection, dict) or not isinstance(selection.get("optionId"), int):
            return "every option selection requires integer optionId and an explicit optionValue"
        if "optionValue" not in selection:
            return "every option selection requires integer optionId and an explicit optionValue"
        option_id = selection["optionId"]
        if option_id in selected:
            return "every product option may be selected only once"
        selected[option_id] = selection["optionValue"]
    if not set(selected) <= set(normalized_options):
        return "option selection contains an option not returned by products"
    for option_id, value in selected.items():
        raw_values = normalized_options[option_id].get("values")
        if not isinstance(raw_values, list):
            return "option selection must use a public select/radio value returned by products"
        values = {
            item.get("value"): item
            for item in raw_values
            if isinstance(item, dict) and "value" in item
        }
        if value not in values:
            return "option selection must use a public select/radio value returned by products"
        if values[value].get("available") is not True:
            return "option selection is unavailable"
    missing = [option.get("label") for option in options if option.get("required") and option.get("option_id") not in selected]
    if missing:
        return "required options need explicit selections: " + ", ".join(str(value) for value in missing)
    return None


def _cart_selection(href: str) -> tuple[int, list[dict[str, int]]] | None:
    parts = urlsplit(unescape(href))
    if parts.path.lower() != "/cart.php":
        return None
    params = dict(parse_qsl(parts.query))
    if params.get("action") != "add" or not params.get("product_id", "").isdigit():
        return None
    selections = []
    for name, value in parse_qsl(parts.query):
        if not name.startswith("attribute[") or not name.endswith("]"):
            continue
        option_id = name.removeprefix("attribute[").removesuffix("]")
        if not option_id.isdigit() or not value.isdigit():
            return None
        selections.append({"optionId": int(option_id), "optionValue": int(value)})
    return int(params["product_id"]), selections


def _concrete_selections(
    options: list[dict[str, Any]],
    candidates: list[list[dict[str, int]]],
) -> list[dict[str, int]] | None:
    concrete = []
    for candidate in candidates:
        if _validate_options(options, candidate) is not None:
            continue
        normalized = sorted(candidate, key=lambda item: item["optionId"])
        if normalized not in concrete:
            concrete.append(normalized)
    return concrete[0] if len(concrete) == 1 else None


def _cart_item(cart: dict[str, Any], product_id: int) -> dict[str, Any] | None:
    line_items = cart.get("lineItems")
    physical = line_items.get("physicalItems") if isinstance(line_items, dict) else None
    if not isinstance(physical, list):
        return None
    matches = [item for item in physical if isinstance(item, dict) and item.get("productId") == product_id]
    return matches[0] if len(matches) == 1 else None


def _shipping_option(option: dict[str, Any], currency: str | None) -> dict[str, Any]:
    option_type = str(option.get("type", ""))
    description = str(option.get("description", ""))
    error = str(option["errorMessage"]) if option.get("errorMessage") else None
    available = option.get("available") is not False
    return {
        "id": str(option.get("id")),
        "type": option_type,
        "title": description or option_type,
        "additional_description": option.get("additionalDescription"),
        "transit_time": option.get("transitTime"),
        "disposition": option_disposition(option_type, description, available, error),
        "available": available,
        "error": error,
        "amount": money(option.get("cost"), currency),
        "discounted_amount": money(option.get("costAfterDiscount"), currency),
    }
