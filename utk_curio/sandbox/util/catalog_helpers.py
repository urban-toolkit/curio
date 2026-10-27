"""The helpers node code uses to reach what the account's catalogs hold.

``curio_load_data("<id>")``
    A Data Catalog dataset, read the way its format is read: a table, a
    GeoDataFrame, a raster, a JSON document, the parts of a multi-output result
    in the tuple, list or dict its node returned,
    a collection's index, an onnxruntime session for an ONNX model, or an
    xarray Dataset for a NetCDF file. A layer group (an OSM extract or a
    GeoPackage of several layers) is a dict of its layers by name, each read
    as its own id is. For a GeoTIFF,
    ``curio_load_data("<id>", bounds=(west, south, east, north))`` reads only
    the cells inside the bounds, in the raster's CRS, at its own cell size.
    For a dataset of several files (a ``bundle``),
    ``curio_load_data("<id>", part="<file>")`` reads the one its
    ``bundle.json`` lists under that file name or label, and ``bounds`` then
    windows it if it is a GeoTIFF.
``curio_data_path("<id>")``
    The dataset's file, for a reader of your own (``pd.read_csv(..., sep=";")``,
    ``netCDF4.Dataset(...)``).
``curio_load_collection("<id>")``
    A collection's index, one row per file with a readable ``path``.
``curio_load_model("<id>")``
    A Model Catalog model, ready for ``curio_segment``, or, for an
    ``image-to-image`` model, for ``model.run({input name: array})``.

The backend resolves each id a node's code names, for the account running it,
and sends the paths, the formats, the collections and the models with the
code. The in-process worker and the isolated child install the same helpers
through :func:`install_catalog_helpers`; only how a path resolves differs
(absolute in process, staged copies under isolation).

The names these replaced (``curio_dataset_path``, ``curio_collection``,
``curio_model``) are not aliases: calling one raises an error that names its
replacement, so a saved dataflow says what to change. So do the raster math
helpers every Python node used to have (``curio_raster_calculate``,
``curio_raster_statistics``): raster math is the Scout package's, in the
Raster Calculator's code (``scout_rasters.raster_algebra``).
"""

from __future__ import annotations

import glob
import json
import os
from pathlib import Path
from typing import Any, Callable

#: The format of a layer group's entry among a run's formats: the group's
#: layers, in its order, each as ``[name, dataset id]`` under ``layers``.
#: The group has no file; each layer has its own path and format.
LAYER_GROUP_FORMAT = "layer-group"

#: The most datasets a run reads by the ids its code names, as the backend's
#: scan finds them (``code_refs.MAX_DATASET_IDS``)...
MAX_NAMED_DATASETS = 32
#: ...and the most layers of the layer groups among them it reads besides.
MAX_GROUP_LAYERS = 256

#: The extensions a dataset whose format did not travel with it is read by.
_FORMAT_BY_SUFFIX = {
    ".csv": "csv",
    ".geojson": "geojson",
    ".shp": "shp",
    ".parquet": "parquet",
    ".json": "json",
    ".zlib": "json",
    ".tif": "geotiff",
    ".tiff": "geotiff",
    ".onnx": "onnx",
    ".nc": "netcdf",
}


def _format_of(path: str, declared: str | None) -> str | None:
    if declared:
        return declared
    name = os.path.basename(path)
    if name == "bundle.json":
        return "bundle"
    return _FORMAT_BY_SUFFIX.get(os.path.splitext(name)[1].lower())


def _read_parquet(path: str):
    import pandas as pd

    try:
        import geopandas as gpd

        frame = gpd.read_parquet(path)
    except Exception:  # noqa: BLE001 - a table with no geometry column
        frame = pd.read_parquet(path)
    # Object columns (dict/list cells) are JSON-encoded on save; the columns
    # are named in a <file>.decode.json sidecar, beside the frame's own
    # metadata (its name and Autark layer type), which parquet cannot hold.
    sidecar = path + ".decode.json"
    if os.path.exists(sidecar):
        with open(sidecar, encoding="utf-8") as handle:
            meta = json.load(handle)
        for column in meta.get("encoded_object_columns", []):
            if column in frame.columns:
                frame[column] = frame[column].apply(
                    lambda value: json.loads(value) if isinstance(value, str) and value else value
                )
        if isinstance(meta.get("frame_metadata"), dict):
            frame.metadata = dict(meta["frame_metadata"])
    return frame


