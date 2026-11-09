"""SAM 3 through a collection's videos: the frames it looks at, the objects it
follows from frame to frame, and the overlay and tracks it writes for each video.

Track Objects calls :func:`track_objects`, with its settings and Curio's
plumbing: the model ``curio_load_model("model.curio.sam3")`` gives, whose
``path`` is the folder of SAM 3's weights, and ``curio_derived_file``, which
says where a file made from a collection's video is kept and served.
"""

import colorsys
import datetime
from dataclasses import dataclass
from fractions import Fraction

import av
import geopandas as gpd
import numpy as np
import pandas as pd
import torch
from PIL import Image, ImageDraw
from transformers import Sam3VideoModel, Sam3VideoProcessor

__all__ = ["track_objects"]

#: A video's own columns that describe its file, which the overlay's replace.
PER_FILE = frozenset({
    "file_id", "relpath", "name", "ext", "kind", "bytes", "mtime", "duration_s", "fps", "codec",
    "width", "height", "path", "thumbnail", "image_url", "audio_url", "probe_error", "geometry",
})
#: The columns of a video's tracks, one row per object, after the video's own.
TRACK_COLUMNS = ["object_id", "label", "start_s", "end_s", "frames", "largest_share", "mean_score"]
#: The tag of the overlay and the tracks a video gets.
TAG = "sam3"


@dataclass(frozen=True)
class _Run:
    """SAM 3, loaded once, and what one call asked of it."""

    processor: object
    sam3: object
    device: str
    dtype: object
    labels: list
    colors: dict
    every_seconds: float
    from_seconds: float
    width: int
    derived_file: object


def track_objects(media, model, derived_file, *, labels, every_seconds=0.5, from_seconds=0, to_seconds=None,
                  max_seconds=300, width=960):
    """Follow what *labels* name, such as curb ramp or traffic cone, through
    each video of a collection with SAM 3: each video comes back as its
    overlay, its frames with each object's mask and id drawn, which Simple View
    plays, with a count of the objects of each label and the path of a table of
    one row per object.

    *media* is a collection's rows, as ``curio_load_collection`` returns them;
    rows that are not videos are left out. *model* is SAM 3 as
    ``curio_load_model("model.curio.sam3")`` gives it, and *derived_file* is
    ``curio_derived_file``. SAM 3 looks at one frame every *every_seconds*,
    from *from_seconds* to *to_seconds* (None: the video's end), read at most
    *width* wide, and follows each object it finds from frame to frame under
    one id. It keeps every frame it looked at until the video's end, so a part
    longer than *max_seconds* stops the call before SAM 3 loads, as do empty
    *labels* and a video not on this machine.

    Each row keeps the video's own columns, its overlay's (``file_id``,
    ``path``, ``thumbnail``, ``image_url``, ``duration_s``, ``fps``, ``width``,
    ``height``), and adds ``video_file_id``, ``t_s`` (where the overlay starts
    in the video), a ``<label>_objects`` count for each label, spaces written
    as ``_``, and ``tracks``, the path of the video's tracks: one row per
    object, with ``video_file_id``, ``video``, ``object_id``, ``label``,
    ``start_s`` and ``end_s`` (in seconds from the video's start), ``frames``,
    ``largest_share`` and ``mean_score``.
    """
    if not labels:
        raise ValueError("LABELS is empty: name at least one thing to look for")
    videos = [video for _, video in media[media["kind"] == "video"].iterrows()]
    ends = [_part_end(video, from_seconds, to_seconds, max_seconds) for video in videos]
    rows = []
    if videos:
        device, dtype = _device()
        run = _Run(
            processor=Sam3VideoProcessor.from_pretrained(model.path, local_files_only=True),
            sam3=Sam3VideoModel.from_pretrained(model.path, local_files_only=True, dtype=dtype).to(device).eval(),
            device=device, dtype=dtype, labels=list(labels), colors=_colors(labels),
            every_seconds=every_seconds, from_seconds=from_seconds, width=width, derived_file=derived_file,
        )
        rows = [_track(run, video, end) for video, end in zip(videos, ends)]
    result = pd.DataFrame(rows)
    if isinstance(media, gpd.GeoDataFrame) and rows:
        geometries = [video["geometry"] if "geometry" in video.index else None for video in videos]
        result = gpd.GeoDataFrame(result, geometry=geometries, crs=media.crs)
    return result


