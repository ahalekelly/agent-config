# /// script
# dependencies = ["httpx>=0.28,<0.29"]
# ///

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import httpx


ROOT = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(ROOT))

from platform_api_core import Detection, Http, item_ref
from platforms import extra


def response(
    request: httpx.Request,
    value: object,
    *,
    cookies: list[str] | None = None,
) -> httpx.Response:
    headers = [("Content-Type", "application/json")]
    headers.extend(("Set-Cookie", cookie) for cookie in cookies or [])
    return httpx.Response(200, json=value, headers=headers, request=request)


class SquarespaceLiveRegressionTests(unittest.TestCase):
    def test_normalizes_collection_links_and_requires_website_id(self) -> None:
        requested: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested.append(request.url.path)
            if request.url.path == "/":
                decoys = "".join(f'<a href="/page-{index}">Page</a>' for index in range(20))
                markup = '<nav data-content-field="navigation">' + decoys + (
                    '<a href="/chairs-and-stools?tag=chair#featured">Seating</a>'
                    '<a href="/chairs-and-stools#duplicate">Seating duplicate</a>'
                    '<a href="/invalid?tag=chair">Invalid</a>'
                    "</nav>"
                )
                return httpx.Response(200, text=markup, request=request)
            if request.url.path == "/chairs-and-stools":
                self.assertEqual(dict(request.url.params), {"format": "json"})
                return response(
                    request,
                    {
                        "website": {"id": "site"},
                        "items": [
                            {
                                "id": "item",
                                "title": "Bearing",
                                "fullUrl": "/p/bearing",
                                "variants": [
                                    {
                                        "sku": "BRG-1",
                                        "priceMoney": {"value": "18.00", "currency": "USD"},
                                        "unlimited": True,
                                    }
                                ],
                            }
                        ],
                    },
                )
            if request.url.path == "/invalid" or request.url.path.startswith("/page-"):
                return response(
                    request,
                    {
                        "website": {},
                        "items": [
                            {
                                "id": "invalid-item",
                                "title": "Bearing",
                                "variants": [
                                    {
                                        "sku": "BAD-1",
                                        "priceMoney": {"value": "1.00", "currency": "USD"},
                                        "unlimited": True,
                                    }
                                ],
                            }
                        ],
                    },
                )
            raise AssertionError(request.url)

        http = Http(httpx.MockTransport(handler))
        detection = Detection(
            "detected",
            "https://store.test",
            "squarespace",
            "https://store.test",
            ("squarespace_html",),
        )
        with http.client:
            catalog = extra.squarespace_products(http, detection, "bearing")

        self.assertEqual([product["sku"] for product in catalog["items"]], ["BRG-1"])
        self.assertEqual(catalog["collection_candidates_scanned"], 22)
        self.assertEqual(requested.count("/chairs-and-stools"), 1)
        self.assertEqual(requested.count("/invalid"), 1)

    def test_quote_starts_a_fresh_canonical_session(self) -> None:
        csrf_token = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal csrf_token
            if request.url.path == "/shop":
                return response(request, {}, cookies=["crumb=fresh; Path=/; Secure"])
            if request.url.path == "/api/commerce/shopping-cart/entries":
                csrf_token = request.headers["x-csrf-token"]
                return response(request, {"shoppingCart": {"cartToken": "ephemeral-cart"}})
            if request.url.path.endswith("/shipping/location"):
                return response(
                    request,
                    {
                        "shippingOptionsStatus": "APPLICABLE_SHIPPING_OPTIONS",
                        "fulfillmentOptions": [
                            {
                                "key": "ground",
                                "name": "Ground",
                                "price": {"decimalValue": "7.00", "currencyCode": "USD"},
                                "isPickup": False,
                            }
                        ],
                    },
                )
            raise AssertionError(request.url)

        http = Http(httpx.MockTransport(handler))
        http.client.cookies.set("crumb", "stale", domain="store.test", path="/")
        detection = Detection(
            "detected",
            "https://www.store.test",
            "squarespace",
            "https://www.store.test",
            ("squarespace_html",),
        )
        reference = item_ref(
            "squarespace",
            {
                "collection": "https://www.store.test/shop",
                "item_id": "item",
                "sku": "BRG-1",
            },
        )
        with http.client:
            result = extra.squarespace_quote(http, detection, reference)

        self.assertEqual(csrf_token, "fresh")
        self.assertEqual(result["status"], "quoted")


