import osmnx as ox
import networkx as nx
import netCDF4 as nc
import numpy as np
import matplotlib.pyplot as plt
from shapely.ops import unary_union

# -----------------------------
# Configuration
# -----------------------------
date = '20250706'
timezone = "t00z"

rain_path = rf'C:\Users\elchi\Desktop\UIC_Chicago\Knowledge_graph\Backend\try_clean\good_candidates\{date}\{timezone}\outputs\RAIN.nc'
graph_path = r'C:\Users\elchi\Desktop\UIC_Chicago\Knowledge_graph\Backend\Backtracking\chicago.graphml'

lat_min, lat_max = 41.61, 42.04
lon_min, lon_max = -88.03, -87.30

# 10-minute intervals -> corresponding weather time indices
time_slices = {600: 18, 1200: 19, 1800: 20, 2400: 21, 3000: 22}  # seconds -> forecast time index

# -----------------------------
# Load rainfall data
# -----------------------------
print("Loading rainfall data...")
ds = nc.Dataset(rain_path)
rain_frames = {t: ds.variables['RAIN'][t, :, :] for t in time_slices.values()}
lats = ds.variables['XLAT'][0, :, :]
lons = ds.variables['XLONG'][0, :, :]
print("Rainfall data loaded")

# -----------------------------
# Load street graph
# -----------------------------
print("Loading OSM graph...")
G = ox.load_graphml(graph_path)
G = ox.routing.add_edge_speeds(G)
G = ox.routing.add_edge_travel_times(G)
print("Graph loaded")

# -----------------------------
# Helper functions
# -----------------------------
def get_rain_at_point(lat, lon, rain_grid, lats, lons):
    i = np.argmin(np.abs(lats[:, 0] - lat))
    j = np.argmin(np.abs(lons[0, :] - lon))
    return rain_grid[i, j]

def apply_rain_penalty(G, rain_grid, lats, lons):
    """Apply rain penalty to all edges based on a rain grid"""
    for u, v, k, data in G.edges(keys=True, data=True):
        y1, x1 = G.nodes[u]['y'], G.nodes[u]['x']
        y2, x2 = G.nodes[v]['y'], G.nodes[v]['x']
        lat, lon = (y1 + y2) / 2, (x1 + x2) / 2

        rain_mm = get_rain_at_point(lat, lon, rain_grid, lats, lons)
        if np.isnan(rain_mm):
            rain_mm = 0.0

        penalty_factor = 1 + rain_mm * 100
        data["rain_length"] = data.get("travel_time", 1) * penalty_factor
    return G

# -----------------------------
# Origin/Destination
# -----------------------------
orig = ox.distance.nearest_nodes(G, Y=41.981486631170625, X=-87.85936593872668)
dest = ox.distance.nearest_nodes(G, Y=41.790567483995126, X=-87.58313070517129)

# -----------------------------
# Compute time-synced isochrones
# -----------------------------
iso_polys = []
nodes_gdf, edges_gdf = ox.graph_to_gdfs(G)

for max_time, weather_t in sorted(time_slices.items()):
    print(f"Computing isochrone ≤ {max_time/60:.0f} min using weather timestep {weather_t}")

    # Apply rain for this timestep
    G_temp = apply_rain_penalty(G.copy(), rain_frames[weather_t], lats, lons)

    # Compute travel times
    node_times = nx.single_source_dijkstra_path_length(G_temp, orig, weight="rain_length")
    nodes_gdf["travel_time"] = nodes_gdf.index.map(node_times)

    # Nodes reachable in this interval
    reachable = nodes_gdf.loc[nodes_gdf["travel_time"] <= max_time]
    if reachable.empty:
        continue

    # Filter edges within reachable nodes
    u_vals = edges_gdf.index.get_level_values(0)
    v_vals = edges_gdf.index.get_level_values(1)
    mask = u_vals.isin(reachable.index) & v_vals.isin(reachable.index)
    subedges = edges_gdf[mask]

    if not subedges.empty:
        merged = unary_union(subedges.geometry.buffer(0.001))
        if merged.geom_type == "MultiPolygon":
            for geom_part in merged.geoms:
                iso_polys.append((max_time, weather_t, geom_part))
        else:
            iso_polys.append((max_time, weather_t, merged))

print("Isochrones computed")

# -----------------------------
# Plot everything
# -----------------------------
fig, ax = plt.subplots(figsize=(10, 10))
colors = ["#ffb700", "#0099ff", "#ff00b3", "#00ff66", "#ff3300"]

for (trip_time, weather_t, poly), color in zip(iso_polys, colors):
    if poly.is_valid:
        # Fill isochrone
        ax.fill(*poly.exterior.xy, color=color, alpha=0.35,
                label=f"{trip_time/60:.0f} min (t={weather_t})")
        # Draw boundary
        ax.plot(*poly.exterior.xy, color=color, linewidth=2.2, linestyle="--", alpha=0.9)

        # Rain overlay clipped to polygon
        rain_grid = rain_frames.get(weather_t)
        if rain_grid is not None:
            # Mask points outside polygon
            rain_mask = np.full(rain_grid.shape, np.nan)
            for i in range(rain_grid.shape[0]):
                for j in range(rain_grid.shape[1]):
                    if poly.contains(ox.utils_geo.Point(lons[i,j], lats[i,j])):
                        rain_mask[i,j] = rain_grid[i,j]
            ax.pcolormesh(lons, lats, rain_mask, cmap="Blues", shading="auto", alpha=0.25)

# Plot graph and route
ox.plot_graph(G, ax=ax, node_size=0, edge_color="gray", edge_linewidth=1, show=False, close=False)
route_rain_aware = nx.shortest_path(G, orig, dest, weight="rain_length", method='bellman-ford')
ox.plot_graph_routes(G, [route_rain_aware], route_colors=["red"], route_linewidth=3, node_size=0, ax=ax, show=False, close=False)

plt.legend(loc="lower left")
plt.title("All Time-Synced Isochrones with Rain Overlay")
plt.xlabel("Longitude")
plt.ylabel("Latitude")
plt.grid(True, linestyle=":", linewidth=0.5)
plt.show()