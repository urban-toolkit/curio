"""Every combination of Node, dist/ and node_modules that a start can meet.

The rule these pin: on a supported Node anything stale is refreshed, and only
an out-of-date Node refuses to start. The three states interact, so the cases
that matter are the products, not the axes:

* ``dist/`` is missing, current, or stale (built in the wrong webpack mode, or
  for a different BACKEND_URL; both read the same stamp).
* ``node_modules/`` is absent, installed by this Node major, or by another.
* the launcher is invoked plain, with ``--dev``, or with ``--force-rebuild``.

Two layers decide the outcome and are tested separately, because mirroring one
inside a test of the other is how a test ends up agreeing with itself:
``start_frontend``'s gate decides whether to consult check_install_build at
all, and ``check_install_build`` decides what to wipe and run. The matrix in
both docstrings below is the same one the launcher docs describe.
"""
from __future__ import annotations

import json
import os

import pytest

import utk_curio.main as main
from utk_curio.main import NODE_MAJOR

OTHER_MAJOR = NODE_MAJOR - 2
BUILD_SCRIPT = {"scripts": {"build": "webpack --mode production && npm run build:packages"}}

DIST_STATES = ["missing", "current", "stale"]
TREE_STATES = ["absent", "this major", "other major"]


def _make(root, dist, tree, *, source=True):
    if source:
        (root / "package.json").write_text(json.dumps(BUILD_SCRIPT), encoding="utf-8")
    if dist != "missing":
        (root / "dist").mkdir(exist_ok=True)
        (root / "dist" / "index.html").write_text("<html></html>", encoding="utf-8")
        (root / "dist" / "bundle.js").write_text("the bundle", encoding="utf-8")
        mode = "production" if dist == "current" else "development"
        (root / "dist" / ".curio-backend-url").write_text(f"{mode}\n\n", encoding="utf-8")
    if tree != "absent":
        (root / "node_modules").mkdir(exist_ok=True)
        major = NODE_MAJOR if tree == "this major" else OTHER_MAJOR
        (root / "node_modules" / main.NODE_STAMP).write_text(str(major), encoding="utf-8")
        (root / "node_modules" / "marker").write_text("x", encoding="utf-8")


@pytest.fixture
def frontend(tmp_path, monkeypatch):
    """A frontend tree at tmp_path, with npm, node and a supported version."""
    monkeypatch.setattr(main, "_frontend_dir", lambda: str(tmp_path))
    monkeypatch.setattr(main.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        main, "_read_node_version", lambda: (f"v{NODE_MAJOR}.0.0", NODE_MAJOR)
    )
    monkeypatch.delenv("BACKEND_URL", raising=False)
    monkeypatch.delenv("CURIO_DEV", raising=False)
    cwd = os.getcwd()
    yield tmp_path
    os.chdir(cwd)


# --------------------------------------------------------------------------
# Layer 1: does start_frontend consult check_install_build, and how?
# --------------------------------------------------------------------------

def _gate(monkeypatch, root, mode):
    """Run start_frontend far enough to see the gate, and report what it did."""
    calls = []
    monkeypatch.setattr(main, "_kill_port", lambda port: None)
    monkeypatch.setattr(
        main, "check_install_build",
        lambda d, force_rebuild=False: calls.append(force_rebuild),
    )
    if mode == "--dev":
        monkeypatch.setenv("CURIO_DEV", "1")
    # no_server returns right after the gate, before anything is spawned.
    main.start_frontend(port=0, force_rebuild=(mode == "--force-rebuild"), no_server=True)
    return calls


@pytest.mark.parametrize("dist", DIST_STATES)
@pytest.mark.parametrize("tree", TREE_STATES)
@pytest.mark.parametrize("mode", ["default", "--dev", "--force-rebuild"])
def test_gate_matrix(frontend, monkeypatch, dist, tree, mode):
    """Only a current dist/ beside a usable tree lets a plain start skip npm.

    A stale or missing bundle and a tree from another major each pull the start
    through check_install_build; --dev and --force-rebuild always do.
    """
    _make(frontend, dist, tree)

    calls = _gate(monkeypatch, frontend, mode)

    expected = (
        mode != "default"
        or dist != "current"
        or tree == "other major"
    )
    assert bool(calls) is expected
    if calls:
        assert calls[0] is (mode == "--force-rebuild")


@pytest.mark.parametrize("dist", DIST_STATES)
@pytest.mark.parametrize("tree", TREE_STATES)
def test_no_source_never_runs_npm_on_a_plain_start(frontend, monkeypatch, dist, tree):
    """The container ships dist/ and no sources; npm must never be reached.

    Nothing to reinstall from means nothing to report as stale, so even a tree
    stamped by another major leaves a plain start alone.
    """
    _make(frontend, dist, tree, source=False)

    calls = _gate(monkeypatch, frontend, "default")

    assert calls == []


