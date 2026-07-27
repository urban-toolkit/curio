import networkx as nx
import osmnx as ox
import netCDF4 as nc
import matplotlib.pyplot as plt
import numpy as np

# -----------------------------
# Load rainfall data
# -----------------------------
date = '20250706'
timezone = "t00z"
base_path = rf'C:\Users\elchi\Desktop\UIC_Chicago\Knowledge_graph\Backend\try_clean\good_candidates\{date}\{timezone}\outputs'

weather_data = rf'{base_path}\RAIN.nc'
wind_speed = rf'{base_path}\WSPD10.nc'
wind_direction = rf'{base_path}\WDIR10.nc'

lat_min, lat_max = 41.61, 42.04
lon_min, lon_max = -88.03, -87.30
time = 18

ds = nc.Dataset(weather_data)
rain = ds.variables['RAIN'][time, :, :]  # timestep
lats = ds.variables['XLAT'][time, :, :]
lons = ds.variables['XLONG'][time, :, :]

# Clip by bounding box
mask = (lats >= lat_min) & (lats <= lat_max) & (lons >= lon_min) & (lons <= lon_max)
rain_masked = np.where(mask, rain, np.nan)
print("Loaded rainfall data")

# -----------------------------
# Load wind data
# -----------------------------
ds_wspd = nc.Dataset(wind_speed)      # wind speed file
ds_wdir = nc.Dataset(wind_direction)  # wind direction file

# Read same timestep
wspd = ds_wspd.variables['WSPD10'][time, :, :]
wdir = ds_wdir.variables['WDIR10'][time, :, :]

lats_w = ds_wspd.variables['XLAT'][time, :, :]
lons_w = ds_wspd.variables['XLONG'][time, :, :]

# Mask to bounding box
mask_wind = (lats_w >= lat_min) & (lats_w <= lat_max) & (lons_w >= lon_min) & (lons_w <= lon_max)
wspd_masked = np.where(mask_wind, wspd, np.nan)
wdir_masked = np.where(mask_wind, wdir, np.nan)

# Convert direction (degrees from) to u/v components
wdir_rad = np.deg2rad(wdir_masked)
u = -wspd_masked * np.sin(wdir_rad)  # east-west
v = -wspd_masked * np.cos(wdir_rad)  # north-south

# Downsample for clarity (~1 arrow per 3 km)
step = 3
lats_sub = lats_w[::step, ::step]
lons_sub = lons_w[::step, ::step]
u_sub = u[::step, ::step]
v_sub = v[::step, ::step]

print("Loaded wind data")

# -----------------------------
# Load street graph
# -----------------------------
G = ox.load_graphml(r'C:\Users\elchi\Desktop\UIC_Chicago\Knowledge_graph\Backend\Backtracking\chicago.graphml')
print("Loaded graph")

# Add speeds/travel times
G = ox.routing.add_edge_speeds(G)
G = ox.routing.add_edge_travel_times(G)

# -----------------------------
# Pick origin/destination
# -----------------------------
orig = ox.distance.nearest_nodes(G, Y=41.981486631170625, X=-87.85936593872668)
dest = ox.distance.nearest_nodes(G, Y=41.790567483995126, X=-87.58313070517129)


# -----------------
# Calculate time zones

# https://github.com/gboeing/osmnx-examples/blob/v0.13.0/notebooks/13-isolines-isochrones.ipynb

trip_times = [10, 20, 30, 40, 50] #in minutes

nodes_gdf, edges_gdf = ox.graph_to_gdfs(G)

node_times = nx.single_source_dijkstra_path_length(G, orig, weight="travel_time")

nodes_gdf["travel_time"] = nodes_gdf.index.map(node_times)



# -----------------------------
# Function to get rain at a point
# -----------------------------
def get_rain_at_point(lat, lon, rain_grid, lats, lons):
    i = np.argmin(np.abs(lats[:, 0] - lat))
    j = np.argmin(np.abs(lons[0, :] - lon))
    return rain_grid[i, j]

# -----------------------------
# Precompute rain-aware edge weights
# -----------------------------
for u, v, k, data in G.edges(keys=True, data=True):
    y1, x1 = G.nodes[u]['y'], G.nodes[u]['x']
    y2, x2 = G.nodes[v]['y'], G.nodes[v]['x']
    lat, lon = (y1 + y2) / 2, (x1 + x2) / 2

    rain_mm = get_rain_at_point(lat, lon, rain, lats, lons)
    penalty_factor = 1 + rain_mm * 1000  # simple scaling
    data["rain_length"] = data.get("travel_time", 1) * penalty_factor

print("Applied rain-aware penalties")


# -----------------------------
# Calculate rain-aware route
# -----------------------------
route_rain_aware = nx.shortest_path(G, orig, dest, weight="rain_length", method='bellman-ford')
fastest_route = nx.shortest_path(G, orig, dest, weight="travel_time")
# -----------------------------
# Plot everything
# -----------------------------
fig, ax = plt.subplots(figsize=(10, 10))

# Rainfall background
c = ax.pcolormesh(lons, lats, rain_masked, cmap="Blues", shading="auto", alpha=0.4)
fig.colorbar(c, ax=ax, label="Rainfall (mm)")
c.set_clim(0, 10.5)

# Wind vectors (quiver)
q = ax.quiver(
    lons_sub, lats_sub, u_sub, v_sub,
    scale=400, width=0.002, color="black", alpha=0.7
)
ax.quiverkey(q, 0.9, 1.05, 10, "10 m/s", labelpos='E')

# Streets
ox.plot_graph(G, ax=ax, node_size=0, edge_color='gray', edge_linewidth=1, show=False, close=False)

# Route
ox.plot_graph_routes(
    G,
    routes=[route_rain_aware, fastest_route],
    route_colors=["red", "blue"],
    route_linewidth=3,
    node_size=0,
    ax=ax,
    show=False,
    close=False
)

plt.title("Rain-Aware Route at query time with Wind Field Overlay")
plt.xlabel("Longitude")
plt.ylabel("Latitude")
plt.show()

# -----------------------------
# Route statistics
# -----------------------------
route_gdf = ox.routing.route_to_gdf(G, route_rain_aware)
route_length = int(route_gdf["length"].sum())
route_time = int(route_gdf["travel_time"].sum())
rain_length = int(route_gdf["rain_length"].sum())

print(f"Rain-aware route is {route_length} meters, takes {route_time} seconds, and accounts for {rain_length} meters of rain.")
