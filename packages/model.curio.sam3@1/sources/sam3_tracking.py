"""SAM 3 through a collection's videos: the frames it looks at, the objects it
follows from frame to frame, and the overlay and tracks it writes for each video.

Track Objects calls :func:`track_objects`, with its settings and Curio's
plumbing: the model ``curio_load_model("model.curio.sam3")`` gives, whose
``path`` is the folder of SAM 3's weights, and ``curio_derived_file``, which
says where a file made from a collection's video is kept and served.

Its SAM 3 is Transformers' video model with one correction
(:class:`Sam3VideoModel`): on a frame where SAM 3 drops an object that showed
up for a moment, each other object keeps its own mask and score.
"""

import colorsys
import datetime
import math
from dataclasses import dataclass
from fractions import Fraction

import av
import geopandas as gpd
import numpy as np
import pandas as pd
import torch
from PIL import Image, ImageDraw
from transformers import Sam3VideoModel as TransformersSam3VideoModel, Sam3VideoProcessor

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
#: How long before a step's time a frame may come and still be the frame
#: looked at for that step.
EARLY_SECONDS = 1e-3
#: The overlay's time base: each of its frames plays at its own time in the
#: video, to the millisecond.
MILLISECOND = Fraction(1, 1000)
#: What SAM 3 reads again of an object at a frame before the one it looks at:
#: its memory there, and its pointer.
MEMORY = ("maskmem_features", "maskmem_pos_enc")
POINTER = "object_pointer"


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
    forget_seconds: object
    from_seconds: float
    width: int
    derived_file: object