def _with_layer_type(frame, layer_type: str):
    """*frame* drawn as the Autark layer *layer_type*, keeping the rest of the
    metadata it was saved with."""
    saved = frame.__dict__.get("metadata")
    frame.metadata = {**(saved if isinstance(saved, dict) else {}), "layerType": layer_type}
    return frame


def _read_json(path: str):
    import zlib

    with open(path, "rb") as handle:
        raw = handle.read()
    try:
        raw = zlib.decompress(raw)
    except zlib.error:
        pass  # plain .json: the bytes are already the document
    return json.loads(raw.decode("utf-8"))


def read_bundle_part(file_path: str, part: dict):
    """One part of a bundle, the value it holds in the bundle."""
    fmt, kind = _format_of(file_path, part.get("format")), part.get("kind")
    if fmt in ("parquet", "csv", "geojson", "shp", "geotiff", "netcdf", "onnx"):
        return read_dataset(file_path, fmt)
    with open(file_path, encoding="utf-8") as part_file:
        loaded = json.load(part_file)
    if kind in ("int", "float", "bool", "str", "null") and isinstance(loaded, dict) and "value" in loaded:
        return loaded["value"]
    return loaded


def bundle_container(spec: dict, parts: list[dict]) -> Callable[[list], Any]:
    """What puts a bundle's values back together: its parts, *parts* in index
    order, go into the container its ``bundle.json`` (*spec*) records as
    ``container``: a ``tuple``, a ``list``, or a ``dict`` keyed by each
    part's ``key``. A ``bundle.json`` that records none is a tuple. Any other
    container, or a dict part with no key or one another part has, is refused
    before a part is read."""
    container = spec.get("container") or "tuple"
    if container == "tuple":
        return tuple
    if container == "list":
        return list
    keys = [part.get("key") for part in parts]
    if container == "dict" and all(isinstance(key, str) for key in keys) and len(set(keys)) == len(keys):
        return lambda values: dict(zip(keys, values))
    raise ValueError(
        f"bundle.json records the container {container!r}"
        + (f" and the keys {keys}" if container == "dict" else "")
        + ": a bundle is a tuple, a list, or a dict that gives each part a key of its own."
    )


def _read_bundle(path: str):
    """A multi-output result: ``data/bundle.json`` and ``data/parts/*``, in
    the container the producing node returned (:func:`bundle_container`), so
    the node's output is the same value the producing node emitted."""
    base = os.path.dirname(os.path.dirname(path))
    with open(path, encoding="utf-8") as handle:
        spec = json.load(handle)
    parts = sorted(spec.get("parts", []), key=lambda p: p.get("index", 0))
    rebuild = bundle_container(spec, parts)
    items = []
    for part in parts:
        file_path = os.path.join(base, part["file"]) if part.get("file") else None
        items.append(read_bundle_part(file_path, part))
    return rebuild(items)


