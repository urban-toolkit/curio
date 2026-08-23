"""Tests for :mod:`utk_curio.backend.app.packages.factory`."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime

import pytest

from utk_curio.backend.app.packages.factory import (
    FactoryError,
    build_packageage_archive,
    preserve_unedited_sources,
    _STARTER_CODE_SENTINEL,
)
from utk_curio.backend.app.packages.installer import (
    InstallerError,
    install_packageage_from_archive,
    publish_packageage_archive_to_catalog_dir,
)
from utk_curio.backend.app.packages.storage import package_dir


def _draft(**overrides):
    manifest = {
        "id": "ai.test.demo",
        "version": "1.2.3",
        "name": "Demo",
        "publisher": "Test",
        "description": "Test package",
        "license": "MIT",
        "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
        "createdAt": "2000-01-01T00:00:00Z",
        "permissions": [],
        "dependencies": {"packages": {}, "python": {}, "js": {}},
        "templates": [
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
                "source": "sources/demo-kind.py",
            }
        ],
    }
    draft = {
        "manifest": manifest,
        "sources": {
            "demo-kind": {"filename": "demo-kind.py", "code": "def run():\n    return {}\n"},
        },
    }
    draft.update(overrides)
    return draft


def test_build_produces_installable_archive(tmp_curio):
    result = build_packageage_archive(_draft())
    assert result.filename == "ai.test.demo@1-1.2.3.curio.zip"
    install_result = install_packageage_from_archive("guest", result.archive)
    assert install_result.manifest.package_id == "ai.test.demo"
    assert install_result.manifest.version == "1.2.3"


def test_build_accepts_optional_lineage(tmp_curio):
    draft = _draft()
    draft["manifest"]["lineage"] = {
        "forkedFrom": {"packageId": "ai.upstream.origin", "major": 1},
        "root": {"packageId": "ai.upstream.origin", "major": 1},
    }
    result = build_packageage_archive(draft)
    assert result.manifest.lineage is not None
    assert result.manifest.lineage.forked_from.package_id == "ai.upstream.origin"
    install_result = install_packageage_from_archive("guest", result.archive)
    assert install_result.manifest.lineage is not None
    assert install_result.manifest.lineage.root.major == 1


def test_build_is_deterministic(tmp_curio):
    a = build_packageage_archive(_draft()).archive
    b = build_packageage_archive(_draft()).archive
    assert a == b


def test_build_rejects_unknown_template_in_sources():
    draft = _draft()
    draft["sources"]["other-template"] = {"filename": "X.py", "code": "pass"}
    with pytest.raises(FactoryError, match="unknown template id"):
        build_packageage_archive(draft)


def test_build_rejects_bad_filename():
    draft = _draft()
    draft["sources"]["demo-kind"] = {"filename": "../escape.py", "code": "pass"}
    with pytest.raises(FactoryError, match="single safe"):
        build_packageage_archive(draft)


def test_build_rejects_missing_source():
    draft = _draft()
    draft["sources"]["demo-kind"] = {"filename": "Different.py", "code": "pass"}
    with pytest.raises(FactoryError, match="source references"):
        build_packageage_archive(draft)


def test_build_rejects_bad_manifest():
    draft = _draft()
    draft["manifest"]["id"] = "not valid"
    with pytest.raises(FactoryError):
        build_packageage_archive(draft)


def test_build_includes_readme_and_license():
    draft = _draft()
    draft["readme"] = "# Demo\n"
    draft["license_text"] = "MIT"
    result = build_packageage_archive(draft)
    with zipfile.ZipFile(io.BytesIO(result.archive), "r") as zf:
        names = set(zf.namelist())
    assert "README.md" in names
    assert "LICENSE" in names


def test_preserve_unedited_sources_restores_real_source_for_placeholder_kind(tmp_curio):
    """Regression: Save-As into an existing package must not clobber unedited templates.

    When ``NodeSaveAsModal`` rebuilds a package, the frontend only carries the
    real edited source for the one canvas template; every other template in
    the target package comes through with the ``STARTER_CODE`` placeholder
    because ``_manifest_to_payload`` does not surface source bodies. Without
    the preservation hook in ``factory_install``, the rebuild would overwrite
    every unedited template with that placeholder, silently destroying real
    code.
    """
    # 1. Install a two-kind package with distinctive source for each kind.
    distinctive_foo = "import numpy\n\ndef run():\n    return 'foo-original'\n"
    distinctive_bar = "import pandas\n\ndef run():\n    return 'bar-original'\n"
    install_draft = _draft()
    install_draft["manifest"]["templates"] = [
        {
            "id": "foo-kind",
            "label": "Foo",
            "category": "computation",
            "engine": "python",
            "editor": "code",
            "hasCode": True,
            "hasWidgets": False,
            "hasGrammar": False,
            "inputPorts": [],
            "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
            "source": "sources/foo-kind.py",
        },
        {
            "id": "bar-kind",
            "label": "Bar",
            "category": "computation",
            "engine": "python",
            "editor": "code",
            "hasCode": True,
            "hasWidgets": False,
            "hasGrammar": False,
            "inputPorts": [],
            "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
            "source": "sources/bar-kind.py",
        },
    ]
    install_draft["sources"] = {
        "foo-kind": {"filename": "foo-kind.py", "code": distinctive_foo},
        "bar-kind": {"filename": "bar-kind.py", "code": distinctive_bar},
    }
    built = build_packageage_archive(install_draft)
    install_packageage_from_archive("guest", built.archive)
    installed_dir = package_dir("guest", "ai.test.demo@1")
    assert (installed_dir / "sources" / "foo-kind.py").read_text() == distinctive_foo
    assert (installed_dir / "sources" / "bar-kind.py").read_text() == distinctive_bar

    # 2. Simulate a Save-As rebuild: foo gets a real edit, bar carries placeholder.
    edited_foo = "import numpy\n\ndef run():\n    return 'foo-edited'\n"
    rebuild_draft = dict(install_draft)
    rebuild_draft["sources"] = {
        "foo-kind": {"filename": "foo-kind.py", "code": edited_foo},
        "bar-kind": {"filename": "bar-kind.py", "code": _STARTER_CODE_SENTINEL},
    }

    # 3. Preserve should swap the placeholder back to the real on-disk body.
    merged = preserve_unedited_sources(rebuild_draft, installed_dir)
    assert merged["sources"]["foo-kind"]["code"] == edited_foo
    assert merged["sources"]["bar-kind"]["code"] == distinctive_bar


def test_preserve_unedited_sources_noop_for_fresh_install():
    """Without an existing package directory, the draft passes through unchanged."""
    draft = _draft()
    assert preserve_unedited_sources(draft, None) is draft


def test_build_auto_detects_python_dependencies_from_source(tmp_curio):
    """``build_packageage_archive`` populates ``dependencies.python`` from source imports.

    The Node Factory wizard is gone (no UI for manual dep entry), so dependency
    declarations are derived from each template's source file. Test that a draft
    whose body imports ``numpy`` and ``sklearn`` produces a manifest whose
    ``dependencies.python`` contains ``numpy`` and the alias-mapped
    ``scikit-learn``, with stdlib filtered out.
    """
    draft = _draft()
    draft["sources"]["demo-kind"]["code"] = (
        "import os\n"  # stdlib — filtered
        "import numpy\n"  # straight pass-through
        "import sklearn\n"  # alias-mapped → scikit-learn
        "def run():\n"
        "    return {}\n"
    )
    result = build_packageage_archive(draft)
    assert result.manifest.python_deps == {"numpy": "*", "scikit-learn": "*"}
    assert result.manifest.js_deps == {}


def test_publish_packageage_archive_to_catalog_dir(tmp_path):
    root = tmp_path / "catalog"
    archive = build_packageage_archive(_draft()).archive

    result = publish_packageage_archive_to_catalog_dir(archive, root, replace=False)
    assert result.manifest.package_id == "ai.test.demo"
    dest = root / result.manifest.dir_name
    assert dest.is_dir()

    with pytest.raises(InstallerError, match="already exists"):
        publish_packageage_archive_to_catalog_dir(archive, root, replace=False)

    bumped = _draft()
    bumped["manifest"]["version"] = "2.0.0"
    archive2 = build_packageage_archive(bumped).archive

    replaced = publish_packageage_archive_to_catalog_dir(archive2, root, replace=True)
    assert replaced.replaced_existing is True
    assert replaced.manifest.version == "2.0.0"


# ---------------------------------------------------------------------------
# Builder details the existing tests skip
# ---------------------------------------------------------------------------

def test_build_omits_integrity_json(tmp_curio):
    """Hashes describe files as installed, so no archive ever carries them."""
    result = build_packageage_archive(_draft())
    with zipfile.ZipFile(io.BytesIO(result.archive)) as zf:
        assert "integrity.json" not in set(zf.namelist())


def test_build_stamps_created_at_when_the_draft_omits_it(tmp_curio):
    """``_draft()`` pins ``createdAt``, so the stamping branch is otherwise dead.

    A Save-As draft never carries one (``makeDraft`` leaves it unset), which
    makes this the branch every real Save-As actually takes.
    """
    draft = _draft()
    del draft["manifest"]["createdAt"]
    result = build_packageage_archive(draft)

    with zipfile.ZipFile(io.BytesIO(result.archive)) as zf:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    stamped = manifest["createdAt"]
    # ISO-8601 UTC, parseable — the format the manifest loader expects.
    assert stamped.endswith("Z")
    datetime.strptime(stamped, "%Y-%m-%dT%H:%M:%SZ")


def test_build_leaves_a_pinned_created_at_alone(tmp_curio):
    result = build_packageage_archive(_draft())
    with zipfile.ZipFile(io.BytesIO(result.archive)) as zf:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    assert manifest["createdAt"] == "2000-01-01T00:00:00Z"


def test_build_accepts_license_text_camel_case_alias(tmp_curio):
    """The frontend sends ``licenseText``; the docstring documents ``license_text``."""
    draft = _draft()
    draft["licenseText"] = "MIT-ish, camelCase key"
    result = build_packageage_archive(draft)
    with zipfile.ZipFile(io.BytesIO(result.archive)) as zf:
        assert zf.read("LICENSE").decode("utf-8") == "MIT-ish, camelCase key"


def test_build_auto_detects_js_dependencies_from_source(tmp_curio):
    """The JS half of the dependency scanner, reached through the builder.

    Only the Python scanner was covered here, though a Save-As draft of a JS
    node goes through this path.
    """
    draft = _draft()
    draft["manifest"]["templates"][0]["engine"] = "javascript"
    draft["manifest"]["templates"][0]["source"] = "sources/demo-kind.js"
    draft["sources"] = {
        "demo-kind": {
            "filename": "demo-kind.js",
            "code": """
