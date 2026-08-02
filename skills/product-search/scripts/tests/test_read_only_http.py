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

import httpx

sys.path.insert(0, str(Path(__file__).parents[1]))

from platform_api_core import ReadOnlyHttp, ToolError
from platforms.magento import DETAIL_QUERY, DETECT_QUERY, SEARCH_QUERY
from platforms.shopify import PRODUCT_QUERY
from read_only_http import GRAPHQL_DOCUMENT_SHA256_BY_OPERATION, ReadGet

SHOP_QUERY = "{ shop { name } }"


class ReadOnlyHttpTests(unittest.TestCase):
    def test_get_requires_a_sealed_read_capability(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, request=request)

        http = ReadOnlyHttp(httpx.MockTransport(handler))
        for url in (
            "https://store.example/logout",
            "https://store.example/basket/add?format=json",
        ):
            with self.subTest(url=url), self.assertRaisesRegex(
                ToolError, "Http.get"
            ):
                http.request("GET", url)

        self.assertEqual(requests, [])

    def test_storefront_entry_authorizes_each_redirect_hop(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path == "/location.html":
                return httpx.Response(
                    302, headers={"Location": "https://www.store.example/"}, request=request
                )
            if request.url.host == "www.store.example":
                return httpx.Response(
                    302, headers={"Location": "https://store.example/"}, request=request
                )
            return httpx.Response(200, content=b"storefront", request=request)

        http = ReadOnlyHttp(httpx.MockTransport(handler))
        response = http.get(
            http.storefront_entry(
                "https://store.example/location.html",
                ["https://store.example", "https://www.store.example"],
            )
        )

        self.assertEqual(str(response.url), "https://store.example/")
        self.assertEqual(len(requests), 3)
        self.assertEqual(
            [value["operation_kind"] for value in http.evidence],
            ["storefront_entry", "storefront_entry", "storefront_entry"],
        )
        for index in (1, 2):
            self.assertRegex(
                http.evidence[index]["source_request_sha256"], r"^[0-9a-f]{64}$"
            )
            self.assertEqual(
                http.evidence[index]["source_response_sha256"],
                http.evidence[index - 1]["sha256"],
            )

    def test_storefront_entry_redirect_cannot_escape_its_purpose(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                302, headers={"Location": "/logout"}, request=request
            )

        http = ReadOnlyHttp(httpx.MockTransport(handler))
        with self.assertRaisesRegex(ToolError, "resource purpose"):
            http.get(
                http.storefront_entry(
                    "https://store.example/", ["https://store.example"]
                )
            )

        self.assertEqual(len(requests), 1)

    def test_storefront_entry_rejects_unscoped_origin_before_transport(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                302,
                headers={"Location": "https://other.example/"},
                request=request,
            )

        http = ReadOnlyHttp(httpx.MockTransport(handler))
        with self.assertRaisesRegex(ToolError, "preauthorized origin scope"):
            http.get(
                http.storefront_entry(
                    "https://store.example/", ["https://store.example"]
                )
            )

        self.assertEqual(len(requests), 1)

    def test_storefront_entry_resolves_brand_and_locale_landings(self) -> None:
        cases = (
            (
                "https://mettleair.com/location.html",
                ["https://mettleair.com", "https://mettleairstore.com"],
                {"https://mettleair.com/location.html": "https://mettleairstore.com/"},
                "https://mettleairstore.com/",
            ),
            (
                "https://nour-hammour.com/",
                ["https://nour-hammour.com"],
                {"https://nour-hammour.com/": "/us-en/"},
                "https://nour-hammour.com/us-en/",
            ),
            (
                "https://www.alcott.eu/",
                ["https://www.alcott.eu"],
                {"https://www.alcott.eu/": "/it_IT/"},
                "https://www.alcott.eu/it_IT/",
            ),
            (
                "https://hugoboss.com/",
                ["https://hugoboss.com", "https://www.hugoboss.com"],
                {
                    "https://hugoboss.com/": "https://www.hugoboss.com/",
                    "https://www.hugoboss.com/": "/us/home",
                },
                "https://www.hugoboss.com/us/home",
            ),
        )
        def check(
            start: str,
            origins: list[str],
            redirects: dict[str, str],
            final: str,
        ) -> None:
            requests: list[str] = []

            def handler(request: httpx.Request) -> httpx.Response:
                url = str(request.url)
                requests.append(url)
                location = redirects.get(url)
                if location is not None:
                    return httpx.Response(
                        302, headers={"Location": location}, request=request
                    )
                return httpx.Response(200, content=b"storefront", request=request)

            http = ReadOnlyHttp(httpx.MockTransport(handler))
            response = http.get(http.storefront_entry(start, origins))

            self.assertEqual(str(response.url), final)
            self.assertEqual(requests[-1], final)

        for start, origins, redirects, final in cases:
            with self.subTest(start=start):
                check(start, origins, redirects, final)

    def test_storefront_entry_loop_is_rejected_before_retransport(self) -> None:
        requests: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            requests.append(url)
            location = "/us/" if request.url.path == "/" else "/"
            return httpx.Response(302, headers={"Location": location}, request=request)

        http = ReadOnlyHttp(httpx.MockTransport(handler))
        with self.assertRaisesRegex(ToolError, "redirect loop"):
            http.get(
                http.storefront_entry(
                    "https://store.example/", ["https://store.example"]
                )
            )

        self.assertEqual(
            requests, ["https://store.example/", "https://store.example/us/"]
        )

    def test_exact_known_route_returns_redirect_without_following(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(301, headers={"Location": "/"}, request=request)

        http = ReadOnlyHttp(httpx.MockTransport(handler))
        response = http.get(http.woo_products("https://store.example", "probe", 1))

        self.assertEqual(response.status_code, 301)
        self.assertEqual(len(requests), 1)

    def test_shopify_shop_query_is_authorized_before_transport(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json={"data": {"shop": {}}}, request=request)

        http = ReadOnlyHttp(httpx.MockTransport(handler))
        response = http.request(
            "POST",
            "https://store.example/api/2026-07/graphql.json",
            json={"query": SHOP_QUERY},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(requests), 1)

    def test_graphql_write_operations_are_rejected_before_transport(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, request=request)

        http = ReadOnlyHttp(httpx.MockTransport(handler))
        for operation in ("mutation", "subscription"):
            with self.subTest(operation=operation), self.assertRaisesRegex(
                ToolError, operation
            ):
                http.request(
                    "POST",
                    "https://store.example/api/2026-07/graphql.json",
                    json={"query": f"{operation} Shop {{ shop {{ name }} }}"},
                )

        self.assertEqual(requests, [])

    def test_unclassified_post_is_rejected_before_transport(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, request=request)

        http = ReadOnlyHttp(httpx.MockTransport(handler))
        with self.assertRaisesRegex(ToolError, "unclassified POST"):
            http.request(
                "POST",
                "https://store.example/api/inventory/search",
                json={"query": "valve"},
            )

        self.assertEqual(requests, [])

    def test_exact_get_builders_own_the_route_and_query(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, request=request)

        http = ReadOnlyHttp(httpx.MockTransport(handler))
        reads = (
            http.woo_products("https://store.example", "valve", 20),
            http.bigcommerce_search("https://store.example", "valve"),
            http.magento_html_search(
                "https://store.example", "https://store.example/de/", "valve"
            ),
            http.squarespace_search("https://store.example", "valve"),
            http.wix_bootstrap("https://store.example"),
            http.sfcc_search(
                "https://store.example", "https://store.example/en_US/", "valve"
            ),
        )
        for read in reads:
            http.get(read)

        self.assertEqual(
            [request.url.path for request in requests],
            [
                "/wp-json/wc/store/v1/products",
                "/search.php",
                "/de/catalogsearch/result",
                "/search",
                "/_api/v1/access-tokens",
                "/en_US/search",
            ],
        )
        self.assertEqual(
            [value["operation_kind"] for value in http.evidence],
            [
                "woo_products",
                "bigcommerce_search",
                "magento_html_search",
                "squarespace_search",
                "wix_bootstrap",
                "sfcc_search",
            ],
        )

    def test_read_capabilities_cannot_be_forged_or_reused_by_another_http(self) -> None:
        first = ReadOnlyHttp(
            httpx.MockTransport(lambda request: httpx.Response(200, request=request))
        )
        second = ReadOnlyHttp(
            httpx.MockTransport(lambda request: httpx.Response(200, request=request))
        )

        with self.assertRaisesRegex(ValueError, "cannot be publicly forged"):
            ReadGet(object(), object(), object())  # type: ignore[arg-type]
        with self.assertRaisesRegex(ToolError, "another Http instance"):
            second.get(
                first.storefront_entry(
                    "https://store.example/", ["https://store.example"]
                )
            )

    def test_dynamic_product_reads_require_the_exact_source_response(self) -> None:
        http = ReadOnlyHttp(
            httpx.MockTransport(
                lambda request: httpx.Response(
                    200, content=b'<a href="/products/real">Real</a>', request=request
                )
            )
        )
        source = http.get(http.bigcommerce_search("https://store.example", "real"))

        with self.assertRaisesRegex(ToolError, "absent from its source"):
            http.discovered_product_page(
                source, "/products/forged", "https://store.example"
            )

        product = http.get(
            http.discovered_product_page(
                source, "/products/real", "https://store.example"
            )
        )
        self.assertEqual(product.status_code, 200)
        self.assertEqual(
            http.evidence[-1]["source_response_sha256"],
            http.evidence[0]["sha256"],
        )

    def test_exact_route_mutation_and_dynamic_logout_are_rejected_pretransport(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200, content=b'<a href="/logout">Account</a>', request=request
            )

        http = ReadOnlyHttp(httpx.MockTransport(handler))
        with self.assertRaisesRegex(ToolError, "limit must be 1 or 20"):
            http.get(http.woo_products("https://store.example", "valve", 2))  # type: ignore[arg-type]
        source = http.get(http.bigcommerce_search("https://store.example", "valve"))
        with self.assertRaisesRegex(ToolError, "resource purpose"):
            http.get(
                http.discovered_product_page(
                    source, "/logout", "https://store.example"
                )
            )

        self.assertEqual(len(requests), 1)

    def test_method_override_is_rejected_before_transport(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, request=request)

        http = ReadOnlyHttp(httpx.MockTransport(handler))
        cases = [
            ("GET", "https://store.example/products", {}),
            (
                "POST",
                "https://store.example/api/2026-07/graphql.json",
                {"json": {"query": SHOP_QUERY}},
            ),
        ]
        for method, url, kwargs in cases:
            with self.subTest(method=method), self.assertRaisesRegex(
                ToolError, "method override"
            ):
                http.request(
                    method,
                    url,
                    headers={"X-HTTP-Method-Override": "DELETE"},
                    **kwargs,
                )

        self.assertEqual(requests, [])

    def test_http_and_url_credentials_are_rejected_before_transport(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, request=request)

        http = ReadOnlyHttp(httpx.MockTransport(handler))
        for url in (
            "http://store.example/products/valve",
            "https://user:secret@store.example/products/valve",
        ):
            with self.subTest(url=url), self.assertRaisesRegex(
                ToolError, "HTTPS URLs without credentials"
            ):
                http.request("GET", url)

        self.assertEqual(requests, [])

    def test_safe_get_records_closed_read_only_evidence(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"products", request=request)

        http = ReadOnlyHttp(httpx.MockTransport(handler))
        http.get(
            http.magento_html_search(
                "https://store.example", "https://store.example/", "valve"
            )
        )

        self.assertEqual(
            http.evidence[0],
            {
                "method": "GET",
                "requested_url": "https://store.example/catalogsearch/result?q=valve",
                "final_url": "https://store.example/catalogsearch/result?q=valve",
                "status": 200,
                "elapsed_ms": http.evidence[0]["elapsed_ms"],
                "content_type": "",
                "bytes": 8,
                "sha256": "0a3e27b8ca818264d75c8d816c12922c0e6d1c919204e329c580fbc9429ab4f9",
                "operation_kind": "magento_html_search",
                "body_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "document_sha256": None,
                "source_request_sha256": None,
                "source_response_sha256": None,
            },
        )

    def test_secret_query_values_are_redacted_before_evidence_is_saved(self) -> None:
        token = "secret-public-profile-token"
        http = ReadOnlyHttp(httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=(f'{{"token":"{token}"}}').encode(), request=request
            )
        ))
        source = http.request(
            "POST",
            "https://storefront-api.ecwid.com/storefront/api/v1/248360/initial-data",
            json={"lang": "en"},
        )
        http.get(
            http.ecwid_products(source, "248360", token, "valve")
        )

        evidence = str(http.evidence)
        self.assertNotIn("secret-public-profile-token", evidence)
        self.assertIn("token=%5Bredacted%5D", evidence)
        self.assertIn("keyword=valve", evidence)

    def test_ecwid_bare_store_id_query_is_preserved_in_evidence(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            content = (
                b'<script src="https://app.ecwid.com/script.js?248360"></script>'
                if request.url.host == "store.example"
                else b"runtime"
            )
            return httpx.Response(200, content=content, request=request)

        http = ReadOnlyHttp(
            httpx.MockTransport(handler)
        )

        entry = http.get(
            http.storefront_entry(
                "https://store.example/", ["https://store.example"]
            )
        )
        http.get(http.ecwid_script(entry, "248360"))

        self.assertEqual(
            http.evidence[-1]["requested_url"],
            "https://app.ecwid.com/script.js?248360",
        )
        self.assertEqual(
            http.evidence[-1]["final_url"],
            "https://app.ecwid.com/script.js?248360",
        )

    def test_shopify_product_search_is_source_bound(self) -> None:
        http = ReadOnlyHttp(
            httpx.MockTransport(
                lambda request: httpx.Response(200, json={}, request=request)
            )
        )
        http.request(
            "POST",
            "https://store.example/api/2026-07/graphql.json",
            json={"query": PRODUCT_QUERY, "variables": {"query": "valve"}},
        )

        self.assertEqual(http.evidence[0]["operation_kind"], "shopify_product_search")

    def test_magento_probe_is_source_bound(self) -> None:
        http = ReadOnlyHttp(
            httpx.MockTransport(
                lambda request: httpx.Response(200, json={}, request=request)
            )
        )
        http.request(
            "POST",
            "https://store.example/graphql",
            json={"query": DETECT_QUERY, "variables": {}},
        )

        self.assertEqual(http.evidence[0]["operation_kind"], "magento_probe")

    def test_magento_search_is_source_bound(self) -> None:
        http = ReadOnlyHttp(
            httpx.MockTransport(
                lambda request: httpx.Response(200, json={}, request=request)
            )
        )
        http.request(
            "POST",
            "https://store.example/graphql",
            json={"query": SEARCH_QUERY, "variables": {"search": "valve"}},
        )

        self.assertEqual(http.evidence[0]["operation_kind"], "magento_product_search")

    def test_magento_detail_is_source_bound(self) -> None:
        http = ReadOnlyHttp(
            httpx.MockTransport(
                lambda request: httpx.Response(200, json={}, request=request)
            )
        )
        http.request(
            "POST",
            "https://store.example/graphql",
            json={"query": DETAIL_QUERY, "variables": {"sku": "VALVE-1"}},
        )

        self.assertEqual(http.evidence[0]["operation_kind"], "magento_product_detail")

    def test_wix_catalog_query_is_exact_and_does_not_save_its_token(self) -> None:
        http = ReadOnlyHttp(
            httpx.MockTransport(
                lambda request: httpx.Response(200, json={}, request=request)
            )
        )
        filter_value = json.dumps(
            {"name": {"$contains": "valve"}}, separators=(",", ":")
        )
        http.request(
            "POST",
            "https://store.example/_api/catalog-reader-server/api/v1/products/query",
            headers={"Authorization": "public-store-token"},
            json={
                "query": {
                    "filter": filter_value,
                    "paging": {"limit": 10, "offset": 0},
                },
                "includeVariants": True,
            },
        )

        self.assertEqual(http.evidence[0]["operation_kind"], "wix_catalog_search")
        self.assertNotIn("public-store-token", str(http.evidence))

    def test_ecwid_initial_data_is_exact(self) -> None:
        http = ReadOnlyHttp(
            httpx.MockTransport(
                lambda request: httpx.Response(200, json={}, request=request)
            )
        )
        http.request(
            "POST",
            "https://storefront-api.ecwid.com/storefront/api/v1/12345/initial-data",
            json={"lang": "en"},
        )

        self.assertEqual(http.evidence[0]["operation_kind"], "ecwid_initial_data")

    def test_every_request_in_a_safe_redirect_chain_is_authorized(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path == "/search":
                return httpx.Response(
                    302,
                    headers={"Location": "/de-de/search?q=valve"},
                    request=request,
                )
            return httpx.Response(200, request=request)

        http = ReadOnlyHttp(httpx.MockTransport(handler))
        http.get(
            http.sfcc_search(
                "https://store.example", "https://store.example/", "valve"
            )
        )

        self.assertEqual(
            [request.url.path for request in requests], ["/search", "/de-de/search"]
        )
        self.assertEqual(
            http.evidence[1]["final_url"],
            "https://store.example/de-de/search?q=valve",
        )

    def test_unsafe_redirect_is_rejected_before_the_second_transport(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                302, headers={"Location": "https://other.example/search?q=valve"}, request=request
            )

        http = ReadOnlyHttp(httpx.MockTransport(handler))
        with self.assertRaisesRegex(ToolError, "same storefront origin"):
            http.get(
                http.sfcc_search(
                    "https://store.example", "https://store.example/", "valve"
                )
            )

        self.assertEqual(len(requests), 1)

    def test_signed_direct_send_is_checked_before_transport(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, request=request)

        http = ReadOnlyHttp(httpx.MockTransport(handler))
        request = http.client.build_request(
            "POST",
            "https://store.example/api/2026-07/graphql.json",
            json={"query": "mutation CartCreate { cartCreate { cart { id } } }"},
        )
        with self.assertRaisesRegex(ToolError, "mutation"):
            http.send_signed(
                request,
                lambda client, prepared: client.send(prepared),
            )

        self.assertEqual(requests, [])

    def test_signed_sender_is_not_invoked_until_the_request_is_authorized(self) -> None:
        senders: list[httpx.Request] = []
        http = ReadOnlyHttp(
            httpx.MockTransport(
                lambda request: httpx.Response(200, request=request)
            )
        )
        request = http.client.build_request(
            "POST",
            "https://store.example/api/2026-07/graphql.json",
            json={"query": "mutation CartCreate { cartCreate { cart { id } } }"},
        )

        def sender(
            client: httpx.Client, prepared: httpx.Request
        ) -> httpx.Response:
            del client
            senders.append(prepared)
            return httpx.Response(200, request=prepared)

        with self.assertRaisesRegex(ToolError, "mutation"):
            http.send_signed(request, sender)

        self.assertEqual(senders, [])

    def test_graphql_document_digest_mapping_is_immutable(self) -> None:
        self.assertEqual(
            set(GRAPHQL_DOCUMENT_SHA256_BY_OPERATION),
            {
                "shopify_probe",
                "shopify_product_search",
                "magento_probe",
                "magento_product_search",
                "magento_product_detail",
            },
        )
        with self.assertRaises(TypeError):
            GRAPHQL_DOCUMENT_SHA256_BY_OPERATION["shopify_probe"] = "forged"


if __name__ == "__main__":
    unittest.main()
