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
    StorefrontBotWall,
    ToolError,
    UnknownStore,
    WooCommerceQuote,
    WooCommerceShipping,
    canonical_url,
    item_ref,
    minor_money,
    money,
    parse_item_ref,
    public_detection,
    quote_not_attempted,
    quote_outcome,
    redact_url,
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

    def test_redact_url_removes_camel_case_secret_query_values(self) -> None:
        redacted = redact_url(
            "https://store.example/products"
            "?accessToken=one&storefrontAccessToken=two&apiKey=three&keyword=valve"
        )

        self.assertNotIn("one", redacted)
        self.assertNotIn("two", redacted)
        self.assertNotIn("three", redacted)
        self.assertIn("keyword=valve", redacted)


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

    def test_bot_wall_status_rejects_json_boolean(self) -> None:
        with self.assertRaisesRegex(ToolError, "HTTP status"):
            StorefrontBotWall(
                origin="https://shop.example",
                entry_url="https://shop.example/",
                evidence=("challenge",),
                system="cloudflare",
                status=True,
            )


class ItemReferenceTests(unittest.TestCase):
    def test_reference_is_platform_bound(self) -> None:
        reference = item_ref("shopify", {"variant_id": "gid://variant/1"})
        self.assertEqual(
            parse_item_ref(reference, "shopify"), {"variant_id": "gid://variant/1"}
        )
        with self.assertRaisesRegex(ToolError, "does not belong"):
            parse_item_ref(reference, "woocommerce")

    def test_reference_rejects_extra_keys_at_the_parser_seam(self) -> None:
        cases = (
            (
                "shopify",
                {"variant_id": "gid://shopify/ProductVariant/1", "cart_id": "forged"},
            ),
            (
                "woocommerce",
                {
                    "product_id": 1,
                    "product_type": "simple",
                    "minimum": 1,
                    "cart_token": "forged",
                },
            ),
        )
        for platform, payload in cases:
            with self.subTest(platform=platform), self.assertRaisesRegex(
                ToolError, "invalid payload"
            ):
                parse_item_ref(item_ref(platform, payload), platform)

    def test_all_platform_reference_schemas_round_trip(self) -> None:
        cases = {
            "shopify": {"variant_id": "gid://shopify/ProductVariant/1"},
            "woocommerce": {
                "product_id": 1,
                "product_type": "simple",
                "minimum": 1,
            },
            "magento": {"sku": "SKU-1"},
            "bigcommerce": {
                "product_id": 1,
                "product_url": "https://store.example/product",
            },
            "squarespace": {
                "collection_url": "https://store.example/shop",
                "item_id": "item-1",
                "sku": "SKU-1",
            },
            "wix": {"product_id": "product-1"},
            "ecwid": {"product_id": 1, "store_id": "12345"},
            "sfcc": {"pid": "product-1"},
        }
        for platform, payload in cases.items():
            with self.subTest(platform=platform):
                self.assertEqual(
                    parse_item_ref(item_ref(platform, payload), platform), payload
                )

    def test_all_platform_reference_schemas_reject_invalid_values(self) -> None:
        cases = {
            "shopify": {"variant_id": ""},
            "woocommerce": {
                "product_id": 1,
                "product_type": "simple",
                "minimum": True,
            },
            "magento": {"sku": ""},
            "bigcommerce": {
                "product_id": True,
                "product_url": "https://store.example/product",
            },
            "squarespace": {
                "collection_url": "https://store.example/shop",
                "item_id": "item-1",
                "sku": None,
            },
            "wix": {"product_id": ""},
            "ecwid": {"product_id": 1, "store_id": ""},
            "sfcc": {"pid": ""},
        }
        for platform, payload in cases.items():
            with self.subTest(platform=platform), self.assertRaisesRegex(
                ToolError, "invalid payload"
            ):
                parse_item_ref(item_ref(platform, payload), platform)


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

    def test_minor_unit_digits_require_a_bounded_nonnegative_integer(self) -> None:
        for digits in (True, -1, 5):
            with (
                self.subTest(digits=digits),
                self.assertRaisesRegex(ToolError, "minor-unit count"),
            ):
                minor_money("123", "USD", digits)

        self.assertEqual(
            minor_money("12345", "CLF", 4),
            {"amount": "1.2345", "currency": "CLF"},
        )

    def test_cleanup_status_rejects_json_boolean(self) -> None:
        with self.assertRaisesRegex(ToolError, "invalid facts"):
            quote_outcome(
                WooCommerceQuote(cart_totals={}, cleanup_status=True),
                [],
                money("10", "USD"),
            )

    def test_terminal_status_rejects_json_boolean(self) -> None:
        outcomes = [
            {
                "kind": "gated",
                "operation": "search",
                "platform": "woocommerce",
                "reason": "refused",
                "endpoint": "/products",
                "status": True,
                "browser_required": True,
            },
            {
                "kind": "bot_wall",
                "operation": "search",
                "platform": "woocommerce",
                "reason": "challenge response",
                "system": "cloudflare",
                "status": True,
            },
        ]
        for outcome in outcomes:
            with (
                self.subTest(kind=outcome["kind"]),
                self.assertRaisesRegex(ToolError, "status"),
            ):
                validate_result(outcome)

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
