"""SCOUT's weather-aware routing.

Ported from SCOUT (https://github.com/urban-toolkit/scout),
backend/models/routing/scripts/weather_routing.py. SCOUT's
``calculate_weather_route`` is split in two: ``plan_weather_route`` holds its
steps, from the road graph's bounds to the routes, and
``calculate_weather_route`` builds the road graph from a roads layer, reads the
start time, and returns the routes as two tables instead of writing GeoJSON and
CSV files.

What Curio does instead of SCOUT:

- The roads are a Curio roads layer (road_graph.py), not SCOUT's pickled
  Chicago graph, and the weather is the Data Catalog's SCOUT WRF group, a
  NetCDF file per variable. SCOUT's ``load_static.DataLoader`` is not ported:
  ``cut_graph`` is its graph cut, and its masked weather slices fed only the
  training SCOUT runs when its model file is missing.
- The routes are a GeoDataFrame an Autark map draws, and their metrics a table
  Compare Scenarios charts.

SCOUT's bugs fixed here:

- A route's ``distance_m`` is its length in metres; SCOUT wrote kilometres there.
- Every call reads the weather at its own start time: SCOUT kept one DataLoader
  per process, with the first time it was given.
- Every route is a row of the result: SCOUT named each route's files after a
  list of output names, and a mode that makes more routes than names ran past
  the list ("Custom weights" makes 2K + 1 routes, "Single-factor weights" one
  per factor and one more).
- A start time is local time in the weather's time zone and reads the hourly
  step it falls in (``weather_time_index``): SCOUT counted 15-minute steps from
  2025-07-06T00:00 plus 1, so its 00:00 read the 01:00 UTC step.
- The origin's latitude is checked against the graph's northern edge: SCOUT
  compared its longitude there, which never failed.
"""

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone as _utc_zone
from zoneinfo import ZoneInfo

import geopandas as gpd
import netCDF4 as nc
import networkx as nx
import osmnx as ox
import pandas as pd
from shapely.geometry import LineString

from .calculate_isochrones import calculate_isochrones
from .road_graph import road_graph
from .weight_calculation import GNN_weight_calculations

#: SCOUT's route modes.
MODES = ("Default weights", "Custom weights", "Single-factor weights")
#: The weather variables: SCOUT's file names, which are the variables' own.
WEATHER_VARIABLES = ("RAIN", "T2", "WSPD10", "WDIR10", "RH2")
#: The minutes between two steps of the weather (SCOUT's WRF files are hourly).
STEP_MINUTES = 60
#: The metrics SCOUT gives each route, in its order.
METRICS = ("distance", "duration", "rain_exposure", "heat_exposure", "wind_exposure", "humidity_exposure")


