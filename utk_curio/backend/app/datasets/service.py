"""Dataset catalog service.

This module intentionally knows nothing about node packages. It normalizes
datasets from three sources: local/imported files, fixture-backed Data Hub rows,
and datasets already recorded on a saved dataflow.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from utk_curio.backend.app.datasets.manifest import DatasetManifest


SUPPORTED_SUFFIXES = {
    ".csv": "csv",
    ".geojson": "geojson",
    ".json": "json",
    ".parquet": "parquet",
    ".tif": "geotiff",
    ".tiff": "geotiff",
    ".shp": "shp",
}


class DatasetCatalogError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _iso_from_timestamp(ts: float | None = None) -> str:
    dt = datetime.fromtimestamp(ts, timezone.utc) if ts is not None else datetime.now(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _stable_id(prefix: str, raw: str) -> str:
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14]
    return f"{prefix}-{digest}"


def _count_file(path: Path, fmt: str) -> tuple[int | None, int | None]:
    """Return (row_count, feature_count) for a local dataset file.

    Both values may be None if the format is unsupported or the file cannot
    be read.  For CSV the header row is excluded from the count.  For GeoJSON
    only the feature array length is returned as feature_count.
    """
    try:
        if fmt == "csv":
            with path.open("r", encoding="utf-8-sig", newline="") as fh:
                reader = csv.reader(fh)
                next(reader, None)  # skip header
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
        pass
    return None, None


def _meta_path(data_path: Path) -> Path:
    """Return the sidecar metadata path for a dataset file.

    E.g. ``data/energy_dataset.csv`` → ``data/energy_dataset.csv.meta.json``
    """
    return data_path.parent / (data_path.name + ".meta.json")


def _read_file_meta(data_path: Path) -> tuple[int | None, int | None]:
    """Read (row_count, feature_count) from the sidecar, or (None, None) if absent."""
    meta = _meta_path(data_path)
    try:
        raw = json.loads(meta.read_text(encoding="utf-8"))
        return raw.get("rowCount"), raw.get("featureCount")
    except Exception:
        return None, None


def _write_file_meta(data_path: Path, row_count: int | None, feature_count: int | None) -> None:
    """Persist counts to the sidecar file next to the dataset."""
    meta = _meta_path(data_path)
    try:
        payload: dict[str, Any] = {}
        if row_count is not None:
            payload["rowCount"] = row_count
        if feature_count is not None:
            payload["featureCount"] = feature_count
        meta.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        pass  # never break a request over a cache write failure


def _patch_manifest_file(
    manifest_path: Path,
    row_count: int | None,
    feature_count: int | None,
) -> None:
    """Write rowCount/featureCount into an existing manifest.json on disk.

    Only patches fields that are currently null/missing.  Silently skips
    on any I/O or parse error so callers never break on a patching failure.
    """
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
        pass


def _catalog_id_from_title(title: str) -> str:
    """Generate a local catalog dataset id from a human title.

    Returns a string like ``local.data.<slug>`` that satisfies the
    ``<datasetId>@<major>`` directory-name regex when combined with ``@1``.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "dataset"
    return f"local.data.{slug}"


def _format_for_path(path: Path) -> str | None:
    return SUPPORTED_SUFFIXES.get(path.suffix.lower())


def _loader_snippet(fmt: str, path: str | None) -> dict[str, Any]:
    dataset_path = path or "<dataset-path>"
    if fmt == "csv":
        return {
            "language": "python",
            "imports": ["import pandas as pd"],
            "pathVariable": "dataset_path",
            "code": f'dataset_path = "{dataset_path}"\ndf = pd.read_csv(dataset_path)',
        }
    if fmt in {"geojson", "shp"}:
        return {
            "language": "python",
            "imports": ["import geopandas as gpd"],
            "pathVariable": "dataset_path",
            "code": f'dataset_path = "{dataset_path}"\ngdf = gpd.read_file(dataset_path)',
        }
    if fmt == "json":
        return {
            "language": "python",
            "imports": ["import json"],
            "pathVariable": "dataset_path",
            "code": f'dataset_path = "{dataset_path}"\nwith open(dataset_path) as f:\n    data = json.load(f)',
        }
    if fmt == "geotiff":
        return {
            "language": "python",
            "imports": ["import rasterio"],
            "pathVariable": "dataset_path",
            "code": f'dataset_path = "{dataset_path}"\nsrc = rasterio.open(dataset_path)',
        }
    return {
        "language": "python",
        "imports": [],
        "pathVariable": "dataset_path",
        "code": f'dataset_path = "{dataset_path}"',
    }


