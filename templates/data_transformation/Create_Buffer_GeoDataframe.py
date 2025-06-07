import pandas as pd
import geopandas as gpd

gdf_points = arg # Getting GeoDataFrame from previous node

gdf_points = gdf_points.to_crs(3857) # Transforming to a a coordinate system that operates in meters

gdf_points["geometry"] = gdf_points["geometry"].buffer(25)

gdf_points = gdf_points.to_crs(4326) # Transforming back to Latitude and Longitude

return gdf_points