class ProductOnlyLiveRegressionTests(unittest.TestCase):
    def test_ecwid_uses_store_currency_and_keeps_quote_boundary(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "store.test":
                markup = '<script src="https://app.ecwid.com/script.js?123"></script>'
                return httpx.Response(200, text=markup, request=request)
            if request.url.path == "/script.js":
                return httpx.Response(
                    200,
                    text='{"apiBaseUrl":"https://storefront.example/api"}',
                    request=request,
                )
            if request.url.path.endswith("/initial-data"):
                return response(
                    request,
                    {
                        "storeProfile": {
                            "value": {
                                "formats": {"currencyFormat": {"currencyCode": "USD"}},
                                "integrations": {
                                    "apps": {
                                        "publicTokens": {"ecwid-storefront": "ephemeral"}
                                    }
                                },
                            }
                        }
                    },
                )
            if request.url.path.endswith("/products"):
                return response(
                    request,
                    {
                        "items": [
                            {"id": 6, "enabled": False},
                            {
                                "id": 7,
                                "name": "Bearing",
                                "sku": "B-7",
                                "enabled": True,
                                "inStock": True,
                                "unlimited": True,
                                "price": 9.5,
                                "url": "https://store.test/bearing",
                            }
                        ]
                    },
                )
            raise AssertionError(request.url)

        http = Http(httpx.MockTransport(handler))
        detection = Detection(
            "detected",
            "https://store.test",
            "ecwid",
            "https://store.test",
            ("ecwid_script",),
        )
        with http.client:
            catalog = extra.ecwid_products(http, detection, "bearing")
            quote = extra.quote(http, detection, catalog["items"][0]["item_ref"])

        self.assertEqual(catalog["items"][0]["price"], {"amount": "9.5", "currency": "USD"})
        self.assertEqual(quote["status"], "unsupported")
        self.assertEqual(quote["stage"], "quote")

    def test_wix_decodes_json_escaped_access_tokens_url(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/":
                markup = r'{"accessTokensUrl":"https:\/\/store.test\/_api\/v1\/access-tokens"}'
                return httpx.Response(200, text=markup, request=request)
            if request.url.path == "/_api/v1/access-tokens":
                return response(
                    request,
                    {"apps": {extra.WIX_ECOM_APP: {"accessToken": "ephemeral"}}},
                )
            if request.url.path.endswith("/products/query"):
                self.assertEqual(request.headers["authorization"], "ephemeral")
                return response(
                    request,
                    {
                        "products": [
                            {
                                "id": "p1",
                                "name": "Wheel",
                                "sku": "W-1",
                                "slug": "wheel",
                                "stock": {"inStock": True},
                                "priceData": {"price": 12.5, "currency": "USD"},
                            }
                        ]
                    },
                )
            raise AssertionError(request.url)

        http = Http(httpx.MockTransport(handler))
        detection = Detection(
            "detected",
            "https://store.test",
            "wix",
            "https://store.test",
            ("wix_html",),
        )
        with http.client:
            catalog = extra.wix_products(http, detection, "wheel")
            quote = extra.quote(http, detection, catalog["items"][0]["item_ref"])

        self.assertEqual(catalog["items"][0]["sku"], "W-1")
        self.assertEqual(quote["status"], "unsupported")
        self.assertEqual(quote["stage"], "quote")

    def test_sfcc_uses_the_homepage_search_form(self) -> None:
        requested: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested.append(request.url.path)
            if request.url.path == "/":
                markup = (
                    '<form action="/search"><input name="q"></form>'
                    '<form action="/search"><input name="q"></form>'
                    '<form action="https://search.example/query"><input name="q"></form>'
                )
                return httpx.Response(200, text=markup, request=request)
            if request.url.path == "/search":
                self.assertEqual(dict(request.url.params), {"q": "red"})
                markup = (
                    '<script src="/on/demandware.static/theme.js"></script>'
                    '<a href="/search?q=red#product-search-results">Products</a>'
                    '<div class="product" data-pid="P-RED">'
                    '<a href="/product/p.html?dwvar_P_color=red">'
                    '<img alt="Red Product"></a></div>'
                )
                return httpx.Response(200, text=markup, request=request)
            raise AssertionError(request.url)

        http = Http(httpx.MockTransport(handler))
        detection = Detection(
            "detected",
            "https://store.test",
            "sfcc",
            "https://store.test",
            ("sfcc_html",),
        )
        with http.client:
            catalog = extra.sfcc_products(http, detection, "red")
            quote = extra.quote(http, detection, catalog["items"][0]["item_ref"])

        self.assertEqual(requested, ["/", "/search"])
        self.assertEqual(catalog["items"][0]["sku"], "P-RED")
        self.assertEqual(catalog["items"][0]["title"], "Red Product")
        self.assertEqual(catalog["items"][0]["url"], "https://store.test/product/p.html?dwvar_P_color=red")
        self.assertEqual(quote["status"], "unsupported")
        self.assertEqual(quote["stage"], "quote")


if __name__ == "__main__":
    unittest.main()
