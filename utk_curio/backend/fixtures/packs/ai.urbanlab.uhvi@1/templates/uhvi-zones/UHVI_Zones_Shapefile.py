import geopandas as gpd

# Load a polygon GeoDataFrame to use as the zonal-aggregation footprint
# downstream. The default points at the Milan socio-demographics layer
# bundled with the spike fixtures; swap it for any polygon dataset whose
# units you want UHVI summarised against.
path = [!! path$INPUT_TEXT$./milan/R03_21-11_WGS84_P_SocioDemographics_MILANO_Selected.shp !!]
gdf = gpd.read_file(path)

# Tag the layer so downstream visualisers (grammar nodes) can label it.
gdf.metadata = {"name": "uhvi_zones"}
return gdf
