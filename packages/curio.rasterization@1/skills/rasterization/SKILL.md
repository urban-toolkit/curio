---
name: rasterization
description: >-
  Use this skill when a dataflow uses Rasterization (curio.rasterization@1) and a task writes,
  wires or fixes one of its nodes: a Raster Calculator, for math or statistics over rasters on one grid, such as the
  difference of two scenarios' flood depths; Rasterize Buildings, for a buildings layer as the
  height raster an Autark map draws and Deep Umbra reads. It gives the Raster Calculator's calls
  and its rules on grids, masks and zones, and what Rasterize Buildings writes.
license: MIT
compatibility: Written for Curio's agents, on a dataflow that uses Curio's Rasterization package, curio.rasterization@1.
metadata:
  author: curio
  version: "1.0.0"
  curio-templates: raster-calculator rasterize-buildings
---
## Rasterization

Rasterization is SCOUT's two raster nodes in Curio, ported from SCOUT (urban-toolkit/scout). A plan names each by its node type, `curio.rasterization/<id>`, and a dataflow that holds the package lists them under **Rasterization** in the Tools panel's **Node Catalog** dropdown. A chart that compares scenarios is a Vega-Lite node, never a node of this package.

### Which node

- A raster computed from rasters, such as the difference of two scenarios' rasters or a class chosen per cell, and a raster's mean, median, minimum, maximum and count, is a Raster Calculator node, `curio.rasterization/raster-calculator`. A Python node of no package cannot import the package's functions, so a raster step is never one.
- Heights drawn from a buildings layer, for an Autark map or for Deep Umbra's Accumulated Shadow, are a Rasterize Buildings node, `curio.rasterization/rasterize-buildings`.

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
- A node of another package imports these functions when that package names Rasterization in its manifest's `dependencies.packages`, `{"curio.rasterization@1": "*"}`, as Deep Umbra's does.

### Rasterize Buildings

- Its input is a buildings GeoDataFrame: polygons, a CRS, and a column of heights in metres.
- Its widgets are `attribute`, the height column (`height`); `zoom`, the zoom level of the map tiles (16); and `max_height`, the height drawn as gray level 255 (550 m). Deep Umbra reads zoom-16 tiles where 255 is 550 m, so keep both for Accumulated Shadow.
- Its output is one RASTER: the tiles side by side in one GeoTIFF in EPSG:3395, one band of heights in metres, each gray level 2.16 m at 550 m. An Autark map draws it as `{"dataRef": "input_0", "getFnv": "band_1"}`.
- A tile with no building near it has no value, which a map, a Raster Calculator's statistics and Accumulated Shadow leave out. In a tile it writes, a cell with no building is 0, the ground. A building with no height adds nothing, and one taller than `max_height` is drawn at `max_height`.
