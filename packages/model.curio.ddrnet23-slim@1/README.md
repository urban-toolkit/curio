# `model.curio.ddrnet23-slim@1`: DDRNet23-Slim (street scenes)

DDRNet23-Slim labels every pixel of a street photo with one of the 19
Cityscapes classes: road, sidewalk, building, wall, fence, pole, traffic light,
traffic sign, vegetation, terrain, sky, person, rider, car, truck, bus, train,
motorcycle and bicycle. It runs on the CPU with onnxruntime, and gives the same
results on every x86 CPU.

This is a model package: the model's weights and its node. The
[Model Catalog](../../docs/MODEL-CATALOG.md) lists it.

| Part | What it is | License |
|---|---|---|
| `models/ddrnet23_slim.onnx`, `models/ddrnet23_slim.data` | The weights: the w8a8 ONNX export published by Qualcomm AI Hub Models, its int8 zero points stored as uint8 by [`scripts/onnx_zero_points_to_uint8.py`](../../scripts/onnx_zero_points_to_uint8.py), which computes the same values | MIT; trained on Cityscapes (`LICENSE`) |
| `sources/image-segmentation.py` | The Image Segmentation node's code: its settings and a call of the [Segmentation](../curio.segmentation@1/README.md) package's `segment_images` | MIT |

## Nodes

| Canonical id | Label | Input | Output |
|---|---|---|---|
| `model.curio.ddrnet23-slim/image-segmentation` | Image Segmentation | A collection's rows, each with a `path` | The same rows with each class's share of the image |

**Image Segmentation** labels every pixel of each image with the model. Each
row gains the share of its pixels every class covers (`<class>_pct`, in
percent), the class covering most (`dominant_class`, `dominant_pct`), and an
`overlay_url` that shows the image tinted by class. The input is a
collection's rows, as a Data Loading node gives them with
`curio_load_collection(...)`: images from the Data Catalog, or added from the
Discovery Catalog (Mapillary, a storage folder). Every input column is kept, so
the output goes straight to Spatial Join, Vega-Lite or Simple View.

A new node opens with this code, under a docstring that says what it does:

```python
from semantic_segmentation import segment_images

model = curio_load_model("model.curio.ddrnet23-slim")
classes = None  # every class the model names

return segment_images(input_0, model, curio_derived_file, classes=classes)
```

Set `classes` to the labels to report, such as
`["vegetation", "sky", "road"]`, or leave `None` for every label.
`segment_images` is the [Segmentation](../curio.segmentation@1/README.md)
package's, which this package names in `dependencies.packages`: adding
DDRNet23-Slim adds it too, and the header above the node's code lists it
under **Functions**.

A typical pipeline:

```
Data Loading (photos) → Image Segmentation → Simple View → Spatial Join → Vega-Lite
                                                                ↑
                                          Data Loading (neighborhood polygons)
```

See [`docs/examples/10-street-vision-cv-analysis.md`](../../docs/examples/10-street-vision-cv-analysis.md) for a worked walkthrough.

## Other models

A model from the Discovery Catalog's **Hugging Face models** lands in the
**Model Catalog** as a model package of its own, with an Image Segmentation
node that runs it: this node, with its code naming that model, and the
Segmentation package in its `dependencies.packages`. To run it in this node
instead, drag it from the Model Catalog onto the node: the node's code now
names it in `curio_load_model("<model id>")`.

## Setup

Curio installs `onnxruntime` with the package, and the Segmentation package
with its libraries. They are installed for you when Curio starts with
`--with-examples`, and when you open a dataflow that names the package, such
as example 10.

## Origin

The original CV pipeline and node design was contributed by
[@ManeeshJupalle](https://github.com/ManeeshJupalle) in
[PR #120](https://github.com/urban-toolkit/curio/pull/120) as a CS 524
university project.
