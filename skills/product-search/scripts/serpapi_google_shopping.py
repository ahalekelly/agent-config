# /// script
# requires-python = ">=3.11"
# ///

from __future__ import annotations

import argparse
import json
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
    return message.replace(secret, "[redacted]")


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
        raise RuntimeError("SerpApi returned a non-object response")
    if "error" in payload:
        message = _redact(str(payload["error"]), api_key)
        raise RuntimeError(f"SerpApi error: {message}")

    metadata = payload.get("search_metadata")
    if not isinstance(metadata, dict) or metadata.get("status") != "Success":
        raise RuntimeError("SerpApi search did not report Success")
    if "processed_at" not in metadata:
        raise RuntimeError("SerpApi response omitted search_metadata.processed_at")

    result_keys = [
        key for key in ("shopping_results", "inline_shopping_results") if key in payload
    ]
    if len(result_keys) > 1:
        raise RuntimeError("SerpApi returned two incompatible Shopping result layouts")

    result_key = result_keys[0] if result_keys else None
    items = payload[result_key] if result_key else []
    if not isinstance(items, list):
        raise RuntimeError("SerpApi Shopping results were not a list")

    normalized = []
    for item in items:
        if not isinstance(item, dict):
            raise RuntimeError("SerpApi returned a non-object Shopping result")
        for field in ("title", "source", "price"):
            if field not in item:
                raise RuntimeError(f"SerpApi Shopping result omitted {field}")

        lead = {
            "evidence_class": "lead",
            "title": item["title"],
            "merchant": item["source"],
            "displayed_price": item["price"],
        }
        optional_fields = {
            "extracted_price": "price_value",
            "old_price": "displayed_old_price",
            "extracted_old_price": "old_price_value",
            "delivery": "delivery_text",
            "second_hand_condition": "condition",
            "rating": "rating",
            "reviews": "review_count",
            "thumbnail": "image_url",
        }
        if result_key == "shopping_results":
            optional_fields |= {
                "product_id": "google_product_id",
                "product_link": "google_product_url",
                "direct_link": "retailer_url",
            }
        elif result_key == "inline_shopping_results":
            optional_fields |= {"link": "retailer_url"}
        lead.update(
            {
                output_key: item[provider_key]
                for provider_key, output_key in optional_fields.items()
                if provider_key in item
            }
        )
        normalized.append(lead)

    return {
        "source": "SerpApi Google Shopping",
        "evidence_class": "lead",
        "verification_required": VERIFICATION,
        "query": query,
        "location": LOCATION,
        "retrieved_at": metadata["processed_at"],
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
    except (RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from error
    json.dump(result, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
