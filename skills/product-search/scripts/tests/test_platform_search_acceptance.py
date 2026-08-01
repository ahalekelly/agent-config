# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "cryptography>=45,<47",
#   "httpx>=0.28,<0.29",
# ]
# ///

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import platform_search_acceptance as acceptance  # noqa: E402

EXPECTED_SOURCE_HASH = (
    "f812a3e3895a82d24c62e5ab39bc2c7851085971f753a10b5845ec2078cc5586"
)


class SavedCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.jobs = acceptance.load_jobs(acceptance.DEFAULT_INPUT)
        cls.rows = acceptance.load_rows(acceptance.DEFAULT_JSONL)
        cls.cache_domains = acceptance.learned_cache_domains(acceptance.DEFAULT_VENDORS)

    def validate(self, rows: list[dict[str, object]]) -> None:
        acceptance.validate_rows(rows, self.jobs, self.cache_domains)

    def test_saved_corpus_matches_input_and_production_source(self) -> None:
        self.validate(self.rows)
        summary = acceptance.summarize(self.rows)

        self.assertEqual(summary["row_count"], 59)
        self.assertEqual(summary["unique_domain_count"], 59)
        self.assertEqual(
            sum(group["successes"] for group in summary["groups"].values()), 47
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
        cases.append((raw_signature, "selected product has unsafe keys"))

        raw_reference = copy.deepcopy(self.rows)
        raw_reference[0]["detection"]["evidence"].append("item-v1.secret")
        cases.append((raw_reference, "raw item reference"))

        raw_token = copy.deepcopy(self.rows)
        raw_token[0]["http_evidence"][0]["requested_url"] += "?token=secret"
        cases.append((raw_token, "unredacted secret query value"))

        raw_cart = copy.deepcopy(self.rows)
        raw_cart[0]["http_evidence"][0]["final_url"] += "/guest-carts/secret"
        cases.append((raw_cart, "unredacted Magento cart path"))

        mutation = copy.deepcopy(self.rows)
        mutation[0]["http_evidence"][0]["requested_url"] = (
            "https://shop.example/api/storefront/carts"
        )
        mutation[0]["http_evidence"][0]["final_url"] = (
            "https://shop.example/api/storefront/carts"
        )
        cases.append((mutation, "mutating endpoint"))

        unjoined = copy.deepcopy(self.rows)
        unjoined[0]["shipping_cache_domain"] = "missing.example"
        cases.append((unjoined, "learned-cache join"))

        for rows, message in cases:
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(SystemExit, message),
            ):
                self.validate(rows)

    def test_validator_rejects_source_hash_and_terminal_changes(self) -> None:
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
            "selected_index": None,
            "selected_product": None,
            "item_ref_sha256": None,
            "message": "synthetic error",
        }
        with self.assertRaisesRegex(SystemExit, "search outcome counts"):
            self.validate(changed_outcome)

        changed_candidate_count = copy.deepcopy(self.rows)
        changed_candidate_count[0]["search"]["candidate_count"] += 1
        with self.assertRaisesRegex(SystemExit, "per-store search dispositions"):
            self.validate(changed_candidate_count)

        changed_terminal = copy.deepcopy(self.rows)
        valin = next(
            row for row in changed_terminal if row["domain"] == "valinonline.com"
        )
        valin["search"]["reason"] = "different challenge"
        with self.assertRaisesRegex(SystemExit, "terminal dispositions"):
            self.validate(changed_terminal)


if __name__ == "__main__":
    unittest.main()
