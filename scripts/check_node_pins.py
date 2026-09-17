#!/usr/bin/env python3
"""Fail when the Node.js major is declared inconsistently across the repo.

``NODE_MAJOR`` in ``utk_curio/main.py`` gates the launcher, ``.nvmrc`` and
``.node-version`` drive nvm/fnm/asdf, the two ``package.json`` ``engines``
fields are what npm warns on, and the Dockerfile installs what the image ships.
Nothing links them but a comment, so a bump that misses one leaves contributors
on a Node the launcher then refuses.

Lives here rather than only in the test suite because the suite runs inside the
container image, which carries ``utk_curio/`` and none of the files above. CI
runs this on the checkout instead, where there is something to check.

Usage::

    python scripts/check_node_pins.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def disagreements(root: Path = REPO_ROOT) -> list[str]:
    """Every declaration that does not match NODE_MAJOR, one readable line each."""
    sys.path.insert(0, str(root))
    from utk_curio.main import NODE_MAJOR

    found: list[str] = []

    for name in (".nvmrc", ".node-version"):
        declared = (root / name).read_text(encoding="utf-8").strip()
        if declared != str(NODE_MAJOR):
            found.append(f"{name} pins {declared}, NODE_MAJOR is {NODE_MAJOR}")

    frontend = root / "utk_curio" / "frontend" / "urban-workflows"
    for pkg in (root / "package.json", frontend / "package.json"):
        engines = json.loads(pkg.read_text(encoding="utf-8")).get("engines", {})
        if engines.get("node") != f"^{NODE_MAJOR}":
            found.append(
                f"{pkg.relative_to(root)} engines.node is {engines.get('node')!r}, "
                f"expected '^{NODE_MAJOR}'"
            )

    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    for needle in (f"setup_{NODE_MAJOR}.x", f"node:{NODE_MAJOR}-"):
        if needle not in dockerfile:
            found.append(f"Dockerfile never mentions {needle}")

    return found


def main() -> int:
    found = disagreements()
    if found:
        print("Node.js version declarations disagree:", file=sys.stderr)
        for line in found:
            print(f"  - {line}", file=sys.stderr)
        print(
            "Update them together, or change NODE_MAJOR in utk_curio/main.py.",
            file=sys.stderr,
        )
        return 1
    print("Node.js version declarations agree.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
