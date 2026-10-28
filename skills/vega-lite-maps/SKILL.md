---
name: vega-lite-maps
description: >-
  Use this skill when a Vega-Lite chart draws a map of a GeoDataFrame. It says to return the frame
  as it is and use a geoshape mark, that Curio fills in the shape encoding and a fitted
  projection, and how a layer draws a geometry column other than the active one.
license: MIT
compatibility: Written for Curio's agents, their tools and node code.
metadata:
  author: curio
  version: "1.0.0"
---
## Maps in Vega-Lite

A node that returns a GeoDataFrame can be charted as a map directly. Do NOT
write a conversion helper: no shapely.geometry.mapping, no manual x/y centroid
columns, no flattening the GeoDataFrame into a plain DataFrame. Just
`return gdf`, and in the Vega-Lite spec use `"mark": "geoshape"`.

Attribute columns are addressed by their bare pandas names, exactly as for a
bar chart over the same frame.

```json
{
  "$schema": "{{vega.schema_url}}",
  "mark": "geoshape",
  "encoding": { "color": {"field": "pop", "type": "quantitative"} }
}
```

Curio fills in two things, and only when the spec does not already have them:
the `shape` encoding for the frame's active geometry column, and a `projection`
fitted to the data (`mercator` for lon/lat, `{"type": "identity",
"reflectY": true}` for a projected CRS). Do not write these yourself unless you
want a specific projection; if you do write one, it is respected.

A GeoDataFrame may have MORE THAN ONE geometry column, and each keeps its own
pandas name. The active column is wired automatically; any other must be named
explicitly, because with several present there is no single right answer:

```json
{
  "layer": [
    {"mark": "geoshape"},
    {"mark": "geoshape",
     "encoding": {"shape": {"field": "centroid", "type": "geojson"}}}
  ]
}
```

A `geoshape` mark draws a Point as a small circle, so a centroid layer needs no
special mark type.
