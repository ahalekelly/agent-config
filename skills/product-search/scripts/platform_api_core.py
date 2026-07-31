from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, assert_never
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

Platform = Literal[
    "shopify",
    "woocommerce",
    "magento",
    "bigcommerce",
    "squarespace",
    "wix",
    "ecwid",
    "sfcc",
]
DetectionKind = Literal["detected", "unknown", "bot_wall"]
Operation = Literal["search", "quote"]
Disposition = Literal["delivery", "pickup", "paid_later", "unavailable", "fallback"]
PLATFORMS = {
    "shopify",
    "woocommerce",
    "magento",
    "bigcommerce",
    "squarespace",
    "wix",
    "ecwid",
    "sfcc",
}
TERMINAL_KINDS = {
    "gated",
    "bot_wall",
    "unsupported_operation",
    "unsupported_product_configuration",
}
SECRET_QUERY_NAMES = {
    "access_token",
    "api_key",
    "authenticity_token",
    "key",
    "sf_authenticity_token",
    "token",
}


class ToolError(RuntimeError):
    """A transport, response-schema, or workflow-contract failure."""


@dataclass(frozen=True)
class Detection:
    kind: DetectionKind
    origin: str
    entry_url: str
    platform: Platform | None
    api_origin: str | None
    evidence: tuple[str, ...]
    system: str | None = None
    status: int | None = None

    def __post_init__(self) -> None:
        if (
            self.origin != url_origin(self.origin)
            or url_origin(self.entry_url) != self.origin
        ):
            raise ToolError(
                "Detection origin and entry URL must share one HTTPS authority"
            )
        if not self.evidence or any(
            not isinstance(value, str) or not value for value in self.evidence
        ):
            raise ToolError("Detection requires nonempty evidence strings")
        if self.kind == "detected":
            if (
                self.platform not in PLATFORMS
                or self.api_origin is None
                or self.system is not None
                or self.status is not None
            ):
                raise ToolError(
                    "Detected storefront requires exactly a supported platform and API origin"
                )
            if self.api_origin != url_origin(self.api_origin):
                raise ToolError("Detected API origin must be an HTTPS origin")
            return
        if self.kind == "unknown":
            if any(
                value is not None
                for value in (self.platform, self.api_origin, self.system, self.status)
            ):
                raise ToolError(
                    "Unknown storefront cannot carry platform, API origin, or wall fields"
                )
            return
        if self.kind == "bot_wall":
            if (
                self.platform is not None
                or self.api_origin is not None
                or not self.system
                or not isinstance(self.status, int)
            ):
                raise ToolError(
                    "Bot-wall detection requires only its system and HTTP status"
                )
            return
        assert_never(self.kind)

    def public(self) -> dict[str, Any]:
        if self.kind == "detected":
            return {
                "kind": "detected",
                "origin": self.origin,
                "platform": self.platform,
                "api_origin": self.api_origin,
                "evidence": list(self.evidence),
            }
        if self.kind == "bot_wall":
            return {
                "kind": "bot_wall",
                "origin": self.origin,
                "system": self.system,
                "status": self.status,
                "evidence": list(self.evidence),
            }
        return {
            "kind": "unknown",
            "origin": self.origin,
            "evidence": list(self.evidence),
        }


class Http:
    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self.client = httpx.Client(
            transport=transport,
            timeout=httpx.Timeout(45, connect=10),
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
            },
            follow_redirects=False,
        )
        self.evidence: list[dict[str, Any]] = []

    def close(self) -> None:
        self.client.close()

    def request(
        self, method: str, url: str, *, follow_redirects: bool = False, **kwargs: Any
    ) -> httpx.Response:
        request = self.client.build_request(method, url, **kwargs)
        return self._send(
            request,
            lambda: self.client.send(request, follow_redirects=follow_redirects),
        )

    def send_signed(
        self,
        request: httpx.Request,
        sender: Callable[[httpx.Client, httpx.Request], httpx.Response],
    ) -> httpx.Response:
        return self._send(request, lambda: sender(self.client, request))

    def _send(
        self, request: httpx.Request, send: Callable[[], httpx.Response]
    ) -> httpx.Response:
        started = time.monotonic()
        try:
            response = send()
        except (httpx.HTTPError, ValueError) as error:
            raise ToolError(
                f"{request.method} {redact_url(str(request.url))} failed: {type(error).__name__}"
            ) from error
        self.evidence.append(
            {
                "method": request.method,
                "requested_url": redact_url(str(request.url)),
                "final_url": redact_url(str(response.url)),
                "status": response.status_code,
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "content_type": response.headers.get("content-type", ""),
                "bytes": len(response.content),
                "sha256": hashlib.sha256(response.content).hexdigest(),
            }
        )
        return response


