#!/usr/bin/env python3
"""Write each shipped dataflow's scenario sets into it.

Every scenario of a committed dataflow names its set and keeps its context
and outcomes (``dataflow.scenarioSets``, ``projects/scenario_sets.py``). This
fills them in the way a save does, the context and outcomes inferred along
the edges, and names each file's set; a dataflow already holding them is
written as it is. ``--check`` writes nothing and fails when a file would
change.

    python scripts/migrate_scenario_sets.py [--check]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from utk_curio.backend.app.projects.scenarios import normalize_spec_scenarios  # noqa: E402

#: The shipped dataflows with scenarios, and the name of their one set. A
#: file with several comparisons (no name here) keeps the names its sets are
#: grouped with: its scenarios' names, joined.
SET_NAMES = {
    "docs/examples/06-back-bay-road-sunlight.json": "Back Bay road sunlight",
    "docs/examples/dataflows/quad-cities-flood-vulnerability.json": "Nature-based solutions",
    "docs/examples/dataflows/chicago-rain-wind-routing.json": "Routing around rain and wind",
    "docs/examples/dataflows/scenario-comparison-charts.json": None,
    "docs/examples/dataflows/lower-manhattan-park-shade.json": "Lower Manhattan park shade",
    "docs/examples/dataflows/chicago-loop-shadow-towers.json": "Chicago Loop shadow",
    "docs/examples/dataflows/crown-heights-1550-bedford-shadow.json": "1550 Bedford Avenue shade",
    "docs/examples/dataflows/scenarios.json": "Building heights",
}


def with_sets(spec: dict, name: str | None = None) -> dict:
    """*spec* with its scenarios in sets, each with its context and outcomes;
    a lone set new to it is called *name* when given."""
    had = {s.get("id") for s in spec.get("dataflow", {}).get("scenarioSets") or []}
    normalize_spec_scenarios(spec)
    sets = spec.get("dataflow", {}).get("scenarioSets") or []
    if name and len(sets) == 1 and sets[0]["id"] not in had:
        sets[0]["name"] = name
    return spec


def dumped(spec: dict) -> str:
    return json.dumps(spec, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="write nothing; fail when a file would change")
    args = parser.parse_args(argv)
    stale = []
    for rel, name in SET_NAMES.items():
        path = REPO / rel
        before = path.read_text(encoding="utf-8")
        after = dumped(with_sets(json.loads(before), name))
        if after == before:
            continue
        stale.append(rel)
        if not args.check:
            path.write_text(after, encoding="utf-8")
            print(f"wrote {rel}")
    if args.check and stale:
        print("scenario sets missing or stale in: " + ", ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
