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
import math
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from platform_search_corpus_contract import (
    EXPECTED_DISPOSITION_SHA256,
    disposition_sha256,
)
from read_only_http import GRAPHQL_DOCUMENT_SHA256_BY_OPERATION
from read_only_http import _strict_unquote as strict_unquote_url

SCHEMA_VERSION = 4
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REPORT_DIR = SKILL_DIR / "dev" / "reports"
DEFAULT_INPUT = REPORT_DIR / "Product Search Storefront Corpus 2026-07-31.input.json"
DEFAULT_JSONL = REPORT_DIR / "Product Search Storefront Corpus 2026-08-01.jsonl"
DEFAULT_REPORT = REPORT_DIR / "Product Search Storefront Corpus 2026-08-01.md"
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
    "www.alcott.eu": "Alcott",
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
    "entry_origins",
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


class CorpusJob(TypedDict):
    store: str
    entry_origins: list[str]
    expected_group: str
    query: str
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
PRODUCT_REQUIRED_KEYS = {"name", "variant", "sku", "barcode", "product_url"}
HTTP_KEYS = {
    "method",
    "requested_url",
    "final_url",
    "status",
    "content_type",
    "bytes",
    "sha256",
    "elapsed_ms",
    "operation_kind",
    "body_sha256",
    "document_sha256",
    "source_request_sha256",
    "source_response_sha256",
}
GRAPHQL_OPERATION_KINDS = {
    "shopify_probe",
    "shopify_product_search",
    "magento_probe",
    "magento_product_search",
    "magento_product_detail",
}
POST_OPERATION_KINDS = GRAPHQL_OPERATION_KINDS | {
    "wix_catalog_search",
    "ecwid_initial_data",
}
GET_OPERATION_KINDS = {
    "bigcommerce_search",
    "discovered_product_page",
    "ecwid_products",
    "ecwid_script",
    "magento_html_search",
    "sfcc_search",
    "squarespace_product_json",
    "squarespace_search",
    "storefront_entry",
    "storefront_entry_replay",
    "wix_bootstrap",
    "woo_products",
}
READ_ONLY_OPERATION_KINDS = POST_OPERATION_KINDS | GET_OPERATION_KINDS
EMPTY_BODY_SHA256 = hashlib.sha256(b"").hexdigest()
SEARCH_COMMON_KEYS = {
    "kind",
    "platform",
    "source",
    "candidate_count",
    "selection",
    "selected_index",
    "selected_product",
    "item_ref_sha256",
}
TERMINAL_KEYS = {
    "tool_error": SEARCH_COMMON_KEYS | {"stage", "message"},
    "not_run": SEARCH_COMMON_KEYS | {"stage", "reason"},
    "gated": SEARCH_COMMON_KEYS
    | {"operation", "reason", "status", "browser_required", "endpoint"},
    "bot_wall": SEARCH_COMMON_KEYS | {"operation", "reason", "system", "status"},
    "unsupported_operation": SEARCH_COMMON_KEYS
    | {"operation", "reason", "browser_required"},
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


def validate_saved_http_evidence(
    values: list[dict[str, Any]], row: dict[str, Any]
) -> None:
    domain = row["domain"]
    prior: list[dict[str, Any]] = []
    for request in values:
        _validate_saved_http_record(request, domain)
        source = _saved_source(request, prior, domain)
        _validate_get_route(request, source, row, prior)
        prior.append(request)
    entries = [
        request
        for request in values
        if request["operation_kind"] == "storefront_entry"
    ]
    if not entries:
        raise SystemExit(f"HTTP evidence has no storefront entry: {domain}")
    terminal_entry = entries[-1]
    if _origin(terminal_entry["requested_url"]) != row["resolved_origin"]:
        raise SystemExit(f"storefront entry does not join resolved origin: {domain}")
    entry_urls = [request["requested_url"] for request in entries]
    if len(entry_urls) > 6:
        raise SystemExit(f"storefront entry exceeded five redirects: {domain}")
    if len(entry_urls) != len(set(entry_urls)):
        raise SystemExit(f"storefront entry contains a redirect loop: {domain}")


def _validate_saved_http_record(request: dict[str, Any], domain: str) -> None:
    if set(request) != HTTP_KEYS:
        raise SystemExit(f"HTTP evidence has unsafe keys: {domain}")
    operation_kind = request["operation_kind"]
    if (
        not isinstance(operation_kind, str)
        or operation_kind not in READ_ONLY_OPERATION_KINDS
        or request["method"]
        != ("GET" if operation_kind in GET_OPERATION_KINDS else "POST")
        or not isinstance(request["requested_url"], str)
        or not isinstance(request["final_url"], str)
        or not isinstance(request["content_type"], str)
        or type(request["status"]) is not int
        or not 100 <= request["status"] <= 599
        or type(request["bytes"]) is not int
        or request["bytes"] < 0
        or type(request["elapsed_ms"]) is not int
        or request["elapsed_ms"] < 0
    ):
        raise SystemExit(f"HTTP evidence has invalid fields: {domain}")
    for key in ("sha256", "body_sha256"):
        if (
            not isinstance(request[key], str)
            or re.fullmatch(r"[0-9a-f]{64}", request[key]) is None
        ):
            raise SystemExit(f"HTTP evidence hash is invalid: {domain}")
    document_sha256 = request["document_sha256"]
    if request["operation_kind"] in GRAPHQL_OPERATION_KINDS:
        if (
            not isinstance(document_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", document_sha256) is None
            or document_sha256
            != GRAPHQL_DOCUMENT_SHA256_BY_OPERATION[request["operation_kind"]]
        ):
            raise SystemExit(f"GraphQL document hash is invalid: {domain}")
    elif document_sha256 is not None:
        raise SystemExit(f"non-GraphQL evidence has a document hash: {domain}")
    for key in ("requested_url", "final_url"):
        _saved_https_url(request[key], domain)
    requested = urlsplit(request["requested_url"])
    if operation_kind in GET_OPERATION_KINDS:
        if request["body_sha256"] != EMPTY_BODY_SHA256:
            raise SystemExit(f"GET evidence has a nonempty body: {domain}")
        if request["requested_url"] != request["final_url"]:
            raise SystemExit(f"GET evidence must represent one transport hop: {domain}")
    elif requested.query or not _valid_operation_endpoint(operation_kind, requested):
        raise SystemExit(f"HTTP operation endpoint is invalid: {domain}")
    source_values = (
        request["source_request_sha256"],
        request["source_response_sha256"],
    )
    if (source_values[0] is None) != (source_values[1] is None) or any(
        value is not None
        and (
            not isinstance(value, str)
            or re.fullmatch(r"[0-9a-f]{64}", value) is None
        )
        for value in source_values
    ):
        raise SystemExit(f"HTTP evidence provenance is invalid: {domain}")


def _saved_source(
    request: dict[str, Any], prior: list[dict[str, Any]], domain: str
) -> dict[str, Any] | None:
    source_request = request["source_request_sha256"]
    if source_request is None:
        return None
    matches = [
        candidate
        for candidate in prior
        if _saved_request_sha256(candidate) == source_request
        and candidate["sha256"] == request["source_response_sha256"]
    ]
    if len(matches) != 1:
        raise SystemExit(f"HTTP evidence provenance has no unique earlier source: {domain}")
    return matches[0]


def _saved_request_sha256(request: dict[str, Any]) -> str:
    value = "\0".join(
        (
            request["method"],
            request["requested_url"],
            request["operation_kind"],
            request["body_sha256"],
        )
    )
    return hashlib.sha256(value.encode()).hexdigest()


def _validate_get_route(
    request: dict[str, Any],
    source: dict[str, Any] | None,
    row: dict[str, Any],
    prior: list[dict[str, Any]],
) -> None:
    kind = request["operation_kind"]
    if kind not in GET_OPERATION_KINDS:
        if source is not None:
            raise SystemExit(f"POST evidence has unexpected provenance: {row['domain']}")
        return
    url = urlsplit(request["requested_url"])
    root = source is None
    if source is not None and source["operation_kind"] == kind:
        if source["status"] not in {301, 302, 303, 307, 308}:
            raise SystemExit(f"redirect provenance is not a redirect: {row['domain']}")
        _validate_saved_redirect(kind, source, request, row)
        return
    if kind == "ecwid_script":
        _require_source(source, {"storefront_entry_replay"}, row)
        if (
            request["requested_url"]
            != f"https://app.ecwid.com/script.js?{url.query}"
            or re.fullmatch(r"[1-9][0-9]*", url.query) is None
        ):
            raise SystemExit(f"Ecwid script route is invalid: {row['domain']}")
        return
    origin = row["resolved_origin"]
    query = _strict_pairs(url.query, row["domain"])
    if kind == "storefront_entry":
        if not root or request["requested_url"] != _normalized_entry(row["entry_url"]):
            raise SystemExit(f"storefront entry differs from row input: {row['domain']}")
    elif kind == "storefront_entry_replay":
        _require_source(source, {"storefront_entry"}, row)
        if request["requested_url"] != source["requested_url"]:
            raise SystemExit(f"entry replay differs from its source: {row['domain']}")
    elif kind == "woo_products":
        _require_root(root, row)
        valid = query == [("search", "__codex_platform_probe__"), ("per_page", "1")]
        valid = valid or (
            query == [("search", row["query"]), ("per_page", "20")]
            and row["detection"] is not None
            and row["detection"].get("platform") == "woocommerce"
        )
        if _origin(request["requested_url"]) != origin or url.path != "/wp-json/wc/store/v1/products" or not valid:
            raise SystemExit(f"WooCommerce GET route is invalid: {row['domain']}")
    elif kind == "bigcommerce_search":
        _exact_search_root(request, root, row, "/search.php", "search_query", "bigcommerce")
    elif kind == "magento_html_search":
        _require_root(root, row)
        expected_path = urlsplit(urljoin(_terminal_entry(prior), "catalogsearch/result")).path
        if _origin(request["requested_url"]) != origin or url.path != expected_path or query != [("q", row["query"])] or not _detected(row, "magento", "html"):
            raise SystemExit(f"Magento HTML GET route is invalid: {row['domain']}")
    elif kind == "squarespace_search":
        _exact_search_root(request, root, row, "/search", "q", "squarespace")
    elif kind == "squarespace_product_json":
        _require_source(source, {"storefront_entry", "squarespace_search"}, row)
        if _origin(request["requested_url"]) != origin or query != [("format", "json")]:
            raise SystemExit(f"Squarespace product JSON route is invalid: {row['domain']}")
    elif kind == "wix_bootstrap":
        _exact_path_root(request, root, row, "/_api/v1/access-tokens", "wix")
    elif kind == "ecwid_products":
        _require_source(source, {"ecwid_initial_data"}, row)
        if (
            url.hostname != "app.ecwid.com"
            or re.fullmatch(r"/api/v3/[1-9][0-9]*/products", url.path) is None
            or query != [("token", "[redacted]"), ("keyword", row["query"]), ("limit", "10")]
        ):
            raise SystemExit(f"Ecwid products route is invalid: {row['domain']}")
    elif kind == "sfcc_search":
        _require_root(root, row)
        expected_path = urlsplit(urljoin(_terminal_entry(prior), "search")).path
        if _origin(request["requested_url"]) != origin or url.path != expected_path or query != [("q", row["query"])] or not _detected(row, "sfcc"):
            raise SystemExit(f"SFCC GET route is invalid: {row['domain']}")
    elif kind == "discovered_product_page":
        _require_source(source, {"bigcommerce_search", "magento_html_search"}, row)
        if _origin(request["requested_url"]) != origin or query or _unsafe_saved_path(url.path):
            raise SystemExit(f"discovered product route is invalid: {row['domain']}")
    else:
        raise AssertionError(kind)


def _validate_saved_redirect(
    kind: str, source: dict[str, Any], request: dict[str, Any], row: dict[str, Any]
) -> None:
    source_url = urlsplit(source["requested_url"])
    target = urlsplit(request["requested_url"])
    if _unsafe_saved_path(target.path):
        raise SystemExit(f"redirect changed resource purpose: {row['domain']}")
    if kind == "storefront_entry":
        if _origin(request["requested_url"]) not in row["entry_origins"] or target.query:
            raise SystemExit(f"entry redirect changed resource purpose: {row['domain']}")
        return
    if _origin(request["requested_url"]) != _origin(source["requested_url"]):
        raise SystemExit(f"redirect left storefront origin: {row['domain']}")
    if kind in {"discovered_product_page", "squarespace_product_json"} and target.path.rstrip("/") != source_url.path.rstrip("/"):
        raise SystemExit(f"product redirect changed resource purpose: {row['domain']}")
    if kind == "magento_html_search":
        if source["source_request_sha256"] is not None or target.query not in {
            source_url.query,
            "",
        }:
            raise SystemExit(f"Magento redirect changed resource purpose: {row['domain']}")
        return
    if target.query != source_url.query:
        raise SystemExit(f"redirect changed resource query: {row['domain']}")


def _saved_https_url(value: Any, domain: str) -> None:
    if not isinstance(value, str):
        raise SystemExit(f"HTTP evidence URL is invalid: {domain}")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as error:
        raise SystemExit(f"HTTP evidence URL is invalid: {domain}") from error
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
        or port not in {None, 443}
    ):
        raise SystemExit(f"HTTP evidence URL is invalid: {domain}")


def _origin(value: str) -> str:
    parts = urlsplit(value)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def _normalized_entry(value: str) -> str:
    parts = urlsplit(value)
    return urlunsplit(("https", parts.netloc, parts.path or "/", "", ""))


def _strict_pairs(value: str, domain: str) -> list[tuple[str, str]]:
    pairs = parse_qsl(value, keep_blank_values=True)
    if any(not name or not item for name, item in pairs) or len(pairs) != len(
        {name for name, _ in pairs}
    ):
        raise SystemExit(f"HTTP evidence query is invalid: {domain}")
    return pairs


def _require_root(root: bool, row: dict[str, Any]) -> None:
    if not root:
        raise SystemExit(f"exact GET route has unexpected provenance: {row['domain']}")


def _require_source(
    source: dict[str, Any] | None, kinds: set[str], row: dict[str, Any]
) -> None:
    if (
        source is None
        or source["operation_kind"] not in kinds
        or source["status"] != 200
    ):
        raise SystemExit(f"dynamic GET has invalid source: {row['domain']}")


def _detected(row: dict[str, Any], platform: str, source: str | None = None) -> bool:
    detection = row["detection"]
    return bool(
        isinstance(detection, dict)
        and detection.get("kind") == "detected"
        and detection.get("platform") == platform
        and (source is None or detection.get("search_source") == source)
    )


def _terminal_entry(prior: list[dict[str, Any]]) -> str:
    entries = [
        request["requested_url"]
        for request in prior
        if request["operation_kind"] == "storefront_entry"
    ]
    if not entries:
        raise SystemExit("HTTP evidence has no earlier storefront entry")
    return entries[-1]


def _exact_search_root(
    request: dict[str, Any],
    root: bool,
    row: dict[str, Any],
    path: str,
    query_name: str,
    platform: str,
) -> None:
    _require_root(root, row)
    url = urlsplit(request["requested_url"])
    if (
        _origin(request["requested_url"]) != row["resolved_origin"]
        or url.path != path
        or _strict_pairs(url.query, row["domain"])
        != [(query_name, row["query"])]
        or not _detected(row, platform)
    ):
        raise SystemExit(f"{platform} GET route is invalid: {row['domain']}")


def _exact_path_root(
    request: dict[str, Any],
    root: bool,
    row: dict[str, Any],
    path: str,
    platform: str,
) -> None:
    _require_root(root, row)
    url = urlsplit(request["requested_url"])
    if (
        _origin(request["requested_url"]) != row["resolved_origin"]
        or url.path != path
        or url.query
        or not _detected(row, platform)
    ):
        raise SystemExit(f"{platform} GET route is invalid: {row['domain']}")


def _unsafe_saved_path(path: str) -> bool:
    try:
        decoded = strict_unquote_url(path, plus_as_space=False)
    except ValueError:
        return True
    segments = {
        segment.rsplit(".", 1)[0].casefold()
        for segment in decoded.split("/")
        if segment
    }
    return bool(
        segments
        & {
            "add-to-cart",
            "address",
            "addresses",
            "basket",
            "cart",
            "carts",
            "checkout",
            "checkouts",
            "consignment",
            "consignments",
            "guest-carts",
            "login",
            "logout",
            "rate",
            "rates",
            "shipping",
            "session",
            "sessions",
            "wishlist",
            "wishlists",
        }
    )


def _valid_operation_endpoint(operation_kind: str, requested: Any) -> bool:
    if operation_kind.startswith("shopify_"):
        return requested.path == "/api/2026-07/graphql.json"
    if operation_kind.startswith("magento_"):
        return requested.path == "/graphql"
    if operation_kind == "wix_catalog_search":
        return requested.path == "/_api/catalog-reader-server/api/v1/products/query"
    if operation_kind == "ecwid_initial_data":
        return bool(
            requested.hostname
            and requested.hostname.endswith(".ecwid.com")
            and re.fullmatch(
                r"/storefront/api/v1/[1-9][0-9]*/initial-data", requested.path
            )
        )
    raise AssertionError(f"unhandled read-only operation: {operation_kind}")


def load_jobs(path: Path) -> list[CorpusJob]:
    value = json.loads(path.read_text())
    if not isinstance(value, list) or len(value) != 59:
        raise SystemExit("input must contain exactly 59 jobs")
    jobs: list[CorpusJob] = []
    for job in value:
        if not isinstance(job, dict) or set(job) != {
            "store",
            "entry_origins",
            "expected_group",
            "query",
        }:
            raise SystemExit(
                "every job must contain store, entry_origins, expected_group, and query"
            )
        if job["expected_group"] not in EXPECTED_PLATFORMS:
            raise SystemExit(f"unknown expected group: {job['expected_group']}")
        if not all(
            isinstance(job[key], str) and job[key]
            for key in ("store", "expected_group", "query")
        ):
            raise SystemExit("job fields must be nonempty strings")
        _validate_entry_origins(job["store"], job["entry_origins"])
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


def _validate_entry_origins(store: str, value: Any) -> None:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(origin, str) or not origin for origin in value)
        or len(value) != len(set(value))
    ):
        raise SystemExit("entry_origins must be a unique nonempty list")
    for origin in value:
        _saved_https_url(origin, urlsplit(store).hostname or store)
        if _origin(origin) != origin:
            raise SystemExit("entry_origins must contain exact HTTPS origins")
    if _origin(_normalized_entry(store)) not in value:
        raise SystemExit("entry_origins must contain the normalized input origin")


