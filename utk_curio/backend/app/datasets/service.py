"""Dataset catalog service.

This module intentionally knows nothing about node packages. It normalizes
datasets from three sources: local/imported files, fixture-backed Data Catalog rows,
and datasets already recorded on a saved dataflow.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
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

logger = logging.getLogger(__name__)

def _catalog_item_is_computed_provenance(item: dict[str, Any]) -> bool:
    """Return True when a row should appear under the Data Catalog *Computed* rail.

    Stored ``origin`` may remain ``hub`` for datasets published from node outputs;
    those rows are still surfaced as *computed* using tags / description / producer.
    """
    if item.get("origin") == "computed":
        return True
    if item.get("producerNodeId"):
        return True
    if item.get("origin") != "hub":
        return False
    tags_cf = [str(t).casefold() for t in (item.get("tags") or [])]
    if "computed" in tags_cf:
        return True
    desc = (item.get("description") or "").casefold()
    if "dataflow node" in desc:
        return True
    if "computed" in desc and "node" in desc:
        return True
    sl = (item.get("sourceLabel") or "").strip().casefold()
    if sl == "computed":
        return True
    return False


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
        # Best-effort counts; unreadable or unsupported files return (None, None).
        logger.debug(
            "Could not count rows/features for %s (format=%s); returning None",
            path,
            fmt,
            exc_info=True,
        )
        return None, None
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
        # Optional manifest patch; never break callers on I/O or parse errors.
        logger.debug(
            "Skipping optional manifest patch for %s",
            manifest_path,
            exc_info=True,
        )


def _catalog_id_from_title(title: str) -> str:
    """Generate a local catalog dataset id from a human title.

    Returns a string like ``local.data.<slug>`` that satisfies the
    ``<datasetId>@<major>`` directory-name regex when combined with ``@1``.

    Each dot-segment in a valid dataset ID must start with a letter ``[a-z]``.
    A numeric-leading slug (e.g. from a timestamp-based filename) is prefixed
    with ``d`` so the generated ID always passes the storage regex.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "dataset"
    # Ensure the slug's first character is a letter.
    if slug and not slug[0].isalpha():
        slug = f"d{slug}"
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
            "returnVariable": "df",
        }
    if fmt in {"geojson", "shp"}:
        return {
            "language": "python",
            "imports": ["import geopandas as gpd"],
            "pathVariable": "dataset_path",
            "code": f'dataset_path = "{dataset_path}"\ngdf = gpd.read_file(dataset_path)',
            "returnVariable": "gdf",
        }
    if fmt == "parquet":
        return {
            "language": "python",
            "imports": ["import pandas as pd"],
            "pathVariable": "dataset_path",
            "code": f'dataset_path = "{dataset_path}"\ndf = pd.read_parquet(dataset_path)',
            "returnVariable": "df",
        }
    if fmt == "json":
        return {
            "language": "python",
            "imports": ["import json"],
            "pathVariable": "dataset_path",
            "code": f'dataset_path = "{dataset_path}"\nwith open(dataset_path) as f:\n    data = json.load(f)',
            "returnVariable": "data",
        }
    if fmt == "geotiff":
        return {
            "language": "python",
            "imports": ["import rasterio"],
            "pathVariable": "dataset_path",
            "code": f'dataset_path = "{dataset_path}"\nsrc = rasterio.open(dataset_path)',
            "returnVariable": "src",
        }
    return {
        "language": "python",
        "imports": [],
        "pathVariable": "dataset_path",
        "code": f'dataset_path = "{dataset_path}"',
        "returnVariable": None,
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


def _origin_from_dataflow_ref(ref: dict[str, Any]) -> str:
    """Resolve ``origin`` for a dataflow's installed dataset ref.

    ``hub`` applies only to global registry rows under the repo catalog tree.
    Datasets living in the per-user store stay ``imported``, ``computed``, or
    ``source_node`` regardless of project or publish state (use ``publishedToHub``).
    """
    dir_name = str(ref.get("dirName") or "")
    explicit = ref.get("origin")

    if explicit == "computed" or ref.get("producerNodeId") or dir_name.startswith("computed."):
        return "computed"
    if explicit == "source_node":
        return "source_node"
    if explicit == "hub":
        return "imported"
    if explicit == "imported":
        return "imported"
    return "imported"


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
    """Manifest-backed Data Catalog at ``<repo_root>/datasets/``."""

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
    def list_items(
        self,
        *,
        manifest: dict[str, Any] | None = None,
        live_outputs: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Return catalog items for node-computed outputs.

        Sources (merged, with live_outputs taking precedence over manifest):
        - ``manifest``:     project manifest written to disk on save
        - ``live_outputs``: current session outputs from the frontend
                            (present even when the project hasn't been saved yet)
        """
        # Build a merged list of {node_id, filename} entries.
        # live_outputs override manifest entries for the same node_id so a
        # re-execution is reflected immediately without requiring a save.
        merged: dict[str, dict[str, Any]] = {}  # node_id -> entry

        manifest_outputs = (manifest or {}).get("outputs", []) if manifest else []
        for output in manifest_outputs:
            if isinstance(output, dict) and output.get("node_id") and output.get("filename"):
                merged[output["node_id"]] = output

        for output in (live_outputs or []):
            if isinstance(output, dict) and output.get("node_id") and output.get("filename"):
                merged[output["node_id"]] = output

        items: list[dict[str, Any]] = []
        for output in merged.values():
            filename = output.get("filename")
            node_id = output.get("node_id")
            if not filename:
                continue
            raw = str(filename)
            fmt = SUPPORTED_SUFFIXES.get(Path(raw).suffix.lower(), "json")
            # Use the same stable node-based ID that install_computed_file_for_node
            # writes to the manifest so that the live-output item and the
            # user-store item share the same ID and are correctly deduped.
            if node_id:
                from utk_curio.backend.app.datasets.installer import sanitize_node_id_segment
                item_id = f"computed.{sanitize_node_id_segment(node_id)}"
            else:
                item_id = _stable_id("computed", f"{node_id}:{raw}")
            items.append(_base_item(
                id=item_id,
                title=Path(raw).stem.replace("_", " ").replace("-", " ").title() or raw,
                description="Dataset produced by a node output.",
                origin="computed",
                format=fmt,
                uri=f"curio://outputs/{raw}",
                path=raw,
                producerNodeId=node_id,
                updatedAt=_iso_from_timestamp(),
                sourceLabel="Computed",
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
                try:
                    installed_dir = dataset_dir(user_key, dir_name)
                    manifest = load_dataset_manifest(installed_dir)
                    data_path = resolve_installed_data_path(user_key, manifest)
                    item = _item_from_manifest(
                        manifest, installed_dir, origin=_origin_from_dataflow_ref(ref)
                    )
                    item["path"] = data_path.as_posix()
                    # Keep loaderSnippet in sync with the resolved path.
                    item["loaderSnippet"] = _loader_snippet(item["format"], data_path.as_posix())
                    item["sizeBytes"] = data_path.stat().st_size
                    item["installed"] = True
                    item["producerNodeId"] = ref.get("producerNodeId")
                    item["consumerNodeIds"] = ref.get("consumerNodeIds") or []
                    # Propagate publishedToHub flag so computed datasets can be
                    # shown as published without changing their origin.
                    if ref.get("publishedToHub"):
                        item["publishedToHub"] = True
                    items.append(item)
                except (InstallerError, ManifestError, OSError, ValueError):
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
                description=ref.get("description") or "Dataset installed in this project.",
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
                sourceLabel=ref.get("sourceLabel")
                or (
                    "Computed"
                    if ref.get("origin") == "computed" or ref.get("producerNodeId")
                    else "Imported"
                ),
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
        if fmt == "parquet":
            return self._preview_parquet(path, row_limit, offset, item)
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

    def _preview_parquet(self, path: Path, row_limit: int, offset: int, item: dict[str, Any]) -> dict[str, Any]:
        from utk_curio.sandbox.util.tabular_preview import preview_parquet_file

        try:
            rows, total_rows, _parsed = preview_parquet_file(
                path,
                row_limit=row_limit,
                offset=offset,
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "schema": item.get("schema") or {"fields": []},
                "rows": [],
                "rowLimit": row_limit,
                "offset": offset,
                "totalRows": item.get("featureCount") or item.get("rowCount") or 0,
                "truncated": False,
                "unsupported": True,
                "message": f"Could not read parquet preview: {exc}",
            }

        end = offset + len(rows)
        schema_fields = (item.get("schema") or {}).get("fields", [])
        return {
            "schema": {
                "fields": schema_fields if schema_fields else self._infer_fields(rows),
            },
            "rows": rows,
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

    def _resolve_computed_output_path(self, item: dict[str, Any]) -> str | None:
        """Resolve a ``curio://outputs/{filename}`` URI to an absolute filesystem path.

        Computed datasets live in the shared-data directory written by node
        execution.  This helper maps the virtual URI to the real file so that
        preview and install can both work without any special-casing at call
        sites.

        Falls back to checking the ``artifacts/`` subdirectory for legacy
        DuckDB artifact IDs (bare name, no extension) that were stored in
        project specs before the named-parquet dataset system was introduced.
        """
        uri = item.get("uri") or ""
        if not uri.startswith("curio://outputs/"):
            return None
        filename = uri[len("curio://outputs/"):]
        if not filename:
            return None
        from utk_curio.backend.app.projects.storage import _shared_data_dir

        shared = _shared_data_dir()

        # 1. Exact filename match in the top-level shared-data dir (new-style
        #    named parquet files written by save_dataset_parquet).
        candidate = shared / filename
        if candidate.is_file():
            return candidate.as_posix()

        # 2. Legacy DuckDB artifact: the path stored in the ref is the bare
        #    artifact ID (no extension).  DuckDB saves these as
        #    ``artifacts/<id>.parquet`` inside the shared-data dir.  Only
        #    parquet files are returned — compressed JSON artifacts
        #    (.json.zlib) are an internal format and cannot be loaded with
        #    standard Python tooling.
        if "." not in Path(filename).name:
            artifact_parquet = shared / "artifacts" / f"{filename}.parquet"
            if artifact_parquet.is_file():
                return artifact_parquet.as_posix()

        return None

    def _resolve_item_path(self, item: dict[str, Any]) -> str | None:
        # ── Computed datasets must be resolved via the shared-data directory
        # first, regardless of what the ``path`` field says (it is just the
        # bare filename, not an absolute path).
        if item.get("origin") == "computed":
            resolved = self._resolve_computed_output_path(item)
            if resolved:
                return resolved
            return None

        path_value = item.get("path")
        uri_value = item.get("uri") or ""

        # Resolve curio://outputs/ for items that carry that URI scheme (legacy
        # fat refs stored before the origin field existed use this URI even
        # when origin is "imported").  Check the item URI, not just the path,
        # because the path may be a bare artifact ID with no curio:// prefix.
        if uri_value.startswith("curio://outputs/"):
            resolved = self._resolve_computed_output_path(item)
            if resolved:
                return resolved
            return None  # artifact gone – caller will show unsupported preview

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
        live_outputs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        if include_hub:
            items.extend(self.registry.list_items())
        if dataflow_id:
            items.extend(self.installed.list_items(dataflow_id))
            items.extend(self.computed.list_items(
                manifest=self._project_manifest(dataflow_id),
                live_outputs=live_outputs,
            ))
        elif live_outputs:
            # No project yet (unsaved new dataflow) but live outputs provided —
            # still show computed items so outputs are visible immediately.
            items.extend(self.computed.list_items(live_outputs=live_outputs))

        inst_items = self.installed.list_items(dataflow_id)
        installed_ids = {item["id"] for item in inst_items if item.get("id")}

        # Map producerNodeId → installed output basename for computed datasets.
        # Used to determine whether the node has been re-executed since the last
        # install: if the current output filename differs from the installed one
        # the node was re-run and a "Reinstall" prompt is warranted.
        installed_computed_filenames: dict[str, str] = {}
        for inst_item in inst_items:
            pid = inst_item.get("producerNodeId")
            if pid and inst_item.get("origin") == "computed":
                inst_path = inst_item.get("path") or ""
                installed_computed_filenames[pid] = Path(inst_path).name if inst_path else ""

        for item in items:
            if item["id"] in installed_ids:
                item["installed"] = True
            elif item.get("origin") == "computed":
                pid = item.get("producerNodeId")
                if pid and pid in installed_computed_filenames:
                    item["installed"] = True
                    # Only flag needsReinstall when the node produced a NEW output
                    # file after the last install (filenames differ).  If the
                    # filename is unchanged the node has not been re-executed and
                    # the "Reinstall" button should not appear.
                    current_filename = Path(item.get("path") or "").name
                    installed_filename = installed_computed_filenames[pid]
                    if current_filename and installed_filename and current_filename != installed_filename:
                        item["needsReinstall"] = True
        items = self._dedupe_items(items)

        # Enrich computed items: resolve their bare filename to an absolute path
        # so the loader snippet points to a real file.  This must happen after
        # deduplication so we don't do wasted work on duplicates.
        #
        # Also covers legacy "fat refs" stored in old project specs: those refs
        # carry a ``curio://outputs/`` URI but may have ``origin == "imported"``
        # (or no origin at all) because they predate the ``origin`` field.
        for item in items:
            uri = item.get("uri") or ""
            is_outputs_uri = uri.startswith("curio://outputs/")
            if item.get("origin") == "computed" or is_outputs_uri:
                # Auto-installed copies already carry an absolute path into the
                # user's dataset store — do not replace it with the ephemeral
                # shared-data parquet used only for live discovery.
                path_val = item.get("path") or ""
                if path_val and Path(path_val).is_file():
                    item["loaderSnippet"] = _loader_snippet(item["format"], path_val)
                    continue
                resolved = self._resolve_computed_output_path(item)
                if resolved:
                    # If the resolved file is a parquet but the stored format
                    # differs (e.g. legacy "json" artifact), update the format
                    # so the loader snippet uses the right reader.
                    resolved_ext = Path(resolved).suffix.lower()
                    if resolved_ext in SUPPORTED_SUFFIXES:
                        item["format"] = SUPPORTED_SUFFIXES[resolved_ext]
                    item["path"] = resolved
                    item["loaderSnippet"] = _loader_snippet(item["format"], resolved)
                elif is_outputs_uri:
                    # The URI looks like an output but the file no longer
                    # exists on disk.  Replace the stale relative path with
                    # None so the loader snippet shows a clear placeholder
                    # rather than a bare artifact ID that Python can't open.
                    path_val = item.get("path") or ""
                    if not path_val or not Path(path_val).is_absolute():
                        item["path"] = None
                        item["loaderSnippet"] = _loader_snippet(item["format"], None)

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

        # Facet counts should reflect the same universe as search (q), not the
        # narrowed list after format/origin filters — otherwise rails show zeros
        # or misleading counts while other filters are active.
        facets = self._facets(items)

        if fmt:
            items = [item for item in items if item.get("format") == fmt]
        if origin:
            if origin == "imported":
                items = [item for item in items if not _catalog_item_is_computed_provenance(item)]
            elif origin == "computed":
                items = [item for item in items if _catalog_item_is_computed_provenance(item)]
            else:
                items = [item for item in items if item.get("origin") == origin]

        if sort == "name":
            items.sort(key=lambda item: (item.get("title") or "").casefold())
        else:
            items.sort(key=lambda item: item.get("updatedAt") or "", reverse=True)

        return {"items": items, "facets": facets}

    def get_dataset(self, dataset_id: str, *, dataflow_id: str | None = None, live_outputs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        for include_hub in (True, False):
            result = self.list_catalog(dataflow_id=dataflow_id, include_hub=include_hub, live_outputs=live_outputs)

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
        # Keep loaderSnippet in sync with the resolved path.
        item["loaderSnippet"] = _loader_snippet(item["format"], data_path.as_posix())
        item["sizeBytes"] = data_path.stat().st_size
        if row_count is not None:
            item["rowCount"] = row_count
        if feature_count is not None:
            item["featureCount"] = feature_count

        if dataflow_id:
            self.install_dataset(dataflow_id, item["id"], source_item=item)
            item["installed"] = True
        return item

    def publish_dataset(self, dataset_id: str, metadata: dict[str, Any], *, dataflow_id: str | None = None, live_outputs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        from utk_curio.backend.app.datasets.storage import catalog_root

        item = deepcopy(self.get_dataset(dataset_id, dataflow_id=dataflow_id, live_outputs=live_outputs))
        for key in ("title", "description", "license", "tags"):
            if key in metadata:
                item[key] = metadata[key]

        publish_is_computed = item.get("origin") == "computed" or bool(item.get("producerNodeId"))
        prior_source_label = item.get("sourceLabel")
        prior_producer_node_id = item.get("producerNodeId")

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
            publisher=str(self.user) if self.user else "Data Catalog",
            license=item.get("license") or "MIT",
            tags=item.get("tags") or [],
            data_file=data_file,
            major=1,
            source_label="Computed" if publish_is_computed else "Data Catalog",
            row_count=item.get("rowCount"),
            feature_count=item.get("featureCount"),
            schema=item.get("schema"),
            created_at=item.get("updatedAt") or now,
            updated_at=now,
        )
        write_manifest(manifest_obj, dest)

        item["dirName"] = dir_name
        item["updatedAt"] = _iso_from_timestamp()
        if publish_is_computed:
            item["origin"] = "computed"
            item["producerNodeId"] = prior_producer_node_id
            item["publishedToHub"] = True
            sl = (prior_source_label or "").strip()
            bad = ("data catalog", "data hub", "current dataflow", "current workflow")
            if sl and sl.lower() not in bad:
                item["sourceLabel"] = prior_source_label
            else:
                item["sourceLabel"] = "Computed"
        else:
            item["sourceLabel"] = "Data Catalog"
            item["origin"] = "hub"

        # ── Update dataflow ref so the next catalog reload shows publish state ──
        # The canonical catalog entry is ``origin="hub"`` under ``datasets/``; the
        # dataflow ref still points at the user-store copy and keeps
        # ``imported`` / ``computed`` provenance (``publishedToHub`` for the badge).
        if dataflow_id:
            try:
                refs = self.installed.list_refs(dataflow_id)
                changed = False
                for ref in refs:
                    ref_id = ref.get("datasetId") or ref.get("id")
                    # Match by id, or (computed) any ref for the same producer node so
                    # project refs keyed as ``computed.<node>`` update when publish is
                    # invoked with the hub / remapped catalog id from the Data Catalog page.
                    matches_producer = bool(
                        publish_is_computed
                        and prior_producer_node_id
                        and ref.get("producerNodeId") == prior_producer_node_id,
                    )
                    if ref_id in (dataset_id, catalog_id) or matches_producer:
                        ref["datasetId"] = catalog_id
                        ref["dirName"] = dir_name
                        # Computed datasets keep origin="computed" always; track publish
                        # state with a separate publishedToHub flag so the frontend can
                        # show the correct Published badge without changing the origin.
                        if ref.get("origin") == "computed" or ref.get("producerNodeId"):
                            ref["publishedToHub"] = True
                            # Ensure origin is "computed" (not "hub") for computed datasets
                            ref.setdefault("origin", "computed")
                        else:
                            ref["publishedToHub"] = True
                            # Keep provenance: published copies in the user store stay imported.
                            if ref.get("origin") == "source_node":
                                pass
                            else:
                                ref["origin"] = "imported"
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
                raise DatasetCatalogError("Catalog dataset is missing catalog directory metadata", 500)
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

            # Project install is a user-store copy — not a global hub row.
            item["origin"] = "imported"
            item["uri"] = f"curio://datasets/{dir_name}"

        elif item.get("origin") == "computed":
            # ── Promote a node-computed output to a persistent installed dataset.
            #
            # Computed datasets live as raw files in the shared-data directory
            # while the workflow is active, but they are ephemeral — they
            # disappear when the project is unloaded.  "Installing" a computed
            # dataset copies the file into the user's dataset store, writes a
            # proper manifest.json, and registers it as ``origin="computed"``
            # keyed on the producer node ID.  Re-running "Install" (Reinstall)
            # replaces the same ``computed.<node_id>@1`` folder so the dataset
            # ID remains stable across multiple node executions.
            #
            # If no producerNodeId is known (legacy items) we fall back to the
            # old content-hash naming.
            #
            # Fast-path: if the item was already auto-installed by the execution
            # route (has a dirName pointing to the user's dataset store) we skip
            # re-copying the file and just fall through to the ref-write below.
            already_in_store = bool(item.get("dirName"))
            if not already_in_store:
                resolved = self._resolve_computed_output_path(item)
                if resolved is None:
                    raise DatasetCatalogError(
                        "Computed output file is not available. Run the dataflow node first.",
                        404,
                    )
                data_path = Path(resolved)
                suffix = data_path.suffix.lower()
                fmt = SUPPORTED_SUFFIXES.get(suffix, "json")

                producer_node_id = item.get("producerNodeId")

                if producer_node_id:
                    from utk_curio.backend.app.datasets.installer import (
                        InstallerError,
                        install_computed_file_for_node,
                        resolve_installed_data_path,
                    )

                    user_key = self._user_key()
                    file_bytes = data_path.read_bytes()
                    try:
                        result = install_computed_file_for_node(
                            user_key, file_bytes, data_path.name, fmt,
                            node_id=producer_node_id,
                            title=item.get("title"),
                        )
                    except InstallerError as exc:
                        raise DatasetCatalogError(str(exc)) from exc
                else:
                    from utk_curio.backend.app.datasets.installer import (
                        InstallerError,
                        install_computed_file,
                        resolve_installed_data_path,
                    )

                    user_key = self._user_key()
                    file_bytes = data_path.read_bytes()
                    try:
                        result = install_computed_file(
                            user_key, file_bytes, data_path.name, fmt,
                            title=item.get("title"),
                            node_id=producer_node_id,
                        )
                    except InstallerError as exc:
                        raise DatasetCatalogError(str(exc)) from exc

                inst_data_path = resolve_installed_data_path(user_key, result.manifest)

                # Compute row/feature counts and patch the sidecar.
                row_count, feature_count = _count_file(inst_data_path, fmt)
                if (result.manifest.row_count is None and row_count is not None) or (
                    result.manifest.feature_count is None and feature_count is not None
                ):
                    _patch_manifest_file(result.dest / "manifest.json", row_count, feature_count)
                    _write_file_meta(inst_data_path, row_count, feature_count)

                from utk_curio.backend.app.datasets.manifest import load_dataset_manifest

                installed_manifest = load_dataset_manifest(result.dest)
                installed_item = _item_from_manifest(installed_manifest, result.dest, origin="computed")
                installed_item["path"] = inst_data_path.as_posix()
                installed_item["sizeBytes"] = inst_data_path.stat().st_size
                if row_count is not None:
                    installed_item["rowCount"] = row_count
                if feature_count is not None:
                    installed_item["featureCount"] = feature_count
                # Preserve the producer link so the catalog can show the connection.
                installed_item["producerNodeId"] = item.get("producerNodeId")
                item = installed_item

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
        removed_ref = next(
            (ref for ref in refs if ref.get("datasetId") == dataset_id or ref.get("id") == dataset_id),
            None,
        )
        next_refs = [ref for ref in refs if ref.get("datasetId") != dataset_id and ref.get("id") != dataset_id]
        if len(next_refs) == len(refs):
            raise DatasetCatalogError("Dataset is not installed in this dataflow", 404)
        self.installed.replace_refs(dataflow_id, next_refs)

        # For computed datasets, also remove the folder from the user's dataset store
        # so the dataset is fully gone (it can be regenerated by re-running the node).
        if removed_ref and removed_ref.get("origin") == "computed" and self.user is not None:
            dir_name = removed_ref.get("dirName")
            if dir_name:
                try:
                    from utk_curio.backend.app.datasets.storage import dataset_dir
                    dest = dataset_dir(self._user_key(), dir_name)
                    if dest.exists():
                        shutil.rmtree(dest, ignore_errors=True)
                except Exception:  # noqa: BLE001
                    pass

        return {"datasets": next_refs}

    def unpublish_dataset(self, dataset_id: str, *, dataflow_id: str | None = None) -> dict[str, Any]:
        """Remove a dataset from the local Data Catalog directory.

        The dataset must exist in the committed catalog tree. Project refs keep
        ``imported`` / ``computed`` provenance; only ``publishedToHub`` is cleared.
        The user's store copy (if any) is left intact.
        """
        from utk_curio.backend.app.datasets.storage import catalog_root

        # Locate the catalog directory for this dataset.
        root = catalog_root()
        catalog_dir: Path | None = None
        for d in root.iterdir():
            if not d.is_dir():
                continue
            # The dir_name is typically <catalog_id>@<major>
            base = d.name.split("@")[0] if "@" in d.name else d.name
            if base == dataset_id or d.name == dataset_id:
                catalog_dir = d
                break

        if catalog_dir is None:
            raise DatasetCatalogError(f"Dataset '{dataset_id}' is not in the Data Catalog", 404)

        dir_name = catalog_dir.name

        # Before removing the catalog folder, ensure the user's own dataset store has
        # a copy so that the spec ref's dirName continues to resolve after unpublish.
        # This also preserves the manifest.json (and therefore the dataset title).
        if self.user is not None:
            try:
                from utk_curio.backend.app.datasets.installer import (
                    install_dataset_from_catalog,
                )
                install_dataset_from_catalog(self._user_key(), dir_name, replace=False)
            except Exception:  # noqa: BLE001
                pass

        # Remove the catalog directory tree.
        shutil.rmtree(catalog_dir, ignore_errors=True)

        # Revert the spec.trill.json ref back to 'imported' origin so the dataset
        # keeps working from the user's store.  Keep dirName so the manifest (and
        # therefore the title) is still readable from the user's local copy.
        if dataflow_id:
            try:
                refs = self.installed.list_refs(dataflow_id)
                changed = False
                for ref in refs:
                    ref_id = ref.get("datasetId") or ref.get("id")
                    if ref_id == dataset_id or ref.get("dirName", "").split("@")[0] == dataset_id:
                        # Computed datasets keep origin="computed"; only clear the publishedToHub flag.
                        # Non-computed datasets revert to "imported".
                        if ref.get("origin") == "computed" or ref.get("producerNodeId"):
                            ref["publishedToHub"] = False
                            ref.setdefault("origin", "computed")
                        else:
                            ref["origin"] = "imported"
                            ref["publishedToHub"] = False
                        # Keep dirName – it now points to the user's store copy.
                        changed = True
                if changed:
                    self.installed.replace_refs(dataflow_id, refs)
            except Exception:  # noqa: BLE001
                pass

        return {"id": dataset_id, "unpublished": True}

    def legacy_dataset_paths(self) -> list[str]:
        """Return paths for backwards-compatible /datasets route.

        Now that all datasets live in the manifest-backed catalog, this
        delegates to the registry instead of scanning the raw data/ folder.
        """
        items = self.registry.list_items()
        return [item["path"] for item in items if item.get("path")]

    @staticmethod
    def _catalog_item_rank(item: dict[str, Any]) -> int:
        """Higher rank = richer catalog record (prefer when deduping by id)."""
        score = 0
        if item.get("dirName"):
            score += 8
        path_val = item.get("path") or ""
        if path_val and Path(path_val).is_absolute() and Path(path_val).is_file():
            score += 4
        if item.get("installed"):
            score += 2
        uri = item.get("uri") or ""
        if not uri.startswith("curio://outputs/"):
            score += 1
        return score

    @classmethod
    def _merge_catalog_items(cls, existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        """Merge two catalog rows that share the same id."""
        winner = existing if cls._catalog_item_rank(existing) >= cls._catalog_item_rank(incoming) else incoming
        loser = incoming if winner is existing else existing
        merged = dict(winner)
        if loser.get("installed"):
            merged["installed"] = True
        if loser.get("needsReinstall"):
            merged["needsReinstall"] = True
        if not merged.get("dirName") and loser.get("dirName"):
            merged["dirName"] = loser["dirName"]
        if not merged.get("producerNodeId") and loser.get("producerNodeId"):
            merged["producerNodeId"] = loser["producerNodeId"]
        if not merged.get("publishedToHub") and loser.get("publishedToHub"):
            merged["publishedToHub"] = loser["publishedToHub"]
        # Hub registry rows do not carry ``publishedToHub``; merge must still reflect
        # that the dataset is listed in the committed Data Catalog when the same id
        # appears as a project ``computed`` / live row (or publish ran without ref sync).
        if winner.get("origin") == "hub" or loser.get("origin") == "hub":
            merged["publishedToHub"] = True
        # Prefer project provenance when the same id appears as hub (registry) + installed copy.
        win_o, los_o = winner.get("origin"), loser.get("origin")
        if merged.get("installed") and win_o == "hub" and los_o in ("imported", "computed", "source_node"):
            merged["origin"] = los_o
        elif merged.get("installed") and los_o == "hub" and win_o in ("imported", "computed", "source_node"):
            merged["origin"] = win_o
        # Node-produced rows must never pick up the global catalog listing subtitle.
        if (
            winner.get("origin") == "computed"
            or loser.get("origin") == "computed"
            or winner.get("producerNodeId")
            or loser.get("producerNodeId")
        ):
            merged["origin"] = "computed"
            pid = merged.get("producerNodeId") or winner.get("producerNodeId") or loser.get("producerNodeId")
            if pid:
                merged["producerNodeId"] = pid
            chosen_sl = None
            bad_sl = frozenset(
                {"data catalog", "data hub", "current dataflow", "current workflow"},
            )
            for cand in (winner, loser):
                if cand.get("origin") == "computed" or cand.get("producerNodeId"):
                    lab = (cand.get("sourceLabel") or "").strip()
                    if lab and lab.lower() not in bad_sl:
                        chosen_sl = cand.get("sourceLabel")
                        break
            merged["sourceLabel"] = chosen_sl or "Computed"
        return merged

    def _dedupe_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_id: dict[str, dict[str, Any]] = {}
        anonymous: list[dict[str, Any]] = []
        for item in items:
            item_id = item.get("id")
            if not item_id:
                anonymous.append(item)
                continue
            prev = by_id.get(item_id)
            by_id[item_id] = item if prev is None else self._merge_catalog_items(prev, item)
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
            fmt = item.get("format")
            if fmt in facets["format"]:
                facets["format"][fmt] += 1
            if _catalog_item_is_computed_provenance(item):
                facets["origin"]["computed"] += 1
            else:
                raw_origin = item.get("origin")
                if raw_origin in facets["origin"]:
                    facets["origin"][raw_origin] += 1
        return facets