def listed_bundle_parts(path) -> list[tuple[dict, Path]]:
    """The parts the ``bundle.json`` at *path* lists, each with its file,
    resolved against the dataset's folder (two levels up). Only a regular
    file inside that folder, not a link, is listed. Staging stages these, and
    ``curio_load_data(..., part=...)`` reads one of them."""
    bundle = Path(path)
    base = bundle.parent.parent.resolve()
    try:
        spec = json.loads(bundle.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    parts = spec.get("parts") if isinstance(spec, dict) else None
    found = []
    for part in parts if isinstance(parts, list) else []:
        name = part.get("file") if isinstance(part, dict) else None
        if not isinstance(name, str) or not name:
            continue
        file = base / name
        if file.is_symlink() or not file.is_file():
            continue
        resolved = file.resolve()
        if base not in resolved.parents:
            continue
        found.append((part, resolved))
    return found


def bundle_part(path: str, part: str, dataset_id: str) -> tuple[str, dict]:
    """``(file, entry)`` of the part of the bundle at *path* that *part* names:
    by its file's name (``2020_2040_NbS.tif``) or by its label. A name the
    bundle does not list, a path among them, is refused with the files it has."""
    listed = listed_bundle_parts(path)
    wanted = str(part)
    for entry, file in listed:
        if wanted == os.path.basename(entry["file"]) or wanted == entry.get("label"):
            return str(file), entry
    names = ", ".join(os.path.basename(entry["file"]) for entry, _file in listed) or "none"
    raise ValueError(f"{dataset_id} has no file {wanted!r}; its files are {names}.")


def files_read_beside(path) -> list[Path]:
    """The files read beside the file at *path*: those named after it
    (``labels.parquet.decode.json``, a raster's ``.aux.xml``) or after its
    stem (a shapefile's ``.shx``, ``.dbf`` and ``.prj``). Only regular files,
    not links. Staging stages them with the file, and an install keeps them
    with its output's files."""
    path = Path(path)
    return [
        other for other in sorted(path.parent.glob(glob.escape(path.stem) + ".*"))
        if other.name != path.name and other.is_file() and not other.is_symlink()
    ]


def _read_onnx(path: str):
    """An ONNX model as an onnxruntime session on the CPU, opened the way
    ``curio_segment`` opens a Model Catalog model's."""
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise RuntimeError(
            "This dataset is an ONNX model, which runs on onnxruntime, and this Curio "
            "does not have it: add a model that runs on ONNX, such as DDRNet23-Slim, "
            "with Add in the Model Catalog, which installs it."
        ) from exc
    return ort.InferenceSession(path, providers=["CPUExecutionProvider"])


def read_dataset(path: str, fmt: str | None, *, layer_type: str | None = None):
    """The value a dataset at *path* holds, read the way *fmt* is read.

    *layer_type* is the Autark layer a Discovery download is (``buildings``,
    say); it is set as the frame's ``metadata`` so an Autark node draws the
    frame as that layer.
    """
    fmt = _format_of(path, fmt)
    if fmt == "csv":
        import pandas as pd

        return pd.read_csv(path)
    if fmt in ("geojson", "shp"):
        import geopandas as gpd

        frame = gpd.read_file(path)
        if layer_type:
            frame.metadata = {"layerType": layer_type}
        return frame
    if fmt == "parquet":
        frame = _read_parquet(path)
        if layer_type:
            frame = _with_layer_type(frame, layer_type)
        return frame
    if fmt == "json":
        return _read_json(path)
    if fmt == "geotiff":
        import rasterio

        return rasterio.open(path)
    if fmt == "onnx":
        return _read_onnx(path)
    if fmt == "netcdf":
        import xarray as xr

        # netCDF4 reads every NetCDF format: classic, 64-bit offset, 64-bit
        # data and NetCDF-4.
        return xr.open_dataset(path, engine="netcdf4")
    if fmt == "bundle":
        return _read_bundle(path)
    raise RuntimeError(
        f"curio_load_data cannot read a dataset stored as {fmt or 'an unknown format'} - "
        "read its file yourself: curio_data_path(\"<id>\") gives the path."
    )


class CurioModel:
    """A Model Catalog model, loaded: what ``curio_segment`` runs.

    ``folder`` is where its files are and ``manifest`` what its manifest says;
    both are read when the model is loaded, so a folder that is not a model
    fails there. ``runner``, the callable that labels one image's pixels, opens
    the model's runtime the first time it is used, and ``labels`` are the
    classes it can name. ``run`` feeds an ONNX model's graph the arrays the
    node prepared itself, as an ``image-to-image`` model is run.
    """

    def __init__(self, model_id: str, folder: str):
        from utk_curio.sandbox.util.models import model_spec

        self.id = model_id
        self.folder = folder
        path = os.path.join(folder, "manifest.json")
        try:
            with open(path, encoding="utf-8") as handle:
                self.manifest = model_spec(json.load(handle))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"Model '{model_id}' has no readable manifest: {exc}") from exc
        self._runner = None
        self._session = None

    @property
    def runner(self):
        if self._runner is None:
            from utk_curio.sandbox.util.vision import load_runner

            self._runner, _manifest = load_runner(self.folder)
        return self._runner

    def run(self, feeds: dict) -> list:
        """The outputs of an ONNX model's graph for *feeds*, ``{input name:
        array}``, in the graph's output order. The session opens on the CPU
        the first time, as ``curio_segment`` opens one, and is kept for the
        next call; its thread count is onnxruntime's own."""
        if self.manifest.get("runtime") != "onnx":
            raise RuntimeError(f"Model '{self.id}' is not an ONNX model, so it has no graph to run.")
        if self._session is None:
            try:
                import onnxruntime as ort
            except ImportError as exc:
                raise RuntimeError(
                    f"Model '{self.id}' runs on onnxruntime, which is not installed here: "
                    "add the model with Add in the Model Catalog, which installs it."
                ) from exc
            self._session = ort.InferenceSession(
                os.path.join(self.folder, self.manifest["entry"]), providers=["CPUExecutionProvider"]
            )
        names = [spec.name for spec in self._session.get_inputs()]
        missing = [name for name in names if name not in feeds]
        if missing:
            raise ValueError(f"Model '{self.id}' needs the inputs {', '.join(names)}; missing {', '.join(missing)}")
        return self._session.run(None, {name: feeds[name] for name in names})

    @property
    def labels(self) -> list:
        return list(self.manifest.get("labels") or []) or list(self.runner.labels)

    def __repr__(self) -> str:
        return f"<CurioModel {self.id}>"


