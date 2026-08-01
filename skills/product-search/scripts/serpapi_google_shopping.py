# /// script
# requires-python = ">=3.11"
# ///

from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API_URL = "https://serpapi.com/search.json"
LOCATION = "San Francisco, California, United States"
VERIFICATION = (
    "Lead only: verify price, stock, specifications, retailer identity, and "
    "shipping with the retailer before recommending or buying."
)


def _redact(message: str, secret: str) -> str:
    for value in {
        secret,
        urllib.parse.quote(secret, safe=""),
        urllib.parse.quote_plus(secret),
    }:
        message = message.replace(value, "[redacted]")
    return message


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"SerpApi Shopping result had invalid {field}")
    return value.strip()


def _display_price(value: object, field: str) -> str:
    price = _text(value, field)
    if not any(character.isdigit() for character in price):
        raise RuntimeError(f"SerpApi Shopping result had invalid {field}")
    return price


def _number(value: object, field: str, maximum: float | None = None) -> int | float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
        or (maximum is not None and value > maximum)
    ):
        raise RuntimeError(f"SerpApi Shopping result had invalid {field}")
    return value


def _count(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeError(f"SerpApi Shopping result had invalid {field}")
    return value


def _url(value: object, field: str) -> str:
    url = _text(value, field)
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise RuntimeError(f"SerpApi Shopping result had invalid {field}") from error
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or any(character.isspace() for character in url)
        or (port is not None and port < 1)
    ):
        raise RuntimeError(f"SerpApi Shopping result had invalid {field}")
    return url


def _product_id(value: object, field: str) -> str:
    return _text(value, field)


def _processed_at(value: object) -> str:
    timestamp = _text(value, "search_metadata.processed_at")
    try:
        datetime.datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S UTC").replace(
            tzinfo=datetime.timezone.utc
        )
    except ValueError as error:
        raise RuntimeError(
            "SerpApi returned invalid search_metadata.processed_at"
        ) from error
    return timestamp


def _normalize_item(item: object, result_key: str) -> dict[str, object]:
    if not isinstance(item, dict):
        raise TypeError("SerpApi returned a non-object Shopping result")
    for field in ("title", "source", "price"):
        if field not in item:
            raise RuntimeError(f"SerpApi Shopping result omitted {field}")

    lead: dict[str, object] = {
        "evidence_class": "lead",
        "title": _text(item["title"], "title"),
        "merchant": _text(item["source"], "source"),
        "displayed_price": _display_price(item["price"], "price"),
    }
    optional_fields = {
        "extracted_price": ("price_value", _number),
        "old_price": ("displayed_old_price", _display_price),
        "extracted_old_price": ("old_price_value", _number),
        "delivery": ("delivery_text", _text),
        "second_hand_condition": ("condition", _text),
        "rating": ("rating", lambda value, field: _number(value, field, 5)),
        "reviews": ("review_count", _count),
        "thumbnail": ("image_url", _url),
    }
    if result_key == "shopping_results":
        optional_fields |= {
            "product_id": ("google_product_id", _product_id),
            "product_link": ("google_product_url", _url),
            "direct_link": ("retailer_url", _url),
        }
    else:
        optional_fields |= {"link": ("retailer_url", _url)}
    for provider_field, (output_field, validate) in optional_fields.items():
        if provider_field in item:
            lead[output_field] = validate(item[provider_field], provider_field)
    return lead


def search(query: str, api_key: str) -> dict[str, object]:
    if not query:
        raise ValueError("query is required")
    if not api_key:
        raise ValueError("api_key is required")

    params = urllib.parse.urlencode(
        {
            "engine": "google_shopping",
            "q": query,
            "location": LOCATION,
            "gl": "us",
            "hl": "en",
            "direct_link": "true",
            "api_key": api_key,
        }
    )
    request = urllib.request.Request(f"{API_URL}?{params}")

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"SerpApi HTTP {error.code}: {_redact(body, api_key)}"
        ) from error
    except urllib.error.URLError as error:
        message = _redact(str(error.reason), api_key)
        raise RuntimeError(f"SerpApi request failed: {message}") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("SerpApi returned invalid JSON") from error

    if not isinstance(payload, dict):
        raise TypeError("SerpApi returned a non-object response")
    if "error" in payload:
        message = _redact(str(payload["error"]), api_key)
        raise RuntimeError(f"SerpApi error: {message}")

    metadata = payload.get("search_metadata")
    if not isinstance(metadata, dict) or metadata.get("status") != "Success":
        raise RuntimeError("SerpApi search did not report Success")
    if "processed_at" not in metadata:
        raise RuntimeError("SerpApi response omitted search_metadata.processed_at")
    processed_at = _processed_at(metadata["processed_at"])

    result_keys = [
        key for key in ("shopping_results", "inline_shopping_results") if key in payload
    ]
    if len(result_keys) > 1:
        raise RuntimeError("SerpApi returned two incompatible Shopping result layouts")

    result_key = result_keys[0] if result_keys else None
    items = payload[result_key] if result_key else []
    if not isinstance(items, list):
        raise TypeError("SerpApi Shopping results were not a list")

    normalized = [_normalize_item(item, result_key) for item in items]

    return {
        "source": "SerpApi Google Shopping",
        "evidence_class": "lead",
        "verification_required": VERIFICATION,
        "query": query,
        "location": LOCATION,
        "retrieved_at": processed_at,
        "items": normalized,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find cross-retailer product leads through Google Shopping."
    )
    parser.add_argument("query")
    args = parser.parse_args()

    api_key = os.environ.get("SERPAPI_API_KEY")
    if not api_key:
        raise SystemExit("SERPAPI_API_KEY is required")

    try:
        result = search(args.query, api_key)
    except (RuntimeError, TypeError, ValueError) as error:
        raise SystemExit(str(error)) from error
    json.dump(result, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
