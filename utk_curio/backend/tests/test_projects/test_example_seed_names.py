"""Does the seeded examples gallery show the titles the example JSONs declare?

This is the direct reading of #148 - "some dataflows shown in the examples is
different than the ones in the json files". The structural drift was zero: node
and edge counts in the seeded copies always matched. What differed was the
*title*, on every single example.

``seed_example_projects`` derived the project name from the filename via
``_name_from_stem`` and then stamped it over the spec's own ``dataflow.name``,
justified by a comment claiming "the example JSONs don't carry a name field of
their own". All eleven do. So the gallery showed ``Vega lite chained
transforms`` where the JSON and docs/README.md both say ``Vega-Lite chained
transforms``, and - the worst case - ``Street vision cv analysis`` for the
example both other sources call ``Street-level computer vision``.

Unit-level on purpose: the name resolution is pure, so it needs neither a DB nor
a browser, and a failure here points straight at the resolver rather than at
seeding, storage, or the gallery's rendering.
"""
from __future__ import annotations

import glob
import json
import os

import pytest

from utk_curio.backend.app.projects.seed import (
    _name_from_spec,
    _name_from_stem,
    _repo_root,
)

EXAMPLES_DIR = os.path.join(str(_repo_root()), "docs", "examples")


def _example_paths() -> list[str]:
    return sorted(glob.glob(os.path.join(EXAMPLES_DIR, "[0-9][0-9]-*.json")))


def _stem(path: str) -> str:
    return os.path.basename(path)[:-5]


def _spec(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


PATHS = _example_paths()
IDS = [_stem(p) for p in PATHS]


def test_examples_were_discovered():
    # Without this the parametrized tests below would be a vacuous pass.
    assert PATHS, f"no example JSONs found under {EXAMPLES_DIR}"


@pytest.mark.parametrize("path", PATHS, ids=IDS)
def test_the_seeded_title_is_the_specs_own_name(path: str):
    """What the gallery shows must be what the JSON declares."""
    spec = _spec(path)
    declared = (spec["dataflow"].get("name") or "").strip()
    assert declared, f"{_stem(path)}.json declares no dataflow.name"

    resolved = _name_from_spec(spec) or _name_from_stem(_stem(path))
    assert resolved == declared, (
        f"{_stem(path)}: the gallery would show {resolved!r} but the JSON says "
        f"{declared!r}"
    )


def test_the_street_vision_example_keeps_its_real_title():
    """The case that drifted furthest, pinned by name.

    ``street-vision-cv-analysis`` is nothing like ``Street-level computer
    vision``: the filename route did not just lose punctuation, it produced a
    different title. Worth its own assertion so the regression is recognizable.
    """
    path = os.path.join(EXAMPLES_DIR, "10-street-vision-cv-analysis.json")
    spec = _spec(path)

    assert _name_from_spec(spec) == "Street-level computer vision"
    # The old behaviour, kept here to document what this replaced.
    assert _name_from_stem("10-street-vision-cv-analysis") == "Street vision cv analysis"


def test_the_filename_fallback_still_works_for_a_spec_with_no_name():
    """The stamp exists so TrillGenerator never falls back to "DefaultWorkflow".

    Keeping the fallback matters: a hand-added example without a name must still
    get a readable title rather than an empty one.
    """
    assert _name_from_spec({"dataflow": {}}) is None
    assert _name_from_spec({"dataflow": {"name": "   "}}) is None
    assert _name_from_spec({}) is None
    assert _name_from_stem("42-some-new-example") == "Some new example"


@pytest.mark.parametrize("path", PATHS, ids=IDS)
def test_the_seeded_description_is_present(path: str):
    """Five examples had none, so their gallery cards rendered with no subtitle."""
    from utk_curio.backend.app.projects.seed import _description_from_spec

    assert _description_from_spec(_spec(path)), (
        f"{_stem(path)}.json has no dataflow.description, so its gallery card "
        f"has no subtitle (#148)"
    )
