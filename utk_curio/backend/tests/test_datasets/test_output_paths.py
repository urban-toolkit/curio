"""Tests for shared output path resolution."""

from __future__ import annotations


def test_resolve_shared_output_path_artifact_parquet(app, tmp_path, monkeypatch):
    import os

    from utk_curio.backend.app.datasets.output_paths import resolve_shared_output_path

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
    from utk_curio.backend.app.datasets.output_paths import resolve_shared_output_path

    def _boom():
        raise OSError("Could not set lock on file")

    monkeypatch.setattr(
        "utk_curio.sandbox.util.db.get_read_connection",
        _boom,
    )

    # Extensionless id with no artifacts/*.parquet on disk falls through to DuckDB.
    assert resolve_shared_output_path("bare_artifact_id") is None
