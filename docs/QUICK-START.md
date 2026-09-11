# Quick start

Before you begin, please read our [usage guide](USAGE.md).

## Creating a barchart

In this tutorial, we are going to learn how Curio can easily help with visualizing a simple dataset using a Vega-Lite barchart.

After initializing Curio, you will see a blank canvas. The left rail holds icons for each built-in node type; drag any of them onto the canvas to instantiate a node. Below them sit the **Node Catalog** and **Data Catalog** dropdowns, which is where extra nodes and datasets come from once you need them.

Start by dragging a `Data Loading` node onto the canvas. Inside the node, switch to the `Code` view and enter the following snippet:

```python
import pandas as pd

d = {'a': ["A", "B", "C", "D", "E", "F", "G", "H", "I"], 'b': [28, 55, 43, 91, 81, 53, 19, 87, 52]}
df = pd.DataFrame(data=d)

return df
```

Hit **Run**. The Python `return` outputs `df` for the next node.

The dataset above is written inline because it is three lines long. A
`Data Loading` node has no file picker of its own: to work from a CSV or
GeoJSON, import it through **Data ⏷ → Data Catalog** and drag the dataset onto
the canvas, which creates a `Data Loading` node already wired to it. See
[DATA-CATALOG.md](DATA-CATALOG.md#3-using-a-dataset-in-a-dataflow). If you want
the node itself to prompt for a path when it runs, declare a file widget in the
code with the marker `[!! path$FILE !!]`.

Next, drag a `Vega-Lite` node onto the canvas and connect its input handle to the output of the `Data Loading` node. Switch to the `Grammar` view and enter the following Vega-Lite specification:

```json
{
  "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
  "mark": "bar",
  "encoding": {
    "x": {"field": "a", "type": "nominal", "axis": {"labelAngle": 0}},
    "y": {"field": "b", "type": "quantitative", "stack": null}
  }
}
```

Hit **Run**. Curio handles the dataflow and `Vega-Lite` has access to the DataFrame output by the previous node. You should see a barchart like this:

![Final result](images/final_result.png?raw=true)

Congratulations! You created your first data-flow using Curio :)