def _renamed(old: str, replacement: str) -> Callable[..., Any]:
    def gone(*_args, **_kwargs):
        raise RuntimeError(f"{old} was renamed: use {replacement}.")

    gone.__name__ = old
    return gone


def layer_group_entry(layers) -> dict:
    """The entry among a run's formats of a layer group whose layers are
    *layers*, ``(name, dataset id)`` pairs in the group's order."""
    return {"format": LAYER_GROUP_FORMAT, "layers": [[str(name), str(dataset_id)] for name, dataset_id in layers]}


def layers_of_group(entry) -> list[tuple[str, str]] | None:
    """The ``(name, dataset id)`` pairs of a layer group's *entry*, in its
    order, at most :data:`MAX_GROUP_LAYERS`; None when *entry* is no layer
    group's. A pair of any other shape is left out."""
    if not isinstance(entry, dict) or entry.get("format") != LAYER_GROUP_FORMAT:
        return None
    listed = entry.get("layers")
    layers = []
    for layer in listed if isinstance(listed, list) else []:
        if len(layers) == MAX_GROUP_LAYERS:
            break
        if isinstance(layer, (list, tuple)) and len(layer) == 2 and all(isinstance(p, str) and p for p in layer):
            layers.append((layer[0], layer[1]))
    return layers


def dataset_refs(paths, formats) -> tuple[dict, dict]:
    """``(paths, formats)`` of a run's request as the sandbox takes them.

    The paths of the first :data:`MAX_NAMED_DATASETS` ids the code names, and
    of the layers of the layer groups among them, at most
    :data:`MAX_GROUP_LAYERS` in all; how each of those is read (its
    ``format`` and ``layerType``, as text); and each group's entry, which has
    no path of its own. A value of any other shape is dropped, never fatal.
    """
    paths = {str(key): str(value) for key, value in paths.items() if value} if isinstance(paths, dict) else {}
    formats = {str(key): value for key, value in formats.items()} if isinstance(formats, dict) else {}
    groups: dict[str, list] = {}
    for key, entry in formats.items():
        layers = layers_of_group(entry)
        if layers is not None and len(groups) < MAX_NAMED_DATASETS:
            groups[key] = layers
    layer_ids = list(dict.fromkeys(dataset_id for layers in groups.values() for _name, dataset_id in layers))
    layer_ids = layer_ids[:MAX_GROUP_LAYERS]
    named = [key for key in paths if key not in layer_ids][:MAX_NAMED_DATASETS]
    kept = {key: paths[key] for key in [*named, *layer_ids] if key in paths}
    read_as = {
        key: {k: str(v) for k, v in formats[key].items() if k in ("format", "layerType") and v}
        for key in kept if isinstance(formats.get(key), dict)
    }
    read_as.update((key, layer_group_entry(layers)) for key, layers in groups.items())
    return kept, read_as


