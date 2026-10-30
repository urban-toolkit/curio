---
name: scout
description: >-
  Use this skill whenever a dataflow uses Scout (curio.scout@1) and the user asks how to compute,
  chart, set or wire something there, even if they name no Scout node: math or statistics over
  rasters, such as two scenarios' difference or a mean over some cells, a buildings layer
  rasterized for the shadow model, or a chart comparing scenarios. It gives the Raster
  Calculator's calls and its rules on grids, masks and zones, what Rasterize Buildings writes and
  which of its settings the shadow model needs, and how Scout's fifteen charts read one input per
  scenario, set their column widgets, and color and order the scenarios.
license: MIT
compatibility: Written for Curio's agents, on a dataflow that uses Curio's Scout package, curio.scout@1.
metadata:
  author: curio
  version: "1.0.0"
  curio-templates: >-
    raster-calculator rasterize-buildings lines-with-band curves-by-group bars-with-error-bars
    ensemble-strips stacked-bars-with-totals donuts weighted-matrix dots-with-a-range bars
    grouped-bars lines points pie lollipops table
---
## Scout

Scout is SCOUT's nodes in Curio: two raster nodes and fifteen Vega-Lite charts that compare scenarios. A plan names each by its node type, `curio.scout/<id>`, and a dataflow that holds the package lists them under **Scout** in the Tools panel's **Node Catalog** dropdown.

### Which node

- A raster computed from rasters, such as the difference of two scenarios' rasters or a class chosen per cell, and a raster's mean, median, minimum, maximum and count, is a Raster Calculator node, `curio.scout/raster-calculator`. A Python node of no package cannot import Scout's functions, so a raster step is never one.
- Heights drawn from a buildings layer, for an Autark map or for Deep Umbra's Accumulated Shadow, are a Rasterize Buildings node, `curio.scout/rasterize-buildings`.
- A chart that compares scenarios is one of the fifteen charts, each a node type of its own: `lines-with-band`, `curves-by-group`, `bars-with-error-bars`, `ensemble-strips`, `stacked-bars-with-totals`, `donuts`, `weighted-matrix`, `dots-with-a-range`, `bars`, `grouped-bars`, `lines`, `points`, `pie`, `lollipops` and `table`.

### The Raster Calculator

Its code is Python that imports the operations from the package's module and returns one call:

```python
from scout_rasters.raster_algebra import raster_calculate, raster_statistics

return raster_calculate("subtract", [input_0, input_1], output_file=curio_output_file)
```

| Call | Returns |
|---|---|
| `raster_calculate("add", [input_0, input_1], output_file=curio_output_file)` | input_0 plus input_1, cell by cell; also `"subtract"` (input_0 minus input_1), `"multiply"` and `"divide"`, where a cell divided by 0 has no value |
| `raster_calculate("choose", [input_0, input_1, input_2], codes=[21, 31], output_file=curio_output_file)` | input_1 where input_0's class is one of the codes, input_2 elsewhere |
| `raster_calculate("subtract", [input_1, input_0], absolute=True, output_file=curio_output_file)` | how much each cell changed, 0 where it did not: `absolute=True` takes the size of any operation's result |
| `raster_statistics(input_0)` | the `mean`, `median`, `min`, `max` and `count` of the cells with a value, as a table of one row |
| `raster_statistics(input_0, mask=input_1, mask_values=[0])` | the same over the cells where the mask, a raster on the same grid on input_1, is 0 |
| `raster_statistics(input_0, where=lambda value: value < 1.08)` | the same over the cells whose value meets the condition; with a mask, the condition tests the mask's values |

- The rasters come in on its input circles, one to three, in order: `input_0`, `input_1`, `input_2`.
- The rasters an operation reads are on one grid. Rasters on different grids are refused, so bring them to one grid upstream.
- A raster it returns is written with `curio_output_file`: pass `output_file=curio_output_file` to every `raster_calculate`.
- A cell with no value in an input the operation reads has no value in the result.
- A difference is signed, input_0 minus input_1. Take `absolute=True` only when the task asks how much each cell changed, whichever way.
- A circle may take a GeoDataFrame, which the code reads as zones or a mask, for example rasterized on a raster's grid with `rasterio.features.rasterize`, or a JSON value, which it reads as it is, such as a region's corners.
- A node of another package imports these functions when that package names Scout in its manifest's `dependencies.packages`, `{"curio.scout@1": "*"}`, as Deep Umbra's does.

### Rasterize Buildings

- Its input is a buildings GeoDataFrame: polygons, a CRS, and a column of heights in metres.
- Its widgets are `attribute`, the height column (`height`); `zoom`, the zoom level of the map tiles (16); and `max_height`, the height drawn as gray level 255 (550 m). Deep Umbra reads zoom-16 tiles where 255 is 550 m, so keep both for Accumulated Shadow.
- Its output is one RASTER: the tiles side by side in one GeoTIFF in EPSG:3395, one band of heights in metres, each gray level 2.16 m at 550 m. An Autark map draws it as `{"dataRef": "input_0", "getFnv": "band_1"}`.
- A tile with no building near it has no value, which a map, a Raster Calculator's statistics and Accumulated Shadow leave out. In a tile it writes, a cell with no building is 0, the ground. A building with no height adds nothing, and one taller than `max_height` is drawn at `max_height`.

### The charts

- Connect each scenario's outcome to an input circle of its own: each edge takes the next circle.
- The spec reads every input as the dataset its chip names, `"data": {"name": "[!! inputs !!]"}`: the inputs' rows stacked in circle order, each with `__input__` (its circle), `scenario` (the id of the scenario box its input comes from) and `scenario_name` (that box's name) beside its own columns. A column one input lacks is empty in its rows, an input that is a single value is one row with a `value` column, and an input from a node in no box has an empty `scenario` and its node's name as `scenario_name`.
- The columns a chart plots are text widgets, each naming a column of the inputs: `x`, `y`, `low`, `high`, `facet`, `group`, `error`, `part`, `value`, `factor`, `weight` and `category`. A new node's widgets hold their own names, so set each to a column the inputs have. `columns`, the Table's, is a list of the column names it shows, in order. With `facet` empty, Lines with a band draws one panel.
- `combine` is the Vega-Lite aggregate of a scenario's rows: `mean`, `sum`, `median`, `min`, `max` or `count`. `x_type`, the Lines', is `quantitative`, `temporal`, `ordinal` or `nominal`, as the X column holds numbers, dates or names. `highlight` is the value of `part` that Donuts colors. The widgets ending in `_title` are titles, none when empty, and `y_format` is a d3 format, such as `.0%` or `,.1f`.
- The spec reads each widget through its chip, such as `"field": "[!! y !!]"` and `"aggregate": "[!! combine !!]"`.
- Scenario colors and order are chips: a color, fill or stroke by `scenario_name` takes `"scale": [!! scenario colors !!]`, the colors of the scenario boxes, and an axis, an offset or a facet by it takes `"sort": [!! scenario order !!]`, the order the dataflow lists the boxes. Text in each scenario's color takes `[!! scenario text_colors !!]`. Keep the chips: a scale written in their place draws its own colors, not the boxes'.
- A column name that holds `'` cannot be read: rename the column upstream. A name that holds `.` or `[`, such as `rain.mm`, is set in its widget as it is, and the chip escapes it where Vega-Lite reads a field. Bars with error bars draws no error bars for such a Y column.
