from __future__ import annotations

import base64
import functools
import hashlib
import json
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


PRIVATE_KEY_PATH = Path("/Users/akelly/.agents/web-bot-auth/private.pem")
KEY_ID = "PtFPEn59EWaohh4V82GazSOYlIBm3LqPOhoLUu--1So"
SIGNATURE_AGENT = "https://lancelotlabs.org"
SIGNATURE_HEADERS = {"signature-agent", "signature-input", "signature"}


def send_signed(client: httpx.Client, request: httpx.Request) -> httpx.Response:
    """Sign and immediately send one HTTPS request without following redirects."""
    return _send_signed(
        client,
        request,
        _validated_key(PRIVATE_KEY_PATH, KEY_ID),
        KEY_ID,
        int(time.time()),
        secrets.token_bytes(64),
    )


def _send_signed(
    client: httpx.Client,
    request: httpx.Request,
    private_key: Ed25519PrivateKey,
    key_id: str,
    created: int,
    nonce: bytes,
) -> httpx.Response:
    if SIGNATURE_HEADERS & set(request.headers):
        raise ValueError("Web Bot Auth request is already signed")
    request.headers.update(_signature_headers(str(request.url), private_key, key_id, created, nonce))
    return client.send(request, follow_redirects=False)


@functools.cache
def _validated_key(path: Path, key_id: str) -> Ed25519PrivateKey:
    private_key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("Web Bot Auth private key must be Ed25519")
    if _key_id(private_key) != key_id:
        raise ValueError(f"Private key does not match configured key ID {key_id}")
    return private_key


def _signature_headers(
    target: str,
    private_key: Ed25519PrivateKey,
    key_id: str,
    created: int,
    nonce: bytes,
) -> dict[str, str]:
    authority = _https_authority(target)
    if len(nonce) != 64:
        raise ValueError("Web Bot Auth nonce must be exactly 64 bytes")
    signature_agent = json.dumps(SIGNATURE_AGENT)
    nonce_base64 = base64.b64encode(nonce).decode("ascii")
    parameters = (
        f'("@authority" "signature-agent");created={created}'
        f';keyid="{key_id}";alg="ed25519";expires={created + 60}'
        f';nonce="{nonce_base64}";tag="web-bot-auth"'
    )
    signature_base = (
        f'"@authority": {authority}\n'
        f'"signature-agent": {signature_agent}\n'
        f'"@signature-params": {parameters}'
    )
    signature = base64.b64encode(private_key.sign(signature_base.encode())).decode("ascii")
    return {
        "Signature-Agent": signature_agent,
        "Signature-Input": f"sig1={parameters}",
        "Signature": f"sig1=:{signature}:",
    }


def _https_authority(target: str) -> str:
    url = urlsplit(target)
    if url.scheme != "https":
        raise ValueError(f"Web Bot Auth target must use HTTPS: {target}")
    if url.username is not None or url.password is not None:
        raise ValueError("Web Bot Auth target must not contain credentials")
    if url.hostname is None:
        raise ValueError(f"Web Bot Auth target has no authority: {target}")
    host = f"[{url.hostname}]" if ":" in url.hostname else url.hostname.encode("idna").decode("ascii").lower()
    return host if url.port in {None, 443} else f"{host}:{url.port}"


def _key_id(private_key: Ed25519PrivateKey) -> str:
    public_key = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    public_jwk = json.dumps(
        {"crv": "Ed25519", "kty": "OKP", "x": _base64url(public_key)},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return _base64url(hashlib.sha256(public_jwk).digest())


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
