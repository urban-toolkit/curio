"""The dataflows Curio ships, and where each came from.

Two folders ship: ``docs/examples/*.json`` (the numbered examples) and
``docs/examples/dataflows/*.json`` (the e2e fixtures, seeded as tests so the
deploy shows them too), found through ``utk_curio/shipped.py``. Beside the
numbered examples, ``use-cases.json`` names the ones that are use cases, by
key; it is not a dataflow. Kept free of app imports because the launcher's
package walk (``packages/seed.py``) reads it before any app exists.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from utk_curio import shipped

#: The index beside the numbered examples that names the use cases among them:
#: ``{"useCases": [<key>, ...]}``. Every other numbered file is an example.
USE_CASE_INDEX = "use-cases.json"

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
    return shipped.path("docs/examples")


def use_case_keys(root: Optional[Path] = None) -> frozenset[str]:
    """The keys the use-case index in *root* (the shipped examples' folder by
    default) names; none when it has no index, or one that does not read."""
    root = root or examples_dir()
    try:
        raw = json.loads((root / USE_CASE_INDEX).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    keys = raw.get("useCases") if isinstance(raw, dict) else None
    return frozenset(key for key in keys if isinstance(key, str)) if isinstance(keys, list) else frozenset()


def shipped_dataflows(root: Optional[Path] = None) -> list[ShippedDataflow]:
    """Every dataflow Curio seeds: the numbered examples, then the tests.

    The one list the project, dataset and package seeders all walk, so none of
    them can disagree about what ships. Numbered files come first so their
    accent colours stay what they were before the tests joined. A numbered
    file's source comes from its key: a use case when the use-case index
    names it, else an example.
    """
    root = root or examples_dir()
    if not root.is_dir():
        return []
    use_cases = use_case_keys(root)
    shipped = [
        ShippedDataflow(
            key=p.stem,
            path=p,
            source=SOURCE_USE_CASE if p.stem in use_cases else SOURCE_EXAMPLE,
        )
        for p in sorted(root.glob("*.json"))
        if p.is_file() and p.name != USE_CASE_INDEX
    ]
    tests_dir = root / TESTS_SUBDIR
    if tests_dir.is_dir():
        shipped += [
            ShippedDataflow(key=f"{TESTS_SUBDIR}/{p.stem}", path=p, source=SOURCE_TEST)
            for p in sorted(tests_dir.glob("*.json"))
            if p.is_file()
        ]
    return shipped
