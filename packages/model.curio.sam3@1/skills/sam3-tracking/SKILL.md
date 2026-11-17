---
name: sam3-tracking
description: >-
  Use this skill when a dataflow uses SAM 3 (model.curio.sam3@1) and a task writes, wires or fixes
  its Track Objects node, which follows objects named in words, such as curb ramp or traffic cone,
  through a collection's videos, or its Segment Images node, which finds them in a collection's
  images or in the frames Sample Video Frames samples, or reads what either returns: an overlay
  video, counts and a table of tracks, or each image's counts and shares per label and its overlay.
  It gives each node's settings, its output's columns, how a later node reads them, and what each of
  its stops means.
license: MIT
compatibility: Written for Curio's agents, on a dataflow that uses Curio's SAM 3 model package, model.curio.sam3@1.
metadata:
  author: curio
  version: "1.0.0"
  curio-templates: track-objects segment-images
---
## SAM 3, Track Objects and Segment Images

SAM 3 is a model of the Model Catalog that finds every object a short phrase names, such as `curb ramp` or `traffic cone`, and follows each one from frame to frame of a video under one id. Its package has two nodes: Track Objects, `model.curio.sam3/track-objects`, runs it through every video of a collection, and Segment Images, `model.curio.sam3/segment-images`, runs it on every image of a collection, or every frame Sample Video Frames sampled from one.

### Which node

- Objects named in words, followed through a collection's videos, are a Track Objects node, wired from the Data Loading node that loads the collection (`curio_load_collection(...)`). Rows that are not videos are left out.
- Its code holds its settings and one call of `track_objects`, from the package's module `sam3_tracking`. Change what it does through the settings, and keep the call, which hands it `curio_load_model("model.curio.sam3")`, a literal id Curio reads, and `curio_derived_file`.
- Objects named in words, found in a collection's images or in a video's frames, with how much of each image they cover, are a Segment Images node (below), wired from the Data Loading node of the images, or from a Sample Video Frames node for a video's frames.
- An Image Segmentation node does not run SAM 3: Segmentation's `segment_images` refuses a concept segmentation model, and a model dropped on a node swaps only for one of the node's type.
- A table of the objects is a Python Computation node that reads the tracks (below); a chart of them is a Vega-Lite node on that table.

### Its settings

The constants at the top of its code, each passed to `track_objects` as the argument of its name in lowercase:

