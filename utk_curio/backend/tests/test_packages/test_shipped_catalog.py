"""Every committed package under ``packages/`` must load and serialize.

``test_builtin_package.py`` covers ``curio.builtin@1`` specifically. This walks
the whole shipped catalog, so a new entry is exercised the moment it is
committed rather than whenever someone remembers to add a test: both
``curio.example-ui@1`` and ``curio.weather@1`` landed with no coverage at all.

The catalog is baked into the deploy image, so a manifest that fails to load
here is a package that silently vanishes from every user's Browse tab.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path, PurePosixPath

import pytest

from utk_curio.backend.app.execution.code_references import references_as_names
from utk_curio.backend.app.packages.domain.dependency_scanner import scan_python_imports
from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
from utk_curio.backend.app.packages.repositories.python_modules import module_names
from utk_curio.backend.app.packages.domain.versions import merge_python_deps
from utk_curio.backend.app.packages.schemas.responses import package_payload

# The COMMITTED catalog, named directly rather than through
# ``catalog_root()``: these assertions are about what the repository ships,
# and the runtime root is relocatable (``CURIO_PACKAGES_ROOT``) so a test
# session gets its own copy to publish into.
REAL_CATALOG = Path(__file__).resolve().parents[4] / "packages"
CATALOG = REAL_CATALOG
PACKAGE_DIRS = sorted(p for p in CATALOG.glob("*@*") if (p / "manifest.json").is_file())
IDS = [p.name for p in PACKAGE_DIRS]


def test_the_catalog_is_not_empty():
    # Guards the walk itself: a bad glob would turn every test below into a
    # vacuous pass.
    assert PACKAGE_DIRS, f"no packages discovered under {CATALOG}"


@pytest.mark.parametrize("package_root", PACKAGE_DIRS, ids=IDS)
def test_manifest_loads(package_root: Path):
    assert load_package_manifest(package_root) is not None


@pytest.mark.parametrize("package_root", PACKAGE_DIRS, ids=IDS)
def test_manifest_serializes_to_a_catalog_payload(package_root: Path):
    payload = package_payload(load_package_manifest(package_root))
    assert payload["dirName"] == package_root.name
    assert payload["templates"], "a package with no templates adds nothing to the palette"


@pytest.mark.parametrize("package_root", PACKAGE_DIRS, ids=IDS)
def test_dir_name_matches_the_declared_id_and_major(package_root: Path):
    raw = json.loads((package_root / "manifest.json").read_text(encoding="utf-8"))
    expected = f"{raw['id']}@{raw['compatibility']['major']}"
    assert package_root.name == expected


@pytest.mark.parametrize("package_root", PACKAGE_DIRS, ids=IDS)
def test_declared_sources_and_behavior_bundle_exist(package_root: Path):
    """A template's ``source`` and the package's ``behaviorScript`` are paths.

    A missing bundle is the failure mode AUTHORING-NODES.md calls out: the node
    renders as an empty code editor with only a console warning.
    """
    raw = json.loads((package_root / "manifest.json").read_text(encoding="utf-8"))

    bundle = raw.get("behaviorScript")
    if bundle:
        assert (package_root / bundle).is_file(), f"missing behaviorScript {bundle}"

    for template in raw["templates"]:
        source = template.get("source")
        if source:
            assert (package_root / source).is_file(), (
                f"template {template['id']} declares a missing source {source}"
            )

# ---------------------------------------------------------------------------
# Co-installability with the mandatory built-in package (#154)
# ---------------------------------------------------------------------------
#
# ``curio.builtin@1`` is force-reseeded for every user and refuses to uninstall,
# so it is present in every ``/resolve`` probe. A shipped package whose Python
# ranges do not intersect builtin's is therefore not "conflicting", it is
# *uninstallable* - and the install dialog's only advice ("uninstall one of the
# conflicting packages") cannot be followed.
#
# ``ai.utk.uhvi@1`` shipped that way: ``geopandas ^0.14`` against builtin's
# ``>=1.1.3``. Generalized here so the next package with a stray upper bound
# fails in CI instead of in a user's install dialog.

BUILTIN_DIR = "curio.builtin@1"


def _raw_python_deps(package_root: Path) -> dict[str, str]:
    raw = json.loads((package_root / "manifest.json").read_text(encoding="utf-8"))
    return (raw.get("dependencies") or {}).get("python") or {}


@pytest.mark.parametrize(
    "package_root",
    [p for p in PACKAGE_DIRS if p.name != BUILTIN_DIR],
    ids=[p.name for p in PACKAGE_DIRS if p.name != BUILTIN_DIR],
)
def test_python_deps_are_co_installable_with_the_builtin_package(package_root: Path):
    builtin = CATALOG / BUILTIN_DIR
    assert builtin.is_dir(), f"{BUILTIN_DIR} missing from {CATALOG}"

    _, conflicts = merge_python_deps([
        (BUILTIN_DIR, _raw_python_deps(builtin)),
        (package_root.name, _raw_python_deps(package_root)),
    ])
    assert not conflicts, (
        f"{package_root.name} cannot be installed alongside {BUILTIN_DIR}: "
        + ", ".join(
            c.package + " (" + " vs ".join(r for _, r in c.ranges) + ")"
            for c in conflicts
        )
        + ". Relax this package's range - the built-in package is mandatory and "
        "read-only, so the user has no way to resolve this themselves."
    )


def test_the_whole_shipped_catalog_resolves_together():
    """Not just pairwise: installing everything at once must also resolve.

    Two packages can each be fine against builtin and still disagree with each
    other (uhvi's rasterio floor vs curio.weather's, for instance).
    """
    _, conflicts = merge_python_deps(
        [(p.name, _raw_python_deps(p)) for p in PACKAGE_DIRS]
    )
    assert not conflicts, (
        "the shipped catalog cannot be fully installed: "
        + ", ".join(c.package for c in conflicts)
    )


# ---------------------------------------------------------------------------
# The manifest declares what the sources import
# ---------------------------------------------------------------------------
#
# The Package Builder and Save into a package scan a package's code for its
# imports (``references_as_names``, then ``scan_python_imports``) and add each
# library the manifest does not declare at ``*``. So a shipped package declares
# every library its sources import, those ``curio.builtin@1`` also declares
# included: ``curio.weather@1`` left ``geopandas`` and ``pandas`` to the
# built-in package, and a Save into it added both unpinned.


def _libraries_imported_by(source: str, own_modules: frozenset[str]) -> list[str]:
    """The libraries *source* imports, named as the builder names them: its
    module-level imports, scanned as the builder scans them, and the imports
    at the top of each of its functions, through the same scanner."""
    code = references_as_names(source)
    tree = ast.parse(code)
    found = set(scan_python_imports(code, own_modules))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = ast.unparse(ast.Module(body=node.body, type_ignores=[]))
            found.update(scan_python_imports(body, own_modules))
    return sorted(found)


@pytest.mark.parametrize("package_root", PACKAGE_DIRS, ids=IDS)
def test_the_manifest_declares_every_library_the_sources_import(package_root: Path):
    """Every library a ``.py`` file under ``sources/`` imports, at module level
    or in a function, is in ``dependencies.python`` under the name the scanner
    gives it, the name a Save merges by. The scanner leaves out the standard
    library, Curio's own modules and the package's own modules. A source that
    does not parse fails here, since the scanner would read nothing in it."""
    own_modules = module_names(package_root, load_package_manifest(package_root))
    declared = set(_raw_python_deps(package_root))
    undeclared: dict[str, list[str]] = {}
    for source in sorted((package_root / "sources").rglob("*.py")):
        where = source.relative_to(package_root).as_posix()
        for library in _libraries_imported_by(source.read_text(encoding="utf-8"), own_modules):
            if library not in declared:
                undeclared.setdefault(library, []).append(where)
    assert not undeclared, (
        f"{package_root.name} imports libraries its manifest does not declare: "
        + "; ".join(f"{library} ({', '.join(files)})" for library, files in sorted(undeclared.items()))
    )


@pytest.mark.parametrize("package_root", PACKAGE_DIRS, ids=IDS)
def test_sources_do_not_read_the_examples_data_directory(package_root: Path):
    """A shipped node template must not depend on ``docs/``.

    ``MANIFEST.in`` does not include ``docs/``, so a source that reads
    ``docs/examples/data/...`` works on a repo checkout and silently breaks in
    every pip install and every isolated sandbox. ``curio.weather@1``'s three
    loader templates did exactly that until the Data Catalog migration; they now
    resolve their inputs with ``curio_data_path("<id>")``.

    This is the check that catches migrating an example's nodes but forgetting
    the package whose templates those nodes were copied from.
    """
    offenders = []
    for source in sorted(package_root.glob("sources/*.py")):
        if "docs/examples/data" in source.read_text(encoding="utf-8"):
            offenders.append(source.name)
    assert not offenders, (
        f"{package_root.name}: {offenders} read from docs/examples/data; "
        f'resolve the file through curio_data_path("<id>") instead'
    )


# ---------------------------------------------------------------------------
# ai.utk.uhvi@1 loader defaults (#585)
# ---------------------------------------------------------------------------

UHVI_DIR = CATALOG / "ai.utk.uhvi@1"


def _input_text_default(source: Path) -> str:
    """The default of the one text widget *source* references (#662).

    The default lives in the manifest's template ``widgets``; *source* names
    the widget with one ``[!! name !!]`` reference.
    """
    manifest = json.loads((source.parent.parent / "manifest.json").read_text(encoding="utf-8"))
    rel = f"sources/{source.name}"
    (template,) = [t for t in manifest["templates"] if t.get("source") == rel]
    (widget,) = [w for w in template.get("widgets", []) if w.get("type") == "text"]
    refs = re.findall(r"\[!!\s*(\w+)\s*!!\]", source.read_text(encoding="utf-8"))
    assert refs == [widget["name"]], (source.name, refs)
    return widget["default"]


def test_uhvi_loader_defaults_share_one_folder_and_match_the_readme():
    """The raster and zones loaders default to the Milan files the README names.

    The README puts both files under ``./milan/``. The zones loader followed it
    and the raster loader did not, so a workspace laid out as the README says
    left the raster loader pointing at a file that is not there.
    """
    raster = _input_text_default(UHVI_DIR / "sources" / "uhvi-load.py")
    zones = _input_text_default(UHVI_DIR / "sources" / "uhvi-zones.py")
    assert PurePosixPath(raster).parent == PurePosixPath(zones).parent, (raster, zones)

    readme = (UHVI_DIR / "README.md").read_text(encoding="utf-8")
    for default in (raster, zones):
        assert f"`{default}`" in readme, f"README.md does not give the loader default {default}"
