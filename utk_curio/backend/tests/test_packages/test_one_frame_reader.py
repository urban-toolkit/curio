"""Media's ``read_video_frames`` reads the frames main's three reads read.

Before it, Sample Video Frames read a video with Media's ``_by_decoding``,
Split Video with the decode in its ``_cut``, and Track Objects with SAM 3's
``_sample``. Each is kept below as main had it (17eeb08851). Every case their
tests pin, with a few more (frames far apart, frames a moment before a step,
a part past a key frame, a narrower or odd width), runs through it and
through what reads now, compared frame for frame: each frame's time, and its
pixels as the node hands them on (Sample Video Frames' JPEG and row, the
frame Split Video re-encodes, the image SAM 3 looks at).

One read changes: a stream whose frames carry no time, such as a raw H.264
file, which main's ``_sample`` stopped on at its seek. Track Objects now
reads its frames where Sample Video Frames read them.

av, numpy and pandas are imported inside the tests, and so are Media's and
SAM 3's modules, staged as a run of their nodes stages them, so a checkout
without them fails each test on its own.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import math
import tempfile
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[4]
MEDIA = REPO / "packages" / "curio.media@1"
#: How long before a time a frame may come and still be read for it, in
#: main's three reads.
EARLY_SECONDS = 1e-3


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Main's three reads, as 17eeb08851 had them
# ---------------------------------------------------------------------------

def _main_length_of(container, stream):
    """The video's length in seconds, or None when its file does not say."""
    if stream.duration is not None:
        return float(stream.duration * stream.time_base)
    if container.duration is not None:
        return container.duration / 1_000_000
    return None


def _main_by_decoding(container, stream, rate, length, every_seconds, max_frames_per_video):
    """Media's ``_by_decoding``: the first frame at or past each sample time."""
    stream.thread_type = "AUTO"
    step = 0
    for index, frame in enumerate(container.decode(stream)):
        if step >= max_frames_per_video or (length is not None and step * every_seconds >= length):
            return
        at = frame.time if frame.time is not None else (index / rate if rate else None)
        if at is None:
            if index == 0:
                yield 0.0, frame
            return
        if at < step * every_seconds - 1e-3:
            continue
        yield at, frame
        step = max(step + 1, math.floor((at + 1e-3) / every_seconds) + 1)


def _main_sampled(path: str, folder: Path, every_seconds, max_frames_per_video) -> list:
    """What main's Sample Video Frames made of the video at *path*: each
    frame's ``t_s``, ``frame``, ``width`` and ``height``, and its JPEG's
    digest, written into *folder*."""
    import av

    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    with av.open(path) as container:
        stream = container.streams.video[0]
        rate = float(stream.average_rate) if stream.average_rate else None
        length = _main_length_of(container, stream)
        last = None
        for at, frame in _main_by_decoding(container, stream, rate, length, every_seconds, max_frames_per_video):
            t_s = round(float(at), 3)
            if t_s == last:
                continue
            last = t_s
            number = int(round(t_s * rate)) if rate else len(rows)
            image = frame.to_image()
            written = folder / f"{round(t_s * 1000)}.jpg"
            image.save(written, "JPEG", quality=85)
            rows.append((t_s, number, image.width, image.height, _digest(written.read_bytes())))
            if len(rows) >= max_frames_per_video:
                break
    return rows


