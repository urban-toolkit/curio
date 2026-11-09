# `model.curio.sam3@1`: SAM 3 (objects found by name)

SAM 3, Meta's Segment Anything Model 3, finds every object a short phrase
names, such as *curb ramp* or *traffic cone*, in an image or a video. It
outlines each object with a mask, and in a video it follows each one from frame
to frame under one id. Curio runs it with Hugging Face Transformers.

This is a model package: the model's node, the module that holds the node's
logic, and where the model's weights come from. The
[Model Catalog](../../docs/MODEL-CATALOG.md) lists it.

| Part | What it is | License |
|---|---|---|
| `models/checkpoint/` | The weights, Meta's `facebook/sam3`: the eight files Transformers reads, 3.4 GB, downloaded on first use from an identical copy, `jetjodh/sam3` on Hugging Face at revision `1aa50ce07302cb375f85d8084b68a0fb378b8d85`. Never shipped | SAM License (`LICENSE`), published by Meta |
| `sources/track-objects.py` | The Track Objects node's code: its settings and one call of `track_objects` | MIT |
| `sources/sam3_tracking.py` | The module the node calls: `track_objects`, SAM 3 through a collection's videos | MIT |

## Nodes

| Canonical id | Label | Input | Output |
|---|---|---|---|
| `model.curio.sam3/track-objects` | Track Objects | A collection's rows, each video with a `path` | One row per video: its overlay, a count of the objects of each label, and the path of its tracks |

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
    labels=LABELS, every_seconds=EVERY_SECONDS, from_seconds=FROM_SECONDS,
    to_seconds=TO_SECONDS, max_seconds=MAX_SECONDS, width=WIDTH,
)
```

The node hands the function Curio's plumbing: the model, whose `path` is the
folder of its weights, and `curio_derived_file`, which says where the overlay
and the tracks are kept. Empty `LABELS`, a part longer than `MAX_SECONDS` and a
video not cached yet stop the node before SAM 3 loads.

The input is a collection's rows, as a Data Loading node gives them with
`curio_load_collection(...)`, each video's file cached on the machine. Rows
that are not videos are left out.

## Settings

The constants at the top of the node's code, each handed to `track_objects` as
the argument of its name in lowercase:

| Setting | Default | What it sets |
|---|---|---|
| `LABELS` | curb ramp, curb cut, tactile paving, bollard, pole, construction barrier, traffic cone, person | What to look for, in plain words. SAM 3 takes any short noun phrase, not only the package's labels below. |
| `EVERY_SECONDS` | `0.5` | The gap between two frames SAM 3 looks at. |
| `FROM_SECONDS`, `TO_SECONDS` | `0`, `None` | The part of each video to track, in seconds from its start; `None` is its end. |
| `MAX_SECONDS` | `300` | The most video one run takes. SAM 3 keeps every frame it looked at until the video's end, so a longer part stops the node, with a message naming the limit and the two settings above. |
| `WIDTH` | `960` | The widest frames are read and drawn at. A narrower video keeps its size. |

The node runs on the GPU when the machine has one (CUDA, in bfloat16, or
Apple's MPS), else on the CPU.

## Output

Each video comes back as one row: its overlay, a video of the frames SAM 3
looked at, each object's mask and box drawn in its label's color with its label
and id. Simple View plays it, a frame every `EVERY_SECONDS`, so it runs as long
as the part it tracked. It is H.264, which every browser plays. The row keeps
the video's own columns, its fields and its position, and has:

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

Both files are kept beside the collection's other files derived from that video,
under one name per video and `FROM_SECONDS`, so a run again replaces them.

## Labels

The package's labels are 35 phrases for what a camera looking at a sidewalk
sees, in seven groups. The node's `LABELS` starts with eight of them.

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
