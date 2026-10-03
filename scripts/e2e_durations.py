#!/usr/bin/env python3
"""Record how long each e2e group takes, for balancing the CI shards.

    python scripts/e2e_durations.py <e2e JUnit> [<e2e JUnit> ...]

Reads the e2e JUnit of CI runs (``e2e.xml`` in the ``ci-inputs-test-gpu`` and
``ci-inputs-e2e-desktop-*`` artifacts; pass every one) and writes
``utk_curio/backend/tests/test_frontend/e2e_durations.json``: seconds per group,
where a group is what ``runner_split.group_of`` puts together (one workflow of
``test_workflows``, one walkthrough scene, otherwise one module). A group seen
in several files keeps its longest time.

Rerun it when the shards drift out of balance. Nothing breaks when it is
stale: a group missing from the file is priced at a default.
"""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

OUT = (Path(__file__).resolve().parents[1] / "utk_curio" / "backend" / "tests"
       / "test_frontend" / "e2e_durations.json")


def group_of(classname: str, name: str) -> str | None:
    """The xdist group of one JUnit test case.

    A run under ``--dist loadgroup`` (the GPU runner) appends it to the name
    (``test_x[...]@wf-Vega.json``); a run without workers does not, so it is
    rebuilt from the module and the parameter id the way conftest assigns it.
    """
    if "@" in name:
        return name.rsplit("@", 1)[1]
    module = [part for part in classname.split(".") if not part[:1].isupper()][-1:]
    module = module[0] if module else ""
    param = re.search(r"\[(.*)\]$", name)
    param = param.group(1) if param else ""
    if module == "test_workflows" and param:
        return "wf-" + Path(re.sub(r"-chromium$", "", param)).name
    if module == "test_walkthrough_baselines" and param:
        return "walk-" + re.sub(r"^chromium-", "", param)
    return module or None


def main(argv) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    seconds: dict[str, float] = {}
    for junit in argv:
        per_file: dict[str, float] = {}
        for case in ET.parse(junit).iter("testcase"):
            group = group_of(case.get("classname", ""), case.get("name", ""))
            if group:
                per_file[group] = per_file.get(group, 0.0) + float(case.get("time") or 0)
        for group, value in per_file.items():
            seconds[group] = max(seconds.get(group, 0.0), value)
    OUT.write_text(json.dumps({k: round(v, 1) for k, v in sorted(seconds.items())},
                              indent=1) + "\n")
    print(f"wrote {OUT} ({len(seconds)} groups, {sum(seconds.values()) / 60:.1f} min)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
