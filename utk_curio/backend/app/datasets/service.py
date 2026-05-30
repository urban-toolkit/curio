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
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename


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
    return _base_item(
        id=_stable_id("file", str(path.resolve())),
        title=title,
        description=f"{fmt.upper()} dataset available in the current workspace.",
        origin=origin,
        format=fmt,
        uri=f"file://{file_path}",
        path=file_path,
        sizeBytes=stat.st_size,
        updatedAt=_iso_from_timestamp(stat.st_mtime),
        sourceLabel=source_label,
        tags=[fmt, origin],
    )


class DatasetRegistryRepository:
    """Fixture-backed Data Hub rows for v1."""

    def list_items(self) -> list[dict[str, Any]]:
        return [
            _base_item(
                id="hub-chicago-boundaries",
                title="Chicago Community Areas",
                description="Boundary geometries for Chicago community areas.",
                origin="hub",
                format="geojson",
                uri="curio://hub/chicago-community-areas",
                path=None,
                featureCount=77,
                sizeBytes=1_800_000,
                updatedAt="2026-05-20T12:00:00Z",
                sourceLabel="Data Hub",
                license="Open Data",
                tags=["boundaries", "chicago", "geojson"],
            ),
            _base_item(
                id="hub-census-acs-profile",
                title="ACS Neighborhood Profile",
                description="Tabular demographic indicators prepared for urban analysis.",
                origin="hub",
                format="csv",
                uri="curio://hub/acs-neighborhood-profile",
                path=None,
                rowCount=2_408,
                sizeBytes=1_200_000,
                updatedAt="2026-05-19T09:00:00Z",
                sourceLabel="Data Hub",
                license="Public domain",
                tags=["acs", "demographics", "csv"],
            ),
            _base_item(
                id="hub-street-vision-sample",
                title="Street Vision Detections",
                description="Sample detections for visual analytics workflows.",
                origin="hub",
                format="json",
                uri="curio://hub/street-vision-detections",
                path=None,
                rowCount=12_800,
                sizeBytes=3_400_000,
                updatedAt="2026-05-17T16:30:00Z",
                sourceLabel="Data Hub",
                license="CC BY 4.0",
                tags=["vision", "detections", "json"],
            ),
        ]


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
            fmt = ref.get("format") or "csv"
            items.append(_base_item(
                id=ref.get("datasetId") or ref.get("id") or _stable_id("installed", ref.get("uri", "")),
                title=ref.get("title") or "Installed dataset",
                description=ref.get("description") or "Dataset installed in the current dataflow.",
                origin=ref.get("origin") or "imported",
                format=fmt,
                uri=ref.get("uri") or "",
                path=ref.get("path"),
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
    def preview(self, item: dict[str, Any], row_limit: int = 50) -> dict[str, Any]:
        path_value = item.get("path")
        if not path_value or str(path_value).startswith("curio://"):
            return {
                "schema": item.get("schema") or {"fields": []},
                "rows": [],
                "rowLimit": row_limit,
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
                "truncated": False,
                "unsupported": True,
                "message": "Dataset file is not available on disk.",
            }

        fmt = item.get("format")
        if fmt == "csv":
            return self._preview_csv(path, row_limit)
        if fmt == "json":
            return self._preview_json(path, row_limit)
        if fmt == "geojson":
            return self._preview_geojson(path, row_limit)
        return {
            "schema": {"fields": []},
            "rows": [],
            "rowLimit": row_limit,
            "truncated": False,
            "unsupported": True,
            "message": f"Preview is not supported for {fmt} datasets yet.",
        }

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

    def _preview_csv(self, path: Path, row_limit: int) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for index, row in enumerate(reader):
                if index >= row_limit:
                    return {
                        "schema": {"fields": self._infer_fields(rows)},
                        "rows": rows,
                        "rowLimit": row_limit,
                        "truncated": True,
                    }
                rows.append(dict(row))
        return {
            "schema": {"fields": self._infer_fields(rows)},
            "rows": rows,
            "rowLimit": row_limit,
            "truncated": False,
        }

    def _preview_json(self, path: Path, row_limit: int) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        rows = data if isinstance(data, list) else [data] if isinstance(data, dict) else [{"value": data}]
        display_rows = [row if isinstance(row, dict) else {"value": row} for row in rows[:row_limit]]
        return {
            "schema": {"fields": self._infer_fields(display_rows)},
            "rows": display_rows,
            "rowLimit": row_limit,
            "truncated": len(rows) > row_limit,
        }

    def _preview_geojson(self, path: Path, row_limit: int) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        features = data.get("features", []) if isinstance(data, dict) else []
        rows = []
        geometry_type = None
        for feature in features[:row_limit]:
            props = feature.get("properties") or {}
            geom = feature.get("geometry") or {}
            geometry_type = geometry_type or geom.get("type")
            rows.append({**props, "geometry": geom.get("type")})
        return {
            "schema": {
                "fields": self._infer_fields(rows),
                "geometryType": geometry_type,
                "crs": data.get("crs", {}).get("properties", {}).get("name") if isinstance(data, dict) else None,
            },
            "rows": rows,
            "rowLimit": row_limit,
            "truncated": len(features) > row_limit,
        }


class DatasetCatalogService:
    def __init__(self, user: Any | None = None):
        self.user = user
        self.registry = DatasetRegistryRepository()
        self.local = LocalDatasetRepository()
        self.installed = InstalledDatasetRepository(user)
        self.computed = ComputedDatasetIndexer()
        self.preview_service = DatasetPreviewService()

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
        items.extend(self.local.list_items())
        if dataflow_id:
            items.extend(self.installed.list_items(dataflow_id))
            items.extend(self.computed.list_items(manifest=self._project_manifest(dataflow_id)))

        installed_ids = {item["id"] for item in self.installed.list_items(dataflow_id) if item.get("id")}
        for item in items:
            if item["id"] in installed_ids:
                item["installed"] = True

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

    def preview(self, dataset_id: str, *, dataflow_id: str | None = None, row_limit: int = 50) -> dict[str, Any]:
        item = self.get_dataset(dataset_id, dataflow_id=dataflow_id)
        return self.preview_service.preview(item, row_limit=row_limit)

    def import_dataset(
        self,
        file: FileStorage,
        *,
        dataflow_id: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        item = self.local.save_import(file)
        if title:
            item["title"] = title
        if dataflow_id:
            self.install_dataset(dataflow_id, item["id"], source_item=item)
            item["installed"] = True
        return item

    def publish_dataset(self, dataset_id: str, metadata: dict[str, Any], *, dataflow_id: str | None = None) -> dict[str, Any]:
        item = deepcopy(self.get_dataset(dataset_id, dataflow_id=dataflow_id))
        for key in ("title", "description", "license", "tags"):
            if key in metadata:
                item[key] = metadata[key]
        item["sourceLabel"] = "Data Hub draft"
        item["origin"] = "hub"
        item["updatedAt"] = _iso_from_timestamp()
        return item

    def install_dataset(
        self,
        dataflow_id: str,
        dataset_id: str,
        *,
        source_item: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        item = deepcopy(source_item or self.get_dataset(dataset_id, dataflow_id=dataflow_id))
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
        return [item["path"] for item in self.local.list_items() if item.get("path")]

    def _ref_from_item(self, item: dict[str, Any]) -> dict[str, Any]:
        origin = item.get("origin")
        ref_origin = origin if origin in {"computed", "source_node"} else "imported"
        return {
            "datasetId": item["id"],
            "title": item.get("title") or "Dataset",
            "description": item.get("description") or "",
            "origin": ref_origin,
            "sourceOrigin": origin,
            "uri": item.get("uri") or "",
            "path": item.get("path"),
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
