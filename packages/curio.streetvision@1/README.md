# Street Vision (curio.streetvision@1)

One node for street-level computer vision in Curio:

- **Image Segmentation.** Labels every pixel of each image with a model from the Model Catalog. Each row gains the share of its pixels every class covers (`<class>_pct`, in percent), the class covering most (`dominant_class`, `dominant_pct`), and an `overlay_url` that shows the image tinted by class. The input is a collection's rows, as a Data Loading node gives them with `curio_collection(...)`: images from the Data Catalog, or added from the Discovery Catalog (Mapillary, Google Street View, a storage folder). Every input column is kept, so the output goes straight to Spatial Join, Vega-Lite or Simple View.

A typical pipeline:

```
Data Loading (photos) → Image Segmentation → Simple View → Spatial Join → Vega-Lite
                                                                ↑
                                          Data Loading (neighborhood polygons)
```

See [`docs/examples/10-street-vision-cv-analysis.md`](../../docs/examples/10-street-vision-cv-analysis.md) for a worked walkthrough.

## Models

A new node runs **DDRNet23-Slim**, which ships with Curio. It labels street scenes with the 19 Cityscapes classes: road, sidewalk, building, wall, fence, pole, traffic light, traffic sign, vegetation, terrain, sky, person, rider, car, truck, bus, train, motorcycle and bicycle.

To use another model:

1. Open the **Discovery Catalog**, choose **Hugging Face models**, and add one. It lands in the **Model Catalog**.
2. Drag it from the Model Catalog onto the node. The node's code now names it in `curio_model("<model id>")`.
3. Set `classes` in the code to the labels to report, or `None` for every label the model names. The model's page in the Model Catalog lists its labels.

## Setup

Open `/catalog` in Curio and click **Add to all projects** on Street Vision. The first add installs `onnxruntime`. A model that runs on Transformers brings `torch`, `transformers` and `safetensors`, installed when you add it to the Model Catalog.

Models run on the CPU.

## Origin

The original CV pipeline + node design was contributed by [@ManeeshJupalle](https://github.com/ManeeshJupalle) in [PR #120](https://github.com/urban-toolkit/curio/pull/120) as a CS 524 university project.
