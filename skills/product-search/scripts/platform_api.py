#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "beautifulsoup4>=4.13,<5",
#   "cryptography>=45,<47",
#   "httpx>=0.28,<0.29",
# ]
# ///

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from platform_api_core import (
    Detection,
    Http,
    ToolError,
    canonical_url,
    normalize_store_url,
    url_origin,
    validate_result,
    wall_system,
)
from platforms import bigcommerce, extra, magento, shopify, squarespace, woocommerce

SCHEMA_VERSION = 1
ADAPTERS = {
    "shopify": shopify,
    "woocommerce": woocommerce,
    "magento": magento,
    "bigcommerce": bigcommerce,
    "squarespace": squarespace,
    "wix": extra,
    "ecwid": extra,
    "sfcc": extra,
}


def detect_store(http: Http, store: str) -> Detection:
    requested = normalize_store_url(store)
    homepage = http.request("GET", requested, follow_redirects=True)
    entry_url = canonical_url(str(homepage.url))
    origin = url_origin(entry_url)
    detections: list[Detection] = []
    walls: list[Detection] = []

    _collect(detections, walls, woocommerce.detect(http, origin, entry_url))
    _collect(detections, walls, shopify.detect(http, origin, entry_url, homepage))
    _collect(detections, walls, magento.detect(http, origin, entry_url, homepage))
    _collect(detections, walls, bigcommerce.detect(homepage, origin, entry_url))
    _collect(detections, walls, squarespace.detect(homepage, origin, entry_url))
    _collect(detections, walls, extra.detect(homepage, origin, entry_url))

    platforms = {detection.platform for detection in detections}
    if len(platforms) > 1:
        names = ", ".join(
            sorted(platform for platform in platforms if platform is not None)
        )
        raise ToolError(f"Conflicting positive storefront detections: {names}")
    if detections:
        chosen = detections[0]
        evidence = tuple(
            dict.fromkeys(
                value for detection in detections for value in detection.evidence
            )
        )
        api_origins = {detection.api_origin for detection in detections}
        if len(api_origins) != 1:
            raise ToolError(f"Conflicting {chosen.platform} API origins")
        return Detection(
            "detected", origin, entry_url, chosen.platform, chosen.api_origin, evidence
        )
    if walls:
        systems = {detection.system for detection in walls}
        statuses = {detection.status for detection in walls}
        if len(systems) != 1 or len(statuses) != 1:
            raise ToolError("Conflicting bot-wall classifications")
        wall = walls[0]
        evidence = tuple(
            dict.fromkeys(value for detection in walls for value in detection.evidence)
        )
        return Detection(
            "bot_wall",
            origin,
            entry_url,
            None,
            None,
            evidence,
            wall.system,
            wall.status,
        )
    system = wall_system(homepage)
    if system is not None:
        return Detection(
            "bot_wall",
            origin,
            entry_url,
            None,
            None,
            (f"HTTP {homepage.status_code} {system} challenge",),
            system,
            homepage.status_code,
        )
    return Detection(
        "unknown",
        origin,
        entry_url,
        None,
        None,
        (f"No positive platform signal; homepage HTTP {homepage.status_code}",),
    )


def execute(command: str, store: str, value: str | None, http: Http) -> dict[str, Any]:
    detection = detect_store(http, store)
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "observed_at": _now(),
        "input": {
            "store": store,
            **({"query": value} if command in {"search", "probe"} else {}),
        },
        "origin": detection.origin,
        "detection": detection.public(),
        "evidence": http.evidence,
    }
    if command == "detect" or detection.kind != "detected":
        return record
    if detection.platform is None:
        raise AssertionError("Detected storefront must contain a platform")
    adapter = ADAPTERS[detection.platform]
    if command == "search":
        if value is None:
            raise AssertionError("Search requires a query")
        record["result"] = adapter.search(http, detection, value)
    elif command == "quote":
        if value is None:
            raise AssertionError("Quote requires an item_ref")
        record["input"]["item_ref"] = value
        record["result"] = adapter.quote(http, detection, value)
    elif command == "probe":
        if value is None:
            raise AssertionError("Probe requires a query")
        found = adapter.search(http, detection, value)
        record["search"] = found
        if found["kind"] != "search":
            record["result"] = found
        else:
            candidate = next(
                (
                    _candidate(item)
                    for item in found["items"]
                    if _candidate(item) is not None
                ),
                None,
            )
            record["result"] = (
                found
                if candidate is None
                else adapter.quote(http, detection, candidate)
            )
    else:
        raise AssertionError(f"Unknown command {command}")
    if "search" in record:
        validate_result(record["search"])
    validate_result(record["result"])
    record["evidence"] = http.evidence
    return record


