# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "cryptography>=45,<47",
#   "httpx>=0.28,<0.29",
# ]
# ///

from __future__ import annotations

import base64
import importlib
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

sys.path.insert(0, str(Path(__file__).parents[1]))
web_bot_auth = importlib.import_module("web_bot_auth")

# RFC 8032 test vector 1. This key is public test material, not a deployed identity.
TEST_PRIVATE_KEY = b"""-----BEGIN PRIVATE KEY-----
MC4CAQAwBQYDK2VwBCIEIJ1hsZ3v/VpguoRK9JLsLMREScVpezJpGXA7rAMcrn9g
-----END PRIVATE KEY-----
"""
TEST_KEY_ID = "kPrK_qmxVWaYVA9wwBF6Iuo3vVzz7TxHCTwXBygrS4k"
TEST_CREATED = 1_700_000_000
TEST_NONCE = bytes(range(64))
TEST_NONCE_BASE64 = (
    "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8gISIjJCUmJygpKissLS4v"
    "MDEyMzQ1Njc4OTo7PD0+Pw=="
)
TEST_SIGNATURE = (
    "vYziIqoJKYvrhq4WSpDyBysfWotGt68VU49emzyyacex8/BXI9kHXBXF5xy4H0t4"
    "ZzfsNmVEvtJ/4BqXihlNBA=="
)


def signature_headers(request: httpx.Request) -> dict[str, str]:
    return {name: request.headers[name] for name in web_bot_auth.SIGNATURE_HEADER_NAMES}


def nonce(headers: dict[str, str]) -> bytes:
    match = re.search(r';nonce="([A-Za-z0-9+/]+=*)";', headers["Signature-Input"])
    if match is None:
        raise AssertionError("Signature-Input has no nonce")
    return base64.b64decode(match.group(1), validate=True)


