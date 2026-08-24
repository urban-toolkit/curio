"""Tests for :mod:`utk_curio.backend.app.packages.resolver`.

Focused unit tests on the pure-Python core (no DB needed) plus a
fixture-installed scenario for the project-wide resolve.
"""

from __future__ import annotations

import pytest

from utk_curio.backend.app.packages.resolver import (
    DepConflict,
    Range,
    ResolverError,
    merge_python_deps,
    parse_range,
    parse_version,
    resolve_for_project,
)


# ---------------------------------------------------------------------------
# Semver parsing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1.2.3", (1, 2, 3)),
        ("1.2", (1, 2, 0)),
        ("7", (7, 0, 0)),
        ("0.5.0-alpha", (0, 5, 0)),
    ],
)
def test_parse_version(raw, expected):
    assert parse_version(raw) == expected


def test_parse_version_rejects_garbage():
    with pytest.raises(ResolverError):
        parse_version("v2025")


@pytest.mark.parametrize(
    "raw,expected_lo,expected_hi",
    [
        ("*",          (0, 0, 0), None),
        ("^1.2.3",     (1, 2, 3), (2, 0, 0)),
        ("~1.2.3",     (1, 2, 3), (1, 3, 0)),
        ("~1.2",       (1, 2, 0), (1, 3, 0)),
        ("==1.2.3",    (1, 2, 3), (1, 2, 4)),
        ("1.2.3",      (1, 2, 3), (1, 2, 4)),
        (">=1.2",      (1, 2, 0), None),
        ("<2.0",       (0, 0, 0), (2, 0, 0)),
        (">=1.0,<2.0", (1, 0, 0), (2, 0, 0)),
    ],
)
def test_parse_range(raw, expected_lo, expected_hi):
    rng = parse_range(raw)
    assert rng.lo == expected_lo
    assert rng.hi == expected_hi


def test_parse_range_unsatisfiable_pair():
    with pytest.raises(ResolverError):
        parse_range(">=2.0,<1.0")


# ---------------------------------------------------------------------------
# Range intersection
# ---------------------------------------------------------------------------

def test_range_intersection_yields_open_lower():
    a = Range(lo=(1, 0, 0), hi=(2, 0, 0))
    b = Range(lo=(1, 5, 0), hi=None)
    out = a.intersect(b)
    assert out == Range(lo=(1, 5, 0), hi=(2, 0, 0))


def test_range_intersection_empty():
    a = Range(lo=(1, 0, 0), hi=(2, 0, 0))
    b = Range(lo=(2, 0, 0), hi=(3, 0, 0))
    assert a.intersect(b) is None


# ---------------------------------------------------------------------------
# Dep merging across packages
# ---------------------------------------------------------------------------

def test_merge_python_deps_compatible():
    merged, conflicts = merge_python_deps([
        ("alpha@1", {"rasterio": "^1.3"}),
        ("beta@1",  {"rasterio": ">=1.3.5,<2.0"}),
    ])
    assert conflicts == []
    # Lower bound rises to 1.3.5 (taken from beta), upper bound stays at 2.0.0.
    assert merged["rasterio"] == ">=1.3.5,<2.0.0"


def test_merge_python_deps_conflict():
    merged, conflicts = merge_python_deps([
        ("alpha@1", {"rasterio": "^1.3"}),
        ("beta@1",  {"rasterio": "^2.0"}),
    ])
    assert "rasterio" not in merged
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert isinstance(conflict, DepConflict)
    assert conflict.package == "rasterio"
    packages_in_conflict = {p for (p, _r) in conflict.ranges}
    assert packages_in_conflict == {"alpha@1", "beta@1"}


def test_merge_python_deps_disjoint_packageages():
    merged, conflicts = merge_python_deps([
        ("alpha@1", {"numpy": "^1.26"}),
        ("beta@1",  {"shapely": "^2.0"}),
    ])
    assert conflicts == []
    assert set(merged) == {"numpy", "shapely"}


# ---------------------------------------------------------------------------
# Package DAG + project-level resolve
# ---------------------------------------------------------------------------

def _kind(template_id: str = "k") -> dict:
    return {
        "id": template_id,
        "label": template_id.title(),
        "category": "computation",
        "engine": "python",
        "editor": "code",
        "hasCode": True,
        "hasWidgets": False,
        "hasGrammar": False,
        "inputPorts": [],
        "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
        "templateDir": f"starters/{template_id}",
        "defaultTemplate": f"starters/{template_id}/Default.py",
    }


