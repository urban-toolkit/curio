"""Overture Maps: buildings, places and road segments for a box.

Overture publishes each theme as GeoParquet files in a public bucket, a few
hundred files of half a gigabyte each per feature type, and a STAC catalog
saying where each file is and what box it covers. Only the latest releases
stay in the bucket, so a download asks the catalog for the latest release
rather than naming one.

A download of a box:

1. reads the release's collection for the resource's feature type, and the
   catalog items of the files whose box meets the area;
2. reads each such file's footer (two range requests), and keeps the row
   groups whose ``bbox`` statistics meet the area;
3. fetches those row groups, one range request each, keeps the rows whose
   ``bbox`` meets the area, and writes them as one GeoParquet file, with the
   columns as Overture names them.

Every request goes through the transport (``infrastructure/remote_parquet.py``),
to the catalog's host or a host ``options.dataHosts`` lists.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from utk_curio.backend.app.discovery.domain.errors import DiscoveryError, ProviderError
from utk_curio.backend.app.discovery.domain.manifest import DiscoverySourceManifest, ResourceSpec
from utk_curio.backend.app.discovery.domain.resource import DiscoveryResource
from utk_curio.backend.app.discovery.infrastructure.remote_parquet import RemoteParquet, boxes_meet
from utk_curio.backend.app.discovery.providers.autark_osm import LoadedLayer
from utk_curio.backend.app.discovery.providers.mapillary import host_allowed

PARAMETER_IDS = ("area",)

#: Where Overture's STAC catalog is.
STAC_BASE = "https://stac.overturemaps.org"

#: The asset of a catalog item read: the file in the AWS bucket.
ASSET = "aws"

#: Bytes one download may fetch, footers and row groups together.
MAX_JOB_BYTES = 512 * 1024 * 1024

#: The longest footer read.
MAX_FOOTER_BYTES = 16 * 1024 * 1024

#: Where Overture says how to credit each theme.
ATTRIBUTION_URL = "https://docs.overturemaps.org/attribution/"

_RELEASE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.\d+$")


class OvertureService:
    """The ``overture`` provider: declared resources in, one GeoParquet table out."""

    type = "overture"

    #: Overture's geometries are longitude and latitude.
    crs = "EPSG:4326"

    def __init__(self, manifest: DiscoverySourceManifest, *, transport) -> None:
        self.manifest = manifest
        self.transport = transport
        self.base = manifest.provider.base_url
        self.data_hosts = tuple(str(h).lower() for h in manifest.provider.options.get("dataHosts") or ())
        #: What the last download read: the release and its license.
        self.release: str | None = None
        self.license: str | None = None

    def rows(self) -> tuple[DiscoveryResource, ...]:
        return tuple(self.row(spec) for spec in self.manifest.resources)

    def describe_download(self, spec: ResourceSpec, place: str) -> str:
        """What a dataset's description says of the download just made: the
        release it came from and the license its catalog names."""
        text = f"{spec.name} from Overture Maps release {self.release} for {place}."
        if self.license and self.license.lower() != "other":
            return f"{text} License: {self.license}."
        return f"{text} License and attribution: {ATTRIBUTION_URL}."

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
    ) -> list[LoadedLayer]:
        """The rows of *spec*'s feature type whose box meets the area in *values*."""
        box = (values.get("area") or {}).get("box")
        if not box:
            raise DiscoveryError("Overture Maps needs an area: a box")
        theme, kind = spec.options["theme"], spec.options["type"]
        if stage is not None:
            stage("Finding Overture's latest release…")
        self.release = self._latest_release()
        collection = self._json(f"{self.base}/{self.release}/{theme}/{kind}/collection.json")
        self.license = str(collection.get("license") or "") or None
        files = self._files_meeting(collection, box)
        if stage is not None:
            stage(f"Reading the index of {len(files)} {'file' if len(files) == 1 else 'files'}…")
        plans = []
        planned = 0
        for url, size in files:
            remote = RemoteParquet(
                self.transport, url, size, max_footer_bytes=MAX_FOOTER_BYTES, cancelled=cancelled
            )
            groups = remote.row_groups_meeting(box)
            planned += sum(len(span) for span in remote.requests) + remote.planned_bytes(groups)
            if groups:
                plans.append((remote, groups))
        if planned > MAX_JOB_BYTES:
            raise DiscoveryError(
                f"this area needs {planned / 2**20:,.0f} MB of Overture data, more than one download "
                f"reads ({MAX_JOB_BYTES // 2**20} MB); draw a smaller area"
            )
        layer = str(spec.options.get("layer") or spec.id)
        path = out_dir / f"{layer}.parquet"
        rows = self._write(plans, box, spec.options.get("subtype"), path, stage=stage)
        return [LoadedLayer(layer=layer, path=path, features=rows)]

    # ── the catalog ────────────────────────────────────────────────────────

    def _json(self, url: str) -> dict[str, Any]:
        if not url.startswith(self.base + "/"):
            raise ProviderError(f"Overture's catalog pointed off {self.base}: {url}")
        try:
            payload = json.loads(self.transport.json_get(url))
        except ValueError as exc:
            raise ProviderError(f"Overture's catalog answered {url} with something that is not JSON") from exc
        if not isinstance(payload, dict):
            raise ProviderError(f"Overture's catalog answered {url} in an unknown shape")
        return payload

    def _latest_release(self) -> str:
        release = self._json(f"{self.base}/catalog.json").get("latest")
        if not isinstance(release, str) or not _RELEASE_RE.match(release):
            raise ProviderError("Overture's catalog names no latest release")
        return release

    def _files_meeting(self, collection: dict[str, Any], box) -> list[tuple[str, int]]:
        """The files of *collection* whose box meets *box*, as (url, size).

        The collection lists each file's box in the order it lists the files'
        items; each item kept is read, and its own box and file checked.
        """
        boxes = ((collection.get("extent") or {}).get("spatial") or {}).get("bbox") or []
        items = [link.get("href") for link in collection.get("links") or [] if link.get("rel") == "item"]
        # The first box is the whole collection's; the others are the items', in order.
        if len(boxes) != len(items) + 1:
            raise ProviderError("Overture's collection lists a box count that does not match its files")
        files = []
        for box_of_item, href in zip(boxes[1:], items):
            if not boxes_meet(box_of_item, box):
                continue
            item = self._json(str(href))
            if [float(v) for v in item.get("bbox") or []] != [float(v) for v in box_of_item]:
                raise ProviderError(
                    "Overture's collection lists its files' boxes in an order Curio does not expect"
                )
            asset = (item.get("assets") or {}).get(ASSET) or {}
            url, size = asset.get("href"), asset.get("file:size")
            if not isinstance(url, str) or not isinstance(size, int) or isinstance(size, bool):
                raise ProviderError(f"Overture's item {item.get('id')} names no file and size")
            if urlsplit(url).scheme != "https" or not host_allowed(url, self.data_hosts):
                raise ProviderError(f"Overture's item {item.get('id')} names a file on a host its source does not list")
            files.append((url, size))
        return files

    # ── the rows ───────────────────────────────────────────────────────────

    def _write(self, plans, box, subtype, path: Path, *, stage) -> int:
        """Keep the rows meeting *box* (and of *subtype*, when one is named),
        written to *path* as GeoParquet. Returns the rows kept."""
        import pyarrow.compute as pc
        import pyarrow.parquet as pq

        west, south, east, north = box
        total_groups = sum(len(groups) for _, groups in plans)
        # The rows are written here first: the box of the rows kept, which the
        # final file's metadata carries, is known only once they all are.
        part = path.with_name(path.name + ".part")
        writer = None
        schema = None
        geo: dict[str, Any] = {}
        extent = [float("inf"), float("inf"), float("-inf"), float("-inf")]
        rows = 0
        done = 0
        try:
            for remote, groups in plans:
                for g in groups:
                    done += 1
                    if stage is not None:
                        stage(f"Downloading part {done:,} of {total_groups:,}…")
                    table = remote.read_row_group(g)
                    bbox = table.column("bbox").combine_chunks()
                    xmin, ymin = bbox.field("xmin"), bbox.field("ymin")
                    xmax, ymax = bbox.field("xmax"), bbox.field("ymax")
                    keep = pc.and_(
                        pc.and_(pc.less_equal(xmin, east), pc.greater_equal(xmax, west)),
                        pc.and_(pc.less_equal(ymin, north), pc.greater_equal(ymax, south)),
                    )
                    if subtype is not None:
                        keep = pc.and_(keep, pc.equal(table.column("subtype"), subtype))
                    table = table.filter(pc.fill_null(keep, False))
                    if table.num_rows == 0:
                        continue
                    bbox = table.column("bbox").combine_chunks()
                    extent = [
                        min(extent[0], pc.min(bbox.field("xmin")).as_py()),
                        min(extent[1], pc.min(bbox.field("ymin")).as_py()),
                        max(extent[2], pc.max(bbox.field("xmax")).as_py()),
                        max(extent[3], pc.max(bbox.field("ymax")).as_py()),
                    ]
                    if writer is None:
                        geo = remote.geo()
                        schema = table.schema.remove_metadata()
                        writer = pq.ParquetWriter(part, schema)
                    try:
                        table = table.replace_schema_metadata(None).cast(schema)
                    except (ValueError, TypeError) as exc:
                        raise ProviderError("Overture's files of one feature type disagree on their columns") from exc
                    writer.write_table(table)
                    rows += table.num_rows
            if writer is not None:
                writer.close()
                writer = None
                _with_geo(part, path, geo, extent)
        finally:
            if writer is not None:
                writer.close()
            part.unlink(missing_ok=True)
        return rows


def _with_geo(part: Path, path: Path, geo: dict[str, Any], extent: list[float]) -> None:
    """*part*'s rows, copied a row group at a time to *path* with GeoParquet
    ``geo`` metadata: the source file's, its geometry column's box made the
    box of the rows kept."""
    import pyarrow.parquet as pq

    geo = json.loads(json.dumps(geo)) if geo else {}
    primary = geo.get("primary_column") or "geometry"
    geo.setdefault("version", "1.1.0")
    geo["primary_column"] = primary
    column = geo.setdefault("columns", {}).setdefault(primary, {"encoding": "WKB", "geometry_types": []})
    column["bbox"] = [float(v) for v in extent]
    source = pq.ParquetFile(part)
    schema = source.schema_arrow.with_metadata({b"geo": json.dumps(geo).encode("utf-8")})
    with pq.ParquetWriter(path, schema) as writer:
        for g in range(source.num_row_groups):
            writer.write_table(source.read_row_group(g).replace_schema_metadata(schema.metadata))


__all__ = ["OvertureService", "STAC_BASE", "MAX_JOB_BYTES"]
