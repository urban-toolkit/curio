"""Weather-Aware Routes: SCOUT's weather-aware route planning.

Input: the roads of the area to route in, SCOUT's data layer, cut from the
Data Catalog's data.osm.chicago-roads. The code reads the road network from
it, and SCOUT's WRF weather run of 6 July 2025 from
data.scout.chicago-weather-2025-07-06, a file each.
Output: (routes, endpoints, ribbons, metrics).
- routes: one LineString per route, with its route label, distance_km,
  duration_min and the exposure to each weather condition chosen. An Autark
  map draws it as input_0.
- endpoints: the origin and destination, at the road nodes they snap to
  (input_1), drawn as circles; ribbons: each route as a band as wide as the
  Route width widget sets, for a map (input_2).
- metrics: one row per route and measure (route, metric, value), for a
  Vega-Lite chart that compares the routes (input_3).
The GNN, from the Model Catalog, estimates the weather at every road node;
each street is weighed by it, and the routes are the lightest. The Widgets tab
sets the origin, destination, start time, mode, K, the conditions and their
weights. To use another model, drag it from the Model Catalog onto this node.
Ported from SCOUT, https://github.com/urban-toolkit/scout.
"""
from scout_weather_routing.node_outputs import weather_routes

model = curio_load_model("model.scout.weather-gnn")

# SCOUT's road network, and its WRF weather run of 6 July 2025, a file each.
roads = curio_load_data("data.osm.chicago-roads")
weather = {
    "RAIN": curio_load_data("data.scout.chicago-weather-2025-07-06", part="RAIN.nc"),
    "T2": curio_load_data("data.scout.chicago-weather-2025-07-06", part="T2.nc"),
    "WSPD10": curio_load_data("data.scout.chicago-weather-2025-07-06", part="WSPD10.nc"),
    "WDIR10": curio_load_data("data.scout.chicago-weather-2025-07-06", part="WDIR10.nc"),
    "RH2": curio_load_data("data.scout.chicago-weather-2025-07-06", part="RH2.nc"),
}

# The conditions the routes weigh, each with its weight.
weights = {"rain": [!! rain !!], "heat": [!! heat !!], "wind": [!! wind !!], "humidity": [!! humidity !!]}
conditions = {name: weights[name] for name in [!! conditions !!]}

return weather_routes(
    arg,
    roads,
    weather,
    model,
    origin=[!! origin !!],
    destination=[!! destination !!],
    mode=[!! mode !!],
    k=[!! k !!],
    time=[!! time !!],
    conditions=conditions,
    width=[!! width !!],
)
