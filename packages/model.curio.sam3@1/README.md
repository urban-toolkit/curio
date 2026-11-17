# `model.curio.sam3@1`: SAM 3 (objects found by name)

SAM 3, Meta's Segment Anything Model 3, finds every object a short phrase
names, such as *curb ramp* or *traffic cone*, in an image or a video. It
outlines each object with a mask, and in a video it follows each one from frame
to frame under one id. Curio runs it with Hugging Face Transformers.

This is a model package: the model's two nodes, the modules that hold their
logic, and where the model's weights come from. The
[Model Catalog](../../docs/MODEL-CATALOG.md) lists it, and its card, dropped on
the canvas, offers both nodes.

| Part | What it is | License |
|---|---|---|
| `models/checkpoint/` | The weights, Meta's `facebook/sam3`: the eight files Transformers reads, 3.4 GB, downloaded on first use from an identical copy, `jetjodh/sam3` on Hugging Face at revision `1aa50ce07302cb375f85d8084b68a0fb378b8d85`. Never shipped | SAM License (`LICENSE`), published by Meta |
| `sources/track-objects.py` | The Track Objects node's code: its settings and one call of `track_objects` | MIT |
| `sources/sam3_tracking.py` | The module Track Objects calls: `track_objects`, SAM 3 through a collection's videos | MIT |
| `sources/segment-images.py` | The Segment Images node's code: its settings and one call of `find_in_images` | MIT |
| `sources/sam3_images.py` | The module Segment Images calls: `find_in_images`, SAM 3 on a collection's images | MIT |

## Nodes

| Canonical id | Label | Input | Output |
|---|---|---|---|
| `model.curio.sam3/track-objects` | Track Objects | A collection's rows, each video with a `path` | One row per video: its overlay, a count of the objects of each label, and the path of its tracks |
| `model.curio.sam3/segment-images` | Segment Images | A collection's images, or the frames Sample Video Frames sampled, each with a `path` | Each image with the label covering the most of it, each label's share of it and count of objects, and its overlay |

**Track Objects** samples each video of a collection, one frame every
`EVERY_SECONDS`, and runs SAM 3 on those frames with the phrases in `LABELS`.
SAM 3 holds each frame back until it has seen a few after it, so it can drop an
object that showed up for a moment and was never there.

Its code tab holds its settings and one call of `track_objects`, the function of
the package's module `sam3_tracking`, which the header above the code lists:

```python
from sam3_tracking import track_objects

LABELS = [...]
EVERY_SECONDS = 0.5
...

return track_objects(
    input_0, curio_load_model("model.curio.sam3"), curio_derived_file,
    labels=LABELS, every_seconds=EVERY_SECONDS, forget_seconds=FORGET_SECONDS,
    from_seconds=FROM_SECONDS, to_seconds=TO_SECONDS, max_frames=MAX_FRAMES, width=WIDTH,
)
```

The node hands the function Curio's plumbing: the model, whose `path` is the
folder of its weights, and `curio_derived_file`, which says where the overlay
and the tracks are kept. Empty `LABELS`, a part that needs more than
`MAX_FRAMES` frames and a video not on the machine yet stop the node before
SAM 3 loads.

The input is a collection's rows, as a Data Loading node gives them with
`curio_load_collection(...)`, each video's file on the machine, in a mounted
bucket or cached. Rows that are not videos are left out.

## Settings

The constants at the top of the node's code, each handed to `track_objects` as
the argument of its name in lowercase:

| Setting | Default | What it sets |
|---|---|---|
| `LABELS` | curb ramp, curb cut, tactile paving, bollard, pole, construction barrier, traffic cone, person | What to look for, in plain words. SAM 3 takes any short noun phrase, not only the package's labels below. |
| `EVERY_SECONDS` | `0.5` | The gap between two frames SAM 3 looks at. |
| `FORGET_SECONDS` | `10` | How long SAM 3 follows an object it no longer sees. An object it has not seen for that long is let go: its track ends where it was last seen, and if it comes back SAM 3 finds it again as a new object, with a new id, and counts it again. `None` follows every object to the end of the part. |
| `FROM_SECONDS`, `TO_SECONDS` | `0`, `None` | The part of each video to track, in seconds from its start; `None` is its end. |
| `MAX_FRAMES` | `450` | The most frames of a video one run looks at. A part of W seconds needs W / `EVERY_SECONDS` frames, rounded up, and one that needs more stops the node, with a message naming the limit, the frames the part needs, and an `EVERY_SECONDS` and a shorter part that fit. |
| `WIDTH` | `960` | The widest frames are read and drawn at. A narrower video keeps its size. |

