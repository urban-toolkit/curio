"""Sample Video Frames.

Input: a collection's rows, as Data Loading's `curio_load_collection(...)` returns
them. Every video row becomes one row per sampled frame, and each frame is a
JPEG written beside the collection's other derived files. A frame row has the
columns of an image row (`path`, `thumbnail`, `image_url`, `width`, `height`),
so Simple View shows the frames and any node that reads images reads them. It
also keeps the video's own columns: its fields, its position, and its time,
moved forward by the frame's offset. `t_s` is the frame's time in the video,
and `frame` its number there.

Settings:
- EVERY_SECONDS: the gap between two sampled frames.
- MAX_FRAMES_PER_VIDEO: frames kept from one video at most.
"""

import datetime

import av
import geopandas as gpd
import pandas as pd

EVERY_SECONDS = 2.0
MAX_FRAMES_PER_VIDEO = 300

#: A video's own columns that describe the file, not what a frame inherits.
PER_FILE = {
    "file_id", "relpath", "name", "ext", "kind", "bytes", "mtime", "duration_s",
    "fps", "codec", "width", "height", "path", "thumbnail", "image_url",
    "audio_url", "probe_error", "geometry",
}


def length_of(container, stream):
    """The video's length in seconds, or None when its file does not say."""
    if stream.duration is not None:
        return float(stream.duration * stream.time_base)
    if container.duration is not None:
        return container.duration / 1_000_000
    return None


def by_seeking(container, stream, length):
    """The frame showing at each sample time, reached by seeking."""
    targets = [0.0]
    while len(targets) < MAX_FRAMES_PER_VIDEO and targets[-1] + EVERY_SECONDS < length:
        targets.append(round(targets[-1] + EVERY_SECONDS, 6))
    for target in targets:
        container.seek(int(target / stream.time_base), stream=stream, backward=True)
        frame = None
        for candidate in container.decode(stream):
            frame = candidate
            if candidate.time is None or candidate.time >= target - 1e-3:
                break
        if frame is not None:
            yield (frame.time if frame.time is not None else target), frame


def by_reading(container, stream, rate):
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
            wanted = at + EVERY_SECONDS


media = arg
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
        length = length_of(container, stream)
        sampled = by_seeking(container, stream, length) if length is not None else by_reading(container, stream, rate)
        last = None
        for at, frame in sampled:
            t_s = round(float(at), 3)
            if t_s == last:
                continue  # two sample times that land on one frame
            last = t_s
            number = int(round(t_s * rate)) if rate else len([r for r in rows if r["video_file_id"] == video["file_id"]])
            image = frame.to_image()
            derived = curio_derived_file(video["dataset_id"], video["file_id"], round(t_s * 1000))
            image.save(derived["path"], "JPEG", quality=85)
            row = {k: video[k] for k in video.index if k not in PER_FILE}
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
            if len([r for r in rows if r["video_file_id"] == video["file_id"]]) >= MAX_FRAMES_PER_VIDEO:
                break

frames = pd.DataFrame(rows)
if isinstance(media, gpd.GeoDataFrame) and rows:
    frames = gpd.GeoDataFrame(frames, geometry=geometries, crs=media.crs)
return frames
