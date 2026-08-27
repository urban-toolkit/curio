import geopandas as gpd

dataset_path = curio_dataset_path("data.urbanlab.milan-census-gt65")
gdf = gpd.read_file(dataset_path)

return gdf