def run_corpus(input_path: Path, output_path: Path) -> bool:
    jobs = _corpus_jobs(input_path)
    completed, prior_error = _completed(output_path)
    failed = prior_error
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as output:
        for job in jobs:
            identity = (job["store"], job["query"])
            if identity in completed:
                continue
            http = Http()
            try:
                record = execute("probe", job["store"], job["query"], http)
            except ToolError as error:
                failed = True
                record = {
                    "schema_version": SCHEMA_VERSION,
                    "observed_at": _now(),
                    "input": job,
                    "error": {"kind": "tool_error", "message": str(error)},
                    "evidence": http.evidence,
                }
            finally:
                http.close()
            output.write(
                json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n"
            )
            output.flush()
    return not failed


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "corpus":
        try:
            return 0 if run_corpus(args.input, args.output) else 1
        except ToolError as error:
            print(f"tool_error: {error}", file=sys.stderr)
            return 1

    http = Http()
    try:
        record = execute(args.command, args.store, getattr(args, "value", None), http)
    except ToolError as error:
        print(f"tool_error: {error}", file=sys.stderr)
        return 1
    finally:
        http.close()
    print(json.dumps(record, separators=(",", ":"), sort_keys=True))
    return 0


def _collect(
    detections: list[Detection], walls: list[Detection], value: Detection | None
) -> None:
    if value is None:
        return
    if value.kind == "detected":
        detections.append(value)
    elif value.kind == "bot_wall":
        walls.append(value)
    elif value.kind != "unknown":
        raise AssertionError(value.kind)


def _candidate(item: Any) -> str | None:
    if not isinstance(item, dict):
        raise ToolError("Search adapter returned a non-object item")
    reference = item.get("item_ref")
    if not isinstance(reference, str):
        raise ToolError("Search adapter returned an item without item_ref")
    if (
        item.get("available") is False
        or item.get("purchasable") is False
        or item.get("requires_configuration") is True
    ):
        return None
    return reference


def _corpus_jobs(path: Path) -> list[dict[str, str]]:
    try:
        value = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ToolError(f"Corpus input is not readable JSON: {path}") from error
    if not isinstance(value, list) or not 1 <= len(value) <= 100:
        raise ToolError("Corpus input must be an array of 1 to 100 jobs")
    jobs: list[dict[str, str]] = []
    for job in value:
        if not isinstance(job, dict) or set(job) != {"store", "query"}:
            raise ToolError("Each corpus job must contain exactly store and query")
        if any(
            not isinstance(job[name], str) or not job[name].strip()
            for name in ("store", "query")
        ):
            raise ToolError("Corpus store and query values must be nonempty strings")
        jobs.append({"store": job["store"], "query": job["query"]})
    return jobs


def _completed(path: Path) -> tuple[set[tuple[str, str]], bool]:
    if not path.exists():
        return set(), False
    completed: set[tuple[str, str]] = set()
    failed = False
    for number, line in enumerate(path.read_text().splitlines(), 1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ToolError(
                f"Corpus output has invalid JSON on line {number}"
            ) from error
        job = record.get("input") if isinstance(record, dict) else None
        if (
            not isinstance(job, dict)
            or not isinstance(job.get("store"), str)
            or not isinstance(job.get("query"), str)
        ):
            raise ToolError(f"Corpus output line {number} has no store/query identity")
        completed.add((job["store"], job["query"]))
        failed = failed or "error" in record
    return completed, failed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe public storefront product and shipping APIs"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    detect = commands.add_parser("detect")
    detect.add_argument("store")
    for name in ("search", "probe"):
        command = commands.add_parser(name)
        command.add_argument("store")
        command.add_argument("value", metavar="QUERY")
    quote = commands.add_parser("quote")
    quote.add_argument("store")
    quote.add_argument("value", metavar="ITEM_REF")
    corpus = commands.add_parser("corpus")
    corpus.add_argument("input", type=Path)
    corpus.add_argument("output", type=Path)
    return parser


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


if __name__ == "__main__":
    raise SystemExit(main())
