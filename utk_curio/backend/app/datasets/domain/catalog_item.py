"""Build normalized catalog item dicts from files, manifests, and refs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from utk_curio.backend.app.datasets.infrastructure.catalog_utils import iso_from_timestamp, stable_id, title_from_filename
from utk_curio.backend.app.datasets.domain.constants import SUPPORTED_SUFFIXES
from utk_curio.backend.app.datasets.infrastructure.file_meta import read_file_meta
from utk_curio.backend.app.datasets.domain.manifest import DatasetManifest


def format_for_path(path: Path) -> str | None:
    return SUPPORTED_SUFFIXES.get(path.suffix.lower())


# Loader body for ``format: bundle`` datasets (multi-output / tuple node results).
# Reads ``data/bundle.json`` + ``data/parts/*`` and returns the parts as a tuple so
# the sandbox re-detects the same ``outputs`` envelope the producing node emitted.
# Note: the only ``{}`` here is the ``{bundle_path}`` placeholder (no dict literals),
# so ``str.format`` is safe.
_BUNDLE_LOADER_CODE = '''bundle_path = "{bundle_path}"
def _curio_load_bundle(path):
    base = os.path.dirname(os.path.dirname(path))
    with open(path) as f:
        spec = json.load(f)
    items = []
    for part in sorted(spec.get("parts", []), key=lambda p: p.get("index", 0)):
        fmt, kind = part.get("format"), part.get("kind")
        file_path = os.path.join(base, part["file"]) if part.get("file") else None
        if fmt == "parquet":
            try:
                value = gpd.read_parquet(file_path)
            except Exception:
                value = pd.read_parquet(file_path)
        elif fmt == "csv":
            value = pd.read_csv(file_path)
        elif fmt in ("geojson", "shp"):
            value = gpd.read_file(file_path)
        elif fmt == "geotiff":
            import rasterio
            value = rasterio.open(file_path)
        else:
            with open(file_path) as part_file:
                loaded = json.load(part_file)
            if kind in ("int", "float", "bool", "str", "null") and isinstance(loaded, dict) and "value" in loaded:
                value = loaded["value"]
            else:
                value = loaded
        items.append(value)
    return tuple(items)
bundle = _curio_load_bundle(bundle_path)'''


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
        # Computed GeoDataFrames are stored as GeoParquet (geometry + CRS
        # preserved); plain DataFrames as ordinary parquet. Read with
        # ``gpd.read_parquet`` first so a geo dataset reloads as a GeoDataFrame
        # — matching the output type/schema of the node that produced it — and
        # fall back to ``pd.read_parquet`` for non-geo tables.
        return {
            "language": "python",
            "imports": ["import os", "import json", "import pandas as pd", "import geopandas as gpd"],
            "pathVariable": "dataset_path",
            "code": (
                f'dataset_path = "{dataset_path}"\n'
                "try:\n"
                "    df = gpd.read_parquet(dataset_path)\n"
                "except Exception:\n"
                "    df = pd.read_parquet(dataset_path)\n"
                "# Restore object columns (dict/list cells) that were JSON-encoded\n"
                "# on save; the column list lives in a <file>.decode.json sidecar.\n"
                "_meta_path = dataset_path + \".decode.json\"\n"
                "if os.path.exists(_meta_path):\n"
                "    with open(_meta_path) as _meta_file:\n"
                "        _encoded_cols = json.load(_meta_file).get(\"encoded_object_columns\", [])\n"
                "    for _col in _encoded_cols:\n"
                "        if _col in df.columns:\n"
                "            df[_col] = df[_col].apply(lambda _v: json.loads(_v) if isinstance(_v, str) and _v else _v)"
            ),
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
    if fmt == "bundle":
        # A bundle is a multi-output (tuple / ``outputs``) node result, stored as
        # ``data/bundle.json`` + ``data/parts/*`` under the dataset dir. Rebuild
        # each part with the reader matching its kind and return them as a tuple,
        # so the sandbox re-detects an ``outputs`` envelope identical to the one
        # the producing node emitted (same parts, order, and types/schema).
        return {
            "language": "python",
            "imports": [
                "import json",
                "import os",
                "import pandas as pd",
                "import geopandas as gpd",
            ],
            "pathVariable": "bundle_path",
            "code": _BUNDLE_LOADER_CODE.format(bundle_path=dataset_path),
            "returnVariable": "bundle",
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
        "fileName": None,
        "description": "",
        "origin": "imported",
        "format": "csv",
        "uri": "",
        "path": None,
        "sizeBytes": None,
        "rowCount": None,
        "featureCount": None,
        "producerNodeId": None,
        # Authoritative producer info, resolved across the user's projects (not
        # just the open dataflow) so a computed dataset opened from a dataflow
        # that only imported it still shows its true generating node. Populated
        # by ``get_dataset(resolve_producer=True)``; ``None`` otherwise.
        "producerNodeType": None,
        "producerDataflowId": None,
        "producerDataflowName": None,
        "consumerNodeIds": [],
        # Real count of nodes consuming this dataset, summed across the user's
        # dataflows. Populated by ``list_catalog`` from the dependency-graph
        # resolver; ``consumerNodeIds`` (a canvas-binding concept) stays empty in
        # persisted specs and must not be used for this count. See
        # ``CatalogListing._consumer_counts``.
        "consumerNodeCount": 0,
        # ``createdAt`` / ``updatedAt`` are the Curio *record* dates (when the
        # dataset was created/imported and last changed in Curio).
        # ``sourceUpdatedAt`` is the *original source file's* last-modified date,
        # kept distinct so the UI never conflates the two. ``None`` when unknown.
        "createdAt": None,
        "updatedAt": iso_from_timestamp(),
        "sourceUpdatedAt": None,
        # When this dataset was installed into the current dataflow (from the
        # project ref's ``installedAt``). Distinct from ``createdAt`` (import /
        # record creation). ``None`` for datasets not installed in a dataflow.
        "installedAt": None,
        "sourceLabel": "",
        "license": None,
        "tags": [],
        "schema": None,
        "loaderSnippet": None,
        "installed": False,
        # Grouping for multi-part imports (OSM PBF layers). ``groupId`` links the
        # sibling layer datasets; ``layerName`` is this dataset's layer.
        "groupId": None,
        "layerName": None,
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
    title = title_from_filename(path.name)
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
    created_at = manifest.created_at or manifest.updated_at or updated_at
    return base_item(
        id=manifest.id,
        title=manifest.name,
        # The generated data-file name, kept as a distinct field so a computed
        # dataset's ``title`` can carry the producing node's name while the
        # original filename stays available for display (see datasetSubtitle).
        fileName=title_from_filename(Path(manifest.data_file).name),
        description=manifest.description,
        origin=origin,
        format=manifest.format,
        uri=f"curio://hub/{manifest.id}" if origin == "hub" else f"curio://datasets/{manifest.dir_name}",
        path=data_path.as_posix() if data_path.is_file() else None,
        dirName=manifest.dir_name,
        sizeBytes=size_bytes,
        rowCount=manifest.row_count,
        featureCount=manifest.feature_count,
        createdAt=created_at,
        updatedAt=updated_at,
        sourceUpdatedAt=manifest.source_updated_at,
        sourceLabel=manifest.source_label or manifest.publisher,
        license=manifest.license or None,
        tags=manifest.tags,
        schema=manifest.schema,
        groupId=manifest.group_id,
        layerName=manifest.layer_name,
    )
