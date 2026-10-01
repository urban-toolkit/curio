"""Smoke tests for the committed ``packages/curio.builtin@1`` catalog entry.

The built-in package is auto-installed for every user and provides the 14
default node templates. A regression in its manifest would silently strand
users with an empty palette, so we exercise the load + payload-serialize
paths against the on-disk artefact.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
from utk_curio.backend.app.packages.repositories.catalog_dir import catalog_root
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
    "merge-flow",
    "spatial-join",
})

EXPECTED_BEHAVIORS: frozenset[str] = frozenset({
    "code", "data-export", "data-pool", "data-summary", "vega",
    "simple-vis", "autk-grammar",
    "merge-flow", "spatial-join",
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
