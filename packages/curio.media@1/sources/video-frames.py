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

from media_collections import sample_video_frames

EVERY_SECONDS = 2.0
MAX_FRAMES_PER_VIDEO = 300

return sample_video_frames(
    input_0, curio_derived_file,
    every_seconds=EVERY_SECONDS, max_frames_per_video=MAX_FRAMES_PER_VIDEO,
)
