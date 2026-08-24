"""Resolve node output filenames to files on disk (shared data + DuckDB artifacts)."""

from __future__ import annotations

import os
from pathlib import Path

from utk_curio.backend.app.common.safe_paths import is_within

# Kinds whose ``artifacts.value_str`` genuinely holds a path (shared with
# ``install/bundle.py``'s reader so the two can never disagree).
PATH_BEARING_KINDS = frozenset({"dataframe", "geodataframe", "dict", "list", "raster"})


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
    # Only the kinds that STORE a path in ``value_str`` may contribute one. A
    # ``str`` artifact holds the user's own return value there, so a node doing
    # ``return "cities.csv"`` used to resolve to a real shared-data file and get
    # it hard-linked in as that node's computed dataset (#180). Skipping it here
    # lets the installer fall through to the DuckDB-row branch, which stores
    # ``{"value": "cities.csv"}`` - the value the node actually returned.
    if value_str and kind in PATH_BEARING_KINDS:
        candidates.extend([
            Path(value_str),
            shared / value_str,
            _launch_dir() / value_str,
        ])
    if kind in ("dataframe", "geodataframe"):
        candidates.append(shared / "artifacts" / f"{art_id}.parquet")
    elif kind in ("dict", "list"):
        # Mirror ``bundle._resolve_artifact_source``: a JSON-native artifact lives
        # at ``artifacts/<id>.json[.zlib]`` even when value_str is absent.
        candidates.append(shared / "artifacts" / f"{art_id}.json.zlib")
        candidates.append(shared / "artifacts" / f"{art_id}.json")

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
    """Return a readable file for a node output ref filename, or None.

    A node-output ref filename is a single flat segment. Reject any path
    separator / traversal so an untrusted ``liveOutputs`` entry (e.g.
    ``../../../../etc/passwd``) can't be resolved to a file outside the shared
    output dir and streamed back to the client. Containment is also asserted on
    the resolved path as a second line of defence.
    """
    if not filename or not str(filename).strip():
        return None

    name = str(filename).strip()
    if "/" in name or "\\" in name or "\x00" in name or name in (".", ".."):
        return None

    shared = _shared_data_dir()

    direct = shared / name
    if direct.is_file() and is_within(direct, shared):
        return direct

    if "." not in Path(name).name:
        artifact_parquet = shared / "artifacts" / f"{name}.parquet"
        if artifact_parquet.is_file() and is_within(artifact_parquet, shared):
            return artifact_parquet

        duckdb_path = _resolve_duckdb_artifact_path(name)
        if duckdb_path is not None and (
            is_within(duckdb_path, shared) or is_within(duckdb_path, _launch_dir())
        ):
            return duckdb_path

    return None
