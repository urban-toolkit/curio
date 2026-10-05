"""Google Street View: told where, it answers with images, sent with the
person's own key.

Two stages, both through the catalog's transport and its address policy:

1. **Where the panoramas are.** Points are laid over the box every
   ``spacing`` metres, in a fixed shuffled order so a count reached early is
   spread over the area, and each is asked of the metadata endpoint, which
   Google does not bill. A point with no panorama answers ``ZERO_RESULTS``;
   panoramas found twice are kept once. It stops once it has enough panoramas
   for the images asked, or after :data:`MAX_POINTS` points.
2. **The images.** One per panorama and heading, at the field of view, pitch
   and size asked. Google answers a grey placeholder where it has no image;
   one of under :data:`PLACEHOLDER_BYTES` is not kept. An image that cannot
   be fetched is skipped and counted, and the rest are kept.

The key goes as Google documents it, ``key=``: the transport adds it to the
request it sends and takes it out of everything it hands back, so no URL a
dataset records holds it. Google's terms allow storing only panorama IDs;
API Settings and the docs say so where the key is entered.
"""

from __future__ import annotations

import math
import random
import re
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

from utk_curio.backend.app.discovery.domain.errors import DiscoveryError, ProviderError
from utk_curio.backend.app.discovery.domain.manifest import (
    DiscoverySourceManifest,
    ResourceSpec,
)
from utk_curio.backend.app.discovery.domain.resource import DiscoveryResource
from utk_curio.backend.app.discovery.providers.autark_osm import Cancelled
from utk_curio.backend.app.discovery.providers.mapillary import (
    FETCH_FAILURES,
    DownloadedImage,
    ImageSet,
    skip_reason,
)

PARAMETER_IDS = ("area", "spacing", "headings", "fov", "pitch", "size", "outdoorOnly", "maxImages")

METADATA_PATH = "/maps/api/streetview/metadata"
IMAGE_PATH = "/maps/api/streetview"

#: The most points one download asks about.
MAX_POINTS = 1000

#: Google's "no image here" answer is a small grey JPEG.
PLACEHOLDER_BYTES = 5000

MAX_IMAGE_BYTES = 8 * 1024 * 1024

DEFAULT_SPACING_M = 30.0
DEFAULT_HEADINGS = ("0", "90", "180", "270")
DEFAULT_FOV = 90
DEFAULT_PITCH = 0
DEFAULT_SIZE = "640x640"
DEFAULT_MAX_IMAGES = 50

_PANO_RE = re.compile(r"[A-Za-z0-9_-]{1,128}")
_SIZE_RE = re.compile(r"^(\d{2,3})x(\d{2,3})$")
_METRES_PER_DEGREE = 111_320.0


def grid(box: list[float], spacing_m: float, *, seed: int = 0) -> list[tuple[float, float]]:
    """``(lat, lon)`` points every *spacing_m* metres inside *box*, in a fixed
    shuffled order (the same box always asks the same points)."""
    west, south, east, north = box
    lat_step = spacing_m / _METRES_PER_DEGREE
    mid = math.radians((south + north) / 2)
    lon_step = spacing_m / (_METRES_PER_DEGREE * max(math.cos(mid), 1e-6))
    rows = max(1, int((north - south) / lat_step))
    cols = max(1, int((east - west) / lon_step))
    points = [
        (round(south + (north - south) * (r + 0.5) / rows, 6), round(west + (east - west) * (c + 0.5) / cols, 6))
        for r in range(rows)
        for c in range(cols)
    ]
    random.Random(seed).shuffle(points)
    return points


