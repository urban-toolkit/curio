# Example: Spec forms and data sources

Anything you write in the spec yourself is kept, and it does not matter which
catalog format the data came from.

One of four examples on drawing a `GeoDataFrame`:
[12](12-vega-lite-geodataframe-maps.md) the basics,
[13](13-vega-lite-geometry-columns.md) geometry columns,
[14](14-vega-lite-crs-and-geometry-types.md) coordinate systems and geometry types,
[15](15-vega-lite-spec-forms-and-catalogs.md) spec forms and data sources.

## Pipeline

```mermaid
flowchart LR
  L1[Data Loading<br/>ZIP polygons] --> V16[Vega-Lite<br/>explicit shape]
  L1 --> V17[Vega-Lite<br/>own projection]
  L1 --> V18[Vega-Lite<br/>layer inheritance]
  L1 --> V19[Vega-Lite<br/>hconcat]
  L2[Data Loading<br/>green roofs] --> V20[Vega-Lite<br/>lon/lat channels]
  L2 --> SJ[Spatial Join<br/>tag by zip]
  L1 --> SJ
  SJ --> V23[Vega-Lite<br/>joined points]
  L3[Data Loading<br/>GeoParquet] --> V24[Vega-Lite<br/>GeoParquet]
```

## Data

Loaded from the [Data Catalog](../DATA-CATALOG.md) by id, so the dataflow runs
anywhere without editing paths.

| Dataset | Id | Format |
|---|---|---|
| Chicago Boundary (ZIP polygons) | `data.urbanlab.chicago-boundary` | geojson |
| Chicago Green Roofs | `data.cityofchicago.green-roofs` | csv |
| Project Sidewalk labels | `data.projectsidewalk.chicago-labels` | parquet |

## Your spec wins

Curio fills in a `shape` encoding and a `projection` only when you have not
written them. Two views here write their own, one naming the geometry column
explicitly and one asking for `albersUsa`, and both come back untouched.

This holds inside `layer` and `hconcat` too, so a multi-view map composes the way
you would expect.

## Maps without geoshape

A `circle` mark with `longitude` and `latitude` channels is a map too, and gets
the same projection treatment as a `geoshape`. One view here plots the rooftop
points that way, sized by roof area, with no geometry column involved at all.

## Any catalog format

```python
import geopandas as gpd

dataset_path = curio_dataset_path("data.projectsidewalk.chicago-labels")
gdf = gpd.read_parquet(dataset_path)

return gdf[["label_type", "severity", "geometry"]].head(400)
```

GeoParquet, read with `gpd.read_parquet`. The spec is no different from the
geojson one.

The join is a node, not code. `Spatial Join` takes the green-roof points on
its top handle and the ZIP polygons on its bottom handle, and tags every point
with the polygon it falls in. The polygon property used as the tag is a
setting on the node (`name` by default); here it is `zip`, so the tag column
the node adds, `neighborhood_name`, holds the ZIP code. What comes out is the
points again, as plain GeoJSON, which the map draws without declaring
anything about geometry:

```json
{
  "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
  "description": "Rooftop points tagged with their ZIP by the Spatial Join node.",
  "mark": {
    "type": "geoshape",
    "opacity": 0.6
  },
  "encoding": {
    "color": {
      "field": "neighborhood_name",
      "type": "nominal",
      "legend": null
    },
    "tooltip": [
      {
        "field": "neighborhood_name",
        "title": "ZIP"
      },
      {
        "field": "TOTAL_ROOF_SQFT",
        "title": "roof sqft"
      }
    ]
  }
}
```

Every point keeps its own columns, so `TOTAL_ROOF_SQFT` is still there for the
tooltip, and `neighborhood_name` colours the dots by ZIP.
