"""Weather Routing: SCOUT's weather-aware routes over a roads layer.

Input: the layers an Autark node loads from OpenStreetMap, whose roads layer,
table_osm_roads, the node reads as a GeoDataFrame of road lines (with highway,
and oneway and maxspeed where known), or such a GeoDataFrame on its own. The
routes run inside its bounds.
Output: (routes, metrics).
- routes: one row per route, a line through its nodes, with the route
  (weight_type), route_index, distance_m in metres, duration_minutes and the
  route's rain, heat, wind and humidity exposure. An Autark map draws it.
- metrics: the same routes as a table: route, route_index, distance in km,
  duration in minutes and the four exposures, for Compare Scenarios.
The Widgets tab sets the origin and destination, the mode, K, the start time
(local time where the weather is, Chicago) and the rain and wind weights.
Ported from SCOUT, https://github.com/urban-toolkit/scout.
"""
from scout_routing.weather_routing import calculate_weather_route

# The Data Catalog's SCOUT WRF group, a NetCDF file per variable.
weather = {
    "RAIN": curio_data_path("data.scout.wrf-rain"),
    "T2": curio_data_path("data.scout.wrf-t2"),
    "WSPD10": curio_data_path("data.scout.wrf-wspd10"),
    "WDIR10": curio_data_path("data.scout.wrf-wdir10"),
    "RH2": curio_data_path("data.scout.wrf-rh2"),
}

return calculate_weather_route(
    [!! input 0:table_osm_roads !!],
    weather,
    # SCOUT's weather graph network, the Model Catalog's weather GNN.
    curio_load_model("model.scout.weather-gnn"),
    [!! origin !!],
    [!! destination !!],
    mode=[!! mode !!],
    K=int([!! K !!]),
    time_=[!! time !!],
    rain=[!! rain !!],
    wind=[!! wind !!],
)
