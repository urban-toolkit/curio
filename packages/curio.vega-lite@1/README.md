# `curio.vega-lite@1`: Vega-Lite

Fifteen Vega-Lite charts that compare scenarios. Each takes one input per
scenario and draws each scenario in its box's color, through its scenario chips.

Once the package is in a dataflow (**Add to project** in the Node Catalog
drawer), its fifteen nodes are under **Vega-Lite** in the Tools panel's **Node
Catalog** dropdown.

## Nodes

| Canonical id | Label | What it draws | Widgets |
|---|---|---|---|
| `curio.vega-lite/lines-with-band` | Lines with a band | One line per scenario over `x`, a band from `low` to `high` around it, and a panel per value of the `facet` column | `x`, `y`, `low`, `high`, `facet`, `x_title`, `y_title`, `y_format` |
| `curio.vega-lite/curves-by-group` | Curves by group | One curve per scenario and group over `x`, each group in a dash of its own | `x`, `y`, `group`, `x_title`, `y_title`, `y_format`, `group_title` |
| `curio.vega-lite/bars-with-error-bars` | Bars with error bars | Bars per category of `x`, the scenarios side by side, each `y` plus or minus its `error` | `x`, `y`, `error`, `x_title`, `y_title`, `y_format` |
| `curio.vega-lite/ensemble-strips` | Ensemble strips | A tick per row for each scenario, such as the runs of an ensemble, and a black tick at its median | `y`, `y_title`, `y_format` |
| `curio.vega-lite/stacked-bars-with-totals` | Stacked bars with totals | One bar per scenario, stacked by `part` in the table's row order, its total on top | `y`, `part`, `y_title`, `y_format`, `part_title` |
| `curio.vega-lite/donuts` | Donuts | One donut per scenario: the `highlight` part in the scenario's color, the rest grey, each slice's share of the `value` total in percent | `part`, `value`, `highlight` |
| `curio.vega-lite/weighted-matrix` | Weighted matrix | One ring per `factor` and scenario, sized by its `weight` from -1 to 1, green for and red against; a weight of 0 draws no ring | `factor`, `weight` |
| `curio.vega-lite/dots-with-a-range` | Dots with a range | For each `category`, a grey rule from its lowest `value` to its highest and a dot per scenario, the categories the scenarios differ most on first | `category`, `value`, `x_title`, `y_title` |
| `curio.vega-lite/bars` | Bars | One bar per scenario, its `y` values combined | `y`, `combine`, `y_title` |
| `curio.vega-lite/grouped-bars` | Grouped bars | Bars per category of `x`, the scenarios side by side, `y` combined per category | `x`, `y`, `combine`, `x_title`, `y_title` |
| `curio.vega-lite/lines` | Lines | One line per scenario over `x`, a point at each value, `y` combined per value of `x` | `x`, `x_type`, `y`, `combine`, `x_title`, `y_title` |
| `curio.vega-lite/points` | Points | One point per row, `x` against `y` | `x`, `y`, `x_title`, `y_title` |
| `curio.vega-lite/pie` | Pie | One slice per scenario, its `value` combined and written on it | `value`, `combine`, `value_title` |
| `curio.vega-lite/lollipops` | Lollipops | One stem from 0 and one dot per scenario, at its `value` combined | `value`, `combine`, `x_title` |
| `curio.vega-lite/table` | Table | The inputs' rows, up to 40, in the `columns` it lists | `columns` |

## Charts

