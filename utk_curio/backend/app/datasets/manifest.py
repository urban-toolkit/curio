"""Dataset manifest reader for committed catalog and user-store copies."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from utk_curio.backend.app.datasets.storage import DatasetId


SUPPORTED_FORMATS = {"csv", "geojson", "json", "parquet", "geotiff", "shp"}


class ManifestError(ValueError):
    """Raised when a dataset manifest is malformed."""


@dataclass(frozen=True)
class DatasetManifest:
    id: str
    name: str
    version: str
    format: str
    description: str
    publisher: str
    license: str
    tags: list[str]
    data_file: str
    major: int
    created_at: str | None = None
    updated_at: str | None = None
    feature_count: int | None = None
    row_count: int | None = None
    schema: dict[str, Any] | None = None
    source_label: str | None = None

    @property
    def dir_name(self) -> str:
        return f"{self.id}@{self.major}"


def _require_str(raw: object, field_name: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ManifestError(f"manifest.{field_name} must be a non-empty string")
    return raw.strip()


def _parse_manifest(raw: dict[str, Any], *, where: str) -> DatasetManifest:
    dataset_id = _require_str(raw.get("id"), "id")

    compatibility = raw.get("compatibility") or {}
    major_raw = compatibility.get("major", 1)
    try:
        major = int(major_raw)
    except (TypeError, ValueError) as exc:
        raise ManifestError(f"{where}.compatibility.major must be an integer") from exc

    try:
        DatasetId.parse_dir(f"{dataset_id}@{major}")
    except Exception as exc:
        raise ManifestError(f"{where}.id is not a valid dataset id: {dataset_id!r}") from exc

    fmt = _require_str(raw.get("format"), "format").lower()
    if fmt not in SUPPORTED_FORMATS:
        raise ManifestError(f"{where}.format must be one of {sorted(SUPPORTED_FORMATS)}")

    tags_raw = raw.get("tags") or []
    if not isinstance(tags_raw, list):
        raise ManifestError(f"{where}.tags must be an array")
    tags = [str(tag) for tag in tags_raw]

    schema = raw.get("schema")
    if schema is not None and not isinstance(schema, dict):
        raise ManifestError(f"{where}.schema must be an object when present")

    feature_count = raw.get("featureCount")
    row_count = raw.get("rowCount")
    if feature_count is not None:
        feature_count = int(feature_count)
    if row_count is not None:
        row_count = int(row_count)

    return DatasetManifest(
        id=dataset_id,
        name=_require_str(raw.get("name"), "name"),
        version=_require_str(raw.get("version"), "version"),
        format=fmt,
        description=str(raw.get("description") or ""),
        publisher=str(raw.get("publisher") or "Data Catalog"),
        license=str(raw.get("license") or ""),
        tags=tags,
        data_file=_require_str(raw.get("dataFile"), "dataFile"),
        major=major,
        created_at=str(raw.get("createdAt") or "") or None,
        updated_at=str(raw.get("updatedAt") or "") or None,
        feature_count=feature_count,
        row_count=row_count,
        schema=schema,
        source_label=str(raw.get("sourceLabel") or raw.get("publisher") or "Data Catalog") or None,
    )


def build_manifest_dict(manifest: DatasetManifest) -> dict[str, Any]:
    """Serialise a DatasetManifest to a complete JSON-ready dict.

    Every known field is always present.  Optional fields that carry no value
    are written as ``null`` (or ``""`` for string fields that are semantically
    empty rather than absent).  This ensures that manifest.json files on disk
    are self-describing and forward-compatible.
    """
    return {
        "id": manifest.id,
        "name": manifest.name,
        "version": manifest.version,
        "format": manifest.format,
        "description": manifest.description or "",
        "publisher": manifest.publisher or "",
        "license": manifest.license or "",
        "tags": list(manifest.tags),
        "dataFile": manifest.data_file,
        "compatibility": {"major": manifest.major},
        "sourceLabel": manifest.source_label or "",
        "rowCount": manifest.row_count,
        "featureCount": manifest.feature_count,
        "schema": manifest.schema,
        "createdAt": manifest.created_at or None,
        "updatedAt": manifest.updated_at or None,
    }


def write_manifest(manifest: DatasetManifest, dataset_root: Path) -> None:
    """Write a complete manifest.json to *dataset_root*, replacing any existing file."""
    manifest_path = dataset_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(build_manifest_dict(manifest), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_dataset_manifest(dataset_root: Path) -> DatasetManifest:
    manifest_path = dataset_root / "manifest.json"
    if not manifest_path.is_file():
        raise ManifestError(f"missing manifest.json in {dataset_root}")
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"manifest.json is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ManifestError("manifest.json must be a JSON object")
    manifest = _parse_manifest(raw, where="manifest.json")
    expected_dir = f"{manifest.id}@{manifest.major}"
    if dataset_root.name != expected_dir:
        raise ManifestError(
            f"directory name {dataset_root.name!r} does not match manifest id {expected_dir!r}"
        )
    return manifest


def load_dataset_manifest_from_dir(dataset_root: Path) -> DatasetManifest:
    """Load manifest without enforcing directory-name match (staging/catalog scan)."""
    manifest_path = dataset_root / "manifest.json"
    if not manifest_path.is_file():
        raise ManifestError(f"missing manifest.json in {dataset_root}")
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ManifestError("manifest.json must be a JSON object")
    return _parse_manifest(raw, where="manifest.json")
