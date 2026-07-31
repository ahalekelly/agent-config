from __future__ import annotations

import copy
import json
import re
from email import policy
from email.parser import BytesParser
from typing import Any

import httpx
import web_bot_auth

from .commerce_common import AdapterError, RequestPlan, decimal_money, quote_result


API_VERSION = "2026-07"
CART_GID = re.compile(r"gid://shopify/Cart/[^\s'\"<>{}\[\],]+")
DETECT_QUERY = "query DetectStore { shop { name } }"

PRODUCTS_QUERY = """query Products($query: String!) {
  products(first: 20, query: $query) {
    nodes { title handle onlineStoreUrl variants(first: 50) {
      nodes { id title sku barcode availableForSale price { amount currencyCode } }
    } }
  }
}"""
CART_CREATE_QUERY = """mutation CartCreate($input: CartInput!) {
  cartCreate(input: $input) {
    cart { id cost { subtotalAmount { amount currencyCode } } }
    userErrors { field code message }
  }
}"""
CART_RATES_QUERY = """query CartRates($id: ID!) {
  cart(id: $id) {
    id
    ... @defer {
      deliveryGroups(first: 10, withCarrierRates: true) {
        nodes { groupType deliveryOptions {
          handle title code description deliveryMethodType
          estimatedCost { amount currencyCode }
        } }
      }
    }
  }
}"""

SF_ADDRESS = {
    "firstName": "Jordan",
    "lastName": "Smith",
    "company": "Pacific Prototyping LLC",
    "address1": "747 Howard St",
    "city": "San Francisco",
    "province": "CA",
    "country": "US",
    "zip": "94103",
    "phone": "+14155550132",
}


def send(client: httpx.Client, request: httpx.Request) -> httpx.Response:
    return web_bot_auth.send_signed(client, request)


def detect_request(origin: str) -> RequestPlan:
    return _graphql_request(origin, DETECT_QUERY, {}, deferred=False)


def products_request(origin: str, query: str) -> RequestPlan:
    return _graphql_request(origin, PRODUCTS_QUERY, {"query": query}, deferred=False)


def cart_create_request(origin: str, variant_id: str) -> RequestPlan:
    if not variant_id.startswith("gid://shopify/ProductVariant/"):
        raise AdapterError("Shopify quote requires a ProductVariant GID")
    variables = {
        "input": {
            "lines": [{"merchandiseId": variant_id, "quantity": 1}],
            "buyerIdentity": {
                "countryCode": "US",
                "deliveryAddressPreferences": [{"deliveryAddress": SF_ADDRESS}],
            },
        }
    }
    return _graphql_request(origin, CART_CREATE_QUERY, variables, deferred=False)


def cart_rates_request(origin: str, cart_id: str) -> RequestPlan:
    return _graphql_request(origin, CART_RATES_QUERY, {"id": cart_id}, deferred=True)


def parse_products(body: bytes) -> dict[str, Any]:
    data = _graphql_json(body, "Shopify products")
    products = _object(data, "products").get("nodes")
    if not isinstance(products, list):
        raise AdapterError("Shopify products.nodes must be an array")
    items: list[dict[str, Any]] = []
    for product in products:
        if not isinstance(product, dict):
            raise AdapterError("Shopify product must be an object")
        variants = _object(product, "variants").get("nodes")
        if not isinstance(variants, list):
            raise AdapterError("Shopify variants.nodes must be an array")
        for variant in variants:
            if not isinstance(variant, dict) or not isinstance(variant.get("id"), str):
                raise AdapterError("Shopify variant must have an ID")
            price = _object(variant, "price")
            items.append({
                "quote_ref": variant["id"],
                "title": product.get("title"),
                "variant": variant.get("title"),
                "sku": variant.get("sku"),
                "barcode": variant.get("barcode"),
                "available": variant.get("availableForSale") is True,
                "price": decimal_money(price.get("amount"), price.get("currencyCode")),
                "url": product.get("onlineStoreUrl"),
            })
    return {"platform": "shopify", "products": items}


def parse_cart_create(body: bytes) -> dict[str, Any]:
    create = _object(_graphql_json(body, "Shopify cartCreate"), "cartCreate")
    errors = create.get("userErrors")
    if not isinstance(errors, list):
        raise AdapterError("Shopify cartCreate userErrors must be an array")
    if errors:
        raise AdapterError(f"Shopify rejected cartCreate: {_redact_cart_gids(repr(errors))}")
    cart = _object(create, "cart")
    cart_id = cart.get("id")
    if not isinstance(cart_id, str):
        raise AdapterError("Shopify cartCreate returned no cart ID")
    subtotal_node = _object(_object(cart, "cost"), "subtotalAmount")
    return {
        "cart_id": cart_id,
        "subtotal": decimal_money(subtotal_node.get("amount"), subtotal_node.get("currencyCode")),
    }


