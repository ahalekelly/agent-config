#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "cryptography>=45,<47",
#   "httpx>=0.28,<0.29",
# ]
# ///

from __future__ import annotations

import base64
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

import httpx
from cryptography.hazmat.primitives import serialization


sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import web_bot_auth  # noqa: E402
import platform_api  # noqa: E402
from platform_api_core import Detection, item_ref  # noqa: E402
from platforms import commerce_common as common, shopify, woocommerce  # noqa: E402


FIXTURES = Path(__file__).parent / "fixtures"
TEST_PRIVATE_KEY = b"""-----BEGIN PRIVATE KEY-----
MC4CAQAwBQYDK2VwBCIEIJ1hsZ3v/VpguoRK9JLsLMREScVpezJpGXA7rAMcrn9g
-----END PRIVATE KEY-----
"""
TEST_KEY_ID = "kPrK_qmxVWaYVA9wwBF6Iuo3vVzz7TxHCTwXBygrS4k"
TEST_CREATED = 1_700_000_000
TEST_NONCE = bytes(range(64))
TEST_SIGNATURE = (
    "vYziIqoJKYvrhq4WSpDyBysfWotGt68VU49emzyyacex8/BXI9kHXBXF5xy4H0t4"
    "ZzfsNmVEvtJ/4BqXihlNBA=="
)
def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class ShopifyTests(unittest.TestCase):
    def test_web_bot_auth_exact_vector_and_covered_components(self) -> None:
        private = serialization.load_pem_private_key(TEST_PRIVATE_KEY, password=None)
        headers = web_bot_auth._signature_headers(
            "https://EXAMPLE.com:8443/products?query=valve",
            private,
            TEST_KEY_ID,
            TEST_CREATED,
            TEST_NONCE,
        )
        nonce = base64.b64encode(TEST_NONCE).decode()
        parameters = (
            f'("@authority" "signature-agent");created={TEST_CREATED}'
            f';keyid="{TEST_KEY_ID}";alg="ed25519";expires={TEST_CREATED + 60}'
            f';nonce="{nonce}";tag="web-bot-auth"'
        )
        self.assertEqual(headers, {
            "Signature-Agent": '"https://lancelotlabs.org"',
            "Signature-Input": f"sig1={parameters}",
            "Signature": f"sig1=:{TEST_SIGNATURE}:",
        })
        signature_base = (
            '"@authority": example.com:8443\n'
            '"signature-agent": "https://lancelotlabs.org"\n'
            f'"@signature-params": {parameters}'
        ).encode()
        private.public_key().verify(base64.b64decode(TEST_SIGNATURE), signature_base)

    def test_every_shopify_plan_is_signed_and_cart_shapes_are_exact(self) -> None:
        signed_targets: list[str] = []

        def send_signed(client: httpx.Client, request: httpx.Request) -> httpx.Response:
            signed_targets.append(str(request.url))
            request.headers.update({
                "Signature-Agent": '"https://lancelotlabs.org"',
                "Signature-Input": "sig1=test",
                "Signature": "sig1=:test:",
            })
            return client.send(request)

        requests = [
            shopify.detect_request("https://shop.example"),
            shopify.products_request("https://shop.example", "valve"),
            shopify.cart_create_request("https://shop.example", "gid://shopify/ProductVariant/123"),
            shopify.cart_rates_request("https://shop.example", "gid://shopify/Cart/redacted"),
        ]
        captured: list[httpx.Request] = []
        transport = httpx.MockTransport(
            lambda request: captured.append(request) or httpx.Response(200, request=request)
        )
        with mock.patch.object(shopify.web_bot_auth, "send_signed", side_effect=send_signed):
            with httpx.Client(transport=transport) as client:
                for plan in requests:
                    request = client.build_request(
                        plan.method,
                        plan.url,
                        headers=plan.headers,
                        content=plan.body,
                    )
                    shopify.send(client, request)
        self.assertEqual(signed_targets, ["https://shop.example/api/2026-07/graphql.json"] * 4)
        for request in captured:
            self.assertEqual(request.method, "POST")
            self.assertEqual(
                {"signature-agent", "signature-input", "signature"},
                set(request.headers) & {"signature-agent", "signature-input", "signature"},
            )
        create = json.loads(requests[2].body)
        identity = create["variables"]["input"]["buyerIdentity"]
        address = identity["deliveryAddressPreferences"][0]["deliveryAddress"]
        self.assertEqual(identity["countryCode"], "US")
        self.assertEqual(address["country"], "US")
        self.assertEqual(address["province"], "CA")
        self.assertNotIn("countryCode", address)
        self.assertNotIn("provinceCode", address)
        self.assertIn("... @defer", requests[3].body.decode())
        self.assertIn("withCarrierRates: true", requests[3].body.decode())
        self.assertIn("multipart/mixed", requests[3].headers["Accept"])

    def test_products_and_cart_create(self) -> None:
        products = shopify.parse_products(fixture("shopify-products.json"))
        self.assertEqual(products["products"][0]["quote_ref"], "gid://shopify/ProductVariant/123")
        self.assertEqual(products["products"][0]["price"], {"amount": "12.50", "currency": "USD"})
        cart = shopify.parse_cart_create(fixture("shopify-cart-create.json"))
        self.assertEqual(cart["subtotal"], {"amount": "12.50", "currency": "USD"})

    def test_multipart_quote_preserves_all_options(self) -> None:
        result = shopify.parse_cart_rates(
            'multipart/mixed; boundary="graphql"',
            fixture("shopify-rates.multipart"),
            {"amount": "12.50", "currency": "USD"},
        )
        self.assertEqual(result["status"], "quoted")
        self.assertEqual([option["disposition"] for option in result["shipping_options"]], [
            "delivery", "pickup", "unavailable"
        ])
        self.assertEqual(result["delivery_rates"], [{
            "option_id": "ground",
            "title": "Ground",
            "amount": {"amount": "8.00", "currency": "USD"},
        }])

    def test_empty_multipart_options_are_no_quote(self) -> None:
        result = shopify.parse_cart_rates(
            "multipart/mixed; boundary=graphql",
            fixture("shopify-rates-empty.multipart"),
            {"amount": "12.50", "currency": "USD"},
        )
        self.assertEqual(result["status"], "no_quote")
        self.assertEqual(result["shipping_options"], [])
        self.assertEqual(result["delivery_rates"], [])

    def test_multipart_requires_terminal_part(self) -> None:
        incomplete = fixture("shopify-rates.multipart").replace(b'"hasNext":false', b'"hasNext":true')
        with self.assertRaisesRegex(common.AdapterError, "incomplete"):
            shopify.parse_cart_rates(
                "multipart/mixed; boundary=graphql",
                incomplete,
                {"amount": "12.50", "currency": "USD"},
            )

    def test_provider_error_redacts_ephemeral_cart_gid_from_api_error(self) -> None:
        cart_id = "gid://shopify/Cart/cart-secret?key=key-secret"

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                body = '<script src="https://cdn.shopify.com/theme.js"></script>' if request.url.path == "/" else ""
                return httpx.Response(200 if body else 404, text=body, request=request)
            if request.url.path == "/rest/V1/guest-carts":
                return httpx.Response(404, request=request)
            payload = json.loads(request.content)
            query = payload["query"]
            if "DetectStore" in query:
                return httpx.Response(200, json={"data": {"shop": {"name": "Test"}}}, request=request)
            if "CartCreate" in query:
                return httpx.Response(200, json={
                    "data": {
                        "cartCreate": {
                            "cart": {
                                "id": cart_id,
                                "cost": {"subtotalAmount": {"amount": "12.50", "currencyCode": "USD"}},
                            },
                            "userErrors": [],
                        }
                    }
                }, request=request)
            if "CartRates" in query:
                body = (
                    "--graphql\r\nContent-Type: application/json\r\n\r\n"
                    + json.dumps({"errors": [{"message": f"Cart {cart_id} is unavailable"}], "hasNext": False})
                    + "\r\n--graphql--\r\n"
                )
                return httpx.Response(
                    200,
                    content=body,
                    headers={"Content-Type": "multipart/mixed; boundary=graphql"},
                    request=request,
                )
            raise AssertionError(query)

        workflow = platform_api.new_workflow(httpx.MockTransport(handler))
        reference = item_ref("shopify", {"variant_id": "gid://shopify/ProductVariant/123"})
        with mock.patch.object(shopify, "send", side_effect=lambda client, request: client.send(request)):
            result = platform_api.single("quote", "https://shop.test", reference, workflow=workflow)

        serialized = json.dumps(result)
        self.assertEqual(result["result"]["status"], "api_error")
        self.assertNotIn("cart-secret", serialized)
        self.assertNotIn("key-secret", serialized)
        self.assertIn("gid://shopify/Cart/[redacted]", serialized)


