#!/usr/bin/env python3
"""Fail a CI run whose desktop e2e runners skipped a test they should not have.

    python scripts/ci_check_split.py <downloaded ci-inputs-* artifacts dir>

The e2e suite is split between the utk GPU runner and the CPU runners
(utk_curio/backend/tests/test_frontend/runner_split.py). That every test is
collected on exactly one side is a unit test; what only a run can show is a
test that went to a CPU runner and then skipped because it needed what only
utk has -- hardware WebGPU, or the sibling backends of --parallel. Such a test
passes nowhere and would sit in the green run as one more skip.

Exits 1, naming each one, if any desktop part skipped a test for one of those
reasons.
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

#: What a skip message says when the test wanted the GPU runner.
UTK_ONLY = re.compile(r"webgpu|gpu adapter|\badapter\b|hardware gpu|needs --parallel", re.IGNORECASE)


def desktop_skips(root: Path):
    """(part, test id, message) for every skipped desktop e2e test."""
    for junit in sorted(root.glob("ci-inputs-e2e-desktop-*/e2e.xml")):
        part = junit.parent.name.rsplit("-", 1)[-1]
        for case in ET.parse(junit).getroot().iter("testcase"):
            skipped = case.find("skipped")
            if skipped is not None:
                test = f"{case.get('classname')}::{case.get('name')}"
                yield part, test, skipped.get("message") or skipped.text or ""


def main(argv) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    root = Path(argv[0])
    parts = sorted(root.glob("ci-inputs-e2e-desktop-*/e2e.xml"))
    if not parts:
        print("no desktop e2e results to check")
        return 0
    wrong = [(p, t, m) for p, t, m in desktop_skips(root) if UTK_ONLY.search(m)]
    for part, test, message in wrong:
        print(f"::error::desktop part {part} skipped {test}, which needs the GPU runner: "
              f"{message.strip()[:200]}")
    if wrong:
        print(f"{len(wrong)} test(s) ran nowhere: classify them for utk "
              "(runner_split.py) or mark them needs_parallel.")
        return 1
    print(f"OK: {len(parts)} desktop parts, no test skipped for want of the GPU runner")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
