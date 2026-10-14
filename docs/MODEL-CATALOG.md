# Model Catalog

The Model Catalog is where Curio keeps the **trained models** your nodes can run. A model ships with Curio, or you add one from the [Discovery Catalog](DISCOVERY-CATALOG.md) or import its package. You add a model to one dataflow, or to all your projects, as you add a node package in the [Node Catalog](NODE-CATALOG.md). A node such as **Image Segmentation** runs the model its code names, and you choose which by dragging a model onto it.

Curio has six catalogs: the [Node Catalog](NODE-CATALOG.md) holds the nodes you drop on the canvas, the [Data Catalog](DATA-CATALOG.md) the datasets they read, the Model Catalog the models they run, the [Agent Catalog](AGENT-CATALOG.md) the assistants you attach to them, the [Discovery Catalog](DISCOVERY-CATALOG.md) the portals, storage, services and models you take datasets and models from, and the [Scenario Catalog](SCENARIO-CATALOG.md) the scenarios saved in your projects.

This guide is in six parts, plus operator notes:

- [1. What is the Model Catalog?](#1-what-is-the-model-catalog): models, what ships, and where they are stored.
- [2. Surfaces and workflows](#2-surfaces-and-workflows): the page, the canvas drawer and palette, the action matrix, and walkthroughs.
- [3. Using a model in a dataflow](#3-using-a-model-in-a-dataflow): dragging a model onto a node, and what the node does with it.
- [4. Runtimes and libraries](#4-runtimes-and-libraries): ONNX and Transformers, and what each needs.
- [5. Importing, publishing, and sharing](#5-importing-publishing-and-sharing): where models come from, exporting and publishing one, and sharing a dataflow that names one.
- [6. The manifest](#6-the-manifest): the fields a model package declares.
- [Operator notes](#operator-notes): shipping a model of your own.

---

## 1. What is the Model Catalog?

### Concept

A **model** is a model package: a package of kind `model` that holds the model's weights under `models/`, the weights' license, the node that runs the model, and any Python modules that node imports, under `sources/`. A model that ships with Curio is identified by `model.<publisher>.<name>` and a major version; a model you add gets an id of its own, such as `imported.x1f3a9c2b7d40`:

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

DDRNet23-Slim is about 23 MB and labels a street photo in a fraction of a second on a CPU. Its package, `model.curio.ddrnet23-slim@1`, has the **Image Segmentation** node, which runs it on a collection's photos and reports each class's share of every image ([example 10](examples/10-street-vision-cv-analysis.md)); a model added from the Discovery Catalog's Hugging Face models gets the same node. The package is read-only, depends only on `onnxruntime`, and is installed with the example that declares it. See its [README](../packages/model.curio.ddrnet23-slim@1/README.md).

Deep Umbra, [SCOUT](https://github.com/urban-toolkit/scout)'s shadow model, is about 10.5 MB. Its package, `model.scout.deep-umbra@1`, has the **Accumulated Shadow** node, which runs it on a raster of building heights and returns the minutes of shadow on the same grid ([example 24](examples/24-scout-building-rasters.md)). A pip install downloads its weights from GitHub the first time a node runs it ([Installation from pip](USAGE.md#installation-from-pip)). The package is read-only, depends on `onnxruntime`, `rasterio`, `numpy` and `pyproj`, and is installed when Curio starts with `--with-examples`. See its [README](../packages/model.scout.deep-umbra@1/README.md).

The weather GNN, SCOUT's weather graph network, is about 52 KB. Its package, `model.scout.weather-gnn@1`, has the **Weather Routing** node, which runs it on the road graph it builds from a roads layer, to weigh each road by the weather the network predicts on it from the WRF forecast in the Data Catalog, before routing ([the WeatherRouting test dataflow](examples/dataflows/WeatherRouting.json)). The package is read-only, depends on `osmnx`, `networkx`, `netCDF4`, `scipy`, `scikit-learn`, `onnxruntime`, `geopandas`, `numpy`, `pandas` and `shapely`, and is installed when Curio starts with `--with-examples`. See its [README](../packages/model.scout.weather-gnn@1/README.md).

### Storage layers

| Layer | On disk | Written by |
|---|---|---|
| **Shared catalog** | `<repo_root>/packages/<packageId>@<major>/`, the weights under its `models/` | The release, and **Publish** when the operator allows it. |
| **Your package store** | `.curio/users/<user-key>/packages/<packageId>@<major>/` | **Add to Model Catalog** in the Discovery Catalog, **Import package**, and adding a model to a project. A copy of a shipped package, added or brought by a dataflow, holds no weights: they are read where they ship. Removing the model from the last dataflow that uses it deletes the copy. |
| **Your defaults** | `.curio/users/<user-key>/default-packages.json` | **Add to all projects** adds an entry. Removing the model from the last dataflow that uses it drops the entry. |
| **A dataflow's lockfile** | `dataflow.packages` in the project's `spec.trill.json` | **Add to project** and **Remove from project** in the drawer. **Add to all projects** also patches every existing project. |
| **A node's model** | The node's code, `curio_load_model("<id>")`, saved with the dataflow | A drop on the node, or what you type. |

A node runs a model whose package is in your store: one you added, one a dataflow that names it brought, or one installed for the examples. A model whose package your store does not hold stops the node, with a message saying to add it.

---

## 2. Surfaces and workflows

- **The Model Catalog drawer**, on the canvas, works on the open dataflow. Open it from the **Model Catalog** button in the top bar, or from the left Tools panel's **Model Catalog** dropdown and **Browse Model Catalog +**. Its two tabs are **Browse all**, the shared catalog's models and your own (imported, published, or downloaded from the Discovery Catalog), and **In project**, this dataflow's models, with their count. Each card shows the runtime, the label count (the type, for a model with no labels), the size and the weights' license. **Import package** is in its footer.
- **The `/catalog/models` page**, reached from the **Model Catalog** tab, works on your whole account: a model added here goes into every project you have and every new one. Search with **Search models…**, sort, and filter in the left rail by **All models**, **In all projects**, **By type** or **By runtime**. Each card shows the runtime, the type, the label count, the size and the weights' license. Click a card to describe it in the right-hand drawer, which offers **Add to all projects** (or **Update all projects**), **Publish** or **Unpublish** for a model of your own, **Remove from account** for a model of your own that no dataflow uses, and **View details**. **Import package** is in the header, and `/catalog/models/<id>` opens the page with that model's details.
- **The Model Catalog dropdown**, in the left Tools panel, lists every model you can use, the shared catalog's and your own, as cards to drag onto a node.

**View details** opens the same details window as a node package's. For a model it starts with a **Model** section: **Type**, **Runtime**, **Input size**, **Labels**, **Size**, **Weights license** (with **View license** when the package ships its text), **Weights publisher**, **Homepage**, **Node** (the node a drop on the canvas creates), and **Weights**: *Downloads on first use* for weights a pip install left out that no node has fetched yet. Then come the labels, **Downloaded from** (the Discovery Catalog source, linked) for a model you downloaded, **Package info** (**Identifier**, **Version**, **Category**, **Publisher**, **Code license**, **Channel**, **Nodes**, **In all projects**, **In the catalog**), **Nodes in this package**, **Modules** (the Python modules the package ships, such as Deep Umbra's `deep_umbra`), **Permissions** and **Dependencies**. **Export** is in the header.

### Action matrix

| Action | Where | What it changes | What you see |
|---|---|---|---|
| **View details** | A card, the page's right-hand drawer, or a row of the **Model Catalog** dropdown | Nothing | The model's details. |
| **View license** | The details | Nothing | The text of the weights' license, when the package ships it. |
| **Add to project** | Drawer | This dataflow's lockfile, plus your package store if the model is not there yet | A review first, listing the model's permissions and libraries. The model joins the **In project** tab, and its node this dataflow's palette. When the add changes a library under the running Curio, the drawer says to restart Curio to pick it up. |
| **Add to all projects** | `/catalog/models` | Your defaults and every project's lockfile, plus your package store | The same review first. The model is in every project, and new projects start with it. |
| **Update** (drawer), **Update all projects** (`/catalog/models`) | Shown when the shared catalog has a higher version than your copy | Your store copy, replaced by the catalog's version | Every project that uses the model gets the new version. |
| **Remove from project** | Drawer | This dataflow's lockfile; when no other dataflow uses the model, also your store copy, your defaults entry and its Python libraries | A confirmation first, then the model leaves the **In project** tab. |
| **Remove from account** | The `/catalog/models` right-hand drawer, for a model of your own that no dataflow uses | Your store copy, weights included, and your defaults entry | A confirmation first, then the model leaves your account. |
| **Import package** | The drawer's footer, or the `/catalog/models` header | Your package store; from the drawer, this dataflow's lockfile too | The model from a `.curio.zip` archive, weights included. |
| **Export** | The details | Nothing | The model's package saved as `<packageId>@<major>.curio.zip`, weights included. |
| **Publish**, **Unpublish** | The `/catalog/models` right-hand drawer, for a model of your own | The shared catalog | **Publish** lets every user on this install browse and add the model; **Unpublish** takes it out. Both are hidden when the operator turns publishing off. |
| **Drag onto a node** | The **Model Catalog** dropdown or the canvas drawer | The node's code | The node's `curio_load_model(...)` line names the model. A node whose code calls no `curio_load_model` says *This node does not run a model*. |
| **Drag onto the canvas** | The **Model Catalog** dropdown or the canvas drawer | The dataflow | A new node where you drop it, its `curio_load_model(...)` line naming the model: the model's own node (**Image Segmentation** for DDRNet23-Slim, **Accumulated Shadow** for Deep Umbra, **Weather Routing** for the weather GNN), else another node of the dataflow that runs a model. When no node in the dataflow runs a model, nothing is added and a message names the package to add from the Model Catalog. |
| **Add to Model Catalog** | A **Hugging Face models** row, in the Discovery Catalog | Your Model Catalog gains a model | A progress bar, then *"Added `<name>` to your Model Catalog."* with **View model**. |

### Workflows

**I want to label street photos.** Load the photos with a **Data Loading** node (`curio_load_collection(...)`). Open the Model Catalog drawer, click **Add to project** on DDRNet23-Slim, then drag its card onto the canvas, which adds its **Image Segmentation** node, and wire the two. [Example 10](examples/10-street-vision-cv-analysis.md) does this end to end.

**I want a different model.** Open the Discovery Catalog's **Hugging Face models**, search, and click **Add to Model Catalog** on a model ([DISCOVERY-CATALOG.md part 4](DISCOVERY-CATALOG.md#adding-a-model)). On the canvas, open **Model Catalog** in the left Tools panel and drag it onto the Image Segmentation node. Set `classes` in the node's code to the labels you want, or `None` for all of them; the model's details list its labels.

**A node says a model is not one of your models.** The node names a model whose package is not in your store, for example in a dataflow someone shared with you. Add that model (**Add to project** in the drawer, or **Import package** with an archive of it), or drag one of yours onto the node.

**I want to remove a model.** Open each dataflow that has it and use **Remove from project** in the Model Catalog drawer. When you remove it from the last one, Curio deletes it from your account, drops it from your defaults and uninstalls its Python libraries.

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

A model ships with the deployment, or you add one from the Discovery Catalog's **Hugging Face models**, or import a model package's archive with **Import package**: from the drawer's footer it joins your account and the open dataflow, from the `/catalog/models` header your account only. A model you add is yours: every dataflow you open can run it, and other users on the install see it once you publish it.

**Export**, in a model's details, saves its package as `<packageId>@<major>.curio.zip`, weights included, which **Import package** reads in any Curio. **Publish**, in the `/catalog/models` right-hand drawer, puts a model of your own in the shared catalog, where every user on this install can browse and add it, and **Unpublish** takes it out. Both are hidden when the operator turns publishing off ([NODE-CATALOG.md, Operator notes](NODE-CATALOG.md#operator-notes)).

A dataflow names its models by id, and lists their packages. Someone you share it with runs a shipped model once opening the dataflow has added its package. A model of your own keeps its id through **Export** and **Import package**, so send them its archive, or publish it for them to add; else they drag a model of their own onto the node.

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
- [`docs/NODE-CATALOG.md`](NODE-CATALOG.md): adding, removing and publishing packages, which the Model Catalog does the same way, and the manifest a model package extends.
- [`docs/examples/10-street-vision-cv-analysis.md`](examples/10-street-vision-cv-analysis.md): two models over the same street photos.
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md#model-catalog): how models are stored, staged for a run, and resolved.
