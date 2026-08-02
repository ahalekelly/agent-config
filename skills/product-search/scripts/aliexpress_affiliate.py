# /// script
# requires-python = ">=3.11"
# ///

from __future__ import annotations

import argparse
import datetime
import decimal
import hashlib
import hmac
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

API_URL = "https://api.taobao.com/router/rest"
VERIFICATION = (
    "Lead only: verify the exact variant, price, stock, specifications, seller, "
    "and delivered cost on AliExpress before recommending or buying."
)


def _redact(message: str, credentials: tuple[str, ...]) -> str:
    for credential in credentials:
        for value in {
            credential,
            urllib.parse.quote(credential, safe=""),
            urllib.parse.quote_plus(credential),
        }:
            message = message.replace(value, "[redacted]")
    return message


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"AliExpress product had invalid {field}")
    return value.strip()


def _url(value: object, field: str) -> str:
    url = _text(value, field)
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise RuntimeError(f"AliExpress product had invalid {field}") from error
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or any(character.isspace() for character in url)
        or (port is not None and port < 1)
    ):
        raise RuntimeError(f"AliExpress product had invalid {field}")
    return url


def _product_id(value: object, field: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise TypeError(f"AliExpress product had invalid {field}")
    product_id = str(value).strip()
    if not product_id.isdigit() or int(product_id) < 1:
        raise RuntimeError(f"AliExpress product had invalid {field}")
    return product_id


def _price(value: object, field: str) -> str:
    price = _text(value, field)
    if not re.fullmatch(r"\d+(?:\.\d+)?", price):
        raise RuntimeError(f"AliExpress product had invalid {field}")
    amount = decimal.Decimal(price)
    if not amount.is_finite() or amount < 0:
        raise RuntimeError(f"AliExpress product had invalid {field}")
    return price


def _currency(value: object, field: str) -> str:
    currency = _text(value, field)
    if not re.fullmatch(r"[A-Z]{3}", currency) or currency != "USD":
        raise RuntimeError(f"AliExpress product had invalid {field}")
    return currency


def _feedback_rate(value: object, field: str) -> str:
    rate = _text(value, field)
    if not rate.endswith("%"):
        raise RuntimeError(f"AliExpress product had invalid {field}")
    try:
        percentage = decimal.Decimal(rate[:-1])
    except decimal.InvalidOperation as error:
        raise RuntimeError(f"AliExpress product had invalid {field}") from error
    if not percentage.is_finite() or percentage < 0 or percentage > 100:
        raise RuntimeError(f"AliExpress product had invalid {field}")
    return rate


def _count(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeError(f"AliExpress product had invalid {field}")
    return value


def _normalize_product(product: object) -> dict[str, object]:
    if not isinstance(product, dict):
        raise TypeError("AliExpress returned a non-object product")
    for field in (
        "product_id",
        "product_title",
        "product_detail_url",
        "shop_url",
        "target_sale_price",
        "target_sale_price_currency",
    ):
        if field not in product:
            raise RuntimeError(f"AliExpress product omitted {field}")

    lead: dict[str, object] = {
        "evidence_class": "lead",
        "product_id": _product_id(product["product_id"], "product_id"),
        "title": _text(product["product_title"], "product_title"),
        "product_url": _url(product["product_detail_url"], "product_detail_url"),
        "seller_url": _url(product["shop_url"], "shop_url"),
        "displayed_price": _price(product["target_sale_price"], "target_sale_price"),
        "currency": _currency(
            product["target_sale_price_currency"], "target_sale_price_currency"
        ),
    }
    optional_fields = {
        "sale_price": ("listed_price", _price),
        "sale_price_currency": ("listed_price_currency", _currency),
        "evaluate_rate": ("positive_feedback_rate", _feedback_rate),
        "lastest_volume": ("recent_sales", _count),
        "ship_to_days": ("delivery_text", _text),
        "product_main_image_url": ("image_url", _url),
    }
    for provider_field, (output_field, validate) in optional_fields.items():
        if provider_field in product:
            lead[output_field] = validate(product[provider_field], provider_field)
    if ("sale_price" in product) != ("sale_price_currency" in product):
        raise RuntimeError(
            "AliExpress product must provide sale_price and sale_price_currency together"
        )
    return lead


def sign(params: dict[str, str], app_secret: str) -> str:
    if not app_secret:
        raise ValueError("app_secret is required")
    message = "".join(key + params[key] for key in sorted(params))
    return (
        hmac.new(app_secret.encode(), message.encode(), hashlib.md5).hexdigest().upper()
    )


def search(query: str, app_key: str, app_secret: str) -> dict[str, object]:
    if not query:
        raise ValueError("query is required")
    if not app_key:
        raise ValueError("app_key is required")
    if not app_secret:
        raise ValueError("app_secret is required")

    params = {
        "app_key": app_key,
        "format": "json",
        "keywords": query,
        "method": "aliexpress.affiliate.product.query",
        "page_no": "1",
        "page_size": "50",
        "ship_to_country": "US",
        "sign_method": "hmac",
        "target_currency": "USD",
        "target_language": "EN",
        "timestamp": datetime.datetime.now(ZoneInfo("Asia/Shanghai")).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "v": "2.0",
    }
    params["sign"] = sign(params, app_secret)
    credentials = (app_key, app_secret, params["sign"])
    request = urllib.request.Request(
        API_URL,
        data=urllib.parse.urlencode(params).encode(),
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        body = _redact(body, credentials)
        raise RuntimeError(f"AliExpress HTTP {error.code}: {body}") from error
    except urllib.error.URLError as error:
        message = _redact(str(error.reason), credentials)
        raise RuntimeError(f"AliExpress request failed: {message}") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("AliExpress returned invalid JSON") from error

    if not isinstance(payload, dict):
        raise TypeError("AliExpress returned a non-object response")
    if "error_response" in payload:
        error = payload["error_response"]
        if not isinstance(error, dict) or "code" not in error or "msg" not in error:
            raise RuntimeError("AliExpress returned an invalid error response")
        details = " ".join(
            str(error[key]) for key in ("sub_code", "sub_msg") if key in error
        )
        suffix = f": {details}" if details else ""
        message = f"AliExpress error {error['code']} {error['msg']}{suffix}"
        raise RuntimeError(_redact(message, credentials))

    response_key = "aliexpress_affiliate_product_query_response"
    if response_key not in payload:
        raise RuntimeError("AliExpress response omitted the product-query result")
    response = payload[response_key]
    if not isinstance(response, dict) or not isinstance(
        response.get("resp_result"), dict
    ):
        raise TypeError("AliExpress returned an invalid product-query response")
    result = response["resp_result"]
    if result.get("resp_code") != 200:
        message = (
            f"AliExpress product query failed: {result.get('resp_code')} "
            f"{result.get('resp_msg')}"
        )
        raise RuntimeError(_redact(message, credentials))

    try:
        products = result["result"]["products"]["product"]
    except (KeyError, TypeError) as error:
        raise RuntimeError("AliExpress response omitted its product list") from error
    if not isinstance(products, list):
        raise TypeError("AliExpress products were not a list")

    normalized = [_normalize_product(product) for product in products]

    return {
        "source": "AliExpress Affiliate API",
        "evidence_class": "lead",
        "verification_required": VERIFICATION,
        "query": query,
        "ship_to_country": "US",
        "currency": "USD",
        "items": normalized,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find AliExpress product leads through its Affiliate API."
    )
    parser.add_argument("query")
    args = parser.parse_args()

    app_key = os.environ.get("ALIEXPRESS_APP_KEY")
    app_secret = os.environ.get("ALIEXPRESS_APP_SECRET")
    if not app_key or not app_secret:
        raise SystemExit("ALIEXPRESS_APP_KEY and ALIEXPRESS_APP_SECRET are required")

    try:
        result = search(args.query, app_key, app_secret)
    except (RuntimeError, TypeError, ValueError) as error:
        raise SystemExit(str(error)) from error
    json.dump(result, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
