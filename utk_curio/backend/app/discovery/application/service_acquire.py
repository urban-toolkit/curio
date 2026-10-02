"""Add a service source's resource to the Data Catalog.

A service is told where and what, and answers once. OpenStreetMap is the one
so far: autk-db's ``loadOsm``, run in Node by ``providers/autark_osm.py``,
writes one GeoJSON file per Autark layer, in autk-db's workspace CRS
(EPSG:3395). Here each layer is moved to WGS84, as GeoJSON requires, with its
features and properties as Autark built them, and installed: one layer as an
ordinary dataset, several as one ``osm.x`` layer group, the group an uploaded
``.pbf`` forms.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from utk_curio.backend.app.common.user_storage import user_key_segment, users_base
from utk_curio.backend.app.discovery.domain import parameters as P
from utk_curio.backend.app.discovery.domain.errors import DiscoveryError, ResourceNotFound
from utk_curio.backend.app.discovery.domain.manifest import DiscoverySourceManifest
from utk_curio.backend.app.discovery.infrastructure import ratelimit

#: autk-db keeps every layer in this CRS (World Mercator).
AUTARK_WORKSPACE_CRS = "EPSG:3395"

#: Decimal places kept for a longitude or latitude: about a centimetre.
COORDINATE_PLACES = 7


#: A service's add is never part of a row, as a storage selection can be.
_WHOLE = SimpleNamespace(split=None, narrowed=False)


class _Folder:
    """Where a service's files are while they are indexed, as a provider
    reports a file it can read in place."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def local_path(self, relpath: str) -> Path:
        return self.root / relpath


def place_label(values: dict[str, Any]) -> str:
    """The area a download covers, for its title: "Golf (Illinois)", a box's
    place name, or the box as the area field shows it."""
    area = values.get("area") or {}
    names = area.get("names")
    if names:
        return f"{', '.join(names.get('areas') or [])} ({names.get('geocodeArea', '')})"
    if area.get("label"):
        return str(area["label"])
    box = area.get("box")
    if box:
        west, south, east, north = box
        return f"{west:.4f}, {south:.4f} to {east:.4f}, {north:.4f}"
    return "the area"


def to_wgs84(collection: dict[str, Any]) -> dict[str, Any]:
    """*collection* with every position moved from autk-db's CRS to WGS84.

    Only positions change: each feature keeps its geometry type (a building of
    several parts stays a GeometryCollection) and its properties exactly.
    autk-db's own keys on the collection (``bbox`` in its CRS, ``__autk_layer``)
    are dropped, as they describe the workspace rather than the data.
    """
    from pyproj import Transformer

    transform = Transformer.from_crs(AUTARK_WORKSPACE_CRS, "EPSG:4326", always_xy=True).transform

    def move(coords):
        if not coords:
            return coords
        if isinstance(coords[0], (int, float)):
            lon, lat = transform(coords[0], coords[1])
            return [round(lon, COORDINATE_PLACES), round(lat, COORDINATE_PLACES), *coords[2:]]
        if isinstance(coords[0][0], (int, float)):
            lons, lats = transform([c[0] for c in coords], [c[1] for c in coords])
            return [
                [round(lon, COORDINATE_PLACES), round(lat, COORDINATE_PLACES), *c[2:]]
                for lon, lat, c in zip(lons, lats, coords)
            ]
        return [move(part) for part in coords]

    def geometry(geom):
        if not geom:
            return geom
        if geom.get("type") == "GeometryCollection":
            return {"type": "GeometryCollection", "geometries": [geometry(g) for g in geom.get("geometries") or []]}
        return {"type": geom["type"], "coordinates": move(geom.get("coordinates"))}

    features = []
    for feature in collection.get("features") or []:
        moved = {k: v for k, v in feature.items() if k != "bbox"}
        moved["geometry"] = geometry(feature.get("geometry"))
        features.append(moved)
    return {"type": "FeatureCollection", "features": features}


