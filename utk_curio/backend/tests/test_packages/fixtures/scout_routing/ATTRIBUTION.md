# SCOUT's weather routing, run on Curio's cuts of its data

From SCOUT, https://github.com/urban-toolkit/scout, commit b98369e5, used with the
permission of SCOUT's authors.

- `roads_nodes.parquet` and `roads_edges.parquet`: SCOUT's Chicago road graph
  (`backend/data/osm/processed/chicago/roads.pkl.gz`), cut to longitude -87.69 to
  -87.585 and latitude 41.835 to 41.92 by `scripts/scout/crop_routing_data.py`:
  60,000 nodes (`osmid`, `x`, `y`) and 67,733 edges (`u`, `v`, `key`, `length`,
  `speed_kph`, `travel_time`). Adding the nodes in row order, then the edges in row
  order, rebuilds SCOUT's graph with SCOUT's node, successor and predecessor order.
- `routing_reference.json`: the routes and metrics SCOUT's own
  `calculate_weather_route` (`backend/models/routing/scripts/`, unchanged) gives on
  that graph and on the Data Catalog's SCOUT WRF forecast
  (`data.scout.chicago-weather-2025-07-06`), for the origin, destination,
  start times and weights of SCOUT's weather routing example and its three modes.
  Written once by `scripts/scout/reference_routing.py` in SCOUT's own stack (Python
  3.9, torch 2.2.2, torch-geometric 2.6.1, osmnx 2.0.6, networkx 3.2.1, numpy 1.23.5;
  `made_with` in the file). It holds no data of SCOUT's beyond node ids, metrics and
  hashes.

The `scout.routing@1` tests route on the graph with the package's port and compare
with `routing_reference.json`.
