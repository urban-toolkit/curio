"""The helpers node code uses to reach what the account's catalogs hold.

``curio_load_data("<id>")``
    A Data Catalog dataset, read the way its format is read: a table, a
    GeoDataFrame, a raster, a JSON document, the parts of a multi-output result,
    a collection's index, an onnxruntime session for an ONNX model, or an
    xarray Dataset for a NetCDF file. For a GeoTIFF,
    ``curio_load_data("<id>", bounds=(west, south, east, north))`` reads only
    the cells inside the bounds, in the raster's CRS, at its own cell size.
    For a dataset of several files (a ``bundle``),
    ``curio_load_data("<id>", part="<file>")`` reads the one its
    ``bundle.json`` lists under that file name or label, and ``bounds`` then
    windows it if it is a GeoTIFF.
``curio_raster_calculate(operation, rasters, codes=None)``,
``curio_raster_statistics(raster, band=1, mask=None, mask_values=None, where=None)``
    The Raster Calculator and Raster Statistics nodes' steps
    (``util/raster_algebra.py``).
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
replacement, so a saved dataflow says what to change.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

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


def _read_part(file_path: str, part: dict):
    """One part of a bundle, the value it holds in the bundle's tuple."""
    fmt, kind = _format_of(file_path, part.get("format")), part.get("kind")
    if fmt in ("parquet", "csv", "geojson", "shp", "geotiff", "netcdf", "onnx"):
        return read_dataset(file_path, fmt)
    with open(file_path, encoding="utf-8") as part_file:
        loaded = json.load(part_file)
    if kind in ("int", "float", "bool", "str", "null") and isinstance(loaded, dict) and "value" in loaded:
        return loaded["value"]
    return loaded


def _read_bundle(path: str):
    """A multi-output result: ``data/bundle.json`` and ``data/parts/*``, as a
    tuple, so the node's output is the same ``outputs`` envelope the producing
    node emitted."""
    base = os.path.dirname(os.path.dirname(path))
    with open(path, encoding="utf-8") as handle:
        spec = json.load(handle)
    items = []
    for part in sorted(spec.get("parts", []), key=lambda p: p.get("index", 0)):
        file_path = os.path.join(base, part["file"]) if part.get("file") else None
        items.append(_read_part(file_path, part))
    return tuple(items)


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


def _read_onnx(path: str):
    """An ONNX model as an onnxruntime session on the CPU, opened the way
    ``curio_segment`` opens a Model Catalog model's."""
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise RuntimeError(
            "This dataset is an ONNX model, which runs on onnxruntime, and this Curio "
            "does not have it: install a package that brings it, such as Street Vision, "
            "from the Node Catalog."
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
        self.id = model_id
        self.folder = folder
        path = os.path.join(folder, "manifest.json")
        try:
            with open(path, encoding="utf-8") as handle:
                self.manifest = json.load(handle)
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
                    "add the package whose node runs it from the Node Catalog."
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
    as the backend resolved it. *models* is ``{id: folder}``, relative to
    *model_base* when staged.
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
        """Where a raster this node returns is written: the node's output
        folder, else, in process with no media folder, beside the artifacts."""
        if output_dir or media_dir:
            return collection_helpers["curio_output_file"](name)
        from utk_curio.sandbox.util.rasters import python_raster_dir

        return str(python_raster_dir() / name)

    def curio_load_data(dataset_id, bounds=None, part=None):
        dataset_id = str(dataset_id)
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
                return _read_part(path, entry)
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

    def curio_raster_calculate(operation, rasters, codes=None):
        """The Raster Calculator's step: *operation* over *rasters*, cell by cell
        (``util/raster_algebra.calculate``)."""
        from utk_curio.sandbox.util.raster_algebra import calculate

        return calculate(operation, rasters, codes=codes, output_file=raster_output_file)

    def curio_raster_statistics(raster, band=1, mask=None, mask_values=None, where=None):
        """The Raster Statistics node's step: a raster's mean, median, minimum,
        maximum and count, nodata left out (``util/raster_algebra.statistics``)."""
        from utk_curio.sandbox.util.raster_algebra import statistics

        return statistics(raster, band=band, mask=mask, mask_values=mask_values, where=where)

    def curio_load_model(model_id):
        model_id = str(model_id)
        return CurioModel(model_id, model_folder(model_id))

    namespace["curio_data_path"] = data_path
    namespace["curio_load_data"] = curio_load_data
    namespace["curio_raster_calculate"] = curio_raster_calculate
    namespace["curio_raster_statistics"] = curio_raster_statistics
    namespace.update(collection_helpers)
    namespace["curio_load_model"] = curio_load_model
    namespace["curio_segment"] = make_curio_segment(collection_helpers["curio_derived_file"])
    namespace["curio_dataset_path"] = _renamed(
        "curio_dataset_path",
        'curio_load_data("<id>") for the data, or curio_data_path("<id>") for its file',
    )
    namespace["curio_collection"] = _renamed("curio_collection", 'curio_load_collection("<id>")')
    namespace["curio_model"] = _renamed("curio_model", 'curio_load_model("<id>")')
