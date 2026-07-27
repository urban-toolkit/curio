import osmnx as ox
import networkx as nx
import netCDF4 as nc
import numpy as np
import matplotlib.pyplot as plt
from shapely import MultiPolygon, Polygon
from shapely.ops import unary_union
import geopandas as gpd
from shapely.geometry import Point
from descartes import PolygonPatch

# -----------------------------
# Configuration
# -----------------------------
date = '20250706'
timezone = "t00z"
base_path = rf'C:\Users\elchi\Desktop\UIC_Chicago\Knowledge_graph\Backend\try_clean\good_candidates\{date}\{timezone}\outputs'

rain_path = rf'{base_path}\RAIN.nc'
wind_speed = rf'{base_path}\WSPD10.nc'
wind_direction = rf'{base_path}\WDIR10.nc'

lat_min, lat_max = 41.61, 42.04
lon_min, lon_max = -88.03, -87.30
time = 18

ds = nc.Dataset(rain_path)
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

trip_times = [10, 20, 30, 40, 50] #in minutes
# travel_speed = 73.5 #walking speed in km/hour

graph_path = r'C:\Users\elchi\Desktop\UIC_Chicago\Knowledge_graph\Backend\Backtracking\chicago.graphml'


G = ox.load_graphml(graph_path)
G = ox.routing.add_edge_speeds(G)
G = ox.routing.add_edge_travel_times(G)

orig = ox.distance.nearest_nodes(G, Y=41.981486631170625, X=-87.85936593872668)
dest = ox.distance.nearest_nodes(G, Y=41.790567483995126, X=-87.58313070517129)


#--------------------
# Create isochrones zones
#--------------------

# meters_per_minute = travel_speed * 1000 / 60 #km per hour to m per minute
for u, v, k, data in G.edges(data=True, keys=True):
    
    # Add a tag for zone
    data['zone'] = 0
    
    
    # Convert everything to kmh
    if 'maxspeed' in data:
        
        
        # Speed is saved as "00 mph", we'll just take the first part and convert to kph
        # Also data is saved as a list sometimes, so we handle that too
        if isinstance(data['maxspeed'], list):
            data['maxspeed'] = data['maxspeed'][0]
        # print(data['maxspeed'])   
        if isinstance(data['maxspeed'], (int, float)):
            data['speed_kph'] = float(data['maxspeed']) * 1.60934
        else:
            text = data['maxspeed']
            # Convert to string and split by spaces, take first part
            first_part = str(text).split()[0]
            if first_part.isdigit():
                speed_value = first_part
            else: 
                speed_value = text[:-4].strip()
            data['speed_kph'] = float(speed_value) * 1.60934

    data['time'] = data['length'] / (data['speed_kph'] * 1000 / 3600) #in seconds

trip_times_seconds = [t * 60 for t in trip_times]


# Calculate zones and assign tags to edges
for zone_num, trip_time in enumerate(sorted(trip_times_seconds), start=1):
    subgraph = nx.ego_graph(G, orig, radius=trip_time, distance='time')
    
    # Tag all edges in this subgraph with the current zone
    for u, v, k in subgraph.edges(keys=True):
        if G.has_edge(u, v, k):  # Make sure edge exists in original graph
            G[u][v][k]['zone'] = zone_num

# print("Sample edge zones:")
# for i, (u, v, k, data) in enumerate(G.edges(data=True, keys=True)):
#     if i < 10:  # Print first 10 edges as example
#         print(f"Edge {u}-{v} (key {k}): Zone {data['zone']}")
#     else:
#         break


# -----------------------------
# Function to get rain at a point
# -----------------------------
def get_rain_at_point(lat, lon, rain_grid, lats, lons):
    i = np.argmin(np.abs(lats[:, 0] - lat))
    j = np.argmin(np.abs(lons[0, :] - lon))
    return rain_grid[i, j]