class ServiceAcquire:
    """Turns a service resource, and the answers to its parameters, into datasets."""

    def __init__(
        self,
        *,
        user_key: str,
        service_for: Callable[[DiscoverySourceManifest], Any],
        install_bytes: Callable[..., dict[str, Any]],
        find_held: Callable[..., dict[str, Any] | None],
        install_path: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self.user_key = user_key
        self._service_for = service_for
        self._install_bytes = install_bytes
        self._find_held = find_held
        self._install_path = install_path

    def acquire(
        self,
        manifest: DiscoverySourceManifest,
        resource_id: str,
        *,
        title: str | None = None,
        refresh: bool = False,
        parameters: dict[str, Any] | None = None,
        stage: Callable[[str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """Ask the service and register. Returns ``{dataset, alreadyPresent, unchanged}``.

        *parameters* are answers already checked against the manifest
        (``service.start_acquire``).
        """
        spec = manifest.resource(resource_id)
        if spec is None:
            raise ResourceNotFound(f"{resource_id!r} is not a resource of {manifest.name}")
        values = dict(parameters or {})
        values_hash = P.values_hash(values) if values else None
        held = self._find_held(manifest.dir_name, resource_id, spec.dataset_format, values_hash)
        if held is not None and not refresh:
            return {"dataset": held, "alreadyPresent": True, "unchanged": True}

        # One token per download: a service request is one ask, however many
        # requests the service makes to answer it.
        ratelimit.limiter.check(self.user_key, manifest.dir_name, manifest.requests_per_minute)
        service = self._service_for(manifest)
        if spec.is_collection:
            incoming = self._incoming_dir()
            try:
                answer = service.load(spec, values, incoming, stage=stage, cancelled=cancelled)
                dataset = self._add_images(
                    manifest, spec, resource_id, answer, values, values_hash,
                    root=incoming, title=title, stage=stage, cancelled=cancelled,
                    attribution=getattr(service, "attribution", None),
                )
            finally:
                shutil.rmtree(incoming, ignore_errors=True)
            return {"dataset": dataset, "alreadyPresent": False, "unchanged": False}
        work = self._work_dir()
        # Autark's layers are in its workspace CRS; a service that answers in
        # longitude and latitude says so.
        in_wgs84 = getattr(service, "crs", AUTARK_WORKSPACE_CRS) == "EPSG:4326"
        try:
            layers = service.load(
                spec, values, work, stage=stage, cancelled=cancelled
            )
            filled = [layer for layer in layers if layer.features > 0]
            place = place_label(values)
            if not filled:
                raise DiscoveryError(f"{manifest.name} has no {spec.name.lower()} in {place}")
            if stage is not None:
                stage("Adding to your Data Catalog…")
            provenance = {
                "sourceId": manifest.dir_name,
                "sourceName": manifest.name,
                "resourceId": resource_id,
                "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "parameters": values,
                "parametersHash": values_hash,
            }
            several = len(spec.options.get("layers") or ()) > 1
            prefix = (title or "").strip() or (
                f"{manifest.name}, {place}" if several else f"{spec.name}, {place}"
            )
            # One unique group per download, as a .pbf import has, so the same
            # area downloaded again forms its own group.
            group_id = f"osm.x{uuid.uuid4().hex[:8]}" if len(filled) > 1 else None
            items = []
            for layer in filled:
                collection = json.loads(layer.path.read_text(encoding="utf-8"))
                if not in_wgs84:
                    collection = to_wgs84(collection)
                blob = json.dumps(collection, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
                items.append(
                    self._install_bytes(
                        blob,
                        f"osm_{layer.layer}.geojson",
                        "geojson",
                        title=f"{prefix} ({layer.layer})" if group_id else prefix,
                        feature_count_override=layer.features,
                        group_id=group_id,
                        layer_name=layer.layer,
                        discovery_source=provenance,
                    )
                )
        finally:
            shutil.rmtree(work, ignore_errors=True)

        primary = items[0]
        if len(items) > 1:
            primary["importedDatasetCount"] = len(items)
        return {"dataset": primary, "alreadyPresent": False, "unchanged": False}

    def _add_images(
        self, manifest, spec, resource_id, answer, values, values_hash, *, root: Path,
        title, stage, cancelled, attribution: str | None = None,
    ) -> dict[str, Any]:
        """A service's images as one collection, its files where a node reads
        a downloaded collection's: ``objects/<datasetId>/<file_id>.<ext>``."""
        from utk_curio.backend.app.discovery.application import cache_collection, index_collection
        from utk_curio.backend.app.discovery.application.scan import MatchedFile
        from utk_curio.backend.app.discovery.infrastructure import media_dirs

        place = place_label(values)
        if not answer.images:
            if answer.found and answer.skipped:
                raise DiscoveryError(
                    f"{manifest.name} found {answer.found:,} in {place} and kept no "
                    f"{spec.name.lower()}: {answer.skip_reason or 'none could be downloaded'}"
                )
            raise DiscoveryError(f"{manifest.name} has no {spec.name.lower()} in {place} that match")
        if self._install_path is None:  # pragma: no cover - wired in service.py
            raise DiscoveryError("this Curio cannot add a collection from a service")
        if stage is not None:
            stage(f"Indexing {len(answer.images):,} images…")
        now = time.time()
        files = [
            MatchedFile(relpath=image.relpath, size=image.size, mtime=now, values={}, etag=image.image_id)
            for image in answer.images
        ]
        rows = index_collection.build_rows(manifest, _Folder(root), spec, files, cancelled=cancelled)
        for row, image in zip(rows, answer.images):
            # What the service says about an image is more than its pixels say:
            # the photographer, the capture time and the corrected position.
            row.update({key: value for key, value in image.columns.items() if value is not None})
        frame, columns = index_collection.to_frame(spec, rows)
        dest = root / "index.parquet"
        has_gps = index_collection.write_index(spec, frame, columns, dest)
        block = index_collection.collection_block(
            manifest, spec, resource_id, _WHOLE, files, frame, has_gps=has_gps
        )
        provenance = {
            "sourceId": manifest.dir_name,
            "sourceName": manifest.name,
            "resourceId": resource_id,
            "fileCount": len(files),
            "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "fingerprint": block["fingerprint"],
            "parameters": values,
            "parametersHash": values_hash,
        }
        if stage is not None:
            stage("Adding to your Data Catalog…")
        label = (title or "").strip() or f"{spec.name}, {place}"
        description = f"{len(files):,} {spec.name.lower()} from {manifest.name} for {place}"
        if attribution:
            description += f". {attribution}"
        dataset = self._install_path(
            dest, "index.parquet", "collection",
            title=label, discovery_source=provenance, row_count=len(rows),
            collection=block, description=description + ".",
        )
        target = cache_collection.objects_dir(self.user_key, dataset["id"])
        for row, image in zip(rows, answer.images):
            final = target / cache_collection.cached_name(row["file_id"], row["ext"])
            os.replace(image.path, final)
            media_dirs.grant_to_child(final)
        return dataset

    def _incoming_dir(self) -> Path:
        """Where a service's files arrive: under the media root, on the same
        disk as the folder a node reads them from, so they move in by rename."""
        from utk_curio.backend.app.discovery.infrastructure import media_dirs

        return media_dirs.media_work_dir(self.user_key, "incoming", f"svc{uuid.uuid4().hex[:16]}")

    def _work_dir(self) -> Path:
        """A fresh folder under the user's own tree, removed when the add ends."""
        path = (
            users_base() / user_key_segment(self.user_key) / "discovery" / "tmp"
            / f"svc{uuid.uuid4().hex[:16]}"
        )
        path.mkdir(parents=True, exist_ok=True)
        return path
