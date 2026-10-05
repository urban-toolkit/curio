#!/usr/bin/env python3
"""Record how long each backend test file takes, for balancing the CI parts.

    python scripts/unit_durations.py <backend JUnit> [<backend JUnit> ...]

Reads the backend unit suite's JUnit (the ``ci-inputs-unit-backend-*``
artifacts of a CI run; pass every part) and writes
``utk_curio/backend/tests/unit_durations.json``: seconds per test file, keyed
the way ``conftest.unit_group_of`` names them (``test_agents.test_routes_solve``).

Rerun it when the parts drift out of balance. Nothing breaks when it is stale:
a file missing from it is priced at a default.
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

OUT = (Path(__file__).resolve().parents[1] / "utk_curio" / "backend" / "tests"
       / "unit_durations.json")


def group_of(classname: str) -> str:
    """``tests.test_agents.test_routes_solve.TestX`` -> ``test_agents.test_routes_solve``."""
    module = [part for part in classname.split(".") if not part[:1].isupper()]
    for prefix in (["utk_curio", "backend", "tests"], ["tests"]):
        if module[:len(prefix)] == prefix:
            module = module[len(prefix):]
            break
    return ".".join(module)


def main(argv) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    seconds: dict[str, float] = defaultdict(float)
    for path in argv:
        for case in ET.parse(path).getroot().iter("testcase"):
            group = group_of(case.get("classname", ""))
            if group:
                seconds[group] += float(case.get("time") or 0)
    OUT.write_text(json.dumps({k: round(v, 1) for k, v in sorted(seconds.items())},
                              indent=1) + "\n")
    print(f"wrote {OUT} ({len(seconds)} files, {sum(seconds.values()) / 60:.1f} min)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
