from __future__ import annotations

import hashlib
import json
from typing import Any

EXPECTED_DISPOSITION_SHA256 = (
    "d19ffd2b33185417116488bd32abb5e8d1caa8dba802255740f4717deef8c496"
)


def disposition_sha256(rows: list[dict[str, Any]]) -> str:
    projection = [
        {
            "domain": row["domain"],
            "kind": row["search"]["kind"],
            "candidate_count": row["search"]["candidate_count"],
            "selection": row["search"]["selection"],
            "selected_index": row["search"]["selected_index"],
            "selected_product": row["search"]["selected_product"],
            "item_ref_sha256": row["search"]["item_ref_sha256"],
        }
        for row in sorted(rows, key=lambda row: row["domain"])
    ]
    canonical = json.dumps(projection, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
