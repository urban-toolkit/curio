"""Media's steps over a collection's rows, as ``curio_load_collection`` returns
them: frames sampled from its videos (``sample_video_frames``) and its
recordings split into windows with their levels (``split_audio``). Sample
Video Frames and Split Audio call them with their settings. Each frame or
window is a file written where ``curio_derived_file``, which a node hands in,
says: beside the collection's other derived files.

Mosaic Rasters calls Rasterization's ``scout_rasters.mosaic``
(``curio.rasterization@1``, which the package names in
``dependencies.packages``).
"""

import datetime
import math
import wave

import av
import geopandas as gpd
import numpy as np
import pandas as pd

#: What node code calls.
__all__ = ["sample_video_frames", "split_audio"]

#: A video's own columns that describe the file, not what a frame inherits.
VIDEO_FILE_COLUMNS = {
    "file_id", "relpath", "name", "ext", "kind", "bytes", "mtime", "duration_s",
    "fps", "codec", "width", "height", "path", "thumbnail", "image_url",
    "audio_url", "probe_error", "geometry",
}

#: A recording's own columns that describe the file, not what a window inherits.
RECORDING_FILE_COLUMNS = {
    "file_id", "relpath", "name", "ext", "kind", "bytes", "mtime", "duration_s",
    "sample_rate", "channels", "codec", "path", "thumbnail", "image_url",
    "audio_url", "probe_error", "geometry",
}


# ---------------------------------------------------------------------------
# Frames from videos
# ---------------------------------------------------------------------------

def sample_video_frames(media, derived_file, *, every_seconds=2.0, max_frames_per_video=300):
    """A frame every *every_seconds* seconds from every video in a collection,
    at most *max_frames_per_video* from one video: one row per frame, each
    frame a JPEG written where *derived_file* (``curio_derived_file``) says.

    *media* is a collection's rows, as ``curio_load_collection`` returns them;
    rows that are not videos are left out. A frame row has the columns of an
    image row (``path``, ``thumbnail``, ``image_url``, ``width``, ``height``),
    so Simple View shows the frames and any node that reads images reads them.
    It also keeps the video's own columns: its fields, its position, and its
    time, moved forward by the frame's offset. ``t_s`` is the frame's time in
    the video, ``frame`` its number there and ``sequence`` the video. A video
    whose file is not on this machine yet is refused with its path in the
    collection.
    """
    videos = media[media["kind"] == "video"]
    rows = []
    geometries = []
    for _, video in videos.iterrows():
        if not isinstance(video["path"], str) or not video["path"]:
            raise ValueError(
                f"{video['relpath']} is not on this machine yet; cache the collection's files first"
            )
        with av.open(video["path"]) as container:
            stream = container.streams.video[0]
            rate = float(stream.average_rate) if stream.average_rate else None
            length = _length_of(container, stream)
            sampled = (
                _by_seeking(container, stream, length, every_seconds, max_frames_per_video)
                if length is not None
                else _by_reading(container, stream, rate, every_seconds)
            )
            last = None
            for at, frame in sampled:
                t_s = round(float(at), 3)
                if t_s == last:
                    continue  # two sample times that land on one frame
                last = t_s
                number = (
                    int(round(t_s * rate)) if rate
                    else len([r for r in rows if r["video_file_id"] == video["file_id"]])
                )
                image = frame.to_image()
                derived = derived_file(video["dataset_id"], video["file_id"], round(t_s * 1000))
                image.save(derived["path"], "JPEG", quality=85)
                row = {k: video[k] for k in video.index if k not in VIDEO_FILE_COLUMNS}
                taken = video.get("taken_at")
                if isinstance(taken, (pd.Timestamp, datetime.datetime)) and not pd.isna(taken):
                    row["taken_at"] = taken + datetime.timedelta(seconds=t_s)
                row.update({
                    "file_id": derived["file_id"],
                    "kind": "frame",
                    "video_file_id": video["file_id"],
                    "sequence": video["name"],
                    "frame": number,
                    "t_s": t_s,
                    "width": image.width,
                    "height": image.height,
                    "path": derived["path"],
                    "thumbnail": derived["thumbnail"],
                    "image_url": derived["image_url"],
                })
                rows.append(row)
                geometries.append(video["geometry"] if "geometry" in video.index else None)
                if len([r for r in rows if r["video_file_id"] == video["file_id"]]) >= max_frames_per_video:
                    break

    frames = pd.DataFrame(rows)
    if isinstance(media, gpd.GeoDataFrame) and rows:
        frames = gpd.GeoDataFrame(frames, geometry=geometries, crs=media.crs)
    return frames


def _length_of(container, stream):
    """The video's length in seconds, or None when its file does not say."""
    if stream.duration is not None:
        return float(stream.duration * stream.time_base)
    if container.duration is not None:
        return container.duration / 1_000_000
    return None


