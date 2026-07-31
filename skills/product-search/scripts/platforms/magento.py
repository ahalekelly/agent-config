from __future__ import annotations

from typing import Any, Callable
from urllib.parse import quote as url_quote, urljoin

from .catalog_common import api_error, denied, money, option_disposition, quote_result


Request = Callable[..., dict[str, Any]]

SEARCH_QUERY = """
query ProductSearch($search: String!) {
  storeConfig { base_url product_url_suffix base_currency_code }
  products(search: $search, pageSize: 10) {
    items { __typename name sku stock_status url_key }
  }
}
"""

DETAIL_QUERY = """
query ProductDetail($sku: String!) {
  storeConfig { base_url product_url_suffix base_currency_code }
  products(filter: {sku: {eq: $sku}}, pageSize: 1) {
    items {
      __typename name sku stock_status url_key
      price_range { minimum_price { final_price { value currency } } }
      ... on ConfigurableProduct {
        variants {
          attributes { code label value_index }
          product {
            __typename name sku stock_status
            price_range { minimum_price { final_price { value currency } } }
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


def search(request: Request, origin: str, query: str, detection_evidence: list[str]) -> dict[str, Any]:
    response = request(
        "POST",
        origin + "/graphql",
        json={"query": SEARCH_QUERY, "variables": {"search": query}},
    )
    failure = _graphql_failure(response, "search", detection_evidence)
    if failure:
        return failure
    envelope = response["json"]
    errors = _graphql_errors(envelope, "search")
    products = envelope.get("data", {}).get("products")
    if not isinstance(products, dict) or not isinstance(products.get("items"), list):
        return api_error("magento", "search", "GraphQL products data is absent", errors)
    candidates = []
    for item in products["items"]:
        if not isinstance(item, dict) or not isinstance(item.get("sku"), str):
            continue
        candidates.append(
            {
                "parent_sku": item["sku"],
                "type": item.get("__typename"),
                "title": item.get("name"),
                "available": item.get("stock_status") == "IN_STOCK",
                "url_key": item.get("url_key"),
            }
        )
    return {
        "operation": "search",
        "platform": "magento",
        "query": query,
        "candidates": candidates,
        "evidence": errors,
    }


def product(request: Request, origin: str, parent_sku: str, detection_evidence: list[str]) -> dict[str, Any]:
    response = request(
        "POST",
        origin + "/graphql",
        json={"query": DETAIL_QUERY, "variables": {"sku": parent_sku}},
    )
    failure = _graphql_failure(response, "product", detection_evidence)
    if failure:
        return failure
    envelope = response["json"]
    errors = _graphql_errors(envelope, "product")
    data = envelope.get("data", {})
    products = data.get("products") if isinstance(data, dict) else None
    items = products.get("items") if isinstance(products, dict) else None
    if not isinstance(items, list):
        return api_error("magento", "product", "GraphQL product detail is absent", errors)
    matches = [item for item in items if isinstance(item, dict) and item.get("sku") == parent_sku]
    if len(matches) != 1:
        return api_error("magento", "product", "selected parent SKU did not resolve exactly once", errors)
    config = data.get("storeConfig") if isinstance(data.get("storeConfig"), dict) else {}
    parent = matches[0]
    concrete = _concrete_products(parent, config, origin)
    if not concrete:
        return {
            "status": "unsupported",
            "platform": "magento",
            "operation": "product",
            "reason": "selected product has no physical simple SKU",
            "evidence": errors,
        }
    return {
        "operation": "product",
        "platform": "magento",
        "parent_sku": parent_sku,
        "products": concrete,
        "evidence": errors,
    }


def quote(request: Request, origin: str, selection: dict[str, Any], detection_evidence: list[str]) -> dict[str, Any]:
    if selection.get("type") != "SimpleProduct" or selection.get("physical") is not True:
        return {
            "status": "unsupported",
            "platform": "magento",
            "operation": "quote",
            "reason": "quote requires a physical simple product returned by product",
        }
    sku = selection.get("sku")
    if not isinstance(sku, str) or not sku or any(character in sku for character in "\r\n"):
        return api_error("magento", "quote", "selected product has no valid SKU", [])

    create = request("POST", origin + "/rest/V1/guest-carts", json={})
    if create["status"] in {401, 403, 404, 405}:
        return denied("magento", "quote", "/rest/V1/guest-carts", create, detection_evidence)
    token = create.get("json")
    if create["status"] not in {200, 201} or not isinstance(token, str) or not 16 <= len(token) <= 128:
        return api_error(
            "magento",
            "quote",
            "guest cart did not return a token",
            [{"type": "http_status", "endpoint": "/rest/V1/guest-carts", "status": create["status"]}],
        )

    cart_path = "/rest/V1/guest-carts/" + quote_path(token)
    add = request(
        "POST",
        origin + cart_path + "/items",
        json={"cartItem": {"sku": sku, "qty": 1, "quote_id": token}},
    )
    if add["status"] in {401, 403}:
        return denied("magento", "quote", "/rest/V1/guest-carts/[redacted]/items", add, detection_evidence)
    added = add.get("json")
    if add["status"] not in {200, 201} or not isinstance(added, dict) or added.get("sku") != sku:
        return api_error(
            "magento",
            "quote",
            "guest cart rejected or changed the selected SKU",
            [{"type": "http_status", "endpoint": "/rest/V1/guest-carts/[redacted]/items", "status": add["status"]}],
        )

    rates_response = request(
        "POST",
        origin + cart_path + "/estimate-shipping-methods",
        json={"address": DUMMY_SF},
    )
    if rates_response["status"] in {401, 403}:
        return denied(
            "magento",
            "quote",
            "/rest/V1/guest-carts/[redacted]/estimate-shipping-methods",
            rates_response,
            detection_evidence,
        )
    raw_rates = rates_response.get("json")
    if rates_response["status"] != 200 or not isinstance(raw_rates, list):
        return api_error(
            "magento",
            "quote",
            "shipping estimate did not return an array",
            [{"type": "http_status", "endpoint": "/rest/V1/guest-carts/[redacted]/estimate-shipping-methods", "status": rates_response["status"]}],
        )

    currency = selection.get("price", {}).get("currency") if isinstance(selection.get("price"), dict) else None
    options = [_shipping_option(rate, currency) for rate in raw_rates if isinstance(rate, dict)]
    subtotal = money(added.get("price"), currency)
    item = {"sku": sku, "title": added.get("name"), "quantity": added.get("qty", 1), "price": money(added.get("price"), currency)}
    return quote_result("magento", options, item=item, subtotal=subtotal)


def quote_path(value: str) -> str:
    return url_quote(value, safe="")


def _graphql_failure(response: dict[str, Any], operation: str, detection_evidence: list[str]) -> dict[str, Any] | None:
    if response["status"] in {401, 403, 404}:
        return denied("magento", operation, "/graphql", response, detection_evidence)
    if response["status"] != 200 or not isinstance(response.get("json"), dict):
        return api_error(
            "magento",
            operation,
            "GraphQL did not return an object",
            [{"type": "http_status", "endpoint": "/graphql", "status": response["status"]}],
        )
    return None


def _graphql_errors(envelope: dict[str, Any], stage: str) -> list[dict[str, Any]]:
    errors = envelope.get("errors", [])
    if not isinstance(errors, list):
        return [{"type": "api_error", "stage": stage, "message": "GraphQL errors was not an array"}]
    return [
        {
            "type": "api_error",
            "stage": stage,
            "message": str(error.get("message", "GraphQL error")),
            "path": error.get("path"),
            "partial": envelope.get("data") is not None,
        }
        for error in errors
        if isinstance(error, dict)
    ]


def _concrete_products(parent: dict[str, Any], config: dict[str, Any], origin: str) -> list[dict[str, Any]]:
    if parent.get("__typename") == "SimpleProduct":
        return [_product_record(parent, parent, [], config, origin)]
    if parent.get("__typename") != "ConfigurableProduct" or not isinstance(parent.get("variants"), list):
        return []
    products = []
    for variant in parent["variants"]:
        if not isinstance(variant, dict) or not isinstance(variant.get("product"), dict):
            continue
        child = variant["product"]
        if child.get("__typename") != "SimpleProduct":
            continue
        attributes = variant.get("attributes") if isinstance(variant.get("attributes"), list) else []
        products.append(_product_record(child, parent, attributes, config, origin))
    return products


def _product_record(
    product: dict[str, Any],
    parent: dict[str, Any],
    attributes: list[Any],
    config: dict[str, Any],
    origin: str,
) -> dict[str, Any]:
    price_range = product.get("price_range")
    minimum = price_range.get("minimum_price") if isinstance(price_range, dict) else None
    final = minimum.get("final_price") if isinstance(minimum, dict) else None
    price = money(final.get("value"), final.get("currency")) if isinstance(final, dict) else None
    base = config.get("base_url") if isinstance(config.get("base_url"), str) else origin + "/"
    suffix = config.get("product_url_suffix") if isinstance(config.get("product_url_suffix"), str) else ""
    options = [
        {"code": value.get("code"), "label": value.get("label"), "value": value.get("value_index")}
        for value in attributes
        if isinstance(value, dict)
    ]
    return {
        "type": "SimpleProduct",
        "physical": True,
        "sku": product.get("sku"),
        "title": parent.get("name"),
        "variant": product.get("name") if product is not parent else None,
        "options": options,
        "available": product.get("stock_status") == "IN_STOCK",
        "price": price,
        "url": urljoin(base, str(parent.get("url_key") or "") + suffix),
    }


def _shipping_option(rate: dict[str, Any], currency: str | None) -> dict[str, Any]:
    carrier = str(rate.get("carrier_code", ""))
    method = str(rate.get("method_code", ""))
    description = " — ".join(str(value) for value in (rate.get("carrier_title"), rate.get("method_title")) if value)
    error = str(rate["error_message"]) if rate.get("error_message") else None
    available = rate.get("available") is not False
    return {
        "id": f"{carrier}/{method}",
        "type": carrier,
        "title": description or f"{carrier}/{method}",
        "disposition": option_disposition(f"{carrier}/{method}", description, available, error),
        "available": available,
        "error": error,
        "amount": money(rate.get("amount"), currency),
        "price_excl_tax": money(rate.get("price_excl_tax"), currency),
        "price_incl_tax": money(rate.get("price_incl_tax"), currency),
    }