def test_resolve_for_project_pulls_transitive(tmp_curio, install_packageage, manifest_dict):
    install_packageage(
        "guest",
        manifest=manifest_dict(
            package_id="ai.test.base", major=1,
            python_deps={"numpy": "^1.26"},
            kinds=[_kind("base-kind")],
        ),
        sources={"base-kind": {"Default.py": "def run():\n    return {}\n"}},
    )
    install_packageage(
        "guest",
        manifest=manifest_dict(
            package_id="ai.test.leaf", major=1,
            python_deps={"rasterio": "^1.3"},
            package_deps={"ai.test.base": "^1.0"},
            kinds=[_kind("leaf-kind")],
        ),
        sources={"leaf-kind": {"Default.py": "def run():\n    return {}\n"}},
    )
    result = resolve_for_project("guest", ["ai.test.leaf@1"])
    dirs = [p["dirName"] for p in result.installed_packageages]
    assert dirs == ["ai.test.base@1", "ai.test.leaf@1"]
    assert set(result.python_deps) == {"numpy", "rasterio"}
    assert result.conflicts == ()


def test_resolve_for_project_reports_conflict(tmp_curio, install_packageage, manifest_dict):
    install_packageage(
        "guest",
        manifest=manifest_dict(
            package_id="ai.test.alpha", major=1,
            python_deps={"rasterio": "^1.3"},
            kinds=[_kind("alpha-kind")],
        ),
        sources={"alpha-kind": {"Default.py": "def run():\n    return {}\n"}},
    )
    install_packageage(
        "guest",
        manifest=manifest_dict(
            package_id="ai.test.beta", major=1,
            python_deps={"rasterio": "^2.0"},
            kinds=[_kind("beta-kind")],
        ),
        sources={"beta-kind": {"Default.py": "def run():\n    return {}\n"}},
    )
    result = resolve_for_project(
        "guest", ["ai.test.alpha@1", "ai.test.beta@1"]
    )
    assert any(c.package == "rasterio" for c in result.conflicts)
    assert result.ok is False


def test_resolve_for_project_missing_packageage_dep(tmp_curio, install_packageage, manifest_dict):
    install_packageage(
        "guest",
        manifest=manifest_dict(
            package_id="ai.test.leaf", major=1,
            python_deps={},
            package_deps={"ai.test.missing": "^1.0"},
            kinds=[_kind("leaf-kind")],
        ),
        sources={"leaf-kind": {"Default.py": "def run():\n    return {}\n"}},
    )
    with pytest.raises(ResolverError, match="not installed"):
        resolve_for_project("guest", ["ai.test.leaf@1"])


def test_resolve_for_project_detects_cycle(tmp_curio, install_packageage, manifest_dict):
    install_packageage(
        "guest",
        manifest=manifest_dict(
            package_id="ai.test.a", major=1,
            python_deps={},
            package_deps={"ai.test.b": "^1.0"},
            kinds=[_kind("a-kind")],
        ),
        sources={"a-kind": {"Default.py": "def run():\n    return {}\n"}},
    )
    install_packageage(
        "guest",
        manifest=manifest_dict(
            package_id="ai.test.b", major=1,
            python_deps={},
            package_deps={"ai.test.a": "^1.0"},
            kinds=[_kind("b-kind")],
        ),
        sources={"b-kind": {"Default.py": "def run():\n    return {}\n"}},
    )
    with pytest.raises(ResolverError, match="cycle"):
        resolve_for_project("guest", ["ai.test.a@1"])


def test_resolve_empty():
    result = resolve_for_project("guest", [])
    assert result.installed_packageages == ()
    assert result.python_deps == {}
    assert result.conflicts == ()


def test_resolve_for_project_duplicate_packageage_id_requires_at_major(
    tmp_curio, install_packageage, manifest_dict,
):
    kind = _kind("k1")
    install_packageage(
        "guest",
        manifest=manifest_dict(
            package_id="ai.test.shared", major=1, kinds=[kind],
        ),
        sources={"k1": {"Default.py": "def run():\n    return {}\n"}},
    )
    install_packageage(
        "guest",
        manifest=manifest_dict(
            package_id="ai.test.shared", major=2, kinds=[kind],
        ),
        sources={"k1": {"Default.py": "def run():\n    return {}\n"}},
    )
    install_packageage(
        "guest",
        manifest=manifest_dict(
            package_id="ai.test.leaf", major=1,
            package_deps={"ai.test.shared": "^1.0"},
            kinds=[_kind("leaf-kind")],
        ),
        sources={"leaf-kind": {"Default.py": "def run():\n    return {}\n"}},
    )
    with pytest.raises(ResolverError, match="ambiguous"):
        resolve_for_project("guest", ["ai.test.leaf@1"])


