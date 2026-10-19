#!/usr/bin/env python3
"""Record how long each e2e test takes, for balancing the CI parts.

    python scripts/e2e_durations.py <e2e JUnit> [<e2e JUnit> ...]

Reads the e2e JUnit of a CI run (``e2e.xml`` in the ``ci-inputs-test-gpu`` and
``ci-inputs-e2e-desktop-*`` artifacts; pass every one, and no other job's) and
writes ``utk_curio/backend/tests/test_frontend/e2e_durations.json``: seconds
per test, keyed by its JUnit classname and name without the GPU runner's
``@<group>`` suffix (``parts.case_key``, which also names a collected item, so
the split prices each test by the key written here). A part's group costs the
sum of its tests (``runner_split.part_key``). A test seen in several files
keeps its longest time. A repeated suite's later runs (``e2e.run2.xml``, ...)
are left out.

Rerun it when the parts drift out of balance (the CI report's spread lines).
Nothing breaks when it is stale: a test missing from the file is priced at
the median recorded test.
"""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from utk_curio.backend.tests.parts import case_key  # noqa: E402

OUT = REPO / "utk_curio" / "backend" / "tests" / "test_frontend" / "e2e_durations.json"

#: A later run of a repeated suite (scripts/ci_repeat.sh).
REPEAT_RUN = re.compile(r"\.run\d+$")


def main(argv) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    seconds: dict[str, float] = {}
    for junit in argv:
        if REPEAT_RUN.search(Path(junit).stem):
            continue
        per_file: dict[str, float] = {}
        for case in ET.parse(junit).iter("testcase"):
            key = case_key(case.get("classname", ""), case.get("name", ""))
            per_file[key] = per_file.get(key, 0.0) + float(case.get("time") or 0)
        for key, value in per_file.items():
            seconds[key] = max(seconds.get(key, 0.0), value)
    OUT.write_text(json.dumps({k: round(v, 1) for k, v in sorted(seconds.items())},
                              indent=1) + "\n")
    print(f"wrote {OUT} ({len(seconds)} tests, {sum(seconds.values()) / 60:.1f} min)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
