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
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

import httpx

sys.path.insert(0, str(Path(__file__).parents[1]))

import platform_api  # noqa: E402
from platform_api_core import (  # noqa: E402
    Detection,
    Http,
    ToolError,
    item_ref,
    search_result,
)


def detected(platform: str = "shopify") -> Detection:
    return Detection(
        kind="detected",
        origin="https://store.example",
        entry_url="https://store.example/",
        platform=platform,
        api_origin="https://store.example",
        evidence=("positive API response",),
    )


class FakeAdapter:
    def __init__(self, items: list[dict[str, object]]) -> None:
        self.items = items
        self.quoted: list[str] = []

    def search(self, http: Http, detection: Detection, query: str) -> dict[str, object]:
        return search_result("shopify", query, self.items)

    def quote(
        self, http: Http, detection: Detection, reference: str
    ) -> dict[str, object]:
        self.quoted.append(reference)
        return {
            "kind": "unsupported_operation",
            "operation": "quote",
            "platform": "shopify",
            "reason": "test boundary",
            "browser_required": True,
        }


class DetectionTests(unittest.TestCase):
    def test_shopify_redirect_boundary_allows_later_magento_detection(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET" and request.url.path == "/":
                return httpx.Response(
                    200,
                    text='<script type="text/x-magento-init">{}</script>',
                    request=request,
                )
            if request.url.path == "/wp-json/wc/store/v1/cart":
                return httpx.Response(404, request=request)
            if request.url.path == "/api/2026-07/graphql.json":
                return httpx.Response(
                    307,
                    headers={"Location": "https://different.example/graphql"},
                    request=request,
                )
            if request.url.path == "/rest/V1/guest-carts":
                return httpx.Response(
                    200, json="guest-token-secret-1234567890", request=request
                )
            raise AssertionError(request.url)

        def unsigned_send(
            client: httpx.Client, request: httpx.Request
        ) -> httpx.Response:
            return client.send(request, follow_redirects=False)

        http = Http(httpx.MockTransport(handler))
        with mock.patch.object(
            platform_api.shopify, "send_signed", side_effect=unsigned_send
        ):
            result = platform_api.detect_store(http, "store.example")

        self.assertEqual(result.platform, "magento")
        self.assertEqual(result.evidence, ("magento_guest_cart_token",))

    def test_conflicting_positive_platforms_fail_loudly(self) -> None:
        def home(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="store", request=request)

        http = Http(httpx.MockTransport(home))
        with (
            mock.patch.object(platform_api.woocommerce, "detect", return_value=None),
            mock.patch.object(
                platform_api.shopify, "detect", return_value=detected("shopify")
            ),
            mock.patch.object(platform_api.magento, "detect", return_value=None),
            mock.patch.object(
                platform_api.bigcommerce, "detect", return_value=detected("bigcommerce")
            ),
            mock.patch.object(platform_api.squarespace, "detect", return_value=None),
            mock.patch.object(platform_api.extra, "detect", return_value=None),
            self.assertRaisesRegex(
                ToolError, "Conflicting positive storefront detections"
            ),
        ):
            platform_api.detect_store(http, "store.example")

    def test_unknown_detection_is_explicit(self) -> None:
        def home(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="custom store", request=request)

        http = Http(httpx.MockTransport(home))
        with (
            mock.patch.object(platform_api.woocommerce, "detect", return_value=None),
            mock.patch.object(platform_api.shopify, "detect", return_value=None),
            mock.patch.object(platform_api.magento, "detect", return_value=None),
            mock.patch.object(platform_api.bigcommerce, "detect", return_value=None),
            mock.patch.object(platform_api.squarespace, "detect", return_value=None),
            mock.patch.object(platform_api.extra, "detect", return_value=None),
        ):
            result = platform_api.detect_store(http, "store.example")
        self.assertEqual(result.kind, "unknown")
        self.assertIn("No positive platform signal", result.evidence[0])


class EntrypointTests(unittest.TestCase):
    def test_probe_selects_first_usable_exact_reference(self) -> None:
        unavailable = item_ref("shopify", {"variant_id": "unavailable"})
        available = item_ref("shopify", {"variant_id": "available"})
        adapter = FakeAdapter(
            [
                {"item_ref": unavailable, "available": False},
                {"item_ref": available, "available": True},
            ]
        )
        with (
            mock.patch.object(platform_api, "detect_store", return_value=detected()),
            mock.patch.dict(platform_api.ADAPTERS, {"shopify": adapter}),
        ):
            record = platform_api.execute(
                "probe",
                "store.example",
                "valve",
                Http(httpx.MockTransport(lambda request: None)),
            )
        self.assertEqual(adapter.quoted, [available])
        self.assertEqual(record["result"]["kind"], "unsupported_operation")
        self.assertEqual(record["search"]["kind"], "search")

    def test_no_usable_candidate_keeps_the_search_result(self) -> None:
        reference = item_ref("shopify", {"variant_id": "configured"})
        adapter = FakeAdapter([{"item_ref": reference, "requires_configuration": True}])
        with (
            mock.patch.object(platform_api, "detect_store", return_value=detected()),
            mock.patch.dict(platform_api.ADAPTERS, {"shopify": adapter}),
        ):
            record = platform_api.execute(
                "probe",
                "store.example",
                "valve",
                Http(httpx.MockTransport(lambda request: None)),
            )
        self.assertEqual(adapter.quoted, [])
        self.assertEqual(record["result"]["kind"], "search")

    def test_probe_skips_nonpurchasable_item_and_quotes_the_next_candidate(
        self,
    ) -> None:
        quote_only = item_ref("shopify", {"variant_id": "quote-only"})
        available = item_ref("shopify", {"variant_id": "available"})
        adapter = FakeAdapter(
            [
                {
                    "item_ref": quote_only,
                    "available": True,
                    "purchasable": False,
                    "price": None,
                },
                {"item_ref": available, "available": True},
            ]
        )
        with (
            mock.patch.object(platform_api, "detect_store", return_value=detected()),
            mock.patch.dict(platform_api.ADAPTERS, {"shopify": adapter}),
        ):
            platform_api.execute(
                "probe",
                "store.example",
                "valve",
                Http(httpx.MockTransport(lambda request: None)),
            )

        self.assertEqual(adapter.quoted, [available])

    def test_parser_exposes_search_and_no_products_alias(self) -> None:
        parser = platform_api._parser()
        self.assertEqual(
            parser.parse_args(["search", "store.example", "valve"]).command, "search"
        )
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["products", "store.example", "valve"])


