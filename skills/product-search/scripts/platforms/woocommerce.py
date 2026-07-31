from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
from platform_api_core import (
    Detection,
    Http,
    ToolError,
    bot_wall,
    gated,
    item_ref,
    json_list,
    json_object,
    minor_money,
    parse_item_ref,
    quote_outcome,
    search_result,
    shipping_option,
    unsupported_configuration,
    wall_system,
)

API_PATH = "/wp-json/wc/store/v1"
ADDRESS = {
    "first_name": "Jordan",
    "last_name": "Smith",
    "company": "Pacific Prototyping LLC",
    "address_1": "747 Howard St",
    "address_2": "",
    "city": "San Francisco",
    "state": "CA",
    "postcode": "94103",
    "country": "US",
    "phone": "4155550132",
}


def detect(http: Http, origin: str, entry_url: str) -> Detection | None:
    response = http.request("GET", origin + API_PATH + "/cart")
    if response.status_code != 200:
        return None
    try:
        payload = response.json()
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("totals"), dict):
        return None
    return Detection(
        "detected",
        origin,
        entry_url,
        "woocommerce",
        origin,
        ("WooCommerce Store API cart object with totals",),
    )


def search(http: Http, detection: Detection, query: str) -> dict[str, object]:
    base = _api_base(detection)
    response = http.request(
        "GET", f"{base}/products", params={"search": query, "per_page": "20"}
    )
    terminal = _terminal_response("search", response)
    if terminal is not None:
        return terminal
    products = json_list(response, "WooCommerce product search")
    return search_result(
        "woocommerce", query, [_product_item(product) for product in products]
    )


def quote(http: Http, detection: Detection, reference: str) -> dict[str, object]:
    selected = parse_item_ref(reference, "woocommerce")
    product_id = selected.get("product_id")
    product_type = selected.get("product_type")
    if (
        not isinstance(product_id, int)
        or product_id <= 0
        or not isinstance(product_type, str)
    ):
        raise ToolError("WooCommerce item_ref has no valid product identity")
    if product_type not in {"simple", "variation"}:
        return unsupported_configuration(
            "woocommerce", ["variation"], "Product requires an exact variation"
        )
    quantity = selected.get("minimum")
    if not isinstance(quantity, int) or quantity <= 0:
        raise ToolError("WooCommerce item_ref has no positive integer minimum quantity")

    base = _api_base(detection)
    cart_response = http.request("GET", f"{base}/cart")
    terminal = _terminal_response("quote", cart_response)
    if terminal is not None:
        return terminal
    cart = json_object(cart_response, "WooCommerce cart")
    _cart_totals(cart, "WooCommerce cart")
    token = cart_response.headers.get("Cart-Token")
    if not token:
        raise ToolError("WooCommerce cart response has no Cart-Token")
    headers = {"Cart-Token": token}

    add_response = http.request(
        "POST",
        f"{base}/cart/add-item",
        headers=headers,
        json={"id": product_id, "quantity": quantity},
    )
    terminal = _terminal_response("quote", add_response)
    if terminal is not None:
        return terminal
    added_cart = json_object(add_response, "WooCommerce add item")
    item_key = _selected_item_key(added_cart, product_id)

    update_response = http.request(
        "POST",
        f"{base}/cart/update-customer",
        headers=headers,
        json={"shipping_address": ADDRESS},
    )
    terminal = _terminal_response("quote", update_response)
    if terminal is not None:
        return terminal
    updated_cart = json_object(update_response, "WooCommerce customer update")
    subtotal, totals = _cart_totals(updated_cart, "WooCommerce customer update")
    options = _shipping_options(updated_cart, subtotal["currency"])

    cleanup_response = http.request(
        "DELETE", f"{base}/cart/items/{item_key}", headers=headers
    )
    return quote_outcome(
        "woocommerce",
        options,
        subtotal,
        cart_totals=totals,
        cleanup_status=cleanup_response.status_code,
    )


def _api_base(detection: Detection) -> str:
    if detection.platform != "woocommerce" or detection.api_origin is None:
        raise ToolError(
            "WooCommerce adapter requires a detected WooCommerce API origin"
        )
    return detection.api_origin + API_PATH


def _terminal_response(
    operation: str, response: httpx.Response
) -> dict[str, object] | None:
    system = wall_system(response)
    if system is not None:
        return bot_wall(operation, "woocommerce", response, system)
    if response.status_code in {401, 403}:
        return gated(
            operation,
            "woocommerce",
            str(response.url),
            response,
            "WooCommerce Store API authorization required",
        )
    if response.status_code >= 400:
        raise ToolError(f"WooCommerce {operation} returned HTTP {response.status_code}")
    return None