# -----------------------------
# Precompute rain-aware edge weights at different zones
# -----------------------------
isochrone_polys = []
for u, v, k, data in G.edges(keys=True, data=True):
    y1, x1 = G.nodes[u]['y'], G.nodes[u]['x']
    y2, x2 = G.nodes[v]['y'], G.nodes[v]['x']
    lat, lon = (y1 + y2) / 2, (x1 + x2) / 2

    rain = ds.variables['RAIN'][time+data['zone']-1, :, :]  # timestep
    
    rain_mm = get_rain_at_point(lat, lon, rain, lats, lons)
    penalty_factor = 1 + rain_mm / 10  # simple scaling
    data["rain_length"] = data.get("travel_time", 1) * penalty_factor

print("Applied rain-aware penalties")

route_rain_aware = nx.shortest_path(G, orig, dest, weight="rain_length", method='bellman-ford')
fastest_route = nx.shortest_path(G, orig, dest, weight="travel_time")
# get one color for each isochrone
iso_colors = ox.plot.get_colors(n=len(trip_times_seconds), cmap='plasma', start=0)
iso_colors = [mcolors.to_hex(c) for c in iso_colors]

# color the nodes according to isochrone then plot the street network
node_colors = {}
for trip_time, color in zip(sorted(trip_times_seconds, reverse=True), iso_colors):
    subgraph = nx.ego_graph(G, orig, radius=trip_time, distance='time')
    for node in subgraph.nodes():
        node_colors[node] = color

nc = [node_colors[node] if node in node_colors else 'none' for node in G.nodes()]
ns = [15 if node in node_colors else 0 for node in G.nodes()]
fig, ax = ox.plot_graph(G, node_color=nc, node_size=ns, node_alpha=0.8, node_zorder=2,
                        bgcolor='k', edge_linewidth=0.2, edge_color='#999999')

# make the isochrone polygons
isochrone_polys = []
for trip_time in sorted(trip_times_seconds, reverse=True):
    subgraph = nx.ego_graph(G, orig, radius=trip_time, distance='time')
    node_points = [Point((data['x'], data['y'])) for node, data in subgraph.nodes(data=True)]
    bounding_poly = gpd.GeoSeries(node_points).unary_union.convex_hull
    isochrone_polys.append(bounding_poly)

# plot the network then add isochrones as colored descartes polygon patches
fig, ax = ox.plot_graph(G, show=False, close=False, edge_color='#999999', edge_alpha=0.2,
                        node_size=0, bgcolor='k')

# ADD RAINFALL BACKGROUND HERE
c = ax.pcolormesh(lons, lats, rain_masked, cmap="Blues", shading="auto", alpha=0.4)
fig.colorbar(c, ax=ax, label="Rainfall (mm)")
c.set_clim(0, 10.5)

# Add the isochrone polygons on top of the rainfall
for polygon, fc in zip(isochrone_polys, iso_colors):
    patch = PolygonPatch(polygon, fc=fc, ec='none', alpha=0.6, zorder=-1)
    ax.add_patch(patch)

