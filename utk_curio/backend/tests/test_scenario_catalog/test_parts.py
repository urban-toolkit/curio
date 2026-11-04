"""A scenario's parts by role, read from a saved spec (#662): its own nodes,
its shared context and shared outcomes, its boundary, what saves its output
because of the scenarios, and the nodes whose saved outputs stand for a node's.

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


def _scenarios(case: dict) -> list[dict]:
    return [{"name": s["id"], "color": "#2a9d8f", **s} for s in case["scenarios"]]


def test_the_catalog_reads_a_scenario_as_its_canvas_does():
    from utk_curio.backend.app.scenario_catalog.domain.parts import (
        saved_sources,
        scenario_parts,
        scenario_source_node_ids,
    )

    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    assert cases
    mismatches = []
    for case in cases:
        scenarios = _scenarios(case)
        for scenario in scenarios:
            got = scenario_parts(scenario, case["nodes"], case["edges"], scenarios)
            if got != case["expected"][scenario["id"]]:
                mismatches.append(
                    f"{case['name']}: {scenario['id']} read {got!r}, the table says {case['expected'][scenario['id']]!r}"
                )
        spec = {"dataflow": {"name": case["name"], "nodes": case["nodes"], "edges": case["edges"], "scenarios": scenarios}}
        saves = sorted(scenario_source_node_ids(spec))
        if saves != case["saves"]:
            mismatches.append(f"{case['name']}: the scenarios save {saves!r}, the table says {case['saves']!r}")
        for node_id, expected in (case.get("savedSources") or {}).items():
            sources = saved_sources(node_id, case["nodes"], case["edges"])
            if sources != expected:
                mismatches.append(f"{case['name']}: {node_id} stands for {sources!r}, the table says {expected!r}")
    assert not mismatches, "\n".join(mismatches)