def weather_time_index(time_string, start_date, time_zone, steps):
    """``(step, minutes into it)`` of a start time.

    *time_string* is local time, ``YYYY-MM-DDTHH:mm:ss``, in *time_zone*; the
    weather's first step is *start_date* (its ``START_DATE``, UTC) and it has
    *steps* steps of STEP_MINUTES.
    """
    local = datetime.strptime(time_string, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=ZoneInfo(time_zone))
    start = datetime.strptime(start_date, "%Y-%m-%d_%H:%M:%S").replace(tzinfo=_utc_zone.utc)
    minutes = int((local - start).total_seconds() // 60)
    step, into = divmod(minutes, STEP_MINUTES)
    if not 0 <= step < steps:
        first = start.astimezone(ZoneInfo(time_zone))
        last = (start + timedelta(minutes=STEP_MINUTES * (steps - 1))).astimezone(ZoneInfo(time_zone))
        raise ValueError(
            f"The start time {time_string} ({time_zone}) is outside the weather data, which runs from "
            f"{first:%Y-%m-%dT%H:%M:%S} to {last:%Y-%m-%dT%H:%M:%S} there."
        )
    return step, into


def cut_graph(graph, bounds):
    """The part of *graph* SCOUT routes on: the subgraph of the nodes whose x
    and y lie inside *bounds*, ``(xmin, ymin, xmax, ymax)``, cut as SCOUT's
    ``DataLoader.load_graph`` cuts it, so its nodes keep SCOUT's order."""
    xmin, ymin, xmax, ymax = bounds
    nodes = ox.graph_to_gdfs(graph, nodes=True, edges=False)
    mask = (nodes["y"] <= ymax) & (nodes["y"] >= ymin) & (nodes["x"] <= xmax) & (nodes["x"] >= xmin)
    return graph.subgraph(nodes.loc[mask].index)


def _route(G, route, weight_type, route_index, weather_conditions):
    return {
        'route': route,
        'weight_type': weight_type,
        'route_index': route_index,
        "distance": nx.path_weight(G, route, weight='length') / 1000,  # in km
        "duration": nx.path_weight(G, route, weight='travel_time') / 60,  # in minutes
        "rain_exposure": nx.path_weight(G, route, weight='rain_weight') if 'rain' in weather_conditions else 0,
        "heat_exposure": nx.path_weight(G, route, weight='heat_weight') if 'heat' in weather_conditions else 0,
        "wind_exposure": nx.path_weight(G, route, weight='wind_weight') if 'wind' in weather_conditions else 0,
        "humidity_exposure": nx.path_weight(G, route, weight='humidity_weight') if 'humidity' in weather_conditions else 0,
    }


def plan_weather_route(graph, bounds, weather, model, origin_, destination_, mode="Default weights", K=1,
                       time_index=1, minutes_into_step=0, rain=None, heat=None, wind=None, humidity=None):
    """SCOUT's routing, from the graph's bounds to its routes.

    *graph* is the road graph and *bounds* its ``(xmin, ymin, xmax, ymax)``;
    *weather* maps RAIN, T2, WSPD10, WDIR10 and RH2 to their NetCDF files and
    *model* is the weather GNN (``curio_load_model("model.scout.weather-gnn")``,
    or anything whose ``run(feeds)`` returns its outputs). The trip starts in step
    *time_index* of the weather, *minutes_into_step* minutes in.

    Returns everything the routes come from: the graph SCOUT routes on, the
    origin and destination nodes, the trip's zones, the conditions and weights,
    the GNN's input and output, and SCOUT's list of routes.
    """
    if mode not in MODES:
        raise ValueError(f"There is no route mode {mode!r}: the modes are {', '.join(MODES)}.")
    xmin, ymin, xmax, ymax = (float(b) for b in bounds)

    weather_conditions = []
    weather_weights = []

    keyword_map = {
        'rain': rain,
        'heat': heat,
        'wind': wind,
        'humidity': humidity
    }

    for condition, weight in keyword_map.items():
        if weight is not None:
            weather_conditions.append(condition)
            weather_weights.append(weight)

    origin = (float(origin_['lat']), float(origin_['lon']))
    destination = (float(destination_['lat']), float(destination_['lon']))

    for what, (lat, lon) in (("origin", origin), ("destination", destination)):
        if not (ymin <= lat <= ymax and xmin <= lon <= xmax):
            raise ValueError(
                f"The {what} ({lat}, {lon}) is outside the roads, which cover latitude {ymin} to {ymax} "
                f"and longitude {xmin} to {xmax}."
            )

    time = int(time_index)

    # The graph SCOUT routes on
    G = cut_graph(graph, (xmin, ymin, xmax, ymax))

    with ExitStack() as files:
        # The weather, a NetCDF file per variable
        datasets = {name: files.enter_context(nc.Dataset(weather[name])) for name in WEATHER_VARIABLES}

        # Obtain valid origin and destination points
        orig_node = ox.distance.nearest_nodes(G, X=origin[1], Y=origin[0])
        dest_node = ox.distance.nearest_nodes(G, X=destination[1], Y=destination[0])

        # Calculate isochrones
        route = nx.shortest_path(G, orig_node, dest_node, weight="travel_time")
        trip_times_seconds = calculate_isochrones(G, orig_node, route)

        # In the optimized mode we always use the default weights
        if mode == "Default weights":
            rain_weight = 0.85834
            heat_weight = 0.02850
            humidity_weight = 0.09648
            wind_weight = 0.01657
        # In maps mode we are able to create a (for example) rain + heat aware path, so we need to check that the sum of weights is less than 1.0
        elif mode == "Custom weights":
            rain_weight = weather_weights[weather_conditions.index('rain')] if 'rain' in weather_conditions else 0
            heat_weight = weather_weights[weather_conditions.index('heat')] if 'heat' in weather_conditions else 0
            wind_weight = weather_weights[weather_conditions.index('wind')] if 'wind' in weather_conditions else 0
            humidity_weight = weather_weights[weather_conditions.index('humidity')] if 'humidity' in weather_conditions else 0
            if sum(weather_weights) > 1.0:
                raise ValueError("In 'Custom weights' mode, the weather weights must add up to at most 1.0.")
        # In variable mode we just assign the weights as per user input as long as they are between 0 and 1
        else:
            rain_weight = weather_weights[weather_conditions.index('rain')] if 'rain' in weather_conditions else 0
            heat_weight = weather_weights[weather_conditions.index('heat')] if 'heat' in weather_conditions else 0
            wind_weight = weather_weights[weather_conditions.index('wind')] if 'wind' in weather_conditions else 0
            humidity_weight = weather_weights[weather_conditions.index('humidity')] if 'humidity' in weather_conditions else 0

            if (rain_weight < 0 or rain_weight > 1 or
                heat_weight < 0 or heat_weight > 1 or
                wind_weight < 0 or wind_weight > 1 or
                humidity_weight < 0 or humidity_weight > 1):
                raise ValueError("In 'Single-factor weights' mode, each weather weight must be between 0 and 1.")

        gnn = GNN_weight_calculations(G,
                                      rain_ds=datasets["RAIN"],
                                      heat_ds=datasets["T2"],
                                      wind_speed_ds=datasets["WSPD10"],
                                      wind_dir_ds=datasets["WDIR10"],
                                      humidity_ds=datasets["RH2"],
                                      time=time,
                                      trip_time_seconds=trip_times_seconds,
                                      rain_weight=rain_weight,
                                      heat_weight=heat_weight,
                                      wind_weight=wind_weight,
                                      humidity_weight=humidity_weight,
                                      model=model,
                                      minutes_into_step=minutes_into_step)

    routes_data = []

    # Single map with single route!!
    if mode == "Default weights":
        route_fastest = nx.shortest_path(G, orig_node, dest_node, weight="travel_time")
        route_total = nx.shortest_path(G, orig_node, dest_node, weight="total_weight")
        routes_data.append(_route(G, route_fastest, "fastest-route", 0, weather_conditions))
        routes_data.append(_route(G, route_total, "weighted-route", 1, weather_conditions))

    elif mode == "Custom weights":

        # For future reference, the k_shortest_paths and shortest_paths are the ones that acually return a list of osm ID's
        for weight in weather_conditions:
            # Use Yen's algorithm for k-shortest paths
            k_paths = list(ox.routing.k_shortest_paths(G, orig_node, dest_node, k=(K), weight=f"{weight}_weight"))
            for i, route in enumerate(k_paths[:K]):
                routes_data.append(_route(G, route, "%s-aware-route" % weight, i, weather_conditions))

        route_fastest = nx.shortest_path(G, orig_node, dest_node, weight="travel_time")
        routes_data.append(_route(G, route_fastest, "fastest-route", 0, weather_conditions))

    # With this you are able to compare a only rain aware path, a only heat aware path and a heat + rain aware path
    elif mode == "Single-factor weights":

        i = 1
        for weight in weather_conditions:
            route = nx.shortest_path(G, orig_node, dest_node, weight=f"{weight}_weight")
            routes_data.append(_route(G, route, "%s-aware-route" % weight, i, weather_conditions))
            i += 1

        route_fastest = nx.shortest_path(G, orig_node, dest_node, weight="travel_time")
        routes_data.append(_route(G, route_fastest, "fastest-route", 0, weather_conditions))

    return {
        "graph": G, "orig_node": orig_node, "dest_node": dest_node,
        "trip_time_seconds": trip_times_seconds, "time_index": time,
        "weather_conditions": weather_conditions,
        "weights": {"rain_weight": rain_weight, "heat_weight": heat_weight,
                    "wind_weight": wind_weight, "humidity_weight": humidity_weight},
        "gnn": gnn, "routes": routes_data,
    }


def route_tables(plan):
    """``(routes, metrics)`` of a plan: one row per route in SCOUT's order.

    - routes: a GeoDataFrame in EPSG:4326, each route a line through its nodes,
      with the properties SCOUT gave its route GeoJSON, ``distance_m`` in metres.
    - metrics: the table SCOUT wrote per route, with which route it is.
    """
    G = plan["graph"]
    rows, lines, metrics = [], [], []
    for route in plan["routes"]:
        lines.append(LineString([(G.nodes[n]["x"], G.nodes[n]["y"]) for n in route["route"]]))
        rows.append({
            "weight_type": route["weight_type"],
            "route_index": route["route_index"],
            "distance_m": nx.path_weight(G, route["route"], weight="length"),
            "duration_minutes": float(route["duration"]),
            "rain_exposure": float(route["rain_exposure"]),
            "heat_exposure": float(route["heat_exposure"]),
            "wind_exposure": float(route["wind_exposure"]),
            "humidity_exposure": float(route["humidity_exposure"]),
        })
        metrics.append({"route": route["weight_type"], "route_index": route["route_index"],
                        **{m: float(route[m]) for m in METRICS}})
    routes = gpd.GeoDataFrame(rows, geometry=lines, crs="EPSG:4326")
    return routes, pd.DataFrame(metrics, columns=["route", "route_index", *METRICS])


def calculate_weather_route(roads, weather, model, origin_, destination_, mode="Default weights", K=1,
                            time_="2025-07-06T00:00:00", rain=None, heat=None, wind=None, humidity=None):
    """SCOUT's weather-aware routes over a roads layer: ``(routes, metrics)``.

    *roads* is a Curio roads layer (see road_graph.py); the routes run inside
    its bounds. *weather* maps RAIN, T2, WSPD10, WDIR10 and RH2 to their NetCDF
    files, *model* is the weather GNN (as ``plan_weather_route`` takes it), and *time_* is
    the start time, local time in the weather's time zone (its ``timezone``
    attribute, else UTC).
    """
    with nc.Dataset(weather["RAIN"]) as ds:
        start_date = ds.getncattr("START_DATE")
        time_zone = ds.getncattr("timezone") if "timezone" in ds.ncattrs() else "UTC"
        steps = len(ds.dimensions["Time"])
    time_index, minutes_into_step = weather_time_index(time_, start_date, time_zone, steps)
    G, bounds = road_graph(roads)
    plan = plan_weather_route(G, bounds, weather, model, origin_, destination_, mode=mode,
                              K=int(K), time_index=time_index, minutes_into_step=minutes_into_step,
                              rain=rain, heat=heat, wind=wind, humidity=humidity)
    return route_tables(plan)
