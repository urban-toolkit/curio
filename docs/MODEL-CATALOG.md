# Model Catalog

The Model Catalog is where Curio keeps the **trained models** your nodes can run. A model ships with Curio, or you add one from the [Discovery Catalog](DISCOVERY-CATALOG.md). A node such as **Image Segmentation** runs the model its code names, and you choose which by dragging a model onto it.

Curio has six catalogs: the [Node Catalog](NODE-CATALOG.md) holds the nodes you drop on the canvas, the [Data Catalog](DATA-CATALOG.md) the datasets they read, the Model Catalog the models they run, the [Agent Catalog](AGENT-CATALOG.md) the assistants you attach to them, the [Discovery Catalog](DISCOVERY-CATALOG.md) the portals, storage, services and models you take datasets and models from, and the [Scenario Catalog](SCENARIO-CATALOG.md) the scenarios saved in your projects.

This guide is in six parts, plus operator notes:

- [1. What is the Model Catalog?](#1-what-is-the-model-catalog): models, what ships, and where they are stored.
- [2. Surfaces and workflows](#2-surfaces-and-workflows): the page, the canvas drawer and palette, the action matrix, and walkthroughs.
- [3. Using a model in a dataflow](#3-using-a-model-in-a-dataflow): dragging a model onto a node, and what the node does with it.
- [4. Runtimes and libraries](#4-runtimes-and-libraries): ONNX and Transformers, and what each needs.
- [5. Importing, publishing, and sharing](#5-importing-publishing-and-sharing): where models come from, and sharing a dataflow that names one.
- [6. The manifest](#6-the-manifest): the fields a model package declares.
- [Operator notes](#operator-notes): shipping a model of your own.

---

## 1. What is the Model Catalog?

### Concept

A **model** is a model package: a node package of kind `model` that holds the model's weights under `models/`, the weights' license, and the node that runs the model. A model that ships with Curio is identified by `model.<publisher>.<name>` and a major version; a model you add gets an id of its own, such as `imported.x1f3a9c2b7d40`:

```
model.curio.ddrnet23-slim@1/
  manifest.json
  LICENSE
  models/ddrnet23_slim.onnx
  models/ddrnet23_slim.data
```

The manifest's `model` block says which runtime runs the model (**ONNX** or **Transformers**), its type (semantic segmentation: a class for every pixel; image to image: images in, an image out; or node regression: a graph in, its node features and edges, and values for each node out), the **labels** of its classes, and how an image is prepared for it. A node's code names the model it runs; a dataflow lists the model's package with the other packages it uses.

### What ships with Curio

| Model | Runtime | Labels | License |
|---|---|---|---|
| DDRNet23-Slim (street scenes) | ONNX | The 19 Cityscapes classes: road, sidewalk, building, wall, fence, pole, traffic light, traffic sign, vegetation, terrain, sky, person, rider, car, truck, bus, train, motorcycle, bicycle | MIT; trained on Cityscapes |
| Deep Umbra (accumulated shadows) | ONNX | None: image to image, building heights in, the share of a day in shadow out | Used with the permission of SCOUT's authors |
| SCOUT weather GNN (weather at road nodes) | ONNX | None: node regression, a road graph's nodes and the weather at each in, five weather values at each node out | Used with the permission of SCOUT's authors |

Each package's code is MIT; its weights keep their own license.

DDRNet23-Slim is about 23 MB and labels a street photo in a fraction of a second on a CPU. Its package, `model.curio.ddrnet23-slim@1`, has the **Image Segmentation** node, which runs it on a collection's photos ([example 10](examples/10-street-vision-cv-analysis.md)).

Deep Umbra, [SCOUT](https://github.com/urban-toolkit/scout)'s shadow model, is about 10.5 MB. Its package, `model.scout.deep-umbra@1`, has the **Accumulated Shadow** node, which runs it on a raster of building heights ([example 24](examples/24-scout-building-rasters.md)). A pip install downloads its weights from GitHub the first time a node runs it ([Installation from pip](USAGE.md#installation-from-pip)).

The weather GNN, SCOUT's weather graph network, is about 52 KB. Its package, `model.scout.weather-gnn@1`, has the **Weather Routing** node, which runs it on the road graph it builds from a roads layer, to weigh each road by the weather before routing ([the WeatherRouting test dataflow](examples/dataflows/WeatherRouting.json)).

### Storage layers

| Layer | On disk | Written by |
|---|---|---|
| **Shipped model packages** | `<repo_root>/packages/<packageId>@<major>/`, the weights under its `models/` | The release. Nothing in the app writes here, and a shipped model package cannot be deleted. |
| **Your model packages** | `.curio/users/<user-key>/packages/<packageId>@<major>/` | **Add to Model Catalog** in the Discovery Catalog, importing a model package's archive, or publishing one. A copy of a shipped package, added or brought by a dataflow, holds no weights: they are read where they ship. |
| **A node's model** | The node's code, `curio_load_model("<id>")`, saved with the dataflow | A drop on the node, or what you type. |

A node runs a model whose package is in your store: one you added, one a dataflow that names it brought, or one installed for the examples. A model whose package your store does not hold stops the node, with a message saying to add it.

---

## 2. Surfaces and workflows

- **The `/catalog/models` page** lists the models: the shipped ones and yours. Reach it from the **Model Catalog** tab. Search with **Search models**, sort, and filter by **By origin** (**Shipped with Curio** or **Downloaded**) or **By runtime** in the left rail. Click a card to describe it in the right-hand drawer.
- **The Model Catalog drawer**, on the canvas. Open it from the **Model Catalog** button in the top bar, or from the left Tools panel's **Model Catalog** dropdown and **Browse Model Catalog +**.
- **The Models dropdown**, in the left Tools panel, lists your models as cards to drag onto a node.

A model's details show its **Identifier**, **Version**, **Runtime**, **Input**, **Labels**, **License** (with **View license**), **Homepage** and **Origin**. A model you added also says where it was **Downloaded from**: the source and the model's page there.

### Action matrix

| Action | Where | What it changes | What you see |
|---|---|---|---|
| **View details** | A card, the drawer, or the canvas drawer | Nothing | The model's details. |
| **View license** | The details | Nothing | The model's license text. |
| **Drag onto a node** | The **Model Catalog** dropdown or the canvas drawer | The node's code | The node's `curio_load_model(...)` line names the model. A node whose code calls no `curio_load_model` says *This node does not run a model*. |
| **Drag onto the canvas** | The **Model Catalog** dropdown or the canvas drawer | The dataflow | A new node where you drop it, its `curio_load_model(...)` line naming the model: the model's own node (**Image Segmentation** for DDRNet23-Slim, **Accumulated Shadow** for Deep Umbra, **Weather Routing** for the weather GNN), else another node of the dataflow that runs a model. When no node in the dataflow runs a model, nothing is added and a message names the package to add from the Node Catalog. |
| **Delete** | A model you added: its card or the drawer | Your Model Catalog loses the model | A confirmation first; the model's package leaves every dataflow that lists it, and nodes that name it fail the next time they run. A shipped model offers no **Delete**. |
| **Add to Model Catalog** | A **Hugging Face models** row, in the Discovery Catalog | Your Model Catalog gains a model | A progress bar, then *"Added `<name>` to your Model Catalog."* with **View model**. |

### Workflows

**I want to label street photos.** Load the photos with a **Data Loading** node (`curio_load_collection(...)`), then add the **Image Segmentation** node of DDRNet23-Slim's package and wire the two. [Example 10](examples/10-street-vision-cv-analysis.md) does this end to end.

**I want a different model.** Open the Discovery Catalog's **Hugging Face models**, search, and click **Add to Model Catalog** on a model ([DISCOVERY-CATALOG.md part 4](DISCOVERY-CATALOG.md#adding-a-model)). On the canvas, open **Model Catalog** in the left Tools panel and drag it onto the Image Segmentation node. Set `classes` in the node's code to the labels you want, or `None` for all of them; the model's details list its labels.

**A node says a model is not one of your models.** The node names a model whose package is not in your store, for example in a dataflow someone shared with you. Add that model, or drag one of yours onto the node.

---

## 3. Using a model in a dataflow

A node's code loads its model with `curio_load_model("<id>")`. **Image Segmentation** passes the model to `curio_segment`:

```python
model = curio_load_model("model.curio.ddrnet23-slim")
classes = ["vegetation", "terrain", "sky", "road", "sidewalk", "building"]

return curio_segment(input_0, model, classes)
```

A new Image Segmentation node opens with `classes = None`, every class the model names.

`curio_segment` reads a collection's rows, each with a `path`, as a Data Loading node gives them for images from the Data or Discovery Catalog. Each row comes back with the results as its first columns:

| Column | What it holds |
|---|---|
| `dominant_class`, `dominant_pct` | Of the classes the node asks for, the one that covers most of the image, and its share of the pixels, in percent. |
| `<class>_pct` | Each class asked for, as its share of all the image's pixels, in percent. |
| `overlay_url` | The image tinted by class, which **Simple View** shows beside the image. |
| `segment_error` | Empty, or why the row was skipped: *the image is not on this machine* when the row's file is missing, *the image could not be read* when the file is not an image Curio can open or is cut short. |

Every input column follows. A class the model does not label stops the node, with a message naming the labels it has.

Dragging a model onto a node rewrites the id in its first `curio_load_model(...)` call and nothing else, so `classes` stays as you set it. The dataflow saves the node's code, so it reopens with the same model.

An image-to-image or node-regression model is run by the node made for it, which prepares the model's inputs itself and calls `model.run({input name: array})`; it returns the graph's outputs in order. **Accumulated Shadow** runs Deep Umbra this way, one map tile at a time, and **Weather Routing** runs the weather GNN on its road graph's node features and edges. A model package whose node ships no code of its own opens with a `model.run` skeleton that names each array the model's graph takes. `curio_segment` refuses these models.

---

## 4. Runtimes and libraries

| Runtime | What runs it | Libraries |
|---|---|---|
| **ONNX** | `onnxruntime`, on the CPU | `onnxruntime`, installed when you add the model. |
| **Transformers** | Hugging Face Transformers, on the CPU | `torch`, `transformers` and `safetensors`, installed when you add the model. |

A model's libraries install the way a node package's do. When they do not install, the model is still added, and the message says why; the node then says what to install when it runs. An account that may not install libraries cannot add a model.

A node reads its model from your store and needs no network to run it.

---

## 5. Importing, publishing, and sharing

A model ships with the deployment, or you add one from the Discovery Catalog's **Hugging Face models**, or import a model package's archive. A model you add is yours: every dataflow you open can run it, and nobody else on the install sees it.

A dataflow names its models by id, and lists their packages. Someone you share it with runs a shipped model once opening the dataflow has added its package. A model you added has an id of your own, so they add a model of their own and drag it onto the node.

---

## 6. The manifest

A model package's `manifest.json` is a node package's ([NODE-CATALOG.md](NODE-CATALOG.md)) with `"kind": "model"` and a `model` block:

| Field | Required | What it declares |
|---|---|---|
| `kind` | Yes | `model`. |
| `id`, `name`, `version`, `compatibility.major`, `publisher`, `license`, `templates` | Yes | As every node package declares them. `license` is the license of the package's code; `id` is the id a node loads the model by. |
| `model.type` | Yes | `semantic-segmentation`, `image-to-image` or `node-regression`. |
| `model.runtime` | Yes | `onnx` or `transformers`. |
| `model.entry` | Yes | For `onnx`, the graph file; for `transformers`, the folder of the checkpoint. A path under `models/`. |
| `model.labels` | | The classes, in the order the model numbers them. An `image-to-image` or `node-regression` model has none. |
| `model.input` | For an `onnx` image model | A `node-regression` model reads a graph of any size and has none. How an image is prepared: `width` and `height` (8 to 8192 pixels), `dtype` (`uint8` or `float32`), `layout` (`NCHW`, or `NHWC` for an `image-to-image` model), `scale`, and an optional `mean` and `std` of three numbers each. |
| `model.license`, `model.licenseFile` | `model.license` | The weights' license, and the file in the package that holds its text. |
| `model.publisher`, `model.homepage`, `model.sizeBytes` | | Who published the weights, where they are described, and their size. Shown on the card and in the details. |

A template with no `source` opens with the cell Curio writes for the model's type.

---

## Operator notes

**Shipping a model.** Add its model package to `packages/` and restart; `--packages-root` moves that folder. The Docker image bakes `packages/` in. A model there must be one Curio may redistribute, with the weights' license in the package.

---

## See also

- [`docs/DISCOVERY-CATALOG.md`](DISCOVERY-CATALOG.md#adding-a-model): adding a model from Hugging Face.
- [`docs/NODE-CATALOG.md`](NODE-CATALOG.md): DDRNet23-Slim's package and its Image Segmentation node, and the packages Curio ships.
- [`docs/examples/10-street-vision-cv-analysis.md`](examples/10-street-vision-cv-analysis.md): two models over the same street photos.
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md#model-catalog): how models are stored, staged for a run, and resolved.
