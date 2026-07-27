import os
import netCDF4 as nc
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
import numpy as np

date = '20250711'
timezone = "t12z"  

# fp = rf'C:\Users\elchi\Desktop\UIC_Chicago\Knowledge_graph\Backend\try_clean\{date}\{timezone}\outputs'
# fp = rf'V:\Datos_CLEETS\Data_forecast\{date}\{timezone}\outputs'

# bounding box
lat_min, lat_max = 41.61, 42.04
lon_min, lon_max = -88.03, -87.48

# Gather all .nc files
nc_files = []
for root, dirs, files in os.walk(fp):
    for file in files:
        if file.endswith(".nc"):
            nc_files.append(os.path.join(root, file))
            
batch_size = 6  # number of graphs per batch

for batch_start in range(0, len(nc_files), batch_size):
    batch = nc_files[batch_start:batch_start+batch_size]
    n_files = len(batch)
    cols = 3
    rows = int(np.ceil(n_files / cols))

    fig, axes = plt.subplots(rows, cols, figsize=(5*cols, 4*rows))
    axes = axes.flatten() if isinstance(axes, np.ndarray) else [axes]

    images = []
    data_list = []
    titles = []
    
    name_map = {
        "HI": "Heat Index (F°)",
        "RAIN": "Daily total Precipitation (mm)",
        "RH2": "Relative Humidity at 2M (%)",
        "T2": "Temperature at 2M (K°)",
        "WDIR10": "Wind Direction at 10M (degrees)",
        "WSPD10": "Wind Speed at 10M (m/s)"
    }

    for i, file_path in enumerate(batch):
        dataset = nc.Dataset(file_path)
        var_name = os.path.basename(file_path)[:-3]  # remove ".nc"
        
        if var_name in dataset.variables:
            data = dataset.variables[var_name][:]  # (time, lat, lon)
            lats = dataset.variables["XLAT"][:]     # check your dataset: may be 'latitude'
            lons = dataset.variables["XLONG"][:]     # check your dataset: may be 'longitude'

            # find indices inside bounding box
            lat_inds = np.where((lats >= lat_min) & (lats <= lat_max))[0]
            lon_inds = np.where((lons >= lon_min) & (lons <= lon_max))[0]

            lat_slice = slice(lat_inds.min(), lat_inds.max()+1)
            lon_slice = slice(lon_inds.min(), lon_inds.max()+1)

            # subset
            data = data[:, lat_slice, lon_slice]
            sub_lats = lats[lat_slice]
            sub_lons = lons[lon_slice]

            data_list.append(data)

            im = axes[i].imshow(
                data[17, :, :],

                extent=[sub_lons.min(), sub_lons.max(), sub_lats.min(), sub_lats.max()],
                origin='lower',
                cmap='viridis'
            )
            axes[i].set_title(name_map.get(var_name, var_name))
            fig.colorbar(im, ax=axes[i])
            images.append(im)
            titles.append(name_map.get(var_name, var_name))
        else:
            print(f"Variable {var_name} not found in {file_path}")
            data_list.append(None)
            images.append(None)
            titles.append(name_map.get(var_name, var_name))

    # Hide unused subplots
    for j in range(i+1, len(axes)):
        axes[j].axis("off")
        
    plt.tight_layout()
    plt.show()
