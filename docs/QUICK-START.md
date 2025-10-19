# Quick start

Before you begin, please read our [usage guide](USAGE.md).

## Creating a barchart

In this tutorial, we are going to learn how Curio can easily help with visualizing a simple dataset using a Vega-Lite barchart. 

After initializing Curio, we can see a blank canvas like this:

![Blank canvas](images/blank.png?raw=true)

The icons on the left-hand side can be used to instantiate different nodes, including visualization ones. Let's start by instantiating a `Data Loading` node (1) and changing its view to `Code` (2). External files can be referenced through regular Python file handling functions, given that the file was uploaded to the server. However, for simplicity's sake, we will use the following synthetic dataset (3):

![Data loading](images/data_loading.png?raw=true)

```console
import pandas as pd

d = {'a': ["A", "B", "C", "D", "E", "F", "G", "H", "I"], 'b': [28, 55, 43, 91, 81, 53, 19, 87, 52]}
df = pd.DataFrame(data=d)

return df
```

After hitting run (4). The Python `return` will output `df` for the next node.

We can now proceed and create a `Vega-Lite` node (1) that will be connected to the first box (2) and render the barchart. This time, we are going to use the `Grammar` view (3) to create the Vega-Lite specification:

![Vega lite](images/vega_lite.png?raw=true)

```console
{
  "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
  "description": "A simple bar chart with embedded data.",
  "mark": "bar",
  "encoding": {
    "x": {"field": "a", "type": "nominal", "axis": {"labelAngle": 0}},
    "y": {"field": "b", "type": "quantitative"}
  }
}
```

Curio handles the dataflow and `Vega-Lite` has access to the DataFrame outputed by the previous box. After hitting run, we can see that a barchart was created:

![Final result](images/final_result.png?raw=true)

Congratulations! You created your first data-flow using Curio :)

