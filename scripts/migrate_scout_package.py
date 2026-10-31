#!/usr/bin/env python3
"""Write the Scout package's replacements into the shipped dataflows (#1270).

Scout's raster nodes are the Rasterization package's now
(``curio.rasterization/…``), and its charts are Vega-Lite nodes
(``curio.builtin/vis-vega``) that keep their spec, widgets and title. Each
shipped dataflow that holds one is rewritten as a save after loading it would write it
(``projects/legacy_node_types.migrate_legacy_types``), and its prompt
fixture's ``source.sha256`` follows. ``--check`` writes nothing and fails when
a file would change.

    python scripts/migrate_scout_package.py [--check]
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from utk_curio.backend.app.agents.evaluation.canonical import canonical_graph_from_spec  # noqa: E402
from utk_curio.backend.app.agents.evaluation.dependencies import (  # noqa: E402
    declared_dependencies,
    referenced_sources,
)
from utk_curio.backend.app.projects.legacy_node_types import current_node_type, migrate_legacy_types  # noqa: E402
from scripts.example_fixture_skeleton import template_index  # noqa: E402

EXAMPLES = REPO / "docs" / "examples"
PROMPTS = EXAMPLES / "prompts"


def dataflows() -> list[Path]:
    """Every shipped dataflow: the examples and the test dataflows."""
    return sorted(
        p for p in EXAMPLES.rglob("*.json")
        if PROMPTS not in p.parents and "expected_outputs" not in p.parts and "vega-lite-charts" not in p.parts
    )


def dumped(spec: dict) -> str:
    return json.dumps(spec, indent=2, ensure_ascii=False) + "\n"


def fixture_of(path: Path) -> Path:
    return PROMPTS / path.relative_to(EXAMPLES).with_suffix(".prompt.json")


def refreshed(fixture: dict, spec: dict, text: str) -> dict:
    """*fixture* following its example *spec*, written as *text*: its digest,
    the packages it requires, its expected graph (refs kept) and the
    browser-only kinds, each type as Curio ships it now."""
    templates = template_index()
    graph = canonical_graph_from_spec(spec, templates=templates, sources=referenced_sources(spec, templates=templates))
    fixture["source"]["sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    fixture["required"]["packages"] = declared_dependencies(spec).as_required_dict()["packages"]
    fixture["expected"] = graph.as_expected_dict(refs=[n["ref"] for n in fixture["expected"]["nodes"]])
    execution = fixture.get("execution") or {}
    if isinstance(execution.get("browserOnlyKinds"), list):
        kinds: list = []
        for kind in execution["browserOnlyKinds"]:
            if current_node_type(kind) not in kinds:
                kinds.append(current_node_type(kind))
        execution["browserOnlyKinds"] = sorted(kinds)
    return fixture


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="write nothing; fail when a file would change")
    args = parser.parse_args(argv)
    stale = []
    for path in dataflows():
        before = path.read_text(encoding="utf-8")
        spec = json.loads(before)
        if not isinstance(spec, dict) or "dataflow" not in spec:
            continue
        if migrate_legacy_types(copy.deepcopy(spec)) == spec:
            continue
        after = dumped(migrate_legacy_types(spec))
        rel = str(path.relative_to(REPO))
        stale.append(rel)
        if not args.check:
            path.write_text(after, encoding="utf-8")
            print(f"wrote {rel}")
        fixture = fixture_of(path)
        if not fixture.exists():
            continue
        stale.append(str(fixture.relative_to(REPO)))
        if not args.check:
            fixture.write_text(dumped(refreshed(json.loads(fixture.read_text(encoding="utf-8")), spec, after)), encoding="utf-8")
            print(f"wrote {fixture.relative_to(REPO)}")
    if args.check and stale:
        print("Scout types or fixture hashes stale in: " + ", ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
