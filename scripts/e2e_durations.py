#!/usr/bin/env python3
"""Record how long each e2e group takes, for balancing the CI shards.

    python scripts/e2e_durations.py <allure-report dir> [<allure-report dir> ...]

Reads the ``allure-report`` artifact(s) of CI runs and writes
``utk_curio/backend/tests/test_frontend/e2e_durations.json``: seconds per group,
where a group is what ``runner_split.group_of`` puts together (one workflow of
``test_workflows``, one walkthrough scene, otherwise one module). Pass the
reports of every runner that ran part of the suite; a group seen twice keeps
its longest time.

Rerun it when the shards drift out of balance. Nothing breaks when it is
stale: a group missing from the file is priced at a default.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

OUT = (Path(__file__).resolve().parents[1] / "utk_curio" / "backend" / "tests"
       / "test_frontend" / "e2e_durations.json")


def group_of(case: dict) -> str | None:
    labels = {label["name"]: label["value"] for label in case.get("labels", [])}
    module = labels.get("suite") or ""
    if module == "test_workflows":
        for param in case.get("parameters", []):
            if param.get("name") == "loaded_workflow":
                return "wf-" + Path(param["value"].strip("'\"")).name
    if module == "test_walkthrough_baselines":
        for param in case.get("parameters", []):
            match = re.search(r"slug='([^']+)'", param.get("value", ""))
            if param.get("name") == "walk" and match:
                return "walk-" + match.group(1)
    return module or None


def main(argv) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    seconds: dict[str, float] = {}
    for report in argv:
        per_run: dict[str, float] = {}
        for path in Path(report, "data", "test-cases").glob("*.json"):
            case = json.loads(path.read_text())
            group = group_of(case)
            if not group:
                continue
            timing = case.get("time", {})
            per_run[group] = per_run.get(group, 0.0) + (
                (timing.get("stop", 0) - timing.get("start", 0)) / 1000.0
            )
        for group, value in per_run.items():
            seconds[group] = max(seconds.get(group, 0.0), value)
    OUT.write_text(json.dumps({k: round(v, 1) for k, v in sorted(seconds.items())},
                              indent=1) + "\n")
    print(f"wrote {OUT} ({len(seconds)} groups, {sum(seconds.values()) / 60:.1f} min)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
