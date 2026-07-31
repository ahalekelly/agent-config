from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Literal, Never, TypedDict, assert_never
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import httpx


Status = Literal["quoted", "no_quote", "fallback", "gated", "bot_wall", "unsupported", "api_error"]
Disposition = Literal["delivery", "pickup", "paid_later", "unavailable", "fallback"]
DetectionState = Literal["detected", "unknown", "bot_wall"]
STATUSES = {"quoted", "no_quote", "fallback", "gated", "bot_wall", "unsupported", "api_error"}
DISPOSITIONS = {"delivery", "pickup", "paid_later", "unavailable", "fallback"}
DETECTION_STATES = {"detected", "unknown", "bot_wall"}
PLATFORMS = {"shopify", "woocommerce", "magento", "bigcommerce", "squarespace", "wix", "ecwid", "sfcc"}
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"


class ToolError(RuntimeError):
    pass


class Money(TypedDict):
    amount: str
    currency: str | None


class ShippingOption(TypedDict):
    id: str
    title: str
    disposition: Disposition
    amount: Money | None


class DeliveryRate(TypedDict):
    option_id: str
    title: str
    amount: Money


class QuoteResult(TypedDict, total=False):
    status: Status
    platform: str
    shipping_options: list[ShippingOption]
    delivery_rates: list[DeliveryRate]
    subtotal: Money | None
    destination: str
    reason: str
    stage: str
    http_status: int
    system: str
    evidence: list[dict[str, Any]]


@dataclass(frozen=True)
class Detection:
    state: DetectionState
    origin: str
    platform: str | None
    api_origin: str | None
    evidence: tuple[str, ...]
    system: str | None = None
    http_status: int | None = None

    def __post_init__(self) -> None:
        if self.state not in DETECTION_STATES:
            raise ToolError(f"unknown detection state: {self.state}")
        if self.state == "detected":
            if self.platform not in PLATFORMS or self.api_origin is None:
                raise ToolError("detected storefront requires a supported platform and API origin")
        elif self.platform is not None or self.api_origin is not None:
            raise ToolError(f"{self.state} storefront cannot name a platform or API origin")

    def public(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "state": self.state,
            "origin": self.origin,
            "platform": self.platform,
            "evidence": list(self.evidence),
        }
        if self.api_origin != self.origin:
            value["api_origin"] = self.api_origin
        if self.system:
            value.update(system=self.system, http_status=self.http_status)
        return value


def origin(value: str) -> str:
    url = value if "://" in value else f"https://{value}"
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ToolError("store must be an absolute HTTPS origin without credentials")
    if parts.query or parts.fragment:
        raise ToolError("store must not contain a query or fragment")
    host = parts.hostname.encode("idna").decode().lower()
    port = "" if parts.port in {None, 443} else f":{parts.port}"
    return f"https://{host}{port}"


def redact_url(value: str) -> str:
    parts = urlsplit(value)
    path = re.sub(r"/(guest-carts|commerce/cart|checkouts?)/[^/]+", r"/\1/[redacted]", parts.path)
    path = re.sub(r"(/wp-json/wc/store/v1/cart/items)/[^/]+", r"\1/[redacted]", path)
    query = urlencode([
        (name, "[redacted]" if name.lower() in {"token", "key", "api_key", "access_token"} else item)
        for name, item in parse_qsl(parts.query)
    ])
    return urlunsplit((parts.scheme, parts.netloc, path, query, ""))


def money(amount: Any, currency: Any = None) -> Money:
    if isinstance(amount, bool) or not isinstance(amount, (str, int, float, Decimal)):
        raise ToolError(f"invalid money amount type: {type(amount).__name__}")
    if currency is not None and not isinstance(currency, str):
        raise ToolError("money currency must be a string or null")
    return {"amount": format(Decimal(str(amount)), "f"), "currency": currency}


def minor_money(amount: Any, currency: Any, digits: Any) -> Money:
    if not isinstance(amount, str) or not re.fullmatch(r"-?\d+", amount):
        raise ToolError("minor-unit money must be an integer string")
    if not isinstance(digits, int):
        raise ToolError("currency_minor_unit must be an integer")
    value = Decimal(amount).scaleb(-digits)
    return {"amount": f"{value:.{digits}f}", "currency": currency}


def option(option_id: Any, title: Any, disposition: Disposition, amount: Money | None, **facts: Any) -> dict[str, Any]:
    if not isinstance(option_id, str) or not option_id or not isinstance(title, str) or not title:
        raise ToolError("shipping option requires a nonempty id and title")
    if disposition not in DISPOSITIONS:
        raise ToolError(f"unknown shipping disposition: {disposition}")
    return {"id": option_id, "title": title, "disposition": disposition, "amount": amount, **facts}


