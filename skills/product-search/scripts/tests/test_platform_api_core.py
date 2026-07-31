# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "httpx>=0.28,<0.29",
# ]
# ///

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from platform_api_core import (  # noqa: E402
    Detection,
    ToolError,
    canonical_url,
    item_ref,
    money,
    parse_item_ref,
    quote_outcome,
    search_result,
    shipping_option,
    unsupported_configuration,
    validate_result,
)


class UrlTests(unittest.TestCase):
    def test_canonical_url_strips_query_and_fragment(self) -> None:
        self.assertEqual(
            canonical_url("https://BÜCHER.example/product/?utm_source=test#details"),
            "https://xn--bcher-kva.example/product/",
        )

    def test_canonical_url_rejects_credentials(self) -> None:
        with self.assertRaisesRegex(ToolError, "without credentials"):
            canonical_url("https://user:secret@example.com/product")


class DetectionTests(unittest.TestCase):
    def test_detected_state_is_exact(self) -> None:
        detection = Detection(
            kind="detected",
            origin="https://shop.example",
            entry_url="https://shop.example/collections/tools",
            platform="shopify",
            api_origin="https://backend.myshopify.com",
            evidence=("data.shop",),
        )
        self.assertEqual(detection.public()["platform"], "shopify")

    def test_contradictory_unknown_state_fails(self) -> None:
        with self.assertRaisesRegex(ToolError, "Unknown storefront"):
            Detection(
                kind="unknown",
                origin="https://shop.example",
                entry_url="https://shop.example/",
                platform="shopify",
                api_origin=None,
                evidence=("no positive signal",),
            )


class ItemReferenceTests(unittest.TestCase):
    def test_reference_is_platform_bound(self) -> None:
        reference = item_ref("shopify", {"variant_id": "gid://variant/1"})
        self.assertEqual(
            parse_item_ref(reference, "shopify"), {"variant_id": "gid://variant/1"}
        )
        with self.assertRaisesRegex(ToolError, "does not belong"):
            parse_item_ref(reference, "woocommerce")


class ResultTests(unittest.TestCase):
    def test_search_requires_item_references(self) -> None:
        reference = item_ref("shopify", {"variant_id": "gid://variant/1"})
        result = search_result(
            "shopify", "valve", [{"name": "Valve", "item_ref": reference}]
        )
        self.assertEqual(result["kind"], "search")
        with self.assertRaisesRegex(ToolError, "requires items"):
            search_result("shopify", "valve", [{"name": "Valve"}])

    def test_quote_preserves_noncomparable_options(self) -> None:
        options = [
            shipping_option("ground", "Ground", "delivery", money("12.99", "USD")),
            shipping_option("pickup", "Store pickup", "pickup", None),
            shipping_option("freight", "Freight billed later", "paid_later", None),
        ]
        result = quote_outcome("shopify", options, money("25.00", "USD"))
        self.assertEqual(result["kind"], "quote")
        self.assertEqual([rate["option_id"] for rate in result["rates"]], ["ground"])
        self.assertEqual(len(result["shipping_options"]), 3)

    def test_empty_is_never_free_shipping(self) -> None:
        result = quote_outcome("woocommerce", [], money("25.00", "USD"))
        self.assertEqual(result["kind"], "empty")
        self.assertEqual(result["rates"], [])
        self.assertEqual(result["reason"], "empty_rate_list")

    def test_fallback_is_distinct(self) -> None:
        option = shipping_option(
            "flat_fallback", "Flat rate", "fallback", money("19.95", "USD")
        )
        result = quote_outcome("woocommerce", [option], money("25.00", "USD"))
        self.assertEqual(result["kind"], "fallback")
        self.assertEqual(result["fallback_rate_ids"], ["flat_fallback"])
        self.assertEqual(result["rates"], [])

    def test_contradictory_success_result_fails(self) -> None:
        with self.assertRaisesRegex(ToolError, "exactly match"):
            validate_result(
                {
                    "kind": "quote",
                    "operation": "quote",
                    "platform": "shopify",
                    "shipping_options": [
                        shipping_option(
                            "ground", "Ground", "delivery", money("4", "USD")
                        )
                    ],
                    "rates": [],
                    "subtotal": money("10", "USD"),
                    "destination": "dummy_sf",
                }
            )

    def test_configuration_terminal_requires_fields(self) -> None:
        result = unsupported_configuration(
            "bigcommerce", ["Color"], "Required options are unresolved"
        )
        self.assertEqual(result["kind"], "unsupported_product_configuration")
        with self.assertRaisesRegex(ToolError, "requires fields"):
            unsupported_configuration(
                "bigcommerce", [], "Required options are unresolved"
            )


if __name__ == "__main__":
    unittest.main()
