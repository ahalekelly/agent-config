# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.28,<0.29"]
# ///

from __future__ import annotations

import importlib
import json
import sys
import unittest
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).parents[1]
FIXTURES = Path(__file__).parents[2] / "tests" / "fixtures"
sys.path.insert(0, str(ROOT / "scripts"))

core = importlib.import_module("platform_api_core")
magento = importlib.import_module("platforms.magento")
Detection = core.Detection
Http = core.Http
ToolError = core.ToolError
parse_item_ref = core.parse_item_ref


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def fixture_json(name: str) -> Any:
    return json.loads(fixture(name))


def response(
    request: httpx.Request,
    status: int = 200,
    *,
    json_value: Any = None,
    content: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    if content is not None:
        return httpx.Response(status, content=content, headers=headers, request=request)
    return httpx.Response(status, json=json_value, headers=headers, request=request)


def detection() -> Detection:
    return Detection(
        kind="detected",
        origin="https://magento.test",
        entry_url="https://magento.test/",
        platform="magento",
        api_origin="https://magento.test",
        evidence=("magento_guest_cart_response",),
    )


class MagentoDetectionTests(unittest.TestCase):
    def homepage(self, content: bytes = b"<html></html>") -> httpx.Response:
        request = httpx.Request("GET", "https://magento.test/")
        return response(request, content=content)

    def test_guest_cart_token_is_positive_evidence(self) -> None:
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            return response(request, json_value="guest-token-secret-1234567890")

        http = Http(httpx.MockTransport(handler))
        with http.client:
            result = magento.detect(
                http,
                "https://magento.test",
                "https://magento.test/",
                self.homepage(),
            )

        self.assertEqual(result.platform, "magento")
        self.assertEqual(result.evidence, ("magento_guest_cart_token",))
        self.assertEqual(calls, ["/rest/V1/guest-carts"])

    def test_magento_guest_cart_error_shape_is_positive_evidence(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return response(
                request,
                400,
                json_value={"message": "The request is invalid.", "parameters": []},
            )

        http = Http(httpx.MockTransport(handler))
        with http.client:
            result = magento.detect(
                http,
                "https://magento.test",
                "https://magento.test/",
                self.homepage(),
            )

        self.assertEqual(result.evidence, ("magento_guest_cart_error",))

    def test_graphql_store_config_is_positive_evidence(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/rest/V1/guest-carts":
                return response(request, 404)
            return response(
                request,
                json_value={
                    "data": {"storeConfig": {"base_url": "https://magento.test/"}}
                },
            )

        http = Http(httpx.MockTransport(handler))
        with http.client:
            result = magento.detect(
                http,
                "https://magento.test",
                "https://magento.test/",
                self.homepage(),
            )

        self.assertEqual(result.evidence, ("magento_graphql_store_config",))

    def test_generic_denials_without_magento_marker_do_not_detect(self) -> None:
        http = Http(
            httpx.MockTransport(
                lambda request: response(request, 403, content=b"Forbidden")
            )
        )
        with http.client:
            result = magento.detect(
                http,
                "https://magento.test",
                "https://magento.test/",
                self.homepage(b'<input name="form_key" value="not-platform-specific">'),
            )

        self.assertIsNone(result)

    def test_homepage_marker_survives_denied_probes(self) -> None:
        http = Http(
            httpx.MockTransport(
                lambda request: response(request, 403, content=b"Forbidden")
            )
        )
        with http.client:
            result = magento.detect(
                http,
                "https://magento.test",
                "https://magento.test/",
                self.homepage(b'<script type="text/x-magento-init">{}</script>'),
            )

        self.assertEqual(result.evidence, ("magento_x_magento_init",))


class MagentoSearchTests(unittest.TestCase):
    def test_narrow_search_then_exact_detail_preserves_partial_errors(self) -> None:
        calls: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            calls.append(body)
            query = body["query"]
            if "ProductSearch" in query:
                self.assertNotIn("variants", query)
                self.assertEqual(body["variables"], {"search": "bearing"})
                return response(
                    request, content=fixture("platform-magento-search-partial.json")
                )
            self.assertIn("filter: {sku: {eq: $sku}}", query)
            sku = body["variables"]["sku"]
            if sku == "BRG-PARENT":
                return response(
                    request, content=fixture("platform-magento-detail-partial.json")
                )
            if sku == "BRG-1":
                return response(
                    request,
                    json_value={
                        "data": {
                            "storeConfig": {
                                "base_url": "https://magento.test/",
                                "product_url_suffix": ".html",
                                "base_currency_code": "USD",
                            },
                            "products": {
                                "items": [
                                    {
                                        "__typename": "SimpleProduct",
                                        "name": "Bearing",
                                        "sku": "BRG-1",
                                        "stock_status": "IN_STOCK",
                                        "url_key": "bearing",
                                        "price_range": {
                                            "minimum_price": {
                                                "final_price": {
                                                    "value": 2.5,
                                                    "currency": "USD",
                                                },
                                                "regular_price": {
                                                    "value": 3,
                                                    "currency": "USD",
                                                },
                                            }
                                        },
                                    }
                                ]
                            },
                        }
                    },
                )
            raise AssertionError(sku)

        http = Http(httpx.MockTransport(handler))
        with http.client:
            result = magento.search(http, detection(), "bearing")

        self.assertEqual(
            [item["sku"] for item in result["items"]], ["BRG-1", "BRG-STEEL"]
        )
        self.assertEqual(
            parse_item_ref(result["items"][1]["item_ref"], "magento"),
            {"sku": "BRG-STEEL"},
        )
        self.assertEqual(
            result["items"][0]["compare_at_price"], {"amount": "3", "currency": "USD"}
        )
        self.assertEqual(
            result["items"][1]["options"],
            [{"code": "material", "label": "Steel", "value": 7}],
        )
        self.assertEqual(len(result["api_errors"]), 2)
        self.assertEqual(len(calls), 3)

    def test_graphql_denial_falls_back_to_bounded_same_origin_html(self) -> None:
        fetched: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            fetched.append(str(request.url))
            if request.url.path == "/graphql":
                return response(request, 403, content=b"Forbidden")
            if request.url.path == "/catalogsearch/result/":
                self.assertEqual(request.url.params["q"], "bearing")
                return response(
                    request, content=fixture("platform-magento-search.html")
                )
            if request.url.path == "/configurable-bearing.html":
                return response(
                    request,
                    content=fixture("platform-magento-product-configurable.html"),
                )
            if request.url.path == "/simple-bearing.html":
                return response(
                    request, content=fixture("platform-magento-product-simple.html")
                )
            if request.url.path == "/removed-bearing.html":
                self.assertFalse(request.url.query)
                return response(request, 404)
            raise AssertionError(request.url)

        http = Http(httpx.MockTransport(handler))
        with http.client:
            result = magento.search(http, detection(), "bearing")

        self.assertEqual(result["kind"], "search")
        self.assertEqual(result["source"], "html")
        self.assertEqual(
            [(item["sku"], item["available"]) for item in result["items"]],
            [("BRG-STEEL", True), ("BRG-BRONZE", False), ("BRG-SIMPLE", True)],
        )
        self.assertEqual(
            result["items"][2]["price"], {"amount": "6.25", "currency": "USD"}
        )
        self.assertFalse(
            any("other.test" in url or "mailto:" in url for url in fetched)
        )

    def test_html_denial_after_graphql_failure_is_gated(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/graphql":
                return response(request, 404)
            if request.url.path == "/catalogsearch/result/":
                return response(request, 403, content=b"Forbidden")
            raise AssertionError(request.url)

        http = Http(httpx.MockTransport(handler))
        with http.client:
            result = magento.search(http, detection(), "bearing")

        self.assertEqual(result["kind"], "gated")
        self.assertEqual(result["endpoint"], "/catalogsearch/result/")

    def test_html_challenge_is_bot_wall(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/graphql":
                return response(request, 404)
            return response(
                request,
                403,
                content=b'<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>',
            )

        http = Http(httpx.MockTransport(handler))
        with http.client:
            result = magento.search(http, detection(), "bearing")

        self.assertEqual(result["kind"], "bot_wall")
        self.assertEqual(result["system"], "cloudflare")


class MagentoQuoteTests(unittest.TestCase):
    def handler(self, rates: list[dict[str, Any]] | None = None):
        token = "guest-token-secret-1234567890"
        calls: list[tuple[str, str]] = []
        quote_rates = (
            fixture_json("platform-magento-rates.json") if rates is None else rates
        )

        def handle(request: httpx.Request) -> httpx.Response:
            calls.append((request.method, request.url.path))
            if request.url.path == "/rest/V1/guest-carts":
                return response(request, json_value=token)
            if request.url.path.endswith("/items"):
                body = json.loads(request.content)
                self.assertEqual(
                    body,
                    {"cartItem": {"sku": "BRG-STEEL", "qty": 1, "quote_id": token}},
                )
                return response(
                    request,
                    json_value={
                        "sku": "BRG-STEEL",
                        "name": "Configurable Bearing - Steel",
                        "qty": 1,
                        "price": 3.95,
                    },
                )
            if request.url.path.endswith("/totals"):
                return response(
                    request, content=fixture("platform-magento-totals.json")
                )
            if request.url.path.endswith("/estimate-shipping-methods"):
                body = json.loads(request.content)
                self.assertEqual(body["address"]["region_id"], 12)
                return response(request, json_value=quote_rates)
            raise AssertionError(request.url)

        return handle, calls, token

    def test_exact_sku_cart_totals_currency_and_rate_dispositions(self) -> None:
        handler, calls, token = self.handler()
        http = Http(httpx.MockTransport(handler))
        reference = magento.item_ref("magento", {"sku": "BRG-STEEL"})
        with http.client:
            result = magento.quote(http, detection(), reference)

        self.assertEqual(result["kind"], "quote")
        self.assertEqual(result["subtotal"], {"amount": "3.95", "currency": "USD"})
        self.assertEqual(result["base_subtotal"], {"amount": "3.95", "currency": "USD"})
        self.assertEqual(
            [option["disposition"] for option in result["shipping_options"]],
            ["delivery", "pickup", "paid_later", "unavailable"],
        )
        self.assertEqual(
            result["rates"],
            [
                {
                    "option_id": "freeshipping/freeshipping",
                    "title": "Free Shipping — Free Shipping",
                    "amount": {"amount": "0", "currency": "USD"},
                }
            ],
        )
        self.assertIn(("GET", f"/rest/V1/guest-carts/{token}/totals"), calls)
        self.assertNotIn(token, json.dumps(http.evidence))

    def test_empty_rate_array_is_not_free_shipping(self) -> None:
        handler, _, _ = self.handler(fixture_json("platform-magento-empty.json"))
        http = Http(httpx.MockTransport(handler))
        with http.client:
            result = magento.quote(
                http, detection(), magento.item_ref("magento", {"sku": "BRG-STEEL"})
            )

        self.assertEqual(result["kind"], "empty")
        self.assertEqual(result["reason"], "empty_rate_list")
        self.assertEqual(result["rates"], [])
        self.assertEqual(result["subtotal"]["currency"], "USD")

    def test_noncomparable_options_are_preserved_but_not_quoted(self) -> None:
        rates = fixture_json("platform-magento-rates.json")[1:]
        handler, _, _ = self.handler(rates)
        http = Http(httpx.MockTransport(handler))
        with http.client:
            result = magento.quote(
                http, detection(), magento.item_ref("magento", {"sku": "BRG-STEEL"})
            )

        self.assertEqual(result["kind"], "empty")
        self.assertEqual(result["reason"], "no_comparable_delivery_rate")
        self.assertEqual(len(result["shipping_options"]), 3)

    def test_guest_cart_denial_is_gated_and_challenge_is_bot_wall(self) -> None:
        def denial(response_headers: dict[str, str], response_content: bytes):
            def handle(request: httpx.Request) -> httpx.Response:
                return response(
                    request, 403, content=response_content, headers=response_headers
                )

            return handle

        cases = [
            ({}, b"Forbidden", "gated"),
            ({"cf-mitigated": "challenge"}, b"Just a moment", "bot_wall"),
        ]
        for headers, content, expected in cases:
            with self.subTest(expected=expected):
                http = Http(httpx.MockTransport(denial(headers, content)))
                with http.client:
                    result = magento.quote(
                        http,
                        detection(),
                        magento.item_ref("magento", {"sku": "BRG-STEEL"}),
                    )
                self.assertEqual(result["kind"], expected)

    def test_reference_must_be_exactly_one_sku(self) -> None:
        http = Http(
            httpx.MockTransport(lambda request: self.fail("request must not run"))
        )
        with (
            http.client,
            self.assertRaisesRegex(ToolError, "exactly one nonempty simple SKU"),
        ):
            magento.quote(
                http,
                detection(),
                magento.item_ref("magento", {"sku": "BRG-STEEL", "currency": "USD"}),
            )


if __name__ == "__main__":
    unittest.main()
