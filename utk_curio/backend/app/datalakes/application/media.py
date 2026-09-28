"""A collection's files, as the browser sees them.

The browser names a file by its collection and ``file_id``, never by a path:
the id is looked up in the collection's own index, the relpath found there is
resolved through the collection's lake source (which checks it against the
source's root), and only then is anything read. What is served:

- ``thumb``: a JPEG drawn from an image, a raster, a video's frame, or an
  audio recording's spectrogram;
- ``poster``: a video's frame;
- ``original``: the file itself, when a browser can show or play its format.

Every type is decided from the file's own first bytes against an allowlist, so
a file named ``.jpg`` that holds HTML is refused rather than served.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from utk_curio.backend.app.datalakes.domain.errors import (
    CapabilityUnsupported,
    DataLakeError,
    ResourceNotFound,
)
from utk_curio.backend.app.datalakes.infrastructure import media_dirs
from utk_curio.backend.app.datalakes.application.probe import (  # noqa: F401 - sniff is media's API too
    open_container,
    open_image,
    open_raster,
    sniff,
)

THUMB_EDGE = 384
JPEG_QUALITY = 82

#: A remote image is fetched whole to draw its thumbnail, up to this size.
MAX_REMOTE_THUMB_SOURCE_BYTES = 64 * 1024 * 1024

#: An image larger than this, after JPEG's own downscaling, has no thumbnail:
#: decoding it would cost more memory than a preview is worth.
MAX_THUMB_SOURCE_PIXELS = 64_000_000

#: The formats served as ``original``: ones a browser shows or plays.
BROWSER_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp",
    "video/mp4", "video/webm", "video/quicktime",
    "audio/wav", "audio/mpeg", "audio/ogg", "audio/flac", "audio/mp4",
}


class MediaUnavailable(DataLakeError):
    """The file exists in the index but cannot be served as asked."""

    status = 415


@dataclass(frozen=True)
class IndexRow:
    file_id: str
    relpath: str
    ext: str
    kind: str
    bytes: int
    mtime: str


class _IndexCache:
    """``file_id -> row`` per collection, for the few collections in use."""

    def __init__(self, size: int = 8) -> None:
        self._rows: OrderedDict[tuple[str, int], dict[str, IndexRow]] = OrderedDict()
        self._lock = threading.Lock()
        self.size = size

    def rows(self, index_path: str) -> dict[str, IndexRow]:
        stamp = os.stat(index_path).st_mtime_ns
        key = (index_path, stamp)
        with self._lock:
            if key in self._rows:
                self._rows.move_to_end(key)
                return self._rows[key]
        import pandas as pd

        frame = pd.read_parquet(index_path, columns=["file_id", "relpath", "ext", "kind", "bytes", "mtime"])
        rows = {
            r.file_id: IndexRow(r.file_id, r.relpath, r.ext, r.kind, int(r.bytes), str(r.mtime))
            for r in frame.itertuples(index=False)
        }
        with self._lock:
            self._rows[key] = rows
            while len(self._rows) > self.size:
                self._rows.popitem(last=False)
        return rows


index_cache = _IndexCache()


@dataclass(frozen=True)
class Located:
    dataset_id: str
    row: IndexRow
    #: A readable path on this machine, or None for an uncached bucket file.
    local: Path | None
    provider: Any


_DERIVED_ID_RE = __import__("re").compile(r"^([0-9a-f]{16})@([0-9]{1,12})$")


def locate(service, dataset_id: str, file_id: str) -> Located:
    """Find one file of this account's collection, by id.

    ``<file_id>@<t_ms>`` names a file a node derived from one of the
    collection's: a video's frame or a recording's window, written where
    ``curio_derived_file`` put it.
    """
    from utk_curio.backend.app.datalakes.application import cache_collection

    item, manifest = service.collection(dataset_id)
    path = item.get("path")
    if not path or not os.path.isfile(path):
        raise ResourceNotFound(f"{dataset_id!r} has no index on disk")
    rows = index_cache.rows(path)
    derived = _DERIVED_ID_RE.match(file_id)
    if derived:
        return _locate_derived(service, dataset_id, rows, derived.group(1), int(derived.group(2)))
    row = rows.get(file_id)
    if row is None:
        raise ResourceNotFound(f"{file_id!r} is not a file of {dataset_id!r}")
    provider = service._storage_for(manifest)
    local = provider.local_path(row.relpath)
    if local is None:
        local = cache_collection.cached_file(service.user_key, dataset_id, row.file_id, row.ext)
    return Located(dataset_id=dataset_id, row=row, local=Path(local) if local else None, provider=provider)


def _locate_derived(service, dataset_id: str, rows, source_id: str, t_ms: int) -> Located:
    from utk_curio.sandbox.util.collections import DERIVED, derived_relpath

    source = rows.get(source_id)
    if source is None or source.kind not in DERIVED:
        raise ResourceNotFound(f"{source_id!r} is not a video or recording of {dataset_id!r}")
    folder, ext, kind = DERIVED[source.kind]
    path = media_dirs.media_work_root(service.user_key) / derived_relpath(
        folder, dataset_id, source_id, t_ms, ext
    )
    if not path.is_file():
        raise ResourceNotFound("this file has not been extracted; run the node that makes it again")
    stat = path.stat()
    row = IndexRow(
        file_id=f"{source_id}@{t_ms}", relpath=f"{source.relpath}@{t_ms}", ext=ext, kind=kind,
        bytes=stat.st_size, mtime=str(stat.st_mtime_ns),
    )
    return Located(dataset_id=dataset_id, row=row, local=path, provider=None)


# ── what is served ─────────────────────────────────────────────────────────


def original(found: Located) -> tuple[Path, str]:
    """The file itself and its sniffed type, when a browser can use it."""
    if found.local is None:
        raise MediaUnavailable(
            f"{found.row.relpath} is in a bucket and not on this machine; cache the collection's files first"
        )
    with found.local.open("rb") as handle:
        kind = sniff(handle.read(32))
    if kind not in BROWSER_TYPES:
        raise MediaUnavailable(f"{found.row.relpath} is not a format a browser shows")
    return found.local, kind


def thumbnail(service, found: Located, *, variant: str = "thumb") -> Path:
    """A cached JPEG for the file, drawn on first request."""
    stamp = hashlib.sha1(f"{found.row.bytes}:{found.row.mtime}".encode()).hexdigest()[:10]
    cache = media_dirs.media_cache_dir(service.user_key, found.dataset_id)
    target = cache / f"{found.row.file_id}-{variant}-{stamp}.jpg"
    if target.is_file():
        return target
    _render(found, variant, target)
    for stale in cache.glob(f"{found.row.file_id}-{variant}-*.jpg"):
        if stale != target:
            stale.unlink(missing_ok=True)
    return target


def _render(found: Located, variant: str, target: Path) -> None:
    try:
        image = _draw(found, variant)
    except DataLakeError:
        raise
    except Exception as exc:  # noqa: BLE001 - a file that cannot be decoded
        raise MediaUnavailable(f"{found.row.relpath} could not be drawn: {exc}"[:200]) from exc
    image.thumbnail((THUMB_EDGE, THUMB_EDGE))
    # A name of its own: two requests can draw the same thumbnail at once.
    fd, part = tempfile.mkstemp(dir=target.parent, prefix=target.name + ".", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as handle:
            image.convert("RGB").save(handle, "JPEG", quality=JPEG_QUALITY)
        os.replace(part, target)
    except BaseException:
        Path(part).unlink(missing_ok=True)
        raise


def _source_path(found: Located) -> tuple[Path, bool]:
    """A local copy to draw from: the file, or a temporary fetch of it."""
    if found.local is not None:
        return found.local, False
    if found.row.kind not in ("image", "frame", "raster") or found.row.bytes > MAX_REMOTE_THUMB_SOURCE_BYTES:
        raise MediaUnavailable(
            f"{found.row.relpath} is in a bucket; cache the collection's files to preview it"
        )
    body = found.provider.open(found.row.relpath).read(MAX_REMOTE_THUMB_SOURCE_BYTES + 1)
    if len(body) > MAX_REMOTE_THUMB_SOURCE_BYTES:
        raise MediaUnavailable(f"{found.row.relpath} is too large to preview before it is cached")
    handle = tempfile.NamedTemporaryFile(suffix="." + found.row.ext, delete=False)
    with handle:
        handle.write(body)
    return Path(handle.name), True


def _draw(found: Located, variant: str):
    kind = found.row.kind
    if variant == "poster" and kind != "video":
        raise MediaUnavailable("only a video has a poster")
    path, temporary = _source_path(found)
    try:
        if kind in ("image", "frame"):
            return _image(path, kind)
        if kind == "raster":
            return _raster(path)
        if kind == "video":
            return _poster(path)
        if kind == "audio":
            return _spectrogram(path)
    finally:
        if temporary:
            path.unlink(missing_ok=True)
    raise CapabilityUnsupported(f"no preview for a {kind}")


def _image(path: Path, kind: str = "image"):
    from PIL import ImageOps

    with open_image(path, kind) as image:
        image.draft("RGB", (THUMB_EDGE, THUMB_EDGE))
        if image.width * image.height > MAX_THUMB_SOURCE_PIXELS:
            raise MediaUnavailable("the image is too large to preview")
        return ImageOps.exif_transpose(image).convert("RGB")


def _raster(path: Path):
    import numpy as np
    from PIL import Image
    from rasterio.enums import Resampling

    with open_raster(path) as src:
        scale = max(src.width, src.height) / THUMB_EDGE
        width = max(1, int(src.width / max(scale, 1)))
        height = max(1, int(src.height / max(scale, 1)))
        bands = list(range(1, min(src.count, 3) + 1))
        data = src.read(bands, out_shape=(len(bands), height, width), resampling=Resampling.average)
        nodata = src.nodata
    data = data.astype("float64")
    if nodata is not None:
        data = np.where(data == nodata, np.nan, data)
    out = np.zeros_like(data)
    for index in range(data.shape[0]):
        band = data[index]
        finite = band[np.isfinite(band)]
        low, high = (np.percentile(finite, [2, 98]) if finite.size else (0.0, 1.0))
        high = high if high > low else low + 1
        out[index] = np.clip((band - low) / (high - low), 0, 1)
    pixels = (np.nan_to_num(out) * 255).astype("uint8")
    if pixels.shape[0] == 1:
        return Image.fromarray(pixels[0], mode="L")
    if pixels.shape[0] == 2:
        pixels = np.concatenate([pixels, pixels[:1]])
    return Image.fromarray(np.transpose(pixels, (1, 2, 0)), mode="RGB")


def _poster(path: Path):
    with open_container(path, "video") as container:
        stream = container.streams.video[0]
        duration = None
        if stream.duration is not None and stream.time_base is not None:
            duration = float(stream.duration * stream.time_base)
        elif container.duration:
            duration = container.duration / 1_000_000
        if duration:
            container.seek(int(duration * 0.1 / stream.time_base), stream=stream, any_frame=False)
        for frame in container.decode(stream):
            return frame.to_image()
    raise MediaUnavailable("the video has no frame to show")


def _spectrogram(path: Path, *, seconds: float = 60.0):
    """A log-magnitude spectrogram of the first minute, drawn in viridis-like tones."""
    import av
    import numpy as np
    from PIL import Image

    samples = []
    rate = None
    with open_container(path, "audio") as container:
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="flt", layout="mono", rate=16000)
        rate = 16000
        total = 0
        for frame in container.decode(stream):
            for out in resampler.resample(frame):
                chunk = out.to_ndarray().reshape(-1)
                samples.append(chunk)
                total += chunk.size
            if total >= seconds * rate:
                break
    if not samples:
        raise MediaUnavailable("the recording holds no samples")
    signal = np.concatenate(samples)[: int(seconds * rate)]
    window, hop = 512, 256
    if signal.size < window:
        signal = np.pad(signal, (0, window - signal.size))
    frames = 1 + (signal.size - window) // hop
    stack = np.lib.stride_tricks.as_strided(
        signal, shape=(frames, window), strides=(signal.strides[0] * hop, signal.strides[0])
    )
    magnitude = np.abs(np.fft.rfft(stack * np.hanning(window), axis=1)).T
    db = 20 * np.log10(magnitude + 1e-6)
    db = np.clip((db - db.max() + 80) / 80, 0, 1)[::-1]
    stops = np.array([[68, 1, 84], [59, 82, 139], [33, 145, 140], [94, 201, 98], [253, 231, 37]], float)
    positions = db * (len(stops) - 1)
    low = np.floor(positions).astype(int).clip(0, len(stops) - 2)
    frac = (positions - low)[..., None]
    rgb = stops[low] * (1 - frac) + stops[low + 1] * frac
    image = Image.fromarray(rgb.astype("uint8"), mode="RGB")
    return image.resize((THUMB_EDGE, THUMB_EDGE // 3))


# ── sample thumbnails, before anything is added ────────────────────────────


def sample_thumbnail(manifest, provider, sample, *, user_key: str | None = None) -> Path:
    """A thumbnail of one of a lake row's sample files.

    Cached with the listing it belongs to: per source for a public one, and in
    *user_key*'s own media cache for a source that sends a token. Never in the
    source itself.
    """
    from utk_curio.backend.app.common.user_storage import curio_root

    if sample.kind not in ("image", "frame", "raster", "video", "audio"):
        raise MediaUnavailable("no preview for this file")
    if user_key is None:
        folder = curio_root() / "datalakes-cache" / manifest.dir_name / "samples"
        folder.mkdir(parents=True, exist_ok=True)
    else:
        source = hashlib.sha1(manifest.dir_name.encode("utf-8")).hexdigest()[:16]
        folder = media_dirs.media_cache_dir(user_key, "lake-samples") / source
        folder.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f"{sample.relpath}:{sample.bytes}:{sample.mtime}".encode()).hexdigest()[:20]
    target = folder / f"{key}.jpg"
    if target.is_file():
        return target
    local = provider.local_path(sample.relpath)
    row = IndexRow(key, sample.relpath, sample.relpath.rsplit(".", 1)[-1].lower(), sample.kind, sample.bytes, "")
    _render(Located(dataset_id="", row=row, local=Path(local) if local else None, provider=provider), "thumb", target)
    return target


# ── signed links, for <video> and <audio> ──────────────────────────────────

LINK_TTL_SECONDS = 600
_LINK_SALT = "curio-collection-media"


def _link_secret() -> bytes:
    """A key only this deployment holds, kept beside its other state.

    Not ``SECRET_KEY``: that falls back to a well-known placeholder when unset,
    and a link signed with a public key is no link at all. Generated once and
    shared by every worker on the host.
    """
    from utk_curio.backend.app.common.user_storage import curio_root

    path = curio_root() / "media-link.key"
    if path.is_file():
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    secret = os.urandom(32)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        return path.read_bytes()
    with os.fdopen(fd, "wb") as handle:
        handle.write(secret)
    return secret


def _serializer():
    from itsdangerous import URLSafeTimedSerializer

    return URLSafeTimedSerializer(_link_secret(), salt=_LINK_SALT)


def sign(user_id: int | None, user_key: str, dataset_id: str, file_id: str) -> str:
    return _serializer().dumps({"u": user_id, "k": user_key, "d": dataset_id, "f": file_id})


def verify(token: str) -> dict[str, Any]:
    from itsdangerous import BadSignature, SignatureExpired

    try:
        return _serializer().loads(token, max_age=LINK_TTL_SECONDS)
    except SignatureExpired as exc:
        raise ResourceNotFound("this media link has expired") from exc
    except BadSignature as exc:
        raise ResourceNotFound("not a media link") from exc
