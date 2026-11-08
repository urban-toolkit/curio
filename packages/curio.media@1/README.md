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
| `curio.media/mosaic-rasters` | Mosaic Rasters | A raster collection's rows, often filtered | One RASTER: a virtual mosaic of the tiles, which must share their CRS, resolution, bands, data type and no-data value. Where tiles overlap, a tile's no-data pixels show the tile below |

## Settings

Each node's settings are constants at the top of its code:

- Sample Video Frames: `EVERY_SECONDS` (default 2.0) and `MAX_FRAMES_PER_VIDEO` (default 300).
- Split Audio: `WINDOW_SECONDS` (default 5.0) and `MAX_WINDOWS_PER_RECORDING` (default 2000).

## Functions

Each node's code is its settings and the call of one function, which does its
work:

| Function | Module | What it does |
|---|---|---|
| `sample_video_frames(media, derived_file, *, every_seconds=2.0, max_frames_per_video=300)` | `media_collections`, this package's | A frame every `every_seconds` seconds from each video in a collection's rows, at most `max_frames_per_video` from one video: one image row per frame |
| `split_audio(media, derived_file, *, window_seconds=5.0, max_windows_per_recording=2000)` | `media_collections`, this package's | Each recording in a collection's rows split into windows of `window_seconds` seconds: one row per window, with its level, its peak and its clip |
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
[ Data Loading: orthoimagery ] ──► [ Python Computation: keep one year ] ──► [ Mosaic Rasters ] ──► [ UHVI Zonal Stats ]
```

## Files

A frame or a window is a file the node writes beside the collection's other
derived files, served back to Simple View by its id. The media files
themselves are never written. A bucket collection's files must be cached first
(**Cache files**, in the collection's details in the Data Catalog); a node
that meets an uncached file says so.

## Examples

- [Storage: orthorectified imagery](../../docs/examples/18-storage-orthorectified-imagery.md) runs Mosaic Rasters on one year's tiles.
- [Storage: photos and videos](../../docs/examples/21-storage-photos-and-videos.md) runs Sample Video Frames on a survey's video.
- [Storage: audio recordings](../../docs/examples/22-storage-audio-recordings.md) runs Split Audio and charts the levels.
