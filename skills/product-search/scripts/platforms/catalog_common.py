from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


QUOTE_STATUSES = {
    "quoted",
    "no_quote",
    "fallback",
    "gated",
    "bot_wall",
    "unsupported",
    "api_error",
}


def money(value: Any, currency: str | None) -> dict[str, str] | None:
    if value is None:
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError(f"invalid money value: {value!r}") from error
    return {"amount": format(amount, "f"), "currency": currency or "unknown"}


def api_error(platform: str, operation: str, reason: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "api_error",
        "platform": platform,
        "operation": operation,
        "reason": reason,
        "evidence": evidence,
    }


def denied(
    platform: str,
    operation: str,
    endpoint: str,
    response: dict[str, Any],
    detection_evidence: list[str],
) -> dict[str, Any]:
    wall = bot_wall_system(response)
    if wall:
        return {
            "status": "bot_wall",
            "platform": platform,
            "operation": operation,
            "system": wall,
            "http_status": response["status"],
            "evidence": [{"type": "challenge_response", "endpoint": endpoint}],
        }
    if detection_evidence:
        return {
            "status": "gated",
            "platform": platform,
            "operation": operation,
            "endpoint": endpoint,
            "http_status": response["status"],
            "evidence": [{"type": "platform_detection", "signals": detection_evidence}],
        }
    return api_error(
        platform,
        operation,
        "access was denied without independent platform evidence",
        [{"type": "http_status", "endpoint": endpoint, "status": response["status"]}],
    )


def bot_wall_system(response: dict[str, Any]) -> str | None:
    headers = {name.lower(): str(value).lower() for name, value in response.get("headers", {}).items()}
    text = response.get("text", "").lower()
    if headers.get("cf-mitigated") == "challenge" or "/cdn-cgi/challenge-platform" in text:
        return "cloudflare"
    if "datadome" in text or "captcha-delivery.com" in text:
        return "datadome"
    if "bunny-shield" in text or "shield-challenge.js" in text:
        return "bunny_shield"
    return None


def option_disposition(option_type: str, description: str, available: bool, error: str | None) -> str:
    label = f"{option_type} {description}".lower()
    if not available or error:
        return "unavailable"
    if "paid later" in label or "quote later" in label:
        return "paid_later"
    if any(marker in label for marker in ("pickup", "pick up", "click and collect", "collect in store", "instore")):
        return "pickup"
    if "fallback" in label:
        return "fallback"
    return "delivery"


def quote_result(
    platform: str,
    shipping_options: list[dict[str, Any]],
    *,
    item: dict[str, Any],
    subtotal: dict[str, str] | None,
) -> dict[str, Any]:
    delivery_rates = [
        {
            "option_id": option["id"],
            "title": option["title"],
            "amount": option.get("discounted_amount") or option["amount"],
        }
        for option in shipping_options
        if option["disposition"] == "delivery"
        and (option.get("discounted_amount") or option["amount"]) is not None
    ]
    fallback_rates = [option for option in shipping_options if option["disposition"] == "fallback"]
    if delivery_rates:
        status = "quoted"
    elif fallback_rates:
        status = "fallback"
    else:
        status = "no_quote"
    result = {
        "status": status,
        "platform": platform,
        "operation": "quote",
        "destination": "dummy_sf",
        "item": item,
        "subtotal": subtotal,
        "shipping_options": shipping_options,
        "delivery_rates": delivery_rates,
    }
    if status == "no_quote":
        result["reason"] = "no_comparable_delivery_rate"
    return result
