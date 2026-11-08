"""Track Objects.

Input: a collection's rows, as Data Loading's `curio_load_collection(...)` returns
them. SAM 3 looks for what LABELS name in every video, one frame every
EVERY_SECONDS, and follows each object it finds from frame to frame under one id.

Every video row comes back as its overlay: a video of the frames SAM 3 looked at,
each object's mask drawn in its label's color with its id, which Simple View
plays, a frame every EVERY_SECONDS. The row keeps the video's own columns and adds:
- `t_s`: where the overlay starts in the video, so a time in the overlay is
  `t_s` plus that time in the video;
- `<label>_objects`: how many objects of each label SAM 3 followed;
- `tracks`: a Parquet file with one row per object (object_id, label, start_s,
  end_s, frames, largest_share, mean_score), which `pd.read_parquet` reads.

Settings:
- LABELS: what to look for, in plain words; SAM 3 takes any short noun phrase.
- EVERY_SECONDS: the gap between two frames SAM 3 looks at.
- FROM_SECONDS, TO_SECONDS: the part of each video to track, in seconds from
  its start; None is its end.
- MAX_SECONDS: the most video one run takes: SAM 3 keeps every frame it looked
  at until the video's end.
- WIDTH: the widest frames are read and drawn at.
"""

import colorsys
import datetime
from fractions import Fraction

import av
import geopandas as gpd
import numpy as np
import pandas as pd
import torch
from PIL import Image, ImageDraw
from transformers import Sam3VideoModel, Sam3VideoProcessor

LABELS = [
    "curb ramp", "curb cut", "tactile paving", "bollard", "pole",
    "construction barrier", "traffic cone", "person",
]
EVERY_SECONDS = 0.5
FROM_SECONDS = 0
TO_SECONDS = None
MAX_SECONDS = 300
WIDTH = 960

if not LABELS:
    raise ValueError("LABELS is empty: name at least one thing to look for")

#: A video's own columns that describe its file, which the overlay's replace.
PER_FILE = {
    "file_id", "relpath", "name", "ext", "kind", "bytes", "mtime", "duration_s", "fps", "codec",
    "width", "height", "path", "thumbnail", "image_url", "audio_url", "probe_error", "geometry",
}

COLORS = {
    label: tuple(int(255 * c) for c in colorsys.hsv_to_rgb(index / len(LABELS), 0.85, 1.0))
    for index, label in enumerate(LABELS)
}

if torch.cuda.is_available():
    device, dtype = "cuda", torch.bfloat16
elif torch.backends.mps.is_available():
    device, dtype = "mps", torch.float32
else:
    device, dtype = "cpu", torch.float32

model = curio_load_model("model.curio.sam3")
processor = Sam3VideoProcessor.from_pretrained(model.path, local_files_only=True)
sam3 = Sam3VideoModel.from_pretrained(model.path, local_files_only=True, dtype=dtype).to(device).eval()


def length_of(container, stream):
    """The video's length in seconds, or None when its file does not say."""
    if stream.duration is not None:
        return float(stream.duration * stream.time_base)
    if container.duration is not None:
        return container.duration / 1_000_000
    return None


