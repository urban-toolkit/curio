"""A scenario's levers, fixed context and outcomes, read from a saved spec
(#662), and the nodes whose saved outputs stand for a node's.

One table of cases, ``scenarioParts.cases.json``, is read here and by Jest
(``src/tests/utils/scenarioParts.cases.test.ts``), which reads it through the
canvas's ``scenarioParts``: the catalog lists a scenario as its canvas shows it.

The catalog module is imported inside the test, so a before-run fails here and
not the whole collection.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
CASES = REPO_ROOT / "utk_curio" / "frontend" / "urban-workflows" / "src" / "utils" / "scenarios" / "scenarioParts.cases.json"


def test_the_catalog_reads_a_scenario_as_its_canvas_does():
    from utk_curio.backend.app.scenario_catalog.domain.parts import saved_sources, scenario_parts

    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    assert cases
    mismatches = []
    for case in cases:
        scenario = {"id": "s1", "name": "Baseline", "color": "#2a9d8f", "nodes": case["scenario"]}
        got = scenario_parts(scenario, case["nodes"], case["edges"])
        if got != case["expected"]:
            mismatches.append(f"{case['name']}: read {got!r}, the table says {case['expected']!r}")
        for node_id, expected in (case.get("savedSources") or {}).items():
            sources = saved_sources(node_id, case["nodes"], case["edges"])
            if sources != expected:
                mismatches.append(f"{case['name']}: {node_id} stands for {sources!r}, the table says {expected!r}")
    assert not mismatches, "\n".join(mismatches)
