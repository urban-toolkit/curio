# `curio.media@1`: Media

Nodes for the collections the Discovery Catalog adds from a folder, a bucket
or a Hugging Face dataset repository: videos, recordings and raster tiles.
Each node takes the
rows a Data Loading node returns for a collection (`curio_collection(...)`) and
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

## A dataflow

```
[ Data Loading: a collection ] ──► [ Sample Video Frames ] ──► [ Simple View ]
[ Data Loading: noise recordings ] ──► [ Split Audio ] ──► [ Vega-Lite: level over time ]
[ Data Loading: orthoimagery ] ──► [ Data Transformation: keep one year ] ──► [ Mosaic Rasters ] ──► [ UHVI Zonal Stats ]
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