def _by_seeking(container, stream, length, every_seconds, max_frames_per_video):
    """The frame showing at each sample time, reached by seeking."""
    targets = [0.0]
    while len(targets) < max_frames_per_video and targets[-1] + every_seconds < length:
        targets.append(round(targets[-1] + every_seconds, 6))
    for target in targets:
        container.seek(int(target / stream.time_base), stream=stream, backward=True)
        frame = None
        for candidate in container.decode(stream):
            frame = candidate
            if candidate.time is None or candidate.time >= target - 1e-3:
                break
        if frame is not None:
            yield (frame.time if frame.time is not None else target), frame


def _by_reading(container, stream, rate, every_seconds):
    """The first frame at or past each sample time, read from the start: for a
    video whose length its file does not give."""
    wanted = 0.0
    for index, frame in enumerate(container.decode(stream)):
        at = frame.time if frame.time is not None else (index / rate if rate else None)
        if at is None:
            # Neither a time nor a rate: only the first frame can be placed.
            if index == 0:
                yield 0.0, frame
            return
        if at >= wanted - 1e-3:
            yield at, frame
            wanted = at + every_seconds


# ---------------------------------------------------------------------------
# Windows of recordings
# ---------------------------------------------------------------------------

def split_audio(media, derived_file, *, window_seconds=5.0, max_windows_per_recording=2000):
    """Every recording in a collection split into windows of *window_seconds*
    seconds, at most *max_windows_per_recording* from one recording: one row
    per window, with its level and peak in dBFS and its clip, a WAV written
    where *derived_file* (``curio_derived_file``) says.

    *media* is a collection's rows, as ``curio_load_collection`` returns them;
    rows that are not recordings are left out. ``level_dbfs`` and ``peak_dbfs``
    are the window's level and peak in decibels below full scale, over all of
    its channels, and its clip keeps the recording's channels, so Simple View
    can play it (``audio_url``). A window row keeps the recording's fields, and
    its ``recorded_at`` moves forward by the window's offset, ``t_s``. A
    recording is read one window at a time. A recording whose file is not on
    this machine yet is refused with its path in the collection.
    """
    recordings = media[media["kind"] == "audio"]
    rows = []
    for _, recording in recordings.iterrows():
        if not isinstance(recording["path"], str) or not recording["path"]:
            raise ValueError(
                f"{recording['relpath']} is not on this machine yet; cache the collection's files first"
            )
        for rate, start, window in _windows(recording["path"], window_seconds, max_windows_per_recording):
            scaled = window.astype(np.float64) / 32768.0
            t_s = round(start / rate, 3)
            derived = derived_file(
                recording["dataset_id"], recording["file_id"], round(t_s * 1000), kind="audio"
            )
            with wave.open(derived["path"], "wb") as handle:
                handle.setnchannels(window.shape[1])
                handle.setsampwidth(2)
                handle.setframerate(rate)
                handle.writeframes(window.astype("<i2").tobytes())
            row = {k: recording[k] for k in recording.index if k not in RECORDING_FILE_COLUMNS}
            started = recording.get("recorded_at")
            if isinstance(started, (pd.Timestamp, datetime.datetime)) and not pd.isna(started):
                row["recorded_at"] = started + datetime.timedelta(seconds=t_s)
            row.update({
                "file_id": derived["file_id"],
                "kind": "audio",
                "recording_file_id": recording["file_id"],
                "recording": recording["name"],
                "t_s": t_s,
                "duration_s": round(len(window) / rate, 3),
                "level_dbfs": _dbfs(float(np.sqrt(np.mean(scaled ** 2)))),
                "peak_dbfs": _dbfs(float(np.max(np.abs(scaled)))),
                "path": derived["path"],
                "thumbnail": derived["thumbnail"],
                "audio_url": derived["audio_url"],
            })
            rows.append(row)

    return pd.DataFrame(rows)


def _dbfs(value):
    return round(20 * math.log10(value), 2) if value > 0 else -120.0


def _windows(path, window_seconds, max_windows_per_recording):
    """``(rate, start, samples)`` per window, where *samples* is one row per
    sample and one column per channel, decoded as it is needed."""
    with av.open(path) as container:
        stream = container.streams.audio[0]
        rate = stream.codec_context.sample_rate or 16000
        resampler = av.AudioResampler(format="s16", layout=stream.codec_context.layout, rate=rate)
        width = max(1, int(window_seconds * rate))
        pending, held, start, made = [], 0, 0, 0

        def decoded():
            for frame in container.decode(stream):
                yield from resampler.resample(frame)
            yield from resampler.resample(None)

        for out in decoded():
            block = out.to_ndarray().reshape(-1, out.layout.nb_channels)
            pending.append(block)
            held += len(block)
            while held >= width:
                joined = np.concatenate(pending)
                yield rate, start, joined[:width]
                made += 1
                if made >= max_windows_per_recording:
                    return
                rest = joined[width:]
                pending, held, start = ([rest] if len(rest) else []), len(rest), start + width
        if held:
            yield rate, start, np.concatenate(pending)
