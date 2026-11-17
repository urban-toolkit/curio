"""Split Video.

Input: on the top circle, a collection's rows, as Data Loading's
`curio_load_collection(...)` returns them; on the bottom circle, if anything is
wired there, where to cut: one row per block, with `t_s`, where the block
starts in seconds from its video's start, and maybe `end_s`, where it ends, and
`video_file_id`, the video it cuts. Every video becomes one row per block, each
block an MP4 of its own that Simple View plays, with no sound. A block's row
leads with `block`, the cut's own columns (a street's name, say), `t_s` and
`end_s`, where the block starts and ends in the video, so a player linked by
time reads the video's time; then it keeps the video's own columns.

Settings:
- BLOCK_SECONDS: the length of one block, when nothing is wired to the bottom circle.
- WIDTH: the widest a block is drawn.
- MAX_FRAMES: the most frames one run re-encodes.
"""

from media_collections import split_video

BLOCK_SECONDS = 60.0
WIDTH = 960
MAX_FRAMES = 30000

return split_video(
    input_0, curio_derived_file, input_1,
    block_seconds=BLOCK_SECONDS, width=WIDTH, max_frames=MAX_FRAMES,
)