The node runs on the GPU when the machine has one (CUDA, in bfloat16, or
Apple's MPS), else on the CPU.

## Output

Each video comes back as one row: its overlay, a video of the frames SAM 3
looked at, each object's mask and box drawn in its label's color with its label
and id. Simple View plays it in real time, each frame at its own time in the
video, so it runs as long as the part it tracked. It is H.264, which every
browser plays. The row keeps the video's own columns, its fields and its
position, and has:

| Column | What it holds |
|---|---|
| `file_id`, `path`, `thumbnail`, `image_url` | The overlay's, as a collection's video row has them |
| `video_file_id`, `name` | The video tracked |
| `t_s` | Where the overlay starts in the video: a time in the video is `t_s` plus the time in the overlay |
| `duration_s`, `fps`, `width`, `height` | The overlay's |
| `<label>_objects` | How many objects of each label SAM 3 followed, such as `curb_ramp_objects` |
| `tracks` | The path of a Parquet table of the video's objects |

The tracks table has one row per object, which `pd.read_parquet(row["tracks"])`
reads:

| Column | What it holds |
|---|---|
| `video_file_id`, `video` | The video |
| `object_id` | The object's id, the one drawn on the overlay |
| `label` | The phrase of `LABELS` that found it |
| `start_s`, `end_s` | The first and the last time SAM 3 saw it, in seconds from the video's start |
| `frames` | How many of the frames it looked at it was seen in |
| `largest_share` | The largest share of a frame its mask covered, from 0 to 1 |
| `mean_score` | Its mean detection score over those frames |

Both files are kept beside the collection's other files derived from that video.
Their name holds the video, `FROM_SECONDS` and a tag of `LABELS`,
`EVERY_SECONDS`, `FORGET_SECONDS`, where the part ends and `WIDTH`, so a run
with other settings keeps files of its own, and a run with the same settings
writes them again.

## Segment Images

**Segment Images** runs SAM 3 on each image of a collection, or each frame a
Sample Video Frames node sampled from its videos, with the phrases in
`LABELS`, and finds every object each one names. SAM 3 reads the image's
features once and looks for every label in them. Its code tab holds its
settings and one call of `find_in_images`, the function of the package's module
`sam3_images`:

```python
from sam3_images import find_in_images

LABELS = [...]  # the package's 35 labels
THRESHOLD = 0.5
WIDTH = 960
MAX_IMAGES = 300

return find_in_images(
    input_0, curio_load_model("model.curio.sam3"), curio_derived_file,
    labels=LABELS, threshold=THRESHOLD, width=WIDTH, max_images=MAX_IMAGES,
)
```

| Setting | Default | What it sets |
|---|---|---|
| `LABELS` | the package's 35 labels, in their seven groups | What to look for, in plain words. Fewer labels run faster. |
| `THRESHOLD` | `0.5` | The score SAM 3 needs to keep an object. |
| `WIDTH` | `960` | The widest an image is read and its overlay drawn. |
| `MAX_IMAGES` | `300` | The most images one run looks at, as many as Sample Video Frames samples from one video by default. More rows stop the node before SAM 3 loads. |

It reads the model as Track Objects does, on the same device, and draws each
object as Track Objects draws one. Each row comes back with these columns
first, the ones Image Segmentation gives, then its own:

| Column | What it holds |
|---|---|
| `dominant_class`, `dominant_pct` | The label whose objects cover the most of the image, and that share in percent; None and 0 where SAM 3 found nothing |
| `<label>_pct` | The share of the image the label's objects cover together, in percent, the label as written, such as `curb ramp_pct` |
| `<label>_objects` | How many objects of the label SAM 3 found, such as `curb_ramp_objects` |
| `overlay_url` | The image with each object's mask, box and label drawn, which Simple View shows beside it |
| `segment_error` | Why a row has no results: its image is not on the machine, or cannot be read |

An overlay is a PNG kept beside the collection's other derived files. It is
named as Image Segmentation names an overlay, after the image, or after its
video at its time for a sampled frame, and after a tag of `LABELS`,
`THRESHOLD` and `WIDTH`, so a run with other settings keeps overlays of its
own. Empty `LABELS`, a label named twice and more rows than `MAX_IMAGES` stop
the node before SAM 3 loads.

## Labels

The package's labels are 35 phrases for what a camera looking at a sidewalk
sees, in seven groups. Track Objects' `LABELS` starts with eight of them, and
Segment Images' with all 35.

| Group | Labels |
|---|---|
| Surface and crossings | sidewalk, crosswalk, curb, driveway, alley, tactile paving, stairs |
| Curb ramps | curb ramp, curb cut, wheelchair ramp, ramp, curbramp |
| Crossing control | traffic light, pedestrian signal, stop sign |
| Obstacles and furniture | pole, fire hydrant, trash bin, bench, bollard, tree, planter, parking meter, bicycle rack, bus stop |
| Temporary obstructions | construction barrier, traffic cone, scaffolding |
| Surface condition | pothole, puddle, manhole cover, sidewalk crack |
| Context | person, car, bicycle |

## A dataflow

```
Data Loading (videos) → Track Objects → Simple View (the overlay)
                              ↓
               Python Computation (the tracks) → Vega-Lite (one bar per object)

Data Loading (videos) → Sample Video Frames → Segment Images → Simple View (each frame beside its overlay)
```

A Python Computation node reads every video's tracks into one table:

```python
import pandas as pd

return pd.concat([pd.read_parquet(path) for path in input_0["tracks"]])
```

## The weights

The weights are Meta's, published as `facebook/sam3` on Hugging Face, and are
3.4 GB, so they are in neither the Curio repository nor the pip package. The
first time a node runs the model, Curio downloads them from an identical copy,
`jetjodh/sam3` at revision `1aa50ce07302cb375f85d8084b68a0fb378b8d85`, and
checks each file against the digest the manifest names, which are the digests
of Meta's files. The SAM License lets them be shared with its text, which this
package ships. Later runs read them where they were placed, as
[DEPLOYMENT.md](../../docs/DEPLOYMENT.md#model-weights-a-package-fetches) says.
The repository's `sam3.pt`, the checkpoint of SAM 3's original code, is not
downloaded: Transformers reads `model.safetensors`.

## Setup

Curio installs the package's Python libraries with it: `transformers` 5,
`safetensors`, `torch` and `torchvision`, which run the model, and `av`,
`pandas`, `geopandas`, `numpy`, `pillow` and `pyarrow`. It asks for no version of
torch or torchvision: Curio's images hold both, built for CUDA, so adding the
model there installs neither.
