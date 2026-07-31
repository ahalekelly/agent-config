#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "cryptography>=45,<47",
#   "httpx>=0.28,<0.29",
# ]
# ///

"""Detect storefronts, find products, and quote one item to the fixed dummy SF address."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from platform_api_core import Detection, Http, ToolError, api_error, bot_system, item_ref, origin, parse_ref, quote_result
from platforms import bigcommerce, extra, magento, shopify, woocommerce
from platforms.commerce_common import AdapterError, RequestPlan


SCHEMA_VERSION = 1


class Workflow:
    def __init__(self, http: Http, bigcommerce_products_http: Http, bigcommerce_quote_http: Http) -> None:
        self.http = http
        self.bigcommerce_products_http = bigcommerce_products_http
        self.bigcommerce_quote_http = bigcommerce_quote_http

    def detect(self, store: str) -> Detection:
        requested = origin(store)
        homepage = self.http.request("GET", requested + "/", follow_redirects=True)
        resolved = origin(str(homepage.url))
        source = homepage.text[:2_000_000]
        lower = source.lower()
        markers: dict[str, list[str]] = {}

        def mark(platform: str, signal: str, present: bool) -> None:
            if present:
                markers.setdefault(platform, []).append(signal)

        mark("shopify", "shopify_html", "cdn.shopify.com" in lower or "shopify.theme" in lower)
        mark("woocommerce", "woocommerce_html", "woocommerce" in lower and "wp-content" in lower)
        mark("magento", "magento_html", any(value in lower for value in ("x-magento-init", "magento_", "mage-cache-", "private_content_version")))
        mark("bigcommerce", "bigcommerce_stencil", bool(re.search(r"cdn\d+\.bigcommerce\.com/s-[a-z0-9]+", source, re.I)) or "/stencil/" in lower or "x-bc-store-id" in homepage.headers)
        mark("squarespace", "squarespace_html", homepage.headers.get("server", "").lower() == "squarespace" or "static1.squarespace.com" in lower)
        mark("wix", "wix_html", homepage.headers.get("server", "").lower() == "pepyaka" or "x-wix-request-id" in homepage.headers or "wixstatic.com" in lower)
        mark("ecwid", "ecwid_script", "app.ecwid.com/script.js?" in lower or "storefront-api.ecwid.com" in lower)
        mark("sfcc", "sfcc_html", "/on/demandware." in lower or "x-dw-request-base-id" in homepage.headers)

        positives: list[tuple[str, str, str]] = []
        woo = self.http.request("GET", resolved + "/wp-json/wc/store/v1/cart")
        try:
            woo_payload = woo.json()
        except json.JSONDecodeError:
            woo_payload = None
        if woo.status_code == 200 and isinstance(woo_payload, dict) and isinstance(woo_payload.get("totals"), dict):
            positives.append(("woocommerce", resolved, "woocommerce_store_cart"))

        guest = self.http.request("POST", resolved + "/rest/V1/guest-carts", json={})
        try:
            guest_payload = guest.json()
        except json.JSONDecodeError:
            guest_payload = None
        if guest.status_code in {200, 201} and isinstance(guest_payload, str) and 16 <= len(guest_payload) <= 128:
            positives.append(("magento", resolved, "magento_guest_cart"))
        elif "magento" in markers and isinstance(guest_payload, dict) and isinstance(guest_payload.get("message"), str):
            markers["magento"].append("magento_error_envelope")

        admin = self.http.request("GET", resolved + "/admin")
        candidates = set(re.findall(r"[a-z0-9][a-z0-9-]*\.myshopify\.com", source + admin.headers.get("location", ""), re.I))
        shopify_origin = "https://" + next(iter(candidates)).lower() if len(candidates) == 1 else resolved
        if "shopify" in markers or candidates:
            response = self._execute_shopify(shopify.detect_request(shopify_origin))
            try:
                payload = response.json()
            except json.JSONDecodeError:
                payload = None
            shop = payload.get("data", {}).get("shop") if isinstance(payload, dict) else None
            if response.status_code == 200 and isinstance(shop, dict) and isinstance(shop.get("name"), str):
                positives.append(("shopify", shopify_origin, "shopify_graphql_shop"))

        platforms = {platform for platform, _, _ in positives}
        if len(platforms) > 1:
            raise ToolError("contradictory successful platform probes: " + ", ".join(sorted(platforms)))
        if positives:
            platform, api_origin, signal = positives[0]
            return Detection("detected", resolved, platform, api_origin, (signal,))
        fallback_markers = {
            platform: signals
            for platform, signals in markers.items()
            if platform != "woocommerce"
        }
        if len(fallback_markers) == 1:
            platform, signals = next(iter(fallback_markers.items()))
            return Detection("detected", resolved, platform, resolved, tuple(signals))
        if len(fallback_markers) > 1:
            evidence = tuple(
                f"ambiguous:{platform}:{signal}"
                for platform, signals in sorted(fallback_markers.items())
                for signal in signals
            )
            return Detection("unknown", resolved, None, None, evidence)
        for response in (homepage, woo, guest):
            if system := bot_system(response):
                return Detection("bot_wall", resolved, None, None, ("challenge_response",), system, response.status_code)
        if "woocommerce" in markers:
            evidence = tuple(f"unverified:woocommerce:{signal}" for signal in markers["woocommerce"])
            return Detection("unknown", resolved, None, None, evidence)
        return Detection("unknown", resolved, None, None, ("no_positive_platform_signal",))

    def products(self, detection: Detection, query: str) -> dict[str, Any]:
        terminal = self._detection_terminal(detection)
        if terminal:
            return terminal
        assert detection.platform
        if detection.platform == "shopify":
            response = self._execute_shopify(shopify.products_request(detection.api_origin or detection.origin, query))
            if response.status_code != 200:
                return self._http_result("shopify", "products", response)
            catalog = shopify.parse_products(response.content)
            items = [{"item_ref": item_ref("shopify", {"variant_id": item.pop("quote_ref")}), **item} for item in catalog["products"]]
            return {"platform": "shopify", "query": query, "items": items}
        if detection.platform == "woocommerce":
            response = self._execute(woocommerce.products_request(detection.origin, query))
            if response.status_code != 200:
                return self._http_result("woocommerce", "products", response)
            catalog = woocommerce.parse_products(response.content)
            items = [{"item_ref": item_ref("woocommerce", {"product_id": int(item.pop("quote_ref"))}), **item} for item in catalog["products"]]
            return {"platform": "woocommerce", "query": query, "items": items, "omitted": catalog["configurable_products_omitted"]}
        if detection.platform == "magento":
            return self._magento_products(detection, query)
        if detection.platform == "bigcommerce":
            catalog = bigcommerce.products(self._bigcommerce_products_request, detection.origin, query, list(detection.evidence))
            if "status" in catalog:
                return catalog
            items = [{"item_ref": item_ref("bigcommerce", product), **product} for product in catalog["products"]]
            return {"platform": "bigcommerce", "query": query, "items": items, "evidence": catalog["evidence"]}
        return extra.products(self.http, detection, query)

    def quote(self, detection: Detection, reference: str) -> dict[str, Any]:
        terminal = self._detection_terminal(detection)
        if terminal:
            return terminal
        assert detection.platform
        if detection.platform == "shopify":
            variant_id = parse_ref("shopify", reference).get("variant_id")
            if not isinstance(variant_id, str):
                return api_error("shopify", "quote", "item_ref has no variant ID")
            created = self._execute_shopify(shopify.cart_create_request(detection.api_origin or detection.origin, variant_id))
            if created.status_code != 200:
                return self._http_result("shopify", "cart_create", created)
            cart = shopify.parse_cart_create(created.content)
            rates = self._execute_shopify(shopify.cart_rates_request(detection.api_origin or detection.origin, cart["cart_id"]))
            if rates.status_code != 200:
                return self._http_result("shopify", "cart_rates", rates)
            return shopify.parse_cart_rates(rates.headers.get("content-type", ""), rates.content, cart["subtotal"])
        if detection.platform == "woocommerce":
            return self._woo_quote(detection, reference)
        if detection.platform == "magento":
            selection = parse_ref("magento", reference)
            return magento.quote(self._request_dict, detection.origin, selection, list(detection.evidence))
        if detection.platform == "bigcommerce":
            selection = parse_ref("bigcommerce", reference)
            return bigcommerce.quote(self._bigcommerce_quote_request, detection.origin, selection, list(detection.evidence))
        return extra.quote(self.http, detection, reference)

    def probe(self, store: str, query: str) -> dict[str, Any]:
        detection = self.detect(store)
        catalog = self.products(detection, query)
        if "status" in catalog:
            return self.record(store, detection, {"catalog": None, "selected_item": None, "result": catalog}, query=query)
        selected = next((item for item in catalog["items"] if item.get("available") is True), None)
        if selected is None:
            result = quote_result("api_error", detection.platform or "unknown", reason="no available exact product", stage="select")
            return self.record(store, detection, {"catalog": catalog, "selected_item": None, "result": result}, query=query)
        result = self.quote(detection, selected["item_ref"])
        return self.record(store, detection, {"catalog": catalog, "selected_item": selected, "result": result}, query=query)

    def record(self, store: str, detection: Detection, output: dict[str, Any], **inputs: Any) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "observed_at": datetime.now(UTC).isoformat(),
            "input": {"store": store, **inputs},
            "detection": detection.public(),
            **output,
            "evidence": (
                self.http.evidence
                + self.bigcommerce_products_http.evidence
                + self.bigcommerce_quote_http.evidence
            ),
        }

    def _magento_products(self, detection: Detection, query: str) -> dict[str, Any]:
        found = magento.search(self._request_dict, detection.origin, query, list(detection.evidence))
        if "status" in found:
            return found
        items: list[dict[str, Any]] = []
        evidence = list(found["evidence"])
        failures = []
        for candidate in found["candidates"]:
            detail = magento.product(self._request_dict, detection.origin, candidate["parent_sku"], list(detection.evidence))
            if "status" in detail:
                failures.append({
                    "type": "candidate_failure",
                    "parent_sku": candidate["parent_sku"],
                    "result": detail,
                })
                continue
            evidence.extend(detail["evidence"])
            for product in detail["products"]:
                items.append({"item_ref": item_ref("magento", product), **product})
        if not items:
            if len(failures) == 1:
                return failures[0]["result"]
            return api_error(
                "magento",
                "products",
                "no search candidate produced a concrete physical product",
                evidence=failures,
            )
        evidence.extend(failures)
        return {"platform": "magento", "query": query, "items": items, "evidence": evidence}

    def _woo_quote(self, detection: Detection, reference: str) -> dict[str, Any]:
        product_id = parse_ref("woocommerce", reference).get("product_id")
        if not isinstance(product_id, int):
            return api_error("woocommerce", "quote", "item_ref has no product ID")
        selected_response = self._execute(woocommerce.product_request(detection.origin, product_id))
        if selected_response.status_code != 200:
            return self._http_result("woocommerce", "selected_product", selected_response)
        selected = woocommerce.selected_product(selected_response.content, product_id)
        cart_response = self._execute(woocommerce.cart_request(detection.origin))
        if cart_response.status_code != 200:
            return self._http_result("woocommerce", "cart", cart_response)
        token = woocommerce.cart_token(dict(cart_response.headers))
        added_response = self._execute(woocommerce.add_item_request(detection.origin, product_id, selected["quantity"], token))
        if added_response.status_code not in {200, 201}:
            return self._http_result("woocommerce", "add_item", added_response)
        item_key = woocommerce.added_item_key(added_response.content, product_id)
        result: dict[str, Any]
        try:
            quoted = self._execute(woocommerce.update_customer_request(detection.origin, token))
            result = woocommerce.parse_cart_rates(quoted.content) if quoted.status_code == 200 else self._http_result("woocommerce", "update_customer", quoted)
        finally:
            cleanup = self._execute(woocommerce.cleanup_request(detection.origin, item_key, token))
        result["cleanup_status"] = cleanup.status_code
        return result

    def _execute(self, plan: RequestPlan) -> httpx.Response:
        return self.http.request(plan.method, plan.url, headers=plan.headers, content=plan.body)

    def _execute_shopify(self, plan: RequestPlan) -> httpx.Response:
        request = self.http.client.build_request(
            plan.method,
            plan.url,
            headers=plan.headers,
            content=plan.body,
        )
        return self.http.send(request, shopify.send)

    def _request_dict(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        response = self.http.request(method, url, **kwargs)
        return self._response_dict(response, response.text[:50_000])

    def _bigcommerce_products_request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        response = self.bigcommerce_products_http.request(method, url, **kwargs)
        return self._response_dict(response, response.text)

    def _bigcommerce_quote_request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        response = self.bigcommerce_quote_http.request(method, url, **kwargs)
        return self._response_dict(response, response.text)

    @staticmethod
    def _response_dict(response: httpx.Response, text: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except json.JSONDecodeError:
            payload = None
        return {
            "status": response.status_code,
            "headers": dict(response.headers),
            "text": text,
            "json": payload,
            "cookies": dict(response.cookies),
        }

    def _http_result(self, platform: str, stage: str, response: httpx.Response) -> dict[str, Any]:
        system = bot_system(response)
        if system:
            return quote_result("bot_wall", platform, reason="challenge response", system=system, http_status=response.status_code)
        if response.status_code in {401, 403}:
            return quote_result("gated", platform, reason="public storefront operation refused", stage=stage, http_status=response.status_code)
        return api_error(platform, stage, f"unexpected HTTP {response.status_code}", http_status=response.status_code)

    def _detection_terminal(self, detection: Detection) -> dict[str, Any] | None:
        match detection.state:
            case "detected":
                return None
            case "bot_wall":
                return quote_result("bot_wall", "unknown", reason="challenge prevented platform operation", system=detection.system, http_status=detection.http_status)
            case "unknown":
                return quote_result("unsupported", "unknown", reason="storefront platform could not be detected")


def new_workflow(transport: httpx.BaseTransport | None = None) -> Workflow:
    return Workflow(Http(transport), Http(transport), Http(transport))


def single(command: str, store: str, value: str | None = None, *, workflow: Workflow | None = None) -> dict[str, Any]:
    flow = workflow or new_workflow()
    try:
        if command in {"products", "probe", "quote"} and (not isinstance(value, str) or not value.strip()):
            raise ToolError(f"{command} requires a nonempty {'item_ref' if command == 'quote' else 'query'}")
        with flow.http.client, flow.bigcommerce_products_http.client, flow.bigcommerce_quote_http.client:
            if command == "probe":
                return flow.probe(store, value or "")
            detection = flow.detect(store)
            if command == "detect":
                return flow.record(store, detection, {})
            if command == "products":
                output = flow.products(detection, value or "")
                return flow.record(store, detection, {"catalog": output} if "status" not in output else {"result": output}, query=value)
            if command == "quote":
                return flow.record(store, detection, {"result": flow.quote(detection, value or "")}, item_ref=value)
            raise AssertionError(command)
    except (ToolError, AdapterError, ValueError, KeyError) as error:
        detected = locals().get("detection")
        platform = detected.platform if isinstance(detected, Detection) and detected.platform else "unknown"
        fallback_detection = detected if isinstance(detected, Detection) else Detection("unknown", store, None, None, ("operation_failed",))
        inputs = (
            {"query": value}
            if command in {"products", "probe"}
            else {"item_ref": value}
            if command == "quote"
            else {}
        )
        return flow.record(
            store,
            fallback_detection,
            {"result": api_error(platform, command, str(error)[:500])},
            **inputs,
        )


def corpus(input_path: Path, output_path: Path) -> int:
    entries = json.loads(input_path.read_text())
    if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
        raise ToolError("corpus must be an array of 1 to 100 entries")
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"store", "query"}
            or not all(isinstance(entry[name], str) and entry[name].strip() for name in ("store", "query"))
        ):
            raise ToolError("every corpus entry must contain exactly nonempty store and query strings")
    completed: set[tuple[str, str]] = set()
    if output_path.exists():
        for line in output_path.read_text().splitlines():
            value = json.loads(line)["input"]
            completed.add((value["store"], value["query"]))
    had_error = False
    with output_path.open("a", encoding="utf-8") as output:
        for entry in entries:
            identity = (entry["store"], entry["query"])
            if identity in completed:
                continue
            result = single("probe", *identity)
            status = result.get("result", {}).get("status")
            had_error |= status == "api_error"
            output.write(json.dumps(result, separators=(",", ":")) + "\n")
            output.flush()
            completed.add(identity)
    return int(had_error)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    commands = command.add_subparsers(dest="command", required=True)
    detect = commands.add_parser("detect")
    detect.add_argument("store")
    products = commands.add_parser("products")
    products.add_argument("store")
    products.add_argument("query")
    quote = commands.add_parser("quote")
    quote.add_argument("store")
    quote.add_argument("item_ref")
    probe = commands.add_parser("probe")
    probe.add_argument("store")
    probe.add_argument("query")
    batch = commands.add_parser("corpus")
    batch.add_argument("input", type=Path)
    batch.add_argument("output", type=Path)
    return command


def main() -> int:
    args = parser().parse_args()
    if args.command == "corpus":
        return corpus(args.input, args.output)
    value = args.query if args.command in {"products", "probe"} else args.item_ref if args.command == "quote" else None
    result = single(args.command, args.store, value)
    print(json.dumps(result, separators=(",", ":")))
    return int(result.get("result", {}).get("status") == "api_error")


if __name__ == "__main__":
    raise SystemExit(main())
