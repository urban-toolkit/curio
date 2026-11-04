# Vega-Lite charts that compare scenarios

Fifteen Vega-Lite specs for a **Vega-Lite** node (`curio.builtin/vis-vega`) that
compares scenarios, one input per scenario. Each draws every scenario in its
box's color and in the order the dataflow lists the boxes, through scenario
chips.

## Using one

1. Drop a **Vega-Lite** node from the Built-in palette and connect a node of
   each scenario's box to an input circle of its own.
2. Paste the chart's spec into its grammar editor.
3. In its **Widgets** tab, add the widgets the table lists ([`charts.json`](charts.json) holds each one's name, kind, default and choices), each a text widget
   named as listed (`combine` a choice of `mean`, `sum`, `median`, `min`, `max`
   and `count`; `x_type` a choice of `quantitative`, `temporal`, `ordinal` and
   `nominal`; `columns` a list of texts), and set them to your columns.

The test dataflow
[Nine ways to chart scenario comparisons](../dataflows/scenario-comparison-charts.json)
draws nine example tables with nine of them, each taking its scenarios' nodes on
its circles.

## The charts

| Spec | Chart | What it draws | Widgets |
|---|---|---|---|
| [`lines-with-band.vl.json`](lines-with-band.vl.json) | Lines with a band | One line per scenario over `x`, a band from `low` to `high` around it, and a panel per value of the `facet` column | `x`, `y`, `low`, `high`, `facet`, `x_title`, `y_title`, `y_format` |
| [`curves-by-group.vl.json`](curves-by-group.vl.json) | Curves by group | One curve per scenario and group over `x`, each group in a dash of its own | `x`, `y`, `group`, `x_title`, `y_title`, `y_format`, `group_title` |
| [`bars-with-error-bars.vl.json`](bars-with-error-bars.vl.json) | Bars with error bars | Bars per category of `x`, the scenarios side by side, each `y` plus or minus its `error` | `x`, `y`, `error`, `x_title`, `y_title`, `y_format` |
| [`ensemble-strips.vl.json`](ensemble-strips.vl.json) | Ensemble strips | A tick per row for each scenario, such as the runs of an ensemble, and a black tick at its median | `y`, `y_title`, `y_format` |
| [`stacked-bars-with-totals.vl.json`](stacked-bars-with-totals.vl.json) | Stacked bars with totals | One bar per scenario, stacked by `part` in the table's row order, its total on top | `y`, `part`, `y_title`, `y_format`, `part_title` |
| [`donuts.vl.json`](donuts.vl.json) | Donuts | One donut per scenario: the `highlight` part in the scenario's color, the rest grey, each slice's share of the `value` total in percent | `part`, `value`, `highlight` |
| [`weighted-matrix.vl.json`](weighted-matrix.vl.json) | Weighted matrix | One ring per `factor` and scenario, sized by its `weight` from -1 to 1, green for and red against; a weight of 0 draws no ring | `factor`, `weight` |
| [`dots-with-a-range.vl.json`](dots-with-a-range.vl.json) | Dots with a range | For each `category`, a grey rule from its lowest `value` to its highest and a dot per scenario, the categories the scenarios differ most on first | `category`, `value`, `x_title`, `y_title` |
| [`bars.vl.json`](bars.vl.json) | Bars | One bar per scenario, its `y` values combined | `y`, `combine`, `y_title` |
| [`grouped-bars.vl.json`](grouped-bars.vl.json) | Grouped bars | Bars per category of `x`, the scenarios side by side, `y` combined per category | `x`, `y`, `combine`, `x_title`, `y_title` |
| [`lines.vl.json`](lines.vl.json) | Lines | One line per scenario over `x`, a point at each value, `y` combined per value of `x` | `x`, `x_type`, `y`, `combine`, `x_title`, `y_title` |
| [`points.vl.json`](points.vl.json) | Points | One point per row, `x` against `y` | `x`, `y`, `x_title`, `y_title` |
| [`pie.vl.json`](pie.vl.json) | Pie | One slice per scenario, its `value` combined and written on it | `value`, `combine`, `value_title` |
| [`lollipops.vl.json`](lollipops.vl.json) | Lollipops | One stem from 0 and one dot per scenario, at its `value` combined | `value`, `combine`, `x_title` |
| [`table.vl.json`](table.vl.json) | Table | The inputs' rows, up to 40, in the `columns` it lists | `columns` |

## How a chart reads its inputs

Each chart is a Vega-Lite node with one of these specs in its grammar editor, a shared outcome
of the scenarios it compares. Connect a node of each scenario's box to one of its input circles:
each edge takes the next circle. Its spec
reads all its inputs as the dataset its chip names (`"data": {"name": "[!! inputs !!]"}`):
every input's rows, stacked in the order of its circles, each with `__input__`
(its circle), `scenario` (the id of the scenario box its input comes from) and
`scenario_name` (that box's name) beside its own columns. A column one input
lacks is empty in its rows, and an input that is a single value is one row with
a `value` column. An input from a node in no box has an empty `scenario` and
its node's name. The columns a chart plots are widgets in its **Widgets** tab.

The spec is yours to edit: its chips, its widgets' and its scenarios', are
written each time it draws, and the dataflow keeps the spec as you leave it.

### Widgets

- A column widget (`x`, `y`, `low`, `high`, `facet`, `group`, `error`, `part`,
  `value`, `factor`, `weight`, `category`) is a text widget that names a column
  of the inputs. Set each to a column the inputs have; until then the chart says
  which column the inputs lack. With `facet` empty, Lines
  with a band draws one panel.
- `columns`, the Table's, is a list of texts that names the columns it shows,
  in order, such as `["scenario_name", "cost_per_m2"]`.
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
`"field": "rain\\.mm"`; in a title, a sort or an expression it writes `rain.mm`. A
widget that holds the escaped name, `rain\.mm`, is written as it is. Bars with
error bars draws no error bars for such a Y column: rename it upstream.

### Colors and order

Each chart writes its scenarios through scenario chips: a color, fill or stroke
by `scenario_name` takes `"scale": [!! scenario colors !!]`, the colors of the
scenarios' boxes, and an axis, an offset or a facet by it
`"sort": [!! scenario order !!]`, the order the dataflow lists the boxes. Each
input from no box comes after them in the order of the circles, in a grey of its
own; with no input from a box, the chart's own palette colors the scenarios
([Scenario colors and order](../../USAGE.md#scenario-colors-and-order)).
A chart is drawn again when a scenario is renamed or recolored. An edit that
writes its own scale in the chip's place draws its own colors. Stacked bars with
totals and Weighted matrix write each scenario's name in its color under its
bar or beside its row; their bars and rings keep colors of their own. The Table,
and the totals of Stacked bars with totals, write in `[!! scenario text_colors !!]`:
each scenario's color, in a darker shade of it where the color is too light to
read on white.