def learned_cache_domains(path: Path) -> set[str]:
    text = path.read_text()
    section = text.split("## Learned storefront cache", 1)
    if len(section) != 2:
        raise SystemExit("vendors.md has no learned storefront cache")
    return set(re.findall(r"^\| `([^`]+)` \|", section[1], re.MULTILINE))


def validate_search_outcome(search: dict[str, Any], domain: str) -> None:
    kind = search.get("kind")
    if not isinstance(kind, str):
        raise SystemExit(f"search outcome has unsafe keys: {domain}")
    if kind != "search":
        expected = TERMINAL_KEYS.get(kind)
        if expected is None or set(search) != expected:
            raise SystemExit(f"search outcome has unsafe keys: {domain}")
        _validate_terminal_outcome(search, domain)
        return

    expected = SEARCH_COMMON_KEYS | {"operation"}
    if set(search) != expected:
        raise SystemExit(f"search outcome has unsafe keys: {domain}")
    if (
        search["operation"] != "search"
        or not _valid_search_source(search["platform"], search["source"])
        or type(search["candidate_count"]) is not int
        or search["candidate_count"] < 0
    ):
        raise SystemExit(f"search outcome has invalid fields: {domain}")

    count = search["candidate_count"]
    selection = search["selection"]
    selected = (
        search["selected_index"],
        search["selected_product"],
        search["item_ref_sha256"],
    )
    if count == 0:
        if selection != "empty" or selected != (None, None, None):
            raise SystemExit(f"zero-candidate search has invalid selection: {domain}")
        return
    if selection == "no_eligible_candidate":
        if selected != (None, None, None):
            raise SystemExit(f"ineligible search has invalid selection: {domain}")
        return
    if selection != "selected":
        raise SystemExit(f"positive search has invalid selection: {domain}")

    index, product, reference_hash = selected
    if type(index) is not int or not 0 <= index < count:
        raise SystemExit(f"selected search index is out of range: {domain}")
    _validate_safe_product(product, domain, search["platform"])
    if (
        not isinstance(reference_hash, str)
        or re.fullmatch(r"[0-9a-f]{64}", reference_hash) is None
    ):
        raise SystemExit(f"selected search item reference is invalid: {domain}")


