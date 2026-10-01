"""The dataflows Curio ships, and where each came from.

Two folders ship: ``docs/examples/*.json`` (the numbered examples, one of them
a use case) and ``docs/examples/dataflows/*.json`` (the e2e fixtures, seeded as
tests so the deploy shows them too). Kept free of app imports because the
launcher's package walk (``packages/seed.py``) reads it before any app exists.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

#: The numbered examples the guide's use-case section shows. Every other
#: numbered file is an example.
USE_CASES = frozenset({"09-heterogeneous-data-linked-views"})

#: Values of ``categories.source``; the rail labels them.
SOURCE_USE_CASE = "use_case"
SOURCE_EXAMPLE = "example"
SOURCE_TEST = "test"

TESTS_SUBDIR = "dataflows"


@dataclass(frozen=True)
class ShippedDataflow:
    #: What the project id is derived from. A numbered example's key is its
    #: stem, as it always was, so seeded ids do not move; a test's is
    #: ``dataflows/<stem>``.
    key: str
    path: Path
    source: str


def examples_dir() -> Path:
    # utk_curio/backend/app/projects/shipped.py -> repo root is 4 parents up
    return Path(__file__).resolve().parents[4] / "docs" / "examples"


def shipped_dataflows(root: Optional[Path] = None) -> list[ShippedDataflow]:
    """Every dataflow Curio seeds: the numbered examples, then the tests.

    The one list the project, dataset and package seeders all walk, so none of
    them can disagree about what ships. Numbered files come first so their
    accent colours stay what they were before the tests joined.
    """
    root = root or examples_dir()
    if not root.is_dir():
        return []
    shipped = [
        ShippedDataflow(
            key=p.stem,
            path=p,
            source=SOURCE_USE_CASE if p.stem in USE_CASES else SOURCE_EXAMPLE,
        )
        for p in sorted(root.glob("*.json"))
        if p.is_file()
    ]
    tests_dir = root / TESTS_SUBDIR
    if tests_dir.is_dir():
        shipped += [
            ShippedDataflow(key=f"{TESTS_SUBDIR}/{p.stem}", path=p, source=SOURCE_TEST)
            for p in sorted(tests_dir.glob("*.json"))
            if p.is_file()
        ]
    return shipped
