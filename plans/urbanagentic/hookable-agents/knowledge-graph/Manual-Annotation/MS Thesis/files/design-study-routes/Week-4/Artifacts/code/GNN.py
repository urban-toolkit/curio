# rain_aware_routing_pyg.py
# Requires: osmnx, networkx, numpy, scipy, netCDF4, torch, torch_geometric, matplotlib
# pip install osmnx netCDF4 scipy torch torch_geometric matplotlib

import os
import numpy as np
import networkx as nx
import osmnx as ox
from scipy.interpolate import griddata
from netCDF4 import Dataset
import matplotlib.pyplot as plt

import torch
import torch.nn.functional as F
from torch_geometric.data import Data
from torch_geometric.nn import SAGEConv
from torch_geometric.loader import DataLoader

# -------------------------
# USER PATHS / SETTINGS
# -------------------------
graph_path = r'C:\Users\elchi\Desktop\UIC_Chicago\Knowledge_graph\Backend\Backtracking\chicago.graphml'

date = '20250706'
timezone = "t00z"
base_path = rf'C:\Users\elchi\Desktop\UIC_Chicago\Knowledge_graph\Backend\try_clean\good_candidates\{date}\{timezone}\outputs'

rain_path = rf'{base_path}\RAIN.nc'
wind_speed = rf'{base_path}\WSPD10.nc'
wind_direction = rf'{base_path}\WDIR10.nc'
heat_index = rf'{base_path}\T2.nc'
relative_humidity = rf'{base_path}\RH2.nc'

lat_min, lat_max = 41.61, 42.04
lon_min, lon_max = -88.03, -87.30
time_idx = 17  # your chosen timestep

# Hyperparams
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
hidden_dim = 64
lr = 1e-3
epochs = 200
rain_penalty_lambda = 100000.0  # how strongly route optimizer avoids rain

# -------------------------
# 1) Load the graph
# -------------------------
print("Loading graph...")
G = ox.load_graphml(graph_path)  # as you used
# Ensure graph is undirected/simpler for path routing
G = G.to_undirected()
print(f"Graph loaded: {len(G.nodes)} nodes, {len(G.edges)} edges")

# Extract node coordinates in the same order we'll use
node_ids = list(G.nodes)
coords = np.array([[G.nodes[n]['y'], G.nodes[n]['x']] for n in node_ids])  # lat, lon
# (note: OSMnx convention often uses y=lat, x=lon)

# -------------------------
# 2) Load NetCDF rasters & clip
# -------------------------
print("Loading NetCDF files...")
ds_rain = Dataset(rain_path)
rain_grid = ds_rain.variables['RAIN'][time_idx, :, :]
lats = ds_rain.variables['XLAT'][time_idx, :, :]
lons = ds_rain.variables['XLONG'][time_idx, :, :]

ds_hi = Dataset(heat_index)
hi_grid = ds_hi.variables['T2'][time_idx, :, :]
lats_h = ds_hi.variables['XLAT'][time_idx, :, :]
lons_h = ds_hi.variables['XLONG'][time_idx, :, :]

ds_rh = Dataset(relative_humidity)
rh_grid = ds_rh.variables['RH2'][time_idx, :, :]
lats_r = ds_rh.variables['XLAT'][time_idx, :, :]
lons_r = ds_rh.variables['XLONG'][time_idx, :, :]

ds_wspd = Dataset(wind_speed)
wspd_grid = ds_wspd.variables['WSPD10'][time_idx, :, :]
lats_w = ds_wspd.variables['XLAT'][time_idx, :, :]
lons_w = ds_wspd.variables['XLONG'][time_idx, :, :]

ds_wdir = Dataset(wind_direction)
wdir_grid = ds_wdir.variables['WDIR10'][time_idx, :, :]
# Convert to u/v
wdir_rad = np.deg2rad(wdir_grid)
u_grid = -wspd_grid * np.sin(wdir_rad)
v_grid = -wspd_grid * np.cos(wdir_rad)

# Clip / mask the grids (optional)
mask = (lats >= lat_min) & (lats <= lat_max) & (lons >= lon_min) & (lons <= lon_max)
# For interpolation purposes we'll just flatten the arrays and let griddata handle NaNs

# -------------------------
# 3) Interpolate grid -> node points
# -------------------------
print("Interpolating rasters to node locations...")

def interp_grid_to_points(grid_vals, lats_arr, lons_arr, points_latlon, method='linear'):
    # Flatten
    pts = np.vstack((lats_arr.flatten(), lons_arr.flatten())).T
    vals = grid_vals.flatten()
    # mask invalid
    mask_valid = ~np.isnan(vals)
    pts_valid = pts[mask_valid]
    vals_valid = vals[mask_valid]
    # Interpolate
    out = griddata(pts_valid, vals_valid, points_latlon, method=method, fill_value=np.nan)
    return out

