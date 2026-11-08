---
name: sam3-tracking
description: >-
  Use this skill when a dataflow uses SAM 3 (model.curio.sam3@1) and a task writes, wires or fixes
  its Track Objects node, which follows objects named in words, such as curb ramp or traffic cone,
  through a collection's videos, or reads what the node returns: an overlay video, how many objects
  of each label it followed, and a table of their tracks. It gives the node's settings, its output's
  columns, how a later node reads the tracks, and what each of its stops means.
license: MIT
compatibility: Written for Curio's agents, on a dataflow that uses Curio's SAM 3 model package, model.curio.sam3@1.
metadata:
  author: curio
  version: "1.0.0"
  curio-templates: track-objects
---
## SAM 3 and Track Objects

SAM 3 is a model of the Model Catalog that finds every object a short phrase names, such as `curb ramp` or `traffic cone`, and follows each one from frame to frame of a video under one id. Its package's one node, Track Objects, `model.curio.sam3/track-objects`, runs it through every video of a collection.

### Which node

- Objects named in words, followed through a collection's videos, are a Track Objects node, wired from the Data Loading node that loads the collection (`curio_load_collection(...)`). Rows that are not videos are left out.
- Its code holds its settings and one call of `track_objects`, from the package's module `sam3_tracking`. Change what it does through the settings, and keep the call, which hands it `curio_load_model("model.curio.sam3")`, a literal id Curio reads, and `curio_derived_file`.
- An Image Segmentation node does not run SAM 3: `curio_segment` refuses a concept segmentation model, and a model dropped on a node swaps only for one of the node's type.
- A table of the objects is a Python Computation node that reads the tracks (below); a chart of them is a Vega-Lite node on that table.

### Its settings

The constants at the top of its code, each passed to `track_objects` as the argument of its name in lowercase:

- `LABELS`: the phrases to look for, a list of short noun phrases. Any phrase works; the 35 labels of the model are the prompts its package names, such as sidewalk, crosswalk, curb ramp, tactile paving, pole, bollard, trash bin, traffic cone, construction barrier, pothole, person, car and bicycle.
- `EVERY_SECONDS`, 0.5 by default: the gap between two frames SAM 3 looks at. A longer gap runs faster and can miss what passes quickly.
- `FROM_SECONDS` and `TO_SECONDS`, 0 and None by default (None is the video's end): the part of each video to track, in seconds from its start.
- `MAX_SECONDS`, 300 by default: the most video one run takes. SAM 3 keeps every frame it looked at until the video's end, so a larger value can run out of memory: pick a part with `FROM_SECONDS` and `TO_SECONDS` instead.
- `WIDTH`, 960 by default: the widest frames are read and drawn at.

### What it returns

One row per video, its overlay: the frames SAM 3 looked at, each object's mask and box drawn in its label's color with its label and id, which Simple View plays, a frame every `EVERY_SECONDS`. The row keeps the video's own columns, its fields and its position, and has:

- `file_id`, `path`, `thumbnail` and `image_url`: the overlay's;
- `video_file_id` and `name`: the video tracked;
- `t_s`: where the overlay starts in the video, so a time in the video is `t_s` plus the time in the overlay;
- `duration_s`, `fps`, `width` and `height`: the overlay's;
- `<label>_objects`: how many objects of each label of `LABELS` it followed, a space written as `_`, such as `traffic_cone_objects`;
- `tracks`: the Parquet file Track Objects wrote of the video's objects, one row per object: `video_file_id`, `video`, `object_id` (the id drawn on the overlay), `label`, `start_s` and `end_s` (the first and the last time it was seen, in seconds from the video's start), `frames` (how many of the frames looked at it was seen in), `largest_share` (the largest share of a frame its mask covered, 0 to 1) and `mean_score`.

A Python Computation node wired from Track Objects puts every video's objects in one table:

```python
import pandas as pd

return pd.concat([pd.read_parquet(path) for path in input_0["tracks"]])
```

A swimlane of that table, one bar per object, is a Vega-Lite `bar` with `start_s` on `x`, `end_s` on `x2`, `object_id` on `y` and `label` on `color`.

### When it stops

- *The weights of model 'model.curio.sam3' are not on this Curio...*: whoever runs this Curio fetches them, once, with `python scripts/fetch_model_weights.py model.curio.sam3`. No change to the dataflow helps: say so, and change no node.
- *`<file>`: Track Objects takes 300 s of video in one run; set FROM_SECONDS and TO_SECONDS to the part to track*: set them to a part of at most `MAX_SECONDS`, such as 0 and 60 for the first minute.
- *`<file>` does not say how long it is*: set `TO_SECONDS` to where to stop.
- *`<file>` is not on this machine yet; cache the collection's files first*: the collection's videos are in a bucket and not cached yet.
- *LABELS is empty*: name at least one thing to look for.