def normalize_store_url(value: str) -> str:
    url = value if "://" in value else f"https://{value}"
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
    ):
        raise ToolError("Store must be an absolute HTTPS URL without credentials")
    if parts.query or parts.fragment:
        raise ToolError("Store URL must not contain a query or fragment")
    host = (
        f"[{parts.hostname.lower()}]"
        if ":" in parts.hostname
        else parts.hostname.encode("idna").decode("ascii").lower()
    )
    try:
        port = "" if parts.port in {None, 443} else f":{parts.port}"
    except ValueError as error:
        raise ToolError("Store URL has an invalid port") from error
    path = parts.path or "/"
    return urlunsplit(("https", host + port, path, "", ""))


def url_origin(value: str) -> str:
    normalized = normalize_store_url(value)
    parts = urlsplit(normalized)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def canonical_url(value: str) -> str:
    url = value if "://" in value else f"https://{value}"
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
    ):
        raise ToolError(
            "Canonical URL requires an absolute HTTPS URL without credentials"
        )
    return normalize_store_url(
        urlunsplit((parts.scheme, parts.netloc, parts.path or "/", "", ""))
    )


def redact_url(value: str) -> str:
    parts = urlsplit(value)
    path = re.sub(r"(/guest-carts/)[^/]+", r"\1[redacted]", parts.path)
    path = re.sub(r"(/commerce/cart/)[^/]+", r"\1[redacted]", path)
    path = re.sub(r"(/checkouts?/)[^/]+", r"\1[redacted]", path)
    path = re.sub(r"(/wc/store/v1/cart/items/)[^/]+", r"\1[redacted]", path)
    query = urlencode(
        [
            (name, "[redacted]" if name.lower() in SECRET_QUERY_NAMES else item)
            for name, item in parse_qsl(parts.query)
        ]
    )
    return urlunsplit((parts.scheme, parts.netloc, path, query, ""))


def item_ref(platform: Platform, value: dict[str, Any]) -> str:
    raw = json.dumps(
        {"platform": platform, **value}, sort_keys=True, separators=(",", ":")
    ).encode()
    return "item-v1." + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def parse_item_ref(reference: str, platform: Platform) -> dict[str, Any]:
    if not reference.startswith("item-v1."):
        raise ToolError(f"{platform} requires an item_ref returned by search")
    encoded = reference.removeprefix("item-v1.")
    try:
        value = json.loads(
            base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        )
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ToolError("Malformed item_ref") from error
    if not isinstance(value, dict) or value.pop("platform", None) != platform:
        raise ToolError(f"item_ref does not belong to {platform}")
    return value


def json_object(response: httpx.Response, context: str) -> dict[str, Any]:
    value = _json(response, context)
    if not isinstance(value, dict):
        raise ToolError(f"{context} JSON must be an object")
    return value


def json_list(response: httpx.Response, context: str) -> list[Any]:
    value = _json(response, context)
    if not isinstance(value, list):
        raise ToolError(f"{context} JSON must be an array")
    return value


def _json(response: httpx.Response, context: str) -> Any:
    try:
        return response.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ToolError(f"{context} did not return JSON") from error


def money(amount: Any, currency: Any) -> dict[str, str]:
    if isinstance(amount, bool) or not isinstance(amount, (str, int, float, Decimal)):
        raise ToolError(f"Money amount has unexpected type {type(amount).__name__}")
    if not isinstance(currency, str) or not currency:
        raise ToolError("Money requires a nonempty currency code")
    return {"amount": format(Decimal(str(amount)), "f"), "currency": currency}


def minor_money(amount: Any, currency: Any, digits: Any) -> dict[str, str]:
    if not isinstance(amount, str) or not re.fullmatch(r"-?\d+", amount):
        raise ToolError("Minor-unit amount must be an integer string")
    if not isinstance(digits, int):
        raise ToolError("Currency minor-unit count must be an integer")
    value = Decimal(amount).scaleb(-digits)
    normalized = money(value, currency)
    normalized["amount"] = f"{value:.{digits}f}"
    return normalized