class GoogleStreetViewService:
    """The ``google-streetview`` provider: declared resources in, images out."""

    type = "google-streetview"
    crs = "EPSG:4326"
    #: What a dataset's description says of where its images come from.
    attribution = "Google Street View: the Google Maps Platform Terms apply"

    def __init__(self, manifest: DiscoverySourceManifest, *, transport) -> None:
        self.manifest = manifest
        self.transport = transport
        self.base = manifest.provider.base_url

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
    ) -> ImageSet:
        box = (values.get("area") or {}).get("box")
        if not box:
            raise DiscoveryError("Google Street View needs an area: a box")
        headings = sorted({str(h) for h in (values.get("headings") or DEFAULT_HEADINGS)}, key=float)
        size = str(values.get("size") or DEFAULT_SIZE)
        if not _SIZE_RE.match(size) or any(int(n) > 640 for n in size.split("x")):
            raise DiscoveryError(f"Google Street View takes sizes up to 640x640, not {size}")
        limit = int(values.get("maxImages") or DEFAULT_MAX_IMAGES)
        spacing = float(values.get("spacing") or DEFAULT_SPACING_M)
        outdoor = values.get("outdoorOnly", True) is not False
        if stage is not None:
            stage("Finding Street View panoramas…")
        panoramas = self._panoramas(box, spacing, outdoor, math.ceil(limit / len(headings)), cancelled)
        if not panoramas:
            return ImageSet(images=[], found=0)

        folder = out_dir / "images"
        folder.mkdir(parents=True, exist_ok=True)
        fov = int(values.get("fov") if values.get("fov") is not None else DEFAULT_FOV)
        pitch = int(values.get("pitch") if values.get("pitch") is not None else DEFAULT_PITCH)
        images: list[DownloadedImage] = []
        skipped = failed = 0
        asks =[(pano, heading) for pano in panoramas for heading in headings][:limit]
        for index, (pano, heading) in enumerate(asks, start=1):
            if cancelled is not None and cancelled():
                raise Cancelled()
            if stage is not None and (index == 1 or index % 10 == 0):
                stage(f"Downloading image {index:,} of {len(asks):,}…")
            relpath = f"images/{pano['pano_id']}_{heading}.jpg"
            path = out_dir / relpath
            url = f"{self.base}{IMAGE_PATH}?" + urlencode({
                "size": size, "pano": pano["pano_id"], "heading": heading, "fov": fov, "pitch": pitch,
            })
            part = path.with_name(path.name + ".part")
            try:
                with part.open("wb") as handle:
                    self.transport.download(url, handle.write, max_bytes=MAX_IMAGE_BYTES, ceiling=MAX_IMAGE_BYTES)
            except FETCH_FAILURES:
                part.unlink(missing_ok=True)
                skipped += 1
                failed += 1
                continue
            except BaseException:
                part.unlink(missing_ok=True)
                raise
            if part.stat().st_size < PLACEHOLDER_BYTES:
                part.unlink(missing_ok=True)
                skipped += 1
                continue
            part.replace(path)
            images.append(DownloadedImage(
                relpath=relpath, path=path, size=path.stat().st_size,
                image_id=f"{pano['pano_id']}_{heading}",
                columns={
                    "pano_id": pano["pano_id"],
                    "heading": int(heading),
                    "pitch": pitch,
                    "fov": fov,
                    "captured": pano.get("date") or None,
                    "copyright": pano.get("copyright") or None,
                    "gps_lat": pano["lat"],
                    "gps_lon": pano["lon"],
                },
            ))
        return ImageSet(
            images=images, found=len(panoramas), skipped=skipped, failed=failed,
            skip_reason=skip_reason("Google sent its no-image placeholder", skipped, failed),
        )

    def _panoramas(self, box, spacing, outdoor, wanted, cancelled) -> list[dict[str, Any]]:
        import json

        found: list[dict[str, Any]] = []
        seen: set[str] = set()
        for lat, lon in grid(box, spacing)[:MAX_POINTS]:
            if len(found) >= wanted:
                break
            if cancelled is not None and cancelled():
                raise Cancelled()
            params: dict[str, Any] = {"location": f"{lat},{lon}", "radius": int(max(spacing, 10))}
            if outdoor:
                params["source"] = "outdoor"
            try:
                payload = json.loads(self.transport.json_get(f"{self.base}{METADATA_PATH}?" + urlencode(params)))
            except ValueError as exc:
                raise ProviderError("Google Street View answered metadata that is not JSON") from exc
            status = payload.get("status") if isinstance(payload, dict) else None
            if status == "ZERO_RESULTS":
                continue
            if status != "OK":
                # A refused key, a quota or a bad request fails every point the
                # same way: say so rather than reporting no panoramas.
                reason = (payload.get("error_message") if isinstance(payload, dict) else None) or status
                raise ProviderError(f"Google Street View: {reason or 'an unknown answer'}")
            pano_id = str(payload.get("pano_id") or "")
            location = payload.get("location") or {}
            if not _PANO_RE.fullmatch(pano_id) or pano_id in seen:
                continue
            try:
                found_lat, found_lon = float(location["lat"]), float(location["lng"])
            except (KeyError, TypeError, ValueError):
                continue
            seen.add(pano_id)
            found.append({
                "pano_id": pano_id, "lat": found_lat, "lon": found_lon,
                "date": payload.get("date"), "copyright": payload.get("copyright"),
            })
        return found


__all__ = ["GoogleStreetViewService", "grid"]
