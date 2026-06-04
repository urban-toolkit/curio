"""Sidecar metadata and row/feature counting for dataset files."""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def count_file(path: Path, fmt: str) -> tuple[int | None, int | None]:
    """Return (row_count, feature_count) for a local dataset file.

    Both values may be None if the format is unsupported or the file cannot
    be read.  For CSV the header row is excluded from the count.  For GeoJSON
    only the feature array length is returned as feature_count.
    """
    try:
        if fmt == "csv":
            with path.open("r", encoding="utf-8-sig", newline="") as fh:
                reader = csv.reader(fh)
                next(reader, None)
                count = sum(1 for _ in reader)
            return count, None
        if fmt == "json":
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                return len(data), None
            return 1, None
        if fmt == "geojson":
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            features = data.get("features", []) if isinstance(data, dict) else []
            return None, len(features)
    except Exception:
        logger.debug(
            "Could not count rows/features for %s (format=%s); returning None",
            path,
            fmt,
            exc_info=True,
        )
        return None, None
    return None, None


def meta_path(data_path: Path) -> Path:
    """Return the sidecar metadata path for a dataset file."""
    return data_path.parent / (data_path.name + ".meta.json")


def read_file_meta(data_path: Path) -> tuple[int | None, int | None]:
    """Read (row_count, feature_count) from the sidecar, or (None, None) if absent."""
    meta = meta_path(data_path)
    try:
        raw = json.loads(meta.read_text(encoding="utf-8"))
        return raw.get("rowCount"), raw.get("featureCount")
    except Exception:
        return None, None


def write_file_meta(data_path: Path, row_count: int | None, feature_count: int | None) -> None:
    """Persist counts to the sidecar file next to the dataset."""
    meta = meta_path(data_path)
    try:
        payload: dict[str, Any] = {}
        if row_count is not None:
            payload["rowCount"] = row_count
        if feature_count is not None:
            payload["featureCount"] = feature_count
        meta.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        pass


def patch_manifest_file(
    manifest_path: Path,
    row_count: int | None,
    feature_count: int | None,
) -> None:
    """Write rowCount/featureCount into an existing manifest.json on disk."""
    try:
        raw: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
        changed = False
        if row_count is not None and raw.get("rowCount") is None:
            raw["rowCount"] = row_count
            changed = True
        if feature_count is not None and raw.get("featureCount") is None:
            raw["featureCount"] = feature_count
            changed = True
        if changed:
            manifest_path.write_text(
                json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8"
            )
    except Exception:
        logger.debug(
            "Skipping optional manifest patch for %s",
            manifest_path,
            exc_info=True,
        )