def parse_cart_rates(content_type: str, body: bytes, subtotal: dict[str, str]) -> dict[str, Any]:
    data = _parse_multipart(content_type, body)
    cart = data.get("cart")
    if not isinstance(cart, dict):
        raise AdapterError("Shopify cart rates returned no cart")
    delivery_groups = cart.get("deliveryGroups")
    if delivery_groups is None:
        return quote_result("shopify", [], subtotal, no_quote_reason="no_delivery_groups")
    groups = _object(cart, "deliveryGroups").get("nodes")
    if not isinstance(groups, list):
        raise AdapterError("Shopify deliveryGroups.nodes must be an array")
    options: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("deliveryOptions"), list):
            raise AdapterError("Shopify delivery group has invalid shape")
        for raw in group["deliveryOptions"]:
            if not isinstance(raw, dict):
                raise AdapterError("Shopify delivery option must be an object")
            option_id, title = raw.get("handle"), raw.get("title")
            if not isinstance(option_id, str) or not isinstance(title, str):
                raise AdapterError("Shopify delivery option requires handle and title")
            method = raw.get("deliveryMethodType")
            dispositions = {
                "SHIPPING": "delivery",
                "LOCAL": "delivery",
                "PICK_UP": "pickup",
                "PICKUP_POINT": "pickup",
                "RETAIL": "pickup",
                "NONE": "unavailable",
            }
            if method not in dispositions:
                raise AdapterError(f"Unknown Shopify delivery method {method!r}")
            estimate = _object(raw, "estimatedCost")
            options.append({
                "id": option_id,
                "title": title,
                "disposition": dispositions[method],
                "amount": decimal_money(estimate.get("amount"), estimate.get("currencyCode")),
                "evidence": {"delivery_method_type": method, "code": raw.get("code")},
            })
    return quote_result("shopify", options, subtotal, no_quote_reason="empty_rate_list")


def _graphql_request(
    origin: str,
    query: str,
    variables: dict[str, Any],
    *,
    deferred: bool,
) -> RequestPlan:
    url = f"{origin.rstrip('/')}/api/{API_VERSION}/graphql.json"
    headers = {"Content-Type": "application/json"}
    if deferred:
        headers["Accept"] = "multipart/mixed; deferSpec=20220824, application/json"
    body = json.dumps({"query": query, "variables": variables}, separators=(",", ":")).encode()
    return RequestPlan("POST", url, headers, body)


def _parse_multipart(content_type: str, body: bytes) -> dict[str, Any]:
    if not content_type.lower().startswith("multipart/mixed"):
        raise AdapterError(f"Shopify cart rates require multipart/mixed, got {content_type!r}")
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
    )
    if not message.is_multipart():
        raise AdapterError("Shopify response has no valid MIME boundary")
    merged: dict[str, Any] | None = None
    terminal = False
    for part in message.iter_parts():
        if part.get_content_type() != "application/json":
            raise AdapterError("Shopify multipart part must be application/json")
        try:
            document = json.loads(part.get_payload(decode=True))
        except Exception as error:
            raise AdapterError("Shopify multipart part is not JSON") from error
        if not isinstance(document, dict):
            raise AdapterError("Shopify multipart part must be an object")
        if document.get("errors"):
            raise AdapterError(f"Shopify GraphQL errors: {_redact_cart_gids(repr(document['errors']))}")
        if "data" in document:
            if merged is not None or not isinstance(document["data"], dict):
                raise AdapterError("Shopify multipart initial data is invalid or duplicated")
            merged = copy.deepcopy(document["data"])
        for increment in document.get("incremental", []):
            if merged is None or not isinstance(increment, dict):
                raise AdapterError("Shopify incremental result precedes initial data")
            _apply_increment(merged, increment)
        terminal = document.get("hasNext") is False
    if merged is None or not terminal:
        raise AdapterError("Shopify multipart response is incomplete")
    return merged


def _apply_increment(data: dict[str, Any], increment: dict[str, Any]) -> None:
    path, patch = increment.get("path"), increment.get("data")
    if not isinstance(path, list) or not isinstance(patch, dict):
        raise AdapterError("Shopify incremental result requires path and data")
    target: Any = data
    for component in path:
        if isinstance(component, str) and isinstance(target, dict) and component in target:
            target = target[component]
        elif isinstance(component, int) and isinstance(target, list) and 0 <= component < len(target):
            target = target[component]
        else:
            raise AdapterError(f"Shopify incremental path is impossible: {path!r}")
    if not isinstance(target, dict):
        raise AdapterError("Shopify incremental path must identify an object")
    _merge(target, patch)


def _merge(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for name, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(name), dict):
            _merge(target[name], value)
        else:
            target[name] = copy.deepcopy(value)


def _redact_cart_gids(value: str) -> str:
    return CART_GID.sub("gid://shopify/Cart/[redacted]", value)


def _graphql_json(body: bytes, context: str) -> dict[str, Any]:
    try:
        envelope = json.loads(body)
    except Exception as error:
        raise AdapterError(f"{context} did not return JSON") from error
    if not isinstance(envelope, dict) or envelope.get("errors"):
        raise AdapterError(f"{context} returned GraphQL errors or invalid envelope")
    return _object(envelope, "data")


def _object(value: dict[str, Any], name: str) -> dict[str, Any]:
    result = value.get(name)
    if not isinstance(result, dict):
        raise AdapterError(f"{name} must be an object")
    return result
