"""Media's steps over a collection's rows, as ``curio_load_collection`` returns
them: frames sampled from its videos (``sample_video_frames``), its
recordings split into windows with their levels (``split_audio``) and its
videos cut into blocks (``split_video``). Sample Video Frames, Split Audio and
Split Video call them with their settings. Each frame, window or block is a
file written where ``curio_derived_file``, which a node hands in, says:
beside the collection's other derived files.

Mosaic Rasters calls Rasterization's ``scout_rasters.mosaic``
(``curio.rasterization@1``, which the package names in
``dependencies.packages``).
"""

import contextlib
import datetime
import math
import os
import wave
from fractions import Fraction

import av
import geopandas as gpd
import numpy as np
import pandas as pd

#: What node code calls.
__all__ = ["sample_video_frames", "split_audio", "split_video"]

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
            sampled = _by_decoding(container, stream, rate, length, every_seconds, max_frames_per_video)
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


def _by_decoding(container, stream, rate, length, every_seconds, max_frames_per_video):
    """The first frame at or past each sample time, one every *every_seconds*
    from 0, before the video's *length* (when its file gives one) and
    *max_frames_per_video* of them at most, read in one pass from the video's
    start with frame threading. A seek to each sample time would decode from
    the key frame before it instead, so on a video whose key frames are
    seconds apart, as the SideSeeing walks' 8.3 s, each frame would be decoded
    many times over."""
    # Frame threading decodes several frames at once, about five times faster
    # than slice threading at 1080p.
    stream.thread_type = "AUTO"
    step = 0
    for index, frame in enumerate(container.decode(stream)):
        if step >= max_frames_per_video or (length is not None and step * every_seconds >= length):
            return
        at = frame.time if frame.time is not None else (index / rate if rate else None)
        if at is None:
            # Neither a time nor a rate: only the first frame can be placed.
            if index == 0:
                yield 0.0, frame
            return
        if at < step * every_seconds - 1e-3:
            continue
        yield at, frame
        # On to the first sample time this frame does not stand for.
        step = max(step + 1, math.floor((at + 1e-3) / every_seconds) + 1)


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


# ---------------------------------------------------------------------------
# Blocks of videos
# ---------------------------------------------------------------------------

#: How a block is encoded: H.264 in yuv420p, what browsers play, with x264's
#: veryfast preset at a constant quality, so a long video re-encodes within a
#: node's time.
BLOCK_OPTIONS = {"preset": "veryfast", "crf": "23"}

#: A block's time base: each of its frames plays at its own time, to the millisecond.
MILLISECOND = Fraction(1, 1000)

#: How long before a block's start a frame may come and still be its first.
EARLY_SECONDS = 1e-3

#: A cut's columns that place its block, which the block's row does not copy.
PLACING_COLUMNS = ("t_s", "end_s", "video_file_id", "geometry")

#: A block row's own columns: a cut's columns of these names, such as those of
#: a frame a cut was made from, describe another file, and its block keeps its own.
BLOCK_COLUMNS = (
    "block", "file_id", "dataset_id", "kind", "path", "thumbnail",
    "image_url", "audio_url", "duration_s", "fps", "width", "height",
)