points = coords  # lat, lon

rain_nodes = interp_grid_to_points(rain_grid, lats, lons, points)
hi_nodes = interp_grid_to_points(hi_grid, lats_h, lons_h, points)
rh_nodes = interp_grid_to_points(rh_grid, lats_r, lons_r, points)
u_nodes = interp_grid_to_points(u_grid, lats_w, lons_w, points)
v_nodes = interp_grid_to_points(v_grid, lats_w, lons_w, points)

# If any node had NaN (outside grid) fill with 0 or nearest valid value:
def fill_nan_with_nearest(arr):
    if np.all(np.isnan(arr)):
        return np.zeros_like(arr)
    idxs = np.where(~np.isnan(arr))[0]
    if len(idxs)==0:
        return np.nan_to_num(arr)
    # nearest fill: simple nearest neighbor via mask
    nan_idx = np.where(np.isnan(arr))[0]
    if len(nan_idx)==0:
        return arr
    # fallback: fill with median of valid
    median = np.nanmedian(arr)
    arr_filled = np.where(np.isnan(arr), median, arr)
    return arr_filled

rain_nodes = fill_nan_with_nearest(rain_nodes)
hi_nodes = fill_nan_with_nearest(hi_nodes)
rh_nodes = fill_nan_with_nearest(rh_nodes)
u_nodes = fill_nan_with_nearest(u_nodes)
v_nodes = fill_nan_with_nearest(v_nodes)

print("Interpolation done. Example node rain (first 10):", rain_nodes[:10])

# -------------------------
# 4) Build PyG Data object
# -------------------------
print("Building PyG Data object...")

# Map networkx graph to edge_index
# Maintain order: node_ids list
id_to_idx = {nid: i for i, nid in enumerate(node_ids)}
edges = []
for u_n, v_n, data in G.edges(data=True):
    edges.append([id_to_idx[u_n], id_to_idx[v_n]])
    # if undirected and both directions are present, duplicates may be present
edge_index = torch.tensor(edges, dtype=torch.long).t().contiguous()
if edge_index.numel() == 0:
    raise RuntimeError("Edge index is empty!")

# Node features matrix: lat, lon, hi, rh, u, v
x_np = np.column_stack([
    coords[:, 0],  # lat
    coords[:, 1],  # lon
    hi_nodes,
    rh_nodes,
    u_nodes,
    v_nodes,
])
x = torch.tensor(x_np, dtype=torch.float)

# Target: rain value
y = torch.tensor(rain_nodes, dtype=torch.float).unsqueeze(1)

data = Data(x=x, edge_index=edge_index, y=y)
print(data)

# Simple train/val split: random nodes (since we treat each node as sample)
num_nodes = data.num_nodes
perm = np.random.permutation(num_nodes)
train_n = int(0.8 * num_nodes)
train_idx = torch.tensor(perm[:train_n], dtype=torch.long)
val_idx = torch.tensor(perm[train_n:], dtype=torch.long)

# -------------------------
# 5) Define a small GNN for node regression (GraphSAGE)
# -------------------------
class NodeRegressor(torch.nn.Module):
    def __init__(self, in_channels, hidden_channels):
        super().__init__()
        self.conv1 = SAGEConv(in_channels, hidden_channels)
        self.conv2 = SAGEConv(hidden_channels, hidden_channels)
        self.lin = torch.nn.Linear(hidden_channels, 1)

    def forward(self, x, edge_index):
        x = self.conv1(x, edge_index)
        x = F.relu(x)
        x = self.conv2(x, edge_index)
        x = F.relu(x)
        out = self.lin(x)
        return out

model = NodeRegressor(data.num_node_features, hidden_dim).to(device)
optimizer = torch.optim.Adam(model.parameters(), lr=lr)
loss_fn = torch.nn.MSELoss()

# Move data to device (but Data uses tensors per graph)
data = data.to(device)

# -------------------------
# 6) Training loop
# -------------------------
print("Training...")
for epoch in range(1, epochs + 1):
    model.train()
    optimizer.zero_grad()
    out = model(data.x, data.edge_index)  # shape (N,1)
    loss = loss_fn(out[train_idx], data.y[train_idx])
    loss.backward()
    optimizer.step()

    if epoch % 20 == 0 or epoch==1:
        model.eval()
        with torch.no_grad():
            val_out = model(data.x, data.edge_index)
            val_loss = loss_fn(val_out[val_idx], data.y[val_idx])
        print(f"Epoch {epoch:04d} train_loss={loss.item():.6f} val_loss={val_loss.item():.6f}")

print("Training finished.")

model_path = r'C:\Users\elchi\Desktop\UIC_Chicago\Knowledge_graph\Backend\Backtracking\rain_gnn_model.pth'
torch.save({
    'model_state_dict': model.state_dict(),
    'optimizer_state_dict': optimizer.state_dict(),
    'epoch': epoch,
    'train_idx': train_idx,
    'val_idx': val_idx,
}, model_path)
print(f"Model saved to {model_path}")

