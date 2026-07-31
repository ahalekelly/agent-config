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

import aliexpress_affiliate  # noqa: E402


class AliExpressAffiliateTest(unittest.TestCase):
    def test_sign_matches_the_documented_top_hmac_md5_algorithm(self) -> None:
        params = {"foo": "1", "bar": "2", "foo_bar": "3", "foobar": "4"}
        self.assertEqual(
            aliexpress_affiliate.sign(params, "secret"),
            "26C775E5D0EB124C248184BFA79CA514",
        )

    def test_normalizes_affiliate_products_as_unverified_leads(self) -> None:
        payload = {
            "aliexpress_affiliate_product_query_response": {
                "resp_result": {
                    "resp_code": 200,
                    "resp_msg": "success",
                    "result": {
                        "products": {
                            "product": [
                                {
                                    "product_id": 123456789,
                                    "product_title": "M3 brass heat-set inserts",
                                    "product_detail_url": "https://aliexpress.example/item/123",
                                    "shop_url": "https://aliexpress.example/store/456",
                                    "target_sale_price": "11.20",
                                    "target_sale_price_currency": "USD",
                                    "sale_price": "10.90",
                                    "sale_price_currency": "USD",
                                    "evaluate_rate": "96.2%",
                                    "lastest_volume": 218,
                                    "ship_to_days": "ship to US in 7 days",
                                    "product_main_image_url": "https://images.example/123.jpg",
                                }
                            ]
                        }
                    },
                }
            }
        }
        captured = {}

        def open_url(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return io.BytesIO(json.dumps(payload).encode())

        with patch.object(aliexpress_affiliate.urllib.request, "urlopen", open_url):
            result = aliexpress_affiliate.search(
                "M3 heat-set inserts", "test-app-key", "private-test-secret"
            )

        form = urllib.parse.parse_qs(captured["request"].data.decode())
        self.assertEqual(captured["request"].full_url, aliexpress_affiliate.API_URL)
        self.assertEqual(form["method"], ["aliexpress.affiliate.product.query"])
        self.assertEqual(form["ship_to_country"], ["US"])
        self.assertEqual(form["target_currency"], ["USD"])
        self.assertEqual(len(form["sign"][0]), 32)
        self.assertEqual(captured["timeout"], 60)
        self.assertEqual(result["evidence_class"], "lead")
        self.assertIn("verify", result["verification_required"].lower())
        self.assertEqual(
            result["items"],
            [
                {
                    "evidence_class": "lead",
                    "product_id": 123456789,
                    "title": "M3 brass heat-set inserts",
                    "product_url": "https://aliexpress.example/item/123",
                    "seller_url": "https://aliexpress.example/store/456",
                    "displayed_price": "11.20",
                    "currency": "USD",
                    "listed_price": "10.90",
                    "listed_price_currency": "USD",
                    "positive_feedback_rate": "96.2%",
                    "recent_sales": 218,
                    "delivery_text": "ship to US in 7 days",
                    "image_url": "https://images.example/123.jpg",
                }
            ],
        )

    def test_fails_loudly_on_invalid_credentials_without_echoing_them(self) -> None:
        payload = {
            "error_response": {
                "code": 29,
                "msg": "Invalid app Key",
                "sub_code": "isv.appkey-not-exists",
                "sub_msg": "test-key private-test-secret",
            }
        }
        with patch.object(
            aliexpress_affiliate.urllib.request,
            "urlopen",
            return_value=io.BytesIO(json.dumps(payload).encode()),
        ):
            with self.assertRaisesRegex(RuntimeError, "Invalid app Key") as raised:
                aliexpress_affiliate.search("query", "test-key", "private-test-secret")
        self.assertNotIn("private-test-secret", str(raised.exception))
        self.assertNotIn("test-key", str(raised.exception))
        self.assertIn("[redacted]", str(raised.exception))

    def test_product_query_error_cannot_echo_credentials(self) -> None:
        payload = {
            "aliexpress_affiliate_product_query_response": {
                "resp_result": {
                    "resp_code": 500,
                    "resp_msg": "bad app-key private-secret",
                }
            }
        }
        with patch.object(
            aliexpress_affiliate.urllib.request,
            "urlopen",
            return_value=io.BytesIO(json.dumps(payload).encode()),
        ):
            with self.assertRaisesRegex(RuntimeError, "product query failed") as raised:
                aliexpress_affiliate.search("query", "app-key", "private-secret")
        self.assertNotIn("app-key", str(raised.exception))
        self.assertNotIn("private-secret", str(raised.exception))

    def test_http_error_body_cannot_echo_credentials(self) -> None:
        error = urllib.error.HTTPError(
            aliexpress_affiliate.API_URL,
            401,
            "Unauthorized",
            {},
            io.BytesIO(b"bad app-key private-secret"),
        )
        self.addCleanup(error.close)
        with patch.object(
            aliexpress_affiliate.urllib.request,
            "urlopen",
            side_effect=error,
        ):
            with self.assertRaisesRegex(RuntimeError, "AliExpress HTTP 401") as raised:
                aliexpress_affiliate.search("query", "app-key", "private-secret")
        self.assertNotIn("app-key", str(raised.exception))
        self.assertNotIn("private-secret", str(raised.exception))

    def test_rejects_empty_inputs_before_transport(self) -> None:
        with self.assertRaisesRegex(ValueError, "query is required"):
            aliexpress_affiliate.search("", "key", "secret")
        with self.assertRaisesRegex(ValueError, "app_key is required"):
            aliexpress_affiliate.search("query", "", "secret")
        with self.assertRaisesRegex(ValueError, "app_secret is required"):
            aliexpress_affiliate.search("query", "key", "")
        with self.assertRaisesRegex(ValueError, "app_secret is required"):
            aliexpress_affiliate.sign({}, "")

    def test_cli_requires_credentials(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(sys, "argv", ["aliexpress_affiliate.py", "query"]),
        ):
            with self.assertRaisesRegex(
                SystemExit,
                "ALIEXPRESS_APP_KEY and ALIEXPRESS_APP_SECRET are required",
            ):
                aliexpress_affiliate.main()


if __name__ == "__main__":
    unittest.main()
