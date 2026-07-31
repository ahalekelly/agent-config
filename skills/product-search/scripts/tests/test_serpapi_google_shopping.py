# /// script
# requires-python = ">=3.11"
# ///

from __future__ import annotations

import io
import json
import os
import sys
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))

import serpapi_google_shopping  # noqa: E402


class SerpApiGoogleShoppingTest(unittest.TestCase):
    def test_normalizes_inline_results_as_unverified_leads(self) -> None:
        payload = {
            "search_metadata": {
                "status": "Success",
                "processed_at": "2026-07-31 12:00:00 UTC",
            },
            "inline_shopping_results": [
                {
                    "title": "M3 brass heat-set inserts, 100 pack",
                    "source": "Example Fasteners",
                    "price": "$12.50",
                    "extracted_price": 12.5,
                    "delivery": "$4.99 delivery",
                    "rating": 4.8,
                    "reviews": 37,
                    "link": "https://retailer.example/product/1",
                    "thumbnail": "https://images.example/product-1.jpg",
                }
            ],
        }
        captured = {}

        def open_url(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return io.BytesIO(json.dumps(payload).encode())

        with patch.object(serpapi_google_shopping.urllib.request, "urlopen", open_url):
            result = serpapi_google_shopping.search("M3 heat-set inserts", "test-key")

        query = urllib.parse.parse_qs(
            urllib.parse.urlparse(captured["request"].full_url).query
        )
        self.assertEqual(query["api_key"], ["test-key"])
        self.assertEqual(query["location"], [serpapi_google_shopping.LOCATION])
        self.assertEqual(captured["timeout"], 60)
        self.assertEqual(result["evidence_class"], "lead")
        self.assertIn("verify", result["verification_required"].lower())
        self.assertEqual(
            result["items"],
            [
                {
                    "evidence_class": "lead",
                    "title": "M3 brass heat-set inserts, 100 pack",
                    "merchant": "Example Fasteners",
                    "displayed_price": "$12.50",
                    "price_value": 12.5,
                    "delivery_text": "$4.99 delivery",
                    "rating": 4.8,
                    "review_count": 37,
                    "image_url": "https://images.example/product-1.jpg",
                    "retailer_url": "https://retailer.example/product/1",
                }
            ],
        )

    def test_normalizes_the_product_result_layout(self) -> None:
        payload = {
            "search_metadata": {
                "status": "Success",
                "processed_at": "2026-07-31 12:00:00 UTC",
            },
            "shopping_results": [
                {
                    "title": "Precision pliers",
                    "source": "Example Tools",
                    "price": "$29.00",
                    "product_id": "google-product-1",
                    "product_link": "https://google.example/product/1",
                    "direct_link": "https://retailer.example/product/1",
                }
            ],
        }
        with patch.object(
            serpapi_google_shopping.urllib.request,
            "urlopen",
            return_value=io.BytesIO(json.dumps(payload).encode()),
        ):
            result = serpapi_google_shopping.search("precision pliers", "test-key")

        self.assertEqual(
            result["items"][0],
            {
                "evidence_class": "lead",
                "title": "Precision pliers",
                "merchant": "Example Tools",
                "displayed_price": "$29.00",
                "google_product_id": "google-product-1",
                "google_product_url": "https://google.example/product/1",
                "retailer_url": "https://retailer.example/product/1",
            },
        )

    def test_successful_empty_result_is_not_an_error(self) -> None:
        payload = {
            "search_metadata": {
                "status": "Success",
                "processed_at": "2026-07-31 12:00:00 UTC",
            }
        }
        with patch.object(
            serpapi_google_shopping.urllib.request,
            "urlopen",
            return_value=io.BytesIO(json.dumps(payload).encode()),
        ):
            result = serpapi_google_shopping.search("no matching product", "test-key")
        self.assertEqual(result["items"], [])

    def test_fails_loudly_on_ambiguous_result_layout(self) -> None:
        payload = {
            "search_metadata": {
                "status": "Success",
                "processed_at": "2026-07-31 12:00:00 UTC",
            },
            "shopping_results": [],
            "inline_shopping_results": [],
        }
        with patch.object(
            serpapi_google_shopping.urllib.request,
            "urlopen",
            return_value=io.BytesIO(json.dumps(payload).encode()),
        ):
            with self.assertRaisesRegex(RuntimeError, "incompatible"):
                serpapi_google_shopping.search("query", "test-key")

    def test_fails_loudly_on_provider_error_without_echoing_key(self) -> None:
        payload = {"error": "Invalid API key private-test-key"}
        with patch.object(
            serpapi_google_shopping.urllib.request,
            "urlopen",
            return_value=io.BytesIO(json.dumps(payload).encode()),
        ):
            with self.assertRaisesRegex(RuntimeError, "Invalid API key") as raised:
                serpapi_google_shopping.search("query", "private-test-key")
        self.assertNotIn("private-test-key", str(raised.exception))
        self.assertIn("[redacted]", str(raised.exception))

    def test_http_error_body_cannot_echo_key(self) -> None:
        error = urllib.error.HTTPError(
            serpapi_google_shopping.API_URL,
            401,
            "Unauthorized",
            {},
            io.BytesIO(b"bad private-test-key"),
        )
        self.addCleanup(error.close)
        with patch.object(
            serpapi_google_shopping.urllib.request,
            "urlopen",
            side_effect=error,
        ):
            with self.assertRaisesRegex(RuntimeError, "SerpApi HTTP 401") as raised:
                serpapi_google_shopping.search("query", "private-test-key")
        self.assertNotIn("private-test-key", str(raised.exception))

    def test_rejects_empty_inputs_before_transport(self) -> None:
        with self.assertRaisesRegex(ValueError, "query is required"):
            serpapi_google_shopping.search("", "key")
        with self.assertRaisesRegex(ValueError, "api_key is required"):
            serpapi_google_shopping.search("query", "")

    def test_cli_requires_credentials(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(sys, "argv", ["serpapi_google_shopping.py", "query"]),
        ):
            with self.assertRaisesRegex(SystemExit, "SERPAPI_API_KEY is required"):
                serpapi_google_shopping.main()


if __name__ == "__main__":
    unittest.main()