class SigningProfileTests(unittest.TestCase):
    def tearDown(self) -> None:
        web_bot_auth._validated_private_key.cache_clear()

    def test_deterministic_vector_matches_independent_fixture(self) -> None:
        private_key = serialization.load_pem_private_key(
            TEST_PRIVATE_KEY, password=None
        )
        headers = web_bot_auth._signature_headers(
            web_bot_auth._https_authority(
                httpx.URL("https://EXAMPLE.com:8443/products?query=valve")
            ),
            private_key,
            TEST_KEY_ID,
            TEST_CREATED,
            TEST_NONCE,
        )
        signature_parameters = (
            f'("@authority" "signature-agent");created={TEST_CREATED}'
            f';keyid="{TEST_KEY_ID}";alg="ed25519";expires={TEST_CREATED + 60}'
            f';nonce="{TEST_NONCE_BASE64}";tag="web-bot-auth"'
        )
        self.assertEqual(
            headers,
            {
                "Signature-Agent": '"https://lancelotlabs.org"',
                "Signature-Input": f"sig1={signature_parameters}",
                "Signature": f"sig1=:{TEST_SIGNATURE}:",
            },
        )

        signature_base = (
            '"@authority": example.com:8443\n'
            '"signature-agent": "https://lancelotlabs.org"\n'
            f'"@signature-params": {signature_parameters}'
        )
        private_key.public_key().verify(
            base64.b64decode(TEST_SIGNATURE), signature_base.encode()
        )

    def test_authority_uses_prepared_url_normalization(self) -> None:
        cases = {
            "https://EXAMPLE.com:443/path": "example.com",
            "https://EXAMPLE.com:8443/path": "example.com:8443",
            "https://[2001:db8::1]:8443/path": "[2001:db8::1]:8443",
            "https://b\N{LATIN SMALL LETTER U WITH DIAERESIS}cher.example/path": "xn--bcher-kva.example",
        }
        for target, expected in cases.items():
            with self.subTest(target=target):
                self.assertEqual(
                    web_bot_auth._https_authority(httpx.URL(target)), expected
                )

    def test_rejects_wrong_key_id_and_key_type(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            key_path = Path(directory) / "ed25519.pem"
            key_path.write_bytes(TEST_PRIVATE_KEY)
            with self.assertRaisesRegex(ValueError, "does not match configured key ID"):
                web_bot_auth._validated_private_key(key_path, "wrong-key-id")

            ec_key = ec.generate_private_key(ec.SECP256R1())
            key_path.write_bytes(
                ec_key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
            with self.assertRaisesRegex(ValueError, "must be Ed25519"):
                web_bot_auth._validated_private_key(key_path, TEST_KEY_ID)

    def test_rejects_nonce_with_wrong_length(self) -> None:
        private_key = serialization.load_pem_private_key(
            TEST_PRIVATE_KEY, password=None
        )
        with self.assertRaisesRegex(ValueError, "exactly 64 bytes"):
            web_bot_auth._signature_headers(
                "example.com",
                private_key,
                TEST_KEY_ID,
                TEST_CREATED,
                b"short",
            )


class SignedTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        web_bot_auth._validated_private_key.cache_clear()
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.key_path = Path(self.temporary_directory.name) / "private.pem"
        self.key_path.write_bytes(TEST_PRIVATE_KEY)

    def tearDown(self) -> None:
        web_bot_auth._validated_private_key.cache_clear()
        self.temporary_directory.cleanup()

    def test_sends_immediately_with_fresh_replay_material(self) -> None:
        seen: list[dict[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(signature_headers(request))
            return httpx.Response(200, request=request)

        generated_nonces = mock.Mock(side_effect=(b"a" * 64, b"b" * 64))
        with (
            httpx.Client(transport=httpx.MockTransport(handler)) as client,
            mock.patch.object(web_bot_auth, "PRIVATE_KEY_PATH", self.key_path),
            mock.patch.object(web_bot_auth, "KEY_ID", TEST_KEY_ID),
            mock.patch.object(web_bot_auth.time, "time", return_value=TEST_CREATED),
            mock.patch.object(web_bot_auth.secrets, "token_bytes", generated_nonces),
        ):
            first = web_bot_auth.send_signed(
                client, client.build_request("POST", "https://example.com/one")
            )
            second = web_bot_auth.send_signed(
                client, client.build_request("POST", "https://example.com/two")
            )

        self.assertEqual((first.status_code, second.status_code), (200, 200))
        self.assertEqual(len(seen), 2)
        self.assertEqual(nonce(seen[0]), b"a" * 64)
        self.assertEqual(nonce(seen[1]), b"b" * 64)
        self.assertEqual(
            generated_nonces.call_args_list, [mock.call(64), mock.call(64)]
        )
        self.assertNotEqual(seen[0]["Signature-Input"], seen[1]["Signature-Input"])
        self.assertNotEqual(seen[0]["Signature"], seen[1]["Signature"])
        for headers in seen:
            self.assertEqual(set(headers), set(web_bot_auth.SIGNATURE_HEADER_NAMES))
            self.assertIn(";created=1700000000;", headers["Signature-Input"])
            self.assertIn(";expires=1700000060;", headers["Signature-Input"])

    def test_redirect_is_returned_and_never_forwards_a_signature(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if request.url.host == "first.example":
                return httpx.Response(
                    307,
                    headers={"Location": "https://second.example/graphql"},
                    request=request,
                )
            return httpx.Response(200, request=request)

        generated_nonces = iter((b"a" * 64, b"b" * 64))
        with (
            httpx.Client(
                transport=httpx.MockTransport(handler), follow_redirects=True
            ) as client,
            mock.patch.object(web_bot_auth, "PRIVATE_KEY_PATH", self.key_path),
            mock.patch.object(web_bot_auth, "KEY_ID", TEST_KEY_ID),
            mock.patch.object(web_bot_auth.time, "time", return_value=TEST_CREATED),
            mock.patch.object(
                web_bot_auth.secrets,
                "token_bytes",
                side_effect=lambda length: next(generated_nonces),
            ),
        ):
            redirected = web_bot_auth.send_signed(
                client,
                client.build_request("POST", "https://first.example/graphql"),
            )
            self.assertEqual(redirected.status_code, 307)
            self.assertEqual([request.url.host for request in seen], ["first.example"])

            completed = web_bot_auth.send_signed(
                client,
                client.build_request("POST", redirected.headers["Location"]),
            )

        self.assertEqual(completed.status_code, 200)
        self.assertEqual(
            [request.url.host for request in seen], ["first.example", "second.example"]
        )
        self.assertNotEqual(seen[0].headers["Signature"], seen[1].headers["Signature"])

    def test_reusing_a_signed_request_is_rejected_before_transport(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, request=request)

        with (
            httpx.Client(transport=httpx.MockTransport(handler)) as client,
            mock.patch.object(web_bot_auth, "PRIVATE_KEY_PATH", self.key_path),
            mock.patch.object(web_bot_auth, "KEY_ID", TEST_KEY_ID),
        ):
            request = client.build_request("GET", "https://example.com/")
            web_bot_auth.send_signed(client, request)
            with self.assertRaisesRegex(ValueError, "already contains Signature-Agent"):
                web_bot_auth.send_signed(client, request)

        self.assertEqual(calls, 1)

    def test_rejects_invalid_targets_before_transport(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, request=request)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            cases = (
                (client.build_request("GET", "http://example.com/"), "must use HTTPS"),
                (httpx.Request("GET", "https:///path"), "has no authority"),
                (
                    client.build_request("GET", "https://user:password@example.com/"),
                    "must not contain credentials",
                ),
            )
            for request, message in cases:
                with (
                    self.subTest(target=str(request.url)),
                    self.assertRaisesRegex(ValueError, message),
                ):
                    web_bot_auth.send_signed(client, request)
        self.assertEqual(calls, 0)

    def test_rejects_every_preexisting_signature_header_case_insensitively(
        self,
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("invalid request reached transport")

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            for name in ("signature-agent", "SIGNATURE-INPUT", "Signature"):
                with (
                    self.subTest(name=name),
                    self.assertRaisesRegex(ValueError, "already contains"),
                ):
                    request = client.build_request(
                        "GET", "https://example.com/", headers={name: "replayable"}
                    )
                    web_bot_auth.send_signed(client, request)

    def test_caches_only_the_validated_key(self) -> None:
        seen: list[dict[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(signature_headers(request))
            return httpx.Response(200, request=request)

        generated_nonces = iter((b"a" * 64, b"b" * 64))
        with (
            httpx.Client(transport=httpx.MockTransport(handler)) as client,
            mock.patch.object(web_bot_auth, "PRIVATE_KEY_PATH", self.key_path),
            mock.patch.object(web_bot_auth, "KEY_ID", TEST_KEY_ID),
            mock.patch.object(web_bot_auth.time, "time", return_value=TEST_CREATED),
            mock.patch.object(
                web_bot_auth.secrets,
                "token_bytes",
                side_effect=lambda length: next(generated_nonces),
            ),
        ):
            web_bot_auth.send_signed(
                client, client.build_request("GET", "https://example.com/one")
            )
            self.key_path.write_bytes(
                b"the cached key must make this unreadable replacement irrelevant"
            )
            web_bot_auth.send_signed(
                client, client.build_request("GET", "https://example.com/two")
            )

        cache_info = web_bot_auth._validated_private_key.cache_info()
        self.assertEqual(
            (cache_info.misses, cache_info.hits, cache_info.currsize), (1, 1, 1)
        )
        self.assertNotEqual(seen[0]["Signature-Input"], seen[1]["Signature-Input"])
        self.assertNotEqual(seen[0]["Signature"], seen[1]["Signature"])

    def test_header_factory_is_not_public(self) -> None:
        self.assertEqual(web_bot_auth.__all__, ["send_signed"])
        self.assertFalse(hasattr(web_bot_auth, "web_bot_auth_headers"))


if __name__ == "__main__":
    unittest.main()
