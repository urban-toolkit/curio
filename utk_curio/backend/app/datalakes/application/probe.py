"""Read what a media file says about itself.

One function per kind, each taking a local path and returning plain values:
the columns a collection's index carries. A file that cannot be read returns
``{"probe_error": "..."}`` rather than raising, so one bad file costs its own
details and never the collection.

Pillow reads images (lazily: the header, EXIF and GPS, never the pixels),
PyAV reads video and audio containers, and rasterio reads georeferenced
rasters, each pinned to the one format a file's first bytes say it is.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

#: How long a probe may spend on one container before it is given up on.
AV_TIMEOUT_SECONDS = 20


class NotItsFormat(ValueError):
    """A file whose bytes are not a format its kind may be."""


def sniff(head: bytes) -> str | None:
    """The type a file's first bytes say it is, or None."""
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio/wav"
    if head[:4] == b"RIFF" and head[8:12] == b"AVI ":
        return "video/x-msvideo"
    if head[:4] == b"FORM" and head[8:12] in (b"AIFF", b"AIFC"):
        return "audio/aiff"
    if head.startswith(b"BM"):
        return "image/bmp"
    if head[:4] in (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"):
        return "image/tiff"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"M4A ", b"M4B "):
            return "audio/mp4"
        if brand == b"qt  ":
            return "video/quicktime"
        return "video/mp4"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    if head.startswith(b"fLaC"):
        return "audio/flac"
    if head.startswith(b"OggS"):
        return "audio/ogg"
    if head.startswith(b"ID3") or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio/mpeg"
    if head[:12] == b"\x00\x00\x00\x0cjP  \r\n\x87\n":
        return "image/jp2"
    return None


_IMAGE_READERS = {
    "image/jpeg": "JPEG", "image/png": "PNG", "image/gif": "GIF",
    "image/webp": "WEBP", "image/bmp": "BMP", "image/tiff": "TIFF",
}

#: The formats each kind of collection file may be, by its first bytes, and
#: the one reader each is opened with: a Pillow format, a GDAL driver, or an
#: ffmpeg demuxer. A file is decoded only when its content is one of these,
#: whatever its name says, and only by that reader. Left to themselves, GDAL
#: and ffmpeg choose a reader from the content, and some of theirs (a VRT, a
#: playlist) read other files or hosts that the file names.
KIND_READERS: dict[str, dict[str, str]] = {
    "image": _IMAGE_READERS,
    "frame": _IMAGE_READERS,
    "raster": {"image/tiff": "GTiff", "image/jp2": "JP2OpenJPEG"},
    "video": {
        "video/mp4": "mov", "video/quicktime": "mov", "video/webm": "matroska",
        "video/x-msvideo": "avi",
    },
    "audio": {
        "audio/wav": "wav", "audio/mpeg": "mp3", "audio/ogg": "ogg",
        "audio/flac": "flac", "audio/mp4": "mov", "audio/aiff": "aiff",
    },
}

_KIND_NOUN = {
    "image": "an image", "frame": "an image", "raster": "a GeoTIFF or JPEG 2000 raster",
    "video": "a video", "audio": "a recording",
}


def reader_for(kind: str, path: Path) -> str:
    """The one reader *path* may be opened with, as a *kind* file."""
    with open(path, "rb") as handle:
        found = sniff(handle.read(32))
    reader = KIND_READERS.get(kind, {}).get(found or "")
    if reader is None:
        raise NotItsFormat(f"its contents are not {_KIND_NOUN.get(kind, 'a file')} Curio reads")
    return reader


def open_image(path: Path, kind: str = "image"):
    from PIL import Image

    return Image.open(path, formats=[reader_for(kind, path)])


def open_raster(path: Path):
    import rasterio

    return rasterio.open(path, driver=reader_for("raster", path))


def open_container(path: Path, kind: str):
    import av

    return av.open(str(path), format=reader_for(kind, path), timeout=AV_TIMEOUT_SECONDS)

_EXIF_IFD = 0x8769
_GPS_IFD = 0x8825
_DATETIME_ORIGINAL = 0x9003
_DATETIME = 0x0132


def _error(exc: Exception) -> dict[str, Any]:
    text = str(exc).strip() or type(exc).__name__
    return {"probe_error": text[:200]}


