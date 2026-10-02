"""What a dataflow is about, for the Projects rail and the canvas title chips.

A dataflow's categories come from three places, and each has exactly one:

* **source** - where the dataflow came from: a use case, an example or a test
  Curio ships, or ``None`` for the account's own. Decided by ``seed.py`` from
  the project id and never written into the spec, so a duplicate or an imported
  copy of an example is the user's, not a second example.
* **automatic** - ``tags`` and ``data_type``, read off the saved spec's node
  types, imports and datasets by :func:`derive`. Nothing stores them: they are
  recomputed on every read, so they follow the nodes and a dataflow saved
  before this existed gets them without a back-fill.
* **hand-set** - ``dataflow.categories`` in the spec: the user's own tags plus
  city, topic and complexity. Stored in the spec so they travel with export,
  duplicate and "Load dataflow".
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Iterable, Optional

#: The sections a user can write. Everything else on the rail is derived.
HAND_SECTIONS = ("tags", "city", "topic", "complexity")

#: Sections that hold one value; a new pick replaces the old one.
_SINGLE_VALUE = frozenset({"complexity"})

_MAX_VALUE_LENGTH = 40
_MAX_VALUES = 20

#: ``(format, collection kind)`` for a dataset id, or ``(None, None)``.
DatasetKind = Callable[[str], tuple[Optional[str], Optional[str]]]


# ---------------------------------------------------------------------------
# Hand-set
# ---------------------------------------------------------------------------

def _clean_values(raw: object, single: bool) -> list[str]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for value in raw:
        if not isinstance(value, str):
            continue
        cleaned = " ".join(value.split())[:_MAX_VALUE_LENGTH].strip()
        if not cleaned or cleaned.casefold() in seen:
            continue
        seen.add(cleaned.casefold())
        out.append(cleaned)
    if single:
        return out[-1:]
    return out[:_MAX_VALUES]


def normalize_hand(raw: object) -> dict[str, list[str]]:
    """The hand-set sections of *raw*, cleaned: known keys only, trimmed,
    de-duplicated ignoring case (first spelling wins), empty sections dropped."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[str]] = {}
    for section in HAND_SECTIONS:
        values = _clean_values(raw.get(section), section in _SINGLE_VALUE)
        if values:
            out[section] = values
    return out


def hand_categories(spec: object) -> dict[str, list[str]]:
    dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
    raw = dataflow.get("categories") if isinstance(dataflow, dict) else None
    return normalize_hand(raw)


# ---------------------------------------------------------------------------
# Automatic
# ---------------------------------------------------------------------------

def _imports(module: str) -> re.Pattern:
    return re.compile(rf"^\s*(?:import|from)\s+{module}\b", re.M)


_PANDAS = _imports("pandas")
_GEOPANDAS = _imports("geopandas")
_SHAPELY = _imports("shapely")
_OSMNX = _imports("osmnx")
_RASTER_LIBS = [_imports(m) for m in ("rasterio", "rioxarray", "xarray")]
_PIL = _imports("PIL")
_WAVE = _imports("wave")
_PBF_PATH = re.compile(r"\.pbf\b")
_TIFF_PATH = re.compile(r"\.tiff?\b")
_IMAGE_PATH = re.compile(r"data:image/|\.(?:png|jpe?g)\b")
_DATASET_CALL = re.compile(r"curio_dataset_path\(\s*[\"']([^\"']+)")
_COMPUTE_SECTION = re.compile(r"\"compute\"\s*:")

_AUTARK = "curio.builtin/autk-grammar"
_VEGA = "curio.builtin/vis-vega"
_SPATIAL_JOIN = "curio.builtin/spatial-join"
_CV_INFERENCE = "curio.streetvision/image-segmentation"
_VIDEO_FRAMES = "curio.media/video-frames"
_SPLIT_AUDIO = "curio.media/split-audio"
_MOSAIC_RASTERS = "curio.media/mosaic-rasters"

#: Display order within each automatic section.
TAG_ORDER = ("Autark", "Vega-Lite", "GeoPandas", "Pandas", "GPU compute", "Computer vision")
DATA_TYPE_ORDER = (
    "Tables", "Geometries", "Imagery", "OpenStreetMap", "Rasters", "Video", "Audio",
)


def _dataset_ids(dataflow: dict, code: str) -> set[str]:
    ids = set(_DATASET_CALL.findall(code))
    for ref in dataflow.get("datasets") or []:
        if not isinstance(ref, dict):
            continue
        for key in ("dirName", "datasetId", "id"):
            value = ref.get(key)
            if isinstance(value, str) and value:
                ids.add(value)
                break
    return ids


