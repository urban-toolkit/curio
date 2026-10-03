"""Mapillary street-level imagery: told where, it answers with images.

Two kinds of resource, named by ``options.endpoint``:

- ``images``: the photos Mapillary holds in a box, narrowed by when they were
  taken and whether they are panoramas, each downloaded at the size asked
  for. They land as one collection, every row keeping its photographer, its
  capture time and its place (Mapillary imagery is CC BY-SA 4.0).
- ``map_features``: the signs and objects Mapillary detected in the box, as
  points in one GeoJSON table.

Mapillary's search takes a box under 0.01 square degrees and answers at most
2000 images, a sample rather than all of them. So the box is tiled into cells
under that bound, a cell that answers 2000 is split in four, and the images
are taken from the cells in turn, newest first, so the count asked for is
spread over the area. A search names no thumbnail (their signed URLs would
double the answer past the catalog's metadata ceiling); the thumbnails of the
images kept are looked up after, fifty at a time.

Thumbnails live on Mapillary's CDN, not the API's host. Each is fetched only
from a host ``options.imageHosts`` lists (a host or a parent domain), through
the transport's address policy, and without the token: the transport sends a
key only to its source's own host. A thumbnail that cannot be fetched is
skipped and counted, and the rest are kept.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode, urlsplit

from utk_curio.backend.app.discovery.domain.errors import DiscoveryError, DownloadTooLarge, ProviderError
from utk_curio.backend.app.discovery.domain.manifest import (
    DiscoverySourceManifest,
    ResourceSpec,
)
from utk_curio.backend.app.discovery.domain.resource import DiscoveryResource
from utk_curio.backend.app.discovery.infrastructure.transport import DiscoveryTransportError
from utk_curio.backend.app.discovery.providers.autark_osm import Cancelled, LoadedLayer

PARAMETER_IDS = ("area", "captured", "imageType", "size", "maxImages")

#: Mapillary refuses a search box of 0.010 square degrees or more.
MAX_CELL_SQ_DEG = 0.0099

#: The most one search answers.
SEARCH_LIMIT = 2000

#: How many times a full cell is split in four before its sample is kept.
MAX_SPLITS = 3

#: Images per thumbnail lookup.
THUMB_BATCH = 50

#: One image, and all of one download's images together.
MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_JOB_BYTES = 2 * 1024 * 1024 * 1024

SIZES = ("256", "1024", "2048")
DEFAULT_SIZE = "1024"
DEFAULT_MAX_IMAGES = 100

IMAGE_FIELDS = "id,captured_at,compass_angle,computed_geometry,geometry,sequence,is_pano,creator"
FEATURE_FIELDS = "id,object_value,object_type,geometry,first_seen_at,last_seen_at"

#: Where a person sees one image on Mapillary, for attribution.
IMAGE_PAGE = "https://www.mapillary.com/app/?pKey={id}"

#: A Mapillary image id: ASCII digits only, since it names the image's file.
_IMAGE_ID_RE = re.compile(r"[0-9]{1,32}")


@dataclass(frozen=True)
class DownloadedImage:
    """One image on disk, and what Mapillary said about it."""

    relpath: str
    path: Path
    size: int
    image_id: str
    columns: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ImageSet:
    """What an ``images`` resource answers: the images, and what was skipped."""

    images: list[DownloadedImage]
    found: int
    skipped: int = 0
    #: Why an image found was not kept, as a person reads it.
    skip_reason: str = ""
    #: Of those skipped, how many could not be fetched.
    failed: int = 0


#: What one image's download may fail with and the job go on: the rest are kept.
FETCH_FAILURES = (DiscoveryTransportError, DownloadTooLarge)


def skip_reason(reason: str, skipped: int, failed: int) -> str:
    """Why the images skipped were not kept: *reason*, a fetch that failed, or both."""
    if not failed:
        return reason
    if failed == skipped:
        return "none could be fetched"
    return f"{reason}, or it could not be fetched"


def cells(box: list[float], max_sq_deg: float = MAX_CELL_SQ_DEG) -> list[list[float]]:
    """*box* tiled into equal cells, each under *max_sq_deg*, west to east then
    south to north."""
    west, south, east, north = box
    width, height = east - west, north - south
    if width * height <= max_sq_deg:
        return [[west, south, east, north]]
    step = math.sqrt(max_sq_deg)
    cols, rows = max(1, math.ceil(width / step)), max(1, math.ceil(height / step))
    while (width / cols) * (height / rows) > max_sq_deg:
        cols, rows = cols + 1, rows + 1
    out = []
    for r in range(rows):
        for c in range(cols):
            out.append([
                round(west + width * c / cols, 6),
                round(south + height * r / rows, 6),
                round(west + width * (c + 1) / cols, 6),
                round(south + height * (r + 1) / rows, 6),
            ])
    return out


def quarters(box: list[float]) -> list[list[float]]:
    west, south, east, north = box
    mx, my = round((west + east) / 2, 6), round((south + north) / 2, 6)
    return [[west, south, mx, my], [mx, south, east, my], [west, my, mx, north], [mx, my, east, north]]


def host_allowed(url: str, hosts) -> bool:
    """Whether *url* is on one of *hosts* or under one of them as a parent domain."""
    host = (urlsplit(url).hostname or "").lower()
    return bool(host) and any(host == h or host.endswith("." + h) for h in hosts)


def _bbox(box: list[float]) -> str:
    return ",".join(f"{v:.6f}".rstrip("0").rstrip(".") for v in box)


def _ms_to_datetime(value: Any) -> datetime | None:
    """Mapillary's times are milliseconds since 1970, in UTC."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).replace(tzinfo=None)


