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

With that in, the same stage's run 42534743404 still had the GIL's holder in
``safe_join``'s resolve of its base in 6.0% of the samples, and in
``agent_definition_dir``'s resolve of the account's agent store in 6.4%: the
same few folders, walked again on every call. So a base folder is resolved
once (``safe_paths.resolve_base``, which the users root uses too), and only
what is joined under it is walked on each call. A base swapped for a link
after its first use is refused, not followed; a relative base is still read
against the working folder of each call.
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


def test_a_dataflows_folder_is_found_with_one_walk(tmp_path, monkeypatch):
    """``project_dir``, which every read and write of a dataflow's files asks:
    the users root and ``safe_join``'s base, known already, then its target."""
    from utk_curio.backend.app.projects import storage

    monkeypatch.setenv("CURIO_STATE_DIR", str(tmp_path / "state"))
    storage.project_dir("7", DATAFLOW)
    resolved = _resolves(monkeypatch)

    folder = storage.project_dir("7", DATAFLOW)
    walks = list(resolved)

    assert folder.name == DATAFLOW and folder.parent.name == "projects"
    assert walks == [str(folder)], f"a dataflow's folder took {len(walks)} walks: {walks}"


def test_safe_join_resolves_a_base_folder_once_and_its_target_on_every_call(tmp_path, monkeypatch):
    from utk_curio.backend.app.common.safe_paths import safe_join

    base = tmp_path / "launch"
    base.mkdir()
    safe_join(base, "first.csv", validate=False)
    target = base.resolve() / "data" / "second.csv"
    resolved = _resolves(monkeypatch)

    joined = safe_join(base, "data", "second.csv", validate=False)
    walks = list(resolved)

    assert joined == target
    assert walks == [str(target)], f"safe_join walked {walks}, not its target alone"


def test_a_link_out_of_a_base_already_seen_is_still_refused(tmp_path):
    """The target is still walked on every call, under a base known already."""
    from utk_curio.backend.app.common.safe_paths import PathTraversalError, safe_join

    base = tmp_path / "base"
    base.mkdir()
    safe_join(base, "escape")
    outside = tmp_path / "outside"
    outside.mkdir()
    (base / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(PathTraversalError):
        safe_join(base, "escape")
    with pytest.raises(PathTraversalError):
        safe_join(base, "escape", "file.json", validate=False)


def test_a_base_folder_swapped_for_a_link_after_its_first_use_is_refused(tmp_path):
    """The base is kept as it was first seen, so what a link put in its place
    leads to lies outside it."""
    from utk_curio.backend.app.common.safe_paths import PathTraversalError, safe_join

    base = tmp_path / "base"
    base.mkdir()
    safe_join(base, "file.json")
    outside = tmp_path / "outside"
    outside.mkdir()
    base.rename(tmp_path / "moved")
    base.symlink_to(outside, target_is_directory=True)

    with pytest.raises(PathTraversalError):
        safe_join(base, "file.json")


def test_a_relative_base_is_read_against_the_working_folder_of_each_call(tmp_path, monkeypatch):
    from utk_curio.backend.app.common.safe_paths import safe_join

    for name in ("one", "two"):
        (tmp_path / name / "data").mkdir(parents=True)

    monkeypatch.chdir(tmp_path / "one")
    first = safe_join("data", "rows.csv")
    monkeypatch.chdir(tmp_path / "two")
    second = safe_join("data", "rows.csv")

    assert first == (tmp_path / "one").resolve() / "data" / "rows.csv"
    assert second == (tmp_path / "two").resolve() / "data" / "rows.csv"