class CorpusTests(unittest.TestCase):
    def test_corpus_resumes_exact_store_query_identities(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.json"
            output_path = root / "output.jsonl"
            input_path.write_text(
                json.dumps(
                    [
                        {"store": "https://one.example", "query": "valve"},
                        {"store": "https://two.example", "query": "bearing"},
                    ]
                )
            )
            output_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "input": {"store": "https://one.example", "query": "valve"},
                        "detection": {"kind": "unknown"},
                    }
                )
                + "\n"
            )

            def execute(
                command: str, store: str, query: str, http: Http
            ) -> dict[str, object]:
                return {
                    "schema_version": 1,
                    "input": {"store": store, "query": query},
                    "detection": {"kind": "unknown"},
                }

            with mock.patch.object(platform_api, "execute", side_effect=execute) as run:
                self.assertTrue(platform_api.run_corpus(input_path, output_path))
            self.assertEqual(run.call_count, 1)
            self.assertEqual(
                run.call_args.args[1:3], ("https://two.example", "bearing")
            )
            self.assertEqual(len(output_path.read_text().splitlines()), 2)

    def test_corpus_rejects_extra_job_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_text(json.dumps([{"store": "x", "query": "y", "extra": "z"}]))
            with self.assertRaisesRegex(ToolError, "exactly store and query"):
                platform_api._corpus_jobs(path)


if __name__ == "__main__":
    unittest.main()
