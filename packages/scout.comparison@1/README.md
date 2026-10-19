# `scout.comparison@1`: SCOUT Comparison

Seven Vega-Lite charts to connect after a **Compare Scenarios** node, for the
comparisons its **Chart** tab does not draw. Each is a Vega-Lite node with a
spec of its own: it reads the node's stacked table, with its `scenario_name`
column, and draws each scenario in the color of its box, in the order of the
Compare node's inputs. The columns it plots are text widgets in its **Widgets**
tab. The seven forms are re-made from komar41's ScenarioCharts.

Once the package is in a dataflow (**Add to project** in the Node Catalog
drawer), the charts are under **SCOUT Comparison** in the Tools panel's **Node
Catalog** dropdown.

## Nodes

| Canonical id | Label | What it draws | Widgets |
|---|---|---|---|
| `scout.comparison/lines-with-band` | Lines with a band | One line per scenario over `x`, a band from `low` to `high` around it, and a panel per value of the `facet` column | `x`, `y`, `low`, `high`, `facet`, `x_title`, `y_title`, `y_format` |
| `scout.comparison/curves-by-group` | Curves by group | One curve per scenario and group over `x`, each group in a dash of its own | `x`, `y`, `group`, `x_title`, `y_title`, `y_format`, `group_title` |
| `scout.comparison/bars-with-error-bars` | Bars with error bars | Bars per category of `x`, the scenarios side by side, each `y` plus or minus its `error` | `x`, `y`, `error`, `x_title`, `y_title`, `y_format` |
| `scout.comparison/ensemble-strips` | Ensemble strips | A tick per row for each scenario, such as the runs of an ensemble, and a black tick at its median | `y`, `y_title`, `y_format` |
| `scout.comparison/stacked-bars-with-totals` | Stacked bars with totals | One bar per scenario, stacked by `part` in the table's row order, its total on top | `y`, `part`, `y_title`, `y_format`, `part_title` |
| `scout.comparison/donuts` | Donuts | One donut per scenario: the `highlight` part in the scenario's color, the rest grey, each slice's share of the `value` total in percent | `part`, `value`, `highlight` |
| `scout.comparison/weighted-matrix` | Weighted matrix | One ring per `factor` and scenario, sized by its `weight` from -1 to 1, green for and red against; a weight of 0 draws no ring | `factor`, `weight` |

## Widgets

Each widget is a text widget:

- A column widget (`x`, `y`, `low`, `high`, `facet`, `group`, `error`, `part`,
  `value`, `factor`, `weight`) names a column of the stacked table. A new node's
  widgets hold their own names, so the chart says which column the table lacks
  until you set them. With `facet` empty, Lines with a band draws one panel.
- `highlight` is the value of the `part` column that Donuts colors.
- `x_title`, `y_title`, `group_title` and `part_title` are titles; empty, the
  axis or legend has none.
- `y_format` formats the Y axis labels with a
  [d3 format](https://d3js.org/d3-format), such as `.0%` for percents or `,.1f`
  for one decimal; empty, Vega-Lite writes them. Stacked bars with totals writes
  its totals with it too, and with `,.0f` when it is empty.

A column name with a `'` in it cannot be read: rename the column first.

## Colors and order

The charts follow the rule of every Vega-Lite node after a Compare Scenarios
node ([Comparing scenarios](../../docs/USAGE.md#comparing-scenarios)): a color,
fill or stroke by `scenario_name` takes the scenarios' colors, and an axis, an
offset or a facet by it takes the order of the Compare node's inputs. A chart is
drawn again when a scenario is renamed or recolored. Stacked bars with totals and
Weighted matrix write each scenario's name in its color under its bar or beside
its row; their bars and rings keep colors of their own.

## A dataflow

```
[ Scenario A's rows ] ──┐
                        ├──► [ Compare Scenarios ] ──► [ Lines with a band ]
[ Scenario B's rows ] ──┘
```

The test dataflow
[Nine ways to chart scenario comparisons](../../docs/examples/dataflows/scenario-comparison-charts.json)
draws seven example tables with the seven charts, each after a Compare
Scenarios node of its own.

## Setup

The package has no Python libraries. It is installed for you when Curio starts
with `--with-examples`; otherwise add it from the Node Catalog.
