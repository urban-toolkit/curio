import geopandas as gpd

dataset_path = curio_data_path("data.utk.milan-census-gt65")
gdf = gpd.read_file(dataset_path)

return gdf