def _exif_time(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        return datetime.strptime(raw.strip()[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def _dms(value: Any, ref: Any) -> float | None:
    try:
        degrees, minutes, seconds = (float(part) for part in value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    decimal = degrees + minutes / 60 + seconds / 3600
    if isinstance(ref, bytes):
        ref = ref.decode("ascii", "ignore")
    if str(ref).strip().upper() in ("S", "W"):
        decimal = -decimal
    return round(decimal, 7)


def probe_image(path: Path, kind: str = "image") -> dict[str, Any]:
    """Size, capture time and GPS position of an image."""
    try:
        with open_image(path, kind) as image:
            width, height = image.size
            # The size is in the header; EXIF may not be. A PNG keeps it after
            # the pixels, so a bucket file probed from its first bytes has a
            # size and no EXIF, which is still a row worth having.
            try:
                exif = image.getexif()
            except Exception:  # noqa: BLE001 - a partial file, or a broken EXIF block
                exif = None
            taken = lat = lon = None
            if exif is not None:
                orientation = exif.get(0x0112)
                # A camera held on its side writes the pixels landscape and
                # says so here: the size a viewer shows is the swapped one.
                if orientation in (5, 6, 7, 8):
                    width, height = height, width
                taken = _exif_time(exif.get_ifd(_EXIF_IFD).get(_DATETIME_ORIGINAL)) or _exif_time(
                    exif.get(_DATETIME)
                )
                gps = exif.get_ifd(_GPS_IFD)
                lat = _dms(gps.get(2), gps.get(1)) if gps else None
                lon = _dms(gps.get(4), gps.get(3)) if gps else None
    except Exception as exc:  # noqa: BLE001 - one bad file must not stop the rest
        return _error(exc)
    out: dict[str, Any] = {"width": width, "height": height, "taken_at": taken}
    if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180:
        out["gps_lat"], out["gps_lon"] = lat, lon
    return out


def _container_time(container) -> datetime | None:
    meta = dict(container.metadata or {})
    for key in ("creation_time", "date"):
        value = meta.get(key)
        if not value:
            continue
        text = str(value).replace("Z", "+00:00")
        for fmt in (None, "%Y-%m-%d", "%Y:%m:%d %H:%M:%S"):
            try:
                parsed = datetime.fromisoformat(text) if fmt is None else datetime.strptime(text[:19], fmt)
                return parsed.replace(tzinfo=None)
            except ValueError:
                continue
    # A Broadcast Wave file says when it was recorded in its bext chunk.
    date, time = meta.get("origination_date"), meta.get("origination_time")
    if date and time:
        try:
            return datetime.strptime(f"{date} {time}".replace(":", "-", 2)[:19], "%Y-%m-%d %H-%M-%S")
        except ValueError:
            return None
    return None


def _duration(container, stream) -> float | None:
    if stream.duration is not None and stream.time_base is not None:
        return round(float(stream.duration * stream.time_base), 3)
    if container.duration is not None:
        return round(container.duration / 1_000_000, 3)
    return None


def probe_video(path: Path) -> dict[str, Any]:
    """Size, duration, frame rate and codec of a video."""
    try:
        with open_container(path, "video") as container:
            if not container.streams.video:
                return {"probe_error": "no video stream"}
            stream = container.streams.video[0]
            rate = stream.average_rate or stream.base_rate
            return {
                "width": stream.codec_context.width or None,
                "height": stream.codec_context.height or None,
                "duration_s": _duration(container, stream),
                "fps": round(float(rate), 3) if rate else None,
                "codec": stream.codec_context.name,
                "taken_at": _container_time(container),
            }
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


def probe_audio(path: Path) -> dict[str, Any]:
    """Duration, sample rate, channels and codec of a recording."""
    try:
        with open_container(path, "audio") as container:
            if not container.streams.audio:
                return {"probe_error": "no audio stream"}
            stream = container.streams.audio[0]
            context = stream.codec_context
            channels = getattr(getattr(context, "layout", None), "nb_channels", None) or getattr(
                context, "channels", None
            )
            return {
                "duration_s": _duration(container, stream),
                "sample_rate": context.sample_rate or None,
                "channels": channels or None,
                "codec": context.name,
                "recorded_at": _container_time(container),
            }
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


def probe_raster(path: Path) -> dict[str, Any]:
    """Georeferencing, size, bands and footprint of a raster."""
    try:
        from rasterio.warp import transform_bounds
        from shapely.geometry import box

        with open_raster(path) as src:
            if src.crs is None or src.transform.is_identity:
                return {
                    "width": src.width, "height": src.height, "bands": src.count,
                    "probe_error": "not georeferenced",
                }
            west, south, east, north = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
            epsg = src.crs.to_epsg()
            tags = src.tags()
            return {
                "crs": f"EPSG:{epsg}" if epsg else src.crs.to_wkt()[:500],
                "transform": list(src.transform)[:6],
                "res": round(float(src.res[0]), 6),
                "width": src.width,
                "height": src.height,
                "bands": src.count,
                "dtype": str(src.dtypes[0]),
                "nodata": src.nodata,
                "taken_at": _exif_time(tags.get("TIFFTAG_DATETIME")),
                "geometry": box(west, south, east, north),
            }
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


IMAGE_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "webp", "gif", "bmp", "tif", "tiff"})
VIDEO_EXTENSIONS = frozenset({"mp4", "mov", "m4v", "webm", "mkv", "avi"})
AUDIO_EXTENSIONS = frozenset({"wav", "flac", "mp3", "ogg", "opus", "m4a", "aiff", "aif"})


def file_kind(resource_kind: str, relpath: str) -> str:
    """What one file of a collection is: ``image``, ``video``, ``frame``,
    ``audio`` or ``raster``."""
    ext = relpath.rsplit(".", 1)[-1].lower() if "." in relpath else ""
    if resource_kind == "rasters":
        return "raster"
    if resource_kind == "frames":
        return "frame"
    if resource_kind == "audio":
        return "audio"
    if resource_kind == "videos" or ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in AUDIO_EXTENSIONS:
        return "audio"
    return "image"


def probe(file_kind_name: str, path: Path) -> dict[str, Any]:
    if file_kind_name in ("image", "frame"):
        return probe_image(path, file_kind_name)
    if file_kind_name == "video":
        return probe_video(path)
    if file_kind_name == "audio":
        return probe_audio(path)
    if file_kind_name == "raster":
        return probe_raster(path)
    return {}