plt.show()
"""

# Expansive plotting

# Calculate how many plots we need (number of zones + current time)
n_plots = len(trip_times) + 1  # +1 for current conditions
cols = 3
rows = (n_plots + cols - 1) // cols  # Ceiling division

fig, axes = plt.subplots(rows, cols, figsize=(15, 5*rows))
axes = axes.flatten() if rows > 1 else [axes] if cols == 1 else axes

# Plot 1: Current conditions (time 18)
ax = axes[0]
rain_current = ds.variables['RAIN'][time, :, :]
rain_current_masked = np.where(mask, rain_current, np.nan)

# Rainfall background
c = ax.pcolormesh(lons, lats, rain_current_masked, cmap="Blues", shading="auto", alpha=0.6)
fig.colorbar(c, ax=ax, label="Rainfall (mm)")
c.set_clim(0, 10.5)

# Wind vectors
q = ax.quiver(lons_sub, lats_sub, u_sub, v_sub, scale=400, width=0.002, color="black", alpha=0.7)

# Streets and route
ox.plot_graph(G, ax=ax, node_size=0, edge_color='gray', edge_linewidth=0.5, show=False, close=False)
ox.plot_graph_routes(G, routes=[route_rain_aware], route_colors=["red"], route_linewidth=3, node_size=0, ax=ax, show=False, close=False)

ax.set_title(f"Current Conditions (Time {time})")
ax.set_xlabel("Longitude")
ax.set_ylabel("Latitude")

# Plot for each zone
for zone_num in range(1, len(trip_times) + 1):
    ax = axes[zone_num]
    
    # Get rain data for this zone's future time
    future_time = time + zone_num
    max_time = ds.variables['RAIN'].shape[0] - 1
    if future_time > max_time:
        future_time = max_time
    
    rain_zone = ds.variables['RAIN'][future_time, :, :]
    rain_zone_masked = np.where(mask, rain_zone, np.nan)
    
    # Rainfall background
    c = ax.pcolormesh(lons, lats, rain_zone_masked, cmap="Blues", shading="auto", alpha=0.6)
    fig.colorbar(c, ax=ax, label="Rainfall (mm)")
    c.set_clim(0, 10.5)
    
    # Wind vectors (using same wind data for simplicity)
    q = ax.quiver(lons_sub, lats_sub, u_sub, v_sub, scale=400, width=0.002, color="black", alpha=0.7)
    
    # Streets
    ox.plot_graph(G, ax=ax, node_size=0, edge_color='gray', edge_linewidth=0.5, show=False, close=False)
    
    # Highlight the zone - FIXED VERSION
    subgraph = nx.ego_graph(G, orig, radius=trip_times_seconds[zone_num-1], distance='time')
    
    # Get edges with keys for MultiGraph
    zone_edge_list = [(u, v, k) for u, v, k in subgraph.edges(keys=True)]
    if zone_edge_list:
        zone_subgraph = G.edge_subgraph(zone_edge_list)
        ox.plot_graph(zone_subgraph, ax=ax, node_size=0, 
                     edge_color='orange', edge_linewidth=1.5, show=False, close=False)
    
    # Route
    ox.plot_graph_routes(G, routes=[route_rain_aware], route_colors=["red"], 
                        route_linewidth=3, node_size=0, ax=ax, show=False, close=False)
    
    # Origin point
    orig_y, orig_x = G.nodes[orig]['y'], G.nodes[orig]['x']
    ax.plot(orig_x, orig_y, 'ro', markersize=8, label='Origin')
    
    time_range = f"0-{trip_times[zone_num-1]}" if zone_num == 1 else f"{trip_times[zone_num-2]}-{trip_times[zone_num-1]}"
    ax.set_title(f"Zone {zone_num}: {time_range} min\n(Rain at Time {future_time})")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")

# Hide any unused subplots
for i in range(n_plots, len(axes)):
    axes[i].set_visible(False)

plt.tight_layout()
plt.show()
"""

"""

# get one color for each isochrone
iso_colors = ox.plot.get_colors(n=len(trip_times_seconds), cmap='plasma', start=0)

# color the nodes according to isochrone then plot the street network
node_colors = {}
for trip_time, color in zip(sorted(trip_times_seconds, reverse=True), iso_colors):
    subgraph = nx.ego_graph(G, orig, radius=trip_time, distance='time')
    for node in subgraph.nodes():
        node_colors[node] = color
nc = [node_colors[node] if node in node_colors else 'none' for node in G.nodes()]
ns = [15 if node in node_colors else 0 for node in G.nodes()]
fig, ax = ox.plot_graph(G, node_color=nc, node_size=ns, node_alpha=0.8, node_zorder=2,
                        bgcolor='k', edge_linewidth=0.2, edge_color='#999999')

# make the isochrone polygons
isochrone_polys = []
for trip_time in sorted(trip_times_seconds, reverse=True):
    subgraph = nx.ego_graph(G, orig, radius=trip_time, distance='time')
    node_points = [Point((data['x'], data['y'])) for node, data in subgraph.nodes(data=True)]
    bounding_poly = gpd.GeoSeries(node_points).unary_union.convex_hull
    isochrone_polys.append(bounding_poly)

fig, ax = ox.plot_graph(G, show=False, close=False, edge_color='#999999', edge_alpha=0.2,
                        node_size=0, bgcolor='k')
for polygon, fc in zip(isochrone_polys, iso_colors):
    patch = PolygonPatch(polygon, fc=fc, ec='none', alpha=0.6, zorder=-1)
    ax.add_patch(patch)
plt.show()
"""