def _main_cut_frames(path: str, start: float, width: int) -> list:
    """The frames main's Split Video re-encoded from *start* on, read as its
    ``_cut`` read them: each one's time, to the microsecond, and its pixels
    as it went into a block, in yuv420p at most *width* wide."""
    import av

    frames = []
    with av.open(path) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        context = stream.codec_context
        out_width = 2 * (min(width, context.width) // 2)
        out_height = 2 * round(context.height * out_width / context.width / 2)
        rate = stream.average_rate or Fraction(30)
        if start > 0:
            container.seek(int(start / stream.time_base), stream=stream, backward=True)
        last = None
        for frame in container.decode(stream):
            at = float(frame.time) if frame.time is not None else (
                last + 1 / float(rate) if last is not None else start
            )
            last = at
            if at < start - EARLY_SECONDS:
                continue
            picture = frame.reformat(width=out_width, height=out_height, format="yuv420p")
            frames.append((round(at, 6), _digest(picture.to_ndarray().tobytes())))
    return frames


def _main_steps(from_seconds, end, every_seconds):
    """SAM 3's ``_steps``."""
    if end > from_seconds:
        count = math.ceil((end - from_seconds) / every_seconds - 1e-9)
        return count, from_seconds + count * every_seconds - EARLY_SECONDS
    return int(end == from_seconds), float("inf")


def _main_sample(run, video, end):
    """SAM 3's ``_sample``: the frames SAM 3 looked at and their times."""
    import av

    frames, times = [], []
    with av.open(video["path"]) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        width = 2 * (min(run.width, stream.codec_context.width) // 2)
        height = 2 * round(stream.codec_context.height * width / stream.codec_context.width / 2)
        container.seek(int(run.from_seconds / stream.time_base), stream=stream, backward=True)
        count, stop = _main_steps(run.from_seconds, end, run.every_seconds)
        steps, wanted = 0, run.from_seconds
        for frame in container.decode(stream):
            if steps >= count:
                break
            if frame.time is None or frame.time < wanted - EARLY_SECONDS:
                continue
            if frame.time >= stop:
                break
            frames.append(frame.to_image(width=width, height=height))
            times.append(round(float(frame.time), 3))
            steps = max(steps + 1, int((frame.time - run.from_seconds + EARLY_SECONDS) / run.every_seconds) + 1)
            wanted = run.from_seconds + steps * run.every_seconds
    if not frames:
        raise ValueError(f"{video['relpath']} has no frames from {run.from_seconds} to {end} s")
    return frames, times


# ---------------------------------------------------------------------------
# The clips
# ---------------------------------------------------------------------------

def _picture(index: int, width: int, height: int):
    """Frame *index* of a clip: colors that change across it and from frame to frame."""
    import numpy as np

    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :, 0] = (np.arange(width)[None, :] * 7 + index * 13) % 256
    image[:, :, 1] = (np.arange(height)[:, None] * 5 + index * 3) % 256
    image[:, :, 2] = (index * 29) % 256
    return image


def _steady(path: Path, seconds: float, rate, size: tuple[int, int], codec: str = "mpeg4", options=None) -> None:
    """A clip *seconds* long at *rate* frames a second."""
    import av

    width, height = size
    with av.open(str(path), "w") as out:
        stream = out.add_stream(codec, rate=rate, options=options or {})
        stream.width, stream.height, stream.pix_fmt = width, height, "yuv420p"
        for index in range(round(seconds * rate)):
            for packet in stream.encode(av.VideoFrame.from_ndarray(_picture(index, width, height), format="rgb24")):
                out.mux(packet)
        for packet in stream.encode():
            out.mux(packet)


def _at_times(path: Path, times: list[float], size: tuple[int, int] = (64, 48)) -> None:
    """An H.264 clip whose frames come at *times*, in seconds."""
    import av

    width, height = size
    base = Fraction(1, 10000)
    with av.open(str(path), "w") as out:
        stream = out.add_stream("h264", rate=30, options={"bf": "0"})
        stream.width, stream.height, stream.pix_fmt = width, height, "yuv420p"
        stream.codec_context.time_base = base
        stream.time_base = base
        for index, t in enumerate(times):
            frame = av.VideoFrame.from_ndarray(_picture(index, width, height), format="rgb24")
            frame.pts, frame.time_base = round(t * 10000), base
            for packet in stream.encode(frame):
                out.mux(packet)
        for packet in stream.encode():
            out.mux(packet)


def _raw(path: Path, fmt: str, codec: str, frames: int, rate: int, size: tuple[int, int], pix_fmt: str) -> None:
    """A stream with no container: raw MJPEG, whose file gives no length, or
    raw H.264, whose frames carry no time either."""
    import av

    width, height = size
    out = av.open(str(path), "w", format=fmt)
    stream = out.add_stream(codec, rate=rate)
    stream.width, stream.height, stream.pix_fmt = width, height, pix_fmt
    for index in range(frames):
        for packet in stream.encode(av.VideoFrame.from_ndarray(_picture(index, width, height), format="rgb24")):
            out.mux(packet)
    for packet in stream.encode():
        out.mux(packet)
    out.close()


#: Each clip, made as its name says.
CLIPS = {
    # Sample Video Frames' tests: the survey's one second, the walks' seven, raw MJPEG.
    "survey.mp4": lambda path: _steady(path, 1.0, 10, (64, 48)),
    "walks.mp4": lambda path: _steady(path, 7.0, 10, (96, 64)),
    "raw.mjpeg": lambda path: _raw(path, "mjpeg", "mjpeg", 25, 25, (32, 24), "yuvj420p"),
    # Track Objects' tests: the 4 fps clip, the walk's rate, the whole walk, longer clips.
    "corner.mp4": lambda path: _steady(path, 2.0, 4, (96, 64)),
    "walk.mp4": lambda path: _steady(path, 33.0, Fraction(30033, 1000), (32, 32)),
    "whole.mp4": lambda path: _steady(path, 864.3, 10, (32, 32)),
    "thirty.mp4": lambda path: _steady(path, 30.0, 4, (96, 64)),
    "eight.mp4": lambda path: _steady(path, 8.0, 4, (96, 64)),
    # Wider than 960, and odd sizes, which a width draws in even pixels.
    "wide.mp4": lambda path: _steady(path, 2.0, 10, (1280, 720)),
    "odd.mp4": lambda path: _steady(path, 1.0, 10, (101, 57)),
    # Key frames 2 s apart, with B-frames: a read from past one seeks back to it.
    "keys.mp4": lambda path: _steady(path, 10.0, 30, (64, 48), codec="h264", options={"g": "60", "bf": "2"}),
    # Frames far apart, and frames a moment before a step.
    "sparse.mp4": lambda path: _at_times(path, [0, 0.25, 0.5, 3.0, 3.25, 3.5, 3.9985, 4.0, 6.0]),
    "edge.mp4": lambda path: _at_times(path, [k / 10 for k in range(20)] + [1.9991, 2.4991, 2.5]),
    "raw.h264": lambda path: _raw(path, "h264", "h264", 30, 10, (32, 24), "yuv420p"),
}


@pytest.fixture(scope="module")
def clips(tmp_path_factory) -> dict[str, str]:
    """Each clip's path, made once for the module."""
    folder = tmp_path_factory.mktemp("clips")
    for name, make in CLIPS.items():
        make(folder / name)
    return {name: str(folder / name) for name in CLIPS}


@contextlib.contextmanager
def _media(tmp_path: Path):
    """Media's module, importable as a run of a Media node imports it."""
    from utk_curio.sandbox.util.package_modules import importable
    from utk_curio.sandbox.util.staging import stage_package_modules

    run = Path(tempfile.mkdtemp(prefix="run-", dir=tmp_path))
    staged = stage_package_modules([{"root": str(MEDIA / "sources"), "names": ["media_collections"]}], str(run))
    with importable(str(run / staged["root"]), staged["names"]):
        yield importlib.import_module("media_collections")


def _outcome(call):
    """What *call* gives, or the error it raises, as its type and message."""
    try:
        return call()
    except Exception as exc:  # noqa: BLE001 - both reads' failures are compared too
        return f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# Frame for frame
# ---------------------------------------------------------------------------

#: Sample Video Frames' settings on each clip: EVERY_SECONDS and MAX_FRAMES_PER_VIDEO.
SAMPLED = [
    ("survey.mp4", 0.5, 300), ("walks.mp4", 0.5, 300), ("raw.mjpeg", 0.5, 300), ("walk.mp4", 0.5, 300),
    ("walk.mp4", 2.0, 300), ("whole.mp4", 2.0, 450), ("whole.mp4", 2.0, 300), ("corner.mp4", 0.1, 3),
    ("corner.mp4", 0.1, 300), ("sparse.mp4", 0.5, 3), ("sparse.mp4", 0.5, 300), ("sparse.mp4", 1.0, 300),
    ("edge.mp4", 0.5, 300), ("edge.mp4", 0.25, 300), ("keys.mp4", 0.7, 300), ("wide.mp4", 0.3, 300),
    ("odd.mp4", 0.3, 300), ("raw.h264", 0.5, 300), ("corner.mp4", 0.5, 0),
]


def test_sample_video_frames_makes_the_rows_and_jpegs_main_made(clips, tmp_path):
    """Each clip at each setting gives the rows main gave, frame for frame:
    the same times and frame numbers, sizes and JPEG bytes."""
    import pandas as pd

    differ = []
    with _media(tmp_path) as media:
        for index, (name, every, most) in enumerate(SAMPLED):
            folder = tmp_path / f"now-{index}"
            folder.mkdir()

            def derived_file(dataset_id, file_id, t_ms, folder=folder):
                path = folder / f"{t_ms}.jpg"
                return {"file_id": f"{file_id}@{t_ms}", "path": str(path), "thumbnail": "", "image_url": ""}

            rows = pd.DataFrame([{"kind": "video", "path": clips[name], "relpath": name, "name": name,
                                  "file_id": "clip", "dataset_id": "walks"}])

            def now(rows=rows, derived_file=derived_file, every=every, most=most):
                frames = media.sample_video_frames(rows, derived_file, every_seconds=every, max_frames_per_video=most)
                return [(row.t_s, row.frame, row.width, row.height, _digest(Path(row.path).read_bytes()))
                        for row in frames.itertuples()]

            before = _outcome(lambda name=name, index=index, every=every, most=most: _main_sampled(
                clips[name], tmp_path / f"main-{index}", every, most))
            after = _outcome(now)
            if before != after:
                differ.append((name, every, most, before, after))
    assert not differ, f"Sample Video Frames now makes other frames than main: {differ}"


#: Where Split Video's read starts on each clip, and the width it draws at.
CUT = [
    ("walks.mp4", 0, 960), ("walks.mp4", 2.5, 960), ("walks.mp4", 0, 48), ("survey.mp4", 0, 960),
    ("raw.mjpeg", 0, 960), ("raw.mjpeg", 0.4, 960), ("wide.mp4", 0, 960), ("wide.mp4", 1.0, 640),
    ("odd.mp4", 0, 960), ("keys.mp4", 2.5, 960), ("keys.mp4", 5.2, 40), ("walk.mp4", 30.2, 960),
    ("sparse.mp4", 0, 960), ("sparse.mp4", 3.1, 960), ("raw.h264", 0, 960),
]


def test_split_video_re_encodes_the_frames_main_re_encoded(clips, tmp_path):
    """Split Video reads every frame from its first block's start, in yuv420p
    at most WIDTH wide, as main's ``_cut`` read them: the same frames at the
    same times, with the same pixels."""
    differ = []
    with _media(tmp_path) as media:
        for name, start, width in CUT:
            before = _outcome(lambda name=name, start=start, width=width: _main_cut_frames(clips[name], start, width))
            after = _outcome(lambda name=name, start=start, width=width: [
                (round(at, 6), _digest(frame.to_ndarray().tobytes()))
                for at, frame in media.read_video_frames(
                    clips[name], from_seconds=start, width=width, pixel_format="yuv420p")
            ])
            if before != after:
                differ.append((name, start, width, before, after))
    assert not differ, f"Split Video now reads other frames than main: {differ}"


#: Track Objects' parts: the clip, FROM_SECONDS, where the part ends, EVERY_SECONDS and WIDTH.
LOOKED_AT = [
    ("corner.mp4", 0, 2.0, 0.5, 960), ("corner.mp4", 0, 1.0, 0.5, 960), ("corner.mp4", 1.0, 1.0, 0.5, 960),
    ("corner.mp4", 0, 2.0, 0.1, 960), ("corner.mp4", 0, 2.0, 1.0, 960), ("walk.mp4", 30, 31.75, 0.5, 960),
    ("walk.mp4", 30.5, 31.0, 0.5, 960), ("walk.mp4", 30, 31.51, 0.5, 960), ("walk.mp4", 31.0, 31.0, 0.5, 960),
    ("walk.mp4", 31.5, 31.5, 0.5, 960), ("walk.mp4", 40, 40, 0.5, 960), ("whole.mp4", 0, 864.3, 2, 960),
    ("thirty.mp4", 0, 30.0, 10, 960), ("eight.mp4", 0, 8.0, 2, 960), ("eight.mp4", 0, 8.0, 2.5, 960),
    ("wide.mp4", 0, 2.0, 0.5, 960), ("wide.mp4", 0.3, 1.7, 0.2, 640), ("odd.mp4", 0, 1.0, 0.25, 960),
    ("keys.mp4", 2.5, 5.0, 0.5, 960), ("keys.mp4", 4.1, 9.9, 0.7, 48), ("sparse.mp4", 0, 6.0, 0.5, 960),
    ("sparse.mp4", 0.2, 4.0, 1.0, 960), ("edge.mp4", 0, 2.5, 0.5, 960), ("edge.mp4", 0, 2.5, 0.25, 960),
    ("edge.mp4", 1.5, 2.0, 0.5, 960),
]


def test_track_objects_looks_at_the_frames_main_looked_at_and_counts_them_as_main_did(clips, tmp_path):
    """Each part gives SAM 3 the frames main gave it, frame for frame, at the
    same times and with the same pixels, or the same refusal when the part
    holds no frame; and the count Track Objects' MAX_FRAMES refusal reads of
    a part is main's. A raw H.264 stream, whose frames carry no time, gives
    SAM 3 the frames at the times main's Sample Video Frames read them at."""
    from utk_curio.backend.tests.test_packages.test_sam3_package import _staged

    def images(read):
        frames, times = read()
        return [(t, image.size, _digest(image.tobytes())) for t, image in zip(times, frames)]

    differ = []
    with _staged(tmp_path) as module:
        for name, start, end, every, width in LOOKED_AT:
            run = SimpleNamespace(width=width, from_seconds=start, every_seconds=every)
            video = {"path": clips[name], "relpath": name}
            before = _outcome(lambda run=run, video=video, end=end: images(lambda: _main_sample(run, video, end)))
            after = _outcome(lambda run=run, video=video, end=end: images(lambda: module._looked_at(run, video, end)))
            counted = (_main_steps(start, end, every)[0], module._frames_needed(start, end, every))
            if before != after or counted[0] != counted[1]:
                differ.append((name, start, end, every, width, before, after, counted))
        raw = SimpleNamespace(width=960, from_seconds=0, every_seconds=0.5)
        looked_at = module._looked_at(raw, {"path": clips["raw.h264"], "relpath": "raw.h264"}, 3.0)[1]
    assert not differ, f"Track Objects now looks at other frames than main: {differ}"
    sampled = [row[0] for row in _main_sampled(clips["raw.h264"], tmp_path / "raw", 0.5, 300)]
    assert looked_at == sampled and len(sampled) > 1, (looked_at, sampled)