def install_catalog_helpers(
    namespace: dict,
    *,
    data_path: Callable[[str], str],
    formats: dict | None,
    collections: dict | None,
    media_dir: str | None,
    models: dict | None,
    model_base: str | None = None,
    output_dir: str | None = None,
) -> None:
    """Put the catalog helpers into one execution's *namespace*.

    *data_path* resolves a dataset id to its file (absolute in process, a
    staged copy under isolation). *formats* is ``{id: {"format", "layerType"}}``
    as the backend resolved it, and a layer group's id has an entry naming its
    layers (:func:`layer_group_entry`), each of which has a file and a format
    of its own. *models* is ``{id: folder}``, relative to *model_base* when
    staged.
    """
    from utk_curio.sandbox.util.collections import make_collection_helpers
    from utk_curio.sandbox.util.models import make_model_folder
    from utk_curio.sandbox.util.vision import make_curio_segment

    known_formats = {str(k): dict(v) for k, v in (formats or {}).items() if isinstance(v, dict)}
    collection_helpers = make_collection_helpers(data_path, collections, media_dir, output_dir=output_dir)
    curio_load_collection = collection_helpers["curio_load_collection"]
    model_folder = make_model_folder(models, base=model_base)

    known_collections = {str(k) for k in (collections or {})}

    def raster_output_file(name):
        """Where a window of a raster ``curio_load_data`` reads is written:
        the node's output folder, else, in process with no media folder,
        beside the artifacts."""
        if output_dir or media_dir:
            return collection_helpers["curio_output_file"](name)
        from utk_curio.sandbox.util.rasters import python_raster_dir

        return str(python_raster_dir() / name)

    def read_one(dataset_id, bounds, part):
        info = known_formats.get(dataset_id, {})
        # The backend resolves only the ids that are collections into
        # *collections*, on every path (Play, a node run, Solve's validation),
        # so that alone says a collection even where no format travelled.
        if info.get("format") == "collection" or dataset_id in known_collections:
            if bounds is not None:
                raise ValueError(f"bounds read a window of a raster, and {dataset_id} is a collection.")
            if part is not None:
                raise ValueError(f"part names one file of a dataset of several, and {dataset_id} is a collection.")
            return curio_load_collection(dataset_id)
        path = data_path(dataset_id)
        if part is not None:
            fmt = _format_of(path, info.get("format"))
            if fmt != "bundle":
                raise ValueError(
                    f"part names one file of a dataset of several, and {dataset_id} is one "
                    f'{fmt or "file"}: load it without part, curio_load_data("{dataset_id}").'
                )
            path, entry = bundle_part(path, part, dataset_id)
            dataset_id = f"{dataset_id} ({part})"
            if bounds is None:
                return read_bundle_part(path, entry)
            info = {"format": _format_of(path, entry.get("format"))}
        if bounds is None:
            return read_dataset(path, info.get("format"), layer_type=info.get("layerType"))
        fmt = _format_of(path, info.get("format"))
        if fmt != "geotiff":
            raise ValueError(
                f"bounds read a window of a raster, and {dataset_id} is {fmt or 'not a raster'}: "
                f'load it without bounds, curio_load_data("{dataset_id}").'
            )
        import rasterio

        from utk_curio.sandbox.util.rasters import read_window

        with rasterio.open(path) as whole:
            return read_window(whole, bounds, raster_output_file, name=dataset_id)

    def curio_load_data(dataset_id, bounds=None, part=None):
        dataset_id = str(dataset_id)
        layers = layers_of_group(known_formats.get(dataset_id))
        if layers is None:
            return read_one(dataset_id, bounds, part)
        if bounds is not None:
            raise ValueError(
                f"bounds read a window of a raster, and {dataset_id} is a layer group: "
                f'load it without bounds, curio_load_data("{dataset_id}").'
            )
        if part is not None:
            raise ValueError(
                f"part names one file of a dataset of several, and {dataset_id} is a layer group: "
                f'load it without part, curio_load_data("{dataset_id}"), which gives its layers by name.'
            )
        # Each layer as its own id reads, under the name the group's loader
        # gives it (layer_group.named_layers in the backend).
        return {name: read_one(layer_id, None, None) for name, layer_id in layers}

    def curio_load_model(model_id):
        model_id = str(model_id)
        return CurioModel(model_id, model_folder(model_id))

    namespace["curio_data_path"] = data_path
    namespace["curio_load_data"] = curio_load_data
    namespace.update(collection_helpers)
    namespace["curio_load_model"] = curio_load_model
    namespace["curio_segment"] = make_curio_segment(collection_helpers["curio_derived_file"])
    namespace["curio_dataset_path"] = _renamed(
        "curio_dataset_path",
        'curio_load_data("<id>") for the data, or curio_data_path("<id>") for its file',
    )
    namespace["curio_collection"] = _renamed("curio_collection", 'curio_load_collection("<id>")')
    namespace["curio_model"] = _renamed("curio_model", 'curio_load_model("<id>")')
    for old, new in (("curio_raster_calculate", "raster_calculate"), ("curio_raster_statistics", "raster_statistics")):
        namespace[old] = _renamed(
            old, f"a Raster Calculator node (Scout), whose code has from scout_rasters.raster_algebra import {new}",
        )
