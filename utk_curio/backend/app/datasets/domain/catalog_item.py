"""Build normalized catalog item dicts from files, manifests, and refs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from utk_curio.backend.app.datasets.infrastructure.catalog_utils import iso_from_timestamp, stable_id, title_from_filename
from utk_curio.backend.app.datasets.domain.constants import AUTARK_LAYER_TYPES, SUPPORTED_SUFFIXES
from utk_curio.backend.app.datasets.infrastructure.file_meta import read_file_meta
from utk_curio.backend.app.datasets.domain.manifest import DatasetManifest


def format_for_path(path: Path) -> str | None:
    return SUPPORTED_SUFFIXES.get(path.suffix.lower())


# Dataset ids are interpolated into generated Python source, so only ids matching
# this whitelist may appear inside a ``curio_data_path("<id>")`` call. Ids can
# come from user-editable spec JSON (legacy ref fallbacks), so an id with a quote
# or backslash would otherwise break out of the string literal. Must stay in sync
# with the scan regex in api/routes.py and SAFE_DATASET_ID_RE in the frontend
# datasetLoaderSnippets.ts.
_SAFE_DATASET_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,199}$")


def _safe_dataset_id(dataset_id: Any) -> str | None:
    if not isinstance(dataset_id, str) or not _SAFE_DATASET_ID_RE.match(dataset_id):
        return None
    return dataset_id


def is_safe_dataset_id(dataset_id: Any) -> bool:
    """True when *dataset_id* may appear inside a generated ``curio_load_data("<id>")``."""
    return _safe_dataset_id(dataset_id) is not None


def _path_expr(path: str | None) -> str:
    """Python expression for the location line of an id-less loader snippet.

    A dataset with a (safe) id never gets one: its loader is the portable
    ``curio_load_data("<id>")`` call. This literal path keeps legacy fat refs
    and id-less items working unchanged.
    """
    # Embed the path in POSIX form so the generated source parses on every
    # platform: a raw Windows path ("C:\Users\...") inside a Python string
    # literal forms escape sequences like \U and the snippet is a SyntaxError.
    # Windows opens forward-slash paths fine, and as_posix() is a no-op for
    # paths that already are.
    #
    # Guard against non-filesystem values legacy fat refs can carry: a
    # URI-shaped string (curio://, s3://) must NOT go through as_posix() (it
    # collapses // -> / and corrupts the scheme), and a non-str path must not
    # raise TypeError here and 500 the whole listing.
    if path is None:
        return json.dumps("<dataset-path>")
    _p = str(path)
    return json.dumps(_p if "://" in _p else Path(_p).as_posix())


# Loader body for ``format: bundle`` datasets (multi-output node results: a
# tuple, or a list or dict of frames). Reads ``data/bundle.json`` +
# ``data/parts/*`` and returns the parts in the container ``bundle.json``
# records (a tuple when it records none), as ``curio_load_data`` does, so the
# node's output is the value the producing node emitted. KEEP IN SYNC with
# ``bundleLoaderCode`` in the frontend generator (a Jest test compares them).
# Note: the only ``{}`` here is the ``{bundle_path_expr}`` placeholder (no dict
# literals), so ``str.format`` is safe.
_BUNDLE_LOADER_CODE = '''bundle_path = {bundle_path_expr}
def _curio_load_bundle(path):
    base = os.path.dirname(os.path.dirname(path))
    with open(path) as f:
        spec = json.load(f)
    parts = sorted(spec.get("parts", []), key=lambda p: p.get("index", 0))
    items = []
    for part in parts:
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
    container = spec.get("container") or "tuple"
    if container == "tuple":
        return tuple(items)
    if container == "list":
        return items
    if container == "dict":
        return dict(zip([part["key"] for part in parts], items))
    raise ValueError("A bundle is a tuple, a list or a dict, not " + repr(container))
bundle = _curio_load_bundle(bundle_path)'''


def autark_layer_type(item: dict[str, Any]) -> str | None:
    """The Autark layer a dataset downloaded from the Discovery Catalog is, when
    its layer is one (an OpenStreetMap download's ``buildings``). A GeoPackage
    layer may have any name, so the name alone decides nothing."""
    layer = item.get("layerName")
    if item.get("discoverySource") and isinstance(layer, str) and layer in AUTARK_LAYER_TYPES:
        return layer
    return None


def execution_format(item: dict[str, Any]) -> dict[str, str]:
    """How the sandbox's ``curio_load_data`` reads *item*: its ``format`` and,
    for an Autark layer, its ``layerType``. Built from a catalog item or the
    same fields of an index row (``format``, ``layerName``, ``discoverySource``)."""
    entry = {"format": str(item.get("format") or "")}
    layer = autark_layer_type(item)
    if layer:
        entry["layerType"] = layer
    return {k: v for k, v in entry.items() if v}


#: What a loader names the value ``curio_load_data`` returns, per format.
LOADED_VARIABLES = {
    "csv": "df",
    "parquet": "df",
    "geojson": "gdf",
    "shp": "gdf",
    "json": "data",
    "geotiff": "src",
    "bundle": "bundle",
    "onnx": "session",
    "netcdf": "ds",
}

#: Formats whose loaded value stays in the node's own code: a node's output
#: cannot carry an onnxruntime session or an xarray Dataset, so their loader
#: names the value and returns nothing. KEEP IN SYNC with ``KEPT_IN_CODE`` in
#: the frontend generator.
KEPT_IN_CODE = frozenset({"onnx", "netcdf"})

#: The options a loader names after the id, so its node shows them: a
#: GeoTIFF's ``bounds`` read only the cells inside them. KEEP IN SYNC with
#: ``LOADER_OPTIONS`` in the frontend generator.
LOADER_OPTIONS = {"geotiff": ", bounds=None"}


def loader_snippet(
    fmt: str, path: str | None, dataset_id: str | None = None, layer_type: str | None = None,
) -> dict[str, Any]:
    """Build the Python loader snippet for a dataset.

    When a (safe) *dataset_id* is given, the loader is one portable call the
    sandbox resolves at execution time (``/processPythonCode`` sends the paths
    and formats): ``curio_load_data("<id>")``, which reads the dataset by its
    format, ``curio_load_collection("<id>")`` for a collection, and
    ``curio_data_path("<id>")`` for a format nothing reads, so the node's own
    code reads the file. A format in :data:`KEPT_IN_CODE` is loaded but not
    returned. Without an id it falls back to the literal path and
    the reader spelled out, see :func:`_path_expr`; a *layer_type* (one of
    :data:`AUTARK_LAYER_TYPES`) is then set as the frame's ``metadata``, so an
    Autark node draws the frame as that layer.

    KEEP IN SYNC with the frontend generator
    ``frontend/urban-workflows/src/services/datasetCatalog/datasetLoaderSnippets.ts``
    (same call syntax) and the scan regex in ``datasets/domain/code_refs.py``.
    """
    safe_id = _safe_dataset_id(dataset_id)
    if safe_id:
        quoted = json.dumps(safe_id)
        if fmt == "collection":
            code, variable = f"collection = curio_load_collection({quoted})", "collection"
        elif fmt in LOADED_VARIABLES:
            variable = LOADED_VARIABLES[fmt]
            code = f"{variable} = curio_load_data({quoted}{LOADER_OPTIONS.get(fmt, '')})"
        else:
            return {
                "language": "python",
                "imports": [],
                "pathVariable": "dataset_path",
                "code": f"dataset_path = curio_data_path({quoted})",
                "returnVariable": None,
            }
        return {
            "language": "python",
            "imports": [],
            "pathVariable": None,
            "code": code,
            "returnVariable": None if fmt in KEPT_IN_CODE else variable,
        }
    expr = _path_expr(path)
    if fmt == "csv":
        return {
            "language": "python",
            "imports": ["import pandas as pd"],
            "pathVariable": "dataset_path",
            "code": f"dataset_path = {expr}\ndf = pd.read_csv(dataset_path)",
            "returnVariable": "df",
        }
    if fmt in {"geojson", "shp"}:
        code = f"dataset_path = {expr}\ngdf = gpd.read_file(dataset_path)"
        if layer_type in AUTARK_LAYER_TYPES:
            code += f"\ngdf.metadata = {{\"layerType\": {json.dumps(layer_type)}}}"
        return {
            "language": "python",
            "imports": ["import geopandas as gpd"],
            "pathVariable": "dataset_path",
            "code": code,
            "returnVariable": "gdf",
        }
    if fmt == "parquet":
        # Computed GeoDataFrames are stored as GeoParquet (geometry + CRS
        # preserved); plain DataFrames as ordinary parquet. Read with
        # ``gpd.read_parquet`` first so a geo dataset reloads as a GeoDataFrame
        # — matching the output type/schema of the node that produced it — and
        # fall back to ``pd.read_parquet`` for non-geo tables.
        code = (
            f"dataset_path = {expr}\n"
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
        )
        if layer_type in AUTARK_LAYER_TYPES:
            code += f"\ndf.metadata = {{\"layerType\": {json.dumps(layer_type)}}}"
        return {
            "language": "python",
            "imports": ["import os", "import json", "import pandas as pd", "import geopandas as gpd"],
            "pathVariable": "dataset_path",
            "code": code,
            "returnVariable": "df",
        }
    if fmt == "json":
        # Computed dict/list outputs (e.g. autk-grammar pool wrappers) are
        # persisted zlib-compressed (``.json.zlib``) while user-imported ``.json``
        # files are plain text — both carry ``format: json``. Read binary and try
        # zlib first; a plain JSON document never decompresses as zlib, so the
        # fallback is safe (same semantics as the preview's
        # ``_load_json_maybe_compressed``).
        return {
            "language": "python",
            "imports": ["import json", "import zlib"],
            "pathVariable": "dataset_path",
            "code": (
                f"dataset_path = {expr}\n"
                'with open(dataset_path, "rb") as f:\n'
                "    _raw = f.read()\n"
                "try:\n"
                "    _raw = zlib.decompress(_raw)\n"
                "except zlib.error:\n"
                "    pass  # plain .json - bytes are already the document\n"
                'data = json.loads(_raw.decode("utf-8"))'
            ),
            "returnVariable": "data",
        }
    if fmt == "geotiff":
        return {
            "language": "python",
            "imports": ["import rasterio"],
            "pathVariable": "dataset_path",
            "code": f"dataset_path = {expr}\nsrc = rasterio.open(dataset_path)",
            "returnVariable": "src",
        }
    if fmt == "onnx":
        return {
            "language": "python",
            "imports": ["import onnxruntime as ort"],
            "pathVariable": "dataset_path",
            "code": (
                f"dataset_path = {expr}\n"
                'session = ort.InferenceSession(dataset_path, providers=["CPUExecutionProvider"])'
            ),
            "returnVariable": None,
        }
    if fmt == "netcdf":
        return {
            "language": "python",
            "imports": ["import xarray as xr"],
            "pathVariable": "dataset_path",
            "code": f'dataset_path = {expr}\nds = xr.open_dataset(dataset_path, engine="netcdf4")',
            "returnVariable": None,
        }
    if fmt == "collection":
        # A collection's data file is its index: one row per file. The sandbox
        # resolves ``curio_load_collection`` to that index plus a readable path for
        # every file, wherever this execution runs.
        safe_id = _safe_dataset_id(dataset_id)
        if safe_id:
            return {
                "language": "python",
                "imports": [],
                "pathVariable": None,
                "code": f"collection = curio_load_collection({json.dumps(safe_id)})",
                "returnVariable": "collection",
            }
        return {
            "language": "python",
            "imports": ["import pandas as pd"],
            "pathVariable": "dataset_path",
            "code": f"dataset_path = {expr}\ncollection = pd.read_parquet(dataset_path)",
            "returnVariable": "collection",
        }
    if fmt == "bundle":
        # A bundle is a multi-output node result (a tuple, or a list or dict of
        # frames), stored as ``data/bundle.json`` + ``data/parts/*`` under the
        # dataset dir. Rebuild each part with the reader matching its kind and
        # return them in the container ``bundle.json`` records, so the node's
        # output is identical to the one the producing node emitted (same
        # container, parts, order, and types/schema).
        return {
            "language": "python",
            "imports": [
                "import json",
                "import os",
                "import pandas as pd",
                "import geopandas as gpd",
            ],
            "pathVariable": "bundle_path",
            "code": _BUNDLE_LOADER_CODE.format(bundle_path_expr=expr),
            "returnVariable": "bundle",
        }
    return {
        "language": "python",
        "imports": [],
        "pathVariable": "dataset_path",
        "code": f"dataset_path = {expr}",
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
        # Upstream inputs (producer nodes / input datasets) feeding the producing
        # node, persisted on computed manifests as lineage. ``[]`` when unknown.
        "upstreamInputs": [],
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
        # What the file's bytes were decoded from when it was imported (#280).
        # ``"utf-8"`` when nothing had to be transcoded, ``None`` for datasets
        # that predate the normalisation. Surfaced because charset detection can
        # be confidently wrong, and the user is the only one who can tell.
        "sourceEncoding": None,
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
        # Where a dataset downloaded from the Discovery Catalog came from. Null
        # for everything else, which is most datasets. Not an ``origin`` of its
        # own: such a dataset IS imported, and a fifth origin would ripple
        # through the labels, facets, filters and dedup for a distinction this
        # block already carries losslessly.
        "discoverySource": None,
        # A ``collection`` dataset's block: which source and resource its
        # files belong to, their kind and counts. Null for every other format.
        "collection": None,
    }
    item.update(overrides)
    if item["loaderSnippet"] is None:
        item["loaderSnippet"] = loader_snippet(
            item["format"], item.get("path"), dataset_id=item.get("id") or None,
            layer_type=autark_layer_type(item),
        )
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
        sourceEncoding=manifest.source_encoding,
        sourceLabel=manifest.source_label or manifest.publisher,
        license=manifest.license or None,
        tags=manifest.tags,
        schema=manifest.schema,
        groupId=manifest.group_id,
        layerName=manifest.layer_name,
        producerNodeId=manifest.producer_node_id,
        producerNodeType=manifest.producer_node_type,
        producerDataflowId=manifest.producer_dataflow_id,
        producerDataflowName=manifest.producer_dataflow_name,
        upstreamInputs=list(manifest.upstream_inputs) if manifest.upstream_inputs else [],
        discoverySource=dict(manifest.discovery_source) if manifest.discovery_source else None,
        collection=dict(manifest.collection) if manifest.collection else None,
    )
