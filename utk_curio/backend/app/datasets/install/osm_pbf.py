"""OSM PBF → GeoParquet ingestion for the dataset importer.

An OSM ``.pbf`` extract is inherently multi-layer: GDAL's OSM driver exposes
``points``, ``lines``, ``multilinestrings``, ``multipolygons`` and
``other_relations``. To register it as a single standalone catalog dataset we
read every non-empty layer and concatenate them into one GeoDataFrame with an
``osm_layer`` discriminator column (all layers are EPSG:4326), then serialize to
GeoParquet — the same on-disk format computed/imported geo datasets already use,
so the existing loader, preview and export paths work unchanged.

Geospatial libraries are imported lazily and errors degrade gracefully
(``OsmPbfError``), mirroring the backend's existing optional-geo handling — the
framework itself declares only non-geo deps.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Discriminator column added to every feature recording which OSM layer it came
# from (points / lines / multipolygons / …) so a merged extract can be split
# downstream by geometry theme.
OSM_LAYER_COLUMN = "osm_layer"


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


def convert_osm_pbf_to_geoparquet(pbf_bytes: bytes) -> tuple[bytes, int]:
    """Convert OSM PBF bytes to a single GeoParquet.

    Returns ``(geoparquet_bytes, feature_count)``. Merges every non-empty OSM
    layer into one GeoDataFrame with an :data:`OSM_LAYER_COLUMN` column.

    Raises :class:`OsmPbfError` when the geo stack/OSM driver is unavailable,
    the file is not a readable OSM PBF, or the extract has no features.
    """
    gpd, pd, pyogrio = _import_geo()

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

        frames = []
        crs = None
        for layer in layer_names:
            try:
                gdf = gpd.read_file(src, layer=layer, engine="pyogrio")
            except Exception:  # noqa: BLE001 - skip a single unreadable layer
                logger.debug("Skipping unreadable OSM layer %s", layer, exc_info=True)
                continue
            if len(gdf) == 0:
                continue
            gdf = gdf.copy()
            gdf.insert(0, OSM_LAYER_COLUMN, layer)
            crs = crs or gdf.crs
            frames.append(gdf)

        if not frames:
            raise OsmPbfError(
                "The OSM PBF extract contains no importable features."
            )

        merged = pd.concat(frames, ignore_index=True)
        merged = gpd.GeoDataFrame(
            merged, geometry="geometry", crs=crs or "EPSG:4326"
        )

        out = Path(tmp) / "output.parquet"
        merged.to_parquet(out)
        return out.read_bytes(), int(len(merged))
