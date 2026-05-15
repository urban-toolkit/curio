"""Tests for :mod:`utk_curio.backend.app.packs.factory`."""

from __future__ import annotations

import io
import zipfile

import pytest

from utk_curio.backend.app.packs.factory import FactoryError, build_pack_archive
from utk_curio.backend.app.packs.installer import (
    InstallerError,
    install_pack_from_archive,
    publish_pack_archive_to_catalog_dir,
)


def _draft(**overrides):
    manifest = {
        "id": "ai.test.demo",
        "version": "1.2.3",
        "name": "Demo",
        "publisher": "Test",
        "description": "Test pack",
        "license": "MIT",
        "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
        "permissions": [],
        "dependencies": {"packs": {}, "python": {}, "js": {}},
        "kinds": [
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
        ],
    }
    draft = {
        "manifest": manifest,
        "sources": {"demo-kind": {"Default.py": "def run():\n    return {}\n"}},
    }
    draft.update(overrides)
    return draft


def test_build_produces_installable_archive(tmp_curio):
    result = build_pack_archive(_draft())
    assert result.filename == "ai.test.demo@1-1.2.3.curio-nodepack"
    install_result = install_pack_from_archive("guest", result.archive)
    assert install_result.manifest.pack_id == "ai.test.demo"
    assert install_result.manifest.version == "1.2.3"


def test_build_accepts_optional_lineage(tmp_curio):
    draft = _draft()
    draft["manifest"]["lineage"] = {
        "forkedFrom": {"packId": "ai.upstream.origin", "major": 1},
        "root": {"packId": "ai.upstream.origin", "major": 1},
    }
    result = build_pack_archive(draft)
    assert result.manifest.lineage is not None
    assert result.manifest.lineage.forked_from.pack_id == "ai.upstream.origin"
    install_result = install_pack_from_archive("guest", result.archive)
    assert install_result.manifest.lineage is not None
    assert install_result.manifest.lineage.root.major == 1


def test_build_is_deterministic(tmp_curio):
    a = build_pack_archive(_draft()).archive
    b = build_pack_archive(_draft()).archive
    assert a == b


def test_build_rejects_unknown_kind_in_sources():
    draft = _draft()
    draft["sources"]["other-kind"] = {"X.py": "pass"}
    with pytest.raises(FactoryError, match="unknown kind id"):
        build_pack_archive(draft)


def test_build_rejects_bad_filename():
    draft = _draft()
    draft["sources"]["demo-kind"] = {"../escape.py": "pass"}
    with pytest.raises(FactoryError, match="safe single-segment"):
        build_pack_archive(draft)


def test_build_rejects_missing_default_template():
    draft = _draft()
    draft["sources"]["demo-kind"] = {"Different.py": "pass"}
    with pytest.raises(FactoryError, match="defaultTemplate references"):
        build_pack_archive(draft)


def test_build_rejects_bad_manifest():
    draft = _draft()
    draft["manifest"]["id"] = "not valid"
    with pytest.raises(FactoryError):
        build_pack_archive(draft)


def test_build_includes_readme_and_license():
    draft = _draft()
    draft["readme"] = "# Demo\n"
    draft["license_text"] = "MIT"
    result = build_pack_archive(draft)
    with zipfile.ZipFile(io.BytesIO(result.archive), "r") as zf:
        names = set(zf.namelist())
    assert "README.md" in names
    assert "LICENSE" in names


def test_publish_pack_archive_to_catalog_dir(tmp_path):
    root = tmp_path / "catalog"
    archive = build_pack_archive(_draft()).archive

    result = publish_pack_archive_to_catalog_dir(archive, root, replace=False)
    assert result.manifest.pack_id == "ai.test.demo"
    dest = root / result.manifest.dir_name
    assert dest.is_dir()

    with pytest.raises(InstallerError, match="already exists"):
        publish_pack_archive_to_catalog_dir(archive, root, replace=False)

    bumped = _draft()
    bumped["manifest"]["version"] = "2.0.0"
    archive2 = build_pack_archive(bumped).archive

    replaced = publish_pack_archive_to_catalog_dir(archive2, root, replace=True)
    assert replaced.replaced_existing is True
    assert replaced.manifest.version == "2.0.0"
