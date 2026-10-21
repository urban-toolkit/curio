# `curio.scout@1`: Scout

SCOUT's nodes in Curio: two raster nodes and fifteen charts that compare
scenarios. The **Raster Calculator** runs one operation over rasters on one
grid, cell by cell or a raster's statistics. **Rasterize Buildings** is SCOUT's
building rasterizer ("OSM vector to raster"), ported from
[SCOUT](https://github.com/urban-toolkit/scout) (`backend/compute/raster_conversion`):
it draws each building's height into map tiles and joins the tiles into one
raster, which an Autark map draws and SCOUT's Deep Umbra shadow model reads.
The fifteen Vega-Lite charts take one input per scenario and draw each scenario
in its box's color, through their scenario chips. Seven are re-made from komar41's ScenarioCharts, and Dots
with a range is the first view of his "Minutes of shadow per park" chart.

Once the package is in a dataflow (**Add to project** in the Node Catalog
drawer), its seventeen nodes are under **Scout** in the Tools panel's **Node
Catalog** dropdown.

## Nodes

### Raster nodes

| Canonical id | Label | Input | Output |
|---|---|---|---|
| `curio.scout/raster-calculator` | Raster Calculator | One to three RASTERs on one grid, one per input circle; a GeoDataFrame on a circle is a layer its code reads as zones or a mask | One RASTER, or a DATAFRAME of one row of statistics |
| `curio.scout/rasterize-buildings` | Rasterize Buildings | A buildings GeoDataFrame: polygons, a CRS and a column of heights in metres | One RASTER of heights in metres |

### Charts

| Canonical id | Label | What it draws | Widgets |
|---|---|---|---|
| `curio.scout/lines-with-band` | Lines with a band | One line per scenario over `x`, a band from `low` to `high` around it, and a panel per value of the `facet` column | `x`, `y`, `low`, `high`, `facet`, `x_title`, `y_title`, `y_format` |
| `curio.scout/curves-by-group` | Curves by group | One curve per scenario and group over `x`, each group in a dash of its own | `x`, `y`, `group`, `x_title`, `y_title`, `y_format`, `group_title` |
| `curio.scout/bars-with-error-bars` | Bars with error bars | Bars per category of `x`, the scenarios side by side, each `y` plus or minus its `error` | `x`, `y`, `error`, `x_title`, `y_title`, `y_format` |
| `curio.scout/ensemble-strips` | Ensemble strips | A tick per row for each scenario, such as the runs of an ensemble, and a black tick at its median | `y`, `y_title`, `y_format` |
| `curio.scout/stacked-bars-with-totals` | Stacked bars with totals | One bar per scenario, stacked by `part` in the table's row order, its total on top | `y`, `part`, `y_title`, `y_format`, `part_title` |
| `curio.scout/donuts` | Donuts | One donut per scenario: the `highlight` part in the scenario's color, the rest grey, each slice's share of the `value` total in percent | `part`, `value`, `highlight` |
| `curio.scout/weighted-matrix` | Weighted matrix | One ring per `factor` and scenario, sized by its `weight` from -1 to 1, green for and red against; a weight of 0 draws no ring | `factor`, `weight` |
| `curio.scout/dots-with-a-range` | Dots with a range | For each `category`, a grey rule from its lowest `value` to its highest and a dot per scenario, the categories the scenarios differ most on first | `category`, `value`, `x_title`, `y_title` |
| `curio.scout/bars` | Bars | One bar per scenario, its `y` values combined | `y`, `combine`, `y_title` |
| `curio.scout/grouped-bars` | Grouped bars | Bars per category of `x`, the scenarios side by side, `y` combined per category | `x`, `y`, `combine`, `x_title`, `y_title` |
| `curio.scout/lines` | Lines | One line per scenario over `x`, a point at each value, `y` combined per value of `x` | `x`, `x_type`, `y`, `combine`, `x_title`, `y_title` |
| `curio.scout/points` | Points | One point per row, `x` against `y` | `x`, `y`, `x_title`, `y_title` |
| `curio.scout/pie` | Pie | One slice per scenario, its `value` combined and written on it | `value`, `combine`, `value_title` |
| `curio.scout/lollipops` | Lollipops | One stem from 0 and one dot per scenario, at its `value` combined | `value`, `combine`, `x_title` |
| `curio.scout/table` | Table | The inputs' rows, up to 40, in the `columns` it lists | `columns` |

## Raster Calculator

A Python node that opens with the package's starter,
[`sources/raster-calculator.py`](sources/raster-calculator.py), when it is
dropped: input_0 minus input_1, with its other operations listed above it,
statistics among them. Its code imports them from the package's module:

```python
from scout_rasters.raster_algebra import raster_calculate, raster_statistics

return raster_calculate("subtract", [input_0, input_1], output_file=curio_output_file)
```

Return another call to change what it does:

| Call | Result |
|---|---|
| `raster_calculate("add", [input_0, input_1], output_file=curio_output_file)` | input_0 plus input_1, cell by cell; also `"subtract"`, `"multiply"` and `"divide"` |
| `raster_calculate("choose", [input_0, input_1, input_2], codes=[21, 31], output_file=curio_output_file)` | input_1 where input_0's class is one of the codes, input_2 elsewhere |
| `raster_calculate("subtract", [input_1, input_0], absolute=True, output_file=curio_output_file)` | the size of input_1 minus input_0: how much each cell changed, 0 where it did not; `absolute=True` takes the size of any operation's result |
| `raster_statistics(input_0)` | the `mean`, `median`, `min`, `max` and `count` of the raster's cells with a value, as a table of one row |
| `raster_statistics(input_0, mask=input_1, mask_values=[0])` | the same over the cells where a second raster on input_1, on the same grid, is 0 |

`raster_calculate` writes the raster it returns with `curio_output_file`, as
Rasterize Buildings writes its own. A cell with no value in an input an
operation reads has no value in the result, and rasters on different grids
are refused. An input circle also takes a layer, which the node's code reads
as zones or a mask, for example rasterized on a raster's grid with
`rasterio.features.rasterize`. The
[Rasters section of the usage guide](../../docs/USAGE.md#rasters) lists every
option.

### Raster math in another package

The functions are the package's module, `scout_rasters`: `raster_algebra`
holds the operations and the statistics, and `web_tiles` the web map tile
helpers `tile_bounds` and `mosaic_web_tiles`. A node of another package
imports them when its package names Scout in its manifest's
`dependencies.packages`, as Deep Umbra
([`model.scout.deep-umbra@1`](../model.scout.deep-umbra@1/README.md)) does for
`tile_bounds`:

```json
"dependencies": {"packages": {"curio.scout@1": "*"}}
```

A Python node of no package has none of them, so a raster step is a Raster
Calculator node.

## Rasterize Buildings

### Settings

The node's **Widgets** tab holds its settings:

| Widget | Default | What it sets |
|---|---|---|
| Height column (`attribute`) | `height` | The column the heights are read from |
| Zoom level (`zoom`) | `16` | The zoom level of the map tiles |
| Maximum height (`max_height`) | `550` m | The height drawn as gray level 255 |

Deep Umbra reads zoom-16 tiles where 255 is 550 m.

### Output

The tiles side by side in one GeoTIFF in EPSG:3395 (World Mercator), one band of
heights in metres. Each tile is 256 by 256 cells of 8-bit gray, drawn between
the tile's corners, as SCOUT writes `<zoom>_<x>_<y>.png`, and each gray level is
the maximum height over 255 (2.16 m at 550 m). An Autark map draws it as
`input_0`:

```json
{"map": {"layerRefs": [{"dataRef": "input_0", "getFnv": "band_1"}]}}
```

A tile is written when a building is near it. A tile that is not written is no
data (NaN, the file's no-data value): a map leaves it out, and so do a Raster
Calculator's statistics and Accumulated Shadow. Inside a written tile, every pixel with no
building is 0, the ground. A building with no value in the height column adds
nothing, and a building taller than the maximum height is drawn at the maximum.

## Charts

Each chart is a Vega-Lite node with a spec of its own. Connect each scenario's
outcome to one of its input circles: each edge takes the next circle. Its spec
reads all its inputs as the dataset `inputs` (`"data": {"name": "inputs"}`):
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
[ Buildings ] ──► [ Rasterize Buildings ] ──► [ Accumulated Shadow ] ──► [ Autark: map of the shadow ]
                            │                          │
                            └──── mask ──► [ Raster Calculator ] ◄──┘
```

[Example 24](../../docs/examples/24-scout-shadow-model-chicago-loop.md) holds this
dataflow, on SCOUT's Chicago Loop buildings from the Data Catalog, with a map of
the heights too: Accumulated Shadow runs Deep Umbra on the heights, and the
Raster Calculator takes the shadow's statistics over the ground, the heights as
its mask. The test dataflow
[Quad Cities flood depth, nature-based solutions and vulnerability](../../docs/examples/dataflows/quad-cities-flood-vulnerability.json)
chooses SCOUT's flood depth by nature-based solution class with a Raster
Calculator and takes its statistics with another. A third averages the depth
over the riverside tracts' land in each period: it reads the tracts and the
waterways, two layers, as zones and a mask.

```
[ Scenario A's rows ] ──┐
                        ├──► [ Lines with a band ]
[ Scenario B's rows ] ──┘
```

The test dataflow
[Nine ways to chart scenario comparisons](../../docs/examples/dataflows/scenario-comparison-charts.json)
draws nine example tables with nine of the charts, each taking its scenarios'
nodes on its circles.

## Setup

Curio installs the package's Python libraries with it: `datashader`,
`spatialpandas`, `dask`, `rasterio`, `geopandas`, `numpy`, `pandas`, `pillow`,
`pyarrow`, `pyproj` and `shapely`. The raster nodes use them; the charts need
none. The package is installed for you when Curio starts with
`--with-examples`; otherwise add it from the Node Catalog.