def _validate_terminal_outcome(search: dict[str, Any], domain: str) -> None:
    if any(
        search[key] is not None
        for key in (
            "candidate_count",
            "selection",
            "selected_index",
            "selected_product",
            "item_ref_sha256",
        )
    ):
        raise SystemExit(f"terminal outcome requires null selection: {domain}")

    kind = search["kind"]
    platform = search["platform"]
    source = search["source"]
    if (platform is not None and (not isinstance(platform, str) or not platform)) or (
        source is not None and (not isinstance(source, str) or not source)
    ):
        raise SystemExit(f"terminal outcome has invalid fields: {domain}")
    if platform is not None and not _valid_search_source(platform, source):
        raise SystemExit(f"terminal outcome has invalid source: {domain}")
    if (platform is None) != (source is None):
        raise SystemExit(f"terminal outcome has incomplete platform source: {domain}")
    if kind == "tool_error" and (
        (search["stage"] == "detection" and platform is not None)
        or (search["stage"] == "search" and platform is None)
    ):
        raise SystemExit(f"tool error has invalid stage fields: {domain}")
    if kind == "not_run" and (platform is not None or source is not None):
        raise SystemExit(f"not-run outcome has unexpected platform: {domain}")
    if kind == "not_run" and (
        search["stage"] != "search" or search["reason"] != "detection_not_positive"
    ):
        raise SystemExit(f"not-run outcome has invalid reason: {domain}")
    if kind not in {"tool_error", "not_run"} and (
        platform is None or source is None or search["operation"] != "search"
    ):
        raise SystemExit(f"terminal outcome has invalid fields: {domain}")
    for key in ("stage", "message", "reason", "system"):
        if key in search and (not isinstance(search[key], str) or not search[key]):
            raise SystemExit(f"terminal outcome has invalid fields: {domain}")
    if "stage" in search and search["stage"] not in {"detection", "search"}:
        raise SystemExit(f"terminal outcome has invalid stage: {domain}")
    if kind == "tool_error" and len(search["message"]) > 500:
        raise SystemExit(f"terminal outcome has invalid message: {domain}")
    if "status" in search and (
        type(search["status"]) is not int or not 100 <= search["status"] <= 599
    ):
        raise SystemExit(f"terminal outcome has invalid status: {domain}")
    if "browser_required" in search and type(search["browser_required"]) is not bool:
        raise SystemExit(f"terminal outcome has invalid browser flag: {domain}")
    if kind == "gated" and search["browser_required"] is not True:
        raise SystemExit(f"gated outcome must require a browser: {domain}")
    if "endpoint" in search:
        endpoint = urlsplit(search["endpoint"])
        if endpoint.scheme != "https" or not endpoint.hostname:
            raise SystemExit(f"terminal outcome has invalid endpoint: {domain}")