def shipping_option(
    option_id: Any,
    title: Any,
    disposition: Disposition,
    amount: dict[str, str] | None,
    **facts: Any,
) -> dict[str, Any]:
    if (
        not isinstance(option_id, str)
        or not option_id
        or not isinstance(title, str)
        or not title
    ):
        raise ToolError("Shipping option requires a nonempty ID and title")
    if disposition == "delivery" and amount is None:
        raise ToolError("Comparable delivery option requires an amount")
    return {
        "id": option_id,
        "title": title,
        "disposition": disposition,
        "amount": amount,
        **facts,
    }


def search_result(
    platform: Platform, query: str, items: list[dict[str, Any]], **facts: Any
) -> dict[str, Any]:
    result = {
        "kind": "search",
        "operation": "search",
        "platform": platform,
        "query": query,
        "items": items,
        **facts,
    }
    validate_result(result)
    return result


def quote_outcome(
    platform: Platform,
    options: list[dict[str, Any]],
    subtotal: dict[str, str],
    *,
    no_quote_reason: str = "empty_rate_list",
    **facts: Any,
) -> dict[str, Any]:
    rates = [
        {
            "option_id": option["id"],
            "title": option["title"],
            "amount": option["amount"],
        }
        for option in options
        if option.get("disposition") == "delivery"
    ]
    fallback_ids = [
        option["id"] for option in options if option.get("disposition") == "fallback"
    ]
    kind = "fallback" if fallback_ids else "quote" if rates else "empty"
    result: dict[str, Any] = {
        "kind": kind,
        "operation": "quote",
        "platform": platform,
        "shipping_options": options,
        "rates": rates,
        "subtotal": subtotal,
        "destination": "dummy_sf",
        **facts,
    }
    if fallback_ids:
        result["fallback_rate_ids"] = fallback_ids
    if kind == "empty":
        result["reason"] = no_quote_reason
    validate_result(result)
    return result


def gated(
    operation: Operation,
    platform: Platform,
    endpoint: str,
    response: httpx.Response,
    reason: str,
) -> dict[str, Any]:
    return _terminal(
        "gated",
        operation,
        platform,
        reason,
        endpoint=endpoint,
        status=response.status_code,
        browser_required=True,
    )


def bot_wall(
    operation: Operation, platform: Platform, response: httpx.Response, system: str
) -> dict[str, Any]:
    return _terminal(
        "bot_wall",
        operation,
        platform,
        "challenge response",
        system=system,
        status=response.status_code,
    )


def unsupported_operation(
    operation: Operation, platform: Platform, reason: str, *, browser_required: bool
) -> dict[str, Any]:
    return _terminal(
        "unsupported_operation",
        operation,
        platform,
        reason,
        browser_required=browser_required,
    )


def unsupported_configuration(
    platform: Platform, fields: list[str], reason: str
) -> dict[str, Any]:
    return _terminal(
        "unsupported_product_configuration",
        "quote",
        platform,
        reason,
        fields=fields,
        browser_required=True,
    )


def _terminal(
    kind: str, operation: Operation, platform: Platform, reason: str, **facts: Any
) -> dict[str, Any]:
    result = {
        "kind": kind,
        "operation": operation,
        "platform": platform,
        "reason": reason,
        **facts,
    }
    validate_result(result)
    return result


