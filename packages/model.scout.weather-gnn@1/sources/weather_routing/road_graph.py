"""The road graph SCOUT's routing runs on, built from a Curio roads layer.

SCOUT routes on a networkx MultiDiGraph whose nodes carry ``x`` and ``y``
(longitude and latitude) and whose edges carry ``length`` (metres),
``speed_kph`` and ``travel_time`` (seconds): the graph osmnx builds from
OpenStreetMap. SCOUT ships its Chicago graph pickled; in Curio the roads are a
layer, a GeoDataFrame of lines, one per OpenStreetMap way: the roads an Autark
node loads (an OpenStreetMap extract), or a roads layer from the Discovery or
Data Catalog. Here:

- each pair of consecutive points of a line is an edge, both ways, or one way
  where ``oneway`` says so (``yes``, ``true`` or ``1`` along the line, ``-1`` or
  ``reverse`` against it); a point shared by two lines is one node;
- ``length`` is the great-circle distance between the two points, and osmnx
  gives ``speed_kph`` from ``highway`` and ``maxspeed`` (``add_edge_speeds``) and
  ``travel_time`` from both (``add_edge_travel_times``);
- the graph keeps its largest strongly connected part, as osmnx keeps the
  largest part of a graph it builds, so every origin and destination it snaps
  to can reach each other: an extract cut at its edge leaves one-way ends and
  pieces no route can leave.

A layer is read in the CRS it declares. One that declares none is read as an
Autark map reads it: EPSG:4326 when its coordinates look like longitude and
latitude, else EPSG:3395, the CRS Autark keeps its layers in.
"""

import networkx as nx
import osmnx as ox

#: ``oneway`` values that keep a line to the direction it is drawn in, and to the other.
ONEWAY_ALONG = frozenset({"yes", "true", "1"})
ONEWAY_AGAINST = frozenset({"-1", "reverse"})
#: The speed, in km/h, osmnx gives every edge when no road in the layer has a
#: ``maxspeed``: 30 mph, the speed limit of an Illinois urban district.
FALLBACK_SPEED_KPH = 48.28
#: The road type of a line that names none.
DEFAULT_HIGHWAY = "unclassified"
#: The CRS Autark keeps its layers in (World Mercator, metres).
AUTARK_CRS = "EPSG:3395"


def _lines(geometry):
    """The point lists of a LineString or a MultiLineString."""
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "LineString":
        return [list(geometry.coords)]
    if geometry.geom_type == "MultiLineString":
        return [list(part.coords) for part in geometry.geoms]
    raise ValueError(f"A road must be a line, not a {geometry.geom_type}.")


def _value(row, column):
    value = row.get(column)
    try:
        missing = value is None or value != value  # None or NaN
    except (TypeError, ValueError):
        missing = False
    return None if missing else value


def in_longitude_latitude(roads):
    """*roads* in EPSG:4326, read in the CRS it declares, else as Autark reads a frame."""
    if roads.crs is None:
        xmin, ymin, xmax, ymax = roads.total_bounds
        lonlat = -180 <= xmin <= xmax <= 180 and -90 <= ymin <= ymax <= 90
        roads = roads.set_crs("EPSG:4326" if lonlat else AUTARK_CRS)
    return roads if roads.crs.to_epsg() == 4326 else roads.to_crs(4326)


def road_graph(roads):
    """``(graph, bounds)``: the road graph of *roads*, a GeoDataFrame of road
    lines, and the roads' ``(xmin, ymin, xmax, ymax)`` in longitude and latitude."""
    if roads is None or len(roads) == 0:
        raise ValueError("The roads layer is empty: Weather Routing needs the roads to route on.")
    roads = in_longitude_latitude(roads)
    G = nx.MultiDiGraph(crs="EPSG:4326")
    ids = {}

    def node(point):
        if point not in ids:
            ids[point] = len(ids)
            G.add_node(ids[point], x=float(point[0]), y=float(point[1]))
        return ids[point]

    for row in roads.to_dict("records"):
        oneway = str(_value(row, "oneway") or "").strip().lower()
        tags = {"highway": str(_value(row, "highway") or DEFAULT_HIGHWAY)}
        if _value(row, "maxspeed") is not None:
            tags["maxspeed"] = str(_value(row, "maxspeed"))
        for line in _lines(row[roads.geometry.name]):
            for a, b in zip(line, line[1:]):
                if a == b:
                    continue
                u, v = node(a), node(b)
                length = float(ox.distance.great_circle(a[1], a[0], b[1], b[0]))
                if oneway not in ONEWAY_AGAINST:
                    G.add_edge(u, v, length=length, **tags)
                if oneway not in ONEWAY_ALONG:
                    G.add_edge(v, u, length=length, **tags)
    if G.number_of_edges() == 0:
        raise ValueError("The roads layer has no line with two points: Weather Routing needs roads to route on.")
    G = ox.truncate.largest_component(G, strongly=True)
    try:
        ox.add_edge_speeds(G)
    except ValueError:  # no road in the layer has a maxspeed
        ox.add_edge_speeds(G, fallback=FALLBACK_SPEED_KPH)
    ox.add_edge_travel_times(G)
    return G, tuple(float(b) for b in roads.total_bounds)
