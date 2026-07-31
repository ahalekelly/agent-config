# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "cryptography>=45,<46",
#   "httpx>=0.28,<0.29",
#   "pytest>=8,<9",
# ]
# ///

from __future__ import annotations

import base64
import re
import sys
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


sys.path.insert(0, str(Path(__file__).parents[1]))
import web_bot_auth  # noqa: E402


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


def private_key():
    return serialization.load_pem_private_key(TEST_PRIVATE_KEY, password=None)


def test_matches_independent_node_crypto_fixture() -> None:
    headers = web_bot_auth._signature_headers(
        "https://EXAMPLE.com:8443/products?query=valve",
        private_key(),
        TEST_KEY_ID,
        TEST_CREATED,
        TEST_NONCE,
    )
    parameters = (
        f'("@authority" "signature-agent");created={TEST_CREATED}'
        f';keyid="{TEST_KEY_ID}";alg="ed25519";expires={TEST_CREATED + 60}'
        f';nonce="{TEST_NONCE_BASE64}";tag="web-bot-auth"'
    )
    assert headers == {
        "Signature-Agent": '"https://lancelotlabs.org"',
        "Signature-Input": f"sig1={parameters}",
        "Signature": f"sig1=:{TEST_SIGNATURE}:",
    }
    signature_base = (
        '"@authority": example.com:8443\n'
        '"signature-agent": "https://lancelotlabs.org"\n'
        f'"@signature-params": {parameters}'
    )
    private_key().public_key().verify(base64.b64decode(TEST_SIGNATURE), signature_base.encode())


def test_public_api_signs_and_sends_immediately_with_cached_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    key_path = tmp_path / "test-private.pem"
    key_path.write_bytes(TEST_PRIVATE_KEY)
    nonces = iter((b"a" * 64, b"b" * 64))
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"ok": True}, request=request)

    monkeypatch.setattr(web_bot_auth, "PRIVATE_KEY_PATH", key_path)
    monkeypatch.setattr(web_bot_auth, "KEY_ID", TEST_KEY_ID)
    monkeypatch.setattr(web_bot_auth.time, "time", lambda: TEST_CREATED)
    monkeypatch.setattr(web_bot_auth.secrets, "token_bytes", lambda length: next(nonces) if length == 64 else b"")
    web_bot_auth._validated_key.cache_clear()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        for path in ("one", "two"):
            response = web_bot_auth.send_signed(client, client.build_request("GET", f"https://example.com/{path}"))
            assert response.status_code == 200

    assert len(captured) == 2
    assert web_bot_auth._validated_key.cache_info().misses == 1
    assert web_bot_auth._validated_key.cache_info().hits == 1
    assert _nonce(captured[0].headers) == b"a" * 64
    assert _nonce(captured[1].headers) == b"b" * 64
    assert captured[0].headers["signature"] != captured[1].headers["signature"]
    assert ';created=1700000000;' in captured[0].headers["signature-input"]
    assert ';expires=1700000060;' in captured[0].headers["signature-input"]


@pytest.mark.parametrize("header", sorted(web_bot_auth.SIGNATURE_HEADERS))
def test_rejects_already_signed_requests(header: str) -> None:
    request = httpx.Request("GET", "https://example.com", headers={header: "replay"})
    with httpx.Client(transport=httpx.MockTransport(lambda request: pytest.fail("must not send"))) as client:
        with pytest.raises(ValueError, match="already signed"):
            web_bot_auth._send_signed(client, request, private_key(), TEST_KEY_ID, TEST_CREATED, TEST_NONCE)


@pytest.mark.parametrize("target", ["http://example.com", "example.com", "https://user@example.com"])
def test_rejects_invalid_https_authority(target: str) -> None:
    with pytest.raises(ValueError, match="HTTPS|credentials"):
        web_bot_auth._signature_headers(target, private_key(), TEST_KEY_ID, TEST_CREATED, TEST_NONCE)


def test_serializes_idna_and_ipv6_authorities() -> None:
    assert web_bot_auth._https_authority("https://BÜCHER.example:8443/x") == "xn--bcher-kva.example:8443"
    assert web_bot_auth._https_authority("https://[2001:db8::1]:8443/x") == "[2001:db8::1]:8443"


def test_rejects_wrong_key_thumbprint(tmp_path: Path) -> None:
    path = tmp_path / "wrong.pem"
    path.write_bytes(TEST_PRIVATE_KEY)
    web_bot_auth._validated_key.cache_clear()
    with pytest.raises(ValueError, match="does not match configured key ID"):
        web_bot_auth._validated_key(path, web_bot_auth.KEY_ID)


def test_rejects_non_ed25519_key(tmp_path: Path) -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    path = tmp_path / "ec.pem"
    path.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    web_bot_auth._validated_key.cache_clear()
    with pytest.raises(ValueError, match="must be Ed25519"):
        web_bot_auth._validated_key(path, TEST_KEY_ID)


def test_rejects_nonce_with_wrong_length() -> None:
    with pytest.raises(ValueError, match="exactly 64 bytes"):
        web_bot_auth._signature_headers("https://example.com", private_key(), TEST_KEY_ID, TEST_CREATED, b"short")


def _nonce(headers: httpx.Headers) -> bytes:
    match = re.search(r';nonce="([A-Za-z0-9+/]+=*)";', headers["signature-input"])
    assert match is not None
    return base64.b64decode(match.group(1), validate=True)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