def _valid_search_source(platform: Any, source: Any) -> bool:
    if platform not in SOURCES or not isinstance(source, str):
        return False
    if platform == "magento":
        return source in {"magento_graphql", "magento_html"}
    if platform == "squarespace":
        return source in {
            "commerce_collection_json",
            "squarespace_explicit_entry_url",
            "squarespace_storefront_search",
        }
    return source == SOURCES[platform]


def validate_row_relationships(row: dict[str, Any]) -> None:
    detection = row["detection"]
    search = row["search"]
    domain = row["domain"]
    if detection is None:
        if (
            row["resolved_origin"] is not None
            or search["kind"] != "tool_error"
            or search["stage"] != "detection"
        ):
            raise SystemExit(f"missing detection has invalid outcome: {domain}")
        return
    if row["resolved_origin"] != detection["origin"]:
        raise SystemExit(f"resolved origin differs from detection: {domain}")
    if detection["kind"] == "detected":
        if search["platform"] != detection["platform"]:
            raise SystemExit(f"search platform differs from detection: {domain}")
        return
    if search["kind"] != "not_run":
        raise SystemExit(f"non-positive detection ran search: {domain}")


def _validate_safe_product(product: Any, domain: str, platform: str) -> None:
    if (
        not isinstance(product, dict)
        or not PRODUCT_REQUIRED_KEYS <= set(product) <= PRODUCT_KEYS
        or (
            (not isinstance(product["name"], str) or not product["name"])
            and not (platform == "sfcc" and product["name"] is None)
        )
        or any(
            product[key] is not None and not isinstance(product[key], str)
            for key in ("variant", "sku", "barcode")
        )
    ):
        raise SystemExit(f"selected product has invalid fields: {domain}")
    product_url = urlsplit(product["product_url"])
    if product_url.scheme != "https" or not product_url.hostname:
        raise SystemExit(f"selected product has invalid URL: {domain}")
    for key in ("available", "purchasable", "requires_configuration"):
        if key in product and not isinstance(product[key], bool):
            raise SystemExit(f"selected product has invalid boolean: {domain}")
    for key in ("price", "compare_at_price"):
        if key in product and not _valid_saved_money(product[key]):
            raise SystemExit(f"selected product has invalid money: {domain}")
    if "weight" in product and not _valid_saved_weight(product["weight"]):
        raise SystemExit(f"selected product has invalid weight: {domain}")


