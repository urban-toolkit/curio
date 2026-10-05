"""#468: a template imports the Python modules bundled beside it in its package.

The backend sends ``package_modules: {"root": <the package's sources folder>,
"names": [...]}`` for a node whose package ships modules. Both execution modes
link the named modules into a folder of the run's own and make it importable
until the run ends: ``execute_code`` in process, ``child.run_node`` under fork
isolation (here without the fork; ``test_isolation_linux.py`` runs the real
zygote). The rule for a long-lived worker: nothing a run imported from its
package outlives the run, so an updated package, or another package with a
module of the same name, never gets a stale module.

New code is imported inside each test, so a checkout without it fails each
test on its own instead of the whole module at collection.
"""

import os
import shutil
import sys

import pytest

from utk_curio.sandbox.isolation import child, protocol
from utk_curio.sandbox.util import staging
from utk_curio.sandbox.util.db import init_db, release_connection
from utk_curio.sandbox.util.parsers import load_from_duckdb

# The layout of #468's report: a small caller template beside a package of
# modules, which imports a sibling relatively.
HEIGHTS = {
    "building_height/__init__.py": "",
    "building_height/convert_to_raster.py": (
        "from .scale import FACTOR\n"
        "\n"
        "def convert_raster(value):\n"
        "    return value * FACTOR\n"
    ),
    "building_height/scale.py": "FACTOR = 2\n",
}

CALLER = (
    "    from building_height.convert_to_raster import convert_raster\n"
    "    return convert_raster(21)\n"
)

PACKAGE_NODE = "ai.test.heights/caller"


def _sources(root, modules, templates=("caller.py",)):
    """A package's ``sources/`` folder holding *modules* and template files."""
    sources = root / "sources"
    for relative, text in modules.items():
        path = sources / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for name in templates:
        (sources / name).write_text("return 'the template itself'\n", encoding="utf-8")
    return sources


def _spec(sources, *names):
    return {"root": str(sources), "names": list(names)}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    monkeypatch.setenv("CURIO_SHARED_DATA", str(tmp_path / "data"))
    release_connection()
    init_db()
    yield tmp_path
    release_connection()


@pytest.fixture
def run_in_process(workspace):
    from utk_curio.sandbox.app.worker import _worker_init, execute_code

    _worker_init()

    def run(code, node_type=PACKAGE_NODE, **kwargs):
        return execute_code(code, "", node_type, "", save_dataset=False, **kwargs)

    return run


def _namespace():
    import numpy as np
    import pandas as pd

    return {"np": np, "pd": pd}


def _run_child(scratch_dir, code, package_modules=None, session_imports=()):
    """``child.run_node`` with the modules staged the way the parent stages them."""
    staged = staging.stage_package_modules(package_modules, scratch_dir) if package_modules else None
    request = protocol.build_exec_request(
        code=code, node_type=PACKAGE_NODE, data_type="", scratch_dir=scratch_dir,
        input_spec={"kind": "none"}, session_imports=list(session_imports),
        package_modules=staged,
    )
    return child.run_node(request, _namespace)


def _loaded(prefix):
    return sorted(key for key in sys.modules if key == prefix or key.startswith(prefix + "."))


# ---------------------------------------------------------------------------
# A template imports its sibling module, in both modes
# ---------------------------------------------------------------------------

def test_an_in_process_template_imports_the_module_bundled_beside_it(run_in_process, tmp_path):
    sources = _sources(tmp_path / "heights", HEIGHTS)
    result = run_in_process(CALLER, package_modules=_spec(sources, "building_height"))
    assert result["stderr"] == "", result["stderr"]
    assert load_from_duckdb(result["output"]["path"]) == 42


def test_an_isolated_child_imports_the_module_bundled_beside_it(tmp_path):
    sources = _sources(tmp_path / "heights", HEIGHTS)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    result = _run_child(scratch, CALLER, _spec(sources, "building_height"))
    assert result["ok"], result["stderr"]
    assert result["output"] == {"kind": "int", "value": 42}


def test_the_exec_route_hands_the_modules_to_the_run(workspace, tmp_path):
    from utk_curio.sandbox.app import api, app

    sources = _sources(tmp_path / "heights", HEIGHTS)
    previous = api._isolation_state
    api._isolation_state = False  # in process, whatever this host would resolve
    try:
        response = app.test_client().post("/exec", json={
            "code": CALLER, "file_path": "", "nodeType": PACKAGE_NODE, "dataType": "",
            "save_dataset": False, "package_modules": _spec(sources, "building_height"),
        })
    finally:
        api._isolation_state = previous
    assert response.status_code == 200, response.data
    body = response.get_json()
    assert body["stderr"] == "", body["stderr"]
    assert load_from_duckdb(body["output"]["path"]) == 42


