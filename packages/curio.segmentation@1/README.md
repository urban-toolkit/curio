# `curio.segmentation@1`: Segmentation

The code a segmentation model's node runs: one module,
`sources/semantic_segmentation.py`, and no node of its own. The packages whose
nodes run a segmentation model name it in `dependencies.packages`, so their
nodes import it, and the header above their code lists its function under
**Functions**:

- DDRNet23-Slim's Image Segmentation ([`model.curio.ddrnet23-slim@1`](../model.curio.ddrnet23-slim@1/README.md));
- the Image Segmentation node of a segmentation model added from the
  Discovery Catalog's **Hugging Face models**.

Adding one of those packages adds this one, and so do opening a dataflow
that uses one and starting Curio with `--with-examples`.

## `segment_images`

```python
from semantic_segmentation import segment_images

model = curio_load_model("model.curio.ddrnet23-slim")
classes = None  # every class the model names

return segment_images(input_0, model, curio_derived_file, classes=classes)
```

`segment_images(images, model, derived_file, *, classes=None, overlays=True)`
labels every pixel of each image with a model `curio_load_model` loaded, the
way its manifest says to run it: an `onnx` graph on onnxruntime, a
`transformers` checkpoint with its own image processor and torch, both on
the CPU, on as many threads as `OMP_NUM_THREADS` names, else on one per
core. The model's package declares that runtime.

- `images`: a collection's rows, each with a `path`, as Data Loading gives
  them with `curio_load_collection(...)`.
- `classes`: the model's labels to report, such as
  `["vegetation", "sky", "road"]`; `None` reports every label it names. A
  label it does not name stops the node, with the labels it has.
- `derived_file`: where each overlay goes, `curio_derived_file`; `None`
  writes none, and so does `overlays=False`.

It returns the rows with the results first: `dominant_class` and
`dominant_pct`, a `<class>_pct` per class (its share of all the image's
pixels, in percent), `overlay_url` (the image tinted by class, which Simple
View shows) and `segment_error` (why a row has no results: its image is not
on this machine, or cannot be read). Every input column follows. A frame
Sample Video Frames took from a video gets its video's overlay at the
frame's time. Street classes keep the colours street segmentation maps draw
them in; any other class gets a hue of its own.

## Setup

Curio installs `numpy`, `pandas` and `pillow` with the package.
