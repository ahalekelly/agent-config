# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "cryptography>=45,<47",
#   "httpx>=0.28,<0.29",
# ]
# ///

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).parents[1]))

import platform_search_acceptance as acceptance

EXPECTED_SOURCE_HASH = (
    "71fdb9ada5e47129baf9a9beb9be9d612adc7aa3027f9336078f5d8349f5666a"
)


class TypedEvidenceTests(unittest.TestCase):
    def test_saved_evidence_requires_an_exact_earlier_source_graph(self) -> None:
        entry = self.record(
            "storefront_entry", "https://store.example/", status=302
        )
        redirect = self.record("storefront_entry", "https://www.store.example/")
        redirect["source_request_sha256"] = acceptance._saved_request_sha256(entry)
        redirect["source_response_sha256"] = entry["sha256"]
        woo = self.record(
            "woo_products",
            "https://www.store.example/wp-json/wc/store/v1/products"
            "?search=valve&per_page=20",
        )
        row = {
            "domain": "store.example",
            "entry_url": "https://store.example",
            "entry_origins": [
                "https://store.example",
                "https://www.store.example",
            ],
            "resolved_origin": "https://www.store.example",
            "query": "valve",
            "detection": {"kind": "detected", "platform": "woocommerce"},
        }

        acceptance.validate_saved_http_evidence([entry, redirect, woo], row)
        redirect["source_response_sha256"] = "f" * 64
        with self.assertRaisesRegex(SystemExit, "unique earlier source"):
            acceptance.validate_saved_http_evidence([entry, redirect, woo], row)

    def test_saved_dynamic_reads_require_the_right_source_and_safe_purpose(self) -> None:
        entry = self.record("storefront_entry", "https://store.example/")
        search = self.record(
            "bigcommerce_search",
            "https://store.example/search.php?search_query=valve",
        )
        product = self.record(
            "discovered_product_page", "https://store.example/products/valve"
        )
        product["source_request_sha256"] = acceptance._saved_request_sha256(search)
        product["source_response_sha256"] = search["sha256"]
        row = self.row("bigcommerce")

        acceptance.validate_saved_http_evidence([entry, search, product], row)
        product["requested_url"] = product["final_url"] = (
            "https://store.example/logout"
        )
        with self.assertRaisesRegex(SystemExit, "discovered product route"):
            acceptance.validate_saved_http_evidence([entry, search, product], row)

    def test_saved_ecwid_chain_accepts_bare_script_id_and_requires_redacted_token(
        self,
    ) -> None:
        entry = self.record("storefront_entry", "https://store.example/")
        replay = self.record("storefront_entry_replay", "https://store.example/")
        replay["source_request_sha256"] = acceptance._saved_request_sha256(entry)
        replay["source_response_sha256"] = entry["sha256"]
        script = self.record("ecwid_script", "https://app.ecwid.com/script.js?248360")
        script["source_request_sha256"] = acceptance._saved_request_sha256(replay)
        script["source_response_sha256"] = replay["sha256"]
        initial = self.record(
            "ecwid_initial_data",
            "https://us-vir3-storefront-api.ecwid.com/storefront/api/v1/248360/initial-data",
        )
        initial["method"] = "POST"
        initial["body_sha256"] = hashlib.sha256(b'{"lang":"en"}').hexdigest()
        products = self.record(
            "ecwid_products",
            "https://app.ecwid.com/api/v3/248360/products"
            "?token=%5Bredacted%5D&keyword=valve&limit=10",
        )
        products["source_request_sha256"] = acceptance._saved_request_sha256(initial)
        products["source_response_sha256"] = initial["sha256"]
        evidence = [entry, replay, script, initial, products]
        row = self.row("ecwid")

        acceptance.validate_saved_http_evidence(evidence, row)

        products["requested_url"] = products["final_url"] = (
            products["requested_url"].replace("token=%5Bredacted%5D", "token=secret")
        )
        with self.assertRaisesRegex(SystemExit, "Ecwid products route"):
            acceptance.validate_saved_http_evidence(evidence, row)

    def test_saved_redirect_cannot_relabel_logout_as_an_entry(self) -> None:
        entry = self.record(
            "storefront_entry", "https://store.example/", status=302
        )
        redirect = self.record("storefront_entry", "https://store.example/logout")
        redirect["source_request_sha256"] = acceptance._saved_request_sha256(entry)
        redirect["source_response_sha256"] = entry["sha256"]

        with self.assertRaisesRegex(SystemExit, "resource purpose"):
            acceptance.validate_saved_http_evidence(
                [entry, redirect], self.row("bigcommerce")
            )

    def test_saved_entry_redirects_stay_in_scope_without_loops(self) -> None:
        entry = self.record(
            "storefront_entry", "https://store.example/", status=302
        )
        redirect = self.record(
            "storefront_entry", "https://other.example/", status=302
        )
        redirect["source_request_sha256"] = acceptance._saved_request_sha256(entry)
        redirect["source_response_sha256"] = entry["sha256"]
        row = self.row("bigcommerce")
        row["resolved_origin"] = "https://other.example"

        with self.assertRaisesRegex(SystemExit, "entry redirect"):
            acceptance.validate_saved_http_evidence([entry, redirect], row)

        redirect["requested_url"] = redirect["final_url"] = (
            "https://store.example/us/"
        )
        loop = self.record("storefront_entry", "https://store.example/")
        loop["source_request_sha256"] = acceptance._saved_request_sha256(redirect)
        loop["source_response_sha256"] = redirect["sha256"]
        row["resolved_origin"] = "https://store.example"
        with self.assertRaisesRegex(SystemExit, "redirect loop"):
            acceptance.validate_saved_http_evidence([entry, redirect, loop], row)

    def test_corpus_jobs_require_an_exact_preauthorized_entry_scope(self) -> None:
        jobs = json.loads(acceptance.DEFAULT_INPUT.read_text())
        cases = (
            [],
            ["https://other.example"],
            ["https://dernord.com", "https://dernord.com"],
            ["https://dernord.com/path"],
        )
        for entry_origins in cases:
            with self.subTest(entry_origins=entry_origins):
                invalid = copy.deepcopy(jobs)
                invalid[0]["entry_origins"] = entry_origins
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "input.json"
                    path.write_text(json.dumps(invalid))
                    with self.assertRaises(SystemExit):
                        acceptance.load_jobs(path)

    @staticmethod
    def row(platform: str) -> dict[str, object]:
        return {
            "domain": "store.example",
            "entry_url": "https://store.example",
            "entry_origins": ["https://store.example"],
            "resolved_origin": "https://store.example",
            "query": "valve",
            "detection": {"kind": "detected", "platform": platform},
        }

    @staticmethod
    def record(kind: str, url: str, status: int = 200) -> dict[str, object]:
        return {
            "method": "GET",
            "requested_url": url,
            "final_url": url,
            "status": status,
            "content_type": "text/html",
            "bytes": 0,
            "sha256": hashlib.sha256(kind.encode()).hexdigest(),
            "elapsed_ms": 0,
            "operation_kind": kind,
            "body_sha256": acceptance.EMPTY_BODY_SHA256,
            "document_sha256": None,
            "source_request_sha256": None,
            "source_response_sha256": None,
        }


class SavedCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.jobs = acceptance.load_jobs(acceptance.DEFAULT_INPUT)
        cls.rows = acceptance.load_rows(acceptance.DEFAULT_JSONL)
        cls.cache_domains = acceptance.learned_cache_domains(acceptance.DEFAULT_VENDORS)

    def validate(self, rows: list[dict[str, object]]) -> None:
        acceptance.validate_saved_rows(rows, self.jobs, self.cache_domains)

    def test_saved_corpus_matches_input_and_production_source(self) -> None:
        self.validate(self.rows)
        summary = acceptance.summarize(self.rows)

        self.assertEqual(summary["row_count"], 59)
        self.assertEqual(summary["unique_domain_count"], 59)
        self.assertEqual(
            sum(group["successes"] for group in summary["groups"].values()), 49
        )
        self.assertEqual(sum(group["empty"] for group in summary["groups"].values()), 9)
        self.assertEqual(
            sum(group["errors"] for group in summary["groups"].values()), 0
        )
        self.assertEqual(
            {row["source_tree_sha256"] for row in self.rows},
            {EXPECTED_SOURCE_HASH},
        )
        self.assertEqual(
            acceptance.source_tree_hash(acceptance.SCRIPT_DIR),
            EXPECTED_SOURCE_HASH,
        )

    def test_saved_report_is_rendered_from_the_saved_corpus(self) -> None:
        self.assertEqual(
            acceptance.DEFAULT_REPORT.read_text(),
            acceptance.report(self.rows, acceptance.summarize(self.rows)),
        )

    def test_learned_cache_accounts_for_corpus_and_wall_investigations(self) -> None:
        input_domains = {urlsplit(job["store"]).hostname for job in self.jobs}
        wall_investigation_domains = {
            "boltdepot.com",
            "glaciertanks.com",
            "omc-stepperonline.com",
        }

        self.assertEqual(len(input_domains), 59)
        self.assertTrue(input_domains.isdisjoint(wall_investigation_domains))
        tracked_domains = input_domains | wall_investigation_domains
        self.assertEqual(len(tracked_domains), 62)
        self.assertLessEqual(tracked_domains, self.cache_domains)

        vendors = acceptance.DEFAULT_VENDORS.read_text()
        self.assertIn("59-store acceptance corpus", vendors)
        self.assertIn("three separate tracked wall investigations", vendors)

    def test_validator_rejects_aggregate_preserving_disposition_swap(self) -> None:
        changed = copy.deepcopy(self.rows)
        changed[0]["search"], changed[1]["search"] = (
            changed[1]["search"],
            changed[0]["search"],
        )

        with self.assertRaisesRegex(SystemExit, "disposition digest"):
            self.validate(changed)

    def test_zero_candidate_search_cannot_select_a_product(self) -> None:
        empty = copy.deepcopy(
            next(
                row["search"]
                for row in self.rows
                if row["search"]["kind"] == "search"
                and row["search"]["candidate_count"] == 0
            )
        )
        selected = next(
            row["search"]
            for row in self.rows
            if row["search"]["kind"] == "search"
            and row["search"]["selected_product"] is not None
        )
        empty["selection"] = "empty"
        empty["selected_index"] = 0
        empty["selected_product"] = selected["selected_product"]
        empty["item_ref_sha256"] = selected["item_ref_sha256"]

        with self.assertRaisesRegex(SystemExit, "zero-candidate search"):
            acceptance.validate_search_outcome(empty, "empty.example")

    def test_terminal_outcome_requires_null_selection_fields(self) -> None:
        terminal = copy.deepcopy(
            next(row["search"] for row in self.rows if row["search"]["kind"] == "not_run")
        )
        terminal["selection"] = None
        terminal["candidate_count"] = 1

        with self.assertRaisesRegex(SystemExit, "terminal outcome requires null selection"):
            acceptance.validate_search_outcome(terminal, "wall.example")

    def test_search_selection_states_are_exhaustive(self) -> None:
        selected = copy.deepcopy(
            next(
                row["search"]
                for row in self.rows
                if row["search"]["selected_product"] is not None
            )
        )
        selected["selection"] = "selected"
        empty = copy.deepcopy(
            next(
                row["search"]
                for row in self.rows
                if row["search"]["kind"] == "search"
                and row["search"]["candidate_count"] == 0
            )
        )
        empty["selection"] = "empty"
        ineligible = copy.deepcopy(selected)
        ineligible.update(
            selection="no_eligible_candidate",
            selected_index=None,
            selected_product=None,
            item_ref_sha256=None,
        )

        acceptance.validate_search_outcome(selected, "selected.example")
        acceptance.validate_search_outcome(empty, "empty.example")
        acceptance.validate_search_outcome(ineligible, "ineligible.example")

        impossible = [
            {**empty, "selection": "no_eligible_candidate"},
            {**ineligible, "selection": "empty"},
            {**ineligible, "selection": "selected"},
            {**selected, "selected_index": selected["candidate_count"]},
            {**selected, "platform": "unknown-platform"},
            {**selected, "source": "unknown-source"},
        ]
        for search in impossible:
            with self.subTest(search=search), self.assertRaises(SystemExit):
                acceptance.validate_search_outcome(search, "invalid.example")

    def test_search_only_terminal_states_are_closed(self) -> None:
        not_run = copy.deepcopy(
            next(row["search"] for row in self.rows if row["search"]["kind"] == "not_run")
        )
        not_run["selection"] = None
        not_run["reason"] = "some_other_reason"
        quote_only = {
            "kind": "unsupported_product_configuration",
            "operation": "search",
            "platform": "shopify",
            "source": "storefront_graphql",
            "candidate_count": None,
            "selection": None,
            "selected_index": None,
            "selected_product": None,
            "item_ref_sha256": None,
            "reason": "configuration required",
            "browser_required": True,
            "fields": ["choice"],
        }
        invalid_detection_error = {
            "kind": "tool_error",
            "stage": "detection",
            "platform": "shopify",
            "source": "storefront_graphql",
            "candidate_count": None,
            "selection": None,
            "selected_index": None,
            "selected_product": None,
            "item_ref_sha256": None,
            "message": "failed",
        }

        for terminal in (not_run, quote_only, invalid_detection_error):
            with self.subTest(terminal=terminal), self.assertRaises(SystemExit):
                acceptance.validate_search_outcome(terminal, "terminal.example")

    def test_selected_product_values_are_strict_and_finite(self) -> None:
        selected = copy.deepcopy(
            next(
                row["search"]
                for row in self.rows
                if row["search"]["selected_product"] is not None
            )
        )
        selected["selection"] = "selected"
        acceptance.validate_search_outcome(selected, "valid.example")

        invalid_products = [
            {**selected["selected_product"], "variant": 1},
            {**selected["selected_product"], "available": 1},
            {
                **selected["selected_product"],
                "price": {"amount": "NaN", "currency": "USD"},
            },
            {
                **selected["selected_product"],
                "weight": {"value": True, "unit": "lb"},
            },
            {
                **selected["selected_product"],
                "weight": {"value": 10**400, "unit": "lb"},
            },
            {**selected["selected_product"], "product_url": "http://store.example/p"},
            {**selected["selected_product"], "unknown": "unsafe"},
        ]
        for product in invalid_products:
            changed = {**selected, "selected_product": product}
            with self.subTest(product=product), self.assertRaises(SystemExit):
                acceptance.validate_search_outcome(changed, "invalid.example")

        sfcc = copy.deepcopy(
            next(
                row["search"]
                for row in self.rows
                if row["expected_platform"] == "sfcc"
                and row["search"]["selected_product"]["name"] is None
            )
        )
        sfcc["selection"] = "selected"
        acceptance.validate_search_outcome(sfcc, "sfcc.example")

    def test_search_platform_must_match_positive_detection(self) -> None:
        row = copy.deepcopy(self.rows[0])
        row["search"]["selection"] = "selected"
        row["search"]["platform"] = "woocommerce"
        row["search"]["source"] = "wc_store_api"

        with self.assertRaisesRegex(SystemExit, "differs from detection"):
            acceptance.validate_row_relationships(row)

    def test_saved_discriminants_fail_closed(self) -> None:
        with self.assertRaisesRegex(SystemExit, "unsafe keys"):
            acceptance.validate_search_outcome({"kind": []}, "search.example")
        with self.assertRaisesRegex(SystemExit, "detection has unsafe keys"):
            acceptance.validate_detection({"kind": []}, "detection.example")

    def test_candidate_selection_generates_all_three_states(self) -> None:
        class PlatformApi:
            @staticmethod
            def _candidate(item: dict[str, object]) -> str | None:
                return "eligible-reference" if item["eligible"] else None

        product = {
            "name": "Widget",
            "variant": None,
            "sku": None,
            "barcode": None,
            "product_url": "https://store.example/widget",
            "eligible": True,
        }
        def identity(value: str) -> str:
            return value

        self.assertEqual(
            acceptance.select_candidate(PlatformApi, [], identity),
            ("empty", None, None, None),
        )
        self.assertEqual(
            acceptance.select_candidate(
                PlatformApi, [{**product, "eligible": False}], identity
            ),
            ("no_eligible_candidate", None, None, None),
        )
        selection, index, selected, reference_hash = acceptance.select_candidate(
            PlatformApi,
            [{**product, "eligible": False}, product],
            identity,
        )
        self.assertEqual((selection, index), ("selected", 1))
        self.assertEqual(selected["name"], "Widget")
        self.assertRegex(reference_hash, r"^[0-9a-f]{64}$")

    def test_source_hash_binds_runner_and_policy_but_not_corpus_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "scripts"
            shutil.copytree(acceptance.SCRIPT_DIR, source)
            baseline = acceptance.source_tree_hash(source)

            for relative in ("platform_search_acceptance.py", "read_only_http.py"):
                changed = source / relative
                original = changed.read_text()
                changed.write_text(original + "\n# source-bound change\n")
                self.assertNotEqual(acceptance.source_tree_hash(source), baseline)
                changed.write_text(original)

            corpus_contract = source / "platform_search_corpus_contract.py"
            original = corpus_contract.read_text()
            corpus_contract.write_text(original + "\n# excluded digest change\n")
            self.assertEqual(acceptance.source_tree_hash(source), baseline)

    def test_report_exposes_selection_discriminant_and_disposition_digest(self) -> None:
        rows = copy.deepcopy(self.rows)
        for row in rows:
            search = row["search"]
            if search["kind"] != "search":
                search["selection"] = None
            elif search["candidate_count"] == 0:
                search["selection"] = "empty"
            elif search["selected_product"] is None:
                search["selection"] = "no_eligible_candidate"
            else:
                search["selection"] = "selected"
        rendered = acceptance.report(rows, acceptance.summarize(rows))

        self.assertIn("| Selection |", rendered)
        self.assertIn("no_eligible_candidate", rendered)
        self.assertIn(acceptance.disposition_sha256(rows), rendered)

    def test_validator_rejects_count_uniqueness_and_identity_changes(self) -> None:
        cases = []

        missing = copy.deepcopy(self.rows[:-1])
        cases.append((missing, "exactly 59"))

        duplicate = copy.deepcopy(self.rows)
        duplicate[1] = copy.deepcopy(duplicate[0])
        cases.append((duplicate, "match input order"))

        wrong_group = copy.deepcopy(self.rows)
        wrong_group[0]["expected_group"] = "WooCommerce"
        cases.append((wrong_group, "group counts"))

        for rows, message in cases:
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(SystemExit, message),
            ):
                self.validate(rows)

    def test_validator_rejects_unsafe_or_unjoined_evidence(self) -> None:
        cases = []

        unsafe_key = copy.deepcopy(self.rows)
        unsafe_key[0]["body"] = "raw response"
        cases.append((unsafe_key, "unsafe or missing keys"))

        raw_headers = copy.deepcopy(self.rows)
        raw_headers[0]["http_evidence"][0]["headers"] = {"Cookie": "secret"}
        cases.append((raw_headers, "HTTP evidence has unsafe keys"))

        raw_signature = copy.deepcopy(self.rows)
        raw_signature[0]["search"]["selected_product"]["signature"] = "secret"
        cases.append((raw_signature, "selected product has invalid fields"))

        raw_reference = copy.deepcopy(self.rows)
        raw_reference[0]["detection"]["evidence"].append("item-v1.secret")
        cases.append((raw_reference, "raw item reference"))

        raw_token = copy.deepcopy(self.rows)
        ecwid_request = next(
            request
            for row in raw_token
            for request in row["http_evidence"]
            if request["operation_kind"] == "ecwid_products"
        )
        url = urlsplit(ecwid_request["requested_url"])
        query = parse_qsl(url.query, keep_blank_values=True)
        self.assertEqual(
            query,
            [("token", "[redacted]"), ("keyword", "a"), ("limit", "10")],
        )
        raw_query = [
            (name, "secret" if name == "token" else value)
            for name, value in query
        ]
        raw_url = urlunsplit(
            (url.scheme, url.netloc, url.path, urlencode(raw_query), "")
        )
        ecwid_request["requested_url"] = raw_url
        ecwid_request["final_url"] = raw_url
        cases.append((raw_token, "Ecwid products route is invalid"))

        raw_cart = copy.deepcopy(self.rows)
        raw_cart[0]["http_evidence"][0]["final_url"] += "/guest-carts/secret"
        cases.append((raw_cart, "GET evidence must represent one transport hop"))

        mutation = copy.deepcopy(self.rows)
        mutation[0]["http_evidence"][0]["requested_url"] = (
            "https://shop.example/api/storefront/carts"
        )
        mutation[0]["http_evidence"][0]["final_url"] = (
            "https://shop.example/api/storefront/carts"
        )
        cases.append((mutation, "storefront entry differs from row input"))

        for field in ("status", "bytes", "elapsed_ms"):
            boolean_number = copy.deepcopy(self.rows)
            boolean_number[0]["http_evidence"][0][field] = True
            cases.append((boolean_number, "HTTP evidence has invalid fields"))

        for field in ("bytes", "elapsed_ms"):
            negative_metric = copy.deepcopy(self.rows)
            negative_metric[0]["http_evidence"][0][field] = -1
            cases.append((negative_metric, "HTTP evidence has invalid fields"))

        boolean_candidate_count = copy.deepcopy(self.rows)
        boolean_candidate_count[0]["search"]["candidate_count"] = True
        cases.append((boolean_candidate_count, "search outcome has invalid fields"))

        boolean_selected_index = copy.deepcopy(self.rows)
        boolean_selected_index[0]["search"]["selected_index"] = True
        cases.append((boolean_selected_index, "selected search index is out of range"))

        boolean_terminal_status = copy.deepcopy(self.rows)
        terminal = next(
            row
            for row in boolean_terminal_status
            if row["search"]["kind"] == "not_run"
        )
        terminal["search"] = {
            "kind": "bot_wall",
            "operation": "search",
            "platform": "bigcommerce",
            "source": "html_search_and_product_pages",
            "candidate_count": None,
            "selection": None,
            "selected_index": None,
            "selected_product": None,
            "item_ref_sha256": None,
            "reason": "challenge",
            "system": "cloudflare",
            "status": True,
        }
        cases.append((boolean_terminal_status, "terminal outcome has invalid status"))

        boolean_detection_status = copy.deepcopy(self.rows)
        boolean_detection_status[0]["detection"] = {
            "kind": "bot_wall",
            "origin": "https://www.dernord.com",
            "system": "cloudflare",
            "status": True,
            "evidence": ["challenge"],
        }
        cases.append((boolean_detection_status, "detection has invalid fields"))

        unjoined = copy.deepcopy(self.rows)
        unjoined[0]["shipping_cache_domain"] = "missing.example"
        cases.append((unjoined, "learned-cache join"))

        for rows, message in cases:
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(SystemExit, message),
            ):
                self.validate(rows)

    def test_validator_rejects_source_hash_and_tool_errors(self) -> None:
        inconsistent_hash = copy.deepcopy(self.rows)
        inconsistent_hash[0]["source_tree_sha256"] = "0" * 64
        with self.assertRaisesRegex(SystemExit, "one valid source-tree SHA-256"):
            self.validate(inconsistent_hash)

        stale_hash = copy.deepcopy(self.rows)
        for row in stale_hash:
            row["source_tree_sha256"] = "0" * 64
        with self.assertRaisesRegex(SystemExit, "current production source"):
            self.validate(stale_hash)

        changed_outcome = copy.deepcopy(self.rows)
        changed_outcome[0]["search"] = {
            "kind": "tool_error",
            "stage": "search",
            "platform": "shopify",
            "source": "storefront_graphql",
            "candidate_count": None,
            "selection": None,
            "selected_index": None,
            "selected_product": None,
            "item_ref_sha256": None,
            "message": "synthetic error",
        }
        with self.assertRaisesRegex(SystemExit, "tool error"):
            self.validate(changed_outcome)


if __name__ == "__main__":
    unittest.main()