def test_a_module_folder_without_init_imports_too(run_in_process, tmp_path):
    """A folder of modules with no ``__init__.py`` is a namespace package, and
    its relative imports work the same."""
    layout = {k: v for k, v in HEIGHTS.items() if not k.endswith("__init__.py")}
    sources = _sources(tmp_path / "heights", layout)
    result = run_in_process(CALLER, package_modules=_spec(sources, "building_height"))
    assert result["stderr"] == "", result["stderr"]
    assert load_from_duckdb(result["output"]["path"]) == 42


# ---------------------------------------------------------------------------
# The cache rule: nothing a run imported from its package outlives the run
# ---------------------------------------------------------------------------

def test_a_run_leaves_no_module_and_no_path_behind(run_in_process, tmp_path):
    sources = _sources(tmp_path / "heights", HEIGHTS)
    path_before = list(sys.path)
    result = run_in_process(CALLER, package_modules=_spec(sources, "building_height"))
    assert result["stderr"] == "", result["stderr"]
    assert _loaded("building_height") == []
    assert sys.path == path_before
    assert not any("package_modules" in str(key) for key in sys.path_importer_cache)
    # Nor a folder: the run's own copy of the modules is gone with it.
    from utk_curio.sandbox.isolation.supervisor import scratch_root
    from utk_curio.sandbox.util.parsers import _shared_data_dir

    root = scratch_root(str(_shared_data_dir()))
    assert not os.path.isdir(root) or os.listdir(root) == []


def test_another_node_cannot_import_a_packages_modules(run_in_process, tmp_path):
    sources = _sources(tmp_path / "heights", HEIGHTS)
    first = run_in_process(CALLER, session_id="s-468", package_modules=_spec(sources, "building_height"))
    assert first["stderr"] == "", first["stderr"]
    other = run_in_process(
        "    import building_height\n    return 1\n",
        node_type="curio.builtin/computation-analysis", session_id="s-468",
    )
    assert other["output"]["path"] == ""
    assert "No module named 'building_height'" in other["stderr"]


def test_an_updated_package_is_imported_afresh(run_in_process, tmp_path):
    sources = _sources(tmp_path / "heights", HEIGHTS)
    spec = _spec(sources, "building_height")
    first = run_in_process(CALLER, package_modules=spec)
    assert load_from_duckdb(first["output"]["path"]) == 42, first["stderr"]

    # An update replaces the package's files, as a reinstall does.
    shutil.rmtree(sources)
    _sources(tmp_path / "heights", {**HEIGHTS, "building_height/scale.py": "FACTOR = 3\n"})
    second = run_in_process(CALLER, package_modules=spec)
    assert second["stderr"] == "", second["stderr"]
    assert load_from_duckdb(second["output"]["path"]) == 63


def test_two_packages_with_a_module_of_the_same_name_each_import_their_own(run_in_process, tmp_path):
    first = _sources(tmp_path / "a", {"shared_name.py": "WHO = 'a'\n"})
    second = _sources(tmp_path / "b", {"shared_name.py": "WHO = 'b'\n"})
    code = "    import shared_name\n    return shared_name.WHO\n"
    seen = []
    for sources in (first, second, first):
        result = run_in_process(code, package_modules=_spec(sources, "shared_name"))
        assert result["stderr"] == "", result["stderr"]
        seen.append(load_from_duckdb(result["output"]["path"]))
    assert seen == ["a", "b", "a"]


def test_the_child_follows_the_same_rule(tmp_path):
    """``run_node`` runs here in this process, so it shows the child's cleanup
    too: in a real child the process ends with the run anyway."""
    first = _sources(tmp_path / "a", {"shared_name.py": "WHO = 'a'\n"})
    second = _sources(tmp_path / "b", {"shared_name.py": "WHO = 'b'\n"})
    code = "    import shared_name\n    return shared_name.WHO\n"
    seen = []
    for index, sources in enumerate((first, second)):
        scratch = tmp_path / f"scratch{index}"
        scratch.mkdir()
        result = _run_child(scratch, code, _spec(sources, "shared_name"))
        assert result["ok"], result["stderr"]
        seen.append(result["output"]["value"])
    assert seen == ["a", "b"]
    assert _loaded("shared_name") == []


# ---------------------------------------------------------------------------
# A package's module imports are its own nodes' alone (#158 sharing)
# ---------------------------------------------------------------------------

SHARING = (
    "    import statistics\n"
    "    from building_height.convert_to_raster import convert_raster\n"
    "    return convert_raster(21)\n"
)


