# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "httpx>=0.28,<0.29",
# ]
# ///

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parents[1]))

from platform_api_core import (
    DetectedStore,
    Http,
    NonMagentoPlatform,
    StorefrontBotWall,
    ToolError,
    parse_item_ref,
)
from platforms import extra

FIXTURES = Path(__file__).parents[2] / "tests" / "fixtures"


def fixture(name: str) -> bytes:
    return (FIXTURES / f"platform-extra-{name}").read_bytes()


def detected(
    platform: NonMagentoPlatform, api_origin: str = "https://shop.example"
) -> DetectedStore:
    return DetectedStore(
        origin="https://shop.example",
        entry_url="https://shop.example/",
        platform=platform,
        api_origin=api_origin,
        evidence=(f"{platform} fixture",),
    )


class DetectionTests(unittest.TestCase):
    def test_detects_each_platform_from_primary_signatures(self) -> None:
        wix = httpx.Response(
            200,
            headers={"Server": "Pepyaka", "x-wix-request-id": "request"},
            content=fixture("wix-home.html"),
        )
        ecwid = httpx.Response(200, content=fixture("ecwid-home.html"))
        sfcc = httpx.Response(
            200,
            headers={"x-dw-request-base-id": "base"},
            text='<link href="/on/demandware.static/Sites-Test-Site/global.css">',
        )

        self.assertEqual(
            extra.detect(wix, "https://shop.example", "https://shop.example/").platform,
            "wix",
        )
        self.assertEqual(
            extra.detect(
                ecwid, "https://shop.example", "https://shop.example/"
            ).platform,
            "ecwid",
        )
        self.assertEqual(
            extra.detect(
                sfcc, "https://shop.example", "https://shop.example/"
            ).platform,
            "sfcc",
        )

    def test_no_signature_returns_none(self) -> None:
        response = httpx.Response(200, text="<html><body>Custom shop</body></html>")
        self.assertIsNone(
            extra.detect(response, "https://shop.example", "https://shop.example/")
        )

    def test_conflicting_signatures_fail_loudly(self) -> None:
        response = httpx.Response(
            200, headers={"Server": "Pepyaka"}, content=fixture("ecwid-home.html")
        )
        with self.assertRaisesRegex(ToolError, "Conflicting storefront signatures"):
            extra.detect(response, "https://shop.example", "https://shop.example/")

    def test_challenge_is_bot_wall_not_platform_detection(self) -> None:
        response = httpx.Response(
            403,
            headers={"Server": "cloudflare", "cf-mitigated": "challenge"},
            text='<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>',
        )
        result = extra.detect(response, "https://shop.example", "https://shop.example/")
        self.assertEqual(result.kind, "bot_wall")
        self.assertIs(type(result), StorefrontBotWall)


class WixTests(unittest.TestCase):
    def test_public_search_bootstraps_token_and_returns_product_data(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/_api/v1/access-tokens":
                return httpx.Response(
                    200, content=fixture("wix-tokens.json"), request=request
                )
            if request.url.path == "/_api/catalog-reader-server/api/v1/products/query":
                self.assertEqual(
                    request.headers["Authorization"], "anonymous-wix-test-token"
                )
                payload = json.loads(request.content)
                self.assertEqual(
                    json.loads(payload["query"]["filter"]),
                    {"name": {"$contains": "wheel"}},
                )
                self.assertEqual(payload["query"]["paging"], {"limit": 10, "offset": 0})
                self.assertIs(payload["includeVariants"], True)
                return httpx.Response(
                    200, content=fixture("wix-products.json"), request=request
                )
            raise AssertionError(request.url)

        result = extra.search(
            Http(httpx.MockTransport(handler)), detected("wix"), "wheel"
        )
        self.assertEqual(result["total"], 1)
        product = result["items"][0]
        self.assertEqual(product["name"], "Jurassic World - Dino Parade")
        self.assertEqual(product["price"], {"amount": "169.0", "currency": "EUR"})
        self.assertEqual(
            product["compare_at_price"], {"amount": "189.0", "currency": "EUR"}
        )
        self.assertEqual(product["options"], ["Size (Diameter)"])
        self.assertEqual(
            parse_item_ref(product["item_ref"], "wix"), {"product_id": product["id"]}
        )

    def test_public_search_preserves_product_without_optional_sku(self) -> None:
        products = json.loads(fixture("wix-products.json"))
        products["products"][0].pop("sku")

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/_api/v1/access-tokens":
                return httpx.Response(
                    200, content=fixture("wix-tokens.json"), request=request
                )
            if request.url.path == "/_api/catalog-reader-server/api/v1/products/query":
                return httpx.Response(200, json=products, request=request)
            raise AssertionError(request.url)

        result = extra.search(
            Http(httpx.MockTransport(handler)), detected("wix"), "wheel"
        )

        product = result["items"][0]
        self.assertIsNone(product["sku"])
        self.assertEqual(
            parse_item_ref(product["item_ref"], "wix"), {"product_id": product["id"]}
        )

    def test_product_rejects_present_non_string_sku(self) -> None:
        product = json.loads(fixture("wix-products.json"))["products"][0]
        for sku in (False, 7, {}, []):
            with self.subTest(sku=sku):
                product["sku"] = sku
                with self.assertRaisesRegex(ToolError, "sku must be a string or null"):
                    extra._wix_item(detected("wix"), product)

    def test_missing_ecommerce_token_is_a_schema_error(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"apps": {}}, request=request)
        )
        with self.assertRaisesRegex(ToolError, "no e-commerce access token"):
            extra.search(Http(transport), detected("wix"), "wheel")

    def test_challenge_during_bootstrap_is_explicit(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                403,
                headers={"Server": "cloudflare", "cf-mitigated": "challenge"},
                text="challenge",
                request=request,
            )
        )
        result = extra.search(Http(transport), detected("wix"), "wheel")
        self.assertEqual(result["kind"], "bot_wall")
        self.assertEqual(result["operation"], "search")


