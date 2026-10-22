## How nodes are controlled

Nodes are uncontrollable, controllable through code (python or JavaScript) or controllable through grammar:

{{builtin.control}}

An output connection of a node can be connected to the input connection of different nodes.

To pass data forward from a node controllable through python code it is necessary to return it, for example:

```python
    variable1 = 123

    return variable1
```

To use incoming data in a node controllable through python code, read each input through its input chip: `{{inputs.chip:0}}` is the input on circle 0, `{{inputs.chip:1}}` the one on circle 1, and so on. Each input circle is its own variable, named after the circle, so the chip becomes `input_0`, `input_1`, ... when the node runs, and a node with two inputs can combine them like:

```python
    combining_previous_inputs = {{inputs.chip:0}} + {{inputs.chip:1}}

    return combining_previous_inputs
```

Where a column name is written, a column chip such as `{{inputs.chip:0.population}}` becomes the quoted name of that column of input_0. A chip is code, never text: do not put an input chip inside a string or a comment. If the previous box outputs a tuple, its input is that tuple and can be indexed like any tuple.

An input that carries several layers, such as the tables an {{template.label:curio.builtin/autk-grammar}} node hands on, is read one layer at a time through a layer chip: `{{inputs.chip:0:table_osm_roads}}` becomes `curio_layer(input_0, "table_osm_roads", 0)`, that layer of input_0, a GeoDataFrame in python and a GeoJSON FeatureCollection in JavaScript, and `{{inputs.chip:0:table_osm_roads.lanes}}` becomes the quoted name of a column of it. An input that is one frame with no layer name is that layer.

But if the previous node outputs a single data like, but not limited to, a dataframe or number or text, its input will contain that value, not an indexable list.

```python
    return {{inputs.chip:0}}
```

Every data received from a node controllable through grammar is automatically passed forward to its output connection. 

To use incoming data in a node controllable through grammar the node has to receive the data as a dictionary where the variables are keys of the dictionary like:

```python
    import pandas as pd

    d = {'a': ["A", "B", "C", "D", "E", "F", "G", "H", "I"], 'b': [28, 55, 43, 91, 81, 53, 19, 87, 52]}
    df = pd.DataFrame(data=d)

    return df
```

When generating the grammar for Vega-Lite do not include the data field. It will be populated automatically based on the dataframe of the previous node. For example we can connect the previous dataframe into this Vega-Lite grammar:

```json
{
  "$schema": "{{vega.schema_url}}",
  "mark": "bar",
  "encoding": {
    "x": {"field": "a", "type": "nominal", "axis": {"labelAngle": 0}},
    "y": {"field": "b", "type": "quantitative"}
  }
}
```