def _valid_saved_money(value: Any) -> bool:
    if (
        not isinstance(value, dict)
        or set(value) != {"amount", "currency"}
        or not isinstance(value["amount"], str)
        or not isinstance(value["currency"], str)
        or not value["currency"]
    ):
        return False
    try:
        return Decimal(value["amount"]).is_finite()
    except (InvalidOperation, ValueError):
        return False


def _valid_saved_weight(value: Any) -> bool:
    if (
        not isinstance(value, dict)
        or set(value) != {"value", "unit"}
        or isinstance(value["value"], bool)
        or not isinstance(value["value"], (str, int, float))
        or not isinstance(value["unit"], str)
        or not value["unit"]
    ):
        return False
    try:
        return math.isfinite(float(value["value"]))
    except (OverflowError, ValueError):
        return False


def validate_detection(detection: Any, domain: str) -> None:
    if not isinstance(detection, dict) or not isinstance(detection.get("kind"), str):
        raise SystemExit(f"detection has unsafe keys: {domain}")
    kind = detection["kind"]
    if kind == "detected":
        allowed = {"kind", "origin", "platform", "api_origin", "evidence"}
        if detection.get("platform") == "magento":
            allowed.add("search_source")
    elif kind == "unknown":
        allowed = {"kind", "origin", "evidence"}
    elif kind == "bot_wall":
        allowed = {"kind", "origin", "system", "status", "evidence"}
    else:
        raise SystemExit(f"detection has unsafe keys: {domain}")
    if set(detection) != allowed:
        raise SystemExit(f"detection has unsafe keys: {domain}")
    origin = urlsplit(detection["origin"])
    evidence = detection["evidence"]
    if (
        origin.scheme != "https"
        or not origin.hostname
        or not isinstance(evidence, list)
        or not evidence
        or not all(isinstance(item, str) and item for item in evidence)
    ):
        raise SystemExit(f"detection has invalid fields: {domain}")
    if kind == "detected":
        api_origin = urlsplit(detection["api_origin"])
        if (
            detection["platform"] not in SOURCES
            or api_origin.scheme != "https"
            or not api_origin.hostname
            or (
                detection["platform"] == "magento"
                and detection["search_source"] not in {"graphql", "html"}
            )
        ):
            raise SystemExit(f"detection has invalid fields: {domain}")
    if kind == "bot_wall" and (
        not isinstance(detection["system"], str)
        or not detection["system"]
        or type(detection["status"]) is not int
        or not 100 <= detection["status"] <= 599
    ):
        raise SystemExit(f"detection has invalid fields: {domain}")


