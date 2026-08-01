# /// script
# requires-python = ">=3.12"
# dependencies = ["cryptography>=45,<47", "httpx>=0.28,<0.29"]
# ///

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import httpx

sys.path.insert(0, str(Path(__file__).parents[1]))

import platform_api
from platform_api_core import (
    DetectedStore,
    MagentoDetectedStore,
    MagentoSearch,
    ShopifyQuote,
    ShopifySearch,
    ShopifyShipping,
    SquarespaceQuote,
    SquarespaceShipping,
    StorefrontBotWall,
    ToolError,
    UnknownStore,
    item_ref,
    money,
    public_detection,
    quote_outcome,
    search_result,
    shipping_option,
    validate_result,
)
from platforms import magento, woocommerce


def response(
    request: httpx.Request,
    status: int = 200,
    *,
    json_value: Any = None,
    content: bytes | None = None,
) -> httpx.Response:
    if content is not None:
        return httpx.Response(status, content=content, request=request)
    return httpx.Response(status, json=json_value, request=request)


def homepage(body: bytes = b"<html></html>") -> httpx.Response:
    return response(httpx.Request("GET", "https://magento.test/"), content=body)


def magento_detection(source: str) -> MagentoDetectedStore:
    return MagentoDetectedStore(
        origin="https://magento.test",
        entry_url="https://magento.test/",
        api_origin="https://magento.test",
        evidence=("Magento capability negotiation",),
        search_source=source,
    )


def shopify_item() -> dict[str, object]:
    return {
        "name": "Valve",
        "variant": None,
        "sku": "VALVE-1",
        "barcode": None,
        "available": True,
        "price": money("10", "USD"),
        "product_url": "https://store.test/products/valve",
        "item_ref": item_ref("shopify", {"variant_id": "gid://variant/1"}),
    }


class DetectionVariantTests(unittest.TestCase):
    def test_public_detection_is_exhaustive_and_magento_source_is_required(
        self,
    ) -> None:
        detections = [
            DetectedStore(
                origin="https://store.test",
                entry_url="https://store.test/",
                platform="shopify",
                api_origin="https://backend.myshopify.com",
                evidence=("data.shop",),
            ),
            magento_detection("graphql"),
            UnknownStore(
                origin="https://unknown.test",
                entry_url="https://unknown.test/",
                evidence=("No positive platform signal",),
            ),
            StorefrontBotWall(
                origin="https://wall.test",
                entry_url="https://wall.test/",
                evidence=("Cloudflare challenge",),
                system="cloudflare",
                status=403,
            ),
        ]

        public = [public_detection(value) for value in detections]

        self.assertEqual(public[0]["platform"], "shopify")
        self.assertEqual(public[1]["search_source"], "graphql")
        self.assertEqual(set(public[2]), {"kind", "origin", "evidence"})
        self.assertEqual(public[3]["kind"], "bot_wall")

    def test_positive_non_magento_detection_skips_magento_negotiation(self) -> None:
        homepage_response = httpx.Response(
            200,
            text="store",
            request=httpx.Request("GET", "https://store.test/"),
        )
        positive = DetectedStore(
            origin="https://store.test",
            entry_url="https://store.test/",
            platform="shopify",
            api_origin="https://store.test",
            evidence=("data.shop",),
        )
        http = platform_api.Http(httpx.MockTransport(lambda request: homepage_response))
        with (
            mock.patch.object(platform_api.woocommerce, "detect", return_value=None),
            mock.patch.object(platform_api.shopify, "detect", return_value=positive),
            mock.patch.object(platform_api.bigcommerce, "detect", return_value=None),
            mock.patch.object(platform_api.squarespace, "detect", return_value=None),
            mock.patch.object(platform_api.extra, "detect", return_value=None),
            mock.patch.object(platform_api.magento, "detect") as detect_magento,
            http.client,
        ):
            detection = platform_api.detect_store(http, "store.test")

        self.assertEqual(detection, positive)
        detect_magento.assert_not_called()

    def test_all_strong_platform_detectors_run_before_magento(self) -> None:
        calls: list[str] = []
        homepage_response = httpx.Response(
            200,
            text="store",
            request=httpx.Request("GET", "https://store.test/"),
        )
        http = platform_api.Http(httpx.MockTransport(lambda request: homepage_response))

        def no_detection(name: str) -> Any:
            calls.append(name)
            return None

        with (
            mock.patch.object(
                platform_api.woocommerce,
                "detect",
                side_effect=lambda *args: no_detection("woocommerce"),
            ),
            mock.patch.object(
                platform_api.shopify,
                "detect",
                side_effect=lambda *args: no_detection("shopify"),
            ),
            mock.patch.object(
                platform_api.bigcommerce,
                "detect",
                side_effect=lambda *args: no_detection("bigcommerce"),
            ),
            mock.patch.object(
                platform_api.squarespace,
                "detect",
                side_effect=lambda *args: no_detection("squarespace"),
            ),
            mock.patch.object(
                platform_api.extra,
                "detect",
                side_effect=lambda *args: no_detection("extra"),
            ),
            mock.patch.object(
                platform_api.magento,
                "detect",
                side_effect=lambda *args: no_detection("magento"),
            ),
            http.client,
        ):
            platform_api.detect_store(http, "store.test")

        self.assertEqual(
            calls,
            [
                "woocommerce",
                "shopify",
                "bigcommerce",
                "squarespace",
                "extra",
                "magento",
            ],
        )


