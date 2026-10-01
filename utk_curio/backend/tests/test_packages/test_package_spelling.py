"""No name or reference spells "package" with a second ``age`` (#488).

Fifty-five package functions once carried that misspelling. Every caller
agreed, so nothing failed, and a branch cut before the rename can bring the
old names back on merge without any other test noticing. The scan covers the
trees the test image holds: ``utk_curio/``, ``packages/`` and ``scripts/``.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
ROOTS = ("utk_curio", "packages", "scripts")
SKIP_DIRS = {"node_modules", "dist", "__pycache__", ".git"}
# Built from parts so this file does not match itself.
MISSPELLING = ("package" + "age").encode()


def _offenders() -> list[str]:
    found = []
    for root in ROOTS:
        for dirpath, dirnames, filenames in os.walk(REPO_ROOT / root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for filename in filenames:
                path = Path(dirpath) / filename
                if path.is_file() and MISSPELLING in path.read_bytes().lower():
                    found.append(path.relative_to(REPO_ROOT).as_posix())
    return sorted(found)


def test_package_is_never_misspelled():
    # Guards the walk itself: a wrong root would make the scan a vacuous pass.
    missing = [root for root in ROOTS if not (REPO_ROOT / root).is_dir()]
    assert not missing, f"scan roots missing under {REPO_ROOT}: {missing}"

    offenders = _offenders()
    assert not offenders, f"misspelled 'package' in: {offenders}"
