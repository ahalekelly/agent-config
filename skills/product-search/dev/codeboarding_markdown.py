"""Generate CodeBoarding markdown docs from .codeboarding/analysis.json.

The codeboarding CLI writes analysis.json but exposes no markdown command; this
script drives its bundled output_generators to produce on_boarding.md plus one
file per expanded component. Refresh after a codeboarding run:

    ~/.local/share/uv/tools/codeboarding/bin/python dev/codeboarding_markdown.py .codeboarding

Must run with the codeboarding tool venv's python (imports its packages).
"""
import json
import sys
from pathlib import Path

from agents.agent_responses import AnalysisInsights
from output_generators.markdown import generate_markdown_file
from utils import sanitize

out_dir = Path(sys.argv[1]).resolve()
data = json.loads((out_dir / "analysis.json").read_text())
project = data["metadata"]["repo_name"]


def prune(node: dict) -> dict:
    """analysis.json compacts some model fields to strings; keep only what renders."""
    # Relations reference components from any nesting level; project each endpoint
    # onto its ancestor among this node's direct children, then dedupe.
    ancestor: dict[str, str] = {}

    def cover(comp: dict, top: str) -> None:
        ancestor[comp["name"]] = top
        for sub in comp.get("components") or []:
            cover(sub, top)

    for c in node["components"]:
        cover(c, c["name"])

    relations, seen = [], set()
    for r in node["components_relations"]:
        src, dst = ancestor.get(r["src_name"]), ancestor.get(r["dst_name"])
        if src and dst and src != dst and (src, dst) not in seen:
            seen.add((src, dst))
            relations.append({"src_name": src, "dst_name": dst, "relation": r["relation"]})
    return {
        "description": node["description"],
        "components": [
            {k: c[k] for k in ("name", "description", "key_entities", "component_id") if k in c}
            for c in node["components"]
        ],
        "components_relations": relations,
    }


def emit(node: dict, file_name: str) -> None:
    expanded = {c["component_id"] for c in node["components"] if c.get("components")}
    insights = AnalysisInsights.model_validate(prune(node))
    generate_markdown_file(
        file_name, insights, project=project, repo_ref=".",
        expanded_components=expanded, temp_dir=out_dir,
    )
    for comp in node["components"]:
        if comp.get("components"):
            emit(comp, sanitize(comp["name"]))


emit(data, "on_boarding")
print("wrote:", *sorted(p.name for p in out_dir.glob("*.md")))