class EcwidTests(unittest.TestCase):
    def test_public_search_discovers_store_api_and_redacts_token_evidence(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "shop.example":
                return httpx.Response(
                    200, content=fixture("ecwid-home.html"), request=request
                )
            if request.url.host == "app.ecwid.com" and request.url.path == "/script.js":
                return httpx.Response(
                    200, content=fixture("ecwid-script.js"), request=request
                )
            if request.url.host == "us-vir3-storefront-api.ecwid.com":
                self.assertEqual(json.loads(request.content), {"lang": "en"})
                return httpx.Response(
                    200, content=fixture("ecwid-initial.json"), request=request
                )
            if request.url.host == "app.ecwid.com" and request.url.path.endswith(
                "/products"
            ):
                self.assertEqual(request.url.params["token"], "public-test-token")
                self.assertEqual(request.url.params["keyword"], "coffee")
                return httpx.Response(
                    200, content=fixture("ecwid-products.json"), request=request
                )
            raise AssertionError(request.url)

        http = Http(httpx.MockTransport(handler))
        result = extra.search(
            http, detected("ecwid", "https://app.ecwid.com"), "coffee"
        )
        self.assertEqual(result["store_id"], "248360")
        product = result["items"][0]
        self.assertEqual(product["price"], {"amount": "21.0", "currency": "USD"})
        self.assertEqual(product["available"], True)
        self.assertEqual(
            product["product_url"],
            "https://shop.example/store#!/Organic-Spoonbender-p2913395",
        )
        self.assertEqual(
            parse_item_ref(product["item_ref"], "ecwid"),
            {"product_id": 2913395, "store_id": "248360"},
        )
        self.assertNotIn("public-test-token", json.dumps(http.evidence))
        self.assertIn("token=%5Bredacted%5D", http.evidence[-1]["requested_url"])

    def test_untrusted_storefront_api_host_fails_before_initial_data(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "shop.example":
                return httpx.Response(
                    200, content=fixture("ecwid-home.html"), request=request
                )
            return httpx.Response(
                200,
                text='{"apiBaseUrl":"https://attacker.example/storefront/api/v1"}',
                request=request,
            )

        with self.assertRaisesRegex(ToolError, "untrusted storefront API base URL"):
            extra.search(
                Http(httpx.MockTransport(handler)),
                detected("ecwid", "https://app.ecwid.com"),
                "cake",
            )


class SfccTests(unittest.TestCase):
    def test_search_route_is_relative_to_the_detected_entry_url(self) -> None:
        def check(entry_url: str, expected_path: str) -> None:
            paths: list[str] = []

            def handler(request: httpx.Request) -> httpx.Response:
                paths.append(request.url.path)
                self.assertEqual(request.url.path, expected_path)
                return httpx.Response(
                    200, content=fixture("sfcc-search.html"), request=request
                )

            detection = DetectedStore(
                origin="https://shop.example",
                entry_url=entry_url,
                platform="sfcc",
                api_origin="https://shop.example",
                evidence=("sfcc fixture",),
            )
            result = extra.search(
                Http(httpx.MockTransport(handler)), detection, "towel"
            )

            self.assertEqual(result["endpoint"], f"https://shop.example{expected_path}")
            self.assertEqual(paths, [expected_path])

        cases = (
            ("https://shop.example/", "/search"),
            ("https://shop.example/it_IT/", "/it_IT/search"),
            ("https://shop.example/us/home", "/us/search"),
        )
        for entry_url, expected_path in cases:
            with self.subTest(entry_url=entry_url):
                check(entry_url, expected_path)

    def test_search_route_returns_bounded_stable_product_references(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/search")
            self.assertEqual(request.url.params["q"], "towel")
            return httpx.Response(
                200, content=fixture("sfcc-search.html"), request=request
            )

        result = extra.search(
            Http(httpx.MockTransport(handler)), detected("sfcc"), "towel"
        )
        self.assertEqual(
            [item["id"] for item in result["items"]], ["12133488", "12133489"]
        )
        first = result["items"][0]
        self.assertEqual(first["name"], "Summer Major Towel")
        self.assertEqual(first["price"], {"amount": "29.99", "currency": "USD"})
        self.assertEqual(
            first["product_url"],
            "https://shop.example/srixon/summer-major-towel/MT25SM.html",
        )
        self.assertEqual(parse_item_ref(first["item_ref"], "sfcc"), {"pid": "12133488"})
        self.assertEqual(result["endpoint"], "https://shop.example/search")

    def test_search_route_rejects_non_sfcc_html(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200, text="<html>unrelated landing page</html>", request=request
            )
        )
        with self.assertRaisesRegex(ToolError, "no SFCC storefront signature"):
            extra.search(Http(transport), detected("sfcc"), "towel")

    def test_search_denials_are_gated_but_recognized_walls_stay_bot_walls(
        self,
    ) -> None:
        def check(
            status: int,
            headers: dict[str, str],
            content: bytes,
            expected_kind: str,
        ) -> None:
            paths: list[str] = []

            def handler(request: httpx.Request) -> httpx.Response:
                paths.append(request.url.path)
                return httpx.Response(
                    status, headers=headers, content=content, request=request
                )

            result = extra.search(
                Http(httpx.MockTransport(handler)), detected("sfcc"), "towel"
            )

            self.assertEqual(result["kind"], expected_kind)
            self.assertEqual(paths, ["/search"])
            if expected_kind == "gated":
                self.assertIs(result["browser_required"], True)
                self.assertEqual(result["endpoint"], "https://shop.example/search")
            else:
                self.assertEqual(result["system"], "cloudflare")
                self.assertNotIn("browser_required", result)

        cases = (
            (401, {}, b"Unauthorized", "gated"),
            (403, {}, b"Forbidden", "gated"),
            (
                403,
                {"cf-mitigated": "challenge"},
                b"Just a moment",
                "bot_wall",
            ),
        )
        for status, headers, content, expected_kind in cases:
            with self.subTest(status=status, expected_kind=expected_kind):
                check(status, headers, content, expected_kind)

    def test_search_rejects_off_origin_redirect(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "shop.example":
                return httpx.Response(
                    302,
                    headers={"Location": "https://different.example/search"},
                    request=request,
                )
            return httpx.Response(
                200,
                headers={"x-dw-request-base-id": "base"},
                content=fixture("sfcc-search.html"),
                request=request,
            )

        with self.assertRaisesRegex(ToolError, "outside the detected storefront"):
            extra.search(Http(httpx.MockTransport(handler)), detected("sfcc"), "towel")


class QuoteBoundaryTests(unittest.TestCase):
    def test_all_generic_quote_paths_are_explicit_browser_operations(self) -> None:
        for platform, api_origin in (
            ("wix", "https://shop.example"),
            ("ecwid", "https://app.ecwid.com"),
            ("sfcc", "https://shop.example"),
        ):
            with self.subTest(platform=platform):
                result = extra.quote(Http(), detected(platform, api_origin), "unused")
                self.assertEqual(result["kind"], "unsupported_operation")
                self.assertEqual(result["operation"], "quote")
                self.assertIs(result["browser_required"], True)
                self.assertNotEqual(result["kind"], "gated")


if __name__ == "__main__":
    unittest.main()
