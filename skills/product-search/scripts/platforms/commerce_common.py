from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal


Status = Literal[
    "quoted",
    "no_quote",
    "fallback",
    "gated",
    "bot_wall",
    "unsupported",
    "api_error",
]
Disposition = Literal["delivery", "pickup", "paid_later", "unavailable", "fallback"]


class AdapterError(RuntimeError):
    """The storefront response violated the adapter contract."""


@dataclass(frozen=True)
class RequestPlan:
    method: str
    url: str
    headers: dict[str, str]
    body: bytes | None


def decimal_money(amount: Any, currency: Any) -> dict[str, str]:
    if not isinstance(amount, str) or not isinstance(currency, str):
        raise AdapterError("Money requires string amount and currency")
    try:
        Decimal(amount)
    except Exception as error:
        raise AdapterError(f"Invalid decimal money amount {amount!r}") from error
    return {"amount": amount, "currency": currency}


def minor_money(amount: Any, currency: Any, minor_unit: Any) -> dict[str, str]:
    if not isinstance(amount, str) or not re.fullmatch(r"\d+", amount):
        raise AdapterError("Minor-unit money requires a non-negative integer string")
    if not isinstance(currency, str) or not isinstance(minor_unit, int) or minor_unit < 0:
        raise AdapterError("Minor-unit money requires currency and non-negative minor unit")
    value = Decimal(amount).scaleb(-minor_unit)
    return {"amount": f"{value:.{minor_unit}f}", "currency": currency}


def quote_result(
    platform: str,
    shipping_options: list[dict[str, Any]],
    subtotal: dict[str, str] | None,
    *,
    no_quote_reason: str,
) -> dict[str, Any]:
    fallback = any(option["disposition"] == "fallback" for option in shipping_options)
    delivery_rates = [
        {"option_id": option["id"], "title": option["title"], "amount": option["amount"]}
        for option in shipping_options
        if option["disposition"] == "delivery" and option["amount"] is not None
    ]
    status: Status = "quoted" if delivery_rates else "fallback" if fallback else "no_quote"
    result: dict[str, Any] = {
        "status": status,
        "platform": platform,
        "destination": "dummy_sf",
        "shipping_options": shipping_options,
        "delivery_rates": delivery_rates,
        "subtotal": subtotal,
    }
    if status == "no_quote":
        result["reason"] = no_quote_reason
    return result


def terminal_failure(status: Status, platform: str, reason: str) -> dict[str, Any]:
    if status not in {"gated", "bot_wall", "unsupported", "api_error"}:
        raise AdapterError(f"{status} is not a failure status")
    return {"status": status, "platform": platform, "reason": reason}