def quote_result(
    status: Status,
    platform: str,
    shipping_options: list[dict[str, Any]] | None = None,
    *,
    subtotal: Money | None = None,
    reason: str | None = None,
    **facts: Any,
) -> QuoteResult:
    if status not in STATUSES:
        raise ToolError(f"unknown quote status: {status}")
    options = shipping_options or []
    for item in options:
        if item.get("disposition") not in DISPOSITIONS:
            raise ToolError("shipping option has an invalid disposition")
    delivery = [
        {"option_id": item["id"], "title": item["title"], "amount": item["amount"]}
        for item in options
        if item["disposition"] == "delivery" and item["amount"] is not None
    ]
    if status == "quoted" and not delivery:
        raise ToolError("quoted requires at least one comparable delivery rate")
    if status == "no_quote" and reason is None:
        raise ToolError("no_quote requires a reason")
    if status in {"gated", "bot_wall", "unsupported", "api_error"} and options:
        raise ToolError(f"{status} cannot carry shipping options")
    result: QuoteResult = {
        "status": status,
        "platform": platform,
        "shipping_options": options,
        "delivery_rates": delivery,
        "subtotal": subtotal,
        "destination": "dummy_sf",
        **facts,
    }
    if reason is not None:
        result["reason"] = reason
    validate_result(result)
    return result


def validate_result(result: QuoteResult) -> None:
    status = result["status"]
    match status:
        case "quoted" | "no_quote" | "fallback" | "gated" | "bot_wall" | "unsupported" | "api_error":
            return
        case never:
            assert_never(never)


def item_ref(platform: str, value: dict[str, Any]) -> str:
    raw = json.dumps({"platform": platform, **value}, sort_keys=True, separators=(",", ":")).encode()
    return "item-v1." + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def parse_ref(platform: str, reference: str) -> dict[str, Any]:
    if not reference.startswith("item-v1."):
        raise ToolError(f"{platform} requires an item_ref returned by products")
    try:
        value = json.loads(base64.urlsafe_b64decode(reference[8:] + "=" * (-len(reference[8:]) % 4)))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ToolError("malformed item_ref") from error
    if not isinstance(value, dict) or value.pop("platform", None) != platform:
        raise ToolError(f"item_ref does not belong to {platform}")
    return value


def bot_system(response: httpx.Response) -> str | None:
    body = response.text[:50_000].lower()
    if response.headers.get("cf-mitigated", "").lower() == "challenge" or "/cdn-cgi/challenge-platform" in body:
        return "cloudflare"
    if "datadome" in body or "captcha-delivery.com" in body:
        return "datadome"
    if "bunny-shield" in body or "shield-challenge.js" in body:
        return "bunny_shield"
    return None


class Http:
    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self.client = httpx.Client(
            transport=transport,
            timeout=httpx.Timeout(45, connect=10),
            headers={"User-Agent": USER_AGENT},
            follow_redirects=False,
        )
        self.evidence: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        return self._capture(method, url, lambda: self.client.request(method, url, **kwargs))

    def send(
        self,
        request: httpx.Request,
        sender: Callable[[httpx.Client, httpx.Request], httpx.Response],
    ) -> httpx.Response:
        return self._capture(
            request.method,
            str(request.url),
            lambda: sender(self.client, request),
        )

    def _capture(
        self,
        method: str,
        url: str,
        send: Callable[[], httpx.Response],
    ) -> httpx.Response:
        started = time.monotonic()
        try:
            response = send()
        except httpx.HTTPError as error:
            raise ToolError(f"{method} {redact_url(url)} failed: {type(error).__name__}") from error
        self.evidence.append(
            {
                "method": method,
                "url": redact_url(str(response.request.url)),
                "status": response.status_code,
                "content_type": response.headers.get("content-type", ""),
                "bytes": len(response.content),
                "sha256": hashlib.sha256(response.content).hexdigest(),
                "elapsed_ms": round((time.monotonic() - started) * 1000),
            }
        )
        return response

    def json_object(self, response: httpx.Response, stage: str) -> dict[str, Any]:
        try:
            value = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ToolError(f"{stage} did not return JSON") from error
        if not isinstance(value, dict):
            raise ToolError(f"{stage} JSON must be an object")
        return value


def api_error(platform: str, stage: str, reason: str, **facts: Any) -> QuoteResult:
    return quote_result("api_error", platform, reason=reason, stage=stage, **facts)


def classify_http(platform: str, stage: str, response: httpx.Response) -> QuoteResult:
    system = bot_system(response)
    if system:
        return quote_result("bot_wall", platform, reason="challenge response", system=system, http_status=response.status_code)
    if response.status_code in {401, 403}:
        return quote_result("gated", platform, reason="public storefront operation refused", stage=stage, http_status=response.status_code)
    return api_error(platform, stage, f"unexpected HTTP {response.status_code}", http_status=response.status_code)
