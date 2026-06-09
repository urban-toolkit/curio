"""Resolve node output filenames to files on disk (shared data + DuckDB artifacts)."""

from __future__ import annotations

import os
from pathlib import Path


def _shared_data_dir() -> Path:
    from utk_curio.backend.app.projects.storage import _shared_data_dir as _sd

    return _sd()


def _launch_dir() -> Path:
    return Path(os.environ.get("CURIO_LAUNCH_CWD", os.getcwd())).resolve()


def _resolve_duckdb_artifact_path(art_id: str) -> Path | None:
    """Map a bare DuckDB artifact id to a readable file (parquet path or raster source)."""
    try:
        from utk_curio.sandbox.util.db import get_read_connection
    except Exception:  # noqa: BLE001
        return None

    try:
        con = get_read_connection()
        try:
            row = con.execute(
                "SELECT kind, value_str FROM artifacts WHERE id = ?",
                [art_id],
            ).fetchone()
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        # Sandbox may still hold an exclusive lock on curio_data.duckdb during /exec.
        return None

    if not row:
        return None

    kind, value_str = row[0], row[1]
    shared = _shared_data_dir()
    candidates: list[Path] = []
    if value_str:
        candidates.extend([
            Path(value_str),
            shared / value_str,
            _launch_dir() / value_str,
        ])
    if kind in ("dataframe", "geodataframe"):
        candidates.append(shared / "artifacts" / f"{art_id}.parquet")

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_file():
            return resolved

    return None


def resolve_shared_output_path(
    filename: str,
    *,
    data_type: str | None = None,
) -> Path | None:
    """Return a readable file for a node output ref filename, or None."""
    if not filename or not str(filename).strip():
        return None

    name = str(filename).strip()
    shared = _shared_data_dir()

    direct = shared / name
    if direct.is_file():
        return direct

    if "." not in Path(name).name:
        artifact_parquet = shared / "artifacts" / f"{name}.parquet"
        if artifact_parquet.is_file():
            return artifact_parquet

        duckdb_path = _resolve_duckdb_artifact_path(name)
        if duckdb_path is not None:
            return duckdb_path

    return None
