# Bringing your own model into Curio

You have a model you trained in PyTorch or TensorFlow, and you want a node in a
Curio dataflow to run it. This guide takes you from the trained model to that
node: export the model to ONNX, check the export against your framework, make a
model package that holds the weights and the node that runs them, choose what
the user sets on the node, and add the package to your Model Catalog. A worked
example you can run follows the steps, and two of SCOUT's models, Deep Umbra and
the weather graph network, show the same steps on larger models.

- [1. The path a model takes](#1-the-path-a-model-takes)
- [2. Export the model to ONNX](#2-export-the-model-to-onnx)
- [3. Check the export against your framework](#3-check-the-export-against-your-framework)
- [4. Make the model package](#4-make-the-model-package)
- [5. Write the node that runs it](#5-write-the-node-that-runs-it)
- [6. Widgets: what the user sets](#6-widgets-what-the-user-sets)
- [7. Add the model to Curio](#7-add-the-model-to-curio)
- [8. Test the node](#8-test-the-node)
- [9. Worked example: Local Relief](#9-worked-example-local-relief)
- [10. Case study: Deep Umbra (TensorFlow, image to image)](#10-case-study-deep-umbra-tensorflow-image-to-image)
- [11. Case study: the weather GNN (PyTorch Geometric, graph regression)](#11-case-study-the-weather-gnn-pytorch-geometric-graph-regression)
- [12. Things that will trip you up](#12-things-that-will-trip-you-up)
- [13. Checklist](#13-checklist)

---

## 1. The path a model takes

```
your training code  --export-->  model.onnx
(PyTorch or TensorFlow,              |
 an environment of its own)          v
                     model.<publisher>.<name>@1/    a model package
                       manifest.json                kind "model", the model block, one template
                       models/model.onnx            the weights
                       sources/                     the node's code and its module
                                     |
                                     |  Import package, or packages/ in a clone
                                     v
                     its Model Catalog card  --drag onto the canvas-->  the node:
                                                curio_load_model("<id>"), model.run({...})
```

Curio runs an exported model with **onnxruntime**, on the CPU. You export the model once,
in an environment that has your training framework, and Curio reads the
exported file.

Pick the path that fits your model:

| Your model | Path |
|---|---|
| A PyTorch or TensorFlow model you trained | Export it to ONNX and make a model package (this guide). |
| A Hugging Face segmentation model | Add it from the Discovery Catalog's **Hugging Face models**, with no export; it gets the **Image Segmentation** node ([DISCOVERY-CATALOG.md](DISCOVERY-CATALOG.md#adding-a-model)). |
| A scikit-learn model, or plain Python | A node package: put the code in its `sources/` and call it from the node's code ([AUTHORING-NODES.md](AUTHORING-NODES.md)). |

A model package declares one of three types of model:

| Type | In | Out | Example |
|---|---|---|---|
| `semantic-segmentation` | an image | one class per pixel | DDRNet23-Slim, run by **Image Segmentation** |
| `image-to-image` | images or rasters | an image or a raster | Deep Umbra, run by **Accumulated Shadow**; Local Relief, below |
| `node-regression` | a graph: node features and edges | values for each node | the weather GNN, run by **Weather Routing** |

A segmentation model's node calls Curio's `curio_segment` and needs no code of
yours ([MODEL-CATALOG.md](MODEL-CATALOG.md#3-using-a-model-in-a-dataflow)). An
image-to-image or node-regression model is run by the node you write for it,
which prepares the model's inputs itself. That is the case this guide covers.

---

## 2. Export the model to ONNX

Export in a throwaway environment that has your training framework and the
exporter. Write the versions you used at the top of your export script.

```bash
python -m venv export-env
export-env/bin/pip install torch onnx onnxscript onnxruntime numpy   # PyTorch
# or: tensorflow==<your version> tf2onnx onnx onnxruntime numpy       # TensorFlow
```

Whichever framework, decide three things before you export:

1. **The input and output names.** The node feeds the model by name
   (`model.run({"height": ...})`), so name every input and output, in the order
   your model takes them.
2. **The shapes, and which dimensions are free.** A dimension you leave free
   (the number of rows of a raster, the number of nodes of a graph) lets one
   file run on inputs of any size. A dimension you fix (a 512 by 512 tile) is a
   promise the node must keep.
3. **Inference or training behaviour.** Export the model in the mode your
   original code runs it in, which is not always `eval()`. See
   [Batch normalization in training mode](#batch-normalization-in-training-mode).

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

`dynamo=True` is PyTorch's dynamo exporter, which needs `onnxscript`. A model it
cannot trace, often one built on an extension library, may export with the
TorchScript exporter: `dynamo=False`, with `dynamic_axes` in place of
`dynamic_shapes` and an `opset_version`. The weather GNN was exported that way
([section 11](#11-case-study-the-weather-gnn-pytorch-geometric-graph-regression)).

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

## 3. Check the export against your framework

An export can succeed and still answer differently: a layer in the wrong mode,
an operator the converter approximated, a dtype changed on the way. Check the
file in the export script itself, so that every export is checked:

- **Against the framework.** Run onnxruntime and your framework on the same
  inputs and compare. Float32 against float32 agrees to about 1e-5 relative.
- **On inputs of other sizes than the one you traced**, when a dimension is
  free.
- **On the edge cases your data has:** an empty raster, a flat one, a graph
  with a node and no edges, cells with no data.
- **Against results you already trust,** when there are any: the outputs your
  original code wrote.

Have the script exit with a non-zero status when a check fails, and give the
node a test that compares its output with those trusted results
([section 8](#8-test-the-node)).

---

## 4. Make the model package

A model package is a node package of kind `model`: a folder named
`<id>@<major>` that holds the manifest, the weights under `models/`, and the
node's code and its module under `sources/`.

```
model.example.local-relief@1/
├── manifest.json
├── models/
│   └── local_relief.onnx       the weights
└── sources/
    ├── local-relief.py         the node's code
    └── local_relief/           its module: prepares the input, runs the model, writes the result
        ├── __init__.py
        └── run.py
```

Local Relief's manifest, without its descriptions:

```json
{
  "id": "model.example.local-relief",
  "name": "Local Relief (example)",
  "version": "1.0.0",
  "kind": "model",
  "compatibility": { "curioRuntime": ">=0.5.0", "major": 1 },
  "publisher": "Curio",
  "license": "MIT",
  "dependencies": { "python": { "onnxruntime": ">=1.17" } },
  "model": {
    "type": "image-to-image",
    "runtime": "onnx",
    "entry": "models/local_relief.onnx",
    "input": { "width": 64, "height": 64, "dtype": "float32", "layout": "NCHW", "scale": 1.0 },
    "labels": [],
    "license": "MIT",
    "publisher": "Curio",
    "homepage": "https://github.com/urban-toolkit/curio",
    "sizeBytes": 2394
  },
  "templates": [
    {
      "id": "local-relief",
      "label": "Local Relief",
      "category": "computation",
      "behavior": "code",
      "engine": "python",
      "editor": "code",
      "hasCode": true,
      "hasWidgets": true,
      "inputPorts": [{ "cardinality": "1", "types": ["RASTER"] }],
      "outputPorts": [{ "cardinality": "1", "types": ["RASTER"] }],
      "source": "sources/local-relief.py",
      "widgets": [
        { "name": "min_height", "type": "number", "label": "Lowest height", "default": 0,
          "options": { "min": 0, "step": 0.5, "units": "m" } }
      ]
    }
  ]
}
```

The manifest is a node package's ([NODE-CATALOG.md](NODE-CATALOG.md)), with:

- `kind`: `model`.
- `id`: `model.<publisher>.<name>`, lowercase. With `compatibility.major` it
  names the folder, and a node loads the model by it.
- `license`: the license of the package's code.
- `dependencies.python`: the libraries the node's code and its module import,
  `onnxruntime` among them. Adding the model installs them. Imports inside a
  module are not detected, so list every library.
- `templates`: one template, the node that runs the model. Dragging the model's
  card onto the canvas drops it. Its `source` is the node's code; a template
  with no `source` opens with the cell Curio writes for the model's type. Its
  `widgets` are what the user sets ([section 6](#6-widgets-what-the-user-sets)).

The `model` block describes the weights:

- `type`: `semantic-segmentation`, `image-to-image` or `node-regression`.
- `runtime`: `onnx`, for an exported model.
- `entry`: the `.onnx` file, under `models/`.
- `input`: for an `onnx` image model, what the model was made for: `width` and
  `height`, `dtype`, `layout` (`NCHW`, or `NHWC` for an `image-to-image`
  model), `scale`, and an optional `mean` and `std`. A `node-regression` model
  has none.
- `labels`: the classes of a segmentation model, in the order it numbers them;
  none for the other types.
- `license` and `licenseFile`: the weights' license, and the file in the
  package that holds its text when it is not a standard license.
- `publisher`, `homepage` and `sizeBytes`: who published the weights, where
  they are described, and their size in bytes. The card and the details show
  them.

Every field is in [MODEL-CATALOG.md, The manifest](MODEL-CATALOG.md#6-the-manifest)
and in the [node package schema](schemas/node-package.v4.json).

---

## 5. Write the node that runs it

Keep the node's code short and put the work in a module beside it
([AUTHORING-NODES.md, Modules beside your template](AUTHORING-NODES.md#modules-beside-your-template)).
The node's code loads the model by its id and hands it to the module:

```python
from local_relief.run import local_relief

model = curio_load_model("model.example.local-relief")
return local_relief(input_0, model, min_height=[!! min_height !!], output_file=curio_output_file)
```

`curio_load_model("<id>")` loads the weights of the model package with that id,
from your Model Catalog. Name the id as a literal: Curio reads the ids from the
code before the run. A model that is not one of your models stops the node, with a message
saying to add it with Add in the Model Catalog.

The loaded model has one method for an ONNX model:

```python
outputs = model.run({"height": array})   # {input name: numpy array}, every input the graph takes
```

It returns the graph's outputs as a list, in the graph's order, so a model with
one output is read as `(relief,) = model.run(...)`. The onnxruntime session
opens on the first call and is kept for the next ones, so a node that runs the
model once per tile opens it once. A missing input is refused, with the names
the graph takes.

Write the module as you would any function that takes a model. Local Relief's,
`sources/local_relief/run.py`:

```python
import numpy as np
import rasterio

INPUT = "height"


def local_relief(raster, model, output_file, min_height=0.0):
    band = raster.read(1, masked=True)
    heights = band.filled(0).astype(np.float32)
    heights[heights < min_height] = 0  # lower than the lowest height: ground

    # The model reads (1, 1, rows, columns), as it was exported: NCHW.
    (relief,) = model.run({INPUT: heights[np.newaxis, np.newaxis]})
    relief = relief[0, 0].astype(np.float32)
    relief[np.ma.getmaskarray(band)] = np.nan

    profile = {
        "driver": "GTiff",
        "width": raster.width,
        "height": raster.height,
        "count": 1,
        "dtype": "float32",
        "crs": raster.crs,
        "transform": raster.transform,
        "nodata": float("nan"),
    }
    path = output_file("local-relief.tif")
    with rasterio.open(path, "w", **profile) as out:
        out.write(relief, 1)
    return rasterio.open(path)
```

What the node receives and returns:

- **Its inputs** are named after their circles: what the edge on circle 0
  delivers is `input_0`, on circle 1 `input_1`, and so on
  ([USAGE.md, Input names](USAGE.md#input-names)).
- **A raster** comes in as a rasterio dataset. Return one by writing a GeoTIFF
  where `curio_output_file("<name>.tif")` says, with a nodata value (NaN for
  float32), and returning it opened, as above.
- **A table or a layer** comes in as a DataFrame or a GeoDataFrame; return one.
- **What the user sets**, such as a season or a threshold, is a widget
  ([section 6](#6-widgets-what-the-user-sets)).

### Porting a model's code from another project

When the model comes with code that prepares its inputs and reads its outputs,
as SCOUT's models did, port that code instead of rewriting it. Keep its
functions' names and arithmetic. Take the model as an argument where the
original took its framework's model, call `model.run` where it called the
model, and read and return arrays where it read and wrote files. List every
change, and every bug of the original you fix, in the module's docstring.

Match the original's dtypes: a latitude computed in float64 where the original
used float32 shifts every prediction a little, and a comparison with the
original's results then fails by a hair. Deep Umbra's
[`deep_umbra.py`](../packages/model.scout.deep-umbra@1/sources/deep_umbra/deep_umbra.py)
and Weather Routing's
[`weight_calculation.py`](../packages/model.scout.weather-gnn@1/sources/weather_routing/weight_calculation.py)
are ported this way.

---

## 6. Widgets: what the user sets

A model takes only tensors. What the user chooses, such as a season, a place or
a threshold, is a widget of the node that runs the model, declared in the
template's `widgets` in the package's manifest. Each entry is the `widget`
definition (`$defs.widget`) of [the node package schema](schemas/node-package.v4.json).

Each widget has:

- `name`: letters, digits and underscores, not starting with a digit. Not
  `input_0`, `input_1` and so on: those names read the node's inputs. Curio
  refuses a manifest whose widget name breaks either rule, as the Widgets tab
  refuses the name.
- `type`: one of 13 kinds: `number`, `slider`, `text`, `choice`, `checkbox`,
  `checkbox-group`, `multi-select`, `datetime`, `location`, `number-list`,
  `text-list`, `range` and `file`. [USAGE.md, Widgets](USAGE.md#widgets) shows
  the control each kind draws and the value the code gets.
- `label`: what the Widgets tab calls it.
- `default`: the value a dropped node starts with.
- `options`: `choices` for a `choice`, `checkbox-group` or `multi-select`, and
  for a `choice` its `display`, `dropdown` or `radio`; `min`, `max`, `step` and
  `units` for a `number` or a `slider`, and a `slider` needs `min` and `max`.

Set the template's `hasWidgets` to `true`, so its node has the **Widgets** tab.

In the node's code, a widget is `[!! name !!]`. When the node runs, each one is
replaced by the widget's value, written in the code's language:
`min_height=[!! min_height !!]` runs as `min_height=3`. The module turns the
value into the model's inputs. Deep Umbra's **Season** becomes its `date`
input, a plane holding one number for the season, and sets how many minutes a
whole day in shadow counts: 360 in winter, 540 in spring and 720 in summer.
Local Relief's **Lowest height** sets every cell lower than it to 0 m in its
`height` input.

| Node | Its widgets |
|---|---|
| **Accumulated Shadow** (`model.scout.deep-umbra@1`) | `season` (`choice`, as radio buttons): spring, summer or winter. |
| **Weather Routing** (`model.scout.weather-gnn@1`) | `origin` and `destination` (`location`), `mode` (`choice`, a dropdown of Default, Custom and Single-factor weights), `K` (`number`, 1 to 3), `time` (`datetime`, the start time in Chicago), and `rain` and `wind` (`slider`, 0 to 1). |
| **Local Relief** (`model.example.local-relief@1`) | `min_height` (`number`, at least 0, in steps of 0.5 m): a cell lower than it reaches the model as ground. |

Accumulated Shadow's Season, as its manifest declares it:

```json
{ "name": "season", "type": "choice", "label": "Season", "default": "summer",
  "options": { "choices": ["spring", "summer", "winter"], "display": "radio" } }
```

Local Relief's Lowest height:

```json
{ "name": "min_height", "type": "number", "label": "Lowest height", "default": 0,
  "options": { "min": 0, "step": 0.5, "units": "m" } }
```

A dropped node copies its template's widgets into its own, saved with the
dataflow in the node's `metadata.widgets`. The user sets their values in the
node's **Widgets** tab, or adds widgets of their own there and places them in
the code; the package stays as it is. A changed value marks the node as needing
a new run.

`[!! @name !!]` reads a **Parameter** node's value instead: one value that
several nodes share
([USAGE.md, Shared values](USAGE.md#shared-values-the-parameter-node)). In the
[ScoutShadows](examples/dataflows/ScoutShadows.json) dataflow, both scenarios'
Accumulated Shadow nodes read one season this way.

**Save as package node…** writes a node's widgets into the template it makes,
with their values as the defaults
([AUTHORING-NODES.md, Widgets in a template](AUTHORING-NODES.md#widgets-in-a-template)).

---

## 7. Add the model to Curio

**From an archive, in any Curio.** Zip the package's files so that
`manifest.json` is at the archive's root. Leave out `integrity.json`,
`__pycache__` folders and dotfiles: **Import package** refuses them.

```bash
cd model.example.local-relief@1
zip -r ../model.example.local-relief@1.curio.zip manifest.json models sources -x '*__pycache__*' '*/.*'
```

On the canvas, open the **Model Catalog** drawer from the top bar and click
**Import package** in its footer: the model joins your account and the open
dataflow. On the `/catalog/models` page, **Import package** in the header adds
it to your account.

**From a clone, for every user of the install.** Copy the folder into
`packages/`, write its `integrity.json` with
[`scripts/regen_integrity.py`](../scripts/regen_integrity.py)
(`python scripts/regen_integrity.py packages/<id>@1`), and restart Curio
([MODEL-CATALOG.md, Operator notes](MODEL-CATALOG.md#operator-notes)).

Then the model works as every model of the Model Catalog does
([MODEL-CATALOG.md, Surfaces and workflows](MODEL-CATALOG.md#2-surfaces-and-workflows)):

- **Add to project** in the drawer, or **Add to all projects** on the
  `/catalog/models` page, shows a review of the model's permissions and
  libraries, then installs the libraries. An account that may not install
  libraries cannot add a model.
- **Dragging its card onto the canvas** drops its node, whose code names the
  model with `curio_load_model("<id>")`. A dataflow that does not have the
  model goes through the review of **Add to project** first. Dragging the card
  onto a node that runs a model of the same type runs it there.
- **Remove from project** in the drawer takes it out of the dataflow, and is
  refused while its node is on the canvas. **Remove from account**, on the
  `/catalog/models` page, removes a model of your own that no dataflow uses.
- **Export**, in the model's details, saves `<id>@<major>.curio.zip` with the
  weights, which **Import package** reads in any Curio. **Publish**, on the
  `/catalog/models` page, lets every user of the install browse and add it.
- **Save as package node…**, from the cog on a node's header, makes a model
  package of its own from a node whose code loads one of your models: it copies
  the model's weights and its `model` block, and the node's code names the new
  package's id.

---

## 8. Test the node

Give the package a test that runs the node's code as a run runs it, and
compares the answer with one you trust. The worked example's tests,
[`test_local_relief.py`](../utk_curio/sandbox/tests/test_local_relief.py) and
the Local Relief tests of
[`test_model_packages.py`](../utk_curio/backend/tests/test_packages/test_model_packages.py),
do what such a test should:

1. The manifest is one Curio takes: the schema validates it and the parser
   reads its `model` block.
2. The ONNX file gives known answers on inputs the export never traced.
3. The node's code, its widget resolved as a run resolves it, runs in the
   sandbox with the package's module and the model the account's store
   resolves, and its output matches a reference computed another way.
4. The widget's value reaches the model: two values give the model's answers
   for two different inputs.

For a model ported from another project, the reference is that project's own
results: the SCOUT tests compare Curio's shadows and routes with the ones
SCOUT's code wrote
([sections 10](#10-case-study-deep-umbra-tensorflow-image-to-image) and
[11](#11-case-study-the-weather-gnn-pytorch-geometric-graph-regression)).

---

## 9. Worked example: Local Relief

Every file of this example is in the repository's
[`docs/bring-your-own-model/`](bring-your-own-model/) folder.

**The model.** Local Relief takes a raster of building heights and returns, for
each cell, how many metres it stands above the mean height of the 5 by 5 cells
around it: positive on a building's edge above the street, negative on the
street beside a tall building, 0 on flat ground. Its weights are fixed, so you
can check its answer by hand. It stands in for the network you trained, and
every step is the same for yours.

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
`model.example.local-relief@1/models/local_relief.onnx` (2.4 KB), with rows and
columns free, then checks it: onnxruntime against PyTorch and against a numpy
reference, on the traced 64 by 64, on 37 by 90, on a flat raster and on a lone
tower. It exits with status 1 when a check fails. The committed file is what it
wrote.

**Step 2: add the model.** The package is
[`model.example.local-relief@1/`](bring-your-own-model/model.example.local-relief@1/).
Zip it and import it in the **Model Catalog** drawer
([section 7](#7-add-the-model-to-curio)):

```bash
cd docs/bring-your-own-model/model.example.local-relief@1
zip -r ../../../model.example.local-relief@1.curio.zip manifest.json models sources -x '*__pycache__*' '*/.*'
```

**Local Relief (example)** shows in the drawer's **In project** tab.

**Step 3: build the dataflow.**

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

2. Drag the **Local Relief (example)** card from the drawer onto the canvas:
   its **Local Relief** node appears. Connect Make Heights to it.
3. Drop an **Autark** node, connect Local Relief to it, and give it this map:

   ```json
   {
     "map": {
       "layerRefs": [
         {
           "dataRef": "input_0",
           "title": "Local relief (m)",
           "getFnv": "band_1",
           "colorMapInterpolator": "interpolateRdBu",
           "colorMapCenter": 0,
           "colorMapReverse": true
         }
       ]
     }
   }
   ```

   `colorMapCenter` puts 0 at the middle of the scheme, and `colorMapReverse`
   puts red above it ([USAGE.md, Layer titles and colors](USAGE.md#layer-titles-and-colors)).
4. Click **Run All**. The map shows flat ground and the buildings' flat tops
   white (0), the buildings' edges red, above the street around them, and the
   street beside them blue, below the buildings next to it.
5. In Local Relief's **Widgets** tab, set **Lowest height** to 40 and run
   again. The 30 m block reaches the model as ground and leaves the map; the
   tower stays as it was.

With real data, connect any height raster in place of Make Heights.

**Step 4: test it.** The tests read the example's files where they are in
`docs/`. Run each suite on its own, from the repository's root:

```bash
python -m pytest utk_curio/sandbox/tests/test_local_relief.py
python -m pytest utk_curio/backend/tests/test_packages/test_model_packages.py
```

[`test_local_relief.py`](../utk_curio/sandbox/tests/test_local_relief.py)
checks the model and the module against numpy, and
[`test_model_packages.py`](../utk_curio/backend/tests/test_packages/test_model_packages.py)
runs the node's code through the package with Lowest height at its default and
at 3 m.

---

## 10. Case study: Deep Umbra (TensorFlow, image to image)

[SCOUT](https://github.com/urban-toolkit/scout)'s accumulated shadow model is a
TensorFlow generator restored from a checkpoint (`tf_model/ckpt-44`). In Curio
it is the model package
[`model.scout.deep-umbra@1`](../packages/model.scout.deep-umbra@1/), with the
**Accumulated Shadow** node and the weights `models/deep_umbra.onnx`, about
10.5 MB.

| Step | What was done |
|---|---|
| Export | [`scripts/scout/export_deep_umbra.py`](../scripts/scout/export_deep_umbra.py), in SCOUT's environment (Python 3.11, TensorFlow 2.12, tf2onnx 1.16.1). It imports SCOUT's own `deep_umbra.py`, restores the generator with SCOUT's `get_deep_shadow()`, checks that every variable was restored, and exports with `tf2onnx.convert.from_function`: inputs `height`, `latitude` and `date`, output `shadow`, each 1 by 512 by 512 by 1, float32. |
| The catch | SCOUT runs the generator with `training=True`, so its batch normalization uses each tile's own statistics, not the checkpoint's averages. The export keeps that ([below](#batch-normalization-in-training-mode)), so the model runs one tile per call. |
| Checks | ONNX against TensorFlow on SCOUT's committed height tiles; ONNX far from TensorFlow's `training=False`, and unchanged by an export with scrambled averages; the port's inputs against SCOUT's; the port's shadows and metrics against SCOUT's committed ones. |
| Node code | Three lines: `from deep_umbra import accumulated_shadow`, `model = curio_load_model("model.scout.deep-umbra")`, and `return accumulated_shadow(input_0, season=[!! season !!], model=model, output_file=curio_output_file)`. The module `deep_umbra` holds SCOUT's functions, with `model.run` for the generator ([`deep_umbra.py`](../packages/model.scout.deep-umbra@1/sources/deep_umbra/deep_umbra.py)), and the node's input checks, 8-bit height levels, 768 by 768 neighbourhoods and the shadow raster, written with Curio's raster helpers ([`node_outputs.py`](../packages/model.scout.deep-umbra@1/sources/deep_umbra/node_outputs.py)). |
| Widget | **Season**: spring, summer or winter. |
| Result | Each tile within 6 gray levels of SCOUT's committed shadow tile, on at most 6% of its pixels, and the mean and median shadow within 0.1 and 0.05 minutes of SCOUT's, for both of SCOUT's scenarios ([`test_scout_shadow.py`](../utk_curio/backend/tests/test_packages/test_scout_shadow.py)). |

## 11. Case study: the weather GNN (PyTorch Geometric, graph regression)

SCOUT's weather-aware routing weighs each road by the weather a small graph
network predicts on it: two GraphSAGE layers (`SAGEConv`, mean aggregation) and
a linear head, from `rain_model.pth`. In Curio it is the model package
[`model.scout.weather-gnn@1`](../packages/model.scout.weather-gnn@1/), with the
**Weather Routing** node and the weights `models/weather_gnn.onnx`, about 52 KB.

| Step | What was done |
|---|---|
| Export | [`scripts/scout/export_weather_gnn.py`](../scripts/scout/export_weather_gnn.py), in SCOUT's environment (Python 3.9, torch 2.2.2, torch-geometric 2.6.1). It builds SCOUT's `NodeRegressor`, loads the weights with every key used, and exports with the TorchScript exporter (`torch.onnx.export`, opset 17): inputs `x` (nodes by 7) and `edge_index` (2 by edges, int64), output `prediction` (nodes by 5), with the node and edge counts free. Mean aggregation exports as ordinary ONNX operators, so running the model needs no torch-geometric. |
| Checks | onnxruntime against torch on graphs of other sizes than the traced one: repeated edges, nodes without edges, a graph with no edges; and against the inputs and prediction recorded from SCOUT's own run. |
| Node code | The cell reads the SCOUT WRF forecast with `curio_data_path("<id>")`, loads the model with `curio_load_model("model.scout.weather-gnn")` and calls the module `weather_routing`. [`weight_calculation.py`](../packages/model.scout.weather-gnn@1/sources/weather_routing/weight_calculation.py) is SCOUT's, with `model.run({"x": x, "edge_index": edge_index})` for the torch call; [`road_graph.py`](../packages/model.scout.weather-gnn@1/sources/weather_routing/road_graph.py) builds the road graph from the roads an Autark node loads. The SCOUT bugs the port fixes are listed in [`weather_routing.py`](../packages/model.scout.weather-gnn@1/sources/weather_routing/weather_routing.py). |
| Widgets | **Origin**, **Destination**, **Mode**, **Routes per factor (K)**, **Start time (Chicago)**, **Rain weight** and **Wind weight**. |
| Result | For each of SCOUT's 8 recorded runs, the network's input bit for bit, the routes node for node, and the metrics within 0.001 of SCOUT's ([`test_scout_routing.py`](../utk_curio/backend/tests/test_packages/test_scout_routing.py)). The [WeatherRouting](examples/dataflows/WeatherRouting.json) dataflow runs it. |

---

## 12. Things that will trip you up

### Batch normalization in training mode

A batch normalization layer normalizes with the averages it learnt when the
model is in inference mode, and with the statistics of the batch it is given
when it is in training mode. Some projects run their model in training mode:
SCOUT calls Deep Umbra with `training=True`. Export in the mode the original
runs in, then check. An export in the other mode runs and answers plausibly,
and only a comparison with the original's results shows it is wrong.

To keep training mode, Deep Umbra's export sets each layer's `momentum` to 0
before tracing, so TensorFlow's fused batch norm carries an average factor of
1.0, which tf2onnx turns into a normalization by the input's own statistics.
Those statistics mix across a batch, so the model is fed one input at a time,
as SCOUT feeds it.

### A dimension the export fixed

An export traces the model on the example input you give it. Any dimension you
did not declare free is the example's size in the exported file. Declare it
free (`dynamic_shapes`, `dynamic_axes`) and test on another size.

### Dtypes

ONNX takes the dtype you exported with. Feed `float32` where the model reads
float32 (`array.astype(np.float32)`) and `int64` for indices such as a graph's
`edge_index`. A reshape that drops the batch dimension, or NHWC fed to a model
exported NCHW, fails with a shape error at `model.run`.

### Operators the converter cannot export

An extension library's custom operator (a scatter, a sparse matrix product) may
not convert. Try the other PyTorch exporter, a newer opset, or an equivalent
built from plain operators. GraphSAGE with mean aggregation exports as is.

### The node says the model is not one of your models

The node's code names the model as a literal, `curio_load_model("<id>")`, and
the model must be one of the models of whoever runs the dataflow. Send them the
model's archive (**Export**), or publish it for them to add.

### A license

Record the weights' license in the `model` block's `license`, with its text in
the package (`licenseFile`) when it is not a standard license. A model someone
else trained needs their permission to be shared: SCOUT's models carry their
authors' permission.

---

## 13. Checklist

- [ ] An export script, committed, with the environment's versions at its top.
- [ ] Named inputs and outputs, and the free dimensions declared free.
- [ ] Exported in the mode the original runs the model in.
- [ ] The export checked against the framework, on other sizes and edge cases,
      and against results you trust; a failed check exits non-zero.
- [ ] A model package `<id>@<major>/`: `manifest.json` with `kind` `model`, the
      code's `license`, and a `model` block (`type`, `runtime` `onnx`, `entry`
      under `models/`, `input` for an image model, the weights' `license`); the
      `.onnx` file under `models/`; one template.
- [ ] The node's code calls `curio_load_model("<id>")` with a literal id, its
      model code is in a module under `sources/`, and its Python libraries are
      in `dependencies.python`.
- [ ] What the user sets is a widget of the template, read with `[!! name !!]`.
- [ ] A test that runs the node and compares its output with a reference.

## See also

- [MODEL-CATALOG.md](MODEL-CATALOG.md): the Model Catalog, and every manifest field.
- [AUTHORING-NODES.md](AUTHORING-NODES.md): writing a node package, its widgets and its modules.
- [NODE-CATALOG.md](NODE-CATALOG.md): how packages are installed and shared.
- [USAGE.md](USAGE.md): building and running dataflows, widgets and Parameter nodes.
