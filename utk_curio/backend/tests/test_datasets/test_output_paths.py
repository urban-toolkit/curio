"""Tests for shared output path resolution."""

from __future__ import annotations

import pytest

#: The folders the ``app`` fixture moves into each test's ``tmp_path``.
_THE_APPS_FOLDERS = ("CURIO_SHARED_DATA", "CURIO_LAUNCH_CWD")


@pytest.fixture(scope="module", autouse=True)
def _the_folders_the_module_starts_with():
    """``CURIO_SHARED_DATA`` and ``CURIO_LAUNCH_CWD`` as this module's first
    test starts, before any fixture of its own moves them."""
    import os

    return {name: os.environ.get(name) for name in _THE_APPS_FOLDERS}


def test_resolve_shared_output_path_artifact_parquet(app, tmp_path, monkeypatch):
    import os

    from utk_curio.backend.app.datasets.infrastructure.output_paths import resolve_shared_output_path

    shared = tmp_path / "shared"
    (shared / "artifacts").mkdir(parents=True)
    pq = shared / "artifacts" / "abc123.parquet"
    pq.write_bytes(b"PAR1")

    monkeypatch.setenv("CURIO_SHARED_DATA", str(shared))
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))

    resolved = resolve_shared_output_path("abc123", data_type="dataframe")
    assert resolved == pq


def test_after_a_test_that_moves_the_apps_folders_again_they_are_back(_the_folders_the_module_starts_with):
    """Runs after the test above, which moves both folders again through
    ``monkeypatch``, over the ``app`` fixture's. The fixture put them back by
    hand, and ``monkeypatch``, set up before it by an autouse fixture of the
    suite's root conftest, undid the test's moves after that, writing the
    fixture's folders back: every later test of the process ran in that
    test's ``tmp_path``."""
    import os

    now = {name: os.environ.get(name) for name in _THE_APPS_FOLDERS}
    assert now == _the_folders_the_module_starts_with, (
        f"after test_resolve_shared_output_path_artifact_parquet the folders are {now}, "
        f"not {_the_folders_the_module_starts_with}, which this module started with"
    )


def test_computed_output_format_uses_data_type():
    from utk_curio.backend.app.datasets.service import _computed_output_format

    assert _computed_output_format("1780603509873_abc", "raster") == "geotiff"
    assert _computed_output_format("1780603508213_out.parquet", "dataframe") == "parquet"


def test_resolve_duckdb_artifact_path_survives_an_unreadable_artifact(monkeypatch):
    """An artifact the backend cannot read resolves to nothing, not an error.

    The read goes through the sandbox now, so "cannot read" is an unreachable
    or unhappy sandbox rather than a locked file; either way the resolver has
    no path to offer and must say so quietly.
    """
    from utk_curio.backend.app.datasets.infrastructure.output_paths import resolve_shared_output_path

    monkeypatch.setattr(
        "utk_curio.backend.app.datasets.infrastructure.sandbox_artifacts.artifact_row",
        lambda _art_id: None,
    )

    # Extensionless id with no artifacts/*.parquet on disk falls through to DuckDB.
    assert resolve_shared_output_path("bare_artifact_id") is None


def test_str_artifact_value_is_not_treated_as_a_path(app, monkeypatch):
    """#180: ``value_str`` is only a path for the kinds that store one there.

    A ``str`` artifact keeps the user's own return value in that column, so
    ``return "cities.csv"`` used to resolve to a real shared-data file and get it
    hard-linked in as that node's computed dataset. Gating on
    ``PATH_BEARING_KINDS`` makes the resolver decline, which lets the installer
    fall through to the row branch and store the value instead.
    """
    import os
    from pathlib import Path

    from utk_curio.backend.app.datasets.infrastructure import output_paths

    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "cities.csv").write_text("name\nChicago\n", encoding="utf-8")

    # Stand in for the artifact read: kind 'str', value_str = the returned
    # string. The tuple is the row shape the sandbox reports.
    monkeypatch.setattr(
        "utk_curio.backend.app.datasets.infrastructure.sandbox_artifacts.artifact_row",
        lambda _art_id: ("str", None, None, "cities.csv", None),
    )

    assert output_paths._resolve_duckdb_artifact_path("1790000000000_cafebabe") is None


def test_dict_artifact_resolves_its_json_zlib_without_value_str(app, monkeypatch):
    """The dict/list candidates mirror ``bundle._resolve_artifact_source``."""
    import os
    from pathlib import Path

    from utk_curio.backend.app.datasets.infrastructure import output_paths

    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "artifacts").mkdir(parents=True, exist_ok=True)
    art = "1790000000000_f00dcafe"
    blob = shared / "artifacts" / (art + ".json.zlib")
    blob.write_bytes(b"\x78\x9c")

    monkeypatch.setattr(
        "utk_curio.backend.app.datasets.infrastructure.sandbox_artifacts.artifact_row",
        lambda _art_id: ("dict", None, None, None, None),  # no value_str, older sandbox
    )

    assert output_paths._resolve_duckdb_artifact_path(art) == blob.resolve()
