"""Tests for optional pack manifest ``lineage`` (fork provenance)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from utk_curio.backend.app.packs.manifest import (
    ManifestError,
    PackLineageCoord,
    load_pack_manifest,
)


def _minimal_kinds() -> list[dict]:
    return [
        {
            "id": "demo-kind",
            "label": "Demo",
            "category": "computation",
            "engine": "python",
            "editor": "code",
            "hasCode": True,
            "hasWidgets": False,
            "hasGrammar": False,
            "inputPorts": [],
            "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
            "templateDir": "templates/demo-kind",
            "defaultTemplate": "templates/demo-kind/Default.py",
        }
    ]


def _write_pack_dir(base: Path, pack_id: str, major: int, **extra_top: object) -> Path:
    root = base / f"{pack_id}@{major}"
    root.mkdir(parents=True)
    manifest: dict = {
        "id": pack_id,
        "version": "1.0.0",
        "name": "t",
        "publisher": "t",
        "description": "d",
        "license": "MIT",
        "compatibility": {"curioRuntime": ">=0.5.0", "major": major},
        "permissions": [],
        "dependencies": {"packs": {}, "python": {}, "js": {}},
        "kinds": _minimal_kinds(),
    }
    manifest.update(extra_top)
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def test_load_without_lineage(tmp_path: Path) -> None:
    d = _write_pack_dir(tmp_path, "ai.test.lineage", 1)
    m = load_pack_manifest(d)
    assert m.lineage is None


def test_forked_from_only_root_defaults(tmp_path: Path) -> None:
    d = _write_pack_dir(
        tmp_path,
        "curio.test.fork.pack",
        1,
        lineage={"forkedFrom": {"packId": "ai.upstream.parent", "major": 2}},
    )
    m = load_pack_manifest(d)
    assert m.lineage is not None
    assert m.lineage.forked_from == PackLineageCoord("ai.upstream.parent", 2)
    assert m.lineage.root == m.lineage.forked_from


def test_forked_from_and_distinct_root(tmp_path: Path) -> None:
    d = _write_pack_dir(
        tmp_path,
        "curio.test.fork.pack",
        1,
        lineage={
            "forkedFrom": {"packId": "curio.palette.fork.abc", "major": 1},
            "root": {"packId": "ai.upstream.catalog", "major": 1},
        },
    )
    m = load_pack_manifest(d)
    assert m.lineage is not None
    assert m.lineage.forked_from == PackLineageCoord("curio.palette.fork.abc", 1)
    assert m.lineage.root == PackLineageCoord("ai.upstream.catalog", 1)


@pytest.mark.parametrize(
    "bad_lineage",
    [
        [],
        {"forkedFrom": {"packId": "ai.upstream.parent", "major": "1"}},
        {"forkedFrom": {"packId": "BAD_ID", "major": 1}},
        {"root": {"packId": "ai.upstream.parent", "major": 1}},
    ],
)
def test_lineage_validation_errors(tmp_path: Path, bad_lineage: object) -> None:
    d = _write_pack_dir(tmp_path, "curio.test.bad.lineage", 1, lineage=bad_lineage)
    with pytest.raises(ManifestError):
        load_pack_manifest(d)


def test_self_fork_rejected(tmp_path: Path) -> None:
    pid = "curio.test.self.fork"
    d = _write_pack_dir(
        tmp_path,
        pid,
        1,
        lineage={"forkedFrom": {"packId": pid, "major": 1}},
    )
    with pytest.raises(ManifestError, match="forkedFrom must differ"):
        load_pack_manifest(d)


def test_root_equals_self_rejected(tmp_path: Path) -> None:
    pid = "curio.test.root.self"
    d = _write_pack_dir(
        tmp_path,
        pid,
        1,
        lineage={
            "forkedFrom": {"packId": "ai.upstream.parent", "major": 1},
            "root": {"packId": pid, "major": 1},
        },
    )
    with pytest.raises(ManifestError, match="root must differ"):
        load_pack_manifest(d)


def test_curio_palette_dock_fork_hidden_round_trip(tmp_path: Path) -> None:
    d = _write_pack_dir(
        tmp_path,
        "ai.curio.dock.hidden",
        1,
        curio={"paletteDock": {"hiddenFromForkPaletteDock": True}},
    )
    assert load_pack_manifest(d).hidden_from_fork_palette_dock is True


def test_curio_palette_dock_fork_hidden_explicit_false(tmp_path: Path) -> None:
    d = _write_pack_dir(
        tmp_path,
        "ai.curio.dock.visible",
        1,
        curio={"paletteDock": {"hiddenFromForkPaletteDock": False}},
    )
    assert load_pack_manifest(d).hidden_from_fork_palette_dock is False


def test_curio_must_be_object(tmp_path: Path) -> None:
    d = _write_pack_dir(tmp_path, "ai.bad.curio", 1, curio="oops")
    with pytest.raises(ManifestError, match="curio"):
        load_pack_manifest(d)


def test_palette_dock_must_be_object(tmp_path: Path) -> None:
    d = _write_pack_dir(tmp_path, "ai.bad.palettedock", 1, curio={"paletteDock": "x"})
    with pytest.raises(ManifestError, match="paletteDock"):
        load_pack_manifest(d)


@pytest.mark.parametrize("bad_hidden", ["yes", 1])
def test_hidden_flag_must_be_boolean(tmp_path: Path, bad_hidden: object) -> None:
    d = _write_pack_dir(
        tmp_path,
        "ai.bad.hidden.type",
        1,
        curio={"paletteDock": {"hiddenFromForkPaletteDock": bad_hidden}},
    )
    with pytest.raises(ManifestError, match="hiddenFromForkPaletteDock"):
        load_pack_manifest(d)


def test_load_optional_created_at_parses_iso_z(tmp_path: Path) -> None:
    d = _write_pack_dir(tmp_path, "ai.test.created", 1, createdAt="2024-05-20T08:09:11Z")
    m = load_pack_manifest(d)
    assert m.created_at_iso is not None and m.created_at_iso.endswith("Z")
    assert m.created_at_ms == int(
        datetime(2024, 5, 20, 8, 9, 11, tzinfo=timezone.utc).timestamp() * 1000
    )


def test_created_at_invalid_raises(tmp_path: Path) -> None:
    d = _write_pack_dir(tmp_path, "ai.test.bad.created", 1, createdAt="not-a-datetime")
    with pytest.raises(ManifestError, match="createdAt"):
        load_pack_manifest(d)