def _device():
    """``(device, dtype)``: CUDA in bfloat16, else Apple's MPS, else the CPU, in float32."""
    if torch.cuda.is_available():
        return "cuda", torch.bfloat16
    if torch.backends.mps.is_available():
        return "mps", torch.float32
    return "cpu", torch.float32


def _colors(labels):
    """Each label's color, spread around the hue circle."""
    return {
        label: tuple(int(255 * c) for c in colorsys.hsv_to_rgb(index / len(labels), 0.85, 1.0))
        for index, label in enumerate(labels)
    }


def _length_of(container, stream):
    """The video's length in seconds, or None when its file does not say."""
    if stream.duration is not None:
        return float(stream.duration * stream.time_base)
    if container.duration is not None:
        return container.duration / 1_000_000
    return None


def _part_end(video, from_seconds, to_seconds, max_seconds):
    """Where the part of *video* to track ends, in seconds, once it is checked
    with no frame read: the file is on this machine, its end is known, and the
    part fits one run."""
    if not isinstance(video["path"], str) or not video["path"]:
        raise ValueError(f"{video['relpath']} is not on this machine yet; cache the collection's files first")
    end = to_seconds
    if end is None:
        with av.open(video["path"]) as container:
            end = _length_of(container, container.streams.video[0])
    if end is None:
        raise ValueError(f"{video['relpath']} does not say how long it is: set TO_SECONDS to where to stop")
    if end - from_seconds > max_seconds:
        raise ValueError(
            f"{video['relpath']}: Track Objects takes {max_seconds} s of video in one run; "
            f"set FROM_SECONDS and TO_SECONDS to the part to track, such as 0 and {max_seconds}"
        )
    return end