def _base_item(**overrides: Any) -> dict[str, Any]:
    item = {
        "id": "",
        "title": "",
        "description": "",
        "origin": "imported",
        "format": "csv",
        "uri": "",
        "path": None,
        "sizeBytes": None,
        "rowCount": None,
        "featureCount": None,
        "producerNodeId": None,
        "consumerNodeIds": [],
        "updatedAt": _iso_from_timestamp(),
        "sourceLabel": "",
        "license": None,
        "tags": [],
        "schema": None,
        "loaderSnippet": None,
        "installed": False,
    }
    item.update(overrides)
    if item["loaderSnippet"] is None:
        item["loaderSnippet"] = _loader_snippet(item["format"], item.get("path"))
    return item


def _item_from_file(path: Path, *, source_label: str, origin: str = "imported") -> dict[str, Any] | None:
    fmt = _format_for_path(path)
    if fmt is None or not path.is_file():
        return None
    stat = path.stat()
    file_path = path.as_posix()
    title = path.stem.replace("_", " ").replace("-", " ").strip().title() or path.name
    # Counts are read from the sidecar written at import/install time — never
    # computed on the fly here so catalog listing stays fast.
    row_count, feature_count = _read_file_meta(path)
    return _base_item(
        id=_stable_id("file", str(path.resolve())),
        title=title,
        description=f"{fmt.upper()} dataset available in the current workspace.",
        origin=origin,
        format=fmt,
        uri=f"file://{file_path}",
        path=file_path,
        sizeBytes=stat.st_size,
        rowCount=row_count,
        featureCount=feature_count,
        updatedAt=_iso_from_timestamp(stat.st_mtime),
        sourceLabel=source_label,
        tags=[fmt, origin],
    )


class DatasetRegistryRepository:
    """Manifest-backed Data Hub catalog at ``<repo_root>/datasets/``."""

    def list_items(self) -> list[dict[str, Any]]:
        from utk_curio.backend.app.datasets.manifest import ManifestError, load_dataset_manifest_from_dir
        from utk_curio.backend.app.datasets.storage import list_catalog_datasets

        items: list[dict[str, Any]] = []
        for dataset_root in list_catalog_datasets():
            try:
                manifest = load_dataset_manifest_from_dir(dataset_root)
            except ManifestError:
                continue
            items.append(_item_from_manifest(manifest, dataset_root))
        return items

    def get_catalog_dir(self, dataset_id: str) -> Path | None:
        from utk_curio.backend.app.datasets.manifest import ManifestError, load_dataset_manifest_from_dir
        from utk_curio.backend.app.datasets.storage import list_catalog_datasets

        for dataset_root in list_catalog_datasets():
            try:
                manifest = load_dataset_manifest_from_dir(dataset_root)
            except ManifestError:
                continue
            if manifest.id == dataset_id:
                return dataset_root
        return None


def _item_from_manifest(manifest: DatasetManifest, dataset_root: Path, *, origin: str = "hub") -> dict[str, Any]:
    data_path = dataset_root / manifest.data_file
    size_bytes = data_path.stat().st_size if data_path.is_file() else None
    updated_at = manifest.updated_at or manifest.created_at or _iso_from_timestamp()
    return _base_item(
        id=manifest.id,
        title=manifest.name,
        description=manifest.description,
        origin=origin,
        format=manifest.format,
        uri=f"curio://hub/{manifest.id}" if origin == "hub" else f"curio://datasets/{manifest.dir_name}",
        path=data_path.as_posix() if data_path.is_file() else None,
        dirName=manifest.dir_name,
        sizeBytes=size_bytes,
        rowCount=manifest.row_count,
        featureCount=manifest.feature_count,
        updatedAt=updated_at,
        sourceLabel=manifest.source_label or manifest.publisher,
        license=manifest.license or None,
        tags=manifest.tags,
        schema=manifest.schema,
    )


