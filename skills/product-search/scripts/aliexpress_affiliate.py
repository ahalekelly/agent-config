# /// script
# requires-python = ">=3.12"
# ///

import argparse
import hashlib
import hmac
import json
import os
from collections.abc import Mapping, Sequence
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


ENDPOINT = "https://api.taobao.com/router/rest"
RESPONSE_KEY = "aliexpress_affiliate_product_query_response"


def signature(parameters: Mapping[str, str], secret: str) -> str:
    if not secret:
        raise ValueError("secret must not be empty")
    payload = "".join(name + parameters[name] for name in sorted(parameters))
    return hmac.new(
        secret.encode("utf-8"), payload.encode("utf-8"), hashlib.md5
    ).hexdigest().upper()


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search products in the AliExpress Affiliate API."
    )
    parser.add_argument("query")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--min-price", type=int)
    parser.add_argument("--max-price", type=int)
    parser.add_argument(
        "--sort",
        choices=(
            "SALE_PRICE_ASC",
            "SALE_PRICE_DESC",
            "LAST_VOLUME_ASC",
            "LAST_VOLUME_DESC",
        ),
    )
    parser.add_argument("--delivery-days", choices=("3", "5", "7", "10"))
    args = parser.parse_args(argv)

    args.query = args.query.strip()
    if not args.query:
        parser.error("query must not be empty")
    if args.page < 1:
        parser.error("--page must be at least 1")
    if not 1 <= args.page_size <= 50:
        parser.error("--page-size must be between 1 and 50")
    if args.min_price is not None and args.min_price < 0:
        parser.error("--min-price cannot be negative")
    if args.max_price is not None and args.max_price < 0:
        parser.error("--max-price cannot be negative")
    if (
        args.min_price is not None
        and args.max_price is not None
        and args.min_price > args.max_price
    ):
        parser.error("--min-price cannot exceed --max-price")
    return args


def credentials(environ: Mapping[str, str]) -> tuple[str, str]:
    for name in ("ALIEXPRESS_APP_KEY", "ALIEXPRESS_APP_SECRET"):
        if name not in environ or not environ[name].strip():
            raise SystemExit(f"{name} is required")
    return environ["ALIEXPRESS_APP_KEY"], environ["ALIEXPRESS_APP_SECRET"]


def parameters_for(
    args: argparse.Namespace, app_key: str, timestamp: str
) -> dict[str, str]:
    parameters = {
        "app_key": app_key,
        "format": "json",
        "keywords": args.query,
        "method": "aliexpress.affiliate.product.query",
        "page_no": str(args.page),
        "page_size": str(args.page_size),
        "ship_to_country": "US",
        "sign_method": "hmac",
        "target_currency": "USD",
        "target_language": "EN",
        "timestamp": timestamp,
        "v": "2.0",
    }
    for name, value in {
        "delivery_days": args.delivery_days,
        "max_sale_price": args.max_price,
        "min_sale_price": args.min_price,
        "sort": args.sort,
    }.items():
        if value is not None:
            parameters[name] = str(value)
    return parameters


def parse_response(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise SystemExit("AliExpress returned a non-object JSON response")
    if "error_response" in payload:
        error = payload["error_response"]
        if not isinstance(error, dict):
            raise SystemExit("AliExpress returned a malformed error_response")
        raise SystemExit(
            "AliExpress API error: " + json.dumps(error, ensure_ascii=False)
        )
    if RESPONSE_KEY not in payload or not isinstance(payload[RESPONSE_KEY], dict):
        raise SystemExit(f"AliExpress response is missing {RESPONSE_KEY}")
    response = payload[RESPONSE_KEY]
    if "resp_result" not in response or not isinstance(response["resp_result"], dict):
        raise SystemExit("AliExpress response is missing resp_result")
    if response["resp_result"].get("resp_code") != 200:
        raise SystemExit(
            "AliExpress product query failed: "
            + json.dumps(response["resp_result"], ensure_ascii=False)
        )
    return payload


def request_products(parameters: dict[str, str], opener=urlopen) -> dict[str, object]:
    request = Request(
        ENDPOINT,
        data=urlencode(parameters).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
        method="POST",
    )
    with opener(request, timeout=30) as response:
        return parse_response(json.load(response))


def main() -> None:
    args = parse_arguments()
    app_key, app_secret = credentials(os.environ)
    timestamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    parameters = parameters_for(args, app_key, timestamp)
    parameters["sign"] = signature(parameters, app_secret)
    result = request_products(parameters)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