def validate_result(result: dict[str, Any]) -> None:
    kind, operation = result.get("kind"), result.get("operation")
    if result.get("platform") not in PLATFORMS:
        raise ToolError("Operation result requires a supported platform")
    if kind == "search" and operation == "search":
        items = result.get("items")
        if (
            not isinstance(result.get("query"), str)
            or not result["query"]
            or not isinstance(items, list)
            or any(
                not isinstance(item, dict) or not isinstance(item.get("item_ref"), str)
                for item in items
            )
            or any(
                name in result
                for name in ("rates", "shipping_options", "destination", "subtotal")
            )
        ):
            raise ToolError(
                "Search result requires items and cannot carry quote fields"
            )
        return
    if kind in {"quote", "empty", "fallback"} and operation == "quote":
        options, rates = result.get("shipping_options"), result.get("rates")
        if (
            not isinstance(options, list)
            or not isinstance(rates, list)
            or result.get("destination") != "dummy_sf"
        ):
            raise ToolError(
                f"{kind} result requires shipping options, rates, and dummy-SF destination"
            )
        if not _valid_money(result.get("subtotal")):
            raise ToolError(f"{kind} result requires a currency-bearing subtotal")
        if any(not _valid_shipping_option(option) for option in options):
            raise ToolError(f"{kind} result contains an invalid shipping option")
        expected_rates = [
            {
                "option_id": option["id"],
                "title": option["title"],
                "amount": option["amount"],
            }
            for option in options
            if option["disposition"] == "delivery"
        ]
        if rates != expected_rates:
            raise ToolError(
                f"{kind} result rates must exactly match comparable delivery options"
            )
        if kind == "quote" and not rates:
            raise ToolError(
                "Quote result requires at least one comparable delivery rate"
            )
        if kind == "quote" and "fallback_rate_ids" in result:
            raise ToolError("Quote result cannot carry fallback rate IDs")
        if kind == "empty" and (
            rates
            or not isinstance(result.get("reason"), str)
            or "fallback_rate_ids" in result
        ):
            raise ToolError("Empty result requires a reason and no comparable rates")
        expected_fallback_ids = [
            option["id"] for option in options if option["disposition"] == "fallback"
        ]
        if (
            kind == "fallback"
            and result.get("fallback_rate_ids") != expected_fallback_ids
        ):
            raise ToolError("Fallback result requires fallback rate IDs")
        return
    if kind in TERMINAL_KINDS and operation in {"search", "quote"}:
        if not isinstance(result.get("reason"), str) or not result["reason"]:
            raise ToolError(f"{kind} result requires a reason")
        if any(
            name in result
            for name in (
                "items",
                "rates",
                "shipping_options",
                "destination",
                "subtotal",
            )
        ):
            raise ToolError(f"{kind} result cannot carry success fields")
        if kind == "gated" and (
            result.get("browser_required") is not True
            or not isinstance(result.get("endpoint"), str)
        ):
            raise ToolError("Gated result requires endpoint and browser_required=true")
        if kind == "bot_wall" and (
            not isinstance(result.get("system"), str) or "browser_required" in result
        ):
            raise ToolError(
                "Bot-wall result requires a system and no browser_required field"
            )
        if kind == "unsupported_operation" and not isinstance(
            result.get("browser_required"), bool
        ):
            raise ToolError("Unsupported result requires explicit browser_required")
        if kind == "unsupported_product_configuration" and (
            result.get("browser_required") is not True
            or not isinstance(result.get("fields"), list)
            or not result["fields"]
            or any(
                not isinstance(field, str) or not field for field in result["fields"]
            )
        ):
            raise ToolError(
                "Unsupported product configuration requires fields and browser_required=true"
            )
        return
    raise ToolError(
        f"Unknown or contradictory operation result: kind={kind!r}, operation={operation!r}"
    )


def _valid_money(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != {"amount", "currency"}:
        return False
    try:
        Decimal(value["amount"])
    except (ValueError, TypeError):
        return False
    return isinstance(value["currency"], str) and bool(value["currency"])


def _valid_shipping_option(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if (
        not isinstance(value.get("id"), str)
        or not value["id"]
        or not isinstance(value.get("title"), str)
        or not value["title"]
    ):
        return False
    disposition = value.get("disposition")
    if disposition not in {
        "delivery",
        "pickup",
        "paid_later",
        "unavailable",
        "fallback",
    }:
        return False
    amount = value.get("amount")
    return _valid_money(amount) if amount is not None else disposition != "delivery"


def wall_system(response: httpx.Response) -> str | None:
    body = response.text[:50_000].lower()
    server = response.headers.get("server", "").lower()
    if (
        response.headers.get("cf-mitigated", "").lower() == "challenge"
        or "/cdn-cgi/challenge-platform" in body
    ):
        return "cloudflare"
    if "datadome" in body or "captcha-delivery.com" in body:
        return "datadome"
    if "bunny-shield" in body or "shield-challenge.js" in body:
        return "bunny_shield"
    if response.status_code in {403, 429, 503} and "cloudflare" in server:
        return "cloudflare"
    return None
