# Bringing your own model into Curio

You have a model you trained in PyTorch or TensorFlow, and you want a node in a
Curio dataflow to run it. This guide takes you from the trained model to that
node: export the model to ONNX, prove the export answers as your framework does,
put it in the Model Catalog, and write the node that feeds it. A worked example
you can run end to end follows the steps, and two real ports, SCOUT's Deep
Umbra shadow model and SCOUT's weather graph network, show the same steps on
larger models.

- [1. The path a model takes](#1-the-path-a-model-takes)
- [2. Export the model to ONNX](#2-export-the-model-to-onnx)
- [3. Prove the export answers as the original does](#3-prove-the-export-answers-as-the-original-does)
- [4. Put the model in the Model Catalog](#4-put-the-model-in-the-model-catalog)
- [5. Write the node that runs it](#5-write-the-node-that-runs-it)
- [6. Test the node](#6-test-the-node)
- [7. Worked example: Local Relief](#7-worked-example-local-relief)
- [8. Case study: Deep Umbra (TensorFlow, image to image)](#8-case-study-deep-umbra-tensorflow-image-to-image)
- [9. Case study: the weather GNN (PyTorch Geometric, graph regression)](#9-case-study-the-weather-gnn-pytorch-geometric-graph-regression)
- [10. Things that will trip you up](#10-things-that-will-trip-you-up)
- [11. Checklist](#11-checklist)

Before you start, set Curio up from a git clone ([AUTHORING-NODES.md,
Setup](AUTHORING-NODES.md#setup)): a model and its node are added as files in
the repository's `models/` and `packages/` folders.

---

## 1. The path a model takes

```
your training code ──export──▶ model.onnx ──┐
   (PyTorch / TensorFlow,                    ├─▶ models/<id>@1/          the Model Catalog
    its own environment)        manifest ───┘
                                                     │ curio_load_model("<id>")
                                                     ▼
                         packages/<package>@1/   a node: prepares the arrays,
                                                 model.run({...}), writes the result
```

Curio runs a model with **onnxruntime**, on the CPU. Your training framework
never enters Curio's environment: you export the model once, in an environment
of its own, and Curio reads the exported file. That keeps Curio's dependencies
small, and it means a model trained with an old TensorFlow or a PyTorch
extension still runs, because only its exported graph does.

Pick the path that fits your model:

| Your model | Path |
|---|---|
| A PyTorch or TensorFlow model you trained | Export to ONNX (this guide). The Model Catalog's `runtime` is `onnx`. |
| A Hugging Face segmentation model | Add it from the Discovery Catalog's **Hugging Face models**; no export ([MODEL-CATALOG.md](MODEL-CATALOG.md)). |
| A scikit-learn model, or plain Python | No Model Catalog entry needed: put it in a node package's `sources/` and call it from the node's code ([AUTHORING-NODES.md](AUTHORING-NODES.md)). |

The Model Catalog knows three kinds of model, its `task`:

| `task` | In | Out | Example |
|---|---|---|---|
| `semantic-segmentation` | an image | one class per pixel | DDRNet23-Slim, run by **Image Segmentation** |
| `image-to-image` | images or rasters | an image or raster | Deep Umbra, run by **Accumulated Shadow**; Local Relief, below |
| `node-regression` | a graph (node features and edges) | values per node | the weather GNN, run by **Weather Routing** |

A segmentation model is run by Curio's `curio_segment` and needs no node of
your own. An image-to-image or node-regression model is run by the node you
write for it, which prepares the model's inputs itself. That is the case this
guide covers.

---

## 2. Export the model to ONNX

Export in a **throwaway environment** that has your training framework and the
exporter, never in Curio's. Write the versions you used at the top of your
export script: an export is only reproducible in the environment that made it.

```bash
python -m venv export-env
export-env/bin/pip install torch onnx onnxscript onnxruntime numpy   # PyTorch
# or: tensorflow==<your version> tf2onnx onnx onnxruntime numpy       # TensorFlow
```

Whichever framework, decide three things before you export:

1. **The input and output names.** The node feeds the model by name
   (`model.run({"height": ...})`), so name every input and output, in the
   order your model takes them.
2. **The shapes, and which dimensions are free.** A dimension you leave free
   (the number of rows of a raster, the number of nodes of a graph) lets one
   file run on inputs of any size. A dimension you fix (a 512 by 512 tile) is a
   promise the node must keep.
3. **Inference or training behaviour.** Export the model in the mode your
   original code *runs* it in, which is not always `eval()`. See
   [Batch normalization](#batch-normalization-in-training-mode).

### PyTorch

```python
import torch

model = MyModel()
model.load_state_dict(torch.load("weights.pth", map_location="cpu"))
model.eval()

example = torch.zeros(1, 1, 64, 64)                    # one input of a size you have
rows = torch.export.Dim("rows", min=8)                 # free dimensions
cols = torch.export.Dim("cols", min=8)
program = torch.onnx.export(
    model, (example,),
    input_names=["height"], output_names=["relief"],
    dynamic_shapes={"height": {2: rows, 3: cols}},     # keyed by forward()'s argument name
    dynamo=True,
)
program.save("model.onnx", external_data=False)
```

`dynamo=True` is PyTorch's current exporter (it needs `onnxscript`). A model it
cannot trace, often one built on an extension library, may still export with
the older TorchScript exporter: `dynamo=False`, with `dynamic_axes` in place of
`dynamic_shapes` and an `opset_version`. The weather GNN was exported that way
([section 9](#9-case-study-the-weather-gnn-pytorch-geometric-graph-regression)).

### TensorFlow

```python
import tensorflow as tf
import tf2onnx

spec = [tf.TensorSpec((1, 512, 512, 1), tf.float32, name=n) for n in ("height", "latitude", "date")]

@tf.function(input_signature=spec)
def predict(height, latitude, date):
    return {"shadow": generator([height, latitude, date], training=False)}

model_proto, _ = tf2onnx.convert.from_function(predict, input_signature=spec, opset=15)
open("model.onnx", "wb").write(model_proto.SerializeToString())
```

Restore your checkpoint into the model before you export, and check that every
variable was restored: a variable left at its initial value exports without a
complaint and answers wrongly. A Keras model exports with
`tf2onnx.convert.from_keras` the same way.

---

## 3. Prove the export answers as the original does

An export can succeed and still answer differently: a layer in the wrong mode,
an operator the converter approximated, a dtype changed on the way. Check the
file before anything reads it, in the export script itself, so that every
export is checked:

- **Against the framework.** Run onnxruntime and your framework on the same
  inputs and compare. Float32 against float32 agrees to about 1e-5 relative;
  much more than that is a bug, not rounding.
- **On inputs of other sizes than the one you traced**, when a dimension is
  free: an export can bake the traced size in.
- **On the edge cases your data has:** an empty raster, a flat one, a graph
  with a node and no edges, nodata.
- **Against results you already trust,** when there are any: the outputs your
  original code wrote. This is the check that catches a wrong mode or a
  missing weight.

Then make the check permanent: commit the script with the model, and give the
node a test that compares its output with those trusted results
([section 6](#6-test-the-node)).

---

## 4. Put the model in the Model Catalog

A model is a folder named `<id>@<major>` holding a `manifest.json` and its
files:

```
models/model.example.local-relief@1/
├── manifest.json
└── files/
    └── local_relief.onnx
```

```json
{
  "id": "model.example.local-relief",
  "name": "Local Relief (example)",
  "version": "1.0.0",
  "compatibility": { "major": 1 },
  "description": "What it predicts, from what, and how it was made.",
  "publisher": "Curio",
  "license": "MIT",
  "runtime": "onnx",
  "task": "image-to-image",
  "node": "example.local-relief/local-relief@1",
  "entry": "files/local_relief.onnx",
  "input": { "width": 64, "height": 64, "dtype": "float32", "layout": "NCHW", "scale": 1.0 },
  "labels": [],
  "sizeBytes": 2394
}
```

- `id` is `model.<publisher>.<name>`, lowercase, and with `compatibility.major`
  names the folder.
- `runtime` is `onnx`; `entry` is the `.onnx` file, under the folder.
- `task` is one of the three above.
- `input` is required for an `image-to-image` model. For a model your own node
  feeds, it records what the model was made for (`layout` `NCHW` or `NHWC`,
  `dtype`, a size); a `node-regression` model has none.
- `node` is the node that runs the model, as `<packageId>/<templateId>@<major>`.
  Dragging the model from the Model Catalog onto the canvas then makes that
  node, and adds its package to the dataflow.
- `license` is required: a model is someone's work. Put its text in the folder
  and name it in `licenseFile` when it is not a standard licence.

Every field is in [MODEL-CATALOG.md, The manifest](MODEL-CATALOG.md#6-the-manifest).

Copy the folder into `models/` and restart Curio. The model shows in the Model
Catalog. To keep your models outside the repository, start Curio with
`--models-root <folder>` (or `CURIO_MODELS_ROOT`); that folder then replaces
`models/`, so copy the shipped models you still want into it too.

> **Today a model is added as files.** The app adds Hugging Face models from
> the Discovery Catalog, but has no upload for an ONNX file: you need the
> repository, or the folder `--models-root` names.

---

## 5. Write the node that runs it

The node is an ordinary Python node package ([AUTHORING-NODES.md](AUTHORING-NODES.md)).
Keep its code short and put the work in a module beside it:

```
packages/example.local-relief@1/
├── manifest.json                 # a template with "source": "sources/local-relief.py"
└── sources/
    ├── local-relief.py           # the node's code
    └── local_relief/
        ├── __init__.py
        └── run.py                # prepare the inputs, run the model, write the result
```

The node's code loads the model by its id and hands it to the module:

```python
from local_relief.run import local_relief

model = curio_load_model("model.example.local-relief")
return local_relief(input_0, model, output_file=curio_output_file)
```

`curio_load_model(id)` gives the model from the Model Catalog. Its one method
for an ONNX model:

```python
outputs = model.run({"height": array})   # {input name: numpy array}, every input the graph has
```

It returns the graph's outputs as a list, in the graph's order, so a model with
one output is read as `(relief,) = model.run(...)`. The onnxruntime session
opens on the first call and is kept for the next ones, so a node that runs the
model once per tile pays for opening it once. A missing input is refused with
the names the graph has.

When the code you port opens its model itself, hand it the file instead:
`model.entry` is the path of the model's `.onnx` file in the Model Catalog,
for an `onnxruntime.InferenceSession(model.entry)` of the code's own.
Accumulated Shadow does this, so SCOUT's `get_deep_shadow()` stays SCOUT's.

Write the module as you would any function that takes a model:

```python
import numpy as np
import rasterio


def local_relief(raster, model, output_file):
    band = raster.read(1, masked=True)
    heights = band.filled(0).astype(np.float32)

    (relief,) = model.run({"height": heights[np.newaxis, np.newaxis]})   # NCHW, as exported
    relief = relief[0, 0].astype(np.float32)
    relief[np.ma.getmaskarray(band)] = np.nan

    path = output_file("local-relief.tif")
    profile = {"driver": "GTiff", "width": raster.width, "height": raster.height, "count": 1,
               "dtype": "float32", "crs": raster.crs, "transform": raster.transform, "nodata": float("nan")}
    with rasterio.open(path, "w", **profile) as out:
        out.write(relief, 1)
    return rasterio.open(path)
```

What the node receives and returns:

- **Its inputs** are named after their circles: what the edge on circle 0
  delivers is `input_0`, on circle 1 `input_1`, and so on; a tuple an upstream
  node returns is one input, its items `input_0[0]`, `input_0[1]`
  ([USAGE.md, Input names](USAGE.md#input-names)).
- **A raster** comes in as a rasterio dataset. Return one by writing a GeoTIFF
  where `curio_output_file("<name>.tif")` says and returning it opened, as
  above. Write NaN as nodata: autk-db reads a GeoTIFF that names no nodata
  with 0 as its nodata, which would drop every 0 cell from an Autark map.
- **A table or layer** comes in as a DataFrame or GeoDataFrame; return one.
- **Settings** a user changes, such as a season or a threshold, are widgets
  (`[!! season !!]` in the code; [AUTHORING-NODES.md, Widgets in a
  template](AUTHORING-NODES.md#widgets-in-a-template)).

In the package's `manifest.json`, declare what the node imports
(`"dependencies": {"python": {"onnxruntime": ">=1.17", "rasterio": ">=1.4"}}`):
imports inside your modules are not detected. Then copy the package into
`packages/`, write its `integrity.json` with
`python scripts/regen_integrity.py packages/<package>@1`, restart, and add it
from **Node Catalog → Browse Node Catalog + → Browse all → Add to project**.

### Porting a model's code from another project

When the model comes with code that prepares its inputs and reads its outputs,
as SCOUT's did, port that code instead of rewriting it. Two ways work, and
the SCOUT ports show both:

- **The original file, its changed lines marked.** Copy the file into the
  package's `sources/` and change only the lines that cannot stay: the model
  call (`generator(concat, training=True)` becomes
  `generator.run(None, {...})`), the framework's array operations
  (`tf.math.atan` becomes `np.arctan`), and what is left out (training code,
  unused imports). Mark each changed line with a comment saying what it was,
  `# Curio: tf.math.pow`, so `grep "# Curio:"` lists every difference. If
  the original reads and writes files, let it: the node hands it folders
  (`curio_computed_path`, `curio_save_folder`) and reads its output back.
  Accumulated Shadow runs SCOUT's `deep_umbra.py` this way.
- **A port with the original's names.** Keep the functions' names and
  arithmetic, take the model as an argument, and read and return arrays
  instead of files; list every change in the module's docstring. Weather
  Routing ports SCOUT's routing this way.

Either way, list every bug of the original you fix, with what it did, and
match the original's dtypes: a latitude computed in float64 where the
original used float32 shifts every prediction a little, and a parity test
then fails by a hair.

---

## 6. Test the node

Give the package a test that runs the node's code as the sandbox runs it and
compares the answer with one you trust. The worked example's test,
[`test_model_catalog/test_bring_your_own_model.py`](../utk_curio/backend/tests/test_model_catalog/test_bring_your_own_model.py),
does the four things such a test should:

1. The model's manifest is one the Model Catalog takes
   (`parse_manifest(raw, dir_name=...)`).
2. The package is one the Node Catalog takes, and its `integrity.json` matches
   its files.
3. The ONNX file gives known answers on inputs the export never traced.
4. The node's code runs in the sandbox with the model resolved as the backend
   resolves it (`execute_code(..., models={id: folder}, package_modules=...)`),
   and its output matches a reference computed another way.

For a model ported from another project, the reference is that project's own
results: the SCOUT tests compare Curio's shadows and routes with the ones
SCOUT's code wrote ([sections 8 and 9](#8-case-study-deep-umbra-tensorflow-image-to-image)).

---

## 7. Worked example: Local Relief

Every file of this example is in
[`docs/bring-your-own-model/`](bring-your-own-model/), ready to copy.

**The model.** Local Relief takes a raster of building heights and returns,
for each cell, how many metres it stands above the mean height of the 5 by 5
cells around it: positive on a building's edge above the street, negative on
the street beside a tall building, 0 on flat ground. Its weights are fixed, so
you can check its answer by hand; it stands in for the network you trained,
and every step is the same for yours.

```python
class LocalRelief(torch.nn.Module):
    def __init__(self, window=5):
        super().__init__()
        self.mean = torch.nn.AvgPool2d(window, stride=1, padding=window // 2, count_include_pad=False)

    def forward(self, height):
        return height - self.mean(height)
```

**Step 1: export and check it.** In a throwaway environment:

```bash
python -m venv export-env
export-env/bin/pip install torch onnx onnxscript onnxruntime numpy
export-env/bin/python docs/bring-your-own-model/export_local_relief.py
```

[`export_local_relief.py`](bring-your-own-model/export_local_relief.py) writes
`model.example.local-relief@1/files/local_relief.onnx` (2.4 KB), with rows and
columns free, then checks it: onnxruntime against PyTorch and against a numpy
reference, on the traced 64 by 64, on 37 by 90, on a flat raster and on a lone
tower. It exits with status 1 when a check fails, and writes the same bytes on
every run. The committed file is what it wrote.

**Step 2: add the model.** Copy
[`model.example.local-relief@1/`](bring-your-own-model/model.example.local-relief@1/)
into `models/`. Its manifest is the one in [section 4](#4-put-the-model-in-the-model-catalog).

**Step 3: add the node.** Copy
[`example.local-relief@1/`](bring-your-own-model/example.local-relief@1/) into
`packages/`. Its code is the one in [section 5](#5-write-the-node-that-runs-it).

```bash
cp -r docs/bring-your-own-model/model.example.local-relief@1 models/
cp -r docs/bring-your-own-model/example.local-relief@1 packages/
python curio.py start
```

In the browser, add **Local Relief (example)** to your project from
**Node Catalog → Browse Node Catalog + → Browse all → Add to project**. The
Model Catalog lists **Local Relief (example)** too.

**Step 4: build the dataflow.**

1. Drop a **Python Computation** node, name it **Make Heights**, and give it
   this code. It writes a 64 by 64 raster, 10 m a cell, with a 30 m block and
   a 120 m tower on flat ground:

   ```python
   import numpy as np
   import rasterio
   from rasterio.transform import from_origin

   heights = np.zeros((64, 64), dtype="float32")
   heights[8:20, 8:20] = 30      # a 30 m block
   heights[30:44, 36:50] = 120   # a 120 m tower

   path = curio_output_file("heights.tif")
   with rasterio.open(
       path, "w", driver="GTiff", width=64, height=64, count=1, dtype="float32",
       crs="EPSG:3857", transform=from_origin(-9757000, 5143000, 10, 10), nodata=float("nan"),
   ) as out:
       out.write(heights, 1)
   return rasterio.open(path)
   ```

2. Drop **Local Relief** and connect Make Heights to it. (Dragging the model
   from the Model Catalog onto the canvas makes the same node.)
3. Drop an **Autark** node, connect Local Relief to it, and give it this map:

   ```json
   {
     "map": {
       "layerRefs": [
         { "dataRef": "[!! input_0 !!]", "getFnv": "band_1",
           "colorMapInterpolator": "interpolateRdBu", "colorMapCenter": 0, "colorMapReverse": true,
           "legendTitle": "Local relief (m)" }
       ]
     }
   }
   ```

   `colorMapCenter` and `colorMapReverse` center the scheme on 0 and put red
   above it ([USAGE.md, Legend titles](USAGE.md#legend-titles)).
4. Run the Autark node. The map shows flat ground and the buildings' flat
   tops white (0), the buildings' edges red, standing above the street around
   them, and the street beside them blue, below the buildings next to it.

With real data, connect any height raster instead of Make Heights: SCOUT's
**Rasterize Buildings** and **Mosaic Tiles** make one from a buildings layer
(see the [ScoutShadows](examples/dataflows/ScoutShadows.json) dataflow).

**Step 5: test it.**

```bash
pytest utk_curio/backend/tests/test_model_catalog/test_bring_your_own_model.py
```

The test reads the example's files where they are in `docs/`, so it keeps this
guide honest: it runs this page's **Make Heights** code and the package's
Local Relief code in the sandbox and checks every cell against a numpy
reference.

---

## 8. Case study: Deep Umbra (TensorFlow, image to image)

[SCOUT](https://github.com/urban-toolkit/scout)'s accumulated shadow model is a
TensorFlow generator restored from a checkpoint (`tf_model/ckpt-44`). In Curio
it is the model [`model.scout.deep-umbra@1`](../models/model.scout.deep-umbra@1/manifest.json)
(10.5 MB), run by the **Accumulated Shadow** node of
[`scout.shadow@1`](../packages/scout.shadow@1/).

| Step | What was done |
|---|---|
| Export | [`scripts/scout/export_deep_umbra.py`](../scripts/scout/export_deep_umbra.py), in SCOUT's environment (Python 3.11, TensorFlow 2.12, tf2onnx 1.16.1). It imports SCOUT's own `deep_umbra.py`, restores the generator with SCOUT's `get_deep_shadow()`, checks every variable was restored, and exports with `tf2onnx.convert.from_function`: inputs `height`, `latitude`, `date`, output `shadow`, each 1 by 512 by 512 by 1, fp32. |
| The catch | SCOUT runs the generator with `training=True`, so its batch normalization uses each tile's own statistics, not the checkpoint's averages. The export keeps that ([below](#batch-normalization-in-training-mode)), so the model runs one tile per call. |
| Checks | ONNX against TensorFlow on SCOUT's committed height tiles; that ONNX is far from TensorFlow's `training=False`, and unchanged by scrambled averages, so it cannot be using them; the port's inputs against SCOUT's; the port's shadows and metrics against SCOUT's committed ones. |
| Node code | [`deep_umbra.py`](../packages/scout.shadow@1/sources/scout_shadow/deep_umbra.py) is SCOUT's file, each changed line marked `# Curio:` (TensorFlow's operations become numpy, OpenCV and onnxruntime; `get_deep_shadow()` opens the ONNX file `curio_load_model("model.scout.deep-umbra").entry` names). The node runs SCOUT's `run_shadow_model` on the height tiles Rasterize Buildings saved, keeps SCOUT's shadow tiles as a computed dataset, and returns them joined into one raster with the package's [`mosaic.py`](../packages/scout.shadow@1/sources/scout_shadow/mosaic.py), with the metrics `run_shadow_model` returns where SCOUT saves a CSV. |
| Result | Within 1 gray level of SCOUT's committed summer shadows; mean shadow 128.60 minutes against SCOUT's 128.64 ([`test_scout_shadow.py`](../utk_curio/backend/tests/test_packages/test_scout_shadow.py)). |

## 9. Case study: the weather GNN (PyTorch Geometric, graph regression)

SCOUT's weather-aware routing weighs each road by the weather a small graph
network predicts on it: two GraphSAGE layers (`SAGEConv`, mean aggregation)
and a linear head, from `rain_model.pth`. In Curio it is
[`model.scout.weather-gnn@1`](../models/model.scout.weather-gnn@1/manifest.json)
(52 KB, task `node-regression`), run by the **Weather Routing** node of
[`scout.routing@1`](../packages/scout.routing@1/).

| Step | What was done |
|---|---|
| Export | [`scripts/scout/export_weather_gnn.py`](../scripts/scout/export_weather_gnn.py), in SCOUT's environment (Python 3.9, torch 2.2.2, torch-geometric 2.6.1). It builds SCOUT's `NodeRegressor`, loads the weights with every key used, and exports with the TorchScript exporter (`torch.onnx.export`, opset 17): inputs `x` (nodes by 7) and `edge_index` (2 by edges, int64), output `prediction` (nodes by 5), with `dynamic_axes` so the node and edge counts are free. Mean aggregation exports as ordinary ONNX operators, so torch-geometric is not needed to run it. |
| Checks | onnxruntime against torch on graphs of other sizes than the traced one: repeated edges, nodes without edges, a graph with no edges; and against the inputs and prediction recorded from SCOUT's own run. |
| Node code | [`weight_calculation.py`](../packages/scout.routing@1/sources/scout_routing/weight_calculation.py) is SCOUT's, with `model.run({"x": x, "edge_index": edge_index})` for the torch call; [`road_graph.py`](../packages/scout.routing@1/sources/scout_routing/road_graph.py) builds the road graph from a roads layer. Three of SCOUT's bugs are fixed and listed in [`weather_routing.py`](../packages/scout.routing@1/sources/scout_routing/weather_routing.py). |
| Result | SCOUT's routes node for node, and its metrics to about 1e-6, for two scenarios ([`test_scout_routing.py`](../utk_curio/backend/tests/test_packages/test_scout_routing.py)). |

---

## 10. Things that will trip you up

### Batch normalization in training mode

A batch normalization layer normalizes with the averages it learnt when the
model is in inference mode, and with the statistics of the batch it is given
when it is in training mode. Some projects run their model in training mode on
purpose: SCOUT calls Deep Umbra with `training=True`. Export in the mode the
original runs in, then check: an export in the other mode runs and answers
plausibly, and only a comparison with the original's results shows it is
wrong.

To keep training mode, Deep Umbra's export set each layer's `momentum` to 0
before tracing, so TensorFlow's fused batch norm carries an average factor of
1.0, which tf2onnx turns into a normalization by the input's own statistics.
Those statistics then mix across a batch, so the model must be fed one input
at a time, as SCOUT feeds it.

### A dimension the export fixed

An export traces the model on the example input you give it. Any dimension you
did not declare free is the example's size forever. Declare it free
(`dynamic_shapes`, `dynamic_axes`) and test on another size.

### Dtypes

ONNX takes the dtype you exported with. Feed `float32` where the model reads
float32 (`array.astype(np.float32)`) and `int64` for indices such as a graph's
`edge_index`. A reshape that drops the batch dimension, or NHWC fed to a model
exported NCHW, fails with a shape error at `model.run`.

### Operators the converter cannot export

An extension library's custom operator (a scatter, a sparse matrix product) may
not convert. Try the other PyTorch exporter, a newer opset, or an equivalent
built from plain operators. GraphSAGE with mean aggregation exported as is.

### The model is not found when the node runs

The node's code must name the model as a literal, `curio_load_model("<id>")`:
the backend reads the ids from the code to hand the sandbox their folders. The
model must also be in the Model Catalog of whoever runs the dataflow.

### A licence

Curio ships only models it may redistribute. A model trained by someone else,
as SCOUT's were, needs their permission, recorded in the manifest's `license`.

---

## 11. Checklist

- [ ] An export script, committed, with the environment's versions at its top.
- [ ] Named inputs and outputs; the free dimensions declared free.
- [ ] Exported in the mode the original runs the model in.
- [ ] The export checked against the framework, on other sizes and edge cases,
      and against results you trust; a failed check exits non-zero.
- [ ] `models/<id>@<major>/` with `manifest.json` (`runtime` `onnx`, `task`,
      `entry`, `input` for an image model, `node`, `license`) and the `.onnx` file.
- [ ] A node package whose code calls `curio_load_model("<id>")` with a literal
      id, its model code in a module, its Python dependencies declared, and its
      `integrity.json` written.
- [ ] A test that runs the node in the sandbox and compares its output with a
      reference.

## See also

- [MODEL-CATALOG.md](MODEL-CATALOG.md): the Model Catalog, and every manifest field.
- [AUTHORING-NODES.md](AUTHORING-NODES.md): writing and shipping a node package.
- [NODE-CATALOG.md](NODE-CATALOG.md): how packages are installed and shared.
- [USAGE.md](USAGE.md): building and running dataflows.
