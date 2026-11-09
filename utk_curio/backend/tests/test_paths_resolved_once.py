"""The paths the backend builds for every request are resolved once each.

``Path.resolve()`` walks every component of a path in Python, with an lstat
each, and lets the GIL go at each one: under many requests at once, each walk
costs a wait for the GIL. With 100 agent turns at once (``tests/stress``, run
42457985047 of the stage with agents), the GIL's holder was in
``users_base()``'s resolve in 15% of py-spy's samples, and in ``safe_join``'s,
whose ``is_within`` walked its base and its target a second time, in 13%.

So ``safe_join`` resolves its base and its target once each, and
``users_base()`` resolves the users root once. ``safe_join`` still refuses a
symbolic link out of its base.
"""
from __future__ import annotations

import pathlib

import pytest

DATAFLOW = "5e3c0a6e-2b1d-4f7a-9c8e-0d1f2a3b4c5d"


def _resolves(monkeypatch) -> list:
    """The paths resolved from now on."""
    resolved: list = []
    original = pathlib.Path.resolve

    def counted(self, *args, **kwargs):
        resolved.append(str(self))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "resolve", counted)
    return resolved


def test_safe_join_resolves_its_base_and_its_target_once_each(tmp_path, monkeypatch):
    from utk_curio.backend.app.common.safe_paths import safe_join

    base = tmp_path / "users"
    (base / "7" / "projects").mkdir(parents=True)
    resolved = _resolves(monkeypatch)

    joined = safe_join(base, "7", "projects", DATAFLOW)
    walks = list(resolved)

    assert joined == base.resolve() / "7" / "projects" / DATAFLOW
    assert len(walks) == 2, f"safe_join resolved {len(walks)} paths, not its base and its target once each: {walks}"


def test_safe_join_still_refuses_a_symbolic_link_out_of_its_base(tmp_path):
    from utk_curio.backend.app.common.safe_paths import PathTraversalError, safe_join

    base = tmp_path / "base"
    base.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (base / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(PathTraversalError):
        safe_join(base, "escape")
    with pytest.raises(PathTraversalError):
        safe_join(base, "escape", "file.json", validate=False)


def test_the_users_root_is_resolved_once_and_another_root_anew(tmp_path, monkeypatch):
    from utk_curio.backend.app.common import user_storage

    monkeypatch.setenv("CURIO_STATE_DIR", str(tmp_path / "state"))
    first = user_storage.users_base()
    resolved = _resolves(monkeypatch)

    again = user_storage.users_base()
    walks = list(resolved)

    assert again == first
    assert walks == [], f"users_base resolved its root again: {walks}"

    monkeypatch.setenv("CURIO_STATE_DIR", str(tmp_path / "other"))
    other = user_storage.users_base()
    assert other.name == "users" and other.is_relative_to((tmp_path / "other").resolve()), other


def test_a_dataflows_folder_is_found_with_two_walks(tmp_path, monkeypatch):
    """``project_dir``, which every read and write of a dataflow's files asks:
    the users root, known already, and ``safe_join``'s base and target."""
    from utk_curio.backend.app.projects import storage

    monkeypatch.setenv("CURIO_STATE_DIR", str(tmp_path / "state"))
    storage.project_dir("7", DATAFLOW)
    resolved = _resolves(monkeypatch)

    folder = storage.project_dir("7", DATAFLOW)
    walks = list(resolved)

    assert folder.name == DATAFLOW and folder.parent.name == "projects"
    assert len(walks) == 2, f"a dataflow's folder took {len(walks)} walks: {walks}"
