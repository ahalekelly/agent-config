#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "cryptography>=45,<47",
#   "httpx>=0.28,<0.29",
# ]
# ///

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import httpx


ROOT = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(ROOT))

import platform_api
from platform_api_core import Detection, Http, ToolError, option, quote_result, redact_url
from platforms import extra


def response(request: httpx.Request, value: object, *, headers: dict[str, str] | None = None, cookies: list[str] | None = None) -> httpx.Response:
    raw_headers = [("Content-Type", "application/json"), *((name, item) for name, item in (headers or {}).items())]
    raw_headers.extend(("Set-Cookie", item) for item in cookies or [])
    return httpx.Response(200, json=value, headers=raw_headers, request=request)


class ResultTests(unittest.TestCase):
    def test_exhaustive_statuses_and_all_options(self) -> None:
        options = [
            option("ground", "Ground", "delivery", {"amount": "9.00", "currency": "USD"}),
            option("desk", "Collect", "pickup", {"amount": "0.00", "currency": "USD"}),
            option("later", "Paid later", "paid_later", {"amount": "0.00", "currency": "USD"}),
            option("bad", "Unavailable", "unavailable", None),
        ]
        result = quote_result("quoted", "test", options)
        self.assertEqual([item["id"] for item in result["shipping_options"]], ["ground", "desk", "later", "bad"])
        self.assertEqual(result["delivery_rates"], [{"option_id": "ground", "title": "Ground", "amount": {"amount": "9.00", "currency": "USD"}}])
        for status in ("no_quote", "fallback", "gated", "bot_wall", "unsupported", "api_error"):
            result = quote_result(status, "test", reason=status)
            self.assertEqual(result["status"], status)
        with self.assertRaises(ToolError):
            quote_result("surprise", "test")  # type: ignore[arg-type]

    def test_detection_union_and_secret_paths_are_exhaustive(self) -> None:
        with self.assertRaisesRegex(ToolError, "unknown detection state"):
            Detection("surprise", "https://store.test", None, None, ())  # type: ignore[arg-type]
        with self.assertRaisesRegex(ToolError, "supported platform"):
            Detection("detected", "https://store.test", "mystery", "https://store.test", ())
        redacted = redact_url(
            "https://store.test/wp-json/wc/store/v1/cart/items/item-secret?token=query-secret"
        )
        self.assertNotIn("item-secret", redacted)
        self.assertNotIn("query-secret", redacted)

    def test_corpus_api_error_preserves_identity_and_resumes(self) -> None:
        calls = 0
        real_single = platform_api.single

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("offline", request=request)

        def offline_single(command: str, store: str, value: str) -> dict[str, object]:
            nonlocal calls
            calls += 1
            workflow = platform_api.new_workflow(httpx.MockTransport(handler))
            return real_single(command, store, value, workflow=workflow)

        entry = {"store": "https://127.0.0.1:9", "query": "bearing"}
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "corpus.json"
            output_path = Path(directory) / "results.jsonl"
            input_path.write_text(json.dumps([entry, entry]))
            with mock.patch.object(platform_api, "single", side_effect=offline_single):
                self.assertEqual(platform_api.corpus(input_path, output_path), 1)
                self.assertEqual(platform_api.corpus(input_path, output_path), 0)
            rows = [json.loads(line) for line in output_path.read_text().splitlines()]

        self.assertEqual(calls, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["input"], entry)
        self.assertEqual(rows[0]["result"]["status"], "api_error")

    def test_invalid_store_cli_emits_one_api_error_document(self) -> None:
        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", ["platform_api.py", "detect", "http://store.test"]):
            with redirect_stdout(stdout):
                exit_code = platform_api.main()

        lines = stdout.getvalue().splitlines()
        self.assertEqual(exit_code, 1)
        self.assertEqual(len(lines), 1)
        result = json.loads(lines[0])
        self.assertEqual(result["result"]["status"], "api_error")
        self.assertIn("absolute HTTPS origin", result["result"]["reason"])

    def test_woocommerce_html_requires_store_api_confirmation(self) -> None:
        def detect(markup: str) -> Detection:
            def handler(request: httpx.Request) -> httpx.Response:
                if request.url.path == "/":
                    return httpx.Response(200, text=markup, request=request)
                if request.url.path == "/wp-json/wc/store/v1/cart":
                    return httpx.Response(403, request=request)
                return httpx.Response(404, request=request)

            workflow = platform_api.new_workflow(httpx.MockTransport(handler))
            with workflow.http.client:
                return workflow.detect("https://store.test")

        woo = '<link href="/wp-content/plugins/woocommerce/assets/store.css">'
        self.assertEqual(detect(woo).state, "unknown")

        ecwid = detect(woo + '<script src="https://app.ecwid.com/script.js?123"></script>')
        self.assertEqual(ecwid.state, "detected")
        self.assertEqual(ecwid.platform, "ecwid")

    def test_http_sends_fingerprint_chromium_user_agent(self) -> None:
        expected = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.headers["user-agent"], expected)
            return httpx.Response(200, request=request)

        http = Http(httpx.MockTransport(handler))
        with http.client:
            http.request("GET", "https://store.test/")