class LocalDatasetRepository:
    def _roots(self) -> list[tuple[str, Path]]:
        launch_dir = Path(os.environ.get("CURIO_LAUNCH_CWD", os.getcwd()))
        package_data = Path(__file__).resolve().parents[3] / "data"
        return [
            ("Curio sample data", package_data),
            ("Workspace data", launch_dir / "data"),
        ]

    def list_items(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for source_label, root in self._roots():
            if not root.exists() or not root.is_dir():
                continue
            for path in sorted(root.iterdir()):
                fmt = _format_for_path(path)
                if fmt is None:
                    continue
                # Lazily generate the sidecar for pre-existing files that have
                # never been imported through save_import.
                if not _meta_path(path).exists():
                    row_count, feature_count = _count_file(path, fmt)
                    _write_file_meta(path, row_count, feature_count)
                item = _item_from_file(path, source_label=source_label)
                if item is None or item["id"] in seen:
                    continue
                items.append(item)
                seen.add(item["id"])

        return items

    def save_import(self, file: FileStorage) -> dict[str, Any]:
        filename = secure_filename(file.filename or "")
        if not filename:
            raise DatasetCatalogError("No file selected")
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise DatasetCatalogError(f"Unsupported dataset format: {suffix or filename}")
        launch_dir = Path(os.environ.get("CURIO_LAUNCH_CWD", os.getcwd()))
        data_dir = launch_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        target = data_dir / filename
        file.save(target)
        # Compute counts once at import time and persist to sidecar so that
        # every subsequent catalog listing reads cheaply from the cache.
        fmt = SUPPORTED_SUFFIXES[suffix]
        row_count, feature_count = _count_file(target, fmt)
        _write_file_meta(target, row_count, feature_count)
        item = _item_from_file(target, source_label="Workspace data")
        if item is None:
            raise DatasetCatalogError("Imported file could not be cataloged")
        return item


class ComputedDatasetIndexer:
    def list_items(self, *, manifest: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if not manifest:
            return []
        outputs = manifest.get("outputs", [])
        items: list[dict[str, Any]] = []
        for output in outputs:
            if not isinstance(output, dict):
                continue
            filename = output.get("filename")
            node_id = output.get("node_id")
            if not filename:
                continue
            raw = str(filename)
            fmt = SUPPORTED_SUFFIXES.get(Path(raw).suffix.lower(), "json")
            items.append(_base_item(
                id=_stable_id("computed", f"{node_id}:{raw}"),
                title=Path(raw).stem.replace("_", " ").replace("-", " ").title() or raw,
                description="Dataset computed by a node in the current dataflow.",
                origin="computed",
                format=fmt,
                uri=f"curio://outputs/{raw}",
                path=raw,
                producerNodeId=node_id,
                updatedAt=_iso_from_timestamp(),
                sourceLabel="Current dataflow",
                tags=["computed", fmt],
            ))
        return items


class InstalledDatasetRepository:
    def __init__(self, user: Any | None):
        self.user = user

    def _project_spec_and_manifest(self, dataflow_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if self.user is None:
            raise DatasetCatalogError("Authorization required", 401)
        from utk_curio.backend.app.projects import repositories as projects_repo
        from utk_curio.backend.app.projects import storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        project = projects_repo.get_for_user(dataflow_id, self.user.id)
        user_key = _user_dir_key(self.user)
        spec = storage.read_spec(user_key, project.id) or {}
        manifest = storage.read_manifest(user_key, project.id) or {}
        return spec, manifest

    def list_refs(self, dataflow_id: str | None) -> list[dict[str, Any]]:
        if not dataflow_id:
            return []
        spec, _manifest = self._project_spec_and_manifest(dataflow_id)
        dataflow = spec.get("dataflow") if isinstance(spec, dict) else {}
        refs = dataflow.get("datasets", []) if isinstance(dataflow, dict) else []
        return [r for r in refs if isinstance(r, dict)]

    def list_items(self, dataflow_id: str | None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for ref in self.list_refs(dataflow_id):
            dir_name = ref.get("dirName")

            # Folder-based datasets (hub OR imported): all metadata lives in the
            # installed manifest.  Any ref that carries a dirName is handled here,
            # regardless of origin.
            if dir_name:
                from utk_curio.backend.app.datasets.installer import (
                    InstallerError,
                    resolve_installed_data_path,
                )
                from utk_curio.backend.app.datasets.manifest import (
                    ManifestError,
                    load_dataset_manifest,
                )
                from utk_curio.backend.app.datasets.storage import dataset_dir
                from utk_curio.backend.app.projects.services import _user_dir_key

                user_key = _user_dir_key(self.user)
                installed_dir = dataset_dir(user_key, dir_name)
                try:
                    manifest = load_dataset_manifest(installed_dir)
                    data_path = resolve_installed_data_path(user_key, manifest)
                    item = _item_from_manifest(
                        manifest, installed_dir, origin=ref.get("origin") or "hub"
                    )
                    item["path"] = data_path.as_posix()
                    item["sizeBytes"] = data_path.stat().st_size
                    item["installed"] = True
                    item["producerNodeId"] = ref.get("producerNodeId")
                    item["consumerNodeIds"] = ref.get("consumerNodeIds") or []
                    items.append(item)
                except (InstallerError, ManifestError, OSError):
                    # Dataset not on disk or manifest unreadable – show a
                    # placeholder so the user can see it's broken.
                    items.append(_base_item(
                        id=ref.get("datasetId") or ref.get("id") or dir_name,
                        title=dir_name,
                        description="Dataset is not installed on this machine.",
                        origin=ref.get("origin") or "imported",
                        format=ref.get("format") or "csv",
                        uri=f"curio://datasets/{dir_name}",
                        dirName=dir_name,
                        producerNodeId=ref.get("producerNodeId"),
                        consumerNodeIds=ref.get("consumerNodeIds") or [],
                        installed=True,
                    ))
                continue

            # Legacy fat refs (no dirName): reconstruct from the ref's stored fields.
            fmt = ref.get("format") or "csv"
            items.append(_base_item(
                id=ref.get("datasetId") or ref.get("id") or _stable_id("installed", ref.get("uri", "")),
                title=ref.get("title") or "Installed dataset",
                description=ref.get("description") or "Dataset installed in the current dataflow.",
                origin=ref.get("origin") or "imported",
                format=fmt,
                uri=ref.get("uri") or "",
                path=ref.get("path"),
                dirName=ref.get("dirName"),
                sizeBytes=ref.get("sizeBytes"),
                rowCount=ref.get("rowCount"),
                featureCount=ref.get("featureCount"),
                producerNodeId=ref.get("producerNodeId"),
                consumerNodeIds=ref.get("consumerNodeIds") or [],
                updatedAt=ref.get("updatedAt") or ref.get("installedAt") or _iso_from_timestamp(),
                sourceLabel=ref.get("sourceLabel") or "Current dataflow",
                license=ref.get("license"),
                tags=ref.get("tags") or [fmt],
                installed=True,
            ))
        return items

    def replace_refs(self, dataflow_id: str, refs: list[dict[str, Any]]) -> dict[str, Any]:
        if self.user is None:
            raise DatasetCatalogError("Authorization required", 401)
        from utk_curio.backend.app.projects.schemas import ProjectUpdate
        from utk_curio.backend.app.projects import services as project_services

        spec, _manifest = self._project_spec_and_manifest(dataflow_id)
        dataflow = spec.setdefault("dataflow", {})
        dataflow["datasets"] = refs
        detail = project_services.update_project(
            self.user,
            dataflow_id,
            ProjectUpdate(spec=spec, outputs=None, name=None, description=None, thumbnail_accent=None),
        )
        return detail.spec or spec


class DatasetPreviewService:
    def preview(self, item: dict[str, Any], *, row_limit: int = 50, offset: int = 0) -> dict[str, Any]:
        path_value = item.get("path")
        if not path_value or str(path_value).startswith("curio://"):
            return {
                "schema": item.get("schema") or {"fields": []},
                "rows": [],
                "rowLimit": row_limit,
                "offset": offset,
                "totalRows": item.get("featureCount") or item.get("rowCount") or 0,
                "truncated": False,
                "unsupported": True,
                "message": "Preview is available after the dataset is installed or computed locally.",
            }

        path = Path(path_value)
        if not path.exists() or not path.is_file():
            return {
                "schema": item.get("schema") or {"fields": []},
                "rows": [],
                "rowLimit": row_limit,
                "offset": offset,
                "totalRows": item.get("featureCount") or item.get("rowCount") or 0,
                "truncated": False,
                "unsupported": True,
                "message": "Dataset file is not available on disk.",
            }

        fmt = item.get("format")
        if fmt == "csv":
            return self._preview_csv(path, row_limit, offset, item)
        if fmt == "json":
            return self._preview_json(path, row_limit, offset, item)
        if fmt == "geojson":
            return self._preview_geojson(path, row_limit, offset, item)
        return {
            "schema": {"fields": []},
            "rows": [],
            "rowLimit": row_limit,
            "offset": offset,
            "totalRows": item.get("featureCount") or item.get("rowCount") or 0,
            "truncated": False,
            "unsupported": True,
            "message": f"Preview is not supported for {fmt} datasets yet.",
        }

    def _total_rows(self, item: dict[str, Any], computed: int | None) -> int:
        if computed is not None:
            return computed
        return int(item.get("featureCount") or item.get("rowCount") or 0)

    def _count_csv_rows(self, path: Path) -> int:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            next(reader, None)
            return sum(1 for _ in reader)

    def _infer_fields(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not rows:
            return []
        names: list[str] = []
        for row in rows:
            for key in row.keys():
                if key not in names:
                    names.append(key)
        fields = []
        for name in names:
            sample = next((row.get(name) for row in rows if row.get(name) not in (None, "")), None)
            field_type = "string"
            if isinstance(sample, bool):
                field_type = "boolean"
            elif isinstance(sample, int):
                field_type = "integer"
            elif isinstance(sample, float):
                field_type = "number"
            fields.append({"name": name, "type": field_type, "nullable": True, "sample": sample})
        return fields

    def _preview_csv(self, path: Path, row_limit: int, offset: int, item: dict[str, Any]) -> dict[str, Any]:
        total_rows = self._count_csv_rows(path)
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for index, row in enumerate(reader):
                if index < offset:
                    continue
                if len(rows) >= row_limit:
                    break
                rows.append(dict(row))
        end = offset + len(rows)
        return {
            "schema": {"fields": self._infer_fields(rows) if rows else (item.get("schema") or {}).get("fields", [])},
            "rows": rows,
            "rowLimit": row_limit,
            "offset": offset,
            "totalRows": self._total_rows(item, total_rows),
            "truncated": end < self._total_rows(item, total_rows),
        }

    def _preview_json(self, path: Path, row_limit: int, offset: int, item: dict[str, Any]) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        rows = data if isinstance(data, list) else [data] if isinstance(data, dict) else [{"value": data}]
        total_rows = len(rows)
        page = rows[offset : offset + row_limit]
        display_rows = [row if isinstance(row, dict) else {"value": row} for row in page]
        end = offset + len(display_rows)
        return {
            "schema": {"fields": self._infer_fields(display_rows) if display_rows else (item.get("schema") or {}).get("fields", [])},
            "rows": display_rows,
            "rowLimit": row_limit,
            "offset": offset,
            "totalRows": self._total_rows(item, total_rows),
            "truncated": end < self._total_rows(item, total_rows),
        }

    def _preview_geojson(self, path: Path, row_limit: int, offset: int, item: dict[str, Any]) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        features = data.get("features", []) if isinstance(data, dict) else []
        total_rows = len(features)
        rows = []
        geometry_type = None
        for feature in features[offset : offset + row_limit]:
            props = feature.get("properties") or {}
            geom = feature.get("geometry") or {}
            geometry_type = geometry_type or geom.get("type")
            rows.append({**props, "geometry": geom.get("type")})
        end = offset + len(rows)
        schema_fields = self._infer_fields(rows) if rows else (item.get("schema") or {}).get("fields", [])
        return {
            "schema": {
                "fields": schema_fields,
                "geometryType": geometry_type or (item.get("schema") or {}).get("geometryType"),
                "crs": data.get("crs", {}).get("properties", {}).get("name") if isinstance(data, dict) else None,
            },
            "rows": rows,
            "rowLimit": row_limit,
            "offset": offset,
            "totalRows": self._total_rows(item, total_rows),
            "truncated": end < self._total_rows(item, total_rows),
        }


class DatasetCatalogService:
    def __init__(self, user: Any | None = None):
        self.user = user
        self.registry = DatasetRegistryRepository()
        self.local = LocalDatasetRepository()
        self.installed = InstalledDatasetRepository(user)
        self.computed = ComputedDatasetIndexer()
        self.preview_service = DatasetPreviewService()

    def _user_key(self) -> str:
        if self.user is None:
            raise DatasetCatalogError("Authorization required", 401)
        from utk_curio.backend.app.projects.services import _user_dir_key

        return _user_dir_key(self.user)

    def _resolve_item_path(self, item: dict[str, Any]) -> str | None:
        path_value = item.get("path")
        if path_value and not str(path_value).startswith("curio://"):
            return str(path_value)

        dir_name = item.get("dirName")
        if not dir_name:
            catalog_dir = self.registry.get_catalog_dir(item.get("id", ""))
            if catalog_dir is not None:
                dir_name = catalog_dir.name
            else:
                return None

        from utk_curio.backend.app.datasets.installer import resolve_installed_data_path
        from utk_curio.backend.app.datasets.manifest import ManifestError, load_dataset_manifest
        from utk_curio.backend.app.datasets.storage import catalog_root, dataset_dir

        if self.user is not None:
            user_key = self._user_key()
            user_root = dataset_dir(user_key, dir_name)
            if (user_root / "manifest.json").is_file():
                try:
                    manifest = load_dataset_manifest(user_root)
                    return resolve_installed_data_path(user_key, manifest).as_posix()
                except (ManifestError, Exception):
                    pass

        catalog_root_dir = catalog_root() / dir_name
        if (catalog_root_dir / "manifest.json").is_file():
            try:
                manifest = load_dataset_manifest(catalog_root_dir)
                candidate = catalog_root_dir / manifest.data_file
                if candidate.is_file():
                    return candidate.as_posix()
            except ManifestError:
                return None
        return None

    def _project_manifest(self, dataflow_id: str | None) -> dict[str, Any]:
        if not dataflow_id:
            return {}
        _spec, manifest = self.installed._project_spec_and_manifest(dataflow_id)
        return manifest

    def list_catalog(
        self,
        *,
        dataflow_id: str | None = None,
        q: str | None = None,
        fmt: str | None = None,
        origin: str | None = None,
        sort: str = "recent",
        include_hub: bool = True,
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        if include_hub:
            items.extend(self.registry.list_items())
        if dataflow_id:
            items.extend(self.installed.list_items(dataflow_id))
            items.extend(self.computed.list_items(manifest=self._project_manifest(dataflow_id)))

        installed_ids = {item["id"] for item in self.installed.list_items(dataflow_id) if item.get("id")}
        for item in items:
            if item["id"] in installed_ids:
                item["installed"] = True
        items = self._dedupe_items(items)

        if q:
            needle = q.casefold()
            items = [
                item for item in items
                if needle in " ".join([
                    item.get("title") or "",
                    item.get("description") or "",
                    item.get("sourceLabel") or "",
                    item.get("path") or "",
                    " ".join(item.get("tags") or []),
                ]).casefold()
            ]
        if fmt:
            items = [item for item in items if item.get("format") == fmt]
        if origin:
            items = [item for item in items if item.get("origin") == origin]

        if sort == "name":
            items.sort(key=lambda item: (item.get("title") or "").casefold())
        else:
            items.sort(key=lambda item: item.get("updatedAt") or "", reverse=True)

        return {"items": items, "facets": self._facets(items)}

    def get_dataset(self, dataset_id: str, *, dataflow_id: str | None = None) -> dict[str, Any]:
        for include_hub in (True, False):
            result = self.list_catalog(dataflow_id=dataflow_id, include_hub=include_hub)

            for item in result["items"]:
                if item["id"] == dataset_id:
                    return item
        raise DatasetCatalogError("Dataset not found", 404)

    def preview(
        self,
        dataset_id: str,
        *,
        dataflow_id: str | None = None,
        row_limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        item = deepcopy(self.get_dataset(dataset_id, dataflow_id=dataflow_id))
        resolved = self._resolve_item_path(item)
        if resolved:
            item["path"] = resolved
        return self.preview_service.preview(item, row_limit=row_limit, offset=offset)

    def import_dataset(
        self,
        file: FileStorage,
        *,
        dataflow_id: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        from utk_curio.backend.app.datasets.installer import (
            InstallerError,
            install_imported_file,
        )

        filename = secure_filename(file.filename or "")
        if not filename:
            raise DatasetCatalogError("No file selected")
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise DatasetCatalogError(f"Unsupported dataset format: {suffix or filename}")
        fmt = SUPPORTED_SUFFIXES[suffix]

        user_key = self._user_key()
        file_bytes = file.read()

        try:
            result = install_imported_file(
                user_key, file_bytes, filename, fmt, title=title
            )
        except InstallerError as exc:
            raise DatasetCatalogError(str(exc)) from exc

        # Compute row/feature counts and patch the manifest if they were missing.
        data_path = result.dest / result.manifest.data_file
        row_count, feature_count = _count_file(data_path, fmt)
        if (result.manifest.row_count is None and row_count is not None) or (
            result.manifest.feature_count is None and feature_count is not None
        ):
            _patch_manifest_file(result.dest / "manifest.json", row_count, feature_count)
            _write_file_meta(data_path, row_count, feature_count)

        from utk_curio.backend.app.datasets.manifest import load_dataset_manifest
        manifest = load_dataset_manifest(result.dest)
        item = _item_from_manifest(manifest, result.dest, origin="imported")
        item["path"] = data_path.as_posix()
        item["sizeBytes"] = data_path.stat().st_size
        if row_count is not None:
            item["rowCount"] = row_count
        if feature_count is not None:
            item["featureCount"] = feature_count

        if dataflow_id:
            self.install_dataset(dataflow_id, item["id"], source_item=item)
            item["installed"] = True
        return item

    def publish_dataset(self, dataset_id: str, metadata: dict[str, Any], *, dataflow_id: str | None = None) -> dict[str, Any]:
        from utk_curio.backend.app.datasets.storage import catalog_root

        item = deepcopy(self.get_dataset(dataset_id, dataflow_id=dataflow_id))
        for key in ("title", "description", "license", "tags"):
            if key in metadata:
                item[key] = metadata[key]

        # ── Compute counts from the local data file ──────────────────────────
        local_path: Path | None = None
        path_value = item.get("path")
        if path_value and not str(path_value).startswith("curio://"):
            p = Path(path_value)
            if p.is_file():
                local_path = p

        if local_path is not None:
            fmt = item.get("format", "")
            row_count, feature_count = _count_file(local_path, fmt)
            if row_count is not None and item.get("rowCount") is None:
                item["rowCount"] = row_count
            if feature_count is not None and item.get("featureCount") is None:
                item["featureCount"] = feature_count

        # ── Write to the local catalog ────────────────────────────────────────
        catalog_id = item.get("id", "")
        # Convert file-hash IDs (e.g. "file-abc123") to a valid catalog id
        if not re.match(r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*){1,5}$", catalog_id):
            catalog_id = _catalog_id_from_title(str(item.get("title") or "dataset"))
            item["id"] = catalog_id

        dir_name = f"{catalog_id}@1"
        dest = catalog_root() / dir_name
        (dest / "data").mkdir(parents=True, exist_ok=True)

        # Copy data file into the catalog data/ subdirectory
        data_file = "data/data." + str(item.get("format", "csv"))
        if local_path is not None:
            dest_data = dest / "data" / local_path.name
            shutil.copy2(local_path, dest_data)
            data_file = f"data/{local_path.name}"

        # ── Write manifest.json with all fields ───────────────────────────────
        from utk_curio.backend.app.datasets.manifest import DatasetManifest, write_manifest

        now = _iso_from_timestamp()
        manifest_obj = DatasetManifest(
            id=catalog_id,
            name=item.get("title") or catalog_id,
            version="1.0.0",
            format=item.get("format", "csv"),
            description=item.get("description") or "",
            publisher=str(self.user) if self.user else "Data Hub",
            license=item.get("license") or "MIT",
            tags=item.get("tags") or [],
            data_file=data_file,
            major=1,
            source_label="Data Hub",
            row_count=item.get("rowCount"),
            feature_count=item.get("featureCount"),
            schema=item.get("schema"),
            created_at=item.get("updatedAt") or now,
            updated_at=now,
        )
        write_manifest(manifest_obj, dest)

        item["sourceLabel"] = "Data Hub"
        item["origin"] = "hub"
        item["dirName"] = dir_name
        item["updatedAt"] = _iso_from_timestamp()

        # ── Promote ref in spec.trill to hub so next catalog reload reflects publish ──
        # The original dataset (e.g. imported.x{hash}) may have been stored with
        # origin="imported".  We update the ref so InstalledDatasetRepository returns
        # the correct origin="hub" on the next list, ensuring the Published badge shows.
        if dataflow_id:
            try:
                refs = self.installed.list_refs(dataflow_id)
                changed = False
                for ref in refs:
                    ref_id = ref.get("datasetId") or ref.get("id")
                    # Match by original dataset_id OR new catalog_id (in case ID was remapped)
                    if ref_id in (dataset_id, catalog_id):
                        ref["datasetId"] = catalog_id
                        ref["dirName"] = dir_name
                        ref["origin"] = "hub"
                        changed = True
                if changed:
                    self.installed.replace_refs(dataflow_id, refs)
            except Exception:  # noqa: BLE001 – never block publish on a ref update failure
                pass

        # ── If the dataset ID was remapped, also install the catalog entry into the
        # user's store so the ref's new dirName can be resolved on next list. ─────────
        if catalog_id != dataset_id and dataflow_id:
            try:
                from utk_curio.backend.app.datasets.installer import (
                    InstallerError,
                    install_dataset_from_catalog,
                )
                user_key = self._user_key()
                install_dataset_from_catalog(user_key, dir_name)
            except Exception:  # noqa: BLE001 – best-effort; don't block the publish response
                pass

        return item

    def install_dataset(
        self,
        dataflow_id: str,
        dataset_id: str,
        *,
        source_item: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        item = deepcopy(source_item or self.get_dataset(dataset_id, dataflow_id=dataflow_id))
        if item.get("origin") == "hub":
            dir_name = item.get("dirName")
            if not dir_name:
                raise DatasetCatalogError("Hub dataset is missing catalog directory metadata", 500)
            from utk_curio.backend.app.datasets.installer import (
                InstallerError,
                install_dataset_from_catalog,
                resolve_installed_data_path,
            )

            user_key = self._user_key()
            try:
                result = install_dataset_from_catalog(user_key, dir_name)
                data_path = resolve_installed_data_path(user_key, result.manifest)
            except InstallerError as exc:
                raise DatasetCatalogError(str(exc)) from exc
            item["path"] = data_path.as_posix()
            item["sizeBytes"] = data_path.stat().st_size
            item["dirName"] = dir_name

            # Backfill rowCount/featureCount into the user-store manifest when
            # the hub manifest didn't include them (older catalog entries, etc.)
            if item.get("rowCount") is None and item.get("featureCount") is None:
                fmt = item.get("format", "")
                row_count, feature_count = _count_file(data_path, fmt)
                if row_count is not None:
                    item["rowCount"] = row_count
                if feature_count is not None:
                    item["featureCount"] = feature_count
                if row_count is not None or feature_count is not None:
                    _patch_manifest_file(result.dest / "manifest.json", row_count, feature_count)
                    _write_file_meta(data_path, row_count, feature_count)

        refs = self.installed.list_refs(dataflow_id)
        existing = next((ref for ref in refs if ref.get("datasetId") == item["id"]), None)
        ref = self._ref_from_item(item)
        if existing:
            existing.update(ref)
        else:
            refs.append(ref)
        self.installed.replace_refs(dataflow_id, refs)
        installed_item = deepcopy(item)
        installed_item["origin"] = ref["origin"]
        installed_item["installed"] = True
        return installed_item

    def uninstall_dataset(self, dataflow_id: str, dataset_id: str) -> dict[str, Any]:
        refs = self.installed.list_refs(dataflow_id)
        next_refs = [ref for ref in refs if ref.get("datasetId") != dataset_id and ref.get("id") != dataset_id]
        if len(next_refs) == len(refs):
            raise DatasetCatalogError("Dataset is not installed in this dataflow", 404)
        self.installed.replace_refs(dataflow_id, next_refs)
        return {"datasets": next_refs}

    def legacy_dataset_paths(self) -> list[str]:
        """Return paths for backwards-compatible /datasets route.

        Now that all datasets live in the manifest-backed catalog, this
        delegates to the registry instead of scanning the raw data/ folder.
        """
        items = self.registry.list_items()
        return [item["path"] for item in items if item.get("path")]

    def _dedupe_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_id: dict[str, dict[str, Any]] = {}
        anonymous: list[dict[str, Any]] = []
        for item in items:
            item_id = item.get("id")
            if not item_id:
                anonymous.append(item)
                continue
            by_id[item_id] = item
        return [*by_id.values(), *anonymous]

    def _ref_from_item(self, item: dict[str, Any]) -> dict[str, Any]:
        origin = item.get("origin")
        dir_name = item.get("dirName")

        # Folder-based datasets (hub OR imported): store only the link to the
        # dataset folder.  All metadata is authoritative in manifest.json.
        if dir_name:
            return {
                "datasetId": item["id"],
                "dirName": dir_name,
                "origin": origin or "imported",
                "producerNodeId": item.get("producerNodeId"),
                "consumerNodeIds": item.get("consumerNodeIds") or [],
                "installedAt": _iso_from_timestamp(),
            }

        # Legacy datasets without a folder (computed, source_node, or old
        # imported files): keep a fat ref because there is no manifest to
        # hydrate from at read time.
        ref_origin = origin if origin in {"computed", "source_node"} else "imported"
        return {
            "datasetId": item["id"],
            "title": item.get("title") or "Dataset",
            "description": item.get("description") or "",
            "origin": ref_origin,
            "sourceOrigin": origin,
            "uri": item.get("uri") or "",
            "path": item.get("path"),
            "dirName": dir_name,
            "format": item.get("format") or "csv",
            "sizeBytes": item.get("sizeBytes"),
            "rowCount": item.get("rowCount"),
            "featureCount": item.get("featureCount"),
            "producerNodeId": item.get("producerNodeId"),
            "consumerNodeIds": item.get("consumerNodeIds") or [],
            "sourceLabel": item.get("sourceLabel") or "",
            "license": item.get("license"),
            "tags": item.get("tags") or [],
            "updatedAt": item.get("updatedAt") or _iso_from_timestamp(),
            "installedAt": _iso_from_timestamp(),
        }

    def _facets(self, items: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
        facets = {
            "origin": {"source_node": 0, "computed": 0, "imported": 0, "hub": 0},
            "format": {fmt: 0 for fmt in sorted(set(SUPPORTED_SUFFIXES.values()))},
        }
        for item in items:
            origin = item.get("origin")
            fmt = item.get("format")
            if origin in facets["origin"]:
                facets["origin"][origin] += 1
            if fmt in facets["format"]:
                facets["format"][fmt] += 1
        return facets
