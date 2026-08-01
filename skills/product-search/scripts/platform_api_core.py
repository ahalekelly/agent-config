from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
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
NonMagentoPlatform = Literal[
    "shopify",
    "woocommerce",
    "bigcommerce",
    "squarespace",
    "wix",
    "ecwid",
    "sfcc",
]
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


@dataclass(frozen=True, kw_only=True)
class _StorefrontState:
    origin: str
    entry_url: str
    evidence: tuple[str, ...]

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


@dataclass(frozen=True, kw_only=True)
class DetectedStore(_StorefrontState):
    platform: NonMagentoPlatform
    api_origin: str
    kind: Literal["detected"] = field(init=False, default="detected")

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.platform not in PLATFORMS or self.platform == "magento":
            raise ToolError("Generic detected storefront cannot be Magento")
        if self.api_origin != url_origin(self.api_origin):
            raise ToolError("Detected API origin must be an HTTPS origin")


@dataclass(frozen=True, kw_only=True)
class MagentoDetectedStore(_StorefrontState):
    api_origin: str
    search_source: Literal["graphql", "html"]
    kind: Literal["detected"] = field(init=False, default="detected")
    platform: Literal["magento"] = field(init=False, default="magento")

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.api_origin != url_origin(self.api_origin):
            raise ToolError("Detected API origin must be an HTTPS origin")
        if self.search_source not in {"graphql", "html"}:
            raise ToolError("Magento detection requires graphql or html search_source")


@dataclass(frozen=True, kw_only=True)
class UnknownStore(_StorefrontState):
    kind: Literal["unknown"] = field(init=False, default="unknown")


@dataclass(frozen=True, kw_only=True)
class StorefrontBotWall(_StorefrontState):
    system: str
    status: int
    kind: Literal["bot_wall"] = field(init=False, default="bot_wall")

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.system or not isinstance(self.status, int):
            raise ToolError("Bot-wall detection requires its system and HTTP status")


StorefrontDetection = (
    DetectedStore | MagentoDetectedStore | UnknownStore | StorefrontBotWall
)
PositiveDetection = DetectedStore | MagentoDetectedStore


def public_detection(detection: StorefrontDetection) -> dict[str, Any]:
    if isinstance(detection, DetectedStore):
        return {
            "kind": "detected",
            "origin": detection.origin,
            "platform": detection.platform,
            "api_origin": detection.api_origin,
            "evidence": list(detection.evidence),
        }
    if isinstance(detection, MagentoDetectedStore):
        return {
            "kind": "detected",
            "origin": detection.origin,
            "platform": "magento",
            "api_origin": detection.api_origin,
            "search_source": detection.search_source,
            "evidence": list(detection.evidence),
        }
    if isinstance(detection, UnknownStore):
        return {
            "kind": "unknown",
            "origin": detection.origin,
            "evidence": list(detection.evidence),
        }
    if isinstance(detection, StorefrontBotWall):
        return {
            "kind": "bot_wall",
            "origin": detection.origin,
            "system": detection.system,
            "status": detection.status,
            "evidence": list(detection.evidence),
        }
    assert_never(detection)


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
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, ValueError) as error:
        raise ToolError("Money amount must be a valid decimal") from error
    if not value.is_finite():
        raise ToolError("Money amount must be finite")
    return {"amount": format(value, "f"), "currency": currency}


def minor_money(amount: Any, currency: Any, digits: Any) -> dict[str, str]:
    if not isinstance(amount, str) or not re.fullmatch(r"-?\d+", amount):
        raise ToolError("Minor-unit amount must be an integer string")
    if not isinstance(digits, int):
        raise ToolError("Currency minor-unit count must be an integer")
    value = Decimal(amount).scaleb(-digits)
    normalized = money(value, currency)
    normalized["amount"] = f"{value:.{digits}f}"
    return normalized


@dataclass(frozen=True, kw_only=True)
class ShopifySearch:
    platform: Literal["shopify"] = field(init=False, default="shopify")


