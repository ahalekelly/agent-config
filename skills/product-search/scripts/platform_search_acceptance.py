# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "cryptography>=45,<47",
#   "httpx>=0.28,<0.29",
# ]
# ///

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

SCHEMA_VERSION = 1
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REPORT_DIR = SKILL_DIR / "dev" / "reports"
DEFAULT_INPUT = REPORT_DIR / "Product Search Storefront Corpus 2026-07-31.input.json"
DEFAULT_JSONL = REPORT_DIR / "Product Search Storefront Corpus 2026-07-31.jsonl"
DEFAULT_VENDORS = SKILL_DIR / "vendors.md"
EXPECTED_PLATFORMS = {
    "Shopify": "shopify",
    "WooCommerce": "woocommerce",
    "Magento": "magento",
    "BigCommerce": "bigcommerce",
    "Squarespace": "squarespace",
    "Wix": "wix",
    "Ecwid": "ecwid",
    "Salesforce Commerce Cloud": "sfcc",
}
EXPECTED_COUNTS = {
    "Shopify": 12,
    "WooCommerce": 12,
    "Magento": 12,
    "BigCommerce": 11,
    "Squarespace": 3,
    "Wix": 3,
    "Ecwid": 3,
    "Salesforce Commerce Cloud": 3,
}
LABELS = {
    "dernord.com": "DERNORD",
    "mettleair.com": "Mettle Air",
    "garagecabinetsonline.com": "Garage Cabinets Online",
    "aircompressorservices.com": "Air Compressor Services",
    "hydraulic-components.net": "VHS Hydraulics",
    "parkerhydraulics-shop.co.uk": "Parker Hydraulics & Pneumatics",
    "carex.com": "Carex",
    "saslocksmiths.com": "SAS Locksmiths",
    "sikahealth.com": "Sika Marketplace",
    "manorsgolf.com": "Manors Golf",
    "nour-hammour.com": "Nour Hammour",
    "attitudeliving.com": "ATTITUDE Living",
    "actisense.com": "Actisense",
    "gps.co.uk": "GPS Pilot Supplies",
    "puresealservices.co.uk": "Pureseal Services",
    "f-o-a.com": "F-O-A Shocks",
    "resin-pro.co.uk": "Resin Pro UK",
    "rope-source.co.uk": "Rope Source",
    "protosupplies.com": "ProtoSupplies",
    "makerstore.cc": "Maker Store USA",
    "rotarysolutions.com": "Rotary Solutions",
    "tech7000.com": "Tech7000",
    "store.nrgwave.com": "NRG Wave",
    "myolyn.com": "MYOLYN",
    "sparkfun.com": "SparkFun",
    "decksdirect.com": "DecksDirect",
    "barrdisplay.com": "Barr Display",
    "scoutshop.org": "Scout Shop",
    "blanks.ca": "Blanks.ca",
    "signet.net.au": "Signet Australia",
    "atxfitness.com": "ATX Fitness USA",
    "thecpapshop.com": "The CPAP Shop",
    "dillonprecision.com": "Dillon Precision",
    "tilebar.com": "TileBar",
    "bulkreefsupply.com": "Bulk Reef Supply",
    "aheadworks.com": "Aheadworks",
    "servocity.com": "ServoCity",
    "hi-line.com": "Hi-Line",
    "hydraulichosetogo.com": "Hydraulic Hose To Go",
    "gobilda.com": "goBILDA",
    "intlairtool.com": "International Air Tool",
    "spwindustrial.com": "SPW Industrial",
    "fabricwarehouse.com": "Fabric Warehouse",
    "buckleguy.com": "Buckleguy",
    "debrovys.com": "DeBrovys",
    "tackledirect.com": "TackleDirect",
    "valinonline.com": "Valin",
    "franklygoodcoffee.com": "Frankly Good Coffee",
    "archive07.com": "Archive07",
    "marieburgoscollection.com": "Marie Burgos Collection",
    "izzywheels.com": "Izzy Wheels",
    "bestiehugs.com": "Bestie Hugs",
    "holzbuchstaben.ch": "Holzbuchstaben",
    "northboundcoffee.com": "Northbound Coffee",
    "cakesafe.com": "CakeSafe",
    "wyliebeckert.com": "Wylie Beckert",
    "us.dunlopsports.com": "Dunlop Sports US",
    "alcott.eu": "Alcott",
    "hugoboss.com": "HUGO BOSS",
}
SOURCES = {
    "shopify": "storefront_graphql",
    "woocommerce": "wc_store_api",
    "magento": "magento_search",
    "bigcommerce": "html_search_and_product_pages",
    "squarespace": "commerce_collection_json",
    "wix": "catalog_reader",
    "ecwid": "storefront_api_v3",
    "sfcc": "search_show",
}
TOP_KEYS = {
    "schema_version",
    "observed_at",
    "label",
    "entry_url",
    "domain",
    "shipping_cache_domain",
    "expected_group",
    "expected_platform",
    "resolved_origin",
    "query",
    "source_tree_sha256",
    "detection",
    "search",
    "http_evidence",
}
PRODUCT_KEYS = {
    "name",
    "variant",
    "sku",
    "barcode",
    "available",
    "purchasable",
    "requires_configuration",
    "price",
    "compare_at_price",
    "weight",
    "product_url",
}
HTTP_KEYS = {
    "method",
    "requested_url",
    "final_url",
    "status",
    "content_type",
    "bytes",
    "sha256",
    "elapsed_ms",
}
SEARCH_COMMON_KEYS = {
    "kind",
    "platform",
    "source",
    "candidate_count",
    "selected_index",
    "selected_product",
    "item_ref_sha256",
}
EXPECTED_TERMINALS = {
    "tech7000.com": ("not_run", "detection_not_positive"),
    "valinonline.com": ("bot_wall", "challenge response"),
    "wyliebeckert.com": ("not_run", "detection_not_positive"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run or validate the fixed 59-store storefront acceptance corpus."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="perform the bounded live HTTP rerun")
    run.add_argument("jsonl", type=Path)
    run.add_argument("report", type=Path)
    validate = commands.add_parser(
        "validate", help="validate a saved JSONL artifact without network access"
    )
    validate.add_argument("jsonl", type=Path, nargs="?", default=DEFAULT_JSONL)
    return parser.parse_args()


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        value = json.loads(line)
        if not isinstance(value, dict):
            raise SystemExit(f"JSONL line {line_number} must be an object")
        rows.append(value)
    return rows


def load_jobs(path: Path) -> list[dict[str, str]]:
    value = json.loads(path.read_text())
    if not isinstance(value, list) or len(value) != 59:
        raise SystemExit("input must contain exactly 59 jobs")
    jobs: list[dict[str, str]] = []
    for job in value:
        if not isinstance(job, dict) or set(job) != {
            "store",
            "expected_group",
            "query",
        }:
            raise SystemExit("every job must contain store, expected_group, and query")
        if job["expected_group"] not in EXPECTED_PLATFORMS:
            raise SystemExit(f"unknown expected group: {job['expected_group']}")
        if not all(isinstance(job[key], str) and job[key] for key in job):
            raise SystemExit("job fields must be nonempty strings")
        jobs.append(job)

    domains = [urlsplit(job["store"]).hostname for job in jobs]
    if None in domains or len(domains) != len(set(domains)):
        raise SystemExit("input domains must be present and unique")
    counts = Counter(job["expected_group"] for job in jobs)
    if dict(counts) != EXPECTED_COUNTS:
        raise SystemExit(f"unexpected group counts: {dict(counts)}")
    if set(domains) != set(LABELS):
        raise SystemExit("labels must exactly cover the input domains")
    return jobs


def learned_cache_domains(path: Path) -> set[str]:
    text = path.read_text()
    section = text.split("## Learned storefront cache", 1)
    if len(section) != 2:
        raise SystemExit("vendors.md has no learned storefront cache")
    return set(re.findall(r"^\| `([^`]+)` \|", section[1], re.MULTILINE))


def source_tree_hash(source: Path) -> str:
    files = [source / "platform_api.py", source / "platform_api_core.py"]
    files.extend(sorted((source / "platforms").glob("*.py")))
    files.append(source / "web_bot_auth.py")
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(source).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def safe_error(error: Exception) -> str:
    if error.__class__.__name__ == "ToolError":
        message = str(error)
    else:
        message = error.__class__.__name__
    message = re.sub(r"item-v1\.[A-Za-z0-9_-]+", "[redacted-item-ref]", message)
    message = re.sub(
        r"(?i)(access_token|api_key|authenticity_token|key|token)=([^&\s]+)",
        r"\1=[redacted]",
        message,
    )
    message = re.sub(r"(/guest-carts/)[^/\s]+", r"\1[redacted]", message)
    message = re.sub(r"(/commerce/cart/)[^/\s]+", r"\1[redacted]", message)
    message = re.sub(r"(/checkouts?/)[^/\s]+", r"\1[redacted]", message)
    return " ".join(message.split())[:500]


def source_name(platform: str | None, result: dict[str, Any] | None) -> str | None:
    if platform is None:
        return None
    if platform == "magento" and isinstance(result, dict):
        detail = result.get("source")
        if isinstance(detail, str):
            return f"magento_{detail}"
    if platform == "squarespace" and isinstance(result, dict):
        detail = result.get("discovery")
        if isinstance(detail, str):
            return f"squarespace_{detail}"
    return SOURCES[platform]


def safe_product(item: dict[str, Any], redact_url: Any) -> dict[str, Any]:
    product: dict[str, Any] = {}
    name = item.get("name")
    if not isinstance(name, str):
        title = item.get("title")
        name = title if isinstance(title, str) else None
    product["name"] = name
    for key in ("variant", "sku", "barcode"):
        value = item.get(key)
        if isinstance(value, str) or value is None:
            product[key] = value
    for key in ("available", "purchasable", "requires_configuration"):
        value = item.get(key)
        if isinstance(value, bool):
            product[key] = value
    for key in ("price", "compare_at_price", "weight"):
        value = item.get(key)
        if isinstance(value, dict):
            product[key] = value
    product_url = item.get("product_url")
    if not isinstance(product_url, str):
        url = item.get("url")
        product_url = url if isinstance(url, str) else None
    if isinstance(product_url, str):
        product["product_url"] = redact_url(product_url)
    return product


def safe_http_evidence(
    values: list[dict[str, Any]], redact_url: Any
) -> list[dict[str, Any]]:
    evidence = []
    for value in values:
        evidence.append(
            {
                "method": value["method"],
                "requested_url": redact_url(value["requested_url"]),
                "final_url": redact_url(value["final_url"]),
                "status": value["status"],
                "content_type": value["content_type"],
                "bytes": value["bytes"],
                "sha256": value["sha256"],
                "elapsed_ms": value["elapsed_ms"],
            }
        )
    return evidence


def select_candidate(
    platform_api: Any, items: list[dict[str, Any]], redact_url: Any
) -> tuple[int | None, dict[str, Any] | None, str | None]:
    for index, item in enumerate(items):
        reference = platform_api._candidate(item)
        if reference is not None:
            return (
                index,
                safe_product(item, redact_url),
                hashlib.sha256(reference.encode()).hexdigest(),
            )
    return None, None, None


def terminal_outcome(
    result: dict[str, Any], platform: str, source: str | None, redact_url: Any
) -> dict[str, Any]:
    outcome: dict[str, Any] = {
        "kind": result["kind"],
        "operation": result.get("operation", "search"),
        "platform": platform,
        "source": source,
        "candidate_count": None,
        "selected_index": None,
        "selected_product": None,
        "item_ref_sha256": None,
    }
    for key in ("reason", "system", "status", "browser_required", "fields"):
        if key in result:
            outcome[key] = result[key]
    endpoint = result.get("endpoint")
    if isinstance(endpoint, str):
        outcome["endpoint"] = redact_url(endpoint)
    return outcome


def run_job(
    platform_api: Any,
    Http: Any,
    redact_url: Any,
    job: dict[str, str],
    tree_hash: str,
) -> dict[str, Any]:
    entry_url = job["store"]
    domain = urlsplit(entry_url).hostname
    if domain is None:
        raise AssertionError("validated job has no domain")
    expected_platform = EXPECTED_PLATFORMS[job["expected_group"]]
    http = Http()
    observed_at = datetime.now(UTC).isoformat(timespec="seconds")
    detection_public: dict[str, Any] | None = None
    resolved_origin: str | None = None
    outcome: dict[str, Any]
    try:
        try:
            detection = platform_api.detect_store(http, entry_url)
        except Exception as error:
            outcome = {
                "kind": "tool_error",
                "stage": "detection",
                "platform": None,
                "source": None,
                "candidate_count": None,
                "selected_index": None,
                "selected_product": None,
                "item_ref_sha256": None,
                "message": safe_error(error),
            }
        else:
            detection_public = detection.public()
            resolved_origin = detection.origin
            if detection.kind != "detected":
                outcome = {
                    "kind": "not_run",
                    "stage": "search",
                    "platform": None,
                    "source": None,
                    "candidate_count": None,
                    "selected_index": None,
                    "selected_product": None,
                    "item_ref_sha256": None,
                    "reason": "detection_not_positive",
                }
            else:
                if detection.platform is None:
                    raise AssertionError("detected store has no platform")
                source = source_name(detection.platform, None)
                try:
                    result = platform_api.ADAPTERS[detection.platform].search(
                        http, detection, job["query"]
                    )
                except Exception as error:
                    outcome = {
                        "kind": "tool_error",
                        "stage": "search",
                        "platform": detection.platform,
                        "source": source,
                        "candidate_count": None,
                        "selected_index": None,
                        "selected_product": None,
                        "item_ref_sha256": None,
                        "message": safe_error(error),
                    }
                else:
                    source = source_name(detection.platform, result)
                    if result["kind"] == "search":
                        items = result["items"]
                        selected_index, selected_product, reference_hash = (
                            select_candidate(platform_api, items, redact_url)
                        )
                        outcome = {
                            "kind": "search",
                            "operation": "search",
                            "platform": detection.platform,
                            "source": source,
                            "candidate_count": len(items),
                            "selected_index": selected_index,
                            "selected_product": selected_product,
                            "item_ref_sha256": reference_hash,
                        }
                    else:
                        outcome = terminal_outcome(
                            result, detection.platform, source, redact_url
                        )
    finally:
        evidence = safe_http_evidence(http.evidence, redact_url)
        http.close()
    return {
        "schema_version": SCHEMA_VERSION,
        "observed_at": observed_at,
        "label": LABELS[domain],
        "entry_url": entry_url,
        "domain": domain,
        "shipping_cache_domain": domain,
        "expected_group": job["expected_group"],
        "expected_platform": expected_platform,
        "resolved_origin": resolved_origin,
        "query": job["query"],
        "source_tree_sha256": tree_hash,
        "detection": detection_public,
        "search": outcome,
        "http_evidence": evidence,
    }


def validate_rows(
    rows: list[dict[str, Any]],
    jobs: list[dict[str, str]],
    cache_domains: set[str],
) -> None:
    if len(rows) != 59:
        raise SystemExit("output must contain exactly 59 rows")
    domains = [row["domain"] for row in rows]
    expected_domains = [urlsplit(job["store"]).hostname for job in jobs]
    if domains != expected_domains:
        raise SystemExit("output domains must match input order exactly")
    if Counter(row["expected_group"] for row in rows) != Counter(EXPECTED_COUNTS):
        raise SystemExit("output group counts do not match the acceptance corpus")
    if any(row["shipping_cache_domain"] not in cache_domains for row in rows):
        raise SystemExit("one or more output rows have no learned-cache join")
    tree_hashes = {row["source_tree_sha256"] for row in rows}
    if (
        len(tree_hashes) != 1
        or re.fullmatch(r"[0-9a-f]{64}", tree_hashes.pop()) is None
    ):
        raise SystemExit("output must contain one valid source-tree SHA-256")

    for row, job in zip(rows, jobs, strict=True):
        if set(row) != TOP_KEYS:
            raise SystemExit(f"row has unsafe or missing keys: {row['domain']}")
        domain = urlsplit(job["store"]).hostname
        if row["schema_version"] != SCHEMA_VERSION:
            raise SystemExit(f"unexpected schema version: {row['domain']}")
        if datetime.fromisoformat(row["observed_at"]).utcoffset() is None:
            raise SystemExit(f"observation has no timezone: {row['domain']}")
        expected_identity = {
            "entry_url": job["store"],
            "domain": domain,
            "shipping_cache_domain": domain,
            "expected_group": job["expected_group"],
            "expected_platform": EXPECTED_PLATFORMS[job["expected_group"]],
            "query": job["query"],
            "label": LABELS[domain],
        }
        for key, expected in expected_identity.items():
            if row[key] != expected:
                raise SystemExit(f"{key} differs from input: {row['domain']}")
        if row["shipping_cache_domain"] != row["domain"]:
            raise SystemExit(f"cache join differs from entry domain: {row['domain']}")
        detection = row["detection"]
        if detection is not None:
            allowed = {
                "detected": {"kind", "origin", "platform", "api_origin", "evidence"},
                "unknown": {"kind", "origin", "evidence"},
                "bot_wall": {"kind", "origin", "system", "status", "evidence"},
            }[detection["kind"]]
            if set(detection) != allowed:
                raise SystemExit(f"detection has unsafe keys: {row['domain']}")
        product = row["search"]["selected_product"]
        search = row["search"]
        allowed_search_keys = {
            "search": SEARCH_COMMON_KEYS | {"operation"},
            "tool_error": SEARCH_COMMON_KEYS | {"stage", "message"},
            "not_run": SEARCH_COMMON_KEYS | {"stage", "reason"},
            "gated": SEARCH_COMMON_KEYS
            | {
                "operation",
                "reason",
                "status",
                "browser_required",
                "endpoint",
            },
            "bot_wall": SEARCH_COMMON_KEYS
            | {"operation", "reason", "system", "status"},
            "unsupported_operation": SEARCH_COMMON_KEYS
            | {"operation", "reason", "browser_required"},
            "unsupported_product_configuration": SEARCH_COMMON_KEYS
            | {"operation", "reason", "browser_required", "fields"},
        }.get(search["kind"])
        if allowed_search_keys is None or set(search) != allowed_search_keys:
            raise SystemExit(f"search outcome has unsafe keys: {row['domain']}")
        if product is not None and not set(product) <= PRODUCT_KEYS:
            raise SystemExit(f"selected product has unsafe keys: {row['domain']}")
        reference_hash = search["item_ref_sha256"]
        if (
            reference_hash is not None
            and re.fullmatch(r"[0-9a-f]{64}", reference_hash) is None
        ):
            raise SystemExit(f"item reference is not a SHA-256: {row['domain']}")
        if product is not None:
            for money_key in ("price", "compare_at_price"):
                if money_key in product and set(product[money_key]) != {
                    "amount",
                    "currency",
                }:
                    raise SystemExit(
                        f"selected product has unsafe money fields: {row['domain']}"
                    )
            if "weight" in product and set(product["weight"]) != {"value", "unit"}:
                raise SystemExit(
                    f"selected product has unsafe weight fields: {row['domain']}"
                )
        for request in row["http_evidence"]:
            if set(request) != HTTP_KEYS:
                raise SystemExit(f"HTTP evidence has unsafe keys: {row['domain']}")
            if re.fullmatch(r"[0-9a-f]{64}", request["sha256"]) is None:
                raise SystemExit(f"HTTP evidence hash is invalid: {row['domain']}")

    positive = sum(
        row["search"]["kind"] == "search" and row["search"]["candidate_count"] > 0
        for row in rows
    )
    empty = sum(
        row["search"]["kind"] == "search" and row["search"]["candidate_count"] == 0
        for row in rows
    )
    errors = sum(row["search"]["kind"] == "tool_error" for row in rows)
    if (positive, empty, errors) != (47, 9, 0):
        raise SystemExit("unexpected positive, empty, or error disposition counts")
    terminals = {
        row["domain"]: (row["search"]["kind"], row["search"]["reason"])
        for row in rows
        if row["search"]["kind"] not in {"search", "tool_error"}
    }
    if terminals != EXPECTED_TERMINALS:
        raise SystemExit("terminal dispositions differ from the accepted run")

    serialized = "\n".join(json.dumps(row, sort_keys=True) for row in rows)
    forbidden_patterns = {
        "raw item reference": r"item-v1\.",
        "cookie header": r"(?i)set-cookie|cart-token|shop_session_token|sf-csrf-token",
        "authorization header": r"(?i)\bauthorization\b",
        "private key": r"(?i)private\.pem|begin private key",
        "unredacted secret query value": r"(?i)(?:token|key|signature|cookie)=(?!%5Bredacted%5D|\[redacted\])[^&\s?\"']+",
        "unredacted Magento cart path": r"/guest-carts/(?!\[redacted\])[^/\s?\"']+",
        "unredacted Squarespace cart path": r"/commerce/cart/(?!\[redacted\])[^/\s?\"']+",
        "unredacted checkout path": r"/checkouts?/(?!\[redacted\])[^/\s?\"']+",
    }
    for label, pattern in forbidden_patterns.items():
        if re.search(pattern, serialized):
            raise SystemExit(f"output contains forbidden {label}")


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, Any] = {}
    mismatches: list[dict[str, Any]] = []
    for row in rows:
        detection = row["detection"]
        observed_platform = detection.get("platform") if detection else None
        if observed_platform != row["expected_platform"]:
            mismatches.append(
                {
                    "domain": row["domain"],
                    "expected": row["expected_platform"],
                    "detection_kind": detection.get("kind") if detection else None,
                    "observed_platform": observed_platform,
                    "search_kind": row["search"]["kind"],
                }
            )
    for group in EXPECTED_COUNTS:
        selected = [row for row in rows if row["expected_group"] == group]
        outcomes = Counter(row["search"]["kind"] for row in selected)
        groups[group] = {
            "total": len(selected),
            "successes": sum(
                row["search"]["kind"] == "search"
                and row["search"]["candidate_count"] > 0
                for row in selected
            ),
            "empty": sum(
                row["search"]["kind"] == "search"
                and row["search"]["candidate_count"] == 0
                for row in selected
            ),
            "errors": outcomes["tool_error"],
            "terminal_or_not_run": sum(
                count
                for kind, count in outcomes.items()
                if kind not in {"search", "tool_error"}
            ),
            "detection_mismatches": sum(
                mismatch["domain"] in {row["domain"] for row in selected}
                for mismatch in mismatches
            ),
            "outcomes": dict(sorted(outcomes.items())),
        }
    return {
        "row_count": len(rows),
        "unique_domain_count": len({row["domain"] for row in rows}),
        "groups": groups,
        "mismatches": mismatches,
    }


def report(rows: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    observations = [datetime.fromisoformat(row["observed_at"]) for row in rows]
    local_date = min(observations).astimezone(ZoneInfo("America/Los_Angeles")).date()
    tree_hash = rows[0]["source_tree_sha256"]
    lines = [
        f"# Product-search storefront HTTP evidence — {local_date}",
        "",
        "This read-only acceptance rerun used one literal query (`a`) per store with no alternate-query retries. It called the production detection and platform search adapters over plain HTTP. The production detector's empty `POST /rest/V1/guest-carts` request is an authorized Magento-positive probe; the run created no product line, customer address, consignment, or shipping-rate request.",
        "",
        "Opaque product references were hashed in memory and discarded. The JSONL contains only public detection evidence, whitelisted product fields, sanitized HTTP request metadata, and learned-cache domain joins.",
        "",
        f"Every row carries source-tree SHA-256 `{tree_hash}`, computed from `platform_api.py`, `platform_api_core.py`, `platforms/*.py`, and `web_bot_auth.py`. The observation window was {min(observations).astimezone(UTC).strftime('%Y-%m-%d %H:%M:%S')}–{max(observations).astimezone(UTC).strftime('%H:%M:%S')} UTC ({local_date} local time).",
        "",
        "## Summary",
        "",
        "| Expected group | Total | Positive candidates | Empty | Tool errors | Terminal/not run | Detection mismatches |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for group, values in summary["groups"].items():
        lines.append(
            f"| {group} | {values['total']} | {values['successes']} | {values['empty']} | {values['errors']} | {values['terminal_or_not_run']} | {values['detection_mismatches']} |"
        )
    lines.extend(
        [
            "",
            "## Per-store outcomes",
            "",
            "| Store | Expected | Detection | Search outcome | Candidates | Selected product | SKU |",
            "| --- | --- | --- | --- | ---: | --- | --- |",
        ]
    )
    for row in rows:
        detection = row["detection"]
        detected = (
            detection.get("platform") or detection.get("kind") if detection else "error"
        )
        search = row["search"]
        product = search["selected_product"] or {}
        source = search.get("source") or "—"
        candidates = search["candidate_count"]
        values = [
            f"{row['label']} (`{row['domain']}`)",
            row["expected_group"],
            detected,
            f"{search['kind']} / {source}",
            "—" if candidates is None else candidates,
            product.get("name") or "—",
            product.get("sku") or "—",
        ]
        escaped = [
            str(value).replace("|", "\\|").replace("\n", " ") for value in values
        ]
        lines.append("| " + " | ".join(escaped) + " |")
    if summary["mismatches"]:
        lines.extend(["", "## Detection mismatches", ""])
        for mismatch in summary["mismatches"]:
            lines.append(
                f"- `{mismatch['domain']}`: expected `{mismatch['expected']}`, observed kind `{mismatch['detection_kind']}` / platform `{mismatch['observed_platform']}`; search `{mismatch['search_kind']}`."
            )
    lines.extend(
        [
            "",
            "The JSONL is the authoritative per-request evidence. Empty results mean only that the fixed query returned zero candidates at observation time. Tool errors and terminal outcomes were not retried with another query.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    jobs = load_jobs(DEFAULT_INPUT)
    cache_domains = learned_cache_domains(DEFAULT_VENDORS)
    input_domains = {urlsplit(job["store"]).hostname for job in jobs}
    if not input_domains <= cache_domains:
        missing = sorted(input_domains - cache_domains)
        raise SystemExit(f"acceptance domains missing from learned cache: {missing}")

    if args.command == "validate":
        rows = load_rows(args.jsonl)
        validate_rows(rows, jobs, cache_domains)
        print(json.dumps(summarize(rows), separators=(",", ":"), sort_keys=True))
        return 0

    sys.path.insert(0, str(SCRIPT_DIR))
    import platform_api
    from platform_api_core import Http, redact_url

    tree_hash = source_tree_hash(SCRIPT_DIR)
    rows = []
    with args.jsonl.open("x", encoding="utf-8") as output:
        for index, job in enumerate(jobs, 1):
            row = run_job(platform_api, Http, redact_url, job, tree_hash)
            rows.append(row)
            output.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")
            output.flush()
            print(
                f"[{index:02d}/59] {row['domain']} {row['search']['kind']} {row['search']['candidate_count']}",
                file=sys.stderr,
                flush=True,
            )
    validate_rows(rows, jobs, cache_domains)
    summary = summarize(rows)
    args.report.write_text(report(rows, summary), encoding="utf-8")
    print(json.dumps(summary, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
