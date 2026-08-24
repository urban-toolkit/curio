"""Tests for shared output path resolution."""

from __future__ import annotations


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


def test_computed_output_format_uses_data_type():
    from utk_curio.backend.app.datasets.service import _computed_output_format

    assert _computed_output_format("1780603509873_abc", "raster") == "geotiff"
    assert _computed_output_format("1780603508213_out.parquet", "dataframe") == "parquet"


def test_resolve_duckdb_artifact_path_ignores_lock_errors(monkeypatch):
    from utk_curio.backend.app.datasets.infrastructure.output_paths import resolve_shared_output_path

    def _boom():
        raise OSError("Could not set lock on file")

    monkeypatch.setattr(
        "utk_curio.sandbox.util.db.get_read_connection",
        _boom,
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

    # Stand in for the DuckDB read: kind 'str', value_str = the returned string.
    class _Con:
        def execute(self, *_a, **_k):
            class _R:
                @staticmethod
                def fetchone():
                    return ("str", "cities.csv")
            return _R()

        def close(self):
            pass

    monkeypatch.setattr("utk_curio.sandbox.util.db.get_read_connection", lambda: _Con())

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

    class _Con:
        def execute(self, *_a, **_k):
            class _R:
                @staticmethod
                def fetchone():
                    return ("dict", None)  # no value_str, older sandbox
            return _R()

        def close(self):
            pass

    monkeypatch.setattr("utk_curio.sandbox.util.db.get_read_connection", lambda: _Con())

    assert output_paths._resolve_duckdb_artifact_path(art) == blob.resolve()