Each chart is a Vega-Lite node with a spec of its own. Connect each scenario's
outcome to one of its input circles: each edge takes the next circle. Its spec
reads all its inputs as the dataset its chip names (`"data": {"name": "[!! inputs !!]"}`):
every input's rows, stacked in the order of its circles, each with `__input__`
(its circle), `scenario` (the id of the scenario box its input comes from) and
`scenario_name` (that box's name) beside its own columns. A column one input
lacks is empty in its rows, and an input that is a single value is one row with
a `value` column. An input from a node in no box has an empty `scenario` and
its node's name. The columns a chart plots are widgets in its **Widgets** tab.

A new chart opens with its template's spec in its grammar editor. The spec is
yours to edit: its chips, its widgets' and its scenarios', are written each time
it draws, and the dataflow keeps the spec as you leave it.

### Widgets

- A column widget (`x`, `y`, `low`, `high`, `facet`, `group`, `error`, `part`,
  `value`, `factor`, `weight`, `category`) is a text widget that names a column
  of the inputs. A new node's widgets hold their own names, so the chart says
  which column the inputs lack until you set them. With `facet` empty, Lines
  with a band draws one panel.
- `columns`, the Table's, is a list of texts that names the columns it shows,
  in order, such as `["scenario_name", "cost_per_m2"]`. A new Table lists
  `scenario_name`.
- `combine` is the Vega-Lite aggregate that combines the values of a
  scenario's rows: `mean`, `sum`, `median`, `min`, `max` or `count`, the number
  of rows. It starts at `sum` in Pie and at `mean` elsewhere. Grouped bars
  combine per category, and Lines per value of `x`.
- `x_type`, the Lines', is the kind of the X column: `quantitative`, `temporal`,
  `ordinal` or `nominal`. Pick the one that matches the X column: `temporal` for
  dates, `quantitative` for numbers, `ordinal` or `nominal` for names.
- `highlight` is the value of the `part` column that Donuts colors.
- `x_title`, `y_title`, `group_title` and `part_title` are titles; empty, the
  axis or the legend has none.
- `value_title`, Pie's, names the value in the arcs' tooltips; empty, Vega-Lite's
  own title stands there. The white labels on the arcs show the values alone.
- `y_format` formats the Y axis labels with a
  [d3 format](https://d3js.org/d3-format), such as `.0%` for percents or `,.1f`
  for one decimal; empty, Vega-Lite writes them. Stacked bars with totals writes
  its totals with it too, and with `,.0f` when it is empty.

A column name with a `'` in it cannot be read: rename the column first.

A column whose name holds a `.` or a `[`, such as `rain.mm`, is set in its
widget as it is. Where Vega-Lite reads a field, the chip writes the name escaped,
`"field": "rain\\.mm"`, since Vega-Lite reads a `.` or a `[` in a field as a
path into the row; in a title, a sort or an expression it writes `rain.mm`. A
widget that holds the escaped name, `rain\.mm`, is written as it is. Bars with
error bars draws no error bars for such a Y column: rename it upstream.

### Colors and order

Each chart writes its scenarios through scenario chips: a color, fill or stroke
by `scenario_name` takes `"scale": [!! scenario colors !!]`, the colors of the
scenarios' boxes, and an axis, an offset or a facet by it
`"sort": [!! scenario order !!]`, the order the dataflow lists the boxes. Each
input from no box comes after them in the order of the circles, in a grey of its
own; with no input from a box, the chart's own palette colors the scenarios
([Scenario colors and order](../../docs/USAGE.md#scenario-colors-and-order)).
A chart is drawn again when a scenario is renamed or recolored. An edit that
writes its own scale in the chip's place draws its own colors. Stacked bars with
totals and Weighted matrix write each scenario's name in its color under its
bar or beside its row; their bars and rings keep colors of their own. The Table,
and the totals of Stacked bars with totals, write in `[!! scenario text_colors !!]`:
each scenario's color, in a darker shade of it where the color is too light to
read on white.

## Dataflows

```
[ Scenario A's rows ] ──┐
                        ├──► [ Lines with a band ]
[ Scenario B's rows ] ──┘
```

The test dataflow
[Nine ways to chart scenario comparisons](../../docs/examples/dataflows/scenario-comparison-charts.json)
draws nine example tables with nine of the charts, each taking its scenarios'
nodes on its circles.

## Skills

The package ships one skill for Curio's agents,
[`skills/vega-lite-charts/SKILL.md`](skills/vega-lite-charts/SKILL.md): which
chart draws what, and how a chart reads its stacked inputs, sets its column
widgets, and colors and orders its scenarios. Every agent on a dataflow that
uses the package lists it, and a run that writes one of its fifteen nodes is
handed it ([a package's skills](../../docs/NODE-CATALOG.md#6-the-manifest)).

## Setup

The charts need no Python library. The package is installed for you when Curio
starts with `--with-examples`; otherwise add it from the Node Catalog.
