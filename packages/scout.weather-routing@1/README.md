# `scout.weather-routing@1`: SCOUT Weather Routing

SCOUT's weather-aware route planning, ported from
[SCOUT](https://github.com/urban-toolkit/scout) (`backend/models/routing`).
It weighs every street of a road network by the weather the trip will meet
there, and compares the fastest route with routes that avoid rain, heat, wind
or humidity.

The GNN is not in this package. It is `model.scout.weather-gnn` in the
[Model Catalog](../../docs/MODEL-CATALOG.md), and the node's code names it:

```python
model = curio_load_model("model.scout.weather-gnn")
```

## Nodes

| Canonical id | Label | Input | Output |
|---|---|---|---|
| `scout.weather-routing/weather-aware-routes` | Weather-Aware Routes | the roads of the area to route in | `(routes, endpoints, ribbons, metrics)` |

## Input

The roads of the area to route in, SCOUT's data layer: the network's roads
cut to a box with `.cx` (see
[example 26](../../docs/examples/26-scout-weather-routing.md)). The graph is
the network's nodes inside the area's bounds and the edges between them, as
SCOUT crops its graph.

The node's code reads the rest from the Data Catalog:

- `data.osm.chicago-roads`: the road network, one row per directed edge with
  `u`, `v`, `key`, `length` (m), `speed_kph` and `travel_time` (s).
- `data.scout.chicago-weather-2025-07-06`, a file at a time with `part=`: `RAIN.nc`, `T2.nc`, `WSPD10.nc`, `WDIR10.nc`, `RH2.nc`: SCOUT's WRF weather
  run, each an xarray Dataset with its variable, `XLAT` and `XLONG`.

## Settings

The node's **Widgets** tab holds SCOUT's settings:

| Widget | Default | What it sets |
|---|---|---|
| Origin (`origin`) | 1256 West Chicago Avenue | Where the trip starts; it snaps to the nearest road node |
| Destination (`destination`) | 1410 South Special Olympics Drive | Where it ends |
| Start time (`time`) | `2025-07-06T00:00:00` | When it leaves, within the weather run |
| Mode (`mode`) | `Default weights` | Which routes, below |
| K (`k`) | 1 | Routes per condition, in `Custom weights` |
| Weather conditions (`conditions`) | rain, wind | The conditions the routes weigh and report |
| Rain, Heat, Wind, Humidity weight | 0.85834, 0.0285, 0.01657, 0.09648 | Each condition's weight, 0 to 1 |
| Route width on the map (`width`) | 40 m | How wide the ribbons are |

The modes are SCOUT's:

- **Default weights**: the fastest route and the route lightest by the total
  weight, with SCOUT's default weights whatever the sliders say.
- **Custom weights**: for each condition chosen, the K routes lightest by
  its weight (Yen's algorithm), and the fastest. The weights add up to 1 at
  most.
- **Single-factor weights**: for each condition chosen, the route lightest
  by its weight alone, and the fastest.

## What it does

As SCOUT's `calculate_weather_route` does:

1. The fastest route gives the trip's length. The network is cut into
   quarter-hour zones: the streets reached within 15 minutes of the origin,
   within 30, and so on.
2. For each weather variable, each zone's cells take the weather at the time
   the trip reaches the zone, from the start time on.
3. The GNN reads each road node's coordinates and the weather of its nearest
   cell, and estimates the rain, temperature, humidity, wind speed and wind
   direction there.
4. Each street gets a weight for each condition, the condition's weight
   times the estimate at its end node plus the rest of the weight times its
   travel time, and a total weight that mixes them. The routes are the
   lightest by those weights.

The exposure of a route to a condition is the sum of that weight along it.
SCOUT's time index reads the quarter hour after the start time (a start at
00:00 reads 00:15), and the port keeps it.

## Outputs

- **routes**: one LineString per route through its road nodes, with `route`
  (`fastest-route`, `weighted-route`, `rain-aware-route`, ...),
  `weight_type`, `route_index`, `distance_km`, `duration_min`, the four
  `*_exposure` columns (0 for a condition not chosen) and `route_number`.
- **endpoints**: the origin and destination at the nodes they snap to, with
  `kind`.
- **ribbons**: each route as a band as wide as **Route width on the map**
  sets (40 m by default), with the routes' columns. Autark draws a line layer
  at a fixed width (about 17 m) that its document cannot change, so a map draws
  the bands instead.
- **metrics**: one row per route and measure, `route`, `metric` and `value`:
  the travel time, the distance and the exposure to each condition chosen,
  for a Vega-Lite chart that compares the routes as SCOUT's comparison nodes
  do.

An Autark map draws the ribbons, `input_2`, coloured by `route` with a
categorical scheme (`"getFnvType": "categorical"`), and the endpoints,
`input_1`, as circles. The routes themselves, `input_0`, keep the exact path
through the road nodes. A Vega-Lite chart reads the metrics as `input_3`.

## A dataflow

```
[ Data Loading: roads and weather, cut to an area ] ──► [ Weather-Aware Routes ] ──► [ Autark: the routes on a map ]
                                                                                 └──► [ Vega-Lite: the routes compared ]
```

## Setup

Curio installs the package's Python libraries with it: `networkx`, `scipy`
and `onnxruntime`. The GNN ships with Curio in the Model Catalog; PyTorch is
not needed.