def _sample(run, video, end):
    """The frames SAM 3 looks at, read in order up to *end*, and their times in seconds."""
    frames, times = [], []
    with av.open(video["path"]) as container:
        stream = container.streams.video[0]
        # Every frame up to *end* is decoded, whatever the frames looked at:
        # FFmpeg decodes several at once with frame threading, about five
        # times faster than with its default, slice threading, at 1080p.
        stream.thread_type = "AUTO"
        width = 2 * (min(run.width, stream.codec_context.width) // 2)
        height = 2 * round(stream.codec_context.height * width / stream.codec_context.width / 2)
        container.seek(int(run.from_seconds / stream.time_base), stream=stream, backward=True)
        wanted = run.from_seconds
        for frame in container.decode(stream):
            if frame.time is None or frame.time < wanted - 1e-3:
                continue
            if frame.time > end:
                break
            frames.append(frame.to_image(width=width, height=height))
            times.append(round(float(frame.time), 3))
            steps = int((frame.time - run.from_seconds) / run.every_seconds + 1e-6) + 1
            wanted = run.from_seconds + steps * run.every_seconds
    if not frames:
        raise ValueError(f"{video['relpath']} has no frames from {run.from_seconds} to {end} s")
    return frames, times


def _draw(run, image, found, label_of):
    """The frame with each object's mask, box, label and id drawn on it."""
    pixels = np.asarray(image, dtype=np.float32)
    for object_id, mask in zip(found["object_ids"].tolist(), found["masks"].cpu().numpy()):
        pixels[mask] = pixels[mask] * 0.45 + np.array(run.colors[label_of[object_id]]) * 0.55
    picture = Image.fromarray(pixels.astype(np.uint8))
    pen = ImageDraw.Draw(picture)
    for object_id, box in zip(found["object_ids"].tolist(), found["boxes"].tolist()):
        color = run.colors[label_of[object_id]]
        pen.rectangle(box, outline=color, width=2)
        pen.text((box[0] + 3, box[1] + 2), f"{label_of[object_id]} {object_id}", fill=color)
    return picture


def _track(run, video, end):
    """Run SAM 3 through one video: its overlay's row, with its tracks file."""
    frames, times = _sample(run, video, end)
    session = run.processor.init_video_session(
        video=frames, inference_device=run.device, processing_device=run.device,
        video_storage_device=run.device, dtype=run.dtype,
    )
    run.processor.add_text_prompt(session, run.labels)
    start_ms = round(run.from_seconds * 1000)
    overlay = run.derived_file(video["dataset_id"], video["file_id"], start_ms, "mp4", tag=TAG)
    tracks_file = run.derived_file(video["dataset_id"], video["file_id"], start_ms, "parquet", tag=TAG)
    width, height = frames[0].size
    tracks, label_of = {}, {}
    # H.264 in yuv420p, its index first: what browsers play as the file arrives.
    with av.open(overlay["path"], "w", options={"movflags": "+faststart"}) as out:
        rate = 1 / Fraction(run.every_seconds).limit_denominator(1000)
        drawn = out.add_stream("h264", rate=rate)
        drawn.width, drawn.height, drawn.pix_fmt = width, height, "yuv420p"
        drawn.codec_context.time_base = 1 / rate
        # SAM 3 holds each frame back until it has seen a few after it, so it
        # can drop an object that was never really there.
        with torch.inference_mode():
            for output in run.sam3.propagate_in_video_iterator(inference_session=session):
                found = run.processor.postprocess_outputs(session, output)
                t_s = times[output.frame_idx]
                for label, ids in found["prompt_to_obj_ids"].items():
                    label_of.update({object_id: label for object_id in ids})
                shares = found["masks"].flatten(1).sum(1).cpu().numpy() / (width * height)
                for object_id, score, share in zip(found["object_ids"].tolist(), found["scores"].tolist(), shares):
                    seen = tracks.setdefault(object_id, {
                        "object_id": object_id, "label": label_of[object_id], "start_s": t_s,
                        "frames": 0, "largest_share": 0.0, "scores": [],
                    })
                    seen["end_s"] = t_s
                    seen["frames"] += 1
                    seen["largest_share"] = max(seen["largest_share"], round(float(share), 4))
                    seen["scores"].append(float(score))
                picture = av.VideoFrame.from_image(_draw(run, frames[output.frame_idx], found, label_of))
                picture.pts, picture.time_base = output.frame_idx, 1 / rate
                for packet in drawn.encode(picture):
                    out.mux(packet)
        for packet in drawn.encode():
            out.mux(packet)
    table = pd.DataFrame([
        {**{k: v for k, v in seen.items() if k != "scores"}, "mean_score": round(float(np.mean(seen["scores"])), 4)}
        for seen in tracks.values()
    ], columns=TRACK_COLUMNS)
    table.insert(0, "video_file_id", video["file_id"])
    table.insert(1, "video", video["name"])
    table.to_parquet(tracks_file["path"], index=False)
    row = {k: video[k] for k in video.index if k not in PER_FILE}
    taken = video.get("taken_at")
    if isinstance(taken, (pd.Timestamp, datetime.datetime)) and not pd.isna(taken):
        row["taken_at"] = taken + datetime.timedelta(seconds=times[0])
    row.update(overlay)
    row.update({
        "kind": "video", "video_file_id": video["file_id"], "name": video["name"], "t_s": times[0],
        "duration_s": float(len(frames) * run.every_seconds), "width": width, "height": height, "fps": float(rate),
        "tracks": tracks_file["path"],
    })
    for label in run.labels:
        row[label.replace(" ", "_") + "_objects"] = int((table["label"] == label).sum())
    return row
