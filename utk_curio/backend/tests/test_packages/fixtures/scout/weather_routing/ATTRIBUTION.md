# SCOUT's weather-aware routes

These files are what SCOUT, https://github.com/urban-toolkit/scout, wrote when
its own `calculate_weather_route` (`backend/models/routing/scripts/weather_routing.py`)
ran on its Chicago road graph and WRF-Chem weather run, with its trained GNN
(`backend/models/routing/gnn/rain_model.pth`), for two scenarios of its routing
use case, from 1256 West Chicago Avenue (41.896438, -87.659758) to 1410 South
Special Olympics Drive (41.861649, -87.614034), inside its data layer's roi
`-87.662, 41.859, -87.613, 41.898`:

- `default/`: its defaults: mode "Default weights", K 1, start
  2025-07-06T00:00:00, rain 0.85834 and wind 0.01657.
- `single/`: mode "Single-factor weights", K 1, start 2025-07-06T06:00:00,
  rain 0.6 and wind 0.3.

Each folder holds `route_<C, D, E>.geojson`, the routes in SCOUT's order, `<C,
D, E>.csv`, SCOUT's metrics of each, and `route_origin.geojson` and
`route_destination.geojson`. They were made in SCOUT's own environment
(Python 3.9, torch 2.2.2, torch_geometric 2.6.1, osmnx 1.9.4) with one change
that leaves every result as it is: the cropped graph was copied
(`G.subgraph(...).copy()`, which keeps its order) so a run takes seconds, not
an hour.

The `scout.weather-routing@1` tests run its Weather-Aware Routes node, with
the Model Catalog's `model.scout.weather-gnn` and the Data Catalog's
`data.scout.chicago-weather-2025-07-06`, and compare the result with these files.
