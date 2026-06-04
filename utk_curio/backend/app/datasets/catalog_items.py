"""Build normalized catalog item dicts from files, manifests, and refs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from utk_curio.backend.app.datasets.catalog_utils import iso_from_timestamp, stable_id
from utk_curio.backend.app.datasets.constants import SUPPORTED_SUFFIXES
from utk_curio.backend.app.datasets.file_meta import read_file_meta
from utk_curio.backend.app.datasets.manifest import DatasetManifest


def format_for_path(path: Path) -> str | None:
    return SUPPORTED_SUFFIXES.get(path.suffix.lower())


def loader_snippet(fmt: str, path: str | None) -> dict[str, Any]:
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


def base_item(**overrides: Any) -> dict[str, Any]:
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
        "updatedAt": iso_from_timestamp(),
        "sourceLabel": "",
        "license": None,
        "tags": [],
        "schema": None,
        "loaderSnippet": None,
        "installed": False,
    }
    item.update(overrides)
    if item["loaderSnippet"] is None:
        item["loaderSnippet"] = loader_snippet(item["format"], item.get("path"))
    return item


def origin_from_dataflow_ref(ref: dict[str, Any]) -> str:
    """Resolve ``origin`` for a dataflow's installed dataset ref."""
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


def item_from_file(path: Path, *, source_label: str, origin: str = "imported") -> dict[str, Any] | None:
    fmt = format_for_path(path)
    if fmt is None or not path.is_file():
        return None
    stat = path.stat()
    file_path = path.as_posix()
    title = path.stem.replace("_", " ").replace("-", " ").strip().title() or path.name
    row_count, feature_count = read_file_meta(path)
    return base_item(
        id=stable_id("file", str(path.resolve())),
        title=title,
        description=f"{fmt.upper()} dataset available in the current workspace.",
        origin=origin,
        format=fmt,
        uri=f"file://{file_path}",
        path=file_path,
        sizeBytes=stat.st_size,
        rowCount=row_count,
        featureCount=feature_count,
        updatedAt=iso_from_timestamp(stat.st_mtime),
        sourceLabel=source_label,
        tags=[fmt, origin],
    )


def item_from_manifest(manifest: DatasetManifest, dataset_root: Path, *, origin: str = "hub") -> dict[str, Any]:
    data_path = dataset_root / manifest.data_file
    size_bytes = data_path.stat().st_size if data_path.is_file() else None
    updated_at = manifest.updated_at or manifest.created_at or iso_from_timestamp()
    return base_item(
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