class MagentoNegotiationTests(unittest.TestCase):
    def test_usable_products_capability_selects_graphql_without_creating_cart(
        self,
    ) -> None:
        requests: list[tuple[str, str, dict[str, Any]]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            requests.append((request.method, request.url.path, payload))
            return response(
                request,
                json_value={
                    "data": {
                        "storeConfig": {"base_url": "https://magento.test/"},
                        "products": {"total_count": 0},
                    }
                },
            )

        http = magento.Http(httpx.MockTransport(handler))
        with http.client:
            detected = magento.detect(
                http,
                "https://magento.test",
                "https://magento.test/",
                homepage(),
            )

        self.assertIsInstance(detected, MagentoDetectedStore)
        self.assertEqual(detected.search_source, "graphql")
        self.assertEqual(
            [(method, path) for method, path, _ in requests], [("POST", "/graphql")]
        )
        query = requests[0][2]["query"]
        self.assertIn("storeConfig", query)
        self.assertIn(
            'products(search: "__codex_platform_probe__", pageSize: 1)', query
        )

    def test_homepage_proof_and_unavailable_graphql_select_html(self) -> None:
        for status in (400, 401, 403, 404, 405, 422):
            with self.subTest(status=status):
                http = magento.Http(
                    httpx.MockTransport(
                        lambda request, status=status: response(request, status)
                    )
                )
                with http.client:
                    detected = magento.detect(
                        http,
                        "https://magento.test",
                        "https://magento.test/",
                        homepage(b'<script type="text/x-magento-init">{}</script>'),
                    )
                self.assertEqual(detected.search_source, "html")

    def test_unavailable_graphql_without_independent_proof_is_not_detection(
        self,
    ) -> None:
        http = magento.Http(httpx.MockTransport(lambda request: response(request, 403)))
        with http.client:
            detected = magento.detect(
                http,
                "https://magento.test",
                "https://magento.test/",
                homepage(),
            )
        self.assertIsNone(detected)

    def test_transport_failure_without_independent_proof_fails_loudly(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("offline", request=request)

        http = magento.Http(httpx.MockTransport(handler))
        with http.client, self.assertRaisesRegex(ToolError, "ConnectError"):
            magento.detect(
                http,
                "https://magento.test",
                "https://magento.test/",
                homepage(),
            )

    def test_usable_products_data_wins_over_graphql_errors(self) -> None:
        http = magento.Http(
            httpx.MockTransport(
                lambda request: response(
                    request,
                    json_value={
                        "data": {
                            "storeConfig": {"base_url": "https://magento.test/"},
                            "products": {"total_count": 0},
                        },
                        "errors": [{"message": "non-fatal extension error"}],
                    },
                )
            )
        )
        with http.client:
            detected = magento.detect(
                http,
                "https://magento.test",
                "https://magento.test/",
                homepage(),
            )
        self.assertEqual(detected.search_source, "graphql")

    def test_transient_negotiation_status_fails_loudly(self) -> None:
        for status in (302, 429, 500, 503):
            with self.subTest(status=status):
                http = magento.Http(
                    httpx.MockTransport(
                        lambda request, status=status: response(request, status)
                    )
                )
                with (
                    http.client,
                    self.assertRaisesRegex(ToolError, "capability query"),
                ):
                    magento.detect(
                        http,
                        "https://magento.test",
                        "https://magento.test/",
                        homepage(b'<script type="text/x-magento-init">{}</script>'),
                    )

    def test_transient_status_without_platform_proof_still_fails_loudly(self) -> None:
        http = magento.Http(httpx.MockTransport(lambda request: response(request, 503)))
        with http.client, self.assertRaisesRegex(ToolError, "capability query"):
            magento.detect(
                http,
                "https://magento.test",
                "https://magento.test/",
                homepage(),
            )

    def test_same_response_config_does_not_replace_independent_error_proof(
        self,
    ) -> None:
        http = magento.Http(
            httpx.MockTransport(
                lambda request: response(
                    request,
                    json_value={
                        "data": {
                            "storeConfig": {"base_url": "https://magento.test/"},
                            "products": None,
                        },
                        "errors": [{"message": "Product search unavailable"}],
                    },
                )
            )
        )
        with http.client, self.assertRaisesRegex(ToolError, "independent proof"):
            magento.detect(
                http,
                "https://magento.test",
                "https://magento.test/",
                homepage(),
            )

    def test_contradictory_proven_magento_shape_fails_loudly(self) -> None:
        http = magento.Http(
            httpx.MockTransport(
                lambda request: response(
                    request,
                    json_value={
                        "data": {
                            "storeConfig": {"base_url": "https://magento.test/"},
                            "products": {"total_count": "many"},
                        }
                    },
                )
            )
        )
        with http.client, self.assertRaisesRegex(ToolError, "contradictory"):
            magento.detect(
                http,
                "https://magento.test",
                "https://magento.test/",
                homepage(),
            )


class MagentoStrategyTests(unittest.TestCase):
    def test_html_detection_runs_only_html_search(self) -> None:
        paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            return response(request, content=b"<html></html>")

        http = magento.Http(httpx.MockTransport(handler))
        with http.client:
            result = magento.search(http, magento_detection("html"), "bearing")

        self.assertEqual(result["source"], "html")
        self.assertEqual(paths, ["/catalogsearch/result"])

    def test_graphql_detection_never_switches_to_html(self) -> None:
        paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            return response(request, 403)

        http = magento.Http(httpx.MockTransport(handler))
        with http.client:
            result = magento.search(http, magento_detection("graphql"), "bearing")

        self.assertEqual(result["kind"], "gated")
        self.assertEqual(paths, ["/graphql"])


class ClosedResultTests(unittest.TestCase):
    def test_search_context_serializes_only_named_platform_fields(self) -> None:
        result = search_result(ShopifySearch(), "valve", [shopify_item()])
        self.assertEqual(
            set(result), {"kind", "operation", "platform", "query", "items"}
        )

    def test_magento_search_requires_detection_selected_source(self) -> None:
        result = search_result(
            MagentoSearch(
                source="html", api_errors=(), configurable_products_omitted=0
            ),
            "valve",
            [],
        )
        self.assertEqual(result["source"], "html")
        self.assertEqual(result["api_errors"], [])

    def test_quote_and_shipping_contexts_have_exact_keys(self) -> None:
        option = shipping_option(
            ShopifyShipping(code=None, description=None),
            "ground",
            "Ground",
            "delivery",
            money("4", "USD"),
        )
        result = quote_outcome(ShopifyQuote(), [option], money("10", "USD"))
        self.assertEqual(
            set(option),
            {"id", "title", "disposition", "amount", "code", "description"},
        )
        self.assertEqual(
            set(result),
            {
                "kind",
                "operation",
                "platform",
                "shipping_options",
                "rates",
                "subtotal",
                "destination",
            },
        )

    def test_validator_rejects_unknown_keys_for_known_platform(self) -> None:
        result = search_result(ShopifySearch(), "valve", [shopify_item()])
        result["override"] = True
        with self.assertRaisesRegex(ToolError, "exact keys"):
            validate_result(result)

    def test_validator_rejects_unknown_or_invalid_search_item_fields(self) -> None:
        product = shopify_item()
        product["raw_response"] = "unsafe"
        with self.assertRaisesRegex(ToolError, "exact keys"):
            search_result(ShopifySearch(), "valve", [product])

        product = shopify_item()
        product["available"] = "yes"
        with self.assertRaisesRegex(ToolError, "invalid values"):
            search_result(ShopifySearch(), "valve", [product])

        product = shopify_item()
        product["item_ref"] = item_ref("shopify", {"product_id": "wrong"})
        with self.assertRaisesRegex(ToolError, "invalid item_ref payload"):
            search_result(ShopifySearch(), "valve", [product])

    def test_validator_rejects_invalid_platform_field_values(self) -> None:
        magento_result = search_result(
            MagentoSearch(
                source="html", api_errors=(), configurable_products_omitted=0
            ),
            "valve",
            [],
        )
        magento_result["source"] = "bogus"
        with self.assertRaisesRegex(ToolError, "invalid platform fields"):
            validate_result(magento_result)

        shopify_option = shipping_option(
            ShopifyShipping(code=None, description=None),
            "ground",
            "Ground",
            "delivery",
            money("4", "USD"),
        )
        shopify_result = quote_outcome(
            ShopifyQuote(), [shopify_option], money("10", "USD")
        )
        shopify_option["code"] = 123
        with self.assertRaisesRegex(ToolError, "invalid shipping option"):
            validate_result(shopify_result)

        squarespace_option = shipping_option(
            SquarespaceShipping(),
            "ground",
            "Ground",
            "delivery",
            money("4", "USD"),
        )
        squarespace_result = quote_outcome(
            SquarespaceQuote(shipping_options_status="APPLICABLE_SHIPPING_OPTIONS"),
            [squarespace_option],
            money("10", "USD"),
        )
        squarespace_result["shipping_options_status"] = "bogus"
        with self.assertRaisesRegex(ToolError, "invalid platform fields"):
            validate_result(squarespace_result)


class WooCommerceDetectionTests(unittest.TestCase):
    def test_detection_uses_only_the_read_only_product_capability(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return response(request, json_value=[])

        http = woocommerce.Http(httpx.MockTransport(handler))
        with http.client:
            detection = woocommerce.detect(
                http,
                "https://woo.test",
                "https://woo.test/",
            )

        self.assertIsInstance(detection, DetectedStore)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].method, "GET")
        self.assertEqual(requests[0].url.path, "/wp-json/wc/store/v1/products")
        self.assertEqual(
            dict(requests[0].url.params),
            {"search": "__codex_platform_probe__", "per_page": "1"},
        )
        self.assertNotIn("cart", str(requests[0].url))

    def test_product_capability_wall_is_an_explicit_detection_wall(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                403,
                headers={"server": "cloudflare", "cf-mitigated": "challenge"},
                content=b"challenge",
                request=request,
            )

        http = woocommerce.Http(httpx.MockTransport(handler))
        with http.client:
            detection = woocommerce.detect(
                http,
                "https://woo.test",
                "https://woo.test/",
            )

        self.assertIsInstance(detection, StorefrontBotWall)


if __name__ == "__main__":
    unittest.main()
