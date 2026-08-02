from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from functools import cache
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

__all__ = ["send_signed"]

PRIVATE_KEY_PATH = Path("/Users/akelly/.agents/web-bot-auth/private.pem")
KEY_ID = "PtFPEn59EWaohh4V82GazSOYlIBm3LqPOhoLUu--1So"
SIGNATURE_AGENT = "https://lancelotlabs.org"
SIGNATURE_HEADER_NAMES = ("Signature-Agent", "Signature-Input", "Signature")


def send_signed(client: httpx.Client, request: httpx.Request) -> httpx.Response:
    for name in SIGNATURE_HEADER_NAMES:
        if name in request.headers:
            raise ValueError(f"Web Bot Auth request already contains {name}")

    authority = _https_authority(request.url)
    private_key = _validated_private_key(PRIVATE_KEY_PATH, KEY_ID)
    request.headers.update(
        _signature_headers(
            authority,
            private_key,
            KEY_ID,
            int(time.time()),
            secrets.token_bytes(64),
        )
    )
    return client.send(request, follow_redirects=False)


@cache
def _validated_private_key(path: Path, key_id: str) -> Ed25519PrivateKey:
    private_key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("Web Bot Auth private key must be Ed25519")  # noqa: TRY004
    if _key_id(private_key) != key_id:
        raise ValueError(f"Private key does not match configured key ID {key_id}")
    return private_key


def _signature_headers(
    authority: str,
    private_key: Ed25519PrivateKey,
    key_id: str,
    created: int,
    nonce: bytes,
) -> dict[str, str]:
    if len(nonce) != 64:
        raise ValueError("Web Bot Auth nonce must be exactly 64 bytes")

    signature_agent = json.dumps(SIGNATURE_AGENT)
    nonce_base64 = base64.b64encode(nonce).decode("ascii")
    signature_parameters = (
        f'("@authority" "signature-agent");created={created}'
        f';keyid="{key_id}";alg="ed25519";expires={created + 60}'
        f';nonce="{nonce_base64}";tag="web-bot-auth"'
    )
    signature_base = (
        f'"@authority": {authority}\n'
        f'"signature-agent": {signature_agent}\n'
        f'"@signature-params": {signature_parameters}'
    )
    signature = base64.b64encode(private_key.sign(signature_base.encode())).decode(
        "ascii"
    )
    return {
        "Signature-Agent": signature_agent,
        "Signature-Input": f"sig1={signature_parameters}",
        "Signature": f"sig1=:{signature}:",
    }


def _https_authority(target: httpx.URL) -> str:
    if target.scheme != "https":
        raise ValueError(f"Web Bot Auth target must use HTTPS: {target}")
    if target.userinfo:
        raise ValueError("Web Bot Auth target must not contain credentials")
    if not target.host:
        raise ValueError(f"Web Bot Auth target has no authority: {target}")

    host = target.host
    if ":" in host:
        host = f"[{host}]"
    else:
        host = host.encode("idna").decode("ascii")
    return host if target.port is None else f"{host}:{target.port}"


def _key_id(private_key: Ed25519PrivateKey) -> str:
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    public_jwk = json.dumps(
        {
            "crv": "Ed25519",
            "kty": "OKP",
            "x": _base64url(public_key),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return _base64url(hashlib.sha256(public_jwk).digest())


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
