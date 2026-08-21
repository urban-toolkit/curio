"""OSM PBF → GeoParquet ingestion for the dataset importer.

An OSM ``.pbf`` extract is inherently multi-layer: GDAL's OSM driver exposes
``points``, ``lines``, ``multilinestrings``, ``multipolygons`` and
``other_relations``. Each has a homogeneous geometry type, so we register one
standalone catalog dataset **per non-empty layer** — every layer becomes its own
GeoParquet (EPSG:4326), the same on-disk format computed/imported geo datasets
already use, so the existing loader, preview and export paths work unchanged.

Geospatial libraries are imported lazily and errors degrade gracefully
(``OsmPbfError``), mirroring the backend's existing optional-geo handling — the
framework itself declares only non-geo deps.
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OsmLayer:
    """One non-empty OSM layer serialized to GeoParquet, ready to import."""

    name: str
    geoparquet_bytes: bytes
    feature_count: int


class OsmPbfError(Exception):
    """Raised when an OSM PBF cannot be read or converted to a dataset."""


def _import_geo():
    """Lazily import the geo stack, raising a user-facing OsmPbfError if the
    server lacks the geospatial extras or the GDAL OSM driver."""
    try:
        import geopandas as gpd  # noqa: WPS433 (lazy by design)
        import pandas as pd
        import pyogrio
    except Exception as exc:  # noqa: BLE001 - any import failure = extras absent
        raise OsmPbfError(
            "Importing OSM PBF files requires the geospatial extras "
            "(geopandas / pyogrio), which aren't available on this server."
        ) from exc

    try:
        drivers = pyogrio.list_drivers()
    except Exception:  # noqa: BLE001 - be permissive; only fail on a definite "no"
        drivers = {}
    if drivers and not drivers.get("OSM"):
        raise OsmPbfError(
            "The GDAL OSM driver isn't available on this server, so OSM PBF "
            "files can't be imported."
        )
    return gpd, pd, pyogrio


def convert_osm_pbf_layers(pbf_bytes: bytes) -> list[OsmLayer]:
    """Convert OSM PBF bytes to one GeoParquet per non-empty layer.

    Returns a list of :class:`OsmLayer` (points / lines / multipolygons / …),
    each a homogeneous-geometry GeoParquet in EPSG:4326.

    Raises :class:`OsmPbfError` when the geo stack/OSM driver is unavailable,
    the file is not a readable OSM PBF, or the extract has no features in any
    layer.
    """
    gpd, _pd, pyogrio = _import_geo()

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "input.osm.pbf"
        src.write_bytes(pbf_bytes)

        try:
            layer_names = [name for name, _geom in pyogrio.list_layers(src)]
        except Exception as exc:  # noqa: BLE001
            raise OsmPbfError(
                "Could not read the OSM PBF file — it may be corrupt or not a "
                "valid OpenStreetMap PBF extract."
            ) from exc

        layers: list[OsmLayer] = []
        for name in layer_names:
            try:
                gdf = gpd.read_file(src, layer=name, engine="pyogrio")
            except Exception:  # noqa: BLE001 - skip a single unreadable layer
                logger.debug("Skipping unreadable OSM layer %s", name, exc_info=True)
                continue
            if len(gdf) == 0:
                continue
            if gdf.crs is None:
                gdf = gdf.set_crs("EPSG:4326")
            out = Path(tmp) / f"{name}.parquet"
            gdf.to_parquet(out)
            layers.append(
                OsmLayer(
                    name=name,
                    geoparquet_bytes=out.read_bytes(),
                    feature_count=int(len(gdf)),
                )
            )

        if not layers:
            raise OsmPbfError(
                "The OSM PBF extract contains no importable features."
            )
        return layers