def split_video(media, derived_file, cuts=None, *, block_seconds=60.0, width=960, max_frames=30000):
    """Every video in a collection cut into blocks, each an MP4 that Simple View
    plays, written where *derived_file* (``curio_derived_file``) says: a block
    every *block_seconds* seconds, or where the rows of *cuts* say.

    *media* is a collection's rows, as ``curio_load_collection`` returns them;
    rows that are not videos are left out. *cuts*, when given, is a table of
    blocks, one row each: ``t_s``, where the block starts, in seconds from its
    video's start; ``end_s``, where it ends, when the row has it, else where
    the next block starts or the video ends; and ``video_file_id``, the video
    it cuts, when the row has it, else every video. A video no row cuts gets
    no block. Each block is re-encoded as H.264, at most *width* wide, and has
    no sound.

    A block's row leads with ``block``, its number in its video from 1, the
    cut's own columns, such as a street's name, then ``t_s`` and ``end_s``,
    where the block starts and ends in the video, so a player linked by time
    reads the video's time. Then come the video's own columns, its
    ``taken_at`` moved forward by ``t_s``, and the block's file: ``file_id``,
    ``kind`` (``video``), ``path``, ``thumbnail``, ``image_url``,
    ``video_file_id``, ``duration_s``, ``fps``, ``width`` and ``height``. A
    cut's columns of those names, such as those of a frame it was made from,
    describe another file, and are not copied.

    One call re-encodes at most *max_frames* frames. Blocks that need more, a
    block that starts before 0 or past its video's end, blocks that overlap,
    a cut without ``t_s``, and a video not on this machine stop the call
    before any block is written; a video whose file does not say how long it
    is stops at the frame past *max_frames*, or at its end when a block starts
    past it. A call that cuts a video into the same blocks at the same width
    writes the same files again.
    """
    if isinstance(block_seconds, bool) or not isinstance(block_seconds, (int, float)) or not block_seconds > 0:
        raise ValueError("BLOCK_SECONDS is the length of a block, in seconds: a number above 0")
    if isinstance(width, bool) or not isinstance(width, int) or width < 2:
        raise ValueError("WIDTH is the widest a block is drawn, in pixels: a whole number of 2 or more")
    table = _cut_table(cuts)
    plans = []
    for _, video in media[media["kind"] == "video"].iterrows():
        if not isinstance(video["path"], str) or not video["path"]:
            raise ValueError(
                f"{video['relpath']} is not on this machine yet; cache the collection's files first"
            )
        with av.open(video["path"]) as container:
            stream = container.streams.video[0]
            length = _length_of(container, stream)
            rate = float(stream.average_rate) if stream.average_rate else None
        blocks = _blocks_of(video, table, float(block_seconds), length, rate)
        if blocks:
            plans.append((video, blocks, rate))
    if table is not None and not plans and len(media[media["kind"] == "video"]):
        raise ValueError(
            "No row of the cuts on the bottom circle cuts a video of the collection: a row's "
            "video_file_id is the file_id of a video on the top circle, and a row without one cuts every video"
        )
    counted = [_frames_in(blocks, rate) for _, blocks, rate in plans]
    needed = sum(count for count in counted if count is not None)
    if needed > max_frames:
        raise ValueError(
            f"These blocks hold about {needed} frames, and Split Video re-encodes at most {max_frames} "
            "in one run (MAX_FRAMES): cut a part of each video, with t_s and end_s on the bottom circle, "
            "or raise MAX_FRAMES"
        )
    # What a video whose blocks could not be counted before may still take.
    left = [max_frames - needed]
    rows, geometries = [], []
    for (video, blocks, _rate), count in zip(plans, counted):
        for row in _cut(video, blocks, derived_file, width, None if count is not None else left, max_frames):
            rows.append(row)
            geometries.append(video["geometry"] if "geometry" in video.index else None)
    result = pd.DataFrame(rows)
    if isinstance(media, gpd.GeoDataFrame) and rows:
        result = gpd.GeoDataFrame(result, geometry=geometries, crs=media.crs)
    return result


def _cut_table(cuts):
    """*cuts* checked as a table of blocks, or None when nothing is wired."""
    if cuts is None:
        return None
    if not isinstance(cuts, pd.DataFrame):
        raise ValueError(
            "The bottom circle takes a table of blocks, one row each, with t_s, where each starts "
            f"in seconds from its video's start; it got {type(cuts).__name__}"
        )
    if "t_s" not in cuts.columns:
        raise ValueError(
            "The cuts on the bottom circle need a t_s column: where each block starts, in seconds "
            f"from its video's start. They have {', '.join(map(str, cuts.columns)) or 'no column'}"
        )
    if not len(cuts):
        raise ValueError("The cuts on the bottom circle hold no row: wire a table of one row per block")
    for column in ("t_s", "end_s"):
        if column in cuts.columns:
            values = pd.to_numeric(cuts[column], errors="coerce")
            # t_s is every row's; end_s may be left empty on a row.
            bad = values.isna() if column == "t_s" else values.isna() & cuts[column].notna()
            if bad.any():
                raise ValueError(f"Every cut's {column} is a number of seconds from its video's start")
    return cuts