def source_tree_hash(source: Path) -> str:
    files = [
        source / "platform_api.py",
        source / "platform_api_core.py",
        source / "platform_search_acceptance.py",
        source / "read_only_http.py",
    ]
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
                "operation_kind": value["operation_kind"],
                "body_sha256": value["body_sha256"],
                "document_sha256": value["document_sha256"],
                "source_request_sha256": value["source_request_sha256"],
                "source_response_sha256": value["source_response_sha256"],
            }
        )
    return evidence


def select_candidate(
    platform_api: Any, items: list[dict[str, Any]], redact_url: Any
) -> tuple[str, int | None, dict[str, Any] | None, str | None]:
    for index, item in enumerate(items):
        reference = platform_api._candidate(item)
        if reference is not None:
            return (
                "selected",
                index,
                safe_product(item, redact_url),
                hashlib.sha256(reference.encode()).hexdigest(),
            )
    selection = "empty" if not items else "no_eligible_candidate"
    return selection, None, None, None


def terminal_outcome(
    result: dict[str, Any], platform: str, source: str | None, redact_url: Any
) -> dict[str, Any]:
    outcome: dict[str, Any] = {
        "kind": result["kind"],
        "operation": result.get("operation", "search"),
        "platform": platform,
        "source": source,
        "candidate_count": None,
        "selection": None,
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
    job: CorpusJob,
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
            detection = platform_api.detect_store(
                http, entry_url, job["entry_origins"]
            )
        except platform_api.ToolError as error:
            outcome = {
                "kind": "tool_error",
                "stage": "detection",
                "platform": None,
                "source": None,
                "candidate_count": None,
                "selection": None,
                "selected_index": None,
                "selected_product": None,
                "item_ref_sha256": None,
                "message": safe_error(error),
            }
        else:
            detection_public = platform_api.public_detection(detection)
            resolved_origin = detection.origin
            if detection.kind != "detected":
                outcome = {
                    "kind": "not_run",
                    "stage": "search",
                    "platform": None,
                    "source": None,
                    "candidate_count": None,
                    "selection": None,
                    "selected_index": None,
                    "selected_product": None,
                    "item_ref_sha256": None,
                    "reason": "detection_not_positive",
                }
            else:
                source = (
                    f"magento_{detection.search_source}"
                    if detection.platform == "magento"
                    else source_name(detection.platform, None)
                )
                try:
                    result = platform_api.ADAPTERS[detection.platform].search(
                        http, detection, job["query"]
                    )
                except platform_api.ToolError as error:
                    outcome = {
                        "kind": "tool_error",
                        "stage": "search",
                        "platform": detection.platform,
                        "source": source,
                        "candidate_count": None,
                        "selection": None,
                        "selected_index": None,
                        "selected_product": None,
                        "item_ref_sha256": None,
                        "message": safe_error(error),
                    }
                else:
                    if detection.platform == "magento":
                        if (
                            result["kind"] == "search"
                            and result.get("source") != detection.search_source
                        ):
                            raise SystemExit(
                                "Magento result source differs from detection"
                            )
                        source = f"magento_{detection.search_source}"
                    else:
                        source = source_name(detection.platform, result)
                    if result["kind"] == "search":
                        items = result["items"]
                        selection, selected_index, selected_product, reference_hash = (
                            select_candidate(platform_api, items, redact_url)
                        )
                        outcome = {
                            "kind": "search",
                            "operation": "search",
                            "platform": detection.platform,
                            "source": source,
                            "candidate_count": len(items),
                            "selection": selection,
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
        "entry_origins": job["entry_origins"],
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
    jobs: list[CorpusJob],
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
    if len(tree_hashes) != 1:
        raise SystemExit("output must contain one valid source-tree SHA-256")
    tree_hash = next(iter(tree_hashes))
    if re.fullmatch(r"[0-9a-f]{64}", tree_hash) is None:
        raise SystemExit("output must contain one valid source-tree SHA-256")
    if tree_hash != source_tree_hash(SCRIPT_DIR):
        raise SystemExit("source-tree SHA-256 differs from current production source")

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
            "entry_origins": job["entry_origins"],
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
            validate_detection(detection, row["domain"])
        search = row["search"]
        validate_search_outcome(search, row["domain"])
        validate_row_relationships(row)
        if (
            detection is not None
            and detection.get("platform") == "magento"
            and search["source"] != f"magento_{detection['search_source']}"
        ):
            raise SystemExit(
                f"Magento result source differs from detection: {row['domain']}"
            )
        validate_saved_http_evidence(row["http_evidence"], row)

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

    errors = [row["domain"] for row in rows if row["search"]["kind"] == "tool_error"]
    if errors:
        raise SystemExit(f"search produced a tool error: {', '.join(errors)}")


def validate_saved_rows(
    rows: list[dict[str, Any]],
    jobs: list[CorpusJob],
    cache_domains: set[str],
) -> None:
    validate_rows(rows, jobs, cache_domains)
    if disposition_sha256(rows) != EXPECTED_DISPOSITION_SHA256:
        raise SystemExit("per-domain search disposition digest differs")


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
        "This read-only acceptance rerun used one literal query (`a`) per store with no alternate-query retries. It called the production detection and platform search adapters over plain HTTP. Magento capability negotiation used one bounded product-search GraphQL query. The run created no cart, product line, customer address, consignment, or shipping-rate request.",
        "",
        "Opaque product references were hashed in memory and discarded. The JSONL contains only public detection evidence, whitelisted product fields, sanitized HTTP request metadata, and learned-cache domain joins.",
        "",
        f"Every row carries source-tree SHA-256 `{tree_hash}`, computed from the platform API, adapters, read-only HTTP policy, acceptance runner, and signing helper. The exact per-domain disposition SHA-256 is `{disposition_sha256(rows)}`. The observation window was {min(observations).astimezone(UTC).strftime('%Y-%m-%d %H:%M:%S')}–{max(observations).astimezone(UTC).strftime('%H:%M:%S')} UTC ({local_date} local time).",
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
            "| Store | Expected | Detection | Search outcome | Candidates | Selection | Selected product | SKU |",
            "| --- | --- | --- | --- | ---: | --- | --- | --- |",
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
            search["selection"] or "—",
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
        validate_saved_rows(rows, jobs, cache_domains)
        print(json.dumps(summarize(rows), separators=(",", ":"), sort_keys=True))
        return 0

    sys.path.insert(0, str(SCRIPT_DIR))
    import platform_api
    from platform_api_core import ReadOnlyHttp, redact_url

    tree_hash = source_tree_hash(SCRIPT_DIR)
    rows = []
    with args.jsonl.open("x", encoding="utf-8") as output:
        for index, job in enumerate(jobs, 1):
            row = run_job(platform_api, ReadOnlyHttp, redact_url, job, tree_hash)
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
