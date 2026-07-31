# /// script
# requires-python = ">=3.11"
# ///

from __future__ import annotations

import argparse
import datetime
import hashlib
import hmac
import json
import os
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
        message = message.replace(credential, "[redacted]")
    return message


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
        raise RuntimeError("AliExpress returned a non-object response")
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
        raise RuntimeError("AliExpress returned an invalid product-query response")
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
        raise RuntimeError("AliExpress products were not a list")

    normalized = []
    for product in products:
        if not isinstance(product, dict):
            raise RuntimeError("AliExpress returned a non-object product")
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

        lead = {
            "evidence_class": "lead",
            "product_id": product["product_id"],
            "title": product["product_title"],
            "product_url": product["product_detail_url"],
            "seller_url": product["shop_url"],
            "displayed_price": product["target_sale_price"],
            "currency": product["target_sale_price_currency"],
        }
        optional_fields = {
            "sale_price": "listed_price",
            "sale_price_currency": "listed_price_currency",
            "evaluate_rate": "positive_feedback_rate",
            "lastest_volume": "recent_sales",
            "ship_to_days": "delivery_text",
            "product_main_image_url": "image_url",
        }
        lead.update(
            {
                output_key: product[provider_key]
                for provider_key, output_key in optional_fields.items()
                if provider_key in product
            }
        )
        normalized.append(lead)

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
    except (RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from error
    json.dump(result, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
