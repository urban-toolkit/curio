"""Smoke tests for the committed ``packages/curio.builtin@1`` catalog entry.

The built-in package is auto-installed for every user and provides the 14
default node templates. A regression in its manifest would silently strand
users with an empty palette, so we exercise the load + payload-serialize
paths against the on-disk artefact. The Raster Calculator is not one of them:
it is a node of Scout, ``curio.scout@1`` (``test_scout_rasters.py``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
from utk_curio.backend.app.packages.schemas.responses import package_payload

# The COMMITTED catalog, named directly rather than through
# ``catalog_root()``: these assertions are about what the repository ships,
# and the runtime root is relocatable (``CURIO_PACKAGES_ROOT``) so a test
# session gets its own copy to publish into.
REAL_CATALOG = Path(__file__).resolve().parents[4] / "packages"


EXPECTED_TEMPLATE_IDS: frozenset[str] = frozenset({
    "data-loading",
    "data-export",
    "data-transformation",
    "data-pool",
    "computation-analysis",
    "data-summary",
    "js-computation",
    "vis-vega",
    "vis-simple",
    "autk-grammar",
    "spatial-join",
    "parameter",
    "edit-features",
    "note",
})

EXPECTED_BEHAVIORS: frozenset[str] = frozenset({
    "code", "data-export", "data-pool", "data-summary", "vega",
    "simple-vis", "autk-grammar", "spatial-join", "parameter",
    "edit-features", "note",
})


@pytest.fixture()
def builtin_package_dir() -> Path:
    root = REAL_CATALOG
    candidates = sorted(
        d for d in root.iterdir()
        if d.is_dir() and d.name.startswith("curio.builtin@")
    )
    assert candidates, f"no curio.builtin@<X> in catalog at {root}"
    return candidates[-1]


def test_builtin_package_manifest_loads(builtin_package_dir: Path):
    manifest = load_package_manifest(builtin_package_dir)
    assert manifest.package_id == "curio.builtin"
    assert manifest.major == 1
    template_ids = {t.template_id for t in manifest.templates}
    assert template_ids == EXPECTED_TEMPLATE_IDS


def test_builtin_package_every_template_has_behavior_and_icon(builtin_package_dir: Path):
    manifest = load_package_manifest(builtin_package_dir)
    for template in manifest.templates:
        assert template.behavior in EXPECTED_BEHAVIORS, (
            f"template {template.template_id} declares unknown behavior {template.behavior!r}"
        )
        assert template.icon_ref, f"template {template.template_id} is missing iconRef"
        assert template.palette_order is not None, (
            f"template {template.template_id} must declare paletteOrder"
        )


def test_the_edit_features_template_is_the_interaction_node(builtin_package_dir: Path):
    """The node is called Interaction, with a hand icon; its template id and
    behavior stay ``edit-features``, so saved dataflows load as they are."""
    manifest = load_package_manifest(builtin_package_dir)
    (template,) = [t for t in manifest.templates if t.template_id == "edit-features"]
    assert template.label == "Interaction"
    assert template.icon_ref == "fa-solid:hand-pointer"
    assert template.behavior == "edit-features"
    assert not any(t.label == "Edit Features" for t in manifest.templates)


def test_the_note_holds_text_and_runs_nothing(builtin_package_dir: Path):
    """The Note: a title and simple markdown on a color. It has no port, so no
    edge reaches it, and no code, so a run has nothing to execute; its text is
    the content a note template carries (``note``), which the Researcher writes."""
    from utk_curio.backend.app.packages.application.templates import (
        CONTENT_KIND_NOTE,
        template_content_kind,
        template_is_executable,
    )

    manifest = load_package_manifest(builtin_package_dir)
    note = next(t for t in manifest.templates if t.template_id == "note")
    assert note.label == "Note"
    assert note.behavior == "note"
    assert note.editor == "none"
    assert note.input_ports == [] and note.output_ports == []
    assert not note.has_code and not note.has_grammar and not note.has_widgets
    assert template_is_executable(note) is False
    assert template_content_kind(note) == CONTENT_KIND_NOTE
    assert note.icon_ref == "fa-solid:note-sticky"


def test_no_raster_node_is_built_in(builtin_package_dir: Path):
    """The Raster Calculator left the built-in nodes for Scout,
    ``curio.scout@1``, and no other raster node took its place."""
    manifest = load_package_manifest(builtin_package_dir)
    assert not [t.template_id for t in manifest.templates if "raster" in t.template_id], (
        [t.template_id for t in manifest.templates]
    )
    assert not [t.label for t in manifest.templates if "Raster" in t.label]


def test_no_shipped_package_names_compare_scenarios():
    """Compare Scenarios is gone (step 6.4 of the plan answering komar41's
    review of the #914 merges): no shipped package holds a template of that
    id or that behavior, and no manifest names the node, so no palette, Node
    Catalog or agent preamble offers it."""
    import json

    manifests = sorted(REAL_CATALOG.glob("*/manifest.json"))
    assert manifests, "expected at least one package in the catalog"
    named = {}
    for path in manifests:
        text = path.read_text(encoding="utf-8")
        templates = json.loads(text).get("templates", [])
        found = [
            t.get("id") for t in templates
            if "compare-scenarios" in (t.get("id"), t.get("behavior"))
        ]
        found += [word for word in ("compare-scenarios", "Compare Scenarios") if word in text]
        if found:
            named[path.parent.name] = found
    assert named == {}, f"packages that still name Compare Scenarios: {named}"


def test_the_interaction_node_names_no_what_differs(builtin_package_dir: Path):
    """What differs went with Compare Scenarios: the Interaction node's
    description, which its tile, the Node Catalog and the agents' preamble
    show, names neither."""
    manifest = load_package_manifest(builtin_package_dir)
    (template,) = [t for t in manifest.templates if t.template_id == "edit-features"]
    for word in ("What differs", "Compare Scenarios"):
        assert word not in template.description, template.description
    preamble = REAL_CATALOG.parent / "utk_curio" / "llm-prompts" / "default_preamble.md"
    # The node's lines in each of the preamble's lists: its description, its
    # controls, its input and output types and its circles.
    lines = [line for line in preamble.read_text(encoding="utf-8").splitlines() if line.startswith("- Interaction:")]
    assert any("Removes features" in line for line in lines), lines
    for line in lines:
        for word in ("What differs", "Compare Scenarios"):
            assert word not in line, line


def test_builtin_package_ships_no_sources(builtin_package_dir: Path):
    """Built-in templates are structural shells — no starter code files."""
    manifest = load_package_manifest(builtin_package_dir)
    for template in manifest.templates:
        assert template.source is None, (
            f"built-in template {template.template_id} must not declare a source"
        )
    assert not (builtin_package_dir / "sources").exists(), (
        "built-in package must not ship a sources/ directory"
    )


def test_every_catalog_package_validates_against_schema():
    """Every manifest in ``packages/`` must satisfy ``docs/schemas/node-package.v4.json``."""
    import json
    from jsonschema import Draft202012Validator

    schema_path = REAL_CATALOG.parent / "docs" / "schemas" / "node-package.v4.json"
    assert schema_path.is_file(), f"schema not found at {schema_path}"
    validator = Draft202012Validator(json.loads(schema_path.read_text()))

    manifests = sorted(REAL_CATALOG.glob("*/manifest.json"))
    assert manifests, "expected at least one package in the catalog"
    for m in manifests:
        errors = list(validator.iter_errors(json.loads(m.read_text())))
        assert not errors, (
            f"{m} fails schema:\n"
            + "\n".join(f"  {list(e.absolute_path)}: {e.message}" for e in errors[:5])
        )


def test_builtin_package_payload_passthrough(builtin_package_dir: Path):
    """The wire payload exposes the new manifest fields per template."""
    manifest = load_package_manifest(builtin_package_dir)
    payload = package_payload(manifest)
    templates_by_id = {t["templateId"]: t for t in payload["templates"]}
    vega = templates_by_id["vis-vega"]
    assert vega["behavior"] == "vega"
    assert vega["iconRef"] == "fa-solid:chart-line"
    assert vega["badge"] == "VEGA"
    assert vega["grammarId"] == "vega-lite"
    assert vega["source"] is None

    autk_grammar = templates_by_id["autk-grammar"]
    assert autk_grammar["behavior"] == "autk-grammar"
    assert autk_grammar["badge"] == "AUTK"
    assert autk_grammar["grammarId"] == "autk-grammar"

    data_loading = templates_by_id["data-loading"]
    assert data_loading["behavior"] == "code"
    assert data_loading["iconRef"] == "fa-solid:upload"
    assert data_loading["badge"] is None
