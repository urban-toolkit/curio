"""#468: a package's Python modules beside its templates.

- What counts as a module: an importable name in ``sources/`` that no
  template names as its ``source``.
- The one-name rule: an install is refused when another installed package
  ships a module of the same top-level name, naming both and the module.
- What a run of one of its nodes is handed: the package's ``sources/`` folder
  and its module names, for the sandbox to make importable.
- Save into a package and the Package Builder do not declare the package's
  own modules as PyPI dependencies.

New code is imported inside each test, so a checkout without it fails each
test on its own instead of the whole module at collection.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from utk_curio.backend.app.packages.application.store_install import install_package_from_archive
from utk_curio.backend.app.packages.repositories.archive import InstallerError
from utk_curio.backend.app.packages.repositories.store import package_dir

HEIGHTS = {
    "building_height/__init__.py": "",
    "building_height/convert_to_raster.py": "def convert_raster(value):\n    return value * 2\n",
}


def _manifest(package_id: str, major: int = 1, templates=("caller",)) -> dict:
    return {
        "id": package_id,
        "version": "1.0.0",
        "name": package_id,
        "publisher": "Test",
        "description": "Test package",
        "license": "MIT",
        "compatibility": {"curioRuntime": ">=0.5.0", "major": major},
        "permissions": [],
        "dependencies": {"packages": {}, "python": {}, "js": {}},
        "createdAt": "2026-06-01T12:00:00Z",
        "templates": [
            {
                "id": template_id,
                "label": template_id,
                "category": "computation",
                "engine": "python",
                "editor": "code",
                "hasCode": True,
                "hasWidgets": False,
                "hasGrammar": False,
                "inputPorts": [],
                "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
                "source": f"sources/{template_id}.py",
            }
            for template_id in templates
        ],
    }


def _archive(package_id: str, *, major: int = 1, modules=None, templates=("caller",)) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(_manifest(package_id, major, templates)))
        for template_id in templates:
            zf.writestr(f"sources/{template_id}.py", "return 1\n")
        for relative, text in (modules or {}).items():
            zf.writestr(f"sources/{relative}", text)
    return buf.getvalue()


def _package_on_disk(root: Path, package_id: str, files: dict, templates=("caller",)):
    """A package directory written by hand, and its loaded manifest."""
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

    package = root / f"{package_id}@1"
    (package / "sources").mkdir(parents=True)
    (package / "manifest.json").write_text(json.dumps(_manifest(package_id, 1, templates)), encoding="utf-8")
    for template_id in templates:
        (package / "sources" / f"{template_id}.py").write_text("return 1\n", encoding="utf-8")
    for relative, text in files.items():
        path = package / "sources" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return package, load_package_manifest(package)


# ---------------------------------------------------------------------------
# What counts as a module
# ---------------------------------------------------------------------------

class TestWhatCountsAsAModule:
    def test_importable_names_beside_the_templates_are_modules(self, tmp_path):
        from utk_curio.backend.app.packages.repositories.python_modules import module_names

        package, manifest = _package_on_disk(tmp_path, "ai.test.heights", {
            **HEIGHTS,
            "helpers.py": "X = 1\n",
            "not-a-name.py": "X = 1\n",
            "class.py": "X = 1\n",
            "notes/readme.txt": "no Python here\n",
        })
        assert module_names(package, manifest) == {"building_height", "helpers"}

    def test_a_template_source_is_not_a_module(self, tmp_path):
        """Two packages may each have a ``loader`` template, and a template
        named like a library must not hide that library."""
        from utk_curio.backend.app.packages.repositories.python_modules import module_names

        package, manifest = _package_on_disk(tmp_path, "ai.test.loaders", {}, templates=("loader", "osmnx"))
        assert module_names(package, manifest) == frozenset()

    def test_a_folder_of_template_sources_only_is_not_a_module(self, tmp_path):
        from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
        from utk_curio.backend.app.packages.repositories.python_modules import module_names

        package, _ = _package_on_disk(tmp_path, "ai.test.nested", {"nodes/helpers.py": "X = 1\n"})
        raw = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
        raw["templates"][0]["source"] = "sources/nodes/caller.py"
        (package / "manifest.json").write_text(json.dumps(raw), encoding="utf-8")
        (package / "sources" / "caller.py").rename(package / "sources" / "nodes" / "caller.py")
        assert module_names(package, load_package_manifest(package)) == {"nodes"}
        (package / "sources" / "nodes" / "helpers.py").unlink()
        assert module_names(package, load_package_manifest(package)) == frozenset()

    def test_links_are_not_followed(self, tmp_path):
        from utk_curio.backend.app.packages.repositories.python_modules import module_names

        outside = tmp_path / "outside.py"
        outside.write_text("X = 1\n", encoding="utf-8")
        package, manifest = _package_on_disk(tmp_path / "store", "ai.test.links", {})
        (package / "sources" / "linked.py").symlink_to(outside)
        assert module_names(package, manifest) == frozenset()


# ---------------------------------------------------------------------------
# The one-name rule, at install
# ---------------------------------------------------------------------------

class TestTheInstallerRefusesAModuleNameInUse:
    def test_the_second_package_is_refused_naming_both_and_the_module(self, tmp_curio):
        install_package_from_archive("guest", _archive("ai.test.first", modules={"shared_mod.py": "X = 1\n"}))
        with pytest.raises(InstallerError) as caught:
            install_package_from_archive(
                "guest", _archive("ai.test.second", modules={"shared_mod/core.py": "X = 2\n"}),
            )
        message = str(caught.value)
        assert "ai.test.second@1" in message
        assert "ai.test.first@1" in message
        assert "'shared_mod'" in message
        assert not package_dir("guest", "ai.test.second@1").exists()
        assert package_dir("guest", "ai.test.first@1").is_dir()

    def test_the_upload_route_answers_with_the_reason(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        headers = {"Authorization": f"Bearer {token}"}
        for package_id, status in (("ai.test.first", 201), ("ai.test.second", 400)):
            resp = client.post(
                "/api/packages/upload",
                data={"file": (io.BytesIO(_archive(package_id, modules=HEIGHTS)), "p.curio.zip")},
                headers=headers,
                content_type="multipart/form-data",
            )
            assert resp.status_code == status, resp.get_data(as_text=True)
        error = resp.get_json()["error"]
        assert "'building_height'" in error and "ai.test.first@1" in error and "ai.test.second@1" in error

    def test_a_template_of_the_same_name_is_no_conflict(self, tmp_curio):
        install_package_from_archive("guest", _archive("ai.test.first", templates=("loader",)))
        install_package_from_archive("guest", _archive("ai.test.second", templates=("loader",)))
        assert package_dir("guest", "ai.test.second@1").is_dir()

    def test_two_majors_of_one_package_keep_their_module_names(self, tmp_curio):
        install_package_from_archive("guest", _archive("ai.test.first", modules=HEIGHTS))
        install_package_from_archive("guest", _archive("ai.test.first", major=2, modules=HEIGHTS))
        assert package_dir("guest", "ai.test.first@2").is_dir()

    def test_replacing_a_package_is_no_conflict_with_itself(self, tmp_curio):
        install_package_from_archive("guest", _archive("ai.test.first", modules=HEIGHTS))
        result = install_package_from_archive("guest", _archive("ai.test.first", modules=HEIGHTS), replace=True)
        assert result.replaced_existing is True

    def test_another_accounts_packages_do_not_count(self, tmp_curio):
        install_package_from_archive("guest", _archive("ai.test.first", modules=HEIGHTS))
        install_package_from_archive("7", _archive("ai.test.second", modules=HEIGHTS))
        assert package_dir("7", "ai.test.second@1").is_dir()


class TestArchivesCarryPythonPackages:
    def test_a_module_folder_may_hold_init_py(self, tmp_curio):
        install_package_from_archive("guest", _archive("ai.test.heights", modules=HEIGHTS))
        assert (package_dir("guest", "ai.test.heights@1") / "sources" / "building_height" / "__init__.py").is_file()

    @pytest.mark.parametrize("member", [
        "sources/building_height/__pycache__/scale.cpython-312.pyc",
        "sources/__init__.py/scale.py",
        "sources/_private.py",
    ])
    def test_other_leading_underscores_are_still_refused(self, member):
        from utk_curio.backend.app.packages.repositories.archive import _safe_member_path

        with pytest.raises(InstallerError, match="unsafe segment"):
            _safe_member_path(member)


# ---------------------------------------------------------------------------
# What a run of one of the package's nodes is handed
# ---------------------------------------------------------------------------

class TestARunIsHandedItsPackagesModules:
    def test_a_node_of_the_package_gets_its_sources_folder_and_names(self, tmp_curio):
        from utk_curio.backend.app.packages.service import modules_for_node

        install_package_from_archive("guest", _archive("ai.test.heights", modules={**HEIGHTS, "helpers.py": "X = 1\n"}))
        expected = {
            "root": str(package_dir("guest", "ai.test.heights@1") / "sources"),
            "names": ["building_height", "helpers"],
        }
        assert modules_for_node("guest", "ai.test.heights/caller") == expected
        assert modules_for_node("guest", "ai.test.heights/caller@1") == expected

    @pytest.mark.parametrize("node_type", [
        "curio.builtin/computation-analysis",
        "curio.builtin/computation-analysis@1",
        "PYTHON_COMPUTATION",
        "ai.test.absent/caller",
        "ai.test.heights/not-a-template",
        "ai.test.heights/caller@2",
        "ai.test.plain/caller",
    ])
    def test_nothing_for_every_other_node(self, tmp_curio, node_type):
        from utk_curio.backend.app.packages.service import modules_for_node

        install_package_from_archive("guest", _archive("ai.test.heights", modules=HEIGHTS))
        install_package_from_archive("guest", _archive("ai.test.plain"))
        assert modules_for_node("guest", node_type) is None

    def test_nothing_without_an_account(self, tmp_curio):
        from utk_curio.backend.app.packages.service import modules_for_node

        install_package_from_archive("guest", _archive("ai.test.heights", modules=HEIGHTS))
        assert modules_for_node(None, "ai.test.heights/caller") is None

    def test_with_two_majors_the_dataflows_pin_wins_else_the_highest(self, tmp_curio, monkeypatch):
        from utk_curio.backend.app.packages.application import project_packages
        from utk_curio.backend.app.packages.service import modules_for_node

        for major in (1, 2):
            install_package_from_archive("guest", _archive("ai.test.heights", major=major, modules=HEIGHTS))
        monkeypatch.setattr(
            project_packages, "_lockfile_or_empty",
            lambda user_key, project_id: {"ai.test.heights@1"} if project_id == "pinned" else set(),
        )
        pinned = modules_for_node("guest", "ai.test.heights/caller", "pinned")
        assert pinned["root"] == str(package_dir("guest", "ai.test.heights@1") / "sources")
        unpinned = modules_for_node("guest", "ai.test.heights/caller", "other")
        assert unpinned["root"] == str(package_dir("guest", "ai.test.heights@2") / "sources")


# ---------------------------------------------------------------------------
# Save into a package: its own modules are not PyPI dependencies
# ---------------------------------------------------------------------------

def test_saving_into_a_package_does_not_declare_its_modules_as_libraries(tmp_curio):
    from utk_curio.backend.app.packages.builder.factory import build_package_archive

    # A folder of modules without __init__.py is a namespace package.
    modules = {k: v for k, v in HEIGHTS.items() if not k.endswith("__init__.py")}
    install_package_from_archive("guest", _archive("ai.test.heights", modules=modules))
    draft = {
        "manifest": _manifest("ai.test.heights"),
        "sources": {"caller": {"filename": "caller.py", "code": (
            "import numpy\n"
            "from building_height.convert_to_raster import convert_raster\n"
            "return convert_raster(numpy.int64(21))\n"
        )}},
    }
    built = build_package_archive(draft, onto=package_dir("guest", "ai.test.heights@1"))
    assert "numpy" in built.manifest.python_deps
    assert "building_height" not in built.manifest.python_deps
    with zipfile.ZipFile(io.BytesIO(built.archive)) as zf:
        assert "sources/building_height/convert_to_raster.py" in zf.namelist()


class TestThePackageBuilderLeavesTheOwnModulesOut:
    """The agent Package Builder scans every file it is handed. An import of
    the package's own module is no PyPI dependency there either: an install
    would otherwise fetch whatever PyPI package has that name."""

    @staticmethod
    def _request(files):
        from utk_curio.backend.app.packages.builder.models import parse_build_request

        return parse_build_request({
            "mode": "create",
            "target": "ai.test.heights@1",
            "manifest": {
                "id": "ai.test.heights", "compatibility": {"major": 1},
                "templates": [{"id": "caller", "source": "sources/caller.py"}],
            },
            "files": {path: {"text": text} for path, text in files.items()},
        })

    def test_a_module_the_draft_ships_is_not_a_dependency(self):
        from utk_curio.backend.app.packages.builder.deps import merge_declared_and_detected

        request = self._request({
            "sources/caller.py": "import numpy\nfrom scripts.convert import convert\nreturn convert(arg)\n",
            "sources/scripts/convert.py": "import shapely\nimport scripts.scale\nfrom .scale import FACTOR\n",
            "sources/scripts/scale.py": "FACTOR = 2\n",
        })
        python, _js, findings = merge_declared_and_detected(request)
        assert sorted(python) == ["numpy", "shapely"]
        assert [f.message for f in findings if "scripts" in f.message] == []

    def test_a_module_the_extended_package_keeps_is_not_a_dependency(self):
        from utk_curio.backend.app.packages.builder.deps import merge_declared_and_detected

        request = self._request({"sources/caller.py": "from scripts.convert import convert\nreturn convert(arg)\n"})
        python, _js, _findings = merge_declared_and_detected(request, ("sources/scripts/convert.py",))
        assert python == {}


# ---------------------------------------------------------------------------
# The shipped catalog keeps the rule the installer enforces
# ---------------------------------------------------------------------------

def test_no_two_shipped_packages_ship_a_module_of_the_same_name():
    """The seeder copies shipped packages without going through the installer,
    so the catalog itself has to keep the one-name rule. The committed catalog,
    named directly, as ``test_shipped_catalog.py`` names it."""
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
    from utk_curio.backend.app.packages.repositories.python_modules import module_names

    catalog = Path(__file__).resolve().parents[4] / "packages"
    owners: dict[str, str] = {}
    shipped = sorted(p for p in catalog.glob("*@*") if (p / "manifest.json").is_file())
    assert shipped, f"no packages under {catalog}; this test would be vacuous"
    for package in shipped:
        package_id = package.name.rsplit("@", 1)[0]
        for name in module_names(package, load_package_manifest(package)):
            owner = owners.setdefault(name, package_id)
            assert owner == package_id, f"{package.name} and {owner} both ship the module {name!r}"
