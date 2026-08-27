import rasterio

dataset_path = curio_dataset_path("data.urbanlab.milan-mrt")
src = rasterio.open(dataset_path)

return src
