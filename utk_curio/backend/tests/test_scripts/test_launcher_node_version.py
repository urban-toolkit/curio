"""The Node.js major is declared in five places; keep them in step.

``utk_curio.main.NODE_MAJOR`` gates the frontend start, ``.nvmrc`` and
``.node-version`` drive nvm/fnm/asdf, and the two ``package.json`` ``engines``
fields are what npm warns on. Nothing links them but a comment, so a bump that
misses one leaves contributors on a Node the launcher then refuses (or, worse,
accepts while the build was made for another).

The second half covers the node_modules stamp (``NODE_STAMP``): a tree
installed by a different Node major is wiped and reinstalled once, which is how
a checkout from before the Node 26 move heals itself without anyone being told
to delete a folder.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import utk_curio.main as main
from utk_curio.main import (
    NODE_MAJOR,
    NODE_STAMP,
    _node_tree_is_stale,
    _write_node_stamp,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
FRONTEND = REPO_ROOT / "utk_curio" / "frontend" / "urban-workflows"


@pytest.mark.parametrize("name", [".nvmrc", ".node-version"])
def test_version_files_match_node_major(name):
    assert (REPO_ROOT / name).read_text(encoding="utf-8").strip() == str(NODE_MAJOR)


@pytest.mark.parametrize(
    "pkg", [REPO_ROOT / "package.json", FRONTEND / "package.json"]
)
def test_package_engines_match_node_major(pkg):
    engines = json.loads(pkg.read_text(encoding="utf-8")).get("engines", {})
    assert engines.get("node") == f"^{NODE_MAJOR}"


def test_dockerfile_matches_node_major():
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert f"setup_{NODE_MAJOR}.x" in dockerfile
    assert f"node:{NODE_MAJOR}-" in dockerfile


def test_missing_tree_is_not_stale(tmp_path):
    # Nothing to wipe, and the install that follows is a fresh one.
    assert _node_tree_is_stale(str(tmp_path), NODE_MAJOR) is False


def test_unstamped_tree_is_stale(tmp_path):
    # Every checkout installed before the stamp existed, which is the case this
    # was written for.
    (tmp_path / "node_modules").mkdir()
    assert _node_tree_is_stale(str(tmp_path), NODE_MAJOR) is True


def test_other_major_is_stale(tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / NODE_STAMP).write_text("24", encoding="utf-8")
    assert _node_tree_is_stale(str(tmp_path), 26) is True


def test_same_major_is_current(tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / NODE_STAMP).write_text("26\n", encoding="utf-8")
    assert _node_tree_is_stale(str(tmp_path), 26) is False


def test_written_stamp_reads_back_as_current(tmp_path):
    _write_node_stamp(str(tmp_path), NODE_MAJOR)
    assert _node_tree_is_stale(str(tmp_path), NODE_MAJOR) is False
    assert _node_tree_is_stale(str(tmp_path), NODE_MAJOR - 1) is True


@pytest.fixture
def fake_npm(monkeypatch):
    """``check_install_build`` with npm/node stubbed; returns the commands run."""
    commands = []

    monkeypatch.setattr(main.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(main, "_read_node_version", lambda: (f"v{NODE_MAJOR}.0.0", NODE_MAJOR))
    monkeypatch.setattr(
        main.subprocess, "run", lambda cmd, **kw: commands.append(cmd) or None
    )
    cwd = os.getcwd()
    yield commands
    os.chdir(cwd)


def _tree(root: Path, stamp: str | None):
    (root / "node_modules").mkdir()
    (root / "node_modules" / "marker").write_text("x", encoding="utf-8")
    (root / "build").mkdir()
    if stamp is not None:
        (root / "node_modules" / NODE_STAMP).write_text(stamp, encoding="utf-8")


def test_tree_from_another_major_is_rebuilt(tmp_path, fake_npm):
    _tree(tmp_path, str(NODE_MAJOR - 2))

    main.check_install_build(str(tmp_path))

    # The old tree is gone -- not just re-installed over -- and the bundle with
    # it, and the stamp now names the Node that did the install.
    assert not (tmp_path / "node_modules" / "marker").exists()
    assert ["npm", "install"] in fake_npm
    assert ["npm", "run", "build"] in fake_npm
    assert (tmp_path / "node_modules" / NODE_STAMP).read_text(encoding="utf-8") == str(NODE_MAJOR)


def test_tree_from_this_major_is_kept(tmp_path, fake_npm):
    _tree(tmp_path, str(NODE_MAJOR))

    main.check_install_build(str(tmp_path))

    assert (tmp_path / "node_modules" / "marker").exists()
    assert ["npm", "install"] in fake_npm


def test_leftover_build_dir_does_not_suppress_the_build(tmp_path, fake_npm):
    """A stale ``build/`` must never stand in for a missing ``dist/``.

    ``build_dir`` used to fall back to ``build`` whenever ``dist`` was absent.
    Since this function writes the ``.curio-backend-url`` stamp into
    ``build_dir`` while webpack writes ``dist``, a first build left an otherwise
    empty ``build/`` holding a matching stamp -- and from then on, deleting
    ``dist`` (the documented first step before an e2e run) made the launcher
    report the bundle current and skip the build, leaving start_frontend
    serving a directory that was not there.
    """
    _tree(tmp_path, str(NODE_MAJOR))
    (tmp_path / "build" / ".curio-backend-url").write_text("", encoding="utf-8")
    assert not (tmp_path / "dist").exists()

    main.check_install_build(str(tmp_path))

    assert ["npm", "run", "build"] in fake_npm
