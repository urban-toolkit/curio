# `model.curio.ddrnet23-slim@1`: DDRNet23-Slim (street scenes)

DDRNet23-Slim labels every pixel of a street photo with one of the 19
Cityscapes classes: road, sidewalk, building, wall, fence, pole, traffic light,
traffic sign, vegetation, terrain, sky, person, rider, car, truck, bus, train,
motorcycle and bicycle. It runs on the CPU with onnxruntime.

This is a model package: the model's weights and its node. The
[Model Catalog](../../docs/MODEL-CATALOG.md) lists it.

| Part | What it is | License |
|---|---|---|
| `models/ddrnet23_slim.onnx`, `models/ddrnet23_slim.data` | The weights: the w8a8 ONNX export published by Qualcomm AI Hub Models | MIT; trained on Cityscapes (`LICENSE`) |
| The Image Segmentation node | Its cell, which Curio writes for a segmentation model | MIT |

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

A new node opens with this cell:

```python
model = curio_load_model("model.curio.ddrnet23-slim")
classes = None  # every class the model names

return curio_segment(input_0, model, classes)
```

Set `classes` to the labels to report, such as
`["vegetation", "sky", "road"]`, or leave `None` for every label.

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
node that runs it. To run it in this node instead, drag it from the Model
Catalog onto the node: the node's code now names it in
`curio_load_model("<model id>")`.

## Setup

Curio installs `onnxruntime` with the package. It is installed for you when
Curio starts with `--with-examples`, and when you open a dataflow that names
it, such as example 10.

## Origin

The original CV pipeline and node design was contributed by
[@ManeeshJupalle](https://github.com/ManeeshJupalle) in
[PR #120](https://github.com/urban-toolkit/curio/pull/120) as a CS 524
university project.