class SquarespaceTests(unittest.TestCase):
    def test_exact_address_deduped_products_and_distinct_statuses(self) -> None:
        address = None
        add = None
        shipping_status = "POSTAL_CODE_NOT_APPLICABLE"

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal address, add
            if request.url.path == "/":
                return httpx.Response(
                    200,
                    text='<nav data-content-field="navigation"><a href="/shop">Shop</a><a href="/sale">Sale</a></nav>',
                    request=request,
                )
            if request.url.path in {"/shop", "/sale"}:
                return response(
                    request,
                    {"website": {"id": "site"}, "items": [{"id": "item", "title": "Bearing", "fullUrl": "/p/bearing", "variants": [{"sku": "BRG-1", "priceMoney": {"value": "18.00", "currency": "USD"}, "unlimited": True}]}]},
                    cookies=["crumb=crumb-value; Path=/; Secure"],
                )
            if request.url.path == "/api/commerce/shopping-cart/entries":
                add = json.loads(request.content)
                return response(request, {"shoppingCart": {"cartToken": "ephemeral-cart"}})
            if request.url.path.endswith("/shipping/location"):
                address = json.loads(request.content)
                return response(request, {"shippingOptionsStatus": shipping_status, "fulfillmentOptions": []})
            raise AssertionError(request.url)

        http = Http(httpx.MockTransport(handler))
        detection = Detection("detected", "https://store.test", "squarespace", "https://store.test", ("squarespace_html",))
        with http.client:
            catalog = extra.squarespace_products(http, detection, "BRG-1")
            result = extra.squarespace_quote(http, detection, catalog["items"][0]["item_ref"])
        self.assertEqual(len(catalog["items"]), 1)
        self.assertEqual(add["additionalFields"], None)
        self.assertEqual(address, extra.SQUARESPACE_ADDRESS)
        self.assertEqual(address["line2"], "Pacific Prototyping LLC")
        self.assertEqual(result["status"], "no_quote")
        self.assertEqual(result["reason"], "postal_code_not_applicable")

        shipping_status = "SHIPPING_NOT_REQUIRED"
        http = Http(httpx.MockTransport(handler))
        with http.client:
            result = extra.squarespace_quote(http, detection, catalog["items"][0]["item_ref"])
        self.assertEqual(result["status"], "no_quote")
        self.assertEqual(result["reason"], "shipping_not_required")

    def test_preserves_and_dedupes_delivery_and_pickup(self) -> None:
        payload = {
            "shippingOptionsStatus": "APPLICABLE_SHIPPING_OPTIONS",
            "subtotal": {"decimalValue": "20.00", "currencyCode": "USD"},
            "fulfillmentOptions": [
                {"key": "ground", "name": "Ground", "price": {"decimalValue": "7.00", "currencyCode": "USD"}, "isPickup": False},
                {"key": "ground", "name": "Ground", "price": {"decimalValue": "7.00", "currencyCode": "USD"}, "isPickup": False},
                {"key": "pickup", "name": "Pickup", "price": {"decimalValue": "0.00", "currencyCode": "USD"}, "isPickup": True},
            ],
        }

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/shop":
                return response(request, {}, cookies=["crumb=crumb-value; Path=/; Secure"])
            if request.url.path == "/api/commerce/shopping-cart/entries":
                return response(request, {"shoppingCart": {"cartToken": "ephemeral-cart"}})
            if request.url.path.endswith("/shipping/location"):
                return response(request, payload)
            raise AssertionError(request.url)

        http = Http(httpx.MockTransport(handler))
        detection = Detection("detected", "https://store.test", "squarespace", "https://store.test", ("squarespace_html",))
        reference = __import__("platform_api_core").item_ref("squarespace", {"collection": "https://store.test/shop", "item_id": "item", "sku": "BRG"})
        with http.client:
            result = extra.squarespace_quote(http, detection, reference)
        self.assertEqual(result["status"], "quoted")
        self.assertEqual([item["disposition"] for item in result["shipping_options"]], ["delivery", "pickup"])
        self.assertEqual(len(result["delivery_rates"]), 1)