# -------------------------
# 7) Predict per-node rain & attach to graph
# -------------------------
model.eval()
with torch.no_grad():
    preds = model(data.x, data.edge_index).cpu().numpy().squeeze()

# clip negatives
preds = np.clip(preds, a_min=0.0, a_max=None)

# attach to NetworkX nodes
for i, nid in enumerate(node_ids):
    G.nodes[nid]['pred_rain'] = float(preds[i])
    G.nodes[nid]['obs_rain'] = float(rain_nodes[i])  # observed

print("Predicted rain stats: min {:.4f}, max {:.4f}, mean {:.4f}".format(preds.min(), preds.max(), preds.mean()))

# -------------------------
# 8) Build rain-aware edge weights and shortest path
# -------------------------
print("Computing rain-aware shortest path...")
# Base edge length (meters) if available - OSMnx edges often have 'length' attribute
def edge_base_cost(u_n, v_n):
    # try to use edge data 'length' if present
    try:
        # for multigraph, G[u][v] may be a dict of keys
        data = G.get_edge_data(u_n, v_n)
        # if multigraph -> take first
        if isinstance(data, dict):
            k = list(data.keys())[0]
            d = data[k]
        else:
            d = data
        length = d.get('length', 1.0)
        return float(length)
    except Exception:
        return 1.0

# We'll set cost(u->v) = base_length + lambda * pred_rain_at_v (you can change to avg along edge)
edge_weights = {}
for u_n, v_n, key, edata in G.edges(keys=True, data=True):
    base = edge_base_cost(u_n, v_n)
    rain_v = G.nodes[v_n].get('pred_rain', 0.0)
    cost = base + rain_penalty_lambda * rain_v
    # store weight in graph (as 'weight')
    if isinstance(G, nx.MultiGraph) or isinstance(G, nx.MultiDiGraph):
        # assign to the specific key
        G[u_n][v_n][key]['weight'] = cost
    else:
        G[u_n][v_n]['weight'] = cost

# choose start/end by coordinates (or pick two node ids)
def nearest_node_to_point(lat, lon):
    # uses coords array and node_ids
    pts = coords  # lat lon
    dists = (pts[:,0]-lat)**2 + (pts[:,1]-lon)**2
    return node_ids[int(np.argmin(dists))]

# Example: pick two arbitrary coordinates in bounding box; replace with real start/end
start_latlon = (41.981486631170625, -87.85936593872668)   # near downtown chicago
end_latlon = (41.790567483995126, -87.58313070517129)     # another place
start_node = nearest_node_to_point(*start_latlon)
end_node = nearest_node_to_point(*end_latlon)

print(f"Start node: {start_node}  End node: {end_node}")

# Compute shortest path using 'weight'
try:
    path = nx.shortest_path(G, source=start_node, target=end_node, weight='weight')
    path_length = nx.shortest_path_length(G, source=start_node, target=end_node, weight='weight')
    print(f"Found path of cost {path_length:.3f} with {len(path)} nodes.")
except nx.NetworkXNoPath:
    print("No path found between nodes with current graph/weights.")
    path = None

# -------------------------
# 9) Plot route on map with predicted rain color
# -------------------------
print("Plotting results...")
fig, ax = ox.plot_graph(G, node_size=0, show=False, close=False)

# overlay nodes colored by predicted rain
node_x = [G.nodes[n]['x'] for n in node_ids]
node_y = [G.nodes[n]['y'] for n in node_ids]
sc = ax.scatter(node_x, node_y, c=preds, cmap='Blues', s=8, alpha=0.8, zorder=3)
plt.colorbar(sc, ax=ax, label='Predicted rain')

if path is not None:
    # plot the path as red line
    path_coords = [(G.nodes[n]['x'], G.nodes[n]['y']) for n in path]  # lon, lat
    xs = [p[0] for p in path_coords]
    ys = [p[1] for p in path_coords]
    ax.plot(xs, ys, linewidth=3, color='red', zorder=4, label='rain-avoiding route')
    ax.scatter([xs[0], xs[-1]], [ys[0], ys[-1]], c=['green', 'black'], s=40, zorder=5)
    ax.legend()

plt.title("Predicted rain (nodes) and rain-aware route")
plt.show()

# -------------------------
# 10) Save predicted node rain to disk (optional)
# -------------------------
out_csv = "predicted_node_rain.csv"
with open(out_csv, "w") as f:
    f.write("node_id,lat,lon,obs_rain,pred_rain\n")
    for i, nid in enumerate(node_ids):
        f.write(f"{nid},{coords[i,0]},{coords[i,1]},{G.nodes[nid]['obs_rain']},{G.nodes[nid]['pred_rain']}\n")
print(f"Saved predictions to {out_csv}")
