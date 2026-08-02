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
from unittest import mock

import httpx

sys.path.insert(0, str(Path(__file__).parents[1]))

from platform_api_core import DetectedStore, Http
from platforms import shopify


def detection() -> DetectedStore:
    return DetectedStore(
        origin="https://store.example",
        entry_url="https://store.example/",
        platform="shopify",
        api_origin="https://backend.myshopify.com",
        evidence=("data.shop",),
    )


def unsigned_send(client: httpx.Client, request: httpx.Request) -> httpx.Response:
    return client.send(request, follow_redirects=False)


def redirect_transport(
    location: str, requests: list[httpx.Request]
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(307, headers={"Location": location}, request=request)

    return httpx.MockTransport(handler)


def json_transport(payload: object) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    return httpx.MockTransport(handler)


class ShopifyTests(unittest.TestCase):
    def test_detection_discovers_bare_myshopify_backend_in_headless_source(
        self,
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "store.example":
                return httpx.Response(404, text="not found", request=request)
            self.assertEqual(request.url.host, "main-us-attitude.myshopify.com")
            return httpx.Response(
                200, json={"data": {"shop": {"name": "ATTITUDE"}}}, request=request
            )

        homepage_request = httpx.Request("GET", "https://store.example/")
        homepage = httpx.Response(
            200,
            text='{"publicStoreDomain":"main-us-attitude.myshopify.com"}',
            request=homepage_request,
        )
        http = Http(httpx.MockTransport(handler))
        with mock.patch.object(shopify, "send_signed", side_effect=unsigned_send):
            result = shopify.detect(
                http, "https://store.example", "https://store.example/", homepage
            )
        self.assertIsNotNone(result)
        self.assertEqual(result.api_origin, "https://main-us-attitude.myshopify.com")

    def test_detection_treats_signed_redirect_boundary_as_no_match(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                307,
                headers={"Location": "https://different.example/graphql"},
                request=request,
            )

        homepage_request = httpx.Request("GET", "https://store.example/")
        homepage = httpx.Response(200, text="<html></html>", request=homepage_request)
        http = Http(httpx.MockTransport(handler))
        with mock.patch.object(shopify, "send_signed", side_effect=unsigned_send):
            result = shopify.detect(
                http, "https://store.example", "https://store.example/", homepage
            )

        self.assertIsNone(result)

    def test_detection_rejects_non_api_redirect_before_a_second_send(self) -> None:
        homepage_request = httpx.Request("GET", "https://store.example/")
        homepage = httpx.Response(200, text="<html></html>", request=homepage_request)
        locations = (
            "/not-shopify",
            "/api/2026-07/graphql.json?redirected=true",
            "https://user:secret@store.example/api/2026-07/graphql.json",
            "http://store.example/api/2026-07/graphql.json",
        )
        for location in locations:
            with self.subTest(location=location):
                requests: list[httpx.Request] = []
                http = Http(redirect_transport(location, requests))
                with mock.patch.object(
                    shopify, "send_signed", side_effect=unsigned_send
                ) as signer:
                    result = shopify.detect(
                        http,
                        "https://store.example",
                        "https://store.example/",
                        homepage,
                    )

                self.assertIsNone(result)
                self.assertEqual(len(requests), 1)
                self.assertEqual(signer.call_count, 1)

    def test_search_flattens_exact_variants(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.host, "backend.myshopify.com")
            return httpx.Response(
                200,
                json={
                    "data": {
                        "products": {
                            "nodes": [
                                {
                                    "title": "Valve",
                                    "handle": "valve",
                                    "vendor": "Acme",
                                    "productType": "Parts",
                                    "variants": {
                                        "nodes": [
                                            {
                                                "id": "gid://shopify/ProductVariant/7",
                                                "title": "1 inch",
                                                "sku": "VALVE-1",
                                                "barcode": "123",
                                                "availableForSale": True,
                                                "weight": 2.5,
                                                "weightUnit": "POUNDS",
                                                "price": {
                                                    "amount": "12.50",
                                                    "currencyCode": "USD",
                                                },
                                                "compareAtPrice": None,
                                            }
                                        ]
                                    },
                                }
                            ]
                        }
                    }
                },
                request=request,
            )

        http = Http(httpx.MockTransport(handler))
        with mock.patch.object(
            shopify, "send_signed", side_effect=unsigned_send
        ) as signer:
            result = shopify.search(http, detection(), "VALVE-1")
        self.assertEqual(result["kind"], "search")
        self.assertEqual(result["items"][0]["sku"], "VALVE-1")
        self.assertEqual(
            result["items"][0]["price"], {"amount": "12.50", "currency": "USD"}
        )
        self.assertEqual(signer.call_count, 1)

    def test_graphql_error_shape_is_strictly_validated(self) -> None:
        invalid_errors = (
            None,
            {"message": "Not an array"},
            [],
            ["Not an object"],
            [{}],
            [{"message": 7}],
            [{"message": ""}],
        )
        for errors in invalid_errors:
            with self.subTest(errors=errors):
                http = Http(json_transport({"errors": errors}))
                with (
                    mock.patch.object(
                        shopify, "send_signed", side_effect=unsigned_send
                    ),
                    self.assertRaisesRegex(
                        shopify.ToolError,
                        "GraphQL errors must be a nonempty array of objects with nonempty messages",
                    ),
                ):
                    shopify.search(http, detection(), "bearing")

    def test_graphql_error_messages_are_preserved(self) -> None:
        http = Http(
            json_transport(
                {
                    "errors": [
                        {"message": "first", "extensions": {"code": "ONE"}},
                        {"message": "second"},
                    ]
                }
            )
        )
        with (
            mock.patch.object(shopify, "send_signed", side_effect=unsigned_send),
            self.assertRaisesRegex(
                shopify.ToolError,
                "Shopify product search returned GraphQL errors: first; second",
            ),
        ):
            shopify.search(http, detection(), "bearing")

    def test_deferred_graphql_error_shape_is_strictly_validated(self) -> None:
        request = httpx.Request("POST", "https://backend.myshopify.com/graphql")
        response = httpx.Response(200, json={"errors": []}, request=request)
        with self.assertRaisesRegex(
            shopify.ToolError,
            "GraphQL errors must be a nonempty array of objects with nonempty messages",
        ):
            shopify._delivery_groups(response)

    def test_quote_parses_deferred_multipart_and_preserves_pickup(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            body = json.loads(request.content)
            if "cartCreate" in body["query"]:
                self.assertEqual(
                    body["variables"]["input"]["buyerIdentity"],
                    {
                        "countryCode": "US",
                        "deliveryAddressPreferences": [
                            {"deliveryAddress": shopify.ADDRESS}
                        ],
                    },
                )
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "cartCreate": {
                                "cart": {
                                    "id": "gid://shopify/Cart/secret",
                                    "cost": {
                                        "subtotalAmount": {
                                            "amount": "12.50",
                                            "currencyCode": "USD",
                                        }
                                    },
                                },
                                "userErrors": [],
                            }
                        }
                    },
                    request=request,
                )
            body = (
                b"--graphql\r\nContent-Type: application/json\r\n\r\n"
                b'{"data":{"cart":{"id":"secret"}},"hasNext":true}\r\n'
                b"--graphql\r\nContent-Type: application/json\r\n\r\n"
                b'{"incremental":[{"path":["cart"],"data":{"deliveryGroups":{"nodes":[{"groupType":"ONE_TIME_PURCHASE","deliveryOptions":[{"handle":"ground","title":"Ground","code":"GROUND","description":null,"deliveryMethodType":"SHIPPING","estimatedCost":{"amount":"6.95","currencyCode":"USD"}},{"handle":null,"title":"Pickup","code":null,"description":null,"deliveryMethodType":"PICK_UP","estimatedCost":{"amount":"0.00","currencyCode":"USD"}}]}]}}}],"hasNext":false}\r\n'
                b"--graphql--\r\n"
            )
            return httpx.Response(
                200,
                headers={"Content-Type": 'multipart/mixed; boundary="graphql"'},
                content=body,
                request=request,
            )

        http = Http(httpx.MockTransport(handler))
        reference = shopify.item_ref(
            "shopify", {"variant_id": "gid://shopify/ProductVariant/7"}
        )
        with mock.patch.object(
            shopify, "send_signed", side_effect=unsigned_send
        ) as signer:
            result = shopify.quote(http, detection(), reference)
        self.assertEqual(calls, 2)
        self.assertEqual(signer.call_count, 2)
        self.assertEqual(result["kind"], "quote")
        self.assertEqual([rate["option_id"] for rate in result["rates"]], ["ground"])
        self.assertEqual(
            [option["disposition"] for option in result["shipping_options"]],
            ["delivery", "pickup"],
        )
        self.assertEqual(
            [option["id"] for option in result["shipping_options"]],
            ["ground", "Pickup"],
        )

    def test_delivery_method_type_must_be_a_known_enum_value(self) -> None:
        option = {
            "handle": "ground",
            "title": "Ground",
            "code": "GROUND",
            "description": None,
            "estimatedCost": {"amount": "6.95", "currencyCode": "USD"},
        }

        expected = {
            "SHIPPING": "delivery",
            "LOCAL": "delivery",
            "PICK_UP": "pickup",
            "PICKUP_POINT": "pickup",
            "RETAIL": "pickup",
            "NONE": "unavailable",
        }
        for method, disposition in expected.items():
            with self.subTest(method=method):
                option["deliveryMethodType"] = method
                self.assertEqual(
                    shopify._shipping_option(option)["disposition"], disposition
                )

        option["deliveryMethodType"] = "UNKNOWN"
        with self.assertRaisesRegex(shopify.ToolError, "deliveryMethodType"):
            shopify._shipping_option(option)

        for method in ([], {}):
            with self.subTest(method=method), self.assertRaisesRegex(
                shopify.ToolError, "deliveryMethodType"
            ):
                option["deliveryMethodType"] = method
                shopify._shipping_option(option)

    def test_signed_redirect_uses_a_fresh_request(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if len(seen) == 1:
                return httpx.Response(
                    307,
                    headers={"Location": "/api/2026-07/graphql.json"},
                    request=request,
                )
            return httpx.Response(
                200, json={"data": {"products": {"nodes": []}}}, request=request
            )

        def signing_send(
            client: httpx.Client, request: httpx.Request
        ) -> httpx.Response:
            self.assertNotIn("Signature-Agent", request.headers)
            request.headers["Signature-Agent"] = f'"call-{len(seen) + 1}"'
            return client.send(request, follow_redirects=False)

        result = None
        http = Http(httpx.MockTransport(handler))
        with mock.patch.object(shopify, "send_signed", side_effect=signing_send):
            result = shopify.search(http, detection(), "bearing")
        self.assertEqual(result["items"], [])
        self.assertEqual(
            [str(request.url) for request in seen],
            [
                "https://backend.myshopify.com/api/2026-07/graphql.json",
                "https://backend.myshopify.com/api/2026-07/graphql.json",
            ],
        )
        self.assertNotEqual(
            seen[0].headers["Signature-Agent"], seen[1].headers["Signature-Agent"]
        )

    def test_signed_redirect_rejects_another_api_authority(self) -> None:
        for location in (
            "https://attacker.example/graphql",
            "//attacker.example/graphql",
            "https://backend.myshopify.com:444/graphql",
        ):
            with self.subTest(location=location):
                requests: list[httpx.Request] = []
                http = Http(redirect_transport(location, requests))
                with (
                    mock.patch.object(
                        shopify, "send_signed", side_effect=unsigned_send
                    ) as signer,
                    self.assertRaisesRegex(
                        shopify.SignedRedirectBoundary,
                        "redirect target must use the detected API authority",
                    ),
                ):
                    shopify.search(http, detection(), "bearing")
                self.assertEqual(len(requests), 1)
                self.assertEqual(signer.call_count, 1)

    def test_quote_propagates_signed_redirect_boundary(self) -> None:
        http = Http(
            httpx.MockTransport(
                lambda request: httpx.Response(
                    307,
                    headers={"Location": "https://different.example/graphql"},
                    request=request,
                )
            )
        )
        reference = shopify.item_ref(
            "shopify", {"variant_id": "gid://shopify/ProductVariant/7"}
        )
        with (
            mock.patch.object(shopify, "send_signed", side_effect=unsigned_send),
            self.assertRaises(shopify.SignedRedirectBoundary),
        ):
            shopify.quote(http, detection(), reference)

    def test_quote_rejects_item_ref_with_extra_key_before_transport(self) -> None:
        reference = shopify.item_ref(
            "shopify",
            {
                "variant_id": "gid://shopify/ProductVariant/7",
                "forged": "value",
            },
        )

        def unexpected_request(request: httpx.Request) -> httpx.Response:
            self.fail(f"quote reached transport: {request.url}")

        with self.assertRaisesRegex(
            shopify.ToolError, "shopify item_ref has an invalid payload"
        ):
            shopify.quote(
                Http(httpx.MockTransport(unexpected_request)), detection(), reference
            )

    def test_empty_rate_list_is_not_free_shipping(self) -> None:
        responses = iter(
            [
                {
                    "data": {
                        "cartCreate": {
                            "cart": {
                                "id": "gid://shopify/Cart/secret",
                                "cost": {
                                    "subtotalAmount": {
                                        "amount": "9.99",
                                        "currencyCode": "USD",
                                    }
                                },
                            },
                            "userErrors": [],
                        }
                    }
                },
                {"data": {"cart": {"deliveryGroups": {"nodes": []}}}},
            ]
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=next(responses), request=request)

        http = Http(httpx.MockTransport(handler))
        reference = shopify.item_ref(
            "shopify", {"variant_id": "gid://shopify/ProductVariant/7"}
        )
        with mock.patch.object(shopify, "send_signed", side_effect=unsigned_send):
            result = shopify.quote(http, detection(), reference)
        self.assertEqual(result["kind"], "empty")
        self.assertEqual(result["rates"], [])


if __name__ == "__main__":
    unittest.main()