def _iso(value: Any) -> str | None:
    moment = _ms_to_datetime(value)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ") if moment else (str(value) if value else None)


def _point(record: dict[str, Any]) -> tuple[float, float] | None:
    """Where an image was taken: Mapillary's corrected position, else the camera's."""
    for key in ("computed_geometry", "geometry"):
        geom = record.get(key) or {}
        coords = geom.get("coordinates") if isinstance(geom, dict) else None
        if isinstance(coords, list) and len(coords) >= 2:
            try:
                return float(coords[0]), float(coords[1])
            except (TypeError, ValueError):
                continue
    return None


class MapillaryService:
    """The ``mapillary`` provider: declared resources in, images or points out."""

    type = "mapillary"

    #: What its GeoJSON is in. Autark's OpenStreetMap layers are in World
    #: Mercator and are moved; these are already longitude and latitude.
    crs = "EPSG:4326"
    #: What a dataset's description says of where its images come from.
    attribution = "CC BY-SA 4.0: each row names its photographer"

    def __init__(self, manifest: DiscoverySourceManifest, *, transport) -> None:
        self.manifest = manifest
        self.transport = transport
        self.base = manifest.provider.base_url
        self.image_hosts = tuple(
            str(h).lower() for h in manifest.provider.options.get("imageHosts") or ()
        )

    def rows(self) -> tuple[DiscoveryResource, ...]:
        return tuple(self.row(spec) for spec in self.manifest.resources)

    def row(self, spec: ResourceSpec) -> DiscoveryResource:
        return DiscoveryResource(
            source_id=self.manifest.id,
            resource_id=spec.id,
            name=spec.name,
            description=spec.description,
            publisher=self.manifest.publisher,
            formats=(spec.dataset_format,),
            kind=spec.kind,
        )

    def load(
        self,
        spec: ResourceSpec,
        values: dict[str, Any],
        out_dir: Path,
        *,
        stage: Callable[[str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ):
        """Ask Mapillary for *spec* over the area in *values*.

        An ``images`` resource answers an :class:`ImageSet`; a ``map_features``
        one, one :class:`LoadedLayer` of GeoJSON.
        """
        box = (values.get("area") or {}).get("box")
        if not box:
            raise DiscoveryError("Mapillary needs an area: a box")
        endpoint = spec.options.get("endpoint")
        if endpoint == "map_features":
            return [self._features(box, out_dir, stage=stage, cancelled=cancelled)]
        if endpoint == "images":
            return self._images(spec, values, box, out_dir, stage=stage, cancelled=cancelled)
        raise ProviderError(f"{spec.name}: Mapillary has no endpoint {endpoint!r}")

    # ── searching ──────────────────────────────────────────────────────────

    def _search(self, path: str, cell: list[float], params: dict[str, Any],
                cancelled, splits: int = 0) -> list[list[dict[str, Any]]]:
        """Every record in *cell*, as one list per cell searched."""
        if cancelled is not None and cancelled():
            raise Cancelled()
        url = f"{self.base}/{path}?" + urlencode({"bbox": _bbox(cell), **params, "limit": SEARCH_LIMIT})
        try:
            payload = json.loads(self.transport.json_get(url))
        except ValueError as exc:
            raise ProviderError("Mapillary answered a search that is not JSON") from exc
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise ProviderError("Mapillary answered a search in an unknown shape")
        records = [r for r in data if isinstance(r, dict) and r.get("id")]
        if len(records) >= SEARCH_LIMIT and splits < MAX_SPLITS:
            out: list[list[dict[str, Any]]] = []
            for part in quarters(cell):
                out.extend(self._search(path, part, params, cancelled, splits + 1))
            return out
        return [records]

    def _image_filters(self, values: dict[str, Any]) -> dict[str, Any]:
        filters: dict[str, Any] = {"fields": IMAGE_FIELDS}
        kind = values.get("imageType") or "all"
        if kind == "panoramas":
            filters["is_pano"] = "true"
        elif kind == "flat":
            filters["is_pano"] = "false"
        captured = values.get("captured") or {}
        if captured.get("start"):
            filters["start_captured_at"] = f"{captured['start']}T00:00:00Z"
        if captured.get("end"):
            filters["end_captured_at"] = f"{captured['end']}T23:59:59Z"
        return filters

    @staticmethod
    def spread(groups: list[list[dict[str, Any]]], limit: int) -> list[dict[str, Any]]:
        """Up to *limit* records, one cell at a time in turn, newest first in
        each, each id once."""
        queues = [
            sorted(group, key=lambda r: (-(r.get("captured_at") or 0), str(r.get("id"))))
            for group in groups
        ]
        picked: list[dict[str, Any]] = []
        seen: set[str] = set()
        position = 0
        while len(picked) < limit and any(position < len(q) for q in queues):
            for queue in queues:
                if position < len(queue):
                    record = queue[position]
                    key = str(record["id"])
                    if key not in seen:
                        seen.add(key)
                        picked.append(record)
                        if len(picked) >= limit:
                            break
            position += 1
        return picked

    # ── images ─────────────────────────────────────────────────────────────

    def _images(self, spec, values, box, out_dir: Path, *, stage, cancelled) -> ImageSet:
        size = str(values.get("size") or DEFAULT_SIZE)
        if size not in SIZES:
            raise DiscoveryError(f"Mapillary has images at {', '.join(SIZES)} pixels, not {size}")
        limit = int(values.get("maxImages") or DEFAULT_MAX_IMAGES)
        if stage is not None:
            stage("Searching Mapillary…")
        filters = self._image_filters(values)
        groups: list[list[dict[str, Any]]] = []
        for cell in cells(box):
            groups.extend(self._search("images", cell, filters, cancelled))
        # An id names a file, so one that is not Mapillary's digits is no image.
        groups = [[r for r in group if _IMAGE_ID_RE.fullmatch(str(r["id"]))] for group in groups]
        found = len({str(r["id"]) for group in groups for r in group})
        chosen = self.spread(groups, limit)
        if not chosen:
            return ImageSet(images=[], found=0)

        thumbs = self._thumbnails([str(r["id"]) for r in chosen], size, cancelled)
        folder = out_dir / "images"
        folder.mkdir(parents=True, exist_ok=True)
        images: list[DownloadedImage] = []
        skipped = failed = 0
        total = 0
        for index, record in enumerate(chosen, start=1):
            if cancelled is not None and cancelled():
                raise Cancelled()
            if stage is not None and (index == 1 or index % 10 == 0):
                stage(f"Downloading image {index:,} of {len(chosen):,}…")
            image_id = str(record["id"])
            url = thumbs.get(image_id)
            if not url or not host_allowed(url, self.image_hosts):
                skipped += 1
                continue
            relpath = f"images/{image_id}.jpg"
            path = out_dir / relpath
            try:
                written = self._download(url, path)
            except FETCH_FAILURES:
                skipped += 1
                failed += 1
                continue
            total += written
            if total > MAX_JOB_BYTES:
                raise DiscoveryError(
                    f"these images come to more than {MAX_JOB_BYTES // (1024 ** 3)} GB; "
                    "ask for fewer or smaller images"
                )
            images.append(DownloadedImage(
                relpath=relpath, path=path, size=written, image_id=image_id,
                columns=self._columns(record),
            ))
        return ImageSet(
            images=images, found=found, skipped=skipped, failed=failed,
            skip_reason=skip_reason("its image was not on a host the source lists", skipped, failed),
        )

    def _thumbnails(self, ids: list[str], size: str, cancelled) -> dict[str, str]:
        out: dict[str, str] = {}
        key = f"thumb_{size}_url"
        for start in range(0, len(ids), THUMB_BATCH):
            if cancelled is not None and cancelled():
                raise Cancelled()
            batch = ids[start:start + THUMB_BATCH]
            url = f"{self.base}/images?" + urlencode({"image_ids": ",".join(batch), "fields": f"id,{key}"})
            try:
                payload = json.loads(self.transport.json_get(url))
            except ValueError as exc:
                raise ProviderError("Mapillary answered a thumbnail lookup that is not JSON") from exc
            for record in (payload.get("data") if isinstance(payload, dict) else None) or []:
                if isinstance(record, dict) and record.get("id") and isinstance(record.get(key), str):
                    out[str(record["id"])] = record[key]
        return out

    def _download(self, url: str, path: Path) -> int:
        part = path.with_name(path.name + ".part")
        try:
            with part.open("wb") as handle:
                result = self.transport.download(
                    url, handle.write, max_bytes=MAX_IMAGE_BYTES, ceiling=MAX_IMAGE_BYTES
                )
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        if not host_allowed(getattr(result, "final_url", url) or url, self.image_hosts):
            part.unlink(missing_ok=True)
            raise ProviderError("a Mapillary thumbnail redirected off the hosts its source lists")
        part.replace(path)
        return path.stat().st_size

    @staticmethod
    def _columns(record: dict[str, Any]) -> dict[str, Any]:
        creator = record.get("creator") if isinstance(record.get("creator"), dict) else {}
        point = _point(record)
        angle = record.get("compass_angle")
        return {
            "image_id": str(record["id"]),
            "captured_at": _ms_to_datetime(record.get("captured_at")),
            "compass_angle": float(angle) if isinstance(angle, (int, float)) and not isinstance(angle, bool) else None,
            "is_pano": bool(record.get("is_pano")),
            "sequence": str(record.get("sequence") or "") or None,
            "creator": str(creator.get("username") or "") or None,
            "mapillary_url": IMAGE_PAGE.format(id=record["id"]),
            "gps_lon": point[0] if point else None,
            "gps_lat": point[1] if point else None,
        }

    # ── map features ───────────────────────────────────────────────────────

    def _features(self, box, out_dir: Path, *, stage, cancelled) -> LoadedLayer:
        if stage is not None:
            stage("Searching Mapillary…")
        groups: list[list[dict[str, Any]]] = []
        for cell in cells(box):
            groups.extend(self._search("map_features", cell, {"fields": FEATURE_FIELDS}, cancelled))
        features = []
        seen: set[str] = set()
        for record in (r for group in groups for r in group):
            key = str(record["id"])
            point = _point(record)
            if key in seen or point is None:
                continue
            seen.add(key)
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [point[0], point[1]]},
                "properties": {
                    "feature_id": key,
                    "object_value": record.get("object_value"),
                    "object_type": record.get("object_type"),
                    "first_seen_at": _iso(record.get("first_seen_at")),
                    "last_seen_at": _iso(record.get("last_seen_at")),
                },
            })
        path = out_dir / "map_features.geojson"
        path.write_text(
            json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":")),
            encoding="utf-8",
        )
        return LoadedLayer(layer="map-features", path=path, features=len(features))


__all__ = ["MapillaryService", "ImageSet", "DownloadedImage", "cells", "quarters", "host_allowed"]