class ProductOnlyPlatformTests(unittest.TestCase):
    def test_wix_product_path_and_quote_boundary(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/":
                return httpx.Response(
                    200,
                    text=r'{"accessTokensUrl":"https:\/\/store.test\/_api\/v1\/access-tokens"}',
                    request=request,
                )
            if request.url.path == "/_api/v1/access-tokens":
                return response(request, {"apps": {extra.WIX_ECOM_APP: {"accessToken": "ephemeral"}}})
            if request.url.path.endswith("/products/query"):
                self.assertEqual(request.headers["authorization"], "ephemeral")
                return response(request, {"products": [{"id": "p1", "name": "Wheel", "sku": "W-1", "slug": "wheel", "stock": {"inStock": True}, "priceData": {"price": 12.5, "currency": "USD"}}]})
            raise AssertionError(request.url)

        http = Http(httpx.MockTransport(handler))
        detection = Detection("detected", "https://store.test", "wix", "https://store.test", ("wix_html",))
        with http.client:
            catalog = extra.wix_products(http, detection, "wheel")
            result = extra.quote(http, detection, catalog["items"][0]["item_ref"])
        self.assertEqual(catalog["items"][0]["sku"], "W-1")
        self.assertEqual(result["status"], "unsupported")

    def test_ecwid_product_path_and_quote_boundary(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "store.test":
                return httpx.Response(200, text='<script src="https://app.ecwid.com/script.js?123"></script>', request=request)
            if request.url.path == "/script.js":
                return httpx.Response(200, text='{"apiBaseUrl":"https://storefront.example/api"}', request=request)
            if request.url.path.endswith("/initial-data"):
                return response(request, {"storeProfile": {"value": {
                    "formats": {"currencyFormat": {"currencyCode": "USD"}},
                    "integrations": {"apps": {"publicTokens": {"ecwid-storefront": "ephemeral"}}},
                }}})
            if request.url.path.endswith("/products"):
                self.assertNotIn("ephemeral", str(http.evidence))
                return response(request, {"items": [
                    {"enabled": False},
                    {"id": 7, "name": "Bearing", "sku": "B-7", "enabled": True, "inStock": True, "price": 9.5, "url": "https://store.test/bearing"},
                ]})
            raise AssertionError(request.url)

        http = Http(httpx.MockTransport(handler))
        detection = Detection("detected", "https://store.test", "ecwid", "https://store.test", ("ecwid_script",))
        with http.client:
            catalog = extra.ecwid_products(http, detection, "bearing")
            result = extra.quote(http, detection, catalog["items"][0]["item_ref"])
        self.assertEqual(catalog["items"][0]["sku"], "B-7")
        self.assertEqual(result["status"], "unsupported")

    def test_sfcc_search_show_path_and_quote_boundary(self) -> None:
        homepage = '<form action="/on/demandware.store/Sites-Test-Site/en_US/Search-Show"><input name="q"></form>'
        results = '<script src="/on/demandware.static/theme.js"></script><div class="product" data-pid="P-RED"><a href="/product/p.html?dwvar_P_color=red"><img alt="Red Product"></a></div>'

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/":
                return httpx.Response(200, text=homepage, request=request)
            self.assertEqual(request.url.params["q"], "red")
            return httpx.Response(200, text=results, request=request)

        http = Http(httpx.MockTransport(handler))
        detection = Detection("detected", "https://store.test", "sfcc", "https://store.test", ("sfcc_html",))
        with http.client:
            catalog = extra.sfcc_products(http, detection, "red")
            result = extra.quote(http, detection, catalog["items"][0]["item_ref"])
        self.assertEqual(catalog["items"][0]["sku"], "P-RED")
        self.assertEqual(result["status"], "unsupported")


if __name__ == "__main__":
    unittest.main()