def derive(spec: object, dataset_kind: Optional[DatasetKind] = None) -> dict[str, list[str]]:
    """``{"tags": [...], "data_type": [...]}`` for *spec*, in display order.

    Reads what is in the dataflow and nothing else: node types, the import
    lines in its code, and the format of each dataset it names. *dataset_kind*
    resolves a dataset id to its format and collection kind; without it only
    the nodes and the code count.
    """
    from utk_curio.backend.app.packages.domain.spec_packages import unversioned_node_type

    dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
    if not isinstance(dataflow, dict):
        return {"tags": [], "data_type": []}
    nodes = [n for n in dataflow.get("nodes") or [] if isinstance(n, dict)]
    types = {unversioned_node_type(n.get("type")) for n in nodes}
    code = "\n".join(str(n.get("content") or "") for n in nodes)
    autark_documents = [
        str(n.get("content") or "") for n in nodes
        if unversioned_node_type(n.get("type")) == _AUTARK
    ]

    formats: set[str] = set()
    kinds: set[str] = set()
    if dataset_kind is not None:
        for dataset_id in _dataset_ids(dataflow, code):
            fmt, kind = dataset_kind(dataset_id)
            if fmt:
                formats.add(fmt)
            if kind:
                kinds.add(kind)

    has_pandas = bool(_PANDAS.search(code))
    has_geopandas = bool(_GEOPANDAS.search(code))

    tags: set[str] = set()
    if _AUTARK in types:
        tags.add("Autark")
    if _VEGA in types:
        tags.add("Vega-Lite")
    if has_geopandas:
        tags.add("GeoPandas")
    if has_pandas:
        tags.add("Pandas")
    if any(_COMPUTE_SECTION.search(doc) for doc in autark_documents):
        tags.add("GPU compute")
    if _CV_INFERENCE in types:
        tags.add("Computer vision")

    data: set[str] = set()
    if has_pandas or formats & {"csv", "parquet"}:
        data.add("Tables")
    if (has_geopandas or _SHAPELY.search(code) or "geojson" in formats
            or types & {_AUTARK, _SPATIAL_JOIN}):
        data.add("Geometries")
    if _PBF_PATH.search(code) or _OSMNX.search(code):
        data.add("OpenStreetMap")
    if (any(p.search(code) for p in _RASTER_LIBS) or _TIFF_PATH.search(code)
            or "geotiff" in formats or "rasters" in kinds or _MOSAIC_RASTERS in types):
        data.add("Rasters")
    if (_PIL.search(code) or _IMAGE_PATH.search(code)
            or types & {_CV_INFERENCE, _VIDEO_FRAMES}
            or kinds & {"frames", "media", "rasters", "images"}):
        data.add("Imagery")
    if _VIDEO_FRAMES in types or kinds & {"frames", "media"}:
        data.add("Video")
    if _SPLIT_AUDIO in types or "audio" in kinds or _WAVE.search(code):
        data.add("Audio")

    return {
        "tags": [t for t in TAG_ORDER if t in tags],
        "data_type": [d for d in DATA_TYPE_ORDER if d in data],
    }


# ---------------------------------------------------------------------------
# Dataset formats
# ---------------------------------------------------------------------------

class DatasetKinds:
    """Resolve dataset ids to ``(format, collection kind)``, memoized.

    Looks in the account's store first and then in the committed catalog - the
    two places ``curio_dataset_path`` finds a dataset. Accepts a bare id or a
    ``<id>@<major>`` directory name; a bare id takes its highest major. One
    instance per request, so a listing reads each manifest once.
    """

    def __init__(self, user_key: Optional[str]):
        from utk_curio.backend.app.datasets.infrastructure.storage import (
            catalog_root,
            user_datasets_dir,
        )

        self._roots: list[Path] = []
        if user_key:
            self._roots.append(user_datasets_dir(user_key))
        self._roots.append(catalog_root())
        self._memo: dict[str, tuple[Optional[str], Optional[str]]] = {}

    def __call__(self, dataset_id: str) -> tuple[Optional[str], Optional[str]]:
        if dataset_id not in self._memo:
            self._memo[dataset_id] = self._lookup(dataset_id)
        return self._memo[dataset_id]

    def _lookup(self, dataset_id: str) -> tuple[Optional[str], Optional[str]]:
        if "/" in dataset_id or "\\" in dataset_id or dataset_id.startswith("."):
            return (None, None)
        for root in self._roots:
            for directory in self._candidates(root, dataset_id):
                manifest = directory / "manifest.json"
                try:
                    raw = json.loads(manifest.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if not isinstance(raw, dict):
                    continue
                collection = raw.get("collection")
                kind = collection.get("kind") if isinstance(collection, dict) else None
                fmt = raw.get("format")
                return (
                    fmt.lower() if isinstance(fmt, str) else None,
                    kind if isinstance(kind, str) else None,
                )
        return (None, None)

    @staticmethod
    def _candidates(root: Path, dataset_id: str) -> Iterable[Path]:
        if "@" in dataset_id:
            return [root / dataset_id]
        if not root.is_dir():
            return []
        majors = []
        for entry in root.glob(f"{dataset_id}@*"):
            major = entry.name.rsplit("@", 1)[1]
            if entry.is_dir() and major.isdigit():
                majors.append((int(major), entry))
        return [entry for _, entry in sorted(majors, reverse=True)]


# ---------------------------------------------------------------------------
# What the API returns
# ---------------------------------------------------------------------------

def categories_for(
    spec: object,
    source: Optional[str],
    dataset_kind: Optional[DatasetKind] = None,
) -> dict:
    """The ``categories`` field of a project summary or detail."""
    return {
        "source": source,
        "auto": derive(spec, dataset_kind),
        "hand": hand_categories(spec),
    }