def _blocks_of(video, table, block_seconds, length, rate):
    """The blocks to cut *video* into, in order, each ``{start, end, cut,
    to_end}``: *end* is None for the last block of a video its file gives no
    length of, *cut* is the columns the block's row copies from its cut, and
    *to_end* says the block runs to the video's end (``_to_the_end``). Fixed
    blocks of such a video are made as its frames come instead (``every``)."""
    name = video["relpath"]
    if table is None:
        if length is None:
            # Cut as the frames come: each block opens the next (``_cut``).
            return [{"start": 0.0, "end": block_seconds, "cut": {}, "every": block_seconds}]
        count = max(1, math.ceil(length / block_seconds - 1e-9))
        blocks = [
            {"start": k * block_seconds, "end": min((k + 1) * block_seconds, length), "cut": {}}
            for k in range(count)
        ]
        # A tail shorter than one frame, where the video runs a moment past a
        # block's end, is the last block's, not a block of its own.
        if len(blocks) > 1 and rate and (length - blocks[-1]["start"]) * rate < 1:
            blocks.pop()
            blocks[-1]["end"] = length
        return [_to_the_end(block, length) for block in blocks]
    own = table
    if "video_file_id" in table.columns:
        own = table[table["video_file_id"].isna() | (table["video_file_id"].astype(str) == str(video["file_id"]))]
    blocks = []
    for _, cut in own.sort_values("t_s", kind="stable").iterrows():
        end = cut.get("end_s")
        blocks.append({
            "start": float(cut["t_s"]),
            "end": None if end is None or pd.isna(end) else float(end),
            "cut": {key: cut[key] for key in cut.index if key not in PLACING_COLUMNS and key not in BLOCK_COLUMNS},
        })
    for index, block in enumerate(blocks):
        start = block["start"]
        following = blocks[index + 1]["start"] if index + 1 < len(blocks) else None
        if start < 0:
            raise ValueError(f"{name}: a block starts at {start:g} s, and t_s counts seconds from the video's start")
        if length is not None and start >= length - EARLY_SECONDS:
            raise ValueError(f"{name} lasts {length:.3f} s, and a block starts at {start:g} s")
        if following is not None and following - start < EARLY_SECONDS:
            raise ValueError(f"{name}: two blocks start at {start:g} s")
        if block["end"] is None:
            block["end"] = following if following is not None else length
        elif following is not None and block["end"] > following + EARLY_SECONDS:
            raise ValueError(
                f"{name}: the block from {start:g} to {block['end']:g} s overlaps the one from {following:g} s"
            )
        if block["end"] is not None:
            if length is not None:
                block["end"] = min(block["end"], length)
            if block["end"] <= start:
                raise ValueError(f"{name}: the block from {start:g} s ends at {block['end']:g} s, before it starts")
            if rate and (block["end"] - start) * rate < 1 - 1e-6:
                raise ValueError(
                    f"{name}: the block from {start:g} to {block['end']:g} s is shorter than one of its frames"
                )
    return [_to_the_end(block, length) for block in blocks]


def _to_the_end(block, length):
    """*block*, marked ``to_end`` when it runs to its video's end: it takes
    every frame from its start on, whatever length the file gives."""
    end = block["end"]
    block["to_end"] = end is None or (length is not None and end >= length - EARLY_SECONDS)
    return block


def _frames_in(blocks, rate):
    """About how many frames *blocks* hold, or None when that cannot be told
    before the video is read."""
    if not rate or any(block["end"] is None or block.get("every") for block in blocks):
        return None
    return sum(math.ceil((block["end"] - block["start"]) * rate - 1e-6) for block in blocks)


class _Block:
    """One block's MP4 as it is written: H.264 in yuv420p, its index first,
    each frame playing at its own time from the block's first frame."""

    def __init__(self, derived, width, height, rate, first):
        self.derived, self.first, self.last, self.frames = derived, first, first, 0
        self.gap = max(1, round(1000 / float(rate)))
        self.out = av.open(derived["path"], "w", options={"movflags": "+faststart"})
        self.stream = self.out.add_stream("h264", rate=rate, options=dict(BLOCK_OPTIONS))
        self.stream.width, self.stream.height, self.stream.pix_fmt = width, height, "yuv420p"
        self.stream.codec_context.time_base = MILLISECOND
        # No B-frames: each frame is written in the order it plays.
        self.stream.codec_context.max_b_frames = 0

    def add(self, frame, at):
        picture = frame.reformat(width=self.stream.width, height=self.stream.height, format="yuv420p")
        picture.pts, picture.time_base = round(1000 * (at - self.first)), MILLISECOND
        self._mux(self.stream.encode(picture))
        self.last, self.frames = at, self.frames + 1

    def close(self):
        self._mux(self.stream.encode())
        self.out.close()

    def discard(self):
        with contextlib.suppress(Exception):
            self.out.close()
        with contextlib.suppress(FileNotFoundError):
            os.remove(self.derived["path"])

    def _mux(self, packets):
        for packet in packets:
            packet.duration = self.gap
            self.out.mux(packet)


