#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "cryptography>=45,<47",
#   "httpx>=0.28,<0.29",
# ]
# ///

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import httpx


ROOT = Path(__file__).parents[1] / "scripts"
FIXTURES = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(ROOT))

from platforms import bigcommerce, catalog_common as common, magento  # noqa: E402
import platform_api  # noqa: E402
from platform_api_core import Detection  # noqa: E402


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def response(status: int = 200, *, json_value: Any = None, text: str = "", cookies: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "json": json_value,
        "text": text,
        "headers": {},
        "cookies": cookies or {},
    }


def resolved_product(sku: str, option_value: int) -> dict[str, Any]:
    return {
        "data": {
            "sku": sku,
            "gtin": "012345678905",
            "upc": None,
            "mpn": None,
            "weight": {"value": 0.1, "formatted": "0.10 LBS"},
            "price": {"without_tax": {"value": 3, "currency": "USD"}},
            "selected_attributes": {"25450": option_value},
            "instock": True,
            "purchasable": True,
            "available_to_sell": 8,
        }
    }


class BigCommerceTests(unittest.TestCase):
    def test_workflow_parses_bcdata_after_fifty_kilobytes(self) -> None:
        product = "x" * 60_000 + fixture("bigcommerce-product.html")

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/search.php":
                return httpx.Response(
                    200,
                    text=(
                        '<a class="button product" href="/cart.php?action=add&amp;product_id=32571&amp;attribute[25450]=87167">Add</a>'
                        '<a class="card product" href="/bearing/">Bearing</a>'
                    ),
                    request=request,
                )
            if request.url.path == "/bearing/":
                return httpx.Response(200, text=product, request=request)
            if request.url.path == "/remote/v1/product-attributes/32571":
                return httpx.Response(200, json=resolved_product("BRG-STEEL", 87167), request=request)
            raise AssertionError(request.url)

        workflow = platform_api.new_workflow(httpx.MockTransport(handler))
        detection = Detection(
            "detected",
            "https://bc.test",
            "bigcommerce",
            "https://bc.test",
            ("bigcommerce_stencil",),
        )
        with workflow.bigcommerce_products_http.client:
            result = workflow.products(detection, "bearing")

        self.assertEqual(result["items"][0]["sku"], "BRG-STEEL")

    def test_exact_sku_item_ref_stays_identical_through_cart_and_consignment(self) -> None:
        checkout = json.loads(fixture("bigcommerce-checkout.json"))

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/":
                return httpx.Response(
                    200,
                    text='<link href="https://cdn11.bigcommerce.com/s-store/theme.css">',
                    headers={"Set-Cookie": "detection-poison=1; Path=/; Secure"},
                    request=request,
                )
            if request.url.path in {"/wp-json/wc/store/v1/cart", "/rest/V1/guest-carts", "/admin"}:
                return httpx.Response(404, request=request)
            if request.url.path == "/search.php":
                self.assertNotIn("detection-poison", request.headers.get("cookie", ""))
                self.assertEqual(request.url.params["search_query"], "BRG-STEEL")
                return httpx.Response(
                    200,
                    text=(
                        '<a class="button product" href="/cart.php?action=add&amp;product_id=32571&amp;attribute[25450]=87167">Add</a>'
                        '<a class="card product" href="/bearing/">Bearing</a>'
                    ),
                    request=request,
                )
            if request.url.path == "/bearing/":
                return httpx.Response(
                    200,
                    text=fixture("bigcommerce-product.html"),
                    headers={"Set-Cookie": "product-session=1; Path=/; Secure"},
                    request=request,
                )
            if request.url.path == "/remote/v1/product-attributes/32571":
                self.assertIn(b"attribute%5B25450%5D=87167", request.content)
                return httpx.Response(200, json=resolved_product("BRG-STEEL", 87167), request=request)
            if request.url.path == "/api/storefront/carts":
                cookie = request.headers.get("cookie", "")
                self.assertNotIn("product-session", cookie)
                self.assertNotIn("detection-poison", cookie)
                return httpx.Response(
                    200,
                    json={
                        "id": "cart-secret",
                        "baseAmount": 3,
                        "currency": {"code": "USD"},
                        "lineItems": {"physicalItems": [{
                            "id": "item-secret",
                            "productId": 32571,
                            "variantId": 42,
                            "sku": "BRG-STEEL",
                            "name": "Bearing - Steel",
                            "quantity": 1,
                            "salePrice": 3,
                            "isShippingRequired": True,
                        }]},
                    },
                    headers=[
                        ("Set-Cookie", "SHOP_SESSION_TOKEN=session-secret; Path=/; Secure"),
                        ("Set-Cookie", "SF-CSRF-TOKEN=csrf-secret; Path=/; Secure"),
                    ],
                    request=request,
                )
            if request.url.path.endswith("/consignments"):
                cookie = request.headers.get("cookie", "")
                self.assertIn("SHOP_SESSION_TOKEN=session-secret", cookie)
                self.assertNotIn("product-session", cookie)
                self.assertNotIn("detection-poison", cookie)
                return httpx.Response(200, json=checkout, request=request)
            raise AssertionError(request.url)

        workflow = platform_api.new_workflow(httpx.MockTransport(handler))
        with (
            workflow.http.client,
            workflow.bigcommerce_products_http.client,
            workflow.bigcommerce_quote_http.client,
        ):
            detection = workflow.detect("https://bc.test")
            catalog = workflow.products(detection, "BRG-STEEL")
            selection = catalog["items"][0]
            result = workflow.quote(detection, selection["item_ref"])

        self.assertEqual(selection["sku"], "BRG-STEEL")
        self.assertEqual(result["status"], "quoted")
        self.assertEqual(result["item"]["sku"], selection["sku"])

    def test_products_filter_mailto_and_expose_real_product_and_options(self) -> None:
        calls = []

        def request(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
            calls.append((method, url, kwargs))
            if url.endswith("/search.php"):
                return response(
                    text='<a class="card product" href="mailto:sales@example.com">Mail</a>'
                    '<a class="button product" href="/cart.php?action=add&amp;product_id=32571&amp;attribute[25450]=87167">Add</a>'
                    '<a class="card product" href="/bearing/">Bearing</a>'
                )
            if url == "https://bc.test/bearing/":
                return response(text=fixture("bigcommerce-product.html"))
            if url == "https://bc.test/remote/v1/product-attributes/32571":
                self.assertEqual(
                    kwargs["data"],
                    {"action": "add", "product_id": "32571", "attribute[25450]": "87167"},
                )
                return response(json_value=resolved_product("BRG-STEEL", 87167))
            raise AssertionError(url)

        result = bigcommerce.products(request, "https://bc.test", "bearing", ["cdn11.bigcommerce.com/s-store"])

        self.assertEqual(len(result["products"]), 1)
        product = result["products"][0]
        self.assertEqual(product["sku"], "BRG-STEEL")
        self.assertEqual(product["barcode"], "012345678905")
        self.assertEqual(product["price"], {"amount": "3", "currency": "USD"})
        self.assertEqual(product["weight"], {"value": "0.1", "formatted": "0.10 LBS"})
        self.assertEqual(product["stock"], 8)
        self.assertEqual(product["options"][0]["values"][0]["value"], 87167)
        self.assertEqual(product["option_selections"], [{"optionId": 25450, "optionValue": 87167}])
        self.assertFalse(product["selection_required"])
        self.assertFalse(any("mailto:" in url for _, url, _ in calls))

    def test_configurable_without_unique_public_mapping_is_selection_required(self) -> None:
        def request(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
            if url.endswith("/search.php"):
                return response(text='<a class="card product" href="/bearing/">Bearing</a>')
            if url == "https://bc.test/bearing/":
                return response(text=fixture("bigcommerce-product.html"))
            raise AssertionError(url)

        result = bigcommerce.products(request, "https://bc.test", "bearing", ["bigcommerce_stencil"])

        product = result["products"][0]
        self.assertTrue(product["selection_required"])
        quote = bigcommerce.quote(
            lambda *args, **kwargs: self.fail("request must not run"),
            "https://bc.test",
            product,
            ["bigcommerce_stencil"],
        )
        self.assertEqual(quote["status"], "unsupported")

    def test_direct_cart_and_consignment_preserve_every_option(self) -> None:
        checkout = json.loads(fixture("bigcommerce-checkout.json"))
        paths = []

        def request(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
            paths.append(url)
            if url.endswith("/api/storefront/carts"):
                self.assertEqual(
                    kwargs["json"]["lineItems"][0]["optionSelections"],
                    [{"optionId": 25450, "optionValue": 87167}],
                )
                return response(
                    json_value={
                        "id": "cart-secret",
                        "baseAmount": 3,
                        "currency": {"code": "USD"},
                        "lineItems": {
                            "physicalItems": [{
                                "id": "item-secret",
                                "productId": 32571,
                                "variantId": 42,
                                "sku": "BRG-STEEL",
                                "name": "Bearing - Steel",
                                "quantity": 1,
                                "salePrice": 3,
                                "isShippingRequired": True,
                            }]
                        },
                    },
                    cookies={"SHOP_SESSION_TOKEN": "session-secret", "SF-CSRF-TOKEN": "csrf-secret"},
                )
            if "/consignments" in url:
                self.assertEqual(kwargs["params"], {"include": "consignments.availableShippingOptions"})
                self.assertEqual(kwargs["json"][0]["address"]["address1"], "747 Howard St")
                self.assertEqual(kwargs["json"][0]["lineItems"], [{"itemId": "item-secret", "quantity": 1}])
                return response(json_value=checkout)
            raise AssertionError(url)

        result = bigcommerce.quote(
            request,
            "https://bc.test",
            {
                "product_id": 32571,
                "sku": "BRG-STEEL",
                "options": [{
                    "option_id": 25450,
                    "label": "Material",
                    "required": True,
                    "values": [{"value": 87167, "label": "Steel", "available": True}],
                }],
                "option_selections": [{"optionId": 25450, "optionValue": 87167}],
            },
            ["x-bc-store-id"],
        )

        self.assertEqual(result["status"], "quoted")
        self.assertEqual(
            [option["disposition"] for option in result["shipping_options"]],
            ["delivery", "pickup", "paid_later", "unavailable", "fallback"],
        )
        self.assertEqual([rate["option_id"] for rate in result["delivery_rates"]], ["delivery"])
        self.assertEqual(result["delivery_rates"][0]["amount"]["amount"], "10")
        self.assertNotIn("/cart.php", " ".join(paths))
        self.assertNotIn("/remote/v1/shipping-quote", " ".join(paths))
        durable = json.dumps(result)
        for secret in ("cart-secret", "item-secret", "session-secret", "csrf-secret"):
            self.assertNotIn(secret, durable)

    def test_cart_sku_must_match_products_sku(self) -> None:
        def request(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
            self.assertTrue(url.endswith("/api/storefront/carts"))
            return response(
                json_value={
                    "id": "cart-secret",
                    "baseAmount": 3,
                    "currency": {"code": "USD"},
                    "lineItems": {"physicalItems": [{
                        "id": "item-secret",
                        "productId": 32571,
                        "sku": "BRG-BRASS",
                        "quantity": 1,
                        "salePrice": 3,
                        "isShippingRequired": True,
                    }]},
                },
                cookies={"SHOP_SESSION_TOKEN": "session-secret", "SF-CSRF-TOKEN": "csrf-secret"},
            )

        result = bigcommerce.quote(
            request,
            "https://bc.test",
            {"product_id": 32571, "sku": "BRG-STEEL", "options": [], "option_selections": []},
            ["x-bc-store-id"],
        )

        self.assertEqual(result["status"], "api_error")
        self.assertEqual(result["evidence"][0], {
            "type": "sku_mismatch",
            "endpoint": "/api/storefront/carts",
            "expected": "BRG-STEEL",
            "actual": "BRG-BRASS",
        })

    def test_required_configuration_is_explicitly_unsupported(self) -> None:
        result = bigcommerce.quote(
            lambda *args, **kwargs: self.fail("request must not run"),
            "https://bc.test",
            {
                "product_id": 32571,
                "sku": "BRG-PARENT",
                "options": [{"option_id": 25450, "label": "Material", "required": True}],
                "option_selections": [],
            },
            ["x-bc-store-id"],
        )
        self.assertEqual(result["status"], "unsupported")

    def test_consignment_denial_is_session_api_error_not_guest_gate(self) -> None:
        def request(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
            if url.endswith("/api/storefront/carts"):
                return response(
                    json_value={
                        "id": "cart-secret",
                        "baseAmount": 3,
                        "currency": {"code": "USD"},
                        "lineItems": {"physicalItems": [{
                            "id": "item-secret",
                            "productId": 32571,
                            "sku": "BRG-1",
                            "quantity": 1,
                            "salePrice": 3,
                            "isShippingRequired": True,
                        }]},
                    },
                    cookies={"SHOP_SESSION_TOKEN": "session-secret", "SF-CSRF-TOKEN": "csrf-secret"},
                )
            if "/consignments" in url:
                return response(403, text="Forbidden")
            raise AssertionError(url)

        result = bigcommerce.quote(
            request,
            "https://bc.test",
            {"product_id": 32571, "sku": "BRG-1", "options": [], "option_selections": []},
            ["x-bc-store-id"],
        )

        self.assertEqual(result["status"], "api_error")
        self.assertEqual(result["evidence"][0]["type"], "session_failure")

    def test_option_selection_must_be_a_returned_available_value(self) -> None:
        base = {
            "product_id": 32571,
            "sku": "BRG-1",
            "options": [{
                "option_id": 25450,
                "label": "Material",
                "required": True,
                "values": [{"value": 87167, "label": "Steel", "available": False}],
            }],
        }
        for value, reason in ((87167, "unavailable"), (99999, "public select/radio")):
            result = bigcommerce.quote(
                lambda *args, **kwargs: self.fail("request must not run"),
                "https://bc.test",
                {**base, "option_selections": [{"optionId": 25450, "optionValue": value}]},
                ["x-bc-store-id"],
            )
            self.assertEqual(result["status"], "unsupported")
            self.assertIn(reason, result["reason"])


class MagentoTests(unittest.TestCase):
    def test_workflow_keeps_later_valid_detail_after_candidate_failure(self) -> None:
        workflow = platform_api.new_workflow(httpx.MockTransport(lambda request: self.fail(str(request.url))))
        detection = Detection(
            "detected",
            "https://magento.test",
            "magento",
            "https://magento.test",
            ("magento_html",),
        )
        found = {
            "candidates": [{"parent_sku": "BAD"}, {"parent_sku": "GOOD"}],
            "evidence": [],
        }
        unsupported = {"status": "unsupported", "platform": "magento", "reason": "bundle"}
        valid = {
            "products": [{
                "type": "SimpleProduct",
                "physical": True,
                "sku": "GOOD-1",
                "available": True,
            }],
            "evidence": [],
        }
        with (
            mock.patch.object(magento, "search", return_value=found),
            mock.patch.object(magento, "product", side_effect=[unsupported, valid]),
        ):
            result = workflow._magento_products(detection, "bearing")

        self.assertEqual([item["sku"] for item in result["items"]], ["GOOD-1"])
        self.assertEqual(result["evidence"][0]["type"], "candidate_failure")

    def test_search_is_lightweight_and_partial_errors_remain_evidence(self) -> None:
        def request(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
            query = kwargs["json"]["query"]
            self.assertNotIn("variants", query)
            return response(
                json_value={
                    "errors": [{"message": "one result failed", "path": ["products", "items", 1]}],
                    "data": {"products": {"items": [{"__typename": "SimpleProduct", "name": "Bearing", "sku": "BRG-1", "stock_status": "IN_STOCK", "url_key": "bearing"}]}},
                }
            )

        result = magento.search(request, "https://magento.test", "bearing", ["x-magento-init"])

        self.assertEqual(result["candidates"][0]["parent_sku"], "BRG-1")
        self.assertEqual(result["evidence"][0]["type"], "api_error")
        self.assertTrue(result["evidence"][0]["partial"])

    def test_selected_parent_detail_returns_only_physical_simple_children(self) -> None:
        payload = json.loads(fixture("magento-detail-partial.json"))

        def request(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
            self.assertIn("variants", kwargs["json"]["query"])
            self.assertEqual(kwargs["json"]["variables"], {"sku": "BRG-PARENT"})
            return response(json_value=payload)

        result = magento.product(request, "https://magento.test", "BRG-PARENT", ["Magento_Catalog"])

        self.assertEqual([product["sku"] for product in result["products"]], ["BRG-STEEL"])
        self.assertEqual(result["products"][0]["options"], [{"code": "material", "label": "Steel", "value": 7}])
        self.assertEqual(result["evidence"][0]["type"], "api_error")

    def test_guest_quote_preserves_pickup_and_unavailable_options(self) -> None:
        rates = json.loads(fixture("magento-rates.json"))

        def request(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
            if url.endswith("/rest/V1/guest-carts"):
                return response(json_value="guest-token-secret")
            if url.endswith("/items"):
                self.assertEqual(kwargs["json"]["cartItem"]["sku"], "BRG-STEEL")
                return response(json_value={"sku": "BRG-STEEL", "name": "Bearing - Steel", "qty": 1, "price": 3.95})
            if url.endswith("/estimate-shipping-methods"):
                return response(json_value=rates)
            raise AssertionError(url)

        result = magento.quote(
            request,
            "https://magento.test",
            {"type": "SimpleProduct", "physical": True, "sku": "BRG-STEEL", "price": {"amount": "3.95", "currency": "USD"}},
            ["Magento_Catalog"],
        )

        self.assertEqual(result["status"], "quoted")
        self.assertEqual(
            [option["disposition"] for option in result["shipping_options"]],
            ["delivery", "pickup", "unavailable"],
        )
        self.assertEqual([rate["option_id"] for rate in result["delivery_rates"]], ["freeshipping/freeshipping"])
        self.assertNotIn("guest-token-secret", json.dumps(result))

    def test_denial_without_independent_marker_is_api_error_not_gated(self) -> None:
        denied_response = response(403, text="Forbidden")
        unknown = magento.search(lambda *args, **kwargs: denied_response, "https://unknown.test", "bearing", [])
        known = magento.search(lambda *args, **kwargs: denied_response, "https://magento.test", "bearing", ["x-magento-init"])
        self.assertEqual(unknown["status"], "api_error")
        self.assertEqual(known["status"], "gated")


class ContractTests(unittest.TestCase):
    def test_quote_terminal_status_set_is_exact(self) -> None:
        self.assertEqual(
            common.QUOTE_STATUSES,
            {"quoted", "no_quote", "fallback", "gated", "bot_wall", "unsupported", "api_error"},
        )


if __name__ == "__main__":
    unittest.main()
