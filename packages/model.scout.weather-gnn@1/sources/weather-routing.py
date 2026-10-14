from weather_routing import calculate_weather_route

# The Data Catalog's SCOUT WRF group, a NetCDF file per variable.
weather = {
    "RAIN": curio_data_path("data.scout.wrf-rain"),
    "T2": curio_data_path("data.scout.wrf-t2"),
    "WSPD10": curio_data_path("data.scout.wrf-wspd10"),
    "WDIR10": curio_data_path("data.scout.wrf-wdir10"),
    "RH2": curio_data_path("data.scout.wrf-rh2"),
}
model = curio_load_model("model.scout.weather-gnn")
return calculate_weather_route(
    [!! input_0:table_osm_roads !!],
    weather,
    model,
    [!! origin !!],
    [!! destination !!],
    mode=[!! mode !!],
    K=int([!! K !!]),
    time_=[!! time !!],
    rain=[!! rain !!],
    wind=[!! wind !!],
)