def _cut(video, blocks, derived_file, width, left, max_frames):
    """Re-encode *video*'s *blocks*, reading it once from the first: each
    block's row. *left*, for a video whose blocks could not be counted before,
    holds how many frames the call may still re-encode."""
    rows, opened = [], set()
    with av.open(video["path"]) as container:
        stream = container.streams.video[0]
        # Frame threading decodes several frames at once, about five times
        # faster than slice threading at 1080p.
        stream.thread_type = "AUTO"
        context = stream.codec_context
        out_width = 2 * (min(width, context.width) // 2)
        out_height = 2 * round(context.height * out_width / context.width / 2)
        rate = stream.average_rate or Fraction(30)
        if blocks[0]["start"] > 0:
            container.seek(int(blocks[0]["start"] / stream.time_base), stream=stream, backward=True)
        index, block, last = 0, None, None
        for frame in container.decode(stream):
            at = float(frame.time) if frame.time is not None else (
                last + 1 / float(rate) if last is not None else blocks[0]["start"]
            )
            while (index < len(blocks) and not blocks[index].get("to_end")
                   and at >= blocks[index]["end"] - EARLY_SECONDS):
                if block is not None:
                    rows.append(_finished(block, video, blocks[index], index + 1))
                    block = None
                index += 1
                if index == len(blocks) and blocks[-1].get("every"):
                    every, end = blocks[-1]["every"], blocks[-1]["end"]
                    blocks.append({"start": end, "end": end + every, "cut": {}, "every": every})
            if index == len(blocks):
                break
            last = at
            if at < blocks[index]["start"] - EARLY_SECONDS:
                continue  # before the block: a gap between two, or where the seek went back to
            if block is None:
                derived = derived_file(
                    video["dataset_id"], video["file_id"], round(blocks[index]["start"] * 1000), "mp4",
                    tag=_block_tag(blocks[index]["end"], width),
                )
                block = _Block(derived, out_width, out_height, rate, at)
                opened.add(index)
            if left is not None:
                if left[0] <= 0:
                    block.discard()
                    raise ValueError(
                        f"{video['relpath']}: its blocks hold more than the {max_frames} frames Split Video "
                        "re-encodes in one run (MAX_FRAMES): cut a part of it, with t_s and end_s on the "
                        "bottom circle, or raise MAX_FRAMES"
                    )
                left[0] -= 1
            block.add(frame, at)
        if block is not None:
            rows.append(_finished(block, video, blocks[index], index + 1))
    missing = [b for i, b in enumerate(blocks) if i not in opened]
    if missing:
        raise ValueError(
            f"{video['relpath']} has no frame from {missing[0]['start']:g} s on, where a block starts"
            + (f"; its last frame is at {last:.3f} s" if last is not None else "")
        )
    return rows


def _block_tag(end, width):
    """The tag of a block's file, which its name holds besides where it starts:
    where the block ends and how wide it is drawn, so blocks that differ keep
    files of their own."""
    return f"to{round(end * 1000)}w{int(width)}" if end is not None else f"toendw{int(width)}"


def _finished(block, video, planned, number):
    """The row of *block*, number *number* of *video*, once its file is closed."""
    block.close()
    duration_s = round((round(1000 * (block.last - block.first)) + block.gap) / 1000, 3)
    t_s = round(block.first, 3)
    row = {"block": number, **planned["cut"], "t_s": t_s, "end_s": round(t_s + duration_s, 3)}
    for key in video.index:
        if key not in VIDEO_FILE_COLUMNS and key not in row:
            row[key] = video[key]
    taken = video.get("taken_at")
    if isinstance(taken, (pd.Timestamp, datetime.datetime)) and not pd.isna(taken):
        row["taken_at"] = taken + datetime.timedelta(seconds=t_s)
    row.update(block.derived)
    row.setdefault("name", video["name"])
    row.update({
        "video_file_id": video["file_id"],
        "duration_s": duration_s,
        "fps": round(block.frames / duration_s, 3),
        "width": block.stream.width,
        "height": block.stream.height,
    })
    return row