@dataclass(frozen=True, kw_only=True)
class WooCommerceSearch:
    platform: Literal["woocommerce"] = field(init=False, default="woocommerce")


@dataclass(frozen=True, kw_only=True)
class MagentoSearch:
    source: Literal["graphql", "html"]
    api_errors: tuple[dict[str, Any], ...]
    configurable_products_omitted: int
    platform: Literal["magento"] = field(init=False, default="magento")


@dataclass(frozen=True, kw_only=True)
class BigCommerceSearch:
    platform: Literal["bigcommerce"] = field(init=False, default="bigcommerce")


@dataclass(frozen=True, kw_only=True)
class SquarespaceSearch:
    discovery: Literal["explicit_entry_url", "storefront_search"]
    platform: Literal["squarespace"] = field(init=False, default="squarespace")


@dataclass(frozen=True, kw_only=True)
class WixSearch:
    total: int
    platform: Literal["wix"] = field(init=False, default="wix")


@dataclass(frozen=True, kw_only=True)
class EcwidSearch:
    store_id: str
    total: int
    platform: Literal["ecwid"] = field(init=False, default="ecwid")


@dataclass(frozen=True, kw_only=True)
class SfccSearch:
    endpoint: str
    platform: Literal["sfcc"] = field(init=False, default="sfcc")


SearchContext = (
    ShopifySearch
    | WooCommerceSearch
    | MagentoSearch
    | BigCommerceSearch
    | SquarespaceSearch
    | WixSearch
    | EcwidSearch
    | SfccSearch
)


@dataclass(frozen=True, kw_only=True)
class ShopifyQuote:
    platform: Literal["shopify"] = field(init=False, default="shopify")


@dataclass(frozen=True, kw_only=True)
class WooCommerceQuote:
    cart_totals: dict[str, Any]
    cleanup_status: int
    platform: Literal["woocommerce"] = field(init=False, default="woocommerce")


@dataclass(frozen=True, kw_only=True)
class MagentoQuote:
    item: dict[str, Any]
    base_subtotal: dict[str, str] | None
    subtotal_incl_tax: dict[str, str] | None
    platform: Literal["magento"] = field(init=False, default="magento")


@dataclass(frozen=True, kw_only=True)
class BigCommerceQuote:
    selected_sku: str | None
    platform: Literal["bigcommerce"] = field(init=False, default="bigcommerce")


@dataclass(frozen=True, kw_only=True)
class SquarespaceQuote:
    shipping_options_status: Literal[
        "APPLICABLE_SHIPPING_OPTIONS",
        "SHIPPING_NOT_REQUIRED",
        "POSTAL_CODE_NOT_APPLICABLE",
    ]
    platform: Literal["squarespace"] = field(init=False, default="squarespace")


QuoteContext = (
    ShopifyQuote | WooCommerceQuote | MagentoQuote | BigCommerceQuote | SquarespaceQuote
)


@dataclass(frozen=True, kw_only=True)
class ShopifyShipping:
    code: str | None
    description: str | None
    platform: Literal["shopify"] = field(init=False, default="shopify")


@dataclass(frozen=True, kw_only=True)
class WooCommerceShipping:
    selected: bool
    tax: dict[str, str]
    platform: Literal["woocommerce"] = field(init=False, default="woocommerce")


@dataclass(frozen=True, kw_only=True)
class MagentoShipping:
    carrier_code: str
    method_code: str
    available: bool
    error: str | None
    base_amount: dict[str, str] | None
    price_excl_tax: dict[str, str] | None
    price_incl_tax: dict[str, str] | None
    platform: Literal["magento"] = field(init=False, default="magento")


@dataclass(frozen=True, kw_only=True)
class BigCommerceShipping:
    transit_time: str | None
    platform: Literal["bigcommerce"] = field(init=False, default="bigcommerce")


@dataclass(frozen=True, kw_only=True)
class SquarespaceShipping:
    platform: Literal["squarespace"] = field(init=False, default="squarespace")