def test_resolve_for_project_packageage_dep_at_major(tmp_curio, install_packageage, manifest_dict):
    install_packageage(
        "guest",
        manifest=manifest_dict(
            package_id="ai.test.pick", major=1, kinds=[_kind("a")],
        ),
        sources={"a": {"Default.py": "def run():\n    return {}\n"}},
    )
    install_packageage(
        "guest",
        manifest=manifest_dict(
            package_id="ai.test.pick", major=2, kinds=[_kind("b")],
        ),
        sources={"b": {"Default.py": "def run():\n    return {}\n"}},
    )
    install_packageage(
        "guest",
        manifest=manifest_dict(
            package_id="ai.test.leaf", major=1,
            package_deps={"ai.test.pick@2": "^1.0"},
            kinds=[_kind("leaf-kind")],
        ),
        sources={"leaf-kind": {"Default.py": "def run():\n    return {}\n"}},
    )
    result = resolve_for_project("guest", ["ai.test.leaf@1"])
    dirs = [p["dirName"] for p in result.installed_packageages]
    assert dirs == ["ai.test.pick@2", "ai.test.leaf@1"]


def test_lockfile_to_dict(tmp_curio, install_packageage, manifest_dict):
    install_packageage(
        "guest",
        manifest=manifest_dict(
            package_id="ai.test.demo", major=1,
            python_deps={"numpy": "^1.26"},
        ),
    )
    result = resolve_for_project("guest", ["ai.test.demo@1"])
    lock = result.to_lockfile()
    assert lock["pythonDeps"] == {"numpy": ">=1.26.0,<2.0.0"}
    row = lock["installedPackages"][0]
    assert row["dirName"] == "ai.test.demo@1"
    assert row["familyKey"] == "ai.test.demo@1"
    assert "lineageRoot" not in row

# ---------------------------------------------------------------------------
# #154: the resolver was right, the manifest was wrong
# ---------------------------------------------------------------------------

def test_a_caret_zero_x_range_conflicts_with_a_one_x_floor():
    """``^0.14`` and ``>=1.1.3`` are genuinely disjoint.

    This pins the resolver's *correct* behaviour, because the tempting way to
    "fix" #154 was to loosen the resolver until the UHVI package installed. That
    would have let real, unsatisfiable conflicts through for every package. The
    fix belonged in the manifest, and this test exists so a future recurrence is
    fixed there too.

    ``^0.14`` means ``>=0.14.0,<1.0.0`` here (parse_range applies npm's 1.x caret
    semantics to 0.x), which cannot intersect a ``>=1.1.3`` floor.
    """
    merged, conflicts = merge_python_deps([
        ("curio.builtin@1", {"geopandas": ">=1.1.3"}),
        ("ai.urbanlab.uhvi@1", {"geopandas": "^0.14"}),
    ])
    assert [c.package for c in conflicts] == ["geopandas"]
    assert "geopandas" not in merged, (
        "a conflicting package is dropped from the merged set entirely, so the "
        "launcher would stop pip-installing it for the built-in package too"
    )


def test_an_open_ended_floor_below_the_builtin_floor_is_satisfiable():
    """The shape UHVI ships now: a floor with no upper bound.

    Intersecting ``>=0.14`` with ``>=1.1.3`` keeps the higher floor, so the
    package resolves and the environment still honours what builtin needs.
    """
    merged, conflicts = merge_python_deps([
        ("curio.builtin@1", {"geopandas": ">=1.1.3"}),
        ("ai.urbanlab.uhvi@1", {"geopandas": ">=0.14"}),
    ])
    assert conflicts == []
    assert merged["geopandas"] == ">=1.1.3"


def test_an_empty_range_means_any_version():
    """builtin declares ``numpy: ""``, so a capped numpy elsewhere would win.

    Worth pinning: it means a stray ``^1.26`` in one package silently constrains
    numpy for the entire shared environment rather than conflicting with anything.
    """
    merged, conflicts = merge_python_deps([
        ("curio.builtin@1", {"numpy": ""}),
        ("ai.urbanlab.uhvi@1", {"numpy": ">=1.26"}),
    ])
    assert conflicts == []
    assert merged["numpy"] == ">=1.26.0"
