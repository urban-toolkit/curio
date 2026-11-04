"""The list of templates an agent reads names each template's widgets.

A template from a package can declare the widgets a fresh node of it starts
with (#662), and a plan sets their values by name. The Node Builder and the
Dataflow Builder read the templates they may use as one line each
(``turns/roster.py``), its description cut at 140 characters: the line ends
with the template's widgets, so an agent knows what to set without guessing
from the description. Scout's charts read their columns through them (the
plan for #914, step 28.2).
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize("folder", ["curio.scout@1", "model.scout.deep-umbra@1"])
def test_each_package_templates_line_names_its_widgets(folder):
    from utk_curio.backend.app.agents.application.turns.roster import _template_line
    from utk_curio.backend.app.packages.application.templates import _template_entry
    from utk_curio.backend.app.packages.service import load_package_manifest

    manifest = load_package_manifest(REPO / "packages" / folder)
    with_widgets = [t for t in manifest.templates if t.widgets]
    assert with_widgets, folder
    for template in with_widgets:
        names = [widget["name"] for widget in template.widgets]
        entry = _template_entry(manifest.package_id, template)
        assert entry["widgets"] == names
        line = _template_line(entry)
        assert line.endswith(f" (widgets: {', '.join(names)})"), line
        # The enlistable list adds the package after them.
        enlist = _template_line(entry, suffix=f" (package {folder})")
        assert enlist.endswith(f" (widgets: {', '.join(names)}) (package {folder})"), enlist


def test_a_template_with_no_widgets_names_none():
    from utk_curio.backend.app.agents.application.turns.roster import _template_line
    from utk_curio.backend.app.packages.application.templates import _template_entry
    from utk_curio.backend.app.packages.service import load_package_manifest

    manifest = load_package_manifest(REPO / "packages" / "curio.builtin@1")
    (vega,) = [t for t in manifest.templates if t.template_id == "vis-vega"]
    entry = _template_entry(manifest.package_id, vega)
    assert "widgets" not in entry
    assert "(widgets" not in _template_line(entry)