ShippingContext = (
    ShopifyShipping
    | WooCommerceShipping
    | MagentoShipping
    | BigCommerceShipping
    | SquarespaceShipping
)


def shipping_option(
    context: ShippingContext,
    option_id: Any,
    title: Any,
    disposition: Disposition,
    amount: dict[str, str] | None,
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
    result = {
        "id": option_id,
        "title": title,
        "disposition": disposition,
        "amount": amount,
        **_shipping_facts(context),
    }
    if not _valid_shipping_option(result, context.platform):
        raise ToolError(f"Invalid {context.platform} shipping option")
    return result


def search_result(
    context: SearchContext, query: str, items: list[dict[str, Any]]
) -> dict[str, Any]:
    result = {
        "kind": "search",
        "operation": "search",
        "platform": context.platform,
        "query": query,
        "items": items,
        **_search_facts(context),
    }
    validate_result(result)
    return result


def quote_outcome(
    context: QuoteContext,
    options: list[dict[str, Any]],
    subtotal: dict[str, str],
    *,
    no_quote_reason: str = "empty_rate_list",
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
    kind = "quote" if rates else "fallback" if fallback_ids else "empty"
    result: dict[str, Any] = {
        "kind": kind,
        "operation": "quote",
        "platform": context.platform,
        "shipping_options": options,
        "rates": rates,
        "subtotal": subtotal,
        "destination": "dummy_sf",
        **_quote_facts(context),
    }
    if kind == "fallback":
        result["fallback_rate_ids"] = fallback_ids
    if kind == "empty":
        result["reason"] = no_quote_reason
    validate_result(result)
    return result


def quote_not_attempted(
    platform: Platform, query: str, candidate_count: int
) -> dict[str, Any]:
    result = {
        "kind": "quote_not_attempted",
        "operation": "quote",
        "platform": platform,
        "reason": "no_quotable_product",
        "query": query,
        "candidate_count": candidate_count,
    }
    validate_result(result)
    return result


def gated(
    operation: Operation,
    platform: Platform,
    endpoint: str,
    response: httpx.Response,
    reason: str,
) -> dict[str, Any]:
    result = {
        "kind": "gated",
        "operation": operation,
        "platform": platform,
        "reason": reason,
        "endpoint": endpoint,
        "status": response.status_code,
        "browser_required": True,
    }
    validate_result(result)
    return result


def bot_wall(
    operation: Operation, platform: Platform, response: httpx.Response, system: str
) -> dict[str, Any]:
    result = {
        "kind": "bot_wall",
        "operation": operation,
        "platform": platform,
        "reason": "challenge response",
        "system": system,
        "status": response.status_code,
    }
    validate_result(result)
    return result


def unsupported_operation(
    operation: Operation, platform: Platform, reason: str, *, browser_required: bool
) -> dict[str, Any]:
    result = {
        "kind": "unsupported_operation",
        "operation": operation,
        "platform": platform,
        "reason": reason,
        "browser_required": browser_required,
    }
    validate_result(result)
    return result


def unsupported_configuration(
    platform: Platform, fields: list[str], reason: str
) -> dict[str, Any]:
    result = {
        "kind": "unsupported_product_configuration",
        "operation": "quote",
        "platform": platform,
        "reason": reason,
        "fields": fields,
        "browser_required": True,
    }
    validate_result(result)
    return result


def _search_facts(context: SearchContext) -> dict[str, Any]:
    if isinstance(context, (ShopifySearch, WooCommerceSearch, BigCommerceSearch)):
        return {}
    if isinstance(context, MagentoSearch):
        if (
            context.source not in {"graphql", "html"}
            or type(context.configurable_products_omitted) is not int
            or context.configurable_products_omitted < 0
            or any(not isinstance(error, dict) for error in context.api_errors)
        ):
            raise ToolError("Magento search context has invalid facts")
        return {
            "source": context.source,
            "api_errors": list(context.api_errors),
            "configurable_products_omitted": context.configurable_products_omitted,
        }
    if isinstance(context, SquarespaceSearch):
        if context.discovery not in {"explicit_entry_url", "storefront_search"}:
            raise ToolError("Squarespace search context has invalid discovery")
        return {"discovery": context.discovery}
    if isinstance(context, WixSearch):
        if type(context.total) is not int or context.total < 0:
            raise ToolError("Wix search context requires a nonnegative total")
        return {"total": context.total}
    if isinstance(context, EcwidSearch):
        if (
            not isinstance(context.store_id, str)
            or not context.store_id
            or type(context.total) is not int
            or context.total < 0
        ):
            raise ToolError("Ecwid search context requires store ID and total")
        return {"store_id": context.store_id, "total": context.total}
    if isinstance(context, SfccSearch):
        if not isinstance(context.endpoint, str) or not context.endpoint:
            raise ToolError("SFCC search context requires an endpoint")
        return {"endpoint": context.endpoint}
    assert_never(context)


def _quote_facts(context: QuoteContext) -> dict[str, Any]:
    if isinstance(context, ShopifyQuote):
        return {}
    if isinstance(context, WooCommerceQuote):
        if not isinstance(context.cart_totals, dict) or not isinstance(
            context.cleanup_status, int
        ):
            raise ToolError("WooCommerce quote context has invalid facts")
        return {
            "cart_totals": context.cart_totals,
            "cleanup_status": context.cleanup_status,
        }
    if isinstance(context, MagentoQuote):
        if (
            not isinstance(context.item, dict)
            or (
                context.base_subtotal is not None
                and not _valid_money(context.base_subtotal)
            )
            or (
                context.subtotal_incl_tax is not None
                and not _valid_money(context.subtotal_incl_tax)
            )
        ):
            raise ToolError("Magento quote context has invalid facts")
        return {
            "item": context.item,
            "base_subtotal": context.base_subtotal,
            "subtotal_incl_tax": context.subtotal_incl_tax,
        }
    if isinstance(context, BigCommerceQuote):
        if context.selected_sku is not None and not isinstance(
            context.selected_sku, str
        ):
            raise ToolError("BigCommerce quote context has invalid selected SKU")
        return {"selected_sku": context.selected_sku}
    if isinstance(context, SquarespaceQuote):
        if context.shipping_options_status not in {
            "APPLICABLE_SHIPPING_OPTIONS",
            "SHIPPING_NOT_REQUIRED",
            "POSTAL_CODE_NOT_APPLICABLE",
        }:
            raise ToolError("Squarespace quote context has invalid shipping status")
        return {"shipping_options_status": context.shipping_options_status}
    assert_never(context)


def _shipping_facts(context: ShippingContext) -> dict[str, Any]:
    if isinstance(context, ShopifyShipping):
        if any(
            value is not None and not isinstance(value, str)
            for value in (context.code, context.description)
        ):
            raise ToolError("Shopify shipping context has invalid facts")
        return {"code": context.code, "description": context.description}
    if isinstance(context, WooCommerceShipping):
        if not isinstance(context.selected, bool) or not _valid_money(context.tax):
            raise ToolError("WooCommerce shipping context has invalid facts")
        return {"selected": context.selected, "tax": context.tax}
    if isinstance(context, MagentoShipping):
        if (
            not isinstance(context.carrier_code, str)
            or not context.carrier_code
            or not isinstance(context.method_code, str)
            or not context.method_code
            or not isinstance(context.available, bool)
            or (context.error is not None and not isinstance(context.error, str))
            or any(
                value is not None and not _valid_money(value)
                for value in (
                    context.base_amount,
                    context.price_excl_tax,
                    context.price_incl_tax,
                )
            )
        ):
            raise ToolError("Magento shipping context has invalid facts")
        return {
            "carrier_code": context.carrier_code,
            "method_code": context.method_code,
            "available": context.available,
            "error": context.error,
            "base_amount": context.base_amount,
            "price_excl_tax": context.price_excl_tax,
            "price_incl_tax": context.price_incl_tax,
        }
    if isinstance(context, BigCommerceShipping):
        if context.transit_time is not None and not isinstance(
            context.transit_time, str
        ):
            raise ToolError("BigCommerce shipping context has invalid transit time")
        return {"transit_time": context.transit_time}
    if isinstance(context, SquarespaceShipping):
        return {}
    assert_never(context)


SEARCH_EXTRA_KEYS = {
    "shopify": set(),
    "woocommerce": set(),
    "magento": {"source", "api_errors", "configurable_products_omitted"},
    "bigcommerce": set(),
    "squarespace": {"discovery"},
    "wix": {"total"},
    "ecwid": {"store_id", "total"},
    "sfcc": {"endpoint"},
}
SEARCH_ITEM_KEYS = {
    "shopify": (
        {
            "name",
            "variant",
            "sku",
            "barcode",
            "available",
            "price",
            "product_url",
            "item_ref",
        },
        {"compare_at_price", "weight", "purchasable", "requires_configuration"},
    ),
    "woocommerce": (
        {
            "name",
            "sku",
            "type",
            "available",
            "purchasable",
            "price",
            "product_url",
            "requires_configuration",
            "item_ref",
        },
        set(),
    ),
    "magento": (
        {
            "item_ref",
            "title",
            "variant",
            "sku",
            "barcode",
            "available",
            "price",
            "compare_at_price",
            "weight",
            "url",
            "options",
        },
        set(),
    ),
    "bigcommerce": (
        {
            "item_ref",
            "title",
            "variant",
            "sku",
            "barcode",
            "available",
            "purchasable",
            "price",
            "compare_at_price",
            "weight",
            "url",
            "requires_configuration",
            "configuration_fields",
        },
        set(),
    ),
    "squarespace": (
        {
            "item_ref",
            "item_id",
            "title",
            "variant",
            "sku",
            "barcode",
            "available",
            "price",
            "compare_at_price",
            "weight",
            "url",
            "requires_configuration",
        },
        set(),
    ),
    "wix": (
        {
            "id",
            "name",
            "sku",
            "available",
            "price",
            "product_url",
            "options",
            "custom_fields",
            "item_ref",
        },
        {"compare_at_price"},
    ),
    "ecwid": (
        {
            "id",
            "name",
            "sku",
            "available",
            "price",
            "product_url",
            "options",
            "item_ref",
        },
        {"compare_at_price"},
    ),
    "sfcc": ({"id", "item_ref"}, {"name", "product_url", "price"}),
}
ITEM_REF_KEYS = {
    "shopify": {"variant_id"},
    "woocommerce": {"product_id", "product_type", "minimum"},
    "magento": {"sku"},
    "bigcommerce": {"product_id", "product_url"},
    "squarespace": {"collection_url", "item_id", "sku"},
    "wix": {"product_id"},
    "ecwid": {"product_id", "store_id"},
    "sfcc": {"pid"},
}
QUOTE_EXTRA_KEYS = {
    "shopify": set(),
    "woocommerce": {"cart_totals", "cleanup_status"},
    "magento": {"item", "base_subtotal", "subtotal_incl_tax"},
    "bigcommerce": {"selected_sku"},
    "squarespace": {"shipping_options_status"},
}
SHIPPING_EXTRA_KEYS = {
    "shopify": {"code", "description"},
    "woocommerce": {"selected", "tax"},
    "magento": {
        "carrier_code",
        "method_code",
        "available",
        "error",
        "base_amount",
        "price_excl_tax",
        "price_incl_tax",
    },
    "bigcommerce": {"transit_time"},
    "squarespace": set(),
}


def validate_result(result: dict[str, Any]) -> None:
    kind, operation = result.get("kind"), result.get("operation")
    platform = result.get("platform")
    if platform not in PLATFORMS:
        raise ToolError("Operation result requires a supported platform")
    if kind == "search" and operation == "search":
        expected_keys = {
            "kind",
            "operation",
            "platform",
            "query",
            "items",
        } | SEARCH_EXTRA_KEYS[platform]
        if set(result) != expected_keys:
            raise ToolError(f"{platform} search result requires exact keys")
        if not _valid_search_facts(result, platform):
            raise ToolError(f"{platform} search result has invalid platform fields")
        items = result.get("items")
        if (
            not isinstance(result.get("query"), str)
            or not result["query"]
            or not isinstance(items, list)
            or any(
                name in result
                for name in ("rates", "shipping_options", "destination", "subtotal")
            )
        ):
            raise ToolError(
                "Search result requires items and cannot carry quote fields"
            )
        for item in items:
            _validate_search_item(item, platform)
        return
    if kind in {"quote", "empty", "fallback"} and operation == "quote":
        if platform not in QUOTE_EXTRA_KEYS:
            raise ToolError(f"{platform} has no public quote-result schema")
        expected_keys = {
            "kind",
            "operation",
            "platform",
            "shipping_options",
            "rates",
            "subtotal",
            "destination",
        } | QUOTE_EXTRA_KEYS[platform]
        if kind == "empty":
            expected_keys.add("reason")
        if kind == "fallback":
            expected_keys.add("fallback_rate_ids")
        if set(result) != expected_keys:
            raise ToolError(f"{platform} {kind} result requires exact keys")
        if not _valid_quote_facts(result, platform):
            raise ToolError(f"{platform} {kind} result has invalid platform fields")
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
        if any(not _valid_shipping_option(option, platform) for option in options):
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
        expected_kind = (
            "quote" if rates else "fallback" if expected_fallback_ids else "empty"
        )
        if kind != expected_kind:
            raise ToolError("Quote, fallback, and empty results must be exclusive")
        if (
            kind == "fallback"
            and result.get("fallback_rate_ids") != expected_fallback_ids
        ):
            raise ToolError("Fallback result requires fallback rate IDs")
        return
    if kind == "quote_not_attempted" and operation == "quote":
        if set(result) != {
            "kind",
            "operation",
            "platform",
            "reason",
            "query",
            "candidate_count",
        }:
            raise ToolError("quote_not_attempted result requires exact keys")
        if (
            result.get("reason") != "no_quotable_product"
            or not isinstance(result.get("query"), str)
            or not result["query"]
            or type(result.get("candidate_count")) is not int
            or result["candidate_count"] < 0
        ):
            raise ToolError("quote_not_attempted result has invalid facts")
        return
    if kind in TERMINAL_KINDS and operation in {"search", "quote"}:
        expected_keys = {
            "gated": {
                "kind",
                "operation",
                "platform",
                "reason",
                "endpoint",
                "status",
                "browser_required",
            },
            "bot_wall": {
                "kind",
                "operation",
                "platform",
                "reason",
                "system",
                "status",
            },
            "unsupported_operation": {
                "kind",
                "operation",
                "platform",
                "reason",
                "browser_required",
            },
            "unsupported_product_configuration": {
                "kind",
                "operation",
                "platform",
                "reason",
                "fields",
                "browser_required",
            },
        }[kind]
        if set(result) != expected_keys:
            raise ToolError(f"{kind} result requires exact keys")
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
    if (
        not isinstance(value, dict)
        or set(value) != {"amount", "currency"}
        or not isinstance(value["amount"], str)
    ):
        return False
    try:
        amount = Decimal(value["amount"])
    except (InvalidOperation, ValueError):
        return False
    return (
        amount.is_finite()
        and isinstance(value["currency"], str)
        and bool(value["currency"])
    )


def _validate_search_item(value: Any, platform: Platform) -> None:
    if not isinstance(value, dict):
        raise ToolError(f"{platform} search item must be an object")
    required, optional = SEARCH_ITEM_KEYS[platform]
    if not required <= set(value) <= required | optional:
        raise ToolError(f"{platform} search item requires exact keys")
    reference = value.get("item_ref")
    if not isinstance(reference, str):
        raise ToolError(f"{platform} search item requires an item_ref")
    payload = parse_item_ref(reference, platform)
    if set(payload) != ITEM_REF_KEYS[platform] or not _valid_item_ref_payload(
        payload, platform
    ):
        raise ToolError(f"{platform} search item has an invalid item_ref payload")
    if not _valid_search_item_values(value, platform):
        raise ToolError(f"{platform} search item has invalid values")


def _valid_search_item_values(value: dict[str, Any], platform: Platform) -> bool:
    for key in ("price", "compare_at_price"):
        if key in value and value[key] is not None and not _valid_money(value[key]):
            return False
    if "weight" in value and value["weight"] is not None:
        weight = value["weight"]
        if (
            not isinstance(weight, dict)
            or set(weight) != {"value", "unit"}
            or isinstance(weight["value"], bool)
            or not isinstance(weight["value"], (str, int, float, Decimal))
            or not isinstance(weight["unit"], str)
            or not weight["unit"]
        ):
            return False
    if platform == "shopify":
        return (
            _text(value["name"])
            and _optional_text(value["variant"])
            and _optional_text(value["sku"])
            and _optional_text(value["barcode"])
            and isinstance(value["available"], bool)
            and _valid_money(value["price"])
            and _text(value["product_url"])
            and ("purchasable" not in value or isinstance(value["purchasable"], bool))
            and (
                "requires_configuration" not in value
                or isinstance(value["requires_configuration"], bool)
            )
        )
    if platform == "woocommerce":
        return (
            _text(value["name"])
            and _optional_text(value["sku"])
            and _text(value["type"])
            and isinstance(value["available"], bool)
            and isinstance(value["purchasable"], bool)
            and _valid_money(value["price"])
            and _text(value["product_url"])
            and isinstance(value["requires_configuration"], bool)
        )
    if platform in {"magento", "bigcommerce", "squarespace"}:
        if not (
            _text(value["title"])
            and _optional_text(value["variant"])
            and _text(value["sku"])
            and _optional_text(value["barcode"])
            and _text(value["url"])
        ):
            return False
        if platform == "magento":
            return (
                value["available"] is None or isinstance(value["available"], bool)
            ) and _valid_options(value["options"])
        return (
            isinstance(value["available"], bool)
            and isinstance(value["requires_configuration"], bool)
            and (
                platform == "squarespace"
                or (
                    isinstance(value["purchasable"], bool)
                    and _text_list(value["configuration_fields"])
                )
            )
        )
    if platform in {"wix", "ecwid"}:
        return (
            (
                (platform == "wix" and _text(value["id"]))
                or (platform == "ecwid" and _positive_int(value["id"]))
            )
            and _text(value["name"])
            and _optional_text(value["sku"])
            and isinstance(value["available"], bool)
            and _valid_money(value["price"])
            and _text(value["product_url"])
            and _text_list(value["options"])
            and (platform == "ecwid" or _text_list(value["custom_fields"]))
        )
    if platform == "sfcc":
        return (
            _text(value["id"])
            and ("name" not in value or _text(value["name"]))
            and ("product_url" not in value or _text(value["product_url"]))
        )
    assert_never(platform)


def _valid_item_ref_payload(value: dict[str, Any], platform: Platform) -> bool:
    if platform == "shopify":
        return _text(value["variant_id"])
    if platform == "woocommerce":
        return (
            _positive_int(value["product_id"])
            and _text(value["product_type"])
            and _positive_int(value["minimum"])
        )
    if platform == "magento":
        return _text(value["sku"])
    if platform == "bigcommerce":
        return _positive_int(value["product_id"]) and _text(value["product_url"])
    if platform == "squarespace":
        return all(_text(value[key]) for key in ITEM_REF_KEYS[platform])
    if platform == "wix":
        return _text(value["product_id"])
    if platform == "ecwid":
        return _positive_int(value["product_id"]) and _text(value["store_id"])
    if platform == "sfcc":
        return _text(value["pid"])
    assert_never(platform)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _optional_text(value: Any) -> bool:
    return value is None or isinstance(value, str)


def _text_list(value: Any) -> bool:
    return isinstance(value, list) and all(_text(item) for item in value)


def _positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


def _valid_options(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(option, dict)
        and set(option) == {"code", "label", "value"}
        and _text(option["code"])
        and _text(option["label"])
        and isinstance(option["value"], (str, int))
        and not isinstance(option["value"], bool)
        for option in value
    )


def _valid_search_facts(value: dict[str, Any], platform: Platform) -> bool:
    if platform in {"shopify", "woocommerce", "bigcommerce"}:
        return True
    if platform == "magento":
        return (
            value["source"] in {"graphql", "html"}
            and isinstance(value["api_errors"], list)
            and all(isinstance(error, dict) for error in value["api_errors"])
            and type(value["configurable_products_omitted"]) is int
            and value["configurable_products_omitted"] >= 0
        )
    if platform == "squarespace":
        return value["discovery"] in {
            "explicit_entry_url",
            "storefront_search",
        }
    if platform == "wix":
        return type(value["total"]) is int and value["total"] >= 0
    if platform == "ecwid":
        return (
            isinstance(value["store_id"], str)
            and bool(value["store_id"])
            and type(value["total"]) is int
            and value["total"] >= 0
        )
    if platform == "sfcc":
        return isinstance(value["endpoint"], str) and bool(value["endpoint"])
    assert_never(platform)


def _valid_quote_facts(value: dict[str, Any], platform: Platform) -> bool:
    if platform == "shopify":
        return True
    if platform == "woocommerce":
        return isinstance(value["cart_totals"], dict) and isinstance(
            value["cleanup_status"], int
        )
    if platform == "magento":
        return (
            isinstance(value["item"], dict)
            and (value["base_subtotal"] is None or _valid_money(value["base_subtotal"]))
            and (
                value["subtotal_incl_tax"] is None
                or _valid_money(value["subtotal_incl_tax"])
            )
        )
    if platform == "bigcommerce":
        return value["selected_sku"] is None or isinstance(value["selected_sku"], str)
    if platform == "squarespace":
        return value["shipping_options_status"] in {
            "APPLICABLE_SHIPPING_OPTIONS",
            "SHIPPING_NOT_REQUIRED",
            "POSTAL_CODE_NOT_APPLICABLE",
        }
    raise AssertionError(f"No quote schema for {platform}")


def _valid_shipping_option(value: Any, platform: Platform) -> bool:
    if not isinstance(value, dict):
        return False
    if platform not in SHIPPING_EXTRA_KEYS:
        return False
    if (
        set(value)
        != {
            "id",
            "title",
            "disposition",
            "amount",
        }
        | SHIPPING_EXTRA_KEYS[platform]
    ):
        return False
    if not _valid_shipping_facts(value, platform):
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


def _valid_shipping_facts(value: dict[str, Any], platform: Platform) -> bool:
    if platform == "shopify":
        return all(
            value[name] is None or isinstance(value[name], str)
            for name in ("code", "description")
        )
    if platform == "woocommerce":
        return isinstance(value["selected"], bool) and _valid_money(value["tax"])
    if platform == "magento":
        return (
            isinstance(value["carrier_code"], str)
            and bool(value["carrier_code"])
            and isinstance(value["method_code"], str)
            and bool(value["method_code"])
            and isinstance(value["available"], bool)
            and (value["error"] is None or isinstance(value["error"], str))
            and all(
                value[name] is None or _valid_money(value[name])
                for name in ("base_amount", "price_excl_tax", "price_incl_tax")
            )
        )
    if platform == "bigcommerce":
        return value["transit_time"] is None or isinstance(value["transit_time"], str)
    if platform == "squarespace":
        return True
    raise AssertionError(f"No shipping schema for {platform}")


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
