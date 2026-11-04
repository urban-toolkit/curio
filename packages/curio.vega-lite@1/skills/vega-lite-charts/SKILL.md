---
name: vega-lite-charts
description: >-
  Use this skill when a dataflow uses Vega-Lite (curio.vega-lite@1) and a task writes, wires or fixes
  one of its fifteen charts that compare scenarios, one input per scenario: lines with a band, curves
  by group, bars with error bars, ensemble strips, stacked bars with totals, donuts, a weighted matrix,
  dots with a range, bars, grouped bars, lines, points, a pie, lollipops or a table. It gives which
  chart draws what, and how a chart reads its stacked inputs, sets its column widgets, and colors and
  orders its scenarios.
license: MIT
compatibility: Written for Curio's agents, on a dataflow that uses Curio's Vega-Lite package, curio.vega-lite@1.
metadata:
  author: curio
  version: "1.0.0"
  curio-templates: >-
    lines-with-band curves-by-group bars-with-error-bars ensemble-strips stacked-bars-with-totals
    donuts weighted-matrix dots-with-a-range bars grouped-bars lines points pie lollipops table
---
## Vega-Lite charts

The Vega-Lite package is fifteen Vega-Lite charts that compare scenarios. A plan names each by its node type, `curio.vega-lite/<id>`, and a dataflow that holds the package lists them under **Vega-Lite** in the Tools panel's **Node Catalog** dropdown.

### Which node

- A chart that compares scenarios is one of the fifteen charts, each a node type of its own: `lines-with-band`, `curves-by-group`, `bars-with-error-bars`, `ensemble-strips`, `stacked-bars-with-totals`, `donuts`, `weighted-matrix`, `dots-with-a-range`, `bars`, `grouped-bars`, `lines`, `points`, `pie`, `lollipops` and `table`.

### The charts

- Connect each scenario's outcome to an input circle of its own: each edge takes the next circle.
- The spec reads every input as the dataset its chip names, `"data": {"name": "[!! inputs !!]"}`: the inputs' rows stacked in circle order, each with `__input__` (its circle), `scenario` (the id of the scenario box its input comes from) and `scenario_name` (that box's name) beside its own columns. A column one input lacks is empty in its rows, an input that is a single value is one row with a `value` column, and an input from a node in no box has an empty `scenario` and its node's name as `scenario_name`.
- The columns a chart plots are text widgets, each naming a column of the inputs: `x`, `y`, `low`, `high`, `facet`, `group`, `error`, `part`, `value`, `factor`, `weight` and `category`. A new node's widgets hold their own names, so set each to a column the inputs have. `columns`, the Table's, is a list of the column names it shows, in order. With `facet` empty, Lines with a band draws one panel.
- `combine` is the Vega-Lite aggregate of a scenario's rows: `mean`, `sum`, `median`, `min`, `max` or `count`. `x_type`, the Lines', is `quantitative`, `temporal`, `ordinal` or `nominal`, as the X column holds numbers, dates or names. `highlight` is the value of `part` that Donuts colors. The widgets ending in `_title` are titles, none when empty, and `y_format` is a d3 format, such as `.0%` or `,.1f`.
- The spec reads each widget through its chip, such as `"field": "[!! y !!]"` and `"aggregate": "[!! combine !!]"`.
- Scenario colors and order are chips: a color, fill or stroke by `scenario_name` takes `"scale": [!! scenario colors !!]`, the colors of the scenario boxes, and an axis, an offset or a facet by it takes `"sort": [!! scenario order !!]`, the order the dataflow lists the boxes. Text in each scenario's color takes `[!! scenario text_colors !!]`. Keep the chips: a scale written in their place draws its own colors, not the boxes'.
- A column name that holds `'` cannot be read: rename the column upstream. A name that holds `.` or `[`, such as `rain.mm`, is set in its widget as it is, and the chip escapes it where Vega-Lite reads a field. Bars with error bars draws no error bars for such a Y column.
