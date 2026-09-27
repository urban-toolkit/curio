"""Sample Video Frames.

Input: a collection's rows, as Data Loading's `curio_collection(...)` returns
them. Every video row becomes one row per sampled frame, and each frame is a
JPEG written beside the collection's other derived files. A frame row has the
columns of an image row (`path`, `thumbnail`, `image_url`, `width`, `height`),
so Simple View shows the frames and any node that reads images reads them. It
also keeps the video's own columns: its fields, its position, and its time,
moved forward by the frame's offset.

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
        if stream.duration is not None:
            duration = float(stream.duration * stream.time_base)
        else:
            duration = (container.duration or 0) / 1_000_000
        times = []
        t = 0.0
        while t <= duration and len(times) < MAX_FRAMES_PER_VIDEO:
            times.append(round(t, 3))
            t += EVERY_SECONDS
        for index, target in enumerate(times):
            container.seek(int(target / stream.time_base), stream=stream, backward=True)
            frame = None
            for candidate in container.decode(stream):
                frame = candidate
                if candidate.time is None or candidate.time >= target - 1e-3:
                    break
            if frame is None:
                continue
            image = frame.to_image()
            derived = curio_derived_file(video["dataset_id"], video["file_id"], round(target * 1000))
            image.save(derived["path"], "JPEG", quality=85)
            row = {k: video[k] for k in video.index if k not in PER_FILE}
            taken = video.get("taken_at")
            if isinstance(taken, (pd.Timestamp, datetime.datetime)) and not pd.isna(taken):
                row["taken_at"] = taken + datetime.timedelta(seconds=target)
            row.update({
                "file_id": derived["file_id"],
                "kind": "frame",
                "video_file_id": video["file_id"],
                "sequence": video["name"],
                "frame": index,
                "t_s": target,
                "width": image.width,
                "height": image.height,
                "path": derived["path"],
                "thumbnail": derived["thumbnail"],
                "image_url": derived["image_url"],
            })
            rows.append(row)
            geometries.append(video["geometry"] if "geometry" in video.index else None)

frames = pd.DataFrame(rows)
if isinstance(media, gpd.GeoDataFrame) and rows:
    frames = gpd.GeoDataFrame(frames, geometry=geometries, crs=media.crs)
return frames