# --------------------------------------------------------------------------
# Layer 2: what check_install_build wipes and runs
# --------------------------------------------------------------------------

def _build_run(monkeypatch, root, force_rebuild=False):
    ran = []
    monkeypatch.setattr(main.subprocess, "run", lambda cmd, **kw: ran.append(cmd))
    main.check_install_build(str(root), force_rebuild=force_rebuild)
    return ran


@pytest.mark.parametrize("dist", DIST_STATES)
@pytest.mark.parametrize("tree", TREE_STATES)
def test_build_matrix(frontend, monkeypatch, dist, tree):
    """The bundle is rebuilt on its own stamp; the tree on the Node major.

    A Node upgrade does not invalidate a bundle: which Node ran webpack does not
    change the JavaScript it emitted, so a current dist/ survives a reinstall.
    """
    _make(frontend, dist, tree)

    ran = _build_run(monkeypatch, frontend)

    assert ["npm", "install"] in ran
    # The tree is replaced only when its stamp names another major.
    if tree == "other major":
        assert not (frontend / "node_modules" / "marker").exists()
    elif tree != "absent":
        assert (frontend / "node_modules" / "marker").exists()
    # The bundle is rebuilt only when its own stamp says so.
    assert (["npm", "run", "build"] in ran) is (dist != "current")
    if dist == "current":
        assert (frontend / "dist" / "bundle.js").read_text() == "the bundle"


@pytest.mark.parametrize("dist", DIST_STATES)
@pytest.mark.parametrize("tree", TREE_STATES)
def test_force_rebuild_drops_everything(frontend, monkeypatch, dist, tree):
    """--force-rebuild is an explicit ask to redo the lot, bundle included."""
    _make(frontend, dist, tree)

    ran = _build_run(monkeypatch, frontend, force_rebuild=True)

    # Both directories are emptied. They come back holding their stamps only,
    # because the build is stubbed here and writes nothing else.
    assert not (frontend / "node_modules" / "marker").exists()
    assert not (frontend / "dist" / "bundle.js").exists()
    assert ran == [["npm", "install"], ["npm", "run", "build"]]


def test_the_upgrade_case_end_to_end(frontend, monkeypatch):
    """Node 24 checkout, upgraded: one plain start leaves everything correct.

    The bundle predates the production build (old one-line stamp) and the tree
    predates the upgrade, so both are stale for different reasons and both are
    repaired in the right order: reinstall, then rebuild.
    """
    _make(frontend, "current", "other major")
    (frontend / "dist" / ".curio-backend-url").write_text("", encoding="utf-8")

    assert main._frontend_needs_build() is True   # one-line stamp is stale
    assert main._frontend_tree_is_stale() is True

    ran = _build_run(monkeypatch, frontend)

    assert not (frontend / "node_modules" / "marker").exists()
    assert ran == [["npm", "install"], ["npm", "run", "build"]]
    assert (frontend / "node_modules" / main.NODE_STAMP).read_text() == str(NODE_MAJOR)
    assert main._build_stamp_reason() is None


# --------------------------------------------------------------------------
# The Node axis: the one state that refuses instead of repairing
# --------------------------------------------------------------------------

@pytest.mark.parametrize("dist", DIST_STATES)
@pytest.mark.parametrize("tree", TREE_STATES)
def test_an_old_node_refuses_whatever_else_is_on_disk(frontend, monkeypatch, dist, tree):
    """Nothing on disk earns a start on an unsupported Node.

    Not even a current bundle with a matching tree: the sandbox runs autk-db in
    this Node, where Autark data nodes die mid-download (nodejs/undici#5360).
    """
    _make(frontend, dist, tree)
    monkeypatch.setattr(
        main, "_read_node_version", lambda: (f"v{OTHER_MAJOR}.0.0", OTHER_MAJOR)
    )

    with pytest.raises(SystemExit) as exit_info:
        main._require_supported_node()
    assert exit_info.value.code == 1


def test_check_install_build_also_refuses_an_old_node(frontend, monkeypatch):
    """The gate inside the builder, for callers that did not pass the start check."""
    _make(frontend, "missing", "absent")
    monkeypatch.setattr(
        main, "_read_node_version", lambda: (f"v{OTHER_MAJOR}.0.0", OTHER_MAJOR)
    )
    ran = []
    monkeypatch.setattr(main.subprocess, "run", lambda cmd, **kw: ran.append(cmd))

    with pytest.raises(SystemExit):
        main.check_install_build(str(frontend))
    assert ran == []