import cloneDeep from 'lodash/fp';
import { render } from '@scope/widget';
import fs from 'node:fs';
export default function run() { return cloneDeep({}); }
""",
        }
    }

    result = build_packageage_archive(draft)
    js = result.manifest.js_deps
    # Subpath collapsed to the package, scope retained, node: builtin dropped.
    assert js.get("lodash") == "*", js
    assert js.get("@scope/widget") == "*", js
    assert "node:fs" not in js and "fs" not in js, js


def test_preserve_unedited_sources_ignores_a_real_edit(tmp_curio, make_archive):
    """Only placeholder/empty bodies are substituted — a real edit always wins."""
    install_draft = _draft()
    install_draft["sources"] = {
        "demo-kind": {"filename": "demo-kind.py", "code": "ON_DISK = 1"}
    }
    built = build_packageage_archive(install_draft)
    install_packageage_from_archive("guest", built.archive)
    installed_dir = package_dir("guest", "ai.test.demo@1")

    edited = _draft()
    edited["sources"] = {
        "demo-kind": {"filename": "demo-kind.py", "code": "EDITED = 1"}
    }
    merged = preserve_unedited_sources(edited, installed_dir)
    assert merged["sources"]["demo-kind"]["code"] == "EDITED = 1"


def test_preserve_unedited_sources_returns_draft_when_sources_dir_missing(
    tmp_curio, tmp_path
):
    """Guard branches: no ``sources`` key, and an existing dir without ``sources/``."""
    draft = _draft()
    no_sources = {k: v for k, v in draft.items() if k != "sources"}
    assert preserve_unedited_sources(no_sources, tmp_path) is no_sources

    empty_pkg = tmp_path / "pkg"
    empty_pkg.mkdir()
    assert preserve_unedited_sources(draft, empty_pkg) is draft

