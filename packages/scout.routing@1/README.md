# `scout.routing@1`: SCOUT Routing

SCOUT's weather-aware routing, ported from
[SCOUT](https://github.com/urban-toolkit/scout) (`backend/models/routing`).
It finds routes between two points over a roads layer, weighing each road by
the weather a graph network predicts on it from a WRF forecast, and gives each
route's duration, distance and rain and wind exposure.

## Nodes

| Canonical id | Label | Input | Output |
|---|---|---|---|
| `scout.routing/weather-routing` | Weather Routing | A roads GeoDataFrame: OpenStreetMap road lines, such as the roads an Autark node loads | `(routes, metrics)`: one GeoDataFrame and one table |

## Settings

The node's **Widgets** tab holds its settings:

| Widget | Default | What it sets |
|---|---|---|
| Origin (`origin`) | 41.868, -87.636 | Where the routes start, snapped to the nearest road node |
| Destination (`destination`) | 41.889, -87.624 | Where they end |
| Mode (`mode`) | Default weights | Which routes to find (below) |
| Routes per factor (`K`) | `1` | How many routes per factor in Custom weights, 1 to 3 |
| Start time (`time`) | 2025-07-06 12:00 | The trip's start, in Chicago time |
| Rain weight (`rain`) | `0.85834` | How much rain counts against a road |
| Wind weight (`wind`) | `0.01657` | How much wind counts against a road |

The modes:

- **Default weights**: the fastest route, and the route that weighs rain, heat,
  humidity and wind with SCOUT's own weights (0.85834, 0.0285, 0.09648 and
  0.01657).
- **Custom weights**: the K routes that weigh rain most, the K that weigh wind
  most, and the fastest. The rain and wind weights add up to at most 1.
- **Single-factor weights**: one route per factor, each weighed by its weight
  alone, and the fastest.

## Outputs

- **routes**: one row per route, a line through its road nodes in EPSG:4326, with
  `weight_type` (which route it is), `route_index`, `distance_m` in metres,
  `duration_minutes` and its `rain_exposure`, `heat_exposure`, `wind_exposure`
  and `humidity_exposure`. An Autark map draws it.
- **metrics**: the same routes as a table: `route`, `route_index`, `distance` in
  kilometres, `duration` in minutes and the four exposures. Compare Scenarios
  charts it.

A route's exposure to a factor is the sum, over its roads, of the factor's
predicted value weighted by the factor's weight plus the road's travel time
weighted by the rest.

## Weather

The node reads the Data Catalog's SCOUT WRF group, one NetCDF dataset per
variable (`data.scout.wrf-rain`, `-t2`, `-rh2`, `-wspd10` and `-wdir10`): SCOUT's
WRF-Chem forecast over Chicago, an hour a step from 2025-07-06 00:00 UTC to
2025-07-08 00:00 UTC. A start time is read in the time zone the files declare,
Chicago's, so the forecast runs from 2025-07-05 19:00 to 2025-07-07 19:00 there;
the trip reads the hour it starts in, and each 15 minutes of it the hour it is
in by then. The weather at each road node comes from SCOUT's graph network,
`data.scout.weather-gnn`, run with onnxruntime.

## A dataflow

```
[ Autark: Loop roads ] ──► [ Roads ] ──► [ Weather Routing ] ──► [ Routes ] ──► [ Autark: map of the routes ]
                                                            └─► [ Route metrics ] ──► [ Compare Scenarios ]
```

An Autark node that only loads data hands on its layers as an array of
`{name, type, geojson}`, in EPSG:3395; the Roads node, a Python node, takes the
roads layer as a GeoDataFrame:

```python
import geopandas as gpd

(layer,) = [layer for layer in arg if layer["name"] == "table_osm_roads"]
return gpd.GeoDataFrame.from_features(layer["geojson"]["features"], crs="EPSG:3395")
```

The test dataflow [WeatherRouting](../../docs/examples/dataflows/WeatherRouting.json)
is this dataflow in two scenarios, "Avoid rain" and "Avoid wind", over the
Chicago Loop's roads and a start time they share.

## Setup

Curio installs the package's Python libraries with it: `osmnx`, `networkx`,
`netCDF4`, `scipy`, `scikit-learn` and `onnxruntime`. It is installed for you
when Curio starts with `--with-examples`.