class WooCommerceTests(unittest.TestCase):
    def test_products_omit_configurable_items(self) -> None:
        products = woocommerce.parse_products(fixture("woo-products.json"))
        self.assertEqual(products["configurable_products_omitted"], 1)
        self.assertEqual(products["products"][0]["quote_ref"], "42")
        self.assertEqual(products["products"][0]["price"], {"amount": "12.50", "currency": "USD"})

    def test_selected_product_requires_explicit_minimum_quantity(self) -> None:
        product = {
            "id": 42,
            "type": "simple",
            "is_purchasable": True,
            "is_in_stock": True,
            "add_to_cart": {},
        }
        with self.assertRaisesRegex(common.AdapterError, "minimum quantity"):
            woocommerce.selected_product(json.dumps([product]).encode(), 42)

    def test_quote_uses_exact_collection_lookup_when_singleton_is_gated(self) -> None:
        paths: list[str] = []

        def response(request: httpx.Request, value: object, **headers: str) -> httpx.Response:
            return httpx.Response(200, json=value, headers=headers, request=request)

        def handler(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            if request.url.path.endswith("/products/240"):
                return httpx.Response(403, request=request)
            if request.url.path.endswith("/products"):
                self.assertEqual(request.url.params["include"], "240")
                return response(request, [{
                    "id": 240,
                    "type": "simple",
                    "is_purchasable": True,
                    "is_in_stock": True,
                    "add_to_cart": {"minimum": 1},
                }])
            if request.url.path.endswith("/cart"):
                return response(request, {"totals": {}}, **{"Cart-Token": "ephemeral"})
            if request.url.path.endswith("/cart/add-item"):
                return response(request, {"items": [{"id": 240, "key": "ephemeral-item"}]})
            if request.url.path.endswith("/cart/update-customer"):
                return response(request, {
                    "totals": {
                        "total_items": "1000",
                        "total_tax": "0",
                        "currency_code": "USD",
                        "currency_minor_unit": 2,
                    },
                    "shipping_rates": [{
                        "shipping_rates": [{
                            "rate_id": "ups_flat_rate_fallback",
                            "name": "UPS Flat Rate",
                            "price": "1995",
                            "taxes": "0",
                            "method_id": "flat_rate",
                            "selected": True,
                            "currency_code": "USD",
                            "currency_minor_unit": 2,
                        }],
                    }],
                })
            if request.url.path.endswith("/cart/items/ephemeral-item"):
                return httpx.Response(204, request=request)
            raise AssertionError(request.url)

        workflow = platform_api.new_workflow(httpx.MockTransport(handler))
        detection = Detection(
            "detected",
            "https://tech7000.test",
            "woocommerce",
            "https://tech7000.test",
            ("woocommerce_store_cart",),
        )
        reference = item_ref("woocommerce", {"product_id": 240})
        with workflow.http.client:
            result = workflow.quote(detection, reference)

        self.assertEqual(result["status"], "fallback")
        self.assertEqual(result["shipping_options"][0]["disposition"], "fallback")
        self.assertEqual(result["cleanup_status"], 204)
        self.assertNotIn("/wp-json/wc/store/v1/products/240", paths)

    def test_cart_token_is_the_only_mutation_credential(self) -> None:
        self.assertEqual(woocommerce.cart_token({"Cart-Token": "secret", "Nonce": "ignored"}), "secret")
        with self.assertRaisesRegex(common.AdapterError, "Cart-Token"):
            woocommerce.cart_token({"Nonce": "not-a-fallback"})
        add = woocommerce.add_item_request("https://woo.example", 42, 1, "secret")
        update = woocommerce.update_customer_request("https://woo.example", "secret")
        cleanup = woocommerce.cleanup_request("https://woo.example", "a/b", "secret")
        self.assertEqual(add.headers["Cart-Token"], "secret")
        self.assertEqual(update.headers["Cart-Token"], "secret")
        self.assertEqual(cleanup.headers["Cart-Token"], "secret")
        self.assertTrue(cleanup.url.endswith("a%2Fb"))

    def test_tax_gross_delivery_pickup_and_fallback(self) -> None:
        result = woocommerce.parse_cart_rates(fixture("woo-rates.json"))
        self.assertEqual(result["status"], "quoted")
        self.assertEqual([option["disposition"] for option in result["shipping_options"]], [
            "delivery", "pickup", "fallback"
        ])
        delivery = result["shipping_options"][0]
        self.assertEqual(delivery["amount"], {"amount": "11.00", "currency": "USD"})
        self.assertEqual(delivery["tax"], {"amount": "1.00", "currency": "USD"})
        self.assertEqual(
            delivery["evidence"]["amount_excluding_tax"],
            {"amount": "10.00", "currency": "USD"},
        )
        self.assertEqual(result["delivery_rates"], [{
            "option_id": "flat_rate:10",
            "title": "Ground",
            "amount": {"amount": "11.00", "currency": "USD"},
        }])
        self.assertEqual(result["tax"], {"amount": "2.93", "currency": "USD"})
        self.assertEqual(result["destination"], "dummy_sf")

    def test_empty_rate_list_is_no_quote(self) -> None:
        result = woocommerce.parse_cart_rates(fixture("woo-empty.json"))
        self.assertEqual(result["status"], "no_quote")
        self.assertEqual(result["reason"], "empty_rate_list")


class SharedContractTests(unittest.TestCase):
    def test_terminal_status_and_disposition_unions(self) -> None:
        statuses = {"quoted", "no_quote", "fallback", "gated", "bot_wall", "unsupported", "api_error"}
        dispositions = {"delivery", "pickup", "paid_later", "unavailable", "fallback"}
        self.assertEqual(set(common.Status.__args__), statuses)
        self.assertEqual(set(common.Disposition.__args__), dispositions)
        for status in statuses - {"quoted", "no_quote", "fallback"}:
            self.assertEqual(common.terminal_failure(status, "shopify", "reason")["status"], status)


if __name__ == "__main__":
    unittest.main()