def track_objects(media, model, derived_file, *, labels, every_seconds=0.5, forget_seconds=10, from_seconds=0,
                  to_seconds=None, max_seconds=300, width=960):
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
    one id. It lets go of an object it has not seen for *forget_seconds*
    (None: it follows every object to the part's end): the object's track ends
    where it was last seen, and an object that comes back is found again, as a
    new object with a new id. A part longer than *max_seconds*, the most one
    run takes, stops the call before SAM 3 loads, as do empty *labels* and a
    video not on this machine.

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
            every_seconds=every_seconds, forget_seconds=forget_seconds, from_seconds=from_seconds, width=width,
            derived_file=derived_file,
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
    """The frames SAM 3 looks at, read in order, and their times in seconds:
    one for each step of *every_seconds* from *from_seconds* up to *end*, never
    the step at *end*. Each is the first frame from a millisecond before its
    step's time to a millisecond before the next step's, even one that comes
    after *end*. A part of no length looks at one frame wherever the frames
    fall: the first no more than a millisecond before *from_seconds*, or after
    it."""
    frames, times = [], []
    with av.open(video["path"]) as container:
        stream = container.streams.video[0]
        # Every frame up to the last one looked at is decoded, not only those:
        # FFmpeg decodes several at once with frame threading, about five
        # times faster than with its default, slice threading, at 1080p.
        stream.thread_type = "AUTO"
        width = 2 * (min(run.width, stream.codec_context.width) // 2)
        height = 2 * round(stream.codec_context.height * width / stream.codec_context.width / 2)
        container.seek(int(run.from_seconds / stream.time_base), stream=stream, backward=True)
        # The part's steps, ceil(W / every_seconds) of a part of W seconds (the
        # 1e-9 is for float rounding), and where the frames of the step at
        # *end* would start; a part of no length has one step and no such end.
        if end > run.from_seconds:
            count = math.ceil((end - run.from_seconds) / run.every_seconds - 1e-9)
            stop = run.from_seconds + count * run.every_seconds - EARLY_SECONDS
        else:
            count, stop = int(end == run.from_seconds), float("inf")
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
            # On by whole steps, at least one, to the first this frame comes
            # more than a millisecond before: a frame just before a step's
            # time is that step's, and the next frame is not looked at for it.
            steps = max(steps + 1, int((frame.time - run.from_seconds + EARLY_SECONDS) / run.every_seconds) + 1)
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


class Sam3VideoModel(TransformersSam3VideoModel):
    """SAM 3's video model as Transformers has it, but for the frames where
    SAM 3 drops an object that showed up for a moment: there each other
    object keeps its own mask and score.

    SAM 3's tracker gives each frame a mask and a score for each object it
    follows as the frame starts, in order. Transformers drops the objects the
    frame rules out before it pairs those masks and scores with the objects
    it follows, so each object after one dropped got the mask and score of
    the object before it, for that frame. Here SAM 3 drops them once the
    frame's masks and scores are paired, as SAM 3's own code pairs them with
    the objects it followed as the frame started, and the frame's output
    leaves the objects dropped out, as Transformers' does."""

    def run_tracker_update_execution_phase(self, inference_session, frame_idx, det_out, tracker_update_plan,
                                           reverse=False):
        """Take in the frame's new objects, and drop none yet: the frame's
        masks and scores are still to be paired with their objects
        (:meth:`_det_track_one_frame`)."""
        keeping = {**tracker_update_plan, "obj_ids_newly_removed": set()}
        return super().run_tracker_update_execution_phase(
            inference_session=inference_session, frame_idx=frame_idx, det_out=det_out,
            tracker_update_plan=keeping, reverse=reverse,
        )

    def _det_track_one_frame(self, inference_session, frame_idx, reverse, streaming=False):
        """SAM 3 through one frame, each of its masks and scores paired with
        its own object; then the objects SAM 3 no longer follows are dropped,
        as Transformers drops them before it pairs them, and left out of the
        frame's masks."""
        masks, scores, metadata, tracker_scores = super()._det_track_one_frame(
            inference_session=inference_session, frame_idx=frame_idx, reverse=reverse, streaming=streaming,
        )
        following = set(metadata["obj_ids"])
        for object_id in [object_id for object_id in inference_session.obj_ids if object_id not in following]:
            inference_session.remove_object(object_id, strict=False)
            masks.pop(object_id, None)
        return masks, scores, metadata, tracker_scores


class _Frames:
    """The frames of a SAM 3 session, as SAM 3 asks for them: each is made
    ready, as a session handed the whole video makes it, only when SAM 3 comes
    to it, and none is kept. The session still counts every frame of the part,
    since SAM 3 reads how many there are to know how far back to look."""

    def __init__(self, run, frames):
        self._run = run
        self._frames = frames
        #: The last frame SAM 3 has looked at.
        self.latest = -1

    def __len__(self):
        return len(self._frames)

    def __getitem__(self, index):
        self.latest = max(self.latest, index)
        ready = self._run.processor.video_processor(
            videos=[self._frames[index]], device=self._run.device, return_tensors="pt",
        )
        return ready.pixel_values_videos[0][0].to(self._run.device, dtype=self._run.dtype)


def _follow(run, frames, let_go_after=None):
    """SAM 3 through *frames*, in order: each frame's index, with what SAM 3
    found in it, as ``postprocess_outputs`` gives it.

    SAM 3 runs as over a whole video, and holds a frame back until it has seen
    a few after it. It is handed one frame at a time, and after each frame it
    forgets what it never reads again (:func:`_forget`), so what it holds grows
    with the objects it follows, not with the frames, and the memory the frame
    used goes back to the device (:func:`_give_back`). With *let_go_after*, a
    number of frames, it also lets go between two frames of each object it has
    not shown in the last *let_go_after* frames (:class:`_Sightings`), so the
    objects it follows stop adding up over a long video."""
    seen = _Frames(run, frames)
    session = run.processor.init_video_session(inference_device=run.device, dtype=run.dtype)
    session.processed_frames = seen
    # The size masks are drawn at, as a session handed the whole video has it.
    session.video_width, session.video_height = frames[0].size
    run.processor.add_text_prompt(session, run.labels)
    sightings = None if let_go_after is None else _Sightings(session)
    hook = None if sightings is None else run.sam3.register_forward_hook(sightings.note)
    try:
        for output in run.sam3.propagate_in_video_iterator(inference_session=session):
            found = run.processor.postprocess_outputs(session, output)
            _forget(session, seen.latest, run.sam3.tracker_model)
            # Once SAM 3 has looked at the last frame, it has no frame left to
            # follow an object through.
            if sightings is not None and seen.latest < len(frames) - 1:
                sightings.let_go(seen.latest - let_go_after, output.frame_idx)
            _give_back(run.device)
            yield output.frame_idx, found
    finally:
        if hook is not None:
            hook.remove()


class _Sightings:
    """The last frame SAM 3 showed each object it follows at, to let go of an
    object it has not seen for a while.

    SAM 3 holds each frame's output back until it has seen a few frames after
    it, so the frames an object is shown at are noted from each frame's output
    as SAM 3 makes it (:meth:`note`, a forward hook of SAM 3), not from the
    outputs it hands back: an object shown again in a frame SAM 3 still holds
    back is seen."""

    def __init__(self, session):
        self._session = session
        #: Each object SAM 3 follows: the last frame it was shown at.
        self.last = {}
        #: Each object let go that an output SAM 3 holds back shows: the id of
        #: its label's prompt, and the last frame it was shown at.
        self._held = {}

    def note(self, _sam3, _args, output):
        """Note the objects SAM 3's *output* of a frame shows: each with a mask
        SAM 3 does not hide there, and each new object, at the frame SAM 3
        found it. And put back the labels of the objects let go that outputs
        SAM 3 holds back show: dropping the last object it follows, SAM 3
        clears every label."""
        self._session.obj_id_to_prompt_id.update({object_id: label for object_id, (label, _) in self._held.items()})
        masks = output.obj_id_to_mask
        if not masks:
            return
        hidden = output.suppressed_obj_ids or ()
        has_mask = torch.stack([(mask > 0).any() for mask in masks.values()]).tolist()
        for object_id, shown in zip(masks, has_mask):
            if (shown and object_id not in hidden) or object_id not in self.last:
                self.last[object_id] = output.frame_idx

    def let_go(self, before, handed_back):
        """Let go of each object SAM 3 follows and last showed at frame
        *before* or earlier, as SAM 3 removes an object it drops
        (``remove_object``), and drop the entries SAM 3 keeps of it to decide
        whether to drop an object, which it copies at every frame. SAM 3 has
        handed back its outputs up to frame *handed_back*; those it still holds
        back show the object as it was, so its label stays until they are
        handed back."""
        session = self._session
        for object_id in [held for held, (_, last) in self._held.items() if last <= handed_back]:
            del self._held[object_id]
            session.obj_id_to_prompt_id.pop(object_id, None)
        last = {object_id: self.last[object_id] for object_id in session.obj_ids if object_id in self.last}
        gone = {object_id: frame for object_id, frame in last.items() if frame <= before}
        self.last = {object_id: frame for object_id, frame in last.items() if frame > before}
        if not gone:
            return
        for object_id, frame in gone.items():
            if frame > handed_back:
                self._held[object_id] = (session.obj_id_to_prompt_id[object_id], frame)
            session.remove_object(object_id)
        # Removing the last object SAM 3 follows clears every label, those
        # still held among them.
        session.obj_id_to_prompt_id.update({object_id: label for object_id, (label, _) in self._held.items()})
        for kept in (session.obj_first_frame_idx, session.unmatched_frame_inds, session.trk_keep_alive):
            for object_id in gone:
                kept.pop(object_id, None)
        # A pair goes with both its objects' first frames, which SAM 3 reads
        # for each pair it keeps.
        pairs = session.overlap_pair_to_frame_inds
        for pair in [pair for pair in pairs if not gone.keys().isdisjoint(pair)]:
            del pairs[pair]
        # The latest output's scores are the session's own dict: a new dict
        # leaves them as they were.
        session.obj_id_to_score = {
            object_id: score for object_id, score in session.obj_id_to_score.items() if object_id not in gone
        }


def _give_back(device):
    """Give the memory torch keeps on *device* for tensors to come, and no
    tensor uses, back to the device. Each frame's work asks for more than the
    frame before as SAM 3 follows more objects, so what torch kept from one
    frame does not fit the next, and it would stay held from the device's other
    users."""
    if device == "cuda":
        torch.cuda.empty_cache()
    elif device == "mps":
        torch.mps.empty_cache()


def _forget(session, latest, tracker):
    """Drop from a SAM 3 *session* what SAM 3 never reads again once it has
    looked at frame *latest*.

    Of the frames before the one it looks at, SAM 3 reads only an object's
    memory (:data:`MEMORY`) of the last ``num_maskmem - 1`` frames and of its
    last ``max_cond_frame_num`` conditioning frames, where SAM 3 took the
    object from a detection; and the object's pointer (:data:`POINTER`) of the
    last ``max_object_pointers_in_encoder - 1`` frames and of every
    conditioning frame. Of a past frame it never reads again the object's
    masks and scores, the mask it was found with, or the frame's scores and
    suppressed objects. An object's memory of a frame is a slice of all the
    objects' at that frame, so a memory kept after the others' is copied out of
    it."""
    memory_after = latest - (tracker.num_maskmem - 1)
    pointer_after = latest - (tracker.config.max_object_pointers_in_encoder - 1)
    recent = tracker.config.max_cond_frame_num
    for outputs in session.output_dict_per_obj.values():
        tracked, conditioning = outputs["non_cond_frame_outputs"], outputs["cond_frame_outputs"]
        for frame in [frame for frame in tracked if frame <= min(memory_after, pointer_after)]:
            del tracked[frame]
        for frame, output in tracked.items():
            _keep(output, memory=frame > memory_after)
        last = set(sorted(conditioning)[-recent:]) if recent >= 1 else set(conditioning)
        for frame, output in conditioning.items():
            _keep(output, memory=frame > memory_after or frame in last, alone=frame <= memory_after)
    per_frame = [*session.frames_tracked_per_obj.values(), *session.mask_inputs_per_obj.values(),
                 session.obj_id_to_tracker_score_frame_wise, session.suppressed_obj_ids]
    for frames in per_frame:
        for frame in [frame for frame in frames if frame < latest]:
            del frames[frame]


def _keep(output, *, memory, alone=False):
    """Keep of an object's *output* at a past frame only its pointer, and its
    memory when *memory*; a memory kept *alone*, after the other objects' at
    its frame, is copied out of theirs."""
    for key in [key for key in output if key != POINTER and not (memory and key in MEMORY)]:
        del output[key]
    if memory and alone:
        for key in MEMORY:
            value = output.get(key)
            if value is not None and value.untyped_storage().nbytes() > value.nbytes:
                output[key] = value.clone()


def _track(run, video, end):
    """Run SAM 3 through one video: its overlay's row, with its tracks file."""
    frames, times = _sample(run, video, end)
    start_ms = round(run.from_seconds * 1000)
    overlay = run.derived_file(video["dataset_id"], video["file_id"], start_ms, "mp4", tag=TAG)
    tracks_file = run.derived_file(video["dataset_id"], video["file_id"], start_ms, "parquet", tag=TAG)
    width, height = frames[0].size
    # Each frame of the overlay plays at its own time in the video, from the
    # first, in milliseconds, so the overlay plays in real time whatever
    # every_seconds is; the last plays for the frames' mean gap, or for
    # every_seconds when it is the only one.
    shown = [round(1000 * (t - times[0])) for t in times]
    gaps = [later - sooner for sooner, later in zip(shown, shown[1:])]
    gaps.append(round(shown[-1] / len(gaps)) if gaps else round(1000 * run.every_seconds))
    lasting = dict(zip(shown, gaps))
    duration_s = (shown[-1] + gaps[-1]) / 1000
    # An object SAM 3 has not seen for forget_seconds is let go: so many
    # frames, at least one (the 1e-9 is for float rounding).
    let_go_after = None if run.forget_seconds is None else max(
        1, math.ceil(run.forget_seconds / run.every_seconds - 1e-9))
    tracks, label_of = {}, {}
    # H.264 in yuv420p, its index first: what browsers play as the file
    # arrives. With no B-frames each frame is written in the order it plays,
    # with how long it plays, so the file lasts duration_s.
    with av.open(overlay["path"], "w", options={"movflags": "+faststart"}) as out:
        rate = Fraction(1000 * len(frames), shown[-1] + gaps[-1]).limit_denominator(1000)
        drawn = out.add_stream("h264", rate=rate)
        drawn.width, drawn.height, drawn.pix_fmt = width, height, "yuv420p"
        drawn.codec_context.time_base = MILLISECOND
        drawn.codec_context.max_b_frames = 0
        # SAM 3 holds each frame back until it has seen a few after it, so it
        # can drop an object that was never really there.
        with torch.inference_mode():
            for index, found in _follow(run, frames, let_go_after):
                t_s = times[index]
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
                picture = av.VideoFrame.from_image(_draw(run, frames[index], found, label_of))
                picture.pts, picture.time_base = shown[index], MILLISECOND
                for packet in drawn.encode(picture):
                    packet.duration = lasting[packet.pts]
                    out.mux(packet)
        for packet in drawn.encode():
            packet.duration = lasting[packet.pts]
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
        "duration_s": duration_s, "width": width, "height": height, "fps": round(len(frames) / duration_s, 3),
        "tracks": tracks_file["path"],
    })
    for label in run.labels:
        row[label.replace(" ", "_") + "_objects"] = int((table["label"] == label).sum())
    return row