- `LABELS`: the phrases to look for, a list of short noun phrases. Any phrase works; the 35 labels of the model are the prompts its package names, such as sidewalk, crosswalk, curb ramp, tactile paving, pole, bollard, trash bin, traffic cone, construction barrier, pothole, person, car and bicycle.
- `EVERY_SECONDS`, 0.5 by default: the gap between two frames SAM 3 looks at. A longer gap runs faster and can miss what passes quickly.
- `FORGET_SECONDS`, 10 by default: SAM 3 lets go of an object it has not seen for that long. The object's track ends where it was last seen, and if it comes back it is a new object, with a new id and a track of its own, counted again in `<label>_objects`. Raise it when an object hidden for longer, such as behind a parked truck, should keep one id; each frame then takes longer, since SAM 3 follows every object it saw in that time. None follows every object to the part's end.
- `FROM_SECONDS` and `TO_SECONDS`, 0 and None by default (None is the video's end): the part of each video to track, in seconds from its start.
- `MAX_FRAMES`, 450 by default: the most frames of a video one run looks at. A part of W seconds needs W / `EVERY_SECONDS` frames, rounded up, so a 15 minute video fits whole at a frame every 2 s. Keep it, and fit more of a video with a larger `EVERY_SECONDS`, or track it in parts with `FROM_SECONDS` and `TO_SECONDS`.
- `WIDTH`, 960 by default: the widest frames are read and drawn at.

### What it returns

One row per video, its overlay: the frames SAM 3 looked at, each object's mask and box drawn in its label's color with its label and id, which Simple View plays in real time, each frame at its own time in the video. The row keeps the video's own columns, its fields and its position, and has:

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

- *Curio could not download ... of the weights of model.curio.sam3*, or *The weights of model 'model.curio.sam3' are not on this Curio*: the first run downloads the weights, and that download failed for the reason the message gives. Whoever runs this Curio can fetch them once, with `python scripts/fetch_model_weights.py model.curio.sam3`. No change to the dataflow helps: say so, and change no node.
- *`<file>`: Track Objects looks at 450 frames of a video at most in one run, and ... is ... frames; raise EVERY_SECONDS to ... or more, or set FROM_SECONDS and TO_SECONDS to a shorter part, such as ...*: keep `MAX_FRAMES` and do one of the two: set `EVERY_SECONDS` to the gap the message names or a larger one, or set `FROM_SECONDS` and `TO_SECONDS` to a part that fits, such as the one it names, or 0 and 60 for the first minute.
- *`<file>` does not say how long it is*: set `TO_SECONDS` to where to stop.
- *`<file>` is not on this machine yet; cache the collection's files first*: the collection's videos are in a bucket and not cached yet.
- *LABELS is empty*: name at least one thing to look for.

## Segment Images

Its code holds its settings and one call of `find_in_images`, from the package's module `sam3_images`, which hands it `curio_load_model("model.curio.sam3")` and `curio_derived_file`. It reads the images' `path`, so wire it from rows that have one: a collection's images, or Sample Video Frames' frames.

### Its settings

- `LABELS`: the phrases to look for. Its code starts with the model's 35 labels, in their seven groups; any short noun phrase works, and fewer labels run faster.
- `THRESHOLD`, 0.5 by default: the score SAM 3 needs to keep an object. Lower it to find more, and less surely.
- `WIDTH`, 960 by default: the widest an image is read and its overlay drawn.
- `MAX_IMAGES`, 300 by default: the most images one run looks at, as many as Sample Video Frames samples from one video by default.

### What it returns

The input's rows, each with the results first, the columns Image Segmentation gives:

- `dominant_class` and `dominant_pct`: the label whose objects cover the most of the image, and that share in percent; where SAM 3 found nothing, `dominant_class` is missing (NaN, so test it with `.isna()`) and `dominant_pct` is 0;
- for each label of `LABELS`, `<label>_pct`, the share of the image its objects cover together, in percent, the label spelled as written (`curb ramp_pct`), and `<label>_objects`, how many objects of it SAM 3 found, a space written as `_` (`curb_ramp_objects`);
- `overlay_url`: the image with each object's mask, box and label drawn, which Simple View shows beside the image;
- `segment_error`: why a row has no results, such as an image not on this machine; missing otherwise, so `input_0[input_0["segment_error"].isna()]` keeps the rows SAM 3 looked at.

Then come the row's own columns: a frame's `t_s`, its time in the video, and its video's fields. The mean share of each label over the images is a Python Computation node:

```python
import pandas as pd

labels = [c[: -len("_pct")] for c in input_0.columns if c.endswith("_pct") and c != "dominant_pct"]
shares = input_0[[f"{label}_pct" for label in labels]].mean()
return pd.DataFrame({"label": labels, "mean_pct": shares.to_numpy()})
```

### When it stops

- The weights' messages are Track Objects' (above).
- *Segment Images looks at N images in one run (MAX_IMAGES), and its input has M*: sample fewer frames upstream (a larger `EVERY_SECONDS` in Sample Video Frames), keep fewer rows, or raise `MAX_IMAGES`.
- *LABELS names ... more than once*, or *LABELS would give two results one column*: name each label once, and rename one that would be read as another's column, such as `dominant`.
- *Segment Images reads rows with a path*: wire it from a collection's rows or Sample Video Frames' frames.
- A row whose `segment_error` says *the image is not on this machine* or *the image could not be read* gets no results; the other rows do.
