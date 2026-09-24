"""GeoPackage -> GeoParquet ingestion for the dataset importer.

A ``.gpkg`` is a SQLite container holding any number of layers, so it arrives in
the same shape as an OSM ``.pbf``: GDAL exposes each layer separately and each
carries its own geometry type. The importer therefore takes the same route as
``osm_pbf`` - one standalone GeoParquet dataset per layer, tied together by a
shared ``group_id`` - which keeps every reader, loader, preview and export path
working unchanged, because what lands on disk is the parquet they already know.

The alternative, storing the ``.gpkg`` verbatim as a new first-class format,
would need a ``gpkg`` branch in every one of those readers, and the generated
loader snippet has no way to name a layer, so there is nothing sensible it could
emit for a file holding three of them.

Two things genuinely differ from the OSM path:

* **CRS.** Every OSM layer is WGS84, so ``osm_pbf`` can declare a missing CRS
  and be right. A GeoPackage layer carries whatever it was authored in, so one
  that is not 4326 must be *reprojected*. Relabelling it instead would move the
  data to a different place on Earth, and nothing downstream could tell.
* **Non-spatial layers.** A GeoPackage may hold attribute-only tables. They are
  kept, as plain parquet, because silently dropping part of what the user
  imported is worse than carrying a table with no geometry.

Geospatial libraries are imported lazily and failures degrade to a user-facing
``GpkgError``, mirroring ``osm_pbf`` - the framework declares only non-geo deps.
"""

from __future__ import annotations

import logging
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: Layer names come from inside the uploaded file, so they are attacker-supplied
#: and reach a filename. ``secure_filename`` has already run on the upload's own
#: name by this point, but never on these.
_UNSAFE_IN_NAME = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class GpkgLayer:
    """One GeoPackage layer serialized to parquet, ready to import."""

    name: str
    parquet_bytes: bytes
    feature_count: int
    #: False for an attribute-only table, so the caller can describe it honestly.
    has_geometry: bool


class GpkgError(Exception):
    """Raised when a GeoPackage cannot be read or converted to a dataset."""


def safe_layer_name(name: str) -> str:
    """A layer name reduced to something safe to put in a filename."""
    cleaned = _UNSAFE_IN_NAME.sub("_", name).strip("._-")
    return cleaned or "layer"


def _import_geo():
    """Lazily import the geo stack, raising a user-facing GpkgError if the
    server lacks the geospatial extras or the GDAL GPKG driver."""
    try:
        import geopandas as gpd  # noqa: WPS433 (lazy by design)
        import pandas as pd
        import pyogrio
    except Exception as exc:  # noqa: BLE001 - any import failure = extras absent
        raise GpkgError(
            "Importing GeoPackage files requires the geospatial extras "
            "(geopandas / pyogrio), which aren't available on this server."
        ) from exc

    try:
        drivers = pyogrio.list_drivers()
    except Exception:  # noqa: BLE001 - be permissive; only fail on a definite "no"
        drivers = {}
    if drivers and not drivers.get("GPKG"):
        raise GpkgError(
            "The GDAL GPKG driver isn't available on this server, so "
            "GeoPackage files can't be imported."
        )
    return gpd, pd, pyogrio


def _to_wgs84(gdf, layer_name: str):
    """Reproject *gdf* to EPSG:4326, or declare it when it says nothing.

    ``set_crs`` on a layer that already has one is a relabel, not a transform,
    so the two cases are kept strictly apart: declare only when ``crs is None``.
    """
    if gdf.crs is None:
        logger.info("GeoPackage layer %s declares no CRS; assuming EPSG:4326", layer_name)
        return gdf.set_crs("EPSG:4326")
    try:
        if gdf.crs.to_epsg() == 4326:
            return gdf
    except Exception:  # noqa: BLE001 - an exotic CRS with no EPSG code still reprojects
        pass
    return gdf.to_crs("EPSG:4326")


def convert_gpkg_layers(gpkg_bytes: bytes) -> list[GpkgLayer]:
    """Convert GeoPackage bytes to one parquet per layer.

    Spatial layers become GeoParquet in EPSG:4326; attribute-only tables become
    plain parquet. Raises :class:`GpkgError` when the geo stack is unavailable,
    the file is not a readable GeoPackage, or it holds nothing importable.
    """
    gpd, _pd, pyogrio = _import_geo()

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "input.gpkg"
        src.write_bytes(gpkg_bytes)

        try:
            listed = [(str(name), geom) for name, geom in pyogrio.list_layers(src)]
        except Exception as exc:  # noqa: BLE001
            raise GpkgError(
                "Could not read the GeoPackage file - it may be corrupt or not "
                "a valid .gpkg."
            ) from exc

        layers: list[GpkgLayer] = []
        for name, geom_type in listed:
            try:
                frame = gpd.read_file(src, layer=name, engine="pyogrio")
            except Exception:  # noqa: BLE001 - skip a single unreadable layer
                logger.warning("Skipping unreadable GeoPackage layer %s", name, exc_info=True)
                continue
            if len(frame) == 0:
                continue

            # list_layers reports None for a table with no geometry column.
            has_geometry = geom_type is not None and hasattr(frame, "crs")
            if has_geometry:
                frame = _to_wgs84(frame, name)

            out = Path(tmp) / f"{safe_layer_name(name)}.parquet"
            frame.to_parquet(out)
            layers.append(
                GpkgLayer(
                    name=name,
                    parquet_bytes=out.read_bytes(),
                    feature_count=int(len(frame)),
                    has_geometry=bool(has_geometry),
                )
            )

        if not layers:
            raise GpkgError("The GeoPackage contains no importable layers.")
        return layers
