# Model Catalog

The Model Catalog is where Curio keeps the **trained models** your nodes can run. A model ships with Curio, or you add one from the [Discovery Catalog](DISCOVERY-CATALOG.md). An **Image Segmentation** node runs the model its code names, and you choose which by dragging a model onto it.

Curio has six catalogs: the [Node Catalog](NODE-CATALOG.md) holds the nodes you drop on the canvas, the [Data Catalog](DATA-CATALOG.md) the datasets they read, the Model Catalog the models they run, the [Agent Catalog](AGENT-CATALOG.md) the assistants you attach to them, the [Discovery Catalog](DISCOVERY-CATALOG.md) the portals, storage, services and models you take datasets and models from, and the [Scenario Catalog](SCENARIO-CATALOG.md) the scenarios saved in your projects.

This guide is in six parts, plus operator notes:

- [1. What is the Model Catalog?](#1-what-is-the-model-catalog): models, what ships, and where they are stored.
- [2. Surfaces and workflows](#2-surfaces-and-workflows): the page, the canvas drawer and palette, the action matrix, and walkthroughs.
- [3. Using a model in a dataflow](#3-using-a-model-in-a-dataflow): dragging a model onto a node, and what the node does with it.
- [4. Runtimes and libraries](#4-runtimes-and-libraries): ONNX and Transformers, and what each needs.
- [5. Importing, publishing, and sharing](#5-importing-publishing-and-sharing): where models come from, and sharing a dataflow that names one.
- [6. The manifest](#6-the-manifest): the fields a model declares.
- [Operator notes](#operator-notes): shipping a model of your own.

---

## 1. What is the Model Catalog?

### Concept

A **model** is a folder with a `manifest.json`, the model's files, and its license. A model that ships with Curio is identified by `model.<publisher>.<name>` and a major version; a model you add gets an id of its own, such as `imported.x1f3a9c2b7d40`:

```
model.curio.ddrnet23-slim@1/
  manifest.json
  LICENSE
  files/ddrnet23_slim.onnx
  files/ddrnet23_slim.data
```

The manifest says which runtime runs the model (**ONNX** or **Transformers**), its task (semantic segmentation: a class for every pixel), the **labels** of its classes, and how an image is prepared for it. A model is not a dataset and is never added to a dataflow: a node's code names the model it runs.

### What ships with Curio

| Model | Runtime | Labels | License |
|---|---|---|---|
| DDRNet23-Slim (street scenes) | ONNX | The 19 Cityscapes classes: road, sidewalk, building, wall, fence, pole, traffic light, traffic sign, vegetation, terrain, sky, person, rider, car, truck, bus, train, motorcycle, bicycle | MIT; trained on Cityscapes |

DDRNet23-Slim is about 23 MB and labels a street photo in a fraction of a second on a CPU. A new **Image Segmentation** node runs it.

### Storage layers

| Layer | On disk | Written by |
|---|---|---|
| **Shipped models** | `<repo_root>/models/<modelId>@<major>/`, or the directory `--models-root` names | The release. Nothing in the app writes here, and a shipped model cannot be deleted. |
| **Your models** | `.curio/users/<user-key>/models/` | **Add to Model Catalog** in the Discovery Catalog. |
| **A node's model** | The node's code, `curio_load_model("<id>")`, saved with the dataflow | A drop on the node, or what you type. |

---

## 2. Surfaces and workflows

- **The `/catalog/models` page** lists the models you can run: the shipped ones and yours. Reach it from the **Model Catalog** tab. Search with **Search models**, sort, and filter by **By origin** (**Shipped with Curio** or **Downloaded**) or **By runtime** in the left rail. Click a card to describe it in the right-hand drawer.
- **The Model Catalog drawer**, on the canvas. Open it from the **Model Catalog** button in the top bar, or from the left Tools panel's **Model Catalog** dropdown and **Browse Model Catalog +**.
- **The Models dropdown**, in the left Tools panel, lists your models as cards to drag onto a node.

A model's details show its **Identifier**, **Version**, **Runtime**, **Input**, **Labels**, **License** (with **View license**), **Homepage** and **Origin**. A model you added also says where it was **Downloaded from**: the source and the model's page there.

### Action matrix

| Action | Where | What it changes | What you see |
|---|---|---|---|
| **View details** | A card, the drawer, or the canvas drawer | Nothing | The model's details. |
| **View license** | The details | Nothing | The model's license text. |
| **Drag onto a node** | The **Model Catalog** dropdown or the canvas drawer | The node's code | The node's `curio_load_model(...)` line names the model. A node whose code calls no `curio_load_model` says *This node does not run a model*. |
| **Drag onto the canvas** | The **Model Catalog** dropdown or the canvas drawer | The dataflow | A new **Image Segmentation** node where you drop it, its `curio_load_model(...)` line naming the model. When no node in the dataflow runs a model, nothing is added and a message names the package to add from the Node Catalog. |
| **Delete** | A model you added: its card or the drawer | Your Model Catalog loses the model | A confirmation first; nodes that name it fail the next time they run. A shipped model offers no **Delete**. |
| **Add to Model Catalog** | A **Hugging Face models** row, in the Discovery Catalog | Your Model Catalog gains a model | A progress bar, then *"Added `<name>` to your Model Catalog."* with **View model**. |

### Workflows

**I want to label street photos.** Load the photos with a **Data Loading** node (`curio_load_collection(...)`), then add an **Image Segmentation** node from the Street Vision package and wire the two. It runs DDRNet23-Slim. [Example 10](examples/10-street-vision-cv-analysis.md) does this end to end.

**I want a different model.** Open the Discovery Catalog's **Hugging Face models**, search, and click **Add to Model Catalog** on a model ([DISCOVERY-CATALOG.md part 4](DISCOVERY-CATALOG.md#adding-a-model)). On the canvas, open **Model Catalog** in the left Tools panel and drag it onto the Image Segmentation node. Set `classes` in the node's code to the labels you want, or `None` for all of them; the model's details list its labels.

**A node says its model is not available.** The node names a model that is not in your Model Catalog, for example in a dataflow someone shared with you. Add that model, or another, and drag it onto the node.

---

## 3. Using a model in a dataflow

A node's code loads its model with `curio_load_model("<id>")`. **Image Segmentation** passes the model to `curio_segment`:

```python
model = curio_load_model("model.curio.ddrnet23-slim")
classes = ["vegetation", "terrain", "sky", "road", "sidewalk", "building"]

return curio_segment(arg, model, classes)
```

`curio_segment` reads a collection's rows, each with a `path`, as a Data Loading node gives them for images from the Data or Discovery Catalog. Each row comes back with the results as its first columns:

| Column | What it holds |
|---|---|
| `dominant_class`, `dominant_pct` | Of the classes the node asks for, the one that covers most of the image, and its share of the pixels, in percent. |
| `<class>_pct` | Each class asked for, as its share of all the image's pixels, in percent. |
| `overlay_url` | The image tinted by class, which **Simple View** shows beside the image. |
| `segment_error` | Empty, or why the row was skipped: *the image is not on this machine* when the row's file is missing, *the image could not be read* when the file is not an image Curio can open or is cut short. |

Every input column follows. A class the model does not label stops the node, with a message naming the labels it has.

Dragging a model onto a node rewrites the id in its first `curio_load_model(...)` call and nothing else, so `classes` stays as you set it. The dataflow saves the node's code, so it reopens with the same model.

---

## 4. Runtimes and libraries

| Runtime | What runs it | Libraries |
|---|---|---|
| **ONNX** | `onnxruntime`, on the CPU | `onnxruntime`, which the Street Vision package installs. |
| **Transformers** | Hugging Face Transformers, on the CPU | `torch`, `transformers` and `safetensors`, installed when you add the model. |

A Transformers model's libraries install the way a node package's do. When they do not install, the model is still added, and the message says why; the node then says what to install when it runs. An account that may not install libraries can add ONNX models only.

A node reads its model from your Model Catalog and needs no network to run it.

---

## 5. Importing, publishing, and sharing

Models are not uploaded or published from the app. A model ships with the deployment, or you add one from the Discovery Catalog's **Hugging Face models**. A model you add is yours: every dataflow you open can run it, and nobody else on the install sees it.

A dataflow names its models by id. Someone you share it with runs a shipped model as it is. A model you added has an id of your own, so they add a model of their own and drag it onto the node.

---

## 6. The manifest

| Field | Required | What it declares |
|---|---|---|
| `id` | Yes | `model.<publisher>.<name>` for a shipped model. |
| `name`, `version` | Yes | What the card says, and the manifest's own version string. |
| `compatibility.major` | | Defaults to 1. Together with `id` it forms the folder name. |
| `runtime` | Yes | `onnx` or `transformers`. |
| `task` | Yes | `semantic-segmentation`. |
| `entry` | Yes | For `onnx`, the graph file; for `transformers`, the folder of the checkpoint. A path inside the model's folder. |
| `labels` | | The classes, in the order the model numbers them. |
| `input` | For `onnx` | How an image is prepared: `width` and `height` (8 to 8192 pixels), `dtype` (`uint8` or `float32`), `layout` (`NCHW`), `scale`, and an optional `mean` and `std` of three numbers each. |
| `license`, `licenseFile` | `license` | The license, and the file in the folder that holds its text. |
| `description`, `publisher`, `homepage`, `tags`, `sizeBytes` | | Shown on the card and in the details. |

---

## Operator notes

| Variable | Flag | Effect |
|---|---|---|
| `CURIO_MODELS_ROOT` | `--models-root` | Reads the shipped models from this directory instead of `<repo_root>/models`. |

**Shipping a model.** Add its folder to `models/` and restart. The Docker image bakes `models/` in, as it does `datasets/`. A model there must be one Curio may redistribute, with its license in the folder.

---

## See also

- [`docs/DISCOVERY-CATALOG.md`](DISCOVERY-CATALOG.md#adding-a-model): adding a model from Hugging Face.
- [`docs/NODE-CATALOG.md`](NODE-CATALOG.md): the Street Vision package and its Image Segmentation node.
- [`docs/examples/10-street-vision-cv-analysis.md`](examples/10-street-vision-cv-analysis.md): two models over the same street photos.
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md#model-catalog): how models are stored, staged for a run, and resolved.
