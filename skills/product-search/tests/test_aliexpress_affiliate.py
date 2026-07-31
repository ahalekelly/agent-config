import contextlib
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs


SCRIPT = Path(__file__).parents[1] / "scripts" / "aliexpress_affiliate.py"
SPEC = importlib.util.spec_from_file_location("aliexpress_affiliate", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Cannot import {SCRIPT}")
aliexpress = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = aliexpress
SPEC.loader.exec_module(aliexpress)


class SigningTests(unittest.TestCase):
    def test_canonical_top_hmac_md5_signature(self) -> None:
        parameters = {
            "foobar": "4",
            "foo_bar": "3",
            "bar": "2",
            "foo": "1",
        }

        self.assertEqual(
            aliexpress.signature(parameters, "secret"),
            "26C775E5D0EB124C248184BFA79CA514",
        )

    def test_signature_rejects_empty_secret(self) -> None:
        with self.assertRaisesRegex(ValueError, "secret must not be empty"):
            aliexpress.signature({"foo": "1"}, "")


class ValidationTests(unittest.TestCase):
    def test_invalid_arguments_exit_with_specific_error(self) -> None:
        cases = (
            (["   "], "query must not be empty"),
            (["pliers", "--page", "0"], "--page must be at least 1"),
            (
                ["pliers", "--page-size", "0"],
                "--page-size must be between 1 and 50",
            ),
            (
                ["pliers", "--page-size", "51"],
                "--page-size must be between 1 and 50",
            ),
            (["pliers", "--min-price", "-1"], "--min-price cannot be negative"),
            (["pliers", "--max-price", "-1"], "--max-price cannot be negative"),
            (
                ["pliers", "--min-price", "20", "--max-price", "10"],
                "--min-price cannot exceed --max-price",
            ),
        )

        for argv, message in cases:
            with self.subTest(argv=argv):
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr), self.assertRaises(
                    SystemExit
                ) as raised:
                    aliexpress.parse_arguments(argv)
                self.assertEqual(raised.exception.code, 2)
                self.assertIn(message, stderr.getvalue())

    def test_credentials_are_required_and_nonempty(self) -> None:
        cases = (
            ({}, "ALIEXPRESS_APP_KEY is required"),
            ({"ALIEXPRESS_APP_KEY": "   "}, "ALIEXPRESS_APP_KEY is required"),
            ({"ALIEXPRESS_APP_KEY": "key"}, "ALIEXPRESS_APP_SECRET is required"),
            (
                {"ALIEXPRESS_APP_KEY": "key", "ALIEXPRESS_APP_SECRET": " "},
                "ALIEXPRESS_APP_SECRET is required",
            ),
        )

        for environ, message in cases:
            with self.subTest(environ=environ), self.assertRaisesRegex(
                SystemExit, message
            ):
                aliexpress.credentials(environ)

    def test_parameters_preserve_zero_price_and_requested_filters(self) -> None:
        args = aliexpress.parse_arguments(
            [
                "  Knipex Cobra  ",
                "--page",
                "2",
                "--page-size",
                "10",
                "--min-price",
                "0",
                "--max-price",
                "90",
                "--sort",
                "SALE_PRICE_ASC",
                "--delivery-days",
                "7",
            ]
        )

        self.assertEqual(
            aliexpress.parameters_for(args, "app-key", "2026-07-31 20:15:00"),
            {
                "app_key": "app-key",
                "delivery_days": "7",
                "format": "json",
                "keywords": "Knipex Cobra",
                "max_sale_price": "90",
                "method": "aliexpress.affiliate.product.query",
                "min_sale_price": "0",
                "page_no": "2",
                "page_size": "10",
                "ship_to_country": "US",
                "sign_method": "hmac",
                "sort": "SALE_PRICE_ASC",
                "target_currency": "USD",
                "target_language": "EN",
                "timestamp": "2026-07-31 20:15:00",
                "v": "2.0",
            },
        )


class ResponseTests(unittest.TestCase):
    def test_request_posts_form_and_returns_raw_success_envelope(self) -> None:
        payload = {
            aliexpress.RESPONSE_KEY: {
                "resp_result": {
                    "resp_code": 200,
                    "result": {"products": {"product": []}},
                }
            }
        }
        seen = {}

        def opener(request, timeout):
            seen["request"] = request
            seen["timeout"] = timeout
            return io.BytesIO(json.dumps(payload).encode("utf-8"))

        result = aliexpress.request_products(
            {"keywords": "café pliers", "sign": "ABC123"}, opener
        )

        request = seen["request"]
        self.assertEqual(result, payload)
        self.assertEqual(seen["timeout"], 30)
        self.assertEqual(request.full_url, aliexpress.ENDPOINT)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(
            request.get_header("Content-type"),
            "application/x-www-form-urlencoded;charset=utf-8",
        )
        self.assertEqual(
            parse_qs(request.data.decode("utf-8")),
            {"keywords": ["café pliers"], "sign": ["ABC123"]},
        )

    def test_provider_error_exits_with_provider_details(self) -> None:
        payload = {
            "error_response": {
                "code": 29,
                "msg": "Invalid app Key",
                "request_id": "request-1",
            }
        }

        with self.assertRaisesRegex(
            SystemExit,
            r'^AliExpress API error: \{"code": 29, "msg": "Invalid app Key", '
            r'"request_id": "request-1"\}$',
        ):
            aliexpress.request_products(
                {"sign": "BAD"},
                lambda request, timeout: io.BytesIO(
                    json.dumps(payload).encode("utf-8")
                ),
            )

    def test_product_query_error_exits_with_response_details(self) -> None:
        payload = {
            aliexpress.RESPONSE_KEY: {
                "resp_result": {"resp_code": 300, "resp_msg": "invalid parameters"}
            }
        }

        with self.assertRaisesRegex(
            SystemExit,
            r'^AliExpress product query failed: \{"resp_code": 300, '
            r'"resp_msg": "invalid parameters"\}$',
        ):
            aliexpress.parse_response(payload)

    def test_malformed_envelopes_fail_loudly(self) -> None:
        cases = (
            ([], "AliExpress returned a non-object JSON response"),
            (
                {"error_response": "bad"},
                "AliExpress returned a malformed error_response",
            ),
            (
                {"unexpected": {}},
                f"AliExpress response is missing {aliexpress.RESPONSE_KEY}",
            ),
            (
                {aliexpress.RESPONSE_KEY: {}},
                "AliExpress response is missing resp_result",
            ),
        )

        for payload, message in cases:
            with self.subTest(payload=payload), self.assertRaisesRegex(
                SystemExit, message
            ):
                aliexpress.parse_response(payload)


if __name__ == "__main__":
    unittest.main()
