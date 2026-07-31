from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from urllib.parse import quote, urlencode

from .commerce_common import AdapterError, RequestPlan, minor_money, quote_result


SF_ADDRESS = {
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


def cart_request(origin: str) -> RequestPlan:
    return RequestPlan("GET", _endpoint(origin, "cart"), {}, None)


def products_request(origin: str, query: str) -> RequestPlan:
    params = urlencode({"search": query, "per_page": 100})
    return RequestPlan("GET", f"{_endpoint(origin, 'products')}?{params}", {}, None)


def product_request(origin: str, product_id: int) -> RequestPlan:
    params = urlencode({"include": product_id})
    return RequestPlan("GET", f"{_endpoint(origin, 'products')}?{params}", {}, None)


def cart_token(response_headers: dict[str, str]) -> str:
    values = [value for name, value in response_headers.items() if name.lower() == "cart-token"]
    if len(values) != 1 or not values[0]:
        raise AdapterError("WooCommerce cart response must contain one Cart-Token")
    return values[0]


def add_item_request(origin: str, product_id: int, quantity: int | float, token: str) -> RequestPlan:
    return _mutation(origin, "cart/add-item", token, {"id": product_id, "quantity": quantity})


def update_customer_request(origin: str, token: str) -> RequestPlan:
    return _mutation(origin, "cart/update-customer", token, {"shipping_address": SF_ADDRESS})


def cleanup_request(origin: str, item_key: str, token: str) -> RequestPlan:
    return RequestPlan(
        "DELETE",
        _endpoint(origin, f"cart/items/{quote(item_key, safe='')}"),
        {"Cart-Token": token},
        None,
    )


def parse_products(body: bytes) -> dict[str, Any]:
    products = _json(body, list, "WooCommerce products")
    items: list[dict[str, Any]] = []
    omitted = 0
    for product in products:
        if not isinstance(product, dict) or not isinstance(product.get("id"), int):
            raise AdapterError("WooCommerce product must be an object with integer ID")
        if product.get("type") not in {"simple", "variation"}:
            omitted += 1
            continue
        prices = _dict(product, "prices")
        items.append({
            "quote_ref": str(product["id"]),
            "title": product.get("name"),
            "variant": None,
            "sku": product.get("sku"),
            "available": product.get("is_purchasable") is True and product.get("is_in_stock") is True,
            "price": minor_money(prices.get("price"), prices.get("currency_code"), prices.get("currency_minor_unit")),
            "url": product.get("permalink"),
        })
    return {"platform": "woocommerce", "products": items, "configurable_products_omitted": omitted}


def selected_product(body: bytes, expected_id: int) -> dict[str, Any]:
    products = _json(body, list, "WooCommerce selected product")
    matching = [product for product in products if isinstance(product, dict) and product.get("id") == expected_id]
    if len(products) != 1 or len(matching) != 1:
        raise AdapterError("WooCommerce exact product lookup did not return exactly the selected product")
    product = matching[0]
    if product.get("id") != expected_id or product.get("type") not in {"simple", "variation"}:
        raise AdapterError("WooCommerce quote_ref is not an exact simple or variation product")
    if product.get("is_purchasable") is not True or product.get("is_in_stock") is not True:
        raise AdapterError("WooCommerce selected product is not purchasable and in stock")
    add_to_cart = _dict(product, "add_to_cart")
    minimum = add_to_cart.get("minimum")
    if not isinstance(minimum, (int, float)) or minimum <= 0:
        raise AdapterError("WooCommerce product minimum quantity is invalid")
    return {"id": expected_id, "quantity": minimum}


def added_item_key(body: bytes, expected_id: int) -> str:
    cart = _json(body, dict, "WooCommerce add-item")
    items = cart.get("items")
    if not isinstance(items, list):
        raise AdapterError("WooCommerce add-item response has no items array")
    matching = [item for item in items if isinstance(item, dict) and item.get("id") == expected_id]
    if len(matching) != 1 or not isinstance(matching[0].get("key"), str):
        raise AdapterError("WooCommerce add-item did not return exactly the selected item")
    return matching[0]["key"]


def parse_cart_rates(body: bytes) -> dict[str, Any]:
    cart = _json(body, dict, "WooCommerce cart rates")
    packages, totals = cart.get("shipping_rates"), cart.get("totals")
    if not isinstance(packages, list) or not isinstance(totals, dict):
        raise AdapterError("WooCommerce cart rates require shipping_rates and totals")
    subtotal = minor_money(
        totals.get("total_items"), totals.get("currency_code"), totals.get("currency_minor_unit")
    )
    cart_tax = minor_money(
        totals.get("total_tax"), totals.get("currency_code"), totals.get("currency_minor_unit")
    )
    options: list[dict[str, Any]] = []
    for package in packages:
        if not isinstance(package, dict) or not isinstance(package.get("shipping_rates"), list):
            raise AdapterError("WooCommerce shipping package has invalid shape")
        for rate in package["shipping_rates"]:
            if not isinstance(rate, dict):
                raise AdapterError("WooCommerce shipping rate must be an object")
            rate_id, title, method_id = rate.get("rate_id"), rate.get("name"), rate.get("method_id")
            if not all(isinstance(value, str) for value in (rate_id, title, method_id)):
                raise AdapterError("WooCommerce shipping rate requires rate_id, name, and method_id")
            net = minor_money(rate.get("price"), rate.get("currency_code"), rate.get("currency_minor_unit"))
            tax = minor_money(rate.get("taxes"), rate.get("currency_code"), rate.get("currency_minor_unit"))
            gross = _add_money(net, tax)
            disposition = (
                "fallback" if rate_id.endswith("_fallback")
                else "pickup" if method_id == "local_pickup"
                else "delivery"
            )
            options.append({
                "id": rate_id,
                "title": title,
                "disposition": disposition,
                "amount": gross,
                "tax": tax,
                "selected": rate.get("selected") is True,
                "evidence": {
                    "method_id": method_id,
                    "amount_excluding_tax": net,
                    "delivery_time": rate.get("delivery_time"),
                },
            })
    result = quote_result("woocommerce", options, subtotal, no_quote_reason="empty_rate_list")
    result["tax"] = cart_tax
    return result


def _mutation(origin: str, path: str, token: str, value: dict[str, Any]) -> RequestPlan:
    if not token:
        raise AdapterError("WooCommerce cart mutation requires Cart-Token")
    return RequestPlan(
        "POST",
        _endpoint(origin, path),
        {"Cart-Token": token, "Content-Type": "application/json"},
        json.dumps(value, separators=(",", ":")).encode(),
    )


def _endpoint(origin: str, path: str) -> str:
    return f"{origin.rstrip('/')}/wp-json/wc/store/v1/{path}"


def _add_money(left: dict[str, str], right: dict[str, str]) -> dict[str, str]:
    if left["currency"] != right["currency"]:
        raise AdapterError("WooCommerce rate price and tax currencies differ")
    total = Decimal(left["amount"]) + Decimal(right["amount"])
    decimals = max(len(left["amount"].partition(".")[2]), len(right["amount"].partition(".")[2]))
    return {"amount": f"{total:.{decimals}f}", "currency": left["currency"]}


def _json(body: bytes, expected: type, context: str) -> Any:
    try:
        value = json.loads(body)
    except Exception as error:
        raise AdapterError(f"{context} did not return JSON") from error
    if not isinstance(value, expected):
        raise AdapterError(f"{context} returned {type(value).__name__}, expected {expected.__name__}")
    return value


def _dict(value: dict[str, Any], name: str) -> dict[str, Any]:
    result = value.get(name)
    if not isinstance(result, dict):
        raise AdapterError(f"WooCommerce {name} must be an object")
    return result
