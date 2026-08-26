"""dev/105 D1 — `_resolve_catalog_dir_name` / `_package_install_miss_hint`.

Pure-function coverage for the package.install dirName resolver: every
spelling the roster teaches resolves to the one catalog row; an ambiguous
bare id refuses naming every candidate (never guesses a major); the miss hint
names only sources the run holds a grant for (DEC-063). The route-level
behaviour rides in test_routes.TestReuseLadder.
"""
from __future__ import annotations

import pytest

from utk_curio.backend.app.agents.services import (
    _package_install_miss_hint,
    _resolve_catalog_dir_name,
)
from utk_curio.backend.app.packages.services import canonical_template_id

ROWS = {
    "curio.notes@1": {"dirName": "curio.notes@1", "name": "Simple Notes"},
    "curio.weather@1": {"dirName": "curio.weather@1", "name": "Weather"},
    "curio.weather@2": {"dirName": "curio.weather@2", "name": "Weather"},
}


@pytest.mark.parametrize("spelling", [
    "curio.notes@1",              # the dirName itself
    "curio.notes",                # the manifest id (the live miss)
    "curio.notes/note-surface",   # the template id the roster line leads with
    "curio.notes/note-surface@1", # its versioned form
])
def test_every_taught_spelling_resolves_to_the_one_row(spelling):
    row, candidates = _resolve_catalog_dir_name(spelling, ROWS)
    assert row is ROWS["curio.notes@1"]
    assert candidates == []


def test_template_id_form_goes_through_the_one_vocabulary():
    """Lock-step with node.create: the package half the resolver derives is
    exactly canonical_template_id's package half — no second parser."""
    spelling = "curio.notes/note-surface@1"
    expected_pkg = canonical_template_id(spelling).split("/", 1)[0]
    row, _ = _resolve_catalog_dir_name(spelling, ROWS)
    assert row["dirName"].rsplit("@", 1)[0] == expected_pkg == "curio.notes"


def test_bare_id_with_two_majors_refuses_naming_both():
    row, candidates = _resolve_catalog_dir_name("curio.weather", ROWS)
    assert row is None
    assert candidates == ["curio.weather@1", "curio.weather@2"]


def test_true_misses_are_misses():
    assert _resolve_catalog_dir_name("curio.nothing", ROWS) == (None, [])
    assert _resolve_catalog_dir_name("curio.notes@7", ROWS) == (None, [])  # wrong major, no guessing
    assert _resolve_catalog_dir_name("curio.nothing/tpl", ROWS) == (None, [])


def test_miss_hint_is_grant_aware():
    without = _package_install_miss_hint(["package.install", "node.create"])
    assert "Installed but NOT enlisted in this project" in without
    assert "packages.catalog" not in without
    with_catalog = _package_install_miss_hint(["package.install", "packages.catalog"])
    assert "Installed but NOT enlisted in this project" in with_catalog
    assert "packages.catalog" in with_catalog
    assert "Installed but NOT enlisted" in _package_install_miss_hint(None)
