import os
import netCDF4 as nc
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
import numpy as np

fp = r'C:\Users\elchi\Desktop\UIC_Chicago\Knowledge_graph\Backend\try_clean'

# Gather all RAIN.nc directories
rain_dirs = []
for root, dirs, files in os.walk(fp):
    if "RAIN.nc" in files:
        rain_dirs.append(root)

batch_size = 6  # number of graphs per screen

for batch_start in range(0, len(rain_dirs), batch_size):
    batch = rain_dirs[batch_start:batch_start+batch_size]
    n_files = len(batch)
    cols = batch_size // 2
    rows = int(np.ceil(n_files / cols))

    fig, axes = plt.subplots(rows, cols, figsize=(10, 5*rows))
    axes = axes.flatten() if isinstance(axes, np.ndarray) else [axes]

    # Store the first time step images
    images = []
    rain_data_list = []

    for i, dir in enumerate(batch):
        file_path = os.path.join(dir, "RAIN.nc")
        dataset = nc.Dataset(file_path)
        
        if 'RAIN' in dataset.variables:
            rain_data = dataset.variables['RAIN'][:]  # shape (time, lat, lon)
            rain_data_list.append(rain_data)
            im = axes[i].imshow(rain_data[0, :, :], origin='lower', cmap='viridis')
            axes[i].set_title(f"{os.path.basename(os.path.dirname(dir))}")
            fig.colorbar(im, ax=axes[i])
            images.append(im)
        else:
            axes[i].set_title(f"No RAIN in {os.path.basename(dir)}")
            rain_data_list.append(None)
            images.append(None)

    # Hide any unused subplot slots
    for j in range(i+1, len(axes)):
        axes[j].axis("off")

    # Animation update function
    def update(frame):
        for idx, data in enumerate(rain_data_list):
            if data is not None:
                images[idx].set_array(data[frame % data.shape[0], :, :])
                axes[idx].set_title(f"{os.path.basename(os.path.dirname(batch[idx]))} - Time {frame}")
        return images

    ani = FuncAnimation(fig, update, frames=max([d.shape[0] for d in rain_data_list if d is not None]),
                        interval=200, blit=False)

    plt.tight_layout()
    plt.show()