def _product_item(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ToolError("WooCommerce product must be an object")
    product_id, name, product_type = (
        value.get("id"),
        value.get("name"),
        value.get("type"),
    )
    if (
        not isinstance(product_id, int)
        or product_id <= 0
        or not isinstance(name, str)
        or not isinstance(product_type, str)
    ):
        raise ToolError("WooCommerce product has invalid identity fields")
    prices = value.get("prices")
    if not isinstance(prices, dict):
        raise ToolError("WooCommerce product has no prices object")
    add_to_cart = value.get("add_to_cart")
    if not isinstance(add_to_cart, dict):
        raise ToolError("WooCommerce product has no add_to_cart object")
    minimum = add_to_cart.get("minimum")
    if not isinstance(minimum, int) or minimum <= 0:
        raise ToolError(
            "WooCommerce product minimum quantity must be a positive integer"
        )
    return {
        "name": name,
        "sku": value.get("sku"),
        "type": product_type,
        "available": value.get("is_in_stock"),
        "purchasable": value.get("is_purchasable"),
        "price": minor_money(
            prices.get("price"),
            prices.get("currency_code"),
            prices.get("currency_minor_unit"),
        ),
        "product_url": value.get("permalink"),
        "requires_configuration": product_type not in {"simple", "variation"},
        "item_ref": item_ref(
            "woocommerce",
            {
                "product_id": product_id,
                "product_type": product_type,
                "minimum": minimum,
            },
        ),
    }


def _selected_item_key(cart: dict[str, Any], product_id: int) -> str:
    items = cart.get("items")
    if not isinstance(items, list):
        raise ToolError("WooCommerce add-item response has no items array")
    matches = [
        item
        for item in items
        if isinstance(item, dict) and item.get("id") == product_id
    ]
    if (
        len(matches) != 1
        or not isinstance(matches[0].get("key"), str)
        or not matches[0]["key"]
    ):
        raise ToolError(
            "WooCommerce add-item response does not contain the exact selected product"
        )
    return matches[0]["key"]


def _cart_totals(
    cart: dict[str, Any], context: str
) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    totals = cart.get("totals")
    if not isinstance(totals, dict):
        raise ToolError(f"{context} has no totals object")
    currency, digits = totals.get("currency_code"), totals.get("currency_minor_unit")
    normalized: dict[str, dict[str, str]] = {}
    for name in (
        "total_items",
        "total_items_tax",
        "total_discount",
        "total_discount_tax",
        "total_shipping",
        "total_shipping_tax",
        "total_price",
        "total_tax",
    ):
        if totals.get(name) is not None:
            normalized[name] = minor_money(totals[name], currency, digits)
    if "total_items" not in normalized:
        raise ToolError(f"{context} totals has no total_items")
    return normalized["total_items"], normalized


def _shipping_options(
    cart: dict[str, Any], expected_currency: str
) -> list[dict[str, Any]]:
    packages = cart.get("shipping_rates")
    if not isinstance(packages, list):
        raise ToolError("WooCommerce cart has no shipping_rates array")
    options: list[dict[str, Any]] = []
    for package in packages:
        if not isinstance(package, dict) or not isinstance(
            package.get("shipping_rates"), list
        ):
            raise ToolError("WooCommerce shipping package has no shipping_rates array")
        for rate in package["shipping_rates"]:
            options.append(_shipping_option(rate, expected_currency))
    return options


def _shipping_option(rate: Any, expected_currency: str) -> dict[str, Any]:
    if not isinstance(rate, dict):
        raise ToolError("WooCommerce shipping rate must be an object")
    rate_id, name = rate.get("rate_id"), rate.get("name")
    if (
        not isinstance(rate_id, str)
        or not rate_id
        or not isinstance(name, str)
        or not name
    ):
        raise ToolError("WooCommerce shipping rate has invalid identity fields")
    currency, digits = rate.get("currency_code"), rate.get("currency_minor_unit")
    if currency != expected_currency:
        raise ToolError("WooCommerce shipping rate currency differs from cart currency")
    amount = minor_money(rate.get("price"), currency, digits)
    tax_value = minor_money(rate.get("taxes"), currency, digits)
    tax = Decimal(tax_value["amount"])
    disposition = (
        "fallback"
        if rate_id.endswith("_fallback")
        else "pickup"
        if rate_id.startswith("local_pickup")
        else "delivery"
    )
    return shipping_option(
        rate_id,
        name,
        disposition,
        amount,
        selected=rate.get("selected"),
        tax={"amount": format(tax, "f"), "currency": currency},
    )