def sample(video):
    """The frames SAM 3 looks at, read in order, and their times in seconds."""
    frames, times = [], []
    with av.open(video["path"]) as container:
        stream = container.streams.video[0]
        end = TO_SECONDS if TO_SECONDS is not None else length_of(container, stream)
        if end is None:
            raise ValueError(f"{video['relpath']} does not say how long it is: set TO_SECONDS to where to stop")
        if end - FROM_SECONDS > MAX_SECONDS:
            raise ValueError(
                f"{video['relpath']}: Track Objects takes {MAX_SECONDS} s of video in one run; "
                f"set FROM_SECONDS and TO_SECONDS to the part to track, such as 0 and {MAX_SECONDS}"
            )
        width = 2 * (min(WIDTH, stream.codec_context.width) // 2)
        height = 2 * round(stream.codec_context.height * width / stream.codec_context.width / 2)
        container.seek(int(FROM_SECONDS / stream.time_base), stream=stream, backward=True)
        wanted = FROM_SECONDS
        for frame in container.decode(stream):
            if frame.time is None or frame.time < wanted - 1e-3:
                continue
            if frame.time > end:
                break
            frames.append(frame.to_image(width=width, height=height))
            times.append(round(float(frame.time), 3))
            wanted = FROM_SECONDS + (int((frame.time - FROM_SECONDS) / EVERY_SECONDS + 1e-6) + 1) * EVERY_SECONDS
    if not frames:
        raise ValueError(f"{video['relpath']} has no frames from {FROM_SECONDS} to {end} s")
    return frames, times


def draw(image, found, label_of):
    """The frame with each object's mask, box and id drawn on it."""
    pixels = np.asarray(image, dtype=np.float32)
    for object_id, mask in zip(found["object_ids"].tolist(), found["masks"].cpu().numpy()):
        pixels[mask] = pixels[mask] * 0.45 + np.array(COLORS[label_of[object_id]]) * 0.55
    picture = Image.fromarray(pixels.astype(np.uint8))
    pen = ImageDraw.Draw(picture)
    for object_id, box in zip(found["object_ids"].tolist(), found["boxes"].tolist()):
        color = COLORS[label_of[object_id]]
        pen.rectangle(box, outline=color, width=2)
        pen.text((box[0] + 3, box[1] + 2), f"{label_of[object_id]} {object_id}", fill=color)
    return picture


def track(video):
    """Run SAM 3 through one video: its overlay's row, with its tracks file."""
    frames, times = sample(video)
    session = processor.init_video_session(
        video=frames, inference_device=device, processing_device=device,
        video_storage_device=device, dtype=dtype,
    )
    processor.add_text_prompt(session, LABELS)
    start_ms = round(FROM_SECONDS * 1000)
    overlay = curio_derived_file(video["dataset_id"], video["file_id"], start_ms, "mp4", tag="sam3")
    tracks_file = curio_derived_file(video["dataset_id"], video["file_id"], start_ms, "parquet", tag="sam3")
    width, height = frames[0].size
    tracks, label_of = {}, {}
    # H.264 in yuv420p, its index first: what browsers play as the file arrives.
    with av.open(overlay["path"], "w", options={"movflags": "+faststart"}) as out:
        rate = 1 / Fraction(EVERY_SECONDS).limit_denominator(1000)
        drawn = out.add_stream("h264", rate=rate)
        drawn.width, drawn.height, drawn.pix_fmt = width, height, "yuv420p"
        drawn.codec_context.time_base = 1 / rate
        # SAM 3 holds each frame back until it has seen a few after it, so
        # it can drop an object that was never really there.
        with torch.inference_mode():
            for output in sam3.propagate_in_video_iterator(inference_session=session):
                found = processor.postprocess_outputs(session, output)
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
                picture = av.VideoFrame.from_image(draw(frames[output.frame_idx], found, label_of))
                picture.pts, picture.time_base = output.frame_idx, 1 / rate
                for packet in drawn.encode(picture):
                    out.mux(packet)
        for packet in drawn.encode():
            out.mux(packet)
    table = pd.DataFrame([
        {**{k: v for k, v in seen.items() if k != "scores"}, "mean_score": round(float(np.mean(seen["scores"])), 4)}
        for seen in tracks.values()
    ], columns=["object_id", "label", "start_s", "end_s", "frames", "largest_share", "mean_score"])
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
        "duration_s": float(len(frames) * EVERY_SECONDS), "width": width, "height": height, "fps": float(rate),
        "tracks": tracks_file["path"],
    })
    for label in LABELS:
        row[label.replace(" ", "_") + "_objects"] = int((table["label"] == label).sum())
    return row


media = input_0
videos = media[media["kind"] == "video"]
rows, geometries = [], []
for _, video in videos.iterrows():
    if not isinstance(video["path"], str) or not video["path"]:
        raise ValueError(f"{video['relpath']} is not on this machine yet; cache the collection's files first")
    rows.append(track(video))
    geometries.append(video["geometry"] if "geometry" in video.index else None)

result = pd.DataFrame(rows)
if isinstance(media, gpd.GeoDataFrame) and rows:
    result = gpd.GeoDataFrame(result, geometry=geometries, crs=media.crs)
return result
