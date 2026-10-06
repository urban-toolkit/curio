import rasterio
from rasterio.windows import from_bounds
import geopandas as gpd
from shapely.geometry import mapping
from rasterio.mask import mask
import numpy as np
import pandas as pd
import os


def simulate_flood_projection(
    topleft,
    bottomright,
    output,
    year="2020 - 2040",
    use_NBS_classes=[
        "Bioswales/Infiltration trenches",
        "Permeable pavements",
        "Retention ponds",
        "Infiltration trench",
        "Bioswales",
        "Constructed wetlands",
    ],
):
    dict_use_NBS_classes = {
        21: "Bioswales/Infiltration trenches",
        31: "Permeable pavements",
        43: "Retention ponds",
        52: "Infiltration trench",
        71: "Bioswales",
        81: "Bioswales",
        90: "Constructed wetlands",
        95: "Constructed wetlands",
    }

    use_NBS_classes = set(use_NBS_classes)

    use_NBS_classes_ = {
        code for code, name in dict_use_NBS_classes.items()
        if name in use_NBS_classes
    }

    year_dict = {
        "2020 - 2040": "2020_2040",
        "2050 - 2080": "2050_2080",
        "2080 - 2100": "2080_2100",
    }

    year = year_dict.get(year)

    mask_path = "./models/flooding/data_substitutes/NBS_others_5m_4326_cropped_cleaned_resampled.tif"
    nbs_flood_path = f"./models/flooding/data_substitutes/{year}_NbS_4326_cropped.tif"
    nonbs_flood_path = f"./models/flooding/data_substitutes/{year}_noNbS_4326_cropped.tif"
    output_path = f"./data/served/raster/{output}.tif"

    # parse "lon, lat" strings
    top_left_lon, top_left_lat = map(float, topleft.split(","))
    bottom_right_lon, bottom_right_lat = map(float, bottomright.split(","))

    # build bounds for rasterio
    min_lon = top_left_lon
    max_lon = bottom_right_lon
    max_lat = top_left_lat
    min_lat = bottom_right_lat

    with rasterio.open(mask_path) as src_mask, \
         rasterio.open(nbs_flood_path) as src_nbs, \
         rasterio.open(nonbs_flood_path) as src_nonbs:

        assert src_mask.crs == src_nbs.crs == src_nonbs.crs
        assert src_mask.transform == src_nbs.transform == src_nonbs.transform

        window = from_bounds(
            min_lon,
            min_lat,
            max_lon,
            max_lat,
            transform=src_mask.transform,
        )

        mask_data_ = src_mask.read(1, window=window)
        nbs_data_ = src_nbs.read(1, window=window)
        nonbs_data_ = src_nonbs.read(1, window=window)

        out_transform = src_mask.window_transform(window)
        out_height, out_width = mask_data_.shape

        cond_use_NBS = np.isin(mask_data_, list(use_NBS_classes_))
        combined = np.where(cond_use_NBS, nbs_data_, nonbs_data_)

        flood_nodata = src_nbs.nodata
        if flood_nodata is not None:
            combined = np.where(combined == flood_nodata, np.nan, combined)

        profile = src_nbs.profile.copy()
        profile.update(
            dtype=combined.dtype,
            height=out_height,
            width=out_width,
            transform=out_transform,
            nodata=0.0,
        )

        metric_path = f"./data/served/metric/{output}.csv"

        median_val = np.nanmedian(combined)
        mean_val = np.nanmean(combined)
        max_val = np.nanmax(combined)
        min_val = np.nanmin(combined)
        stddev_val = np.nanstd(combined)

        os.makedirs(os.path.dirname(metric_path), exist_ok=True)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        df = pd.DataFrame([{
            "median flood depth": median_val,
            "mean flood depth": mean_val,
        }])

        df.to_csv(metric_path, index=False)

    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(combined, 1)

    print("Saved combined flood raster to:", output_path)