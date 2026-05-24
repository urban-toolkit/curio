"""Smoke tests for the committed ``packs/curio.builtin@1`` catalog entry.

The built-in pack is auto-installed for every user and provides the 14
default node kinds. A regression in its manifest would silently strand
users with an empty palette, so we exercise the load + payload-serialize
paths against the on-disk artefact.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from utk_curio.backend.app.packs.manifest import load_pack_manifest
from utk_curio.backend.app.packs.routes import _catalog_root, _manifest_to_payload


EXPECTED_KIND_IDS: frozenset[str] = frozenset({
    "data-loading",
    "data-export",
    "data-transformation",
    "data-pool",
    "computation-analysis",
    "data-summary",
    "js-computation",
    "vis-vega",
    "vis-simple",
    "autk-plot",
    "autk-map",
    "autk-compute",
    "autk-db",
    "merge-flow",
})

EXPECTED_LIFECYCLES: frozenset[str] = frozenset({
    "code", "data-export", "data-pool", "data-summary", "vega",
    "simple-vis", "autk-plot", "autk-map", "autk-compute", "autk-db",
    "merge-flow",
})


@pytest.fixture()
def builtin_pack_dir() -> Path:
    root = _catalog_root()
    candidates = sorted(
        d for d in root.iterdir()
        if d.is_dir() and d.name.startswith("curio.builtin@")
    )
    assert candidates, f"no curio.builtin@<X> in catalog at {root}"
    return candidates[-1]


def test_builtin_pack_manifest_loads(builtin_pack_dir: Path):
    manifest = load_pack_manifest(builtin_pack_dir)
    assert manifest.pack_id == "curio.builtin"
    assert manifest.major == 1
    kind_ids = {k.kind_id for k in manifest.kinds}
    assert kind_ids == EXPECTED_KIND_IDS


def test_builtin_pack_every_kind_has_lifecycle_and_icon(builtin_pack_dir: Path):
    manifest = load_pack_manifest(builtin_pack_dir)
    for kind in manifest.kinds:
        assert kind.lifecycle in EXPECTED_LIFECYCLES, (
            f"kind {kind.kind_id} declares unknown lifecycle {kind.lifecycle!r}"
        )
        assert kind.icon_ref, f"kind {kind.kind_id} is missing iconRef"
        assert kind.palette_order is not None, (
            f"kind {kind.kind_id} must declare paletteOrder"
        )


def test_builtin_pack_ships_no_sources(builtin_pack_dir: Path):
    """Built-in kinds are structural shells — no starter code files."""
    manifest = load_pack_manifest(builtin_pack_dir)
    for kind in manifest.kinds:
        assert kind.source is None, (
            f"built-in kind {kind.kind_id} must not declare a source"
        )
    assert not (builtin_pack_dir / "sources").exists(), (
        "built-in pack must not ship a sources/ directory"
    )


def test_every_catalog_pack_validates_against_schema():
    """Every manifest in ``packs/`` must satisfy ``docs/schemas/node-pack.v2.json``."""
    import json
    from jsonschema import Draft202012Validator

    schema_path = _catalog_root().parent / "docs" / "schemas" / "node-pack.v2.json"
    assert schema_path.is_file(), f"schema not found at {schema_path}"
    validator = Draft202012Validator(json.loads(schema_path.read_text()))

    manifests = sorted(_catalog_root().glob("*/manifest.json"))
    assert manifests, "expected at least one pack in the catalog"
    for m in manifests:
        errors = list(validator.iter_errors(json.loads(m.read_text())))
        assert not errors, (
            f"{m} fails schema:\n"
            + "\n".join(f"  {list(e.absolute_path)}: {e.message}" for e in errors[:5])
        )


def test_builtin_pack_payload_passthrough(builtin_pack_dir: Path):
    """The wire payload exposes the new manifest fields per kind."""
    manifest = load_pack_manifest(builtin_pack_dir)
    payload = _manifest_to_payload(manifest)
    kinds_by_id = {k["kindId"]: k for k in payload["kinds"]}
    vega = kinds_by_id["vis-vega"]
    assert vega["lifecycle"] == "vega"
    assert vega["iconRef"] == "fa-solid:chart-line"
    assert vega["badge"] == "VEGA"
    assert vega["grammarId"] == "vega-lite"
    assert vega["source"] is None

    autk_map = kinds_by_id["autk-map"]
    assert autk_map["lifecycle"] == "autk-map"
    assert autk_map["badge"] == "AUTK"

    data_loading = kinds_by_id["data-loading"]
    assert data_loading["lifecycle"] == "code"
    assert data_loading["iconRef"] == "fa-solid:upload"
    assert data_loading["badge"] is None