def test_in_process_a_later_node_gets_the_library_import_but_not_the_modules(run_in_process, tmp_path):
    sources = _sources(tmp_path / "heights", HEIGHTS)
    first = run_in_process(SHARING, session_id="s-share", package_modules=_spec(sources, "building_height"))
    assert load_from_duckdb(first["output"]["path"]) == 42, first["stderr"]
    later = run_in_process(
        "    return ','.join(n for n in ('convert_raster', 'statistics') if n in globals())\n",
        node_type="curio.builtin/computation-analysis", session_id="s-share",
    )
    assert later["stderr"] == "", later["stderr"]
    assert load_from_duckdb(later["output"]["path"]) == "statistics"


def test_isolated_the_package_module_import_is_not_replayed(tmp_path):
    sources = _sources(tmp_path / "heights", HEIGHTS)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    result = _run_child(scratch, SHARING, _spec(sources, "building_height"))
    assert result["ok"], result["stderr"]
    assert result["imports"] == ["import statistics"]


def test_one_statement_mixing_a_library_and_a_module_keeps_the_library():
    statements = child._hoisted_import_statements(
        "    import statistics, building_height.scale as scale\n", skip=("building_height",),
    )
    assert statements == ["import statistics"]


# ---------------------------------------------------------------------------
# A run never silently gets another module of the same name
# ---------------------------------------------------------------------------

def test_a_module_named_like_one_already_loaded_is_refused_by_name(run_in_process, tmp_path):
    sources = _sources(tmp_path / "shadow", {"json.py": "WHO = 'the package'\n"})
    result = run_in_process(
        "    import json\n    return json.WHO\n", package_modules=_spec(sources, "json"),
    )
    assert result["output"]["path"] == ""
    assert "ships the module 'json'" in result["stderr"]
    assert "already loaded from" in result["stderr"]


def test_the_child_refuses_it_the_same_way(tmp_path):
    sources = _sources(tmp_path / "shadow", {"json.py": "WHO = 'the package'\n"})
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    result = _run_child(scratch, "    import json\n    return json.WHO\n", _spec(sources, "json"))
    assert not result["ok"]
    assert "ships the module 'json'" in result["stderr"]


# ---------------------------------------------------------------------------
# Staging: the named modules, and nothing else
# ---------------------------------------------------------------------------

def test_only_the_named_modules_are_staged(tmp_path):
    sources = _sources(tmp_path / "heights", {**HEIGHTS, "notes.py": "X = 1\n"})
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    staged = staging.stage_package_modules(_spec(sources, "building_height"), scratch)
    assert staged == {"root": "package_modules", "names": ["building_height"]}
    target = scratch / "package_modules"
    files = sorted(p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file())
    assert files == [
        "building_height/__init__.py",
        "building_height/convert_to_raster.py",
        "building_height/scale.py",
    ]
    source, copy = sources / "building_height" / "scale.py", target / "building_height" / "scale.py"
    if hasattr(os, "link"):
        assert os.stat(source).st_ino == os.stat(copy).st_ino


def test_a_link_out_of_a_module_folder_is_not_followed(tmp_path):
    sources = _sources(tmp_path / "heights", HEIGHTS)
    secret = tmp_path / "secret.py"
    secret.write_text("SECRET = 1\n", encoding="utf-8")
    (sources / "building_height" / "escape.py").symlink_to(secret)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    staging.stage_package_modules(_spec(sources, "building_height"), scratch)
    assert not (scratch / "package_modules" / "building_height" / "escape.py").exists()


def test_nothing_to_stage_is_none(tmp_path):
    sources = _sources(tmp_path / "heights", HEIGHTS)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    assert staging.stage_package_modules(_spec(sources, "missing"), scratch) is None
    assert staging.stage_package_modules({"root": str(tmp_path / "nope"), "names": ["x"]}, scratch) is None
    assert staging.stage_package_modules(None, scratch) is None


def test_the_request_carries_the_staged_folder(tmp_path):
    staged = {"root": "package_modules", "names": ["building_height"]}
    request = protocol.build_exec_request(
        code="", node_type="x", data_type="", scratch_dir=tmp_path,
        input_spec={"kind": "none"}, package_modules=staged,
    )
    assert request["package_modules"] == staged
    plain = protocol.build_exec_request(
        code="", node_type="x", data_type="", scratch_dir=tmp_path, input_spec={"kind": "none"},
    )
    assert plain["package_modules"] is None


def test_the_route_keeps_only_well_formed_names():
    from utk_curio.sandbox.util.package_modules import shape

    assert shape({"root": "/p/sources", "names": ["b", "a", "not-a-name", "class", 3]}) == {
        "root": "/p/sources", "names": ["a", "b"],
    }
    assert shape({"root": "/p/sources", "names": ["../up"]}) is None
    assert shape({"names": ["a"]}) is None
    assert shape("sources") is None
    assert shape(None) is None
