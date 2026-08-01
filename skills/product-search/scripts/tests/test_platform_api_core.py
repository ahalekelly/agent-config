# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "httpx>=0.28,<0.29",
# ]
# ///

from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from platform_api_core import (
    DetectedStore,
    ShopifyQuote,
    ShopifySearch,
    ShopifyShipping,
    ToolError,
    UnknownStore,
    WooCommerceQuote,
    WooCommerceShipping,
    canonical_url,
    item_ref,
    money,
    parse_item_ref,
    public_detection,
    quote_not_attempted,
    quote_outcome,
    search_result,
    shipping_option,
    unsupported_configuration,
    validate_result,
)


def shopify_item() -> dict[str, object]:
    return {
        "name": "Valve",
        "variant": None,
        "sku": "VALVE-1",
        "barcode": None,
        "available": True,
        "price": money("10", "USD"),
        "product_url": "https://shop.example/products/valve",
        "item_ref": item_ref("shopify", {"variant_id": "gid://variant/1"}),
    }


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
        detection = DetectedStore(
            origin="https://shop.example",
            entry_url="https://shop.example/collections/tools",
            platform="shopify",
            api_origin="https://backend.myshopify.com",
            evidence=("data.shop",),
        )
        self.assertEqual(public_detection(detection)["platform"], "shopify")

    def test_unknown_state_has_no_positive_fields(self) -> None:
        detection = UnknownStore(
            origin="https://shop.example",
            entry_url="https://shop.example/",
            evidence=("no positive signal",),
        )
        self.assertEqual(
            set(public_detection(detection)), {"kind", "origin", "evidence"}
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
        product = shopify_item()
        result = search_result(ShopifySearch(), "valve", [product])
        self.assertEqual(result["kind"], "search")
        product.pop("item_ref")
        with self.assertRaisesRegex(ToolError, "exact keys"):
            search_result(ShopifySearch(), "valve", [product])

    def test_quote_preserves_noncomparable_options(self) -> None:
        options = [
            shipping_option(
                ShopifyShipping(code=None, description=None),
                "ground",
                "Ground",
                "delivery",
                money("12.99", "USD"),
            ),
            shipping_option(
                ShopifyShipping(code=None, description=None),
                "pickup",
                "Store pickup",
                "pickup",
                None,
            ),
            shipping_option(
                ShopifyShipping(code=None, description=None),
                "freight",
                "Freight billed later",
                "paid_later",
                None,
            ),
        ]
        result = quote_outcome(ShopifyQuote(), options, money("25.00", "USD"))
        self.assertEqual(result["kind"], "quote")
        self.assertEqual([rate["option_id"] for rate in result["rates"]], ["ground"])
        self.assertEqual(len(result["shipping_options"]), 3)

    def test_empty_is_never_free_shipping(self) -> None:
        result = quote_outcome(
            WooCommerceQuote(cart_totals={}, cleanup_status=200),
            [],
            money("25.00", "USD"),
        )
        self.assertEqual(result["kind"], "empty")
        self.assertEqual(result["rates"], [])
        self.assertEqual(result["reason"], "empty_rate_list")

    def test_fallback_is_distinct(self) -> None:
        option = shipping_option(
            WooCommerceShipping(selected=False, tax={"amount": "0", "currency": "USD"}),
            "flat_fallback",
            "Flat rate",
            "fallback",
            money("19.95", "USD"),
        )
        result = quote_outcome(
            WooCommerceQuote(cart_totals={}, cleanup_status=200),
            [option],
            money("25.00", "USD"),
        )
        self.assertEqual(result["kind"], "fallback")
        self.assertEqual(result["fallback_rate_ids"], ["flat_fallback"])
        self.assertEqual(result["rates"], [])

    def test_comparable_rate_takes_precedence_over_fallback_marker(self) -> None:
        fallback = shipping_option(
            WooCommerceShipping(selected=False, tax=money("0", "USD")),
            "flat_fallback",
            "Flat fallback",
            "fallback",
            money("19.95", "USD"),
        )
        delivery = shipping_option(
            WooCommerceShipping(selected=True, tax=money("0", "USD")),
            "ground",
            "Ground",
            "delivery",
            money("12.00", "USD"),
        )

        result = quote_outcome(
            WooCommerceQuote(cart_totals={}, cleanup_status=200),
            [fallback, delivery],
            money("25.00", "USD"),
        )

        self.assertEqual(result["kind"], "quote")
        self.assertNotIn("fallback_rate_ids", result)
        self.assertEqual(result["shipping_options"][0]["disposition"], "fallback")

        result["kind"] = "fallback"
        result["fallback_rate_ids"] = ["flat_fallback"]
        with self.assertRaisesRegex(ToolError, "exclusive"):
            validate_result(result)

    def test_money_requires_a_finite_decimal(self) -> None:
        for amount in (
            "NaN",
            "Infinity",
            "-Infinity",
            float("nan"),
            float("inf"),
            Decimal("NaN"),
        ):
            with (
                self.subTest(amount=amount),
                self.assertRaisesRegex(ToolError, "finite"),
            ):
                money(amount, "USD")

        with self.assertRaisesRegex(ToolError, "valid decimal"):
            money("not-a-number", "USD")

        option = shipping_option(
            ShopifyShipping(code=None, description=None),
            "ground",
            "Ground",
            "delivery",
            money("4", "USD"),
        )
        with self.assertRaisesRegex(ToolError, "currency-bearing subtotal"):
            quote_outcome(
                ShopifyQuote(),
                [option],
                {"amount": "NaN", "currency": "USD"},
            )

    def test_quote_not_attempted_schema_is_closed(self) -> None:
        result = quote_not_attempted("shopify", "valve", 2)
        self.assertEqual(
            set(result),
            {
                "kind",
                "operation",
                "platform",
                "reason",
                "query",
                "candidate_count",
            },
        )

        result["candidate_count"] = True
        with self.assertRaisesRegex(ToolError, "invalid facts"):
            validate_result(result)

        result = quote_not_attempted("shopify", "valve", 2)
        result["items"] = []
        with self.assertRaisesRegex(ToolError, "exact keys"):
            validate_result(result)

    def test_contradictory_success_result_fails(self) -> None:
        with self.assertRaisesRegex(ToolError, "exactly match"):
            validate_result(
                {
                    "kind": "quote",
                    "operation": "quote",
                    "platform": "shopify",
                    "shipping_options": [
                        shipping_option(
                            ShopifyShipping(code=None, description=None),
                            "ground",
                            "Ground",
                            "delivery",
                            money("4", "USD"),
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
