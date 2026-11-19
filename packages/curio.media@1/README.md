# `curio.media@1`: Media

Nodes for the collections the Discovery Catalog adds from a folder, a bucket
or a Hugging Face dataset repository: videos, recordings and raster tiles.
Each node takes the
rows a Data Loading node returns for a collection (`curio_load_collection(...)`) and
returns rows or a raster the other nodes already read, so Simple View, the map
views and the zonal-statistics nodes work on the result as they are.

## Nodes

| Canonical id | Label | Input | Output |
|---|---|---|---|
| `curio.media/video-frames` | Sample Video Frames | A collection with videos | One row per frame: `path`, `thumbnail`, `image_url`, `width`, `height`, `t_s` (the frame's time in the video), `sequence` (the video), `frame` (the frame's number in it), and the video's fields, position and time |
| `curio.media/split-audio` | Split Audio | A collection with recordings | One row per window: `level_dbfs` and `peak_dbfs` over all of the recording's channels, `t_s`, `duration_s`, a playable clip in the recording's channels (`audio_url`), and the recording's fields and time |
| `curio.media/split-video` | Split Video | On the top circle, a collection with videos; on the bottom circle, optional, where to cut: one row per block, with `t_s` (where it starts, in seconds from its video's start) and, if it has them, `end_s` and `video_file_id` | One row per block, a video Simple View plays, re-encoded as H.264 at most `WIDTH` wide, with no sound: `block` (its number in its video), the cut's own columns, `t_s` and `end_s` (where it starts and ends in the video), then the video's fields, position and time, `duration_s`, `fps`, `width` and `height` |
| `curio.media/mosaic-rasters` | Mosaic Rasters | A raster collection's rows, often filtered | One RASTER: a virtual mosaic of the tiles, which must share their CRS, resolution, bands, data type and no-data value. Where tiles overlap, a tile's no-data pixels show the tile below |

## Settings

Each node's settings are constants at the top of its code:

- Sample Video Frames: `EVERY_SECONDS` (default 2.0) and `MAX_FRAMES_PER_VIDEO` (default 300).
- Split Audio: `WINDOW_SECONDS` (default 5.0) and `MAX_WINDOWS_PER_RECORDING` (default 2000).
- Split Video: `BLOCK_SECONDS` (default 60.0), the length of a block when nothing is wired to the bottom circle; `WIDTH` (default 960), the widest a block is drawn; and `MAX_FRAMES` (default 30000), the most frames one run re-encodes, which a whole 864 s walk at 30 frames a second fits.

## Cutting a video where you choose

Split Video cuts every `BLOCK_SECONDS` seconds until a table is wired to its
bottom circle. Then each row of that table is a block: it starts at its `t_s`
and ends at its `end_s`, or where the next block starts, or where the video
ends. A row with a `video_file_id` cuts only that video, and one without it
cuts every video of the collection; a video no row cuts gets no block. The
table's other columns, such as a street's name, come first on their block's
row, so Simple View's card says which block it is. A Python Computation node
makes such a table from what you know of the walk. With the walk's rows on its
first circle and, on its second, the corners it passed, each with the clock
time it passed them (`passed_at`) and the street that starts there:

```python
walk, corners = input_0, input_1
began = walk["taken_at"].iloc[0]
return pd.DataFrame({
    "t_s": (corners["passed_at"] - began).dt.total_seconds(),
    "street": corners["street"],
})
```

A block's `t_s` is where it starts in its video, so the player linked by time
reads the time of the video it was cut from.

## Functions

Each node's code is its settings and the call of one function, which does its
work:

| Function | Module | What it does |
|---|---|---|
| `sample_video_frames(media, derived_file, *, every_seconds=2.0, max_frames_per_video=300)` | `media_collections`, this package's | A frame every `every_seconds` seconds from each video in a collection's rows, at most `max_frames_per_video` from one video: one image row per frame |
| `split_audio(media, derived_file, *, window_seconds=5.0, max_windows_per_recording=2000)` | `media_collections`, this package's | Each recording in a collection's rows split into windows of `window_seconds` seconds: one row per window, with its level, its peak and its clip |
| `split_video(media, derived_file, cuts=None, *, block_seconds=60.0, width=960, max_frames=30000)` | `media_collections`, this package's | Each video in a collection's rows cut into blocks, every `block_seconds` seconds or where the rows of `cuts` say: one row per block, each a video of its own |
| `mosaic_collection(tiles, output_file)` | `scout_rasters.mosaic`, [Rasterization](../curio.rasterization@1/README.md)'s | A raster collection's rows side by side in one virtual mosaic, opened |

Sample Video Frames' code, for one:

```python
from media_collections import sample_video_frames

EVERY_SECONDS = 2.0
MAX_FRAMES_PER_VIDEO = 300

return sample_video_frames(
    input_0, curio_derived_file,
    every_seconds=EVERY_SECONDS, max_frames_per_video=MAX_FRAMES_PER_VIDEO,
)
```

The package depends on Rasterization (`curio.rasterization@1` in its
`dependencies.packages`), whose mosaic Mosaic Rasters calls: adding Media
adds Rasterization too, and a run of a Media node is handed both packages'
modules.

## A dataflow

```
[ Data Loading: a collection ] ──► [ Sample Video Frames ] ──► [ Simple View ]
[ Data Loading: noise recordings ] ──► [ Split Audio ] ──► [ Vega-Lite: level over time ]
[ Data Loading: a walk ] ──► [ Split Video ] ──► [ Simple View: a block per card ]
[ Python Computation: where each block starts ] ──► [ Split Video's bottom circle ]
[ Data Loading: orthoimagery ] ──► [ Python Computation: keep one year ] ──► [ Mosaic Rasters ] ──► [ UHVI Zonal Stats ]
```

## Files

A frame, a window or a block is a file the node writes beside the collection's
other derived files, served back to Simple View by its id. A block's file is
named after its video, where it starts and ends and its width, so cutting a
video again into the same blocks writes the same files. The media files
themselves are never written. A bucket collection's files are read in place
where the deployment mounts the bucket; elsewhere they must be cached first
(**Cache files**, in the collection's details in the Data Catalog), and a node
that meets an uncached file says so.

## Examples

- [Storage: orthorectified imagery](../../docs/examples/18-storage-orthorectified-imagery.md) runs Mosaic Rasters on one year's tiles.
- [Storage: photos and videos](../../docs/examples/21-storage-photos-and-videos.md) runs Sample Video Frames on a survey's video.
- [Storage: audio recordings](../../docs/examples/22-storage-audio-recordings.md) runs Split Audio and charts the levels.
